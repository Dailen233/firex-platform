"""SQLite persistence.

``init_db`` is idempotent and never drops or clears existing data. New columns
are added to pre-existing databases via ``ALTER TABLE`` (nullable), so records
created before the time contract keep their rows without a fabricated time
mapping (the new columns stay NULL for them).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    plant_id TEXT NOT NULL,
    scene_id TEXT NOT NULL,
    asset_version TEXT NOT NULL,
    coordinate_frame_id TEXT,
    input_source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    simulation_time_origin_s REAL,
    time_origin_utc TEXT
)
"""

_CAPTURES_SCHEMA = """
CREATE TABLE IF NOT EXISTS captures (
    capture_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    scene_id TEXT NOT NULL,
    asset_version TEXT NOT NULL,
    coordinate_frame_id TEXT NOT NULL,
    input_source TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    observation_time_s REAL NOT NULL,
    received_at TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    metadata_sha256 TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    status TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
)
"""


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(_RUNS_SCHEMA)
        _migrate_runs(conn)
        conn.execute(_CAPTURES_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _migrate_runs(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    if "simulation_time_origin_s" not in cols:
        conn.execute("ALTER TABLE runs ADD COLUMN simulation_time_origin_s REAL")
    if "time_origin_utc" not in cols:
        conn.execute("ALTER TABLE runs ADD COLUMN time_origin_utc TEXT")


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn
