"""基于标准观测值的八季度财务量化，不访问网络或数据库。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class FinancialQuantResult:
    status: str
    fundamental_state: str
    quarters_available: int
    data_coverage: float
    earnings_momentum_score: float | None
    business_quality_score: float | None
    component_scores: dict[str, dict[str, float]]
    metrics: dict[str, Any]
    missing_metrics: tuple[str, ...]

    def to_record(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "fundamental_state": self.fundamental_state,
            "quarters_available": self.quarters_available,
            "data_coverage": self.data_coverage,
            "scores": {
                "earnings_momentum": self.earnings_momentum_score,
                "business_quality": self.business_quality_score,
            },
            "component_scores": {
                group: dict(values) for group, values in self.component_scores.items()
            },
            "metrics": dict(self.metrics),
            "missing_metrics": list(self.missing_metrics),
        }


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _rising(value: float | None, low: float, high: float) -> float | None:
    if value is None or high <= low:
        return None
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _falling(value: float | None, full: float, zero: float) -> float | None:
    rising = _rising(value, full, zero)
    return None if rising is None else 1.0 - rising


def _trend(values: list[float]) -> float | None:
    recent = values[-4:]
    if len(recent) < 2:
        return None
    return (recent[-1] - recent[0]) / (len(recent) - 1)


def _relative_trend(values: list[float]) -> float | None:
    recent = values[-4:]
    if len(recent) < 2 or abs(recent[0]) < 1e-12:
        return None
    return (recent[-1] - recent[0]) / abs(recent[0])


def _weighted_score(
    components: dict[str, tuple[float | None, float]],
) -> tuple[float | None, dict[str, float]]:
    available = {
        key: (score, weight)
        for key, (score, weight) in components.items()
        if score is not None
    }
    if not available:
        return None, {}
    weight_sum = sum(weight for _, weight in available.values())
    total = sum(float(score) * weight for score, weight in available.values())
    normalized = total * 100.0 / weight_sum
    details = {
        key: round(float(score) * weight * 100.0 / weight_sum, 4)
        for key, (score, weight) in available.items()
    }
    return round(normalized, 4), details


def analyze_financial_observations(
    observations: Iterable[Any],
) -> FinancialQuantResult:
    """将截止日以前的长表观测值转换成可解释的量化结果。"""

    latest_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    periods: set[str] = set()
    for raw in observations:
        if callable(getattr(raw, "to_record", None)):
            item = dict(raw.to_record())
        else:
            try:
                # sqlite3.Row 支持 dict(row)，但没有注册为 Mapping。
                item = dict(raw)
            except (TypeError, ValueError) as exc:
                raise TypeError(
                    "observation 必须可转换为字典或提供 to_record()"
                ) from exc
        metric = str(item.get("metric", ""))
        period = str(item.get("period_end", ""))
        value = _finite(item.get("value"))
        if not metric or not period or value is None:
            continue
        periods.add(period)
        key = (metric, period)
        previous = latest_by_key.get(key)
        if previous is None or str(item.get("available_at", "")) >= str(
            previous.get("available_at", "")
        ):
            latest_by_key[key] = {**item, "value": value}

    def values(*metric_names: str) -> list[float]:
        candidates: list[list[float]] = []
        for metric_name in metric_names:
            pairs = sorted(
                (
                    (period, item["value"])
                    for (metric, period), item in latest_by_key.items()
                    if metric == metric_name
                ),
                key=lambda pair: pair[0],
            )
            if pairs:
                candidates.append([float(value) for _, value in pairs])
        return max(candidates, key=len) if candidates else []

    def latest(*metric_names: str) -> float | None:
        series = values(*metric_names)
        return series[-1] if series else None

    def acceleration(*metric_names: str) -> float | None:
        series = values(*metric_names)
        return series[-1] - series[-2] if len(series) >= 2 else None

    revenue_yoy_series = values(
        "revenue_single_quarter_yoy", "revenue_yoy"
    )
    profit_yoy_series = values(
        "net_profit_single_quarter_yoy", "net_profit_yoy"
    )
    deduct_yoy_series = values(
        "deduct_net_profit_single_quarter_yoy", "deduct_net_profit_yoy"
    )
    revenue_yoy = revenue_yoy_series[-1] if revenue_yoy_series else None
    profit_yoy = profit_yoy_series[-1] if profit_yoy_series else None
    deduct_yoy = deduct_yoy_series[-1] if deduct_yoy_series else None
    revenue_acceleration = acceleration(
        "revenue_single_quarter_yoy", "revenue_yoy"
    )
    profit_acceleration = acceleration(
        "net_profit_single_quarter_yoy", "net_profit_yoy"
    )
    deduct_acceleration = acceleration(
        "deduct_net_profit_single_quarter_yoy", "deduct_net_profit_yoy"
    )

    earnings_score, earnings_components = _weighted_score(
        {
            "revenue_growth": (_rising(revenue_yoy, -0.10, 0.30), 20.0),
            "revenue_acceleration": (
                _rising(revenue_acceleration, -0.15, 0.15), 15.0
            ),
            "profit_growth": (_rising(profit_yoy, -0.20, 0.50), 25.0),
            "profit_acceleration": (
                _rising(profit_acceleration, -0.25, 0.25), 20.0
            ),
            "deduct_profit_growth": (
                _rising(deduct_yoy, -0.20, 0.50), 10.0
            ),
            "deduct_profit_acceleration": (
                _rising(deduct_acceleration, -0.25, 0.25), 10.0
            ),
        }
    )

    gross_series = values("gross_margin_single_quarter", "gross_margin")
    net_margin_series = values("net_margin_single_quarter", "net_margin")
    roe = latest("roe_weighted")
    roe_periods = sorted(
        period
        for (metric, period) in latest_by_key
        if metric == "roe_weighted"
    )
    if roe is not None and roe_periods:
        month = int(roe_periods[-1][5:7])
        roe_annualized = roe * {3: 4.0, 6: 2.0, 9: 4.0 / 3.0, 12: 1.0}.get(
            month, 1.0
        )
    else:
        roe_annualized = None
    cash_per_share = latest(
        "operating_cash_flow_per_share_single_quarter",
        "operating_cash_flow_per_share",
    )
    eps = latest("basic_eps_single_quarter", "basic_eps")
    cash_profit_support = (
        cash_per_share / eps
        if cash_per_share is not None and eps is not None and eps > 0
        else None
    )
    inventory_series = values("inventory_turnover_days")
    receivables_series = values("receivables_turnover_days")
    debt_ratio = latest("debt_to_assets")

    business_score, business_components = _weighted_score(
        {
            "cash_profit_support": (
                _rising(cash_profit_support, 0.0, 1.25), 25.0
            ),
            "gross_margin_trend": (
                _rising(_trend(gross_series), -0.01, 0.01), 15.0
            ),
            "net_margin_trend": (
                _rising(_trend(net_margin_series), -0.01, 0.01), 15.0
            ),
            "roe_level": (_rising(roe_annualized, 0.0, 0.20), 20.0),
            "inventory_efficiency": (
                _falling(_relative_trend(inventory_series), -0.20, 0.20),
                10.0,
            ),
            "receivables_efficiency": (
                _falling(_relative_trend(receivables_series), -0.20, 0.20),
                10.0,
            ),
            "debt_level": (_falling(debt_ratio, 0.30, 0.85), 5.0),
        }
    )

    required = {
        "revenue_growth": revenue_yoy,
        "profit_growth": profit_yoy,
        "deduct_profit_growth": deduct_yoy,
        "gross_margin": gross_series[-1] if gross_series else None,
        "net_margin": net_margin_series[-1] if net_margin_series else None,
        "roe": roe,
        "operating_cash_flow_per_share": cash_per_share,
        "basic_eps": eps,
        "inventory_turnover_days": (
            inventory_series[-1] if inventory_series else None
        ),
        "receivables_turnover_days": (
            receivables_series[-1] if receivables_series else None
        ),
        "debt_to_assets": debt_ratio,
    }
    missing = tuple(key for key, value in required.items() if value is None)
    coverage = (len(required) - len(missing)) / len(required)
    if coverage >= 0.80 and len(periods) >= 6:
        status = "complete"
    elif coverage >= 0.50 and len(periods) >= 4:
        status = "partial"
    else:
        status = "insufficient"

    if status == "insufficient" or earnings_score is None:
        state = "UNCERTAIN"
    elif earnings_score >= 65 and (business_score is None or business_score >= 45):
        state = "IMPROVING"
    elif earnings_score <= 35:
        state = "DETERIORATING"
    else:
        state = "STABLE"

    return FinancialQuantResult(
        status=status,
        fundamental_state=state,
        quarters_available=len(periods),
        data_coverage=round(coverage, 4),
        earnings_momentum_score=earnings_score,
        business_quality_score=business_score,
        component_scores={
            "earnings_momentum": earnings_components,
            "business_quality": business_components,
        },
        metrics={
            "latest_revenue_yoy": revenue_yoy,
            "revenue_acceleration": revenue_acceleration,
            "latest_profit_yoy": profit_yoy,
            "profit_acceleration": profit_acceleration,
            "latest_deduct_profit_yoy": deduct_yoy,
            "deduct_profit_acceleration": deduct_acceleration,
            "gross_margin_trend_per_quarter": _trend(gross_series),
            "net_margin_trend_per_quarter": _trend(net_margin_series),
            "cash_profit_support": cash_profit_support,
            "roe_weighted": roe,
            "roe_annualized": roe_annualized,
            "inventory_days_relative_trend": _relative_trend(inventory_series),
            "receivables_days_relative_trend": _relative_trend(
                receivables_series
            ),
            "debt_to_assets": debt_ratio,
        },
        missing_metrics=missing,
    )
