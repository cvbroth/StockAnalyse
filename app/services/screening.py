#!/usr/bin/env python3
"""A 股上升周期筛选器 v1.3：分层分析与历史追踪。"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..analysis import (
    ScreenConfig,
    analyze_stock,
    analysis_config_hash,
    apply_transitions,
    apply_screen_overrides,
    apply_market_percentiles,
    create_run_id,
    load_layer1_config,
    load_layer2_config,
    load_latest_full_market,
    load_run_snapshot,
    mark_percentile_not_required,
    normalize_code,
    refresh_score,
    rank_layer2_records,
    write_outputs,
    write_run_snapshot,
)
from ..storage.sqlite import (
    connect_database,
    database_quality_report,
    database_stats,
    load_index_bars,
    load_recent_daily_bars,
    load_securities,
)
from ..project_config import (
    PROJECT_DIR,
    resolve_database_path,
    resolve_output_path,
)


VERSION = "1.3"
HS300_SYMBOL = "sh000300"
APP_DIR = Path(__file__).resolve().parent


def prepare_qfq_bars(raw: pd.DataFrame) -> pd.DataFrame:
    """统一生成前复权行情；腾讯成品前复权数据的因子固定为 1。"""

    required = {
        "code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adj_factor",
    }
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"数据库日线缺少字段：{sorted(missing)}")
    if raw.empty:
        return pd.DataFrame()

    frame = raw.copy()
    frame["code"] = frame["code"].astype(str).str.zfill(6)
    frame["date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume", "adj_factor"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(
        subset=["code", "date", "open", "high", "low", "close", "volume", "adj_factor"]
    )
    frame = frame[
        (frame["close"] > 0)
        & (frame["volume"] >= 0)
        & (frame["adj_factor"] > 0)
    ]
    frame = frame.sort_values(["code", "date"]).drop_duplicates(
        ["code", "date"], keep="last"
    )
    latest_factor = frame.groupby("code", sort=False)["adj_factor"].transform("last")
    adjustment_ratio = frame["adj_factor"] / latest_factor
    for column in ("open", "high", "low", "close"):
        frame[column] = frame[column] * adjustment_ratio
    return frame[
        ["code", "date", "open", "close", "high", "low", "volume"]
    ].reset_index(drop=True)


def prepare_benchmark(raw: pd.DataFrame) -> pd.DataFrame:
    required = {"trade_date", "open", "high", "low", "close", "volume"}
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"数据库指数行情缺少字段：{sorted(missing)}")
    frame = raw.copy()
    frame["date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(
        subset=["date", "open", "high", "low", "close", "volume"]
    )
    frame = frame[(frame["close"] > 0) & (frame["volume"] >= 0)]
    return (
        frame.sort_values("date")
        .drop_duplicates("date", keep="last")
        [["date", "open", "close", "high", "low", "volume"]]
        .reset_index(drop=True)
    )


def permit_database_market(
    record: dict[str, Any],
    market: str,
    provider: str | None,
) -> None:
    """数据库适配层统一允许沪深京，并标记实际初始化数据源。"""

    tests = record["base_filters"]["tests"]
    tests["supported_market"] = market in {"SH", "SZ", "BJ"}
    record["base_filters"]["passed"] = all(bool(value) for value in tests.values())
    record["market"] = market
    record["data_source"] = (
        "sqlite_tencent_qfq"
        if provider == "tx"
        else "sqlite_tushare_raw_plus_adj_factor"
    )
    refresh_score(record)


def parse_yyyymmdd(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期必须是 YYYYMMDD 格式") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="A 股上升周期筛选器 v1.3（分层分析版）"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--all", action="store_true", help="扫描数据库内全部 A 股并计算市场百分位"
    )
    mode.add_argument(
        "--symbols",
        nargs="+",
        metavar="代码",
        help="小样本检查模式；不计算、不强制样本内百分位",
    )
    mode.add_argument(
        "--from-layer",
        type=int,
        choices=(2,),
        metavar="N",
        help="从已有快照的第N层重新运行；当前支持2",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite 数据库路径；省略时读取 config/project.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="输出目录；省略时读取 config/project.json",
    )
    parser.add_argument(
        "--analysis-config",
        type=Path,
        default=None,
        help="第一层TOML配置路径；默认 config/analysis/layer1.toml",
    )
    parser.add_argument(
        "--quality-config",
        type=Path,
        default=None,
        help="第二层TOML评分配置；默认 config/analysis/layer2.toml",
    )
    parser.add_argument(
        "--run-id",
        help="与 --from-layer 配合使用的历史运行编号",
    )
    parser.add_argument(
        "--end-date", type=parse_yyyymmdd, help="历史截面日期 YYYYMMDD；默认数据库最新日期"
    )
    parser.add_argument(
        "--history-dates",
        type=int,
        default=250,
        help="从数据库读取最近 N 个市场交易日",
    )
    parser.add_argument(
        "--percentile-cutoff",
        type=float,
        default=None,
        help="覆盖配置中的全市场百分位门槛；0.70 表示前30%%",
    )
    parser.add_argument(
        "--min-history-days", type=int, default=None, help="覆盖配置中的个股最少历史交易日"
    )
    parser.add_argument(
        "--min-average-volume-lots",
        type=float,
        default=None,
        help="覆盖配置中的近20日最低日均成交量（手）",
    )
    parser.add_argument(
        "--max-stale-calendar-days",
        type=int,
        default=None,
        help="覆盖配置中的最大行情陈旧自然日数",
    )
    parser.add_argument("--include-st", action="store_true", help="允许 ST/*ST 股票")
    parser.add_argument(
        "--limit",
        type=int,
        help="仅扫描前 N 只用于调试；此时 --all 排名不代表全市场",
    )
    parser.add_argument(
        "--progress-every", type=int, default=500, help="每处理 N 只显示一次进度"
    )
    return parser


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.from_layer is not None and not args.run_id:
        parser.error("--from-layer 必须同时提供 --run-id")
    if args.from_layer is None and args.run_id:
        parser.error("--run-id 只能与 --from-layer 一起使用")
    if args.history_dates < 80:
        parser.error("--history-dates 至少为 80，建议使用 250")
    if args.history_dates < args.screen_config.min_history_days:
        parser.error("--history-dates 不能小于 --min-history-days")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit 至少为 1")
    if args.progress_every < 0:
        parser.error("--progress-every 不能为负数")


def resolve_requested_codes(args: argparse.Namespace) -> list[str] | None:
    if args.all:
        return None
    seen: set[str] = set()
    result: list[str] = []
    for raw_code in args.symbols:
        code = normalize_code(raw_code)
        if code not in seen:
            seen.add(code)
            result.append(code)
    return result


def rerun_layer2(args: argparse.Namespace) -> int:
    try:
        parent_manifest, records = load_run_snapshot(
            args.output_dir.resolve(),
            args.run_id,
        )
        rank_layer2_records(records, args.layer2_config)
        end_date = str(parent_manifest["end_date"])
        parent_config_values = parent_manifest.get("config")
        if not isinstance(parent_config_values, dict):
            raise RuntimeError("父运行缺少第一层完整配置，不能安全重跑第二层")
        parent_layer1_config = ScreenConfig(**parent_config_values)
        run_id = create_run_id(end_date)
        metadata = {
            **parent_manifest,
            "run_id": run_id,
            "parent_run_id": args.run_id,
            "mode": "layer2_rerun",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "layer2_config_version": args.layer2_config_version,
            "layer2_config_path": str(args.quality_config),
            "analysis_config_hash": analysis_config_hash(
                parent_layer1_config,
                args.layer2_config,
            ),
            "quality_confirmed_top_n": args.layer2_config.confirmed_top_n,
            "quality_watchlist_top_n": args.layer2_config.watchlist_top_n,
        }
        run_dir = write_run_snapshot(
            args.output_dir.resolve(),
            run_id,
            records,
            metadata,
            update_latest=False,
        )
        reports_dir = run_dir / "reports"
        write_outputs(reports_dir, records, [], metadata)
    except Exception as exc:
        print(f"第二层重跑失败：{exc}", file=sys.stderr)
        return 2
    print(f"第二层重跑完成；父运行：{args.run_id}")
    print(f"研究结果：{reports_dir}")
    print("本次研究重跑不会替换每日全市场最新运行指针。")
    return 0


def run_screen(args: argparse.Namespace) -> int:
    if args.from_layer == 2:
        return rerun_layer2(args)
    connection = connect_database(args.db)
    try:
        stats = database_stats(connection)
        quality = database_quality_report(
            connection,
            args.screen_config.min_history_days,
        )
        provider_labels = {
            "tx": "腾讯前复权（沪深）",
            "tushare": "Tushare原始日线+复权因子（沪深京）",
            "mixed": "混合来源（禁止分析）",
            None: "尚未初始化",
        }
        print(f"当前数据库：{args.db}", flush=True)
        print(
            f"数据库数据源：{provider_labels.get(stats['data_provider'], stats['data_provider'])}",
            flush=True,
        )
        print(
            f"数据范围：{stats['daily_start']} ～ {stats['daily_end']}；"
            f"日线 {stats['daily_rows']} 行；沪深300 {stats['index_rows']} 日。",
            flush=True,
        )
        for message in quality["warnings"]:
            print(f"数据库警告：{message}", file=sys.stderr, flush=True)
        if not quality["passed"]:
            print("数据库质量检查未通过，已停止筛选：", file=sys.stderr)
            for message in quality["errors"]:
                print(f"  - {message}", file=sys.stderr)
            print(
                "请先执行 python app/update_market.py --status 查看状态，"
                "再继续或重新初始化。",
                file=sys.stderr,
            )
            return 2
        if stats["daily_rows"] == 0:
            print(
                "本地行情库为空。请先执行："
                "python app/update_market.py --init --tx --days 250，或选择 --tushare",
                file=sys.stderr,
            )
            return 2

        requested_codes = resolve_requested_codes(args)
        securities = load_securities(connection)
        raw_bars = load_recent_daily_bars(
            connection,
            max_dates=args.history_dates,
            end_date=args.end_date,
            codes=requested_codes,
        )
        raw_index = load_index_bars(
            connection,
            symbol=HS300_SYMBOL,
            max_dates=args.history_dates,
            end_date=args.end_date,
        )
    finally:
        connection.close()

    if raw_bars.empty:
        print("指定范围内没有个股行情。", file=sys.stderr)
        return 2
    if raw_index.empty:
        print("数据库中没有沪深300行情，请先运行 update_market.py。", file=sys.stderr)
        return 2

    try:
        bars = prepare_qfq_bars(raw_bars)
        benchmark = prepare_benchmark(raw_index)
    except Exception as exc:
        print(f"本地行情预处理失败：{exc}", file=sys.stderr)
        return 2

    if len(benchmark) < 61:
        print(f"沪深300历史不足 61 日，实际 {len(benchmark)} 日。", file=sys.stderr)
        return 2

    available_end = min(bars["date"].max(), benchmark["date"].max())
    analysis_end = args.end_date or pd.Timestamp(available_end).strftime("%Y%m%d")
    names = (
        securities.set_index("code")["name"].astype(str).to_dict()
        if not securities.empty
        else {}
    )
    markets = (
        securities.set_index("code")["market"].astype(str).to_dict()
        if not securities.empty
        else {}
    )

    grouped_bars = bars.groupby("code", sort=False)
    scan_codes = sorted(bars["code"].astype(str).unique().tolist())
    if args.limit is not None:
        scan_codes = scan_codes[: args.limit]
    config: ScreenConfig = args.screen_config

    print(
        f"本地扫描开始：{len(scan_codes)} 只，截面日期 {analysis_end}，"
        f"数据库 {args.db.expanduser().resolve()}",
        flush=True,
    )
    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for position, code in enumerate(scan_codes, start=1):
        group = grouped_bars.get_group(code)
        name = names.get(code, "未知名称")
        market = markets.get(code)
        if market is None:
            market = "SH" if code.startswith("6") else (
                "SZ" if code.startswith(("0", "3")) else "BJ"
            )
        try:
            stock_frame = group[
                ["date", "open", "close", "high", "low", "volume"]
            ].reset_index(drop=True)
            record = analyze_stock(
                code,
                name,
                stock_frame,
                benchmark,
                analysis_end,
                config,
            )
            permit_database_market(record, market, stats["data_provider"])
            records.append(record)
        except Exception as exc:
            errors.append({"code": code, "name": name, "error": str(exc)})
        if args.progress_every and (
            position % args.progress_every == 0 or position == len(scan_codes)
        ):
            print(
                f"进度 {position}/{len(scan_codes)}，成功 {len(records)}，"
                f"失败/跳过 {len(errors)}",
                flush=True,
            )

    if not records:
        print("没有股票完成分析，请查看历史长度和数据库状态。", file=sys.stderr)
        return 2

    percentile_universe_size: int | None = None
    percentile_is_full_market = bool(args.all and args.limit is None)
    try:
        if args.all:
            percentile_universe_size = apply_market_percentiles(
                records, config.market_percentile_cutoff
            )
        else:
            mark_percentile_not_required(records)
    except Exception as exc:
        print(f"百分位计算失败：{exc}", file=sys.stderr)
        return 2

    try:
        rank_layer2_records(records, args.layer2_config)
    except Exception as exc:
        print(f"第二层质量评分失败：{exc}", file=sys.stderr)
        return 2

    canonical_full_market = bool(args.all and args.limit is None)
    previous_run_id: str | None = None
    previous_records: list[dict[str, Any]] = []
    if canonical_full_market:
        try:
            previous_run_id, previous_records = load_latest_full_market(
                args.output_dir.resolve()
            )
        except RuntimeError as exc:
            print(f"历史运行状态读取失败：{exc}", file=sys.stderr)
            return 2
    transition_counts = apply_transitions(
        records,
        previous_records,
        previous_run_id,
    )
    run_id = create_run_id(analysis_end)

    market_scope = "沪深" if stats["data_provider"] == "tx" else "沪深京"
    stock_data_source = (
        "SQLite: AKShare Tencent qfq"
        if stats["data_provider"] == "tx"
        else "SQLite: Tushare raw daily + adj_factor -> dynamic qfq"
    )
    metadata = {
        "screener": "A 股上升周期筛选器",
        "version": VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_id": run_id,
        "previous_run_id": previous_run_id,
        "transition_counts": transition_counts,
        "mode": "all" if args.all else "symbols",
        "end_date": analysis_end,
        "stock_data_source": stock_data_source,
        "database_provider": stats["data_provider"],
        "market_scope": market_scope,
        "benchmark_data_source": "SQLite: AKShare Tencent sh000300",
        "database": str(args.db.expanduser().resolve()),
        "database_daily_start": stats["daily_start"],
        "database_daily_end": stats["daily_end"],
        "requested_count": len(scan_codes),
        "successful_count": len(records),
        "error_count": len(errors),
        "percentile_required": bool(args.all),
        "percentile_is_full_market": percentile_is_full_market,
        "percentile_universe_size": percentile_universe_size,
        "percentile_note": (
            f"由本地数据库成功分析股票的60日收益计算{market_scope}市场百分位"
            if percentile_is_full_market
            else (
                "使用 --limit，排名只覆盖受限集合，不代表全市场"
                if args.all
                else "小样本模式不计算、也不强制市场百分位"
            )
        ),
        "layer1_config_version": args.layer1_config_version,
        "layer1_config_path": str(args.analysis_config),
        "layer2_config_version": args.layer2_config_version,
        "layer2_config_path": str(args.quality_config),
        "analysis_config_hash": analysis_config_hash(config, args.layer2_config),
        "quality_confirmed_top_n": args.layer2_config.confirmed_top_n,
        "quality_watchlist_top_n": args.layer2_config.watchlist_top_n,
        "config": asdict(config),
    }
    write_outputs(args.output_dir.resolve(), records, errors, metadata)
    snapshot_dir: Path | None = None
    if canonical_full_market:
        try:
            snapshot_dir = write_run_snapshot(
                args.output_dir.resolve(),
                run_id,
                records,
                metadata,
                update_latest=True,
            )
        except Exception as exc:
            print(f"运行快照保存失败：{exc}", file=sys.stderr)
            return 2

    confirmed = sum(bool(record["technical_pass"]) for record in records)
    watchlist = sum(
        bool(record["base_filters"]["passed"])
        and record["technical_score"] == 4
        for record in records
    )
    print("本地扫描完成。")
    print(f"成功分析：{len(records)}；失败/跳过：{len(errors)}")
    print(f"5/5 技术确认：{confirmed}；4/5 观察池：{watchlist}")
    print(
        f"第二层质量排名：A池展示Top {args.layer2_config.confirmed_top_n}；"
        f"B池展示Top {args.layer2_config.watchlist_top_n}"
    )
    if canonical_full_market:
        print(
            f"状态变化：新进入5/5 {transition_counts.get('newly_5of5', 0)}；"
            f"退回4/5 {transition_counts.get('downgraded_to_4of5', 0)}"
        )
    if args.all:
        scope = f"{market_scope}全市场" if percentile_is_full_market else "受限集合"
        print(f"60 日收益百分位：{scope}，有效样本 {percentile_universe_size}")
    else:
        print("60 日收益百分位：N/A（小样本模式不强制）")
    print(f"结果目录：{args.output_dir.resolve()}")
    if snapshot_dir is not None:
        print(f"运行快照：{snapshot_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.db, args.db_source = resolve_database_path(args.db)
        args.output_dir, args.output_source = resolve_output_path(args.output_dir)
        loaded_config = load_layer1_config(args.analysis_config)
        loaded_layer2 = load_layer2_config(args.quality_config)
        args.screen_config = apply_screen_overrides(
            loaded_config.screen,
            min_history_days=args.min_history_days,
            market_percentile_cutoff=args.percentile_cutoff,
            max_stale_calendar_days=args.max_stale_calendar_days,
            min_average_volume_lots=args.min_average_volume_lots,
            exclude_st=False if args.include_st else None,
        )
        args.analysis_config = loaded_config.path
        args.layer1_config_version = loaded_config.version
        args.layer2_config = loaded_layer2.quality
        args.quality_config = loaded_layer2.path
        args.layer2_config_version = loaded_layer2.version
    except (RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    validate_args(args, parser)
    print(f"数据库选择：{args.db_source} → {args.db}", flush=True)
    print(f"结果目录：{args.output_source} → {args.output_dir}", flush=True)
    print(
        f"第一层配置：{args.layer1_config_version} → {args.analysis_config}",
        flush=True,
    )
    print(
        f"第二层配置：{args.layer2_config_version} → {args.quality_config}",
        flush=True,
    )
    return run_screen(args)


if __name__ == "__main__":
    raise SystemExit(main())
    create_run_id,
    load_latest_full_market,
