"""SQLite 存储：批次、采信、样本、隔离、重复、网格、窗口、对账。

数值列一律用 TEXT 存 Decimal 字面量，避免浮点往返丢精度；
时间列一律存 UTC ISO8601 秒级字符串。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Sequence

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    run_key       TEXT NOT NULL UNIQUE,
    created_at    TEXT NOT NULL,
    rule_version  TEXT NOT NULL,
    sample_name   TEXT NOT NULL,
    offset_name   TEXT NOT NULL,
    params_json   TEXT NOT NULL,
    input_json    TEXT NOT NULL,
    counts_json   TEXT NOT NULL,
    totals_json   TEXT NOT NULL,
    elapsed_ms    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS intake (
    run_id     TEXT NOT NULL,
    encoding   TEXT NOT NULL,
    bom        INTEGER NOT NULL,
    delimiter  TEXT NOT NULL,
    header_json TEXT NOT NULL,
    segments   INTEGER NOT NULL,
    blank_lines INTEGER NOT NULL,
    truncated  INTEGER NOT NULL,
    byte_size  INTEGER NOT NULL,
    sha256     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offsets (
    run_id     TEXT NOT NULL,
    sensor_id  TEXT NOT NULL,
    start_utc  TEXT NOT NULL,
    end_utc    TEXT NOT NULL,
    seconds    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS samples (
    run_id     TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    sensor_id  TEXT NOT NULL,
    bucket_utc TEXT NOT NULL,
    value      TEXT NOT NULL,
    unit       TEXT NOT NULL,
    quality    TEXT NOT NULL,
    quality_rank INTEGER NOT NULL,
    ingest_seq INTEGER NOT NULL,
    offset_seconds INTEGER NOT NULL,
    late       INTEGER NOT NULL,
    flags      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quarantine (
    run_id     TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    sensor_id  TEXT,
    column_name TEXT,
    raw_value  TEXT,
    code       TEXT NOT NULL,
    label      TEXT NOT NULL,
    detail     TEXT
);

CREATE TABLE IF NOT EXISTS duplicates (
    run_id     TEXT NOT NULL,
    sensor_id  TEXT NOT NULL,
    bucket_utc TEXT NOT NULL,
    kept_row   INTEGER NOT NULL,
    dropped_row INTEGER NOT NULL,
    kept_value TEXT NOT NULL,
    dropped_value TEXT NOT NULL,
    kept_quality TEXT NOT NULL,
    dropped_quality TEXT NOT NULL,
    code       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS grid (
    run_id     TEXT NOT NULL,
    sensor_id  TEXT NOT NULL,
    bucket_utc TEXT NOT NULL,
    value      TEXT,
    unit       TEXT NOT NULL,
    state      TEXT NOT NULL,
    reason     TEXT NOT NULL,
    fill_policy TEXT NOT NULL,
    source_row INTEGER
);

CREATE TABLE IF NOT EXISTS windows (
    run_id     TEXT NOT NULL,
    sensor_id  TEXT NOT NULL,
    window_start TEXT NOT NULL,
    observed   INTEGER NOT NULL,
    expected   INTEGER NOT NULL,
    coverage   TEXT NOT NULL,
    state      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reconcile (
    run_id     TEXT NOT NULL,
    line_no    INTEGER NOT NULL,
    name       TEXT NOT NULL,
    expected   TEXT NOT NULL,
    actual     TEXT NOT NULL,
    delta      TEXT NOT NULL,
    state      TEXT NOT NULL,
    note       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_samples_run ON samples(run_id);
CREATE INDEX IF NOT EXISTS idx_quarantine_run ON quarantine(run_id);
CREATE INDEX IF NOT EXISTS idx_grid_run ON grid(run_id);
CREATE INDEX IF NOT EXISTS idx_windows_run ON windows(run_id);
CREATE INDEX IF NOT EXISTS idx_reconcile_run ON reconcile(run_id);
CREATE INDEX IF NOT EXISTS idx_duplicates_run ON duplicates(run_id);
"""


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    target = Path(path) if path is not None else config.db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def session(path: str | Path | None = None) -> sqlite3.Connection:
    conn = connect(path)
    init_db(conn)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def rows(conn: sqlite3.Connection, sql: str, params: Sequence = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, params).fetchall())


def one(conn: sqlite3.Connection, sql: str, params: Sequence = ()) -> sqlite3.Row | None:
    return conn.execute(sql, params).fetchone()


def value(conn: sqlite3.Connection, sql: str, params: Sequence = (), default=None):
    row = one(conn, sql, params)
    if row is None:
        return default
    return row[0]


def insert_many(conn: sqlite3.Connection, sql: str, records: Iterable[Sequence]) -> int:
    payload = list(records)
    if not payload:
        return 0
    conn.executemany(sql, payload)
    return len(payload)


def reset(path: str | Path | None = None) -> None:
    """重建数据库（README 里记录的恢复方式）。"""
    target = Path(path) if path is not None else config.db_path()
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(target) + suffix)
        if candidate.exists():
            candidate.unlink()
