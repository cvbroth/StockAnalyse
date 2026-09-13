"""稀疏基本面缓存库；与全市场行情库物理隔离。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from ..fundamentals import (
    FUNDAMENTAL_DATA_SCHEMA_VERSION,
    FundamentalFetchRequest,
    FundamentalObservation,
)


SCHEMA_VERSION = "2"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def connect_fundamental_database(path: str | Path) -> sqlite3.Connection:
    database = Path(path).expanduser().resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=60.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA busy_timeout=60000")
    initialize_schema(connection)
    return connection


def initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS candidate_requests (
            run_id TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            as_of_date TEXT NOT NULL,
            requested_quarters INTEGER NOT NULL,
            technical_score INTEGER NOT NULL,
            technical_quality_score REAL NOT NULL,
            quality_rank INTEGER,
            selection_reason TEXT NOT NULL,
            selected_at TEXT NOT NULL,
            PRIMARY KEY (run_id, code)
        );

        CREATE INDEX IF NOT EXISTS idx_candidate_requests_code
            ON candidate_requests(code, as_of_date);

        CREATE TABLE IF NOT EXISTS fundamental_observations (
            code TEXT NOT NULL,
            metric TEXT NOT NULL,
            period_end TEXT NOT NULL,
            published_date TEXT NOT NULL,
            available_at TEXT NOT NULL,
            value REAL,
            unit TEXT NOT NULL,
            source TEXT NOT NULL,
            source_record_id TEXT NOT NULL,
            availability_basis TEXT NOT NULL DEFAULT 'reported',
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (
                code, metric, period_end, available_at,
                source, source_record_id
            )
        );

        CREATE INDEX IF NOT EXISTS idx_fundamental_observations_lookup
            ON fundamental_observations(code, metric, available_at, period_end);

        CREATE TABLE IF NOT EXISTS fundamental_sync_status (
            provider TEXT NOT NULL,
            code TEXT NOT NULL,
            status TEXT NOT NULL,
            checked_through_date TEXT NOT NULL,
            requested_quarters INTEGER NOT NULL,
            observation_count INTEGER NOT NULL DEFAULT 0,
            last_checked_at TEXT NOT NULL,
            error TEXT,
            PRIMARY KEY (provider, code)
        );
        """
    )
    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(fundamental_observations)"
        ).fetchall()
    }
    if "availability_basis" not in columns:
        connection.execute(
            """
            ALTER TABLE fundamental_observations
            ADD COLUMN availability_basis TEXT NOT NULL DEFAULT 'reported'
            """
        )
    connection.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
        ("schema_version", SCHEMA_VERSION),
    )
    connection.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
        ("data_contract_version", FUNDAMENTAL_DATA_SCHEMA_VERSION),
    )
    connection.commit()


def record_candidate_requests(
    connection: sqlite3.Connection,
    requests: Iterable[FundamentalFetchRequest],
) -> int:
    timestamp = now_iso()
    rows = [
        (
            item.run_id,
            item.code,
            item.name,
            item.as_of_date,
            item.requested_quarters,
            item.technical_score,
            item.technical_quality_score,
            item.quality_rank,
            item.selection_reason,
            timestamp,
        )
        for item in requests
    ]
    connection.executemany(
        """
        INSERT INTO candidate_requests(
            run_id, code, name, as_of_date, requested_quarters,
            technical_score, technical_quality_score, quality_rank,
            selection_reason, selected_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, code) DO UPDATE SET
            name=excluded.name,
            as_of_date=excluded.as_of_date,
            requested_quarters=excluded.requested_quarters,
            technical_score=excluded.technical_score,
            technical_quality_score=excluded.technical_quality_score,
            quality_rank=excluded.quality_rank,
            selection_reason=excluded.selection_reason,
            selected_at=excluded.selected_at
        """,
        rows,
    )
    connection.commit()
    return len(rows)


def upsert_observations(
    connection: sqlite3.Connection,
    observations: Iterable[FundamentalObservation],
) -> int:
    timestamp = now_iso()
    rows = [
        (
            item.code,
            item.metric,
            item.period_end,
            item.published_date,
            item.available_at,
            item.value,
            item.unit,
            item.source,
            item.source_record_id,
            item.availability_basis,
            timestamp,
        )
        for item in observations
    ]
    connection.executemany(
        """
        INSERT INTO fundamental_observations(
            code, metric, period_end, published_date, available_at,
            value, unit, source, source_record_id, availability_basis, fetched_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(
            code, metric, period_end, available_at, source, source_record_id
        ) DO UPDATE SET
            published_date=excluded.published_date,
            value=excluded.value,
            unit=excluded.unit,
            availability_basis=excluded.availability_basis,
            fetched_at=excluded.fetched_at
        """,
        rows,
    )
    return len(rows)


def set_sync_status(
    connection: sqlite3.Connection,
    provider: str,
    request: FundamentalFetchRequest,
    status: str,
    observation_count: int = 0,
    error: str | None = None,
) -> None:
    if status not in {"running", "complete", "failed"}:
        raise ValueError(f"基本面同步状态无效：{status}")
    connection.execute(
        """
        INSERT INTO fundamental_sync_status(
            provider, code, status, checked_through_date,
            requested_quarters, observation_count, last_checked_at, error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, code) DO UPDATE SET
            status=excluded.status,
            checked_through_date=excluded.checked_through_date,
            requested_quarters=excluded.requested_quarters,
            observation_count=excluded.observation_count,
            last_checked_at=excluded.last_checked_at,
            error=excluded.error
        """,
        (
            provider,
            request.code,
            status,
            request.as_of_date,
            request.requested_quarters,
            int(observation_count),
            now_iso(),
            error,
        ),
    )
    connection.commit()


def needs_sync(
    connection: sqlite3.Connection,
    provider: str,
    request: FundamentalFetchRequest,
    stale_after_days: int,
    now: datetime | None = None,
) -> bool:
    if stale_after_days < 0:
        raise ValueError("stale_after_days 不能为负数")
    row = connection.execute(
        """
        SELECT status, checked_through_date, requested_quarters, last_checked_at
        FROM fundamental_sync_status
        WHERE provider=? AND code=?
        """,
        (provider, request.code),
    ).fetchone()
    if row is None or row["status"] != "complete":
        return True
    if int(row["requested_quarters"]) < request.requested_quarters:
        return True
    checked_through = str(row["checked_through_date"])
    if checked_through == request.as_of_date:
        return False
    # 较新的“最近八季”不保证包含旧截面所需的八季，历史请求必须单独校验/获取。
    if checked_through > request.as_of_date:
        return True
    checked_at = datetime.fromisoformat(str(row["last_checked_at"]))
    current = now or datetime.now().astimezone()
    if checked_at.tzinfo is None and current.tzinfo is not None:
        checked_at = checked_at.replace(tzinfo=current.tzinfo)
    return checked_at < current - timedelta(days=stale_after_days)


def load_observations(
    connection: sqlite3.Connection,
    code: str,
    as_of_date: str,
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT code, metric, period_end, published_date, available_at,
               value, unit, source, source_record_id,
               availability_basis, fetched_at
        FROM fundamental_observations
        WHERE code=? AND available_at<=?
        ORDER BY period_end, metric, available_at
        """,
        (str(code).zfill(6), as_of_date),
    ).fetchall()


def fundamental_database_stats(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        "candidate_runs": int(
            connection.execute(
                "SELECT COUNT(DISTINCT run_id) FROM candidate_requests"
            ).fetchone()[0]
        ),
        "candidate_codes": int(
            connection.execute(
                "SELECT COUNT(DISTINCT code) FROM candidate_requests"
            ).fetchone()[0]
        ),
        "observations": int(
            connection.execute(
                "SELECT COUNT(*) FROM fundamental_observations"
            ).fetchone()[0]
        ),
        "completed_codes": int(
            connection.execute(
                "SELECT COUNT(*) FROM fundamental_sync_status WHERE status='complete'"
            ).fetchone()[0]
        ),
        "failed_codes": int(
            connection.execute(
                "SELECT COUNT(*) FROM fundamental_sync_status WHERE status='failed'"
            ).fetchone()[0]
        ),
    }
