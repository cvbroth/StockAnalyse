from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.storage.sqlite import (
    bind_data_provider,
    connect_database,
    infer_data_provider,
    upsert_daily_bars,
)


class ProviderBindingTests(unittest.TestCase):
    def test_provider_is_idempotent_but_cannot_be_switched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = connect_database(Path(directory) / "market.db")
            try:
                self.assertEqual(bind_data_provider(connection, "tx"), "tx")
                self.assertEqual(bind_data_provider(connection, "tx"), "tx")
                with self.assertRaisesRegex(ValueError, "不能改为"):
                    bind_data_provider(connection, "tushare")
            finally:
                connection.close()

    def test_metadata_and_stored_source_mismatch_is_mixed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = connect_database(Path(directory) / "market.db")
            try:
                bind_data_provider(connection, "tx")
                frame = pd.DataFrame(
                    [
                        {
                            "code": "600000",
                            "trade_date": "20260911",
                            "open": 10.0,
                            "high": 11.0,
                            "low": 9.5,
                            "close": 10.5,
                            "volume": 1000.0,
                            "amount": 10000.0,
                            "adj_factor": 2.0,
                            "source": "tushare",
                        }
                    ]
                )
                upsert_daily_bars(connection, frame)
                connection.commit()
                self.assertEqual(infer_data_provider(connection), "mixed")
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
