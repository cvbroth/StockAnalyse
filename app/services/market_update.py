#!/usr/bin/env python3
"""批量更新 A 股本地行情库。

首次初始化时二选一：

    python app/update_market.py --init --tx --days 250
    python app/update_market.py --init --tushare --days 250

以后每个交易日收盘后：

    python app/update_market.py --daily

数据库会记住初始化数据源，日常更新自动沿用且不允许切换。腾讯模式直接获取
逐只股票的前复权行情；Tushare 模式按交易日获取全市场未复权日线和复权因子。
股票名称及沪深300交易日历统一使用 AKShare 腾讯链路。
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import math
import queue
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from ..storage.sqlite import (
    bind_data_provider,
    completed_trade_dates,
    completed_security_codes,
    connect_database,
    database_quality_report,
    database_stats,
    finish_update_run,
    infer_data_provider,
    replace_daily_bars_for_code,
    set_security_update_status,
    set_metadata,
    set_trade_date_status,
    start_update_run,
    upsert_daily_bars,
    upsert_index_bars,
    upsert_securities,
)
from ..project_config import (
    PROJECT_DIR,
    resolve_database_path,
    save_project_config,
)
from ..providers import TencentProvider, TushareProvider, get_provider_descriptor


HS300_SYMBOL = "sh000300"
APP_DIR = Path(__file__).resolve().parent


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
                    f"{label} 第 {attempt} 次失败，"
                    f"{wait_seconds:.1f} 秒后重试：{exc}",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(wait_seconds)
    raise RuntimeError(f"{label} 获取失败（已重试 {retries} 次）：{last_error}")


def call_with_timeout(
    label: str,
    operation: Callable[[], Any],
    timeout_seconds: float,
) -> Any:
    """为不支持 timeout 参数的元数据接口提供进程级等待上限。"""

    results: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def target() -> None:
        try:
            results.put((True, operation()))
        except BaseException as exc:
            results.put((False, exc))

    worker = threading.Thread(target=target, daemon=True, name=f"timeout:{label}")
    worker.start()
    try:
        succeeded, value = results.get(timeout=timeout_seconds)
    except queue.Empty as exc:
        raise TimeoutError(f"{label} 超过 {timeout_seconds:g} 秒仍未返回") from exc
    if succeeded:
        return value
    raise value


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


def fetch_stock_list(retries: int, timeout_seconds: float) -> list[tuple[str, str]]:
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError(
            "缺少 akshare，请执行：python -m pip install -U akshare"
        ) from exc

    raw = call_with_retries(
        "A股股票列表",
        lambda: call_with_timeout(
            "A股股票列表", ak.stock_info_a_code_name, timeout_seconds
        ),
        retries,
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


def fetch_hs300_index(
    retries: int,
    end_date: str,
    timeout_seconds: float,
) -> pd.DataFrame:
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError(
            "缺少 akshare，请执行：python -m pip install -U akshare"
        ) from exc

    raw = call_with_retries(
        "腾讯沪深300",
        lambda: call_with_timeout(
            "腾讯沪深300",
            lambda: ak.stock_zh_index_daily_tx(symbol=HS300_SYMBOL),
            timeout_seconds,
        ),
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
                "python app/update_market.py --init --tx --days 250，"
                "或将 --tx 改为 --tushare"
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
        stats = database_quality_report(connection)
    finally:
        connection.close()
    print(f"数据库：{db_path.expanduser().resolve()}")
    provider_labels = {
        "tx": "腾讯前复权",
        "tushare": "Tushare 未复权日线 + 复权因子",
        "mixed": "混合来源（不允许继续更新）",
        None: "尚未初始化",
    }
    provider_label = provider_labels.get(
        stats["data_provider"], stats["data_provider"]
    )
    print(f"初始化数据源：{provider_label}")
    print(f"股票列表：{stats['securities']} 只")
    print(f"日线记录：{stats['daily_rows']} 行，{stats['daily_codes']} 只股票")
    print(f"日期范围：{stats['daily_start']} ～ {stats['daily_end']}")
    print(
        f"沪深300：{stats['index_rows']} 行，"
        f"{stats['index_start']} ～ {stats['index_end']}"
    )
    if stats["data_provider"] == "tx":
        print(f"腾讯完整股票：{stats['completed_securities']} 只")
        print(f"腾讯失败股票：{stats['failed_securities']} 只")
    else:
        print(f"完整交易日：{stats['completed_dates']} 个")
        print(f"最近完整日期：{stats['latest_completed_date']}")
        print(f"失败日期：{stats['failed_dates']} 个")
    print(f"初始化标记：{stats['initialization_status'] or '旧数据库/未记录'}")
    print_quality_report(stats, heading="质量检查")
    return 0


def set_current_database(db_path: Path) -> Path:
    connection = connect_database(db_path)
    try:
        provider = infer_data_provider(connection)
        report = database_quality_report(connection, minimum_history_days=80)
        if not report["passed"]:
            raise RuntimeError("；".join(report["errors"]))
        with connection:
            set_metadata(connection, "initialization_status", "complete")
    finally:
        connection.close()
    if provider not in {"tx", "tushare"}:
        raise RuntimeError(
            "只有已经绑定单一数据源的数据库才能设为当前数据库；"
            f"实际数据源为 {provider!r}"
        )
    return save_project_config(db_path, provider)


def print_quality_report(report: dict[str, Any], heading: str) -> None:
    result = "通过" if report["passed"] else "未通过"
    print(f"{heading}：{result}")
    print(
        f"  至少 {report['minimum_history_days']} 日历史："
        f"{report['codes_with_history']}/{report['expected_codes']} 只"
    )
    for message in report["warnings"]:
        print(f"  警告：{message}", file=sys.stderr)
    for message in report["errors"]:
        print(f"  错误：{message}", file=sys.stderr)


def finish_with_quality_check(
    connection: Any,
    args: argparse.Namespace,
    update_result: int,
) -> int:
    """完成阶段四检查，并维护初始化状态。"""

    print("[4/4] 正在校验数据库完整性……", flush=True)
    minimum_days = min(120, args.days) if args.init else 120
    report = database_quality_report(connection, minimum_days)
    if args.init:
        initialization_status = (
            "complete" if update_result == 0 and report["passed"] else "incomplete"
        )
        with connection:
            set_metadata(connection, "initialization_status", initialization_status)
    print_quality_report(report, heading="数据库质量检查")
    if update_result == 0 and not report["passed"]:
        return 2
    return update_result


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
    provider = parser.add_mutually_exclusive_group()
    provider.add_argument(
        "--tx", action="store_true", help="初始化时选择腾讯前复权数据源"
    )
    provider.add_argument(
        "--tushare",
        action="store_true",
        help="初始化时选择 Tushare 日线和复权因子",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite 数据库路径；省略时读取 config/project.json",
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
        "--metadata-timeout",
        type=float,
        default=30.0,
        help="股票列表和沪深300接口的单次等待上限秒数",
    )
    parser.add_argument(
        "--set-current",
        action="store_true",
        help="配合 --status，将指定的现有数据库设为项目默认数据库",
    )
    parser.add_argument(
        "--tx-workers",
        type=int,
        default=6,
        help="腾讯模式并发下载股票数",
    )
    parser.add_argument(
        "--tx-timeout",
        type=float,
        default=15.0,
        help="腾讯单次请求超时秒数",
    )
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
    if args.set_current and not args.status:
        parser.error("--set-current 必须与 --status 一起使用")
    if args.init and not (args.tx or args.tushare):
        parser.error("--init 必须同时选择 --tx 或 --tushare")
    if not args.init and (args.tx or args.tushare):
        parser.error(
            "--tx/--tushare 只能在初始化时选择；日常更新会自动沿用数据库数据源"
        )
    if args.days < 80:
        parser.error("--days 至少为 80；建议使用 250")
    if args.repair_days < 0:
        parser.error("--repair-days 不能为负数")
    if args.retries < 1:
        parser.error("--retries 至少为 1")
    if args.metadata_timeout <= 0 or not math.isfinite(args.metadata_timeout):
        parser.error("--metadata-timeout 必须是正有限数")
    if args.tx_workers < 1:
        parser.error("--tx-workers 至少为 1")
    if args.tx_timeout <= 0 or not math.isfinite(args.tx_timeout):
        parser.error("--tx-timeout 必须是正有限数")
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


def resolve_update_provider(
    connection: Any,
    args: argparse.Namespace,
) -> str:
    if args.init:
        requested = "tx" if args.tx else "tushare"
        return bind_data_provider(connection, requested)

    existing = infer_data_provider(connection)
    if existing is None:
        raise RuntimeError(
            "数据库尚未初始化。请先使用 --init --tx 或 --init --tushare。"
        )
    if existing == "mixed":
        raise RuntimeError(
            "数据库包含混合来源，无法确定日常更新数据源；请新建数据库重新初始化。"
        )
    return bind_data_provider(connection, existing)


def run_tencent_update(
    connection: Any,
    args: argparse.Namespace,
    securities: list[tuple[str, str]],
    index_frame: pd.DataFrame,
    provider: TencentProvider,
) -> int:
    available_dates = index_frame["trade_date"].astype(str).tolist()
    requested_dates = available_dates[-args.days :]
    if not requested_dates:
        raise RuntimeError("腾讯初始化范围内没有可用交易日")
    start_date, end_date = requested_dates[0], requested_dates[-1]

    completed = completed_security_codes(
        connection, "tx", start_date, end_date
    )
    if args.repair_days > 0:
        completed = set()
        print(
            "腾讯前复权是动态序列；--repair-days 将重新获取全部股票的完整窗口。",
            flush=True,
        )
    supported_securities = [
        (code, name) for code, name in securities if provider.supports_code(code)
    ]
    unsupported_count = len(securities) - len(supported_securities)
    targets = [
        (code, name)
        for code, name in supported_securities
        if code not in completed
    ]
    if unsupported_count:
        print(
            f"腾讯模式当前只更新沪深股票；跳过北交所 {unsupported_count} 只。",
            flush=True,
        )
    if not targets:
        print("腾讯前复权数据库已经是最新状态，没有待更新股票。")
        return 0

    mode = "init:tx" if args.init else "daily:tx"
    print(
        f"腾讯前复权模式：{start_date} ～ {end_date}，"
        f"待更新 {len(targets)}/{len(supported_securities)} 只沪深股票，"
        f"并发数 {args.tx_workers}。",
        flush=True,
    )
    print("可随时按 Ctrl+C 中断；重新运行会从未完成股票续传。", flush=True)

    run_id = start_update_run(connection, mode, len(targets))
    successes = 0
    rows_written = 0
    failures: list[str] = []
    executor = ThreadPoolExecutor(max_workers=args.tx_workers)
    future_to_stock = {
        executor.submit(
            provider.fetch_security_history,
            code,
            start_date,
            end_date,
            args.retries,
            args.tx_timeout,
        ): (code, name)
        for code, name in targets
    }
    try:
        for position, future in enumerate(as_completed(future_to_stock), start=1):
            code, name = future_to_stock[future]
            try:
                frame = future.result()
                with connection:
                    stored = replace_daily_bars_for_code(connection, frame)
                    set_security_update_status(
                        connection,
                        "tx",
                        code,
                        "complete",
                        start_date,
                        end_date,
                        stored_rows=stored,
                    )
                successes += 1
                rows_written += stored
            except Exception as exc:
                message = str(exc)
                failures.append(f"{code} {name}: {message}")
                with connection:
                    set_security_update_status(
                        connection,
                        "tx",
                        code,
                        "failed",
                        start_date,
                        end_date,
                        error=message,
                    )
                print(f"    {code} {name} 失败：{message}", file=sys.stderr)

            if position % 50 == 0 or position == len(targets):
                print(
                    f"进度 {position}/{len(targets)}，成功 {successes}，"
                    f"失败 {len(failures)}，写入 {rows_written} 行",
                    flush=True,
                )
    except BaseException as exc:
        for future in future_to_stock:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        status = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        finish_update_run(
            connection,
            run_id,
            status,
            successes,
            rows_written,
            "用户中断" if isinstance(exc, KeyboardInterrupt) else str(exc),
        )
        raise
    else:
        executor.shutdown(wait=True)

    status = "complete" if not failures else "partial"
    finish_update_run(
        connection,
        run_id,
        status,
        successes,
        rows_written,
        "\n".join(failures) if failures else None,
    )
    print(
        f"腾讯更新结束：成功 {successes}/{len(targets)} 只股票，"
        f"写入 {rows_written} 行。"
    )
    if failures:
        print("失败股票已记录；重新执行同一命令会自动续传。", file=sys.stderr)
        return 1
    return 0


def run_update(args: argparse.Namespace) -> int:
    connection = connect_database(args.db)
    run_id: int | None = None
    successes = 0
    rows_written = 0
    failures: list[str] = []
    try:
        provider = resolve_update_provider(connection, args)
        descriptor = get_provider_descriptor(provider)
        print(f"当前数据库：{args.db}", flush=True)
        print(
            f"数据库数据源：{descriptor.label}；市场：{descriptor.market_scope}；"
            f"更新单位：{'股票' if descriptor.update_unit == 'security' else '交易日'}",
            flush=True,
        )
        if args.init:
            with connection:
                set_metadata(connection, "initialization_status", "running")
            config_path = save_project_config(args.db, provider)
            print(f"已设为当前项目数据库：{config_path}", flush=True)

        print("[1/4] 正在获取A股股票列表……", flush=True)
        securities = fetch_stock_list(args.retries, args.metadata_timeout)
        print(f"[1/4] 股票列表完成：{len(securities)} 只。", flush=True)
        print("[2/4] 正在获取腾讯沪深300交易日历……", flush=True)
        index_frame = fetch_hs300_index(
            args.retries, args.end_date, args.metadata_timeout
        )
        if index_frame.empty:
            raise RuntimeError("截止指定日期没有可用的沪深300行情")
        print(
            f"[2/4] 沪深300完成：{len(index_frame)} 个交易日，"
            f"截至 {index_frame['trade_date'].iloc[-1]}。",
            flush=True,
        )

        with connection:
            upsert_securities(connection, securities)
            upsert_index_bars(connection, index_frame, HS300_SYMBOL)

        if provider == "tx":
            print("[3/4] 正在更新腾讯个股前复权行情……", flush=True)
            result = run_tencent_update(
                connection, args, securities, index_frame, TencentProvider()
            )
            return finish_with_quality_check(connection, args, result)

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
            return finish_with_quality_check(connection, args, 0)

        print("[3/4] 正在更新Tushare个股行情和复权因子……", flush=True)
        print(
            f"本次需更新 {len(targets)} 个交易日：{targets[0]} ～ {targets[-1]}",
            flush=True,
        )
        tushare_provider = TushareProvider(
            token_environment=args.token_env,
            env_file=args.env_file,
            retries=args.retries,
            pause=args.pause,
            minimum_rows=args.min_daily_rows,
            daily_per_minute=args.daily_per_minute,
            factor_per_minute=args.adj_factor_per_minute,
        )
        estimated_seconds = tushare_provider.estimate_seconds(len(targets))
        if estimated_seconds > 0:
            print(
                f"当前 adj_factor 设置为每分钟最多 "
                f"{args.adj_factor_per_minute:g} 次，"
                f"预计接口等待时间至少 {format_duration(estimated_seconds)}。",
                flush=True,
            )
            print("可随时按 Ctrl+C 中断；重新运行会从未完成日期续传。", flush=True)
        run_id = start_update_run(connection, mode, len(targets))

        for position, trade_date in enumerate(targets, start=1):
            print(f"[{position}/{len(targets)}] 更新 {trade_date}……", flush=True)
            try:
                frame, daily_rows, factor_rows = (
                    tushare_provider.fetch_trade_date(trade_date)
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
            return finish_with_quality_check(connection, args, 1)
        return finish_with_quality_check(connection, args, 0)
    except KeyboardInterrupt:
        if args.init:
            try:
                with connection:
                    set_metadata(connection, "initialization_status", "interrupted")
            except Exception:
                pass
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
        if args.init:
            try:
                with connection:
                    set_metadata(connection, "initialization_status", "failed")
            except Exception:
                pass
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
    try:
        args.db, args.db_source = resolve_database_path(args.db)
    except RuntimeError as exc:
        parser.error(str(exc))
    validate_args(args, parser)
    print(f"数据库选择：{args.db_source} → {args.db}", flush=True)
    if args.status:
        if args.set_current:
            try:
                config_path = set_current_database(args.db)
            except RuntimeError as exc:
                print(f"设置当前数据库失败：{exc}", file=sys.stderr)
                return 2
            print(f"已写入当前项目配置：{config_path}", flush=True)
        return show_status(args.db)
    return run_update(args)


if __name__ == "__main__":
    raise SystemExit(main())
