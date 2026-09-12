#!/usr/bin/env python3
"""A 股上升周期筛选器 v1.2：完全从本地 SQLite 读取行情。"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from market_db import (
    connect_database,
    database_stats,
    load_index_bars,
    load_recent_daily_bars,
    load_securities,
)
from screener_v1_1 import (
    ScreenConfig,
    analyze_stock,
    apply_market_percentiles,
    mark_percentile_not_required,
    normalize_code,
    refresh_score,
    write_outputs,
)


VERSION = "1.2"
HS300_SYMBOL = "sh000300"
APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DEFAULT_DB_PATH = PROJECT_DIR / "data" / "market.db"
DEFAULT_OUTPUT_PATH = PROJECT_DIR / "output"


def prepare_qfq_bars(raw: pd.DataFrame) -> pd.DataFrame:
    """使用数据库中的原始价格和复权因子动态生成前复权行情。"""

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


def permit_database_market(record: dict[str, Any], market: str) -> None:
    """v1.2 的 Tushare 数据支持沪深京，不再套用腾讯个股市场限制。"""

    tests = record["base_filters"]["tests"]
    tests["supported_market"] = market in {"SH", "SZ", "BJ"}
    record["base_filters"]["passed"] = all(bool(value) for value in tests.values())
    record["market"] = market
    record["data_source"] = "sqlite_tushare_raw_plus_adj_factor"
    refresh_score(record)


def parse_yyyymmdd(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期必须是 YYYYMMDD 格式") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="A 股上升周期筛选器 v1.2（SQLite 本地行情版）"
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
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite 数据库路径"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_PATH, help="输出目录"
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
        default=0.70,
        help="全市场百分位门槛，0.70 表示前 30%%",
    )
    parser.add_argument(
        "--min-history-days", type=int, default=120, help="个股最少历史交易日"
    )
    parser.add_argument(
        "--min-average-volume-lots",
        type=float,
        default=0.0,
        help="近20日最低日均成交量（手）",
    )
    parser.add_argument(
        "--max-stale-calendar-days",
        type=int,
        default=10,
        help="最近交易日距离截面日期的最大自然日数",
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
    if args.history_dates < 80:
        parser.error("--history-dates 至少为 80，建议使用 250")
    if args.min_history_days < 80:
        parser.error("--min-history-days 至少为 80")
    if args.history_dates < args.min_history_days:
        parser.error("--history-dates 不能小于 --min-history-days")
    if not 0 < args.percentile_cutoff <= 1:
        parser.error("--percentile-cutoff 必须位于 (0, 1] 区间")
    if args.min_average_volume_lots < 0:
        parser.error("--min-average-volume-lots 不能为负数")
    if args.max_stale_calendar_days < 0:
        parser.error("--max-stale-calendar-days 不能为负数")
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


def run_screen(args: argparse.Namespace) -> int:
    connection = connect_database(args.db)
    try:
        stats = database_stats(connection)
        if stats["daily_rows"] == 0:
            print(
                "本地行情库为空。请先执行："
                "python app/update_market.py --init --days 250",
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
    config = ScreenConfig(
        min_history_days=args.min_history_days,
        market_percentile_cutoff=args.percentile_cutoff,
        max_stale_calendar_days=args.max_stale_calendar_days,
        min_average_volume_lots=args.min_average_volume_lots,
        exclude_st=not args.include_st,
    )

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
            permit_database_market(record, market)
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

    metadata = {
        "screener": "A 股上升周期筛选器",
        "version": VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": "all" if args.all else "symbols",
        "end_date": analysis_end,
        "stock_data_source": "SQLite: Tushare raw daily + adj_factor -> dynamic qfq",
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
            "由本地数据库成功分析股票的60日收益计算全市场百分位"
            if percentile_is_full_market
            else (
                "使用 --limit，排名只覆盖受限集合，不代表全市场"
                if args.all
                else "小样本模式不计算、也不强制市场百分位"
            )
        ),
        "config": asdict(config),
    }
    write_outputs(args.output_dir.resolve(), records, errors, metadata)

    confirmed = sum(bool(record["technical_pass"]) for record in records)
    watchlist = sum(
        bool(record["base_filters"]["passed"])
        and record["technical_score"] == 4
        for record in records
    )
    print("本地扫描完成。")
    print(f"成功分析：{len(records)}；失败/跳过：{len(errors)}")
    print(f"5/5 技术确认：{confirmed}；4/5 观察池：{watchlist}")
    if args.all:
        scope = "全市场" if percentile_is_full_market else "受限集合"
        print(f"60 日收益百分位：{scope}，有效样本 {percentile_universe_size}")
    else:
        print("60 日收益百分位：N/A（小样本模式不强制）")
    print(f"结果目录：{args.output_dir.resolve()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(args, parser)
    return run_screen(args)


if __name__ == "__main__":
    raise SystemExit(main())
