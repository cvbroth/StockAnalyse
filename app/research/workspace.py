"""研究请求工作区、逐股结果和批量结果文件管理。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ..analysis.fundamentals import (
    FUNDAMENTAL_RESEARCH_SCHEMA_VERSION,
    FUNDAMENTAL_RESEARCH_SCHEMA_VERSIONS,
)
from ..fundamentals.models import normalize_date
from ..services.fundamental_sync import write_json_atomic


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label}读取失败：{path}：{exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label}必须是JSON对象：{path}")
    return payload


def load_research_request(
    path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """读取并校验由基本面命令生成的不可变研究任务。"""

    payload = _read_json(path, "研究请求")
    metadata = payload.get("metadata")
    records = payload.get("records")
    if not isinstance(metadata, dict) or not isinstance(records, list):
        raise RuntimeError("研究请求必须包含 metadata 对象和 records 数组")
    if metadata.get("schema_version") not in FUNDAMENTAL_RESEARCH_SCHEMA_VERSIONS:
        raise RuntimeError("研究请求 schema_version 不兼容")
    run_id = str(metadata.get("run_id", ""))
    if not run_id:
        raise RuntimeError("研究请求缺少 run_id")
    cutoff = normalize_date(
        str(metadata.get("as_of_date", "")),
        "metadata.as_of_date",
    )
    if metadata.get("record_count") != len(records):
        raise RuntimeError("研究请求 record_count 与实际记录数不一致")
    codes: set[str] = set()
    request_schema = str(metadata.get("schema_version"))
    for raw in records:
        if not isinstance(raw, dict):
            raise RuntimeError("研究请求 records 的每一项必须是对象")
        code = str(raw.get("code", "")).zfill(6)
        input_hash = str(raw.get("input_hash", ""))
        if len(code) != 6 or not code.isdigit():
            raise RuntimeError(f"研究请求股票代码无效：{code!r}")
        if code in codes:
            raise RuntimeError(f"研究请求包含重复股票：{code}")
        if str(raw.get("run_id", "")) != run_id:
            raise RuntimeError(f"{code} 的运行编号与研究请求元数据不一致")
        if normalize_date(str(raw.get("as_of_date", "")), "as_of_date") != cutoff:
            raise RuntimeError(f"{code} 的截止日期与研究请求元数据不一致")
        if len(input_hash) != 64 or any(
            character not in "0123456789abcdef" for character in input_hash
        ):
            raise RuntimeError(f"{code} 的 input_hash 无效")
        result_contract = raw.get("result_contract")
        if not isinstance(result_contract, dict):
            raise RuntimeError(f"{code} 的研究请求缺少 result_contract")
        if str(result_contract.get("schema_version", "")) != request_schema:
            raise RuntimeError(f"{code} 的研究契约版本与请求元数据不一致")
        codes.add(code)
    return {**metadata, "as_of_date": cutoff}, records


def load_research_templates(path: Path) -> dict[str, dict[str, Any]]:
    payload = _read_json(path, "研究结果模板")
    records = payload.get("records")
    if not isinstance(records, list):
        raise RuntimeError("研究结果模板必须包含 records 数组")
    templates: dict[str, dict[str, Any]] = {}
    for raw in records:
        if not isinstance(raw, dict):
            raise RuntimeError("研究结果模板的每一项必须是对象")
        code = str(raw.get("code", "")).zfill(6)
        if code in templates:
            raise RuntimeError(f"研究结果模板包含重复股票：{code}")
        templates[code] = raw
    return templates


class ResearchWorkspace:
    """一个运行快照内的研究工作区；不修改Layer1/2和财务量化文件。"""

    def __init__(self, run_directory: Path) -> None:
        self.run_directory = run_directory.expanduser().resolve()
        self.fundamental_directory = self.run_directory / "fundamental"
        self.root = self.fundamental_directory / "research"
        self.work_items_directory = self.root / "work_items"
        self.inbox_directory = self.root / "inbox"
        self.results_directory = self.root / "results"
        self.summary_path = self.root / "execution_summary.json"
        self.aggregate_path = self.fundamental_directory / "research_results.json"

    def prepare(
        self,
        requests: Iterable[dict[str, Any]],
        templates: dict[str, dict[str, Any]],
        selected_codes: set[str],
    ) -> None:
        self.inbox_directory.mkdir(parents=True, exist_ok=True)
        self.results_directory.mkdir(parents=True, exist_ok=True)
        for request in requests:
            code = str(request["code"]).zfill(6)
            if code not in selected_codes:
                continue
            template = templates.get(code)
            if template is None:
                raise RuntimeError(f"研究结果模板缺少股票：{code}")
            if template.get("input_hash") != request.get("input_hash"):
                raise RuntimeError(f"{code} 的研究结果模板 input_hash 不匹配")
            item_directory = self.work_items_directory / code
            write_json_atomic(
                item_directory / "request.json",
                {
                    "metadata": {
                        "schema_version": (
                            (request.get("result_contract") or {}).get(
                                "schema_version"
                            )
                            or FUNDAMENTAL_RESEARCH_SCHEMA_VERSION
                        ),
                        "usage": "只读研究输入；不得修改input_hash或截止日期",
                    },
                    "record": request,
                },
            )
            write_json_atomic(
                item_directory / "result.template.json",
                template,
            )

    def result_path(self, code: str) -> Path:
        return self.results_directory / f"{str(code).zfill(6)}.json"

    def write_result(self, code: str, record: dict[str, Any]) -> Path:
        path = self.result_path(code)
        write_json_atomic(path, record)
        return path

    def write_aggregate(
        self,
        metadata: dict[str, Any],
        records: list[dict[str, Any]],
    ) -> Path:
        write_json_atomic(
            self.aggregate_path,
            {
                "metadata": {
                    "schema_version": metadata.get(
                        "schema_version",
                        FUNDAMENTAL_RESEARCH_SCHEMA_VERSION,
                    ),
                    "run_id": metadata["run_id"],
                    "as_of_date": metadata["as_of_date"],
                    "record_count": len(records),
                },
                "records": records,
            },
        )
        return self.aggregate_path
