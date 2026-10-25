# C0：真实图像算法输入盘点（定点补查修订版）

- 日期：2026-10-24（首轮盘点 + 同日定点补查修订）
- 判定口径：**已找到**（路径存在、可读、类型核对）／**已检查**（本轮实际读取并核验内容）／**尚未运行**（存在但本轮未执行任何推理或加载模型）／**缺失**（在声明检查范围内不存在）。
- 本轮未运行模型、未训练、未下载权重、未安装新环境、未修改旧实验数据；`inference.py` 的 `load_model`（本地缓存失败会联网下载 `facebook/VGGT-1B`）**未调用**。

## 0. 检查范围（重要修正）

首轮盘点范围仅限 `firex-platform` 工作区，结论「工作区内无旧算法/权重」正确；但当时将其推广为「本机缺失」，**范围过宽，现予修正**。本轮按旧代码中的实际引用路径做定点只读检查：

- `/home/dailen/vggt`（旧算法仓库 + 环境 + 权重）— 已找到，目录可读
- `/home/dailen/vggt/runs/detect/train_full_v1/weights/best.pt` — 已找到，文件可读（5.2MB，`file` 识别为 Zip 归档，即 PyTorch `.pt`）
- `/home/dailen/Nutstore Files/Fire_X/demo_sequences`（含 `case01_single_fire/images/`、`poses/`）— 已找到，目录可读

未扫描用户主目录、整个磁盘或其他项目；上述路径未被任何忽略规则影响（显式指定路径不因 `.gitignore` 判缺）。以下目录仅确认存在、未逐一核验内容：`community_weights/`、`fire_detect_dataset/`、`fire_smoke_dataset_v2..v5/`、`raw_dataset/`、`outputs/`（150+ 历史结果目录）、`inputs/`。

## 结论先行（修订）

1. 旧算法资源本机**实际存在且环境可用**：Python 3.12.3 venv 已装 `torch 2.3.1`、`torchvision 0.18.1`、`ultralytics 8.4.19`、`opencv-python 4.11.0.86`、`numpy 1.26.4`、`vggt 0.0.1`（editable 指向 `/home/dailen/vggt`）。首轮「backend 未装 torch/opencv」只适用于新后端环境，不代表旧算法环境。
2. 存在**含可见火焰的 Unity 仿真巡检序列**（`case01` frame_0021 火焰清晰可见），第一阶段按 `simulation` 契约使用；现场实拍与 real 时间戳**不是本阶段必备条件**。
3. **二维检测基线可以立即开展**；**位姿定位复验在有真值的 case06_train 上可开展**；**动态火区重建尚不具备**（缺轮廓级真值、山地场景、时间、场景映射）。

---

## 1. 旧算法代码与权重（已找到，尚未运行）

### 1.1 位置与关键入口

代码位于 `/home/dailen/vggt/my_project/pipeline/`（约 100 个脚本，含 `firex_benchmark/` 子包）。本轮已检查 5 个指定脚本：

| 脚本 | 作用 | 依赖 | 联网风险 |
| --- | --- | --- | --- |
| `inference.py` | 加载 VGGT 预训练模型 + 前向推理（CUDA 下缩放对齐 patch、fp16 autocast） | torch、vggt | **高**：`load_model` 本地缓存失败即联网下载 `facebook/VGGT-1B`（本轮未调用） |
| `pipeline_run.py` | 主入口，`MODE="yolo"|"diff"`：VGGT→YOLO→bbox 缩放→3D 候选→多视角融合→JSON；diff 模式用 current/reference 差分 + 火色 HSV 先验 | torch、cv2、numpy、ultralytics、VGGT | 同上（经 `load_model`） |
| `firepoint_from_yolo.py` | `pick_3d_from_bbox`（bbox 内取 `world_points_conf` 最大像素为 3D 候选）+ `robust_fuse`（加权平均 + 距离阈值剔除离群） | torch、ultralytics、VGGT | 同上 |
| `multi_view_firepoint_localization.py` | **不用 VGGT**：YOLO 检火 → bbox 下 40% 中心为锚点 → 由 pose JSON 生成世界射线 → 多射线最小二乘求交 → 重投影误差；支持 GT 反投影搜索欧拉角顺序 | cv2、numpy、ultralytics | **无**（权重与输入全为本地）——最安全的复验入口 |
| `two_frame_vggt_depth_demo.py` | YOLO + VGGT 置信度精修锚点（bbox 下 40% 裁边内核）+ 两帧位姿射线三角化 | torch、cv2、numpy、ultralytics、VGGT | 同上（经 `load_model`） |

可复用部分（不依赖 VGGT、无联网）：`multi_view_firepoint_localization.py` 的位姿→射线→三角化/最小二乘链路；`pipeline_run.py` diff 模式的差分+火色先验 bbox 提取；`firepoint_from_yolo.py` 的融合函数。

硬编码路径（事实记录）：`DEFAULT_YOLO=/home/dailen/vggt/runs/detect/train_full_v1/weights/best.pt`、`DEFAULT_OUT_DIR=/home/dailen/Nutstore Files/Fire_X/outputs`、`TEAM_INPUT_DIR=…/Fire_X/inputs`。

### 1.2 权重（已找到，未加载）

- `/home/dailen/vggt/runs/detect/train_full_v1/weights/best.pt`（5.2MB）——自训练火点检测器（`train_full_v1`）。
- `/home/dailen/vggt/yolo11n.pt`、`yolo26n.pt`、`yolov8n.pt`——YOLO 基础权重（旧脚本曾以 `yolov8n.pt` 先通管线）。
- VGGT 预训练权重：仅见 `load_model` 走 HuggingFace 缓存；本地是否已有缓存**未核实**（本轮不触发下载）。

### 1.3 环境（已找到，已核对版本）

`/home/dailen/vggt/vggt-env`（venv，Python 3.12.3）：`torch 2.3.1`、`torchvision 0.18.1`、`ultralytics 8.4.19`、`opencv-python 4.11.0.86`、`numpy 1.26.4`、`pillow 12.1.1`、`huggingface_hub 1.4.1`、`vggt 0.0.1 (editable)`。事实记录，未据此宣称可运行（本轮未运行）。

## 2. 图像序列（已找到；抽查两帧）

### 2.1 demo_sequences 总览（`/home/dailen/Nutstore Files/Fire_X/demo_sequences/`）

| case | 帧数 | 火点 | 说明（notes.txt，已检查） | 主要用途 |
| --- | --- | --- | --- | --- |
| case01_single_fire | 24 | 1 | 相机从远到近、斜侧方缓慢接近 | 检测/定位复验（前段帧火焰不可见，见 2.2） |
| case02_double_fire | 20 | 2 | 左主火右次火，由远及近侧面靠近 | 多目标检测 |
| case03_turn_away_and_back | 26 | 1 | 固定机位只转视角：火出画→回画 | 视角变化对照（火本身不变） |
| case04_extinguish | 21 | 1→0 | 正常燃烧→明显减弱→无火，机位几乎不变 | **火区随时间变化** |
| case05_false_positive_challenge | 12 | 0（notes 标注） | 无火但高亮复杂背景、有烟无火（逐帧真值待核） | 无火候选（误报挑战，逐帧真值待核） |
| case06_forward | 6 | — | 无 notes | 定位（无 pose 文件，见 §7） |
| case06_forward_static | 6 | 0 | 与 case06_forward 同路径的无火对照 | 对照组 |
| case06_train | 嵌套 case001–003 | — | 每 case 含 images/poses/**notes（真值）** | **定位复验（有 GT）** |
| case07_text | 12 | — | 无 notes | 未核验 |
| state_machine_case | 11 | — | `manifest.json` 逐帧 role 标签 fire/miss_N/return_N | **状态机评测（带逐帧标签）** |

### 2.2 抽查两帧（case01_single_fire）

| 项 | frame_0001 | frame_0021 |
| --- | --- | --- |
| 原图路径 | `…/case01_single_fire/images/frame_0001.png` | `…/case01_single_fire/images/frame_0021.png` |
| 尺寸 | 2194×1000 RGB PNG | 2194×1000 RGB PNG |
| sha256 | `0c211e6087877658355ea46729863c35272c697e3770213bd1cd36546395af46` | `bbb66eae6476ca73c47f91b4b2fb7171f48f95fbfa88666d66de29a2a6c951ad` |
| 火焰可见性 | **未见火焰**（远距全景，变电站建筑/构架） | **火焰清晰可见**（橙黄火焰 + 黑烟，位于场区中部） |
| pose 文件 | `poses/frame_0001.json`（frame_id=1, fov_y=60.0, pos≈(28.50,2.60,2.81), euler≈(0,247.54,0)） | `poses/frame_0021.json`（frame_id=21） |

「能否看见火焰」为人工目视判定，未经检测器验证；case01 同序列内可见性变化由**相机接近**造成，不是火情变化。

### 2.3 变化类型区分（明确回答）

- **可用于检测或定位复验**（火不随时间变，仅视角/距离变）：case01、case02、case03、case06_train（有 GT）。
- **可用于验证火区随时间变化（物理演化）**：case04_extinguish（1→0）。
- **无火反例候选（误报挑战）**：case05（notes 标注无火、有烟/高亮背景；逐帧真值待核，**不当作已确认无火**），不表示火区变化。C1 检测：frame_0001 未检出、frame_0012 检出 fire 但真值待核。
- **可见性 / 检测缺失 / 恢复评测**：state_machine_case 的 `manifest.json` 逐帧 role（fire/miss_N/return_N）标签只标注「火焰是否在画面内」，**不能直接证明火势物理演化**。
- case01 前段「看不见火」属相机远离，**不**算火情变化。
- 旧单火点定位成绩（outputs/ 历史结果）不能直接当作新山地火区范围重建成绩。

## 3. 相机与位姿

### 3.1 两种 pose schema（已检查）

- **旧 schema**（case01–05，4 月采集）：`frame_id`、`image_width/height`、`fov_y_deg`、`camera_position{x,y,z}`、`camera_rotation_euler{x,y,z 度}`。仅欧拉角，**顺序有歧义**（Unity Transform.eulerAngles 内部常见 ZXY；旧脚本用 GT 反投影在 6 种顺序 × y 轴两式中搜索）。
- **新 schema**（state_machine_case，7 月采集；`TakePhoto.cs` 现版）：另加 `camera_forward/up/right` 三轴向量与 `camera_to_world_matrix` 4×4（Unity `localToWorldMatrix`，行主序 `data[0..15]`，`data[3]/[7]/[11]` 为平移）——**免去欧拉角顺序解码歧义**；但 Unity 左手系、相机轴向定义及与后端右手系 `camera_to_world` 的换算仍需验证（见 3.3）。
- 采集方式（`scripts-wang/TakePhoto.cs`，已检查）：按键截图 + 同帧写 pose；`ScreenCapture.CaptureScreenshot` + `WaitForEndOfFrame`；含 Windows 硬编码路径（`C:\Users\20244\Nutstore\1\Fire_X\...`）。

### 3.2 内参（可推导）

由 `fov_y_deg=60.0` + 分辨率推导（与旧脚本 `get_intrinsics` 同式）：`fy = H/(2·tan(30°)) ≈ 866.0px`，`fx = fy`（假设方形像素）、`cx=W/2`、`cy=H/2`；无畸变参数（默认 none）。分辨率与 FOV 逐帧在 pose 内给出，无「随意变化」迹象。

### 3.3 轴向 / 手性 / 单位 / 待核实约定

- Unity 世界系：**左手系、Y 向上、单位米**；相机 forward/up/right 语义按 Unity（forward=视线方向）。欧拉角单位度。
- 新后端上传契约要求**右手系** `camera_to_world`（列向量 `p_world=T@p_cam`，x 右/y 下/z 前）：Unity→契约的**手性/轴向换算公式尚未核实**（需专项推导与反投影验证），记为待验证项。
- `camera_to_world_matrix` 为 Unity 左手矩阵；转为右手矩阵前不能直接填入后端 metadata。

### 3.4 时间（缺失；第一阶段允许 simulation）

pose JSON **无拍摄时间字段**；`frame_id` 只是采集计数器，**不得当作时间**；文件修改时间（4 月/7 月）只说明采集批次，同样不是逐帧时间。→ 不满足 `real` 契约；按 **`simulation` 契约**处理时需自行定义 `simulation_time_origin_s` 与逐帧 `simulation_time_s`（第一阶段允许，需在切片方案中显式声明约定）。

### 3.5 场景归属与坐标系映射（缺失）

图像内容为 **Unity 变电站演示场景**（沙漠平地、构架/主变/建筑，见抽查截图），相机坐标尺度 ~30m。与双江口（10km 山地，EPSG:32647/EGM2008）或织金（EPSG:32648）地形**无已建立的映射**；不能直接对应，需单独的配准资料。

## 4. 真值与评估资料（已找到，范围有限）

- **单点真值**：`case06_train/case003/notes/fire_11.txt` = `x=-4.05, y=1.2, z=12.47`（Unity 世界坐标）；case06_train/case001、case002 亦有 notes/ 目录（本轮未逐一读取）。case01–05、state_machine_case 无点真值。
- **逐帧状态标签**：`state_machine_case/manifest.json`（已检查）为每帧标注 role（fire/miss_1..3/return_1..2），可作为「火焰是否在画面内」的评测真值。
- **历史评测**：`outputs/` 下 150+ 目录（anchor 扫描、batch_v3_eval、geometry sweep、`colored_output.ply` 等）——旧实验记录，仅作参考，不作为新场景成绩依据（评估资料，后续仅用于评估）。

## 5. 修正后的能力判定

| 目标 | 判定 | 依据与缺口 |
| --- | --- | --- |
| A. 两帧二维检测基线 | **可立即开展** | 材料：case01 frame_0021/0022（火焰清晰）+ `best.pt` + vggt-env；方法：ultralytics YOLO 推理或 `pipeline_run.py` diff 模式；反例集 case05/`case06_forward_static` |
| B. 相机/地形空间映射验证 | **部分可开展** | 已有逐帧位姿（新 schema 无歧义）+ 可推导内参；可在 case06_train（有 GT）复验 `multi_view_firepoint_localization.py` 射线定位（无 VGGT、无联网）。缺口：Unity→右手系换算未核实；demo 变电站场景与双江口/织金地形无映射 |
| C. 动态火区重建 | **尚不具备定量评估** | 缺：火区**轮廓级**真值（现仅单点；此限制的是**定量评估**，**不是先运行图像估计的硬性前提**）、山地场景序列（现仅变电站平地）、逐帧时间、场景映射；旧单点定位成绩不能外推为火区范围重建成绩 |

## 6. 最小离线验证切片建议（本轮不执行）

- **图像**：`…/case01_single_fire/images/frame_0021.png` 与 `frame_0022.png`（相邻两帧、火焰均清晰、各有 pose；两帧基线较小，定位精度预期有限）。
- **环境**：`/home/dailen/vggt/vggt-env`（已装 torch/ultralytics，**不再安装任何东西**）。
- **方法**：仅 `ultralytics.YOLO(best.pt)` 检测两帧 → 取 fire bbox 与下 40% 锚点像素；用 pose JSON + fov 推导内参 → 像素射线 → 两帧三角化（复用 `multi_view_firepoint_localization.py`/`two_frame_vggt_depth_demo.py` 中的纯几何函数）。**不调用 `inference.load_model`**（避免联网下载 VGGT）。
- **预期输出**：两帧各一个 fire bbox+conf+锚点 uv；一个三角化世界坐标点 + gap/重投影误差。**不产出火区轮廓**（缺轮廓真值，不伪造）。
- **仍缺输入**：火区轮廓级真值、山地场景序列与配准、逐帧时间约定、Unity→右手系换算核验、欧拉角顺序确认（case01–05 旧 schema）。

## 7. 未检查 / 不确定项

- `outputs/` 150+ 历史结果、`fire_detect_dataset`、`fire_smoke_dataset_v2..v5`、`raw_dataset`、`community_weights/`：仅确认存在，未核验内容。
- `case06_forward` 无 pose 文件（命名或缺失未查）；case06_train/case001–002 真值未读取。
- case01–05 旧 schema 的欧拉角顺序未定（本轮未运行 `--search-pose-modes`）；VGGT 本地缓存是否存在未核实。
- 「火焰可见性」为人工目视判定；`case06_forward_static`/`case07_text` 内容未看图核验。

---

## 附：非算法素材（继续单列，不得充作算法验证素材）

- `backend/scripts/upload_test_capture.py` 运行时生成的 32×24 纯色 RGB(200,60,40) PNG（接口测试）。
- `evidence/*.jpg`、`evidence/2026-10-24-dev-browser/*.png` 等界面截图。
- `backend/app/provider.py` 的预设 fixture 方形轮廓（`result_origin="fixture"`）。
- `frontend/public/models/*/reference_preview.png`、`scene_preview.png` 场景预览图。
