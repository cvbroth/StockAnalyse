"""报告发布包：稳定归档、最新版指针和OpenClaw只读出口。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from .fundamental_sync import write_json_atomic


PUBLICATION_SCHEMA_VERSION = "report-publication-v1"
PRINT_LATEST_SCRIPT = """#!/usr/bin/env sh
set -eu

kind="${1:-}"
report_directory="${A_SHARE_REPORT_DIR:-/reports}"

case "${kind}" in
  daily)
    expected_period="$(date +%Y%m%d)"
    ;;
  weekly)
    expected_period="$(date +%G-W%V)"
    ;;
  *)
    echo "用法：print-latest.sh daily|weekly" >&2
    exit 2
    ;;
esac

period_file="${report_directory}/latest/${kind}-period.txt"
message_file="${report_directory}/latest/${kind}-qq.txt"

if [ ! -s "${period_file}" ] || [ ! -s "${message_file}" ]; then
  echo "NO_REPLY"
  exit 0
fi

actual_period="$(tr -d '\r\n' < "${period_file}")"
if [ "${actual_period}" != "${expected_period}" ]; then
  echo "NO_REPLY"
  exit 0
fi

cat "${message_file}"
"""


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content.rstrip())
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _content_hash(report: dict[str, Any], markdown: str, qq_text: str) -> str:
    digest = hashlib.sha256()
    canonical_report = deepcopy(report)
    metadata = canonical_report.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("generated_at", None)
    digest.update(
        json.dumps(
            canonical_report,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    digest.update(markdown.encode("utf-8"))
    digest.update(qq_text.encode("utf-8"))
    return digest.hexdigest()


def output_directory_from_run(run_directory: Path) -> Path:
    resolved = run_directory.expanduser().resolve()
    if resolved.parent.name != "runs":
        raise RuntimeError(f"运行目录不位于 output/runs 下：{resolved}")
    return resolved.parent.parent


def write_publication_bundle(
    output_directory: Path,
    kind: str,
    period: str,
    report: dict[str, Any],
    markdown: str,
    qq_text: str,
) -> dict[str, Path]:
    """归档一份报告，并原子更新供OpenClaw读取的最新版文件。"""

    if kind not in {"daily", "weekly"}:
        raise ValueError(f"未知报告类型：{kind}")
    if not period or "/" in period or "\\" in period:
        raise ValueError(f"报告周期格式无效：{period!r}")

    root = output_directory.expanduser().resolve() / "reports"
    bundle = root / kind / period
    latest = root / "latest"
    bundle.mkdir(parents=True, exist_ok=True)
    latest.mkdir(parents=True, exist_ok=True)

    report_path = bundle / "report.json"
    markdown_path = bundle / "report.md"
    qq_path = bundle / "qq.txt"
    publication_path = bundle / "publication.json"
    content_hash = _content_hash(report, markdown, qq_text)

    previous_destinations: dict[str, Any] = {}
    if publication_path.is_file():
        try:
            previous = json.loads(publication_path.read_text(encoding="utf-8"))
            if previous.get("content_sha256") == content_hash:
                value = previous.get("destinations")
                if isinstance(value, dict):
                    previous_destinations = value
        except (OSError, json.JSONDecodeError):
            previous_destinations = {}

    write_json_atomic(report_path, report)
    write_text_atomic(markdown_path, markdown)
    write_text_atomic(qq_path, qq_text)
    write_json_atomic(
        publication_path,
        {
            "schema_version": PUBLICATION_SCHEMA_VERSION,
            "report_id": f"{kind}-{period}",
            "kind": kind,
            "period": period,
            "report_status": report.get("metadata", {}).get("status", "unknown"),
            "content_sha256": content_hash,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "destinations": previous_destinations,
            "artifacts": {
                "json": "report.json",
                "markdown": "report.md",
                "qq": "qq.txt",
            },
        },
    )

    latest_period_path = latest / f"{kind}-period.txt"
    try:
        latest_period = latest_period_path.read_text(encoding="utf-8").strip()
    except OSError:
        latest_period = ""
    if not latest_period or period >= latest_period:
        write_json_atomic(latest / f"{kind}.json", report)
        write_text_atomic(latest / f"{kind}.md", markdown)
        write_text_atomic(latest / f"{kind}-qq.txt", qq_text)
        write_text_atomic(latest_period_path, period)
    script_path = root / "print-latest.sh"
    write_text_atomic(script_path, PRINT_LATEST_SCRIPT)
    try:
        script_path.chmod(0o755)
    except OSError:
        pass

    return {
        "directory": bundle,
        "json": report_path,
        "markdown": markdown_path,
        "qq": qq_path,
        "publication": publication_path,
        "latest": latest,
        "print_script": script_path,
    }
