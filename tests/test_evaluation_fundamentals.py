from __future__ import annotations

import unittest
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from app.analysis.evaluation import evaluate_forward_performance
from app.analysis.history import write_run_snapshot
from app.analysis.layer2 import Layer2Config, rank_layer2_records
from app.analysis.fundamentals import (
    DisabledFundamentalAnalyzer,
    FundamentalInput,
)
from tests.test_layer2_scoring import quality_record
from app.cli.evaluate import main as evaluate_main
from app.storage.sqlite import connect_database, upsert_daily_bars


class EvaluationTests(unittest.TestCase):
    def test_forward_returns_use_adjusted_price_and_trading_day_offsets(self) -> None:
        record = quality_record()
        start = date(2026, 9, 1)
        record["as_of_date"] = start.strftime("%Y-%m-%d")
        dates = [start + timedelta(days=offset) for offset in range(65)]
        closes = [10.0 + offset * 0.10 for offset in range(65)]
        bars = pd.DataFrame(
            {
                "code": [record["code"]] * 65,
                "trade_date": [value.strftime("%Y%m%d") for value in dates],
                "close": closes,
                "adj_factor": [1.0] * 65,
                "source": ["test"] * 65,
            }
        )
        report = evaluate_forward_performance([record], bars, (20, 60))
        self.assertEqual(report["completed_by_horizon"], {"20": 1, "60": 1})
        result = report["records"][0]["forward"]
        self.assertAlmostEqual(result["20"]["return"], 0.20)
        self.assertAlmostEqual(result["60"]["return"], 0.60)
        self.assertAlmostEqual(result["60"]["maximum_drawdown"], 0.0)
        self.assertEqual(report["summary_by_pool"][0]["pool"], "A_5of5")

    def test_missing_future_horizon_is_reported_not_fabricated(self) -> None:
        record = quality_record()
        record["as_of_date"] = "2026-09-01"
        bars = pd.DataFrame(
            {
                "code": [record["code"]] * 5,
                "trade_date": [f"2026090{day}" for day in range(1, 6)],
                "close": [10.0, 10.1, 10.2, 10.3, 10.4],
                "adj_factor": [1.0] * 5,
            }
        )
        report = evaluate_forward_performance([record], bars, (20,))
        self.assertEqual(report["completed_by_horizon"], {"20": 0})
        self.assertIsNone(report["records"][0]["forward"]["20"])

    def test_evaluation_cli_writes_report_into_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            database = root / "market.db"
            start = date(2026, 1, 1)
            record = quality_record()
            record["as_of_date"] = start.strftime("%Y-%m-%d")
            rank_layer2_records([record], Layer2Config())
            run_id = "20260101-120000"
            write_run_snapshot(
                output,
                run_id,
                [record],
                {"end_date": "20260101", "mode": "all"},
                update_latest=True,
            )
            dates = [start + timedelta(days=offset) for offset in range(65)]
            bars = pd.DataFrame(
                {
                    "code": [record["code"]] * 65,
                    "trade_date": [value.strftime("%Y%m%d") for value in dates],
                    "open": [10.0 + offset * 0.1 for offset in range(65)],
                    "high": [10.2 + offset * 0.1 for offset in range(65)],
                    "low": [9.8 + offset * 0.1 for offset in range(65)],
                    "close": [10.0 + offset * 0.1 for offset in range(65)],
                    "volume": [1000.0] * 65,
                    "amount": [None] * 65,
                    "adj_factor": [1.0] * 65,
                    "source": ["akshare_tencent_qfq"] * 65,
                }
            )
            connection = connect_database(database)
            try:
                upsert_daily_bars(connection, bars)
                connection.commit()
            finally:
                connection.close()
            result = evaluate_main(
                [
                    "--run-id", run_id,
                    "--db", str(database),
                    "--output-dir", str(output),
                    "--horizons", "20", "60",
                ]
            )
            self.assertEqual(result, 0)
            self.assertTrue((output / "runs" / run_id / "evaluation.json").is_file())
            self.assertTrue((output / "runs" / run_id / "evaluation.csv").is_file())


class FundamentalInterfaceTests(unittest.TestCase):
    def test_disabled_provider_never_invents_fundamental_score(self) -> None:
        stock = FundamentalInput(
            code="600000",
            name="测试",
            as_of_date="20260911",
            technical_quality_score=88.0,
            technical_record={},
        )
        result = DisabledFundamentalAnalyzer().analyze(stock)
        self.assertEqual(result.status, "disabled")
        self.assertEqual(result.scores, {})
        self.assertEqual(result.vetoes, ())


if __name__ == "__main__":
    unittest.main()
