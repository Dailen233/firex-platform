#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 历史 pose 核验（层级 2：字段与矩阵内部一致性；层级 1 的合成数学在 test_camera_geometry.py）。

读取 samples.json 中固定的两张不同来源/位姿帧，逐帧核验：
- 图像哈希与尺寸（与清单一致）；pose 哈希（与清单一致）；
- 尺寸三向绑定：实际解码尺寸、manifest 尺寸、pose image_width/image_height 三者一致，且 pose 宽高为正整数；
- pose 字段与 camera_to_world_matrix 内部一致性；手性转换；内参与射线。

任一绑定失败 → 该帧 status=error，整体退出码非零，且**不继续**为该帧生成内参/射线结论。

输出写入 runtime-data/c2/（gitignore 覆盖）。verify_frame/run 可被 test_camera_geometry.py 直接调用做端到端反例。

运行（仓库根）：
    /home/dailen/vggt/vggt-env/bin/python experiments/c2-camera-geometry/verify_historical_poses.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import camera_geometry as cg

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = Path(__file__).resolve().parent / "samples.json"
OUT_DIR = REPO_ROOT / "runtime-data" / "c2"


def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def image_size(p):
    import cv2
    img = cv2.imread(str(p))
    if img is None:
        raise RuntimeError(f"无法读取图像: {p}")
    h, w = img.shape[:2]
    return w, h


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def _is_positive_int(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return v > 0
    if isinstance(v, float):
        return v.is_integer() and v > 0
    return False


def verify_frame(fr) -> dict:
    """验证单帧。返回记录字典（status 为 ok 或 error）。绑定失败后不生成内参/射线结论。"""
    rec = {"id": fr["id"], "source_stem": fr.get("source_stem"), "role": fr.get("role"), "checks": []}
    errors = []
    try:
        # 1) 图像哈希 + 实际解码尺寸
        img_path = Path(fr["image"])
        actual_sha = sha256_file(img_path)
        w_img, h_img = image_size(img_path)
        actual_size = [w_img, h_img]
        rec["image_sha256_actual"] = actual_sha
        rec["image_size_actual"] = actual_size
        sha_ok = actual_sha == fr.get("image_sha256")
        rec["checks"].append(("image_sha256", sha_ok, actual_sha[:16]))
        if not sha_ok:
            errors.append(f"图像哈希不符：期望 {fr.get('image_sha256')} 实际 {actual_sha}")

        # 2) pose 读取 + 哈希
        pose_path = Path(fr["pose"])
        pose_bytes = pose_path.read_bytes()
        pose_sha = hashlib.sha256(pose_bytes).hexdigest()
        rec["pose_sha256_actual"] = pose_sha
        pose_sha_ok = pose_sha == fr.get("pose_sha256")
        rec["checks"].append(("pose_sha256", pose_sha_ok, pose_sha[:16]))
        if not pose_sha_ok:
            errors.append(f"pose 哈希不符：期望 {fr.get('pose_sha256')} 实际 {pose_sha}")

        pose = json.loads(pose_bytes.decode("utf-8"))
        rec["pose_frame_id"] = pose.get("frame_id")
        pw, ph = pose.get("image_width"), pose.get("image_height")
        rec["pose_declared_size"] = [pw, ph]
        rec["manifest_size"] = fr.get("image_size")

        # 3) 尺寸三向绑定（实际 == manifest == pose，且 pose 为正整数）
        size_errors = []
        if not _is_positive_int(pw):
            size_errors.append(f"pose image_width 非正整数：{pw!r}")
        if not _is_positive_int(ph):
            size_errors.append(f"pose image_height 非正整数：{ph!r}")
        if _is_positive_int(pw) and _is_positive_int(ph):
            pose_size = [int(pw), int(ph)]
            if pose_size != actual_size:
                size_errors.append(f"pose 尺寸 {pose_size} 与图像实际尺寸 {actual_size} 不一致")
            msz = fr.get("image_size")
            if msz is not None:
                msz = [int(x) for x in msz]
                if msz != actual_size:
                    size_errors.append(f"manifest 尺寸 {msz} 与图像实际尺寸 {actual_size} 不一致")
                if msz != pose_size:
                    size_errors.append(f"manifest 尺寸 {msz} 与 pose 尺寸 {pose_size} 不一致")
        rec["size_binding_errors"] = size_errors
        rec["checks"].append(("size_binding", not size_errors, size_errors or f"ok actual={actual_size}"))
        errors.extend(size_errors)

        # 4) 绑定失败 → 不生成内参/射线结论
        if errors:
            rec["status"] = "error"
            rec["errors"] = errors
            rec["skipped"] = "绑定失败（哈希/尺寸），未生成内参与射线结论"
            return rec

        # 5) pose 内部一致性 + 手性转换 + 内参/射线
        rep, pose_errs = cg.check_pose_internal(pose)
        rec["pose_errors"] = pose_errs
        rec["checks"].append(("pose_internal_consistent", not pose_errs, pose_errs or "ok"))
        rec["matrix_det"] = rep.get("matrix_det")
        if "R_unity" not in rep:
            raise RuntimeError("矩阵解析失败，无法进行后续转换")

        Rd, td, cerrs = cg.convert_to_demo(rep["R_unity"], rep["t_unity"])
        rec["R_demo"] = Rd.tolist()
        rec["t_demo"] = td.tolist()
        rec["convert_errors"] = cerrs
        rec["checks"].append(("convert_demo", not cerrs, cerrs or "ok"))

        K = cg.intrinsics_from_fov(float(pose["fov_y_deg"]), int(pw), int(ph))
        rec["K"] = K.tolist()
        ok_center, cos_center = cg.check_center_ray_forward(K)
        ok_axes, (cos_x, cos_y) = cg.check_pixel_axes(K)
        ok_cols, col_err = cg.check_axes_columns(Rd, rep)
        ok_cross, cross_err = cg.check_cross_product(Rd)
        ok_rt, reproj_px, world_err = cg.check_projection_roundtrip(Rd, td, K)
        rec["checks"].append(("center_ray_is_forward", ok_center, f"cos={cos_center:.8f}"))
        rec["checks"].append(("pixel_axes", ok_axes, f"cos_x={cos_x:.8f} cos_y={cos_y:.8f}"))
        rec["checks"].append(("axes_columns_match", ok_cols, f"max_err={col_err:.3e}"))
        rec["checks"].append(("cross_product_right_x_down_is_forward", ok_cross, f"max_err={cross_err:.3e}"))
        rec["checks"].append(("projection_roundtrip", ok_rt, f"reproj={reproj_px:.6f}px world_err={world_err:.3e}"))
        all_ok = all(ok for _, ok, _ in rec["checks"])
        rec["status"] = "ok" if all_ok else "error"
    except Exception as exc:
        rec["status"] = "error"
        rec["error"] = str(exc)
        rec["traceback"] = traceback.format_exc()
    return rec


def run(manifest_path=MANIFEST_PATH, out_dir=None) -> int:
    manifest_path = Path(manifest_path)
    out_dir = Path(out_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames = manifest["frames"]

    run_meta = {
        "interpreter": sys.executable,
        "python_version": sys.version.split()[0],
        "numpy_version": np.__version__,
        "source_dir": manifest.get("source_dir"),
        "conventions": {
            "unity_world": "left-handed, X right / Y up / Z forward",
            "demo_rh_point": "[Unity x, Unity y, -Unity z]",
            "backend_camera_axes": "x right / y down / z forward (right-handed)",
            "image_coords": "top-left-origin continuous image coordinates (u,v)",
            "W": cg.W.tolist(),
            "C": cg.C.tolist(),
            "formula": "R_demo = W @ R_unity @ C ; t_demo = W @ t_unity",
        },
        "thresholds": {
            "ORTHO_TOL": cg.ORTHO_TOL, "VEC_TOL": cg.VEC_TOL,
            "RAY_ANGLE_DEG": cg.RAY_ANGLE_DEG, "REPROJ_PX": cg.REPROJ_PX, "EPS": cg.EPS,
        },
    }

    print("=" * 72)
    print("C2 历史 pose 核验（尺寸三向绑定 + 哈希 + 内部一致性 + 手性转换 + 内参/射线）")

    results = []
    for fr in frames:
        rec = verify_frame(fr)
        results.append(rec)
        print(f"  [{rec['id']}] {rec['status']}")
        for name, ok, detail in rec.get("checks", []):
            print(f"      {'PASS' if ok else 'FAIL'}  {name}: {detail}")
        if rec["status"] == "error":
            print(f"      ERROR: {rec.get('errors') or rec.get('error')}")

    summary = {"run_meta": run_meta, "results": results}
    write_json(out_dir / "summary.json", summary)
    write_json(out_dir / "run_meta.json", run_meta)
    for rec in results:
        write_json(out_dir / f"{rec['id']}.json", rec)

    errors = [r for r in results if r["status"] != "ok"]
    print("=" * 72)
    print(f"完成：{len(results)} 帧，错误 {len(errors)}")
    for r in errors:
        print(f"  ERROR {r['id']}: {r.get('errors') or r.get('error')}")
    return 1 if errors else 0


def main():
    return run()


if __name__ == "__main__":
    sys.exit(main())
