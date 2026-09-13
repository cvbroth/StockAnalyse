"""筛选结果的JSON和CSV输出。"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


CSV_FIELDS = (
    "code", "name", "as_of_date", "close", "return_20d_pct",
    "return_60d_pct", "hs300_return_20d_pct", "hs300_return_60d_pct",
    "excess_return_20d_pct", "excess_return_60d_pct", "market_percentile",
    "market_percentile_required", "base_filters_passed", "price_structure",
    "ma_trend", "volume_price", "breakout_retest", "relative_strength",
    "technical_score", "technical_pass", "tier",
    "technical_quality_score", "overheat_penalty", "quality_rank",
    "quality_comparable", "missing_conditions",
)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except (ValueError, AttributeError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def flatten_record(record: dict[str, Any]) -> dict[str, Any]:
    relative = record["conditions"]["relative_strength"]["detail"]
    quality = record.get("quality", {})
    return {
        "code": record["code"],
        "name": record["name"],
        "as_of_date": record["as_of_date"],
        "close": record["metrics"]["close"],
        "return_20d_pct": record["metrics"]["return_20d"] * 100.0,
        "return_60d_pct": record["metrics"]["return_60d"] * 100.0,
        "hs300_return_20d_pct": relative["hs300_return_20d"] * 100.0,
        "hs300_return_60d_pct": relative["hs300_return_60d"] * 100.0,
        "excess_return_20d_pct": relative["excess_return_20d"] * 100.0,
        "excess_return_60d_pct": relative["excess_return_60d"] * 100.0,
        "market_percentile": relative["market_percentile"],
        "market_percentile_required": relative["market_percentile_required"],
        "base_filters_passed": record["base_filters"]["passed"],
        "price_structure": record["conditions"]["price_structure"]["passed"],
        "ma_trend": record["conditions"]["ma_trend"]["passed"],
        "volume_price": record["conditions"]["volume_price"]["passed"],
        "breakout_retest": record["conditions"]["breakout_retest"]["passed"],
        "relative_strength": record["conditions"]["relative_strength"]["passed"],
        "technical_score": record["technical_score"],
        "technical_pass": record["technical_pass"],
        "tier": record["tier"],
        "technical_quality_score": quality.get("technical_quality_score"),
        "overheat_penalty": quality.get("overheat_penalty"),
        "quality_rank": quality.get("rank_within_tier"),
        "quality_comparable": quality.get("score_comparable_to_full_market"),
        "missing_conditions": ",".join(quality.get("missing_conditions", [])),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_outputs(
    output_dir: Path,
    records: list[dict[str, Any]],
    errors: list[dict[str, str]],
    metadata: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    eligible = [record for record in records if record["base_filters"]["passed"]]
    eligible.sort(
        key=lambda item: (
            item["technical_score"],
            item.get("quality", {}).get("technical_quality_score", -1.0),
            item["metrics"]["return_60d"],
        ),
        reverse=True,
    )
    candidates = [record for record in eligible if record["technical_score"] >= 3]
    selections = {
        "candidates.json": candidates,
        "technical_pass_5of5.json": [
            record for record in eligible if record["technical_score"] == 5
        ],
        "watchlist_4of5.json": [
            record for record in eligible if record["technical_score"] == 4
        ],
    }
    confirmed = selections["technical_pass_5of5.json"]
    watchlist = selections["watchlist_4of5.json"]
    confirmed_top_n = int(metadata.get("quality_confirmed_top_n", 25))
    watchlist_top_n = int(metadata.get("quality_watchlist_top_n", 30))
    selections.update(
        {
            "technical_ranked_5of5.json": confirmed,
            "technical_top.json": confirmed[:confirmed_top_n],
            "watchlist_ranked_4of5.json": watchlist[:watchlist_top_n],
            "transitions.json": [
                record
                for record in candidates
                if record.get("transition", {}).get("status")
                not in {None, "unchanged", "still_5of5"}
            ],
        }
    )
    for filename, selected_records in selections.items():
        write_json(
            output_dir / filename,
            {
                "metadata": {**metadata, "record_count": len(selected_records)},
                "records": selected_records,
            },
        )
    pd.DataFrame(
        [flatten_record(record) for record in candidates], columns=CSV_FIELDS
    ).to_csv(output_dir / "candidates.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(errors, columns=["code", "name", "error"]).to_csv(
        output_dir / "errors.csv", index=False, encoding="utf-8-sig"
    )
