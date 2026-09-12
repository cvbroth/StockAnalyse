from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.cli.daily import main


class DailyOrchestrationTests(unittest.TestCase):
    def test_failed_update_stops_before_screening(self) -> None:
        with patch("app.cli.daily.subprocess.run") as run:
            run.return_value = SimpleNamespace(returncode=1)
            result = main(
                [
                    "--db",
                    str(Path("data/test.db")),
                    "--output-dir",
                    str(Path("output")),
                ]
            )
        self.assertEqual(result, 1)
        self.assertEqual(run.call_count, 1)

    def test_successful_update_runs_screening(self) -> None:
        with patch("app.cli.daily.subprocess.run") as run:
            run.side_effect = [
                SimpleNamespace(returncode=0),
                SimpleNamespace(returncode=0),
            ]
            result = main(
                [
                    "--db",
                    str(Path("data/test.db")),
                    "--output-dir",
                    str(Path("output")),
                ]
            )
        self.assertEqual(result, 0)
        self.assertEqual(run.call_count, 2)
        first_command = run.call_args_list[0].args[0]
        second_command = run.call_args_list[1].args[0]
        self.assertIn("--daily", first_command)
        self.assertIn("--all", second_command)


if __name__ == "__main__":
    unittest.main()
