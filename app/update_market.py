#!/usr/bin/env python3
"""批量更新 A 股本地行情库。

首次初始化：

    python app/update_market.py --init --days 250

以后每个交易日收盘后：

    python app/update_market.py --daily

程序优先从环境变量 ``TUSHARE_TOKEN`` 读取凭证，其次读取项目根目录的
``.env``。个股日线和复权因子按交易日批量获取；股票名称及沪深300交易日历
使用 AKShare 腾讯链路。
"""

from __future__ import annotations

import argparse
import math
import os
import re
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


class EndpointRateLimiter:
    """按接口独立控制请求频率，并从服务端错误中自动收紧限制。"""

    def __init__(self, label: str, calls_per_minute: float) -> None:
        self.label = label
        self.calls_per_minute = calls_per_minute
        self.last_request_started: float | None = None

    @property
    def interval_seconds(self) -> float:
        if self.calls_per_minute <= 0:
            return 0.0
        base_interval = 60.0 / self.calls_per_minute
        # 留少量余量，避免客户端与服务端计时边界不同而再次触发限频。
        safety_buffer = min(1.0, max(0.1, base_interval * 0.02))
        return base_interval + safety_buffer

    def wait_before_request(self) -> None:
        interval = self.interval_seconds
        if interval <= 0:
            self.last_request_started = time.monotonic()
            return

        now = time.monotonic()
        if self.last_request_started is not None:
            remaining = interval - (now - self.last_request_started)
            if remaining > 0:
                print(
                    f"{self.label} 频率控制：等待 {remaining:.1f} 秒"
                    f"（每分钟最多 {self.calls_per_minute:g} 次）……",
                    flush=True,
                )
                time.sleep(remaining)
        self.last_request_started = time.monotonic()

    def adapt_to_error(self, error: Exception) -> bool:
        message = str(error)
        lowered = message.lower()
        is_rate_limit = (
            "频率超限" in message
            or "rate limit" in lowered
            or "too many requests" in lowered
        )
        if not is_rate_limit:
            return False

        match = re.search(r"(\d+(?:\.\d+)?)\s*次\s*/\s*分钟", message)
        detected_limit = float(match.group(1)) if match else 1.0
        if self.calls_per_minute <= 0 or detected_limit < self.calls_per_minute:
            self.calls_per_minute = detected_limit
            print(
                f"{self.label} 已从服务端错误识别到频率限制："
                f"每分钟最多 {detected_limit:g} 次。",
                file=sys.stderr,
                flush=True,
            )
        return True

    def estimate_seconds(self, request_count: int) -> float:
        return max(0, request_count - 1) * self.interval_seconds


def format_duration(seconds: float) -> str:
    total_minutes = max(0, math.ceil(seconds / 60.0))
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours} 小时 {minutes} 分钟"
    if hours:
        return f"{hours} 小时"
    return f"{minutes} 分钟"


def call_with_retries(
    label: str,
    operation: Callable[[], Any],
    retries: int,
    rate_limiter: EndpointRateLimiter | None = None,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            if rate_limiter is not None:
                rate_limiter.wait_before_request()
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                is_rate_limit = (
                    rate_limiter.adapt_to_error(exc)
                    if rate_limiter is not None
                    else False
                )
                if is_rate_limit:
                    print(
                        f"{label} 第 {attempt} 次触发限频，"
                        "将按服务端频率等待后重试。",
                        file=sys.stderr,
                        flush=True,
                    )
                else:
                    wait_seconds = min(20.0, 1.5 * (2 ** (attempt - 1)))
                    print(
                        f"{label} 第 {attempt} 次失败，"
                        f"{wait_seconds:.1f} 秒后重试：{exc}",
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


def read_dotenv_value(path: Path, variable_name: str) -> str | None:
    """读取简单 KEY=VALUE 格式；不修改当前进程的环境变量。"""

    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise RuntimeError(f"无法读取 .env 文件 {path}: {exc}") from exc

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, raw_value = stripped.partition("=")
        if not separator or key.strip() != variable_name:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        return value.strip()
    return None


def resolve_tushare_token(
    token_environment: str,
    env_file: Path,
) -> tuple[str, str]:
    token = os.environ.get(token_environment, "").strip()
    if token:
        return token, f"环境变量 {token_environment}"

    resolved_env_file = env_file.expanduser().resolve()
    token = (read_dotenv_value(resolved_env_file, token_environment) or "").strip()
    if token:
        return token, str(resolved_env_file)

    raise RuntimeError(
        f"未找到 {token_environment}。已经检查：\n"
        f"1. 当前进程环境变量 {token_environment}\n"
        f"2. 配置文件 {resolved_env_file}\n"
        "Linux/macOS 可执行：export TUSHARE_TOKEN='你的Token'\n"
        "Windows PowerShell 可执行：$env:TUSHARE_TOKEN='你的Token'\n"
        f"也可以在 {resolved_env_file} 中写入：\n"
        f"{token_environment}=你的Token"
    )


def create_tushare_client(token_environment: str, env_file: Path) -> Any:
    token, source = resolve_tushare_token(token_environment, env_file)
    try:
        import tushare as ts
    except ImportError as exc:
        raise RuntimeError(
            "缺少 tushare，请执行：python -m pip install -U tushare"
        ) from exc
    print(f"Tushare Token 已从 {source} 读取。", flush=True)
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
    daily_rate_limiter: EndpointRateLimiter,
    factor_rate_limiter: EndpointRateLimiter,
) -> tuple[pd.DataFrame, int, int]:
    daily = call_with_retries(
        f"{trade_date} 全市场日线",
        lambda: pro.daily(trade_date=trade_date),
        retries,
        daily_rate_limiter,
    )
    if pause > 0:
        time.sleep(pause)
    factors = call_with_retries(
        f"{trade_date} 全市场复权因子",
        lambda: pro.adj_factor(trade_date=trade_date),
        retries,
        factor_rate_limiter,
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
        "--daily-per-minute",
        type=float,
        default=50.0,
        help="daily 接口每分钟调用上限；0 表示不主动限速",
    )
    parser.add_argument(
        "--adj-factor-per-minute",
        type=float,
        default=1.0,
        help="adj_factor 接口每分钟调用上限；默认按低频权限每分钟 1 次",
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
    parser.add_argument(
        "--env-file",
        type=Path,
        default=PROJECT_DIR / ".env",
        help="环境配置文件路径；默认读取项目根目录 .env",
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
    if args.daily_per_minute < 0 or not math.isfinite(args.daily_per_minute):
        parser.error("--daily-per-minute 必须是非负有限数")
    if args.adj_factor_per_minute < 0 or not math.isfinite(
        args.adj_factor_per_minute
    ):
        parser.error("--adj-factor-per-minute 必须是非负有限数")
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
        daily_rate_limiter = EndpointRateLimiter(
            "daily 接口", args.daily_per_minute
        )
        factor_rate_limiter = EndpointRateLimiter(
            "adj_factor 接口", args.adj_factor_per_minute
        )
        estimated_seconds = factor_rate_limiter.estimate_seconds(len(targets))
        if estimated_seconds > 0:
            print(
                f"当前 adj_factor 设置为每分钟最多 "
                f"{args.adj_factor_per_minute:g} 次，"
                f"预计接口等待时间至少 {format_duration(estimated_seconds)}。",
                flush=True,
            )
            print("可随时按 Ctrl+C 中断；重新运行会从未完成日期续传。", flush=True)
        pro = create_tushare_client(args.token_env, args.env_file)
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
                    daily_rate_limiter,
                    factor_rate_limiter,
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
