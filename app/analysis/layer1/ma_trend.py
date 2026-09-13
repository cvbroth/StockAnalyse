"""均线多头结构与斜率条件。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..contracts import ConditionResult, StockInput
from ..models import ScreenConfig


def evaluate_ma_trend(df: pd.DataFrame) -> dict[str, Any]:
    close = df["close"]
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    current_close = float(close.iloc[-1])
    current_ma20 = float(ma20.iloc[-1])
    current_ma60 = float(ma60.iloc[-1])
    ma20_5d_ago = float(ma20.iloc[-6])
    ma60_10d_ago = float(ma60.iloc[-11])
    return {
        "passed": bool(
            current_close > current_ma20 > current_ma60
            and current_ma20 > ma20_5d_ago
            and current_ma60 > ma60_10d_ago
        ),
        "detail": {
            "close": current_close,
            "ma20": current_ma20,
            "ma60": current_ma60,
            "ma20_5d_rise": current_ma20 / ma20_5d_ago - 1.0,
            "ma60_10d_rise": current_ma60 / ma60_10d_ago - 1.0,
        },
    }


class MATrendModule:
    name = "ma_trend"

    def analyze(
        self,
        stock: StockInput,
        config: ScreenConfig,
    ) -> ConditionResult:
        return ConditionResult.from_record(evaluate_ma_trend(stock.bars))
