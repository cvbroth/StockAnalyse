#!/usr/bin/env python3
"""依次更新本地行情库并执行全市场筛选。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DEFAULT_DB_PATH = PROJECT_DIR / "data" / "market.db"
DEFAULT_OUTPUT_PATH = PROJECT_DIR / "output"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A 股筛选器 v1.2 每日运行入口")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--token-env", default="TUSHARE_TOKEN")
    parser.add_argument("--percentile-cutoff", type=float, default=0.70)
    parser.add_argument("--include-st", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    update_command = [
        sys.executable,
        str(APP_DIR / "update_market.py"),
        "--daily",
        "--db",
        str(args.db),
        "--retries",
        str(args.retries),
        "--token-env",
        args.token_env,
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
