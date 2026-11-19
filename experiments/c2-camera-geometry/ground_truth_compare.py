#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""双江口离线实验真值对照入口（轻量、只读）。

复用 runtime-data/e3-photo3-flame-anchor/summary.json 里的两组候选点（bbox_bottom、
flame_lower_edge_debug，均为 GLB 坐标），不重跑 YOLO、不修改取点或求交逻辑。

读取 Unity 独立导出的贴地点真值（Unity 世界坐标），按帧名匹配，校验场景/地形版本/坐标系，
将两组候选点经「当帧 terrain_localToWorldMatrix + E3.1 轴映射 diag(-1,1,1)」转到 Unity 世界，
逐帧输出 XZ 水平误差与三维距离误差，并列出实际参与比较的帧数。

- 真值文件缺失 → 输出 status=awaiting_ground_truth。
- 帧或资产不匹配 → 标原因，不计算误差。
- fire_base_world 与现有候选点均不作真值。
- 结果统一标「精度未验收」。

真值文件 schema（Unity 独立导出，`coordinate_frame="unity_world"`）：
    {
      "schema_version": "1.0",
      "coordinate_frame": "unity_world",
      "scene_id": "sjk_hydropower_sim_v0_1",
      "asset_version": "hydro-sim-v0.1-local",
      "coordinate_frame_id": "SJK_TEAM_FBX_FILE_METRE_UNREGISTERED_v1",
      "glb_sha256": "722b8514…66fb91",
      "terrain_mesh_name": "team_fbx_terrain_129",
      "frames": [
        {"image_file": "Drone_20261108_164451_244.png",
         "ground_truth_unity_world_xyz": [x, y, z]}
      ]
    }

运行（仓库根）：
    /home/dailen/vggt/vggt-env/bin/python experiments/c2-camera-geometry/ground_truth_compare.py \
        [--ground-truth data/sjk_photo3_ground_truth.json]
    # 最小样例自检（已知距离）：
    /home/dailen/vggt/vggt-env/bin/python experiments/c2-camera-geometry/ground_truth_compare.py --selftest
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
C2_DIR = REPO_ROOT / "experiments" / "c2-camera-geometry"
sys.path.insert(0, str(C2_DIR))
import play_mode_frame as pmf  # EXPECTED 五字段（资产/地形版本/坐标系基准）

ANCHOR_SUMMARY = REPO_ROOT / "runtime-data" / "e3-photo3-flame-anchor" / "summary.json"
INPUT_DIR = REPO_ROOT / "runtime-data" / "e3-photo3" / "input"
DEFAULT_GT = REPO_ROOT / "data" / "sjk_photo3_ground_truth.json"
OUT_DIR = REPO_ROOT / "runtime-data" / "e3-photo3-ground-truth"

A = np.diag([-1.0, 1.0, 1.0])  # E3.1 轴映射：mesh_local <-> GLB（X 反射，自逆）


def mat44(flat):
    arr = np.asarray(flat, dtype=np.float64)
    if arr.size != 16:
        raise ValueError(f"矩阵元素数 {arr.size} != 16")
    return arr.reshape(4, 4)


def glb_to_unity(glb_xyz, L):
    """GLB 米制坐标 -> Unity 世界：glb ->(A) mesh_local ->(L) unity_world。"""
    ml = A @ np.asarray(glb_xyz, dtype=np.float64)
    return (L @ np.append(ml, 1.0))[:3]


def xz_error(a, b):
    """XZ 平面水平距离（米）。"""
    return float(np.hypot(a[0] - b[0], a[2] - b[2]))


def dist3d(a, b):
    """三维欧氏距离（米）。"""
    return float(np.linalg.norm(np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)))


def selftest():
    """已知距离最小样例 + GLB->Unity 转换校验。"""
    a = np.array([0.0, 0.0, 0.0])
    b = np.array([3.0, 4.0, 12.0])
    xz = xz_error(a, b)          # sqrt(3^2 + 12^2) = sqrt(153) ≈ 12.3693
    d3 = dist3d(a, b)            # sqrt(3^2 + 4^2 + 12^2) = 13
    assert abs(xz - math.hypot(3, 12)) < 1e-9, xz
    assert abs(d3 - 13.0) < 1e-9, d3

    # 当帧 terrain_localToWorldMatrix（photo(3) 实际值，纯平移）
    L = np.array([[1, 0, 0, 22278.349609375],
                  [0, 1, 0, 0],
                  [0, 0, 1, 8561.326171875],
                  [0, 0, 0, 1]], dtype=np.float64)
    g = np.array([-5.0, 40.0, 7.0])
    u = glb_to_unity(g, L)
    # glb(-5,40,7) -> mesh_local A@(-5,40,7)=(5,40,7) -> unity=(22283.349609375, 40, 8568.326171875)
    assert np.allclose(u, [22283.349609375, 40.0, 8568.326171875], atol=1e-6), u

    # 往返：unity -> mesh_local(Linv) -> glb(A)，应还原原 glb
    ml_back = (np.linalg.inv(L) @ np.append(u, 1.0))[:3]
    g2 = A @ ml_back
    assert np.allclose(g2, g, atol=1e-9), g2
    return {"xz_error": round(xz, 6), "dist3d": round(d3, 6),
            "glb_to_unity": [round(float(v), 6) for v in u]}


def check_asset_decl(gt):
    """校验真值文件声明的资产五字段 + coordinate_frame。返回错误列表。"""
    errors = []
    if gt.get("coordinate_frame") != "unity_world":
        errors.append(f"coordinate_frame 必须为 unity_world，实际 {gt.get('coordinate_frame')!r}")
    for key, expected in pmf.EXPECTED.items():
        val = gt.get(key)
        if val is None:
            errors.append(f"真值缺少资产字段 {key}")
        elif str(val) != expected:
            errors.append(f"资产字段 {key} 不符：声明 {val!r}，预期 {expected!r}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ground-truth", default=str(DEFAULT_GT))
    ap.add_argument("--selftest", action="store_true", help="运行已知距离最小样例自检后退出")
    args = ap.parse_args()

    if args.selftest:
        r = selftest()
        print("selftest PASS")
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0

    gt_path = Path(args.ground_truth)
    anchor = json.loads(ANCHOR_SUMMARY.read_text(encoding="utf-8"))
    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "source_anchor_summary": str(ANCHOR_SUMMARY),
        "ground_truth": str(gt_path),
        "note": "精度未验收；fire_base_world 与现有候选点均不作真值",
        "selftest": selftest(),
    }

    # 真值文件缺失 -> awaiting_ground_truth
    if not gt_path.exists():
        report["status"] = "awaiting_ground_truth"
        report["reason"] = f"真值文件不存在：{gt_path}"
        report["compared_frames"] = 0
        report["frames"] = []
        (out_dir / "ground_truth_compare.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        print("=" * 72)
        print(f"status = awaiting_ground_truth（真值文件缺失：{gt_path}）")
        print(f"selftest: xz_error={report['selftest']['xz_error']}  dist3d={report['selftest']['dist3d']}  PASS")
        print(f"summary -> {out_dir / 'ground_truth_compare.json'}")
        return 0

    gt = json.loads(gt_path.read_text(encoding="utf-8"))

    # 资产校验
    asset_errors = check_asset_decl(gt)
    report["asset_errors"] = asset_errors

    # 当帧 L 缓存（frame -> L）
    L_cache = {}

    def get_L(filename):
        stem = Path(filename).stem
        frame = json.loads((INPUT_DIR / f"{stem}.json").read_text(encoding="utf-8"))
        return mat44(frame["terrain_localToWorldMatrix"])

    gt_by_frame = {f.get("image_file"): f for f in gt.get("frames", [])}

    frames_out = []
    compared = 0
    for r in anchor["results"]:
        fn = r["filename"]
        fr = {"filename": fn, "bbox_bottom": {}, "flame_lower_edge_debug": {}}
        gt_entry = gt_by_frame.get(fn)
        if gt_entry is None:
            fr["ground_truth_status"] = "missing_frame"
            fr["reason"] = "真值中无该帧"
            frames_out.append(fr)
            continue
        gt_xyz = gt_entry.get("ground_truth_unity_world_xyz")
        if gt_xyz is None or len(gt_xyz) != 3:
            fr["ground_truth_status"] = "invalid_truth"
            fr["reason"] = "ground_truth_unity_world_xyz 缺失或非 3 维"
            frames_out.append(fr)
            continue
        gt_xyz = np.asarray(gt_xyz, dtype=np.float64)
        L = get_L(fn)

        for key in ("bbox_bottom", "flame_lower_edge_debug"):
            cand_glb = r[key].get("glb_xyz")
            if cand_glb is None:
                fr[key] = {"candidate_status": r[key].get("status", "none"), "error_m": None}
                continue
            cand_unity = glb_to_unity(np.asarray(cand_glb, dtype=np.float64), L)
            fr[key] = {
                "candidate_status": r[key].get("status"),
                "unity_world_xyz": [round(float(v), 4) for v in cand_unity],
                "xz_error_m": round(xz_error(cand_unity, gt_xyz), 4),
                "dist3d_error_m": round(dist3d(cand_unity, gt_xyz), 4),
            }
        fr["ground_truth_status"] = "matched"
        fr["ground_truth_unity_world_xyz"] = [round(float(v), 4) for v in gt_xyz]
        compared += 1
        frames_out.append(fr)

    report["status"] = "ok" if (not asset_errors and compared == len(anchor["results"])) else "partial"
    report["compared_frames"] = compared
    report["total_frames"] = len(anchor["results"])
    report["frames"] = frames_out

    (out_dir / "ground_truth_compare.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    print("=" * 72)
    print(f"status = {report['status']}   compared_frames = {compared}/{report['total_frames']}")
    if asset_errors:
        for e in asset_errors:
            print(f"  [资产不匹配] {e}")
    for fr in frames_out:
        if fr.get("ground_truth_status") != "matched":
            print(f"  [{fr['filename']}] {fr.get('ground_truth_status')}: {fr.get('reason')}")
        else:
            bb = fr["bbox_bottom"]; fl = fr["flame_lower_edge_debug"]
            print(f"  [{fr['filename']}] bbox_bottom: xz={bb.get('xz_error_m')}m 3d={bb.get('dist3d_error_m')}m  |  "
                  f"flame_edge: xz={fl.get('xz_error_m')}m 3d={fl.get('dist3d_error_m')}m")
    print(f"summary -> {out_dir / 'ground_truth_compare.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
