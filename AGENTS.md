# AGENTS.md

## 多 Codex 并行协作规则

本项目可能同时由多个 Codex 实例修改，包括 GUI Codex 和 CLI Codex。

不要假设 GUI 只做前端，CLI 只做后端。任务由用户每一轮明确分配。

核心原则：按“本轮任务边界”工作，而不是按工具类型固定分工。

## 每轮开始前必须检查

在修改前，必须检查：

```bash
git status --short
git branch --show-current
git diff --stat
git log --oneline -5
git worktree list
```

然后先用中文说明：

- 当前分支
- 是否有 dirty / staged / untracked 文件
- 哪些改动可能是已有改动或他人改动
- 本轮任务目标
- 预计修改范围
- 明确不修改范围
- 潜在冲突点

未说明前，不要直接改代码。

## 治理文件读取提示

每次运行、修改或测试前，如果根据项目规则读取 `MAIN_GOAL.md`、`CHANGELOG_AI.md`、`BRANCH_RULES.md`、`AGENTS.md`、`README` 或其他治理 / 红线文件内容，必须先用单独醒目的中文提示告知用户。

提示必须包含：

- 醒目标记，例如 `【显眼提示：即将读取治理文件】`
- 将读取的文件列表
- 读取目的
- 说明读取本身是否会修改文件

不要把治理文件读取动作隐藏在普通进度说明里。

## 任务边界规则

- 只做用户本轮明确要求的任务。
- 不要擅自扩大任务范围。
- 不要顺手修复无关问题。
- 不要做全项目格式化。
- 不要做大范围重构。
- 不要修改计划外文件。
- 如果必须修改计划外文件，先暂停并说明原因，等待用户确认。
- 如果发现当前任务可能会和另一个 Codex 实例冲突，先说明冲突点。
- 不要假设 dirty 文件都是自己造成的；归属不清楚时先报告，不要覆盖、删除、回滚或格式化。
- 修改前后都要检查 `git status --short` 和 `git diff --stat`。

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
- `CHANGELOG_AI.md`
- `MAIN_GOAL.md`
- `AGENTS.md`

如果确实必须修改这些文件，先暂停说明原因。

## VDS 文档修改要求

修改 `README`、`CHANGELOG`、`CHANGELOG_AI.md`、`MAIN_GOAL.md`、方案文档、进度文档、benchmark 说明或对外说明时，必须遵守以下要求：

- 文档结论必须和当前代码、测试结果、运行结果一致；不要写未验证的完成状态。
- 进度和架构说明默认使用中文，除非用户明确要求英文。
- VDS 总体进度 / 架构 / Agent 角色报告默认按这个顺序组织：当前阶段和测试状态 -> 主架构层 -> 数据处理流程 -> Agent 角色分工 -> 已解决问题 -> 当前阻塞/风险/dirty worktree -> 下一阶段方向。
- 计划类文档必须使用 repo phase 语言，内容要详尽且可执行，并能直接合入 `MAIN_GOAL.md`。
- post-baseline enhancement 工作使用 `Phase 7` 口径；不要继续写成含混的 `Phase 6+`。
- 前端工作在计划中应排在核心算法、解析、验证、输出、benchmark 可靠性之后，除非用户本轮明确要求先做前端。
- 涉及 benchmark、parser、verifier、output、多文件、join、安全边界的文档，必须写清楚能力边界、适用输入、不支持范围、回归风险和验证证据。
- benchmark 结果说明优先使用 `comparison.*`、`comparison_scored.*` 和 `scripts/score_comparison_answers.py` 相关产物；不要只用泛化的 gate exact / GPT-like 数量下结论。
- 如果 benchmark 数字异常，先区分 smoke coverage、proxy/accepted-answer observation、offline scorer correctness，再修改结论或文档。
- 对浏览器可见结果、demo、运行时行为的描述，必须写清楚实际验证的目录、分支、端口、URL 和验证方式。
- 当前真实产品目标必须写成“真实上传 CSV / Excel / 多文件数据后的连续自然语言数据分析”，不要写成 benchmark solver、random eval 玩具或只为通过某个 eval。
- Random eval、benchmark、LLM judge、`comparison_scored.*` 都只是评估手段；不能把 pass_rate、`success=true`、空 errors 或漂亮 overview 写成真实语义成功。
- 如果只改文档，不能声称代码测试通过；只能说明“文档变更，未涉及代码测试”，并记录是否做了 markdown / diff 检查。
- 每次修复用户可见行为，都应沉淀 focused regression、before / after 示例、API 级验证，必要时补 UI 可见验证；真实用户暴露的问题不能只靠 smoke 或单测结论覆盖。

## VDS 红线

- 不要写或实现只针对当前题面、当前数据集、当前 task_id 的 `特调` 或 `伪泛化补丁`。
- 不要把 “没有 task_id 泄漏” 当作泛化能力已经成立的充分证据。
- 不要把 benchmark patch 包装成通用能力；必须说明可复用能力家族和边界。
- 不要为了提高单个 benchmark 分数牺牲已有能力；能力非回归是硬验收门槛。
- 不要在没有代表性旧回归和同族新检查的情况下声称 benchmark / parser / verifier / output 行为已稳定。
- 不要把规则文件和数据文件重新混成无语义 file list；文件用途必须以后端 metadata 为准。
- 不要把 benchmark 规则执行混入普通 Chat 主路径；benchmark 应保持独立 runner / 独立接口边界。
- 不要在文档中夸大 GPT-like parity；必须按语义正确性、文件解析、可见布局、回答风格分别说明差距和证据。
- 不要在 dirty worktree 下用 `git add .` 或泛化 staging 提交文档；只 stage 本轮明确修改的文件。
- 不要在未确认用户要求的情况下修改 `main`、push、改远程、删 worktree、覆盖已有目录或重写历史。
- 不要让 LLM 绕过 executor、Result Normalizer、Verifier、Correction Planner 或 Response Builder 直接编最终答案。
- 不要把规则文件、字段说明、schema / metadata / dictionary / catalog 类文件当作普通业务事实表参与 join，除非用户明确询问字段含义、表结构或数据字典。
- 不要用低可信 join 硬算答案；如果本来应该单表计算，也不能让 join blocker 掩盖上游规划错误。
- 不要假设配置了 DeepSeek / LLM provider 就代表真实分析链路已经调用它；涉及 planner、answer builder、judge 或 provider 的任务必须诊断实际调用路径和 fallback / mock 状态。
- 不要在用户可见正常结果中暴露 raw markdown 标记，例如 `###`；标题和正文必须有清晰视觉层级，回答不能堆成一坨 markdown 文本。
- 不要用“缺少指标口径、维表或映射关系”这类泛化模板掩盖可回答问题；必须指出缺哪个字段、候选字段是什么、可以采用什么安全默认口径。

## 真实用户语义契约

后续任何影响用户可见回答、planner、executor、verifier、output 或 frontend 渲染的修改，都必须维护以下契约：

- 有答案时，第一屏必须先给直接答案。
- TopN 问题必须返回 N 个对象，或者明确说明 distinct 值不足。
- “哪个 X 最大 / 最高 / 最多”这类 groupby / ranking 问题必须保留 dimension + metric，不能压成只有 scalar `answer`。
- “差距 / 对比 / 相差多少”必须直接计算 pairwise gap 或 adjacent gap。
- follow-up 必须继承上一轮 source table、metric、dimension、filter、top objects、time range 和 operation。
- 多文件 overview 必须列出所有相关表、字段、可能 join key 和分析方向，不能漏表。
- 数据质量问题必须给字段级 / 规则级证据，例如缺失率、重复行、异常值、类型问题或不可解析日期。

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
- 常规 git 检查、diff 查看、单文件 staging、commit、分支同步、worktree 状态确认，应由当前 Codex 实例自动执行；不要把这些命令仅作为说明交给用户手动输入。
- 如果用户要求创建/修复分支、worktree、checkpoint、协作规则或同步分支，且当前状态允许安全执行，应直接完成对应 git 操作。
- 只有遇到权限、认证、冲突、不明来源改动、危险覆盖、远程 push、历史重写等需要用户决策的情况，才暂停并说明原因。
- dirty worktree 下提交时必须只 stage 本轮明确修改的文件；不要使用 `git add .`、`git add -A` 或宽泛路径，除非用户明确要求 checkpoint 全量提交。
- 合并前先查看：

```bash
git status
git log --oneline --graph --decorate --all -10
git worktree list
```

- 合并时如果出现冲突，不要盲目覆盖，先说明冲突文件和冲突原因。
