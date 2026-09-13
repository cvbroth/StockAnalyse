"""利用后续行情评估历史技术评分。"""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean, median
from typing import Any

import pandas as pd


def _score_band(score: float) -> str:
    lower = min(90, max(0, int(score // 10) * 10))
    return f"{lower}-{lower + 10}"


def _pool(record: dict[str, Any]) -> str:
    return "A_5of5" if int(record.get("technical_score", 0)) == 5 else "B_4of5"


def evaluate_forward_performance(
    records: list[dict[str, Any]],
    raw_bars: pd.DataFrame,
    horizons: tuple[int, ...] = (20, 60),
) -> dict[str, Any]:
    if not horizons or any(horizon < 1 for horizon in horizons):
        raise ValueError("评估周期必须是正整数交易日")
    required = {"code", "trade_date", "close", "adj_factor"}
    missing = required.difference(raw_bars.columns)
    if missing:
        raise ValueError(f"向前评估行情缺少字段：{sorted(missing)}")

    bars = raw_bars.copy()
    bars["code"] = bars["code"].astype(str).str.zfill(6)
    bars["trade_date"] = bars["trade_date"].astype(str)
    bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
    bars["adj_factor"] = pd.to_numeric(bars["adj_factor"], errors="coerce")
    bars["adjusted_close"] = bars["close"] * bars["adj_factor"]
    bars = bars.dropna(subset=["adjusted_close"])
    bars = bars[(bars["adjusted_close"] > 0) & (bars["adj_factor"] > 0)]
    grouped = {
        code: group.sort_values("trade_date").drop_duplicates("trade_date", keep="last")
        for code, group in bars.groupby("code", sort=False)
    }

    evaluated: list[dict[str, Any]] = []
    for record in records:
        code = str(record["code"]).zfill(6)
        group = grouped.get(code)
        if group is None or group.empty:
            continue
        as_of = str(record.get("as_of_date", "")).replace("-", "")
        base_positions = group.index[group["trade_date"] <= as_of].tolist()
        if not base_positions:
            continue
        base_label = base_positions[-1]
        base_position = group.index.get_loc(base_label)
        base_close = float(group.iloc[base_position]["adjusted_close"])
        horizon_results: dict[str, dict[str, float] | None] = {}
        for horizon in horizons:
            target_position = base_position + horizon
            if target_position >= len(group):
                horizon_results[str(horizon)] = None
                continue
            path = group.iloc[base_position:target_position + 1]["adjusted_close"].astype(float)
            target_close = float(path.iloc[-1])
            running_peak = path.cummax()
            maximum_drawdown = float((path / running_peak - 1.0).min())
            horizon_results[str(horizon)] = {
                "return": target_close / base_close - 1.0,
                "maximum_drawdown": maximum_drawdown,
                "target_date": str(group.iloc[target_position]["trade_date"]),
            }
        quality = record.get("quality", {})
        score = float(quality.get("technical_quality_score", 0.0))
        evaluated.append(
            {
                "code": code,
                "name": record.get("name"),
                "as_of_date": as_of,
                "pool": _pool(record),
                "technical_score": int(record.get("technical_score", 0)),
                "technical_quality_score": score,
                "score_band": _score_band(score),
                "transition_status": record.get("transition", {}).get("status"),
                "forward": horizon_results,
            }
        )

    def summaries(group_key: str) -> list[dict[str, Any]]:
        buckets: dict[tuple[str, int], list[tuple[float, float]]] = defaultdict(list)
        for item in evaluated:
            group_name = str(item[group_key])
            for horizon in horizons:
                result = item["forward"][str(horizon)]
                if result is not None:
                    buckets[(group_name, horizon)].append(
                        (float(result["return"]), float(result["maximum_drawdown"]))
                    )
        output: list[dict[str, Any]] = []
        for (group_name, horizon), values in sorted(buckets.items()):
            returns = [value[0] for value in values]
            drawdowns = [value[1] for value in values]
            output.append(
                {
                    group_key: group_name,
                    "horizon_days": horizon,
                    "count": len(values),
                    "mean_return": mean(returns),
                    "median_return": median(returns),
                    "win_rate": sum(value > 0 for value in returns) / len(returns),
                    "average_maximum_drawdown": mean(drawdowns),
                }
            )
        return output

    completed_by_horizon = {
        str(horizon): sum(
            item["forward"][str(horizon)] is not None for item in evaluated
        )
        for horizon in horizons
    }
    return {
        "requested_records": len(records),
        "matched_records": len(evaluated),
        "completed_by_horizon": completed_by_horizon,
        "horizons": list(horizons),
        "summary_by_pool": summaries("pool"),
        "summary_by_score_band": summaries("score_band"),
        "records": evaluated,
    }


def flatten_evaluation_records(
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    horizons = [int(value) for value in report["horizons"]]
    for item in report["records"]:
        row = {
            key: item.get(key)
            for key in (
                "code", "name", "as_of_date", "pool", "technical_score",
                "technical_quality_score", "score_band", "transition_status",
            )
        }
        for horizon in horizons:
            result = item["forward"].get(str(horizon))
            row[f"return_{horizon}d"] = (
                float(result["return"]) if result is not None else math.nan
            )
            row[f"max_drawdown_{horizon}d"] = (
                float(result["maximum_drawdown"])
                if result is not None else math.nan
            )
            row[f"target_date_{horizon}d"] = (
                result["target_date"] if result is not None else None
            )
        rows.append(row)
    return rows
