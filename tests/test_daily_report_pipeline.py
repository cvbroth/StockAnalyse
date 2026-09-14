from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.services.daily_pipeline import DailyPipeline
from app.services.daily_report import generate_daily_report
from app.cli.report import main as report_main


RUN_ID = "20260911-pipeline"


def layer3_record(status: str = "complete", rank: int | None = 1) -> dict:
    return {
        "code": "603505",
        "name": "测试公司",
        "status": status,
        "fundamental_state": "IMPROVING",
        "focus_status": "KEY_FOCUS" if status == "complete" else "PENDING_REVIEW",
        "scores": {
            "earnings_momentum": 80.0,
            "business_quality": 72.0,
            "industry_cycle": 85.0 if status == "complete" else None,
            "expectation_delta": 82.0 if status == "complete" else None,
            "risk": 25.0 if status == "complete" else None,
        },
        "positive_score": 80.0 if status == "complete" else None,
        "risk_penalty": 3.75 if status == "complete" else None,
        "final_score": 76.25 if status == "complete" else None,
        "confidence": 0.9 if status == "complete" else None,
        "vetoes": [],
        "catalysts": ["产品价格改善"] if status == "complete" else [],
        "risks": ["产品价格回落"] if status == "complete" else [],
        "rank": rank,
        "technical_context": {
            "technical_score": 5,
            "technical_quality_score": 88.0,
            "quality_rank": 1,
        },
        "financial_quant": {
            "data_coverage": 1.0,
            "quarters_available": 8,
            "scores": {
                "earnings_momentum": 80.0,
                "business_quality": 72.0,
            },
        },
        "research": {
            "why_now": "行业和盈利预期同步改善",
            "evidence": [
                {
                    "claim": "公司订单与盈利预期改善",
                    "source_type": "filing",
                    "source_name": "测试公司公告",
                    "source_tier": 1,
                    "published_date": "20260910",
                    "effective_period": "2026年三季度",
                    "confidence": 0.9,
                    "source_url": "https://example.com/filing",
                }
            ],
        } if status == "complete" else None,
    }


def prepare_run(
    output_directory: Path,
    status: str = "complete",
    run_id: str = RUN_ID,
    market_date: str = "20260911",
    record: dict | None = None,
) -> Path:
    run_directory = output_directory / "runs" / run_id
    fundamental = run_directory / "fundamental"
    fundamental.mkdir(parents=True)
    manifest = {
        "run_id": run_id,
        "end_date": market_date,
        "status": "complete",
    }
    (run_directory / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (run_directory / "layer1.json").write_text(
        json.dumps({"metadata": manifest, "records": []}), encoding="utf-8"
    )
    (run_directory / "layer2.json").write_text(
        json.dumps({"metadata": manifest, "records": [{"code": "603505"}]}),
        encoding="utf-8",
    )
    record = record or layer3_record(
        status=status,
        rank=1 if status == "complete" else None,
    )
    (fundamental / "layer3.json").write_text(
        json.dumps(
            {
                "metadata": {
                    "run_id": run_id,
                    "status": status,
                    "config_version": "fundamental-layer3-v1.0",
                },
                "records": [record],
            }
        ),
        encoding="utf-8",
    )
    (fundamental / "financial_quant.json").write_text(
        json.dumps({"records": [{"code": record["code"]}]}),
        encoding="utf-8",
    )
    runs = output_directory / "runs"
    (runs / "latest_full_market.json").write_text(
        json.dumps({"run_id": run_id, "end_date": market_date}),
        encoding="utf-8",
    )
    return run_directory


class DailyReportTests(unittest.TestCase):
    def test_report_cli_generates_daily_and_weekly_centers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            prepare_run(output)

            code = report_main(
                ["--run-id", RUN_ID, "--output-dir", str(output)]
            )

            self.assertEqual(code, 0)
            self.assertTrue(
                (output / "reports" / "daily" / "20260911" / "report.json").is_file()
            )
            self.assertTrue(
                (output / "reports" / "weekly" / "2026-W37" / "report.json").is_file()
            )

    def test_generates_complete_json_and_markdown_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_directory = prepare_run(Path(directory) / "output")
            json_path, markdown_path, report = generate_daily_report(run_directory)

            self.assertEqual(report["metadata"]["status"], "complete")
            self.assertEqual(
                report["metadata"]["schema_version"],
                "daily-research-report-v3",
            )
            self.assertEqual(report["metadata"]["layer3_counts"]["complete"], 1)
            self.assertEqual(report["metadata"]["focus_counts"]["KEY_FOCUS"], 1)
            self.assertTrue(json_path.is_file())
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("A股上升周期日报", markdown)
            self.assertIn("30秒结论", markdown)
            self.assertIn("筛选漏斗", markdown)
            self.assertIn("重点关注", markdown)
            self.assertIn("证据索引", markdown)
            self.assertIn("https://example.com/filing", markdown)
            self.assertIn("603505", markdown)
            self.assertIn("76.2", markdown)
            self.assertIn("不构成投资建议", markdown)
            output = run_directory.parents[1]
            self.assertTrue(
                (output / "reports" / "daily" / "20260911" / "report.md").is_file()
            )
            self.assertTrue(
                (output / "reports" / "latest" / "daily-qq.txt").is_file()
            )

    def test_pending_research_produces_partial_report_without_fake_score(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_directory = prepare_run(
                Path(directory) / "output",
                status="pending",
            )
            _, markdown_path, report = generate_daily_report(run_directory)

            self.assertEqual(report["metadata"]["status"], "partial")
            self.assertEqual(report["metadata"]["layer3_counts"]["pending"], 1)
            self.assertIn("待研究", markdown_path.read_text(encoding="utf-8"))
            self.assertIsNone(report["records"][0]["final_score"])

    def test_compares_rank_score_and_focus_status_with_previous_day(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            previous_record = layer3_record()
            previous_record["rank"] = 3
            previous_record["final_score"] = 69.0
            previous_record["focus_status"] = "FOLLOW_UP"
            previous_run = prepare_run(
                output,
                run_id="20260910-previous",
                market_date="20260910",
                record=previous_record,
            )
            generate_daily_report(previous_run)

            current_run = prepare_run(
                output,
                run_id=RUN_ID,
                market_date="20260911",
            )
            _, markdown_path, report = generate_daily_report(current_run)

            comparison = report["records"][0]["comparison"]
            self.assertEqual(report["changes"]["previous_as_of_date"], "20260910")
            self.assertEqual(comparison["rank_change"], 2)
            self.assertEqual(comparison["final_score_change"], 7.25)
            self.assertTrue(comparison["focus_status_changed"])
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("排名+2", markdown)
            self.assertIn("持续跟踪 → 重点关注", markdown)

    def test_follow_up_candidate_shows_gap_to_key_focus_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            record = layer3_record()
            record["focus_status"] = "FOLLOW_UP"
            record["final_score"] = 74.4
            run_directory = prepare_run(output, record=record)

            _, markdown_path, report = generate_daily_report(run_directory)

            gap = report["records"][0]["score_breakdown"]["threshold_gap"]
            self.assertAlmostEqual(gap["key_focus"], 0.6)
            self.assertEqual(gap["next_level"], "KEY_FOCUS")
            self.assertIn(
                "距重点关注0.6分",
                markdown_path.read_text(encoding="utf-8"),
            )


class DailyPipelineTests(unittest.TestCase):
    def test_runs_all_four_stages_and_records_complete_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            run_directory = prepare_run(output)
            generate_daily_report(run_directory)
            commands: list[list[str]] = []

            def runner(command: list[str]) -> int:
                commands.append(command)
                return 0

            pipeline = DailyPipeline(
                Path(directory) / "market.db",
                output,
                runner=runner,
            )
            return_code, state = pipeline.run()

            self.assertEqual(return_code, 0)
            self.assertEqual(state["status"], "complete")
            self.assertEqual(
                [state["stages"][name]["status"] for name in state["stages"]],
                ["success", "success", "success", "success"],
            )
            self.assertEqual(len(commands), 4)
            self.assertIn("app.cli.daily", commands[0])
            self.assertIn("app.cli.fundamentals", commands[1])
            self.assertEqual(commands[2][1:3], ["agent", "exec"])
            self.assertIn("app.cli.report", commands[3])
            self.assertTrue(pipeline.state_path.is_file())

    def test_resume_retries_research_and_regenerates_report_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            run_directory = prepare_run(output, status="pending")
            generate_daily_report(run_directory)
            first_commands: list[list[str]] = []

            def first_runner(command: list[str]) -> int:
                first_commands.append(command)
                if len(command) > 2 and command[1:3] == ["agent", "exec"]:
                    return 1
                return 0

            pipeline = DailyPipeline(
                Path(directory) / "market.db",
                output,
                runner=first_runner,
            )
            first_code, first_state = pipeline.run()
            self.assertEqual(first_code, 2)
            self.assertEqual(first_state["status"], "partial")
            self.assertEqual(first_state["stages"]["research"]["status"], "failed")

            second_commands: list[list[str]] = []

            def second_runner(command: list[str]) -> int:
                second_commands.append(command)
                if "app.cli.report" in command:
                    complete_report = json.loads(
                        (run_directory / "fundamental" / "daily_report.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    complete_report["metadata"]["status"] = "complete"
                    (run_directory / "fundamental" / "daily_report.json").write_text(
                        json.dumps(complete_report), encoding="utf-8"
                    )
                return 0

            resumed = DailyPipeline(
                Path(directory) / "market.db",
                output,
                runner=second_runner,
            )
            second_code, second_state = resumed.run(resume=True)

            self.assertEqual(second_code, 0)
            self.assertEqual(second_state["status"], "complete")
            self.assertEqual(len(second_commands), 2)
            self.assertEqual(second_commands[0][1:3], ["agent", "exec"])
            self.assertIn("app.cli.report", second_commands[1])

    def test_next_scheduled_run_skips_research_when_market_date_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            run_directory = prepare_run(output)
            generate_daily_report(run_directory)
            pipeline = DailyPipeline(
                Path(directory) / "market.db",
                output,
                runner=lambda command: 0,
            )
            first_code, first_state = pipeline.run()
            self.assertEqual(first_code, 0)
            self.assertEqual(first_state["status"], "complete")

            commands: list[list[str]] = []
            next_run_id = "20260911-next"

            def runner(command: list[str]) -> int:
                commands.append(command)
                if "app.cli.daily" in command:
                    next_run = output / "runs" / next_run_id
                    next_run.mkdir(parents=True)
                    (next_run / "manifest.json").write_text(
                        json.dumps(
                            {
                                "run_id": next_run_id,
                                "end_date": "20260911",
                                "status": "complete",
                            }
                        ),
                        encoding="utf-8",
                    )
                    (next_run / "layer1.json").write_text(
                        json.dumps({"records": []}),
                        encoding="utf-8",
                    )
                    (output / "runs" / "latest_full_market.json").write_text(
                        json.dumps(
                            {"run_id": next_run_id, "end_date": "20260911"}
                        ),
                        encoding="utf-8",
                    )
                return 0

            next_pipeline = DailyPipeline(
                Path(directory) / "market.db",
                output,
                runner=runner,
            )
            second_code, second_state = next_pipeline.run(resume=True)

            self.assertEqual(second_code, 0)
            self.assertEqual(len(commands), 1)
            self.assertIn("app.cli.daily", commands[0])
            self.assertEqual(second_state["run_id"], next_run_id)
            self.assertEqual(second_state["market_date_unchanged"], "20260911")
            self.assertEqual(second_state["reused_report_run_id"], RUN_ID)
            self.assertEqual(
                second_state["stages"]["research"]["status"],
                "skipped",
            )
            self.assertFalse(
                (output / "runs" / next_run_id / "fundamental" / "layer3.json").is_file()
            )
            self.assertEqual(
                report_main(["--output-dir", str(output)]),
                0,
            )


if __name__ == "__main__":
    unittest.main()
