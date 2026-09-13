#!/usr/bin/env python3
"""评估历史运行在未来20/60个交易日的表现。"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..analysis.evaluation import (
    evaluate_forward_performance,
    flatten_evaluation_records,
)
from ..analysis.history import load_run_layer2
from ..analysis.outputs import write_json
from ..project_config import resolve_database_path, resolve_output_path
from ..storage.sqlite import connect_database, load_daily_bars_range


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="历史技术评分向前表现评估")
    parser.add_argument("--run-id", required=True, help="需要评估的运行编号")
    parser.add_argument("--db", type=Path, help="SQLite数据库路径")
    parser.add_argument("--output-dir", type=Path, help="历史运行所在结果目录")
    parser.add_argument(
        "--horizons",
        type=int,
        nargs="+",
        default=[20, 60],
        metavar="N",
        help="向前评估的交易日周期，默认20和60",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if any(value < 1 for value in args.horizons):
        parser.error("--horizons 必须全部为正整数")
    try:
        database, _ = resolve_database_path(args.db)
        output_dir, _ = resolve_output_path(args.output_dir)
        manifest, records = load_run_layer2(output_dir, args.run_id)
        if not records:
            raise RuntimeError("该运行没有可评估的A池或B池股票")
        start_date = str(manifest["end_date"]).replace("-", "")
        connection = connect_database(database)
        try:
            bars = load_daily_bars_range(
                connection,
                start_date=start_date,
                codes=[record["code"] for record in records],
            )
        finally:
            connection.close()
        report = evaluate_forward_performance(
            records,
            bars,
            tuple(sorted(set(args.horizons))),
        )
        report["metadata"] = {
            "run_id": args.run_id,
            "database": str(database.resolve()),
            "evaluated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        if not any(report["completed_by_horizon"].values()):
            raise RuntimeError("数据库尚无足够的运行日后行情，暂时不能完成评估")
        run_dir = output_dir / "runs" / args.run_id
        write_json(run_dir / "evaluation.json", report)
        pd.DataFrame(flatten_evaluation_records(report)).to_csv(
            run_dir / "evaluation.csv",
            index=False,
            encoding="utf-8-sig",
        )
    except Exception as exc:
        print(f"历史评分评估失败：{exc}", file=sys.stderr)
        return 2
    print(f"历史评分评估完成：{run_dir / 'evaluation.json'}")
    for horizon, count in report["completed_by_horizon"].items():
        print(f"未来{horizon}个交易日：有效样本{count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
