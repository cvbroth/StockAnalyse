"""第二层评分配置与结果模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Layer2Weights:
    structure_high: float = 7.5
    structure_low: float = 7.5
    ma20_slope: float = 6.0
    ma60_slope: float = 5.0
    ma_spread: float = 4.0
    price_position: float = 5.0
    up_down_volume: float = 8.0
    breakout_volume: float = 7.0
    retest_volume: float = 5.0
    breakout_recency: float = 8.0
    breakout_extension: float = 10.0
    breakout_support: float = 7.0
    market_percentile: float = 10.0
    excess_return_20d: float = 4.0
    excess_return_60d: float = 6.0
    overheat_ma20: float = 10.0
    overheat_breakout: float = 10.0

    @property
    def positive_total(self) -> float:
        return sum(
            value
            for key, value in self.__dict__.items()
            if not key.startswith("overheat_")
        )


@dataclass(frozen=True)
class Layer2Thresholds:
    structure_full_rise: float = 0.10
    ma20_slope_full: float = 0.04
    ma60_slope_full: float = 0.05
    ma_spread_full: float = 0.12
    price_ma20_lower_zero: float = -0.03
    price_ma20_ideal_high: float = 0.08
    price_ma20_upper_zero: float = 0.15
    volume_ratio_zero: float = 1.00
    volume_ratio_full: float = 2.00
    breakout_volume_zero: float = 1.00
    breakout_volume_full: float = 2.00
    retest_volume_full: float = 0.80
    retest_volume_zero: float = 1.50
    breakout_recency_full_days: float = 5.0
    breakout_recency_zero_days: float = 20.0
    breakout_extension_lower_zero: float = -0.10
    breakout_extension_ideal_low: float = -0.03
    breakout_extension_ideal_high: float = 0.08
    breakout_extension_upper_zero: float = 0.30
    breakout_support_zero: float = -0.10
    breakout_support_full: float = -0.03
    market_percentile_zero: float = 50.0
    market_percentile_full: float = 100.0
    excess_return_20d_full: float = 0.10
    excess_return_60d_full: float = 0.30
    overheat_ma20_start: float = 0.15
    overheat_ma20_full: float = 0.25
    overheat_breakout_start: float = 0.20
    overheat_breakout_full: float = 0.30


@dataclass(frozen=True)
class Layer2Config:
    confirmed_top_n: int = 25
    watchlist_top_n: int = 30
    weights: Layer2Weights = Layer2Weights()
    thresholds: Layer2Thresholds = Layer2Thresholds()


@dataclass(frozen=True)
class Layer2Result:
    component_scores: dict[str, float]
    raw_quality_score: float
    available_weight: float
    overheat_penalty: float
    technical_quality_score: float
    score_comparable_to_full_market: bool
    missing_conditions: tuple[str, ...]
    metrics: dict[str, Any]

    def to_record(self) -> dict[str, Any]:
        return {
            "component_scores": dict(self.component_scores),
            "raw_quality_score": self.raw_quality_score,
            "available_weight": self.available_weight,
            "overheat_penalty": self.overheat_penalty,
            "technical_quality_score": self.technical_quality_score,
            "score_comparable_to_full_market": (
                self.score_comparable_to_full_market
            ),
            "missing_conditions": list(self.missing_conditions),
            "metrics": dict(self.metrics),
        }
