from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.analysis.fundamentals import analyze_financial_observations
from app.fundamentals import FundamentalFetchRequest, FundamentalObservation
from app.providers.fundamentals import (
    AkshareThsFundamentalProvider,
    normalize_akshare_ths_financials,
)
from app.storage.fundamentals_sqlite import (
    connect_fundamental_database,
    load_observations,
    upsert_observations,
)


def request(as_of_date: str = "20250902", quarters: int = 8) -> FundamentalFetchRequest:
    return FundamentalFetchRequest(
        run_id="20250902-test",
        code="603505",
        name="测试",
        as_of_date=as_of_date,
        requested_quarters=quarters,
        technical_score=5,
        technical_quality_score=88.0,
        quality_rank=1,
        selection_reason="test",
    )


class AkshareFundamentalProviderTests(unittest.TestCase):
    def test_normalizer_respects_notice_date_and_cutoff(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "report_date": "2025-06-30",
                    "metric_name": "operating_income_total",
                    "value": "1000",
                    "single": "600",
                    "yoy": "0.20",
                    "single_yoy": "0.30",
                },
                {
                    "report_date": "2025-09-30",
                    "metric_name": "operating_income_total",
                    "value": "1800",
                    "single": "800",
                    "yoy": "0.25",
                    "single_yoy": "0.35",
                },
            ]
        )
        dataset = normalize_akshare_ths_financials(
            frame,
            request(),
            {
                "2025-06-30": "2025-08-29",
                "2025-09-30": "2025-10-28",
            },
        )
        self.assertTrue(dataset.observations)
        self.assertEqual(
            {item.period_end for item in dataset.observations},
            {"2025-06-30"},
        )
        self.assertEqual(dataset.observations[0].available_at, "2025-08-30")
        self.assertEqual(dataset.observations[0].availability_basis, "reported")
        metric_values = {
            item.metric: item.value for item in dataset.observations
        }
        self.assertEqual(metric_values["revenue"], 1000.0)
        self.assertEqual(metric_values["revenue_single_quarter_yoy"], 0.30)

    def test_missing_notice_uses_conservative_deadline(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "report_date": "2025-06-30",
                    "metric_name": "sale_gross_margin",
                    "value": "25",
                    "single": "26",
                    "yoy": "",
                    "single_yoy": "",
                }
            ]
        )
        dataset = normalize_akshare_ths_financials(frame, request(), {})
        self.assertEqual(dataset.observations[0].published_date, "2025-08-31")
        self.assertEqual(dataset.observations[0].available_at, "2025-09-01")
        self.assertEqual(
            dataset.observations[0].availability_basis,
            "conservative_deadline",
        )
        self.assertEqual(dataset.observations[0].value, 0.25)

    def test_provider_can_be_tested_without_network(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "report_date": "2025-06-30",
                    "metric_name": "basic_eps",
                    "value": "0.5",
                    "single": "0.3",
                    "yoy": "0.1",
                    "single_yoy": "0.2",
                }
            ]
        )
        provider = AkshareThsFundamentalProvider(
            abstract_loader=lambda **_: frame,
            notice_loader=lambda _: {"2025-06-30": "2025-08-20"},
        )
        dataset = provider.fetch(request())
        self.assertEqual(dataset.provider, "akshare_ths")
        self.assertEqual(dataset.observations[0].code, "603505")

    def test_notice_failure_falls_back_without_losing_financials(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "report_date": "2025-06-30",
                    "metric_name": "basic_eps",
                    "value": "0.5",
                    "single": "0.3",
                    "yoy": "0.1",
                    "single_yoy": "0.2",
                }
            ]
        )

        def failed_notice_loader(_: str) -> dict[str, str]:
            raise TimeoutError("notice timeout")

        provider = AkshareThsFundamentalProvider(
            retries=1,
            abstract_loader=lambda **_: frame,
            notice_loader=failed_notice_loader,
        )
        dataset = provider.fetch(request())
        self.assertTrue(dataset.observations)
        self.assertEqual(
            dataset.observations[0].availability_basis,
            "conservative_deadline",
        )


class FinancialQuantTests(unittest.TestCase):
    def observation(
        self, metric: str, period: str, value: float
    ) -> FundamentalObservation:
        return FundamentalObservation(
            code="603505",
            metric=metric,
            period_end=period,
            published_date=period,
            available_at=period,
            value=value,
            unit="RATIO",
            source="test",
            source_record_id=f"{period}:{metric}",
        )

    def test_improving_eight_quarters_are_scored_and_explained(self) -> None:
        periods = [
            "2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30",
            "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30",
        ]
        observations: list[FundamentalObservation] = []
        for index, period in enumerate(periods):
            observations.extend(
                [
                    self.observation(
                        "revenue_single_quarter_yoy", period, 0.02 + index * 0.04
                    ),
                    self.observation(
                        "net_profit_single_quarter_yoy", period, -0.10 + index * 0.09
                    ),
                    self.observation(
                        "deduct_net_profit_single_quarter_yoy",
                        period,
                        -0.12 + index * 0.09,
                    ),
                    self.observation(
                        "gross_margin_single_quarter", period, 0.18 + index * 0.005
                    ),
                    self.observation(
                        "net_margin_single_quarter", period, 0.06 + index * 0.004
                    ),
                    self.observation("roe_weighted", period, 0.04 + index * 0.01),
                    self.observation(
                        "operating_cash_flow_per_share_single_quarter",
                        period,
                        0.30 + index * 0.03,
                    ),
                    self.observation(
                        "basic_eps_single_quarter", period, 0.25 + index * 0.02
                    ),
                    self.observation(
                        "inventory_turnover_days", period, 120.0 - index * 4.0
                    ),
                    self.observation(
                        "receivables_turnover_days", period, 70.0 - index * 2.0
                    ),
                    self.observation(
                        "debt_to_assets", period, 0.60 - index * 0.02
                    ),
                ]
            )
        result = analyze_financial_observations(observations)
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.fundamental_state, "IMPROVING")
        self.assertEqual(result.data_coverage, 1.0)
        self.assertGreater(result.earnings_momentum_score or 0.0, 65.0)
        self.assertGreater(result.business_quality_score or 0.0, 50.0)
        self.assertAlmostEqual(
            sum(result.component_scores["earnings_momentum"].values()),
            result.earnings_momentum_score or 0.0,
            places=3,
        )
        self.assertIn("profit_acceleration", result.metrics)
        self.assertIn("cash_profit_support", result.metrics)

    def test_missing_metrics_reduce_coverage_instead_of_becoming_zero(self) -> None:
        observations = [
            self.observation(
                "revenue_single_quarter_yoy", f"202{i}-03-31", 0.10 + i * 0.01
            )
            for i in range(1, 7)
        ]
        result = analyze_financial_observations(observations)
        self.assertEqual(result.status, "insufficient")
        self.assertEqual(result.fundamental_state, "UNCERTAIN")
        self.assertGreater(result.earnings_momentum_score or 0.0, 0.0)
        self.assertLess(result.data_coverage, 0.50)
        self.assertIsNone(result.business_quality_score)

    def test_analyzer_accepts_sqlite_row_from_real_storage_boundary(self) -> None:
        observation = self.observation(
            "revenue_single_quarter_yoy",
            "2025-06-30",
            0.20,
        )
        with tempfile.TemporaryDirectory() as directory:
            connection = connect_fundamental_database(
                Path(directory) / "fundamentals.db"
            )
            try:
                upsert_observations(connection, [observation])
                connection.commit()
                rows = load_observations(
                    connection,
                    "603505",
                    "2025-06-30",
                )
                self.assertEqual(type(rows[0]).__name__, "Row")
                result = analyze_financial_observations(rows)
            finally:
                connection.close()
        self.assertEqual(result.quarters_available, 1)
        self.assertIsNotNone(result.earnings_momentum_score)


if __name__ == "__main__":
    unittest.main()
