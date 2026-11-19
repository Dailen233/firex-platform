"""Uploaded-ZIP reconstruction job persistence.

A job is one uploaded ZIP (one simulation time point). The reconstruction worker
runs jobs serially, one at a time; on success it publishes the reconstructed
frame as the next run revision via ``reconstruction.publish_frame``.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .models import ReconstructionJob

STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

SOURCE_UPLOADED_ZIP = "uploaded_zip"

_ZIP_FILENAME = "capture.zip"


@dataclass
class JobTask:
    job_id: str
    run_id: str
    zip_path: Path
    zip_sha256: str
    zip_byte_size: int


def _new_job_id() -> str:
    return uuid.uuid4().hex


def _persist_zip(jobs_dir: Path, storage_key: str, zip_bytes: bytes) -> None:
    jobs_dir.mkdir(parents=True, exist_ok=True)
    final_dir = jobs_dir / storage_key
    tmp_dir = Path(tempfile.mkdtemp(dir=jobs_dir, prefix=".tmp-"))
    try:
        (tmp_dir / _ZIP_FILENAME).write_bytes(zip_bytes)
        os.replace(tmp_dir, final_dir)
    except Exception:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def save_job(db_path: Path, jobs_dir: Path, run_id: str, zip_bytes: bytes) -> ReconstructionJob:
    """Persist an uploaded ZIP and queue its reconstruction."""
    job_id = _new_job_id()
    zip_sha = hashlib.sha256(zip_bytes).hexdigest()
    received_at = datetime.now(timezone.utc)

    conn = db.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO reconstruction_jobs "
            "(job_id, run_id, status, source, received_at, storage_key, zip_sha256, zip_byte_size) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, run_id, STATUS_QUEUED, SOURCE_UPLOADED_ZIP, received_at.isoformat(), job_id, zip_sha, len(zip_bytes)),
        )
        try:
            _persist_zip(jobs_dir, job_id, zip_bytes)
        except Exception:
            conn.rollback()
            raise
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    return ReconstructionJob(
        job_id=job_id,
        run_id=run_id,
        status=STATUS_QUEUED,
        source=SOURCE_UPLOADED_ZIP,
        received_at=received_at,
        zip_sha256=zip_sha,
        zip_byte_size=len(zip_bytes),
    )


def claim_next_job(db_path: Path) -> str | None:
    """Atomically claim the oldest queued job; returns its job_id or None."""
    conn = db.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT job_id FROM reconstruction_jobs WHERE status = ? ORDER BY received_at ASC LIMIT 1",
            (STATUS_QUEUED,),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        job_id = row["job_id"]
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE reconstruction_jobs SET status = ?, started_at = ? WHERE job_id = ?",
            (STATUS_PROCESSING, now, job_id),
        )
        conn.commit()
        return job_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def load_job(db_path: Path, jobs_dir: Path, job_id: str) -> JobTask:
    conn = db.connect(db_path)
    try:
        row = conn.execute("SELECT * FROM reconstruction_jobs WHERE job_id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise LookupError(f"job not found: {job_id}")
    zip_path = jobs_dir / row["storage_key"] / _ZIP_FILENAME
    if not zip_path.is_file():
        raise LookupError(f"job ZIP missing: {job_id}")
    return JobTask(
        job_id=job_id,
        run_id=row["run_id"],
        zip_path=zip_path,
        zip_sha256=row["zip_sha256"],
        zip_byte_size=row["zip_byte_size"],
    )


def complete_job(
    db_path: Path,
    job_id: str,
    *,
    simulation_time_s: float,
    group_id: str,
    voxel_count: int,
    mask_source: str | None,
    revision: int,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = db.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE reconstruction_jobs SET status = ?, finished_at = ?, error = NULL, "
            "simulation_time_s = ?, group_id = ?, voxel_count = ?, mask_source = ?, revision = ? "
            "WHERE job_id = ?",
            (STATUS_COMPLETED, now, simulation_time_s, group_id, voxel_count, mask_source, revision, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def fail_job(db_path: Path, job_id: str, error: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = db.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE reconstruction_jobs SET status = ?, finished_at = ?, error = ? "
            "WHERE job_id = ? AND status IN (?, ?)",
            (STATUS_FAILED, now, error[:1000], job_id, STATUS_QUEUED, STATUS_PROCESSING),
        )
        conn.commit()
    finally:
        conn.close()


def get_job(db_path: Path, job_id: str) -> ReconstructionJob | None:
    conn = db.connect(db_path)
    try:
        row = conn.execute("SELECT * FROM reconstruction_jobs WHERE job_id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _row_to_job(row)


def recover_interrupted_jobs(db_path: Path) -> int:
    """Re-queue jobs left ``processing`` by a previous crash (safe: nothing was published)."""
    conn = db.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "UPDATE reconstruction_jobs SET status = ?, started_at = NULL WHERE status = ?",
            (STATUS_QUEUED, STATUS_PROCESSING),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def _maybe_dt(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _row_to_job(row: sqlite3.Row) -> ReconstructionJob:
    return ReconstructionJob(
        job_id=row["job_id"],
        run_id=row["run_id"],
        status=row["status"],
        source=row["source"],
        received_at=datetime.fromisoformat(row["received_at"]),
        started_at=_maybe_dt(row["started_at"]),
        finished_at=_maybe_dt(row["finished_at"]),
        error=row["error"],
        simulation_time_s=row["simulation_time_s"],
        group_id=row["group_id"],
        voxel_count=row["voxel_count"],
        mask_source=row["mask_source"],
        revision=row["revision"],
        zip_sha256=row["zip_sha256"],
        zip_byte_size=row["zip_byte_size"],
    )
