#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C1：小样本离线二维火焰检测（已有环境 + 自训练权重，含严格校验）。

约束：
- 仅加载本地明确指定的权重（绝对路径），不联网、不下载、不安装/升级依赖。
- 不调用旧算法仓库的 inference.load_model（其缓存失败会联网下载 VGGT-1B）。
- 不读取真值来选框/调参/决定输出；samples.json 的 expected_label 仅用于结果复核。
- 本轮不做三角化、火区轮廓、双江口配准或后端算法提供者接入。

严格校验（本轮新增，校验失败即真实失败）：
- 首次 predict 前强制核对本地权重 SHA256 与清单一致，并核对 task、规范化类别映射；
  权重哈希不符则不加载模型、不调用 predict；task/names 不符则已加载模型（用于读取 task/names）但不调用 predict。
  两种情况均非零退出，且不下载或切换模型。
- 每图必须通过：输入哈希、orig_shape 与原图尺寸一致、所有框及置信度有限、
  置信度 ∈ [0,1]、框正面积且在原图范围、类别 ID 可解析、叠加图写回后尺寸与原图一致。
- 任一失败 → 该图 status=error，整体退出码非零；合法零检测仍为 ok（空列表），不算失败。
- JSON 以 allow_nan=False 写出，绝不写入 NaN/Infinity；校验错误不会转成“未检出”。

运行（仓库根）：
    /home/dailen/vggt/vggt-env/bin/python experiments/c1-detection/run_detection.py

固定参数：device=cpu, imgsz=640, conf=0.25, iou=0.45。
输出目录：runtime-data/c1-final/（本轮独立目录，gitignore 覆盖）。

参考（按已安装 Ultralytics 8.4.19 实际核对）：predict() 参数经 **kwargs；Results.orig_shape(H,W)/boxes/plot()；Boxes.xyxy 为原图像素坐标。
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import sys
import time
import traceback
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = Path(__file__).resolve().parent / "samples.json"
OUT_DIR = REPO_ROOT / "runtime-data" / "c1-final"

WEIGHTS = "/home/dailen/vggt/runs/detect/train_full_v1/weights/best.pt"
DEVICE = "cpu"
IMGSZ = 640
CONF = 0.25
IOU = 0.45

FIRE_LABELS = {"fire", "flame", "fires"}


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _to_numpy(x) -> np.ndarray:
    if hasattr(x, "detach"):
        x = x.detach().cpu()
    return np.asarray(x, dtype=np.float64)


def normalize_names(names) -> dict:
    out = {}
    for k, v in (names or {}).items():
        out[int(k)] = str(v)
    return out


def check_weight_meta(actual_sha, task, names, declared) -> list:
    """核对权重哈希、task 与规范化类别映射；返回错误列表（空=通过）。"""
    errors = []
    declared = declared or {}
    if declared.get("sha256") and actual_sha != declared["sha256"]:
        errors.append(f"权重 SHA256 不符：期望 {declared['sha256']} 实际 {actual_sha}")
    if declared.get("task") and task != declared["task"]:
        errors.append(f"模型 task 不符：期望 {declared['task']} 实际 {task}")
    norm = normalize_names(names)
    if not norm:
        errors.append("模型无有效类别映射")
    if declared.get("names"):
        exp = normalize_names(declared["names"])
        if exp and norm != exp:
            errors.append(f"类别映射不符：期望 {exp} 实际 {norm}")
    return errors


def validate_box_records(boxes, names, w, h) -> list:
    """纯校验：每框有限、置信度∈[0,1]、正面积、在界、类别可解析。返回错误列表。"""
    errors = []
    for i, b in enumerate(boxes):
        x1, y1, x2, y2 = b["xyxy"]
        conf = b["conf"]
        cid = b["class_id"]
        vals = [x1, y1, x2, y2, conf]
        if not all(math.isfinite(float(v)) for v in vals):
            errors.append(f"box[{i}] 含非有限值 xyxy={b['xyxy']} conf={conf}")
            continue
        if not (0.0 <= conf <= 1.0):
            errors.append(f"box[{i}] 置信度 {conf} 不在 [0,1]")
        if not (x2 > x1 and y2 > y1):
            errors.append(f"box[{i}] 非正面积 {b['xyxy']}")
        if not (0 <= x1 < w and 0 <= y1 < h and 0 < x2 <= w and 0 < y2 <= h):
            errors.append(f"box[{i}] 越界 {b['xyxy']} 超出 {w}x{h}")
        if cid not in names:
            errors.append(f"box[{i}] 类别 ID {cid} 无法解析")
    return errors


def extract_boxes(boxes, names, w, h):
    """把 torch/numpy 的 Boxes 转成字典列表并校验。返回 (raw_boxes, errors)。"""
    raw_boxes = []
    errors = []
    if boxes is None or len(boxes) == 0:
        return raw_boxes, errors
    xyxy = _to_numpy(boxes.xyxy)
    confs = _to_numpy(boxes.conf)
    clss = _to_numpy(boxes.cls)
    for i in range(len(xyxy)):
        x1, y1, x2, y2 = [float(v) for v in xyxy[i]]
        conf = float(confs[i])
        cls_id = int(clss[i])
        raw_boxes.append({
            "class_id": cls_id,
            "class_name": names.get(cls_id, str(cls_id)),
            "conf": conf,
            "xyxy": [x1, y1, x2, y2],
        })
    errors.extend(validate_box_records(raw_boxes, names, w, h))
    return raw_boxes, errors


def write_overlay(res, out_png):
    if res.orig_shape is None:
        return "orig_shape 缺失，无法核验叠加图尺寸"
    annot = res.plot()
    if annot is None:
        return "plot() 返回空"
    if not cv2.imwrite(str(out_png), annot):
        return "叠加图写入失败"
    if not out_png.exists() or out_png.stat().st_size == 0:
        return "叠加图文件为空"
    check = cv2.imread(str(out_png))
    if check is None:
        return "叠加图重新解码失败"
    h2, w2 = check.shape[:2]
    oh, ow = res.orig_shape
    if (h2, w2) != (oh, ow):
        return f"叠加图尺寸 {w2}x{h2} 与 orig_shape {ow}x{oh} 不一致"
    return None


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def _jsonify_box(b):
    x1, y1, x2, y2 = b["xyxy"]
    return {
        "class_id": b["class_id"],
        "class_name": b["class_name"],
        "conf": round(float(b["conf"]), 6),
        "xyxy": [round(x1, 3), round(y1, 3), round(x2, 3), round(y2, 3)],
    }


def _safe_num(v):
    f = float(v)
    return f if math.isfinite(f) else str(v)


def _sanitize_boxes(boxes):
    out = []
    for b in boxes:
        x1, y1, x2, y2 = b["xyxy"]
        out.append({
            "class_id": b["class_id"],
            "class_name": b["class_name"],
            "conf": _safe_num(b["conf"]),
            "xyxy": [_safe_num(x1), _safe_num(y1), _safe_num(x2), _safe_num(y2)],
        })
    return out


def _load_model(weights_path):
    from ultralytics import YOLO
    return YOLO(str(weights_path))  # 本地绝对路径，不触发下载


def process_result(res, sample_id, input_sha, expected_sha, img_w, img_h, names, out_dir):
    """校验单个 predict 结果并写叠加图。返回记录字典（status 为 ok 或 error）。"""
    rec = {"id": sample_id, "status": "running"}
    errors = []
    rec["sha256_actual"] = input_sha
    rec["sha256_expected"] = expected_sha
    if expected_sha and input_sha != expected_sha:
        errors.append(f"输入哈希不符：期望 {expected_sha} 实际 {input_sha}")
    rec["width"], rec["height"] = img_w, img_h
    rec["orig_shape"] = list(res.orig_shape) if res.orig_shape is not None else None
    if res.orig_shape is None or tuple(res.orig_shape) != (img_h, img_w):
        errors.append(f"orig_shape {res.orig_shape} 与原图尺寸 ({img_w},{img_h}) 不一致")
    rec["speed_ms"] = res.speed if isinstance(getattr(res, "speed", None), dict) else None
    raw_boxes, box_errors = extract_boxes(getattr(res, "boxes", None), names, img_w, img_h)
    errors.extend(box_errors)
    overlay_png = Path(out_dir) / f"{sample_id}.overlay.png"
    overlay_err = write_overlay(res, overlay_png)
    if overlay_err:
        errors.append(overlay_err)
    rec["overlay_png"] = str(overlay_png)
    rec["overlay_saved"] = overlay_err is None and overlay_png.exists() and overlay_png.stat().st_size > 0

    if errors:
        rec["status"] = "error"
        rec["errors"] = errors
        rec["raw_boxes"] = _sanitize_boxes(raw_boxes)
        rec["fire_boxes"] = []
        rec["num_raw"] = 0
        rec["num_fire"] = 0
    else:
        rec["status"] = "ok"
        rec["raw_boxes"] = [_jsonify_box(b) for b in raw_boxes]
        fire_boxes = []
        for b in raw_boxes:
            if str(names.get(b["class_id"], "")).lower() in FIRE_LABELS:
                fb = _jsonify_box(b)
                x1, y1, x2, y2 = b["xyxy"]
                fb["lower40_center_anchor_uv"] = [round((x1 + x2) / 2.0, 3), round(y1 + 0.8 * (y2 - y1), 3)]
                fb["anchor_note"] = "bbox 下 40% 中心；定位候选像素，非真实地面火点"
                fire_boxes.append(fb)
        rec["fire_boxes"] = fire_boxes
        rec["num_raw"] = len(raw_boxes)
        rec["num_fire"] = len(fire_boxes)
    rec["smoke_boxes"] = []
    rec["smoke_note"] = "best.pt 类别仅 fire，无 smoke 类别，故 smoke 单列为空"
    return rec


def run(manifest_path=MANIFEST_PATH, out_dir=None, weights_path=None):
    weights_path = Path(weights_path or WEIGHTS)
    out_dir = Path(out_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    samples = manifest.get("samples", [])
    declared = manifest.get("weights", {})

    try:
        import ultralytics
        ultralytics_version = ultralytics.__version__
    except Exception:
        ultralytics_version = None
    try:
        import torch
        torch_version = torch.__version__
    except Exception:
        torch_version = None

    actual_sha = sha256_file(weights_path)
    run_meta = {
        "interpreter": sys.executable,
        "python_version": sys.version.split()[0],
        "weights": str(weights_path),
        "weights_sha256": actual_sha,
        "ultralytics_version": ultralytics_version,
        "torch_version": torch_version,
        "params": {"device": DEVICE, "imgsz": IMGSZ, "conf": CONF, "iou": IOU},
        "fire_labels": sorted(FIRE_LABELS),
    }

    print("=" * 72)
    print("C1 离线二维火焰检测（小样本基线，严格校验）")
    for k, v in run_meta.items():
        print(f"  {k}: {v}")

    # 1) 首次 predict 前：强制核对权重哈希、task、类别映射
    meta_errors = []
    if declared.get("sha256") and actual_sha != declared["sha256"]:
        meta_errors.append(f"权重 SHA256 不符：期望 {declared['sha256']} 实际 {actual_sha}")
    model = None
    names = {}
    if not meta_errors:
        model = _load_model(weights_path)
        task = getattr(model, "task", None)
        names = normalize_names(getattr(model, "names", {}) or {})
        meta_errors.extend(check_weight_meta(actual_sha, task, names, declared))
        run_meta["model_task"] = task
        run_meta["model_names"] = names
    run_meta["model_loaded"] = model is not None
    run_meta["meta_errors"] = meta_errors

    if meta_errors:
        for e in meta_errors:
            print(f"  [权重核对失败] {e}", file=sys.stderr)
        write_json(out_dir / "run_meta.json", run_meta)
        write_json(out_dir / "summary.json", {
            "run_meta": run_meta, "status": "weight_check_failed", "errors": meta_errors, "results": [],
        })
        print("=" * 72)
        print(f"权重/模型核对失败：{'已加载模型（用于读取 task/names）但' if model is not None else '未加载模型，'}未调用 predict。")
        return 2

    # 2) 逐图
    results_out = []
    for s in samples:
        rec = {"id": s["id"], "status": "running"}
        p = Path(s["path"])
        try:
            input_sha = sha256_file(p)
            img = cv2.imread(str(p))
            if img is None:
                raise RuntimeError(f"无法读取图像: {p}")
            h, w = img.shape[:2]
            t0 = time.perf_counter()
            res = model.predict(str(p), imgsz=IMGSZ, conf=CONF, iou=IOU, device=DEVICE, verbose=False)[0]
            dt = round(time.perf_counter() - t0, 4)
            rec = process_result(res, s["id"], input_sha, s.get("sha256"), w, h, names, out_dir)
            rec["inference_seconds"] = dt
        except Exception as exc:
            rec["status"] = "error"
            rec["error"] = str(exc)
            rec["traceback"] = traceback.format_exc()
        results_out.append(rec)
        try:
            write_json(out_dir / f"{s['id']}.json", rec)
        except (ValueError, TypeError) as exc:
            rec["status"] = "error"
            rec["json_write_error"] = str(exc)
            write_json(out_dir / f"{s['id']}.json", {"id": s["id"], "status": "error", "json_write_error": str(exc)})
        if rec["status"] == "ok":
            print(f"  [{s['id']}] ok  raw={rec['num_raw']} fire={rec['num_fire']} t={rec.get('inference_seconds')}s")
        else:
            print(f"  [{s['id']}] {rec['status']}: {rec.get('errors') or rec.get('error')}")

    summary = {"run_meta": run_meta, "results": results_out}
    write_json(out_dir / "summary.json", summary)
    write_json(out_dir / "run_meta.json", run_meta)
    shutil.copyfile(str(manifest_path), str(out_dir / "samples.json"))

    errors = [r for r in results_out if r["status"] != "ok"]
    print("=" * 72)
    print(f"完成：{len(results_out)} 张，错误 {len(errors)}")
    for r in errors:
        print(f"  ERROR {r['id']}: {r.get('errors') or r.get('error')}")
    return 1 if errors else 0


def main():
    return run()


if __name__ == "__main__":
    sys.exit(main())
