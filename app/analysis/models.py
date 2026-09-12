"""筛选规则的数据模型与集中参数。"""

from __future__ import annotations

from dataclasses import dataclass


CONDITION_KEYS = (
    "price_structure",
    "ma_trend",
    "volume_price",
    "breakout_retest",
    "relative_strength",
)


@dataclass(frozen=True)
class ScreenConfig:
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
