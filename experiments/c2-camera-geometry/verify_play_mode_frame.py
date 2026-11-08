#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E3.2 Play Mode 采集帧核验入口（只读）。

读 manifest（共享地形 + 帧清单），逐帧核对帧标识、图像尺寸/哈希、资产与坐标约定，
做前向投影（顶点→像素，比 Unity 导出像素）与反向射线（像素→GLB 地形求交，比独立参考位置），
输出像素误差、落点米制误差与异常原因。

运行（仓库根）：
    /home/dailen/vggt/vggt-env/bin/python experiments/c2-camera-geometry/verify_play_mode_frame.py \
        --manifest runtime-data/e3-synthetic/manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import play_mode_frame as pmf


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_terrain(spec, base: Path):
    """加载共享地形（GLB 坐标）。支持内嵌 {vertices, triangles} 或文件 {vertices_file, triangles_file}。"""
    errors = []
    if "vertices" in spec and "triangles" in spec:
        return np.asarray(spec["vertices"], dtype=np.float64), np.asarray(spec["triangles"], dtype=np.int64), errors
    if "vertices_file" in spec and "triangles_file" in spec:
        vp = base / spec["vertices_file"]
        tp = base / spec["triangles_file"]
        try:
            vertices = np.load(vp) if vp.suffix == ".npy" else np.asarray(json.loads(vp.read_text()), dtype=np.float64)
            triangles = np.load(tp) if tp.suffix == ".npy" else np.asarray(json.loads(tp.read_text()), dtype=np.int64)
            return vertices, triangles, errors
        except Exception as e:
            errors.append(f"地形文件读取失败：{e}")
            return None, None, errors
    errors.append("manifest.terrain 缺少 vertices/triangles 或 vertices_file/triangles_file")
    return None, None, errors


def run(manifest_path: Path) -> int:
    manifest_path = Path(manifest_path)
    base = manifest_path.resolve().parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    terrain_v, terrain_t, terr_errs = load_terrain(manifest.get("terrain") or {}, base)
    if terr_errs:
        print("地形加载失败：", terr_errs)
        return 1

    frames = manifest.get("frames") or []
    print("=" * 72)
    print(f"E3.2 Play Mode 采集帧核验（{len(frames)} 帧）")
    print(f"  地形：{terrain_v.shape[0]} 顶点 / {terrain_t.shape[0]} 三角形（GLB 坐标）")

    results = []
    for fr in frames:
        fid = fr.get("id")
        rec = {"id": fid, "checks": []}
        try:
            frame_path = base / fr["frame"]
            image_path = base / fr.get("image", "")
            frame_bytes = frame_path.read_bytes()
            frame_sha = hashlib.sha256(frame_bytes).hexdigest()
            declared_fsha = fr.get("frame_sha256")
            frame = json.loads(frame_bytes.decode("utf-8"))

            # 帧标识核对
            if declared_fsha and frame_sha != declared_fsha:
                rec["checks"].append(("frame_sha256", False, f"清单 {declared_fsha[:12]}… 实际 {frame_sha[:12]}…"))
            else:
                rec["checks"].append(("frame_sha256", True, frame_sha[:12]))
            ffid = frame.get("frame_id")
            if ffid is not None and str(ffid) != str(fid):
                rec["checks"].append(("frame_id", False, f"清单 {fid} vs 帧内 {ffid}"))
            else:
                rec["checks"].append(("frame_id", True, str(ffid or fid)))

            # 几何核验
            vr = pmf.verify_frame(
                frame, terrain_v, terrain_t,
                image_path=str(image_path) if image_path.exists() else None,
                image_sha256=fr.get("image_sha256"),
            )
            rec.update(vr)
            rec["id"] = fid
            rec["frame_id"] = ffid
        except Exception as exc:
            rec["status"] = "error"
            rec["error"] = str(exc)
            rec["traceback"] = traceback.format_exc()
        results.append(rec)

        # 打印
        status = rec.get("status", "error")
        print(f"\n  [{fid}] {status}")
        for name, ok, detail in rec.get("checks", []):
            print(f"      {'PASS' if ok else 'FAIL'}  {name}: {detail}")
        for p in rec.get("points", []):
            print(f"      · {p['point_id']}: 像素误差 {p.get('pixel_error_px')}px | "
                  f"命中 {p.get('ray_hit_xyz')} | 米制误差 {p.get('metric_error_m')}m")
        if status == "error":
            print(f"      ERROR: {rec.get('errors') or rec.get('error')}")

    # summary
    out = manifest_path.parent / "e3_summary.json"
    summary = {
        "manifest": str(manifest_path),
        "terrain_vertices": int(terrain_v.shape[0]),
        "terrain_triangles": int(terrain_t.shape[0]),
        "thresholds": {"REPROJ_PX": pmf.REPROJ_PX, "RAY_HIT_M": pmf.RAY_HIT_M},
        "results": results,
    }
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print("=" * 72)
    bad = [r for r in results if r.get("status") != "ok"]
    print(f"完成：{len(results)} 帧，异常 {len(bad)}")
    for r in bad:
        print(f"  ERROR {r['id']}: {r.get('errors') or r.get('error')}")
    print(f"summary -> {out}")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description="E3.2 Play Mode 采集帧核验（只读）")
    ap.add_argument("--manifest", required=True, help="manifest.json 路径")
    args = ap.parse_args()
    sys.exit(run(Path(args.manifest)))


if __name__ == "__main__":
    main()
