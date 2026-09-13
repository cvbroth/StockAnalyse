"""从独立基本面缓存读取数据并运行纯财务量化模块。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..analysis.fundamentals import analyze_financial_observations
from ..fundamentals import (
    FUNDAMENTAL_DATA_SCHEMA_VERSION,
    FundamentalFetchRequest,
)
from ..storage.fundamentals_sqlite import load_observations
from .fundamental_sync import write_json_atomic


def analyze_cached_fundamentals(
    connection: Any,
    requests: list[FundamentalFetchRequest],
    run_directory: Path,
    provider: str,
    config_version: str,
) -> tuple[Path, list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    for request in requests:
        all_observations = load_observations(
            connection,
            request.code,
            request.as_of_date,
        )
        recent_periods = sorted(
            {str(item["period_end"]) for item in all_observations},
            reverse=True,
        )[:request.requested_quarters]
        selected_periods = set(recent_periods)
        observations = [
            item
            for item in all_observations
            if str(item["period_end"]) in selected_periods
        ]
        result = analyze_financial_observations(observations)
        basis_counts: dict[str, int] = {}
        for observation in observations:
            basis = str(observation["availability_basis"])
            basis_counts[basis] = basis_counts.get(basis, 0) + 1
        records.append(
            {
                "code": request.code,
                "name": request.name,
                "as_of_date": request.as_of_date,
                "technical_context": {
                    "technical_score": request.technical_score,
                    "technical_quality_score": request.technical_quality_score,
                    "quality_rank": request.quality_rank,
                },
                "observation_count": len(observations),
                "availability_basis_counts": basis_counts,
                "financial_quant": result.to_record(),
            }
        )
    target = run_directory / "fundamental" / "financial_quant.json"
    write_json_atomic(
        target,
        {
            "metadata": {
                "schema_version": FUNDAMENTAL_DATA_SCHEMA_VERSION,
                "config_version": config_version,
                "provider": provider,
                "status": "complete",
                "record_count": len(records),
                "run_id": requests[0].run_id if requests else run_directory.name,
                "as_of_date": requests[0].as_of_date if requests else None,
            },
            "records": records,
        },
    )
    return target, records
