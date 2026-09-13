"""第一层0至5分资格分与分层标签。"""

from __future__ import annotations

from typing import Any

from ..models import CONDITION_KEYS


def score_summary(
    base_filters: dict[str, Any],
    conditions: dict[str, Any],
) -> tuple[int, int, bool, str]:
    score = sum(bool(conditions[key]["passed"]) for key in CONDITION_KEYS)
    score_max = len(CONDITION_KEYS)
    base_passed = bool(base_filters["passed"])
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
    return score, score_max, bool(base_passed and score == score_max), tier


def refresh_score(record: dict[str, Any]) -> None:
    score, score_max, technical_pass, tier = score_summary(
        record["base_filters"],
        record["conditions"],
    )
    record["technical_score"] = score
    record["technical_score_max"] = score_max
    record["technical_pass"] = technical_pass
    record["tier"] = tier
