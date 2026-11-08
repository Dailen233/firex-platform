#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D1 重建的替身回归：关键失败条件 + 纯函数索引对应。不加载真实模型、不占 GPU。

替身测试与真实 GPU 推理（reconstruct.py 实际运行）明确分开：本文件只用 numpy/torch 合成张量
+ unittest.mock 打桩，验证「失败条件真实生效」与「六视图展平索引一致」。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reconstruct as R

_MANIFEST_DIR = Path(__file__).resolve().parent
MANIFEST = _MANIFEST_DIR / "samples.json" if (_MANIFEST_DIR / "samples.json").exists() else _MANIFEST_DIR / "samples_cloud.json"
S = 6
H, W = 14, 28  # patch 对齐的小尺寸，便于合成


def synthetic_images():
    img = torch.zeros(S, 3, H, W)
    for s in range(S):
        img[s] = s / S
    return img


def synthetic_predictions(images, world_points_val=0.0, conf_val=1.0, pose_valid=True):
    """构造与 images 尺寸一致的预测 dict；world_points_val="grid" 时点云有非退化空间变化。"""
    sh = images.shape  # (S,3,H,W)
    if world_points_val == "grid":
        wp = torch.zeros(1, sh[0], sh[2], sh[3], 3)
        for s in range(sh[0]):
            for h in range(sh[2]):
                for w in range(sh[3]):
                    wp[0, s, h, w, 0] = h
                    wp[0, s, h, w, 1] = w
                    wp[0, s, h, w, 2] = s
    else:
        wp = torch.full((1, sh[0], sh[2], sh[3], 3), float(world_points_val))
    wpc = torch.full((1, sh[0], sh[2], sh[3]), float(conf_val))
    depth = torch.full((1, sh[0], sh[2], sh[3], 1), 1.0)
    depthc = torch.full((1, sh[0], sh[2], sh[3]), 1.0)
    pe = torch.zeros(1, sh[0], 9)
    if pose_valid:
        pe[..., 3] = 1.0  # 四元数 w=1（单位旋转）
        pe[..., 7] = 1.0  # fov_h
        pe[..., 8] = 1.0  # fov_w
    return {"world_points": wp, "world_points_conf": wpc, "depth": depth, "depth_conf": depthc, "pose_enc": pe}


def run_with_stub(manifest, pred, patch_write_fail=False, verify_ply_result=None):
    """打桩 load/preprocess/inference 后运行 run_config。返回 (code, meta, td:TemporaryDirectory)。"""
    img = synthetic_images()
    pre_meta = {"config": "A", "config_label": "official_crop", "loader_shape": tuple(img.shape),
                "final_shape": tuple(img.shape), "resize": {"applied": False}}
    infer_meta = {"infer_seconds": 0.0, "peak_allocated_bytes": 0, "peak_reserved_bytes": 0, "autocast_dtype": "stub"}
    load_ret = (None, {"repo_id": "stub", "snapshot": "stub", "snapshot_dir": "stub",
                       "weight_path": "stub", "weight_sha256_actual": "stub", "load_seconds": 0.0})
    with mock.patch.object(R, "load_model_offline", return_value=load_ret), \
         mock.patch.object(R, "preprocess_images", return_value=(img, pre_meta)), \
         mock.patch.object(R, "run_inference", return_value=(pred, infer_meta)), \
         mock.patch.object(R, "check_resources", return_value=(True, {"ok": True, "resources": {}, "checks": ["stub"]})), \
         mock.patch.object(R, "_probe_cuda", return_value=(True, {"torch_version": "stub", "cuda_device": "stub", "cuda_driver": (0, 0)})), \
         mock.patch.object(R, "sample_resources", return_value={"mem_available_kb": 20 * 1024 * 1024, "gpu_mem_free_mib": 8 * 1024}):
        writer = mock.patch.object(R, "write_ply_binary", side_effect=OSError("disk full")) if patch_write_fail \
            else mock.patch.object(R, "write_ply_binary", wraps=R.write_ply_binary)
        vp = mock.patch.object(R, "verify_ply", return_value=verify_ply_result) if verify_ply_result is not None \
            else mock.patch.object(R, "verify_ply", wraps=R.verify_ply)
        with writer, vp:
            td = tempfile.TemporaryDirectory()
            code = R.run_config(manifest, "A", Path(td.name))
            meta = json.loads((Path(td.name) / "meta.json").read_text(encoding="utf-8"))
            return code, meta, td


class TestInputValidation(unittest.TestCase):
    def test_hash_mismatch_fails_before_model_load(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["frames"][0]["image_sha256"] = "0" * 64
        with mock.patch.object(R, "check_resources", return_value=(True, {"ok": True})), \
             mock.patch.object(R, "sample_resources", return_value={"mem_available_kb": 20 * 1024 * 1024, "gpu_mem_free_mib": 8 * 1024}), \
             mock.patch.object(R, "_probe_cuda", return_value=(True, {"torch_version": "stub"})), \
             mock.patch.object(R, "load_model_offline") as spy:
            with tempfile.TemporaryDirectory() as d:
                code = R.run_config(manifest, "A", Path(d))
        self.assertEqual(code, R.EXIT_INPUT)
        spy.assert_not_called()

    def test_duplicate_input_detected(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        # 让第 2 帧与第 1 帧指向同一图像文件（相同路径+哈希），触发重复检测
        manifest["frames"][1]["image"] = manifest["frames"][0]["image"]
        manifest["frames"][1]["image_sha256"] = manifest["frames"][0]["image_sha256"]
        errors = R.verify_frames(manifest["frames"])
        self.assertTrue(any("重复" in e for e in errors))

    def test_pose_hash_mismatch_detected(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["frames"][0]["pose_sha256"] = "0" * 64
        errors = R.verify_frames(manifest["frames"])
        self.assertTrue(any("pose 哈希不符" in e for e in errors))


class TestFlattenIndex(unittest.TestCase):
    def test_point_color_index_correspondence(self):
        img = torch.zeros(2, 3, 3, 4)
        for s in range(2):
            for h in range(3):
                for w in range(4):
                    img[s, 0, h, w] = (s * 12 + h * 4 + w) / 24
        wp = torch.zeros(2, 3, 4, 3)
        pts, cols = R.build_points_colors(wp, img)
        self.assertEqual(pts.shape, (24, 3))
        self.assertEqual(cols.shape, (24, 3))
        vals = np.array([s * 12 + h * 4 + w for s in range(2) for h in range(3) for w in range(4)])
        self.assertTrue(np.array_equal(np.round(vals / 24 * 255).astype(np.uint8), cols[:, 0]))

    def test_conf_median_mask_top_half(self):
        conf = np.array([1.0, 2.0, 3.0, 4.0])
        fin = np.ones(4, dtype=bool)
        keep, cutoff = R.conf_median_mask(conf, fin)
        self.assertAlmostEqual(cutoff, 2.5)
        self.assertEqual(keep.tolist(), [False, False, True, True])


class TestRunConfigFailures(unittest.TestCase):
    def test_wrong_output_shape_fails(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        pred = synthetic_predictions(synthetic_images())
        pred["world_points"] = torch.zeros(1, S, 7, W, 3)
        code, meta, td = run_with_stub(manifest, pred)
        try:
            self.assertEqual(code, R.EXIT_OUTPUT)
            self.assertTrue(any("形状" in e for e in meta["errors"]))
        finally:
            td.cleanup()

    def test_missing_key_fails(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        pred = synthetic_predictions(synthetic_images())
        del pred["world_points"]
        code, meta, td = run_with_stub(manifest, pred)
        try:
            self.assertEqual(code, R.EXIT_OUTPUT)
            self.assertTrue(any("缺键" in e for e in meta["errors"]))
        finally:
            td.cleanup()

    def test_no_valid_geometry_fails(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        pred = synthetic_predictions(synthetic_images(), world_points_val=float("nan"))
        code, meta, td = run_with_stub(manifest, pred)
        try:
            self.assertEqual(code, R.EXIT_OUTPUT)
        finally:
            td.cleanup()

    def test_file_write_failure_not_success(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        pred = synthetic_predictions(synthetic_images(), world_points_val="grid")
        code, meta, td = run_with_stub(manifest, pred, patch_write_fail=True)
        try:
            self.assertEqual(code, R.EXIT_OUTPUT)
        finally:
            td.cleanup()

    def test_success_covers_all_six_views(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        pred = synthetic_predictions(synthetic_images(), world_points_val="grid")
        code, meta, td = run_with_stub(manifest, pred)
        try:
            self.assertEqual(code, R.EXIT_OK)
            self.assertEqual(meta["outputs"]["world_points_shape"], [S, H, W, 3])
            self.assertEqual(set(meta["outputs"]["per_view"].keys()), {"case6_0%d" % i for i in range(1, 7)})
            self.assertTrue((Path(td.name) / "aggregated_points.ply").exists())
        finally:
            td.cleanup()


class TestPlyRoundtrip(unittest.TestCase):
    def test_ply_write_and_reread(self):
        pts = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [2.0, 0.0, 1.0]], dtype=np.float32)
        cols = np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], dtype=np.uint8)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.ply"
            R.write_ply_binary(p, pts, cols)
            rec = R.verify_ply(p, 3)
            self.assertTrue(rec["ok"], rec)
            self.assertEqual(rec["points"], 3)
            self.assertTrue(rec["non_degenerate"])


class TestRecoveryGuards(unittest.TestCase):
    """中断恢复与审核修复的守卫测试。"""

    def test_resource_insufficient_no_heavy_import_no_model_load(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        with mock.patch.object(R, "check_resources", return_value=(False, {"ok": False, "resources": {}, "checks": ["MemAvailable 不足"]})), \
             mock.patch.object(R, "sample_resources", return_value={"mem_available_kb": 1}), \
             mock.patch.object(R, "_ensure_torch") as spy_torch, \
             mock.patch.object(R, "load_model_offline") as spy_model:
            td = tempfile.TemporaryDirectory()
            try:
                code = R.run_config(manifest, "A", Path(td.name))
                meta = json.loads((Path(td.name) / "meta.json").read_text(encoding="utf-8"))
                self.assertEqual(code, R.EXIT_RESOURCE)
                self.assertEqual(meta["status"], "resource_failed")
                self.assertNotIn("torch_version", meta)  # 未进入 torch 导入
                spy_torch.assert_not_called()  # 重型导入 0 次
                spy_model.assert_not_called()  # 模型加载 0 次
            finally:
                td.cleanup()

    def test_early_stage_persisted_on_error(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        with mock.patch.object(R, "check_resources", return_value=(True, {"ok": True})), \
             mock.patch.object(R, "sample_resources", return_value={"mem_available_kb": 20 * 1024 * 1024, "gpu_mem_free_mib": 8 * 1024}), \
             mock.patch.object(R, "_probe_cuda", return_value=(True, {"torch_version": "stub"})), \
             mock.patch.object(R, "load_model_offline", side_effect=RuntimeError("boom")):
            td = tempfile.TemporaryDirectory()
            try:
                code = R.run_config(manifest, "A", Path(td.name))
                meta = json.loads((Path(td.name) / "meta.json").read_text(encoding="utf-8"))
                self.assertEqual(code, R.EXIT_ERR)
                self.assertIn("stage", meta)
                self.assertEqual(meta["status"], "error")
                self.assertIn("run_id", meta)
            finally:
                td.cleanup()

    def test_auto_refuses_without_heavy_import(self):
        with mock.patch.object(sys, "argv", ["reconstruct.py", "--auto"]), \
             mock.patch.object(R, "_ensure_torch") as spy_torch, \
             mock.patch.object(R, "load_manifest") as spy_manifest:
            code = R.main()
        self.assertEqual(code, R.EXIT_ERR)
        spy_torch.assert_not_called()
        spy_manifest.assert_not_called()

    def test_nonempty_dir_without_meta_rejected(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        td = tempfile.TemporaryDirectory()
        try:
            d = Path(td.name)
            old = d / "predictions.npz"
            old.write_bytes(b"old-artifact-bytes")
            with mock.patch.object(R, "load_model_offline") as spy:
                code = R.run_config(manifest, "A", d)
            self.assertEqual(code, R.EXIT_EXISTS)
            self.assertEqual(old.read_bytes(), b"old-artifact-bytes")  # 旧文件字节不变
            spy.assert_not_called()
        finally:
            td.cleanup()

    def test_offline_env_forced(self):
        os.environ["HF_HUB_OFFLINE"] = "0"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "0"
        R._enforce_offline()
        self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")
        self.assertEqual(os.environ["HF_HUB_DISABLE_TELEMETRY"], "1")


class TestReviewFixes(unittest.TestCase):
    """针对审核意见的反例测试。"""

    def test_conf_mask_excludes_nan_coords_high_conf(self):
        conf = np.array([1.0, 5.0, 5.0, 5.0])
        fin = np.array([True, False, False, True])  # 索引 1,2 坐标无效但置信度高
        keep, cutoff = R.conf_median_mask(conf, fin)
        self.assertAlmostEqual(cutoff, 3.0)
        self.assertEqual(keep.tolist(), [False, False, False, True])  # 高置信 NaN 坐标被排除

    def test_move_input_to_device_consistent(self):
        model = mock.MagicMock()
        model.parameters.return_value = iter([torch.nn.Parameter(torch.zeros(1))])  # CPU
        images = torch.zeros(2, 3, 4, 4)
        moved = R._move_input_to_device(images, model, "cpu")
        self.assertEqual(str(moved.device), "cpu")

    def test_move_input_device_mismatch_raises(self):
        model = mock.MagicMock()
        model.parameters.return_value = iter([torch.nn.Parameter(torch.empty(1, device="meta"))])
        with self.assertRaises(RuntimeError):
            R._move_input_to_device(torch.zeros(1), model, "cpu")

    def test_ply_verify_failure_is_fatal(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        pred = synthetic_predictions(synthetic_images(), world_points_val="grid")
        code, meta, td = run_with_stub(manifest, pred, verify_ply_result={"ok": False, "error": "点数不符"})
        try:
            self.assertEqual(code, R.EXIT_OUTPUT)
            self.assertEqual(meta["status"], "export_failed")
        finally:
            td.cleanup()

    def test_load_binds_verified_snapshot_dir(self):
        import hashlib as _h
        dummy = b"fake-weights"
        sha = _h.sha256(dummy).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            hf = Path(td) / "hf"
            snap = hf / "hub" / "models--facebook--VGGT-1B" / "snapshots" / "abc123"
            snap.mkdir(parents=True)
            (snap / "model.safetensors").write_bytes(dummy)
            (snap / "config.json").write_text('{"img_size": 518}')
            manifest = {"model": {"repo_id": "facebook/VGGT-1B", "snapshot": "abc123", "weight_sha256": sha}}
            with mock.patch.dict(os.environ, {"HF_HOME": str(hf)}):
                with mock.patch("vggt.models.vggt.VGGT.from_pretrained", return_value=mock.MagicMock()) as fp:
                    model, meta = R.load_model_offline("cuda", manifest)
            fp.assert_called_once()
            called = fp.call_args[0][0]
            self.assertEqual(called, str(snap))
            self.assertIn("snapshots", called)
            self.assertNotEqual(called, "facebook/VGGT-1B")


class TestCloudMigration(unittest.TestCase):
    """云端迁移适配的反例测试（路径解析、容器限额、缺文件）。"""

    def test_resolve_path_absolute_and_relative(self):
        self.assertEqual(str(R.resolve_path("/abs/x.png")), "/abs/x.png")
        self.assertEqual(R.resolve_path("frames/a.png"), R.PACKAGE_ROOT / "frames" / "a.png")

    def test_effective_mem_budget_takes_min(self):
        # 容器限额更小 → 取容器剩余
        self.assertEqual(
            R._effective_mem_available_kib({"memavailable_kb": 20 * 1024 * 1024,
                                            "cgroup_memory_limit_bytes": 5 * (1024 ** 3),
                                            "cgroup_memory_usage_bytes": 0}),
            5 * 1024 * 1024)
        # MemAvailable 更小 → 取 MemAvailable
        self.assertEqual(
            R._effective_mem_available_kib({"memavailable_kb": 5 * 1024 * 1024,
                                            "cgroup_memory_limit_bytes": 30 * (1024 ** 3),
                                            "cgroup_memory_usage_bytes": 10 * (1024 ** 3)}),
            5 * 1024 * 1024)
        # 无 cgroup → 取 MemAvailable
        self.assertEqual(R._effective_mem_available_kib({"memavailable_kb": 8 * 1024 * 1024}), 8 * 1024 * 1024)
        # 无任何 → None
        self.assertIsNone(R._effective_mem_available_kib({}))
        # cgroup 无限制哨兵值 → 忽略容器限额，取 MemAvailable
        self.assertEqual(
            R._effective_mem_available_kib({"memavailable_kb": 8 * 1024 * 1024,
                                            "cgroup_memory_limit_bytes": 9223372036854771712}),
            8 * 1024 * 1024)
        # 有限限额但 usage 缺失 → None（无法确定剩余，显式失败）
        self.assertIsNone(
            R._effective_mem_available_kib({"memavailable_kb": 20 * 1024 * 1024,
                                            "cgroup_memory_limit_bytes": 30 * (1024 ** 3)}))

    def test_container_limit_insufficient_blocks_heavy_import(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        res = {"memavailable_kb": 20 * 1024 * 1024,  # 系统 MemAvailable 充足
               "cgroup_memory_limit_bytes": 5 * (1024 ** 3),  # 但容器限额 5GiB
               "cgroup_memory_usage_bytes": 0,
               "gpu_mem_free_mib": 8 * 1024}
        with mock.patch.object(R, "sample_resources", return_value=res), \
             mock.patch.object(R, "_ensure_torch") as spy_torch, \
             mock.patch.object(R, "load_model_offline") as spy_model:
            td = tempfile.TemporaryDirectory()
            try:
                code = R.run_config(manifest, "A", Path(td.name))
                meta = json.loads((Path(td.name) / "meta.json").read_text(encoding="utf-8"))
                self.assertEqual(code, R.EXIT_RESOURCE)
                self.assertEqual(meta["status"], "resource_failed")
                spy_torch.assert_not_called()
                spy_model.assert_not_called()
            finally:
                td.cleanup()

    def test_container_limit_missing_usage_blocks_heavy_import(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        res = {"memavailable_kb": 20 * 1024 * 1024,  # 系统 MemAvailable 20GiB 充足
               "cgroup_memory_limit_bytes": 30 * (1024 ** 3),  # 有限限额 30GiB
               # 缺 cgroup_memory_usage_bytes → 无法确定剩余
               "gpu_mem_free_mib": 8 * 1024}
        with mock.patch.object(R, "sample_resources", return_value=res), \
             mock.patch.object(R, "_ensure_torch") as spy_torch, \
             mock.patch.object(R, "load_model_offline") as spy_model:
            td = tempfile.TemporaryDirectory()
            try:
                code = R.run_config(manifest, "A", Path(td.name))
                meta = json.loads((Path(td.name) / "meta.json").read_text(encoding="utf-8"))
                self.assertEqual(code, R.EXIT_RESOURCE)
                self.assertEqual(meta["status"], "resource_failed")
                spy_torch.assert_not_called()
                spy_model.assert_not_called()
            finally:
                td.cleanup()

    def test_missing_file_blocks_model_load(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["frames"][0]["image"] = "/nonexistent/missing.png"
        with mock.patch.object(R, "check_resources", return_value=(True, {"ok": True})), \
             mock.patch.object(R, "sample_resources", return_value={"memavailable_kb": 20 * 1024 * 1024, "gpu_mem_free_mib": 8 * 1024}), \
             mock.patch.object(R, "_probe_cuda", return_value=(True, {"torch_version": "stub"})), \
             mock.patch.object(R, "load_model_offline") as spy:
            td = tempfile.TemporaryDirectory()
            try:
                code = R.run_config(manifest, "A", Path(td.name))
                meta = json.loads((Path(td.name) / "meta.json").read_text(encoding="utf-8"))
                self.assertEqual(code, R.EXIT_INPUT)
                self.assertEqual(meta["status"], "input_failed")
                spy.assert_not_called()
            finally:
                td.cleanup()

    def test_relative_paths_resolve_against_package_not_cwd(self):
        from PIL import Image as PILImage
        import hashlib as _h
        with tempfile.TemporaryDirectory() as td:
            pkg = Path(td)
            (pkg / "frames").mkdir()
            (pkg / "poses").mkdir()
            frames = []
            for i, color in (("a", (255, 0, 0)), ("b", (0, 255, 0))):
                img = pkg / "frames" / f"{i}.png"
                pose = pkg / "poses" / f"{i}.json"
                PILImage.new("RGB", (1, 1), color).save(img)
                pose.write_text('{"x": 0}', encoding="utf-8")
                frames.append({"id": i, "image": f"frames/{i}.png",
                               "image_sha256": _h.sha256(img.read_bytes()).hexdigest(),
                               "image_size": [1, 1],
                               "pose": f"poses/{i}.json",
                               "pose_sha256": _h.sha256(pose.read_bytes()).hexdigest()})
            with mock.patch.object(R, "PACKAGE_ROOT", pkg):
                old = os.getcwd()
                try:
                    os.chdir("/")
                    errs = R.verify_frames(frames)
                finally:
                    os.chdir(old)
            self.assertEqual(errs, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
