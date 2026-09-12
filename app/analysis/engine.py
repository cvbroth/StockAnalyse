"""纯本地技术指标、筛选规则和市场百分位计算。"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import pandas as pd

from .models import CONDITION_KEYS, ScreenConfig


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


def evaluate_price_structure(df: pd.DataFrame, window: int) -> dict[str, Any]:
    previous = df.iloc[-2 * window:-window]
    recent = df.iloc[-window:]
    recent_high = float(recent["high"].max())
    previous_high = float(previous["high"].max())
    recent_low = float(recent["low"].min())
    previous_low = float(previous["low"].min())
    return {
        "passed": bool(recent_high > previous_high and recent_low > previous_low),
        "detail": {
            "recent_high": recent_high,
            "previous_high": previous_high,
            "recent_low": recent_low,
            "previous_low": previous_low,
            "window_days": window,
        },
    }


def evaluate_ma_trend(df: pd.DataFrame) -> dict[str, Any]:
    close = df["close"]
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    current_close = float(close.iloc[-1])
    current_ma20 = float(ma20.iloc[-1])
    current_ma60 = float(ma60.iloc[-1])
    ma20_5d_ago = float(ma20.iloc[-6])
    ma60_10d_ago = float(ma60.iloc[-11])
    return {
        "passed": bool(
            current_close > current_ma20 > current_ma60
            and current_ma20 > ma20_5d_ago
            and current_ma60 > ma60_10d_ago
        ),
        "detail": {
            "close": current_close,
            "ma20": current_ma20,
            "ma60": current_ma60,
            "ma20_5d_rise": current_ma20 / ma20_5d_ago - 1.0,
            "ma60_10d_rise": current_ma60 / ma60_10d_ago - 1.0,
        },
    }


def evaluate_volume_price(
    df: pd.DataFrame,
    window: int,
    ratio_threshold: float,
) -> dict[str, Any]:
    recent = df.iloc[-(window + 1):].copy()
    recent["change"] = recent["close"].pct_change()
    observations = recent.iloc[1:]
    up_volume = observations.loc[observations["change"] > 0, "volume"]
    down_volume = observations.loc[observations["change"] < 0, "volume"]
    up_mean = float(up_volume.mean()) if not up_volume.empty else math.nan
    down_mean = float(down_volume.mean()) if not down_volume.empty else math.nan
    ratio = up_mean / down_mean if down_mean > 0 else math.nan
    return {
        "passed": bool(math.isfinite(ratio) and ratio > ratio_threshold),
        "detail": {
            "up_day_average_volume_lots": up_mean,
            "down_day_average_volume_lots": down_mean,
            "up_down_volume_ratio": ratio,
            "up_days": int(len(up_volume)),
            "down_days": int(len(down_volume)),
            "threshold": ratio_threshold,
            "window_days": window,
        },
    }


def evaluate_breakout_retest(
    df: pd.DataFrame,
    lookback: int,
    search_days: int,
    volume_multiple: float,
    max_fall: float,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    first_position = max(lookback, len(df) - search_days)
    for position in range(first_position, len(df)):
        prior_high = float(df["high"].iloc[position - lookback:position].max())
        prior_average_volume = float(
            df["volume"].iloc[max(0, position - 20):position].mean()
        )
        close = float(df["close"].iloc[position])
        volume = float(df["volume"].iloc[position])
        if (
            prior_high > 0
            and prior_average_volume > 0
            and close > prior_high
            and volume > prior_average_volume * volume_multiple
        ):
            events.append(
                {
                    "position": position,
                    "date": df["date"].iloc[position],
                    "breakout_price": prior_high,
                    "breakout_close": close,
                    "breakout_volume_lots": volume,
                    "prior_20d_average_volume_lots": prior_average_volume,
                }
            )
    if not events:
        return {
            "passed": False,
            "detail": {
                "breakout_found": False,
                "lookback_days": lookback,
                "search_days": search_days,
                "volume_multiple_threshold": volume_multiple,
                "maximum_allowed_fall": max_fall,
            },
        }
    event = events[-1]
    minimum_close = float(df["close"].iloc[event["position"]:].min())
    support_floor = float(event["breakout_price"] * (1.0 - max_fall))
    held = minimum_close >= support_floor
    return {
        "passed": bool(held),
        "detail": {
            "breakout_found": True,
            "breakout_date": event["date"],
            "breakout_price": event["breakout_price"],
            "breakout_close": event["breakout_close"],
            "breakout_volume_lots": event["breakout_volume_lots"],
            "prior_20d_average_volume_lots": event[
                "prior_20d_average_volume_lots"
            ],
            "days_since_breakout": int(len(df) - 1 - event["position"]),
            "minimum_close_since_breakout": minimum_close,
            "support_floor": support_floor,
            "held_breakout": bool(held),
            "lookback_days": lookback,
            "search_days": search_days,
            "volume_multiple_threshold": volume_multiple,
            "maximum_allowed_fall": max_fall,
        },
    }


def evaluate_relative_strength_base(
    df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    excess_60d_threshold: float,
) -> dict[str, Any]:
    stock_20, benchmark_20 = aligned_returns(df, benchmark_df, 20)
    stock_60, benchmark_60 = aligned_returns(df, benchmark_df, 60)
    excess_20 = stock_20 - benchmark_20
    excess_60 = stock_60 - benchmark_60
    finite = all(
        math.isfinite(value)
        for value in (stock_20, benchmark_20, stock_60, benchmark_60)
    )
    benchmark_rules_passed = bool(
        finite
        and excess_20 > 0
        and stock_60 > benchmark_60
        and excess_60 > excess_60d_threshold
    )
    return {
        "passed": benchmark_rules_passed,
        "detail": {
            "stock_return_20d": stock_20,
            "hs300_return_20d": benchmark_20,
            "excess_return_20d": excess_20,
            "stock_return_60d": stock_60,
            "hs300_return_60d": benchmark_60,
            "excess_return_60d": excess_60,
            "excess_return_60d_threshold": excess_60d_threshold,
            "benchmark_rules_passed": benchmark_rules_passed,
            "market_percentile": None,
            "market_percentile_cutoff": None,
            "market_percentile_required": False,
        },
    }


def basic_filters(
    code: str,
    name: str,
    df: pd.DataFrame,
    end_date: str,
    config: ScreenConfig,
) -> dict[str, Any]:
    latest_date = pd.Timestamp(df["date"].iloc[-1])
    requested_end = pd.Timestamp(parse_yyyymmdd(end_date))
    stale_days = max(0, int((requested_end - latest_date).days))
    recent_average_volume = float(df["volume"].tail(20).mean())
    is_st = "ST" in name.upper()
    tests = {
        "supported_market": is_supported_a_share(code),
        "minimum_history": len(df) >= config.min_history_days,
        "recent_trade": stale_days <= config.max_stale_calendar_days,
        "minimum_average_volume": (
            recent_average_volume >= config.min_average_volume_lots
        ),
        "not_st": (not is_st) if config.exclude_st else True,
    }
    return {
        "passed": all(tests.values()),
        "tests": tests,
        "detail": {
            "history_days": int(len(df)),
            "minimum_history_days": config.min_history_days,
            "latest_trade_date": latest_date,
            "stale_calendar_days": stale_days,
            "max_stale_calendar_days": config.max_stale_calendar_days,
            "recent_20d_average_volume_lots": recent_average_volume,
            "minimum_average_volume_lots": config.min_average_volume_lots,
            "is_st": is_st,
        },
    }


def analyze_stock(
    code: str,
    name: str,
    df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    end_date: str,
    config: ScreenConfig,
) -> dict[str, Any]:
    required_rows = max(
        config.min_history_days,
        config.breakout_lookback + config.breakout_search_days,
        71,
    )
    if len(df) < required_rows:
        raise ValueError(f"历史交易日不足：需要至少 {required_rows}，实际 {len(df)}")
    conditions = {
        "price_structure": evaluate_price_structure(df, config.structure_window),
        "ma_trend": evaluate_ma_trend(df),
        "volume_price": evaluate_volume_price(
            df, config.volume_window, config.up_down_volume_ratio
        ),
        "breakout_retest": evaluate_breakout_retest(
            df,
            config.breakout_lookback,
            config.breakout_search_days,
            config.breakout_volume_multiple,
            config.breakout_max_fall,
        ),
        "relative_strength": evaluate_relative_strength_base(
            df, benchmark_df, config.excess_return_60d
        ),
    }
    result = {
        "code": code,
        "name": name,
        "tx_symbol": to_tx_symbol(code),
        "as_of_date": df["date"].iloc[-1],
        "base_filters": basic_filters(code, name, df, end_date, config),
        "conditions": conditions,
        "metrics": {
            "close": float(df["close"].iloc[-1]),
            "return_20d": period_return(df["close"], 20),
            "return_60d": period_return(df["close"], 60),
        },
    }
    refresh_score(result)
    return result


def refresh_score(record: dict[str, Any]) -> None:
    score = sum(
        bool(record["conditions"][key]["passed"]) for key in CONDITION_KEYS
    )
    base_passed = bool(record["base_filters"]["passed"])
    if not base_passed:
        tier = "基础过滤未通过"
    elif score == 5:
        tier = "5/5 技术确认"
    elif score == 4:
        tier = "4/5 观察池"
    elif score == 3:
        tier = "3/5 潜在观察"
    else:
        tier = f"{score}/5"
    record["technical_score"] = score
    record["technical_score_max"] = len(CONDITION_KEYS)
    record["technical_pass"] = bool(base_passed and score == len(CONDITION_KEYS))
    record["tier"] = tier


def apply_market_percentiles(records: list[dict[str, Any]], cutoff: float) -> int:
    valid = {
        record["code"]: record["metrics"]["return_60d"]
        for record in records
        if math.isfinite(float(record["metrics"]["return_60d"]))
    }
    if not valid:
        raise RuntimeError("没有可用于计算全市场60日收益百分位的数据")
    percentiles = pd.Series(valid, dtype="float64").rank(pct=True, method="average")
    for record in records:
        detail = record["conditions"]["relative_strength"]["detail"]
        percentile = percentiles.get(record["code"], math.nan)
        percentile_value = float(percentile) if pd.notna(percentile) else math.nan
        detail["market_percentile"] = percentile_value * 100.0
        detail["market_percentile_cutoff"] = cutoff * 100.0
        detail["market_percentile_required"] = True
        detail["market_percentile_universe_size"] = int(len(valid))
        record["conditions"]["relative_strength"]["passed"] = bool(
            detail["benchmark_rules_passed"]
            and math.isfinite(percentile_value)
            and percentile_value >= cutoff
        )
        refresh_score(record)
    return len(valid)


def mark_percentile_not_required(records: list[dict[str, Any]]) -> None:
    for record in records:
        detail = record["conditions"]["relative_strength"]["detail"]
        detail["market_percentile"] = None
        detail["market_percentile_cutoff"] = None
        detail["market_percentile_required"] = False
        detail["market_percentile_note"] = (
            "--symbols为小样本检查模式：未计算、也不强制样本内百分位"
        )
        record["conditions"]["relative_strength"]["passed"] = bool(
            detail["benchmark_rules_passed"]
        )
        refresh_score(record)
