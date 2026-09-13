"""上涨日与下跌日成交量关系条件。"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from ..contracts import ConditionResult, StockInput
from ..models import ScreenConfig


def evaluate_volume_price(
    df: pd.DataFrame,
    window: int,
    ratio_threshold: float,
) -> dict[str, Any]:
    recent = df.iloc[-(window + 1):].copy()
    recent["change"] = recent["close"].pct_change()
    observations = recent.iloc[1:]
    up_volume = observations.loc[observations["change"] > 0, "volume"]
    down_volume = observations.loc[observations["change"] < 0, "volume"]
    up_mean = float(up_volume.mean()) if not up_volume.empty else math.nan
    down_mean = float(down_volume.mean()) if not down_volume.empty else math.nan
    ratio = up_mean / down_mean if down_mean > 0 else math.nan
    return {
        "passed": bool(math.isfinite(ratio) and ratio > ratio_threshold),
        "detail": {
            "up_day_average_volume_lots": up_mean,
            "down_day_average_volume_lots": down_mean,
            "up_down_volume_ratio": ratio,
            "up_days": int(len(up_volume)),
            "down_days": int(len(down_volume)),
            "threshold": ratio_threshold,
            "window_days": window,
        },
    }


class VolumePriceModule:
    name = "volume_price"

    def analyze(
        self,
        stock: StockInput,
        config: ScreenConfig,
    ) -> ConditionResult:
        return ConditionResult.from_record(
            evaluate_volume_price(
                stock.bars,
                config.volume_window,
                config.up_down_volume_ratio,
            )
        )
