from __future__ import annotations

import tempfile
import unittest
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from app.analysis import (
    AnalysisEngine,
    CONDITION_KEYS,
    ScreenConfig,
    StockInput,
    analyze_stock,
    apply_screen_overrides,
    load_layer1_config,
)
from app.analysis.layer1 import Layer1Analyzer


def regression_frame(rows: int = 130) -> pd.DataFrame:
    dates = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(rows)]
    close = [10.0 + offset * 0.04 for offset in range(rows)]
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "open": [value - 0.02 for value in close],
            "high": [value + 0.08 for value in close],
            "low": [value - 0.08 for value in close],
            "close": close,
            "volume": [1000.0 + (offset % 7) * 20 for offset in range(rows)],
        }
    )
    breakout_position = rows - 5
    prior_high = float(frame["high"].iloc[breakout_position - 60:breakout_position].max())
    frame.loc[breakout_position, ["open", "high", "low", "close", "volume"]] = [
        prior_high + 0.20,
        prior_high + 0.50,
        prior_high + 0.10,
        prior_high + 0.40,
        3000.0,
    ]
    for position in range(breakout_position + 1, rows):
        price = prior_high + 0.25 + (position - breakout_position) * 0.03
        frame.loc[position, ["open", "high", "low", "close", "volume"]] = [
            price - 0.02,
            price + 0.08,
            price - 0.08,
            price,
            1100.0,
        ]
    return frame


class Layer1ContractTests(unittest.TestCase):
    def test_default_modules_follow_stable_condition_order(self) -> None:
        analyzer = Layer1Analyzer()
        self.assertEqual(
            tuple(module.name for module in analyzer.modules),
            CONDITION_KEYS,
        )

    def test_standard_result_preserves_legacy_record_shape(self) -> None:
        bars = regression_frame()
        benchmark = bars.copy()
        end_date = bars.iloc[-1]["date"].strftime("%Y%m%d")
        config = ScreenConfig()
        stock = StockInput("600000", "回归样本", bars, benchmark, end_date)

        standard = AnalysisEngine().analyze(stock, config)
        legacy = analyze_stock(
            stock.code,
            stock.name,
            stock.bars,
            stock.benchmark,
            stock.end_date,
            config,
        )

        self.assertEqual(standard.to_record(), legacy)
        self.assertEqual(tuple(legacy["conditions"]), CONDITION_KEYS)
        self.assertEqual(legacy["technical_score_max"], 5)
        self.assertEqual(
            legacy["technical_score"],
            sum(item["passed"] for item in legacy["conditions"].values()),
        )


class Layer1ConfigurationTests(unittest.TestCase):
    def test_baseline_toml_matches_previous_code_defaults(self) -> None:
        loaded = load_layer1_config()
        self.assertEqual(loaded.version, "layer1-v1.2-baseline")
        self.assertEqual(asdict(loaded.screen), asdict(ScreenConfig()))

    def test_command_line_style_override_changes_only_named_value(self) -> None:
        baseline = ScreenConfig()
        overridden = apply_screen_overrides(
            baseline,
            market_percentile_cutoff=0.80,
        )
        self.assertEqual(overridden.market_percentile_cutoff, 0.80)
        self.assertEqual(overridden.breakout_lookback, baseline.breakout_lookback)
        self.assertEqual(overridden.up_down_volume_ratio, baseline.up_down_volume_ratio)

    def test_unknown_configuration_key_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "layer1.toml"
            path.write_text(
                "version = 'test'\n[screen]\nunknown = 1\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "未知参数"):
                load_layer1_config(path)


if __name__ == "__main__":
    unittest.main()
