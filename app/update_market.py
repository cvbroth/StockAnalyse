#!/usr/bin/env python3
"""批量更新 A 股本地行情库。

首次初始化：

    python app/update_market.py --init --days 250

以后每个交易日收盘后：

    python app/update_market.py --daily

环境变量 ``TUSHARE_TOKEN`` 必须包含有效的 Tushare token。个股日线和
复权因子按交易日批量获取；股票名称及沪深300交易日历使用 AKShare 腾讯链路。
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from market_db import (
    completed_trade_dates,
    connect_database,
    database_stats,
    finish_update_run,
    set_trade_date_status,
    start_update_run,
    upsert_daily_bars,
    upsert_index_bars,
    upsert_securities,
)


HS300_SYMBOL = "sh000300"
APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DEFAULT_DB_PATH = PROJECT_DIR / "data" / "market.db"


def call_with_retries(
    label: str,
    operation: Callable[[], Any],
    retries: int,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                wait_seconds = min(20.0, 1.5 * (2 ** (attempt - 1)))
                print(
                    f"{label} 第 {attempt} 次失败，{wait_seconds:.1f} 秒后重试：{exc}",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(wait_seconds)
    raise RuntimeError(f"{label} 获取失败（已重试 {retries} 次）：{last_error}")


def normalize_code(raw: Any) -> str:
    code = str(raw).strip().upper()
    if "." in code:
        code = code.split(".", 1)[0]
    if code.lower().startswith(("sh", "sz", "bj")):
        code = code[2:]
    if code.endswith(".0") and code[:-2].isdigit():
        code = code[:-2]
    if not code.isdigit():
        raise ValueError(f"无效股票代码：{raw!r}")
    return code.zfill(6)


def fetch_stock_list(retries: int) -> list[tuple[str, str]]:
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError(
            "缺少 akshare，请执行：python -m pip install -U akshare"
        ) from exc

    raw = call_with_retries(
        "A股股票列表", ak.stock_info_a_code_name, retries
    )
    if raw is None or raw.empty:
        raise RuntimeError("stock_info_a_code_name() 返回空数据")
    columns = {str(column).strip().lower(): column for column in raw.columns}
    code_column = columns.get("code", columns.get("代码"))
    name_column = columns.get("name", columns.get("名称"))
    if code_column is None or name_column is None:
        raise RuntimeError(f"无法识别股票列表字段：{list(raw.columns)!r}")

    result: dict[str, str] = {}
    for _, row in raw.iterrows():
        try:
            result[normalize_code(row[code_column])] = str(row[name_column]).strip()
        except ValueError:
            continue
    return sorted(result.items())


def fetch_hs300_index(retries: int, end_date: str) -> pd.DataFrame:
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError(
            "缺少 akshare，请执行：python -m pip install -U akshare"
        ) from exc

    raw = call_with_retries(
        "腾讯沪深300",
        lambda: ak.stock_zh_index_daily_tx(symbol=HS300_SYMBOL),
        retries,
    )
    if raw is None or raw.empty:
        raise RuntimeError("stock_zh_index_daily_tx() 返回空数据")

    aliases = {
        "trade_date": ("date", "日期"),
        "open": ("open", "开盘"),
        "high": ("high", "最高"),
        "low": ("low", "最低"),
        "close": ("close", "收盘"),
        "volume": ("volume", "amount", "成交量"),
    }
    normalized_columns = {
        str(column).strip().lower(): column for column in raw.columns
    }
    rename: dict[Any, str] = {}
    for target, candidates in aliases.items():
        source = next(
            (
                normalized_columns[candidate.lower()]
                for candidate in candidates
                if candidate.lower() in normalized_columns
            ),
            None,
        )
        if source is None:
            raise RuntimeError(
                f"腾讯沪深300数据缺少 {target!r} 字段：{list(raw.columns)!r}"
            )
        rename[source] = target

    frame = raw.rename(columns=rename)[list(aliases)].copy()
    parsed_dates = pd.to_datetime(frame["trade_date"], errors="coerce")
    frame["trade_date"] = parsed_dates.dt.strftime("%Y%m%d")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=list(aliases))
    frame = frame[(frame["close"] > 0) & (frame["volume"] >= 0)]
    frame = frame[frame["trade_date"] <= end_date]
    return (
        frame.sort_values("trade_date")
        .drop_duplicates("trade_date", keep="last")
        .reset_index(drop=True)
    )


def create_tushare_client(token_environment: str) -> Any:
    token = os.environ.get(token_environment, "").strip()
    if not token:
        raise RuntimeError(
            f"未设置环境变量 {token_environment}。当前 PowerShell 可执行：\n"
            f'$env:{token_environment}="你的Tushare Token"'
        )
    try:
        import tushare as ts
    except ImportError as exc:
        raise RuntimeError(
            "缺少 tushare，请执行：python -m pip install -U tushare"
        ) from exc
    return ts.pro_api(token)


def normalize_tushare_trade_date(
    daily: pd.DataFrame,
    factors: pd.DataFrame,
    trade_date: str,
    minimum_rows: int,
) -> pd.DataFrame:
    daily_required = {
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
    }
    factor_required = {"ts_code", "trade_date", "adj_factor"}
    if daily is None or daily.empty:
        raise ValueError(f"{trade_date} 日线行情为空，数据可能尚未更新")
    if factors is None or factors.empty:
        raise ValueError(
            f"{trade_date} 复权因子为空，请检查 Tushare 接口权限"
        )
    missing_daily = daily_required.difference(daily.columns)
    missing_factors = factor_required.difference(factors.columns)
    if missing_daily:
        raise ValueError(f"日线行情缺少字段：{sorted(missing_daily)}")
    if missing_factors:
        raise ValueError(f"复权因子缺少字段：{sorted(missing_factors)}")
    if len(daily) < minimum_rows:
        raise ValueError(
            f"{trade_date} 日线仅返回 {len(daily)} 行，低于安全门槛 {minimum_rows}"
        )

    price = daily[list(daily_required)].copy()
    factor = factors[list(factor_required)].copy()
    price["ts_code"] = price["ts_code"].astype(str).str.upper()
    factor["ts_code"] = factor["ts_code"].astype(str).str.upper()
    price["trade_date"] = price["trade_date"].astype(str)
    factor["trade_date"] = factor["trade_date"].astype(str)
    factor = factor.drop_duplicates(["ts_code", "trade_date"], keep="last")
    merged = price.merge(
        factor,
        on=["ts_code", "trade_date"],
        how="left",
        validate="one_to_one",
    )
    coverage = float(merged["adj_factor"].notna().mean())
    if coverage < 0.98:
        raise ValueError(
            f"{trade_date} 复权因子覆盖率仅 {coverage:.2%}，拒绝写入不完整数据"
        )
    merged = merged.dropna(subset=["adj_factor"]).copy()
    merged["code"] = merged["ts_code"].map(normalize_code)
    merged = merged.rename(columns={"vol": "volume"})
    for column in (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adj_factor",
    ):
        merged[column] = pd.to_numeric(merged[column], errors="coerce")
    merged = merged.dropna(
        subset=[
            "open",
            "high",
            "low",
            "close",
            "volume",
            "adj_factor",
        ]
    )
    merged = merged[
        (merged["close"] > 0)
        & (merged["volume"] >= 0)
        & (merged["adj_factor"] > 0)
    ]
    merged["source"] = "tushare"
    return merged[
        [
            "code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "adj_factor",
            "source",
        ]
    ].drop_duplicates(["code", "trade_date"], keep="last")


def fetch_one_trade_date(
    pro: Any,
    trade_date: str,
    retries: int,
    pause: float,
    minimum_rows: int,
) -> tuple[pd.DataFrame, int, int]:
    daily = call_with_retries(
        f"{trade_date} 全市场日线",
        lambda: pro.daily(trade_date=trade_date),
        retries,
    )
    if pause > 0:
        time.sleep(pause)
    factors = call_with_retries(
        f"{trade_date} 全市场复权因子",
        lambda: pro.adj_factor(trade_date=trade_date),
        retries,
    )
    if pause > 0:
        time.sleep(pause)
    normalized = normalize_tushare_trade_date(
        daily, factors, trade_date, minimum_rows
    )
    return normalized, len(daily), len(factors)


def select_target_dates(
    available_dates: list[str],
    completed: set[str],
    mode: str,
    days: int,
    repair_days: int,
) -> list[str]:
    if mode == "init":
        base = available_dates[-days:]
        targets = [trade_date for trade_date in base if trade_date not in completed]
    else:
        if not completed:
            raise RuntimeError(
                "数据库尚未初始化。请先执行："
                "python app/update_market.py --init --days 250"
            )
        latest = max(completed)
        recent_unfinished = [
            trade_date
            for trade_date in available_dates[-30:]
            if trade_date not in completed
        ]
        newer = [trade_date for trade_date in available_dates if trade_date > latest]
        targets = sorted(set(recent_unfinished + newer))

    if repair_days > 0:
        targets = sorted(set(targets + available_dates[-repair_days:]))
    return targets


def show_status(db_path: Path) -> int:
    connection = connect_database(db_path)
    try:
        stats = database_stats(connection)
    finally:
        connection.close()
    print(f"数据库：{db_path.expanduser().resolve()}")
    print(f"股票列表：{stats['securities']} 只")
    print(f"日线记录：{stats['daily_rows']} 行，{stats['daily_codes']} 只股票")
    print(f"日期范围：{stats['daily_start']} ～ {stats['daily_end']}")
    print(f"完整交易日：{stats['completed_dates']} 个")
    print(f"最近完整日期：{stats['latest_completed_date']}")
    print(f"失败日期：{stats['failed_dates']} 个")
    return 0


def parse_yyyymmdd(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期必须是 YYYYMMDD 格式") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A 股本地行情库更新器 v1.2")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--init", action="store_true", help="首次初始化或断点续传")
    mode.add_argument("--daily", action="store_true", help="补齐初始化后的缺失交易日")
    mode.add_argument("--status", action="store_true", help="只查看数据库状态")
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite 数据库路径"
    )
    parser.add_argument("--days", type=int, default=250, help="初始化交易日数量")
    parser.add_argument(
        "--end-date",
        type=parse_yyyymmdd,
        default=date.today().strftime("%Y%m%d"),
        help="更新截止日期 YYYYMMDD",
    )
    parser.add_argument(
        "--repair-days",
        type=int,
        default=0,
        help="强制重取最近 N 个交易日，用于修复数据",
    )
    parser.add_argument("--retries", type=int, default=3, help="接口重试次数")
    parser.add_argument(
        "--pause", type=float, default=0.15, help="两次 Tushare 请求之间的间隔秒数"
    )
    parser.add_argument(
        "--min-daily-rows",
        type=int,
        default=1000,
        help="单个交易日最少股票行数安全门槛",
    )
    parser.add_argument(
        "--token-env",
        default="TUSHARE_TOKEN",
        help="保存 Tushare token 的环境变量名",
    )
    return parser


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.days < 80:
        parser.error("--days 至少为 80；建议使用 250")
    if args.repair_days < 0:
        parser.error("--repair-days 不能为负数")
    if args.retries < 1:
        parser.error("--retries 至少为 1")
    if args.pause < 0 or not math.isfinite(args.pause):
        parser.error("--pause 必须是非负有限数")
    if args.min_daily_rows < 1:
        parser.error("--min-daily-rows 至少为 1")


def run_update(args: argparse.Namespace) -> int:
    connection = connect_database(args.db)
    run_id: int | None = None
    successes = 0
    rows_written = 0
    failures: list[str] = []
    try:
        print("正在更新股票列表和腾讯沪深300交易日历……", flush=True)
        securities = fetch_stock_list(args.retries)
        index_frame = fetch_hs300_index(args.retries, args.end_date)
        if index_frame.empty:
            raise RuntimeError("截止指定日期没有可用的沪深300行情")

        with connection:
            upsert_securities(connection, securities)
            upsert_index_bars(connection, index_frame, HS300_SYMBOL)

        available_dates = index_frame["trade_date"].astype(str).tolist()
        completed = completed_trade_dates(connection)
        mode = "init" if args.init else "daily"
        targets = select_target_dates(
            available_dates,
            completed,
            mode,
            args.days,
            args.repair_days,
        )
        if not targets:
            print("数据库已经是最新状态，没有缺失交易日。")
            return 0

        print(
            f"本次需更新 {len(targets)} 个交易日：{targets[0]} ～ {targets[-1]}",
            flush=True,
        )
        pro = create_tushare_client(args.token_env)
        run_id = start_update_run(connection, mode, len(targets))

        for position, trade_date in enumerate(targets, start=1):
            print(f"[{position}/{len(targets)}] 更新 {trade_date}……", flush=True)
            try:
                frame, daily_rows, factor_rows = fetch_one_trade_date(
                    pro,
                    trade_date,
                    args.retries,
                    args.pause,
                    args.min_daily_rows,
                )
                with connection:
                    stored = upsert_daily_bars(connection, frame)
                    set_trade_date_status(
                        connection,
                        trade_date,
                        "complete",
                        daily_rows=daily_rows,
                        factor_rows=factor_rows,
                        stored_rows=stored,
                    )
                successes += 1
                rows_written += stored
                print(f"    写入 {stored} 只股票", flush=True)
            except Exception as exc:
                message = str(exc)
                failures.append(f"{trade_date}: {message}")
                with connection:
                    set_trade_date_status(
                        connection, trade_date, "failed", error=message
                    )
                print(f"    失败：{message}", file=sys.stderr, flush=True)

        status = "complete" if not failures else "partial"
        finish_update_run(
            connection,
            run_id,
            status,
            successes,
            rows_written,
            "\n".join(failures) if failures else None,
        )
        run_id = None
        print(
            f"更新结束：成功 {successes}/{len(targets)} 个交易日，"
            f"写入 {rows_written} 行。"
        )
        if failures:
            print("失败日期已记录；重新执行同一命令会自动续传。", file=sys.stderr)
            return 1
        return 0
    except KeyboardInterrupt:
        if run_id is not None:
            finish_update_run(
                connection,
                run_id,
                "interrupted",
                successes,
                rows_written,
                "用户中断",
            )
        print("更新已中断；已完成的交易日已经保存。", file=sys.stderr)
        return 130
    except Exception as exc:
        if run_id is not None:
            finish_update_run(
                connection,
                run_id,
                "failed",
                successes,
                rows_written,
                str(exc),
            )
        print(f"更新失败：{exc}", file=sys.stderr)
        return 2
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(args, parser)
    if args.status:
        return show_status(args.db)
    return run_update(args)


if __name__ == "__main__":
    raise SystemExit(main())
