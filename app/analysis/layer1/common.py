"""第一层模块共享的无状态计算工具。"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import pandas as pd


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
    normalized = normalize_code(code)
    if normalized.startswith("6"):
        return f"sh{normalized}"
    if normalized.startswith(("0", "3")):
        return f"sz{normalized}"
    return None


def is_supported_a_share(code: str) -> bool:
    return normalize_code(code).startswith(("0", "3", "4", "6", "8", "9"))


def parse_yyyymmdd(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"日期 {value!r} 格式错误，应为 YYYYMMDD") from exc


def period_return(close: pd.Series, trading_days: int) -> float:
    if len(close) <= trading_days:
        return math.nan
    start_value = float(close.iloc[-(trading_days + 1)])
    end_value = float(close.iloc[-1])
    return end_value / start_value - 1.0 if start_value > 0 else math.nan


def aligned_returns(
    stock_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    trading_days: int,
) -> tuple[float, float]:
    merged = stock_df[["date", "close"]].merge(
        benchmark_df[["date", "close"]],
        on="date",
        how="inner",
        suffixes=("_stock", "_benchmark"),
    )
    if len(merged) <= trading_days:
        return math.nan, math.nan
    window = merged.iloc[-(trading_days + 1):]
    stock_start = float(window["close_stock"].iloc[0])
    benchmark_start = float(window["close_benchmark"].iloc[0])
    if stock_start <= 0 or benchmark_start <= 0:
        return math.nan, math.nan
    return (
        float(window["close_stock"].iloc[-1]) / stock_start - 1.0,
        float(window["close_benchmark"].iloc[-1]) / benchmark_start - 1.0,
    )
