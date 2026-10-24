# Fire-X Platform

Fire-X 新阶段团队协作工程。首轮前端基线为0.1.0；旧Fire-X仓库不再用于后续开发。仓库建立后，三位成员各自克隆；CodeBuddy只在本机克隆目录中实施，统一通过功能分支与Pull Request合并。具体规则见CONTRIBUTING.md。

## 第一轮前端（0.1.0）

已实现全国省级地图 / 省份列表 → 电厂详情 → 织金 v4 原始 GLB → 返回。8 个电厂是样例；织金具备正式三维场景（试建），双江口水电站正式模型待接入、可浏览公开 DSM 山地参考底座。场景名称、路径、相机、统计与能力开关统一由 `scene_profile.json` 配置读取。电网与应急资料暂缓，未接入火势、巡检算法或告警。

## 目录结构

- `frontend/`：现有 Vue3 前端（src、public、index.html、package.json、锁文件、Vite/TS 配置、`scripts/check-data.ts`）。所有前端命令从此目录运行。
- `backend/`：Fire-X 后端（B1 最小运行创建与持久化查询），FastAPI + SQLite（见 `backend/README.md`）。
- `contracts/`：接口约定、OpenAPI 快照与样例（由后端生成，见 `contracts/README.md`）。
- `runtime-data/`：本机运行产物，已忽略，不提交。
- 根目录：README、AGENTS、CONTRIBUTING、docs、evidence、.github 与 Git 配置。
- `evidence/` 仍输出到仓库根，不会生成 `frontend/evidence`。

## Ubuntu + CodeBuddy 接手

先克隆新仓库，在 VS Code/CodeBuddy 打开目录：

```bash
mkdir -p ~/projects
cd ~/projects
git clone git@github.com:Dailen233/firex-platform.git
cd firex-platform
code .
```

建议 Node.js 22.12+ 或24；先查看 `node -v`，不要影响已有 Python/VGGT 环境。

```bash
npm --prefix frontend ci
npm --prefix frontend run test:data
npm --prefix frontend run build
npm --prefix frontend run dev
```

打开终端显示的地址，默认 `http://localhost:4173/`。关闭服务按 Ctrl+C。无需Unity、Python算法端、API Key或联网地图接口。运行时地图、模型与库均为本地资源；首次npm安装需要网络，主动点击来源链接才访问外网。

本机若因 inotify 实例上限（`fs.inotify.max_user_instances`）导致 `dev` 报 `EMFILE: too many open files`，改用轮询开发模式（默认关闭、代价略高 CPU）：

```bash
npm --prefix frontend run dev:polling
```

## 后端（B1+B2+B3：运行、时间契约、上传与串行后台处理）

后端已实现运行创建/查询、时间契约、图片上传与同帧 metadata 保存，以及串行后台处理（fixture 提供者）与持久化状态快照；**图像算法与火势估计未接入**（`GET /health` 返回 `algorithm_mode=unconfigured`）。需 Python 3.12 与 uv：

```bash
uv --directory backend sync --locked                                        # 首次：创建 backend/.venv 并安装锁定依赖
uv --directory backend run --locked uvicorn app.main:app --host 127.0.0.1 --port 8002
uv --directory backend run --locked python -m pytest -q                     # 后端测试（52 项）
uv --directory backend run --locked python scripts/export_openapi.py        # 导出 contracts/openapi.json
```

服务默认 `127.0.0.1:8001`（本机该端口被其他项目占用，实际验证改用 `8002`）；运行数据默认落在 `runtime-data/backend/`（已忽略，可用 `FIREX_BACKEND_DATA_DIR` 覆盖）。`GET /health` 返回 `service="firex-backend"`，离线上传脚本据此核对目标服务，避免误连其他项目。创建运行与上传（仿真需带 `simulation_time_origin_s`，真实需带带时区的 `time_origin_utc`；`capture_id` 首次生成后复用）：

```bash
curl -s http://127.0.0.1:8002/health
curl -s -X POST http://127.0.0.1:8002/api/v1/runs -H "Content-Type: application/json" \
  -d '{"plant_id":"GEM_HYDRO_SHUANGJIANGKOU","scene_id":"shuangjiangkou_reference_terrain","asset_version":"reference-v1","coordinate_frame_id":"SJK_REFERENCE_UTM47N_EGM2008_v1","input_source":"simulation","simulation_time_origin_s":10.0}'
curl -s -X POST http://127.0.0.1:8002/api/v1/runs/{run_id}/captures \
  -F "file=@interface-test.png;type=image/png" -F "metadata=$(cat capture_metadata.json)"
curl -s http://127.0.0.1:8002/api/v1/runs/{run_id}/state
curl -s http://127.0.0.1:8002/api/v1/captures/{capture_id}
```

离线上传脚本：`uv --directory backend run --locked python scripts/upload_test_capture.py --base-url http://127.0.0.1:8002 <run_id>`（不同帧用 `--frame N`，重试复用同 ID）。

显式开启 fixture 后台处理（`unconfigured` 为默认，不产生结果）：`FIREX_PROCESSING_MODE=fixture uv --directory backend run --locked uvicorn app.main:app --host 127.0.0.1 --port 8002`，随后上传多帧并查询 `/api/v1/runs/{run_id}/state`。fixture 结果仅为接口测试数据，不代表图像重建。

详见 `backend/README.md` 与 `contracts/`。

## 前端连接已有运行（B4：fixture 前后端显示链路）

前端可连接后端已有 run，轮询快照并在三维场景显示火区覆盖层（fixture 接口测试数据）。`algorithm_mode=unconfigured`（未接图像算法）与 `processing_mode=fixture`（接口测试提供者）分别展示。坐标映射为同一局部 XZ 帧（X 东、Z 南，米；Y 由地形采样），不换轴/缩放/平移。

启动顺序（本机 8002 后端 + 4173 前端，Vite 代理 `/api`、`/health` 到后端）：

```bash
# 1. 后端（fixture）
FIREX_PROCESSING_MODE=fixture uv --directory backend run --locked uvicorn app.main:app --host 127.0.0.1 --port 8002
# 2. 前端（inotify 受限时改用 dev:polling）
npm --prefix frontend run dev
# 3. 创建运行
curl -s -X POST http://127.0.0.1:8002/api/v1/runs -H "Content-Type: application/json" \
  -d '{"plant_id":"GEM_HYDRO_SHUANGJIANGKOU","scene_id":"shuangjiangkou_reference_terrain","asset_version":"reference-v1","coordinate_frame_id":"SJK_REFERENCE_UTM47N_EGM2008_v1","input_source":"simulation","simulation_time_origin_s":10.0}'
# 4. 上传两帧（不同观测时间 -> 同一 patch_id 不同几何）
uv --directory backend run --locked python scripts/upload_test_capture.py --base-url http://127.0.0.1:8002 --frame 1 --simulation-time 11.0 <run_id>
uv --directory backend run --locked python scripts/upload_test_capture.py --base-url http://127.0.0.1:8002 --frame 2 --simulation-time 29.0 <run_id>
```

浏览器打开 `http://127.0.0.1:4173/#/scene/shuangjiangkou_reference_terrain`，在“连接已有运行”输入 `run_id` 并连接；fixture 快照显示“接口测试数据，不代表图像重建”与 revision/观测时间/提供者版本，三维场景沿地形显示闭合火区轮廓（“聚焦火区”对准）。地图与详情同步显示接口测试状态。

### 构建后运行静态演示

新克隆的仓库不跟踪dist，请先运行上面的 `npm --prefix frontend ci` 与 `npm --prefix frontend run build`。

```bash
cd frontend/dist
python3 -m http.server 8080
```

打开 `http://localhost:8080/`。不要双击index.html（file://不能读取资源）。

## 演示路径

全国样例 → 贵州省 → 国能织金电厂 → 进入三维场景 → 厂区/全域切换 → 定位B01、CH01、CT-A → 拖动旋转、滚轮缩放 → 返回详情。

四川7个关联样例，云南4个；全国去重8个。北京市等未收录地区显示“暂无样例数据”；双江口显示“正式模型待接入 + 浏览山地参考底座”，其他无模型电厂显示“尚无三维模型”。

## 验收限制

云验收浏览器GPU禁用，因此**本轮只实际通过Canvas2D兼容显示的三维交互验收**。兼容模式解析同一GLB，地形粗采样原始顶点，厂区设施保留原几何，光照为近似。WebGL2可用时默认通过Three.js显示完整模型。不得称WebGL与显卡性能已通过。用户Ubuntu浏览器的GPU和真实窄屏验收是下一步。

## 文件导航

- docs/01-requirements.md：需求基线。
- docs/02-design.md：架构、坐标、生命周期与技术决策。
- docs/03-acceptance.md：验收与未验证清单。
- docs/04-codebuddy-prompt.md：首次接手提示词。
- docs/05-development-plan.md：迭代路线。
- docs/06-model-delivery-requirements.md：正式模型交付要求（双江口）。
- docs/07-performance-check-method.md：场景加载与交互检查方法。
- evidence/：实际浏览器截图与资源检查。
- frontend/public/data/province_metadata.json：底图下载来源、哈希与CRS。
- frontend/public/models/zhijin-v4/：原始模型交接资源，manifest/registry原字段保留。
- frontend/scripts/check-data.ts：数据与资源校验，路径与 cwd 无关，产物写回仓库根 `evidence/`。

hash路由支持静态服务器，无rewrite要求。模型资源按scene_index及manifest相对路径解析。前端无后端、数据库、账号或凭据；后端 B1 已实现（FastAPI + SQLite，见 `backend/README.md`），图像处理尚未接入。

## 技术与署名

Vue3 + TypeScript + Vite，ECharts二维地图、Three.js局部三维；实际版本见package-lock.json。

底图来自GeoJSON.CN第三方分发与转换，来源页注明天地图：https://geojson.cn/data/atlas/tiandi 。模型包含GBA PartII对应数据（CC BY-NC4.0）、© OpenStreetMap contributors（ODbL）、Mapzen及源地形说明、厂方资料。完整来源和使用限制保留在scene_manifest.json。研究试建，不把未知几何与高度称为实测。
