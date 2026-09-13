#!/usr/bin/env python3
"""生成指定或最近一周的研究汇总报告。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..project_config import resolve_output_path
from ..services.weekly_report import generate_weekly_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从已生成的每日报告汇总周报"
    )
    parser.add_argument(
        "--week",
        default=None,
        help="ISO周编号 YYYY-Www；省略时使用最近日报所在周",
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
        help="周报最多展示多少只周末候选，默认10",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output_directory, output_source = resolve_output_path(args.output_dir)
        json_path, markdown_path, report = generate_weekly_report(
            output_directory,
            week=args.week,
            top_n=args.top_n,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"周报生成失败：{exc}", file=sys.stderr)
        return 2
    metadata = report["metadata"]
    print(f"结果目录：{output_source} → {output_directory}")
    print(
        f"周报：{metadata['week_id']}；纳入{metadata['trading_days']}个交易日；"
        f"状态：{metadata['status']}"
    )
    print(f"JSON周报：{json_path}")
    print(f"Markdown周报：{markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
