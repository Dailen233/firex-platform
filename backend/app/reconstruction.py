"""Offline multiview reconstruction publishing and read-only retrieval.

A published frame binds a run's immutable scene/asset/coordinate frame to the
``summary.json`` + voxel PLY it was built from, and each run advances its own
strictly increasing ``revision``. A duplicate, older-time, or malformed frame
never overwrites the most recent valid result.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .config import sjk_glb_sha256
from .models import ReconstructionSummary
from .store import get_run

DEFAULT_SOURCE = "offline_multiview_reconstruction"


class ReconstructionError(Exception):
    """A frame cannot be published (binding / PLY / ordering failure)."""


@dataclass
class PublishedFrame:
    run_id: str
    revision: int
    group_id: str
    simulation_time_s: float
    source: str
    voxel_count: int
    voxel_size_m: float
    byte_size: int
    ply_sha256: str
    glb_sha256: str | None
    mask_source: str | None
    produced_at: datetime
    storage_key: str


def _read_ply_header(data: bytes) -> tuple[int, int, int]:
    """Return ``(vertex_count, data_offset, stride)`` for a binary little-endian
    ``float x/y/z`` PLY; raise on malformed input."""
    header_end = data.find(b"end_header")
    if header_end < 0:
        raise ReconstructionError("PLY 缺少 end_header")
    header = data[:header_end].decode("ascii", errors="replace")
    if "binary_little_endian" not in header:
        raise ReconstructionError("PLY 必须为 binary_little_endian")
    vertex = re.search(r"element\s+vertex\s+(\d+)", header)
    if not vertex:
        raise ReconstructionError("PLY 缺少 element vertex")
    count = int(vertex.group(1))
    props = re.findall(r"property\s+float\s+(\w+)", header)
    if "x" not in props or "y" not in props or "z" not in props:
        raise ReconstructionError("PLY 顶点缺少 x/y/z 属性")
    data_offset = header_end + len(b"end_header")
    while data_offset < len(data) and data[data_offset] in (0x0A, 0x0D):
        data_offset += 1
    return count, data_offset, len(props)


def _validate_ply(data: bytes, expected_count: int) -> tuple[int, str]:
    """Validate PLY format, point count and size; return ``(byte_size, sha256)``."""
    if not data:
        raise ReconstructionError("PLY 文件为空")
    count, data_offset, stride = _read_ply_header(data)
    if data_offset + count * stride * 4 > len(data):
        raise ReconstructionError(f"PLY 数据长度不足（声明 {count} 个顶点）")
    if count != expected_count:
        raise ReconstructionError(f"PLY 点数 {count} 与摘要 {expected_count} 不一致")
    return len(data), hashlib.sha256(data).hexdigest()


def _latest_row(db_path: Path, run_id: str) -> sqlite3.Row | None:
    conn = db.connect(db_path)
    try:
        return conn.execute(
            "SELECT * FROM reconstruction_frames WHERE run_id = ? ORDER BY revision DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()


def publish_frame(
    db_path: Path,
    recon_dir: Path,
    run_id: str,
    results_dir: Path,
    group_id: str,
    source: str = DEFAULT_SOURCE,
    expected_glb_sha256: str | None = None,
) -> ReconstructionSummary:
    """Publish one frame from ``results_dir`` (summary.json + <group>-voxels.ply).

    Returns the new latest summary. Raises ``ReconstructionError`` on any binding,
    PLY or ordering problem, leaving the previous result untouched.
    """
    run = get_run(db_path, run_id)
    if run is None:
        raise ReconstructionError(f"run not found: {run_id}")
    expected_glb = expected_glb_sha256 or sjk_glb_sha256()

    summary_path = Path(results_dir) / "summary.json"
    if not summary_path.is_file():
        raise ReconstructionError(f"缺少 summary.json：{summary_path}")
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReconstructionError(f"summary.json 不是有效 JSON：{exc}") from exc

    # Immutable run binding (scene / asset / coordinate frame).
    if summary.get("scene_id") != run.scene_id:
        raise ReconstructionError(f"场景 ID 不匹配：结果「{summary.get('scene_id')}」vs 运行「{run.scene_id}」")
    if summary.get("asset_version") != run.asset_version:
        raise ReconstructionError(f"资产版本不匹配：结果「{summary.get('asset_version')}」vs 运行「{run.asset_version}」")
    if summary.get("coordinate_frame_id") != run.coordinate_frame_id:
        raise ReconstructionError(
            f"坐标系不匹配：结果「{summary.get('coordinate_frame_id')}」vs 运行「{run.coordinate_frame_id}」"
        )

    groups = summary.get("groups") or []
    group = next((g for g in groups if g.get("group_id") == group_id), None)
    if group is None:
        raise ReconstructionError(f"summary.json 中找不到分组 {group_id}")

    sim_time = group.get("simulation_time_s")
    if not isinstance(sim_time, (int, float)):
        raise ReconstructionError(f"分组 {group_id} 缺少 simulation_time_s")
    voxel_count = group.get("candidate_voxel_count")
    if not isinstance(voxel_count, int) or voxel_count <= 0:
        raise ReconstructionError(f"分组 {group_id} 缺少有效的候选体素数")
    voxel_size_m = summary.get("voxel_size_m")
    if not isinstance(voxel_size_m, (int, float)) or voxel_size_m <= 0:
        voxel_size_m = 4.0
    glb_sha = (group.get("terrain_clip") or {}).get("glb_sha256")
    if glb_sha and glb_sha != expected_glb:
        raise ReconstructionError(f"GLB SHA 不匹配：结果「{glb_sha}」vs 期望「{expected_glb}」")
    mask_source = group.get("mask_source") or None

    ply_path = Path(results_dir) / f"{group_id}-voxels.ply"
    if not ply_path.is_file():
        raise ReconstructionError(f"缺少 PLY：{ply_path}")
    ply_data = ply_path.read_bytes()
    byte_size, ply_sha = _validate_ply(ply_data, voxel_count)

    # Ordering / duplicate guard: a new frame must be strictly later in time.
    latest = _latest_row(db_path, run_id)
    if latest is not None:
        if float(sim_time) < latest["simulation_time_s"]:
            raise ReconstructionError(
                f"旧时间帧：{sim_time}s 早于当前最新 {latest['simulation_time_s']}s，不能覆盖"
            )
        if float(sim_time) == latest["simulation_time_s"]:
            raise ReconstructionError(
                f"重复帧：分组 {latest['group_id']} 时间 {sim_time}s 已发布，不能覆盖"
            )

    new_revision = 1 if latest is None else latest["revision"] + 1
    produced_at = datetime.now(timezone.utc)
    storage_key = f"{run_id}/r{new_revision}.ply"

    # Atomic switch: write the file fully first, then commit the DB row that
    # makes it the latest result.
    final = Path(recon_dir) / storage_key
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_suffix(".ply.tmp")
    tmp.write_bytes(ply_data)
    os.replace(tmp, final)

    conn = db.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO reconstruction_frames "
            "(run_id, revision, group_id, simulation_time_s, source, voxel_count, voxel_size_m, "
            "byte_size, ply_sha256, glb_sha256, mask_source, produced_at, storage_key) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                new_revision,
                group_id,
                float(sim_time),
                source,
                voxel_count,
                float(voxel_size_m),
                byte_size,
                ply_sha,
                glb_sha,
                mask_source,
                produced_at.isoformat(),
                storage_key,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        final.unlink(missing_ok=True)
        raise
    finally:
        conn.close()

    return ReconstructionSummary(
        run_id=run_id,
        status="available",
        revision=new_revision,
        group_id=group_id,
        simulation_time_s=float(sim_time),
        source=source,
        mask_source=mask_source,
        voxel_count=voxel_count,
        voxel_size_m=float(voxel_size_m),
        byte_size=byte_size,
        ply_sha256=ply_sha,
        glb_sha256=glb_sha,
        produced_at=produced_at,
    )


def get_latest_summary(db_path: Path, run_id: str) -> ReconstructionSummary | None:
    row = _latest_row(db_path, run_id)
    if row is None:
        return None
    return ReconstructionSummary(
        run_id=run_id,
        status="available",
        revision=row["revision"],
        group_id=row["group_id"],
        simulation_time_s=row["simulation_time_s"],
        source=row["source"],
        mask_source=row["mask_source"],
        voxel_count=row["voxel_count"],
        voxel_size_m=row["voxel_size_m"],
        byte_size=row["byte_size"],
        ply_sha256=row["ply_sha256"],
        glb_sha256=row["glb_sha256"],
        produced_at=datetime.fromisoformat(row["produced_at"]),
    )


def get_frame(db_path: Path, run_id: str, revision: int) -> PublishedFrame | None:
    conn = db.connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM reconstruction_frames WHERE run_id = ? AND revision = ?",
            (run_id, revision),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return PublishedFrame(
        run_id=run_id,
        revision=row["revision"],
        group_id=row["group_id"],
        simulation_time_s=row["simulation_time_s"],
        source=row["source"],
        voxel_count=row["voxel_count"],
        voxel_size_m=row["voxel_size_m"],
        byte_size=row["byte_size"],
        ply_sha256=row["ply_sha256"],
        glb_sha256=row["glb_sha256"],
        mask_source=row["mask_source"],
        produced_at=datetime.fromisoformat(row["produced_at"]),
        storage_key=row["storage_key"],
    )


def read_ply(recon_dir: Path, frame: PublishedFrame) -> bytes | None:
    path = Path(recon_dir) / frame.storage_key
    if not path.is_file():
        return None
    return path.read_bytes()


def list_frames(db_path: Path, run_id: str) -> list[PublishedFrame]:
    """All successfully published frames for a run, ordered by simulation time."""
    conn = db.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM reconstruction_frames WHERE run_id = ? ORDER BY simulation_time_s ASC",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        PublishedFrame(
            run_id=run_id,
            revision=row["revision"],
            group_id=row["group_id"],
            simulation_time_s=row["simulation_time_s"],
            source=row["source"],
            voxel_count=row["voxel_count"],
            voxel_size_m=row["voxel_size_m"],
            byte_size=row["byte_size"],
            ply_sha256=row["ply_sha256"],
            glb_sha256=row["glb_sha256"],
            mask_source=row["mask_source"],
            produced_at=datetime.fromisoformat(row["produced_at"]),
            storage_key=row["storage_key"],
        )
        for row in rows
    ]
