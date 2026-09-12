#!/usr/bin/env python3
"""依次更新本地行情库并执行全市场筛选。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from ..project_config import (
    PROJECT_DIR,
    resolve_database_path,
    resolve_output_path,
)

APP_DIR = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A 股筛选器 v1.2 每日运行入口")
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite数据库路径；省略时读取 config/project.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="结果目录；省略时读取 config/project.json",
    )
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--metadata-timeout", type=float, default=30.0)
    parser.add_argument("--tx-workers", type=int, default=6)
    parser.add_argument("--tx-timeout", type=float, default=15.0)
    parser.add_argument("--daily-per-minute", type=float, default=50.0)
    parser.add_argument("--adj-factor-per-minute", type=float, default=1.0)
    parser.add_argument("--token-env", default="TUSHARE_TOKEN")
    parser.add_argument("--env-file", type=Path, default=PROJECT_DIR / ".env")
    parser.add_argument("--percentile-cutoff", type=float, default=0.70)
    parser.add_argument("--include-st", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.db, db_source = resolve_database_path(args.db)
        args.output_dir, output_source = resolve_output_path(args.output_dir)
    except RuntimeError as exc:
        parser.error(str(exc))
    print(f"当前数据库：{db_source} → {args.db}", flush=True)
    print(f"当前结果目录：{output_source} → {args.output_dir}", flush=True)
    update_command = [
        sys.executable,
        str(APP_DIR / "update_market.py"),
        "--daily",
        "--db",
        str(args.db),
        "--retries",
        str(args.retries),
        "--metadata-timeout",
        str(args.metadata_timeout),
        "--tx-workers",
        str(args.tx_workers),
        "--tx-timeout",
        str(args.tx_timeout),
        "--daily-per-minute",
        str(args.daily_per_minute),
        "--adj-factor-per-minute",
        str(args.adj_factor_per_minute),
        "--token-env",
        args.token_env,
        "--env-file",
        str(args.env_file),
    ]
    screen_command = [
        sys.executable,
        str(APP_DIR / "screener_v1_2.py"),
        "--all",
        "--db",
        str(args.db),
        "--output-dir",
        str(args.output_dir),
        "--percentile-cutoff",
        str(args.percentile_cutoff),
    ]
    if args.include_st:
        screen_command.append("--include-st")

    print("第一步：更新本地行情库", flush=True)
    update_result = subprocess.run(update_command, cwd=PROJECT_DIR, check=False)
    if update_result.returncode != 0:
        print(
            "行情更新未完整成功，本次不会使用不完整数据生成新筛选结果。",
            file=sys.stderr,
        )
        return update_result.returncode

    print("第二步：从本地数据库扫描全市场", flush=True)
    screen_result = subprocess.run(screen_command, cwd=PROJECT_DIR, check=False)
    return screen_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
