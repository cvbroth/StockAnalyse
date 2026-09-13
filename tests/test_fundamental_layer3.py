from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.analysis.fundamentals import (
    FUNDAMENTAL_RESEARCH_SCHEMA_VERSION,
    FundamentalEvidence,
    FundamentalResearchResult,
    compose_layer3_result,
    rank_layer3_results,
)
from app.analysis.pipeline import AnalysisEngine
from app.fundamentals import FundamentalScoringConfig
from app.services.fundamental_research import (
    load_research_results,
    prepare_research_request_file,
    write_layer3_results,
)


def financial_record(code: str = "603505") -> dict:
    return {
        "code": code,
        "name": "测试公司",
        "as_of_date": "2026-09-11",
        "technical_context": {
            "technical_score": 5,
            "technical_quality_score": 88.0,
            "quality_rank": 1,
        },
        "financial_quant": {
            "status": "complete",
            "fundamental_state": "IMPROVING",
            "data_coverage": 1.0,
            "scores": {
                "earnings_momentum": 80.0,
                "business_quality": 70.0,
            },
        },
    }


def research_result(
    input_hash: str = "a" * 64,
    risk_level: str = "LOW",
    risk_score: float = 20.0,
) -> FundamentalResearchResult:
    return FundamentalResearchResult(
        run_id="20260911-test",
        input_hash=input_hash,
        code="603505",
        name="测试公司",
        as_of_date="20260911",
        status="complete",
        fundamental_state="IMPROVING",
        industry_cycle_score=90.0,
        expectation_delta_score=85.0,
        risk_score=risk_score,
        risk_level=risk_level,
        confidence=0.90,
        signals={
            "revenue_accelerating": True,
            "profit_accelerating": True,
            "margin_improving": True,
            "industry_improving": True,
            "expectation_revision": True,
        },
        catalysts=("产品价格上涨",),
        risks=("产品价格回落",),
        vetoes=(),
        evidence=(
            FundamentalEvidence(
                claim="产品价格上涨",
                source_type="filing",
                source_name="公司公告",
                source_tier=1,
                published_date="20260901",
                effective_period="最近90天",
                confidence=0.9,
                source_url="https://example.com/notice",
            ),
        ),
        why_now="盈利和行业景气同步改善",
        industry_summary="行业库存下降",
        expectation_summary="盈利预期可能上修",
        risk_summary="主要风险为价格回落",
    )


class ResearchContractTests(unittest.TestCase):
    def test_future_evidence_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "晚于运行截止日"):
            FundamentalResearchResult(
                **{
                    **research_result().__dict__,
                    "evidence": (
                        FundamentalEvidence(
                            claim="未来消息",
                            source_type="media",
                            source_name="测试",
                            published_date="20260912",
                            effective_period="未来",
                            confidence=0.5,
                            source_url="https://example.com/future",
                        ),
                    ),
                }
            )

    def test_request_has_stable_hash_and_result_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_directory = Path(directory)
            request_path, template_path, requests = prepare_research_request_file(
                [financial_record(), financial_record("600000")],
                run_directory,
                "20260911-test",
                "20260911",
                top_n=1,
                config_version="test",
            )
            self.assertTrue(request_path.is_file())
            self.assertTrue(template_path.is_file())
            self.assertEqual(len(requests), 1)
            self.assertEqual(len(requests[0]["input_hash"]), 64)
            template = json.loads(template_path.read_text(encoding="utf-8"))
            self.assertEqual(
                template["records"][0]["input_hash"],
                requests[0]["input_hash"],
            )

    def test_loader_rejects_result_from_different_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_directory = Path(directory)
            _, template_path, requests = prepare_research_request_file(
                [financial_record()],
                run_directory,
                "20260911-test",
                "20260911",
                top_n=1,
                config_version="test",
            )
            payload = json.loads(template_path.read_text(encoding="utf-8"))
            payload["records"][0]["input_hash"] = "b" * 64
            result_path = run_directory / "research_results.json"
            result_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "input_hash"):
                load_research_results(
                    result_path,
                    requests,
                    "20260911-test",
                    "20260911",
                )


class Layer3CompositionTests(unittest.TestCase):
    def test_missing_research_stays_pending_without_final_score(self) -> None:
        result = compose_layer3_result(
            financial_record(),
            None,
            FundamentalScoringConfig(),
        )
        self.assertEqual(result.status, "pending")
        self.assertEqual(result.focus_status, "PENDING_RESEARCH")
        self.assertIsNone(result.final_score)

    def test_analysis_engine_exposes_layer3_boundary(self) -> None:
        result = AnalysisEngine().analyze_layer3(
            financial_record(),
            None,
            FundamentalScoringConfig(),
        )
        self.assertEqual(result.status, "pending")

    def test_complete_research_produces_explainable_focus_score(self) -> None:
        result = compose_layer3_result(
            financial_record(),
            research_result(),
            FundamentalScoringConfig(),
        )
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.focus_status, "KEY_FOCUS")
        self.assertAlmostEqual(result.risk_penalty or 0.0, 3.0)
        self.assertGreater(result.final_score or 0.0, 75.0)

    def test_incomplete_financial_coverage_cannot_receive_final_rank(self) -> None:
        financial = financial_record()
        financial["financial_quant"]["status"] = "partial"
        result = compose_layer3_result(
            financial,
            research_result(),
            FundamentalScoringConfig(),
        )
        self.assertEqual(result.status, "partial")
        self.assertIsNone(result.final_score)

    def test_red_risk_is_vetoed_and_never_ranked(self) -> None:
        rejected = compose_layer3_result(
            financial_record(),
            research_result(risk_level="RED", risk_score=90.0),
            FundamentalScoringConfig(),
        )
        ranked = rank_layer3_results([rejected])
        self.assertEqual(ranked[0].status, "rejected")
        self.assertEqual(ranked[0].focus_status, "REJECTED")
        self.assertIsNone(ranked[0].rank)
        self.assertTrue(ranked[0].vetoes)

    def test_service_writes_pending_layer3_without_research(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_directory = Path(directory)
            _, _, requests = prepare_research_request_file(
                [financial_record()],
                run_directory,
                "20260911-test",
                "20260911",
                top_n=1,
                config_version="test",
            )
            path, records = write_layer3_results(
                [financial_record()],
                requests,
                {},
                run_directory,
                "20260911-test",
                "20260911",
                "test",
                FundamentalScoringConfig(),
            )
            self.assertTrue(path.is_file())
            self.assertEqual(records[0]["status"], "pending")
            self.assertIsNone(records[0]["final_score"])

    def test_complete_research_file_flows_through_validation_and_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_directory = Path(directory)
            _, _, requests = prepare_research_request_file(
                [financial_record()],
                run_directory,
                "20260911-test",
                "20260911",
                top_n=1,
                config_version="test",
            )
            research = research_result(input_hash=requests[0]["input_hash"])
            result_path = run_directory / "research_results.json"
            result_path.write_text(
                json.dumps(
                    {
                        "metadata": {
                            "schema_version": FUNDAMENTAL_RESEARCH_SCHEMA_VERSION,
                            "run_id": "20260911-test",
                            "as_of_date": "2026-09-11",
                            "record_count": 1,
                        },
                        "records": [research.to_record()],
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_research_results(
                result_path,
                requests,
                "20260911-test",
                "20260911",
            )
            _, records = write_layer3_results(
                [financial_record()],
                requests,
                loaded,
                run_directory,
                "20260911-test",
                "20260911",
                "test",
                FundamentalScoringConfig(),
            )
            self.assertEqual(records[0]["status"], "complete")
            self.assertEqual(records[0]["rank"], 1)
            self.assertEqual(records[0]["focus_status"], "KEY_FOCUS")


if __name__ == "__main__":
    unittest.main()
