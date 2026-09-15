"""项目级运行配置：统一当前数据库和输出目录。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONFIG_VERSION = 1
APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DEFAULT_CONFIG_PATH = PROJECT_DIR / "config" / "project.json"
DEFAULT_DB_PATH = PROJECT_DIR / "data" / "market.db"
DEFAULT_FUNDAMENTAL_DB_PATH = PROJECT_DIR / "data" / "fundamentals.db"
DEFAULT_OUTPUT_PATH = PROJECT_DIR / "output"


def _resolve_project_path(project_dir: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project_dir / path
    return path.resolve()


def _portable_path(project_dir: Path, path: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(project_dir.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def load_project_config(
    project_dir: Path = PROJECT_DIR,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """读取项目配置；文件不存在时返回空配置。"""

    path = (
        config_path or project_dir / "config" / "project.json"
    ).expanduser().resolve()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取项目配置 {path}：{exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"项目配置 {path} 的顶层必须是 JSON 对象")
    version = data.get("version", CONFIG_VERSION)
    if version != CONFIG_VERSION:
        raise RuntimeError(
            f"项目配置版本 {version!r} 不受支持，当前支持 {CONFIG_VERSION}"
        )
    return data


def resolve_database_path(
    command_line_value: Path | None,
    project_dir: Path = PROJECT_DIR,
    config_path: Path | None = None,
) -> tuple[Path, str]:
    """按命令行、项目配置、旧默认值的优先级选择数据库。"""

    if command_line_value is not None:
        return _resolve_project_path(project_dir, command_line_value), "命令行 --db"
    config = load_project_config(project_dir, config_path)
    configured = config.get("database")
    if configured:
        return _resolve_project_path(project_dir, str(configured)), "项目配置"
    return DEFAULT_DB_PATH.resolve(), "默认值"


def resolve_output_path(
    command_line_value: Path | None,
    project_dir: Path = PROJECT_DIR,
    config_path: Path | None = None,
) -> tuple[Path, str]:
    """按命令行、项目配置、旧默认值的优先级选择输出目录。"""

    if command_line_value is not None:
        return _resolve_project_path(project_dir, command_line_value), "命令行 --output-dir"
    config = load_project_config(project_dir, config_path)
    configured = config.get("output_directory")
    if configured:
        return _resolve_project_path(project_dir, str(configured)), "项目配置"
    return DEFAULT_OUTPUT_PATH.resolve(), "默认值"


def resolve_fundamental_database_path(
    command_line_value: Path | None,
    project_dir: Path = PROJECT_DIR,
    config_path: Path | None = None,
) -> tuple[Path, str]:
    """选择独立基本面缓存库，不复用全市场行情库。"""

    if command_line_value is not None:
        return (
            _resolve_project_path(project_dir, command_line_value),
            "命令行 --fundamental-db",
        )
    config = load_project_config(project_dir, config_path)
    configured = config.get("fundamental_database")
    if configured:
        return _resolve_project_path(project_dir, str(configured)), "项目配置"
    return (project_dir / "data" / "fundamentals.db").resolve(), "默认值"


def save_project_config(
    database: Path,
    data_provider: str,
    output_directory: Path | None = None,
    fundamental_database: Path | None = None,
    project_dir: Path = PROJECT_DIR,
    config_path: Path | None = None,
) -> Path:
    """原子写入当前项目配置，供三个命令入口共同使用。"""

    if data_provider not in {"tx", "tushare"}:
        raise ValueError(f"不能保存未知数据源：{data_provider}")
    current = load_project_config(project_dir, config_path)
    if output_directory is None:
        configured_output = current.get("output_directory", "output")
        output_directory = _resolve_project_path(project_dir, configured_output)
    if fundamental_database is None:
        configured_fundamental = current.get(
            "fundamental_database", "data/fundamentals.db"
        )
        fundamental_database = _resolve_project_path(
            project_dir, configured_fundamental
        )
    payload = {
        **current,
        "version": CONFIG_VERSION,
        "database": _portable_path(project_dir, database),
        "fundamental_database": _portable_path(
            project_dir, fundamental_database
        ),
        "output_directory": _portable_path(project_dir, output_directory),
        "data_provider": data_provider,
    }
    path = (
        config_path or project_dir / "config" / "project.json"
    ).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path
