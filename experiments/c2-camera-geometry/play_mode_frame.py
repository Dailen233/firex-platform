#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E3.2 Play Mode 采集帧核验（只读模块）：复用 C2 相机几何 + E3.1 轴映射。

链路（列向量；坐标约定见 C2 README 与 contracts/conventions.md）：
- 前向：顶点 Unity 世界 → demo_rh 世界（W 翻 Z）→ 后端相机（R_demo）→ 左上连续图像 (u,v)，
  与 Unity 导出的屏幕像素（左下原点）经 `unity_screen_to_image` 翻转后比较 → 像素误差。
- 反向：Unity 导出像素 → 左上 (u,v) → 后端相机射线 → demo_rh → Unity 世界射线 →（当帧
  `mesh_local_to_world` 逆 + E3.1 轴映射 diag(-1,1,1)）→ GLB 射线 → 只与地形网格求交 →
  与顶点独立参考位置比较 → 米制误差。

只读：不改模型/火区开关、不写 run/state、不叠火区。真实采集样本未到前用合成样本自验。
"""
from __future__ import annotations

import numpy as np

import camera_geometry as cg

# E3.1 轴映射：mesh_local -> GLB（X 反射；diag(-1,1,1) 自逆，故 glb↔mesh_local 同矩阵）。
AXIS_MAP_GLB_FROM_MESH_LOCAL = np.diag([-1.0, 1.0, 1.0])

# 阈值（看结果前声明）
REPROJ_PX = 0.5    # 前向投影像素误差上限
RAY_HIT_M = 0.01   # 反向射线落点米制误差上限（真实 float32 样本留 1 cm 余量）

# 预期资产/坐标约定（来自 sjk_local_registration_v1.json 的 web_asset；真实样本须声明并与之一致）
EXPECTED = {
    "scene_id": "sjk_hydropower_sim_v0_1",
    "asset_version": "hydro-sim-v0.1-local",
    "coordinate_frame_id": "SJK_TEAM_FBX_FILE_METRE_UNREGISTERED_v1",
    "glb_sha256": "722b8514a17715f3c109b1cbaa8259dc958c8f212af71cd1c0ae75608566fb91",
    "terrain_mesh_name": "team_fbx_terrain_129",
}


def _pos_int(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return v > 0
    if isinstance(v, float):
        return v.is_integer() and v > 0
    return False


def parse_rigid(data, name):
    """解析 row-major 16 元素 -> (R, t, errors)。复用 C2 刚体核验（末行/正交/det=+1/单位轴）。"""
    errors = []
    try:
        M = cg.reshape_matrix(data)
    except ValueError as e:
        return None, None, [f"{name} 矩阵解析失败：{e}"]
    R, t, merrs = cg.decompose_c2w(M)
    for e in merrs:
        errors.append(f"{name}：{e}")
    return R, t, errors


def unity_world_to_image(unity_world, R_demo, t_demo, K):
    """Unity 世界点 -> 左上连续图像坐标 (u, v)。"""
    p_demo = cg.W @ np.asarray(unity_world, dtype=np.float64)  # Unity -> demo_rh
    return cg.project(p_demo, R_demo, t_demo, K)


def unity_image_to_ray(u, v, R_demo, t_demo, K):
    """左上像素 (u,v) -> Unity 世界射线 (origin, direction)（方向未归一化）。"""
    d_cam = cg.pixel_to_cam_dir(u, v, K)     # 后端相机方向（z=1 前向）
    d_demo = R_demo @ d_cam                   # demo_rh 世界方向
    d_unity = cg.W @ d_demo                   # Unity 世界方向
    o_unity = cg.W @ t_demo                   # = t_unity（相机位置）
    return o_unity, d_unity


def unity_ray_to_glb(o_unity, d_unity, R_mlw, t_mlw):
    """Unity 世界射线 -> GLB 射线。mesh_local = R_mlwᵀ (p - t_mlw)；glb = diag(-1,1,1) @ mesh_local。"""
    A = AXIS_MAP_GLB_FROM_MESH_LOCAL
    R_inv = R_mlw.T
    o_glb = A @ R_inv @ (np.asarray(o_unity, dtype=np.float64) - t_mlw)
    d_glb = A @ R_inv @ np.asarray(d_unity, dtype=np.float64)
    return o_glb, d_glb


def ray_mesh_intersect(o, d, vertices, triangles, tmax=1e6):
    """射线 o + t*d 与三角形网格求交（Möller–Trumbore，向量化）。返回 (t, xyz) 或 None。"""
    o = np.asarray(o, dtype=np.float64)
    d = np.asarray(d, dtype=np.float64)
    V = np.asarray(vertices, dtype=np.float64)
    T = np.asarray(triangles, dtype=np.int64)
    if V.ndim != 2 or V.shape[1] != 3:
        raise ValueError("地形顶点必须为 (V,3)")
    if T.ndim != 2 or T.shape[1] != 3:
        raise ValueError("三角形索引必须为 (M,3)")
    v0, v1, v2 = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    e1 = v1 - v0
    e2 = v2 - v0
    p = np.cross(d[None, :], e2)
    det = np.einsum("ij,ij->i", e1, p)
    eps = 1e-12
    s = o - v0
    u = np.einsum("ij,ij->i", s, p) / det
    q = np.cross(s, e1)
    v = np.einsum("ij,ij->i", d[None, :], q) / det
    t = np.einsum("ij,ij->i", e2, q) / det
    hit = (
        (np.abs(det) > eps) & (u >= -eps) & (v >= -eps)
        & (u + v <= 1.0 + eps) & (t >= 0.0) & (t <= tmax)
    )
    if not np.any(hit):
        return None
    tvals = np.where(hit, t, np.inf)
    k = int(np.argmin(tvals))
    th = float(t[k])
    return th, (o + th * d).tolist()


def _check_asset(frame, rec):
    """核对资产与坐标约定：帧声明字段与 E3.1 注册 JSON 的 web_asset 一致。"""
    errors = []
    for key, expected in EXPECTED.items():
        val = frame.get(key)
        if val is None:
            errors.append(f"帧缺少资产字段 {key}")
            continue
        if str(val) != expected:
            errors.append(f"资产字段 {key} 不符：声明 {val!r}，预期 {expected!r}")
    rec["asset_expected"] = dict(EXPECTED)
    return errors


def verify_frame(frame, terrain_vertices, terrain_triangles, image_path=None, image_sha256=None):
    """核验单帧 Play Mode 采集。返回记录（status=ok/error；含 checks 与 errors）。"""
    rec = {"frame_id": frame.get("frame_id"), "checks": []}
    errors = []

    # 1) 资产与坐标约定
    asset_errs = _check_asset(frame, rec)
    rec["checks"].append(("asset_binding", not asset_errs, asset_errs or "ok"))
    errors.extend(asset_errs)

    # 2) 图像尺寸三向绑定（帧声明尺寸 == 清单尺寸 == 实际解码尺寸）
    W_img = frame.get("image_width")
    H_img = frame.get("image_height")
    if not _pos_int(W_img) or not _pos_int(H_img):
        errors.append(f"帧 image_width/image_height 非正整数：{W_img!r}x{H_img!r}")
        rec["status"] = "error"; rec["errors"] = errors
        return rec
    W_img, H_img = int(W_img), int(H_img)
    size_errors = []
    if image_path is not None:
        import cv2
        img = cv2.imread(str(image_path))
        if img is None:
            size_errors.append(f"无法读取图像：{image_path}")
        else:
            h, w = img.shape[:2]
            if (w, h) != (W_img, H_img):
                size_errors.append(f"图像实际尺寸 {w}x{h} 与帧声明 {W_img}x{H_img} 不一致")
    if image_sha256 is not None and image_path is not None:
        import hashlib
        h = hashlib.sha256()
        with open(image_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        actual = h.hexdigest()
        if actual != image_sha256:
            size_errors.append(f"图像哈希不符：清单 {image_sha256[:12]}… 实际 {actual[:12]}…")
    rec["checks"].append(("image_size_sha", not size_errors, size_errors or f"ok {W_img}x{H_img}"))
    errors.extend(size_errors)
    if errors:
        rec["status"] = "error"; rec["errors"] = errors
        rec["skipped"] = "资产/尺寸绑定失败，未生成几何结论"
        return rec

    # 3) 相机解析 + 内部一致性（复用 C2）
    try:
        rep, pose_errs = cg.check_pose_internal(frame)
    except Exception as e:
        rec["status"] = "error"; rec["errors"] = [f"相机字段解析失败：{e}"]; return rec
    rec["checks"].append(("camera_internal_consistent", not pose_errs, pose_errs or "ok"))
    errors.extend(pose_errs)
    if "R_unity" not in rep:
        rec["status"] = "error"; rec["errors"] = errors or ["相机矩阵解析失败"]; return rec

    Rd, td, cerrs = cg.convert_to_demo(rep["R_unity"], rep["t_unity"])
    rec["checks"].append(("camera_handedness", not cerrs, cerrs or "ok"))
    errors.extend(cerrs)
    K = cg.intrinsics_from_fov(float(frame["fov_y_deg"]), W_img, H_img)

    # 4) 当帧 mesh_local_to_world 解析（刚体，det=+1）
    R_mlw, t_mlw, merrs = parse_rigid(frame.get("mesh_local_to_world"), "mesh_local_to_world")
    rec["checks"].append(("mesh_local_to_world_rigid", not merrs, merrs or "ok"))
    errors.extend(merrs)

    # 5) 轴映射（默认 E3.1 的 diag(-1,1,1)；帧可显式声明并须与之一致）
    am = frame.get("axis_map_glb_from_mesh_local")
    am_errors = []
    if am is not None:
        am = np.asarray(am, dtype=np.float64)
        if am.shape not in ((9,), (16,)):
            am_errors.append("axis_map_glb_from_mesh_local 必须为 9 或 16 元素")
        else:
            linear = am.reshape(3, 3) if am.shape == (9,) else am.reshape(4, 4)[:3, :3]
            if not np.allclose(linear, AXIS_MAP_GLB_FROM_MESH_LOCAL, atol=cg.ORTHO_TOL):
                am_errors.append("axis_map_glb_from_mesh_local 与 E3.1 的 diag(-1,1,1) 不符")
    rec["checks"].append(("axis_map", not am_errors, am_errors or "ok"))
    errors.extend(am_errors)

    if R_mlw is None or errors:
        rec["status"] = "error"; rec["errors"] = errors; return rec

    # 6) 逐顶点：前向投影 + 反向射线地形求交
    points = frame.get("points") or []
    if not points:
        errors.append("帧缺少 points（至少一个已知顶点）")
        rec["status"] = "error"; rec["errors"] = errors; return rec

    pt_results = []
    for p in points:
        pid = p.get("point_id", "?")
        pr = {"point_id": pid}
        perr = []
        try:
            uw = np.asarray(p["unity_world_xyz"], dtype=np.float64)
            ref = np.asarray(p["glb_reference_xyz"], dtype=np.float64)
            upx = p["unity_pixel"]  # Unity 屏幕坐标（左下原点）
            # 前向：Unity 世界 -> 左上图像
            u_proj, v_proj = unity_world_to_image(uw, Rd, td, K)
            u_ref, v_ref = cg.unity_screen_to_image(float(upx[0]), float(upx[1]), H_img)
            px_err = float(np.hypot(u_proj - u_ref, v_proj - v_ref))
            pr["projected_px"] = [round(float(u_proj), 4), round(float(v_proj), 4)]
            pr["exported_px_image"] = [round(float(u_ref), 4), round(float(v_ref), 4)]
            pr["pixel_error_px"] = px_err
            if px_err > REPROJ_PX:
                perr.append(f"前向投影像素误差 {px_err:.4f}px 超阈值 {REPROJ_PX}px")
            # 反向：像素 -> 射线 -> GLB -> 地形求交
            o_u, d_u = unity_image_to_ray(u_ref, v_ref, Rd, td, K)
            o_glb, d_glb = unity_ray_to_glb(o_u, d_u, R_mlw, t_mlw)
            hit = ray_mesh_intersect(o_glb, d_glb, terrain_vertices, terrain_triangles)
            if hit is None:
                pr["ray_hit_xyz"] = None
                pr["metric_error_m"] = None
                perr.append("反向射线未命中地形")
            else:
                th, hit_xyz = hit
                hit_xyz = np.asarray(hit_xyz, dtype=np.float64)
                pr["ray_hit_xyz"] = [round(float(x), 4) for x in hit_xyz]
                pr["metric_error_m"] = float(np.linalg.norm(hit_xyz - ref))
                if pr["metric_error_m"] > RAY_HIT_M:
                    perr.append(f"落点米制误差 {pr['metric_error_m']:.6g}m 超阈值 {RAY_HIT_M}m")
            pr["glb_reference_xyz"] = [round(float(x), 4) for x in ref]
        except KeyError as e:
            perr.append(f"点字段缺失：{e}")
        except (ValueError, TypeError) as e:
            perr.append(f"点解析失败：{e}")
        pr["ok"] = not perr
        pr["errors"] = perr
        pt_results.append(pr)
    rec["points"] = pt_results
    rec["checks"].append(("points_projection_raycast", all(p["ok"] for p in pt_results), "ok"))
    errors.extend(f"[{p['point_id']}] {e}" for p in pt_results for e in p["errors"])

    rec["status"] = "ok" if not errors else "error"
    if errors:
        rec["errors"] = errors
    return rec
