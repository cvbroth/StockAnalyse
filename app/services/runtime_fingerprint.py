"""Deterministic code/config/skill fingerprint for reproducible pipelines."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from ..project_config import PROJECT_DIR


FINGERPRINT_SCHEMA_VERSION = "pipeline-runtime-fingerprint-v1"


def _iter_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return ()
    return (
        path
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and "__pycache__" not in path.parts
    )


def _tree_digest(project_directory: Path, roots: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for root in roots:
        for path in _iter_files(root):
            try:
                relative = path.relative_to(project_directory).as_posix()
            except ValueError:
                relative = str(path)
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def build_runtime_fingerprint(
    research_execution: dict[str, Any],
    project_directory: Path = PROJECT_DIR,
) -> dict[str, Any]:
    """Hash analysis code, analysis configuration, skill and executor config."""

    project_directory = project_directory.expanduser().resolve()
    components = {
        "application": _tree_digest(
            project_directory,
            [project_directory / "app"],
        ),
        "analysis_config": _tree_digest(
            project_directory,
            [project_directory / "config" / "analysis"],
        ),
        "research_skill": _tree_digest(
            project_directory,
            [project_directory / "skills" / "a-share-fundamental"],
        ),
    }
    canonical = json.dumps(
        {
            "schema_version": FINGERPRINT_SCHEMA_VERSION,
            "components": components,
            "research_execution": research_execution,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "components": components,
        "research_execution": research_execution,
    }
