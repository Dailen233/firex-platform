"""Offline reconstruction publishing + read-only retrieval tests."""
from __future__ import annotations

import json
import struct
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import DEFAULT_SJK_GLB_SHA256
from app.main import create_app
from app.reconstruction import ReconstructionError, publish_frame

SJK_RUN = {
    "plant_id": "GEM_HYDRO_SHUANGJIANGKOU",
    "scene_id": "sjk_hydropower_sim_v0_1",
    "asset_version": "hydro-sim-v0.1-local",
    "coordinate_frame_id": "SJK_TEAM_FBX_FILE_METRE_UNREGISTERED_v1",
    "input_source": "simulation",
    "simulation_time_origin_s": 0.0,
}


def make_ply(count: int) -> bytes:
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {count}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "end_header\n"
    ).encode("ascii")
    body = b"".join(struct.pack("<fff", float(i), float(i), float(i)) for i in range(count))
    return header + body


def make_summary(group_id: str, t: float, count: int, scene_id: str | None = None, glb: str | None = None) -> dict:
    return {
        "scene_id": scene_id if scene_id is not None else SJK_RUN["scene_id"],
        "asset_version": SJK_RUN["asset_version"],
        "coordinate_frame_id": SJK_RUN["coordinate_frame_id"],
        "voxel_size_m": 4.0,
        "groups": [
            {
                "group_id": group_id,
                "simulation_time_s": t,
                "source_camera_count": 2,
                "candidate_voxel_count": count,
                "terrain_clip": {"glb_sha256": glb} if glb is not None else {"glb_sha256": DEFAULT_SJK_GLB_SHA256},
            }
        ],
    }


@contextmanager
def make_client(data_dir: Path):
    with TestClient(
        create_app(
            db_path_override=data_dir / "runs.sqlite3",
            captures_dir_override=data_dir / "captures",
        )
    ) as client:
        yield client


def write_results(tmp_path: Path, group_id: str, t: float, count: int, scene_id: str | None = None, glb: str | None = None, ply_count: int | None = None) -> Path:
    d = tmp_path / f"results-{group_id}-{int(t)}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(json.dumps(make_summary(group_id, t, count, scene_id, glb)), encoding="utf-8")
    (d / f"{group_id}-voxels.ply").write_bytes(make_ply(ply_count if ply_count is not None else count))
    return d


def _recon_dir(tmp_path: Path) -> Path:
    return tmp_path / "reconstruction"


def test_publish_then_read_latest_and_ply(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        run_id = client.post("/api/v1/runs", json=SJK_RUN).json()["run_id"]

        assert client.get(f"/api/v1/runs/{run_id}/reconstruction").json()["status"] == "none"

        results = write_results(tmp_path, "group_01", 1800.0, 33)
        summary = publish_frame(tmp_path / "runs.sqlite3", _recon_dir(tmp_path), run_id, results, "group_01")
        assert summary.revision == 1
        assert summary.voxel_count == 33
        assert summary.simulation_time_s == 1800.0

        body = client.get(f"/api/v1/runs/{run_id}/reconstruction").json()
        assert body["status"] == "available"
        assert body["revision"] == 1
        assert body["voxel_count"] == 33
        assert body["simulation_time_s"] == 1800.0
        assert len(body["ply_sha256"]) == 64

        ply = client.get(f"/api/v1/runs/{run_id}/reconstruction/1/ply")
        assert ply.status_code == 200
        assert ply.headers["content-type"] == "application/octet-stream"
        assert len(ply.content) > 0


def test_duplicate_and_older_frame_rejected(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        run_id = client.post("/api/v1/runs", json=SJK_RUN).json()["run_id"]
        dbp = tmp_path / "runs.sqlite3"
        recon = _recon_dir(tmp_path)

        publish_frame(dbp, recon, run_id, write_results(tmp_path, "group_02", 3600.0, 50), "group_02")
        assert client.get(f"/api/v1/runs/{run_id}/reconstruction").json()["revision"] == 1

        # Duplicate (same time, different group) must not overwrite.
        with pytest.raises(ReconstructionError, match="重复帧|不能覆盖"):
            publish_frame(dbp, recon, run_id, write_results(tmp_path, "group_01", 3600.0, 33), "group_01")

        # Older time must not overwrite.
        with pytest.raises(ReconstructionError, match="旧时间帧"):
            publish_frame(dbp, recon, run_id, write_results(tmp_path, "group_01", 1800.0, 33), "group_01")

        body = client.get(f"/api/v1/runs/{run_id}/reconstruction").json()
        assert body["revision"] == 1
        assert body["group_id"] == "group_02"
        assert body["voxel_count"] == 50


def test_binding_mismatch_rejected(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        run_id = client.post("/api/v1/runs", json=SJK_RUN).json()["run_id"]
        dbp = tmp_path / "runs.sqlite3"
        recon = _recon_dir(tmp_path)

        with pytest.raises(ReconstructionError, match="场景 ID 不匹配"):
            publish_frame(
                dbp, recon, run_id,
                write_results(tmp_path, "group_01", 1800.0, 33, scene_id="other_scene"),
                "group_01",
            )
        assert client.get(f"/api/v1/runs/{run_id}/reconstruction").json()["status"] == "none"


def test_ply_count_mismatch_rejected(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        run_id = client.post("/api/v1/runs", json=SJK_RUN).json()["run_id"]
        dbp = tmp_path / "runs.sqlite3"
        recon = _recon_dir(tmp_path)

        with pytest.raises(ReconstructionError, match="点数"):
            publish_frame(
                dbp, recon, run_id,
                write_results(tmp_path, "group_01", 1800.0, 33, ply_count=10),
                "group_01",
            )
        assert client.get(f"/api/v1/runs/{run_id}/reconstruction").json()["status"] == "none"


def test_revision_independent_per_run(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        a = client.post("/api/v1/runs", json=SJK_RUN).json()["run_id"]
        b = client.post("/api/v1/runs", json=SJK_RUN).json()["run_id"]
        dbp = tmp_path / "runs.sqlite3"
        recon = _recon_dir(tmp_path)

        publish_frame(dbp, recon, a, write_results(tmp_path, "group_01", 1800.0, 33), "group_01")
        publish_frame(dbp, recon, b, write_results(tmp_path, "group_01", 1800.0, 33), "group_01")
        assert client.get(f"/api/v1/runs/{a}/reconstruction").json()["revision"] == 1
        assert client.get(f"/api/v1/runs/{b}/reconstruction").json()["revision"] == 1

        publish_frame(dbp, recon, a, write_results(tmp_path, "group_02", 3600.0, 50), "group_02")
        assert client.get(f"/api/v1/runs/{a}/reconstruction").json()["revision"] == 2
        assert client.get(f"/api/v1/runs/{b}/reconstruction").json()["revision"] == 1


def test_list_frames_empty_then_ordered(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        run_id = client.post("/api/v1/runs", json=SJK_RUN).json()["run_id"]
        dbp = tmp_path / "runs.sqlite3"
        recon = _recon_dir(tmp_path)

        # 空 run 返回空列表
        assert client.get(f"/api/v1/runs/{run_id}/reconstruction/frames").json() == []

        publish_frame(dbp, recon, run_id, write_results(tmp_path, "group_01", 1800.0, 33), "group_01")
        publish_frame(dbp, recon, run_id, write_results(tmp_path, "group_02", 3600.0, 50), "group_02")

        frames = client.get(f"/api/v1/runs/{run_id}/reconstruction/frames").json()
        assert [f["simulation_time_s"] for f in frames] == [1800.0, 3600.0]
        assert [f["revision"] for f in frames] == [1, 2]
        assert [f["voxel_count"] for f in frames] == [33, 50]
        assert all(len(f["ply_sha256"]) == 64 for f in frames)


def test_frames_endpoint_run_not_found(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.get("/api/v1/runs/nope/reconstruction/frames").status_code == 404
