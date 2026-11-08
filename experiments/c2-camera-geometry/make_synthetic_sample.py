#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E3.2 合成样本生成器：构造自洽的 Play Mode 采集帧（地形 + 相机 + 顶点 + 像素 + 原图）。

用「Unity 直接投影」（左手系 WorldToScreenPoint 语义，独立于 camera_geometry 的 demo 手性
转换路径）计算导出像素，供 verify_play_mode_frame.py 的前向投影路径交叉验证；反向射线则须
在 GLB 地形上恢复到顶点的独立参考位置。

输出目录：runtime-data/e3-synthetic/（gitignore 覆盖）。真实 Play Mode 采集样本到齐后，
以同 schema 交付即由同一脚本核验。
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "runtime-data" / "e3-synthetic"

# 资产/坐标约定（与 sjk_local_registration_v1.json 一致）
ASSET = {
    "scene_id": "sjk_hydropower_sim_v0_1",
    "asset_version": "hydro-sim-v0.1-local",
    "coordinate_frame_id": "SJK_TEAM_FBX_FILE_METRE_UNREGISTERED_v1",
    "glb_sha256": "722b8514a17715f3c109b1cbaa8259dc958c8f212af71cd1c0ae75608566fb91",
    "terrain_mesh_name": "team_fbx_terrain_129",
}
AXIS_MAP = [-1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]  # diag(-1,1,1)


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)


def look_at_unity(pos, target, world_up=(0.0, 1.0, 0.0)):
    """Unity 左手系 LookAt：返回 R（列 = [right, up, forward]，det=+1，right×up=forward）。"""
    fwd = np.asarray(target, float) - np.asarray(pos, float)
    fwd = fwd / np.linalg.norm(fwd)
    right = np.cross(world_up, fwd)
    right = right / np.linalg.norm(right)
    up = np.cross(fwd, right)
    return np.column_stack([right, up, fwd])


def make_terrain(nx=17, nz=17, span=5000.0):
    """合成地形（GLB 坐标）：规则网格 + 斜坡高度场 y = 0.05x + 0.02z + 100。"""
    xs = np.linspace(-span, span, nx)
    zs = np.linspace(-span, span, nz)
    vertices = []
    for z in zs:
        for x in xs:
            vertices.append([x, 0.05 * x + 0.02 * z + 100.0, z])
    vertices = np.asarray(vertices, dtype=np.float64)
    triangles = []
    for iz in range(nz - 1):
        for ix in range(nx - 1):
            v00 = iz * nx + ix
            v10 = iz * nx + ix + 1
            v01 = (iz + 1) * nx + ix
            v11 = (iz + 1) * nx + ix + 1
            triangles.append([v00, v10, v11])
            triangles.append([v00, v11, v01])
    return vertices, np.asarray(triangles, dtype=np.int64), (xs, zs)


def unity_project_direct(p_world, R_unity, t_unity, fov_y_deg, W, H):
    """Unity 左手系直接投影（WorldToScreenPoint 语义，左下原点）。返回 (x_screen, y_screen, z)。"""
    p_c = R_unity.T @ (np.asarray(p_world, float) - t_unity)
    if p_c[2] <= 1e-9:
        raise ValueError(f"顶点在相机后方：z={p_c[2]:.6g}")
    fy = (H / 2.0) / math.tan(math.radians(fov_y_deg) / 2.0)
    x = W / 2.0 + fy * p_c[0] / p_c[2]
    y = H / 2.0 + fy * p_c[1] / p_c[2]
    return float(x), float(y), float(p_c[2])


def mat4_flat(R, t):
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = t
    return M.reshape(-1).tolist()  # row-major


def main():
    W, H, fov = 1280, 720, 60.0
    # 当帧 mesh_local_to_world：绕 Y 轴 20° + 平移（刚体，det=+1）
    R_mlw = rot_y(math.radians(20.0))
    t_mlw = np.array([1000.0, 0.0, 2000.0])
    mlw = mat4_flat(R_mlw, t_mlw)
    A = np.diag([-1.0, 1.0, 1.0])

    # 地形 + 相机（Unity LookAt 看向地形中心）
    vertices, triangles, (xs, zs) = make_terrain()
    center_glb = np.array([0.0, 100.0, 0.0])
    center_ml = A @ center_glb
    center_uw = R_mlw @ center_ml + t_mlw
    cam_pos = center_uw + np.array([0.0, 2600.0, -4200.0])
    R_unity = look_at_unity(cam_pos, center_uw)
    t_unity = cam_pos
    c2w = mat4_flat(R_unity, t_unity)
    fwd = R_unity[:, 2]
    up = R_unity[:, 1]
    right = R_unity[:, 0]

    # 顶点（含 X≠0 点，用于验证 X 反射）
    picks = [
        ("P_center", np.array([0.0, 0.0, 0.0])),          # 中心 X=0
        ("P_xpos", np.array([2500.0, 0.0, 0.0])),          # X>0（mesh_local X=-2500 → glb X=+2500）
        ("P_xneg_zpos", np.array([-2500.0, 0.0, 2500.0])), # X<0、Z>0 偏轴点
    ]
    points = []
    for pid, (gx, gy0, gz) in picks:
        y = 0.05 * gx + 0.02 * gz + 100.0
        glb = np.array([gx, y, gz])
        ml = A @ glb
        uw = R_mlw @ ml + t_mlw
        xs_screen, ys_screen, depth = unity_project_direct(uw, R_unity, t_unity, fov, W, H)
        if not (0.0 <= xs_screen <= W and 0.0 <= ys_screen <= H):
            raise RuntimeError(f"{pid} 投影超出图像范围：({xs_screen:.1f},{ys_screen:.1f})，请调整相机")
        points.append({
            "point_id": pid,
            "unity_world_xyz": [round(float(v), 6) for v in uw],
            "unity_mesh_local_xyz": [round(float(v), 6) for v in ml],
            "glb_reference_xyz": [round(float(v), 6) for v in glb],
            "unity_pixel": [round(xs_screen, 4), round(ys_screen, 4)],  # 左下原点（Unity 屏幕坐标）
        })

    # 原图：深灰背景 + 顶点标记（左上原点坐标 = x_screen, H - y_screen）
    img = np.full((H, W, 3), 58, dtype=np.uint8)
    for p in points:
        xs_s, ys_s = p["unity_pixel"]
        cv2.circle(img, (int(round(xs_s)), int(round(H - ys_s))), 6, (0, 255, 120), -1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    img_path = OUT_DIR / "play_001.png"
    cv2.imwrite(str(img_path), img)

    frame = {
        "schema": "fire-x.play-mode-frame.v1",
        "frame_id": "play_001",
        **ASSET,
        "image_width": W,
        "image_height": H,
        "fov_y_deg": fov,
        "camera_position": {"x": float(t_unity[0]), "y": float(t_unity[1]), "z": float(t_unity[2])},
        "camera_forward": {"x": float(fwd[0]), "y": float(fwd[1]), "z": float(fwd[2])},
        "camera_up": {"x": float(up[0]), "y": float(up[1]), "z": float(up[2])},
        "camera_right": {"x": float(right[0]), "y": float(right[1]), "z": float(right[2])},
        "camera_to_world_matrix": {"data": c2w},
        "mesh_local_to_world": mlw,
        "axis_map_glb_from_mesh_local": AXIS_MAP,
        "points": points,
    }
    frame_path = OUT_DIR / "play_001.json"
    frame_path.write_text(json.dumps(frame, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    manifest = {
        "description": "E3.2 合成 Play Mode 采集帧（自洽样本，用于验证核验脚本链路）",
        "terrain": {
            "vertices": [[round(float(v), 6) for v in vv] for vv in vertices],
            "triangles": [[int(i) for i in t] for t in triangles],
        },
        "frames": [
            {
                "id": "play_001",
                "frame": "play_001.json",
                "frame_sha256": hashlib.sha256(frame_path.read_bytes()).hexdigest(),
                "image": "play_001.png",
                "image_sha256": hashlib.sha256(img_path.read_bytes()).hexdigest(),
                "image_size": [W, H],
            }
        ],
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    print(f"合成样本已生成：{OUT_DIR}")
    for p in points:
        print(f"  {p['point_id']}: glb={p['glb_reference_xyz']} 像素={p['unity_pixel']}")


if __name__ == "__main__":
    main()
