# backend（Fire-X 后端 B1+B2+B3：运行、时间契约、上传与串行后台处理）

后端已实现：运行（run）的创建与持久化查询、明确的时间契约、图片上传与同帧 metadata 保存、接收记录查询，以及串行后台处理（fixture 提供者）与持久化状态快照。**真实图像算法/火情估计仍未接入**（`algorithm_mode=unconfigured`；fixture 仅为接口测试数据，不代表图像重建）。

## 技术栈与版本

- Python 3.12（`backend/.python-version` 固定；`requires-python = ">=3.12,<3.13"`）。
- FastAPI 0.162.0、Pydantic 2.14.1、uvicorn 0.54.0、Pillow 12.3.0、python-multipart 0.0.32（由 `pyproject.toml` + `uv.lock` 锁定）。
- SQLite（`runtime-data/backend/runs.sqlite3`，默认路径与启动 cwd 无关，可用 `FIREX_BACKEND_DATA_DIR` 覆盖）。
- 本机使用 `uv` 管理独立环境 `backend/.venv`。

## 目录职责

```
backend/
  pyproject.toml, uv.lock, .python-version   依赖与版本声明
  app/
    main.py            应用组装、异常处理（统一错误结构）
    config.py          数据目录/数据库路径与上传限额（与 cwd 无关）
    models.py          Pydantic 请求/响应与错误模型
    time_contract.py   时间契约：机器可读 time_basis 与换算公式
    capture_metadata.py 上传 metadata 模型、相机约定与校验
    image_validation.py  JPEG/PNG 实际解码、尺寸与像素限额校验
    db.py              SQLite 初始化/迁移与连接（幂等建表，不清空）
    store.py           运行仓储：创建、查询、初始状态派生
    capture_store.py   接收记录：原子落盘、幂等、冲突检测、查询、receipt 恢复
    provider.py        处理提供者接口 + fixture 提供者（接口测试数据）
    worker.py          串行后台工作器（独立线程，随 lifespan 启停）
    results.py         任务生命周期、结果历史与当前快照持久化
    routes/            health.py、runs.py、captures.py
  scripts/
    export_openapi.py       导出 OpenAPI 快照到 contracts/openapi.json
    upload_test_capture.py  离线上传脚本（生成标注用途的接口测试图）
  tests/
    test_runs.py            运行/时间测试
    test_captures.py        上传/幂等/一致性/校验测试
    test_interruption.py    进程中断恢复测试
    test_upload_client.py   离线上传客户端服务识别测试
    test_processing.py      后台处理/快照/恢复测试
```

## 接口

| 接口 | 行为 |
| --- | --- |
| `GET /health` | `{ "status": "ok", "algorithm_mode": "unconfigured", "service": "firex-backend", "processing_mode": "unconfigured"|"fixture" }` |
| `POST /api/v1/runs` | 校验并持久化创建运行，返回 201（`run_id` 由服务端生成） |
| `GET /api/v1/runs/{run_id}` | 从 SQLite 查询运行及绑定信息，未知返回 404 |
| `GET /api/v1/runs/{run_id}/state` | 从持久化结果读取当前快照：无结果时 `state_status=no_observation`、`revision=0`；有结果时 `state_status=observation`、`revision>=1` |
| `POST /api/v1/runs/{run_id}/captures` | multipart 上传（`file` + `metadata` JSON 字符串），新接收返回 202，幂等重试返回 200，冲突返回 409；只保存原件与待处理记录，不执行计算 |
| `GET /api/v1/captures/{capture_id}` | 查询所属运行、接收时间、观测时间、内容哈希与处理状态（`queued`/`processing`/`completed`/`failed`），未知返回 404 |

创建运行绑定：`plant_id`、`scene_id`、`asset_version`、`coordinate_frame_id`、`input_source`（`simulation` 或 `real`），并携带对应的**时间配置**。`created_at` 为带时区的 UTC，仅表示服务端创建记录的时间。重复 POST 会新建独立运行，**不提供幂等创建能力**。

## 图片上传与接收记录（B2）

上传请求：`multipart/form-data`，字段 `file`（JPEG/PNG 原始字节，不重新编码）与 `metadata`（JSON 字符串，服务端解析并用 Pydantic 校验）。metadata 至少包含：`schema_version`、`capture_id`（客户端生成、重试复用、全局唯一）、`scene_id`/`asset_version`/`coordinate_frame_id`（须与运行一致）、`width`/`height`、同帧相机内参与位姿、对应输入来源的拍摄时间。未知字段（含 `result_origin`、火区真值/估计）一律拒绝。

保存内容（默认 `runtime-data/backend/captures/<capture_id>/`）：

- `original.bin`：原始图片字节（不重新编码）。
- `metadata.raw.txt`：原始 metadata 文本。
- `metadata.normalized.json`：校验/归一化后的 metadata。
- `manifest.json`：服务端生成的接收清单（`format_version`、`capture_id`、`run_id`、图片字节数与哈希、规范化 metadata 哈希、`received_at`），用于中断恢复时核对归属，不接受客户端指定。
- SQLite `captures` 记录：`received_at`、`observation_time_s`、`content_sha256`（图片）、`byte_size`、`metadata_sha256`（规范化 metadata）、`status`、`storage_key`（= `capture_id`，可追溯，不暴露绝对路径）。

限额（可用环境变量覆盖）：

| 项 | 默认值 | 环境变量 |
| --- | --- | --- |
| 图片字节 | 50 MiB | `FIREX_CAPTURE_MAX_BYTES` |
| metadata 字节 | 1 MiB | `FIREX_CAPTURE_MAX_METADATA_BYTES` |
| 像素规模（宽×高） | 1e8 | `FIREX_CAPTURE_MAX_PIXELS` |

幂等与一致性：

- 同一运行、同一 `capture_id`、相同图片（SHA256）与相同规范化 metadata：返回已有记录（200），不新增、不覆盖、不刷新首次 `received_at`。
- 同一 `capture_id` 对应不同运行/图片/metadata：返回 409。
- JSON 空白与键顺序变化不产生冲突（规范化：`json.dumps(model_dump(mode="json"), sort_keys=True, separators=(",",":"))` 后取哈希）。
- 并发用 SQLite `BEGIN IMMEDIATE` + `capture_id` 主键唯一约束保证，不靠“先查后插”。
- 文件先写临时目录、原子 `os.replace` 落位，再提交事务；失败回滚并清理，不出现“已接收但原件缺失”或“覆盖原件”。
- 中断恢复：若进程在“目录已落位、事务未提交”之间退出，会留下 `captures/<capture_id>/` 孤儿目录（无数据库记录）。下次重试同一 `capture_id` 时，先核对路径边界、目录类型（拒绝符号链接）、`manifest.json` 及实际文件哈希：清单与本次 `run_id`/图片/规范化 metadata 一致则复用原件并保留首次 `received_at`；同一 ID 对应不同运行或内容返回 409 并保留目录；缺/坏清单、归属不明或内容不完整时保留目录并返回恢复错误（500 `RECOVERY_ERROR`），**不直接删除**。

## 时间契约（两类输入的观测时间语义）

`time_basis` 为机器可读值，随状态返回：

| `input_source` | `time_basis` | 起点字段（创建时必填） | 换算公式 |
| --- | --- | --- | --- |
| `simulation` | `simulation_relative` | `simulation_time_origin_s`（有限、`[0, 1e12]` 秒） | `observation_time_s = simulation_time_s − simulation_time_origin_s` |
| `real` | `utc_anchored` | `time_origin_utc`（带时区，归一化到 UTC） | `observation_time_s = (captured_at_utc − time_origin_utc).total_seconds()` |

要点：

- 仿真观测时间来自客户端提交的 `simulation_time_s`（模拟器全局时钟，秒），不根据服务端 `created_at`/接收时间/当前时间推算，不隐含依赖 UTC 墙钟。
- 真实输入必须提供带时区的 UTC 起点 `time_origin_utc`；缺失或无时区（naive）返回 422。
- `created_at` 仅表示服务端创建记录时间；初始 `produced_at` 等于 `created_at`，但不因此产生观测。
- 旧运行时间起点为 `NULL` 时，上传明确返回 422（`TIME_NOT_CONFIGURED`），不静默补零。
- 拒绝非有限或早于运行起点的观测时间。

可复算样例：

1. 仿真：`simulation_time_origin_s=10.0`，`simulation_time_s=15.5` → `observation_time_s=5.5`。
2. 真实：`time_origin_utc=2026-10-24T00:00:00Z`，`captured_at_utc=2026-10-24T00:00:05Z` → `observation_time_s=5.0`。

初始状态始终为 `no_observation`（`observation_time_s=null`、`revision=0`、`patches=[]`）；收到图片不等于已有有效火情观测，空 `patches` 仅表示“尚无观测”。重复 GET 与重启都不推进时间或 `revision`。

## 后台处理与状态快照（B3）

处理模式（环境变量 `FIREX_PROCESSING_MODE`）：

| 模式 | 行为 |
| --- | --- |
| `unconfigured`（默认） | 不处理 `queued`、不产生结果；`/health` 报告 `processing_mode="unconfigured"` |
| `fixture` | 显式开启后启动串行工作器；每份结果固定 `result_origin="fixture"`、提供者 `fixture@1.0`，并附“接口测试数据，不代表图像重建”说明 |

- 工作器为单服务进程内的**串行**线程，随 FastAPI `lifespan` 启动/停止：`import app.main`、构造应用、导出 OpenAPI 均**不初始化数据库、不启动工作器**；数据库初始化只在服务启动（lifespan）发生。计算在独立线程运行，不阻塞 HTTP 事件循环。关闭时先停止领取新任务，`stop()` **阻塞直到工作线程真正退出**（不设超时提前返回；阻塞等待在 lifespan 中经 `asyncio.to_thread` 卸载，事件循环保持可运行），退出后线程已停止、不再领取后续任务、不留下仍写库的后台单元。
- 上传接口只保存原件与待处理记录，不执行计算。任务生命周期 `queued → processing → completed / failed`；持久化处理开始/结束时间、错误信息与提供者版本。领取任务用短事务，计算期间不持有数据库写事务。
- 处理前核对已保存原件与规范化 metadata 的内容哈希；不完整/不一致明确失败并保留原件供排查。
- 提供者输出在写入结果、标记 `completed` 和推进快照**之前**通过几何契约校验（`patch_id` 非空、顶点为有限 `[x,z]` 对、最少顶点数、首尾闭合）；非法输出使该 capture 明确 `failed`、记录原因、不写入非法结果，保留最近有效快照。
- 结果记录：`run`/`plant`/`scene`/`asset_version`/`coordinate_frame_id`、`observation_time_s`（来自 capture 时间契约）、`produced_at`（实际生成时间）、`result_origin`、`provider_version`、`evidence_capture_ids`、稳定 `patch_id` 与局部 XZ 多边形几何。
- 快照语义：新运行 `no_observation`、`revision=0`；发布更新的观测时 `revision` 在该 run 内递增；较旧观测只入历史、不覆盖较新快照；相同观测时刻不覆盖；重复上传/重复完成不重复发布；查询与空闲循环不推进 `revision`、不刷新 `produced_at`、不生成新轮廓。
- 幂等与失败边界：重复完成在事务内识别“该 capture 已发布结果”后直接返回，保留首次 `processing_finished_at`/提供者信息/结果数量/`revision`/`produced_at`；`fail_task` 只更新仍处于 `queued`/`processing` 的任务，不把 `completed` 降级为 `failed`。
- 处理失败：capture 查询返回明确错误；当前快照保留最近有效结果，无有效结果时保持 `no_observation`。
- 重启恢复：启动时把遗留 `processing` 重置为 `queued`（此时未发布结果，安全且幂等），`queued` 记录继续处理；已提交结果不重复发布、不悄悄更换来源。不重写 B2 原件、receipt 或首次 `received_at`。

开启 fixture 并验证（本机 8002）：

```bash
FIREX_PROCESSING_MODE=fixture uv --directory backend run --locked uvicorn app.main:app --host 127.0.0.1 --port 8002
```

上传两帧（不同观测时间 → 同一 `patch_id` 不同几何），随后查询快照与处理状态：

```bash
uv --directory backend run --locked python scripts/upload_test_capture.py --base-url http://127.0.0.1:8002 --frame 1 <run_id>
uv --directory backend run --locked python scripts/upload_test_capture.py --base-url http://127.0.0.1:8002 --frame 2 <run_id>
curl -s http://127.0.0.1:8002/api/v1/runs/<run_id>/state
curl -s http://127.0.0.1:8002/api/v1/captures/<capture_id>
```

## 从仓库根启动（`--directory` 统一入口，已本机验证）

```bash
uv --directory backend sync --locked          # 首次：创建 backend/.venv 并安装锁定依赖
uv --directory backend run --locked uvicorn app.main:app --host 127.0.0.1 --port 8001
uv --directory backend run --locked python -m pytest -q
uv --directory backend run --locked python scripts/export_openapi.py   # 写 contracts/openapi.json
```

创建运行并上传（`capture_id` 首次生成后复用，重试不重生成）：

```bash
curl -s -X POST http://127.0.0.1:8001/api/v1/runs -H "Content-Type: application/json" \
  -d '{"plant_id":"GEM_HYDRO_SHUANGJIANGKOU","scene_id":"shuangjiangkou_reference_terrain","asset_version":"reference-v1","coordinate_frame_id":"SJK_REFERENCE_UTM47N_EGM2008_v1","input_source":"simulation","simulation_time_origin_s":10.0}'
curl -s -X POST http://127.0.0.1:8001/api/v1/runs/{run_id}/captures \
  -F "file=@interface-test.png;type=image/png" -F "metadata=$(cat capture_metadata.json)"
curl -s http://127.0.0.1:8001/api/v1/captures/{capture_id}
```

离线上传脚本（生成标注用途的接口测试图并上传，先核对 `/health` 的 `service="firex-backend"` 再发送写请求；本机 8001 被 `yiban-api` 占用，实际验证用 8002）：

```bash
uv --directory backend run --locked python scripts/upload_test_capture.py --base-url http://127.0.0.1:8002 <run_id>
```

服务默认绑定 `127.0.0.1:8001`；端口占用时另选可用端口（本机已改用 8002），不停止其他项目服务。`--directory` 会把工作目录切到 `backend/`，而 `app` 作为可编辑包安装到 `backend/.venv`，故 `app.main:app` 可从任意 cwd 导入；默认数据目录仍按项目根解析，与 cwd 无关。

## 持久化约定

- 数据库初始化使用 `CREATE TABLE IF NOT EXISTS`，正常启动不清空已有数据。
- 时间列通过 `ALTER TABLE … ADD COLUMN`（可空）对旧库做最小迁移：旧记录保留，新列保持 `NULL`，不为其编造时间映射。
- 默认数据目录 `runtime-data/backend/`（已 Git 忽略），可由 `FIREX_BACKEND_DATA_DIR` 覆盖；`captures/` 存放接收原件。
- `.venv`、SQLite 文件、缓存、运行日志与接收原件均被 Git 忽略，不提交。
