"""A1 atlas fire-status aggregation: derive a per-run map summary.

Read-only: builds a small per-plant summary from explicitly monitored runs and
their latest snapshot. The derived ``alert_status`` distinguishes, in order:

- ``no_observation``: no snapshot yet (not "no fire").
- ``no_detection``: a valid observation that carries no fire evidence.
- ``fire``: a fresh, valid observation with positive fire evidence (current alert).
- ``stale``: an observation older than the freshness window (historical).

Only ``fire`` is a current alert; older records stay visible but are not counted
as current alerts. A processing failure, a disconnected backend or a missing run
never maps to "no fire"/"extinguished".
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .models import AtlasFireStatusItem, RunRecord, RunState
from .store import get_run, get_run_state


def derive_fire_status_item(
    run: RunRecord,
    state: RunState,
    fresh_after_s: int,
    now: datetime,
) -> AtlasFireStatusItem:
    patch_count = len(state.patches)
    detection_count = len(state.detections)
    if state.state_status == "no_observation":
        alert_status = "no_observation"
        fire_detected = False
        is_fresh = False
    else:
        produced = state.produced_at
        age_s: float | None = None
        if produced is not None:
            if produced.tzinfo is None:
                produced = produced.replace(tzinfo=timezone.utc)
            age_s = (now - produced).total_seconds()
        is_fresh = age_s is not None and age_s <= fresh_after_s
        # Positive fire evidence: either a published 3D patch (fixture) or an
        # explicit 2D verdict from a detection provider (yolo). A valid "no
        # detection" (both empty / verdict False) ends the current alert.
        fire_detected = patch_count > 0 or bool(state.fire_detected)
        if not is_fresh:
            alert_status = "stale"
        elif not fire_detected:
            alert_status = "no_detection"
        else:
            alert_status = "fire"
    return AtlasFireStatusItem(
        plant_id=run.plant_id,
        run_id=run.run_id,
        scene_id=run.scene_id,
        asset_version=run.asset_version,
        coordinate_frame_id=run.coordinate_frame_id,
        input_source=run.input_source,
        state_status=state.state_status,
        alert_status=alert_status,
        fire_detected=fire_detected,
        is_fresh=is_fresh,
        revision=state.revision,
        observation_time_s=state.observation_time_s,
        time_basis=state.time_basis,
        result_origin=state.result_origin,
        provider_version=state.provider_version,
        produced_at=state.produced_at,
        evidence_capture_ids=state.evidence_capture_ids,
        patch_count=patch_count,
        detection_count=detection_count,
        model_ref=state.model_ref,
        threshold=state.threshold,
    )


def list_fire_status(
    db_path: Path,
    monitored_run_ids: list[str],
    fresh_after_s: int,
    now: datetime,
) -> list[AtlasFireStatusItem]:
    """Summarize each monitored run that exists; unknown ids are skipped."""
    items: list[AtlasFireStatusItem] = []
    for run_id in monitored_run_ids:
        run = get_run(db_path, run_id)
        if run is None:
            continue
        state = get_run_state(db_path, run_id)
        if state is None:
            continue
        items.append(derive_fire_status_item(run, state, fresh_after_s, now))
    return items
