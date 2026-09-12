from __future__ import annotations

import unittest

import pandas as pd

from app.services.screening import prepare_qfq_bars


class AdjustmentTests(unittest.TestCase):
    @staticmethod
    def bars(factors: list[float], source: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "code": ["600000", "600000"],
                "trade_date": ["20260910", "20260911"],
                "open": [10.0, 12.0],
                "high": [11.0, 13.0],
                "low": [9.0, 11.0],
                "close": [10.0, 12.0],
                "volume": [100.0, 200.0],
                "amount": [1000.0, 2400.0],
                "adj_factor": factors,
                "source": [source, source],
            }
        )

    def test_tushare_raw_prices_become_dynamic_qfq(self) -> None:
        result = prepare_qfq_bars(self.bars([1.0, 2.0], "tushare"))
        self.assertAlmostEqual(result.iloc[0]["close"], 5.0)
        self.assertAlmostEqual(result.iloc[1]["close"], 12.0)
        self.assertEqual(result["volume"].tolist(), [100.0, 200.0])

    def test_tencent_qfq_is_not_adjusted_twice(self) -> None:
        result = prepare_qfq_bars(
            self.bars([1.0, 1.0], "akshare_tencent_qfq")
        )
        self.assertEqual(result["close"].tolist(), [10.0, 12.0])

    def test_invalid_factor_row_is_removed(self) -> None:
        result = prepare_qfq_bars(self.bars([0.0, 1.0], "tushare"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["close"], 12.0)


if __name__ == "__main__":
    unittest.main()
