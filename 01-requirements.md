# 首轮需求基线

R1 / 0.1.0，2026-10-09。依据：开发启动说明、成员王第二轮验收及用户本轮指令。后续CodeBuddy主开发，此对话负责规划、提示词和验收；电网、应急暂缓。

| 编号 | 需求 | 验收 | 实现 |
|---|---|---|---|
| FR-01 | 读取7样例，ID唯一，保留容量口径、来源和空值 | 数据检查和详情 | data.ts / PlantDetail |
| FR-02 | 真实省级地图可点；边界缺失保留列表 | 地图点击与故障注入 | ProvinceMap / AtlasView |
| FR-03 | 关联省份筛选、全国去重、无数据空态 | 贵州1/四川6/云南4/全国7 | AtlasView |
| FR-04 | 详情、容量来源差异、真实模型可用状态 | 织金及向家坝详情 | PlantDetail |
| FR-05 | plant_id→scene_id→manifest→GLB，相对地址解析 | 模型加载与预检 | SceneView / viewer.ts |
| FR-06 | 旋转、缩放、厂区/全域、对象点选与证据标签 | 实際拖动、滚轮、B01/CH01 | SceneCanvas / viewer.ts |
| FR-07 | 返回保留选择，重复两轮无画布累积 | 两轮进退与DOM计数 | 路由与dispose |
| FR-08 | 加载进度、失败提示、重试 | 缺失GLB后恢复 | SceneCanvas |
| NFR-01 | 模型字节与根变换不变，局部坐标约定不变 | 哈希、节点、根变换校验 | check-data / viewer |
| NFR-02 | 卸载释放画布、事件、循环与GPU资源 | DOM检查+审查；GPU待本机 | viewer / ProvinceMap |
| NFR-03 | 桌面、窄屏、键盘操作 | 桌面实测；窄屏CSS实现，设备待测 | style.css / 列表与select |
| NFR-04 | 构建、预检与可运行交付 | npm run build / test:data | package / 锁文件 |

首轮不含：登录、后端、数据库、全国全量电厂、真实火势、无人机、巡检图像估计、告警、电网、应急。未知火情必须“尚未接入”。

CR-01：GPU禁用时从同一原始GLB几何提供明确标注的Canvas2D兼容显示，不能替代GPU和实地精度验收。

变更规则：新增需求先说明目的、涉及编号、数据与验收方式，更新基线/变更记录，再让CodeBuddy实施。不要一次跨轮堆功能。
