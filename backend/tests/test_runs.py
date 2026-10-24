"""B1 backend tests: run creation, persistent query, time contract, validation and 404."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.models import RunCreate
from app.time_contract import (
    observation_time_s_for_real,
    observation_time_s_for_simulation,
)

SIM_RUN = {
    "plant_id": "GEM_HYDRO_SHUANGJIANGKOU",
    "scene_id": "shuangjiangkou_reference_terrain",
    "asset_version": "reference-v1",
    "coordinate_frame_id": "SJK_REFERENCE_UTM47N_EGM2008_v1",
    "input_source": "simulation",
    "simulation_time_origin_s": 10.0,
}

REAL_RUN = {
    "plant_id": "GEM_HYDRO_SHUANGJIANGKOU",
    "scene_id": "shuangjiangkou_reference_terrain",
    "asset_version": "reference-v1",
    "coordinate_frame_id": "SJK_REFERENCE_UTM47N_EGM2008_v1",
    "input_source": "real",
    "time_origin_utc": "2026-10-24T00:00:00+00:00",
}


def make_client(data_dir: Path) -> TestClient:
    return TestClient(create_app(db_path_override=data_dir / "runs.sqlite3"))


def test_health_reports_algorithm_unconfigured(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "algorithm_mode": "unconfigured"}


def test_create_then_get_binding_consistent(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    created = client.post("/api/v1/runs", json=SIM_RUN)
    assert created.status_code == 201
    body = created.json()
    run_id = body["run_id"]
    assert run_id
    for key in ("plant_id", "scene_id", "asset_version", "coordinate_frame_id"):
        assert body[key] == SIM_RUN[key]
    assert body["input_source"] == "simulation"
    assert body["simulation_time_origin_s"] == 10.0
    assert body["time_origin_utc"] is None
    assert body["schema_version"] == "1.0"
    assert body["created_at"].endswith(("Z", "+00:00"))

    fetched = client.get(f"/api/v1/runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json()["run_id"] == run_id
    assert fetched.json()["simulation_time_origin_s"] == 10.0


def test_simulation_and_real_time_config_persisted(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    sim = client.post("/api/v1/runs", json=SIM_RUN).json()
    real = client.post("/api/v1/runs", json=REAL_RUN).json()

    sim_state = client.get(f"/api/v1/runs/{sim['run_id']}/state").json()
    assert sim_state["time_basis"] == "simulation_relative"
    assert sim_state["simulation_time_origin_s"] == 10.0
    assert sim_state["time_origin_utc"] is None

    real_state = client.get(f"/api/v1/runs/{real['run_id']}/state").json()
    assert real_state["time_basis"] == "utc_anchored"
    assert real_state["simulation_time_origin_s"] is None
    assert real_state["time_origin_utc"] == "2026-10-24T00:00:00Z"


def test_time_validation_errors(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    # simulation without origin
    sim_missing = dict(SIM_RUN)
    sim_missing.pop("simulation_time_origin_s")
    assert client.post("/api/v1/runs", json=sim_missing).status_code == 422

    # simulation with negative origin
    assert client.post("/api/v1/runs", json=dict(SIM_RUN, simulation_time_origin_s=-5)).status_code == 422

    # real without time_origin_utc
    real_missing = dict(REAL_RUN)
    real_missing.pop("time_origin_utc")
    assert client.post("/api/v1/runs", json=real_missing).status_code == 422

    # real with naive (timezone-less) time_origin_utc
    naive = dict(REAL_RUN, time_origin_utc="2026-10-24T00:00:00")
    r = client.post("/api/v1/runs", json=naive)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    # cross-field misuse: simulation with time_origin_utc set
    assert client.post("/api/v1/runs", json=dict(SIM_RUN, time_origin_utc="2026-10-24T00:00:00Z")).status_code == 422


def test_simulation_origin_must_be_finite() -> None:
    with pytest.raises(ValidationError):
        RunCreate(
            plant_id="x", scene_id="y", asset_version="z",
            input_source="simulation", simulation_time_origin_s=float("inf"),
        )
    with pytest.raises(ValidationError):
        RunCreate(
            plant_id="x", scene_id="y", asset_version="z",
            input_source="simulation", simulation_time_origin_s=float("nan"),
        )


def test_invalid_input_and_unknown_run(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    bad_source = dict(SIM_RUN, input_source="bogus")
    assert client.post("/api/v1/runs", json=bad_source).status_code == 422
    assert client.post("/api/v1/runs", json={"plant_id": "x"}).status_code == 422

    unknown = client.get("/api/v1/runs/does-not-exist")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "NOT_FOUND"
    assert client.get("/api/v1/runs/does-not-exist/state").status_code == 404


def test_time_conversion_examples() -> None:
    # simulation: observation_time_s = simulation_time_s - simulation_time_origin_s
    assert observation_time_s_for_simulation(15.5, 10.0) == 5.5
    # real: observation_time_s = (captured_at - time_origin_utc) in seconds
    origin = datetime(2026, 10, 24, 0, 0, 0, tzinfo=timezone.utc)
    captured = datetime(2026, 10, 24, 0, 0, 5, tzinfo=timezone.utc)
    assert observation_time_s_for_real(captured, origin) == 5.0


def test_reopen_same_db_preserves_time_config(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = client.post("/api/v1/runs", json=SIM_RUN).json()["run_id"]

    # a fresh app instance on the same database must see the run with its time config
    client2 = make_client(tmp_path)
    fetched = client2.get(f"/api/v1/runs/{run_id}").json()
    assert fetched["run_id"] == run_id
    assert fetched["simulation_time_origin_s"] == 10.0

    state = client2.get(f"/api/v1/runs/{run_id}/state").json()
    assert state["state_status"] == "no_observation"
    assert state["simulation_time_origin_s"] == 10.0


def test_state_stays_no_observation_without_revision_bump(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = client.post("/api/v1/runs", json=SIM_RUN).json()["run_id"]

    first = client.get(f"/api/v1/runs/{run_id}/state").json()
    for _ in range(3):
        body = client.get(f"/api/v1/runs/{run_id}/state").json()
        assert body["state_status"] == "no_observation"
        assert body["revision"] == 0
        assert body["observation_time_s"] is None
        assert body["result_origin"] is None
        assert body["evidence_capture_ids"] == []
        assert body["patches"] == []
    again = client.get(f"/api/v1/runs/{run_id}/state").json()
    assert again["produced_at"] == first["produced_at"]
    assert first["schema_version"] == "1.0"
    assert first["time_basis"] == "simulation_relative"
