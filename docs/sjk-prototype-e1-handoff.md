# 双江口草案预览（E1）交接与 E2 所需资料

日期：2026-11-02。本轮 E1 只做「可查看入口」，两份草案仍为未配准概念预览。

## E1 已就位（E2 可直接接手的文件）

| 文件/位置 | 说明 |
| --- | --- |
| `frontend/public/models/sjk-prototype-v0.1/` | 地形 GLB、概念组合 GLB、两份 scene_profile、`sources.json`（来源与哈希） |
| `frontend/public/data/scene_index.json` | 新增 2 条 `asset_role=prototype_model` 条目（scene_id：`sjk_team_terrain_draft_v0_1`、`sjk_facility_concept_v0_1`） |
| `frontend/src/lib/types.ts` | `SceneAssetRole` 新增 `'prototype_model'`；`SceneProfile.registration_status?`；`SceneLink.notice?` |
| `frontend/src/lib/data.ts` | `prototypeScenesFor(plant_id)` |
| `frontend/src/components/PlantDetail.vue` | 双江口详情新增两份草案卡片；旧参考底座入口保留 |
| `frontend/src/views/SceneView.vue` | 草案徽标按 `scene_badge` 显示；`canvasKey` 含 scene_id，切换场景强制释放旧 viewer；未配准草案坐标轴显示「文件米制轴 · 地理方向待核实」，旧场景保留「X 东 · Y 上 · Z 南」 |
| `frontend/scripts/check-data.ts` | DATA-06 放宽到 4 条；PROTO-01..04（哈希/根变换/未配准 frame 隔离） |
| `frontend/scripts/verify-prototype-scenes.mjs` | 浏览器验证脚本（需先起 preview 服务）；含故障注入 404/哈希 + 精确分类（仅豁免注入 URL/状态/阶段，非全局 404 白名单） |
| `evidence/sjk-prototype-e1/` | 实测截图 + `result.json`（32/32 通过，2026-11-02；含故障注入分类、草案轴文案、旧场景回归） |

坐标 frame：地形 `SJK_TEAM_FBX_FILE_METRE_UNREGISTERED_v1`；概念 `SJK_CONCEPT_STAGING_ONLY_v1`。
两者均 `formal_model_ready=false`、`registration_status=unregistered`、`fire_patch_overlay=false`，
与旧参考 frame `SJK_REFERENCE_UTM47N_EGM2008_v1` 互不匹配（run/state 连接会被坐标校验拒绝）。

## E2 需要向队友/Unity 侧索取的资料

1. **4 个拟合点 + 1 个独立复核点（同一地形网格）**：交接包根目录已附 `control_points_template.json`，其中 4 个拟合点（`corner_1`..`corner_4`）与 1 个复核点（`centre_holdout`）的 `fbx_file_metres` 已按**实际地形网格角点/中心**预填（四角 ±5000、中心 0,0，含实测高程）；`unity_world_xyz_m` 待队友回填。队友只需为每个点补 Unity 实际世界坐标。**若提供的是根节点局部坐标，必须同时提供 localToWorld**（含明确约定）；经纬度/绝对高程允许未知，不作为局部坐标联调前置条件。注意这些点是「同一网格的工程对应点，非测绘控制点」，**不能把概念设施摆放位置当作已知地形控制点**；`reference_sources/reference_points_wgs84.geojson` 的 3 个 OSM 参考点属旧参考底座，也不能自动当作新 FBX 的配准。
2. **相机交接（position/target/FOV 不单独视为完成）**：需同帧 RGB + 图像宽高及上下方向 + 内参 K（或实际投影矩阵）+ 明确方向的 world-to-camera / camera-from-world 矩阵 + 矩阵排列与坐标约定（列/行主序、左右手、Y 上）。position/target/FOV 只能作取景粗对齐；真实相机投影验证等 Unity 数据到齐后完成。
3. **构件放置依据**：7 项概念组件的摆放理由（哪些来自现场资料、哪些是建模假设）。当前只有大坝 315m 来自公开资料，其余形体/布置为假设；E2 若要在 Unity 中重排，需逐项确认依据。

## E2.0 已就位（本轮）

- `frontend/src/lib/terrain-mesh.ts` + `terrain-sampling.ts`：`TerrainMesh` + `raycastTerrain`（Möller–Trumbore 射线求交）复用 `sampleHeightOnTerrain`；新增 `validateTerrainMesh`（结构/索引/有限值守卫），NaN/Infinity 查询与零/非有限方向返回 null，非法网格显式抛错，命中点/距离/重心保证有限。纯 CPU、无 DOM/GPU、Node 可测，只读文件米制坐标。
- `frontend/scripts/verify-terrain-geometry.ts`：读真实地形 GLB 顶点/索引，核对 129×129、间距 78.125m、边长 10000m、反斜线对角线、射线命中/边界/未命中/非共面四边形对角线区分 + 输入守卫反例；结果 `evidence/sjk-terrain-geometry/result.json`（19/19）。
- **Unity 变换缺失 → 标记「待实测」**：适配器不内置单位矩阵、不默认配准；两份草案保持 `unregistered`、`fire_patch_overlay=false`。真实相机投影验证等 Unity 数据到齐后完成。

## 第一周口径

- 先建立**新的本地米制共用 frame**（如 `SJK_LOCAL_METRE_SHARED_v1`），把队友地形与概念构件放进去做联调；
  **地理精配准（UTM/EGM2008）单列后续**，在 4+1 拟合点核验通过前不改动 `SJK_REFERENCE_UTM47N_EGM2008_v1`。
- 仍缺：`SatelliteCapture.png`（地形贴图）。缺贴图期间前端如实显示「高程示意色地形」，不假装卫星图。
