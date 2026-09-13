#!/usr/bin/env python3
"""为指定或最近一次运行生成Layer3每日研究报告。"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from ..analysis.history import load_latest_full_market
from ..project_config import resolve_output_path
from ..services.daily_report import generate_daily_report


RUN_ID_PATTERN = re.compile(r"^[0-9A-Za-z._-]+$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从Layer2和Layer3快照生成JSON与Markdown研究报告"
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="运行快照编号；省略时使用最近一次完整全市场运行",
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
            run_id, _ = load_latest_full_market(output_dir)
            if run_id is None:
                raise RuntimeError("尚无完整全市场运行，无法生成报告")
            auto_selected = True
        if not RUN_ID_PATTERN.fullmatch(str(run_id)):
            raise RuntimeError(f"运行编号格式无效：{run_id}")
        json_path, markdown_path, report = generate_daily_report(
            output_dir / "runs" / str(run_id),
            top_n=args.top_n,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
