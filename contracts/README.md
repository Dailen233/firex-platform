# contracts（接口约定与样例）

后端 B1 已实现，本目录保存以实际后端模型和路由为源的接口规格，不另写一份互相矛盾的接口定义。

## 内容

- `openapi.json`：当前已实现接口的 OpenAPI 快照，由 `backend/scripts/export_openapi.py` 生成。仅含已实现的 4 个接口（health / 创建运行 / 查询运行 / 查询状态），**不含**本轮尚未实现的上传或算法接口。
- `examples/`：创建运行请求、运行记录响应、初始状态响应、校验错误与未找到错误的实际样例。

## 样例说明

- 创建运行样例使用已确认的 ID 组合：双江口参考底座 `plant_id=GEM_HYDRO_SHUANGJIANGKOU`、`scene_id=shuangjiangkou_reference_terrain`、`asset_version=reference-v1`、`coordinate_frame_id=SJK_REFERENCE_UTM47N_EGM2008_v1`。
- `run_id`、`created_at`、`produced_at` 由服务端生成，样例中的具体值为某次真实请求的结果。
- 织金正式模型尚无已确认的坐标框架（`coordinate_frame_id` 为 null），本轮不为其编造原点、矩阵或高程。

样例文件：

| 文件 | 内容 |
| --- | --- |
| `create_run_request.json` | 仿真运行创建请求（含 `simulation_time_origin_s`） |
| `create_run_real_request.json` | 真实运行创建请求（含 `time_origin_utc`） |
| `run_record_response.json` | 仿真运行记录响应 |
| `run_state_response.json` | 仿真初始状态响应（`time_basis=simulation_relative`） |
| `run_state_real_response.json` | 真实初始状态响应（`time_basis=utc_anchored`） |
| `error_validation.json` | 校验错误（无时区 `time_origin_utc`） |
| `error_not_found.json` | 未知运行 404 |

## 时间契约

`time_basis` 为机器可读值，随状态返回：

| `input_source` | `time_basis` | 起点字段（创建时必填） | 换算公式 |
| --- | --- | --- | --- |
| `simulation` | `simulation_relative` | `simulation_time_origin_s`（有限、`[0, 1e12]` 秒） | `observation_time_s = simulation_time_s − simulation_time_origin_s` |
| `real` | `utc_anchored` | `time_origin_utc`（带时区，归一化到 UTC） | `observation_time_s = (captured_at_utc − time_origin_utc).total_seconds()` |

要点：

- 仿真观测时间来自客户端提交的 `simulation_time_s`（模拟器全局时钟，秒），**不根据服务端 `created_at`、接收时间或当前时间推算**，也不隐含依赖 UTC 墙钟。
- 真实输入必须提供带时区的 UTC 起点 `time_origin_utc`；缺失或无时区（naive）返回 422，**不用服务端 `created_at` 充当拍摄时间起点**。
- `created_at` 仅表示服务端创建记录的时间；初始 `produced_at` 等于 `created_at`，但不因此产生观测。

可复算样例：

1. 仿真：`simulation_time_origin_s=10.0`，`simulation_time_s=15.5` → `observation_time_s = 5.5`。
2. 真实：`time_origin_utc=2026-10-24T00:00:00Z`，`captured_at_utc=2026-10-24T00:00:05Z` → `observation_time_s = 5.0`。

## 当前未实现（留待后续）

上传接收、原图保存、任务工作器、fixture 火区、图像算法及前端 API 接入均不在本轮范围内。
