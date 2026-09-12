from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from app.analysis import apply_market_percentiles, mark_percentile_not_required
from app.providers import get_provider_descriptor
from app.providers.tencent import normalize_tx_qfq
from app.providers.tushare import normalize_trade_date
from app.services.screening import main as screening_main
from app.storage.sqlite import (
    connect_database,
    set_metadata,
    upsert_daily_bars,
    upsert_index_bars,
    upsert_securities,
)


class ProviderContractTests(unittest.TestCase):
    def test_provider_capabilities_are_explicit(self) -> None:
        tx = get_provider_descriptor("tx")
        tushare = get_provider_descriptor("tushare")
        self.assertEqual(tx.update_unit, "security")
        self.assertEqual(tx.adjustment_mode, "provider_qfq")
        self.assertFalse(tx.requires_token)
        self.assertEqual(tushare.update_unit, "trade_date")
        self.assertEqual(tushare.adjustment_mode, "raw_plus_factor")
        self.assertTrue(tushare.requires_token)

    def test_tencent_normalizes_to_storage_schema(self) -> None:
        raw = pd.DataFrame(
            {
                "date": ["2026-09-10", "2026-09-11"],
                "open": [10.0, 10.5],
                "close": [10.5, 10.8],
                "high": [10.8, 11.0],
                "low": [9.9, 10.4],
                "amount": [1000.0, 1200.0],
            }
        )
        result = normalize_tx_qfq(raw, "600000")
        self.assertEqual(result.iloc[-1]["trade_date"], "20260911")
        self.assertEqual(result.iloc[-1]["adj_factor"], 1.0)
        self.assertEqual(result.iloc[-1]["source"], "akshare_tencent_qfq")

    def test_tushare_merges_daily_and_adjustment_factor(self) -> None:
        daily = pd.DataFrame(
            {
                "ts_code": ["600000.SH"],
                "trade_date": ["20260911"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.9],
                "close": [10.8],
                "vol": [1000.0],
                "amount": [1080.0],
            }
        )
        factors = pd.DataFrame(
            {
                "ts_code": ["600000.SH"],
                "trade_date": ["20260911"],
                "adj_factor": [2.5],
            }
        )
        result = normalize_trade_date(daily, factors, "20260911", 1)
        self.assertEqual(result.iloc[0]["code"], "600000")
        self.assertEqual(result.iloc[0]["adj_factor"], 2.5)
        self.assertEqual(result.iloc[0]["source"], "tushare")


class AnalysisCoreTests(unittest.TestCase):
    @staticmethod
    def record(code: str, return_60d: float, benchmark_passed: bool) -> dict:
        return {
            "code": code,
            "metrics": {"return_60d": return_60d},
            "base_filters": {"passed": True},
            "conditions": {
                "price_structure": {"passed": False},
                "ma_trend": {"passed": False},
                "volume_price": {"passed": False},
                "breakout_retest": {"passed": False},
                "relative_strength": {
                    "passed": benchmark_passed,
                    "detail": {"benchmark_rules_passed": benchmark_passed},
                },
            },
        }

    def test_full_market_and_symbol_modes_remain_distinct(self) -> None:
        records = [
            self.record("600000", 0.10, True),
            self.record("000001", 0.20, True),
        ]
        self.assertEqual(apply_market_percentiles(records, 0.70), 2)
        self.assertFalse(records[0]["conditions"]["relative_strength"]["passed"])
        self.assertTrue(records[1]["conditions"]["relative_strength"]["passed"])

        sample = [self.record("600000", 0.10, True)]
        mark_percentile_not_required(sample)
        detail = sample[0]["conditions"]["relative_strength"]["detail"]
        self.assertFalse(detail["market_percentile_required"])
        self.assertIsNone(detail["market_percentile"])
        self.assertTrue(sample[0]["conditions"]["relative_strength"]["passed"])


class ScreeningIntegrationTests(unittest.TestCase):
    def test_local_database_flows_through_new_service(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "market.db"
            output = root / "output"
            dates = [
                (date(2026, 1, 1) + timedelta(days=offset)).strftime("%Y%m%d")
                for offset in range(130)
            ]
            connection = connect_database(database)
            try:
                set_metadata(connection, "data_provider", "tx")
                upsert_securities(
                    connection,
                    [("600000", "测试一"), ("000001", "测试二")],
                )
                daily_rows = []
                for position, trade_date in enumerate(dates):
                    for code, slope in (("600000", 0.02), ("000001", 0.03)):
                        close = 10.0 + position * slope
                        daily_rows.append(
                            {
                                "code": code,
                                "trade_date": trade_date,
                                "open": close - 0.05,
                                "high": close + 0.10,
                                "low": close - 0.10,
                                "close": close,
                                "volume": 1000.0 + position,
                                "amount": None,
                                "adj_factor": 1.0,
                                "source": "akshare_tencent_qfq",
                            }
                        )
                upsert_daily_bars(connection, pd.DataFrame(daily_rows))
                index_rows = pd.DataFrame(
                    {
                        "trade_date": dates,
                        "open": [100.0 + i * 0.05 for i in range(130)],
                        "high": [100.2 + i * 0.05 for i in range(130)],
                        "low": [99.8 + i * 0.05 for i in range(130)],
                        "close": [100.0 + i * 0.05 for i in range(130)],
                        "volume": [10000.0] * 130,
                    }
                )
                upsert_index_bars(connection, index_rows)
                connection.commit()
            finally:
                connection.close()

            result = screening_main(
                [
                    "--all",
                    "--db",
                    str(database),
                    "--output-dir",
                    str(output),
                    "--progress-every",
                    "0",
                ]
            )
            self.assertEqual(result, 0)
            self.assertTrue((output / "candidates.json").is_file())
            self.assertTrue((output / "errors.csv").is_file())


if __name__ == "__main__":
    unittest.main()
