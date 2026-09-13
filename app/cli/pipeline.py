#!/usr/bin/env python3
"""执行或续跑完整的每日筛选、研究与报告流水线。"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from ..project_config import resolve_database_path, resolve_output_path
from ..services.daily_pipeline import DailyPipeline


RUN_ID_PATTERN = re.compile(r"^[0-9A-Za-z._-]+$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="更新行情、全市场筛选、财务同步、OpenClaw研究并生成报告"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="从 pipeline_state.json 中最后一个未完成阶段继续",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="使用已有快照并跳过行情更新和技术筛选",
    )
    parser.add_argument("--db", type=Path, default=None, help="行情数据库路径")
    parser.add_argument(
        "--output-dir", type=Path, default=None, help="结果目录"
    )
    parser.add_argument(
        "--skip-research",
        action="store_true",
        help="跳过OpenClaw，仅生成pending/partial报告",
    )
    parser.add_argument(
        "--report-top-n",
        type=int,
        default=10,
        help="Markdown报告最多展示的状态卡数量，默认10",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.run_id is not None and not RUN_ID_PATTERN.fullmatch(args.run_id):
            raise RuntimeError(f"运行编号格式无效：{args.run_id}")
        database, database_source = resolve_database_path(args.db)
        output_directory, output_source = resolve_output_path(args.output_dir)
        if args.run_id is not None:
            manifest = output_directory / "runs" / args.run_id / "manifest.json"
            if not manifest.is_file():
                raise RuntimeError(
                    f"运行快照不存在或缺少 manifest.json：{args.run_id}"
                )
        pipeline = DailyPipeline(
            database,
            output_directory,
            report_top_n=args.report_top_n,
        )
        return_code, state = pipeline.run(
            resume=args.resume,
            run_id=args.run_id,
            skip_research=args.skip_research,
        )
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"每日流水线执行失败：{exc}", file=sys.stderr)
        return 2
    print(f"行情数据库：{database_source} → {database}")
    print(f"结果目录：{output_source} → {output_directory}")
    print(f"流水线状态：{state['status']}；运行编号：{state.get('run_id')}")
    print(f"状态文件：{pipeline.state_path}")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
