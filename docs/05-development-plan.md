# 迭代路线与协作方式

CodeBuddy主开发；此对话负责需求、路线、提示词、验收与修正建议，不无提示跨阶段扩展。

需求编号/边界 → CodeBuddy Plan核对 → 小范围实现 → 构建/必要测试 → 浏览器证据 → 本对话验收 → 修复/通过 → 独立git提交 → 下一迭代。

每次处理一个可验收目标，先查现有功能，不重生成。保留需求、设计、变更和验收记录，不为形式增加不适合三人大创规模的文件。

| 阶段 | 目标 | 结束条件 |
|---|---|---|
| R1（本次） | 地图、详情、真实模型、返回、证据 | 兼容模式交互通过，GPU/窄屏开放 |
| R1.1（本机） | 接手仓库，WebGL/窄屏复现和最小修复 | 浏览器与视口截图、两轮进退、性能观察 —— 已完成 2026-10-09 |
| R2 | 演示开关、贴地火区、暂停/重置、地图演示告警 | R1.1通过，先冻结mock fire_state接口 |
| R3 | 场景管线、地面约束与候选身份改进 | 来源/坐标/误差指标可核查，不先追纹理 |
| R4 | 无人机路径与巡检图像输出 | 帧+位姿+时间戳可复现，先验证接口 |
| R5 | 图像估计火情动态更新 | 真值/估计分开，未知/遮挡明确，误差可核查 |
| R6 | 风险、应急与电网 | 队友资料恢复并通过规则/来源验收 |

R2不是有依据的真实火势预测。R3–R5可根据团队资源调整，记录理由；本周末先保证R1.1演示稳定。

分工：用户通过CodeBuddy做前端和场景/火情显示；成员王维护地图与点位来源（本次边界已经取得，需完善版本说明）；另一位队友的电网/应急资料暂缓，恢复时按确认分工接入。

本机工程建议 `~/projects/firex-frontend`。先检查已有git；有则沿用，未建再 `git init -b main`。远程由用户选择一个已有Gitee/GitHub账号，不本轮擅自绑定。暂时模型规模可直接git跟踪，后续大影像/视频再制定资源方案。

提交前：npm run test:data、npm run build、git diff --check；确认实际改动范围，建议首轮提交信息 feat: add province atlas and zhijin v4 viewer。

## R1.1 完成状态（2026-10-09）

R1.1 本机复现已完成：基础功能、硬件 WebGL2 渲染与桌面响应式视口验收通过；长期 GPU/内存、真实移动设备、实地精度仍未验证（详见 docs/03-acceptance.md 本机补充验收）。下一阶段为 R2：先冻结并设计 mock fire_state 接口，尚未实现；R2 目标为演示开关、贴地火区、暂停/重置、地图演示告警。

## R3 完成状态（2026-10-11）

R3 场景管线已完成配置解耦与双江口公开 DSM 参考底座接入：场景名称/资源路径/相机/统计/能力开关统一由 `scene_profile.json` 读取，viewer 不再硬编码织金值；双江口第 8 厂以包内 OSM 坝体质心为地图参考点，正式模型 `formal_model_status="awaiting_file"`。用户本机手动确认参考底座浏览流程通过（详见 docs/03-acceptance.md）。

织金合成火情演示覆盖层回归未通过（播放超 50 秒未见火区，原因未定位），本轮暂停演示入口并保留契约/校验/叠加能力，不修复渲染、不扩展火势算法。正式模型待接入；真实配准精度、动态重建、量化性能、真实移动设备仍未验证。约 100 km² 继续保留建议研究区口径。

## 工程整理（2026-10-24）

前端从仓库根迁入 `frontend/`，建立 `backend/`、`contracts/` 骨架与 `runtime-data/` 运行产物位置。前端统一入口改为 `npm --prefix frontend ci / run test:data / run build / run dev`；数据校验脚本 `frontend/scripts/check-data.ts` 已与 cwd 解耦，evidence 仍写回仓库根。资源 SHA 与坐标校验保持一致，未改模型字节与场景约定。

## 后端 B1（2026-10-24）

实现最小后端：`GET /health`、`POST /api/v1/runs`、`GET /api/v1/runs/{run_id}`、`GET /api/v1/runs/{run_id}/state`。Python 3.12 + FastAPI + Pydantic v2 + SQLite，独立 `backend/.venv`（uv 管理，`pyproject.toml` + `uv.lock`）。运行数据默认 `runtime-data/backend/`，支持 `FIREX_BACKEND_DATA_DIR` 覆盖，路径与启动 cwd 无关。

时间契约已明确并持久化：`time_basis` 用机器可读值 `simulation_relative` / `utc_anchored`；仿真运行保存 `simulation_time_origin_s`（模拟器全局时钟起点），真实运行保存带时区的 `time_origin_utc`（UTC 起点），观测时间换算公式见 `backend/app/time_contract.py` 与 `contracts/README.md`。`created_at` 仅表示服务端创建记录时间，不充当观测或拍摄起点。

统一入口 `uv --directory backend sync --locked / run --locked uvicorn app.main:app / run --locked python -m pytest -q` 已在仓库根原样验证。9 个 pytest 通过，真实 HTTP 创建两类运行并重启后时间配置仍可查询（详见 `backend/README.md`）。上传接收、原图保存、任务工作器、fixture 火区、图像算法及前端 API 接入留待后续；`algorithm_mode` 保持 `unconfigured`。

## 后端 B2（2026-10-24）

实现图片上传与接收记录查询：`POST /api/v1/runs/{run_id}/captures`（multipart `file` + `metadata` JSON 字符串）与 `GET /api/v1/captures/{capture_id}`。新增依赖 python-multipart、Pillow（锁文件更新）。metadata 定义相机内参（像素单位、左上原点、`fx/fy/cx/cy`）、轴向（右/下/前）、`camera_to_world` 4×4（行存储、列向量乘法）、仅支持 `none` 畸变模型；时间沿用 B1 契约。原件按 `captures/<capture_id>/` 保存（不重新编码），原子落盘 + `BEGIN IMMEDIATE` + 唯一约束保证幂等与并发一致性；未知字段、非 JPEG/PNG、尺寸/场景/坐标/时间不符、超限均拒绝。接收记录 `status=queued`（等待处理器，不自动 completed），运行状态仍 `no_observation`。25 个 pytest 通过，真实 HTTP 上传/重试/重启再查询已验证（详见 `backend/README.md` 与 `contracts/conventions.md`）。原图后处理、任务工作器、fixture 火区、图像算法及前端接入留待后续。

## 后端 B2 定点审查与收尾（2026-10-24）

多轮定点审查修复四类可靠性问题：

1. **中断恢复**：进程在“文件目录已落位、SQLite 未提交”之间退出会留下 `captures/<capture_id>/` 孤儿目录。落位前在临时目录写入服务端接收清单 `manifest.json`（`format_version`/`capture_id`/`run_id`/图片字节数与哈希/规范化 metadata 哈希/`received_at`），由服务端生成、不接受客户端指定。重试同一 `capture_id` 时核对路径边界、目录类型（拒绝符号链接）、清单及实际文件哈希：一致则复用原件并保留首次 `received_at`；不同运行/内容返回 409 并保留目录；缺/坏清单、归属不明或内容不完整时保留目录并返回 500 `RECOVERY_ERROR`，不直接删除。
2. **服务识别**：`/health` 增加 `service="firex-backend"`，离线上传客户端先核对再 POST，避免误连被其他项目占用的端口。
3. **JPEG 完整解码**：`image_validation` 由仅 `verify()`（不加载像素）改为 `load()` 强制完整解码，截断 JPEG 返回 422 `INVALID_IMAGE`；保存仍用上传原始字节，不重编码/旋转/裁切。
4. **相机旋转手性**：`CameraPose` 增加 `det(R) ≈ +1` 校验，拒绝镜像变换（`det=-1`）；世界系采用右手规范，Unity 左手坐标须在上传适配端显式转换。

新增子进程中断恢复、隔离模拟响应服务识别、截断 JPEG、镜像矩阵等回归用例，**39 个 pytest 通过**。`algorithm_mode` 仍 `unconfigured`，capture 仍 `queued`，run/state 仍 `no_observation`。

## 后端 B3：串行后台处理与持久化状态快照（2026-10-24）

1. **初始化时机**：`create_app` 不再初始化数据库；`import app.main`、构造应用、导出 OpenAPI 均无数据库/工作器副作用（OpenAPI 导出不再依赖 `/tmp` 库）。数据库初始化与工作器启停移入 FastAPI `lifespan`（已登记的 B3 前置项随之解决）；测试通过 `with TestClient(...)` 进入/退出生命周期并使用临时数据目录。
2. **串行工作器**：单服务进程、单工作器线程；上传接口只保存原件与待处理记录。计算在独立线程运行，不阻塞事件循环；关闭时停止领取新任务并等待当前任务结束。
3. **提供者与来源**：`ProcessingProvider` 接口 + `fixture` 提供者；`FIREX_PROCESSING_MODE` 区分 `unconfigured`（默认，不处理）与 `fixture`（显式开启）。fixture 结果固定 `result_origin=fixture`、提供者 `fixture@1.0`，附“接口测试数据，不代表图像重建”说明；客户端不能通过上传字段指定来源。
4. **任务与快照持久化**：任务 `queued→processing→completed/failed`，持久化处理时间、错误、提供者版本；短事务领取任务。结果含 `observation_time_s`（时间契约）、`produced_at`、`result_origin`、`provider_version`、`evidence_capture_ids`、稳定 `patch_id` 与局部 XZ 多边形（首尾闭合、有限值）。`/runs/{run_id}/state` 从持久化结果读取：新运行 `no_observation`/`revision=0`，较新观测递增 revision，较旧观测只入历史；重复上传/完成不重复发布；失败保留最近有效快照；重启把遗留 `processing` 重置为 `queued`。
5. **验证**：**48 个 pytest 通过**（39 既有 + 9 后台处理），真实 HTTP fixture 链路（两帧同 patch 不同几何、revision 递增、重复 GET 稳定）已验证。

## B3 前置项（已解决）

源码审查曾发现 `app.main` 在模块级 `app = create_app()` 导入时即初始化默认数据库；本轮已随生命周期调整一并解决（见上）。

## 前端 B4：fixture 前后端显示链路（2026-10-24）

1. **连接与轮询**：新增 `lib/backend.ts`（后端 OpenAPI 薄适配 + 运行时响应校验：patch_id、顶点有限值、最少顶点、首尾闭合）与 `lib/run-connection.ts`（共享连接状态 + 单轮询器，约 1s、串行、超时、会话/run 身份核对防串扰；重复 revision 不替换快照、不刷新“新观测”时间）。连接入口 `RunConnectionPanel.vue`，地图/详情/场景共用同一连接会话。
2. **显示语义**：`no_observation` 显示“尚无观测”（不解释为确认无火）；fixture 持续标注“接口测试数据，不代表图像重建”并展示 revision/观测时间（相对仿真原点）/提供者版本；`algorithm_mode=unconfigured` 与 `processing_mode=fixture` 分开显示；最近成功查询与最近新 revision 分开记录。
3. **三维覆盖层**：`viewer.ts` 覆盖层为“闭合轮廓沿实际地形三角面重心插值采样”（透明三角填充本轮因质心越界问题停用），采样失败/超范围明确提示、不静默用 y=0；同一 patch_id 新 revision 实际更新顶点（无 ID/等级/强度签名去重）；覆盖层替换正确 dispose、不重载静态 GLB；新增“聚焦火区”取景（不动几何坐标）。双江口 `scene_profile.json` 开启 `fire_patch_overlay`。
4. **坐标映射依据**：后端 `FirePatch.geometry [x,z]` 与前端 `FireRing.ring_xz [x,z]` 同属 `SJK_REFERENCE_UTM47N_EGM2008_v1` 局部帧（X=E−E0 东、Z=N0−N 南、米，Y=H_EGM2008−2000 由地形采样），恒等映射，不换轴/缩放/平移；参考点：大坝代表点局部 (0,0)、fixture 方形中心 (100,200) 恰为 50m 网格顶点（i=102,j=104）。
5. **验证**：前端 `vue-tsc` + `vite build` 通过、`test:data` 26 项通过；后端 52 pytest 通过。真实后端 fixture + 系统 Chrome（临时 Playwright 方案）冒烟 16/16：连接、快照（revision 2 / obs 19 / fixture）、覆盖层映射、地图→详情→场景往返、断开清画布（像素级 72→0）、轮询不重载 GLB（fetches=1）、无控制台错误/失败请求；固定相机下同 patch 轮廓由 28 增至 126 像素（obs 1→19，约 4.5×），证明顶点实际更新。

## 前端 B4 定点修复（2026-10-24，审查反例）

1. **严格校验身份/状态/版本**：`backend.ts` 拆出纯契约层 `backend-contract.ts`（可被 `check-data.ts` 单测）。`validateRunState` 校验非负整数 revision、`input_source`/`state_status`/`time_basis` 枚举及其一致性、observation 必填 `observation_time_s`/`result_origin`/`provider_version`/非空 patches、证据 ID 为字符串、几何闭合有限；`fetchRun`/`fetchRunState` 核对返回 `run_id` 与请求一致；`validateSnapshotAgainstRun` 核对 plant/scene/asset/frame/input_source/时间配置等不可变绑定；`revisionDecision` 只接受更新 revision（回退/重复不覆盖、不刷新新观测时间）；`snapshotToActiveFirePatches` 增加 plant_id 校验，observation 要求明确且匹配的坐标系（缺失即拒绝）。`run-connection` 连接阶段用独立 AbortController 取消、时间标签按 `time_basis`（utc_anchored 不显示“相对仿真原点”）。
2. **清空覆盖层刷新画布**：`setFirePatches([])` 删除覆盖层后 `requestRender()`；成功/清空后清除失效 `overlayIssue`（回调改为 `string|null`）。
3. **采样贴地 + 停用填充**：新增 `terrain-sampling.ts` 纯函数，按实际地形三角面重心插值取高（替代角点双线性），并停用不准确的质心透明填充，保留闭合轮廓。非共面 2×2 合成地形反例已单测（(25,25) 双线性 25 → 实际三角面 0）。
4. **浏览器验证真实失败**：重写 `e2e-*.mjs` 共享 harness，任意未预期异常/断言失败/控制台错误/页面错误/非预期失败请求均非零退出（graceful abort 除外）；revision/观测时间/来源用精确 `dd` 断言；等待带截止时间并输出诊断；写请求前核对服务身份；快照按 run 保存；`analyze_fire_pixels.py` 做像素级断言。
5. **验证**：前端 build 通过、`test:data` 26 项、后端 52 pytest；真实 fixture 正常链路 16/16、像素级断开清画布（72→0）、同 patch 轮廓 28→126 且停止上传后稳定、异常拦截 7/7（身份/绑定/回退/迟到响应）、坏 run 非零退出（exit 1）。

## 前端 B4 同视角断开补证（2026-10-24）

- 原 `e2e-fixture-link.mjs` 顺序为“聚焦截图 → 地图往返 → 场景重挂载 → 断开截图”，断开前后截图来自两次场景挂载、不同相机，不能证明固定画面清空。
- 已重排：先完成地图/详情往返 → 返回场景确认同一 run（revision=2）与覆盖层 → 聚焦火区等待相机稳定 → 同一挂载内断开（相机/画布尺寸/视角不变）→ 等待清空重绘 → 截图。
- 像素断言（`analyze_fire_pixels.py`，新增 `assert-terrain`）：断开前轮廓 72 像素、地形 280610 像素；断开后轮廓 0 像素、地形 283607 像素——火区消失而地形仍正常显示。
- 真实 fixture run `f52f38bb-ab59-4129-a7fe-618d8f520acf`：17/17 检查通过、exit 0；快照 `snapshot.json`、截图 `disconnect-before/after.png` 已存。旧截图（不同相机视角）标为历史证据。

## 本轮变更与修复

- CR-01：GPU禁用，新增明确兼容显示，保留GPU验收缺口。
- CR-02：省级边界实际下载成功，仍保留列表降级。
- 缺陷：目录已读时边界重试被缓存返回阻断；调整条件，故障恢复复验通过。
- 缺陷：兼容提示插入后v-else依附错误，模型失败时重试按钮缺失；改为独立!manifest条件，复验通过。
