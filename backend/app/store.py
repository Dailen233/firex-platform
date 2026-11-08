"""Run repository: create and query runs; derive the initial state snapshot.

The initial state is a fixed ``no_observation`` snapshot derived from the
immutable run record, so repeated GET requests never bump ``revision``, refresh
the observation time, or fabricate results.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db, results
from .models import SCHEMA_VERSION, RunCreate, RunRecord, RunState
from .time_contract import TIME_BASIS


def create_run(path: Path, data: RunCreate) -> RunRecord:
    run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    time_origin_utc = data.time_origin_utc.isoformat() if data.time_origin_utc is not None else None
    conn = db.connect(path)
    try:
        conn.execute(
            "INSERT INTO runs (run_id, plant_id, scene_id, asset_version, coordinate_frame_id, input_source, created_at, schema_version, simulation_time_origin_s, time_origin_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                data.plant_id,
                data.scene_id,
                data.asset_version,
                data.coordinate_frame_id,
                data.input_source,
                created_at.isoformat(),
                SCHEMA_VERSION,
                data.simulation_time_origin_s,
                time_origin_utc,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return RunRecord(
        run_id=run_id,
        plant_id=data.plant_id,
        scene_id=data.scene_id,
        asset_version=data.asset_version,
        coordinate_frame_id=data.coordinate_frame_id,
        input_source=data.input_source,
        created_at=created_at,
        schema_version=SCHEMA_VERSION,
        simulation_time_origin_s=data.simulation_time_origin_s,
        time_origin_utc=data.time_origin_utc,
    )


def get_run(path: Path, run_id: str) -> RunRecord | None:
    conn = db.connect(path)
    try:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _row_to_record(row)


def get_run_state(path: Path, run_id: str) -> RunState | None:
    run = get_run(path, run_id)
    if run is None:
        return None
    snap = results.get_snapshot(path, run_id)
    if snap is None:
        return RunState(
            run_id=run.run_id,
            plant_id=run.plant_id,
            scene_id=run.scene_id,
            asset_version=run.asset_version,
            coordinate_frame_id=run.coordinate_frame_id,
            input_source=run.input_source,
            schema_version=run.schema_version,
            state_status="no_observation",
            revision=0,
            observation_time_s=None,
            result_origin=None,
            provider_version=None,
            evidence_capture_ids=[],
            patches=[],
            produced_at=run.created_at,
            time_basis=TIME_BASIS[run.input_source],
            simulation_time_origin_s=run.simulation_time_origin_s,
            time_origin_utc=run.time_origin_utc,
        )
    return RunState(
        run_id=run.run_id,
        plant_id=run.plant_id,
        scene_id=run.scene_id,
        asset_version=run.asset_version,
        coordinate_frame_id=run.coordinate_frame_id,
        input_source=run.input_source,
        schema_version=run.schema_version,
        state_status="observation",
        revision=snap.revision,
        observation_time_s=snap.observation_time_s,
        result_origin=snap.result_origin,
        provider_version=snap.provider_version,
        evidence_capture_ids=snap.evidence_capture_ids,
        patches=snap.patches,
        produced_at=snap.produced_at,
        time_basis=TIME_BASIS[run.input_source],
        simulation_time_origin_s=run.simulation_time_origin_s,
        time_origin_utc=run.time_origin_utc,
        detections=snap.detections,
        fire_detected=snap.fire_detected,
        model_ref=snap.model_ref,
        threshold=snap.threshold,
    )


def _row_to_record(row: Any) -> RunRecord:
    sim_origin = row["simulation_time_origin_s"]
    time_origin_raw = row["time_origin_utc"]
    return RunRecord(
        run_id=row["run_id"],
        plant_id=row["plant_id"],
        scene_id=row["scene_id"],
        asset_version=row["asset_version"],
        coordinate_frame_id=row["coordinate_frame_id"],
        input_source=row["input_source"],
        created_at=datetime.fromisoformat(row["created_at"]),
        schema_version=row["schema_version"],
        simulation_time_origin_s=None if sim_origin is None else float(sim_origin),
        time_origin_utc=None if time_origin_raw is None else datetime.fromisoformat(time_origin_raw),
    )
