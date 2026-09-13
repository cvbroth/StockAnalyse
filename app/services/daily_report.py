"""从不可变运行快照生成Layer3 JSON与Markdown研究报告。"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .fundamental_sync import write_json_atomic


REPORT_SCHEMA_VERSION = "daily-research-report-v1"


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label}读取失败：{path}：{exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label}必须是JSON对象：{path}")
    return payload


def _records(payload: dict[str, Any], label: str) -> list[dict[str, Any]]:
    records = payload.get("records")
    if not isinstance(records, list) or any(
        not isinstance(item, dict) for item in records
    ):
        raise RuntimeError(f"{label}必须包含 records 对象数组")
    return records


def _text(value: Any) -> str:
    return " ".join(str(value or "").replace("|", "\\|").split()) or "—"


def _number(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _write_text_atomic(path: Path, content: str) -> None:
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


def _render_markdown(report: dict[str, Any], top_n: int) -> str:
    metadata = report["metadata"]
    counts = metadata["layer3_counts"]
    lines = [
        "# A股上升周期每日研究报告",
        "",
        f"- 运行编号：`{_text(metadata['run_id'])}`",
        f"- 数据截止：{_text(metadata['as_of_date'])}",
        f"- 报告状态：`{_text(metadata['status'])}`",
        f"- Layer2候选：{metadata['layer2_count']}只",
        (
            "- Layer3状态："
            f"完成{counts['complete']}、否决{counts['rejected']}、"
            f"部分{counts['partial']}、失败{counts['failed']}、"
            f"待研究{counts['pending']}"
        ),
        "",
        "## Layer3重点池",
        "",
        "| 排名 | 代码 | 名称 | 状态 | 最终分 | 基本面状态 | 可信度 |",
        "|---:|---|---|---|---:|---|---:|",
    ]
    ranked = [
        item
        for item in report["records"]
        if item.get("rank") is not None
    ][:top_n]
    if ranked:
        for item in ranked:
            lines.append(
                "| "
                f"{item['rank']} | {_text(item['code'])} | {_text(item['name'])} | "
                f"{_text(item.get('focus_status'))} | "
                f"{_number(item.get('final_score'))} | "
                f"{_text(item.get('fundamental_state'))} | "
                f"{_number(item.get('confidence'), 2)} |"
            )
    else:
        lines.append("| — | — | 尚无可排名结果 | — | — | — | — |")

    lines.extend(["", "## 候选状态卡", ""])
    cards = report["records"][:top_n]
    if not cards:
        lines.append("当前运行没有Layer3候选。")
    for item in cards:
        technical = item.get("technical_context") or {}
        financial = item.get("financial_quant") or {}
        financial_scores = financial.get("scores") or {}
        scores = item.get("scores") or {}
        lines.extend(
            [
                f"### {_text(item.get('code'))} {_text(item.get('name'))}",
                "",
                (
                    f"技术：{_text(technical.get('technical_score'))}/5，"
                    f"质量分 {_number(technical.get('technical_quality_score'))}，"
                    f"Layer2排名 {_text(technical.get('quality_rank'))}。"
                ),
                "",
                (
                    f"财务：盈利动量 {_number(financial_scores.get('earnings_momentum'))}，"
                    f"经营质量 {_number(financial_scores.get('business_quality'))}，"
                    f"覆盖率 {_number(financial.get('data_coverage'), 2)}。"
                ),
                "",
                (
                    f"研究：行业景气 {_number(scores.get('industry_cycle'))}，"
                    f"预期变化 {_number(scores.get('expectation_delta'))}，"
                    f"风险 {_number(scores.get('risk'))}；"
                    f"状态 `{_text(item.get('focus_status'))}`。"
                ),
                "",
                f"为什么是现在：{_text((item.get('research') or {}).get('why_now'))}",
                "",
                "催化：" + "；".join(
                    _text(value) for value in item.get("catalysts") or []
                ) if item.get("catalysts") else "催化：—",
                "",
                "风险：" + "；".join(
                    _text(value) for value in item.get("risks") or []
                ) if item.get("risks") else "风险：—",
                "",
            ]
        )

    rejected = [
        item for item in report["records"] if item.get("status") == "rejected"
    ]
    lines.extend(["## 风险否决", ""])
    if rejected:
        for item in rejected:
            vetoes = "；".join(_text(value) for value in item.get("vetoes") or [])
            lines.append(
                f"- `{_text(item['code'])}` {_text(item['name'])}：{vetoes or '已否决'}"
            )
    else:
        lines.append("- 当前没有已验证的风险否决。")

    incomplete = [
        item
        for item in report["records"]
        if item.get("status") in {"pending", "partial", "failed"}
    ]
    lines.extend(["", "## 未完成研究", ""])
    if incomplete:
        for item in incomplete:
            lines.append(
                f"- `{_text(item['code'])}` {_text(item['name'])}："
                f"`{_text(item.get('status'))}`"
            )
    else:
        lines.append("- 当前Layer3候选均已形成完成或否决结论。")
    lines.extend(
        [
            "",
            "---",
            "",
            "本报告由规则化筛选、财务量化和结构化研究生成，不构成投资建议。",
        ]
    )
    return "\n".join(lines)


def generate_daily_report(
    run_directory: Path,
    top_n: int = 10,
) -> tuple[Path, Path, dict[str, Any]]:
    if top_n < 1:
        raise ValueError("报告 top_n 必须至少为1")
    run_directory = run_directory.expanduser().resolve()
    manifest = _read_json(run_directory / "manifest.json", "运行清单")
    layer2 = _read_json(run_directory / "layer2.json", "Layer2结果")
    layer3 = _read_json(
        run_directory / "fundamental" / "layer3.json",
        "Layer3结果",
    )
    layer2_records = _records(layer2, "Layer2结果")
    layer3_records = _records(layer3, "Layer3结果")
    run_id = str(manifest.get("run_id", ""))
    as_of_date = str(manifest.get("end_date", ""))
    layer3_metadata = layer3.get("metadata") or {}
    if str(layer3_metadata.get("run_id", "")) != run_id:
        raise RuntimeError("Layer3结果与运行清单的运行编号不一致")
    statuses = ("complete", "rejected", "partial", "failed", "pending")
    counts = {
        status: sum(item.get("status") == status for item in layer3_records)
        for status in statuses
    }
    report_status = (
        "complete"
        if layer3_records
        and counts["partial"] == counts["failed"] == counts["pending"] == 0
        else "partial"
    )
    ordered = sorted(
        layer3_records,
        key=lambda item: (
            item.get("rank") is not None,
            -(int(item.get("rank")) if item.get("rank") is not None else 10**9),
            item.get("status") == "rejected",
        ),
        reverse=True,
    )
    report = {
        "metadata": {
            "schema_version": REPORT_SCHEMA_VERSION,
            "run_id": run_id,
            "as_of_date": as_of_date,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "status": report_status,
            "layer2_count": len(layer2_records),
            "layer3_count": len(layer3_records),
            "layer3_counts": counts,
            "top_n": top_n,
        },
        "records": ordered,
    }
    fundamental_directory = run_directory / "fundamental"
    json_path = fundamental_directory / "daily_report.json"
    markdown_path = fundamental_directory / "daily_report.md"
    write_json_atomic(json_path, report)
    _write_text_atomic(markdown_path, _render_markdown(report, top_n))
    return json_path, markdown_path, report
