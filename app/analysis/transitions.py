"""跨运行比较第一层资格状态。"""

from __future__ import annotations

from typing import Any

from .models import CONDITION_KEYS


def _eligible_score(record: dict[str, Any] | None) -> int | None:
    if record is None:
        return None
    if not bool(record.get("base_filters", {}).get("passed")):
        return 0
    return int(record.get("technical_score", 0))


def classify_transition(previous_score: int | None, current_score: int) -> str:
    if previous_score is None:
        return "first_observation"
    if current_score == 5 and previous_score < 5:
        return "newly_5of5"
    if current_score == 5 and previous_score == 5:
        return "still_5of5"
    if previous_score == 5 and current_score == 4:
        return "downgraded_to_4of5"
    if current_score == 4 and previous_score < 4:
        return "newly_4of5"
    if previous_score == 4 and current_score < 4:
        return "left_watchlist"
    if previous_score == current_score:
        return "unchanged"
    return "changed"


def apply_transitions(
    records: list[dict[str, Any]],
    previous_records: list[dict[str, Any]] | None,
    previous_run_id: str | None,
) -> dict[str, int]:
    previous_by_code = {
        str(record["code"]): record for record in (previous_records or [])
    }
    counts: dict[str, int] = {}
    for record in records:
        previous_score = _eligible_score(previous_by_code.get(str(record["code"])))
        current_score = _eligible_score(record) or 0
        status = classify_transition(previous_score, current_score)
        missing = [
            key for key in CONDITION_KEYS
            if not bool(record["conditions"][key]["passed"])
        ]
        record["transition"] = {
            "status": status,
            "previous_run_id": previous_run_id,
            "previous_score": previous_score,
            "current_score": current_score,
            "missing_conditions": missing,
        }
        record["newly_5of5"] = status == "newly_5of5"
        counts[status] = counts.get(status, 0) + 1
    return counts
