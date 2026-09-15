from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.research.execution import (
    DOCKER_OPENCLAW,
    LOCAL_OPENCLAW,
    ResearchExecutionConfig,
    resolve_research_execution,
)
from app.research.workspace import ResearchWorkspace
from app.services.runtime_fingerprint import build_runtime_fingerprint


class ResearchExecutionConfigTests(unittest.TestCase):
    def test_missing_configuration_preserves_local_openclaw_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict("os.environ", {}, clear=True):
                settings, source = resolve_research_execution(
                    root / "output",
                    project_directory=root,
                    config_path=root / "config" / "project.json",
                )

            self.assertEqual(settings.executor, LOCAL_OPENCLAW)
            self.assertEqual(source, "兼容默认值")
            command = settings.build_agent_command("20260915-test")
            self.assertEqual(command[1:3], ["agent", "exec"])
            self.assertIn("--run-id 20260915-test --resume", command[3])

    def test_docker_command_uses_argv_and_boundary_mode(self) -> None:
        settings = ResearchExecutionConfig(
            executor=DOCKER_OPENCLAW,
            compose_directory=Path("/srv/openclaw"),
            compose_service="openclaw-cli",
            exchange_directory=Path("/srv/stock/output/openclaw_exchange"),
        )

        command = settings.build_agent_command("20260915-test")

        self.assertEqual(
            command[:5],
            [
                "docker",
                "compose",
                "--project-directory",
                str(Path("/srv/openclaw")),
                "run",
            ],
        )
        self.assertIn("openclaw-cli", command)
        prompt = command[command.index("exec") + 1]
        self.assertIn("--boundary-mode", prompt)
        self.assertIn("--exchange-root /research-exchange", prompt)
        self.assertNotIn("market.db", " ".join(command))

    def test_project_config_selects_docker_and_resolves_relative_exchange(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config" / "project.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "research_execution": {
                            "executor": "docker-openclaw",
                            "compose_directory": "/srv/openclaw",
                            "exchange_directory": "output/exchange",
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict("os.environ", {}, clear=True):
                settings, source = resolve_research_execution(
                    root / "output",
                    project_directory=root,
                    config_path=config_path,
                )

            self.assertEqual(source, "项目配置")
            self.assertEqual(settings.executor, DOCKER_OPENCLAW)
            self.assertEqual(
                settings.exchange_directory,
                (root / "output" / "exchange").resolve(),
            )


class ResearchBoundaryWorkspaceTests(unittest.TestCase):
    def test_exchange_separates_untrusted_io_from_validated_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_directory = root / "output" / "runs" / "20260915-test"
            exchange = root / "exchange"

            workspace = ResearchWorkspace(run_directory, exchange)

            self.assertEqual(
                workspace.work_items_directory,
                exchange.resolve() / "work_items" / "20260915-test",
            )
            self.assertEqual(
                workspace.inbox_directory,
                exchange.resolve() / "inbox" / "20260915-test",
            )
            self.assertEqual(
                workspace.results_directory,
                run_directory.resolve() / "fundamental" / "research" / "results",
            )

    def test_fingerprint_changes_when_executor_changes(self) -> None:
        local = build_runtime_fingerprint({"executor": LOCAL_OPENCLAW})
        docker = build_runtime_fingerprint({"executor": DOCKER_OPENCLAW})

        self.assertNotEqual(local["sha256"], docker["sha256"])
        self.assertEqual(len(local["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
