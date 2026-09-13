"""进入五项技术条件前的基础过滤。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..models import ScreenConfig
from .common import is_supported_a_share, parse_yyyymmdd


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
