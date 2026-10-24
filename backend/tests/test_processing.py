"""B3 background processing tests: worker lifecycle, fixture provider, snapshots."""
from __future__ import annotations

import io
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import capture_store, results
from app.main import create_app
from app.provider import FixtureProvider, ProcessingProvider, ProcessingResult
from app.worker import Worker

SIM_RUN = {
    "plant_id": "GEM_HYDRO_SHUANGJIANGKOU",
    "scene_id": "shuangjiangkou_reference_terrain",
    "asset_version": "reference-v1",
    "coordinate_frame_id": "SJK_REFERENCE_UTM47N_EGM2008_v1",
    "input_source": "simulation",
    "simulation_time_origin_s": 10.0,
}


@contextmanager
def make_client(data_dir: Path, processing_mode: str = "unconfigured"):
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


def make_png(width: int, height: int, color: tuple = (120, 60, 30)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_metadata(capture_id: str, width: int, height: int, simulation_time_s: float = 15.5) -> dict:
    return {
        "schema_version": "1.0",
        "capture_id": capture_id,
        "scene_id": SIM_RUN["scene_id"],
        "asset_version": SIM_RUN["asset_version"],
        "coordinate_frame_id": SIM_RUN["coordinate_frame_id"],
        "width": width,
        "height": height,
        "intrinsics": {"fx": 100.0, "fy": 100.0, "cx": width / 2, "cy": height / 2},
        "distortion_model": "none",
        "pose": {"camera_to_world": [[1, 0, 0, 1], [0, 1, 0, 2], [0, 0, 1, 3], [0, 0, 0, 1]]},
        "simulation_time_s": simulation_time_s,
    }


def upload(client: TestClient, run_id: str, capture_id: str, png: bytes, meta: dict):
    return client.post(
        f"/api/v1/runs/{run_id}/captures",
        files={"file": ("x.png", png, "image/png")},
        data={"metadata": json.dumps(meta)},
    )


def wait_until(fn, timeout: float = 5.0, interval: float = 0.02) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return True
        time.sleep(interval)
    return False


def test_create_app_and_openapi_have_no_db_side_effect(tmp_path: Path) -> None:
    app = create_app(db_path_override=tmp_path / "runs.sqlite3", captures_dir_override=tmp_path / "captures")
    assert not (tmp_path / "runs.sqlite3").exists()
    app.openapi()
    assert not (tmp_path / "runs.sqlite3").exists()


def test_health_reports_fixture_mode(tmp_path: Path) -> None:
    with make_client(tmp_path, processing_mode="fixture") as client:
        r = client.get("/health")
        assert r.json()["processing_mode"] == "fixture"
        assert r.json()["service"] == "firex-backend"
        assert r.json()["algorithm_mode"] == "unconfigured"


def test_default_mode_does_not_process(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        run_id = create_run(client)
        png = make_png(10, 8)
        assert upload(client, run_id, "cap-q", png, make_metadata("cap-q", 10, 8)).status_code == 202

        time.sleep(0.3)
        assert client.get("/api/v1/captures/cap-q").json()["status"] == "queued"
        state = client.get(f"/api/v1/runs/{run_id}/state").json()
        assert state["state_status"] == "no_observation"
        assert state["revision"] == 0
        assert state["patches"] == []


def test_fixture_two_captures_same_patch_different_geometry(tmp_path: Path) -> None:
    with make_client(tmp_path, processing_mode="fixture") as client:
        run_id = create_run(client)
        png = make_png(10, 8)

        assert upload(client, run_id, "cap-f1", png, make_metadata("cap-f1", 10, 8, 15.5)).status_code == 202
        assert wait_until(lambda: client.get("/api/v1/captures/cap-f1").json()["status"] == "completed")
        s1 = client.get(f"/api/v1/runs/{run_id}/state").json()
        assert s1["state_status"] == "observation"
        assert s1["revision"] == 1
        assert s1["observation_time_s"] == 5.5
        assert s1["result_origin"] == "fixture"
        assert s1["provider_version"] == "1.0"
        assert s1["evidence_capture_ids"] == ["cap-f1"]
        assert s1["patches"][0]["patch_id"] == "fixture-patch-1"
        geom1 = s1["patches"][0]["geometry"]

        assert upload(client, run_id, "cap-f2", png, make_metadata("cap-f2", 10, 8, 25.5)).status_code == 202
        assert wait_until(lambda: client.get("/api/v1/captures/cap-f2").json()["status"] == "completed")
        s2 = client.get(f"/api/v1/runs/{run_id}/state").json()
        assert s2["revision"] == 2
        assert s2["observation_time_s"] == 15.5
        assert s2["evidence_capture_ids"] == ["cap-f2"]
        assert s2["patches"][0]["patch_id"] == "fixture-patch-1"
        geom2 = s2["patches"][0]["geometry"]

        # same patch_id, but a different contour (geometry changed)
        assert geom1 != geom2


def test_late_result_does_not_overwrite_newer_snapshot(tmp_path: Path) -> None:
    with make_client(tmp_path, processing_mode="fixture") as client:
        run_id = create_run(client)
        png = make_png(10, 8)

        # newer observation first (obs = 25.5 - 10 = 15.5)
        assert upload(client, run_id, "cap-new", png, make_metadata("cap-new", 10, 8, 25.5)).status_code == 202
        assert wait_until(lambda: client.get("/api/v1/captures/cap-new").json()["status"] == "completed")

        # older observation later (obs = 15.5 - 10 = 5.5) -> history only
        assert upload(client, run_id, "cap-old", png, make_metadata("cap-old", 10, 8, 15.5)).status_code == 202
        assert wait_until(lambda: client.get("/api/v1/captures/cap-old").json()["status"] == "completed")

        state = client.get(f"/api/v1/runs/{run_id}/state").json()
        assert state["observation_time_s"] == 15.5
        assert state["revision"] == 1
        assert state["evidence_capture_ids"] == ["cap-new"]


def test_duplicate_upload_no_republish(tmp_path: Path) -> None:
    with make_client(tmp_path, processing_mode="fixture") as client:
        run_id = create_run(client)
        png = make_png(10, 8)
        meta = make_metadata("cap-dup", 10, 8, 15.5)
        assert upload(client, run_id, "cap-dup", png, meta).status_code == 202
        assert wait_until(lambda: client.get("/api/v1/captures/cap-dup").json()["status"] == "completed")
        s1 = client.get(f"/api/v1/runs/{run_id}/state").json()
        assert s1["revision"] == 1

        # idempotent retry: 200, no new processing, no revision bump, no produced_at change
        assert upload(client, run_id, "cap-dup", png, meta).status_code == 200
        time.sleep(0.2)
        s2 = client.get(f"/api/v1/runs/{run_id}/state").json()
        assert s2["revision"] == 1
        assert s2["produced_at"] == s1["produced_at"]

        db = sqlite3.connect(tmp_path / "runs.sqlite3")
        assert db.execute("SELECT COUNT(*) FROM results WHERE capture_id='cap-dup'").fetchone()[0] == 1
        db.close()


def test_provider_failure_keeps_last_valid_snapshot(tmp_path: Path, monkeypatch) -> None:
    original = FixtureProvider.process

    def flaky(self, capture_id, meta, original_bytes, observation_time_s):
        if capture_id == "cap-fail":
            raise RuntimeError("fixture provider failed")
        return original(self, capture_id, meta, original_bytes, observation_time_s)

    monkeypatch.setattr(FixtureProvider, "process", flaky)

    with make_client(tmp_path, processing_mode="fixture") as client:
        run_id = create_run(client)
        png = make_png(10, 8)

        assert upload(client, run_id, "cap-ok1", png, make_metadata("cap-ok1", 10, 8, 15.5)).status_code == 202
        assert wait_until(lambda: client.get("/api/v1/captures/cap-ok1").json()["status"] == "completed")

        assert upload(client, run_id, "cap-fail", png, make_metadata("cap-fail", 10, 8, 25.5)).status_code == 202
        assert wait_until(lambda: client.get("/api/v1/captures/cap-fail").json()["status"] == "failed")

        q = client.get("/api/v1/captures/cap-fail").json()
        assert q["status"] == "failed"
        assert q["processing_error"]

        # snapshot keeps the last valid result (obs = 5.5), not the failed one
        state = client.get(f"/api/v1/runs/{run_id}/state").json()
        assert state["revision"] == 1
        assert state["observation_time_s"] == 5.5
        assert state["evidence_capture_ids"] == ["cap-ok1"]


def test_restart_recovers_interrupted_processing(tmp_path: Path) -> None:
    # upload in default mode so the capture stays queued (no worker)
    with make_client(tmp_path) as client:
        run_id = create_run(client)
        png = make_png(10, 8)
        assert upload(client, run_id, "cap-recover", png, make_metadata("cap-recover", 10, 8, 15.5)).status_code == 202

    # simulate a crash mid-processing: mark it processing with no result
    db = sqlite3.connect(tmp_path / "runs.sqlite3")
    db.execute("UPDATE captures SET status='processing' WHERE capture_id='cap-recover'")
    db.commit()
    db.close()

    # restart in fixture mode -> recover_interrupted re-queues, worker processes it
    with make_client(tmp_path, processing_mode="fixture") as client:
        assert wait_until(lambda: client.get("/api/v1/captures/cap-recover").json()["status"] == "completed")
        state = client.get(f"/api/v1/runs/{run_id}/state").json()
        assert state["revision"] == 1
        assert state["result_origin"] == "fixture"

    # exactly one result was published (no duplicate)
    db = sqlite3.connect(tmp_path / "runs.sqlite3")
    assert db.execute("SELECT COUNT(*) FROM results WHERE capture_id='cap-recover'").fetchone()[0] == 1
    db.close()


def test_repeated_get_does_not_advance_state(tmp_path: Path) -> None:
    with make_client(tmp_path, processing_mode="fixture") as client:
        run_id = create_run(client)
        png = make_png(10, 8)
        assert upload(client, run_id, "cap-stable", png, make_metadata("cap-stable", 10, 8, 15.5)).status_code == 202
        assert wait_until(lambda: client.get("/api/v1/captures/cap-stable").json()["status"] == "completed")

        s1 = client.get(f"/api/v1/runs/{run_id}/state").json()
        for _ in range(3):
            s = client.get(f"/api/v1/runs/{run_id}/state").json()
            assert s["revision"] == s1["revision"]
            assert s["produced_at"] == s1["produced_at"]
            assert s["observation_time_s"] == s1["observation_time_s"]


def _closed_geometry(half: float = 10.0) -> list[list[float]]:
    x0, z0 = 100.0, 200.0
    return [
        [x0 - half, z0 - half],
        [x0 + half, z0 - half],
        [x0 + half, z0 + half],
        [x0 - half, z0 + half],
        [x0 - half, z0 - half],
    ]


def test_worker_stop_waits_for_inflight_task(tmp_path: Path) -> None:
    # Two captures stay queued in default (unconfigured) mode.
    with make_client(tmp_path) as client:
        run_id = create_run(client)
        png = make_png(10, 8)
        assert upload(client, run_id, "cap-w1", png, make_metadata("cap-w1", 10, 8, 15.5)).status_code == 202
        assert upload(client, run_id, "cap-w2", png, make_metadata("cap-w2", 10, 8, 25.5)).status_code == 202

    db_path = tmp_path / "runs.sqlite3"
    captures_dir = tmp_path / "captures"

    entered = threading.Event()
    release = threading.Event()

    class BlockingProvider(ProcessingProvider):
        name = "blocking"
        version = "1.0"

        def process(self, capture_id, meta, original_bytes, observation_time_s):
            entered.set()
            if not release.wait(timeout=10.0):
                raise RuntimeError("provider never released")
            return ProcessingResult("fixture", "1.0", "fixture-patch-1", _closed_geometry(5.0 + observation_time_s % 20.0))

    worker = Worker(db_path, captures_dir, BlockingProvider())
    worker.start()
    assert entered.wait(timeout=5.0)  # worker claimed capture 1 and is processing it

    stop_done = threading.Event()

    def do_stop() -> None:
        worker.stop()
        stop_done.set()

    t = threading.Thread(target=do_stop)
    t.start()

    # stop() must NOT report completion while the in-flight task is still running.
    time.sleep(0.2)
    assert not stop_done.is_set()
    assert worker.running

    release.set()  # let the in-flight task finish
    t.join(timeout=5.0)
    assert stop_done.is_set()
    assert not worker.running

    # first capture completed; second was NOT claimed after the stop signal.
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    assert db.execute("SELECT status FROM captures WHERE capture_id='cap-w1'").fetchone()["status"] == "completed"
    assert db.execute("SELECT status FROM captures WHERE capture_id='cap-w2'").fetchone()["status"] == "queued"
    db.close()


def test_duplicate_complete_and_fail_do_not_downgrade_completed(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        run_id = create_run(client)
        png = make_png(10, 8)
        assert upload(client, run_id, "cap-dup", png, make_metadata("cap-dup", 10, 8, 15.5)).status_code == 202

    db_path = tmp_path / "runs.sqlite3"
    captures_dir = tmp_path / "captures"

    capture_id = results.claim_next_queued(db_path)
    assert capture_id == "cap-dup"
    task, _meta, _original = results.load_for_processing(db_path, captures_dir, capture_id)
    outcome = ProcessingResult("fixture", "1.0", "fixture-patch-1", _closed_geometry(10.0))

    # first completion
    results.complete_and_publish(db_path, task, outcome)
    first = capture_store.get_capture(db_path, "cap-dup")
    assert first.status == "completed"
    first_finished = first.processing_finished_at
    snap1 = results.get_snapshot(db_path, run_id)
    assert snap1.revision == 1

    # duplicate completion (the exact bug: plain INSERT raised IntegrityError) -> no-op
    results.complete_and_publish(db_path, task, outcome)
    second = capture_store.get_capture(db_path, "cap-dup")
    assert second.status == "completed"
    assert second.processing_finished_at == first_finished

    # explicit fail_task on a completed capture -> must NOT downgrade it
    results.fail_task(db_path, "cap-dup", "should be ignored")
    third = capture_store.get_capture(db_path, "cap-dup")
    assert third.status == "completed"
    assert third.processing_error is None

    # exactly one result; snapshot, revision, produced_at, observation unchanged
    db = sqlite3.connect(db_path)
    assert db.execute("SELECT COUNT(*) FROM results WHERE capture_id='cap-dup'").fetchone()[0] == 1
    db.close()
    snap2 = results.get_snapshot(db_path, run_id)
    assert snap2.revision == 1
    assert snap2.produced_at == snap1.produced_at
    assert snap2.observation_time_s == snap1.observation_time_s


@pytest.mark.parametrize(
    "bad_geometry",
    [
        [[0, 0], [1, 0], [1, 1], [0, 1]],  # not closed
        [[0, 0], [1, 0], [1, float("inf")], [0, 1], [0, 0]],  # non-finite coordinate
    ],
)
def test_invalid_provider_geometry_keeps_snapshot(tmp_path: Path, monkeypatch, bad_geometry) -> None:
    original = FixtureProvider.process

    def flaky(self, capture_id, meta, original_bytes, observation_time_s):
        if capture_id == "cap-bad":
            return ProcessingResult("fixture", "1.0", "fixture-patch-1", bad_geometry)
        return original(self, capture_id, meta, original_bytes, observation_time_s)

    monkeypatch.setattr(FixtureProvider, "process", flaky)

    with make_client(tmp_path, processing_mode="fixture") as client:
        run_id = create_run(client)
        png = make_png(10, 8)

        # valid first observation establishes the snapshot
        assert upload(client, run_id, "cap-ok", png, make_metadata("cap-ok", 10, 8, 15.5)).status_code == 202
        assert wait_until(lambda: client.get("/api/v1/captures/cap-ok").json()["status"] == "completed")
        s1 = client.get(f"/api/v1/runs/{run_id}/state").json()
        assert s1["state_status"] == "observation"
        assert s1["revision"] == 1

        # invalid provider output -> capture failed, snapshot unchanged, GET state stays 200
        assert upload(client, run_id, "cap-bad", png, make_metadata("cap-bad", 10, 8, 25.5)).status_code == 202
        assert wait_until(lambda: client.get("/api/v1/captures/cap-bad").json()["status"] == "failed")
        q = client.get("/api/v1/captures/cap-bad").json()
        assert q["status"] == "failed"
        assert q["processing_error"]

        s2 = client.get(f"/api/v1/runs/{run_id}/state").json()
        assert s2 == s1  # every field of the previous valid snapshot unchanged

        # no invalid result row persisted
        db = sqlite3.connect(tmp_path / "runs.sqlite3")
        assert db.execute("SELECT COUNT(*) FROM results WHERE capture_id='cap-bad'").fetchone()[0] == 0
        db.close()

        # a later valid task still processes and advances the snapshot
        assert upload(client, run_id, "cap-ok2", png, make_metadata("cap-ok2", 10, 8, 35.5)).status_code == 202
        assert wait_until(lambda: client.get("/api/v1/captures/cap-ok2").json()["status"] == "completed")
        s3 = client.get(f"/api/v1/runs/{run_id}/state").json()
        assert s3["revision"] == 2
        assert s3["observation_time_s"] == 25.5
