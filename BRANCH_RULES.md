# BRANCH RULES

## 分支规则

main：稳定版本，只放确认能运行的代码。

dev：日常开发主线，所有 feature 分支先合并到 dev，dev 测试稳定后再合并 main。

feature/*：功能开发分支，每个分支只做一个明确功能。

hotfix/*：紧急修复分支，只用于修复影响运行的问题。

refactor/*：重构分支，只用于结构调整，不允许混入新功能。

## 当前分支状态

2026-05-21 更新：

当前本地开发分支为 feature/project-rules-and-data-agent-skeleton。

远端 origin 已配置为 git@github.com:TrevorC-Allen/VDS.git。

2026-05-21 已从 origin/main 创建 origin/dev，本地 dev 已 tracking origin/dev。

本轮继续在当前 feature 分支上推进 Phase 6 最小可运行多 Agent workflow，后续应从 feature 发起 PR 到 dev。

## 禁止行为

1. 禁止直接在 main 分支开发
2. 禁止 feature 分支直接合并 main
3. 禁止一个分支同时做多个无关功能
4. 禁止没有测试就合并 dev
5. 禁止没有说明就解决冲突
6. 禁止把 Benchmark 单题逻辑写死到代码里
7. 禁止写只适配当前数据集、当前字段值、当前问法或当前错误样本的伪泛化补丁
8. 禁止为了快速通过测试破坏系统通用性
9. 禁止在未确认影响范围时大范围重构旧代码
10. 禁止在 feature/data-agent-core 中引入具体 Agent 框架强依赖
11. 禁止在 ms_agent_framework_adapter 中实现核心算法
12. 禁止 data_agent_core import backend
13. 禁止 data_agent_core import ms_agent_framework_adapter
14. 禁止 data_agent_core import multi_agent_workflows
15. 禁止 data_agent_core import agent_framework

## 推荐分支结构

main
- 稳定主分支
- 只合并经过测试的代码

dev
- 日常开发主线
- 所有 feature 分支先合并到 dev

feature/project-rules-and-data-agent-skeleton
- 项目规则文件、契约和 Data Agent 初始骨架

feature/data-agent-core
- Data Agent 核心算法主功能分支

feature/backend-api
- 最小后端 API 分支

feature/agent-runtime
- 内部 Agent 抽象层分支

feature/ms-agent-framework-adapter
- Microsoft Agent Framework 编排层适配

feature/multi-agent-workflows
- 多 Agent 工作流分支

feature/file-parser
- CSV / Excel 文件解析

feature/schema-profiler
- 字段画像和数据概览

feature/logic-form
- 用户问题到结构化分析意图的中间层

feature/pandas-executor
- Pandas / NumPy 执行路径

feature/sql-executor
- SQL / DuckDB 执行路径

feature/result-verifier
- 结果校验、自查、自纠

feature/chart-planner
- 可视化图表规划

feature/benchmark-runner
- Benchmark 评测框架

## 每次开始修改前必须执行

git status
git branch
git pull origin dev

如果当前不在正确分支，必须先切换或新建分支。

示例：

git checkout dev
git pull origin dev
git checkout -b feature/project-rules-and-data-agent-skeleton

## 每次修改完成后必须输出

1. 当前分支
2. 修改摘要
3. 修改文件列表
4. 测试命令
5. 测试结果
6. 风险说明
7. 建议 commit message
8. 是否建议发起 PR
9. PR 合并目标分支
10. 是否存在硬编码或伪泛化风险
11. 泛化验证方式
12. 是否影响未来多 Agent 迁移
13. 是否引入或修改 Microsoft Agent Framework 相关内容

## CHANGELOG 时间规则

1. 每次修改完成后，CHANGELOG_AI.md 必须追加真实修改记录。
2. 新增记录的时间必须精确到分钟，格式为 `YYYY-MM-DD HH:MM TZ`。
3. 禁止只写日期。
4. 禁止为了统一格式而给历史记录编造分钟级时间。

## Commit Message 规范

格式：

type(scope): summary

示例：

docs(project): add main goal changelog and branch rules
docs(project): add project rules contracts and data agent skeleton
feat(data-agent): initialize data agent core structure
feat(backend): add minimal data agent api skeleton
feat(agent-runtime): add internal agent abstraction skeleton
feat(ms-agent): add microsoft agent framework adapter skeleton
feat(workflow): add multi-agent workflow skeleton
feat(parser): add csv and excel parser
feat(schema): add schema profiler
feat(executor): add pandas executor
feat(executor): add duckdb sql executor
feat(verifier): add result comparison checks
feat(benchmark): add benchmark runner skeleton
fix(parser): handle empty csv rows
refactor(core): split logic form from planner
test(executor): add pandas executor unit tests

## PR 规则

每个 PR 必须包含：

1. 本次目标
2. 修改内容
3. 影响范围
4. 测试方式
5. 测试结果
6. 风险
7. 是否影响旧 VDS / BigCat 逻辑
8. 是否涉及 Benchmark
9. 是否存在硬编码或伪泛化风险
10. 泛化验证方式
11. 是否涉及 Microsoft Agent Framework
12. 是否影响未来多 Agent 迁移

## PR 模板

# PR 目标

本 PR 解决什么问题。

## 修改内容

-
-
-

## 影响范围

是否影响旧系统：

是否影响 data_agent_core：

是否影响 backend：

是否影响 agent_runtime：

是否影响 ms_agent_framework_adapter：

是否影响 multi_agent_workflows：

是否影响 benchmark：

是否影响 contracts：

是否影响 tracing：

是否影响 errors：

## 测试方式

pytest

## 测试结果

说明测试是否通过。

## 风险

列出潜在风险。

## 是否涉及 Benchmark

说明是否读取、修改或依赖 Benchmark。

## 是否存在硬编码或伪泛化

明确说明没有针对 Benchmark 单题做特判，也没有写只适配当前数据集、固定字段值、固定候选项、固定问法或当前错误样本的伪泛化补丁。

## 泛化验证方式

说明本次能力是否有合成/非 Benchmark 用例、同类变体用例和旧代表回归用例；如果没有，必须说明为什么本次不是能力提升或为什么只属于文档/接口变更。

## 是否涉及 Microsoft Agent Framework

说明是否只是适配层骨架，还是引入了实际依赖。

## 是否影响未来多 Agent 迁移

说明是否保持核心算法框架无关。

## 合并策略

推荐合并路径：

feature/*
↓
dev
↓
main

禁止：

feature/* 直接合并 main
本地乱 merge main
多个长期分支互相 merge
没有测试就合并 dev
PR 没有说明就合并

## 冲突处理规则

如果出现 merge conflict，不要直接乱改。

必须先输出：

1. 冲突文件
2. 冲突双方分别做了什么
3. 哪一边应该保留
4. 是否需要手动融合
5. 融合后的行为是否变化
6. 是否影响未来 Agent Framework 适配
7. 是否影响 contracts / API_CONTRACT / tracing / errors

解决冲突后必须运行测试。
