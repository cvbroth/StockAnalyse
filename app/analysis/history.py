"""分析运行快照、缓存和最新成功运行指针。"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .outputs import json_safe, write_json


RUN_ID_PATTERN = re.compile(r"^[0-9A-Za-z._-]+$")


def create_run_id(end_date: str) -> str:
    suffix = datetime.now().astimezone().strftime("%H%M%S%f")
    return f"{end_date}-{suffix}"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(json_safe(payload), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _layer1_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in records:
        item = copy.deepcopy(record)
        item.pop("quality", None)
        item.pop("transition", None)
        item.pop("newly_5of5", None)
        result.append(item)
    return result


def write_run_snapshot(
    output_dir: Path,
    run_id: str,
    records: list[dict[str, Any]],
    metadata: dict[str, Any],
    update_latest: bool,
) -> Path:
    runs_dir = output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    final_dir = runs_dir / run_id
    if final_dir.exists():
        raise RuntimeError(f"运行快照已存在：{run_id}")
    temporary_dir = Path(tempfile.mkdtemp(prefix=".tmp-run-", dir=runs_dir))
    try:
        layer1 = _layer1_records(records)
        layer2 = [
            copy.deepcopy(record)
            for record in records
            if record.get("base_filters", {}).get("passed")
            and int(record.get("technical_score", 0)) >= 4
        ]
        transitions = [
            copy.deepcopy(record)
            for record in records
            if record.get("transition", {}).get("status")
            not in {None, "unchanged", "still_5of5"}
            and int(record.get("technical_score", 0)) >= 3
        ]
        manifest = {
            **metadata,
            "run_id": run_id,
            "status": "complete",
            "layer1_cached_count": len(layer1),
            "layer2_count": len(layer2),
            "transition_count": len(transitions),
        }
        write_json(temporary_dir / "manifest.json", manifest)
        write_json(
            temporary_dir / "layer1.json",
            {"metadata": manifest, "records": layer1},
        )
        write_json(
            temporary_dir / "layer2.json",
            {"metadata": manifest, "records": layer2},
        )
        write_json(
            temporary_dir / "transitions.json",
            {"metadata": manifest, "records": transitions},
        )
        temporary_dir.replace(final_dir)
    except Exception:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise

    if update_latest:
        _atomic_json(
            runs_dir / "latest_full_market.json",
            {"run_id": run_id, "end_date": metadata.get("end_date")},
        )
    return final_dir


def _validate_run_id(run_id: str) -> str:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise RuntimeError(f"运行编号格式无效：{run_id}")
    return run_id


def load_run_snapshot(
    output_dir: Path,
    run_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    safe_run_id = _validate_run_id(run_id)
    run_dir = output_dir / "runs" / safe_run_id
    manifest_path = run_dir / "manifest.json"
    layer1_path = run_dir / "layer1.json"
    if not manifest_path.is_file() or not layer1_path.is_file():
        raise RuntimeError(f"找不到完整运行快照：{safe_run_id}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload = json.loads(layer1_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"运行快照读取失败：{safe_run_id}：{exc}") from exc
    records = payload.get("records")
    if manifest.get("status") != "complete" or not isinstance(records, list):
        raise RuntimeError(f"运行快照不完整：{safe_run_id}")
    return manifest, records


def load_run_layer2(
    output_dir: Path,
    run_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    safe_run_id = _validate_run_id(run_id)
    run_dir = output_dir / "runs" / safe_run_id
    manifest_path = run_dir / "manifest.json"
    layer2_path = run_dir / "layer2.json"
    if not manifest_path.is_file() or not layer2_path.is_file():
        raise RuntimeError(f"找不到第二层运行结果：{safe_run_id}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload = json.loads(layer2_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"第二层运行结果读取失败：{safe_run_id}：{exc}") from exc
    records = payload.get("records")
    if manifest.get("status") != "complete" or not isinstance(records, list):
        raise RuntimeError(f"第二层运行结果不完整：{safe_run_id}")
    return manifest, records


def load_latest_full_market(
    output_dir: Path,
) -> tuple[str | None, list[dict[str, Any]]]:
    pointer = output_dir / "runs" / "latest_full_market.json"
    if not pointer.is_file():
        return None, []
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        run_id = str(payload["run_id"])
        _, records = load_run_snapshot(output_dir, run_id)
    except (OSError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
        raise RuntimeError(f"最新全市场运行指针损坏：{pointer}：{exc}") from exc
    return run_id, records


def find_latest_reportable_run(output_dir: Path) -> str | None:
    """查找最近一个具备完整Layer1/2和Layer3输入的运行快照。

    最新全市场指针只表示技术扫描已完成。同一交易日重复扫描时，流水线可以复用
    上一次研究报告，因此该指针指向的运行不一定包含Layer3结果。
    """

    runs_directory = output_dir.expanduser().resolve() / "runs"
    if not runs_directory.is_dir():
        return None
    candidates: list[tuple[str, str]] = []
    for run_directory in runs_directory.iterdir():
        if not run_directory.is_dir() or not RUN_ID_PATTERN.fullmatch(run_directory.name):
            continue
        required = (
            run_directory / "manifest.json",
            run_directory / "layer1.json",
            run_directory / "layer2.json",
            run_directory / "fundamental" / "layer3.json",
        )
        if not all(path.is_file() for path in required):
            continue
        try:
            manifest = json.loads(required[0].read_text(encoding="utf-8"))
            layer3 = json.loads(required[3].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict) or manifest.get("status") != "complete":
            continue
        if not isinstance(layer3, dict) or not isinstance(layer3.get("records"), list):
            continue
        layer3_metadata = layer3.get("metadata")
        if not isinstance(layer3_metadata, dict):
            continue
        if str(manifest.get("run_id", "")) != run_directory.name:
            continue
        if str(layer3_metadata.get("run_id", "")) != run_directory.name:
            continue
        end_date = str(manifest.get("end_date", "")).replace("-", "")
        if len(end_date) != 8 or not end_date.isdigit():
            continue
        candidates.append((end_date, run_directory.name))
    return max(candidates)[1] if candidates else None
