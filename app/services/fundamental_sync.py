"""由技术候选清单驱动的基本面数据准备与可续传同步。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from ..fundamentals import (
    FUNDAMENTAL_DATA_SCHEMA_VERSION,
    FundamentalFetchRequest,
)
from ..providers.fundamentals import FundamentalDataProvider
from ..storage.fundamentals_sqlite import (
    needs_sync,
    record_candidate_requests,
    set_sync_status,
    upsert_observations,
)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def select_fundamental_candidates(
    layer2_records: Iterable[dict[str, Any]],
    run_id: str,
    as_of_date: str,
    top_n: int,
    quarters: int,
) -> list[FundamentalFetchRequest]:
    """从第二层技术候选中选择需要补基本面数据的股票。"""

    if top_n < 1:
        raise ValueError("top_n 必须至少为1")
    if quarters < 1:
        raise ValueError("quarters 必须至少为1")
    eligible = [
        item
        for item in layer2_records
        if bool(item.get("base_filters", {}).get("passed"))
        and int(item.get("technical_score", 0)) >= 4
    ]
    eligible.sort(
        key=lambda item: (
            int(item.get("technical_score", 0)),
            float(item.get("quality", {}).get("technical_quality_score", -1.0)),
            float(item.get("metrics", {}).get("return_60d", -1.0)),
        ),
        reverse=True,
    )
    requests: list[FundamentalFetchRequest] = []
    for item in eligible[:top_n]:
        technical_score = int(item.get("technical_score", 0))
        quality = item.get("quality", {})
        requests.append(
            FundamentalFetchRequest(
                run_id=run_id,
                code=str(item["code"]),
                name=str(item.get("name", "未知名称")),
                as_of_date=as_of_date,
                requested_quarters=quarters,
                technical_score=technical_score,
                technical_quality_score=float(
                    quality.get("technical_quality_score", 0.0)
                ),
                quality_rank=(
                    int(quality["rank_within_tier"])
                    if quality.get("rank_within_tier") is not None
                    else None
                ),
                selection_reason=(
                    "Layer2 5/5技术确认池排名"
                    if technical_score == 5
                    else "Layer2 4/5技术观察池排名"
                ),
            )
        )
    return requests


def prepare_fundamental_requests(
    connection: Any,
    requests: list[FundamentalFetchRequest],
    run_directory: Path,
    config_version: str,
    provider: str,
    run_id: str | None = None,
    as_of_date: str | None = None,
) -> Path:
    """登记稀疏候选范围并写入不可污染Layer1/2的独立请求文件。"""

    record_candidate_requests(connection, requests)
    target_directory = run_directory / "fundamental"
    target_directory.mkdir(parents=True, exist_ok=True)
    path = target_directory / "request.json"
    write_json_atomic(
        path,
        {
            "metadata": {
                "schema_version": FUNDAMENTAL_DATA_SCHEMA_VERSION,
                "config_version": config_version,
                "provider": provider,
                "status": "prepared",
                "record_count": len(requests),
                "run_id": requests[0].run_id if requests else (run_id or run_directory.name),
                "as_of_date": requests[0].as_of_date if requests else as_of_date,
            },
            "records": [item.to_record() for item in requests],
        },
    )
    return path


def synchronize_fundamental_candidates(
    connection: Any,
    provider: FundamentalDataProvider,
    requests: Iterable[FundamentalFetchRequest],
    stale_after_days: int,
) -> dict[str, Any]:
    """按股票提交、失败可续传；不会影响技术分析快照。"""

    summary: dict[str, Any] = {
        "provider": provider.provider_id,
        "requested": 0,
        "fetched": 0,
        "cached": 0,
        "failed": 0,
        "observations_written": 0,
        "errors": [],
    }
    for request in requests:
        summary["requested"] += 1
        if not needs_sync(
            connection,
            provider.provider_id,
            request,
            stale_after_days,
        ):
            summary["cached"] += 1
            continue
        set_sync_status(connection, provider.provider_id, request, "running")
        try:
            dataset = provider.fetch(request)
            if dataset.provider != provider.provider_id:
                raise ValueError("提供者返回的数据源身份不一致")
            if dataset.code != request.code:
                raise ValueError("提供者返回了其他股票的数据")
            if dataset.as_of_date != request.as_of_date:
                raise ValueError("提供者返回的数据截止日期与请求不一致")
            count = upsert_observations(connection, dataset.observations)
            connection.commit()
            set_sync_status(
                connection,
                provider.provider_id,
                request,
                "complete",
                observation_count=count,
            )
            summary["fetched"] += 1
            summary["observations_written"] += count
        except Exception as exc:
            connection.rollback()
            message = str(exc)
            set_sync_status(
                connection,
                provider.provider_id,
                request,
                "failed",
                error=message,
            )
            summary["failed"] += 1
            summary["errors"].append(
                {"code": request.code, "name": request.name, "error": message}
            )
    return summary
