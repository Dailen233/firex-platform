# Fire-X 数字孪生动态建模 D0 准备度核对

日期：2026-10-25。依据：`docs/FireX_Dynamic_Twin_Requirements_and_Route_20261025.md`（正文为需求与候选路线参考，其中未实施方案不写成已完成能力）+ 本机只读核对证据。

本轮只做 D0：暂停单火点 C3，不做三角化定位，不运行模型/加载器，不启动 Unity 工程。只新增本文档与 `runtime-data/review/firex_dynamic_readiness.zip`。

证据分三级：**[已核实]**=本轮实际读取/执行命令得到；**[推断]**=由已核实事实推导，标注依据；**[未核实]**=尚无证据。

## 一、实际仓库状态（[已核实]）

- 分支 `feat/frontend-backend-layout`；HEAD `57831fea4290c77804bd3978450c4e852eb935c7`（C1 检查点），父提交 `4c45e6d`（B4）。
- 未提交：`experiments/c2-camera-geometry/`（C2 全部）、`docs/FireX_Dynamic_Twin_Requirements_and_Route_20261025.md`、`docs/image-estimation-readiness.md` 已随 C1 提交（`git status` 另见 `.codebuddy/`，未修改）。
- 与任务预期一致，无差异；保留全部已有工作，未回退、未覆盖。
- AGENTS.md 相关约束（[已核实]）：按需求编号最小实施；GPU/窄屏未测不得写通过；原 GLB/manifest/坐标约定保持原样；推送/部署/系统安装需用户授权。本轮遵守：未改业务代码、未启动服务、未安装任何依赖。

## 二、环境建模资源

### 2.1 VGGT 加载器与本地缓存（[已核实]）

| 项 | 结果 |
| --- | --- |
| 模型类 | `vggt.models.vggt.VGGT`（`nn.Module` + `PyTorchModelHubMixin`），repo_id `facebook/VGGT-1B` |
| 加载入口 | `my_project/pipeline/inference.py::load_model`：先 `VGGT.from_pretrained(repo_id, local_files_only=True)`，**失败后回退联网** `from_pretrained(repo_id)`（联网 fallback 分支存在，本轮未调用） |
| 本地缓存 | **存在**：`~/.cache/huggingface/hub/models--facebook--VGGT-1B/`，snapshot `860abec7937da0a4c03c41d3c269c366e82abdf9`，含 `config.json` 与 `model.safetensors`（blob `f164acf60724910d8fe1578bb499d800850c7bb0948db7555c413f9fbe60467e`，**4.7 GB**），总计 4.7 GB |
| 离线可用性 | **[推断]** 缓存完整（config+safetensors 齐全），`local_files_only=True` 应可离线加载；未实际执行加载验证（D1 事项） |
| 推理封装 | `run_inference`：CUDA 下把输入行对齐到 patch=14、目标高 256 省显存，fp16 autocast；输出 depth/depth_conf/world_points/world_points_conf/pose_enc |
| 重建脚本 | `reconstruction.py::extract_world_points` 只取 `world_points[0, 0]` **单张 point map（视角 0）**——与需求文档 §2.1 判断一致，不构成多视图融合 |
| 导出脚本 | `export_colored_pointcloud.py`：**把同一张 `inputs/reference.png` 复制为两路输入**（自述"为兼容单机位联调"），用 Open3D 写彩色 PLY——不是真实多视差基线，D1 不能直接复用其输入方式 |

### 2.2 GPU 与环境（[已核实]）

| 项 | 本机实测 | 与项目书差异 |
| --- | --- | --- |
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU，8188 MiB，驱动 580.178.04 | 项目书写 RTX4080；**以本机实测为准，4060 Laptop 8GB 显存对 VGGT-1B 多视图推理是实际约束** |
| 解释器 | `/home/dailen/vggt/vggt-env/bin/python`（3.12.3） | — |
| 关键包 | torch 2.3.1、torchvision 0.18.1、open3d 0.19.0、opencv 4.11.0.86、numpy 1.26.4、huggingface_hub 1.4.1、vggt 0.0.1（editable /home/dailen/vggt） | — |
| SAM / VGGT-Ω | **未找到**（pip 无 sam/segment-anything/omega 包；HF 缓存无 models--facebook--VGGT-Omega） | 不安装、不下载；VGGT-Ω 仅作后续对照分支 |

## 三、环境建模固定样本组（[已核实]位姿/哈希；[已目视]场景；[推断]重叠）

**首选：`case06_forward_static`（无火对照，6 帧，完整矩阵新 schema）**

- notes（[已核实]）：场景里无火；尽量使用和 case06_forward 相同或相近的无人机路径；每张图必须对应一份 pose；图像分辨率/FOV/相机参数无随意变化。
- schema（[已核实]）：`camera_position` + `camera_rotation_euler` + `camera_forward/up/right` + `camera_to_world_matrix`（row-major，C2 已核验列=right/up/forward/position）；`fov_y_deg=60`，2194×1000。
- 位姿（[已核实]）：无人机路径，位置 x∈[-6.66,3.06]、z∈[-12.61,-2.43]、y≈2.07–2.77；两两距离 2.8–11.6 m；全部 forward 的 y=0（平视）指向场景内部——绕场景的环绕式拍摄。
- 场景（[已目视] case6_01）：与 case04_extinguish/state_machine_case 同一 Unity 变电站场景家族（绝缘子串、构架、碎石地面、黄色标线）；**[推断]** 同一场景模型但光照/阴影配置不同（深蓝天空、长阴影），未做像素级同一性核验。
- 重叠判断依据（[推断]）：机位环绕同一场景、基线 2.8–11.6 m、均指向场景内部；**像素级重叠需 D1 实测确认**。
- 时间字段：**无**（pose 无 simulation_time/captured_at；frame 编号非时间）。

| 帧 | 图像 SHA256 | 位姿要点 |
| --- | --- | --- |
| case6_01 | `3b058163…` | pos(1.98,2.07,-2.43) fwd(-0.551,0,-0.835) |
| case6_02 | `01e73ec9…` | pos(3.06,2.07,-8.09) fwd(-1.000,0,0.030) |
| case6_03 | `c3c6ab9d…` | pos(1.84,2.07,-12.61) fwd(-0.612,0,0.791) |
| case6_04 | `a31d003c…` | pos(-4.00,2.77,-10.09) fwd(0.696,0,0.718) |
| case6_05 | `2b7d3171…` | pos(-6.66,2.77,-9.22) fwd(0.896,0,0.445) |
| case6_06 | `c1f12e1f…` | pos(-5.12,2.77,-3.37) fwd(0.602,0,-0.798) |

（完整 64 位哈希见包内 `sample_index.json`；pose 与图像同目录同名。）

备选（[已核实] schema 与位姿，[未核实] 像素重叠）：`state_machine_case` fire 帧 1–5（新 schema，机位两两 2.9–9.1 m，但含火焰=动态干扰）；`case06_train` case001–003（新 schema + 单点 GT，9/9/10 帧）。排除：state_machine miss_1/2/3（同源 case6_06、位姿完全相同）；case06_forward（无 pose 文件）。

## 四、动态候选帧清单（case04_extinguish，[已核实]+[已目视]）

- 21 帧/21 pose；**旧 schema**（仅 `camera_position`+`camera_rotation_euler`，**无** `camera_to_world_matrix`；[已核实] grep 0 命中）。
- 规则：21 帧 → 固定第 1/6/11/16/21 张（不按检测结果换样本）。
- **五帧相机位姿完全相同**（pos(1.66,2.59,-2.58)、euler(0,201.20,0) 五帧一致，[已核实]）——固定机位，零视差；初读图像以为有平移，以 pose 数据为准更正。
- 火焰可见性（[已目视] 5 帧）：frame_0001 大面积明火+黑烟；0006 仍大；0011 明显减弱；0016 进一步减弱；0021 **无火**。渐进熄灭与 notes 一致。
- **这是 Unity 仿真动画的视觉变化，不是物理变化真值**（[推断]，仿真渲染）；帧号/mtime 不作为拍摄时间（pose 无时间字段）。

| 帧 | 火焰可见性（目视） |
| --- | --- |
| frame_0001 | 大面积明火 + 黑烟 |
| frame_0006 | 大面积明火（形态略变） |
| frame_0011 | 明显减弱 |
| frame_0016 | 进一步减弱 |
| frame_0021 | 无火 |

## 五、动态输入与采集缺口

1. **动态火焰同步多视图缺失**（[已核实]）：全部已查 pose（case01/case04/case06_forward_static/case06_train·case003/state_machine_case）均无 `camera_id`、`observation_group`、`simulation_time`/`captured_at` 字段；所有序列为单相机移动或固定。**不能把相机移动的连续帧拼成瞬时体积。**
2. `TakePhoto.cs` 缺口（[已核实] 源码）：整屏 `ScreenCapture.CaptureScreenshot`；pose 取自 Inspector 指定的 `targetCamera`（未证明即截图相机）；无 camera_id、无拍摄时间、无观测组、无同一步多相机导出；row-major `localToWorldMatrix`。
3. `UnityCameraProbe.cs`（C2，[已核实] 源码）：单相机；记录版本/像素矩形/aspect/投影/localToWorldMatrix 与 WorldToScreenPoint/ScreenPointToRay，供层级 3 交叉验证；尚无输出（未运行 Unity）。
4. Unity 工程（[已核实] 存在，未启动/未修改）：`/home/dailen/Nutstore Files/Fire_X/output_unity_review/`——Unity **2022.3.62f3c1**（项目书写 2022.3.62f1c1，**版本号不一致，以工程实际为准**）、渲染管线 **URP**（`com.unity.render-pipelines.universal 14.0.12`）、含 `Assets/Scenes/{SampleScene,DigitalTwin,back_up}.unity`。是否即历史帧采集工程、由谁可运行：**[未核实]，需持有工程的队友提供/确认**；采集实现须按 URP 选择渲染路径，不直接套 `Camera.Render`。

## 六、能立即做 / 需补数据（面向 D1）

**可立即做（无需新数据、无需下载）**：
- D1 RGB→局部三维基线实验：用 `case06_forward_static` 6 帧 + 本地缓存 VGGT-1B（`local_files_only=True`，**禁用联网 fallback**）+ 现有 vggt-env（torch/open3d 齐备）。需新写独立入口：保留完整 depth/depth_conf/world_points/world_points_conf/pose_enc，导出彩色点云，排除天空/低置信度区域，记录 VRAM 与耗时（RTX 4060 8GB 是约束，必要时减视图数/分辨率并如实报告）。
- C2 换基/射线模块可直接用于把 pose 换到右手系做交叉核对（数学部分已验证）。

**需补数据/需他人提供**：
- 动态火焰粗三维包络（D3）：缺同时刻多相机 RGB+pose+camera_id+观测组+仿真时间 → 最小采集任务见下。
- 尺度/场景配准（R03）：缺 Unity 示例场景与双江口/织金的锚点对应（[未核实]，需有场景/测绘资料的成员）。
- Unity 引擎交叉验证（C2 层级 3）：需可运行工程的队友执行探针。

## 七、最小下一步（不做 D1 之外的实施）

1. **D1 最小切片（下一轮首选）**：新写 `experiments/d1-recon/` 本地只读加载入口（local_files_only，异常即失败、不联网），跑 `case06_forward_static` 6 帧，产出彩色点云 + 逐视图深度/置信度摘要 + VRAM/耗时日志；只做几何，不做配准进场景。
2. **同步多视图最小采集任务（交 Unity 同学）**：在 `output_unity_review`（2022.3.62f3c1/URP）中扩展 TakePhoto 式导出：同一仿真步、≥3 台有良好交会角的相机（另留 1 台作留出评估），每台输出 RGB+实际投影（pixelRect/aspect/投影类型）+camera_to_world+`camera_id`+`observation_group_id`+`simulation_time_s`；先做无火场景验证链路，再对火对象采集。
3. 两者并行：D1 证明"图像变模型"，采集任务补"同时刻多视图"；任一失败如实报告，不用预设几何顶替。

## 附录：本轮实际命令与范围

- 核对命令：`git branch/rev-parse/log/status`；`ls/find`（限 vggt、HF 缓存、demo_sequences、Fire_X 目录）；`nvidia-smi --query-gpu`；`pip list`（vggt-env）；sha256sum（样本图像/pose）；python 内联脚本（位姿提取/两两距离）。
- 未执行：任何模型加载/推理（含 `load_model`/`from_pretrained`）、Unity 启动、依赖安装、全盘扫描、业务回归（未改业务代码）。
