"""可解释的技术质量评分。"""

from __future__ import annotations

import math
from typing import Any

from ..models import CONDITION_KEYS
from .models import Layer2Config, Layer2Result


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _rising_score(value: Any, zero: float, full: float, weight: float) -> float:
    number = _finite(value)
    if number is None or full <= zero:
        return 0.0
    return weight * _clamp((number - zero) / (full - zero))


def _falling_score(value: Any, full: float, zero: float, weight: float) -> float:
    number = _finite(value)
    if number is None or zero <= full:
        return 0.0
    return weight * (1.0 - _clamp((number - full) / (zero - full)))


def _sweet_score(
    value: Any,
    lower_zero: float,
    ideal_low: float,
    ideal_high: float,
    upper_zero: float,
    weight: float,
) -> float:
    number = _finite(value)
    if number is None:
        return 0.0
    if ideal_low <= number <= ideal_high:
        return weight
    if lower_zero < number < ideal_low:
        return weight * (number - lower_zero) / (ideal_low - lower_zero)
    if ideal_high < number < upper_zero:
        return weight * (upper_zero - number) / (upper_zero - ideal_high)
    return 0.0


class Layer2Analyzer:
    """只读取第一层标准记录，不重新访问行情或修改资格结果。"""

    def analyze(
        self,
        record: dict[str, Any],
        config: Layer2Config,
    ) -> Layer2Result:
        weights = config.weights
        thresholds = config.thresholds
        conditions = record["conditions"]
        structure = conditions["price_structure"]["detail"]
        trend = conditions["ma_trend"]["detail"]
        volume = conditions["volume_price"]["detail"]
        breakout = conditions["breakout_retest"]["detail"]
        relative = conditions["relative_strength"]["detail"]

        recent_high = _finite(structure.get("recent_high"))
        previous_high = _finite(structure.get("previous_high"))
        recent_low = _finite(structure.get("recent_low"))
        previous_low = _finite(structure.get("previous_low"))
        high_strength = (
            recent_high / previous_high - 1.0
            if recent_high is not None and previous_high and previous_high > 0
            else None
        )
        low_strength = (
            recent_low / previous_low - 1.0
            if recent_low is not None and previous_low and previous_low > 0
            else None
        )

        close = _finite(record["metrics"].get("close"))
        ma20 = _finite(trend.get("ma20"))
        ma60 = _finite(trend.get("ma60"))
        distance_ma20 = close / ma20 - 1.0 if close is not None and ma20 else None
        ma_spread = ma20 / ma60 - 1.0 if ma20 is not None and ma60 else None

        breakout_found = bool(breakout.get("breakout_found"))
        breakout_price = _finite(breakout.get("breakout_price"))
        breakout_extension = (
            close / breakout_price - 1.0
            if breakout_found and close is not None and breakout_price
            else None
        )
        breakout_volume = _finite(breakout.get("breakout_volume_lots"))
        prior_volume = _finite(breakout.get("prior_20d_average_volume_lots"))
        breakout_volume_multiple = (
            breakout_volume / prior_volume
            if breakout_volume is not None and prior_volume and prior_volume > 0
            else None
        )
        minimum_close = _finite(breakout.get("minimum_close_since_breakout"))
        support_margin = (
            minimum_close / breakout_price - 1.0
            if minimum_close is not None and breakout_price
            else None
        )
        retest_volume_ratio = _finite(
            breakout.get("post_breakout_volume_ratio_to_prior_average")
        )

        item_scores = {
            "structure_high": _rising_score(
                high_strength, 0.0, thresholds.structure_full_rise,
                weights.structure_high,
            ),
            "structure_low": _rising_score(
                low_strength, 0.0, thresholds.structure_full_rise,
                weights.structure_low,
            ),
            "ma20_slope": _rising_score(
                trend.get("ma20_5d_rise"), 0.0, thresholds.ma20_slope_full,
                weights.ma20_slope,
            ),
            "ma60_slope": _rising_score(
                trend.get("ma60_10d_rise"), 0.0, thresholds.ma60_slope_full,
                weights.ma60_slope,
            ),
            "ma_spread": _rising_score(
                ma_spread, 0.0, thresholds.ma_spread_full, weights.ma_spread,
            ),
            "price_position": _sweet_score(
                distance_ma20,
                thresholds.price_ma20_lower_zero,
                0.0,
                thresholds.price_ma20_ideal_high,
                thresholds.price_ma20_upper_zero,
                weights.price_position,
            ),
            "up_down_volume": _rising_score(
                volume.get("up_down_volume_ratio"),
                thresholds.volume_ratio_zero,
                thresholds.volume_ratio_full,
                weights.up_down_volume,
            ),
            "breakout_volume": _rising_score(
                breakout_volume_multiple,
                thresholds.breakout_volume_zero,
                thresholds.breakout_volume_full,
                weights.breakout_volume,
            ),
            "retest_volume": _falling_score(
                retest_volume_ratio,
                thresholds.retest_volume_full,
                thresholds.retest_volume_zero,
                weights.retest_volume,
            ),
            "breakout_recency": _falling_score(
                breakout.get("days_since_breakout"),
                thresholds.breakout_recency_full_days,
                thresholds.breakout_recency_zero_days,
                weights.breakout_recency,
            ) if breakout_found else 0.0,
            "breakout_extension": _sweet_score(
                breakout_extension,
                thresholds.breakout_extension_lower_zero,
                thresholds.breakout_extension_ideal_low,
                thresholds.breakout_extension_ideal_high,
                thresholds.breakout_extension_upper_zero,
                weights.breakout_extension,
            ),
            "breakout_support": _rising_score(
                support_margin,
                thresholds.breakout_support_zero,
                thresholds.breakout_support_full,
                weights.breakout_support,
            ),
            "market_percentile": _rising_score(
                relative.get("market_percentile"),
                thresholds.market_percentile_zero,
                thresholds.market_percentile_full,
                weights.market_percentile,
            ),
            "excess_return_20d": _rising_score(
                relative.get("excess_return_20d"),
                0.0,
                thresholds.excess_return_20d_full,
                weights.excess_return_20d,
            ),
            "excess_return_60d": _rising_score(
                relative.get("excess_return_60d"),
                0.0,
                thresholds.excess_return_60d_full,
                weights.excess_return_60d,
            ),
        }
        component_scores = {
            "price_structure": item_scores["structure_high"] + item_scores["structure_low"],
            "ma_trend": sum(item_scores[key] for key in (
                "ma20_slope", "ma60_slope", "ma_spread", "price_position"
            )),
            "volume_price": sum(item_scores[key] for key in (
                "up_down_volume", "breakout_volume", "retest_volume"
            )),
            "breakout_retest": sum(item_scores[key] for key in (
                "breakout_recency", "breakout_extension", "breakout_support"
            )),
            "relative_strength": sum(item_scores[key] for key in (
                "market_percentile", "excess_return_20d", "excess_return_60d"
            )),
        }

        percentile_available = _finite(relative.get("market_percentile")) is not None
        available_weight = weights.positive_total - (
            0.0 if percentile_available else weights.market_percentile
        )
        raw_score = sum(component_scores.values())
        normalized_score = raw_score * weights.positive_total / available_weight
        ma20_penalty = _rising_score(
            distance_ma20,
            thresholds.overheat_ma20_start,
            thresholds.overheat_ma20_full,
            weights.overheat_ma20,
        )
        breakout_penalty = _rising_score(
            breakout_extension,
            thresholds.overheat_breakout_start,
            thresholds.overheat_breakout_full,
            weights.overheat_breakout,
        )
        penalty = ma20_penalty + breakout_penalty
        final_score = _clamp(normalized_score - penalty, 0.0, weights.positive_total)
        missing = tuple(
            key for key in CONDITION_KEYS if not conditions[key]["passed"]
        )
        metrics = {
            "high_strength": high_strength,
            "low_strength": low_strength,
            "distance_from_ma20": distance_ma20,
            "ma20_ma60_spread": ma_spread,
            "breakout_volume_multiple": breakout_volume_multiple,
            "post_breakout_volume_ratio": retest_volume_ratio,
            "days_since_breakout": breakout.get("days_since_breakout"),
            "extension_from_breakout": breakout_extension,
            "support_margin": support_margin,
            "ma20_overheat_penalty": ma20_penalty,
            "breakout_overheat_penalty": breakout_penalty,
        }
        return Layer2Result(
            component_scores={
                key: round(value, 4) for key, value in component_scores.items()
            },
            raw_quality_score=round(raw_score, 4),
            available_weight=round(available_weight, 4),
            overheat_penalty=round(penalty, 4),
            technical_quality_score=round(final_score, 4),
            score_comparable_to_full_market=percentile_available,
            missing_conditions=missing,
            metrics=metrics,
        )


def rank_layer2_records(
    records: list[dict[str, Any]],
    config: Layer2Config,
) -> None:
    analyzer = Layer2Analyzer()
    for record in records:
        record["quality"] = analyzer.analyze(record, config).to_record()

    eligible = [record for record in records if record["base_filters"]["passed"]]
    eligible.sort(
        key=lambda item: (
            item["technical_score"],
            item["quality"]["technical_quality_score"],
            item["metrics"]["return_60d"],
        ),
        reverse=True,
    )
    ranks: dict[int, int] = {}
    for record in eligible:
        tier_score = int(record["technical_score"])
        ranks[tier_score] = ranks.get(tier_score, 0) + 1
        record["quality"]["rank_within_tier"] = ranks[tier_score]
