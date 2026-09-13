from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from app.analysis import (
    ScreenConfig,
    apply_transitions,
    load_latest_full_market,
    load_run_snapshot,
    write_run_snapshot,
)
from app.services.screening import main as screening_main
from tests.test_layer2_scoring import quality_record


class TransitionTests(unittest.TestCase):
    def test_first_run_is_not_reported_as_newly_confirmed(self) -> None:
        current = quality_record()
        counts = apply_transitions([current], [], None)
        self.assertEqual(current["transition"]["status"], "first_observation")
        self.assertFalse(current["newly_5of5"])
        self.assertEqual(counts, {"first_observation": 1})

    def test_watchlist_to_confirmed_is_newly_5of5(self) -> None:
        previous = quality_record()
        previous["technical_score"] = 4
        previous["conditions"]["volume_price"]["passed"] = False
        current = quality_record()
        apply_transitions([current], [previous], "old-run")
        self.assertEqual(current["transition"]["status"], "newly_5of5")
        self.assertTrue(current["newly_5of5"])

    def test_confirmed_to_watchlist_is_downgrade(self) -> None:
        previous = quality_record()
        current = quality_record()
        current["technical_score"] = 4
        current["conditions"]["breakout_retest"]["passed"] = False
        apply_transitions([current], [previous], "old-run")
        self.assertEqual(
            current["transition"]["status"],
            "downgraded_to_4of5",
        )

    def test_low_score_to_watchlist_is_newly_4of5(self) -> None:
        previous = quality_record()
        previous["technical_score"] = 2
        previous["conditions"]["volume_price"]["passed"] = False
        previous["conditions"]["breakout_retest"]["passed"] = False
        previous["conditions"]["relative_strength"]["passed"] = False
        current = quality_record()
        current["technical_score"] = 4
        current["conditions"]["volume_price"]["passed"] = False
        apply_transitions([current], [previous], "old-run")
        self.assertEqual(current["transition"]["status"], "newly_4of5")


class RunHistoryTests(unittest.TestCase):
    def test_snapshot_updates_latest_pointer_only_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            metadata = {"end_date": "20260911", "mode": "all"}
            record = quality_record()
            write_run_snapshot(
                output,
                "20260911-100000",
                [record],
                metadata,
                update_latest=True,
            )
            latest_id, latest_records = load_latest_full_market(output)
            self.assertEqual(latest_id, "20260911-100000")
            self.assertEqual(len(latest_records), 1)

            write_run_snapshot(
                output,
                "20260911-110000",
                [record],
                metadata,
                update_latest=False,
            )
            latest_id, _ = load_latest_full_market(output)
            self.assertEqual(latest_id, "20260911-100000")

    def test_layer2_can_rerun_without_opening_market_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            parent_id = "20260911-120000"
            write_run_snapshot(
                output,
                parent_id,
                [quality_record()],
                {
                    "end_date": "20260911",
                    "mode": "all",
                    "config": asdict(ScreenConfig()),
                },
                update_latest=True,
            )
            result = screening_main(
                [
                    "--from-layer",
                    "2",
                    "--run-id",
                    parent_id,
                    "--output-dir",
                    str(output),
                    "--db",
                    str(output / "does-not-exist.db"),
                ]
            )
            self.assertEqual(result, 0)
            pointer = json.loads(
                (output / "runs" / "latest_full_market.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(pointer["run_id"], parent_id)
            run_dirs = [
                path
                for path in (output / "runs").iterdir()
                if path.is_dir()
            ]
            self.assertEqual(len(run_dirs), 2)
            research = next(path for path in run_dirs if path.name != parent_id)
            self.assertTrue((research / "reports" / "technical_top.json").is_file())

    def test_invalid_run_id_cannot_escape_runs_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "格式无效"):
                load_run_snapshot(Path(directory), "../outside")

    def test_corrupt_latest_pointer_is_not_silently_treated_as_first_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            runs = output / "runs"
            runs.mkdir()
            (runs / "latest_full_market.json").write_text(
                "not-json",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "指针损坏"):
                load_latest_full_market(output)


if __name__ == "__main__":
    unittest.main()
