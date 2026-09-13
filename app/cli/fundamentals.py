#!/usr/bin/env python3
"""从既有Layer2快照按需同步并量化基本面数据。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..analysis.history import load_latest_full_market, load_run_layer2
from ..fundamentals import (
    DEFAULT_FUNDAMENTAL_CONFIG_PATH,
    load_fundamental_settings,
)
from ..project_config import (
    resolve_fundamental_database_path,
    resolve_output_path,
)
from ..providers.fundamentals import AkshareThsFundamentalProvider
from ..services.fundamental_analysis import analyze_cached_fundamentals
from ..services.fundamental_sync import (
    prepare_fundamental_requests,
    select_fundamental_candidates,
    synchronize_fundamental_candidates,
    write_json_atomic,
)
from ..storage.fundamentals_sqlite import (
    connect_fundamental_database,
    fundamental_database_stats,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="按需同步Layer2候选的最近八季度财务数据并生成量化结果",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
典型用法：
  python -m app.cli.screen --all
  python -m app.cli.fundamentals

省略 --run-id 时自动使用最近一次成功的全市场扫描。只有分析指定历史快照时才需：
  python -m app.cli.fundamentals --run-id 20260911-153000123456

只检查将要处理的候选，不访问财务接口：
  python -m app.cli.fundamentals --prepare-only
""",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help=(
            "全市场扫描快照编号；对应 output/runs/<编号>/。"
            "省略时自动选择最近一次成功扫描"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="结果目录；省略时读取 config/project.json",
    )
    parser.add_argument(
        "--fundamental-db",
        type=Path,
        default=None,
        help="独立基本面SQLite路径；省略时读取项目配置",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_FUNDAMENTAL_CONFIG_PATH,
        help="基本面TOML配置路径",
    )
    parser.add_argument("--top-n", type=int, default=None, help="覆盖候选数量")
    parser.add_argument("--quarters", type=int, default=None, help="覆盖季度数量")
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="只生成请求并初始化缓存，不访问真实财务接口",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="公告日期请求超时秒数；财务摘要超时由AKShare内部控制",
    )
    parser.add_argument("--retries", type=int, default=3, help="单只股票失败重试次数")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output_dir, output_source = resolve_output_path(args.output_dir)
        run_id = args.run_id
        auto_selected_run = False
        if run_id is None:
            run_id, _ = load_latest_full_market(output_dir)
            if run_id is None:
                raise RuntimeError(
                    "尚无完整全市场运行。请先执行：python -m app.cli.screen --all"
                )
            auto_selected_run = True
        database, database_source = resolve_fundamental_database_path(
            args.fundamental_db
        )
        settings = load_fundamental_settings(args.config)
        top_n = (
            args.top_n
            if args.top_n is not None
            else settings.collection.financial_top_n
        )
        quarters = (
            args.quarters
            if args.quarters is not None
            else settings.collection.quarters
        )
        if top_n < 1 or quarters < 1:
            raise RuntimeError("top-n 和 quarters 必须至少为1")
        manifest, records = load_run_layer2(output_dir, run_id)
        as_of_date = str(manifest["end_date"])
        requests = select_fundamental_candidates(
            records,
            run_id=run_id,
            as_of_date=as_of_date,
            top_n=top_n,
            quarters=quarters,
        )
        connection = connect_fundamental_database(database)
        try:
            request_path = prepare_fundamental_requests(
                connection,
                requests,
                output_dir / "runs" / run_id,
                config_version=settings.version,
                provider=settings.provider,
                run_id=run_id,
                as_of_date=as_of_date,
            )
            sync_summary = None
            analysis_path = None
            analysis_records: list[dict] = []
            if settings.enabled and not args.prepare_only:
                if settings.provider != "akshare_ths":
                    raise RuntimeError(
                        f"尚未实现基本面提供者：{settings.provider}"
                    )
                provider = AkshareThsFundamentalProvider(
                    timeout=args.timeout,
                    retries=args.retries,
                )
                sync_summary = synchronize_fundamental_candidates(
                    connection,
                    provider,
                    requests,
                    settings.collection.stale_after_days,
                )
                summary_path = (
                    output_dir
                    / "runs"
                    / run_id
                    / "fundamental"
                    / "sync_summary.json"
                )
                write_json_atomic(summary_path, sync_summary)
                analysis_path, analysis_records = analyze_cached_fundamentals(
                    connection,
                    requests,
                    output_dir / "runs" / run_id,
                    provider=settings.provider,
                    config_version=settings.version,
                )
            stats = fundamental_database_stats(connection)
        finally:
            connection.close()
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        print(f"基本面请求准备失败：{exc}", file=sys.stderr)
        return 2

    print(f"结果目录：{output_source} → {output_dir}")
    selection = "自动选择最近一次" if auto_selected_run else "命令行指定"
    print(f"运行快照：{selection} → {run_id}（数据截止 {as_of_date}）")
    print(f"基本面数据库：{database_source} → {database}")
    print(f"候选准备完成：{len(requests)}只；每只请求最近{quarters}个季度。")
    print(f"请求文件：{request_path}")
    print(
        f"稀疏缓存范围：{stats['candidate_codes']}只；"
        f"已存观测值：{stats['observations']}条。"
    )
    if args.prepare_only or not settings.enabled:
        print("本次只登记需求，不访问真实财务接口。")
    elif sync_summary is not None:
        print(
            f"财务同步：获取 {sync_summary['fetched']}，"
            f"复用缓存 {sync_summary['cached']}，失败 {sync_summary['failed']}，"
            f"写入 {sync_summary['observations_written']} 条观测值。"
        )
        complete = sum(
            item["financial_quant"]["status"] == "complete"
            for item in analysis_records
        )
        partial = sum(
            item["financial_quant"]["status"] == "partial"
            for item in analysis_records
        )
        print(f"财务量化：完整 {complete}，部分 {partial}，结果 {analysis_path}")
        if requests and sync_summary["failed"] == len(requests):
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
