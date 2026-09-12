#!/usr/bin/env python3
"""A 股上升周期筛选器 v1.1。

数据源
------
* 股票列表：AKShare ``stock_info_a_code_name``
* 个股日线：腾讯 ``stock_zh_a_hist_tx``（前复权）
* 沪深 300：腾讯 ``stock_zh_index_daily_tx``

示例
----
先用少量股票检查数据链路和规则：

    python app/screener_v1_1.py --symbols 603505 600519 000858

扫描沪深 A 股并计算真正的全市场 60 日收益百分位：

    python app/screener_v1_1.py --all

说明：腾讯行情字段 ``amount`` 的单位是“手”，本程序将其统一命名为
``volume``，不把它误当成成交额。
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

try:
    import akshare as ak
    import pandas as pd
except ImportError as exc:  # pragma: no cover - only runs when dependencies are absent
    missing = getattr(exc, "name", "依赖")
    raise SystemExit(
        f"缺少 Python 包 {missing!r}。请先执行：\n"
        "python -m pip install -U akshare pandas"
    ) from exc

from ..analysis import (
    ScreenConfig as CoreScreenConfig,
    analyze_stock as core_analyze_stock,
    apply_market_percentiles as core_apply_market_percentiles,
    mark_percentile_not_required as core_mark_percentile_not_required,
    normalize_code as core_normalize_code,
    refresh_score as core_refresh_score,
    write_outputs as core_write_outputs,
)


VERSION = "1.1"
HS300_SYMBOL = "sh000300"
APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parents[1]
DEFAULT_OUTPUT_PATH = PROJECT_DIR / "output"
PRINT_LOCK = threading.Lock()


@dataclass(frozen=True)
class ScreenConfig:
    """第一版规则阈值；集中存放，方便以后回测和调整。"""

    min_history_days: int = 120
    structure_window: int = 20
    volume_window: int = 20
    up_down_volume_ratio: float = 1.15
    breakout_lookback: int = 60
    breakout_search_days: int = 20
    breakout_volume_multiple: float = 1.30
    breakout_max_fall: float = 0.03
    excess_return_60d: float = 0.08
    market_percentile_cutoff: float = 0.70
    max_stale_calendar_days: int = 10
    min_average_volume_lots: float = 0.0
    exclude_st: bool = True


def parse_yyyymmdd(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"日期 {value!r} 格式错误，应为 YYYYMMDD，例如 20260911"
        ) from exc


def normalize_code(raw_code: Any) -> str:
    code = str(raw_code).strip().lower()
    if code.startswith(("sh", "sz", "bj")):
        code = code[2:]
    if code.endswith(".0") and code[:-2].isdigit():
        code = code[:-2]
    if not code.isdigit():
        raise ValueError(f"股票代码 {raw_code!r} 不是有效数字代码")
    return code.zfill(6)


def to_tx_symbol(code: str) -> str | None:
    """把六位股票代码转换为腾讯格式；v1.1 暂不扫描北交所。"""

    code = normalize_code(code)
    if code.startswith("6"):
        return f"sh{code}"
    if code.startswith(("0", "3")):
        return f"sz{code}"
    if code.startswith(("4", "8", "9")):
        return None
    return None


def _find_column(df: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    normalized = {str(column).strip().lower(): column for column in df.columns}
    for candidate in candidates:
        if candidate.lower() in normalized:
            return str(normalized[candidate.lower()])
    return None


def normalize_market_df(df: pd.DataFrame) -> pd.DataFrame:
    """把腾讯个股/指数行情统一成 date/open/close/high/low/volume。"""

    if df is None or df.empty:
        return pd.DataFrame(
            columns=["date", "open", "close", "high", "low", "volume"]
        )

    aliases = {
        "date": ("date", "日期"),
        "open": ("open", "开盘"),
        "close": ("close", "收盘"),
        "high": ("high", "最高"),
        "low": ("low", "最低"),
        # 腾讯把成交量列命名为 amount，官方文档给出的单位为“手”。
        "volume": ("volume", "amount", "成交量"),
    }
    rename_map: dict[str, str] = {}
    for standard_name, candidates in aliases.items():
        source_name = _find_column(df, candidates)
        if source_name is None:
            raise ValueError(
                f"行情数据缺少 {standard_name!r} 列；实际列为 {list(df.columns)!r}"
            )
        rename_map[source_name] = standard_name

    result = df.rename(columns=rename_map)[list(aliases)].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.normalize()
    for column in ("open", "close", "high", "low", "volume"):
        result[column] = pd.to_numeric(result[column], errors="coerce")

    result = result.dropna(subset=["date", "open", "close", "high", "low", "volume"])
    result = result[(result["close"] > 0) & (result["volume"] >= 0)]
    result = result.sort_values("date").drop_duplicates("date", keep="last")
    return result.reset_index(drop=True)


def _call_with_retries(label: str, func: Any, retries: int) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return func()
        except Exception as exc:  # network/provider errors vary by AKShare version
            last_error = exc
            if attempt < retries:
                time.sleep(0.8 * attempt)
    raise RuntimeError(f"{label} 获取失败（已重试 {retries} 次）: {last_error}")


def fetch_stock_history(
    code: str,
    start_date: str,
    end_date: str,
    retries: int = 3,
    timeout: float = 15.0,
) -> pd.DataFrame:
    tx_symbol = to_tx_symbol(code)
    if tx_symbol is None:
        return pd.DataFrame()

    raw = _call_with_retries(
        code,
        lambda: ak.stock_zh_a_hist_tx(
            symbol=tx_symbol,
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
            timeout=timeout,
        ),
        retries,
    )
    return normalize_market_df(raw)


def fetch_hs300(
    start_date: str,
    end_date: str,
    retries: int = 3,
) -> pd.DataFrame:
    """读取腾讯沪深300全量历史，再本地按起止日期切片。"""

    raw = _call_with_retries(
        "沪深300",
        lambda: ak.stock_zh_index_daily_tx(symbol=HS300_SYMBOL),
        retries,
    )
    result = normalize_market_df(raw)
    start = pd.Timestamp(parse_yyyymmdd(start_date))
    end = pd.Timestamp(parse_yyyymmdd(end_date))
    return result[(result["date"] >= start) & (result["date"] <= end)].reset_index(
        drop=True
    )


def get_universe(retries: int = 3) -> list[tuple[str, str]]:
    raw = _call_with_retries(
        "A股股票列表", ak.stock_info_a_code_name, retries
    )
    if raw is None or raw.empty:
        raise RuntimeError("stock_info_a_code_name() 返回空股票列表")

    code_column = _find_column(raw, ("code", "代码"))
    name_column = _find_column(raw, ("name", "名称"))
    if code_column is None or name_column is None:
        raise RuntimeError(f"无法识别股票列表字段：{list(raw.columns)!r}")

    stocks: dict[str, str] = {}
    for _, row in raw.iterrows():
        try:
            code = normalize_code(row[code_column])
        except ValueError:
            continue
        stocks[code] = str(row[name_column]).strip()
    return sorted(stocks.items())


# v1.1保留直接联网入口，但分析与输出统一转发到无数据源依赖的核心。
ScreenConfig = CoreScreenConfig
normalize_code = core_normalize_code
analyze_stock = core_analyze_stock
refresh_score = core_refresh_score
apply_market_percentiles = core_apply_market_percentiles
mark_percentile_not_required = core_mark_percentile_not_required
write_outputs = core_write_outputs


def scan_one(
    code: str,
    name: str,
    start_date: str,
    end_date: str,
    benchmark_df: pd.DataFrame,
    config: ScreenConfig,
    retries: int,
    timeout: float,
) -> dict[str, Any]:
    history = fetch_stock_history(
        code, start_date, end_date, retries=retries, timeout=timeout
    )
    if history.empty:
        raise ValueError("腾讯行情返回空数据，或该市场暂不支持")
    return analyze_stock(code, name, history, benchmark_df, end_date, config)


def scan_market(
    stocks: list[tuple[str, str]],
    start_date: str,
    end_date: str,
    benchmark_df: pd.DataFrame,
    config: ScreenConfig,
    retries: int,
    timeout: float,
    workers: int,
    progress_every: int,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    total = len(stocks)

    def collect(code: str, name: str, future: Any, completed: int) -> None:
        try:
            records.append(future.result())
        except Exception as exc:
            errors.append({"code": code, "name": name, "error": str(exc)})
        if progress_every > 0 and (completed % progress_every == 0 or completed == total):
            with PRINT_LOCK:
                print(
                    f"进度 {completed}/{total}，成功 {len(records)}，失败/跳过 {len(errors)}",
                    flush=True,
                )

    if workers == 1:
        for completed, (code, name) in enumerate(stocks, start=1):
            class ImmediateFuture:
                def result(self) -> dict[str, Any]:
                    return scan_one(
                        code,
                        name,
                        start_date,
                        end_date,
                        benchmark_df,
                        config,
                        retries,
                        timeout,
                    )

            collect(code, name, ImmediateFuture(), completed)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(
                    scan_one,
                    code,
                    name,
                    start_date,
                    end_date,
                    benchmark_df,
                    config,
                    retries,
                    timeout,
                ): (code, name)
                for code, name in stocks
            }
            for completed, future in enumerate(as_completed(future_map), start=1):
                code, name = future_map[future]
                collect(code, name, future, completed)
    return records, errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="A 股上升周期筛选器 v1.1（AKShare 腾讯行情版）"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--all", action="store_true", help="扫描沪深 A 股并计算全市场 60 日百分位"
    )
    mode.add_argument(
        "--symbols",
        nargs="+",
        metavar="代码",
        help="小样本检查模式；不计算、不强制样本内百分位",
    )
    parser.add_argument(
        "--end-date", default=date.today().strftime("%Y%m%d"), help="结束日期 YYYYMMDD"
    )
    parser.add_argument(
        "--start-date", help="开始日期 YYYYMMDD；默认从结束日向前 420 个自然日"
    )
    parser.add_argument(
        "--lookback-calendar-days", type=int, default=420, help="默认回看自然日数"
    )
    parser.add_argument("--workers", type=int, default=4, help="并发请求数，默认 4")
    parser.add_argument("--retries", type=int, default=3, help="单个接口重试次数")
    parser.add_argument("--timeout", type=float, default=15.0, help="个股请求超时秒数")
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_PATH, help="输出目录"
    )
    parser.add_argument(
        "--percentile-cutoff",
        type=float,
        default=0.70,
        help="全市场百分位门槛，0.70 表示前 30%%",
    )
    parser.add_argument(
        "--min-history-days", type=int, default=120, help="最少历史交易日"
    )
    parser.add_argument(
        "--min-average-volume-lots",
        type=float,
        default=0.0,
        help="近20日最低日均成交量（手）；默认不设门槛",
    )
    parser.add_argument(
        "--include-st", action="store_true", help="允许 ST/*ST 股票通过基础过滤"
    )
    parser.add_argument(
        "--limit", type=int, help="仅扫描前 N 只（用于调试；--all 时百分位不再代表全市场）"
    )
    parser.add_argument(
        "--progress-every", type=int, default=50, help="每处理 N 只打印一次进度"
    )
    return parser


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    for field in ("end_date", "start_date"):
        value = getattr(args, field, None)
        if value:
            try:
                parse_yyyymmdd(value)
            except argparse.ArgumentTypeError as exc:
                parser.error(str(exc))
    if args.workers < 1:
        parser.error("--workers 必须至少为 1")
    if args.retries < 1:
        parser.error("--retries 必须至少为 1")
    if args.timeout <= 0:
        parser.error("--timeout 必须大于 0")
    if not 0 < args.percentile_cutoff <= 1:
        parser.error("--percentile-cutoff 必须在 (0, 1] 区间")
    if args.min_history_days < 80:
        parser.error("--min-history-days 不能低于 80")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit 必须至少为 1")


def resolve_stocks(args: argparse.Namespace) -> tuple[list[tuple[str, str]], int]:
    universe = get_universe(retries=args.retries)
    name_by_code = dict(universe)
    if args.all:
        selected = [item for item in universe if to_tx_symbol(item[0]) is not None]
        skipped_market = len(universe) - len(selected)
    else:
        selected = []
        skipped_market = 0
        seen: set[str] = set()
        for raw_code in args.symbols:
            code = normalize_code(raw_code)
            if code in seen:
                continue
            seen.add(code)
            if to_tx_symbol(code) is None:
                skipped_market += 1
                print(f"跳过 {code}：v1.1 腾讯数据链路暂不支持该市场")
                continue
            selected.append((code, name_by_code.get(code, "未知名称")))
    if args.limit is not None:
        selected = selected[: args.limit]
    return selected, skipped_market


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(args, parser)

    end_dt = parse_yyyymmdd(args.end_date)
    if args.start_date:
        start_date = args.start_date
    else:
        start_date = (end_dt - timedelta(days=args.lookback_calendar_days)).strftime(
            "%Y%m%d"
        )
    if parse_yyyymmdd(start_date) >= end_dt:
        parser.error("开始日期必须早于结束日期")

    config = ScreenConfig(
        min_history_days=args.min_history_days,
        market_percentile_cutoff=args.percentile_cutoff,
        min_average_volume_lots=args.min_average_volume_lots,
        exclude_st=not args.include_st,
    )
    mode_name = "all" if args.all else "symbols"

    print(f"A 股上升周期筛选器 v{VERSION}")
    print(f"模式：{mode_name}；区间：{start_date}～{args.end_date}")
    print("正在读取股票列表和腾讯沪深300基准……", flush=True)
    try:
        stocks, skipped_market = resolve_stocks(args)
        benchmark_df = fetch_hs300(start_date, args.end_date, retries=args.retries)
    except Exception as exc:
        print(f"初始化失败：{exc}", file=sys.stderr)
        return 2

    if not stocks:
        print("没有可扫描的沪深股票。", file=sys.stderr)
        return 2
    if len(benchmark_df) < 61:
        print(
            f"沪深300历史数据不足 61 个交易日（实际 {len(benchmark_df)}）。",
            file=sys.stderr,
        )
        return 2

    print(
        f"待扫描 {len(stocks)} 只；北交所/不支持代码已跳过 {skipped_market} 只。",
        flush=True,
    )
    records, errors = scan_market(
        stocks=stocks,
        start_date=start_date,
        end_date=args.end_date,
        benchmark_df=benchmark_df,
        config=config,
        retries=args.retries,
        timeout=args.timeout,
        workers=args.workers,
        progress_every=args.progress_every,
    )

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
        "mode": mode_name,
        "start_date": start_date,
        "end_date": args.end_date,
        "stock_data_source": "AKShare stock_zh_a_hist_tx (Tencent, qfq)",
        "benchmark_data_source": (
            "AKShare stock_zh_index_daily_tx (Tencent, sh000300)"
        ),
        "universe_data_source": "AKShare stock_info_a_code_name",
        "requested_count": len(stocks),
        "successful_count": len(records),
        "error_count": len(errors),
        "unsupported_market_skipped_count": skipped_market,
        "percentile_required": bool(args.all),
        "percentile_is_full_market": percentile_is_full_market,
        "percentile_universe_size": percentile_universe_size,
        "percentile_note": (
            "由本次成功扫描股票的60日收益计算全市场百分位"
            if percentile_is_full_market
            else (
                "使用 --limit，排名只覆盖被限制的扫描集合，不代表全市场"
                if args.all
                else "小样本模式不计算、也不强制市场百分位"
            )
        ),
        "config": asdict(config),
    }
    write_outputs(args.output_dir.resolve(), records, errors, metadata)

    confirmed = sum(record["technical_pass"] for record in records)
    watchlist = sum(
        record["base_filters"]["passed"] and record["technical_score"] == 4
        for record in records
    )
    print("扫描完成。")
    print(f"成功分析：{len(records)}；失败/跳过：{len(errors)}")
    print(f"5/5 技术确认：{confirmed}；4/5 观察池：{watchlist}")
    if args.all:
        scope = "全市场" if percentile_is_full_market else "受限集合"
        print(f"60 日收益百分位：{scope}，有效样本 {percentile_universe_size}")
    else:
        print("60 日收益百分位：N/A（小样本模式不强制）")
    print(f"结果目录：{args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
