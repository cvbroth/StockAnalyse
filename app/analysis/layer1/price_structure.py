"""价格高点与低点抬升条件。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..contracts import ConditionResult, StockInput
from ..models import ScreenConfig


def evaluate_price_structure(df: pd.DataFrame, window: int) -> dict[str, Any]:
    previous = df.iloc[-2 * window:-window]
    recent = df.iloc[-window:]
    recent_high = float(recent["high"].max())
    previous_high = float(previous["high"].max())
    recent_low = float(recent["low"].min())
    previous_low = float(previous["low"].min())
    return {
        "passed": bool(recent_high > previous_high and recent_low > previous_low),
        "detail": {
            "recent_high": recent_high,
            "previous_high": previous_high,
            "recent_low": recent_low,
            "previous_low": previous_low,
            "window_days": window,
        },
    }


class PriceStructureModule:
    name = "price_structure"

    def analyze(
        self,
        stock: StockInput,
        config: ScreenConfig,
    ) -> ConditionResult:
        return ConditionResult.from_record(
            evaluate_price_structure(stock.bars, config.structure_window)
        )
