# Fire-X Platform

Fire-X 新阶段团队协作工程。首轮前端基线为0.1.0；旧Fire-X仓库不再用于后续开发。仓库建立后，三位成员各自克隆；CodeBuddy只在本机克隆目录中实施，统一通过功能分支与Pull Request合并。具体规则见CONTRIBUTING.md。

## 第一轮前端（0.1.0）

已实现全国省级地图 / 省份列表 → 电厂详情 → 织金 v4 原始 GLB → 返回。7 个电厂是样例；只有织金具备三维场景。电网与应急资料暂缓，未接入火势、巡检算法或告警。

## Ubuntu + CodeBuddy 接手

将完整工程放到 `~/projects/firex-frontend`，在 VS Code/CodeBuddy 打开目录。建议 Node.js 22.12+ 或24；先查看 `node -v`，不要影响已有 Python/VGGT 环境。

```bash
npm ci
npm run test:data
npm run build
npm run dev
```

打开终端显示的地址，默认 `http://localhost:4173/`。关闭服务按 Ctrl+C。无需Unity、Python算法端、API Key或联网地图接口。运行时地图、模型与库均为本地资源；首次npm安装需要网络，主动点击来源链接才访问外网。

### 构建后运行静态演示

新克隆的仓库不跟踪dist，请先运行上面的npm ci与npm run build。

```bash
cd dist
python3 -m http.server 8080
```

打开 `http://localhost:8080/`。不要双击index.html（file://不能读取资源）。

## 演示路径

全国样例 → 贵州省 → 国能织金电厂 → 进入三维场景 → 厂区/全域切换 → 定位B01、CH01、CT-A → 拖动旋转、滚轮缩放 → 返回详情。

四川6个关联样例，云南4个；全国去重7个。北京市等未收录地区显示“暂无样例数据”；其他六厂显示“尚无三维模型”。

## 验收限制

云验收浏览器GPU禁用，因此**本轮只实际通过Canvas2D兼容显示的三维交互验收**。兼容模式解析同一GLB，地形粗采样原始顶点，厂区设施保留原几何，光照为近似。WebGL2可用时默认通过Three.js显示完整模型。不得称WebGL与显卡性能已通过。用户Ubuntu浏览器的GPU和真实窄屏验收是下一步。

## 文件导航

- docs/01-requirements.md：需求基线。
- docs/02-design.md：架构、坐标、生命周期与技术决策。
- docs/03-acceptance.md：验收与未验证清单。
- docs/04-codebuddy-prompt.md：首次接手提示词。
- docs/05-development-plan.md：迭代路线。
- evidence/：实际浏览器截图与资源检查。
- public/data/province_metadata.json：底图下载来源、哈希与CRS。
- public/models/zhijin-v4/：原始模型交接资源，manifest/registry原字段保留。

hash路由支持静态服务器，无rewrite要求。模型资源按scene_index及manifest相对路径解析。源码无后端、数据库、账号或凭据。

## 技术与署名

Vue3 + TypeScript + Vite，ECharts二维地图、Three.js局部三维；实际版本见package-lock.json。

底图来自GeoJSON.CN第三方分发与转换，来源页注明天地图：https://geojson.cn/data/atlas/tiandi 。模型包含GBA PartII对应数据（CC BY-NC4.0）、© OpenStreetMap contributors（ODbL）、Mapzen及源地形说明、厂方资料。完整来源和使用限制保留在scene_manifest.json。研究试建，不把未知几何与高度称为实测。
