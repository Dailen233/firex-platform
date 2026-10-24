# 开发服务器可用性与浏览器回归（2026-10-24）

分支 `feat/frontend-backend-layout`，HEAD `2de630b`（本轮未提交）。

## EMFILE 根因（已确认，证据支持）

- 普通 `npm --prefix frontend run dev` 报错：`Error: EMFILE: too many open files, watch '…/frontend/vite.config.ts'`，`errno: -24, syscall: 'watch'`（Node `fs.watch` / chokidar inotify 路径）。
- 限制与占用实测：`fs.inotify.max_user_watches=65536`、`fs.inotify.max_user_instances=128`；用户 `dailen`(uid 1000) 实际持有 **147–150 个 inotify 实例**，已超过 128 上限；watch 总数约 46793（未触顶）。
- `ulimit -n` 软/硬均为 1048576（非 FD 上限问题）。
- 结论：**`inotify_init1` 因用户级实例数上限（128）耗尽返回 EMFILE**，非 watch 数、非 FD 数、非配置路径错误。

## 处理方式（最小、显式开启、默认不变）

- `frontend/vite.config.ts`：新增 `server.watch.usePolling`，仅当 `VITE_USE_POLLING=true` 时开启，默认保持 inotify 原行为；interval 默认 300ms（可用 `VITE_POLLING_INTERVAL` 覆盖）。
- `frontend/package.json`：新增 `dev:polling` 脚本（`VITE_USE_POLLING=true vite …`）。
- polling 代价：周期性 stat 全量监听文件，CPU 略高、变更延迟约 interval；仅供 inotify 受限环境使用。

## 开发模式验证

- `npm --prefix frontend run dev`（默认 inotify）：仍复现 EMFILE（环境上限），完整错误见本记录上文。
- `npm --prefix frontend run dev:polling`：`VITE v7.3.7 ready in ~170ms`，无 EMFILE；`/`、`/src/main.ts`、`/data/…` 均 200。
- 源文件更新接收：向 `frontend/src/main.ts` 注入字符串标记后，`/src/main.ts` 转换结果即时含标记（轮询监听 + 重转换有效）；随后已完全恢复，`git status` 无 `main.ts` 残留改动。

## 浏览器回归（Playwright 1.64.1 + 系统 Chrome 147，headless + SwiftShader WebGL）

- atlas：8 个电厂项，标题正常。
- 织金详情 → 进入三维场景：WebGL 上下文 OK（canvas 889×638），标题“国能织金电厂与周边山地（试建场景）”，旋转+缩放后 WebGL 仍正常。
- 返回：回退正常（省过滤视图 1 项，全国视图 8 项）。
- 双江口详情 → 浏览山地参考底座：WebGL OK，标题“双江口公开 DSM 山地参考底座”，旋转+缩放后正常，返回正常。
- **控制台错误：无；失败请求 / HTTP≥400：无。**

## 截图

- `01-atlas.png`、`02-zhijin-detail.png`、`03-zhijin-scene.png`
- `05-shuangjiangkou-detail.png`、`06-shuangjiangkou-scene.png`

（脚本：本目录 `browser-check.mjs`。运行方式：临时目录安装 `playwright` 后 `node browser-check.mjs`，依赖系统 Chrome；未加入项目依赖。）

## 资源哈希

迁移前后 `public/`（现 `frontend/public/`）42 个文件 SHA256 完全一致，见 `hashes-before-migration.txt` / `hashes-after-migration.txt` / `hashes-conclusion.txt`。
