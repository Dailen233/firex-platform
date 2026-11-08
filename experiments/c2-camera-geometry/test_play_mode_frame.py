#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E3.2 合成样本自验（层级 1：合成数学；真实 Play Mode 采集样本标待验）。

覆盖：
- 合成样本端到端：前向投影（demo 手性路径）与 Unity 直接投影一致；反向射线（像素→GLB 地形求交）
  恢复到顶点独立参考位置；X 反射（E3.1 轴映射）在非中心点生效。
- 反例必须失败：资产不符、尺寸非法、相机反射（det=-1）、当帧 mesh_local_to_world 非刚体、
  轴映射被改成恒等（X 反射缺失）。

运行（仓库根）：
    /home/dailen/vggt/vggt-env/bin/python experiments/c2-camera-geometry/test_play_mode_frame.py
"""
from __future__ import annotations

import copy
import json
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import camera_geometry as cg
import play_mode_frame as pmf
import make_synthetic_sample as ms

OUT_DIR = Path(__file__).resolve().parents[2] / "runtime-data" / "e3-synthetic"


def _load_sample():
    manifest = json.loads((OUT_DIR / "manifest.json").read_text(encoding="utf-8"))
    frame = json.loads((OUT_DIR / "play_001.json").read_text(encoding="utf-8"))
    terrain = manifest["terrain"]
    vertices = np.asarray(terrain["vertices"], dtype=np.float64)
    triangles = np.asarray(terrain["triangles"], dtype=np.int64)
    image = OUT_DIR / "play_001.png"
    image_sha = manifest["frames"][0]["image_sha256"]
    return frame, vertices, triangles, image, image_sha


class TestSyntheticEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ms.main()  # 生成/覆盖合成样本

    def test_end_to_end_ok(self):
        frame, vertices, triangles, image, image_sha = _load_sample()
        rec = pmf.verify_frame(frame, vertices, triangles, image_path=image, image_sha256=image_sha)
        self.assertEqual(rec["status"], "ok", rec.get("errors"))
        for p in rec["points"]:
            self.assertTrue(p["ok"], p["errors"])
            # 两条路径数学等价，仅浮点运算顺序不同：像素误差 ~1e-5 px、米制误差 ~1e-3 m
            self.assertLess(p["pixel_error_px"], 1e-3)
            self.assertLess(p["metric_error_m"], 1e-2)

    def test_x_reversal_non_center(self):
        """非中心点 X 反射：mesh_local X=-2500 → GLB X=+2500，且反向射线命中该参考位置。"""
        frame, vertices, triangles, image, image_sha = _load_sample()
        p = next(x for x in frame["points"] if x["point_id"] == "P_xpos")
        ml_x = p["unity_mesh_local_xyz"][0]
        glb_x = p["glb_reference_xyz"][0]
        self.assertAlmostEqual(ml_x, -2500.0, places=5)
        self.assertAlmostEqual(glb_x, 2500.0, places=5)
        self.assertAlmostEqual(glb_x, -ml_x, places=5)  # X 反向成立
        rec = pmf.verify_frame(frame, vertices, triangles, image_path=image, image_sha256=image_sha)
        hit = next(x for x in rec["points"] if x["point_id"] == "P_xpos")["ray_hit_xyz"]
        self.assertLess(np.linalg.norm(np.asarray(hit) - np.asarray(p["glb_reference_xyz"])), 1e-2)


class TestRejections(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ms.main()

    def _verify(self, mutate):
        frame, vertices, triangles, image, image_sha = _load_sample()
        frame = copy.deepcopy(frame)
        mutate(frame)
        return pmf.verify_frame(frame, vertices, triangles, image_path=image, image_sha256=image_sha)

    def test_asset_glb_sha_mismatch(self):
        rec = self._verify(lambda f: f.update(glb_sha256="deadbeef" * 8))
        self.assertEqual(rec["status"], "error")
        self.assertTrue(any("glb_sha256" in e for e in rec["errors"]))

    def test_asset_coordinate_frame_mismatch(self):
        rec = self._verify(lambda f: f.update(coordinate_frame_id="OTHER_FRAME_v9"))
        self.assertEqual(rec["status"], "error")
        self.assertTrue(any("coordinate_frame_id" in e for e in rec["errors"]))

    def test_size_not_positive_int(self):
        rec = self._verify(lambda f: f.update(image_width=-1))
        self.assertEqual(rec["status"], "error")
        self.assertTrue(any("image_width" in e for e in rec["errors"]))

    def test_camera_reflection_rejected(self):
        def mutate(f):
            M = np.asarray(f["camera_to_world_matrix"]["data"], dtype=np.float64).reshape(4, 4)
            M[:3, :3] *= -1.0  # det(-R)= -det(R)，反射被拒
            f["camera_to_world_matrix"]["data"] = M.reshape(-1).tolist()
        rec = self._verify(mutate)
        self.assertEqual(rec["status"], "error")

    def test_mesh_local_to_world_non_rigid(self):
        def mutate(f):
            M = np.asarray(f["mesh_local_to_world"], dtype=np.float64).reshape(4, 4)
            M[0, 0] *= 2.0  # 引入缩放，非刚体
            f["mesh_local_to_world"] = M.reshape(-1).tolist()
        rec = self._verify(mutate)
        self.assertEqual(rec["status"], "error")

    def test_axis_map_identity_breaks_x(self):
        rec = self._verify(lambda f: f.update(axis_map_glb_from_mesh_local=[1, 0, 0, 0, 1, 0, 0, 0, 1]))
        self.assertEqual(rec["status"], "error")
        self.assertTrue(any("axis_map" in e for e in rec["errors"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
