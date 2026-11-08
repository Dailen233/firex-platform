"""A1 atlas fire-status aggregation tests."""
from __future__ import annotations

import io
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.atlas import derive_fire_status_item
from app.main import create_app
from app.models import RunRecord, RunState

SIM_RUN = {
    "plant_id": "GEM_HYDRO_SHUANGJIANGKOU",
    "scene_id": "shuangjiangkou_reference_terrain",
    "asset_version": "reference-v1",
    "coordinate_frame_id": "SJK_REFERENCE_UTM47N_EGM2008_v1",
    "input_source": "simulation",
    "simulation_time_origin_s": 10.0,
}


@contextmanager
def make_client(data_dir: Path, processing_mode: str = "fixture"):
    with TestClient(
        create_app(
            db_path_override=data_dir / "runs.sqlite3",
            captures_dir_override=data_dir / "captures",
            processing_mode=processing_mode,
        )
    ) as client:
        yield client


def create_run(client: TestClient) -> str:
    r = client.post("/api/v1/runs", json=SIM_RUN)
    assert r.status_code == 201, r.text
    return r.json()["run_id"]


def make_png(width: int = 10, height: int = 8) -> bytes:
    img = Image.new("RGB", (width, height), (120, 60, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_metadata(capture_id: str, simulation_time_s: float = 15.5) -> dict:
    return {
        "schema_version": "1.0",
        "capture_id": capture_id,
        "scene_id": SIM_RUN["scene_id"],
        "asset_version": SIM_RUN["asset_version"],
        "coordinate_frame_id": SIM_RUN["coordinate_frame_id"],
        "width": 10,
        "height": 8,
        "intrinsics": {"fx": 100.0, "fy": 100.0, "cx": 5, "cy": 4},
        "distortion_model": "none",
        "pose": {"camera_to_world": [[1, 0, 0, 1], [0, 1, 0, 2], [0, 0, 1, 3], [0, 0, 0, 1]]},
        "simulation_time_s": simulation_time_s,
    }


def upload(client: TestClient, run_id: str, capture_id: str, meta: dict) -> None:
    r = client.post(
        f"/api/v1/runs/{run_id}/captures",
        files={"file": ("x.png", make_png(), "image/png")},
        data={"metadata": json.dumps(meta)},
    )
    assert r.status_code == 202, r.text


def wait_completed(client: TestClient, capture_id: str) -> None:
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if client.get(f"/api/v1/captures/{capture_id}").json()["status"] == "completed":
            return
        time.sleep(0.02)
    raise AssertionError(f"capture {capture_id} did not complete")


def test_no_monitored_runs_returns_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("FIREX_MONITORED_RUN_IDS", raising=False)
    with make_client(tmp_path) as client:
        r = client.get("/api/v1/atlas/fire-status")
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["monitored_run_ids"] == []
        assert body["fresh_after_s"] > 0


def test_unknown_monitored_run_is_skipped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FIREX_MONITORED_RUN_IDS", "does-not-exist")
    with make_client(tmp_path) as client:
        r = client.get("/api/v1/atlas/fire-status")
        assert r.status_code == 200
        body = r.json()
        assert body["monitored_run_ids"] == ["does-not-exist"]
        assert body["items"] == []


def test_monitored_run_no_observation(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path) as client:
        run_id = create_run(client)
    monkeypatch.setenv("FIREX_MONITORED_RUN_IDS", run_id)
    with make_client(tmp_path) as client:
        body = client.get("/api/v1/atlas/fire-status").json()
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["run_id"] == run_id
        assert item["plant_id"] == SIM_RUN["plant_id"]
        assert item["state_status"] == "no_observation"
        assert item["alert_status"] == "no_observation"
        assert item["fire_detected"] is False
        assert item["is_fresh"] is False
        assert item["patch_count"] == 0


def test_monitored_run_fixture_fire(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, processing_mode="fixture") as client:
        run_id = create_run(client)
        upload(client, run_id, "cap-fire", make_metadata("cap-fire", 15.5))
        wait_completed(client, "cap-fire")
    monkeypatch.setenv("FIREX_MONITORED_RUN_IDS", run_id)
    with make_client(tmp_path, processing_mode="fixture") as client:
        body = client.get("/api/v1/atlas/fire-status").json()
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["state_status"] == "observation"
        assert item["alert_status"] == "fire"
        assert item["fire_detected"] is True
        assert item["is_fresh"] is True
        assert item["revision"] == 1
        assert item["observation_time_s"] == 5.5
        assert item["result_origin"] == "fixture"
        assert item["provider_version"] == "1.0"
        assert item["evidence_capture_ids"] == ["cap-fire"]
        assert item["patch_count"] == 1


def test_stale_observation_not_counted_as_fire(tmp_path: Path, monkeypatch) -> None:
    with make_client(tmp_path, processing_mode="fixture") as client:
        run_id = create_run(client)
        upload(client, run_id, "cap-stale", make_metadata("cap-stale", 15.5))
        wait_completed(client, "cap-stale")

    # age the snapshot beyond the freshness window
    old = (datetime.now(timezone.utc) - timedelta(seconds=1000)).isoformat()
    db = sqlite3.connect(tmp_path / "runs.sqlite3")
    db.execute("UPDATE snapshots SET produced_at = ? WHERE run_id = ?", (old, run_id))
    db.commit()
    db.close()

    monkeypatch.setenv("FIREX_MONITORED_RUN_IDS", run_id)
    with make_client(tmp_path, processing_mode="fixture") as client:
        item = client.get("/api/v1/atlas/fire-status").json()["items"][0]
        assert item["state_status"] == "observation"
        assert item["alert_status"] == "stale"
        assert item["fire_detected"] is True  # evidence still positive, but not fresh
        assert item["is_fresh"] is False


def test_no_detection_forward_compatible() -> None:
    """A valid observation with no patches is 'no_detection', not 'no_observation'."""
    run = RunRecord(
        run_id="r", plant_id="p", scene_id="s", asset_version="v",
        coordinate_frame_id=None, input_source="simulation",
        created_at=datetime.now(timezone.utc), schema_version="1.0",
        simulation_time_origin_s=10.0, time_origin_utc=None,
    )
    state = RunState(
        run_id="r", plant_id="p", scene_id="s", asset_version="v",
        coordinate_frame_id=None, input_source="simulation", schema_version="1.0",
        state_status="observation", revision=1, observation_time_s=5.5,
        result_origin="fixture", provider_version="1.0", evidence_capture_ids=["c"],
        patches=[], produced_at=datetime.now(timezone.utc),
        time_basis="simulation_relative", simulation_time_origin_s=10.0, time_origin_utc=None,
    )
    item = derive_fire_status_item(run, state, 120, datetime.now(timezone.utc))
    assert item.alert_status == "no_detection"
    assert item.fire_detected is False
    assert item.is_fresh is True
