# Fire-X 团队 Git 协作规范

本仓库由三名成员共同维护。代码、需求和验收记录统一通过 GitHub 管理：成员可直接向 `develop` 提交，复杂或高风险变更也可采用 Pull Request（PR）；不得通过坚果云同步 `.git/`、`node_modules/` 或正在编辑的源码目录。CodeBuddy 修改代码同样遵守本规范。

## 1. 分支角色

| 分支 | 职责 | 谁可以更新 |
| --- | --- | --- |
| `master` | 经团队验收的稳定基线、阶段演示及发布版本 | 仓库负责人 Dailen233；其他成员不得直接推送或合并 |
| `develop` | 团队日常开发的唯一长期集成分支 | 授权成员可直接推送，需先同步、测试并核对变更；PR 可选 |
| `feat/<topic>` | 新功能，例如 `feat/fire-region-update` | 对应任务成员 |
| `fix/<topic>` | 缺陷修复，例如 `fix/capture-status` | 对应任务成员 |
| `docs/<topic>` | 文档与流程改进，例如 `docs/api-contract` | 对应任务成员 |
| `chore/<topic>` | 工程配置、构建或依赖维护 | 对应任务成员 |

**当前默认分支为 `master`。旧 `main` 已废弃并删除，不再作为任何开发入口；今后不再往 `main` 推送或发起 PR。**

原则：日常可直接在 `develop` 开发并推送；涉及大范围重构、实验性算法、容易产生冲突的并行任务时建议从最新 `develop` 建短期功能分支，并通过 PR 回 `develop`。只在需要发布或里程碑冻结时，由负责人发起/合并 `develop → master`。未经确认，不把实验分支直接合入稳定主线。

## 2. 一项任务的标准流程

在本机 `~/projects/firex-platform` 中执行。已有工作区改动时先检查并保护，不得用 reset/clean/强制同步丢弃。

```bash
git fetch origin --prune
git status --short --branch
git switch develop
git pull --ff-only origin develop
```

若本机还没有 `develop` 分支，首次运行 `git switch -c develop --track origin/develop`，之后使用上述流程。需要隔离开发时再创建 `feat/<topic>` / `fix/<topic>` 分支；`<topic>` 使用简短的小写英文、数字和连字符。切换前必须保护已有未提交文件及正在运行的本机服务。

1. 先明确需求边界、涉及模块、真实输入与验收标准，再交由 VS Code 的 CodeBuddy 分步开发。
2. 只修改本任务范围；不要覆盖队友提交、改写历史、擅自升级主要依赖或修改已核实的模型资源。
3. 对前端执行实际存在的检查与构建：
   ```bash
   npm --prefix frontend run test:data
   npm --prefix frontend run build
   ```
4. 对后端执行相关测试（按当前仓库锁定环境）：
   ```bash
   uv --directory backend run --locked python -m pytest -q
   ```
5. 执行 `git diff --check`、核对 `git status`，只提交任务相关的代码、文档和小型验收证据。禁止提交密钥、模型大权重、`runtime-data/`、虚拟环境和构建产物。
6. 小型、已自测的修改可直接 `git push origin develop`。推送前检查远端是否有新提交；如果被拒绝，先 `fetch` 并核对差异，仅在可以快进时同步；冲突需要人工处理，禁止强推共享 `develop`。
7. 复杂或高风险变更建议使用短期功能分支，推送后创建 **base=`develop`** 的 PR，写明范围、测试、验收证据和风险；有条件时由另一位成员审阅，合并后清理已确认无用的功能分支。任何方式均须在组内说明已完成内容和未验证项。

## 3. 从 develop 发布到 master

1. 检查 `develop` 已包含拟发布的全部任务，不包含尚未验收的实验内容。
2. 确认前端数据检查与构建、后端测试及本轮实际功能验收结果；GPU/WebGL/Unity 联调未执行的项目必须明示，不得写“全部通过”。
3. 由负责人创建或审核 **base=`master`、head=`develop`** 的发布 PR，注明提交范围、版本/里程碑及可回滚点。
4. 仅负责人执行发布合并；不得强推、重置历史或绕开数据真实性、接口与来源要求。
5. 发布后同步 `develop`，避免后续功能从过期基线开发。必要时对稳定版本创建带说明的 Git tag。

## 4. GitHub 分支权限

仅靠本文不会产生仓库权限限制。负责人必须在 GitHub **Settings → Rules → Rulesets** 启用针对 `master` 的分支规则，并确认实际生效：

- 目标分支精确匹配 `master`；启用 `Restrict updates`、`Restrict deletions`、`Block force pushes`。
- Bypass 仅授予 **Repository admins**，模式为 `Always allow`（需确认只有负责人拥有管理员权限）；不能把 Write/Maintain 或所有协作者放入 bypass。
- 为留痕，负责人日常仍通过发布 PR 更新稳定分支。需要强制 PR 审核时，须验证与上述 bypass/发布流程兼容。
- `develop` 允许具有 Write 权限的成员直接推送；**不要启用强制 PR 审核**。可另设仅阻止强推和删除的规则，避免意外丢失共享提交；只有经过实际验证的 CI 检查才设置为 required。
- 配置后通过 Rulesets 页面检查 Active 状态与目标分支，避免把尚未配置的规则当成事实。

团队成员按任务获得写权限，但不应授予管理员权限。保护规则不代替代码审查。

## 5. 数据、模型与协作边界

- 既有 GLB/场景资产、manifest/registry、坐标与时间契约、来源和哈希保持一致，除非本任务明确要求并完成复验。
- 真实火情估计、fixture、仿真真值和未知状态必须分别标注，不得把演示数据描述为算法结果。
- README、`docs/01-requirements.md`、`docs/02-design.md`、`docs/03-acceptance.md`、`AGENTS.md` 和受影响模块的说明是任务开工前的阅读入口。
- 大批影像、视频、权重通过明确的版本清单与外部存储管理；勿把个人数据目录和本机路径作为共享开发接口。
