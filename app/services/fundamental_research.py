"""Layer3研究请求、外部结果校验和最终合并编排。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..analysis.fundamentals import (
    FUNDAMENTAL_RESEARCH_SCHEMA_VERSION,
    FUNDAMENTAL_RESEARCH_SCHEMA_VERSIONS,
    RESEARCH_QUALITY_FLAG_CODES,
    RESEARCH_RUBRIC_VERSION,
    RESEARCH_SKILL_VERSION,
    FundamentalResearchResult,
    compose_layer3_result,
    rank_layer3_results,
)
from ..fundamentals import FundamentalScoringConfig
from ..fundamentals.models import normalize_date
from .fundamental_sync import write_json_atomic


RESEARCH_QUESTIONS = (
    "最近两个季度的营收、利润和毛利率趋势如何，是否加速？",
    "经营现金流是否支持利润，异常变化的原因是什么？",
    "最近90天发生了哪些重要经营变化？",
    "行业价格、需求和库存处于什么方向？",
    "是否存在新订单、新产品、新产能、涨价、政策、并购或海外扩张催化？",
    "盈利预期是否可能上修，市场预期发生了什么边际变化？",
    "当前最大的三个风险是什么，是否存在应直接否决的红色风险？",
    "最终状态是改善、稳定、恶化还是无法判断？",
)


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _request_schema_version(request: dict[str, Any]) -> str:
    contract = request.get("result_contract")
    if not isinstance(contract, dict):
        return ""
    return str(contract.get("schema_version", ""))


def build_research_requests(
    financial_records: list[dict[str, Any]],
    run_id: str,
    as_of_date: str,
    top_n: int,
) -> list[dict[str, Any]]:
    if top_n < 1:
        raise ValueError("research top_n 必须至少为1")
    cutoff = normalize_date(as_of_date, "as_of_date")
    requests: list[dict[str, Any]] = []
    for record in financial_records[:top_n]:
        immutable_input = {
            "run_id": run_id,
            "code": str(record["code"]),
            "name": str(record.get("name", "")),
            "as_of_date": cutoff,
            "technical_context": record.get("technical_context") or {},
            "financial_quant": record.get("financial_quant") or {},
        }
        requests.append(
            {
                **immutable_input,
                "request_id": f"{run_id}:{record['code']}",
                "input_hash": _canonical_hash(immutable_input),
                "questions": list(RESEARCH_QUESTIONS),
                "result_contract": {
                    "schema_version": FUNDAMENTAL_RESEARCH_SCHEMA_VERSION,
                    "skill_version": RESEARCH_SKILL_VERSION,
                    "rubric_version": RESEARCH_RUBRIC_VERSION,
                    "scores": [
                        "industry_cycle",
                        "expectation_delta",
                        "risk",
                    ],
                    "risk_score_direction": "数值越高风险越大",
                    "required_evidence_fields": [
                        "evidence_id",
                        "claim",
                        "source_type",
                        "source_name",
                        "source_title",
                        "source_tier",
                        "published_date",
                        "effective_period",
                        "confidence",
                        "retrieved_at",
                        "supports",
                        "source_url或document_id",
                    ],
                    "required_support_targets": [
                        "industry_cycle_score",
                        "expectation_delta_score",
                        "risk_score",
                        "why_now",
                        "industry_summary",
                        "expectation_summary",
                        "risk_summary",
                        "catalysts.<index>",
                        "risks.<index>",
                        "vetoes.<index>",
                    ],
                    "quality_flag_codes": sorted(RESEARCH_QUALITY_FLAG_CODES),
                    "cutoff_rule": "证据发布日期不得晚于as_of_date",
                },
            }
        )
    return requests


def prepare_research_request_file(
    financial_records: list[dict[str, Any]],
    run_directory: Path,
    run_id: str,
    as_of_date: str,
    top_n: int,
    config_version: str,
) -> tuple[Path, Path, list[dict[str, Any]]]:
    cutoff = normalize_date(as_of_date, "as_of_date")
    requests = build_research_requests(
        financial_records,
        run_id,
        cutoff,
        top_n,
    )
    path = run_directory / "fundamental" / "research_request.json"
    write_json_atomic(
        path,
        {
            "metadata": {
                "schema_version": FUNDAMENTAL_RESEARCH_SCHEMA_VERSION,
                "config_version": config_version,
                "status": "prepared",
                "run_id": run_id,
                "as_of_date": cutoff,
                "record_count": len(requests),
            },
            "records": requests,
        },
    )
    template_path = (
        run_directory / "fundamental" / "research_results.template.json"
    )
    write_json_atomic(
        template_path,
        {
            "metadata": {
                "schema_version": FUNDAMENTAL_RESEARCH_SCHEMA_VERSION,
                "run_id": run_id,
                "as_of_date": cutoff,
                "record_count": len(requests),
            },
            "records": [
                {
                    "schema_version": FUNDAMENTAL_RESEARCH_SCHEMA_VERSION,
                    "run_id": run_id,
                    "input_hash": item["input_hash"],
                    "code": item["code"],
                    "name": item["name"],
                    "as_of_date": cutoff,
                    "status": "partial",
                    "fundamental_state": "UNCERTAIN",
                    "scores": {
                        "industry_cycle": None,
                        "expectation_delta": None,
                        "risk": None,
                    },
                    "risk_level": "UNKNOWN",
                    "confidence": 0.0,
                    "signals": {
                        "revenue_accelerating": None,
                        "profit_accelerating": None,
                        "margin_improving": None,
                        "industry_improving": None,
                        "expectation_revision": None,
                    },
                    "catalysts": [],
                    "risks": [],
                    "vetoes": [],
                    "evidence": [],
                    "quality_flags": [],
                    "research_metadata": {
                        "skill_version": RESEARCH_SKILL_VERSION,
                        "rubric_version": RESEARCH_RUBRIC_VERSION,
                        "model_provider": "",
                        "model_name": "",
                        "started_at": "",
                        "finished_at": "",
                    },
                    "why_now": "",
                    "industry_summary": "",
                    "expectation_summary": "",
                    "risk_summary": "",
                }
                for item in requests
            ],
        },
    )
    return path, template_path, requests


def load_research_results(
    path: Path,
    expected_requests: list[dict[str, Any]],
    run_id: str,
    as_of_date: str,
) -> dict[str, FundamentalResearchResult]:
    cutoff = normalize_date(as_of_date, "as_of_date")
    try:
        payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"研究结果读取失败：{path}：{exc}") from exc
    metadata = payload.get("metadata")
    records = payload.get("records")
    if not isinstance(metadata, dict) or not isinstance(records, list):
        raise RuntimeError("研究结果必须包含 metadata 对象和 records 数组")
    if metadata.get("schema_version") not in FUNDAMENTAL_RESEARCH_SCHEMA_VERSIONS:
        raise RuntimeError("研究结果 schema_version 不兼容")
    expected_schema = (
        _request_schema_version(expected_requests[0])
        if expected_requests
        else ""
    )
    if expected_schema and metadata.get("schema_version") != expected_schema:
        raise RuntimeError("研究结果元数据的契约版本与研究请求不匹配")
    if str(metadata.get("run_id")) != run_id:
        raise RuntimeError("研究结果不属于当前运行编号")
    if metadata.get("record_count") != len(records):
        raise RuntimeError("研究结果 record_count 与实际记录数不一致")
    try:
        metadata_cutoff = normalize_date(
            str(metadata.get("as_of_date", "")),
            "metadata.as_of_date",
        )
    except ValueError as exc:
        raise RuntimeError(f"研究结果截止日期无效：{exc}") from exc
    if metadata_cutoff != cutoff:
        raise RuntimeError("研究结果截止日期与当前运行不一致")
    expected = {str(item["code"]): item for item in expected_requests}
    parsed: dict[str, FundamentalResearchResult] = {}
    for raw in records:
        result = validate_research_result_record(
            raw,
            expected,
            run_id,
            cutoff,
        )
        if result.code in parsed:
            raise RuntimeError(f"研究结果包含重复股票：{result.code}")
        parsed[result.code] = result
    return parsed


def validate_research_result_record(
    raw: Any,
    expected_requests: dict[str, dict[str, Any]] | list[dict[str, Any]],
    run_id: str,
    as_of_date: str,
) -> FundamentalResearchResult:
    """独立校验一只股票，供批量导入和失败隔离共同复用。"""

    if not isinstance(raw, dict):
        raise RuntimeError("研究结果记录必须是对象")
    cutoff = normalize_date(as_of_date, "as_of_date")
    expected = (
        expected_requests
        if isinstance(expected_requests, dict)
        else {str(item["code"]): item for item in expected_requests}
    )
    raw_code = str(raw.get("code", "")).zfill(6)
    request = expected.get(raw_code)
    if request is None:
        raise RuntimeError(f"研究结果包含未请求的股票：{raw_code}")
    if str(raw.get("run_id", "")) != run_id:
        raise RuntimeError(f"{raw_code} 的运行编号不匹配")
    try:
        raw_cutoff = normalize_date(
            str(raw.get("as_of_date", "")),
            "as_of_date",
        )
    except ValueError as exc:
        raise RuntimeError(f"{raw_code} 的截止日期无效：{exc}") from exc
    if raw_cutoff != cutoff:
        raise RuntimeError(f"{raw_code} 的截止日期不匹配")
    if str(raw.get("name", "")) != str(request["name"]):
        raise RuntimeError(f"{raw_code} 的股票名称与研究请求不匹配")
    if str(raw.get("input_hash", "")) != request["input_hash"]:
        raise RuntimeError(f"{raw_code} 的 input_hash 与研究请求不匹配")
    result_contract = request.get("result_contract")
    if isinstance(result_contract, dict):
        expected_schema = str(result_contract.get("schema_version", ""))
        actual_schema = str(raw.get("schema_version", ""))
        if expected_schema and actual_schema != expected_schema:
            raise RuntimeError(
                f"{raw_code} 的研究契约版本与请求不匹配："
                f"需要 {expected_schema}，收到 {actual_schema}"
            )
    try:
        result = FundamentalResearchResult.from_record(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"研究结果字段无效：{exc}") from exc
    if result.run_id != run_id or result.as_of_date != cutoff:
        raise RuntimeError(f"{result.code} 的运行编号或截止日期不匹配")
    if result.name != str(request["name"]):
        raise RuntimeError(f"{result.code} 的股票名称与研究请求不匹配")
    if result.input_hash != request["input_hash"]:
        raise RuntimeError(f"{result.code} 的 input_hash 与研究请求不匹配")
    if isinstance(result_contract, dict):
        expected_rubric = str(result_contract.get("rubric_version", ""))
        expected_skill = str(result_contract.get("skill_version", ""))
        actual_skill = str(
            (result.research_metadata or {}).get("skill_version", "")
        )
        if expected_skill and actual_skill != expected_skill:
            raise RuntimeError(
                f"{result.code} 的研究Skill版本与研究请求不匹配"
            )
        actual_rubric = str(
            (result.research_metadata or {}).get("rubric_version", "")
        )
        if expected_rubric and actual_rubric != expected_rubric:
            raise RuntimeError(
                f"{result.code} 的评分规则版本与研究请求不匹配"
            )
    return result


def write_layer3_results(
    financial_records: list[dict[str, Any]],
    research_requests: list[dict[str, Any]],
    research_results: dict[str, FundamentalResearchResult],
    run_directory: Path,
    run_id: str,
    as_of_date: str,
    config_version: str,
    scoring: FundamentalScoringConfig,
) -> tuple[Path, list[dict[str, Any]]]:
    cutoff = normalize_date(as_of_date, "as_of_date")
    research_schema_version = (
        _request_schema_version(research_requests[0])
        if research_requests
        else FUNDAMENTAL_RESEARCH_SCHEMA_VERSION
    ) or FUNDAMENTAL_RESEARCH_SCHEMA_VERSION
    selected_codes = {str(item["code"]) for item in research_requests}
    selected = [
        item for item in financial_records if str(item["code"]) in selected_codes
    ]
    results = rank_layer3_results(
        compose_layer3_result(
            item,
            research_results.get(str(item["code"])),
            scoring,
        )
        for item in selected
    )
    records: list[dict[str, Any]] = []
    financial_by_code = {str(item["code"]): item for item in selected}
    for result in results:
        financial = financial_by_code[result.code]
        research = research_results.get(result.code)
        records.append(
            {
                **result.to_record(),
                "technical_context": financial.get("technical_context") or {},
                "financial_quant": financial.get("financial_quant") or {},
                "research": research.to_record() if research is not None else None,
            }
        )
    path = run_directory / "fundamental" / "layer3.json"
    write_json_atomic(
        path,
        {
            "metadata": {
                "schema_version": "layer3-result-v1",
                "research_schema_version": research_schema_version,
                "config_version": config_version,
                "run_id": run_id,
                "as_of_date": cutoff,
                "status": (
                    "complete"
                    if records
                    and all(
                        item["status"] in {"complete", "rejected"}
                        for item in records
                    )
                    else "pending"
                ),
                "record_count": len(records),
                "research_results_received": len(research_results),
            },
            "records": records,
        },
    )
    return path, records
