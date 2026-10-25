#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C1 run_detection.py 的针对性回归（受控替身 + monkeypatch，不跑真实模型推理）。

覆盖（全部为替身/纯函数，区别于真实模型推理）：
- 纯函数：normalize_names / validate_box_records（非有限、负面积、越界、非法置信度、非法类别）/ check_weight_meta。
- process_result：正常结果与合法零检测成功；orig_shape 不符、非法框、叠加图保存失败均失败。
- run()：权重哈希不符 → 非零退出，且加载模型调用次数为 0（进而 predict 0 次）。

仅用环境已有的 numpy/cv2 + 标准库 unittest.mock，不新增依赖；不使用真实权重、不跑真实推理。

运行（仓库根）：
    /home/dailen/vggt/vggt-env/bin/python experiments/c1-detection/test_run_detection.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_detection as rd


class FakeBoxes:
    def __init__(self, xyxy, conf, cls):
        self.xyxy = np.asarray(xyxy, dtype=float)
        self.conf = np.asarray(conf, dtype=float)
        self.cls = np.asarray(cls, dtype=float)

    def __len__(self):
        return len(self.xyxy)


class FakeResult:
    def __init__(self, orig_shape, boxes=None, speed=None, plot_arr=None):
        self.orig_shape = orig_shape
        self.boxes = boxes
        self.speed = speed or {}
        self._plot = plot_arr

    def plot(self):
        return self._plot


def make_result(H=100, W=200, n_fire=1):
    if n_fire > 0:
        boxes = FakeBoxes([[10.0, 20.0, 30.0, 40.0]], [0.5], [0])
    else:
        boxes = FakeBoxes([], [], [])
    plot = np.zeros((H, W, 3), dtype=np.uint8)
    return FakeResult((H, W), boxes=boxes, plot_arr=plot)


class TestPureFunctions(unittest.TestCase):
    def test_normalize_names(self):
        self.assertEqual(rd.normalize_names({"0": "fire"}), {0: "fire"})
        self.assertEqual(rd.normalize_names({1: "smoke"}), {1: "smoke"})

    def test_validate_boxes_ok(self):
        boxes = [{"class_id": 0, "conf": 0.5, "xyxy": [10.0, 20.0, 30.0, 40.0]}]
        self.assertEqual(rd.validate_box_records(boxes, {0: "fire"}, 100, 200), [])

    def test_validate_boxes_nonfinite(self):
        boxes = [{"class_id": 0, "conf": float("nan"), "xyxy": [10.0, 20.0, 30.0, 40.0]}]
        self.assertTrue(rd.validate_box_records(boxes, {0: "fire"}, 100, 200))

    def test_validate_boxes_negative_area(self):
        boxes = [{"class_id": 0, "conf": 0.5, "xyxy": [30.0, 20.0, 10.0, 40.0]}]
        self.assertTrue(rd.validate_box_records(boxes, {0: "fire"}, 100, 200))

    def test_validate_boxes_out_of_bounds(self):
        boxes = [{"class_id": 0, "conf": 0.5, "xyxy": [10.0, 20.0, 300.0, 40.0]}]
        self.assertTrue(rd.validate_box_records(boxes, {0: "fire"}, 100, 200))

    def test_validate_boxes_bad_conf(self):
        boxes = [{"class_id": 0, "conf": 1.5, "xyxy": [10.0, 20.0, 30.0, 40.0]}]
        self.assertTrue(rd.validate_box_records(boxes, {0: "fire"}, 100, 200))

    def test_validate_boxes_bad_class(self):
        boxes = [{"class_id": 9, "conf": 0.5, "xyxy": [10.0, 20.0, 30.0, 40.0]}]
        self.assertTrue(rd.validate_box_records(boxes, {0: "fire"}, 100, 200))

    def test_check_weight_meta_sha_mismatch(self):
        errs = rd.check_weight_meta("deadbeef", "detect", {0: "fire"},
                                     {"sha256": "abc", "task": "detect", "names": {"0": "fire"}})
        self.assertTrue(any("SHA256" in e for e in errs))

    def test_check_weight_meta_names_mismatch(self):
        errs = rd.check_weight_meta("abc", "detect", {0: "smoke"},
                                     {"sha256": "abc", "task": "detect", "names": {"0": "fire"}})
        self.assertTrue(any("类别映射" in e for e in errs))


class TestProcessResult(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.tmp.name)
        self.names = {0: "fire"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_normal(self):
        res = make_result(100, 200, n_fire=1)
        rec = rd.process_result(res, "x", "sha", "sha", 200, 100, self.names, self.out_dir)
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(rec["num_raw"], 1)
        self.assertEqual(rec["num_fire"], 1)
        self.assertTrue(rec["overlay_saved"])

    def test_zero_detection(self):
        res = make_result(100, 200, n_fire=0)
        rec = rd.process_result(res, "x", "sha", "sha", 200, 100, self.names, self.out_dir)
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(rec["num_raw"], 0)
        self.assertEqual(rec["raw_boxes"], [])

    def test_orig_shape_mismatch(self):
        res = make_result(90, 200, n_fire=1)  # orig_shape (90,200) != 原图 (100,200)
        rec = rd.process_result(res, "x", "sha", "sha", 200, 100, self.names, self.out_dir)
        self.assertEqual(rec["status"], "error")
        self.assertTrue(any("orig_shape" in e for e in rec["errors"]))

    def test_bad_box(self):
        res = FakeResult((100, 200),
                         boxes=FakeBoxes([[10.0, 20.0, 300.0, 40.0]], [0.5], [0]),
                         plot_arr=np.zeros((100, 200, 3), dtype=np.uint8))
        rec = rd.process_result(res, "x", "sha", "sha", 200, 100, self.names, self.out_dir)
        self.assertEqual(rec["status"], "error")
        self.assertTrue(any("越界" in e for e in rec["errors"]))

    def test_overlay_save_failure(self):
        res = make_result(100, 200, n_fire=1)
        with mock.patch("cv2.imwrite", return_value=False):
            rec = rd.process_result(res, "x", "sha", "sha", 200, 100, self.names, self.out_dir)
        self.assertEqual(rec["status"], "error")
        self.assertTrue(any("叠加图写入失败" in e for e in rec["errors"]))


class TestRunWeightHash(unittest.TestCase):
    def test_weight_hash_mismatch_no_predict(self):
        manifest = {
            "weights": {"sha256": "EXPECTED", "task": "detect", "names": {"0": "fire"}},
            "samples": [],
        }
        with tempfile.TemporaryDirectory() as d:
            mp = Path(d) / "manifest.json"
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            calls = {"load": 0}

            def fake_load(p):
                calls["load"] += 1
                raise AssertionError("权重不符时不应加载模型")

            with mock.patch.object(rd, "sha256_file", return_value="WRONG"), \
                 mock.patch.object(rd, "_load_model", side_effect=fake_load):
                code = rd.run(manifest_path=mp, out_dir=Path(d) / "out", weights_path="/fake/best.pt")

            self.assertNotEqual(code, 0)
            self.assertEqual(calls["load"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
