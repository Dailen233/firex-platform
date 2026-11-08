#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fire-X D1：VGGT-1B 六视图 RGB 局部三维重建基线（离线）。

严格离线：在任何会访问 HuggingFace 的库导入前设置 HF_HUB_OFFLINE=1 与
HF_HUB_DISABLE_TELEMETRY=1；从已核实的本地 snapshot 用 local_files_only=True 加载，
禁用旧 load_model 的联网 fallback。加载失败明确报错，不下载、不换模型、不生成替代结果。

建模输入只使用 RGB；pose 仅用于输入绑定与后续核对，不参与生成结果。

用法（仓库根，vggt-env）：
    预检（不加载模型、不 import torch/open3d）：
    /home/dailen/vggt/vggt-env/bin/python experiments/d1-recon/reconstruct.py --preflight
    加载验证（仅加载权重到设备并记录资源后退出，不预处理/推理，不生成重建成功标记）：
    /home/dailen/vggt/vggt-env/bin/python experiments/d1-recon/reconstruct.py --load-only --run-dir <新目录>
    单配置重建（外部终端建议加 -u 即时刷日志）：
    /home/dailen/vggt/vggt-env/bin/python -u experiments/d1-recon/reconstruct.py --config A --run-dir <新目录>

退出码：0=成功；1=其它错误；2=输入/清单校验失败（模型加载前）；3=CUDA OOM；
4=输出无效/导出失败；5=资源预检失败；6=超时；7=运行目录已存在（不覆盖）。
"""
from __future__ import annotations

import os


def _enforce_offline():
    """强制离线：覆盖环境里可能已存在的 0（不用 setdefault 保留旧值）。"""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


# ---- 离线开关：必须在导入任何 HF 相关库之前设置 ----
_enforce_offline()

import argparse
import hashlib
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np

# torch / torch.nn.functional 延迟导入：--preflight 需在 import torch 之前检查资源，
# 避免导入本身占内存/初始化 CUDA。需要处用函数内 `import torch`（首次后即缓存）。

PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = PACKAGE_ROOT / "samples.json"
DEFAULT_RUN_DIR = PACKAGE_ROOT / "output"


def _default_manifest() -> Path:
    """默认清单：本机 samples.json；包内只有 samples_cloud.json 时用之。

    都不存在时仍返回 samples.json 路径，由 main 显式失败（不静默换用另一份清单）。"""
    for name in ("samples.json", "samples_cloud.json"):
        p = PACKAGE_ROOT / name
        if p.exists():
            return p
    return DEFAULT_MANIFEST


def resolve_path(p, base=None):
    """绝对路径原样返回；相对路径相对包根（或给定 base）解析，保证从不同 cwd 运行也正确。"""
    p = Path(p)
    if p.is_absolute():
        return p
    return (base if base is not None else PACKAGE_ROOT) / p

EXIT_OK = 0
EXIT_ERR = 1
EXIT_INPUT = 2
EXIT_OOM = 3
EXIT_OUTPUT = 4
EXIT_RESOURCE = 5
EXIT_TIMEOUT = 6
EXIT_EXISTS = 7

PATCH = 14

# 资源预检保守门槛（防护预算，非实测安全保证；不足即失败，不自动降低）
MIN_MEM_AVAILABLE_KIB = 10 * 1024 * 1024  # 10 GiB（有效 RAM 预算：MemAvailable 与容器限额取较小值，不含 swap）
MIN_GPU_FREE_MIB = 6 * 1024  # 6 GiB（nvidia-smi 空闲显存）
CGROUP_UNLIMITED_THRESHOLD = 1 << 62  # cgroup v1 无限制哨兵值（约 9.2e18）之上视为无限制

# 三个显存配置（事先固定）：A=官方 crop 尺寸（不再改高）；B/C=若 OOM 再降长边。
CONFIGS = {
    "A": {"label": "official_crop", "target_long_edge": None},
    "B": {"label": "long_edge_392", "target_long_edge": 392},
    "C": {"label": "long_edge_280", "target_long_edge": 280},
}


# =====================================================================
# 基础工具
# =====================================================================

def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def image_size(path):
    import cv2
    img = cv2.imread(str(path))
    if img is None:
        raise RuntimeError(f"无法读取图像: {path}")
    h, w = img.shape[:2]
    return w, h


def _is_positive_int(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return v > 0
    if isinstance(v, float):
        return v.is_integer() and v > 0
    return False


# =====================================================================
# 清单与输入校验（模型加载之前）
# =====================================================================

def load_manifest(manifest_path) -> dict:
    return json.loads(Path(manifest_path).read_text(encoding="utf-8"))


def verify_frames(frames) -> list:
    """校验固定输入：数量、哈希、尺寸、顺序、非重复、pose 哈希。返回错误列表。"""
    errors = []
    if not frames:
        return ["清单无 frames"]
    if len(frames) < 2:
        errors.append(f"视图数不足（需要 ≥2，实际 {len(frames)}）")

    seen_img_sha = set()
    seen_img_path = set()
    expected_order = [f.get("id") for f in frames]

    for i, fr in enumerate(frames):
        tag = fr.get("id", f"#{i}")
        img_path = resolve_path(fr["image"])
        if not img_path.exists():
            errors.append(f"{tag}: 图像不存在 {img_path}")
            continue
        actual_sha = sha256_file(img_path)
        expect_sha = fr.get("image_sha256")
        if actual_sha != expect_sha:
            errors.append(f"{tag}: 图像哈希不符（期望 {expect_sha} 实际 {actual_sha}）")
        w, h = image_size(img_path)
        expect_size = fr.get("image_size")
        if expect_size is not None and [w, h] != [int(expect_size[0]), int(expect_size[1])]:
            errors.append(f"{tag}: 图像尺寸不符（期望 {expect_size} 实际 [{w},{h}]）")
        if actual_sha in seen_img_sha:
            errors.append(f"{tag}: 图像与之前帧重复（相同 SHA256）")
        if str(img_path) in seen_img_path:
            errors.append(f"{tag}: 图像路径与之前帧重复")
        seen_img_sha.add(actual_sha)
        seen_img_path.add(str(img_path))

        pose_path = resolve_path(fr.get("pose", ""))
        if not pose_path.exists():
            errors.append(f"{tag}: pose 不存在 {pose_path}")
        else:
            psha = sha256_file(pose_path)
            if psha != fr.get("pose_sha256"):
                errors.append(f"{tag}: pose 哈希不符（期望 {fr.get('pose_sha256')} 实际 {psha}）")
    return errors


# =====================================================================
# 模型加载（离线，无 fallback）
# =====================================================================

def load_model_offline(device: str, manifest: dict, stage_cb=None):
    """从本地 snapshot 离线加载 VGGT-1B，核对权重哈希。返回 (model, meta)。

    分阶段回调 stage_cb(stage_name)：在「构造+读权重」「搬设备」之间记录资源，
    便于定位 OOM/被杀发生在哪一步。保持官方 fp32 精度路径（不引入 torch_dtype/half）。
    """
    from vggt.models.vggt import VGGT

    def _stage(s):
        if stage_cb:
            stage_cb(s)

    m = manifest.get("model", {})
    repo_id = m.get("repo_id", "facebook/VGGT-1B")
    snapshot = m.get("snapshot")
    expect_wsha = m.get("weight_sha256")

    explicit_dir = m.get("snapshot_dir")  # 可选：显式指定已核验 snapshot 目录（绝对或包内相对）
    if explicit_dir:
        snap_dir = resolve_path(explicit_dir)
    else:
        hf_home = Path(os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface")))
        snap_dir = hf_home / "hub" / f"models--{repo_id.replace('/', '--')}" / "snapshots" / snapshot
    meta = {"repo_id": repo_id, "snapshot": snapshot, "snapshot_dir": str(snap_dir)}

    if not snap_dir.exists():
        raise RuntimeError(f"本地 snapshot 不存在：{snap_dir}（离线加载失败）")

    wpath = snap_dir / "model.safetensors"
    if not wpath.exists():
        raise RuntimeError(f"snapshot 中缺少 model.safetensors：{snap_dir}")
    actual_wsha = sha256_file(wpath)
    meta["weight_path"] = str(wpath)
    meta["weight_sha256_actual"] = actual_wsha
    if expect_wsha and actual_wsha != expect_wsha:
        raise RuntimeError(f"权重哈希不符：期望 {expect_wsha} 实际 {actual_wsha}")

    t0 = time.time()
    _stage("load_model_start")            # 构造 + 读权重之前（CPU 峰值起点）
    # 从已核验的本地 snapshot 目录加载（不是 repo_id），使哈希核对对象与真正加载对象一致；
    # 不联网、不换模型、不改变精度。
    model = VGGT.from_pretrained(str(snap_dir), local_files_only=True)
    _stage("load_model_cpu_done")         # 构造 + 权重读入 CPU 完成（CPU 峰值约在此）
    model = model.to(device)
    _stage("load_model_to_device_done")   # 已搬到设备（GPU 峰值约在此）
    model.eval()
    meta["load_seconds"] = round(time.time() - t0, 3)
    return model, meta


# =====================================================================
# 预处理
# =====================================================================

def resize_long_edge(images, target_long_edge, patch: int = PATCH):
    """按目标长边（宽图取宽）等比缩小并向下对齐到 patch 倍数。返回 (images, meta)。"""
    import torch.nn.functional as F
    if images.ndim == 4:
        S, C, H, W = images.shape
    else:
        raise ValueError(f"unexpected images ndim={images.ndim}")
    long_edge = max(H, W)
    if target_long_edge is None or long_edge <= target_long_edge:
        return images, {"applied": False, "long_edge": long_edge, "shape": (H, W)}
    scale = target_long_edge / long_edge
    new_h = max(patch, (int(round(H * scale)) // patch) * patch)
    new_w = max(patch, (int(round(W * scale)) // patch) * patch)
    x = F.interpolate(images, size=(new_h, new_w), mode="bilinear", align_corners=False)
    return x, {"applied": True, "scale": scale, "from": (H, W), "to": (new_h, new_w), "long_edge": target_long_edge}


def preprocess_images(image_paths, config_key: str):
    """loader 官方 crop → 可选降长边。返回 (images(S,3,H,W), meta)。"""
    from vggt.utils.load_fn import load_and_preprocess_images
    t0 = time.time()
    images = load_and_preprocess_images(image_paths, mode="crop")  # (S,3,H,W)，宽=518
    loader_shape = tuple(images.shape)
    cfg = CONFIGS[config_key]
    images, rmeta = resize_long_edge(images, cfg["target_long_edge"])
    meta = {
        "config": config_key,
        "config_label": cfg["label"],
        "loader_shape": loader_shape,
        "final_shape": tuple(images.shape),
        "resize": rmeta,
        "preprocess_seconds": round(time.time() - t0, 3),
    }
    return images, meta


# =====================================================================
# 推理
# =====================================================================

def run_inference(model, images, device: str):
    """六视图联合推理。前向输入显式搬移到目标设备并核对与模型设备一致。返回 (predictions, meta)。"""
    torch = _ensure_torch()
    if not device.startswith("cuda"):
        raise RuntimeError("D1 要求 CUDA；不自动切 CPU。")
    model.eval()
    images = _move_input_to_device(images, model, device)
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    with torch.inference_mode():
        with torch.cuda.amp.autocast(dtype=torch.float16):
            predictions = model(images)
    torch.cuda.synchronize()
    infer_seconds = time.time() - t0
    meta = {
        "infer_seconds": round(infer_seconds, 3),
        "peak_allocated_bytes": int(torch.cuda.max_memory_allocated()),
        "peak_reserved_bytes": int(torch.cuda.max_memory_reserved()),
        "autocast_dtype": "float16(aggregator)；heads 在 forward 内 enabled=False(fp32)",
        "input_device": str(images.device),
        "model_device": str(next(model.parameters()).device),
    }
    return predictions, meta


# =====================================================================
# 输出提取 / 过滤 / PLY
# =====================================================================

def flatten_view_colors(images_view):
    """images_view (3,H,W) → (H*W,3) uint8（与点图像素逐一对应）。"""
    torch = _ensure_torch()
    return (images_view.permute(1, 2, 0).reshape(-1, 3).clamp(0, 1) * 255).round().to(torch.uint8).cpu().numpy()


def build_points_colors(world_points, images):
    """world_points (S,H,W,3)、images (S,3,H,W) → points (N,3), colors (N,3) uint8，按 (s,h,w) 展平对齐。"""
    torch = _ensure_torch()
    pts = world_points.reshape(-1, 3).detach().float().cpu().numpy()
    cols = (images.permute(0, 2, 3, 1).reshape(-1, 3).clamp(0, 1) * 255).round().to(torch.uint8).cpu().numpy()
    return pts, cols


def finite_mask(pts: np.ndarray, conf: np.ndarray) -> np.ndarray:
    return np.isfinite(pts).all(axis=1) & np.isfinite(conf)


def conf_median_mask(conf: np.ndarray, fin: np.ndarray) -> tuple[np.ndarray, float]:
    """固定规则：保留「有限坐标 + conf ≥ 中位数」（top 50%，与官方 demo 默认一致）。

    返回 (mask, cutoff)；mask 同时包含有限掩膜与置信度条件，
    防止把高置信度但坐标 NaN/Inf 的点重新选入。"""
    if not fin.any():
        return np.zeros_like(fin, dtype=bool), float("nan")
    cutoff = float(np.median(conf[fin]))
    return (conf >= cutoff) & fin, cutoff


def write_ply_binary(path, points: np.ndarray, colors: np.ndarray):
    n = int(points.shape[0])
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {n}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "end_header\n"
    )
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        data = np.zeros(n, dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")])
        data["x"] = points[:, 0].astype("<f4")
        data["y"] = points[:, 1].astype("<f4")
        data["z"] = points[:, 2].astype("<f4")
        data["r"] = colors[:, 0].astype("u1")
        data["g"] = colors[:, 1].astype("u1")
        data["b"] = colors[:, 2].astype("u1")
        f.write(data.tobytes())


def verify_ply(path, expect_n, expect_points=None, expect_colors=None) -> dict:
    """重新读取 PLY，核对点数、有限值、实际 RGB 值与非退化范围。返回记录（ok=false 必须非零退出）。"""
    import open3d as o3d
    pcd = o3d.io.read_point_cloud(str(path))
    pts = np.asarray(pcd.points)
    cols = np.asarray(pcd.colors)
    if len(pts) == 0:
        return {"ok": False, "error": "PLY 复读为空"}
    finite = bool(np.isfinite(pts).all() and np.isfinite(cols).all())
    minp = pts.min(axis=0)
    maxp = pts.max(axis=0)
    extent = maxp - minp
    non_degenerate = bool(np.all(extent > 1e-6))
    n_ok = len(pts) == expect_n
    rgb_ok = len(cols) == expect_n and bool((cols >= 0).all() and (cols <= 1).all())
    pts_match = True
    col_match = True
    if expect_points is not None and n_ok:
        # PLY 写 float32，Open3D 复读为 float64；与 float32 化后的期望值比对（精确往返）
        pts_match = bool(np.allclose(pts, expect_points.astype(np.float32), atol=1e-5))
    if expect_colors is not None and rgb_ok:
        # PLY 写 uchar [0,255]，Open3D 复读为 float [0,1]
        col_match = bool(np.allclose(cols, expect_colors.astype(np.float64) / 255.0, atol=1.5 / 255.0))
    ok = n_ok and finite and non_degenerate and rgb_ok and pts_match and col_match
    return {
        "ok": ok,
        "points": int(len(pts)),
        "expect_n": int(expect_n),
        "colors": int(len(cols)),
        "finite": finite,
        "rgb_in_range": bool(len(cols) == expect_n and (cols >= 0).all() and (cols <= 1).all()),
        "points_match": pts_match,
        "colors_match": col_match,
        "extent": extent.tolist(),
        "non_degenerate": non_degenerate,
        "error": None if ok else "点数/有限值/RGB 值/范围不符",
    }


def decode_cameras(pose_enc, H: int, W: int):
    """pose_enc (S,9) → extrinsics (S,3,4), intrinsics (S,3,3)（OpenCV 相机-from-world）。"""
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri
    extri, intri = pose_encoding_to_extri_intri(pose_enc.unsqueeze(0), (H, W))
    return extri[0], intri[0]


# =====================================================================
# 资源采样 / 预检 / 原子落盘
# =====================================================================

def sample_resources() -> dict:
    """读 /proc/meminfo 的 MemAvailable（可用 RAM，不含 swap）、进程 RSS，及 nvidia-smi 空闲显存。"""
    res = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                k, _, v = line.partition(":")
                k = k.strip()
                if k in ("MemTotal", "MemFree", "MemAvailable", "SwapTotal", "SwapFree"):
                    res[k.lower() + "_kb"] = int(v.split()[0])
    except Exception as e:
        res["meminfo_error"] = str(e)
    try:
        with open(f"/proc/{os.getpid()}/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    res["vmrss_kb"] = int(line.split()[1])
                elif line.startswith("VmSize:"):
                    res["vmsize_kb"] = int(line.split()[1])
    except Exception as e:
        res["proc_status_error"] = str(e)
    # cgroup v1 容器内存限额（若存在）：有限限额时参与「有效 RAM 预算」计算
    for base in ("/sys/fs/cgroup/memory", "/sys/fs/cgroup"):
        lim_path = os.path.join(base, "memory.limit_in_bytes")
        if os.path.exists(lim_path):
            try:
                res["cgroup_memory_limit_bytes"] = int(open(lim_path, encoding="utf-8").read().strip())
                use_path = os.path.join(base, "memory.usage_in_bytes")
                if os.path.exists(use_path):
                    res["cgroup_memory_usage_bytes"] = int(open(use_path, encoding="utf-8").read().strip())
            except Exception as e:
                res["cgroup_memory_error"] = str(e)
            break
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            parts = [p.strip() for p in out.stdout.strip().split(",")]
            if len(parts) >= 3:
                res["gpu_mem_total_mib"] = int(parts[0])
                res["gpu_mem_used_mib"] = int(parts[1])
                res["gpu_mem_free_mib"] = int(parts[2])
        else:
            res["nvidia_smi_error"] = (out.stderr or "").strip()[:200]
    except Exception as e:
        res["nvidia_smi_error"] = str(e)
    return res


def _effective_mem_available_kib(res: dict):
    """有效 RAM 预算：系统 MemAvailable 与容器剩余限额（若有限）的较小值。

    有限 cgroup 限额存在但 usage 缺失/读取失败/非法时返回 None（无法确定剩余，显式失败）。
    真实 usage=0 为合法值。"""
    budget = res.get("memavailable_kb")
    limit = res.get("cgroup_memory_limit_bytes")
    if limit is not None and limit < CGROUP_UNLIMITED_THRESHOLD:
        usage = res.get("cgroup_memory_usage_bytes")
        if usage is None or not isinstance(usage, int) or usage < 0:
            return None
        remaining_kib = max(0, limit - usage) // 1024
        budget = remaining_kib if budget is None else min(budget, remaining_kib)
    return budget


def check_resources():
    """资源门槛检查。返回 (ok, detail)。门槛是防护预算，不是实测安全保证。"""
    res = sample_resources()
    detail = {
        "resources": res,
        "thresholds": {"min_mem_available_gib": MIN_MEM_AVAILABLE_KIB // (1024 * 1024),
                       "min_gpu_free_gib": MIN_GPU_FREE_MIB // 1024},
        "checks": [],
    }
    ok = True
    budget_kib = _effective_mem_available_kib(res)
    detail["effective_mem_available_kib"] = budget_kib
    if budget_kib is None:
        ok = False
        detail["checks"].append("有效 RAM 预算无法获取（无 MemAvailable，或存在有限 cgroup 限额但 usage 缺失/读取失败/非法）")
    elif budget_kib < MIN_MEM_AVAILABLE_KIB:
        ok = False
        detail["checks"].append(f"有效 RAM 预算不足: {budget_kib / 1024 / 1024:.2f}GiB < 10GiB（MemAvailable 与容器限额取较小值）")
    else:
        detail["checks"].append(f"有效 RAM 预算 OK: {budget_kib / 1024 / 1024:.2f}GiB >= 10GiB")
    if "gpu_mem_free_mib" in res:
        if res["gpu_mem_free_mib"] < MIN_GPU_FREE_MIB:
            ok = False
            detail["checks"].append(f"空闲显存不足: {res['gpu_mem_free_mib']}MiB < 6GiB")
        else:
            detail["checks"].append(f"空闲显存 OK: {res['gpu_mem_free_mib']}MiB >= 6GiB")
    else:
        ok = False
        detail["checks"].append("nvidia-smi 无法获取")
    detail["ok"] = ok
    return ok, detail


def write_meta_atomic(run_dir: Path, meta: dict):
    """原子写 meta.json（临时文件 + flush + fsync + os.replace）。"""
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp = run_dir / ".meta.json.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, allow_nan=False, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, run_dir / "meta.json")


def record_stage(run_dir: Path, meta: dict, stage: str):
    """更新阶段并原子落盘（含资源采样）。"""
    meta["stage"] = stage
    meta["stage_timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
    meta["resources"] = sample_resources()
    write_meta_atomic(run_dir, meta)


def _guard_run_dir(run_dir: Path) -> int:
    """轻量保护运行目录：非空即拒绝，不删除/清空/覆盖旧文件。返回 EXIT_OK 或 EXIT_EXISTS。"""
    run_dir = Path(run_dir)
    if run_dir.exists() and any(run_dir.iterdir()):
        print(f"[拒绝] 运行目录非空，不覆盖旧文件：{run_dir}", file=sys.stderr, flush=True)
        return EXIT_EXISTS
    return EXIT_OK


def _ensure_torch():
    """torch 的唯一导入点（供「资源不足时不进入重型导入」的计数测试）。"""
    import torch
    return torch


def _probe_cuda(torch, device: str):
    """CUDA 探测与设备信息查询（供替身测试打桩，不依赖真实 GPU）。返回 (ok, info)。"""
    if not torch.cuda.is_available():
        return False, {"error": "CUDA 不可用：D1 不自动切 CPU"}
    info = {"torch_version": torch.__version__}
    if device.startswith("cuda"):
        info["cuda_device"] = torch.cuda.get_device_name(0)
        info["cuda_driver"] = torch.cuda.get_device_capability(0)
    return True, info


def _move_input_to_device(images, model, device):
    """前向输入显式搬移到目标设备，并核对与模型设备一致。返回已搬移的 images。"""
    images = images.to(device)
    model_device = next(model.parameters()).device
    if images.device != model_device:
        raise RuntimeError(f"输入设备 {images.device} 与模型设备 {model_device} 不一致")
    return images


# =====================================================================
# 单配置完整流程
# =====================================================================

def run_config(manifest: dict, config_key: str, run_dir: Path, device: str = "cuda") -> int:
    # 1) 轻量：保护运行目录（非空即拒绝，不删/不清/不覆盖）
    run_dir = Path(run_dir)
    if _guard_run_dir(run_dir) != EXIT_OK:
        return EXIT_EXISTS
    run_dir.mkdir(parents=True, exist_ok=True)
    frames = manifest["frames"]

    # 2) 轻量：落 started 记录（此时尚未 import torch）
    meta = {
        "mode": "reconstruct",
        "config_key": config_key,
        "run_id": f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}",
        "pid": os.getpid(),
        "status": "started",
        "stage": "init",
        "exit_code": None,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "interpreter": sys.executable,
        "python_version": sys.version.split()[0],
        "numpy_version": np.__version__,
        "device": device,
        "resources": sample_resources(),
    }
    write_meta_atomic(run_dir, meta)  # 运行开始即落盘，被杀后可定位最后阶段

    # 3) 轻量：资源门槛——在 import torch / 初始化 CUDA / 导入 Open3D/vggt 之前
    ok, detail = check_resources()
    meta["resource_check"] = detail
    if not ok:
        meta.update({"status": "resource_failed", "exit_code": EXIT_RESOURCE})
        write_meta_atomic(run_dir, meta)
        for c in detail["checks"]:
            print(f"  [资源不足] {c}", file=sys.stderr, flush=True)
        return EXIT_RESOURCE

    # 4) 资源通过后才进入重型导入
    torch = _ensure_torch()
    ok_cuda, cuda_info = _probe_cuda(torch, device)
    if not ok_cuda:
        meta.update({"status": "error", "exit_code": EXIT_ERR, "error": cuda_info.get("error", "CUDA 不可用")})
        write_meta_atomic(run_dir, meta)
        print(cuda_info.get("error", "CUDA 不可用：D1 不自动切 CPU"), file=sys.stderr, flush=True)
        return EXIT_ERR
    meta.update(cuda_info)
    write_meta_atomic(run_dir, meta)

    # 5) 输入校验（模型加载前；首次 import cv2）
    errors = verify_frames(frames)
    if errors:
        meta.update({"status": "input_failed", "exit_code": EXIT_INPUT, "errors": errors})
        write_meta_atomic(run_dir, meta)
        for e in errors:
            print(f"  [输入校验失败] {e}", file=sys.stderr, flush=True)
        return EXIT_INPUT
    record_stage(run_dir, meta, "verify_input_done")

    try:
        # 2) 模型（分阶段记录：构造/读权重 → 搬设备）
        model, load_meta = load_model_offline(device, manifest, stage_cb=lambda s: record_stage(run_dir, meta, s))
        meta["model"] = load_meta
        record_stage(run_dir, meta, "load_model_done")
        # VGGT 源码版本
        try:
            import vggt
            meta["vggt_version"] = getattr(vggt, "__version__", "unknown")
        except Exception:
            meta["vggt_version"] = "unknown"

        # 3) 预处理
        record_stage(run_dir, meta, "preprocess_start")
        image_paths = [str(resolve_path(f["image"])) for f in frames]
        meta["input"] = {
            "n_views": len(frames),
            "ids": [f["id"] for f in frames],
            "original_size": [image_size(p) for p in image_paths],
        }
        images, pre_meta = preprocess_images(image_paths, config_key)
        meta["preprocess"] = pre_meta
        meta["input"]["final_size"] = list(images.shape)  # (S,3,H,W)
        print(f"  loader 输出: {pre_meta['loader_shape']} → 最终推理尺寸: {pre_meta['final_shape']}", flush=True)
        record_stage(run_dir, meta, "preprocess_done")

        # 4) 推理
        record_stage(run_dir, meta, "inference_start")
        predictions, infer_meta = run_inference(model, images, device)
        meta["inference"] = infer_meta
        record_stage(run_dir, meta, "inference_done")
    except torch.cuda.OutOfMemoryError as exc:
        meta.update({"status": "oom", "exit_code": EXIT_OOM, "error": f"CUDA OOM: {exc}"})
        write_meta_atomic(run_dir, meta)
        print(f"  [OOM] {exc}", file=sys.stderr, flush=True)
        return EXIT_OOM
    except Exception as exc:
        meta.update({"status": "error", "exit_code": EXIT_ERR, "error": str(exc), "traceback": traceback.format_exc()})
        write_meta_atomic(run_dir, meta)
        print(f"  [错误] {exc}", file=sys.stderr, flush=True)
        return EXIT_ERR

    # 5) 校验输出键与形状
    required = ["depth", "depth_conf", "world_points", "world_points_conf", "pose_enc"]
    missing = [k for k in required if k not in predictions]
    S = images.shape[0]
    H, W = images.shape[2], images.shape[3]
    shape_errors = []
    if not missing:
        if tuple(predictions["world_points"].shape) != (1, S, H, W, 3):
            shape_errors.append(f"world_points 形状 {tuple(predictions['world_points'].shape)} != (1,{S},{H},{W},3)")
        if tuple(predictions["depth"].shape) != (1, S, H, W, 1):
            shape_errors.append(f"depth 形状 {tuple(predictions['depth'].shape)} != (1,{S},{H},{W},1)")
        if tuple(predictions["pose_enc"].shape) != (1, S, 9):
            shape_errors.append(f"pose_enc 形状 {tuple(predictions['pose_enc'].shape)} != (1,{S},9)")
    if missing or shape_errors:
        errs = ([f"缺键: {missing}"] if missing else []) + shape_errors
        meta.update({"status": "output_invalid", "exit_code": EXIT_OUTPUT, "errors": errs})
        write_meta_atomic(run_dir, meta)
        for e in errs:
            print(f"  [输出无效] {e}", file=sys.stderr)
        return EXIT_OUTPUT

    # 6) 提取与解码
    wp = predictions["world_points"][0]  # (S,H,W,3)
    wpc = predictions["world_points_conf"][0]  # (S,H,W)
    depth = predictions["depth"][0]  # (S,H,W,1)
    depthc = predictions["depth_conf"][0]  # (S,H,W)
    pe = predictions["pose_enc"][0]  # (S,9)

    try:
        extri, intri = decode_cameras(pe, H, W)
    except Exception as exc:
        meta.update({"status": "output_invalid", "exit_code": EXIT_OUTPUT, "errors": [f"相机解码失败: {exc}"], "traceback": traceback.format_exc()})
        write_meta_atomic(run_dir, meta)
        print(f"  [输出无效] 相机解码失败: {exc}", file=sys.stderr, flush=True)
        return EXIT_OUTPUT
    if not (torch.isfinite(extri).all() and torch.isfinite(intri).all()):
        meta.update({"status": "output_invalid", "exit_code": EXIT_OUTPUT, "errors": ["相机参数含非有限值"]})
        write_meta_atomic(run_dir, meta)
        print("  [输出无效] 相机参数含非有限值", file=sys.stderr, flush=True)
        return EXIT_OUTPUT
    if not (intri[:, 0, 0] > 0).all().item() or not (intri[:, 1, 1] > 0).all().item():
        meta.update({"status": "output_invalid", "exit_code": EXIT_OUTPUT, "errors": ["内参焦距非正"]})
        write_meta_atomic(run_dir, meta)
        print("  [输出无效] 内参焦距非正", file=sys.stderr, flush=True)
        return EXIT_OUTPUT

    pts, cols = build_points_colors(wp, images)
    conf = wpc.reshape(-1).detach().float().cpu().numpy()
    fin = finite_mask(pts, conf)
    conf_keep, cutoff = conf_median_mask(conf, fin)

    per_view = {}
    for s in range(S):
        pv = wp[s].reshape(-1, 3).detach().float().cpu().numpy()
        cv = wpc[s].reshape(-1).detach().float().cpu().numpy()
        dfin = np.isfinite(pv).all(axis=1) & np.isfinite(cv)
        keep = dfin & (cv >= cutoff)
        per_view[frames[s]["id"]] = {
            "total_pixels": int(pv.shape[0]),
            "finite_valid": int(dfin.sum()),
            "kept_after_conf": int(keep.sum()),
        }

    n_finite = int(fin.sum())
    n_kept = int(conf_keep.sum())
    if n_finite == 0 or n_kept == 0:
        meta.update({"status": "no_valid_geometry", "exit_code": EXIT_OUTPUT, "errors": ["无有效几何点"]})
        write_meta_atomic(run_dir, meta)
        print("  [无有效几何] 过滤后点数为 0", file=sys.stderr)
        return EXIT_OUTPUT

    kept_pts = pts[conf_keep]
    kept_cols = cols[conf_keep]
    extent = kept_pts.max(axis=0) - kept_pts.min(axis=0)
    if not np.all(extent > 1e-6):
        meta.update({"status": "degenerate", "exit_code": EXIT_OUTPUT, "errors": [f"点云范围退化 {extent.tolist()}"]})
        write_meta_atomic(run_dir, meta)
        print("  [退化] 点云范围退化", file=sys.stderr)
        return EXIT_OUTPUT

    # 7) 保存完整预测数组（npz 压缩）+ PLY（汇集/逐视图）；可捕获失败一律 export_failed 非零退出
    t_export = time.time()
    arrays = {
        "depth": depth.detach().float().cpu().numpy(),
        "depth_conf": depthc.detach().float().cpu().numpy(),
        "world_points": wp.detach().float().cpu().numpy(),
        "world_points_conf": wpc.detach().float().cpu().numpy(),
        "pose_enc": pe.detach().float().cpu().numpy(),
        "images": images.detach().float().cpu().numpy(),
        "extrinsics": extri.detach().float().cpu().numpy(),
        "intrinsics": intri.detach().float().cpu().numpy(),
    }
    try:
        np.savez_compressed(run_dir / "predictions.npz", **arrays)

        # 汇集 PLY（过滤后 + 未过滤）；复读验收 ok=false 必须非零退出
        write_ply_binary(run_dir / "aggregated_points.ply", kept_pts, kept_cols)
        write_ply_binary(run_dir / "aggregated_points_unfiltered.ply", pts[fin], cols[fin])
        ply_verify = verify_ply(run_dir / "aggregated_points.ply", n_kept, expect_points=kept_pts, expect_colors=kept_cols)
        if not ply_verify["ok"]:
            raise RuntimeError(f"PLY 复读验收失败：{ply_verify['error']}")

        per_view_dir = run_dir / "per_view"
        per_view_dir.mkdir(exist_ok=True)
        for s in range(S):
            fid = frames[s]["id"]
            pv = wp[s].reshape(-1, 3).detach().float().cpu().numpy()
            cv = wpc[s].reshape(-1).detach().float().cpu().numpy()
            dfin = np.isfinite(pv).all(axis=1) & np.isfinite(cv)
            keep = dfin & (cv >= cutoff)
            write_ply_binary(per_view_dir / f"{fid}_points.ply", pv[keep], flatten_view_colors(images[s])[keep])
    except Exception as exc:
        meta.update({"status": "export_failed", "exit_code": EXIT_OUTPUT, "error": str(exc), "traceback": traceback.format_exc()})
        write_meta_atomic(run_dir, meta)
        print(f"  [导出失败] {exc}", file=sys.stderr, flush=True)
        return EXIT_OUTPUT

    meta.update({
        "status": "ok",
        "exit_code": EXIT_OK,
        "outputs": {
            "world_points_shape": list(wp.shape),
            "depth_shape": list(depth.shape),
            "pose_enc_shape": list(pe.shape),
            "dtypes": {k: str(v.dtype) for k, v in arrays.items()},
            "non_finite_world_points": int((~np.isfinite(wp.detach().float().cpu().numpy())).any(axis=-1).sum()),
            "per_view": per_view,
            "n_finite_total": n_finite,
            "n_kept_after_conf": n_kept,
            "conf_cutoff_median": cutoff,
            "extent_min": kept_pts.min(axis=0).tolist(),
            "extent_max": kept_pts.max(axis=0).tolist(),
            "extent_span": extent.tolist(),
            "ply_verify": ply_verify,
        },
        "coordinate_convention": {
            "world_points": "VGGT 联合预测世界坐标（尺度未验证，非米制/非双江口坐标）",
            "extrinsics": "OpenCV x右/y下/z前，camera-from-world [R|t]（pose_enc 解码）",
            "intrinsics": "fx/fy 像素焦距，主点 W/2/H/2",
            "note": "汇集点云=各视图世界点拼接，未做配准优化或融合",
        },
        "export_seconds": round(time.time() - t_export, 3),
    })
    record_stage(run_dir, meta, "export_done")
    write_meta_atomic(run_dir, meta)
    print(f"  [成功] 视图={S} 有限点={n_finite} 过滤后={n_kept} 范围={extent.tolist()}", flush=True)
    print(f"         峰值显存 allocated={infer_meta['peak_allocated_bytes']/1e9:.2f}GB reserved={infer_meta['peak_reserved_bytes']/1e9:.2f}GB", flush=True)
    return EXIT_OK


def run_preflight() -> int:
    """轻量资源预检：不 import torch/open3d，不加载模型。"""
    ok, detail = check_resources()
    print(json.dumps(detail, ensure_ascii=False, indent=2))
    if ok:
        print("[预检] 通过（防护预算，非实测安全保证）")
        return EXIT_OK
    print("[预检] 失败：资源不足或信息无法获取，不加载模型。", file=sys.stderr)
    return EXIT_RESOURCE


def run_load_only(manifest: dict, run_dir: Path, device: str = "cuda") -> int:
    """仅加载权重到设备并验证资源后退出；不预处理、不推理、不生成重建成功标记。"""
    run_dir = Path(run_dir)
    if _guard_run_dir(run_dir) != EXIT_OK:
        return EXIT_EXISTS
    run_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "mode": "load_only",
        "run_id": f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}",
        "pid": os.getpid(),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "started",
        "stage": "init",
        "device": device,
        "python_version": sys.version.split()[0],
        "resources": sample_resources(),
    }
    write_meta_atomic(run_dir, meta)

    # 资源门槛在 import torch / 导入 vggt 之前
    ok, detail = check_resources()
    meta["resource_check"] = detail
    if not ok:
        meta.update({"status": "resource_failed", "exit_code": EXIT_RESOURCE})
        write_meta_atomic(run_dir, meta)
        for c in detail["checks"]:
            print(f"  [资源不足] {c}", file=sys.stderr, flush=True)
        return EXIT_RESOURCE

    torch = _ensure_torch()
    ok_cuda, cuda_info = _probe_cuda(torch, device)
    if not ok_cuda:
        meta.update({"status": "error", "exit_code": EXIT_ERR, "error": cuda_info.get("error", "CUDA 不可用")})
        write_meta_atomic(run_dir, meta)
        print(cuda_info.get("error", "CUDA 不可用：D1 不自动切 CPU"), file=sys.stderr, flush=True)
        return EXIT_ERR
    meta.update(cuda_info)

    errors = verify_frames(manifest["frames"])
    if errors:
        meta.update({"status": "input_failed", "exit_code": EXIT_INPUT, "errors": errors})
        write_meta_atomic(run_dir, meta)
        for e in errors:
            print(f"  [输入校验失败] {e}", file=sys.stderr, flush=True)
        return EXIT_INPUT
    record_stage(run_dir, meta, "verify_input_done")

    try:
        model, load_meta = load_model_offline(device, manifest, stage_cb=lambda s: record_stage(run_dir, meta, s))
        meta["model"] = load_meta
    except torch.cuda.OutOfMemoryError as exc:
        meta.update({"status": "oom", "exit_code": EXIT_OOM, "error": str(exc)})
        write_meta_atomic(run_dir, meta)
        print(f"  [OOM] {exc}", file=sys.stderr, flush=True)
        return EXIT_OOM
    except Exception as exc:
        meta.update({"status": "load_error", "exit_code": EXIT_ERR, "error": str(exc), "traceback": traceback.format_exc()})
        write_meta_atomic(run_dir, meta)
        print(f"  [加载失败] {exc}", file=sys.stderr, flush=True)
        return EXIT_ERR

    meta.update({"status": "load_only_ok", "exit_code": EXIT_OK, "resources_after_load": sample_resources()})
    write_meta_atomic(run_dir, meta)
    print("[load-only] 仅完成权重加载与设备验证；未预处理、未推理，不构成重建成功。", flush=True)
    return EXIT_OK


def _reject_auto() -> int:
    """--auto 本轮明确拒绝（暂停自动降档），不启动 A，不进入重型导入。"""
    print("[拒绝] --auto 本轮已禁用（暂停自动降档）；请用 --preflight / --load-only / --config 手动运行。",
          file=sys.stderr, flush=True)
    return EXIT_ERR


# =====================================================================
# 入口
# =====================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description="D1 VGGT 六视图 RGB 重建（离线）")
    ap.add_argument("--manifest", default=None, help="清单路径；缺省按 samples.json → samples_cloud.json 顺序查找")
    ap.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--config", choices=list(CONFIGS), default=None)
    ap.add_argument("--preflight", action="store_true", help="仅资源预检，不 import torch/open3d，不加载模型")
    ap.add_argument("--load-only", action="store_true", help="仅加载权重到设备并记录资源后退出，不预处理/推理")
    ap.add_argument("--auto", action="store_true", help="[本轮拒绝] 自动降档已禁用，拒绝执行")
    args = ap.parse_args()

    # --preflight 在 import torch 之前执行
    if args.preflight:
        return run_preflight()

    # --auto 明确拒绝，不启动 A，不进入重型导入
    if args.auto:
        return _reject_auto()

    manifest_path = Path(args.manifest) if args.manifest else _default_manifest()
    if not manifest_path.exists():
        print(f"[错误] 清单不存在：{manifest_path}", file=sys.stderr, flush=True)
        return EXIT_INPUT
    manifest = load_manifest(manifest_path)
    if args.load_only:
        return run_load_only(manifest, Path(args.run_dir), args.device)

    config = args.config or "A"
    run_dir = Path(args.run_dir)
    if config != "A":
        run_dir = run_dir / f"run-{config}"
    return run_config(manifest, config, run_dir, args.device)


if __name__ == "__main__":
    sys.exit(main())
