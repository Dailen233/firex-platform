#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A2: single-image YOLO inference for the backend (runs in the C1 environment).

The backend venv has no ultralytics/torch/cv2, so the YoloProvider spawns this
script with the C1 interpreter (default /home/dailen/vggt/vggt-env/bin/python).
Detection logic is reused from C1's validated module (experiments/c1-detection/
run_detection.py): weight SHA/task/names are checked before every predict, and
every box passes the same finite/confidence/area/bounds validation. A weight
check or inference failure prints a JSON error object and exits non-zero — it is
never reported as "no detection".

Output: exactly one JSON object on stdout (allow_nan=False).
  ok:    {"status":"ok", "num_raw", "num_fire", "raw_boxes", "fire_boxes",
          "width", "height", "inference_seconds", "model":{...}}
  error: {"status":"error", "errors":[...], "model":{...}}

Usage:
    <c1-python> yolo_predict_single.py <image> [--conf F] [--imgsz N] [--iou F]
                                       [--device S] [--weights P] [--weights-sha256 SHA]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "experiments" / "c1-detection"))
import run_detection as rd  # C1-validated helpers: sha256_file, check_weight_meta, extract_boxes

# C1-verified weight contract (samples.json). Any other file must pass the same
# declared SHA to be loaded; there is no download and no fallback.
DEFAULT_WEIGHTS = "/home/dailen/vggt/runs/detect/train_full_v1/weights/best.pt"
DEFAULT_WEIGHTS_SHA256 = "69b1f5c11edc646274c9fbb1ac4879d2874ad627b571c156ece45452b612087a"
DEFAULT_TASK = "detect"
DEFAULT_NAMES = {"0": "fire"}


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, allow_nan=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="Image file to run detection on")
    parser.add_argument("--weights", default=DEFAULT_WEIGHTS)
    parser.add_argument("--weights-sha256", default=DEFAULT_WEIGHTS_SHA256)
    parser.add_argument("--conf", type=float, default=rd.CONF)
    parser.add_argument("--imgsz", type=int, default=rd.IMGSZ)
    parser.add_argument("--iou", type=float, default=rd.IOU)
    parser.add_argument("--device", default=rd.DEVICE)
    args = parser.parse_args()

    model_meta = {"weights": args.weights, "conf": args.conf, "imgsz": args.imgsz,
                  "iou": args.iou, "device": args.device}

    image_path = Path(args.image)
    try:
        import cv2

        # 1) Weight contract check BEFORE any predict (C1 rule).
        actual_sha = rd.sha256_file(args.weights)
        meta_errors = rd.check_weight_meta(
            actual_sha, DEFAULT_TASK, DEFAULT_NAMES,
            {"sha256": args.weights_sha256, "task": DEFAULT_TASK, "names": DEFAULT_NAMES},
        )
        model_meta["weights_sha256"] = actual_sha
        if meta_errors:
            _emit({"status": "error", "errors": meta_errors, "model": model_meta})
            return 2

        # 2) Load local weights (absolute path, no download) and read the image.
        model = rd._load_model(args.weights)
        names = rd.normalize_names(getattr(model, "names", {}) or {})
        if not names:
            _emit({"status": "error", "errors": ["模型无有效类别映射"], "model": model_meta})
            return 2
        model_meta["task"] = getattr(model, "task", None)
        model_meta["names"] = names
        img = cv2.imread(str(image_path))
        if img is None:
            _emit({"status": "error", "errors": [f"无法读取图像: {image_path}"], "model": model_meta})
            return 2
        h, w = img.shape[:2]

        # 3) Predict and validate boxes exactly like C1.
        t0 = time.perf_counter()
        res = model.predict(str(image_path), imgsz=args.imgsz, conf=args.conf,
                            iou=args.iou, device=args.device, verbose=False)[0]
        dt = round(time.perf_counter() - t0, 4)
        raw_boxes, errors = rd.extract_boxes(getattr(res, "boxes", None), names, w, h)
        if res.orig_shape is None or tuple(res.orig_shape) != (h, w):
            errors.append(f"orig_shape {res.orig_shape} 与原图尺寸 ({w},{h}) 不一致")
        if errors:
            _emit({"status": "error", "errors": errors, "model": model_meta})
            return 2

        fire_boxes = [b for b in raw_boxes
                      if str(names.get(b["class_id"], "")).lower() in rd.FIRE_LABELS]

        def box_json(b: dict) -> dict:
            return {
                "class_id": b["class_id"],
                "class_name": b["class_name"],
                "conf": round(float(b["conf"]), 6),
                "xyxy": [round(float(v), 3) for v in b["xyxy"]],
            }

        _emit({
            "status": "ok",
            "width": w,
            "height": h,
            "num_raw": len(raw_boxes),
            "num_fire": len(fire_boxes),
            "raw_boxes": [box_json(b) for b in raw_boxes],
            "fire_boxes": [box_json(b) for b in fire_boxes],
            "inference_seconds": dt,
            "model": model_meta,
        })
        return 0
    except Exception as exc:  # noqa: BLE001 - report real failures as errors
        _emit({"status": "error", "errors": [f"{type(exc).__name__}: {exc}"],
               "traceback": traceback.format_exc(), "model": model_meta})
        return 2


if __name__ == "__main__":
    sys.exit(main())
