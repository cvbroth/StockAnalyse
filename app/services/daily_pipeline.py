"""每日行情、筛选、基本面、OpenClaw研究和报告的可续跑流水线。"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..analysis.history import load_latest_full_market
from ..project_config import PROJECT_DIR
from ..research.execution import (
    DISABLED,
    DOCKER_OPENCLAW,
    ResearchExecutionConfig,
)
from .fundamental_sync import write_json_atomic
from .runtime_fingerprint import build_runtime_fingerprint


PIPELINE_SCHEMA_VERSION = "daily-pipeline-v1"
STAGE_NAMES = ("daily", "fundamentals", "research", "report")
CommandRunner = Callable[[list[str]], int]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _new_stage() -> dict[str, Any]:
    return {
        "status": "pending",
        "started_at": None,
        "finished_at": None,
        "return_code": None,
        "command": None,
    }


def _new_state(run_id: str | None = None) -> dict[str, Any]:
    created = _now()
    return {
        "schema_version": PIPELINE_SCHEMA_VERSION,
        "status": "pending",
        "run_id": run_id,
        "created_at": created,
        "updated_at": created,
        "stages": {name: _new_stage() for name in STAGE_NAMES},
    }


def _load_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"流水线状态读取失败：{path}：{exc}") from exc
    if payload.get("schema_version") != PIPELINE_SCHEMA_VERSION:
        raise RuntimeError("流水线状态版本不兼容")
    stages = payload.get("stages")
    if not isinstance(stages, dict) or any(
        name not in stages for name in STAGE_NAMES
    ):
        raise RuntimeError("流水线状态缺少阶段记录")
    return payload


def _is_terminal_state(state: dict[str, Any]) -> bool:
    if state.get("status") == "complete":
        return True
    return (
        state.get("status") == "partial"
        and state["stages"]["research"]["status"] in {"success", "skipped"}
        and state["stages"]["report"]["status"] == "success"
    )


def _run_market_date(output_directory: Path, run_id: str | None) -> str | None:
    if not run_id:
        return None
    path = output_directory / "runs" / run_id / "manifest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("end_date")
    return str(value) if value else None


def _default_runner(command: list[str]) -> int:
    return subprocess.run(command, cwd=PROJECT_DIR, check=False).returncode


class DailyPipeline:
    def __init__(
        self,
        database: Path,
        output_directory: Path,
        report_top_n: int = 10,
        runner: CommandRunner = _default_runner,
        research_execution: ResearchExecutionConfig | None = None,
    ) -> None:
        if report_top_n < 1:
            raise ValueError("report_top_n 必须至少为1")
        self.database = database.expanduser().resolve()
        self.output_directory = output_directory.expanduser().resolve()
        self.report_top_n = report_top_n
        self.runner = runner
        self.research_execution = (
            research_execution or ResearchExecutionConfig()
        )
        self.state_path = self.output_directory / "pipeline_state.json"

    def _write_state(self, state: dict[str, Any]) -> None:
        state["updated_at"] = _now()
        write_json_atomic(self.state_path, state)
        run_id = state.get("run_id")
        if run_id:
            write_json_atomic(
                self.output_directory
                / "runs"
                / str(run_id)
                / "fundamental"
                / "pipeline_state.json",
                state,
            )

    def _reset_downstream(self, state: dict[str, Any], stage_name: str) -> None:
        index = STAGE_NAMES.index(stage_name)
        for name in STAGE_NAMES[index + 1 :]:
            state["stages"][name] = _new_stage()

    def _run_stage(
        self,
        state: dict[str, Any],
        name: str,
        command: list[str],
    ) -> int:
        stage = state["stages"][name]
        stage.update(
            {
                "status": "running",
                "started_at": _now(),
                "finished_at": None,
                "return_code": None,
                "command": command,
            }
        )
        state["status"] = "running"
        self._write_state(state)
        try:
            return_code = int(self.runner(command))
        except (OSError, RuntimeError) as exc:
            stage["status"] = "failed"
            stage["finished_at"] = _now()
            stage["return_code"] = 127
            stage["error"] = str(exc)
            self._write_state(state)
            return 127
        stage["status"] = "success" if return_code == 0 else "failed"
        stage["finished_at"] = _now()
        stage["return_code"] = return_code
        stage.pop("error", None)
        self._write_state(state)
        return return_code

    def _resume_state(self, requested_run_id: str | None) -> dict[str, Any]:
        if not self.state_path.is_file():
            return _new_state(requested_run_id)
        state = _load_state(self.state_path)
        if _is_terminal_state(state):
            return _new_state(requested_run_id)
        if requested_run_id is not None and state.get("run_id") != requested_run_id:
            return _new_state(requested_run_id)
        return state

    def _run_boundary_research_stage(
        self,
        state: dict[str, Any],
        run_id: str,
    ) -> int:
        """Prepare and validate on the host; expose only exchange files to Docker."""

        exchange_directory = self.research_execution.exchange_directory
        if exchange_directory is None:
            raise RuntimeError("Docker研究执行器缺少交换目录")
        common = [
            "--run-id",
            run_id,
            "--output-dir",
            str(self.output_directory),
            "--exchange-dir",
            str(exchange_directory),
            "--resume",
        ]
        commands = (
            (
                "prepare",
                [sys.executable, "-m", "app.cli.research", *common],
            ),
            (
                "agent",
                self.research_execution.build_agent_command(run_id),
            ),
            (
                "validate",
                [sys.executable, "-m", "app.cli.research", *common],
            ),
        )
        stage = state["stages"]["research"]
        stage.update(
            {
                "status": "running",
                "started_at": _now(),
                "finished_at": None,
                "return_code": None,
                "command": commands[1][1],
                "steps": [],
            }
        )
        state["status"] = "running"
        self._write_state(state)
        agent_return_code = 0
        final_return_code = 0
        for step_name, command in commands:
            step = {
                "name": step_name,
                "status": "running",
                "started_at": _now(),
                "finished_at": None,
                "return_code": None,
                "command": command,
            }
            stage["steps"].append(step)
            self._write_state(state)
            try:
                return_code = int(self.runner(command))
                error = None
            except (OSError, RuntimeError) as exc:
                return_code = 127
                error = str(exc)
            step["return_code"] = return_code
            step["finished_at"] = _now()
            step["status"] = "success" if return_code == 0 else "failed"
            if error:
                step["error"] = error
            self._write_state(state)

            if step_name == "prepare" and return_code != 0:
                final_return_code = return_code
                break
            if step_name == "agent":
                agent_return_code = return_code
                final_return_code = return_code
                # Always validate after an agent failure so partial valid results survive.
                continue
            if step_name == "validate" and return_code != 0:
                final_return_code = agent_return_code or return_code

        stage["status"] = "success" if final_return_code == 0 else "failed"
        stage["finished_at"] = _now()
        stage["return_code"] = final_return_code
        if final_return_code == 127:
            failed_steps = [
                step for step in stage["steps"] if step.get("error")
            ]
            if failed_steps:
                stage["error"] = failed_steps[-1]["error"]
        else:
            stage.pop("error", None)
        self._write_state(state)
        return final_return_code

    def run(
        self,
        resume: bool = False,
        run_id: str | None = None,
        skip_research: bool = False,
    ) -> tuple[int, dict[str, Any]]:
        runtime_fingerprint = build_runtime_fingerprint(
            {
                **self.research_execution.public_record(),
                "database": str(self.database),
                "report_top_n": self.report_top_n,
            }
        )
        previous_state = (
            _load_state(self.state_path) if self.state_path.is_file() else None
        )
        previous_terminal_run_id = (
            str(previous_state.get("run_id"))
            if previous_state is not None
            and _is_terminal_state(previous_state)
            and previous_state.get("run_id")
            else None
        )
        state = (
            self._resume_state(run_id)
            if resume
            else _new_state(run_id)
        )
        state["runtime_fingerprint"] = runtime_fingerprint
        self._write_state(state)
        if run_id is not None and state["stages"]["daily"]["status"] == "pending":
            state["stages"]["daily"].update(
                {
                    "status": "skipped",
                    "finished_at": _now(),
                    "return_code": 0,
                    "command": None,
                    "reason": "使用已有运行编号，不更新行情或重跑技术筛选",
                }
            )
            self._write_state(state)

        if state["stages"]["daily"]["status"] not in {"success", "skipped"}:
            self._reset_downstream(state, "daily")
            daily_code = self._run_stage(
                state,
                "daily",
                [
                    sys.executable,
                    "-m",
                    "app.cli.daily",
                    "--db",
                    str(self.database),
                    "--output-dir",
                    str(self.output_directory),
                ],
            )
            if daily_code != 0:
                state["status"] = "failed"
                self._write_state(state)
                return daily_code, state
            latest_run_id, _ = load_latest_full_market(self.output_directory)
            if latest_run_id is None:
                state["status"] = "failed"
                state["stages"]["daily"]["status"] = "failed"
                state["stages"]["daily"]["error"] = (
                    "每日筛选成功后未找到最新全市场运行编号"
                )
                self._write_state(state)
                return 2, state
            state["run_id"] = latest_run_id
            self._write_state(state)

            previous_market_date = _run_market_date(
                self.output_directory,
                previous_terminal_run_id,
            )
            current_market_date = _run_market_date(
                self.output_directory,
                latest_run_id,
            )
            fingerprint_matches = (
                previous_state is not None
                and previous_state.get("runtime_fingerprint", {}).get("sha256")
                == runtime_fingerprint["sha256"]
            )
            if (
                previous_terminal_run_id is not None
                and previous_market_date is not None
                and current_market_date == previous_market_date
                and fingerprint_matches
            ):
                for name in ("fundamentals", "research", "report"):
                    state["stages"][name].update(
                        {
                            "status": "skipped",
                            "finished_at": _now(),
                            "return_code": 0,
                            "command": None,
                            "reason": "行情截止日期未变化，复用上一份研究报告",
                        }
                    )
                state["status"] = "complete"
                state["market_date_unchanged"] = current_market_date
                state["reused_report_run_id"] = previous_terminal_run_id
                self._write_state(state)
                return 0, state
            if (
                previous_terminal_run_id is not None
                and previous_market_date is not None
                and current_market_date == previous_market_date
                and not fingerprint_matches
            ):
                state["same_market_date_reuse_bypassed"] = (
                    "runtime_fingerprint_changed"
                )
                self._write_state(state)

        active_run_id = str(state.get("run_id") or "")
        if not active_run_id:
            raise RuntimeError("流水线没有可用运行编号")

        if state["stages"]["fundamentals"]["status"] != "success":
            self._reset_downstream(state, "fundamentals")
            fundamentals_code = self._run_stage(
                state,
                "fundamentals",
                [
                    sys.executable,
                    "-m",
                    "app.cli.fundamentals",
                    "--run-id",
                    active_run_id,
                    "--output-dir",
                    str(self.output_directory),
                ],
            )
            if fundamentals_code != 0:
                state["status"] = "failed"
                self._write_state(state)
                return fundamentals_code, state

        research_failed = False
        if skip_research or self.research_execution.executor == DISABLED:
            state["stages"]["research"].update(
                {
                    "status": "skipped",
                    "finished_at": _now(),
                    "return_code": 0,
                    "command": None,
                    "reason": (
                        "命令行要求跳过OpenClaw研究"
                        if skip_research
                        else "项目配置已禁用OpenClaw研究执行器"
                    ),
                }
            )
            self._write_state(state)
        elif state["stages"]["research"]["status"] != "success":
            self._reset_downstream(state, "research")
            if self.research_execution.executor == DOCKER_OPENCLAW:
                research_code = self._run_boundary_research_stage(
                    state,
                    active_run_id,
                )
            else:
                research_code = self._run_stage(
                    state,
                    "research",
                    self.research_execution.build_agent_command(active_run_id),
                )
            research_failed = research_code != 0

        if state["stages"]["report"]["status"] != "success":
            report_code = self._run_stage(
                state,
                "report",
                [
                    sys.executable,
                    "-m",
                    "app.cli.report",
                    "--run-id",
                    active_run_id,
                    "--output-dir",
                    str(self.output_directory),
                    "--top-n",
                    str(self.report_top_n),
                ],
            )
            if report_code != 0:
                state["status"] = "failed"
                self._write_state(state)
                return report_code, state

        report_path = (
            self.output_directory
            / "runs"
            / active_run_id
            / "fundamental"
            / "daily_report.json"
        )
        try:
            report_payload = json.loads(report_path.read_text(encoding="utf-8"))
            report_is_partial = (
                report_payload.get("metadata", {}).get("status") != "complete"
            )
        except (OSError, json.JSONDecodeError):
            report_is_partial = True
        if (
            skip_research
            or self.research_execution.executor == DISABLED
            or research_failed
            or report_is_partial
        ):
            state["status"] = "partial"
            self._write_state(state)
            return (2 if research_failed else 0), state
        state["status"] = "complete"
        self._write_state(state)
        return 0, state
