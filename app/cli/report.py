#!/usr/bin/env python3
"""为指定或最近一次运行生成Layer3每日研究报告。"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from ..analysis.history import find_latest_reportable_run
from ..project_config import resolve_output_path
from ..services.daily_report import generate_daily_report
from ..services.weekly_report import generate_weekly_report


RUN_ID_PATTERN = re.compile(r"^[0-9A-Za-z._-]+$")


def _report_week(as_of_date: str) -> str:
    for pattern in ("%Y%m%d", "%Y-%m-%d"):
        try:
            value = datetime.strptime(as_of_date, pattern).date().isocalendar()
            return f"{value.year}-W{value.week:02d}"
        except ValueError:
            continue
    raise RuntimeError(f"日报数据截止日期格式无效：{as_of_date!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从Layer2和Layer3快照生成JSON与Markdown研究报告"
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="运行快照编号；省略时使用最近一次具备Layer3结果的运行",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="结果目录；省略时读取 config/project.json",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="Markdown状态卡最多展示数量，默认10",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output_dir, output_source = resolve_output_path(args.output_dir)
        run_id = args.run_id
        auto_selected = False
        if run_id is None:
            run_id = find_latest_reportable_run(output_dir)
            if run_id is None:
                raise RuntimeError("尚无具备Layer3结果的运行，无法生成报告")
            auto_selected = True
        if not RUN_ID_PATTERN.fullmatch(str(run_id)):
            raise RuntimeError(f"运行编号格式无效：{run_id}")
        json_path, markdown_path, report = generate_daily_report(
            output_dir / "runs" / str(run_id),
            top_n=args.top_n,
        )
        weekly_json_path, weekly_markdown_path, weekly_report = (
            generate_weekly_report(
                output_dir,
                week=_report_week(str(report["metadata"]["as_of_date"])),
                top_n=args.top_n,
            )
        )
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"研究报告生成失败：{exc}", file=sys.stderr)
        return 2
    selection = "自动选择最近一次" if auto_selected else "命令行指定"
    counts = report["metadata"]["layer3_counts"]
    print(f"结果目录：{output_source} → {output_dir}")
    print(f"运行快照：{selection} → {run_id}")
    print(
        f"报告状态：{report['metadata']['status']}；"
        f"完成 {counts['complete']}，否决 {counts['rejected']}，"
        f"未完成 {counts['partial'] + counts['failed'] + counts['pending']}。"
    )
    print(f"JSON报告：{json_path}")
    print(f"Markdown报告：{markdown_path}")
    print(
        f"当周汇总：{weekly_report['metadata']['week_id']} "
        f"（{weekly_report['metadata']['trading_days']}个交易日）"
    )
    print(f"JSON周报：{weekly_json_path}")
    print(f"Markdown周报：{weekly_markdown_path}")
    print(f"统一报告中心：{output_dir / 'reports'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
