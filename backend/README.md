# backend（Fire-X 后端 B1：最小运行创建与持久化查询）

后端基础已实现：运行（run）的创建与持久化查询，以及明确的时间契约。**图像处理、上传接收、任务工作器、fixture 火区与图像算法尚未接入。**

## 技术栈与版本

- Python 3.12（`backend/.python-version` 固定；`requires-python = ">=3.12,<3.13"`）。
- FastAPI 0.162.0、Pydantic 2.14.1、uvicorn 0.54.0（由 `pyproject.toml` + `uv.lock` 锁定）。
- SQLite（`runtime-data/backend/runs.sqlite3`，默认路径与启动 cwd 无关，可用 `FIREX_BACKEND_DATA_DIR` 覆盖）。
- 本机使用 `uv` 管理独立环境 `backend/.venv`。

## 目录职责

```
backend/
  pyproject.toml, uv.lock, .python-version   依赖与版本声明
  app/
    main.py          应用组装、异常处理（统一错误结构）
    config.py        数据目录/数据库路径解析（与 cwd 无关）
    models.py        Pydantic 请求/响应与错误模型、时间校验
    time_contract.py 时间契约：机器可读 time_basis 与换算公式
    db.py            SQLite 初始化/迁移与连接（幂等建表，不清空）
    store.py         运行仓储：创建、查询、初始状态派生
    routes/          health.py、runs.py
  scripts/
    export_openapi.py   导出 OpenAPI 快照到 contracts/openapi.json
  tests/
    test_runs.py        9 个后端测试
```

## 接口（本轮实现）

| 接口 | 行为 |
| --- | --- |
| `GET /health` | `{ "status": "ok", "algorithm_mode": "unconfigured" }` |
| `POST /api/v1/runs` | 校验并持久化创建运行，返回 201（`run_id` 由服务端生成） |
| `GET /api/v1/runs/{run_id}` | 从 SQLite 查询运行及绑定信息，未知返回 404 |
| `GET /api/v1/runs/{run_id}/state` | 返回“尚无观测”初始快照（`state_status=no_observation`、`revision=0`） |

创建运行绑定：`plant_id`、`scene_id`、`asset_version`、`coordinate_frame_id`、`input_source`（`simulation` 或 `real`），并携带对应的**时间配置**（见下）。`created_at` 为带时区的 UTC，仅表示服务端创建记录的时间。

重复 POST 会新建独立运行（每个请求生成新的 `run_id`），**当前不提供幂等创建能力**，不声称已实现。

## 时间契约（两类输入的观测时间语义）

`time_basis` 为机器可读值，随状态返回：

| `input_source` | `time_basis` | 起点字段（创建时必填） | 换算公式 |
| --- | --- | --- | --- |
| `simulation` | `simulation_relative` | `simulation_time_origin_s`（有限、`[0, 1e12]` 秒） | `observation_time_s = simulation_time_s − simulation_time_origin_s` |
| `real` | `utc_anchored` | `time_origin_utc`（带时区，归一化到 UTC） | `observation_time_s = (captured_at_utc − time_origin_utc).total_seconds()` |

要点：

- 仿真观测时间来自客户端提交的 `simulation_time_s`（模拟器全局时钟，秒），**不根据服务端 `created_at`、接收时间或当前时间推算**，也不隐含依赖 UTC 墙钟；`simulation_time_origin_s` 是运行开始时模拟器全局时钟的值。
- 真实输入必须提供带时区的 UTC 起点 `time_origin_utc`；缺失或无时区（naive）时返回 422。**不用服务端 `created_at` 充当拍摄时间起点。**
- `created_at` 仍只表示服务端创建记录的时间；初始 `produced_at` 等于 `created_at`，但不因此产生观测。

可复算样例：

1. 仿真：`simulation_time_origin_s=10.0`，客户端提交 `simulation_time_s=15.5` → `observation_time_s = 15.5 − 10.0 = 5.5`。
2. 真实：`time_origin_utc=2026-10-24T00:00:00Z`，`captured_at_utc=2026-10-24T00:00:05Z` → `observation_time_s = (…).total_seconds() = 5.0`。

初始状态始终为 `no_observation`（`observation_time_s=null`、`revision=0`、`patches=[]`）；空 `patches` 仅表示“尚无观测”，**不表示“确认无火”**。重复 GET 与重启都不推进时间或 `revision`。

## 从仓库根启动（`--directory` 统一入口，已本机验证）

```bash
uv --directory backend sync --locked          # 首次：创建 backend/.venv 并安装锁定依赖
uv --directory backend run --locked uvicorn app.main:app --host 127.0.0.1 --port 8001
uv --directory backend run --locked python -m pytest -q
uv --directory backend run --locked python scripts/export_openapi.py   # 写 contracts/openapi.json
```

服务默认绑定 `127.0.0.1:8001`；端口占用时另选可用端口，不停止其他项目服务。`--directory` 会把工作目录切到 `backend/`，而 `app` 作为可编辑包被安装到 `backend/.venv`，因此 `app.main:app` 可从任意 cwd 导入；默认数据库位置仍按项目根解析，与 cwd 无关。

## 持久化约定

- 数据库初始化使用 `CREATE TABLE IF NOT EXISTS`，正常启动不清空已有数据。
- 时间列通过 `ALTER TABLE … ADD COLUMN`（可空）对旧库做最小迁移：旧记录保留，新列保持 `NULL`，不为其编造时间映射。
- 默认数据目录 `runtime-data/backend/`（已 Git 忽略），可由 `FIREX_BACKEND_DATA_DIR` 覆盖。
- `.venv`、SQLite 文件、缓存与运行日志均被 Git 忽略，不提交。
