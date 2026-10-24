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

## 结果与快照约定

- 任务生命周期：`queued → processing → completed / failed`；处理开始/结束时间、错误信息与提供者版本持久化；领取任务用短事务，计算期间不持有写事务。
- 处理前核对已保存原件与规范化 metadata 的内容哈希；不完整/不一致明确失败并保留原件。
- 提供者输出在写入结果、标记 `completed` 和推进快照**之前**通过几何契约校验（`patch_id` 非空、顶点为有限 `[x,z]` 对、最少顶点数、首尾闭合）；非法输出使该 capture 明确 `failed`、记录原因、不写入非法结果，保留最近有效快照。
- 幂等与失败边界：重复完成在事务内识别“该 capture 已发布结果”后直接返回，保留首次 `processing_finished_at`/提供者信息/结果数量/`revision`/`produced_at`；`fail_task` 只更新仍处于 `queued`/`processing` 的任务，不把 `completed` 降级为 `failed`。
- 结果字段：`observation_time_s`（来自 capture 时间契约）、`produced_at`（实际生成时间）、`result_origin`、`provider_version`、`evidence_capture_ids`、稳定 `patch_id` 与几何。
- 几何：最小局部 XZ 多边形，`geometry` 为 `[x, z]` 有序环，**首尾闭合**（首点 == 末点），顶点有限值；世界语义由 `coordinate_frame_id` 决定。不硬套旧演示的 ±2200 米限制，不生成正式风险等级。
- 快照：新运行 `no_observation`、`revision=0`；发布更新的观测时 `revision` 在该 run 内递增；较旧观测只入历史、不覆盖较新快照；相同观测时刻不覆盖；重复上传/完成不重复发布；查询与空闲循环不推进 `revision`、不刷新 `produced_at`、不生成新轮廓。处理失败时 capture 查询返回明确错误，当前快照保留最近有效结果（无则 `no_observation`）。
- 来源：`result_origin` 由服务端配置决定，客户端不能通过上传字段指定。`fixture` 表示**接口测试数据，不代表图像重建**，每份结果固定标明提供者名称与版本；不接真实图像算法、失败不自动切换为 fixture、不输出 `image_estimation`。
- 重启：遗留 `processing` 重置为 `queued`（未发布结果，安全且幂等）；`queued` 继续处理；已提交结果不重复发布、不悄悄更换来源；不重写原件、receipt 或首次 `received_at`。
