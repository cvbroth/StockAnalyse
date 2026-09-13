"""Layer3研究请求、外部结果校验和最终合并编排。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..analysis.fundamentals import (
    FUNDAMENTAL_RESEARCH_SCHEMA_VERSION,
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
                    "scores": [
                        "industry_cycle",
                        "expectation_delta",
                        "risk",
                    ],
                    "risk_score_direction": "数值越高风险越大",
                    "required_evidence_fields": [
                        "claim",
                        "source_type",
                        "source_name",
                        "source_tier",
                        "published_date",
                        "effective_period",
                        "confidence",
                        "source_url或document_id",
                    ],
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
    if metadata.get("schema_version") != FUNDAMENTAL_RESEARCH_SCHEMA_VERSION:
        raise RuntimeError("研究结果 schema_version 不兼容")
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
        if not isinstance(raw, dict):
            raise RuntimeError("研究结果 records 的每一项必须是对象")
        try:
            result = FundamentalResearchResult.from_record(raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"研究结果字段无效：{exc}") from exc
        request = expected.get(result.code)
        if request is None:
            raise RuntimeError(f"研究结果包含未请求的股票：{result.code}")
        if result.code in parsed:
            raise RuntimeError(f"研究结果包含重复股票：{result.code}")
        if result.run_id != run_id or result.as_of_date != cutoff:
            raise RuntimeError(f"{result.code} 的运行编号或截止日期不匹配")
        if result.name != str(request["name"]):
            raise RuntimeError(f"{result.code} 的股票名称与研究请求不匹配")
        if result.input_hash != request["input_hash"]:
            raise RuntimeError(f"{result.code} 的 input_hash 与研究请求不匹配")
        parsed[result.code] = result
    return parsed


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
                "research_schema_version": FUNDAMENTAL_RESEARCH_SCHEMA_VERSION,
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
