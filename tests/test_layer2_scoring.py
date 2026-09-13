from __future__ import annotations

import copy
import unittest

from app.analysis import ScreenConfig, analysis_config_hash, load_layer2_config
from app.analysis.layer2 import Layer2Analyzer, Layer2Config, rank_layer2_records


def quality_record(code: str = "600000") -> dict:
    conditions = {
        "price_structure": {
            "passed": True,
            "detail": {
                "recent_high": 11.0,
                "previous_high": 10.0,
                "recent_low": 10.0,
                "previous_low": 9.2,
            },
        },
        "ma_trend": {
            "passed": True,
            "detail": {
                "ma20": 10.0,
                "ma60": 9.2,
                "ma20_5d_rise": 0.035,
                "ma60_10d_rise": 0.035,
            },
        },
        "volume_price": {
            "passed": True,
            "detail": {"up_down_volume_ratio": 1.8},
        },
        "breakout_retest": {
            "passed": True,
            "detail": {
                "breakout_found": True,
                "breakout_price": 9.8,
                "breakout_volume_lots": 2000.0,
                "prior_20d_average_volume_lots": 1000.0,
                "post_breakout_volume_ratio_to_prior_average": 0.75,
                "days_since_breakout": 4,
                "minimum_close_since_breakout": 9.7,
            },
        },
        "relative_strength": {
            "passed": True,
            "detail": {
                "market_percentile": 95.0,
                "market_percentile_required": True,
                "hs300_return_20d": 0.02,
                "hs300_return_60d": 0.06,
                "excess_return_20d": 0.08,
                "excess_return_60d": 0.24,
            },
        },
    }
    return {
        "code": code,
        "name": "评分样本",
        "as_of_date": "2026-09-11",
        "base_filters": {"passed": True},
        "conditions": conditions,
        "metrics": {"close": 10.3, "return_20d": 0.10, "return_60d": 0.30},
        "technical_score": 5,
        "technical_score_max": 5,
        "technical_pass": True,
        "tier": "5/5 技术确认",
    }


class Layer2ScoringTests(unittest.TestCase):
    def test_default_weights_total_one_hundred(self) -> None:
        loaded = load_layer2_config()
        self.assertEqual(loaded.version, "layer2-v1.0")
        self.assertAlmostEqual(loaded.quality.weights.positive_total, 100.0)

    def test_configuration_hash_changes_with_scoring_configuration(self) -> None:
        baseline = Layer2Config()
        changed = Layer2Config(confirmed_top_n=30)
        self.assertNotEqual(
            analysis_config_hash(ScreenConfig(), baseline),
            analysis_config_hash(ScreenConfig(), changed),
        )

    def test_quality_score_is_explainable_and_bounded(self) -> None:
        result = Layer2Analyzer().analyze(quality_record(), Layer2Config())
        self.assertGreater(result.technical_quality_score, 0.0)
        self.assertLessEqual(result.technical_quality_score, 100.0)
        self.assertEqual(
            set(result.component_scores),
            {
                "price_structure",
                "ma_trend",
                "volume_price",
                "breakout_retest",
                "relative_strength",
            },
        )
        self.assertEqual(result.missing_conditions, ())
        self.assertTrue(result.score_comparable_to_full_market)

    def test_overextended_stock_receives_visible_penalty(self) -> None:
        normal = Layer2Analyzer().analyze(quality_record(), Layer2Config())
        extended_record = quality_record()
        extended_record["metrics"]["close"] = 13.5
        extended = Layer2Analyzer().analyze(extended_record, Layer2Config())
        self.assertGreater(extended.overheat_penalty, normal.overheat_penalty)
        self.assertLess(extended.technical_quality_score, normal.technical_quality_score)

    def test_small_sample_score_is_marked_non_comparable(self) -> None:
        record = quality_record()
        record["conditions"]["relative_strength"]["detail"]["market_percentile"] = None
        result = Layer2Analyzer().analyze(record, Layer2Config())
        self.assertFalse(result.score_comparable_to_full_market)
        self.assertEqual(result.available_weight, 90.0)

    def test_ranking_is_separate_inside_each_tier(self) -> None:
        first = quality_record("600001")
        second = copy.deepcopy(quality_record("600002"))
        second["metrics"]["close"] = 13.5
        watch = copy.deepcopy(quality_record("600003"))
        watch["technical_score"] = 4
        watch["conditions"]["volume_price"]["passed"] = False
        rank_layer2_records([second, watch, first], Layer2Config())
        self.assertEqual(first["quality"]["rank_within_tier"], 1)
        self.assertEqual(second["quality"]["rank_within_tier"], 2)
        self.assertEqual(watch["quality"]["rank_within_tier"], 1)


if __name__ == "__main__":
    unittest.main()
