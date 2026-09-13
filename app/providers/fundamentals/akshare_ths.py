"""AKShare同花顺财务摘要提供者，东方财富仅补精确公告日期。"""

from __future__ import annotations

import math
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable

import pandas as pd
import requests

from ...fundamentals import (
    FundamentalDataset,
    FundamentalFetchRequest,
    FundamentalObservation,
)


NOTICE_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


VALUE_METRICS: dict[str, tuple[str, str, float, bool]] = {
    # 原字段: (标准字段, 单位, 缩放, 是否保存单季度值和同比)
    "operating_income_total": ("revenue", "CNY", 1.0, True),
    "parent_holder_net_profit": ("net_profit", "CNY", 1.0, True),
    "index_deduct_holder_net_profit": (
        "deduct_net_profit", "CNY", 1.0, True
    ),
    "basic_eps": ("basic_eps", "CNY_PER_SHARE", 1.0, True),
    "sale_gross_margin": ("gross_margin", "RATIO", 0.01, False),
    "sale_net_interest_ratio": ("net_margin", "RATIO", 0.01, False),
    "index_weighted_avg_roe": ("roe_weighted", "RATIO", 0.01, False),
    "index_per_operating_cash_flow_net": (
        "operating_cash_flow_per_share", "CNY_PER_SHARE", 1.0, True
    ),
    "inventory_turnover_days": ("inventory_turnover_days", "DAYS", 1.0, False),
    "receive_accounts_turnover_days": (
        "receivables_turnover_days", "DAYS", 1.0, False
    ),
    "assets_debt_ratio": ("debt_to_assets", "RATIO", 0.01, False),
}


def _date_only(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        raise ValueError("日期为空")
    parsed = pd.to_datetime(value, errors="raise")
    return parsed.date().isoformat()


def _to_float(value: Any, scale: float = 1.0) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "None", "nan", "NaN"}:
        return None
    if text.endswith("%"):
        text = text[:-1]
        scale *= 0.01
    try:
        number = float(text) * scale
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def conservative_publication_date(period_end: str) -> str:
    """缺少真实公告日期时使用最晚披露日，宁可晚用也不偷看未来。"""

    period = datetime.strptime(period_end, "%Y-%m-%d").date()
    if (period.month, period.day) == (3, 31):
        deadline = date(period.year, 4, 30)
    elif (period.month, period.day) == (6, 30):
        deadline = date(period.year, 8, 31)
    elif (period.month, period.day) == (9, 30):
        deadline = date(period.year, 10, 31)
    elif (period.month, period.day) == (12, 31):
        deadline = date(period.year + 1, 4, 30)
    else:
        raise ValueError(f"不是标准季度报告期：{period_end}")
    return deadline.isoformat()


def normalize_akshare_ths_financials(
    frame: pd.DataFrame,
    request: FundamentalFetchRequest,
    notice_dates: dict[str, str],
) -> FundamentalDataset:
    required = {"report_date", "metric_name", "value", "single", "yoy", "single_yoy"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"AKShare财务摘要缺少字段：{sorted(missing)}")
    if frame.empty:
        return FundamentalDataset(
            provider="akshare_ths",
            code=request.code,
            as_of_date=request.as_of_date,
            observations=(),
        )

    working = frame.copy()
    working["report_date"] = working["report_date"].map(_date_only)
    periods = sorted(
        {
            value
            for value in working["report_date"].tolist()
            if value <= request.as_of_date
        },
        reverse=True,
    )
    selected_periods: list[tuple[str, str, str, str]] = []
    for period in periods:
        reported = notice_dates.get(period)
        if reported:
            published_date = _date_only(reported)
            available_at = (
                datetime.strptime(published_date, "%Y-%m-%d").date()
                + timedelta(days=1)
            ).isoformat()
            basis = "reported"
        else:
            published_date = conservative_publication_date(period)
            available_at = (
                datetime.strptime(published_date, "%Y-%m-%d").date()
                + timedelta(days=1)
            ).isoformat()
            basis = "conservative_deadline"
        if available_at <= request.as_of_date:
            selected_periods.append((period, published_date, available_at, basis))
        if len(selected_periods) >= request.requested_quarters:
            break

    observations: list[FundamentalObservation] = []
    for period, published_date, available_at, basis in selected_periods:
        period_rows = working.loc[working["report_date"] == period]
        for row in period_rows.itertuples(index=False):
            source_metric = str(row.metric_name)
            definition = VALUE_METRICS.get(source_metric)
            if definition is None:
                continue
            metric, unit, scale, with_variants = definition
            variants: list[tuple[str, Any, str, float]] = [
                (metric, row.value, unit, scale)
            ]
            variants.append(
                (f"{metric}_single_quarter", row.single, unit, scale)
            )
            if with_variants:
                variants.extend(
                    [
                        (f"{metric}_yoy", row.yoy, "RATIO", 1.0),
                        (
                            f"{metric}_single_quarter_yoy",
                            row.single_yoy,
                            "RATIO",
                            1.0,
                        ),
                    ]
                )
            for output_metric, raw_value, output_unit, output_scale in variants:
                value = _to_float(raw_value, output_scale)
                if value is None:
                    continue
                observations.append(
                    FundamentalObservation(
                        code=request.code,
                        metric=output_metric,
                        period_end=period,
                        published_date=published_date,
                        available_at=available_at,
                        value=value,
                        unit=output_unit,
                        source="akshare_ths",
                        source_record_id=(
                            f"{request.code}:{period}:{source_metric}:{output_metric}"
                        ),
                        availability_basis=basis,
                    )
                )
    return FundamentalDataset(
        provider="akshare_ths",
        code=request.code,
        as_of_date=request.as_of_date,
        observations=tuple(observations),
    )


class AkshareThsFundamentalProvider:
    """每只股票一次财务摘要请求和一次公告日期请求。"""

    provider_id = "akshare_ths"

    def __init__(
        self,
        timeout: float = 15.0,
        retries: int = 3,
        abstract_loader: Callable[..., pd.DataFrame] | None = None,
        notice_loader: Callable[[str], dict[str, str]] | None = None,
    ) -> None:
        if timeout <= 0 or retries < 1:
            raise ValueError("timeout必须大于0，retries必须至少为1")
        if abstract_loader is None:
            import akshare as ak

            abstract_loader = ak.stock_financial_abstract_new_ths
        self.timeout = float(timeout)
        self.retries = int(retries)
        self.abstract_loader = abstract_loader
        self.notice_loader = notice_loader or self._load_notice_dates

    def _retry(self, label: str, action: Callable[[], Any]) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                return action()
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(0.8 * (attempt + 1))
        raise RuntimeError(f"{label}失败（已重试{self.retries}次）：{last_error}")

    def _load_notice_dates(self, code: str) -> dict[str, str]:
        params = {
            "sortColumns": "REPORTDATE",
            "sortTypes": "-1",
            "pageSize": "200",
            "pageNumber": "1",
            "reportName": "RPT_LICO_FN_CPD",
            "columns": "SECURITY_CODE,REPORTDATE,NOTICE_DATE",
            "filter": f'(SECURITY_CODE="{code}")',
        }
        response = requests.get(NOTICE_URL, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        rows = (payload.get("result") or {}).get("data") or []
        result: dict[str, str] = {}
        for row in rows:
            try:
                period = _date_only(row.get("REPORTDATE"))
                notice = _date_only(row.get("NOTICE_DATE"))
            except (TypeError, ValueError):
                continue
            existing = result.get(period)
            if existing is None or notice < existing:
                result[period] = notice
        return result

    def fetch(self, request: FundamentalFetchRequest) -> FundamentalDataset:
        frame = self._retry(
            f"{request.code} 财务摘要",
            lambda: self.abstract_loader(
                symbol=request.code,
                indicator="按报告期",
            ),
        )
        try:
            notices = self._retry(
                f"{request.code} 公告日期",
                lambda: self.notice_loader(request.code),
            )
        except RuntimeError:
            # 公告日期是增强信息；缺失时使用更晚、更保守的法定披露截止日，
            # 不让辅助接口故障阻断整只股票的财务摘要。
            notices = {}
        return normalize_akshare_ths_financials(frame, request, notices)
