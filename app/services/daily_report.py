"""从不可变运行快照生成可解释的每日研究报告。"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..fundamentals.config import load_fundamental_settings
from .fundamental_sync import write_json_atomic
from .report_publication import (
    output_directory_from_run,
    write_publication_bundle,
    write_text_atomic,
)


REPORT_SCHEMA_VERSION = "daily-research-report-v3"

FOCUS_STATUS_LABELS = {
    "KEY_FOCUS": "重点关注",
    "FOLLOW_UP": "持续跟踪",
    "WATCH": "观察",
    "REJECTED": "风险否决",
    "PENDING_RESEARCH": "待研究",
    "PENDING_REVIEW": "待完善",
}
FUNDAMENTAL_STATE_LABELS = {
    "IMPROVING": "改善",
    "STABLE": "稳定",
    "DETERIORATING": "恶化",
    "UNCERTAIN": "不确定",
}
RESEARCH_STATUS_LABELS = {
    "complete": "研究完成",
    "partial": "证据不完整",
    "failed": "研究失败",
    "pending": "待研究",
    "rejected": "风险否决",
}
SCORE_LABELS = {
    "earnings_momentum": "盈利动量",
    "business_quality": "经营质量",
    "industry_cycle": "行业景气",
    "expectation_delta": "预期变化",
}


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label}读取失败：{path}：{exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label}必须是JSON对象：{path}")
    return payload


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


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


def _short_text(value: Any, limit: int) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _normalized_date(value: Any) -> str:
    text = str(value or "").replace("-", "")
    return text if len(text) == 8 and text.isdigit() else ""


def _display_date(value: Any) -> str:
    text = _normalized_date(value)
    return f"{text[:4]}-{text[4:6]}-{text[6:]}" if text else _text(value)


def _focus_label(value: Any) -> str:
    raw = str(value or "")
    return FOCUS_STATUS_LABELS.get(raw, raw or "—")


def _state_label(value: Any) -> str:
    raw = str(value or "")
    return FUNDAMENTAL_STATE_LABELS.get(raw, raw or "—")


def _research_label(value: Any) -> str:
    raw = str(value or "")
    return RESEARCH_STATUS_LABELS.get(raw, raw or "—")


def _load_previous_report(
    output_directory: Path,
    current_as_of_date: str,
) -> dict[str, Any] | None:
    """读取当前交易日前最近一份日报；同日重建不与自己比较。"""

    current = _normalized_date(current_as_of_date)
    if not current:
        return None
    selected: tuple[tuple[str, str, str], dict[str, Any]] | None = None
    runs_directory = output_directory / "runs"
    if not runs_directory.is_dir():
        return None
    for path in runs_directory.glob("*/fundamental/daily_report.json"):
        payload = _read_optional_json(path)
        if payload is None or not isinstance(payload.get("metadata"), dict):
            continue
        metadata = payload["metadata"]
        period = _normalized_date(metadata.get("as_of_date"))
        if not period or period >= current or not isinstance(payload.get("records"), list):
            continue
        key = (
            period,
            str(metadata.get("generated_at", "")),
            str(metadata.get("run_id", "")),
        )
        if selected is None or key > selected[0]:
            selected = (key, payload)
    return selected[1] if selected is not None else None


def _scoring_policy(layer3_metadata: dict[str, Any]) -> dict[str, Any] | None:
    """仅在运行配置版本与当前配置一致时解释分数，避免误解历史快照。"""

    try:
        settings = load_fundamental_settings()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    run_version = str(layer3_metadata.get("config_version", ""))
    if not run_version or run_version != settings.version:
        return None
    scoring = settings.scoring
    return {
        "config_version": settings.version,
        "weights": {
            "earnings_momentum": scoring.earnings_momentum_weight,
            "business_quality": scoring.business_quality_weight,
            "industry_cycle": scoring.industry_cycle_weight,
            "expectation_delta": scoring.expectation_delta_weight,
            "risk": scoring.risk_penalty_weight,
        },
        "thresholds": {
            "follow_up": scoring.follow_up_threshold,
            "key_focus": scoring.key_focus_threshold,
            "red_risk": scoring.red_risk_threshold,
        },
        "key_focus_requires_improving": True,
    }


def _evidence_summary(record: dict[str, Any], as_of_date: str) -> dict[str, Any]:
    research = record.get("research") or {}
    evidence = research.get("evidence") or []
    valid = [item for item in evidence if isinstance(item, dict)]
    dates = sorted(
        date
        for item in valid
        if (date := _normalized_date(item.get("published_date")))
    )
    tiers: dict[str, int] = {}
    for item in valid:
        tier = str(item.get("source_tier", "unknown"))
        tiers[tier] = tiers.get(tier, 0) + 1
    latest_age_days: int | None = None
    if dates and _normalized_date(as_of_date):
        try:
            latest_age_days = (
                datetime.strptime(_normalized_date(as_of_date), "%Y%m%d")
                - datetime.strptime(dates[-1], "%Y%m%d")
            ).days
        except ValueError:
            latest_age_days = None
    unique_sources = {
        str(item.get("source_url") or item.get("document_id") or item.get("source_name"))
        for item in valid
        if item.get("source_url") or item.get("document_id") or item.get("source_name")
    }
    primary_count = 0
    for item in valid:
        try:
            primary_count += int(item.get("source_tier", 4)) <= 2
        except (TypeError, ValueError):
            continue
    return {
        "count": len(valid),
        "primary_count": primary_count,
        "unique_source_count": len(unique_sources),
        "earliest_published_date": dates[0] if dates else None,
        "latest_published_date": dates[-1] if dates else None,
        "latest_age_days": latest_age_days,
        "tier_counts": tiers,
    }


def _score_breakdown(
    record: dict[str, Any],
    policy: dict[str, Any] | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "positive_score": record.get("positive_score"),
        "risk_penalty": record.get("risk_penalty"),
        "final_score": record.get("final_score"),
        "components": {},
        "threshold_gap": None,
    }
    if policy is None:
        return result
    scores = record.get("scores") or {}
    weights = policy["weights"]
    positive_weight = sum(float(weights[name]) for name in SCORE_LABELS)
    components: dict[str, Any] = {}
    for name in SCORE_LABELS:
        raw_score = scores.get(name)
        weight = float(weights[name])
        contribution = (
            round(float(raw_score) * weight / positive_weight, 4)
            if raw_score is not None and positive_weight > 0
            else None
        )
        components[name] = {
            "score": raw_score,
            "weight": weight,
            "positive_contribution": contribution,
        }
    risk_score = scores.get("risk")
    components["risk"] = {
        "score": risk_score,
        "weight": float(weights["risk"]),
        "penalty": record.get("risk_penalty"),
    }
    result["components"] = components

    final_score = record.get("final_score")
    if final_score is not None:
        thresholds = policy["thresholds"]
        key_gap = max(0.0, float(thresholds["key_focus"]) - float(final_score))
        follow_gap = max(0.0, float(thresholds["follow_up"]) - float(final_score))
        state_required = str(record.get("fundamental_state")) != "IMPROVING"
        if float(final_score) < float(thresholds["follow_up"]):
            next_level = "FOLLOW_UP"
            next_gap = follow_gap
        elif float(final_score) < float(thresholds["key_focus"]):
            next_level = "KEY_FOCUS"
            next_gap = key_gap
        elif state_required:
            next_level = "KEY_FOCUS"
            next_gap = 0.0
        else:
            next_level = None
            next_gap = 0.0
        result["threshold_gap"] = {
            "key_focus": round(key_gap, 4),
            "follow_up": round(follow_gap, 4),
            "next_level": next_level,
            "next_level_gap": round(next_gap, 4),
            "key_focus_state_blocked": state_required,
        }
    return result


def _enrich_records(
    records: list[dict[str, Any]],
    previous_report: dict[str, Any] | None,
    as_of_date: str,
    policy: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    previous_records = previous_report.get("records", []) if previous_report else []
    previous_by_code = {
        str(item.get("code", "")).zfill(6): item
        for item in previous_records
        if isinstance(item, dict)
    }
    current_codes: set[str] = set()
    enriched: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    for raw in records:
        item = deepcopy(raw)
        code = str(item.get("code", "")).zfill(6)
        current_codes.add(code)
        previous = previous_by_code.get(code)
        current_rank = item.get("rank")
        previous_rank = previous.get("rank") if previous else None
        current_score = item.get("final_score")
        previous_score = previous.get("final_score") if previous else None
        rank_change = (
            int(previous_rank) - int(current_rank)
            if previous_rank is not None and current_rank is not None
            else None
        )
        score_change = (
            round(float(current_score) - float(previous_score), 4)
            if current_score is not None and previous_score is not None
            else None
        )
        focus_changed = bool(
            previous and previous.get("focus_status") != item.get("focus_status")
        )
        quality_rank = (item.get("technical_context") or {}).get("quality_rank")
        rerank_change = (
            int(quality_rank) - int(current_rank)
            if quality_rank is not None and current_rank is not None
            else None
        )
        item["display"] = {
            "focus_status": _focus_label(item.get("focus_status")),
            "fundamental_state": _state_label(item.get("fundamental_state")),
            "research_status": _research_label(item.get("status")),
        }
        item["comparison"] = {
            "available": previous is not None,
            "is_new": previous_report is not None and previous is None,
            "previous_rank": previous_rank,
            "rank_change": rank_change,
            "previous_final_score": previous_score,
            "final_score_change": score_change,
            "previous_focus_status": previous.get("focus_status") if previous else None,
            "focus_status_changed": focus_changed,
            "layer2_to_layer3_rank_change": rerank_change,
        }
        item["score_breakdown"] = _score_breakdown(item, policy)
        item["evidence_summary"] = _evidence_summary(item, as_of_date)
        if focus_changed:
            transitions.append(
                {
                    "code": code,
                    "name": str(item.get("name", "")),
                    "from": previous.get("focus_status"),
                    "to": item.get("focus_status"),
                }
            )
        enriched.append(item)

    exited = [
        {
            "code": code,
            "name": str(item.get("name", "")),
            "previous_rank": item.get("rank"),
            "previous_focus_status": item.get("focus_status"),
        }
        for code, item in sorted(previous_by_code.items())
        if code not in current_codes
    ]
    entered = [
        {"code": item["code"], "name": str(item.get("name", "")), "rank": item.get("rank")}
        for item in enriched
        if item["comparison"]["is_new"]
    ]
    return enriched, {
        "comparison_available": previous_report is not None,
        "previous_as_of_date": (
            previous_report.get("metadata", {}).get("as_of_date")
            if previous_report is not None
            else None
        ),
        "entered": entered,
        "exited": exited,
        "focus_transitions": transitions,
    }


def _change_text(item: dict[str, Any]) -> str:
    comparison = item.get("comparison") or {}
    if comparison.get("is_new"):
        return "新进入"
    rank_change = comparison.get("rank_change")
    score_change = comparison.get("final_score_change")
    if rank_change is None and score_change is None:
        return "—"
    parts: list[str] = []
    if rank_change is not None:
        parts.append(f"排名{int(rank_change):+d}")
    if score_change is not None:
        parts.append(f"分数{float(score_change):+.1f}")
    return "，".join(parts)


def _threshold_text(item: dict[str, Any]) -> str:
    if item.get("focus_status") == "REJECTED":
        return "已风险否决"
    if item.get("status") in {"pending", "partial", "failed"}:
        return "等待完整研究"
    gap = (item.get("score_breakdown") or {}).get("threshold_gap")
    if not gap:
        return "—"
    if gap.get("next_level") is None:
        return "已达到重点关注条件"
    target = _focus_label(gap.get("next_level"))
    score_gap = float(gap.get("next_level_gap", 0.0))
    if gap.get("key_focus_state_blocked") and score_gap <= 0:
        return "分数已达标，仍需基本面转为改善"
    return f"距{target}{score_gap:.1f}分"


def _score_breakdown_text(item: dict[str, Any]) -> str:
    breakdown = item.get("score_breakdown") or {}
    components = breakdown.get("components") or {}
    parts: list[str] = []
    for name, label in SCORE_LABELS.items():
        component = components.get(name) or {}
        if component.get("score") is not None:
            contribution = component.get("positive_contribution")
            suffix = f"，贡献{float(contribution):.1f}" if contribution is not None else ""
            parts.append(f"{label}{float(component['score']):.1f}{suffix}")
    positive = _number(breakdown.get("positive_score"))
    penalty = _number(breakdown.get("risk_penalty"))
    final = _number(breakdown.get("final_score"))
    risk = components.get("risk") or {}
    risk_text = (
        f"，风险{float(risk['score']):.1f}"
        if risk.get("score") is not None
        else ""
    )
    detail = "；".join(parts) if parts else "分项贡献不可用"
    return (
        f"{detail}。正向分{positive}{risk_text}－风险扣分{penalty}＝最终分{final}"
    )


def _executive_summary(report: dict[str, Any]) -> list[str]:
    metadata = report["metadata"]
    focus = metadata["focus_counts"]
    ranked = [item for item in report["records"] if item.get("rank") is not None]
    formed = focus["KEY_FOCUS"] + focus["FOLLOW_UP"] + focus["WATCH"] + focus["REJECTED"]
    pending = focus["PENDING_RESEARCH"] + focus["PENDING_REVIEW"]
    lines = [
        f"研究覆盖：Layer3已形成结论{formed}只，待完善{pending}只。",
        (
            f"关注分层：重点关注{focus['KEY_FOCUS']}只、持续跟踪{focus['FOLLOW_UP']}只、"
            f"观察{focus['WATCH']}只、风险否决{focus['REJECTED']}只。"
        ),
    ]
    if ranked:
        top = ranked[0]
        lines.append(
            f"当前首位为{top.get('name')}（{top.get('code')}）{_number(top.get('final_score'))}分，"
            f"{_focus_label(top.get('focus_status'))}，{_threshold_text(top)}。"
        )
    else:
        lines.append("当前没有完成评分并进入排名的Layer3候选。")
    changes = report["changes"]
    if changes["comparison_available"]:
        lines.append(
            f"较{_display_date(changes['previous_as_of_date'])}：Layer3新进入{len(changes['entered'])}只、"
            f"退出{len(changes['exited'])}只、关注级别变化{len(changes['focus_transitions'])}只。"
        )
    else:
        lines.append("暂无上一交易日报，本期不计算跨日排名和状态变化。")
    return lines


def _evidence_source(item: dict[str, Any]) -> str:
    name = _text(item.get("source_name"))
    url = str(item.get("source_url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return f"[{name}]({url})"
    document_id = str(item.get("document_id") or "").strip()
    return f"{name}（文档：{_text(document_id)}）" if document_id else name


def _render_markdown(report: dict[str, Any], top_n: int) -> str:
    metadata = report["metadata"]
    market = metadata["market_counts"]
    layer3 = metadata["layer3_counts"]
    focus = metadata["focus_counts"]
    funnel = metadata["selection_funnel"]
    report_status = "完整" if metadata["status"] == "complete" else "部分完成"
    lines = [
        f"# A股上升周期日报｜{_display_date(metadata['as_of_date'])}",
        "",
        "## 30秒结论",
        "",
    ]
    lines.extend(f"- {text}" for text in report["executive_summary"])
    lines.extend(
        [
            "",
            "> “报告完整”仅表示研究流程和字段完整，不代表股票通过投资判断。",
            "",
            "## 筛选漏斗",
            "",
            "```text",
            f"有效分析 {funnel['market_successful']}只",
            f"├─ 5/5技术确认 {funnel['confirmed_5of5']}只",
            f"├─ 4/5观察池 {funnel['watchlist_4of5']}只",
            f"└─ Layer2排序 {funnel['layer2_ranked']}只",
            f"   └─ 财务量化 {funnel['financial_prepared']}只",
            f"      └─ Layer3研究任务 {funnel['layer3_researched']}只",
            "```",
            "",
            f"运行编号：`{_text(metadata['run_id'])}`；报告状态：{report_status}；"
            f"数据源：{_text(metadata.get('data_provider'))}；市场范围：{_text(metadata.get('market_scope'))}。",
            "",
            "## Layer3研究排名",
            "",
            "| 排名 | 代码 | 名称 | 最终分 | 关注级别 | 基本面 | 跨日变化 | 升级距离 | 证据 |",
            "|---:|---|---|---:|---|---|---|---|---:|",
        ]
    )
    ranked = [item for item in report["records"] if item.get("rank") is not None][:top_n]
    if ranked:
        for item in ranked:
            evidence = item.get("evidence_summary") or {}
            lines.append(
                f"| {item['rank']} | {_text(item['code'])} | {_text(item['name'])} | "
                f"{_number(item.get('final_score'))} | {_focus_label(item.get('focus_status'))} | "
                f"{_state_label(item.get('fundamental_state'))} | {_change_text(item)} | "
                f"{_threshold_text(item)} | {evidence.get('primary_count', 0)}/{evidence.get('count', 0)} |"
            )
    else:
        lines.append("| — | — | 尚无可排名结果 | — | — | — | — | — | — |")

    lines.extend(["", "## 今日变化", ""])
    changes = report["changes"]
    if not changes["comparison_available"]:
        lines.append("- 暂无上一交易日报可供比较。")
    else:
        lines.append(f"- 对比基准：{_display_date(changes['previous_as_of_date'])}。")
        if changes["entered"]:
            lines.append("- 新进入Layer3：" + "、".join(f"{item['code']} {item['name']}" for item in changes["entered"]) + "。")
        else:
            lines.append("- 新进入Layer3：无。")
        if changes["exited"]:
            lines.append("- 退出Layer3：" + "、".join(f"{item['code']} {item['name']}" for item in changes["exited"]) + "。")
        else:
            lines.append("- 退出Layer3：无。")
        if changes["focus_transitions"]:
            for item in changes["focus_transitions"]:
                lines.append(
                    f"- {item['code']} {item['name']}："
                    f"{_focus_label(item['from'])} → {_focus_label(item['to'])}。"
                )
        else:
            lines.append("- 关注级别变化：无。")

    lines.extend(["", "## 候选状态卡", ""])
    cards = report["records"][:top_n]
    if not cards:
        lines.append("当前运行没有Layer3候选。")
    for item in cards:
        technical = item.get("technical_context") or {}
        financial = item.get("financial_quant") or {}
        research = item.get("research") or {}
        evidence = item.get("evidence_summary") or {}
        comparison = item.get("comparison") or {}
        rerank = comparison.get("layer2_to_layer3_rank_change")
        rerank_text = "—" if rerank is None else f"{int(rerank):+d}"
        lines.extend(
            [
                f"### {_text(item.get('code'))} {_text(item.get('name'))}",
                "",
                (
                    f"**定位：** {_number(item.get('final_score'))}分｜"
                    f"{_focus_label(item.get('focus_status'))}｜{_threshold_text(item)}｜"
                    f"可信度 {_number(item.get('confidence'), 2)}"
                ),
                "",
                (
                    f"**排名：** Layer2第{_text(technical.get('quality_rank'))} → "
                    f"Layer3第{_text(item.get('rank'))}，基本面重排 {rerank_text}；"
                    f"跨日变化：{_change_text(item)}。"
                ),
                "",
                f"**评分：** {_score_breakdown_text(item)}。",
                "",
                (
                    f"**数据质量：** 财务覆盖{_number(financial.get('data_coverage'), 2)}，"
                    f"可用季度{_text(financial.get('quarters_available'))}；"
                    f"研究证据{evidence.get('count', 0)}条，其中一/二级来源"
                    f"{evidence.get('primary_count', 0)}条，最新证据"
                    f"{_display_date(evidence.get('latest_published_date'))}。"
                ),
                "",
                f"**当前逻辑：** {_text(research.get('why_now'))}",
                "",
                "**主要催化：** " + "；".join(_text(value) for value in (item.get("catalysts") or [])[:3])
                if item.get("catalysts")
                else "**主要催化：** —",
                "",
                "**主要风险：** " + "；".join(_text(value) for value in (item.get("risks") or [])[:3])
                if item.get("risks")
                else "**主要风险：** —",
                "",
            ]
        )

    rejected = [item for item in report["records"] if item.get("status") == "rejected"]
    lines.extend(["## 风险否决", ""])
    if rejected:
        for item in rejected:
            vetoes = "；".join(_text(value) for value in item.get("vetoes") or [])
            lines.append(f"- `{_text(item['code'])}` {_text(item['name'])}：{vetoes or '已否决'}")
    else:
        lines.append("- 当前没有已验证的风险否决。")

    incomplete = [item for item in report["records"] if item.get("status") in {"pending", "partial", "failed"}]
    lines.extend(["", "## 未完成研究", ""])
    if incomplete:
        for item in incomplete:
            lines.append(f"- `{_text(item['code'])}` {_text(item['name'])}：{_research_label(item.get('status'))}")
    else:
        lines.append("- 当前Layer3候选均已形成完成或否决结论。")

    lines.extend(["", "## 证据索引", ""])
    evidence_found = False
    for item in cards:
        evidence_items = (item.get("research") or {}).get("evidence") or []
        evidence_items = [value for value in evidence_items if isinstance(value, dict)]
        if not evidence_items:
            continue
        evidence_found = True
        lines.extend([f"### {_text(item.get('code'))} {_text(item.get('name'))}", ""])
        for index, evidence in enumerate(evidence_items[:5], 1):
            lines.append(
                f"- E{index}｜{_evidence_source(evidence)}｜"
                f"{_display_date(evidence.get('published_date'))}｜"
                f"{_text(evidence.get('source_tier'))}级｜{_text(evidence.get('claim'))}"
            )
        if len(evidence_items) > 5:
            lines.append(f"- 另有{len(evidence_items) - 5}条证据保存在结构化报告JSON中。")
        lines.append("")
    if not evidence_found:
        lines.append("- 当前报告没有可展示的结构化研究证据。")

    lines.extend(
        [
            "",
            "## 状态说明",
            "",
            f"- 报告：{report_status}；Layer3完成{layer3['complete']}、否决{layer3['rejected']}、"
            f"部分{layer3['partial']}、失败{layer3['failed']}、待研究{layer3['pending']}。",
            f"- 关注：重点关注{focus['KEY_FOCUS']}、持续跟踪{focus['FOLLOW_UP']}、"
            f"观察{focus['WATCH']}、风险否决{focus['REJECTED']}。",
            f"- 市场：有效{market['successful']}只，5/5共{market['confirmed_5of5']}只，"
            f"4/5共{market['watchlist_4of5']}只。",
            "",
            "---",
            "",
            "本报告由规则化筛选、财务量化和结构化研究生成，不构成投资建议。",
        ]
    )
    return "\n".join(lines)


def _render_qq(report: dict[str, Any], top_n: int = 3) -> str:
    metadata = report["metadata"]
    market = metadata["market_counts"]
    focus = metadata["focus_counts"]
    status_label = "完整" if metadata["status"] == "complete" else "部分完成"
    lines = [
        f"【A股上升周期日报｜{_display_date(metadata['as_of_date'])}】",
        "",
        f"研究状态：{status_label}（仅表示流程完整）",
        f"市场：有效{market['successful']}｜5/5 {market['confirmed_5of5']}｜4/5 {market['watchlist_4of5']}",
        (
            f"分层：重点{focus['KEY_FOCUS']}｜跟踪{focus['FOLLOW_UP']}｜"
            f"观察{focus['WATCH']}｜否决{focus['REJECTED']}"
        ),
    ]
    changes = report["changes"]
    if changes["comparison_available"]:
        lines.append(
            f"变化：新进入{len(changes['entered'])}｜退出{len(changes['exited'])}｜"
            f"级别变化{len(changes['focus_transitions'])}"
        )
    lines.extend(["", "重点候选："])
    ranked = [item for item in report["records"] if item.get("rank") is not None]
    if not ranked:
        lines.append("暂无完成排名的Layer3候选。")
    for item in ranked[:top_n]:
        lines.append(
            f"{item['rank']}. {item.get('code')} {item.get('name')}｜"
            f"{_number(item.get('final_score'))}分｜{_focus_label(item.get('focus_status'))}｜"
            f"{_threshold_text(item)}"
        )
        why_now = _short_text((item.get("research") or {}).get("why_now"), 100)
        if why_now != "—":
            lines.append(f"   逻辑：{why_now}")
        risks = item.get("risks") or []
        if risks:
            lines.append(f"   风险：{_short_text(risks[0], 70)}")
    lines.extend(["", "详细证据请查看完整日报。本报告不构成投资建议。"])
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
    layer1 = _read_json(run_directory / "layer1.json", "Layer1结果")
    layer3 = _read_json(run_directory / "fundamental" / "layer3.json", "Layer3结果")
    financial_payload = _read_optional_json(run_directory / "fundamental" / "financial_quant.json")
    layer2_records = _records(layer2, "Layer2结果")
    layer1_records = _records(layer1, "Layer1结果")
    layer3_records = _records(layer3, "Layer3结果")
    financial_records = (
        financial_payload.get("records", [])
        if financial_payload is not None and isinstance(financial_payload.get("records"), list)
        else []
    )
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
        if layer3_records and counts["partial"] == counts["failed"] == counts["pending"] == 0
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
    output_directory = output_directory_from_run(run_directory)
    previous_report = _load_previous_report(output_directory, as_of_date)
    policy = _scoring_policy(layer3_metadata)
    enriched, changes = _enrich_records(ordered, previous_report, as_of_date, policy)
    focus_counts = {
        status: sum(item.get("focus_status") == status for item in enriched)
        for status in FOCUS_STATUS_LABELS
    }
    confirmed = sum(
        bool(item.get("base_filters", {}).get("passed"))
        and int(item.get("technical_score", 0)) == 5
        for item in layer1_records
    )
    watchlist = sum(
        bool(item.get("base_filters", {}).get("passed"))
        and int(item.get("technical_score", 0)) == 4
        for item in layer1_records
    )
    report = {
        "metadata": {
            "schema_version": REPORT_SCHEMA_VERSION,
            "run_id": run_id,
            "as_of_date": as_of_date,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "status": report_status,
            "status_label": "完整" if report_status == "complete" else "部分完成",
            "market_scope": manifest.get("market_scope"),
            "data_provider": manifest.get("database_provider"),
            "market_counts": {
                "requested": int(manifest.get("requested_count", len(layer1_records))),
                "successful": int(manifest.get("successful_count", len(layer1_records))),
                "errors": int(manifest.get("error_count", 0)),
                "confirmed_5of5": confirmed,
                "watchlist_4of5": watchlist,
            },
            "transition_counts": manifest.get("transition_counts", {}),
            "layer2_count": len(layer2_records),
            "layer3_count": len(layer3_records),
            "layer3_counts": counts,
            "focus_counts": focus_counts,
            "selection_funnel": {
                "market_successful": int(manifest.get("successful_count", len(layer1_records))),
                "confirmed_5of5": confirmed,
                "watchlist_4of5": watchlist,
                "layer2_ranked": len(layer2_records),
                "financial_prepared": len(financial_records) or len(layer3_records),
                "layer3_researched": len(layer3_records),
            },
            "scoring_policy": policy,
            "top_n": top_n,
        },
        "changes": changes,
        "records": enriched,
    }
    report["executive_summary"] = _executive_summary(report)
    fundamental_directory = run_directory / "fundamental"
    json_path = fundamental_directory / "daily_report.json"
    markdown_path = fundamental_directory / "daily_report.md"
    write_json_atomic(json_path, report)
    markdown = _render_markdown(report, top_n)
    qq_text = _render_qq(report)
    write_text_atomic(markdown_path, markdown)
    write_publication_bundle(output_directory, "daily", as_of_date, report, markdown, qq_text)
    return json_path, markdown_path, report
