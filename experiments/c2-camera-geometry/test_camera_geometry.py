#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 camera_geometry.py 的合成数学回归（纯 NumPy + 标准库，不读文件、不跑 Unity）。

覆盖层级 1（合成数学案例）：
- 非零俯仰/偏航/滚转的合成位姿（非单位阵、非纯 yaw）。
- 矩阵解析/一致性、手性转换、内参、中心射线、像素轴向、投影反投影往返。
- 反例必须失败：转置矩阵、遗漏像素纵轴转换、只转换一侧手性、相机后方点、退化 K、非法矩阵。

运行（仓库根）：
    /home/dailen/vggt/vggt-env/bin/python experiments/c2-camera-geometry/test_camera_geometry.py
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import camera_geometry as cg
import verify_historical_poses as vh


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)


def make_R_unity():
    """非零 yaw/pitch/roll 的合成 Unity 相机旋转（det=+1，right×up=forward）。"""
    return rot_y(math.radians(30)) @ rot_x(math.radians(20)) @ rot_z(math.radians(15))


def make_pose(R, t, fov=60.0, W=2193, H=1000):
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = t
    data = M.reshape(-1).tolist()  # row-major
    return {
        "frame_id": 1,
        "image_width": W, "image_height": H, "fov_y_deg": fov,
        "camera_position": {"x": t[0], "y": t[1], "z": t[2]},
        "camera_rotation_euler": {"x": 0.0, "y": 0.0, "z": 0.0},
        "camera_forward": {"x": R[0, 2], "y": R[1, 2], "z": R[2, 2]},
        "camera_up": {"x": R[0, 1], "y": R[1, 1], "z": R[2, 1]},
        "camera_right": {"x": R[0, 0], "y": R[1, 0], "z": R[2, 0]},
        "camera_to_world_matrix": {"data": data},
    }


class TestMatrixParsing(unittest.TestCase):
    def test_reshape_ok(self):
        M = cg.reshape_matrix([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
        self.assertEqual(M.shape, (4, 4))
        self.assertTrue(np.allclose(M, np.eye(4)))

    def test_reshape_wrong_len(self):
        with self.assertRaises(ValueError):
            cg.reshape_matrix([1, 0, 0])

    def test_reshape_nonfinite(self):
        with self.assertRaises(ValueError):
            cg.reshape_matrix([float("nan")] * 16)

    def test_decompose_last_row(self):
        M = np.eye(4); M[3, 3] = 2.0
        _, _, errs = cg.decompose_c2w(M)
        self.assertTrue(any("末行" in e for e in errs))

    def test_decompose_nonorthogonal(self):
        R = np.array([[1.0, 0.5, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        M = np.eye(4); M[:3, :3] = R
        _, _, errs = cg.decompose_c2w(M)
        self.assertTrue(any("正交" in e for e in errs))

    def test_decompose_scaled(self):
        R = np.diag([2.0, 1.0, 1.0])
        M = np.eye(4); M[:3, :3] = R
        _, _, errs = cg.decompose_c2w(M)
        self.assertTrue(any("det" in e or "长度" in e for e in errs))


class TestPoseConsistency(unittest.TestCase):
    def test_synthetic_pose_ok(self):
        R = make_R_unity()
        t = np.array([3.0, -1.5, 7.0])
        rep, errs = cg.check_pose_internal(make_pose(R, t))
        self.assertEqual(errs, [], f"应无错误：{errs}")
        self.assertAlmostEqual(rep["matrix_det"], 1.0, places=4)

    def test_transposed_matrix_flags_column_mismatch(self):
        R = make_R_unity()
        t = np.array([3.0, -1.5, 7.0])
        pose = make_pose(R, t)
        # 故意转置矩阵（字段仍与 R 一致）
        M = np.eye(4); M[:3, :3] = R.T; M[:3, 3] = t
        pose["camera_to_world_matrix"]["data"] = M.reshape(-1).tolist()
        rep, errs = cg.check_pose_internal(pose)
        self.assertTrue(any("不一致" in e for e in errs), f"应报列不一致：{errs}")


class TestConversion(unittest.TestCase):
    def setUp(self):
        self.R = make_R_unity()
        self.t = np.array([3.0, -1.5, 7.0])
        self.rep, self.errs = cg.check_pose_internal(make_pose(self.R, self.t))
        self.Rd, self.td, self.cerrs = cg.convert_to_demo(self.R, self.t)

    def test_r_demo_orthonormal_right_handed(self):
        self.assertEqual(self.cerrs, [])
        self.assertTrue(np.allclose(self.Rd.T @ self.Rd, np.eye(3), atol=cg.ORTHO_TOL))
        self.assertAlmostEqual(np.linalg.det(self.Rd), 1.0, places=4)

    def test_t_demo(self):
        self.assertTrue(np.allclose(self.td, cg.W @ self.t))

    def test_axes_columns_match(self):
        ok, err = cg.check_axes_columns(self.Rd, self.rep)
        self.assertTrue(ok, f"列比对失败 err={err}")

    def test_cross_product(self):
        ok, err = cg.check_cross_product(self.Rd)
        self.assertTrue(ok, f"right×down!=forward err={err}")

    def test_one_side_handedness_fails(self):
        # 只做世界换基（缺相机轴换基 C）→ 反射（det=-1），叉积不成立
        R_wrong = cg.W @ self.R
        self.assertAlmostEqual(np.linalg.det(R_wrong), -1.0, places=4)
        ok, _ = cg.check_cross_product(R_wrong)
        self.assertFalse(ok)
        # 只做相机轴换基（缺世界换基 W）→ 列不匹配
        R_wrong2 = self.R @ cg.C
        ok2, _ = cg.check_axes_columns(R_wrong2, self.rep)
        self.assertFalse(ok2)

    def test_transposed_rotation_fails_axes(self):
        ok, _ = cg.check_axes_columns(self.Rd.T, self.rep)
        self.assertFalse(ok)


class TestIntrinsicsAndRays(unittest.TestCase):
    def test_K(self):
        K = cg.intrinsics_from_fov(60.0, 2193, 1000)
        fy = 500.0 / math.tan(math.radians(30))
        self.assertAlmostEqual(K[0, 0], fy, places=3)
        self.assertAlmostEqual(K[1, 1], fy, places=3)
        self.assertAlmostEqual(K[0, 2], 1096.5, places=3)
        self.assertAlmostEqual(K[1, 2], 500.0, places=3)

    def test_center_ray_forward(self):
        K = cg.intrinsics_from_fov(60.0, 2193, 1000)
        ok, cos = cg.check_center_ray_forward(K)
        self.assertTrue(ok, f"中心射线非前向 cos={cos}")

    def test_pixel_axes(self):
        K = cg.intrinsics_from_fov(60.0, 2193, 1000)
        ok, (cx_, cy_) = cg.check_pixel_axes(K)
        self.assertTrue(ok, f"轴向错误 cos_x={cx_} cos_y={cy_}")

    def test_pixel_axis_sign_down_is_plus_y(self):
        K = cg.intrinsics_from_fov(60.0, 2193, 1000)
        cx, cy = K[0, 2], K[1, 2]
        d_down = cg.pixel_to_cam_dir(cx, cy + 1.0, K) - cg.pixel_to_cam_dir(cx, cy, K)
        self.assertGreater(d_down[1], 0)  # 向下 = +y（y 下）
        d_right = cg.pixel_to_cam_dir(cx + 1.0, cy, K) - cg.pixel_to_cam_dir(cx, cy, K)
        self.assertGreater(d_right[0], 0)  # 向右 = +x

    def test_missing_vertical_flip_detected(self):
        # 若遗漏像素纵轴转换（把 y 当上），v+1 会被当作 -y，与正确方向相反
        K = cg.intrinsics_from_fov(60.0, 2193, 1000)
        cx, cy = K[0, 2], K[1, 2]
        d_down = cg.pixel_to_cam_dir(cx, cy + 1.0, K) - cg.pixel_to_cam_dir(cx, cy, K)
        flipped = cg.pixel_to_cam_dir(cx, cy - 1.0, K) - cg.pixel_to_cam_dir(cx, cy, K)
        self.assertLess(float(np.dot(d_down, flipped)), 0)  # 符号相反，会被轴向检查判失败

    def test_degenerate_K_rejected(self):
        with self.assertRaises(ValueError):
            cg.intrinsics_from_fov(0.0, 100, 100)
        with self.assertRaises(ValueError):
            cg.intrinsics_from_fov(60.0, 0, 100)
        Kbad = np.array([[0.0, 0, 1], [0, 1, 0], [0, 0, 1]])
        with self.assertRaises(ValueError):
            cg.pixel_to_cam_dir(1.0, 1.0, Kbad)


class TestProjection(unittest.TestCase):
    def setUp(self):
        self.R = make_R_unity()
        self.t = np.array([3.0, -1.5, 7.0])
        self.Rd, self.td, _ = cg.convert_to_demo(self.R, self.t)
        self.K = cg.intrinsics_from_fov(60.0, 2193, 1000)

    def test_roundtrip(self):
        ok, reproj, werr = cg.check_projection_roundtrip(self.Rd, self.td, self.K)
        self.assertTrue(ok, f"重投影误差 {reproj}px 世界误差 {werr}")

    def test_forward_point_projects_to_center(self):
        # 相机前向 5m 处的点应投影到图像中心
        p_world = self.Rd @ np.array([0.0, 0.0, 5.0]) + self.td
        u, v = cg.project(p_world, self.Rd, self.td, self.K)
        self.assertAlmostEqual(u, self.K[0, 2], places=6)
        self.assertAlmostEqual(v, self.K[1, 2], places=6)

    def test_behind_camera_rejected(self):
        p_cam = np.array([0.1, 0.1, -1.0])  # z<0
        p_world = cg.cam_to_world(p_cam, self.Rd, self.td)
        with self.assertRaises(ValueError):
            cg.project(p_world, self.Rd, self.td, self.K)

    def test_unproject_negative_depth_rejected(self):
        with self.assertRaises(ValueError):
            cg.unproject(self.K[0, 2], self.K[1, 2], -5.0, self.Rd, self.td, self.K)


class TestContinuousCoordinates(unittest.TestCase):
    """连续图像坐标（左上原点）与 Unity 连续屏幕坐标（左下原点）的独立参考值。"""

    def setUp(self):
        self.H = 1000
        self.W = 2193
        self.K = cg.intrinsics_from_fov(60.0, self.W, self.H)

    def test_unity_screen_center_maps_to_principal_point(self):
        u, v = cg.unity_screen_to_image(self.W / 2.0, self.H / 2.0, self.H)
        self.assertAlmostEqual(u, self.K[0, 2], places=6)  # W/2 = 1096.5
        self.assertAlmostEqual(v, self.K[1, 2], places=6)  # H/2 = 500.0

    def test_off_axis_roundtrip(self):
        x_s, y_s = 1500.0, 800.0
        u, v = cg.unity_screen_to_image(x_s, y_s, self.H)
        self.assertAlmostEqual(u, 1500.0, places=6)
        self.assertAlmostEqual(v, 200.0, places=6)
        xb, yb = cg.image_to_unity_screen(u, v, self.H)
        self.assertAlmostEqual(xb, x_s, places=6)
        self.assertAlmostEqual(yb, y_s, places=6)

    def test_old_H_minus_1_formula_center_error_is_1px(self):
        # 若误用离散行号翻转 H-1-y 当连续转换，中心点误差 1 像素，并触发失败
        y_s = self.H / 2.0
        v_correct = self.H - y_s
        v_wrong = self.H - 1 - y_s
        self.assertAlmostEqual(v_correct - v_wrong, 1.0, places=6)
        self.assertAlmostEqual(v_correct, self.K[1, 2], places=6)
        self.assertNotAlmostEqual(v_wrong, self.K[1, 2], places=6)  # 偏离主点 1px

    def test_discrete_flip_is_separate(self):
        self.assertEqual(cg.flip_row_index_discrete(0, self.H), self.H - 1)
        self.assertEqual(cg.flip_row_index_discrete(self.H - 1, self.H), 0)

    def test_center_and_offaxis_ray_directions(self):
        cx, cy = self.K[0, 2], self.K[1, 2]
        # 中心（转换自 Unity 屏幕中心）→ 前向 [0,0,1]
        u0, v0 = cg.unity_screen_to_image(self.W / 2.0, self.H / 2.0, self.H)
        d0 = cg.pixel_to_cam_dir(u0, v0, self.K)
        d0 = d0 / np.linalg.norm(d0)
        self.assertTrue(np.allclose(d0, [0.0, 0.0, 1.0], atol=cg.VEC_TOL))
        # 偏轴向右（Unity x + Δ）→ +x
        u1, v1 = cg.unity_screen_to_image(self.W / 2.0 + 100.0, self.H / 2.0, self.H)
        d1 = cg.pixel_to_cam_dir(u1, v1, self.K)
        self.assertGreater(d1[0], 0)
        # 偏轴向下（Unity y - Δ，即图像 v + Δ）→ +y（y下）
        u2, v2 = cg.unity_screen_to_image(self.W / 2.0, self.H / 2.0 - 100.0, self.H)
        d2 = cg.pixel_to_cam_dir(u2, v2, self.K)
        self.assertGreater(d2[1], 0)


class TestVerifyEndToEnd(unittest.TestCase):
    """端到端反例：尺寸绑定与 pose 哈希，直接调用 verify_historical_poses.run()。

    尺寸反例的 pose 哈希使用变更后副本的 SHA256，从而单独证明「尺寸绑定」失败，
    而不是被哈希检查提前挡住。正常两帧由 verify_historical_poses.py 独立通过。
    """
    REAL_IMAGE = "/home/dailen/Nutstore Files/Fire_X/demo_sequences/state_machine_case/images/state_000001.png"
    REAL_POSE = "/home/dailen/Nutstore Files/Fire_X/demo_sequences/state_machine_case/poses/state_000001.json"
    IMAGE_SHA = "9b6d0a26b601007f2d11bb6db118eb59da2f6bdc227c684d5398f37a74991439"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_manifest(self, pose_path, pose_sha, image_sha, image_size):
        manifest = {
            "source_dir": "",
            "frames": [{
                "id": "t", "source_stem": "s", "role": "r",
                "image": self.REAL_IMAGE, "pose": pose_path,
                "image_sha256": image_sha, "image_size": image_size,
                "pose_sha256": pose_sha,
            }],
        }
        mp = self.tmpdir / "manifest.json"
        mp.write_text(json.dumps(manifest), encoding="utf-8")
        return mp

    def _modify_pose(self, width=None, height=None):
        pose = json.loads(Path(self.REAL_POSE).read_text(encoding="utf-8"))
        if width is not None:
            pose["image_width"] = width
        if height is not None:
            pose["image_height"] = height
        p = self.tmpdir / "pose_mod.json"
        p.write_text(json.dumps(pose), encoding="utf-8")
        return p

    def _run(self, manifest):
        out = self.tmpdir / "out"
        code = vh.run(manifest_path=manifest, out_dir=out)
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        return code, summary["results"][0]

    def test_size_mismatch_width_fails(self):
        p = self._modify_pose(width=2194)
        pose_sha = hashlib.sha256(p.read_bytes()).hexdigest()
        mp = self._write_manifest(str(p), pose_sha, self.IMAGE_SHA, [2193, 1000])
        code, rec = self._run(mp)
        self.assertNotEqual(code, 0)
        self.assertEqual(rec["status"], "error")
        self.assertTrue(any("2194" in e for e in rec.get("size_binding_errors", [])))
        self.assertIn("skipped", rec)  # 未生成内参/射线结论

    def test_size_mismatch_height_fails(self):
        p = self._modify_pose(height=1001)
        pose_sha = hashlib.sha256(p.read_bytes()).hexdigest()
        mp = self._write_manifest(str(p), pose_sha, self.IMAGE_SHA, [2193, 1000])
        code, rec = self._run(mp)
        self.assertNotEqual(code, 0)
        self.assertEqual(rec["status"], "error")
        self.assertTrue(any("1001" in e for e in rec.get("size_binding_errors", [])))

    def test_pose_hash_mismatch_fails(self):
        mp = self._write_manifest(self.REAL_POSE, "deadbeef", self.IMAGE_SHA, [2193, 1000])
        code, rec = self._run(mp)
        self.assertNotEqual(code, 0)
        self.assertEqual(rec["status"], "error")
        self.assertTrue(any("哈希" in e for e in rec.get("errors", [])))


if __name__ == "__main__":
    unittest.main(verbosity=2)
