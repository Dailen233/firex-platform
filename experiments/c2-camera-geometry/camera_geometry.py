#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 相机几何：轴向、手性转换与像素射线核验（纯 NumPy，无 IO / 无模型依赖）。

本模块只做可复核的数学：读取 Unity 新 schema 的 camera_to_world_matrix 与轴字段，
验证其内部一致性，做「世界换基」与「相机轴换基」两步转右手系，并推导内参与像素射线。

坐标约定（本轮实验坐标系，独立命名，不用于双江口/织金 coordinate_frame_id，不宣称地理配准）：
- Unity 世界：左手系，X右 / Y上 / Z前（官方文档确认）。
- Unity 相机局部轴：+X右(transform.right) / +Y上(transform.up) / +Z前(transform.forward)。
- 实验右手世界 demo_rh：点 = [Unity x, Unity y, -Unity z]，即 X右 / Y上 / Z朝观察者。
- 后端相机轴（右手系，x右 / y下 / z前，x×y=z）。
- W = diag(1,1,-1)：世界换基 Unity -> demo_rh（翻转世界 Z）。
- C = diag(1,-1,1)：相机轴换基 后端相机 -> Unity 相机（翻转相机局部 Y，把「y下」变回「y上」）。
- 组合（列向量，先右乘相机轴换基、再左乘世界换基）：
      R_demo = W @ R_unity @ C
      t_demo = W @ t_unity
  即：p_demo = R_demo @ p_cam_backend + t_demo。
- 投影（右手相机，x右/y下/z前；像素 u/v 为「左上原点的连续图像坐标」）：
  u = cx + fx·x/z，v = cy + fy·y/z；主点 cx=W/2、cy=H/2（连续坐标）。
- 连续坐标与离散索引（两者是不同操作，不混用）：
  · Unity 屏幕为「左下原点」的连续屏幕坐标；转连续图像坐标 u=x_screen、v=H-y_screen。
  · 离散数组行号翻转 j_top = H-1-j_bottom 只用于数组索引，不用于上述连续投影比较。

矩阵存储顺序（已从 TakePhoto.cs 与数据双重核实）：
  camera_to_world_matrix.data 为 row-major，data[r*4+c] = M[r][c]；
  列 0/1/2/3 = [right, up, forward, position]（Transform.localToWorldMatrix）。

内参假设（未经证明的条件，单独列出）：
  方形像素 fx=fy；主点居中 cx=W/2, cy=H/2；无畸变（Unity 为针孔相机，官方文档确认默认无径向畸变）。
  fy = (H/2) / tan(fov_y_deg/2)。视口/缩放/裁切若改变有效渲染尺寸，将破坏 cx/cy 居中假设（见 README）。

阈值（在看结果前声明）：
  ORTHO_TOL = 1e-4（float32 JSON 精度下的正交性/行列式/单位轴/字段一致）；
  VEC_TOL = 1e-4；RAY_ANGLE_DEG = 0.1；REPROJ_PX = 0.5；EPS = 1e-9（正深度判定）。
"""
from __future__ import annotations

import math

import numpy as np

# ---- 阈值（在看结果前声明） ----
EPS = 1e-9
ORTHO_TOL = 1e-4
VEC_TOL = 1e-4
RAY_ANGLE_DEG = 0.1
REPROJ_PX = 0.5

# ---- 换基矩阵 ----
W = np.diag([1.0, 1.0, -1.0])  # Unity 世界 -> demo_rh 右手世界（翻转 Z）
C = np.diag([1.0, -1.0, 1.0])  # 后端相机 -> Unity 相机（y下 -> y上）


# =========================================================================
# 矩阵解析与原始一致性核验
# =========================================================================

def reshape_matrix(data):
    """把 row-major 的 16 元素列表转成 4x4 矩阵（M[r][c] = data[4r+c]）。异常明确抛出。"""
    arr = np.asarray(data, dtype=np.float64)
    if arr.shape != (16,):
        raise ValueError(f"矩阵 data 必须为 16 个元素，实际 shape={arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ValueError("矩阵 data 含非有限值")
    return arr.reshape(4, 4)


def vec3(d):
    return np.array([float(d["x"]), float(d["y"]), float(d["z"])], dtype=np.float64)


def decompose_c2w(M):
    """分解 4x4 camera-to-world。返回 (R, t, errors)。

    核验：末行 [0,0,0,1]；旋转部分正交、det=+1、各轴单位长（拒绝缩放/剪切/反射）。
    不靠转置猜测、不正交化、不改原始数据；异常只记录不修正。
    """
    errors = []
    if not np.all(np.isfinite(M)):
        errors.append("矩阵含非有限值")
        return M[:3, :3].copy(), M[:3, 3].copy(), errors
    if not np.allclose(M[3], [0.0, 0.0, 0.0, 1.0], atol=ORTHO_TOL):
        errors.append(f"末行非 [0,0,0,1]：{M[3].tolist()}")
    R = M[:3, :3].copy()
    t = M[:3, 3].copy()
    RtR = R.T @ R
    if not np.allclose(RtR, np.eye(3), atol=ORTHO_TOL):
        errors.append("旋转部分不正交（RᵀR≠I）")
    det = float(np.linalg.det(R))
    if abs(det - 1.0) > ORTHO_TOL:
        errors.append(f"det(R)={det:.6g} 非 +1（含缩放/剪切/反射）")
    for i, name in enumerate(["right", "up", "forward"]):
        n = float(np.linalg.norm(R[:, i]))
        if abs(n - 1.0) > ORTHO_TOL:
            errors.append(f"轴 {name} 长度 {n:.6g} 非 1")
    return R, t, errors


def check_pose_internal(pose):
    """核验一个 pose JSON 的字段与矩阵内部一致性。返回 (report, errors)。"""
    errors = []
    report = {}
    try:
        W_img = int(pose["image_width"])
        H_img = int(pose["image_height"])
        fov = float(pose["fov_y_deg"])
    except (KeyError, TypeError, ValueError) as e:
        return report, [f"pose 字段缺失或非法：{e}"]
    report["image_size"] = [W_img, H_img]
    report["fov_y_deg"] = fov
    if W_img <= 0 or H_img <= 0:
        errors.append(f"图像尺寸非法：{W_img}x{H_img}")
    if not (0.0 < fov < 180.0) or not math.isfinite(fov):
        errors.append(f"fov_y_deg 非法：{fov}")

    pos = vec3(pose["camera_position"])
    fwd = vec3(pose["camera_forward"])
    up = vec3(pose["camera_up"])
    right = vec3(pose["camera_right"])
    for name, v in [("position", pos), ("forward", fwd), ("up", up), ("right", right)]:
        if not np.all(np.isfinite(v)):
            errors.append(f"camera_{name} 含非有限值")

    # 轴单位化 + 两两正交
    for name, v in [("forward", fwd), ("up", up), ("right", right)]:
        n = float(np.linalg.norm(v))
        if n < EPS:
            errors.append(f"camera_{name} 为零向量")
        elif abs(n - 1.0) > ORTHO_TOL:
            errors.append(f"camera_{name} 非单位长：{n:.6g}")
    for a, b in [("right", "up"), ("up", "forward"), ("forward", "right")]:
        va = vec3(pose[f"camera_{a}"])
        vb = vec3(pose[f"camera_{b}"])
        dot = float(np.dot(va, vb))
        if abs(dot) > ORTHO_TOL:
            errors.append(f"camera_{a} 与 camera_{b} 不正交：dot={dot:.6g}")

    # Unity 左手系：right × up == forward（用标准叉积公式）
    cross = np.cross(right, up)
    if not np.allclose(cross, fwd, atol=ORTHO_TOL):
        errors.append(f"right×up 与 forward 不一致：cross={cross.tolist()} forward={fwd.tolist()}")

    # 矩阵与字段一致
    try:
        M = reshape_matrix(pose["camera_to_world_matrix"]["data"])
    except (KeyError, ValueError) as e:
        errors.append(f"矩阵解析失败：{e}")
        return report, errors
    R, t, merrs = decompose_c2w(M)
    errors.extend(merrs)
    report["matrix_det"] = float(np.linalg.det(R)) if not merrs else None
    # 列对应关系
    for col, name, field in [(0, "right", "right"), (1, "up", "up"), (2, "forward", "forward")]:
        if not np.allclose(R[:, col], vec3(pose[f"camera_{field}"]), atol=ORTHO_TOL):
            errors.append(f"矩阵第 {col} 列与 camera_{name} 不一致")
    if not np.allclose(t, pos, atol=ORTHO_TOL):
        errors.append(f"矩阵平移与 camera_position 不一致：t={t.tolist()} pos={pos.tolist()}")
    report["R_unity"] = R
    report["t_unity"] = t
    report["pos"] = pos
    report["fwd_unity"] = fwd
    report["up_unity"] = up
    report["right_unity"] = right
    return report, errors


# =========================================================================
# 手性转换（世界换基 + 相机轴换基，分离定义）
# =========================================================================

def convert_to_demo(R_unity, t_unity):
    """R_demo = W @ R_unity @ C；t_demo = W @ t_unity。返回 (R_demo, t_demo, errors)。"""
    errors = []
    R_demo = W @ R_unity @ C
    t_demo = W @ t_unity
    RtR = R_demo.T @ R_demo
    if not np.allclose(RtR, np.eye(3), atol=ORTHO_TOL):
        errors.append("R_demo 不正交")
    det = float(np.linalg.det(R_demo))
    if abs(det - 1.0) > ORTHO_TOL:
        errors.append(f"R_demo det={det:.6g} 非 +1（非右手旋转）")
    return R_demo, t_demo, errors


def convert_pose_to_demo(report):
    """对 check_pose_internal 的报告做转换，返回 (R_demo, t_demo, errors)。"""
    return convert_to_demo(report["R_unity"], report["t_unity"])


def expected_demo_axes(report):
    """由字段推导 demo 世界的三轴（用于与 R_demo 列比对）。返回 (right, down, forward)。"""
    r = report["right_unity"]
    u = report["up_unity"]
    f = report["fwd_unity"]
    right_demo = W @ r          # [rx, ry, -rz]
    down_demo = -W @ u          # [-ux, -uy, uz]
    fwd_demo = W @ f            # [fx, fy, -fz]
    return right_demo, down_demo, fwd_demo


# =========================================================================
# 内参与投影 / 射线
# =========================================================================

def intrinsics_from_fov(fov_y_deg, W_img, H_img):
    """由垂直 FOV 与尺寸推导 K。假设方形像素、主点居中、无畸变。"""
    if not (0.0 < fov_y_deg < 180.0):
        raise ValueError(f"fov_y_deg 非法：{fov_y_deg}")
    if W_img <= 0 or H_img <= 0:
        raise ValueError(f"图像尺寸非法：{W_img}x{H_img}")
    fy = (H_img / 2.0) / math.tan(math.radians(fov_y_deg) / 2.0)
    fx = fy
    cx = W_img / 2.0
    cy = H_img / 2.0
    K = np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64)
    if not np.all(np.isfinite(K)) or fx <= 0:
        raise ValueError(f"K 非法：fx={fx}")
    return K


def pixel_to_cam_dir(u, v, K):
    """像素 -> 相机坐标方向（未归一化，z 分量为 1）。相机系：x右/y下/z前。

    u/v 为「左上原点的连续图像坐标」（continuous image coordinates）。
    """
    if not np.all(np.isfinite(K)) or K[0, 0] <= 0 or K[1, 1] <= 0:
        raise ValueError("K 退化（非有限或非正焦距）")
    return np.array([(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], 1.0], dtype=np.float64)


def unity_screen_to_image(x_screen, y_screen, H):
    """Unity 连续屏幕坐标（左下原点，y 向上）→ 连续图像坐标（左上原点，y 向下）。

    u = x_screen；v = H - y_screen。
    这是连续坐标的翻转（y 关于 H 对称），与离散数组行号翻转 j_top = H-1-j_bottom 是
    两种不同操作：后者用于数组索引，不用于连续投影比较。
    """
    return float(x_screen), float(H) - float(y_screen)


def image_to_unity_screen(u, v, H):
    """连续图像坐标（左上原点）→ Unity 连续屏幕坐标（左下原点）。x=u；y=H-v。"""
    return float(u), float(H) - float(v)


def flip_row_index_discrete(j_bottom, H):
    """离散像素行号翻转：j_top = H-1-j_bottom（仅用于数组索引，不用于连续投影比较）。"""
    return int(H) - 1 - int(j_bottom)


def world_to_cam(p_world, R, t):
    return R.T @ (np.asarray(p_world, dtype=np.float64) - t)


def cam_to_world(p_cam, R, t):
    return R @ np.asarray(p_cam, dtype=np.float64) + t


def project(p_world, R, t, K):
    """世界点 -> 像素。相机后方点（z<=EPS）明确拒绝。"""
    p = world_to_cam(p_world, R, t)
    if p[2] <= EPS:
        raise ValueError(f"点在相机后方或退化：z={p[2]:.6g}")
    u = K[0, 2] + K[0, 0] * p[0] / p[2]
    v = K[1, 2] + K[1, 1] * p[1] / p[2]
    return float(u), float(v)


def unproject(u, v, depth, R, t, K):
    """像素 + 正深度（相机 z）-> 世界点。"""
    if depth <= EPS:
        raise ValueError(f"深度非法：{depth}")
    d = pixel_to_cam_dir(u, v, K)
    return cam_to_world(depth * d, R, t)


# =========================================================================
# 逐项核验（返回 (ok, 数值) 或 (ok, 误差)）
# =========================================================================

def _cos_angle(a, b):
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    return float(np.dot(a, b))


def check_center_ray_forward(K):
    """中心像素 (cx, cy) 的射线方向应为相机 +Z（[0,0,1]）。"""
    d = pixel_to_cam_dir(K[0, 2], K[1, 2], K)
    d = d / np.linalg.norm(d)
    cos = float(np.dot(d, [0.0, 0.0, 1.0]))
    return cos >= math.cos(math.radians(RAY_ANGLE_DEG)), cos


def check_pixel_axes(K):
    """像素向右(+u)射线朝 +x、向下(+v)射线朝 +y（y下）。返回 (ok, [cos_x, cos_y])。"""
    cx, cy = K[0, 2], K[1, 2]
    dx = pixel_to_cam_dir(cx + 1.0, cy, K) - pixel_to_cam_dir(cx, cy, K)
    dy = pixel_to_cam_dir(cx, cy + 1.0, K) - pixel_to_cam_dir(cx, cy, K)
    cos_x = _cos_angle(dx, [1.0, 0.0, 0.0])
    cos_y = _cos_angle(dy, [0.0, 1.0, 0.0])
    th = math.cos(math.radians(RAY_ANGLE_DEG))
    return (cos_x >= th and cos_y >= th), (cos_x, cos_y)


def check_axes_columns(R_demo, report):
    """R_demo 三列应等于 [W@right, -W@up, W@forward]。返回 (ok, max_col_err)。"""
    right, down, fwd = expected_demo_axes(report)
    errs = [
        float(np.max(np.abs(R_demo[:, 0] - right))),
        float(np.max(np.abs(R_demo[:, 1] - down))),
        float(np.max(np.abs(R_demo[:, 2] - fwd))),
    ]
    return all(e <= VEC_TOL for e in errs), max(errs)


def check_cross_product(R_demo):
    """右手系：col0 × col1 == col2（right × down == forward）。返回 (ok, max_err)。"""
    c = np.cross(R_demo[:, 0], R_demo[:, 1])
    return bool(np.allclose(c, R_demo[:, 2], atol=ORTHO_TOL)), float(np.max(np.abs(c - R_demo[:, 2])))


def check_projection_roundtrip(R_demo, t_demo, K):
    """正深度点投影 -> 反投影应一致。返回 (ok, max_reproj_px, max_world_err)。"""
    # 取相机前向 10m 处的一点（含离轴分量）
    p_cam = np.array([0.4, -0.3, 10.0])
    p_world = cam_to_world(p_cam, R_demo, t_demo)
    u, v = project(p_world, R_demo, t_demo, K)
    z = p_cam[2]
    p_back = unproject(u, v, z, R_demo, t_demo, K)
    # 再把反投影点投回，看像素误差
    u2, v2 = project(p_back, R_demo, t_demo, K)
    reproj = math.hypot(u - u2, v - v2)
    world_err = float(np.linalg.norm(p_back - p_world))
    return (reproj <= REPROJ_PX), reproj, world_err
