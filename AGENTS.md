# AGENTS.md

## 多 Codex 并行协作规则

本项目可能同时由多个 Codex 实例修改，包括 GUI Codex 和 CLI Codex。

不要假设 GUI 只做前端，CLI 只做后端。任务由用户每一轮明确分配。

核心原则：按“本轮任务边界”工作，而不是按工具类型固定分工。

## 每轮开始前必须检查

在修改前，必须检查：

```bash
git status
git branch --show-current
git diff --stat
git log --oneline -5
git worktree list
```

然后先用中文说明：

- 当前分支
- 是否有未提交改动
- 本轮任务目标
- 预计修改范围
- 明确不修改范围
- 潜在冲突点

未说明前，不要直接改代码。

## 任务边界规则

- 只做用户本轮明确要求的任务。
- 不要擅自扩大任务范围。
- 不要顺手修复无关问题。
- 不要做全项目格式化。
- 不要做大范围重构。
- 不要修改计划外文件。
- 如果必须修改计划外文件，先暂停并说明原因，等待用户确认。
- 如果发现当前任务可能会和另一个 Codex 实例冲突，先说明冲突点。

## 共享敏感文件

以下文件属于高冲突或共享敏感文件，除非用户明确把它们列入本轮任务，否则不要修改：

- `package.json`
- `package-lock.json`
- `pnpm-lock.yaml`
- `yarn.lock`
- `requirements.txt`
- `pyproject.toml`
- `.env`
- `.env.example`
- `Dockerfile`
- `docker-compose.yml`
- nginx 配置
- 数据库 schema / migration
- 全局类型定义
- 路由总入口
- 项目级配置文件
- `README`
- `CHANGELOG`
- `MAIN_GOAL.md`
- `AGENTS.md`

如果确实必须修改这些文件，先暂停说明原因。

## 修改后必须输出

每次修改完成后必须用中文总结：

- 完成内容
- 修改文件列表
- 每个文件的修改原因
- 是否涉及共享敏感文件
- 是否可能和另一个 Codex 实例冲突
- 是否运行测试或检查
- 建议 commit message

## Git 规则

- 每个 Codex 实例必须在独立 worktree / 独立分支工作。
- 不要在同一个目录、同一个分支中并行修改。
- 每完成一个小任务，提醒用户提交 commit。
- 合并前先查看：

```bash
git status
git log --oneline --graph --decorate --all -10
git worktree list
```

- 合并时如果出现冲突，不要盲目覆盖，先说明冲突文件和冲突原因。
