from __future__ import annotations

import unittest
from datetime import date, timedelta

import pandas as pd

from app.analysis.engine import (
    analyze_stock,
    basic_filters,
    evaluate_breakout_retest,
    normalize_code,
    period_return,
)
from app.analysis.models import ScreenConfig


def rising_frame(rows: int = 130) -> pd.DataFrame:
    dates = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(rows)]
    close = [10.0 + offset * 0.05 for offset in range(rows)]
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "open": [value - 0.02 for value in close],
            "high": [value + 0.10 for value in close],
            "low": [value - 0.10 for value in close],
            "close": close,
            "volume": [1000.0 + offset for offset in range(rows)],
        }
    )


class RuleTests(unittest.TestCase):
    def test_code_normalization_accepts_market_prefix(self) -> None:
        self.assertEqual(normalize_code("sh600000"), "600000")
        self.assertEqual(normalize_code("bj430047"), "430047")
        with self.assertRaises(ValueError):
            normalize_code("not-a-code")

    def test_period_return_uses_trading_day_offset(self) -> None:
        close = pd.Series(range(1, 22), dtype="float64")
        self.assertAlmostEqual(period_return(close, 20), 20.0)

    def test_st_filter_can_be_enabled_or_disabled(self) -> None:
        frame = rising_frame()
        end_date = frame.iloc[-1]["date"].strftime("%Y%m%d")
        blocked = basic_filters(
            "600000", "ST测试", frame, end_date, ScreenConfig(exclude_st=True)
        )
        allowed = basic_filters(
            "600000", "ST测试", frame, end_date, ScreenConfig(exclude_st=False)
        )
        self.assertFalse(blocked["passed"])
        self.assertTrue(allowed["passed"])

    def test_breakout_requires_volume_and_holds_support(self) -> None:
        frame = rising_frame(100)
        breakout_position = 95
        prior_high = float(frame["high"].iloc[35:95].max())
        frame.loc[breakout_position, "close"] = prior_high + 1.0
        frame.loc[breakout_position, "high"] = prior_high + 1.2
        frame.loc[breakout_position, "open"] = prior_high + 0.8
        frame.loc[breakout_position, "low"] = prior_high + 0.7
        frame.loc[breakout_position, "volume"] = 5000.0
        for position in range(96, 100):
            frame.loc[position, ["open", "high", "low", "close"]] = [
                prior_high + 0.7,
                prior_high + 1.0,
                prior_high + 0.5,
                prior_high + 0.8,
            ]
        result = evaluate_breakout_retest(frame, 60, 20, 1.3, 0.03)
        self.assertTrue(result["passed"])
        self.assertTrue(result["detail"]["breakout_found"])

    def test_analysis_rejects_short_history(self) -> None:
        frame = rising_frame(79)
        with self.assertRaisesRegex(ValueError, "历史交易日不足"):
            analyze_stock(
                "600000",
                "测试",
                frame,
                frame,
                frame.iloc[-1]["date"].strftime("%Y%m%d"),
                ScreenConfig(min_history_days=120),
            )


if __name__ == "__main__":
    unittest.main()
