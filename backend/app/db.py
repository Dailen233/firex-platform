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

# Result history (one row per published result; capture_id unique -> one result per capture).
# A2 2D-observation columns are nullable: patch_id/patch_geometry stay NOT NULL with
# an empty sentinel ("") for detection-only providers, so pre-A2 rows remain valid.
_RESULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    plant_id TEXT NOT NULL,
    scene_id TEXT NOT NULL,
    asset_version TEXT NOT NULL,
    coordinate_frame_id TEXT NOT NULL,
    observation_time_s REAL NOT NULL,
    produced_at TEXT NOT NULL,
    result_origin TEXT NOT NULL,
    provider_version TEXT NOT NULL,
    evidence_capture_ids TEXT NOT NULL,
    patch_id TEXT NOT NULL,
    patch_geometry TEXT NOT NULL,
    capture_id TEXT NOT NULL UNIQUE,
    fire_detected INTEGER,
    detections TEXT,
    model_ref TEXT,
    threshold REAL,
    flame TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
)
"""

# Current snapshot per run (the newest published observation).
_SNAPSHOTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    run_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL,
    result_id INTEGER NOT NULL,
    observation_time_s REAL NOT NULL,
    produced_at TEXT NOT NULL,
    result_origin TEXT NOT NULL,
    provider_version TEXT NOT NULL,
    evidence_capture_ids TEXT NOT NULL,
    patch_id TEXT NOT NULL,
    patch_geometry TEXT NOT NULL,
    fire_detected INTEGER,
    detections TEXT,
    model_ref TEXT,
    threshold REAL,
    flame TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
)
"""

# Offline multiview reconstruction frames published per run. Each run has its
# own independent, strictly increasing revision; one row per published frame.
_RECONSTRUCTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS reconstruction_frames (
    run_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    group_id TEXT NOT NULL,
    simulation_time_s REAL NOT NULL,
    source TEXT NOT NULL,
    voxel_count INTEGER NOT NULL,
    voxel_size_m REAL NOT NULL DEFAULT 4.0,
    byte_size INTEGER NOT NULL,
    ply_sha256 TEXT NOT NULL,
    glb_sha256 TEXT,
    mask_source TEXT,
    produced_at TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    PRIMARY KEY (run_id, revision),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
)
"""

# Uploaded-ZIP reconstruction jobs: one ZIP is one simulation time point. The
# worker reconstructs a single group and publishes it as the next frame revision.
_RECONSTRUCTION_JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS reconstruction_jobs (
    job_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    received_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    error TEXT,
    simulation_time_s REAL,
    group_id TEXT,
    voxel_count INTEGER,
    mask_source TEXT,
    revision INTEGER,
    storage_key TEXT NOT NULL,
    zip_sha256 TEXT NOT NULL,
    zip_byte_size INTEGER NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
)
"""

# Optional columns added to pre-existing reconstruction_frames tables.
_RECONSTRUCTION_OPTIONAL_COLUMNS = (
    ("mask_source", "TEXT"),
)

_CAPTURE_PROCESSING_COLUMNS = (
    ("processing_started_at", "TEXT"),
    ("processing_finished_at", "TEXT"),
    ("processing_error", "TEXT"),
    ("provider_version", "TEXT"),
)

# Observation columns added to pre-existing results/snapshots tables.
_RESULT_OPTIONAL_COLUMNS = (
    ("fire_detected", "INTEGER"),
    ("detections", "TEXT"),
    ("model_ref", "TEXT"),
    ("threshold", "REAL"),
    ("flame", "TEXT"),
)


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(_RUNS_SCHEMA)
        _migrate_runs(conn)
        conn.execute(_CAPTURES_SCHEMA)
        _migrate_captures(conn)
        conn.execute(_RESULTS_SCHEMA)
        _migrate_results(conn)
        conn.execute(_SNAPSHOTS_SCHEMA)
        _migrate_snapshots(conn)
        conn.execute(_RECONSTRUCTION_SCHEMA)
        _migrate_reconstruction(conn)
        conn.execute(_RECONSTRUCTION_JOBS_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _migrate_runs(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    if "simulation_time_origin_s" not in cols:
        conn.execute("ALTER TABLE runs ADD COLUMN simulation_time_origin_s REAL")
    if "time_origin_utc" not in cols:
        conn.execute("ALTER TABLE runs ADD COLUMN time_origin_utc TEXT")


def _migrate_captures(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(captures)")}
    for name, decl in _CAPTURE_PROCESSING_COLUMNS:
        if name not in cols:
            conn.execute(f"ALTER TABLE captures ADD COLUMN {name} {decl}")


def _migrate_results(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(results)")}
    for name, decl in _RESULT_OPTIONAL_COLUMNS:
        if name not in cols:
            conn.execute(f"ALTER TABLE results ADD COLUMN {name} {decl}")


def _migrate_snapshots(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(snapshots)")}
    for name, decl in _RESULT_OPTIONAL_COLUMNS:
        if name not in cols:
            conn.execute(f"ALTER TABLE snapshots ADD COLUMN {name} {decl}")


def _migrate_reconstruction(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(reconstruction_frames)")}
    for name, decl in _RECONSTRUCTION_OPTIONAL_COLUMNS:
        if name not in cols:
            conn.execute(f"ALTER TABLE reconstruction_frames ADD COLUMN {name} {decl}")


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn
