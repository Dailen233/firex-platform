#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E3.2 真实采集样本复验：Unity 原生 worldToCameraMatrix + projectionMatrix 路径（单帧）。

样本：data/sjk_vertex_16099_capture_20261108.zip（sjk_play_001.png + sjk_play_001.json）。
- 视图矩阵 worldToCameraMatrix det≈-1（Unity 左手世界 → 右手相机，含手性翻转），单独按原生
  矩阵处理，不套用 C2 的 det=+1 检查。
- projectionMatrix 为 OpenGL 风格透视（near≈100 / far≈10000 / fov=60°）。
- 像素已是 PNG 左上原点，不预翻转 Y。
- 用当帧 localToWorldMatrix + E3.1 X 轴映射（diag(-1,1,1)）→ GLB，对实际 GLB 的
  team_fbx_terrain_129 求最近交点。
- Unity 顶点 16099 ↔ GLB 顶点 8460（索引不混用，独立参考位置取 GLB 顶点 8460）。
- 验收：像素 ≤ 0.5 px，米制 ≤ 0.01 m。

运行（仓库根）：
    /home/dailen/vggt/vggt-env/bin/python experiments/c2-camera-geometry/verify_vertex_16099.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parent))
import play_mode_frame as pmf

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ZIP = REPO_ROOT / "data" / "sjk_vertex_16099_capture_20261108.zip"
DEFAULT_GLB = REPO_ROOT / "frontend" / "public" / "models" / "sjk-hydropower-sim-v0.1" / "sjk_hydropower_sim_v0_1.glb"
DEFAULT_OUT = REPO_ROOT / "runtime-data" / "e3-real" / "e3_summary.json"

# 验收阈值（任务给定）
REPROJ_PX = 0.5
RAY_HIT_M = 0.01

# E3.1 轴映射：mesh_local -> GLB（X 反射）
AXIS_MAP = np.diag([-1.0, 1.0, 1.0])

TERRAIN_NAME = "team_fbx_terrain_129"
UNITY_VERTEX_INDEX = 16099
GLB_VERTEX_INDEX = 8460


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def project_native(world, V, P, W, H):
    """Unity 原生矩阵前向投影：clip = P @ V @ world -> NDC -> 左上像素。"""
    p4 = np.append(np.asarray(world, dtype=np.float64), 1.0)
    clip = P @ (V @ p4)
    if abs(clip[3]) < 1e-12:
        raise ValueError("clip.w 退化")
    ndc = clip[:3] / clip[3]
    u = (ndc[0] + 1.0) / 2.0 * W
    v = (1.0 - ndc[1]) / 2.0 * H
    return float(u), float(v)


def pixel_to_world_ray(px, py, V, P, W, H):
    """左上像素 -> 世界射线 (origin, direction)。direction 未归一化。"""
    ndc_x = 2.0 * px / W - 1.0
    ndc_y = 1.0 - 2.0 * py / H
    # 相机空间方向：OpenGL 相机，z 前为负；取 z_c=-1
    d_cam = np.array([ndc_x / P[0, 0], ndc_y / P[1, 1], -1.0], dtype=np.float64)
    Vinv = np.linalg.inv(V)
    d_world = Vinv[:3, :3] @ d_cam
    o_world = (Vinv @ np.array([0.0, 0.0, 0.0, 1.0]))[:3]
    return o_world, d_world


def world_ray_to_glb(o_world, d_world, L):
    """世界射线 -> GLB 射线：mesh_local = L^-1 @ world；glb = diag(-1,1,1) @ mesh_local。"""
    Linv = np.linalg.inv(L)
    o_ml = (Linv @ np.append(o_world, 1.0))[:3]
    d_ml = Linv[:3, :3] @ d_world
    return AXIS_MAP @ o_ml, AXIS_MAP @ d_ml


def main():
    ap = argparse.ArgumentParser(description="E3.2 真实采集样本复验（Unity 原生矩阵，单帧）")
    ap.add_argument("--zip", default=str(DEFAULT_ZIP))
    ap.add_argument("--glb", default=str(DEFAULT_GLB))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    zip_path = Path(args.zip)
    glb_path = Path(args.glb)
    out_path = Path(args.out)

    # 原件哈希
    zip_sha = sha256_file(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        json_name = next(n for n in names if n.endswith(".json"))
        png_name = next(n for n in names if n.endswith(".png"))
        frame = json.loads(zf.read(json_name).decode("utf-8"))
        png_bytes = zf.read(png_name)
    png_sha = hashlib.sha256(png_bytes).hexdigest()
    json_sha = hashlib.sha256(zipfile.ZipFile(zip_path).read(json_name)).hexdigest()

    # 矩阵（行数组，Unity Matrix4x4.GetRow order）
    V = np.array(frame["worldToCameraMatrix"], dtype=np.float64)
    P = np.array(frame["projectionMatrix"], dtype=np.float64)
    L = np.array(frame["localToWorldMatrix"], dtype=np.float64)
    W, H = int(frame["width"]), int(frame["height"])
    world = np.array([frame["world"]["x"], frame["world"]["y"], frame["world"]["z"]], dtype=np.float64)
    pixel_json = (float(frame["pixel"]["x"]), float(frame["pixel"]["y"]))
    detV = float(np.linalg.det(V))

    # 前向投影
    u, v = project_native(world, V, P, W, H)
    pixel_error = float(np.hypot(u - pixel_json[0], v - pixel_json[1]))

    # 反向射线 -> GLB
    o_world, d_world = pixel_to_world_ray(pixel_json[0], pixel_json[1], V, P, W, H)
    o_glb, d_glb = world_ray_to_glb(o_world, d_world, L)

    # 实际 GLB 地形
    glb_sha = sha256_file(glb_path)
    scene = trimesh.load(str(glb_path), process=False)
    terrain = scene.geometry[TERRAIN_NAME]
    vertices = np.asarray(terrain.vertices, dtype=np.float64)
    faces = np.asarray(terrain.faces, dtype=np.int64)
    ref_glb = vertices[GLB_VERTEX_INDEX]  # 独立参考：GLB 顶点 8460

    # 最近交点（只对 team_fbx_terrain_129）
    hit = pmf.ray_mesh_intersect(o_glb, d_glb, vertices, faces)
    if hit is None:
        metric_error = None
        hit_xyz = None
    else:
        _, hit_xyz = hit
        metric_error = float(np.linalg.norm(np.asarray(hit_xyz) - ref_glb))

    pixel_pass = pixel_error <= REPROJ_PX
    metric_pass = metric_error is not None and metric_error <= RAY_HIT_M
    status = "ok" if (pixel_pass and metric_pass) else "error"

    summary = {
        "capture": zip_path.name,
        "frame": json_name,
        "hashes": {"zip_sha256": zip_sha, "png_sha256": png_sha, "json_sha256": json_sha, "glb_sha256": glb_sha},
        "image_size": [W, H],
        "det_worldToCameraMatrix": detV,
        "note": "视图矩阵 det≈-1，按 Unity 原生矩阵处理（不套用 C2 det=+1）；像素为 PNG 左上原点，不翻转 Y",
        "unity_vertex_index": UNITY_VERTEX_INDEX,
        "glb_vertex_index": GLB_VERTEX_INDEX,
        "projected_pixel": [round(u, 6), round(v, 6)],
        "json_pixel": list(pixel_json),
        "pixel_error_px": pixel_error,
        "pixel_pass": pixel_pass,
        "ray_origin_glb": [round(float(x), 6) for x in o_glb],
        "ray_direction_glb": [round(float(x), 6) for x in d_glb],
        "ray_hit_glb_xyz": [round(float(x), 6) for x in hit_xyz] if hit_xyz else None,
        "glb_reference_xyz": [round(float(x), 6) for x in ref_glb],
        "metric_error_m": metric_error,
        "metric_pass": metric_pass,
        "terrain": {"name": TERRAIN_NAME, "vertices": int(vertices.shape[0]), "triangles": int(faces.shape[0])},
        "thresholds": {"REPROJ_PX": REPROJ_PX, "RAY_HIT_M": RAY_HIT_M},
        "status": status,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    print("=" * 72)
    print("E3.2 真实采集样本复验（Unity 原生矩阵）")
    print(f"  ZIP  = {zip_path} ({zip_sha[:16]}…)")
    print(f"  PNG  = {png_sha[:16]}…   JSON = {json_sha[:16]}…")
    print(f"  GLB  = {glb_sha[:16]}…   det(worldToCameraMatrix) = {detV:.6f}")
    print(f"  图像 {W}x{H}  顶点 Unity {UNITY_VERTEX_INDEX} ↔ GLB {GLB_VERTEX_INDEX}")
    print(f"  投影像素 {u:.6f},{v:.6f}  vs  JSON {pixel_json[0]},{pixel_json[1]}  → 像素误差 {pixel_error:.6f} px {'PASS' if pixel_pass else 'FAIL'}")
    if hit_xyz is None:
        print("  射线未命中地形 → FAIL")
    else:
        print(f"  命中 {[round(x,6) for x in hit_xyz]}  vs  参考 {[round(x,6) for x in ref_glb]}  → 米制误差 {metric_error:.6f} m {'PASS' if metric_pass else 'FAIL'}")
    print(f"  status = {status}")
    print(f"  summary -> {out_path}")
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
