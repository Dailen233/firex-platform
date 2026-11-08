# C2：相机轴向、手性转换与像素射线核验

建立可复核的相机几何基础（不生成火点定位或火区结果）。

## 范围与约束

- 沿用 vggt-env 的 Python + NumPy；旧算法仓库与原始数据只读。
- 不改前后端业务代码、坐标契约或模型资产；不写 run/state；不运行 VGGT；不做三角化/火区轮廓/时间推定。
- 输出写入 `runtime-data/c2/`（gitignore 覆盖）。
- 实验坐标系用独立名称（`demo_rh`），不使用双江口/织金 `coordinate_frame_id`，不宣称地理配准。

## 坐标约定与公式（列向量）

| 名称 | 定义 |
| --- | --- |
| Unity 世界 | 左手系，X右 / Y上 / Z前（官方文档确认） |
| Unity 相机局部轴 | +X右(`transform.right`) / +Y上(`transform.up`) / +Z前(`transform.forward`) |
| demo_rh 世界点 | `[Unity x, Unity y, -Unity z]`（右手系，X右/Y上/Z朝观察者） |
| 后端相机轴 | x右 / y下 / z前（右手系，x×y=z） |

换基矩阵（**世界换基**与**相机轴换基**分开定义）：

- `W = diag(1, 1, -1)`：Unity 世界 → demo_rh（翻转世界 Z）。
- `C = diag(1, -1, 1)`：后端相机 → Unity 相机（翻转相机局部 Y，把「y下」变回「y上」）。

组合（列向量，先右乘相机轴换基、再左乘世界换基）：

```
R_demo = W @ R_unity @ C        # 3×3 旋转
t_demo = W @ t_unity            # 3×1 平移
p_demo = R_demo @ p_cam + t_demo
```

- 逆变换：`p_cam = R_demoᵀ @ (p_demo - t_demo)`（R_demo 正交，R_demoᵀ=R_demo⁻¹）。
- 单位：位置/平移为 Unity 世界米；角度为度（仅 FOV）；旋转无量纲。
- 投影（右手相机 x右/y下/z前）：`u = cx + fx·x/z`，`v = cy + fy·y/z`；`z` 为沿光轴正深度。
- 像素→射线（相机系，未归一化，z=1）：`[(u-cx)/fx, (v-cy)/fy, 1]`；中心像素 → `[0,0,1]`（前向）。

### 连续坐标与像素索引（两者是不同操作，不混用）

本轮投影坐标 `u/v` 定义为「左上原点的**连续图像坐标**」，主点 `cx=W/2、cy=H/2`。

- **Unity 连续屏幕坐标（左下原点，y 向上）→ 连续图像坐标（左上原点，y 向下）**：
  `u_image = x_screen`；`v_image = H - y_screen`（连续翻转，y 关于 H 对称）。
  实现：`camera_geometry.unity_screen_to_image(x_screen, y_screen, H)`；逆变换 `image_to_unity_screen(u, v, H)`。
- **离散数组行号翻转** `j_top = H-1-j_bottom` 是**另一种操作**（用于数组索引），不用于上述连续投影比较。
  实现：`camera_geometry.flip_row_index_discrete(j_bottom, H)`。
- 若误用 `H-1-y` 当连续翻转，中心点误差 1 像素（测试 `test_old_H_minus_1_formula_center_error_is_1px` 已锁定此失败）。

## 矩阵存储顺序

`camera_to_world_matrix.data` 为 **row-major**（`data[r*4+c] = M[r][c]`，来自 `TakePhoto.cs` 的 `Matrix4x4Data`）。
`localToWorldMatrix` 的列 0/1/2/3 = `[right, up, forward, position]`（官方文档 + 数据双重确认）。

## 内参假设（未经证明，单独列出）

- 方形像素 `fx = fy`；主点居中 `cx=W/2, cy=H/2`（连续图像坐标主点）；无畸变（Unity 为针孔相机，默认无径向畸变，官方文档确认）。
- `fy = (H/2) / tan(fov_y_deg/2)`。
- **视口/缩放/裁切 caveat**：`TakePhoto.cs` 用 `Screen.width/height` + `ScreenCapture.CaptureScreenshot`（整屏），pose 未记录 `camera.rect`/`aspect`。若 Game 视图实际渲染尺寸 ≠ 屏尺寸、或相机视口非 (0,0,1,1)、或使用物理相机/自定义投影矩阵，主点居中与 FOV 公式会失效。历史帧 `image_width=2193` 与实际 PNG 一致，故本轮按居中假设处理，但记为待验证项。

## 阈值（在看结果前声明）

`ORTHO_TOL=1e-4`（float32 JSON 精度下的正交性/det/单位轴/字段一致）、`VEC_TOL=1e-4`、`RAY_ANGLE_DEG=0.1`、`REPROJ_PX=0.5`、`EPS=1e-9`（正深度判定）。

## 证据层级（明确区分）

1. **合成数学案例**（`test_camera_geometry.py`，32 项，已通过）：非零俯仰/偏航/滚转位姿、转置矩阵/漏纵轴转换/只换一侧手性的反例均按预期失败；连续坐标转换、主点/离轴正反转换、`H-1-y` 中心 1px 误差；尺寸不符（宽/高）与 pose 哈希不符的端到端反例均按预期失败。合成参考值测试标为**数学测试，不计为 Unity 引擎实测**。
2. **历史 pose 字段与矩阵内部一致性**（`verify_historical_poses.py`，2 帧，已通过）：图像/pose 哈希、尺寸三向绑定、列对应、正交、det=+1、单位轴、right×up=forward、平移=position、转换后 right×down=forward、中心射线=前向、投影往返。
3. **实际 Unity 引擎输出交叉验证**：**待验证**（本机无可运行 Unity 工程）。探针脚本见 `unity_probe/UnityCameraProbe.cs`，运行步骤见下；不得把 Python 自洽测试当作已验证真实截图/Unity 引擎输出。查阅 Unity 6.6 文档 ≠ 核实历史工程版本。

## 运行（仓库根）

```bash
# 合成数学回归（层级 1）
/home/dailen/vggt/vggt-env/bin/python experiments/c2-camera-geometry/test_camera_geometry.py
# 历史 pose 核验（层级 2）
/home/dailen/vggt/vggt-env/bin/python experiments/c2-camera-geometry/verify_historical_poses.py
# 尺寸/哈希反例端到端失败验证（每个反例 run() 应 exit 1；脚本自身 exit 0 = 全部按预期失败）
/home/dailen/vggt/vggt-env/bin/python experiments/c2-camera-geometry/verify_failure_cases.py
```

## 两张固定帧（不同来源、不同位姿，非重复 miss 帧）

| id | source_stem | role | 尺寸 / 图像 SHA256 | 位姿要点 |
| --- | --- | --- | --- | --- |
| state_000001 | case6_01 | fire | 2193×1000 / `9b6d0a26…` | pos≈(-0.77,2.29,20.25)，euler≈(11.86,241.36,0) |
| state_000011 | case6_09 | return_3 | 2193×1000 / `ad77b76a…` | pos≈(-8.05,4.58,19.25)，euler≈(49.04,74.09,0) |

配对清单（含图像与 pose 双哈希）见 `samples.json`。排除 miss_1/2/3（同源 case6_06）。

## 已核实的 `TakePhoto.cs` 事实

- 相机：`targetCamera`（Inspector 指定，脚本未断言与截图相机一致——记为 caveat）。
- 截图：`ScreenCapture.CaptureScreenshot`（整屏 `Screen.width/height`）；pose 在同一协程 `WaitForEndOfFrame` 后写入，与截图同帧（近似）。
- 序列化：`Matrix4x4Data` row-major；平移在 `data[3]/[7]/[11]`；轴向 `transform.forward/up/right`。
- 差异：`state_000011.json` 内部 `frame_id=9`（源 case6_09 计数）与 manifest `frame_id=11`（state 序列号）不一致——命名差异，不影响几何字段。

## Unity 探针运行步骤（层级 3，待验证）

1. 打开历史采集用的 Unity 工程（或任一含相同相机设置的工程）。
2. 新建空物体，挂 `unity_probe/UnityCameraProbe.cs`；把采集相机赋给 `targetCamera`；`worldPoints` 填若干已知世界点（含一正深度点）。
3. 进入 Play 模式；探针用 `JsonUtility.ToJson`（结构化序列化，避免手工拼接浮点受地区小数格式影响）写 `persistentDataPath/camera_probe.json`（日志打印路径）。
4. 探针记录：`Application.unityVersion`、`Screen.width/height`、相机 `pixelWidth/pixelHeight`、`pixelRect`、`aspect`、投影类型（perspective/orthographic）、`usePhysicalProperties`、`camera_to_world`（row-major `localToWorldMatrix`），用于确认 Python 的全屏透视假设是否适用。
5. 取出 JSON，与本仓库 `camera_geometry.py` 对应量比较：
   - `WorldToScreenPoint` 的 y 原点在左下，与 PNG 左上相反，用**连续坐标**翻转 `v_image = H - y_screen`（不是离散行号翻转 `H-1-y`）。
   - `ScreenPointToRay.origin` 在近裁剪面（非光心）：比较**方向**，或把 origin 沿 direction 平移到同一深度，再比较所在直线。
6. 比较射线方向与所在直线；中心/偏轴像素射线方向应与 Python 模块一致（角差 < 0.1°）。若 `projection_type != perspective` 或 `usePhysicalProperties == true`，先记录差异、不套 FOV 公式。

本机缺 Unity 工程，故层级 3 标为**待验证**。
