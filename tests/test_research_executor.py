from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.analysis.fundamentals import (
    FUNDAMENTAL_RESEARCH_SCHEMA_VERSION,
    FundamentalEvidence,
    FundamentalResearchResult,
)
from app.cli.research import main as research_main
from app.research import ResearchOrchestrator, ResearchWorkspace, load_research_request
from app.research.providers import FilesystemResearchProvider
from app.research.workspace import load_research_templates
from app.services.fundamental_research import prepare_research_request_file


def financial_record(code: str, name: str) -> dict:
    return {
        "code": code,
        "name": name,
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


def complete_result(request: dict) -> dict:
    result = FundamentalResearchResult(
        run_id=str(request["run_id"]),
        input_hash=str(request["input_hash"]),
        code=str(request["code"]),
        name=str(request["name"]),
        as_of_date=str(request["as_of_date"]),
        status="complete",
        fundamental_state="IMPROVING",
        industry_cycle_score=82.0,
        expectation_delta_score=78.0,
        risk_score=25.0,
        risk_level="LOW",
        confidence=0.85,
        signals={
            "revenue_accelerating": True,
            "profit_accelerating": True,
            "margin_improving": True,
            "industry_improving": True,
            "expectation_revision": True,
        },
        catalysts=("需求改善",),
        risks=("需求低于预期",),
        vetoes=(),
        evidence=(
            FundamentalEvidence(
                claim="需求改善",
                source_type="filing",
                source_name="公司公告",
                source_tier=1,
                published_date="2026-09-01",
                effective_period="最近90天",
                confidence=0.9,
                source_url="https://example.com/notice",
            ),
        ),
        why_now="盈利趋势与行业需求同时改善",
        industry_summary="需求和价格改善",
        expectation_summary="盈利预期可能上修",
        risk_summary="需求回落是主要风险",
        schema_version=FUNDAMENTAL_RESEARCH_SCHEMA_VERSION,
    )
    return result.to_record()


class ResearchExecutorTests(unittest.TestCase):
    def _prepare(self, root: Path):
        records = [
            financial_record("603505", "甲公司"),
            financial_record("600519", "乙公司"),
        ]
        request_path, template_path, requests = prepare_research_request_file(
            records,
            root,
            "20260911-test",
            "20260911",
            top_n=2,
            config_version="test",
        )
        metadata, loaded = load_research_request(request_path)
        workspace = ResearchWorkspace(root)
        workspace.prepare(
            loaded,
            load_research_templates(template_path),
            {"603505", "600519"},
        )
        return metadata, requests, workspace

    def test_prepares_isolated_work_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, requests, workspace = self._prepare(Path(directory))
            for request in requests:
                code = request["code"]
                item = workspace.work_items_directory / code
                self.assertTrue((item / "request.json").is_file())
                self.assertTrue((item / "result.template.json").is_file())
            self.assertTrue(workspace.inbox_directory.is_dir())

    def test_one_invalid_stock_does_not_discard_valid_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            metadata, requests, workspace = self._prepare(Path(directory))
            source = Path(directory) / "incoming"
            source.mkdir()
            (source / "603505.json").write_text(
                json.dumps(complete_result(requests[0])),
                encoding="utf-8",
            )
            invalid = complete_result(requests[1])
            invalid["input_hash"] = "b" * 64
            (source / "600519.json").write_text(
                json.dumps(invalid),
                encoding="utf-8",
            )

            orchestrator = ResearchOrchestrator(
                workspace,
                metadata,
                requests,
            )
            summary, results = orchestrator.execute(
                FilesystemResearchProvider(source)
            )

            self.assertEqual(summary.imported, 1)
            self.assertEqual(summary.complete, 1)
            self.assertEqual(summary.failed, 1)
            self.assertEqual(set(results), {"603505"})
            aggregate = json.loads(
                workspace.aggregate_path.read_text(encoding="utf-8")
            )
            self.assertEqual(aggregate["metadata"]["record_count"], 1)
            self.assertEqual(aggregate["records"][0]["code"], "603505")

    def test_resume_reuses_complete_and_imports_missing_stock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            metadata, requests, workspace = self._prepare(Path(directory))
            source = Path(directory) / "incoming"
            source.mkdir()
            for request in requests:
                (source / f"{request['code']}.json").write_text(
                    json.dumps(complete_result(request)),
                    encoding="utf-8",
                )
            orchestrator = ResearchOrchestrator(workspace, metadata, requests)
            first, _ = orchestrator.execute(
                FilesystemResearchProvider(source),
                codes=["603505"],
            )
            self.assertEqual(first.imported, 1)

            second, results = orchestrator.execute(
                FilesystemResearchProvider(source),
                resume=True,
            )
            self.assertEqual(second.reused, 1)
            self.assertEqual(second.imported, 1)
            self.assertEqual(second.complete, 2)
            self.assertEqual(second.failed, 0)
            self.assertEqual(set(results), {"603505", "600519"})

    def test_validate_only_does_not_write_summary_or_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            metadata, requests, workspace = self._prepare(Path(directory))
            workspace.write_result("603505", complete_result(requests[0]))
            orchestrator = ResearchOrchestrator(workspace, metadata, requests)

            summary, results = orchestrator.validate_existing()

            self.assertEqual(summary.complete, 1)
            self.assertEqual(summary.pending, 1)
            self.assertEqual(set(results), {"603505"})
            self.assertFalse(workspace.summary_path.exists())
            self.assertFalse(workspace.aggregate_path.exists())

    def test_cli_prepares_workspace_then_resumes_into_layer3(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_directory = Path(directory) / "output"
            run_id = "20260911-test"
            run_directory = output_directory / "runs" / run_id
            record = financial_record("603505", "甲公司")
            _, _, requests = prepare_research_request_file(
                [record],
                run_directory,
                run_id,
                "20260911",
                top_n=1,
                config_version="test",
            )
            financial_path = run_directory / "fundamental" / "financial_quant.json"
            financial_path.write_text(
                json.dumps(
                    {
                        "metadata": {
                            "run_id": run_id,
                            "as_of_date": "2026-09-11",
                        },
                        "records": [record],
                    }
                ),
                encoding="utf-8",
            )
            first_exit = research_main(
                [
                    "--run-id",
                    run_id,
                    "--output-dir",
                    str(output_directory),
                ]
            )
            self.assertEqual(first_exit, 0)
            workspace = ResearchWorkspace(run_directory)
            self.assertTrue(
                (
                    workspace.work_items_directory
                    / "603505"
                    / "request.json"
                ).is_file()
            )
            (workspace.inbox_directory / "603505.json").write_text(
                json.dumps(complete_result(requests[0])),
                encoding="utf-8",
            )

            second_exit = research_main(
                [
                    "--run-id",
                    run_id,
                    "--output-dir",
                    str(output_directory),
                    "--resume",
                ]
            )

            self.assertEqual(second_exit, 0)
            layer3 = json.loads(
                (run_directory / "fundamental" / "layer3.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(layer3["records"][0]["status"], "complete")
            self.assertEqual(layer3["records"][0]["rank"], 1)


if __name__ == "__main__":
    unittest.main()
