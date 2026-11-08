#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线批量检测 photo(1).zip 的 11 张 PNG（复用 C1 best.pt 与项目当前推理配置）。

- 固定参数：device=cpu, imgsz=640, conf=0.25, iou=0.45（与 C1 / A2 完全一致）。
- 逐张记录：文件名、是否检出(fire)、类别、置信度、原图像素坐标 xyxy 框，并保存画框图。
- 没检出如实记录为空列表，不视为失败；校验失败（权重/尺寸/有限值/越界）才记 error。
- 离线：仅本地权重 + 本地图片，不下载、不联网、不安装/升级依赖。
- 复用 C1 已核验模块 run_detection.py（sha256_file / check_weight_meta / extract_boxes /
  FIRE_LABELS / _load_model / write_json）。

运行（仓库根）：
    /home/dailen/vggt/vggt-env/bin/python experiments/c1-detection/detect_photo_batch.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_detection as rd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ZIP = REPO_ROOT / "data" / "photo(1).zip"
DEFAULT_OUT = REPO_ROOT / "runtime-data" / "photo-batch-20261108"

# 与 C1 / A2 一致的固定参数（所有帧同一套）
DEVICE = rd.DEVICE   # cpu
IMGSZ = rd.IMGSZ     # 640
CONF = rd.CONF       # 0.25
IOU = rd.IOU         # 0.45
WEIGHTS = rd.WEIGHTS


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip", default=str(DEFAULT_ZIP))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    zip_path = Path(args.zip)
    out_dir = Path(args.out)
    input_dir = out_dir / "input"
    overlay_dir = out_dir / "overlay"
    input_dir.mkdir(parents=True, exist_ok=True)
    overlay_dir.mkdir(parents=True, exist_ok=True)

    # 1) 解压 PNG（扁平化到 input/）
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".png")]
        for n in names:
            target = input_dir / Path(n).name
            target.write_bytes(zf.read(n))
    names = sorted(Path(n).name for n in names)

    # 2) 权重核对（复用 C1；不符则不 predict）
    declared = {"sha256": rd.sha256_file(WEIGHTS)}
    actual_sha = declared["sha256"]
    model = rd._load_model(WEIGHTS)
    task = getattr(model, "task", None)
    model_names = rd.normalize_names(getattr(model, "names", {}) or {})
    meta_errors = rd.check_weight_meta(actual_sha, task, model_names, declared)
    if meta_errors:
        print("权重/模型核对失败：", meta_errors, file=sys.stderr)
        return 2

    run_meta = {
        "interpreter": sys.executable,
        "python_version": sys.version.split()[0],
        "weights": WEIGHTS,
        "weights_sha256": actual_sha,
        "params": {"device": DEVICE, "imgsz": IMGSZ, "conf": CONF, "iou": IOU},
        "fire_labels": sorted(rd.FIRE_LABELS),
        "model_task": task,
        "model_names": model_names,
        "zip_sha256": rd.sha256_file(zip_path),
        "zip": zip_path.name,
        "images": len(names),
    }

    print("=" * 72)
    print("离线批量检测（best.pt / 项目当前推理配置）")
    for k, v in run_meta.items():
        print(f"  {k}: {v}")

    results = []
    for fn in names:
        img_path = input_dir / fn
        rec = {"filename": fn, "status": "running"}
        try:
            input_sha = rd.sha256_file(img_path)
            img = cv2.imread(str(img_path))
            if img is None:
                raise RuntimeError(f"无法读取图像: {img_path}")
            h, w = img.shape[:2]
            t0 = time.perf_counter()
            res = model.predict(str(img_path), imgsz=IMGSZ, conf=CONF, iou=IOU, device=DEVICE, verbose=False)[0]
            dt = round(time.perf_counter() - t0, 4)
            raw_boxes, box_errors = rd.extract_boxes(getattr(res, "boxes", None), model_names, w, h)
            if res.orig_shape is None or tuple(res.orig_shape) != (h, w):
                box_errors.append(f"orig_shape {res.orig_shape} 与原图尺寸 ({w},{h}) 不一致")
            fire_boxes = [b for b in raw_boxes
                          if str(model_names.get(b["class_id"], "")).lower() in rd.FIRE_LABELS]

            # 画框图（无检出时 plot() 亦返回原图，如实保存）
            annot = res.plot()
            overlay_path = overlay_dir / f"{Path(fn).stem}.overlay.png"
            if annot is None or not cv2.imwrite(str(overlay_path), annot):
                raise RuntimeError("画框图写入失败")

            def box_json(b):
                x1, y1, x2, y2 = b["xyxy"]
                return {"class_id": b["class_id"], "class_name": b["class_name"],
                        "conf": round(float(b["conf"]), 6),
                        "xyxy": [round(float(x1), 3), round(float(y1), 3),
                                 round(float(x2), 3), round(float(y2), 3)]}

            if box_errors:
                rec["status"] = "error"
                rec["errors"] = box_errors
                rec["raw_boxes"] = []
                rec["fire_boxes"] = []
            else:
                rec["status"] = "ok"
                rec["width"], rec["height"] = w, h
                rec["sha256"] = input_sha
                rec["raw_boxes"] = [box_json(b) for b in raw_boxes]
                rec["fire_boxes"] = [box_json(b) for b in fire_boxes]
                rec["num_raw"] = len(raw_boxes)
                rec["num_fire"] = len(fire_boxes)
                rec["detected"] = len(fire_boxes) > 0
            rec["overlay_png"] = str(overlay_path)
            rec["inference_seconds"] = dt
        except Exception as exc:
            rec["status"] = "error"
            rec["error"] = str(exc)
        results.append(rec)
        if rec["status"] == "ok":
            print(f"  [{fn}] ok  raw={rec['num_raw']} fire={rec['num_fire']} "
                  f"detected={rec['detected']} t={rec['inference_seconds']}s")
        else:
            print(f"  [{fn}] {rec['status']}: {rec.get('errors') or rec.get('error')}")

    summary = {"run_meta": run_meta, "results": results}
    rd.write_json(out_dir / "summary.json", summary)
    rd.write_json(out_dir / "run_meta.json", run_meta)
    errors = [r for r in results if r["status"] != "ok"]
    print("=" * 72)
    print(f"完成：{len(results)} 张，错误 {len(errors)}")
    for r in errors:
        print(f"  ERROR {r['filename']}: {r.get('errors') or r.get('error')}")
    print(f"画框图：{overlay_dir}   摘要：{out_dir / 'summary.json'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
