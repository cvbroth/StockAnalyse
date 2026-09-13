from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.services.weekly_report import generate_weekly_report


def write_daily(
    output: Path,
    run_id: str,
    market_date: str,
    code: str,
    rank: int,
    status: str = "complete",
) -> None:
    directory = output / "runs" / run_id / "fundamental"
    directory.mkdir(parents=True)
    payload = {
        "metadata": {
            "run_id": run_id,
            "as_of_date": market_date,
            "generated_at": f"{market_date[:4]}-{market_date[4:6]}-{market_date[6:]}T18:00:00+08:00",
            "status": status,
            "market_counts": {
                "successful": 5100,
                "confirmed_5of5": 100 + rank,
                "watchlist_4of5": 280,
            },
            "layer2_count": 25,
            "layer3_counts": {
                "complete": 1,
                "rejected": 0,
                "partial": 0,
                "failed": 0,
                "pending": 0,
            },
        },
        "records": [
            {
                "code": code,
                "name": "测试公司",
                "rank": rank,
                "status": "complete",
                "focus_status": "KEY_FOCUS",
                "final_score": 80 - rank,
                "catalysts": ["测试催化"],
                "risks": ["测试风险"],
            }
        ],
    }
    (directory / "daily_report.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


class WeeklyReportTests(unittest.TestCase):
    def test_aggregates_daily_reports_and_writes_publication_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            write_daily(output, "run-1", "20260907", "603505", 8)
            write_daily(output, "run-2", "20260911", "603505", 3)

            json_path, markdown_path, report = generate_weekly_report(output)

            self.assertEqual(report["metadata"]["week_id"], "2026-W37")
            self.assertEqual(report["metadata"]["trading_days"], 2)
            self.assertEqual(report["candidates"][0]["appearances"], 2)
            self.assertEqual(report["candidates"][0]["rank_improvement"], 5)
            self.assertTrue(json_path.is_file())
            self.assertTrue(markdown_path.is_file())
            self.assertTrue((output / "reports" / "weekly" / "2026-W37" / "qq.txt").is_file())
            self.assertTrue((output / "reports" / "latest" / "weekly-qq.txt").is_file())
            self.assertTrue((output / "reports" / "print-latest.sh").is_file())

    def test_rejects_week_without_reports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            write_daily(output, "run-1", "20260907", "603505", 8)
            with self.assertRaisesRegex(RuntimeError, "没有可用"):
                generate_weekly_report(output, week="2026-W38")

    def test_historical_week_does_not_replace_newer_latest_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            write_daily(output, "new", "20260914", "603505", 2)
            generate_weekly_report(output, week="2026-W38")
            write_daily(output, "old", "20260907", "603505", 8)
            generate_weekly_report(output, week="2026-W37")

            latest_period = (
                output / "reports" / "latest" / "weekly-period.txt"
            ).read_text(encoding="utf-8").strip()
            self.assertEqual(latest_period, "2026-W38")


if __name__ == "__main__":
    unittest.main()
