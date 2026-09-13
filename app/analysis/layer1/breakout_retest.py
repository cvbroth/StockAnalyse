"""放量突破与突破位支撑条件。"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from ..contracts import ConditionResult, StockInput
from ..models import ScreenConfig


def evaluate_breakout_retest(
    df: pd.DataFrame,
    lookback: int,
    search_days: int,
    volume_multiple: float,
    max_fall: float,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    first_position = max(lookback, len(df) - search_days)
    for position in range(first_position, len(df)):
        prior_high = float(df["high"].iloc[position - lookback:position].max())
        prior_average_volume = float(
            df["volume"].iloc[max(0, position - 20):position].mean()
        )
        close = float(df["close"].iloc[position])
        volume = float(df["volume"].iloc[position])
        if (
            prior_high > 0
            and prior_average_volume > 0
            and close > prior_high
            and volume > prior_average_volume * volume_multiple
        ):
            events.append(
                {
                    "position": position,
                    "date": df["date"].iloc[position],
                    "breakout_price": prior_high,
                    "breakout_close": close,
                    "breakout_volume_lots": volume,
                    "prior_20d_average_volume_lots": prior_average_volume,
                }
            )
    if not events:
        return {
            "passed": False,
            "detail": {
                "breakout_found": False,
                "lookback_days": lookback,
                "search_days": search_days,
                "volume_multiple_threshold": volume_multiple,
                "maximum_allowed_fall": max_fall,
            },
        }
    event = events[-1]
    minimum_close = float(df["close"].iloc[event["position"]:].min())
    support_floor = float(event["breakout_price"] * (1.0 - max_fall))
    held = minimum_close >= support_floor
    post_breakout_volume = df["volume"].iloc[event["position"] + 1:]
    post_breakout_average = (
        float(post_breakout_volume.mean())
        if not post_breakout_volume.empty
        else math.nan
    )
    post_breakout_ratio = (
        post_breakout_average / float(event["prior_20d_average_volume_lots"])
        if math.isfinite(post_breakout_average)
        and float(event["prior_20d_average_volume_lots"]) > 0
        else math.nan
    )
    return {
        "passed": bool(held),
        "detail": {
            "breakout_found": True,
            "breakout_date": event["date"],
            "breakout_price": event["breakout_price"],
            "breakout_close": event["breakout_close"],
            "breakout_volume_lots": event["breakout_volume_lots"],
            "prior_20d_average_volume_lots": event[
                "prior_20d_average_volume_lots"
            ],
            "post_breakout_average_volume_lots": post_breakout_average,
            "post_breakout_volume_ratio_to_prior_average": post_breakout_ratio,
            "days_since_breakout": int(len(df) - 1 - event["position"]),
            "minimum_close_since_breakout": minimum_close,
            "support_floor": support_floor,
            "held_breakout": bool(held),
            "lookback_days": lookback,
            "search_days": search_days,
            "volume_multiple_threshold": volume_multiple,
            "maximum_allowed_fall": max_fall,
        },
    }


class BreakoutRetestModule:
    name = "breakout_retest"

    def analyze(
        self,
        stock: StockInput,
        config: ScreenConfig,
    ) -> ConditionResult:
        return ConditionResult.from_record(
            evaluate_breakout_retest(
                stock.bars,
                config.breakout_lookback,
                config.breakout_search_days,
                config.breakout_volume_multiple,
                config.breakout_max_fall,
            )
        )
