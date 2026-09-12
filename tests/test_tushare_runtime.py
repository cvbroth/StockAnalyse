from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.providers.tushare import EndpointRateLimiter, read_dotenv_value, resolve_token


class TushareRuntimeTests(unittest.TestCase):
    def test_environment_variable_has_priority_over_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("TUSHARE_TOKEN=file-token\n", encoding="utf-8")
            with patch.dict("os.environ", {"TUSHARE_TOKEN": "process-token"}):
                token, source = resolve_token("TUSHARE_TOKEN", env_file)
            self.assertEqual(token, "process-token")
            self.assertIn("环境变量", source)

    def test_dotenv_accepts_export_quotes_and_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "# comment\nexport TUSHARE_TOKEN='file-token' # local only\n",
                encoding="utf-8",
            )
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(
                    read_dotenv_value(env_file, "TUSHARE_TOKEN"), "file-token"
                )
                token, source = resolve_token("TUSHARE_TOKEN", env_file)
            self.assertEqual(token, "file-token")
            self.assertEqual(source, str(env_file.resolve()))

    def test_missing_token_lists_checked_locations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            with patch.dict("os.environ", {}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "当前进程环境变量"):
                    resolve_token("TUSHARE_TOKEN", env_file)

    def test_hourly_limit_is_converted_to_per_minute(self) -> None:
        limiter = EndpointRateLimiter("adj_factor", 200.0)
        changed = limiter.adapt_to_error(
            RuntimeError("抱歉，您访问接口(adj_factor)频率超限(1次/小时)")
        )
        self.assertTrue(changed)
        self.assertAlmostEqual(limiter.calls_per_minute, 1.0 / 60.0)
        self.assertIn("每小时最多 1 次", limiter.describe_limit())


if __name__ == "__main__":
    unittest.main()
