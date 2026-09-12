from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


class CliCompatibilityTests(unittest.TestCase):
    def run_help(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *arguments, "--help"],
            cwd=PROJECT_DIR,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )

    def test_update_old_and_new_entries(self) -> None:
        for arguments in (
            ("app/update_market.py",),
            ("-m", "app.cli.update"),
        ):
            with self.subTest(arguments=arguments):
                result = self.run_help(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--set-current", result.stdout)

    def test_screen_old_and_new_entries(self) -> None:
        for arguments in (
            ("app/screener_v1_2.py",),
            ("-m", "app.cli.screen"),
        ):
            with self.subTest(arguments=arguments):
                result = self.run_help(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--symbols", result.stdout)

    def test_daily_old_and_new_entries(self) -> None:
        for arguments in (
            ("app/run_daily.py",),
            ("-m", "app.cli.daily"),
        ):
            with self.subTest(arguments=arguments):
                result = self.run_help(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--output-dir", result.stdout)


if __name__ == "__main__":
    unittest.main()
