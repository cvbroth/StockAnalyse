"""从一周内的不可变日报生成周汇总报告。"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .report_publication import write_publication_bundle


WEEKLY_REPORT_SCHEMA_VERSION = "weekly-research-report-v1"
WEEK_PATTERN = re.compile(r"^(\d{4})-W(\d{2})$")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"日报读取失败：{path}：{exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("metadata"), dict):
        raise RuntimeError(f"日报缺少 metadata：{path}")
    if not isinstance(payload.get("records"), list):
        raise RuntimeError(f"日报缺少 records：{path}")
    return payload


def _parse_market_date(value: Any) -> date:
    text = str(value or "")
    for pattern in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise RuntimeError(f"日报数据截止日期无效：{text!r}")


def _week_bounds(week: str) -> tuple[date, date]:
    matched = WEEK_PATTERN.fullmatch(week)
    if not matched:
        raise ValueError("周编号必须使用 YYYY-Www，例如 2026-W37")
    year, number = (int(value) for value in matched.groups())
    try:
        start = date.fromisocalendar(year, number, 1)
    except ValueError as exc:
        raise ValueError(f"无效ISO周编号：{week}") from exc
    return start, start + timedelta(days=6)


def _discover_daily_reports(output_directory: Path) -> dict[date, dict[str, Any]]:
    reports: dict[date, dict[str, Any]] = {}
    ordering: dict[date, tuple[str, str]] = {}
    runs_directory = output_directory / "runs"
    if not runs_directory.is_dir():
        return reports
    for path in runs_directory.glob("*/fundamental/daily_report.json"):
        report = _read_json(path)
        metadata = report["metadata"]
        market_date = _parse_market_date(metadata.get("as_of_date"))
        key = (str(metadata.get("generated_at", "")), str(metadata.get("run_id", "")))
        if market_date not in ordering or key > ordering[market_date]:
            reports[market_date] = report
            ordering[market_date] = key
    return reports


def _candidate_summary(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_code: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for day_index, report in enumerate(reports):
        for record in report["records"]:
            code = str(record.get("code", "")).zfill(6)
            if not code.strip("0"):
                continue
            by_code.setdefault(code, []).append((day_index, record))

    summaries: list[dict[str, Any]] = []
    for code, observations in by_code.items():
        latest = observations[-1][1]
        first = observations[0][1]
        ranks = [
            int(item.get("rank"))
            for _, item in observations
            if item.get("rank") is not None
        ]
        first_rank = first.get("rank")
        latest_rank = latest.get("rank")
        summaries.append(
            {
                "code": code,
                "name": str(latest.get("name") or first.get("name") or ""),
                "appearances": len(observations),
                "first_day_index": observations[0][0],
                "last_day_index": observations[-1][0],
                "first_rank": first_rank,
                "latest_rank": latest_rank,
                "best_rank": min(ranks) if ranks else None,
                "rank_improvement": (
                    int(first_rank) - int(latest_rank)
                    if first_rank is not None and latest_rank is not None
                    else None
                ),
                "latest_score": latest.get("final_score"),
                "latest_status": latest.get("status"),
                "focus_status": latest.get("focus_status"),
                "catalysts": latest.get("catalysts") or [],
                "risks": latest.get("risks") or [],
            }
        )
    return sorted(
        summaries,
        key=lambda item: (
            item["latest_rank"] is None,
            int(item["latest_rank"] or 10**9),
            -int(item["appearances"]),
            item["code"],
        ),
    )


def _render_markdown(report: dict[str, Any], top_n: int) -> str:
    metadata = report["metadata"]
    changes = report["changes"]
    lines = [
        "# A股上升周期周汇总报告",
        "",
        f"- 周编号：`{metadata['week_id']}`",
        f"- 日期范围：{metadata['start_date']} 至 {metadata['end_date']}",
        f"- 纳入交易日：{metadata['trading_days']}个",
        f"- 报告状态：`{metadata['status']}`",
        (
            f"- 日报完整度：完整{metadata['complete_days']}天，"
            f"部分完成{metadata['partial_days']}天"
        ),
        "",
        "## 市场结构",
        "",
        "| 日期 | 有效分析 | 5/5 | 4/5 | Layer2 | Layer3完成 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in report["market_series"]:
        lines.append(
            f"| {item['date']} | {item['successful']} | "
            f"{item['confirmed_5of5']} | {item['watchlist_4of5']} | "
            f"{item['layer2_count']} | {item['layer3_complete']} |"
        )
    lines.extend(
        [
            "",
            "## 候选变化",
            "",
            f"- 周末较周初新进入：{len(changes['entered'])}只",
            f"- 周末较周初退出：{len(changes['exited'])}只",
            f"- 周初至周末持续存在：{len(changes['persistent'])}只",
            "",
            "## 周末重点候选",
            "",
            "| 排名 | 代码 | 名称 | 入选天数 | 最佳排名 | 排名变化 | 最终分 | 状态 |",
            "|---:|---|---|---:|---:|---:|---:|---|",
        ]
    )
    latest = [
        item for item in report["candidates"] if item["last_day_index"] == metadata["trading_days"] - 1
    ][:top_n]
    if latest:
        for item in latest:
            change = item.get("rank_improvement")
            change_text = "—" if change is None else f"{change:+d}"
            lines.append(
                f"| {item.get('latest_rank') or '—'} | {item['code']} | "
                f"{item['name']} | {item['appearances']} | "
                f"{item.get('best_rank') or '—'} | {change_text} | "
                f"{item.get('latest_score') if item.get('latest_score') is not None else '—'} | "
                f"{item.get('focus_status') or item.get('latest_status') or '—'} |"
            )
    else:
        lines.append("| — | — | 周末没有Layer3候选 | — | — | — | — | — |")
    lines.extend(["", "## 周末较周初新进入", ""])
    if changes["entered"]:
        lines.extend(f"- `{item['code']}` {item['name']}" for item in changes["entered"])
    else:
        lines.append("- 无。")
    lines.extend(["", "## 周末较周初退出", ""])
    if changes["exited"]:
        lines.extend(f"- `{item['code']}` {item['name']}" for item in changes["exited"])
    else:
        lines.append("- 无。")
    lines.extend(
        [
            "",
            "---",
            "",
            "本周报由不可变日报快照聚合生成，不构成投资建议。",
        ]
    )
    return "\n".join(lines)


def _render_qq(report: dict[str, Any], top_n: int = 5) -> str:
    metadata = report["metadata"]
    changes = report["changes"]
    latest_market = report["market_series"][-1]
    lines = [
        f"【A股上升周期周报｜{metadata['week_id']}】",
        "",
        (
            f"纳入{metadata['trading_days']}个交易日｜"
            f"完整日报{metadata['complete_days']}天｜"
            f"部分日报{metadata['partial_days']}天"
        ),
        (
            f"周末结构：5/5 {latest_market['confirmed_5of5']}只｜"
            f"4/5 {latest_market['watchlist_4of5']}只｜"
            f"Layer2 {latest_market['layer2_count']}只"
        ),
        (
            f"候选变化：新进入{len(changes['entered'])}只｜"
            f"退出{len(changes['exited'])}只｜"
            f"持续{len(changes['persistent'])}只"
        ),
        "",
        "周末重点：",
    ]
    latest = [
        item for item in report["candidates"] if item["last_day_index"] == metadata["trading_days"] - 1
    ][:top_n]
    if not latest:
        lines.append("暂无完成排名的Layer3候选。")
    for item in latest:
        change = item.get("rank_improvement")
        change_text = "—" if change is None else f"{change:+d}"
        lines.append(
            f"{item.get('latest_rank') or '—'}. {item['code']} {item['name']}｜"
            f"入选{item['appearances']}天｜排名变化{change_text}"
        )
    lines.extend(["", "本周报为规则化研究汇总，不构成投资建议。"])
    return "\n".join(lines)


def generate_weekly_report(
    output_directory: Path,
    week: str | None = None,
    top_n: int = 10,
) -> tuple[Path, Path, dict[str, Any]]:
    if top_n < 1:
        raise ValueError("周报 top_n 必须至少为1")
    output_directory = output_directory.expanduser().resolve()
    available = _discover_daily_reports(output_directory)
    if not available:
        raise RuntimeError("尚无已生成的每日报告，无法生成周报")
    if week is None:
        latest = max(available)
        iso = latest.isocalendar()
        week = f"{iso.year}-W{iso.week:02d}"
    start, end = _week_bounds(week)
    selected_dates = sorted(day for day in available if start <= day <= end)
    if not selected_dates:
        raise RuntimeError(f"{week} 没有可用的每日报告")
    daily_reports = [available[day] for day in selected_dates]
    candidates = _candidate_summary(daily_reports)
    first_records = {str(item.get("code", "")).zfill(6): item for item in daily_reports[0]["records"]}
    latest_records = {str(item.get("code", "")).zfill(6): item for item in daily_reports[-1]["records"]}
    first_codes = set(first_records)
    latest_codes = set(latest_records)
    all_daily_sets = [
        {str(item.get("code", "")).zfill(6) for item in report["records"]}
        for report in daily_reports
    ]
    persistent_codes = set.intersection(*all_daily_sets) if all_daily_sets else set()

    def compact(code: str, source: dict[str, dict[str, Any]]) -> dict[str, str]:
        item = source[code]
        return {"code": code, "name": str(item.get("name", ""))}

    complete_days = sum(
        report["metadata"].get("status") == "complete" for report in daily_reports
    )
    report = {
        "metadata": {
            "schema_version": WEEKLY_REPORT_SCHEMA_VERSION,
            "week_id": week,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "status": "complete" if complete_days == len(daily_reports) else "partial",
            "trading_days": len(daily_reports),
            "complete_days": complete_days,
            "partial_days": len(daily_reports) - complete_days,
            "run_ids": [str(item["metadata"].get("run_id", "")) for item in daily_reports],
            "top_n": top_n,
        },
        "market_series": [
            {
                "date": day.isoformat(),
                "successful": int(report["metadata"].get("market_counts", {}).get("successful", 0)),
                "confirmed_5of5": int(report["metadata"].get("market_counts", {}).get("confirmed_5of5", 0)),
                "watchlist_4of5": int(report["metadata"].get("market_counts", {}).get("watchlist_4of5", 0)),
                "layer2_count": int(report["metadata"].get("layer2_count", 0)),
                "layer3_complete": int(report["metadata"].get("layer3_counts", {}).get("complete", 0)),
            }
            for day, report in zip(selected_dates, daily_reports)
        ],
        "changes": {
            "entered": [compact(code, latest_records) for code in sorted(latest_codes - first_codes)],
            "exited": [compact(code, first_records) for code in sorted(first_codes - latest_codes)],
            "persistent": [compact(code, latest_records) for code in sorted(persistent_codes)],
        },
        "candidates": candidates,
    }
    markdown = _render_markdown(report, top_n)
    qq_text = _render_qq(report)
    paths = write_publication_bundle(
        output_directory,
        "weekly",
        week,
        report,
        markdown,
        qq_text,
    )
    return paths["json"], paths["markdown"], report
