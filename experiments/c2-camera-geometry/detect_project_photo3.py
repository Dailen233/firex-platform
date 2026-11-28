#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""双江口离线火点落地试验：photo(3).zip 的 5 帧 YOLO + 检测框底边中点反投影到地形求交。

复用：
- 检测：experiments/c1-detection/run_detection.py（best.pt，device=cpu/imgsz=640/conf=0.25/iou=0.45）
- 反投影/求交：verify_vertex_16099.py（Unity 原生矩阵路径）+ play_mode_frame.py（Möller–Trumbore）
- 地形：sjk_hydropower_sim_v0_1.glb 的 team_fbx_terrain_129（哈希与 E3.1 一致）

每帧：取置信度最高的有效 fire 框，用原图左上坐标下底边中点 ((x1+x2)/2, y2) 作候选像素；
左上像素 Y 只转换一次；worldToCameraMatrix det≈−1 按 Unity 原生路径（不套 C2 det=+1）；
射线先经当帧 terrain_localToWorldMatrix 逆→网格局部→E3.1 X 反射（diag(-1,1,1)）→GLB；
取最近正向地形交点，命中后回投到原图记像素残差（几何自检）。

状态：candidate_hit / no_detection / bottom_clipped / ray_miss / error。
fire_base_world 仅保留作诊断，不当贴地真值、不用于修正。输出统一标「候选落点，精度未验收」。

运行（仓库根）：
    /home/dailen/vggt/vggt-env/bin/python experiments/c2-camera-geometry/detect_project_photo3.py
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

import cv2
import numpy as np
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[2]
C1_DIR = REPO_ROOT / "experiments" / "c1-detection"
C2_DIR = REPO_ROOT / "experiments" / "c2-camera-geometry"
sys.path.insert(0, str(C1_DIR))
sys.path.insert(0, str(C2_DIR))

import run_detection as rd            # C1：权重核对 + 检测 + 框校验
import play_mode_frame as pmf         # ray_mesh_intersect
import verify_vertex_16099 as v16099  # project_native / pixel_to_world_ray / world_ray_to_glb

DEFAULT_ZIP = REPO_ROOT / "data" / "photo(3).zip"
DEFAULT_GLB = REPO_ROOT / "frontend" / "public" / "models" / "sjk-hydropower-sim-v0.1" / "sjk_hydropower_sim_v0_1.glb"
DEFAULT_OUT = REPO_ROOT / "runtime-data" / "e3-photo3"

EXPECTED_ZIP_SHA = "6307e7bdc16e12065a8977b3b991da1ed001f339297938c82bc1cef501bdac60"
EXPECTED_GLB_SHA = "722b8514a17715f3c109b1cbaa8259dc958c8f212af71cd1c0ae75608566fb91"
TERRAIN_NAME = "team_fbx_terrain_129"
A = np.diag([-1.0, 1.0, 1.0])  # E3.1 轴映射：mesh_local -> GLB（X 反射，自逆）


def mat44(flat, name):
    """扁平 row_major 16 值 -> 4x4 numpy。校验长度。"""
    arr = np.asarray(flat, dtype=np.float64)
    if arr.size != 16:
        raise ValueError(f"{name} 元素数 {arr.size} != 16")
    return arr.reshape(4, 4)


def glb_to_world(glb_xyz, L):
    """GLB 米制点 -> Unity 世界：glb -> mesh_local(A) -> world(L)。"""
    ml = A @ np.asarray(glb_xyz, dtype=np.float64)
    return (L @ np.append(ml, 1.0))[:3]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip", default=str(DEFAULT_ZIP))
    ap.add_argument("--glb", default=str(DEFAULT_GLB))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    zip_path = Path(args.zip)
    glb_path = Path(args.glb)
    out_dir = Path(args.out)
    input_dir = out_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    # 1) 核对 ZIP 哈希 + 解压
    zip_sha = rd.sha256_file(zip_path)
    zip_ok = zip_sha == EXPECTED_ZIP_SHA
    with zipfile.ZipFile(zip_path) as zf:
        entries = sorted(n for n in zf.namelist() if n.lower().endswith((".png", ".json")))
        for n in entries:
            (input_dir / Path(n).name).write_bytes(zf.read(n))
    png_names = sorted(Path(n).name for n in entries if n.lower().endswith(".png"))

    # 2) GLB 哈希核对 + 地形网格
    glb_sha = rd.sha256_file(glb_path)
    glb_ok = glb_sha == EXPECTED_GLB_SHA
    scene = trimesh.load(str(glb_path), process=False)
    terrain = scene.geometry[TERRAIN_NAME]
    terrain_v = np.asarray(terrain.vertices, dtype=np.float64)
    terrain_t = np.asarray(terrain.faces, dtype=np.int64)

    # 3) 权重核对 + 加载模型（复用 C1）
    actual_wsha = rd.sha256_file(rd.WEIGHTS)
    model = rd._load_model(rd.WEIGHTS)
    model_names = rd.normalize_names(getattr(model, "names", {}) or {})
    meta_errors = rd.check_weight_meta(actual_wsha, getattr(model, "task", None), model_names,
                                       {"sha256": actual_wsha, "task": "detect", "names": {"0": "fire"}})
    if meta_errors:
        print("权重/模型核对失败：", meta_errors, file=sys.stderr)
        return 2

    run_meta = {
        "interpreter": sys.executable,
        "weights": rd.WEIGHTS,
        "weights_sha256": actual_wsha,
        "params": {"device": rd.DEVICE, "imgsz": rd.IMGSZ, "conf": rd.CONF, "iou": rd.IOU},
        "zip": zip_path.name,
        "zip_sha256": zip_sha,
        "zip_sha_ok": zip_ok,
        "glb": str(glb_path),
        "glb_sha256": glb_sha,
        "glb_sha_ok": glb_ok,
        "terrain": {"name": TERRAIN_NAME, "vertices": int(terrain_v.shape[0]), "triangles": int(terrain_t.shape[0])},
        "note": "候选落点，精度未验收；fire_base_world 仅诊断、非贴地真值、不用于修正",
    }
    print("=" * 72)
    print("双江口离线火点落地试验（photo(3).zip 5 帧）")
    print(f"  zip_sha_ok={zip_ok}  glb_sha_ok={glb_ok}  地形 {terrain_v.shape[0]} 顶点/{terrain_t.shape[0]} 三角形")

    results = []
    for png_name in png_names:
        stem = Path(png_name).stem
        json_name = f"{stem}.json"
        rec = {"filename": png_name, "status": "running"}
        try:
            frame = json.loads((input_dir / json_name).read_text(encoding="utf-8"))
            img = cv2.imread(str(input_dir / png_name))
            if img is None:
                raise RuntimeError("无法读取图像")
            h, w = img.shape[:2]

            # 输入核对
            checks = {
                "image_file_ok": frame.get("image_file") == png_name,
                "size_declared": [int(frame.get("width", 0)), int(frame.get("height", 0))],
                "size_actual": [w, h],
                "size_ok": (int(frame.get("width", 0)), int(frame.get("height", 0))) == (w, h),
                "matrix_order": frame.get("matrix_order"),
                "matrix_order_ok": frame.get("matrix_order") == "row_major",
            }
            V = mat44(frame["worldToCameraMatrix"], "worldToCameraMatrix")
            P = mat44(frame["projectionMatrix"], "projectionMatrix")
            L = mat44(frame["terrain_localToWorldMatrix"], "terrain_localToWorldMatrix")
            detV = float(np.linalg.det(V))
            fire_base_world = [float(x) for x in frame.get("fire_base_world", [])]
            rec["input_check"] = checks
            rec["det_worldToCameraMatrix"] = detV
            rec["fire_base_world"] = fire_base_world

            # 检测（复用 C1）
            res = model.predict(str(input_dir / png_name), imgsz=rd.IMGSZ, conf=rd.CONF,
                                iou=rd.IOU, device=rd.DEVICE, verbose=False)[0]
            raw_boxes, box_errors = rd.extract_boxes(getattr(res, "boxes", None), model_names, w, h)
            if box_errors:
                raise RuntimeError(f"框校验失败：{box_errors}")
            fire_boxes = [b for b in raw_boxes
                          if str(model_names.get(b["class_id"], "")).lower() in rd.FIRE_LABELS]
            rec["num_raw"] = len(raw_boxes)
            rec["num_fire"] = len(fire_boxes)
            rec["fire_boxes"] = [{
                "class_name": b["class_name"], "conf": round(float(b["conf"]), 6),
                "xyxy": [round(float(v), 3) for v in b["xyxy"]],
            } for b in fire_boxes]

            if not fire_boxes:
                rec["status"] = "no_detection"
                rec["note"] = "未检出 fire 框"
                results.append(rec)
                self_annotate(img, [], None, rec)
                cv2.imwrite(str(out_dir / f"{stem}.overlay.png"), img)
                print(f"  [{png_name}] no_detection  raw={len(raw_boxes)}")
                continue

            top = max(fire_boxes, key=lambda b: b["conf"])
            x1, y1, x2, y2 = top["xyxy"]
            cx, cy = (x1 + x2) / 2.0, y2  # 底边中点（左上坐标）
            rec["top_box"] = {"class_name": top["class_name"], "conf": round(float(top["conf"]), 6),
                              "xyxy": [round(v, 3) for v in top["xyxy"]]}
            rec["candidate_pixel"] = [round(cx, 4), round(cy, 4)]

            if cy >= h - 0.5:
                rec["status"] = "bottom_clipped"
                rec["note"] = f"检测框底边 y2={y2:.3f} 触及画面底部，底边被截断，候选像素不可靠"
                results.append(rec)
                self_annotate(img, fire_boxes, top, rec)
                cv2.imwrite(str(out_dir / f"{stem}.overlay.png"), img)
                print(f"  [{png_name}] bottom_clipped  y2={y2:.3f}")
                continue

            # 反投影 -> GLB -> 求交
            o_world, d_world = v16099.pixel_to_world_ray(cx, cy, V, P, w, h)
            o_glb, d_glb = v16099.world_ray_to_glb(o_world, d_world, L)
            hit = pmf.ray_mesh_intersect(o_glb, d_glb, terrain_v, terrain_t)
            if hit is None:
                rec["status"] = "ray_miss"
                rec["note"] = "射线未命中 team_fbx_terrain_129（无正向地形交点）"
                rec["ray_origin_glb"] = [round(float(x), 4) for x in o_glb]
                rec["ray_direction_glb"] = [round(float(x), 4) for x in d_glb]
                results.append(rec)
                self_annotate(img, fire_boxes, top, rec)
                cv2.imwrite(str(out_dir / f"{stem}.overlay.png"), img)
                print(f"  [{png_name}] ray_miss  origin={[round(x,1) for x in o_glb]}")
                continue

            th, hit_glb = hit
            hit_glb = np.asarray(hit_glb, dtype=np.float64)
            hit_world = glb_to_world(hit_glb, L)
            # 回投自检
            ru, rv = v16099.project_native(hit_world, V, P, w, h)
            reproj_px = float(np.hypot(ru - cx, rv - cy))

            rec["status"] = "candidate_hit"
            rec["note"] = "候选落点，精度未验收"
            rec["ray_hit_glb_xyz"] = [round(float(x), 4) for x in hit_glb]
            rec["ray_hit_unity_world_xyz"] = [round(float(x), 4) for x in hit_world]
            rec["ray_hit_t"] = float(th)
            rec["reprojected_pixel"] = [round(ru, 4), round(rv, 4)]
            rec["reprojection_residual_px"] = reproj_px
            results.append(rec)
            self_annotate(img, fire_boxes, top, rec)
            cv2.imwrite(str(out_dir / f"{stem}.overlay.png"), img)
            print(f"  [{png_name}] candidate_hit  glb={[round(x,2) for x in hit_glb]}  "
                  f"reproj={reproj_px:.4f}px")
        except Exception as exc:
            rec["status"] = "error"
            rec["error"] = str(exc)
            results.append(rec)
            print(f"  [{png_name}] error: {exc}")

    summary = {"run_meta": run_meta, "results": results}
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print("=" * 72)
    for r in results:
        print(f"  {r['filename']}: {r['status']}")
    print(f"summary -> {out_dir / 'summary.json'}")
    return 0


def self_annotate(img, fire_boxes, top, rec):
    """在原图上画检测框 + 候选像素 + 状态标注。"""
    h, w = img.shape[:2]
    status = rec.get("status", "")
    for b in fire_boxes:
        x1, y1, x2, y2 = [int(round(v)) for v in b["xyxy"]]
        is_top = top is not None and b is top
        color = (0, 0, 255) if is_top else (0, 200, 0)  # BGR：最高置信度红色，其余绿色
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(img, f"fire {b['conf']:.2f}", (x1, max(20, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1, cv2.LINE_AA)
    if top is not None and status not in ("bottom_clipped",):
        cx, cy = rec.get("candidate_pixel", [0, 0])
        px, py = int(round(cx)), int(round(cy))
        cv2.drawMarker(img, (px, py), (0, 0, 255), cv2.MARKER_CROSS, 18, 2)
        cv2.circle(img, (px, py), 4, (0, 0, 255), -1)
        cv2.putText(img, f"base-mid ({cx:.1f},{cy:.1f})", (min(w - 260, px + 8), max(16, py - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
    # 状态标注
    # cv2.putText 不支持中文，状态用英文；完整状态以 summary.json 为准
    status_text = {
        "candidate_hit": "CANDIDATE LANDING (accuracy unverified)",
        "no_detection": "NO DETECTION",
        "bottom_clipped": "BOTTOM CLIPPED",
        "ray_miss": "RAY MISS (no terrain hit)",
        "error": "PROCESSING ERROR",
    }.get(status, status)
    cv2.rectangle(img, (0, 0), (w, 30), (0, 0, 0), -1)
    cv2.putText(img, status_text, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1, cv2.LINE_AA)


if __name__ == "__main__":
    sys.exit(main())
