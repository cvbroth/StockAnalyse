"""OpenClaw research execution backends and their project configuration."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..project_config import PROJECT_DIR, load_project_config


LOCAL_OPENCLAW = "local-openclaw"
DOCKER_OPENCLAW = "docker-openclaw"
DISABLED = "disabled"
RESEARCH_EXECUTORS = (LOCAL_OPENCLAW, DOCKER_OPENCLAW, DISABLED)


def _project_path(project_directory: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project_directory / path
    return path.resolve()


@dataclass(frozen=True)
class ResearchExecutionConfig:
    """Validated, secret-free configuration for one research executor."""

    executor: str = LOCAL_OPENCLAW
    openclaw_binary: str = "openclaw"
    docker_binary: str = "docker"
    compose_directory: Path | None = None
    compose_service: str = "openclaw-cli"
    compose_action: str = "run"
    compose_files: tuple[Path, ...] = ()
    container_openclaw_binary: str | None = None
    container_project_directory: str = "/workspace/stockanalyse"
    exchange_directory: Path | None = None
    container_exchange_directory: str = "/research-exchange"

    def __post_init__(self) -> None:
        if self.executor not in RESEARCH_EXECUTORS:
            raise ValueError(f"未知研究执行器：{self.executor}")
        if self.compose_action not in {"run", "exec"}:
            raise ValueError("compose_action 只能是 run 或 exec")
        if not self.compose_service.strip():
            raise ValueError("compose_service 不能为空")
        for label, value in (
            ("container_project_directory", self.container_project_directory),
            ("container_exchange_directory", self.container_exchange_directory),
        ):
            if not value.startswith("/") or "\x00" in value:
                raise ValueError(f"{label} 必须是容器内绝对路径")

    @property
    def is_disabled(self) -> bool:
        return self.executor == DISABLED

    @property
    def uses_boundary_exchange(self) -> bool:
        return self.executor == DOCKER_OPENCLAW

    def public_record(self) -> dict[str, Any]:
        """Return a stable, secret-free record suitable for state files."""

        if self.executor == DISABLED:
            return {"executor": self.executor}
        if self.executor == LOCAL_OPENCLAW:
            return {
                "executor": self.executor,
                "openclaw_binary": self.openclaw_binary,
            }
        return {
            "executor": self.executor,
            "docker_binary": self.docker_binary,
            "compose_directory": (
                str(self.compose_directory) if self.compose_directory else None
            ),
            "compose_service": self.compose_service,
            "compose_action": self.compose_action,
            "compose_files": [str(path) for path in self.compose_files],
            "container_openclaw_binary": self.container_openclaw_binary,
            "container_project_directory": self.container_project_directory,
            "exchange_directory": (
                str(self.exchange_directory) if self.exchange_directory else None
            ),
            "container_exchange_directory": self.container_exchange_directory,
        }

    def build_agent_command(self, run_id: str) -> list[str]:
        """Build an argv list without invoking a shell."""

        if self.executor == DISABLED:
            raise RuntimeError("研究执行器已禁用")
        if self.executor == LOCAL_OPENCLAW:
            binary = shutil.which(self.openclaw_binary) or self.openclaw_binary
            return [
                binary,
                "agent",
                "exec",
                f"/a-share-fundamental --run-id {run_id} --resume",
                "--cwd",
                str(PROJECT_DIR),
                "--timeout",
                "0",
            ]

        if self.compose_directory is None:
            raise RuntimeError(
                "docker-openclaw 需要配置 research_execution.compose_directory"
            )
        if self.exchange_directory is None:
            raise RuntimeError("docker-openclaw 缺少研究交换目录")

        command = [
            self.docker_binary,
            "compose",
            "--project-directory",
            str(self.compose_directory),
        ]
        for compose_file in self.compose_files:
            command.extend(["-f", str(compose_file)])
        command.append(self.compose_action)
        if self.compose_action == "run":
            command.extend(["-T", "--rm", self.compose_service])
        else:
            command.extend(["-T", self.compose_service])
        container_binary = self.container_openclaw_binary
        if self.compose_action == "exec" and not container_binary:
            container_binary = "openclaw"
        if container_binary:
            command.append(container_binary)
        command.extend(
            [
                "agent",
                "exec",
                (
                    f"/a-share-fundamental --boundary-mode --run-id {run_id} "
                    f"--exchange-root {self.container_exchange_directory} --resume"
                ),
                "--cwd",
                self.container_project_directory,
                "--timeout",
                "0",
            ]
        )
        return command


def resolve_research_execution(
    output_directory: Path,
    *,
    executor: str | None = None,
    compose_directory: Path | None = None,
    compose_service: str | None = None,
    compose_action: str | None = None,
    exchange_directory: Path | None = None,
    project_directory: Path = PROJECT_DIR,
    config_path: Path | None = None,
) -> tuple[ResearchExecutionConfig, str]:
    """Resolve CLI, environment, local project config, then safe defaults."""

    project_directory = project_directory.expanduser().resolve()
    project_config = load_project_config(project_directory, config_path)
    raw = project_config.get("research_execution", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RuntimeError("project.json 的 research_execution 必须是JSON对象")

    selected_executor = (
        executor
        or os.environ.get("A_SHARE_RESEARCH_EXECUTOR")
        or raw.get("executor")
        or LOCAL_OPENCLAW
    )
    source = (
        "命令行"
        if executor
        else "环境变量"
        if os.environ.get("A_SHARE_RESEARCH_EXECUTOR")
        else "项目配置"
        if raw.get("executor")
        else "兼容默认值"
    )

    raw_compose_directory = (
        compose_directory
        or os.environ.get("OPENCLAW_COMPOSE_DIR")
        or raw.get("compose_directory")
    )
    resolved_compose_directory = (
        _project_path(project_directory, raw_compose_directory)
        if raw_compose_directory
        else None
    )
    raw_exchange_directory = (
        exchange_directory
        or os.environ.get("A_SHARE_RESEARCH_EXCHANGE_DIR")
        or raw.get("exchange_directory")
        or output_directory / "openclaw_exchange"
    )
    resolved_exchange_directory = _project_path(
        project_directory, raw_exchange_directory
    )
    raw_compose_files = raw.get("compose_files", [])
    if not isinstance(raw_compose_files, list) or any(
        not isinstance(item, str) for item in raw_compose_files
    ):
        raise RuntimeError("research_execution.compose_files 必须是字符串数组")
    resolved_compose_files = tuple(
        _project_path(resolved_compose_directory or project_directory, item)
        for item in raw_compose_files
    )
    container_binary = raw.get("container_openclaw_binary")
    if container_binary is not None:
        container_binary = str(container_binary).strip() or None

    settings = ResearchExecutionConfig(
        executor=str(selected_executor),
        openclaw_binary=str(raw.get("openclaw_binary", "openclaw")),
        docker_binary=str(raw.get("docker_binary", "docker")),
        compose_directory=resolved_compose_directory,
        compose_service=(
            compose_service
            or os.environ.get("OPENCLAW_COMPOSE_SERVICE")
            or str(raw.get("compose_service", "openclaw-cli"))
        ),
        compose_action=compose_action or str(raw.get("compose_action", "run")),
        compose_files=resolved_compose_files,
        container_openclaw_binary=container_binary,
        container_project_directory=str(
            raw.get("container_project_directory", "/workspace/stockanalyse")
        ),
        exchange_directory=resolved_exchange_directory,
        container_exchange_directory=str(
            raw.get("container_exchange_directory", "/research-exchange")
        ),
    )
    return settings, source
