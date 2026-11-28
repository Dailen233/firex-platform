#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""双江口 photo(3).zip 取点对照（可复跑离线试验）。

复用 runtime-data/e3-photo3/summary.json 的检测框与原图，不重跑 YOLO；相机矩阵、
坐标转换与 GLB 求交沿用 verify_vertex_16099.py（Unity 原生矩阵）+ play_mode_frame.py。

- 保留 bbox_bottom 基线：最高置信度框底边中点 ((x1+x2)/2, y2) 反投影求交（读 summary.json）。
- 新增 flame_lower_edge_debug：同一框内按固定规则筛亮橙像素
  R>=165, G>=55, R-G>=15, G-B>=38, R-B>=110（先转有符号整数再算通道差）；
  取面积>=100 的最大八连通区域；y=区域行坐标第 95 百分位，x=满足 y_pixel>=y-4 的列坐标中位数；
  锚点反投影求交。无有效区域记 no_flame_anchor（不用框底补成功）。

输出（runtime-data/e3-photo3-flame-anchor/）：双取点叠图、逐帧像素及 GLB 坐标对照、
相邻帧水平位移（XZ 平面）、五帧最大水平间距。结果统一标「候选落点，精度未验收」。

运行（仓库根）：
    /home/dailen/vggt/vggt-env/bin/python experiments/c2-camera-geometry/flame_anchor_photo3.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[2]
C2_DIR = REPO_ROOT / "experiments" / "c2-camera-geometry"
sys.path.insert(0, str(C2_DIR))

import play_mode_frame as pmf         # ray_mesh_intersect
import verify_vertex_16099 as v16099  # pixel_to_world_ray / world_ray_to_glb / project_native

E3_SUMMARY = REPO_ROOT / "runtime-data" / "e3-photo3" / "summary.json"
INPUT_DIR = REPO_ROOT / "runtime-data" / "e3-photo3" / "input"
GLB = REPO_ROOT / "frontend" / "public" / "models" / "sjk-hydropower-sim-v0.1" / "sjk_hydropower_sim_v0_1.glb"
TERRAIN_NAME = "team_fbx_terrain_129"
OUT_DIR = REPO_ROOT / "runtime-data" / "e3-photo3-flame-anchor"
MIN_AREA = 100

# 颜色规则（仿真图诊断专用）
R_MIN, G_MIN = 165, 55
RG_MIN, GB_MIN, RB_MIN = 15, 38, 110


def mat44(flat):
    arr = np.asarray(flat, dtype=np.float64)
    if arr.size != 16:
        raise ValueError(f"矩阵元素数 {arr.size} != 16")
    return arr.reshape(4, 4)


def bright_orange_mask(roi_bgr):
    """ROI(BGR) 内亮橙像素 mask（先转有符号整数再算通道差）。"""
    b = roi_bgr[:, :, 0].astype(np.int16)
    g = roi_bgr[:, :, 1].astype(np.int16)
    r = roi_bgr[:, :, 2].astype(np.int16)
    return (r >= R_MIN) & (g >= G_MIN) & (r - g >= RG_MIN) & (g - b >= GB_MIN) & (r - b >= RB_MIN)


def flame_anchor_local(roi_bgr):
    """返回 (局部 x, y 锚点, 区域面积, 最大区域 mask) 或 (None, None, 0, None)。"""
    mask = bright_orange_mask(roi_bgr)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    best_label, best_area = None, 0
    for i in range(1, num):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area >= MIN_AREA and area > best_area:
            best_label, best_area = i, area
    if best_label is None:
        return None, None, 0, None
    ys, xs = np.where(labels == best_label)
    y_anchor = float(np.percentile(ys, 95))
    sel = xs[ys >= y_anchor - 4.0]
    x_anchor = float(np.median(sel))
    return x_anchor, y_anchor, best_area, (labels == best_label)


def horiz_dist(a, b):
    """GLB 坐标水平距离（XZ 平面）。"""
    return float(np.hypot(a[0] - b[0], a[2] - b[2]))


def max_pairwise_span(glb_list):
    valid = [g for g in glb_list if g is not None]
    if len(valid) < 2:
        return None
    m = 0.0
    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            m = max(m, horiz_dist(valid[i], valid[j]))
    return m


def draw_overlay(img, top, bbox_px, flame_px, region_mask_roi, out_path, flame_status):
    x1, y1, x2, y2 = [int(round(v)) for v in top["xyxy"]]
    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 200, 0), 2)
    # 亮橙区域轮廓（蓝色）
    if region_mask_roi is not None:
        cnts, _ = cv2.findContours(region_mask_roi.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            c = c + np.array([x1, y1])
            cv2.drawContours(img, [c], -1, (255, 0, 0), 2)
    # bbox_bottom 底边中点（红）
    cx, cy = bbox_px
    cv2.drawMarker(img, (int(round(cx)), int(round(cy))), (0, 0, 255), cv2.MARKER_CROSS, 20, 2)
    cv2.circle(img, (int(round(cx)), int(round(cy))), 5, (0, 0, 255), -1)
    cv2.putText(img, f"bbox_bottom ({cx:.1f},{cy:.1f})", (int(cx) + 8, max(18, int(cy) - 10)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
    # flame_lower_edge 锚点（黄）
    if flame_px is not None:
        fx, fy = flame_px
        cv2.drawMarker(img, (int(round(fx)), int(round(fy))), (255, 200, 0), cv2.MARKER_TILTED_CROSS, 20, 2)
        cv2.circle(img, (int(round(fx)), int(round(fy))), 5, (255, 200, 0), -1)
        cv2.putText(img, f"flame_edge ({fx:.1f},{fy:.1f})", (int(fx) + 8, max(18, int(fy) + 18)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 1, cv2.LINE_AA)
    # 顶部状态
    h, w = img.shape[:2]
    cv2.rectangle(img, (0, 0), (w, 30), (0, 0, 0), -1)
    cv2.putText(img, f"bbox_bottom vs flame_lower_edge  [{flame_status}]  (candidate, unverified)",
                (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.imwrite(str(out_path), img)


def main() -> int:
    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = json.loads(E3_SUMMARY.read_text(encoding="utf-8"))
    scene = trimesh.load(str(GLB), process=False)
    terrain = scene.geometry[TERRAIN_NAME]
    tv = np.asarray(terrain.vertices, dtype=np.float64)
    tt = np.asarray(terrain.faces, dtype=np.int64)

    run_meta = {
        "source_summary": str(E3_SUMMARY),
        "input_dir": str(INPUT_DIR),
        "glb": str(GLB),
        "glb_sha256": summary["run_meta"]["glb_sha256"],
        "terrain": {"name": TERRAIN_NAME, "vertices": int(tv.shape[0]), "triangles": int(tt.shape[0])},
        "flame_color_rule": {"R_min": R_MIN, "G_min": G_MIN, "R_minus_G": RG_MIN,
                             "G_minus_B": GB_MIN, "R_minus_B": RB_MIN, "min_area": MIN_AREA,
                             "anchor_y": "percentile 95 of region rows",
                             "anchor_x": "median of columns where y_pixel >= y-4"},
        "note": "候选落点，精度未验收；颜色规则仅用于本组仿真图诊断",
    }

    frames = []
    for r in summary["results"]:
        fn = r["filename"]
        stem = Path(fn).stem
        top = r["top_box"]
        bbox_glb = r["ray_hit_glb_xyz"]  # bbox_bottom 基线（上一轮已求交）
        img = cv2.imread(str(INPUT_DIR / fn))
        frame = json.loads((INPUT_DIR / f"{stem}.json").read_text(encoding="utf-8"))
        V = mat44(frame["worldToCameraMatrix"])
        P = mat44(frame["projectionMatrix"])
        L = mat44(frame["terrain_localToWorldMatrix"])
        h, w = img.shape[:2]

        x1, y1, x2, y2 = [int(round(v)) for v in top["xyxy"]]
        cx, cy = (x1 + x2) / 2.0, y2

        roi = img[y1:y2 + 1, x1:x2 + 1]
        axl, ayl, area, region_mask = flame_anchor_local(roi)

        rec = {
            "filename": fn,
            "top_box_conf": top["conf"],
            "top_box_xyxy": [round(v, 3) for v in top["xyxy"]],
            "bbox_bottom": {"pixel": [round(cx, 4), round(cy, 4)],
                            "glb_xyz": [round(v, 4) for v in bbox_glb]},
        }

        if axl is None:
            rec["flame_lower_edge_debug"] = {"status": "no_flame_anchor",
                                             "pixel": None, "glb_xyz": None, "mask_area": 0}
            flame_px = None
            flame_glb = None
        else:
            ax, ay = axl + x1, ayl + y1
            o_world, d_world = v16099.pixel_to_world_ray(ax, ay, V, P, w, h)
            o_glb, d_glb = v16099.world_ray_to_glb(o_world, d_world, L)
            hit = pmf.ray_mesh_intersect(o_glb, d_glb, tv, tt)
            if hit is None:
                rec["flame_lower_edge_debug"] = {"status": "ray_miss",
                                                 "pixel": [round(ax, 4), round(ay, 4)],
                                                 "glb_xyz": None, "mask_area": int(area)}
                flame_px = (ax, ay)
                flame_glb = None
            else:
                th, hit_glb = hit
                rec["flame_lower_edge_debug"] = {
                    "status": "candidate_hit",
                    "pixel": [round(ax, 4), round(ay, 4)],
                    "glb_xyz": [round(float(v), 4) for v in hit_glb],
                    "mask_area": int(area),
                }
                flame_px = (ax, ay)
                flame_glb = [float(v) for v in hit_glb]

        frames.append((rec, flame_glb))
        draw_overlay(img, top, (cx, cy), flame_px, region_mask,
                     out_dir / f"{stem}.overlay.png", rec["flame_lower_edge_debug"]["status"])
        print(f"  [{fn}] bbox_bottom={[round(v,2) for v in bbox_glb]}  "
              f"flame_edge={rec['flame_lower_edge_debug']['status']}  "
              f"glb={rec['flame_lower_edge_debug']['glb_xyz']}")

    # 位移与间距
    bbox_glbs = [r["bbox_bottom"]["glb_xyz"] for r, _ in frames]
    flame_glbs = [g for _, g in frames]

    def displacements(glbs):
        out = []
        for i in range(len(glbs) - 1):
            a, b = glbs[i], glbs[i + 1]
            out.append(round(horiz_dist(a, b), 4) if (a is not None and b is not None) else None)
        return out

    bbox_disp = displacements(bbox_glbs)
    flame_disp = displacements(flame_glbs)

    report = {
        "run_meta": run_meta,
        "results": [r for r, _ in frames],
        "horizontal_displacements_m": {
            "bbox_bottom": bbox_disp,
            "flame_lower_edge_debug": flame_disp,
        },
        "max_horizontal_span_m": {
            "bbox_bottom": round(max_pairwise_span(bbox_glbs), 4),
            "flame_lower_edge_debug": (round(max_pairwise_span(flame_glbs), 4)
                                       if max_pairwise_span(flame_glbs) is not None else None),
        },
    }
    (out_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    print("=" * 72)
    print(f"相邻帧水平位移 bbox_bottom:    {bbox_disp}")
    print(f"相邻帧水平位移 flame_edge:      {flame_disp}")
    print(f"五帧最大水平间距 bbox_bottom:   {report['max_horizontal_span_m']['bbox_bottom']} m")
    print(f"五帧最大水平间距 flame_edge:    {report['max_horizontal_span_m']['flame_lower_edge_debug']} m")
    print(f"summary -> {out_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
