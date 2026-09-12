"""A 股筛选器 v1.2 的 SQLite 数据访问层。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


SCHEMA_VERSION = "2"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def connect_database(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=60.0)
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

        CREATE TABLE IF NOT EXISTS securities (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            market TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS daily_bars (
            code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            amount REAL,
            adj_factor REAL NOT NULL,
            source TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (code, trade_date)
        );

        CREATE INDEX IF NOT EXISTS idx_daily_bars_date
            ON daily_bars (trade_date);

        CREATE TABLE IF NOT EXISTS index_bars (
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            source TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (symbol, trade_date)
        );

        CREATE TABLE IF NOT EXISTS trade_date_status (
            trade_date TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            daily_rows INTEGER NOT NULL DEFAULT 0,
            factor_rows INTEGER NOT NULL DEFAULT 0,
            stored_rows INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS security_update_status (
            provider TEXT NOT NULL,
            code TEXT NOT NULL,
            status TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            stored_rows INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (provider, code)
        );

        CREATE TABLE IF NOT EXISTS update_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            dates_requested INTEGER NOT NULL DEFAULT 0,
            dates_succeeded INTEGER NOT NULL DEFAULT 0,
            rows_written INTEGER NOT NULL DEFAULT 0,
            error TEXT
        );
        """
    )
    connection.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    connection.commit()


def get_metadata(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute(
        "SELECT value FROM metadata WHERE key=?", (key,)
    ).fetchone()
    return str(row[0]) if row is not None else None


def set_metadata(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        """
        INSERT INTO metadata(key, value) VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, value),
    )


def infer_data_provider(connection: sqlite3.Connection) -> str | None:
    configured = get_metadata(connection, "data_provider")
    sources = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT source FROM daily_bars"
        ).fetchall()
    }
    if not sources:
        return configured
    if sources == {"tushare"}:
        inferred = "tushare"
    elif sources == {"akshare_tencent_qfq"}:
        inferred = "tx"
    else:
        inferred = "mixed"
    if configured is not None and configured != inferred:
        return "mixed"
    return configured or inferred


def bind_data_provider(connection: sqlite3.Connection, provider: str) -> str:
    if provider not in {"tx", "tushare"}:
        raise ValueError(f"不支持的数据源：{provider}")

    existing = infer_data_provider(connection)
    if existing is not None and existing != provider:
        raise ValueError(
            f"数据库已经绑定数据源 {existing!r}，不能改为 {provider!r}。"
            "请使用新的 --db 路径重新初始化。"
        )
    set_metadata(connection, "data_provider", provider)
    connection.commit()
    return provider


def market_from_code(code: str) -> str:
    if code.startswith("6"):
        return "SH"
    if code.startswith(("0", "3")):
        return "SZ"
    if code.startswith(("4", "8", "9")):
        return "BJ"
    return "UNKNOWN"


def upsert_securities(
    connection: sqlite3.Connection,
    securities: Iterable[tuple[str, str]],
) -> int:
    timestamp = now_iso()
    rows = [
        (str(code).zfill(6), str(name), market_from_code(str(code).zfill(6)), timestamp)
        for code, name in securities
    ]
    connection.executemany(
        """
        INSERT INTO securities(code, name, market, active, updated_at)
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(code) DO UPDATE SET
            name=excluded.name,
            market=excluded.market,
            active=1,
            updated_at=excluded.updated_at
        """,
        rows,
    )
    return len(rows)


def upsert_daily_bars(connection: sqlite3.Connection, frame: pd.DataFrame) -> int:
    required = {
        "code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adj_factor",
        "source",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"日线数据缺少字段：{sorted(missing)}")

    timestamp = now_iso()
    rows = [
        (
            str(row.code).zfill(6),
            str(row.trade_date),
            float(row.open),
            float(row.high),
            float(row.low),
            float(row.close),
            float(row.volume),
            None if pd.isna(row.amount) else float(row.amount),
            float(row.adj_factor),
            str(row.source),
            timestamp,
        )
        for row in frame.itertuples(index=False)
    ]
    connection.executemany(
        """
        INSERT INTO daily_bars(
            code, trade_date, open, high, low, close, volume,
            amount, adj_factor, source, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(code, trade_date) DO UPDATE SET
            open=excluded.open,
            high=excluded.high,
            low=excluded.low,
            close=excluded.close,
            volume=excluded.volume,
            amount=excluded.amount,
            adj_factor=excluded.adj_factor,
            source=excluded.source,
            updated_at=excluded.updated_at
        """,
        rows,
    )
    return len(rows)


def replace_daily_bars_for_code(
    connection: sqlite3.Connection,
    frame: pd.DataFrame,
) -> int:
    """用同一来源的一段完整行情替换单只股票，避免动态前复权口径残留。"""

    if frame.empty:
        raise ValueError("不能用空行情替换股票数据")
    codes = frame["code"].astype(str).str.zfill(6).unique().tolist()
    if len(codes) != 1:
        raise ValueError(f"替换操作必须且只能包含一只股票，实际为：{codes}")
    connection.execute("DELETE FROM daily_bars WHERE code=?", (codes[0],))
    return upsert_daily_bars(connection, frame)


def upsert_index_bars(
    connection: sqlite3.Connection,
    frame: pd.DataFrame,
    symbol: str = "sh000300",
) -> int:
    required = {"trade_date", "open", "high", "low", "close", "volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"指数数据缺少字段：{sorted(missing)}")

    timestamp = now_iso()
    rows = [
        (
            symbol,
            str(row.trade_date),
            float(row.open),
            float(row.high),
            float(row.low),
            float(row.close),
            float(row.volume),
            "akshare_tencent",
            timestamp,
        )
        for row in frame.itertuples(index=False)
    ]
    connection.executemany(
        """
        INSERT INTO index_bars(
            symbol, trade_date, open, high, low, close, volume, source, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, trade_date) DO UPDATE SET
            open=excluded.open,
            high=excluded.high,
            low=excluded.low,
            close=excluded.close,
            volume=excluded.volume,
            source=excluded.source,
            updated_at=excluded.updated_at
        """,
        rows,
    )
    return len(rows)


def set_trade_date_status(
    connection: sqlite3.Connection,
    trade_date: str,
    status: str,
    daily_rows: int = 0,
    factor_rows: int = 0,
    stored_rows: int = 0,
    error: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO trade_date_status(
            trade_date, status, daily_rows, factor_rows,
            stored_rows, error, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date) DO UPDATE SET
            status=excluded.status,
            daily_rows=excluded.daily_rows,
            factor_rows=excluded.factor_rows,
            stored_rows=excluded.stored_rows,
            error=excluded.error,
            updated_at=excluded.updated_at
        """,
        (
            trade_date,
            status,
            int(daily_rows),
            int(factor_rows),
            int(stored_rows),
            error,
            now_iso(),
        ),
    )


def set_security_update_status(
    connection: sqlite3.Connection,
    provider: str,
    code: str,
    status: str,
    start_date: str,
    end_date: str,
    stored_rows: int = 0,
    error: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO security_update_status(
            provider, code, status, start_date, end_date,
            stored_rows, error, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, code) DO UPDATE SET
            status=excluded.status,
            start_date=excluded.start_date,
            end_date=excluded.end_date,
            stored_rows=excluded.stored_rows,
            error=excluded.error,
            updated_at=excluded.updated_at
        """,
        (
            provider,
            str(code).zfill(6),
            status,
            start_date,
            end_date,
            int(stored_rows),
            error,
            now_iso(),
        ),
    )


def completed_security_codes(
    connection: sqlite3.Connection,
    provider: str,
    start_date: str,
    end_date: str,
) -> set[str]:
    rows = connection.execute(
        """
        SELECT code
        FROM security_update_status
        WHERE provider=? AND status='complete'
          AND start_date <= ? AND end_date >= ?
        """,
        (provider, start_date, end_date),
    ).fetchall()
    return {str(row[0]) for row in rows}


def completed_trade_dates(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT trade_date FROM trade_date_status WHERE status='complete'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def latest_completed_trade_date(connection: sqlite3.Connection) -> str | None:
    row = connection.execute(
        "SELECT MAX(trade_date) FROM trade_date_status WHERE status='complete'"
    ).fetchone()
    return str(row[0]) if row and row[0] is not None else None


def start_update_run(
    connection: sqlite3.Connection,
    mode: str,
    dates_requested: int,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO update_runs(mode, started_at, status, dates_requested)
        VALUES (?, ?, 'running', ?)
        """,
        (mode, now_iso(), int(dates_requested)),
    )
    connection.commit()
    return int(cursor.lastrowid)


def finish_update_run(
    connection: sqlite3.Connection,
    run_id: int,
    status: str,
    dates_succeeded: int,
    rows_written: int,
    error: str | None = None,
) -> None:
    connection.execute(
        """
        UPDATE update_runs
        SET completed_at=?, status=?, dates_succeeded=?, rows_written=?, error=?
        WHERE run_id=?
        """,
        (
            now_iso(),
            status,
            int(dates_succeeded),
            int(rows_written),
            error,
            int(run_id),
        ),
    )
    connection.commit()


def load_securities(connection: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT code, name, market, active FROM securities ORDER BY code",
        connection,
    )


def _recent_date_floor(
    connection: sqlite3.Connection,
    table: str,
    max_dates: int,
    where_sql: str = "",
    parameters: tuple[Any, ...] = (),
) -> str | None:
    if max_dates < 1:
        raise ValueError("max_dates 必须至少为 1")
    query = (
        f"SELECT DISTINCT trade_date FROM {table} "
        f"{where_sql} ORDER BY trade_date DESC LIMIT ?"
    )
    rows = connection.execute(query, (*parameters, int(max_dates))).fetchall()
    return str(rows[-1][0]) if rows else None


def load_recent_daily_bars(
    connection: sqlite3.Connection,
    max_dates: int = 320,
    end_date: str | None = None,
    codes: Iterable[str] | None = None,
) -> pd.DataFrame:
    date_where = "WHERE trade_date <= ?" if end_date else ""
    date_params: tuple[Any, ...] = (end_date,) if end_date else ()
    floor = _recent_date_floor(
        connection,
        "daily_bars",
        max_dates=max_dates,
        where_sql=date_where,
        parameters=date_params,
    )
    if floor is None:
        return pd.DataFrame()

    clauses = ["trade_date >= ?"]
    params: list[Any] = [floor]
    if end_date:
        clauses.append("trade_date <= ?")
        params.append(end_date)
    normalized_codes = [str(code).zfill(6) for code in codes or []]
    if normalized_codes:
        placeholders = ",".join("?" for _ in normalized_codes)
        clauses.append(f"code IN ({placeholders})")
        params.extend(normalized_codes)
    query = f"""
        SELECT code, trade_date, open, high, low, close,
               volume, amount, adj_factor, source
        FROM daily_bars
        WHERE {' AND '.join(clauses)}
        ORDER BY code, trade_date
    """
    return pd.read_sql_query(query, connection, params=params)


def load_index_bars(
    connection: sqlite3.Connection,
    symbol: str = "sh000300",
    max_dates: int = 320,
    end_date: str | None = None,
) -> pd.DataFrame:
    clauses = ["symbol = ?"]
    params: list[Any] = [symbol]
    if end_date:
        clauses.append("trade_date <= ?")
        params.append(end_date)
    where = "WHERE " + " AND ".join(clauses)
    floor = _recent_date_floor(
        connection,
        "index_bars",
        max_dates=max_dates,
        where_sql=where,
        parameters=tuple(params),
    )
    if floor is None:
        return pd.DataFrame()
    clauses.append("trade_date >= ?")
    params.append(floor)
    query = f"""
        SELECT trade_date, open, high, low, close, volume, source
        FROM index_bars
        WHERE {' AND '.join(clauses)}
        ORDER BY trade_date
    """
    return pd.read_sql_query(query, connection, params=params)


def database_stats(connection: sqlite3.Connection) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    stats["data_provider"] = infer_data_provider(connection)
    stats["securities"] = int(
        connection.execute("SELECT COUNT(*) FROM securities").fetchone()[0]
    )
    stats["daily_rows"] = int(
        connection.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
    )
    stats["daily_codes"] = int(
        connection.execute("SELECT COUNT(DISTINCT code) FROM daily_bars").fetchone()[0]
    )
    row = connection.execute(
        "SELECT MIN(trade_date), MAX(trade_date) FROM daily_bars"
    ).fetchone()
    stats["daily_start"] = row[0]
    stats["daily_end"] = row[1]
    stats["completed_dates"] = int(
        connection.execute(
            "SELECT COUNT(*) FROM trade_date_status WHERE status='complete'"
        ).fetchone()[0]
    )
    stats["failed_dates"] = int(
        connection.execute(
            "SELECT COUNT(*) FROM trade_date_status WHERE status='failed'"
        ).fetchone()[0]
    )
    stats["latest_completed_date"] = latest_completed_trade_date(connection)
    provider = stats["data_provider"]
    if provider in {"tx", "tushare"}:
        stats["completed_securities"] = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM security_update_status
                WHERE provider=? AND status='complete'
                """,
                (provider,),
            ).fetchone()[0]
        )
        stats["failed_securities"] = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM security_update_status
                WHERE provider=? AND status='failed'
                """,
                (provider,),
            ).fetchone()[0]
        )
    else:
        stats["completed_securities"] = 0
        stats["failed_securities"] = 0
    return stats
