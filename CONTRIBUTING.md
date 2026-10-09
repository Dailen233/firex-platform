# 三人协作规则

代码的协作入口为新GitHub仓库firex-platform。旧仓库保留作历史参考，后续需求、分支和提交集中到新仓库。不通过坚果云同步各成员的.git、node_modules或正在编辑的源码目录。

## 分支

- main：已验收、可运行的基线，首次导入后避免直接写业务改动。
- feat/<主题>：单项功能，例如feat/demo-fire-region。
- fix/<问题>：修复，例如fix/mobile-scene-layout。
- docs/<主题>：资料或需求更新，例如docs/plant-data-sources。

三人规模先采用main+功能分支，不额外维护长期develop分支。是否启用分支保护，在仓库可用且队员加入后按实际权限设置；本文不是已启用保护的声明。

## 一轮开发

1. 更新基线：git switch main，然后git pull --ff-only。
2. 从main新建自己的分支：git switch -c fix/local-webgl-check。
3. 将需求编号、输入资源、事实边界和验收条件交给CodeBuddy。一次做一个目标。
4. 完成后检查git diff；运行npm run test:data、npm run build、git diff --check，附浏览器证据。
5. 只提交相关源码和文档；不提交node_modules/dist、密钥、个人环境文件。
6. 推送自己的分支，创建Pull Request，说明问题、变更、验收结果和未验证项。
7. 至少由另一位成员检查；本对话可辅助验收。通过后由负责人合并到main。

提交信息建议：feat: add ... / fix: repair ... / docs: record ...。不要把所有修改揉成一个“update”。

## 资源

现有GLB约6.7MB，直接跟踪于Git；不要每次重新导出或改哈希。manifest与registry原字段保留，新验收结论独立记录。后续大影像/视频先制定下载与版本方案，再决定是否采用Git LFS或外部资源存储。

当前只维护省份/电厂/织金模型/返回流程。本机下一任务为R1.1 WebGL与窄屏复现。电网与应急暂缓；不得提前将模拟真值当成图像估计结果。

新成员先阅读README、docs/01-requirements.md、02-design.md、03-acceptance.md和AGENTS.md，成功本机运行后再开发。添加成员需要成员的GitHub用户名，并由仓库所有者授权；当前不表示已经邀请任何成员。
