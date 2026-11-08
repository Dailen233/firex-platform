# Fire-X D1：VGGT-1B 六视图 RGB 局部三维重建基线（离线）

在 `/home/dailen/projects/firex-platform` 仓库根、用 `/home/dailen/vggt/vggt-env/bin/python` 运行。
固定输入：`case06_forward_static` 无火对照 6 帧（`samples.json`，图像+pose 双哈希，运行前强制核验）。
建模只使用 RGB；pose 仅用于输入绑定与后续核对，不参与生成结果。

## 命令（外部终端）

```bash
# 1) 资源预检：不 import torch/open3d、不加载模型；不足即失败（退出码 5）
/home/dailen/vggt/vggt-env/bin/python experiments/d1-recon/reconstruct.py --preflight

# 2) 加载验证：仅加载权重到设备并记录资源后退出；不预处理/推理，不生成重建成功标记
/home/dailen/vggt/vggt-env/bin/python experiments/d1-recon/reconstruct.py \
    --load-only --run-dir runtime-data/d1-recon/load-only-<新目录>

# 3) 单配置重建（建议加 -u 即时刷日志；每次用新目录，不覆盖）
/home/dailen/vggt/vggt-env/bin/python -u experiments/d1-recon/reconstruct.py \
    --config A --run-dir runtime-data/d1-recon/run-A-<新目录>
```

- `--auto`：**本轮明确拒绝执行**（退出码 1），不再启动 A、不自动降档/重试。
- `--config`：A=官方 crop 尺寸（238×518，不再改高）；B=长边 392；C=长边 280（仅在有明确 CUDA OOM 时才可能降档，本轮不降档）。

## 退出码

0=成功；1=其它错误；2=输入/清单校验失败（模型加载前）；3=CUDA OOM（唯一可考虑降档的情况）；
4=输出无效/导出失败；5=资源预检失败；6=子进程超时（保留）；7=运行目录非空（不删除/清空/覆盖旧文件）。

## 阶段证据（本轮新增）

`run_config`/`run_load_only` 在运行一开始就**原子写** `meta.json`（临时文件 + fsync + `os.replace`），
并在每个阶段更新 `meta["stage"]` + 资源采样（进程 VmRSS、`/proc/meminfo` MemAvailable、`nvidia-smi` 空闲显存）：

`init → verify_input_done → load_model_start → load_model_cpu_done → load_model_to_device_done →
load_model_done → preprocess_start → preprocess_done → inference_start → inference_done → export_done`

即使进程被 SIGKILL，也能从 `meta.json` 定位最后完成的阶段；不会把「缺少日志的推断」写成已核实。
父进程（VS Code）一并被杀时无法保证记录退出码——这种情况下后续只能把未完成运行标为「中断/原因待核实」，不编造 -9。

## 离线策略

- 模块顶部**强制**设 `HF_HUB_OFFLINE=1`、`HF_HUB_DISABLE_TELEMETRY=1`（覆盖环境里可能已存在的 0）。
- 从已核验的本地 snapshot 目录 `snapshots/860abec7…` 加载：`VGGT.from_pretrained(str(snap_dir), local_files_only=True)`，
  使「哈希核对对象」与「真正加载对象」一致（同一 `model.safetensors` = `f164acf6…`）；不传未指定 revision 的 `repo_id`。
  **无联网 fallback**，加载失败即报错。
- 资源守卫在 `import torch` / 初始化 CUDA / 导入 Open3D/vggt **之前**执行（torch 延迟导入）；资源不足写明确终态、退出 5，不进入重型导入。

## 资源门槛（防护预算，非实测安全保证）

- `MemAvailable`（`/proc/meminfo`，不含 swap）≥ 10 GiB；`nvidia-smi` 空闲显存 ≥ 6 GiB。
- 信息无法获取或不足 → 明确失败（退出码 5），不加载、不自动降低门槛。
- `gc.collect`/`empty_cache` 不作为解决系统 RAM 不足的保证。

## 内存峰值来源（只读核对本机实现，未修改旧 VGGT 包）

本机：huggingface_hub 1.4.1、safetensors 0.7.0、vggt 0.0.1（editable）。

1. **`torch_dtype` 不受支持**：`PyTorchModelHubMixin.from_pretrained` 签名无 `torch_dtype`；其 `**model_kwargs`
   最终传给 `VGGT.__init__(img_size=518, patch_size=14, embed_dim=1024, enable_camera/point/depth/track=True)`，
   而 `VGGT.__init__` 不接受 `torch_dtype`/`dtype` → 传 `torch_dtype=torch.float16` 会 `TypeError`。
   因此本轮**保持官方 fp32 精度路径，不 `.half()`**。
2. **`map_location` 受支持**：`_from_pretrained(map_location="cpu")` 可经 `from_pretrained(..., map_location="cuda")`
   传入，最终 `safetensors.torch.load_model(..., device=map_location)`（safetensors≥0.4.3）可把权重直接读到 GPU。
3. **三处内存峰值**（hub_mixin.py:773 / 789 / 822）：
   - `model = cls(**model_kwargs)`：VGGT 构造，CPU fp32 全量参数 ≈ 4.7 GB（随机初始化，随后被覆盖）。
   - `safetensors.torch.load_model(..., device="cpu")`（默认）：权重读入 CPU，再叠加一份 ≈ 4.7 GB。
   - `model.to("cuda")`：GPU ≈ 4.9 GB，同时 CPU 模型仍驻留。
   - 综合：默认路径 CPU 峰值可达构造 + 读权重两份，GPU 峰值 ≈ 4.9 GB。
4. **后续若要优化，需单独验证的路径**（本轮未做）：`map_location="cuda"`（省掉 CPU 读权重峰值，但构造峰值仍在）；
   半精度（需改 VGGT 构造方式或构造后 `.half()`，并验证精度与 8 GB 显存是否足够）。

## 输出

`<run_dir>/`：`meta.json`（阶段/资源/参数/形状/dtype/非有限计数/过滤前后点数/范围/相机）、`predictions.npz`
（depth、depth_conf、world_points、world_points_conf、pose_enc、images、extrinsics、intrinsics）、
`aggregated_points.ply`（过滤后汇集点云）、`aggregated_points_unfiltered.ply`、`per_view/*.ply`。

- 汇集点云 = 各视图世界点**拼接**，非配准优化或融合；坐标是「VGGT 联合预测世界坐标，尺度未验证」，非米制/双江口坐标。
- 置信度过滤固定为「有限坐标 + conf ≥ 中位数（top 50%）」，在看结果前固定；汇集/逐视图/统计使用同一掩膜，
  不会把高置信度但坐标 NaN/Inf 的点重新选入。
- 前向输入显式搬移到目标设备并核对与模型设备一致（记录 `input_device`/`model_device`）。
- PLY 导出后用 Open3D 复读，核对点数、有限值、实际 RGB 值与非退化范围；`ok=false` 必须 `export_failed` 非零退出，不写 `status=ok`。
  NPZ/相机解码/逐视图导出的可捕获失败同样记录明确终态并非零退出。

## 能力边界

仅证明「六张不同视角 RGB 能生成可检查的局部三维几何」；不宣称度量精度、动态火焰重建、配准或融合；
输出点数多/写文件成功 ≠ 重建质量通过。pose 记录相同 ≠ 已核验截图相机绑定。

## 测试

```bash
/home/dailen/vggt/vggt-env/bin/python experiments/d1-recon/test_reconstruct.py
```
21 项替身回归（不加载真实模型）：输入哈希/重复/尺寸、展平索引、输出形状/缺键、无有效几何、写失败、
六视图覆盖、PLY 复读；以及审核修复守卫——资源不足时重型导入与模型加载均为 0 次、早期阶段落盘、
`--auto` 拒绝且不进入重型导入、非空目录（无 meta 也）拒绝且旧文件字节不变、强制离线、高置信 NaN 坐标不保留、
前向输入搬设备与设备一致性、PLY 复读 `ok=false` 必 fatal、从本地 snapshot 目录（非 repo_id）加载。
