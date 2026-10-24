"""Process-interruption recovery: crash after files land but before SQLite commit."""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.capture_metadata import CaptureMetadata, canonical_metadata_json
from app.main import create_app

SIM_RUN = {
    "plant_id": "GEM_HYDRO_SHUANGJIANGKOU",
    "scene_id": "shuangjiangkou_reference_terrain",
    "asset_version": "reference-v1",
    "coordinate_frame_id": "SJK_REFERENCE_UTM47N_EGM2008_v1",
    "input_source": "simulation",
    "simulation_time_origin_s": 10.0,
}

# Subprocess: create run + capture, then hard-exit inside the file-write step
# AFTER the directory has been renamed into place but BEFORE the SQLite commit.
_CRASH_SCRIPT = r"""
import io, json, os, sys
from pathlib import Path
from PIL import Image
from app import db, capture_store
from app.store import create_run
from app.models import RunCreate
from app.capture_metadata import CaptureMetadata

data_dir = Path(sys.argv[1])
db.init_db(data_dir / "runs.sqlite3")

run = create_run(data_dir / "runs.sqlite3", RunCreate(
    plant_id="GEM_HYDRO_SHUANGJIANGKOU",
    scene_id="shuangjiangkou_reference_terrain",
    asset_version="reference-v1",
    coordinate_frame_id="SJK_REFERENCE_UTM47N_EGM2008_v1",
    input_source="simulation",
    simulation_time_origin_s=10.0,
))

img = Image.new("RGB", (10, 8), (9, 8, 7))
buf = io.BytesIO(); img.save(buf, format="PNG")
image = buf.getvalue()

meta_dict = {
    "schema_version": "1.0",
    "capture_id": "cap-crash",
    "scene_id": "shuangjiangkou_reference_terrain",
    "asset_version": "reference-v1",
    "coordinate_frame_id": "SJK_REFERENCE_UTM47N_EGM2008_v1",
    "width": 10, "height": 8,
    "intrinsics": {"fx": 50.0, "fy": 50.0, "cx": 5.0, "cy": 4.0},
    "distortion_model": "none",
    "pose": {"camera_to_world": [[1, 0, 0, 1], [0, 1, 0, 2], [0, 0, 1, 3], [0, 0, 0, 1]]},
    "simulation_time_s": 15.5,
}
meta = CaptureMetadata.model_validate(meta_dict)

(data_dir / "interrupted.json").write_text(json.dumps({
    "run_id": run.run_id,
    "capture_id": "cap-crash",
    "metadata": meta_dict,
}))
(data_dir / "crash-image.png").write_bytes(image)

orig = capture_store._persist_capture_files
def crash_after_rename(captures_dir, capture_id, run_id, image_bytes, raw_meta, normalized_meta, content_sha, metadata_sha, received_at):
    orig(captures_dir, capture_id, run_id, image_bytes, raw_meta, normalized_meta, content_sha, metadata_sha, received_at)  # dir + receipt landed
    os._exit(42)  # crash before the transaction commits

capture_store._persist_capture_files = crash_after_rename
capture_store.save_capture(
    data_dir / "runs.sqlite3", data_dir / "captures", run, meta, json.dumps(meta_dict), image
)
"""


@contextmanager
def make_client(data_dir: Path):
    with TestClient(
        create_app(db_path_override=data_dir / "runs.sqlite3", captures_dir_override=data_dir / "captures")
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


def make_metadata(capture_id: str, width: int, height: int) -> dict:
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
        "simulation_time_s": 15.5,
    }


def upload(client: TestClient, run_id: str, capture_id: str, png: bytes, meta: dict):
    return client.post(
        f"/api/v1/runs/{run_id}/captures",
        files={"file": ("x.png", png, "image/png")},
        data={"metadata": json.dumps(meta)},
    )


def test_process_interruption_recovers(tmp_path: Path) -> None:
    data_dir = tmp_path

    # an already-successful capture that must survive untouched
    with make_client(data_dir) as client:
        ok_run_id = create_run(client)
        ok_png = make_png(10, 8, (1, 2, 3))
        assert upload(client, ok_run_id, "cap-ok", ok_png, make_metadata("cap-ok", 10, 8)).status_code == 202

    # crash subprocess: files landed, SQLite not committed
    proc = subprocess.run([sys.executable, "-c", _CRASH_SCRIPT, str(data_dir)], capture_output=True, text=True)
    assert proc.returncode == 42, proc.stderr

    state = json.loads((data_dir / "interrupted.json").read_text())
    crash_run_id = state["run_id"]
    crash_meta = state["metadata"]
    crash_png = (data_dir / "crash-image.png").read_bytes()

    # orphan dir landed, but no committed record exists
    assert (data_dir / "captures" / "cap-crash").is_dir()
    db = sqlite3.connect(data_dir / "runs.sqlite3")
    assert db.execute("SELECT COUNT(*) FROM captures WHERE capture_id='cap-crash'").fetchone()[0] == 0
    db.close()

    # retry the SAME capture via a fresh app instance (restart)
    with make_client(data_dir) as client2:
        r = upload(client2, crash_run_id, "cap-crash", crash_png, crash_meta)
        assert r.status_code == 202, r.text
        assert r.json()["content_sha256"] == hashlib.sha256(crash_png).hexdigest()

        # the recovered record preserved the crashed attempt's first received_at (from the receipt)
        manifest = json.loads((data_dir / "captures" / "cap-crash" / "manifest.json").read_text())
        assert datetime.fromisoformat(r.json()["received_at"]) == datetime.fromisoformat(manifest["received_at"])

        # subsequent identical retry is idempotent and does not refresh received_at
        r2 = upload(client2, crash_run_id, "cap-crash", crash_png, crash_meta)
        assert r2.status_code == 200
        assert r2.json()["received_at"] == r.json()["received_at"]

        # different content for the same id still conflicts
        r3 = upload(client2, crash_run_id, "cap-crash", make_png(10, 8, (99, 99, 99)), crash_meta)
        assert r3.status_code == 409

        # original is complete and correct
        assert (data_dir / "captures" / "cap-crash" / "original.bin").read_bytes() == crash_png
        assert (data_dir / "captures" / "cap-crash" / "metadata.raw.txt").exists()

        # the other successful capture is unaffected
        assert client2.get("/api/v1/captures/cap-ok").status_code == 200
        assert (data_dir / "captures" / "cap-ok" / "original.bin").read_bytes() == ok_png


def test_orphan_different_content_conflicts_and_preserves_dir(tmp_path: Path) -> None:
    data_dir = tmp_path
    proc = subprocess.run([sys.executable, "-c", _CRASH_SCRIPT, str(data_dir)], capture_output=True, text=True)
    assert proc.returncode == 42, proc.stderr

    state = json.loads((data_dir / "interrupted.json").read_text())
    run_id = state["run_id"]
    meta = state["metadata"]
    original_png = (data_dir / "crash-image.png").read_bytes()

    with make_client(data_dir) as client:
        different_png = make_png(10, 8, (11, 22, 33))
        r = upload(client, run_id, "cap-crash", different_png, meta)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "CONFLICT"

        # the orphan directory content is unchanged (not overwritten or deleted)
        assert (data_dir / "captures" / "cap-crash" / "original.bin").read_bytes() == original_png


def _make_orphan_dir(data_dir: Path, capture_id: str) -> Path:
    d = data_dir / "captures" / capture_id
    d.mkdir(parents=True)
    (d / "original.bin").write_bytes(b"pre-existing bytes")
    (d / "metadata.raw.txt").write_text("{}", encoding="utf-8")
    (d / "metadata.normalized.json").write_text("{}", encoding="utf-8")
    return d


def test_orphan_without_manifest_rejected_and_preserved(tmp_path: Path) -> None:
    data_dir = tmp_path
    with make_client(data_dir) as client:
        run_id = create_run(client)
        orphan = _make_orphan_dir(data_dir, "cap-nomanifest")

        png = make_png(10, 8)
        r = upload(client, run_id, "cap-nomanifest", png, make_metadata("cap-nomanifest", 10, 8))
        assert r.status_code == 500
        assert r.json()["error"]["code"] == "RECOVERY_ERROR"

        # preserved, not deleted
        assert (orphan / "original.bin").read_bytes() == b"pre-existing bytes"
        assert (orphan / "metadata.raw.txt").exists()


def test_orphan_corrupt_manifest_rejected_and_preserved(tmp_path: Path) -> None:
    data_dir = tmp_path
    with make_client(data_dir) as client:
        run_id = create_run(client)
        orphan = _make_orphan_dir(data_dir, "cap-corrupt")
        (orphan / "manifest.json").write_text("{ not valid json", encoding="utf-8")

        png = make_png(10, 8)
        r = upload(client, run_id, "cap-corrupt", png, make_metadata("cap-corrupt", 10, 8))
        assert r.status_code == 500
        assert r.json()["error"]["code"] == "RECOVERY_ERROR"
        assert (orphan / "original.bin").read_bytes() == b"pre-existing bytes"


def test_orphan_incomplete_content_rejected_and_preserved(tmp_path: Path) -> None:
    data_dir = tmp_path
    with make_client(data_dir) as client:
        run_id = create_run(client)
        png = make_png(10, 8)
        meta_dict = make_metadata("cap-incomplete", 10, 8)
        meta = CaptureMetadata.model_validate(meta_dict)
        content_sha = hashlib.sha256(png).hexdigest()
        metadata_sha = hashlib.sha256(canonical_metadata_json(meta).encode("utf-8")).hexdigest()

        orphan = data_dir / "captures" / "cap-incomplete"
        orphan.mkdir(parents=True)
        (orphan / "manifest.json").write_text(
            json.dumps({
                "format_version": "1",
                "capture_id": "cap-incomplete",
                "run_id": run_id,
                "byte_size": len(png),
                "content_sha256": content_sha,
                "metadata_sha256": metadata_sha,
                "received_at": "2026-10-24T00:00:00+00:00",
            }),
            encoding="utf-8",
        )

        r = upload(client, run_id, "cap-incomplete", png, meta_dict)
        assert r.status_code == 500
        assert r.json()["error"]["code"] == "RECOVERY_ERROR"
        # manifest preserved
        assert (orphan / "manifest.json").exists()
