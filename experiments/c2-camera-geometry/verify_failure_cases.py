#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 端到端失败验证：尺寸不符、pose 哈希不符应使 verify_historical_poses.run() 非零退出。

用临时清单 + 变更后的 pose 副本（其 SHA256 与清单一致），单独证明「尺寸绑定」失败，
不被哈希检查提前挡住。每个反例记录 run() 的实际退出码；脚本自身 exit 0 表示
「三个反例均按预期失败」，任一反例未失败（或错误地生成了内参 K）则 exit 1。

运行（仓库根）：
    /home/dailen/vggt/vggt-env/bin/python experiments/c2-camera-geometry/verify_failure_cases.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_historical_poses as vh

REAL_IMAGE = "/home/dailen/Nutstore Files/Fire_X/demo_sequences/state_machine_case/images/state_000001.png"
REAL_POSE = "/home/dailen/Nutstore Files/Fire_X/demo_sequences/state_machine_case/poses/state_000001.json"
IMAGE_SHA = "9b6d0a26b601007f2d11bb6db118eb59da2f6bdc227c684d5398f37a74991439"


def write_manifest(pose_path, pose_sha, image_sha, image_size, out_manifest):
    manifest = {
        "source_dir": "",
        "frames": [{
            "id": "t", "source_stem": "s", "role": "r",
            "image": REAL_IMAGE, "pose": pose_path,
            "image_sha256": image_sha, "image_size": image_size,
            "pose_sha256": pose_sha,
        }],
    }
    Path(out_manifest).write_text(json.dumps(manifest), encoding="utf-8")


def modify_pose(width=None, height=None, out_path=None):
    pose = json.loads(Path(REAL_POSE).read_text(encoding="utf-8"))
    if width is not None:
        pose["image_width"] = width
    if height is not None:
        pose["image_height"] = height
    Path(out_path).write_text(json.dumps(pose), encoding="utf-8")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="c2-failure-"))
    cases = []

    # 1) 尺寸宽不符：pose 宽 2194 vs 图像 2193（pose 哈希 = 变更副本哈希，哈希检查应通过）
    p1 = tmp / "pose_w.json"
    modify_pose(width=2194, out_path=str(p1))
    m1 = tmp / "m1.json"
    write_manifest(str(p1), hashlib.sha256(p1.read_bytes()).hexdigest(), IMAGE_SHA, [2193, 1000], str(m1))
    cases.append(("size_width_mismatch", m1))

    # 2) 尺寸高不符：pose 高 1001 vs 图像 1000
    p2 = tmp / "pose_h.json"
    modify_pose(height=1001, out_path=str(p2))
    m2 = tmp / "m2.json"
    write_manifest(str(p2), hashlib.sha256(p2.read_bytes()).hexdigest(), IMAGE_SHA, [2193, 1000], str(m2))
    cases.append(("size_height_mismatch", m2))

    # 3) pose 哈希不符
    m3 = tmp / "m3.json"
    write_manifest(REAL_POSE, "deadbeef", IMAGE_SHA, [2193, 1000], str(m3))
    cases.append(("pose_hash_mismatch", m3))

    print("=" * 72)
    print("C2 端到端失败验证（每个反例应使 run() 非零退出，且不生成内参 K）")
    all_ok = True
    for name, mpath in cases:
        out = tmp / name
        code = vh.run(manifest_path=mpath, out_dir=out)
        failed = code != 0
        print(f"  {name}: run() exit = {code}  -> {'按预期失败' if failed else '未失败（错误）'}")
        if not failed:
            all_ok = False
        try:
            rec = json.loads((out / "summary.json").read_text(encoding="utf-8"))["results"][0]
            errs = rec.get("errors") or rec.get("size_binding_errors") or []
            for e in errs:
                print(f"      {e}")
            if "K" in rec:
                print("      !! 错误地生成了内参 K")
                all_ok = False
            else:
                print("      未生成内参 K（正确）")
        except Exception as exc:  # noqa: BLE001
            print(f"      （读取结果失败：{exc}）")
            all_ok = False

    print("=" * 72)
    print("结论：" + ("全部反例按预期失败（run() 均非零退出，且未生成内参/射线）" if all_ok else "存在未按预期失败的反例"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
