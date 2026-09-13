"""相对沪深300强度与全市场百分位条件。"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from ..contracts import ConditionResult, StockInput
from ..models import ScreenConfig
from .common import aligned_returns


def evaluate_relative_strength_base(
    df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    excess_60d_threshold: float,
) -> dict[str, Any]:
    stock_20, benchmark_20 = aligned_returns(df, benchmark_df, 20)
    stock_60, benchmark_60 = aligned_returns(df, benchmark_df, 60)
    excess_20 = stock_20 - benchmark_20
    excess_60 = stock_60 - benchmark_60
    finite = all(
        math.isfinite(value)
        for value in (stock_20, benchmark_20, stock_60, benchmark_60)
    )
    benchmark_rules_passed = bool(
        finite
        and excess_20 > 0
        and stock_60 > benchmark_60
        and excess_60 > excess_60d_threshold
    )
    return {
        "passed": benchmark_rules_passed,
        "detail": {
            "stock_return_20d": stock_20,
            "hs300_return_20d": benchmark_20,
            "excess_return_20d": excess_20,
            "stock_return_60d": stock_60,
            "hs300_return_60d": benchmark_60,
            "excess_return_60d": excess_60,
            "excess_return_60d_threshold": excess_60d_threshold,
            "benchmark_rules_passed": benchmark_rules_passed,
            "market_percentile": None,
            "market_percentile_cutoff": None,
            "market_percentile_required": False,
        },
    }


class RelativeStrengthModule:
    name = "relative_strength"

    def analyze(
        self,
        stock: StockInput,
        config: ScreenConfig,
    ) -> ConditionResult:
        return ConditionResult.from_record(
            evaluate_relative_strength_base(
                stock.bars,
                stock.benchmark,
                config.excess_return_60d,
            )
        )


def apply_market_percentiles(records: list[dict[str, Any]], cutoff: float) -> int:
    valid = {
        record["code"]: record["metrics"]["return_60d"]
        for record in records
        if math.isfinite(float(record["metrics"]["return_60d"]))
    }
    if not valid:
        raise RuntimeError("没有可用于计算全市场60日收益百分位的数据")
    percentiles = pd.Series(valid, dtype="float64").rank(pct=True, method="average")
    for record in records:
        detail = record["conditions"]["relative_strength"]["detail"]
        percentile = percentiles.get(record["code"], math.nan)
        percentile_value = float(percentile) if pd.notna(percentile) else math.nan
        detail["market_percentile"] = percentile_value * 100.0
        detail["market_percentile_cutoff"] = cutoff * 100.0
        detail["market_percentile_required"] = True
        detail["market_percentile_universe_size"] = int(len(valid))
        record["conditions"]["relative_strength"]["passed"] = bool(
            detail["benchmark_rules_passed"]
            and math.isfinite(percentile_value)
            and percentile_value >= cutoff
        )
        refresh_score(record)
    return len(valid)


def mark_percentile_not_required(records: list[dict[str, Any]]) -> None:
    for record in records:
        detail = record["conditions"]["relative_strength"]["detail"]
        detail["market_percentile"] = None
        detail["market_percentile_cutoff"] = None
        detail["market_percentile_required"] = False
        detail["market_percentile_note"] = (
            "--symbols为小样本检查模式：未计算、也不强制样本内百分位"
        )
        record["conditions"]["relative_strength"]["passed"] = bool(
            detail["benchmark_rules_passed"]
        )
        refresh_score(record)


def refresh_score(record: dict[str, Any]) -> None:
    from .scoring import refresh_score as update_score

    update_score(record)
