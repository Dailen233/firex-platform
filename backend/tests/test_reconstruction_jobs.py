"""Uploaded-ZIP reconstruction job persistence + endpoint tests.

Real single-group reconstruction (which needs the vggt-env numpy/scipy/PIL
interpreter) is covered by ``experiments/c2-camera-geometry/test_multiview_inputs.py``
and by the end-to-end run against a live service.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.main import create_app
from app.reconstruction_jobs import claim_next_job, complete_job, fail_job, get_job, recover_interrupted_jobs

SJK_RUN = {
    "plant_id": "GEM_HYDRO_SHUANGJIANGKOU",
    "scene_id": "sjk_hydropower_sim_v0_1",
    "asset_version": "hydro-sim-v0.1-local",
    "coordinate_frame_id": "SJK_TEAM_FBX_FILE_METRE_UNREGISTERED_v1",
    "input_source": "simulation",
    "simulation_time_origin_s": 0.0,
}


def make_dummy_zip(path: Path) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("manifest.csv", "group_id,camera_id\n")
        archive.writestr("group_01/cam_01.png", b"dummy")


@contextmanager
def make_client(data_dir: Path):
    with TestClient(
        create_app(db_path_override=data_dir / "runs.sqlite3", captures_dir_override=data_dir / "captures")
    ) as client:
        yield client


def _upload(client: TestClient, run_id: str, zip_path: Path, name: str = "capture.zip"):
    return client.post(
        f"/api/v1/runs/{run_id}/reconstruction-jobs",
        files={"file": (name, zip_path.read_bytes(), "application/zip")},
    )


def test_upload_returns_queued_job(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        run_id = client.post("/api/v1/runs", json=SJK_RUN).json()["run_id"]
        z = tmp_path / "single.zip"
        make_dummy_zip(z)
        resp = _upload(client, run_id, z)
        assert resp.status_code == 202
        job = resp.json()
        assert job["job_id"]
        assert job["status"] == "queued"
        assert job["run_id"] == run_id
        assert len(job["zip_sha256"]) == 64
        assert job["zip_byte_size"] > 0
        fetched = client.get(f"/api/v1/runs/{run_id}/reconstruction-jobs/{job['job_id']}")
        assert fetched.status_code == 200
        assert fetched.json()["status"] == "queued"


def test_upload_missing_run_404(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        z = tmp_path / "single.zip"
        make_dummy_zip(z)
        assert _upload(client, "nope", z).status_code == 404


def test_upload_empty_zip_422(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        run_id = client.post("/api/v1/runs", json=SJK_RUN).json()["run_id"]
        resp = client.post(
            f"/api/v1/runs/{run_id}/reconstruction-jobs",
            files={"file": ("empty.zip", b"", "application/zip")},
        )
        assert resp.status_code == 422


def test_job_not_found_404(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        run_id = client.post("/api/v1/runs", json=SJK_RUN).json()["run_id"]
        assert client.get(f"/api/v1/runs/{run_id}/reconstruction-jobs/nope").status_code == 404


def test_job_claim_recover_roundtrip(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        run_id = client.post("/api/v1/runs", json=SJK_RUN).json()["run_id"]
        z = tmp_path / "single.zip"
        make_dummy_zip(z)
        job_id = _upload(client, run_id, z).json()["job_id"]
        dbp = tmp_path / "runs.sqlite3"
        assert claim_next_job(dbp) == job_id
        assert get_job(dbp, job_id).status == "processing"
        assert recover_interrupted_jobs(dbp) == 1
        assert get_job(dbp, job_id).status == "queued"


def test_complete_then_fail_cannot_downgrade(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        run_id = client.post("/api/v1/runs", json=SJK_RUN).json()["run_id"]
        z = tmp_path / "single.zip"
        make_dummy_zip(z)
        job_id = _upload(client, run_id, z).json()["job_id"]
        dbp = tmp_path / "runs.sqlite3"
        assert claim_next_job(dbp) == job_id
        complete_job(dbp, job_id, simulation_time_s=1800.0, group_id="group_01",
                     voxel_count=33, mask_source="rgb_proxy", revision=1)
        done = get_job(dbp, job_id)
        assert done.status == "completed" and done.revision == 1 and done.mask_source == "rgb_proxy"
        fail_job(dbp, job_id, "boom")
        assert get_job(dbp, job_id).status == "completed"
