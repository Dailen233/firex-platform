"""B3 persistence: task lifecycle, result history, and current snapshot.

Task flow: ``queued`` -> ``processing`` -> ``completed``/``failed``. A task is
claimed in a short transaction (``queued`` -> ``processing``), computed outside
any open write transaction, then completed in one transaction that also inserts
the result and advances the run snapshot. A crash between claim and completion
leaves the capture ``processing``, which ``recover_interrupted`` re-queues on
startup (no result was published yet, so nothing is duplicated).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .capture_metadata import CaptureMetadata
from .capture_store import read_stored_capture
from .models import Detection2D, FirePatch
from .provider import ProcessingResult

STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

# Detection-only providers publish no 3D patch; these sentinels keep the
# pre-A2 NOT NULL columns valid while meaning "no patch".
NO_PATCH_ID = ""
NO_PATCH_GEOMETRY = "[]"


@dataclass
class Snapshot:
    revision: int
    observation_time_s: float
    produced_at: datetime
    result_origin: str
    provider_version: str
    evidence_capture_ids: list[str]
    patches: list[FirePatch]
    detections: list[Detection2D]
    fire_detected: bool | None
    model_ref: str | None
    threshold: float | None


@dataclass
class CaptureTask:
    capture_id: str
    run_id: str
    plant_id: str
    scene_id: str
    asset_version: str
    coordinate_frame_id: str
    input_source: str
    observation_time_s: float
    content_sha256: str
    byte_size: int
    metadata_sha256: str
    storage_key: str


def recover_interrupted(path: Path) -> int:
    """Re-queue captures left ``processing`` by a previous crash (safe: nothing was published)."""
    conn = db.connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "UPDATE captures SET status = ?, processing_started_at = NULL WHERE status = ?",
            (STATUS_QUEUED, STATUS_PROCESSING),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def claim_next_queued(path: Path) -> str | None:
    """Atomically claim the oldest queued capture; returns its capture_id or None."""
    conn = db.connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT capture_id FROM captures WHERE status = ? ORDER BY received_at ASC LIMIT 1",
            (STATUS_QUEUED,),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        capture_id = row["capture_id"]
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE captures SET status = ?, processing_started_at = ? WHERE capture_id = ?",
            (STATUS_PROCESSING, now, capture_id),
        )
        conn.commit()
        return capture_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def load_for_processing(
    path: Path, captures_dir: Path, capture_id: str
) -> tuple[CaptureTask, CaptureMetadata, bytes]:
    """Load a claimed capture (plus run info) and verify stored content integrity."""
    conn = db.connect(path)
    try:
        row = conn.execute(
            "SELECT c.*, r.plant_id AS plant_id FROM captures c "
            "JOIN runs r ON r.run_id = c.run_id WHERE c.capture_id = ?",
            (capture_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise LookupError(f"capture not found: {capture_id}")

    original, _raw, normalized = read_stored_capture(captures_dir, row["storage_key"])
    if hashlib.sha256(original).hexdigest() != row["content_sha256"]:
        raise ValueError("stored original content hash does not match the capture record")
    if hashlib.sha256(normalized.encode("utf-8")).hexdigest() != row["metadata_sha256"]:
        raise ValueError("stored normalized metadata hash does not match the capture record")
    meta = CaptureMetadata.model_validate_json(normalized)

    task = CaptureTask(
        capture_id=row["capture_id"],
        run_id=row["run_id"],
        plant_id=row["plant_id"],
        scene_id=row["scene_id"],
        asset_version=row["asset_version"],
        coordinate_frame_id=row["coordinate_frame_id"],
        input_source=row["input_source"],
        observation_time_s=row["observation_time_s"],
        content_sha256=row["content_sha256"],
        byte_size=row["byte_size"],
        metadata_sha256=row["metadata_sha256"],
        storage_key=row["storage_key"],
    )
    return task, meta, original


def complete_and_publish(path: Path, task: CaptureTask, result: ProcessingResult) -> None:
    """Mark completed, insert the result, and advance the run snapshot (one transaction).

    Provider output is validated against the geometry contract before any write,
    and the exact duplicate (a result already exists for this capture_id) is a
    no-op that preserves the original completion.
    """
    # Validate before any write: an invalid provider result must fail the capture
    # instead of polluting results/snapshot (and later breaking GET state).
    if result.patch_id is not None:
        patch = FirePatch(patch_id=result.patch_id, geometry=result.geometry)
        patch_id, geometry_json = patch.patch_id, json.dumps(patch.geometry)
    else:
        # Detection-only result: no world geometry is fabricated for the map.
        patch_id, geometry_json = NO_PATCH_ID, NO_PATCH_GEOMETRY
    fire_detected = result.fire_detected
    if fire_detected is None:
        # Providers without an explicit 2D verdict: a published patch is the
        # positive-fire evidence (fixture). Detection providers always set it.
        fire_detected = result.patch_id is not None
    detections_json = json.dumps(
        [d.model_dump() for d in result.detections], ensure_ascii=False, allow_nan=False
    )
    now = datetime.now(timezone.utc).isoformat()
    evidence = json.dumps([task.capture_id])
    conn = db.connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        # Exact duplicate: this capture already has a published result -> keep it.
        existing = conn.execute(
            "SELECT 1 FROM results WHERE capture_id = ?", (task.capture_id,)
        ).fetchone()
        if existing is not None:
            conn.commit()
            return
        conn.execute(
            "UPDATE captures SET status = ?, processing_finished_at = ?, provider_version = ?, processing_error = NULL "
            "WHERE capture_id = ?",
            (STATUS_COMPLETED, now, result.provider_version, task.capture_id),
        )
        cur = conn.execute(
            "INSERT INTO results (run_id, plant_id, scene_id, asset_version, coordinate_frame_id, "
            "observation_time_s, produced_at, result_origin, provider_version, evidence_capture_ids, "
            "patch_id, patch_geometry, capture_id, fire_detected, detections, model_ref, threshold) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task.run_id,
                task.plant_id,
                task.scene_id,
                task.asset_version,
                task.coordinate_frame_id,
                task.observation_time_s,
                now,
                result.result_origin,
                result.provider_version,
                evidence,
                patch_id,
                geometry_json,
                task.capture_id,
                int(fire_detected),
                detections_json,
                result.model_ref,
                result.threshold,
            ),
        )
        _advance_snapshot(
            conn, task, cur.lastrowid, result, now, evidence, geometry_json, patch_id,
            fire_detected, detections_json,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _advance_snapshot(
    conn: sqlite3.Connection,
    task: CaptureTask,
    result_id: int,
    result: ProcessingResult,
    produced_at: str,
    evidence: str,
    geometry: str,
    patch_id: str,
    fire_detected: bool,
    detections_json: str,
) -> None:
    snap = conn.execute(
        "SELECT revision, observation_time_s FROM snapshots WHERE run_id = ?", (task.run_id,)
    ).fetchone()
    model_ref = result.model_ref
    threshold = result.threshold
    if snap is None:
        conn.execute(
            "INSERT INTO snapshots (run_id, revision, result_id, observation_time_s, produced_at, "
            "result_origin, provider_version, evidence_capture_ids, patch_id, patch_geometry, "
            "fire_detected, detections, model_ref, threshold) "
            "VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task.run_id,
                result_id,
                task.observation_time_s,
                produced_at,
                result.result_origin,
                result.provider_version,
                evidence,
                patch_id,
                geometry,
                int(fire_detected),
                detections_json,
                model_ref,
                threshold,
            ),
        )
        return
    # advance only on a strictly newer observation; older/equal stay history-only
    if task.observation_time_s > snap["observation_time_s"]:
        conn.execute(
            "UPDATE snapshots SET revision = ?, result_id = ?, observation_time_s = ?, produced_at = ?, "
            "result_origin = ?, provider_version = ?, evidence_capture_ids = ?, patch_id = ?, patch_geometry = ?, "
            "fire_detected = ?, detections = ?, model_ref = ?, threshold = ? "
            "WHERE run_id = ?",
            (
                snap["revision"] + 1,
                result_id,
                task.observation_time_s,
                produced_at,
                result.result_origin,
                result.provider_version,
                evidence,
                patch_id,
                geometry,
                int(fire_detected),
                detections_json,
                model_ref,
                threshold,
                task.run_id,
            ),
        )


def fail_task(path: Path, capture_id: str, error: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = db.connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        # Only fail a task still in a fail-able state; never downgrade an
        # already-completed capture (which already has a published result).
        conn.execute(
            "UPDATE captures SET status = ?, processing_finished_at = ?, processing_error = ? "
            "WHERE capture_id = ? AND status IN (?, ?)",
            (STATUS_FAILED, now, error[:1000], capture_id, STATUS_QUEUED, STATUS_PROCESSING),
        )
        conn.commit()
    finally:
        conn.close()


def get_snapshot(path: Path, run_id: str) -> Snapshot | None:
    conn = db.connect(path)
    try:
        row = conn.execute("SELECT * FROM snapshots WHERE run_id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    patches: list[FirePatch] = []
    if row["patch_id"]:
        # Detection-only rows carry the empty sentinel and no world geometry.
        patches = [FirePatch(patch_id=row["patch_id"], geometry=json.loads(row["patch_geometry"]))]
    raw_detections = json.loads(row["detections"]) if row["detections"] else []
    return Snapshot(
        revision=row["revision"],
        observation_time_s=row["observation_time_s"],
        produced_at=datetime.fromisoformat(row["produced_at"]),
        result_origin=row["result_origin"],
        provider_version=row["provider_version"],
        evidence_capture_ids=json.loads(row["evidence_capture_ids"]),
        patches=patches,
        detections=[Detection2D.model_validate(d) for d in raw_detections],
        fire_detected=None if row["fire_detected"] is None else bool(row["fire_detected"]),
        model_ref=row["model_ref"],
        threshold=row["threshold"],
    )
