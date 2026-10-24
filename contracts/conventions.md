# 坐标与时间约定（单一来源）

本文件是坐标与时间约定的单一来源；`backend/app/capture_metadata.py` 与 `backend/app/time_contract.py` 按其实现与校验，避免多份定义漂移。

## 相机约定

- **像素坐标原点**：左上角；`x` 向右（列），`y` 向下（行）。
- **内参（像素单位）**：`fx`、`fy` 为焦距（像素），`cx`、`cy` 为主点（像素，相对左上角）。
- **相机轴**：`x` 右、`y` 下、`z` 前，构成**右手系**。
- **位姿**：`camera_to_world` 为 4×4 矩阵，**按行存储**，**列向量乘法**：
  `p_world = T_camera_to_world @ p_camera`。
  末行必须为 `[0,0,0,1]`；左上 3×3 旋转部分须为**适当旋转**：近似正交且
  `det(R) ≈ +1`（镜像/反射变换 `det(R) = -1` 被拒绝，服务端不静默修正客户端矩阵）。
- **世界系**采用右手规范（轴向/单位/高程语义由 `coordinate_frame_id` 对应定义决定，不凭名字臆测）。
- Unity 原始左手坐标若需接入，须在**上传适配端**显式转换到对应 `coordinate_frame_id` 的右手世界系，不得将手性转换混作已验证旋转，也不得修改模型根变换来补偿。
- 首版只接受 `distortion_model="none"`（已去畸变/无畸变），其它模型拒绝。
- 不进行隐式旋转、缩放或裁切后沿用旧内参。

## 时间约定

- `simulation`：`observation_time_s = simulation_time_s − simulation_time_origin_s`（模拟器全局时钟，秒，不依赖 UTC 墙钟）。
- `real`：`observation_time_s = (captured_at_utc − time_origin_utc).total_seconds()`（`captured_at` 须带时区）。
- `received_at` 由服务端生成，与拍摄时间分开保存；拒绝非有限或早于运行起点的观测时间。

## 合成坐标样例（仅接口约定，非定位成果）

`camera_to_world = [[1,0,0,100],[0,1,0,200],[0,0,1,300],[0,0,0,1]]`（旋转为单位阵，平移 `[100,200,300]`）：

- 相机位置（世界）＝平移分量 `[100, 200, 300]`。
- 中心射线方向（世界）＝ `R @ [0,0,1]` ＝ `[0, 0, 1]`（前向）。
