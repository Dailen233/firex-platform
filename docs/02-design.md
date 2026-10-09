# 设计与决策

静态Vue前端，无算法或服务端请求。AtlasView→GeoJSON数据，SceneView→scene_index→manifest→GLB与对象表。

- AtlasView：省份、电厂选择在hash路由查询参数中；省份变更清除旧电厂。
- ProvinceMap：注册34真实省级面；原始8个MultiLineString境界线单独显示。
- PlantDetail：按项目ID关联；无模型不给假入口，保留来源差异。
- SceneCanvas/ModelViewer：进入创建，退出销毁；下载和校验原始GLB，用相机取景及raycast选择。
- SoftwareRenderer：只在无WebGL时使用。v4地形为401×401网格，按6格步长采样原始顶点；设施保留原三角形，近似着色与深度排序。不可作精细材质或遮挡评价。

## ADR

ADR-01：交接建议Vite+Vue3+TypeScript，适合CodeBuddy本机继续。锁文件保留，不安装Unity/Python/ROS2。

ADR-02：hash路由便于静态服务、刷新和返回，无rewrite配置。

ADR-03：资源同源本地读取；不每次调用第三方地图API。来源、CRS、哈希随工程保存。

ADR-04：模型根变换不动；只改camera与OrbitControls.target，避免后续火区/无人机错位。

ADR-05：默认WebGL2；无GPU明确降级。云浏览器报GL_RENDERER=Disabled，保留GPU验收缺口。

## 数据与坐标

7个样例按plant_id去重，related_province_codes筛选；GEM_*为自定义项目ID。国能织金八步项目→zhijin_pilot，不匹配金元织金。

2026-10-09默认无版本API下载成功，meta.date=2025/12/16；0.3.0仅为来源页版本说明。原始42要素完整保留，只拆分34面与8线，不手绘或简化国界。来源页审图号不是本页面审图结论。

底图EPSG:4490、点位EPSG:4326，未进行基准转换，仅省级浏览，非米级配准。

原GLB：6,717,876 bytes，38 meshes，340,572 triangles，无纹理。SHA256：ee33bc331332d7345bb73e3a1363f9ce49234da7ec3424996ec5670f07a3aa37。

X东、Y上、Z南，右手、米，UTM48N/EPSG:32648。x=E−581227.9057730192；z=2968452.584594382−N；y=h−1000。h基准未核实，y非离地高度。

34建筑候选不是34已验证建筑；B01拱顶30m与冷却塔150m为展示假设，烟囱240m有报告记载；地形色非植被/火险。

原manifest的readiness不改写。本轮运行结果在验收记录与evidence中单独保存。

## 生命周期与失败

卸载abort请求、取消requestAnimationFrame、移除指针/controls监听、断开ResizeObserver；释放geometry/material/texture/renderer和WebGL context，移除canvas。异步parse若在卸载后完成也释放新模型。

JSON超时20秒，GLB下载45秒；网络/格式/大小/哈希/节点不一致给失败与重试。SHA在HTTPS/localhost的crypto.subtle可用时额外核对；HTTP LAN仍校验大小和节点。

按变动渲染，阻尼期间短时继续；DPR上限1.5，不启用阴影。未宣称达到特定帧率。
