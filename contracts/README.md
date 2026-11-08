# contracts（接口约定与样例）

后端 B1+B2 已实现，本目录保存以实际后端模型和路由为源的接口规格，不另写一份互相矛盾的接口定义。坐标与时间约定见 `conventions.md`（单一来源）。

## 内容

- `openapi.json`：当前已实现接口的 OpenAPI 快照，由 `backend/scripts/export_openapi.py` 生成。含 7 个接口（health / 创建运行 / 查询运行 / 查询状态 / 上传 capture / 查询 capture / atlas 火情反馈聚合），**不含**尚未实现的上传后处理或算法接口。
- `examples/`：创建运行、运行记录、初始状态、上传 metadata、接收记录、错误样例。
- `conventions.md`：相机（像素原点、内参、轴向、位姿）与时间约定的单一来源。

## 样例文件

| 文件 | 内容 |
| --- | --- |
| `create_run_request.json` | 仿真运行创建请求（含 `simulation_time_origin_s`） |
| `create_run_real_request.json` | 真实运行创建请求（含 `time_origin_utc`） |
| `run_record_response.json` | 仿真运行记录响应 |
| `run_state_response.json` | 仿真初始状态响应（`time_basis=simulation_relative`） |
| `run_state_real_response.json` | 真实初始状态响应（`time_basis=utc_anchored`） |
| `capture_metadata.json` | 上传 metadata 样例（仿真，含相机内参/位姿） |
| `capture_record_response.json` | 接收记录响应样例（`status=queued`） |
| `error_validation.json` | 校验错误（无时区 `time_origin_utc`） |
| `error_not_found.json` | 未知运行/capture 404 |

## 时间契约

`time_basis` 为机器可读值，随状态返回：

| `input_source` | `time_basis` | 起点字段（创建时必填） | 换算公式 |
| --- | --- | --- | --- |
| `simulation` | `simulation_relative` | `simulation_time_origin_s`（有限、`[0, 1e12]` 秒） | `observation_time_s = simulation_time_s − simulation_time_origin_s` |
| `real` | `utc_anchored` | `time_origin_utc`（带时区，归一化到 UTC） | `observation_time_s = (captured_at_utc − time_origin_utc).total_seconds()` |

要点：仿真观测时间来自客户端 `simulation_time_s`（模拟器全局时钟），不依赖 UTC 墙钟；真实输入必须提供带时区 UTC 起点，缺失或无时区返回 422；`created_at` 仅表示服务端创建记录时间，不充当拍摄起点。

可复算样例：仿真 `origin=10.0, simulation_time_s=15.5 → 5.5`；真实 `origin=2026-10-24T00:00:00Z, captured_at=…00:05Z → 5.0`。

## 图片上传（B2）

上传为 `multipart/form-data`（`file` + `metadata` JSON 字符串）。metadata 至少含 `schema_version`、`capture_id`（客户端生成、重试复用、全局唯一）、`scene_id`/`asset_version`/`coordinate_frame_id`（须与运行一致）、`width`/`height`、相机内参与位姿、拍摄时间。未知字段（含 `result_origin`/真值/估计）拒绝。相机与时间约定见 `conventions.md`。

接收记录 `status=queued` 表示“尚未启用处理器/等待处理”，不自动标为 `completed`；收到图片不等于已有火情观测，运行状态仍为 `no_observation`。

## 当前未实现（留待后续）

原图后处理、任务工作器、fixture 火区、图像算法与前端 API 接入均不在本轮范围内。
