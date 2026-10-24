"""B2 capture tests: upload, idempotency, conflict, concurrency, validation, persistence."""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import capture_store
from app.capture_metadata import CaptureMetadata
from app.main import create_app
from app.store import get_run

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
    return TestClient(
        create_app(
            db_path_override=data_dir / "runs.sqlite3",
            captures_dir_override=data_dir / "captures",
        )
    )


def create_run(client: TestClient, body: dict = SIM_RUN) -> str:
    r = client.post("/api/v1/runs", json=body)
    assert r.status_code == 201, r.text
    return r.json()["run_id"]


def make_png(width: int, height: int, color: tuple = (120, 60, 30)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_jpeg(width: int, height: int, color: tuple = (100, 50, 20)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def make_metadata(capture_id: str, width: int, height: int, **overrides: object) -> dict:
    meta: dict = {
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
        "simulation_time_s": 15.5,
    }
    meta.update(overrides)
    return meta


def upload(client: TestClient, run_id: str, capture_id: str, png: bytes, meta: dict, filename: str = "x.png"):
    return client.post(
        f"/api/v1/runs/{run_id}/captures",
        files={"file": (filename, png, "image/png")},
        data={"metadata": json.dumps(meta)},
    )


def test_upload_and_query(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = create_run(client)
    png = make_png(10, 8)
    meta = make_metadata("cap-1", 10, 8)
    r = upload(client, run_id, "cap-1", png, meta)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["capture_id"] == "cap-1"
    assert body["run_id"] == run_id
    assert body["status"] == "queued"
    assert body["observation_time_s"] == 5.5
    assert body["content_sha256"] == hashlib.sha256(png).hexdigest()
    assert body["byte_size"] == len(png)
    assert body["storage_key"] == "cap-1"

    q = client.get("/api/v1/captures/cap-1")
    assert q.status_code == 200
    assert q.json()["content_sha256"] == hashlib.sha256(png).hexdigest()

    # original bytes on disk match
    original = tmp_path / "captures" / "cap-1" / "original.bin"
    assert original.read_bytes() == png
    raw_meta = (tmp_path / "captures" / "cap-1" / "metadata.raw.txt").read_text()
    assert json.loads(raw_meta)["capture_id"] == "cap-1"

    # run state still has no observation
    state = client.get(f"/api/v1/runs/{run_id}/state").json()
    assert state["state_status"] == "no_observation"
    assert state["revision"] == 0


def test_real_capture_time_conversion(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = create_run(client, REAL_RUN)
    png = make_png(10, 8)
    meta = make_metadata("cap-real", 10, 8, simulation_time_s=None, captured_at="2026-10-24T00:00:05Z")
    r = upload(client, run_id, "cap-real", png, meta)
    assert r.status_code == 202, r.text
    assert r.json()["observation_time_s"] == 5.0


def test_idempotent_retry_json_variation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = create_run(client)
    png = make_png(10, 8)
    meta = make_metadata("cap-2", 10, 8)

    first = upload(client, run_id, "cap-2", png, meta)
    assert first.status_code == 202

    # reorder top-level keys + nested keys + whitespace -> still idempotent
    reordered = {
        "captured_at": None,
        "simulation_time_s": 15.5,
        "pose": {"camera_to_world": [[1, 0, 0, 1], [0, 1, 0, 2], [0, 0, 1, 3], [0, 0, 0, 1]]},
        "intrinsics": {"cy": 4.0, "cx": 5.0, "fy": 100.0, "fx": 100.0},
        "coordinate_frame_id": SIM_RUN["coordinate_frame_id"],
        "asset_version": SIM_RUN["asset_version"],
        "scene_id": SIM_RUN["scene_id"],
        "height": 8,
        "width": 10,
        "capture_id": "cap-2",
        "schema_version": "1.0",
    }
    # drop the explicit None captured_at for the sim run (matching original semantics)
    reordered.pop("captured_at")
    second = upload(client, run_id, "cap-2", png, reordered)
    assert second.status_code == 200, second.text
    assert second.json()["received_at"] == first.json()["received_at"]

    db = sqlite3.connect(tmp_path / "runs.sqlite3")
    assert db.execute("SELECT COUNT(*) FROM captures WHERE capture_id='cap-2'").fetchone()[0] == 1
    db.close()


def test_conflict_different_image(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = create_run(client)
    png_a = make_png(10, 8, (1, 2, 3))
    png_b = make_png(10, 8, (4, 5, 6))
    assert upload(client, run_id, "cap-c", png_a, make_metadata("cap-c", 10, 8)).status_code == 202
    r = upload(client, run_id, "cap-c", png_b, make_metadata("cap-c", 10, 8))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFLICT"


def test_conflict_different_metadata(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = create_run(client)
    png = make_png(10, 8)
    assert upload(client, run_id, "cap-m", png, make_metadata("cap-m", 10, 8, simulation_time_s=15.5)).status_code == 202
    r = upload(client, run_id, "cap-m", png, make_metadata("cap-m", 10, 8, simulation_time_s=16.0))
    assert r.status_code == 409


def test_cross_run_conflict(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_a = create_run(client)
    run_b = create_run(client)  # different run_id, same scene binding
    png = make_png(10, 8)
    assert upload(client, run_a, "cap-x", png, make_metadata("cap-x", 10, 8)).status_code == 202
    r = upload(client, run_b, "cap-x", png, make_metadata("cap-x", 10, 8))
    assert r.status_code == 409


def test_concurrent_same_upload(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = create_run(client)
    png = make_png(10, 8)
    meta = CaptureMetadata.model_validate(make_metadata("cap-conc", 10, 8))
    raw = json.dumps(make_metadata("cap-conc", 10, 8))
    db_path = tmp_path / "runs.sqlite3"
    captures_dir = tmp_path / "captures"
    run = get_run(db_path, run_id)

    barrier = threading.Barrier(2)
    results: list[tuple[str, bool]] = []

    def worker() -> None:
        barrier.wait()
        record, is_new = capture_store.save_capture(db_path, captures_dir, run, meta, raw, png)
        results.append((record.capture_id, is_new))

    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(worker) for _ in range(2)]
        for f in futs:
            f.result()

    assert sum(1 for _, is_new in results if is_new) == 1
    assert sum(1 for _, is_new in results if not is_new) == 1
    assert len(list((tmp_path / "captures" / "cap-conc").glob("original.bin"))) == 1


def test_invalid_json_and_validation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = create_run(client)
    png = make_png(10, 8)

    r = client.post(
        f"/api/v1/runs/{run_id}/captures",
        files={"file": ("x.png", png, "image/png")},
        data={"metadata": "not json"},
    )
    assert r.status_code == 422

    # unknown field rejected (extra="forbid")
    bad = make_metadata("cap-bad", 10, 8)
    bad["result_origin"] = "fake"
    r = upload(client, run_id, "cap-bad", png, bad)
    assert r.status_code == 422

    # invalid camera matrix (non-orthonormal rotation)
    bad = make_metadata("cap-mat", 10, 8)
    bad["pose"] = {"camera_to_world": [[2, 0, 0, 1], [0, 1, 0, 2], [0, 0, 1, 3], [0, 0, 0, 1]]}
    r = upload(client, run_id, "cap-mat", png, bad)
    assert r.status_code == 422

    # intrinsics fx <= 0
    bad = make_metadata("cap-int", 10, 8)
    bad["intrinsics"] = {"fx": 0.0, "fy": 100.0, "cx": 5.0, "cy": 4.0}
    r = upload(client, run_id, "cap-int", png, bad)
    assert r.status_code == 422


def test_invalid_image_and_dimension_mismatch(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = create_run(client)
    not_image = b"this is not an image at all"
    r = upload(client, run_id, "cap-img", not_image, make_metadata("cap-img", 10, 8))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNSUPPORTED_IMAGE"

    png = make_png(10, 8)
    r = upload(client, run_id, "cap-dim", png, make_metadata("cap-dim", 20, 16))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_IMAGE"


def test_truncated_jpeg_rejected(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = create_run(client)
    jpeg = make_jpeg(16, 12)
    truncated = jpeg[:-10]  # recognizable header, but pixel decode fails
    r = upload(client, run_id, "cap-trunc", truncated, make_metadata("cap-trunc", 16, 12), filename="x.jpg")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_IMAGE"

    # no capture record and no original directory
    db = sqlite3.connect(tmp_path / "runs.sqlite3")
    assert db.execute("SELECT COUNT(*) FROM captures WHERE capture_id='cap-trunc'").fetchone()[0] == 0
    db.close()
    assert not (tmp_path / "captures" / "cap-trunc").exists()


def test_valid_jpeg_and_png_upload(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = create_run(client)
    jpeg = make_jpeg(16, 12)
    assert upload(client, run_id, "cap-jpeg", jpeg, make_metadata("cap-jpeg", 16, 12), filename="x.jpg").status_code == 202
    png = make_png(10, 8)
    assert upload(client, run_id, "cap-png", png, make_metadata("cap-png", 10, 8)).status_code == 202


def test_reflection_matrix_rejected(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = create_run(client)
    png = make_png(10, 8)
    meta = make_metadata("cap-mirror", 10, 8)
    meta["pose"] = {"camera_to_world": [[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]}
    r = upload(client, run_id, "cap-mirror", png, meta)
    assert r.status_code == 422

    db = sqlite3.connect(tmp_path / "runs.sqlite3")
    assert db.execute("SELECT COUNT(*) FROM captures WHERE capture_id='cap-mirror'").fetchone()[0] == 0
    db.close()


def test_valid_nonidentity_rotation_uploads(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = create_run(client)
    png = make_png(10, 8)
    # 90-degree rotation about z: proper rotation, det = +1
    meta = make_metadata("cap-rot", 10, 8)
    meta["pose"] = {"camera_to_world": [[0, -1, 0, 1], [1, 0, 0, 2], [0, 0, 1, 3], [0, 0, 0, 1]]}
    assert upload(client, run_id, "cap-rot", png, meta).status_code == 202


def test_over_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path)
    run_id = create_run(client)
    png = make_png(10, 8)
    monkeypatch.setenv("FIREX_CAPTURE_MAX_BYTES", "10")
    r = upload(client, run_id, "cap-limit", png, make_metadata("cap-limit", 10, 8))
    assert r.status_code == 413


def test_binding_mismatch(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = create_run(client)
    png = make_png(10, 8)
    bad = make_metadata("cap-scene", 10, 8)
    bad["scene_id"] = "other_scene"
    r = upload(client, run_id, "cap-scene", png, bad)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "METADATA_MISMATCH"


def test_time_mismatch_and_before_origin(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = create_run(client)
    png = make_png(10, 8)

    # simulation run given captured_at instead of simulation_time_s
    bad = make_metadata("cap-time", 10, 8)
    bad.pop("simulation_time_s")
    bad["captured_at"] = "2026-10-24T00:00:05Z"
    r = upload(client, run_id, "cap-time", png, bad)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_TIME"

    # before origin (simulation_time_s < origin 10.0)
    bad = make_metadata("cap-neg", 10, 8, simulation_time_s=5.0)
    r = upload(client, run_id, "cap-neg", png, bad)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_TIME"


def test_old_run_missing_origin_rejected(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    # insert a legacy run with NULL origin directly (pre-time-contract record)
    db = sqlite3.connect(tmp_path / "runs.sqlite3")
    db.execute(
        "INSERT INTO runs (run_id, plant_id, scene_id, asset_version, coordinate_frame_id, input_source, created_at, schema_version, simulation_time_origin_s, time_origin_utc) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "legacy-run",
            "GEM_HYDRO_SHUANGJIANGKOU",
            "shuangjiangkou_reference_terrain",
            "reference-v1",
            "SJK_REFERENCE_UTM47N_EGM2008_v1",
            "simulation",
            "2026-10-24T00:00:00+00:00",
            "1.0",
            None,
            None,
        ),
    )
    db.commit()
    db.close()

    png = make_png(10, 8)
    r = upload(client, "legacy-run", "cap-legacy", png, make_metadata("cap-legacy", 10, 8))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "TIME_NOT_CONFIGURED"


def test_unsafe_filename_ignored(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = create_run(client)
    png = make_png(10, 8)
    r = upload(client, run_id, "cap-safe", png, make_metadata("cap-safe", 10, 8), filename="../../etc/passwd.png")
    assert r.status_code == 202
    # storage is under captures/<capture_id>, never influenced by the filename
    assert (tmp_path / "captures" / "cap-safe" / "original.bin").exists()
    assert not (tmp_path / "etc").exists()


def test_save_failure_leaves_no_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(
        db_path_override=tmp_path / "runs.sqlite3",
        captures_dir_override=tmp_path / "captures",
    )
    client = TestClient(app, raise_server_exceptions=False)
    run_id = create_run(client)
    png = make_png(10, 8)

    def boom(*args, **kwargs):  # noqa: ANN001
        raise OSError("disk full")

    monkeypatch.setattr("app.capture_store._persist_capture_files", boom)
    r = upload(client, run_id, "cap-fail", png, make_metadata("cap-fail", 10, 8))
    assert r.status_code == 500

    db = sqlite3.connect(tmp_path / "runs.sqlite3")
    assert db.execute("SELECT COUNT(*) FROM captures WHERE capture_id='cap-fail'").fetchone()[0] == 0
    db.close()
    assert not (tmp_path / "captures" / "cap-fail").exists()


def test_restart_preserves_capture(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = create_run(client)
    png = make_png(10, 8)
    assert upload(client, run_id, "cap-restart", png, make_metadata("cap-restart", 10, 8)).status_code == 202

    # new app instance on the same data dir
    client2 = make_client(tmp_path)
    q = client2.get("/api/v1/captures/cap-restart")
    assert q.status_code == 200
    assert q.json()["content_sha256"] == hashlib.sha256(png).hexdigest()
    assert (tmp_path / "captures" / "cap-restart" / "original.bin").read_bytes() == png

    state = client2.get(f"/api/v1/runs/{run_id}/state").json()
    assert state["state_status"] == "no_observation"
    assert state["patches"] == []
