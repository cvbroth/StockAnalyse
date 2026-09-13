from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.analysis.fundamentals import FundamentalEvidence
from app.analysis.history import write_run_snapshot
from app.cli.fundamentals import main as fundamentals_main
from app.fundamentals import (
    FundamentalDataset,
    FundamentalFetchRequest,
    FundamentalObservation,
)
from app.services.fundamental_sync import (
    select_fundamental_candidates,
    synchronize_fundamental_candidates,
)
from app.storage.fundamentals_sqlite import (
    connect_fundamental_database,
    fundamental_database_stats,
    load_observations,
)


def candidate(code: str, score: int, quality: float, rank: int) -> dict:
    return {
        "code": code,
        "name": f"测试{code}",
        "base_filters": {"passed": True},
        "technical_score": score,
        "metrics": {"return_60d": quality / 1000.0},
        "quality": {
            "technical_quality_score": quality,
            "rank_within_tier": rank,
        },
    }


class FakeFundamentalProvider:
    provider_id = "fake"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch(self, request: FundamentalFetchRequest) -> FundamentalDataset:
        self.calls.append(request.code)
        observation = FundamentalObservation(
            code=request.code,
            metric="revenue",
            period_end="2026-06-30",
            published_date="2026-08-20",
            available_at="2026-08-20",
            value=123.0,
            unit="CNY_100M",
            source=self.provider_id,
            source_record_id=f"{request.code}-2026Q2",
        )
        return FundamentalDataset(
            provider=self.provider_id,
            code=request.code,
            as_of_date=request.as_of_date,
            observations=(observation,),
        )


class FundamentalContractTests(unittest.TestCase):
    def test_dataset_rejects_information_not_available_at_cutoff(self) -> None:
        future = FundamentalObservation(
            code="600000",
            metric="revenue",
            period_end="2026-09-30",
            published_date="2026-10-20",
            available_at="2026-10-20",
            value=1.0,
            unit="CNY",
            source="test",
            source_record_id="future",
        )
        with self.assertRaisesRegex(ValueError, "晚于分析截止日"):
            FundamentalDataset(
                provider="test",
                code="600000",
                as_of_date="2026-09-11",
                observations=(future,),
            )

    def test_evidence_requires_traceable_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "source_url 或 document_id"):
            FundamentalEvidence(
                claim="利润改善",
                source_type="filing",
                source_name="季度报告",
                published_date="20260901",
                effective_period="2026Q2",
                confidence=0.9,
            )


class SparseFundamentalStorageTests(unittest.TestCase):
    def test_candidates_are_ranked_and_limited_before_fetch(self) -> None:
        records = [
            candidate("600003", 4, 99.0, 1),
            candidate("600002", 5, 70.0, 2),
            candidate("600001", 5, 80.0, 1),
            candidate("600004", 3, 100.0, 1),
        ]
        requests = select_fundamental_candidates(
            records,
            run_id="20260911-test",
            as_of_date="20260911",
            top_n=2,
            quarters=8,
        )
        self.assertEqual([item.code for item in requests], ["600001", "600002"])
        self.assertTrue(all(item.requested_quarters == 8 for item in requests))

    def test_sync_is_cached_and_database_has_no_market_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = connect_fundamental_database(
                Path(directory) / "fundamentals.db"
            )
            try:
                request = FundamentalFetchRequest(
                    run_id="20260911-test",
                    code="600000",
                    name="测试",
                    as_of_date="20260911",
                    requested_quarters=8,
                    technical_score=5,
                    technical_quality_score=88.0,
                    quality_rank=1,
                    selection_reason="test",
                )
                provider = FakeFundamentalProvider()
                first = synchronize_fundamental_candidates(
                    connection, provider, [request], stale_after_days=7
                )
                second = synchronize_fundamental_candidates(
                    connection, provider, [request], stale_after_days=7
                )
                self.assertEqual(first["fetched"], 1)
                self.assertEqual(second["cached"], 1)
                self.assertEqual(provider.calls, ["600000"])
                self.assertEqual(len(load_observations(
                    connection, "600000", "2026-09-11"
                )), 1)
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                self.assertNotIn("daily_bars", tables)
            finally:
                connection.close()

    def test_failed_stock_is_recorded_without_aborting_other_candidates(self) -> None:
        class PartialProvider(FakeFundamentalProvider):
            def fetch(self, request: FundamentalFetchRequest) -> FundamentalDataset:
                if request.code == "600001":
                    raise RuntimeError("temporary")
                return super().fetch(request)

        with tempfile.TemporaryDirectory() as directory:
            connection = connect_fundamental_database(
                Path(directory) / "fundamentals.db"
            )
            try:
                requests = select_fundamental_candidates(
                    [candidate("600001", 5, 90.0, 1), candidate("600002", 5, 80.0, 2)],
                    "20260911-test",
                    "20260911",
                    top_n=2,
                    quarters=8,
                )
                result = synchronize_fundamental_candidates(
                    connection, PartialProvider(), requests, stale_after_days=7
                )
                self.assertEqual(result["failed"], 1)
                self.assertEqual(result["fetched"], 1)
                self.assertEqual(fundamental_database_stats(connection)["failed_codes"], 1)
            finally:
                connection.close()


class FundamentalPreparationCliTests(unittest.TestCase):
    def test_cli_prepares_request_without_network_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            database = root / "fundamentals.db"
            run_id = "20260911-test"
            records = [candidate("600001", 5, 90.0, 1)]
            write_run_snapshot(
                output,
                run_id,
                records,
                {"end_date": "20260911", "mode": "all"},
                update_latest=False,
            )
            result = fundamentals_main(
                [
                    "--run-id", run_id,
                    "--output-dir", str(output),
                    "--fundamental-db", str(database),
                    "--top-n", "1",
                    "--prepare-only",
                ]
            )
            self.assertEqual(result, 0)
            request_path = output / "runs" / run_id / "fundamental" / "request.json"
            payload = json.loads(request_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["metadata"]["status"], "prepared")
            self.assertEqual(payload["records"][0]["code"], "600001")
            connection = sqlite3.connect(database)
            try:
                count = connection.execute(
                    "SELECT COUNT(*) FROM candidate_requests"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(count, 1)

    def test_cli_uses_latest_full_market_run_when_run_id_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            database = root / "fundamentals.db"
            run_id = "20260911-latest"
            write_run_snapshot(
                output,
                run_id,
                [candidate("600001", 5, 90.0, 1)],
                {"end_date": "20260911", "mode": "all"},
                update_latest=True,
            )
            result = fundamentals_main(
                [
                    "--output-dir", str(output),
                    "--fundamental-db", str(database),
                    "--top-n", "1",
                    "--prepare-only",
                ]
            )
            self.assertEqual(result, 0)
            request_path = (
                output
                / "runs"
                / run_id
                / "fundamental"
                / "request.json"
            )
            self.assertTrue(request_path.is_file())

    def test_cli_rejects_zero_candidate_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            run_id = "20260911-test"
            write_run_snapshot(
                output,
                run_id,
                [candidate("600001", 5, 90.0, 1)],
                {"end_date": "20260911", "mode": "all"},
                update_latest=True,
            )
            result = fundamentals_main(
                [
                    "--output-dir", str(output),
                    "--fundamental-db", str(root / "fundamentals.db"),
                    "--top-n", "0",
                    "--prepare-only",
                ]
            )
            self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
