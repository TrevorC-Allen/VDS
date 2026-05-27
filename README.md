# VDS Data Agent

本仓库用于从头构建可评测、可复现、可扩展的数据分析 Agent 内核。

当前 Phase 6 的最小可运行多 Agent workflow 已经作为默认链路启用；Phase 7 系列已完成泛化验证、Provider 原生工具链增强基线、submission 风险治理和最终输出契约硬化。Phase 8 已完成核心算法回看与多文件/多表泛化闭环；Phase 9 已在 Phase 8 通过后交付首版前端 workbench；Phase 10 已补齐结果可视化、洞察建议、数据质量扫描和安全过程可视化。Phase 11 已启动轻量会话隔离与历史续聊实现，当前具备本地 JSON conversation store、`conversation_id`、历史载入和重命名持久化；真实登录、权限和多租户隔离仍未实现。Phase 12 已落地 GPT-like general / insight / activity stream 契约；Phase 12.1 已收敛主页面 SSE 活动流、概览/清洗/出口防原始明细倾倒、代码进过程详情和 Insight 卡片化。Phase 13 已完成首个 Project Workspace 落点，新增 project-only memory、共享文件 source 和 project-scoped conversation 边界。

最新状态速览：

- 默认 analyze 已使用 `agent_mode=multi_agent`，由内部 runtime 编排 Planner、Data Engineer、Pandas Executor、SQL Executor、Verifier、Correction、Insight、Visualization 和 Response Builder；`single_agent` 仅保留为 fallback。
- Phase 1 Backend API Shell 已补充外部系统一次性调用入口 `POST /api/data-agent/run`；该接口把调用方传入的 JSON 表格临时转成 dataset，再复用当前默认 `multi_agent` 链路，不新增核心算法能力。
- Phase 7.2 已完成 Capability Registry、Planner 泛化契约、Verifier 语义验收和 executor parity report 第一轮落点；SQL / Pandas / DuckDB 一致性只作为执行层可信度和回归判断支撑，不替代 Agent 泛化能力目标。
- Phase 7.2G 已归入上传表泛化专项，用于闭环 Microsoft 新增 100 与原始五域新增 100 之间的泛化断层；该专项不新增 Phase 7.4，也不覆盖 Phase 7.3。
- Phase 7.3 已完成 output contract、validation-driven retry、submission provenance 和 risk taxonomy 的 mock / 离线闭环；Phase 8/9/10 已补跑真实 DeepSeek representative，Phase 10 full real 三数据集回归已完成并生成 after-fix 汇总。
- Phase 7.5 - 7.10 已作为后续编号计划写入文档，用于承接 Phase 7.1 / 7.2 / 7.2G / 7.3 之后的 tool safety、provider-native real smoke、DuckDB、并行 executor、多轮自纠、MAF demo、ACI associated cost 和复杂中文 BI 增强；不新增 Phase 7.4。
- 当前工作目标已推进到 DAB Hard Recovery v2：先用 Phase 10 after-fix full real report 重新生成 all-450 Easy/Hard proxy observation，再按 Fee / ACI / format / verifier 能力族修复；旧 all-450 proxy hard `75.40%` 只保留为历史风险样本，不代表当前 after-fix 口径。
- 最新 after-fix proxy observation：`outputs/dabstep_all_1_450_proxy_after_phase10_20260524/all_1_to_450_public_proxy_observation_after_fix.json`，total `420/450 = 93.33%`，Easy `71/72 = 98.61%`，Hard `349/378 = 92.33%`。这是本地 task_scores 后验 proxy，不是 official hidden accuracy；外部 Easy `95` / Hard `84` 只作为提交反馈目标线。
- Phase 8 已完成 8A-8E：多文件 dataset 装配、`POST /api/data-agent/upload-batch`、问题到表精准路由、多表 join plan、Pandas join materialize、Verifier join 风险校验、trace / debug join 证据均已落地。
- Phase 9 已完成首版 workbench：`/workbench` 挂载静态前端，支持单/多文件上传、DAB context 规则包上传、无文件直接对话、问题提交、结果表格、用户可读分析过程、历史回看和单页会话内历史重命名；前端不实现指标公式、join、规则解析或数据计算。
- Workbench 和 backend 已新增规则上传链路：普通上传默认 `file_role=dataset`；用户分析规则可以通过 API 显式上传为 `file_role=rule, rule_scope=user_analysis`，也可以和 dataset 一起在 Workbench 上传后自动绑定为 user analysis knowledge；Benchmark 规则仍必须显式上传为 `file_role=rule, rule_scope=benchmark`，只能通过独立 `/api/data-agent/benchmark/run` 使用，不进入普通 Chat 上下文。主界面不再展示高级 Rule Mode / Benchmark 控件。
- Phase 10 已完成首版结果体验增强：后端生成 `chart`、`insight`、`quality_report`、`reasoning_trace_view` 和 `process_view_v2` 稳定字段；`process_view_v2` 会按 chat、概览、指标、TopN、趋势、多表、诊断和需澄清场景生成差异化安全过程叙事，并在占比等问题中展示安全的筛选口径、表选择、分子/分母依据，不展示完整 Chain of Thought、raw reasoning tokens、raw prompt、API key、task_id、标准答案或 proxy / scorer 信息。
- Workbench 已支持统一 `POST /api/data-agent/message`：无文件时直接进入辅助聊天；有文件时由后端判断普通聊天、数据概览或正式分析，避免“你好 / 你是什么模型”被误送进分析链路。
- Phase 12.1 已纳入当前体验修复：针对“看一下这个表单 / 总结一下这个表 / 这个数据主要讲什么 / 这几个表什么意思，有什么字段 / 每个文件分别有多少行、多少列 / 这个数据适合做哪些分析 / introduce this dataset”这类 general 问法，后端返回单表或多表 `overview_report`，不展开原始明细；清洗策略、影响行数/比例和是否修改原始数据等问题走 simulation-only cleaning guidance；正式分析出口增加 raw detail guard，最终答案如果像 CSV、明细行拼接或短日期/数值串会被改写成安全 overview 或澄清；Workbench 主页面消费 monitor SSE 默认显示一行过程，代码 artifact 收进过程详情，Insight 卡片化展示。`phase12_1_finalcheck3_20260526_092141` 三组 quick gate 均达到 GPT-like `35/35`；真实 `127.0.0.1:8001/workbench` smoke 已确认主回答无 raw dump、过程默认一行且展开后才显示完整过程和复现代码。
- 新增 GPT-like parity redline：凡是改文件解析、字段画像、回答结构、Insight、图表/表格、过程流、代码 artifact、Workbench 排版样式或用户可见文案，验收时必须对照 GPT / ChatGPT Data Analysis 同类结果或冻结标准 GPT 参考结果；差距很大直接打回重写，不能只用单测或 smoke 通过替代。
- VDS 中文 BI 已恢复并扩展标准答案所需的通用能力族：周期排名变化、TopN 增减、增长数量占比、阈值计数、同圈层异常、分组环比、当前期过滤指标 TopN、各区域 Top 实体、状态影响和三周期 TopN 都在 `data_agent_core` 内按 schema / 实体 / `_row` 指标执行，不再退回为默认 `区域/订阅收入` 排名。
- 当前分支已新增桌面 VDS 标准答案离线 scorer / runner；标准答案只在 response 生成后评分，不进入 Agent workflow、prompt、Planner、Executor、Verifier、Correction 或 trace。最新 mock 验证为 `outputs/vds_standard_answer_recheck_20260525_core_fix_v2/report.json`，桌面 VDS 五域 `95/95` 正确、`success_count=95/95`。
- Phase 11 已启动首个落点：Workbench `/message` 会自动写入本地 JSON conversation store，历史 Chat 可通过 `conversation_id` 载入旧消息并持久化重命名 / 置顶；API 已预留 `owner_id / tenant_id / owner_context`，但当前仍是本地匿名存储，不代表已经具备真实登录、鉴权或多租户权限隔离。
- Phase 13 首个 Project Workspace 落点已实现：新增本地 JSON Project Store、Project CRUD、Project source upload、Project memory CRUD；`/message`、conversation create/list/record 支持可选 `project_id`。Workbench 采用 GPT-like Project 结构：左侧保留全局新 Chat、Project 列表和最近历史，进入 Project 后右侧主区域显示 Project 标题、项目内新聊天、聊天 / 来源 tabs 和项目内上下文；浏览 Project home 不等于把当前对话放入 Project，只有点击项目内新聊天、续聊项目内会话或在历史菜单显式选择“移至项目”才会带上 / 写入 `project_id`。对话置顶通过后端 `pinned / pinned_at` 持久化，左侧全局历史和 Project home 聊天列表都按置顶优先渲染。当前仍是本地匿名 Project，不代表真实多人协作、鉴权或多租户权限已完成。
- Phase 8 完整门禁结果：DABstep dev 1-10 为 `9/10`；DABstep public all 1-450 mock 执行覆盖为 `450/450`；Microsoft 脱敏数据 1-300 mock scorer 为 `300/300`；桌面 VDS `问题汇总.xlsx` 95 题 smoke 为 `95/95`，当前分支桌面 VDS 标准答案 scorer 也已回归到 `95/95`；`format_risk / submission_risk / trace_redaction_risk` 均为 0。
- Phase 10 验收结果：Full unittest `147 tests OK`，compileall、`node --check frontend/app.js` 和 `git diff --check` 均通过；Phase 10 mock / 离线回归为 DABstep dev `9/10`、DABstep public all `450/450`、Microsoft `300/300`、VDS 95 smoke `95/95`；真实 DeepSeek full 回归为 DABstep public all `450/450` 执行覆盖、Microsoft `300/300`、VDS 95 smoke `95/95`。
- DAB Hard Recovery v2 当前门禁：focused tests `73 OK`、full unittest `152 OK`、architecture hardcoding/secret/dependency `8 OK`、DAB dev `9/10`、DAB all mock `450/450`、Microsoft `300/300`、VDS 95 smoke `95/95`、Phase 8 multi-file/join focused `5 OK`，`git diff --check` 通过。
- DABstep public all answer 为空，所以 public all mock / real full 结果只代表执行覆盖、风险门禁和 trace，不代表 hidden official accuracy；Microsoft 标准答案只在 response 生成后用于 scorer，不进入 Agent workflow、prompt、Planner、Executor、Verifier、Correction 或 trace。
- Phase 10 真实 DeepSeek full 汇总路径：`outputs/phase10_full_real_three_dataset_deepseek_20260523_summary_after_fix.json`；其中 DABstep 通过旧 full offset 结果加 task 36 / 58 after-fix 真实单题 replacement 合并为 `success_count=450/450`。
- 外部 leaderboard 的 Easy / Hard 反馈只作为提交后风险信号，不写成本地可复现 hidden official accuracy；本地只能验证 submission gate、公开 dev、mock 覆盖、离线 scorer 和 trace。
- 仍遗留 DABstep dev `best_fraud_aci_choice` / ACI associated cost 语义口径，需要继续按通用 fee what-if candidate table 和 associated cost 能力建设，不能按单题或固定答案特判。

更完整的阶段记录不只在 README：

- `MAIN_GOAL.md`：项目主目标、当前阶段目标、实现状态和架构红线。
- `CHANGELOG_AI.md`：每轮真实修改、验证命令、验证结果和遗留问题。
- `docs/ARCHITECTURE.md`：主架构层、多 Agent 映射、Tool Calling、Benchmark 和上传文件链路。
- `docs/PHASE_GATES.md`：阶段门槛、禁止伪泛化补丁和中文优先要求。
- `docs/BENCHMARK_RULES.md`：Benchmark 数据、标准答案隔离、评分与回归边界。
- `docs/VDS_BI_STANDARD_ANSWER_ROOT_CAUSE.md`：桌面 VDS 中文 BI 标准答案错误根因、修复计划、红线和泛用性验收。

README 是 GitHub 默认首页的状态摘要。以后任何阶段、状态、主目标、项目规则、API、Benchmark 口径或用户可见能力变更，都必须同步检查并更新根 `README.md`；如果本轮确认 README 不需要修改，必须在 `CHANGELOG_AI.md` 记录原因。

当前仍不做登录权限、数据库持久化、异步队列、微服务、旧 BigCat / VDS 主流程重构，且不在前端实现核心分析逻辑、指标公式、join 或数据计算。Microsoft Agent Framework 只作为可选 adapter 承载层，轻量依赖入口在 `requirements-ms-agent.txt`，核心算法不依赖它。

当前默认多 Agent 链路：

用户问题
→ Planner Agent：LLM 为主
→ Data Engineer Agent：代码为主，LLM 辅助字段语义
→ Pandas Executor Agent：代码为主
→ SQL Executor Agent：代码为主
→ Verifier Agent：规则为主，LLM 辅助
→ Correction Agent：LLM 生成修正方向，代码执行
→ Insight Agent：LLM 为主
→ Visualization Agent：规则 + LLM
→ Response Builder
→ 后端返回 JSON

Prompt 文件在：

```text
data_agent_core/prompts/data_agent_system_prompt.md
```

API key 只允许通过环境变量提供，不写入仓库、文档、trace 或 CHANGELOG。参考 `.env.example`，真实 `.env` / `.env.local` 已在 `.gitignore` 中忽略。

运行追踪只记录 structured analysis plan、reasoning summary、execution trace、verification notes 和工具摘要，不记录完整 Chain of Thought。

## External Agent API

外部系统如果已经有 JSON 表格数据，可以直接调用 `POST /api/data-agent/run`，不必先走文件上传。该接口属于 Phase 1 Backend API Shell 扩展，只负责把 inline tables 转成临时 dataset，然后复用现有 Phase 6+ 默认多 Agent 分析链路。

最小请求示例：

```json
{
  "request_id": "external-001",
  "question": "哪个城市销售额最高？",
  "tables": [
    {
      "table_name": "销售",
      "rows": [
        {"城市": "上海", "销售额": 100},
        {"城市": "北京", "销售额": 150},
        {"城市": "上海", "销售额": 200}
      ]
    }
  ],
  "execution_mode": "dual",
  "agent_mode": "multi_agent"
}
```

响应继续沿用 analyze 契约，包含 `response_version`、`run_id`、`dataset_id`、`answer`、`result`、`verification`、`insight`、`chart`、`quality_report`、`reasoning_trace_view`、`process_view_v2`、`warnings`、`errors` 和 `debug`。`request_id` 会原样返回，便于外部系统对账。

该接口不改变 Benchmark、Microsoft adapter、Provider-native tool loop 或核心算法边界；文件上传复用场景仍使用 `/api/data-agent/upload` + `/api/data-agent/analyze`，多文件一次性上传使用 `/api/data-agent/upload-batch`。

## Frontend Workbench

Phase 9 首版 workbench 由 backend 挂载：

```text
/workbench
/frontend/
```

它只调用稳定后端 API，不在浏览器中实现核心分析逻辑。多文件上传使用 `/api/data-agent/upload-batch`；该接口现在也能在网页端识别完整 DAB context 包：`payments.csv`、`merchant_category_codes.csv`、`acquirer_countries.csv`、`fees.json`、`merchant_data.json`、`manual.md`。用户也可以把 `.md/.txt/.yaml/.yml` 说明文件或规则型 `.json` 和 dataset 一起上传，后端会自动绑定为本 dataset 的 user analysis knowledge；规则解析和费用计算仍由后端完成。用户发送问题时，前端会先调用上传接口取得 dataset，再统一提交到 `/api/data-agent/message`，由后端决定普通聊天、数据概览、清洗策略或正式分析。Project home 只是项目主页；只有项目内新聊天、项目内会话续聊或显式“移至项目”会传递 / 写入 `project_id`，左侧历史记录始终是全局最近历史，不用 Project 过滤，项目内 conversations / sources / memories 由右侧 Project home 单独通过后端 Project / conversation API 渲染；对话置顶通过后端 `PATCH /conversations/{id}` 写入 `pinned`，前端只渲染置顶标记和后端排序。共享文件记录到 Project Source，project memory 只在同一 project 内注入。主界面已去除高级选项，内部 Benchmark 仍只通过独立 API 使用，不进入普通 Chat。用户选择文件后只显示底部附件状态，不在消息区生成上传结果、profile 或错误面板。主界面展示最终答案、紧凑结果表、自动图表、卡片化洞察建议、后端 `process_view_v2` 生成的用户可读分析过程和历史记录；`execution_artifacts` 安全代码只放在“查看处理过程”详情中，不作为主答案区独立代码面板。主页面可消费 monitor SSE 安全事件并默认只显示一行 activity summary；展开过程时可显示后端已脱敏的步骤、evidence / assumptions / caveats chips 和安全代码片段。每一轮用户消息都会创建独立 assistant 回复，不复用上一轮结果容器。左侧历史记录来自后端 conversation store，支持载入旧 user / assistant 消息并持久化重命名、置顶，Enter 保存、Escape 取消、失焦保存。Agent 监看面板只消费 `monitor_run_id` 对应的 SSE 安全摘要事件，不展示完整 Chain of Thought，也不接收完整 response / trace payload。后端审计字段如完整 `source_tables`、`table_selection_reason`、`join_plan`、`join_execution_summary`、verification、warnings、errors 和 `quality_report` 不在主界面直接暴露。

Phase 11 已启动可恢复会话式体验：`/api/data-agent/message` 返回并延续 `conversation_id`，左侧历史 Chat 来自后端会话列表。当前仍未完成 URL `/workbench?conversation_id=...` 自动定位、多窗口实时同步、跨进程 DataFrame 恢复、真实登录鉴权和多租户隔离。

本机开发环境可用 `scripts/run_workbench_server.sh` 启动 8001；当前 Mac 已配置用户级 LaunchAgent `com.trevorcui.vds.workbench` 自动启动并保活 `~/.vds-workbench-runtime/VDS` runtime 副本。以后打开 `http://127.0.0.1:8001/workbench` 应可直接使用；如需把当前仓库改动同步到常驻服务目录，运行 `scripts/sync_workbench_runtime.sh`，该脚本会保留 runtime `storage` 目录，避免删除本地会话历史。如需真实 provider，先在 `.env.local` 设置对应环境变量并同步 runtime，没有配置时默认 `VDS_LLM_PROVIDER=mock`。

## Core Test

当前可用 Codex bundled Python 运行完整核心测试：

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
```

当前可用 mock LLM 跑 DABstep public all 1-450 执行覆盖，验证多 Agent 链路、trace 和能力路由：

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 450 --offset 0 --output-dir outputs/dabstep_all_1_450_mock_current_verify_20260522
```

当前可用 mock LLM 跑 Microsoft 脱敏数据 1-300 离线 scorer；标准答案只在 response 生成后评分，不进入 Agent workflow：

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.microsoft_anonymized_benchmark_runner --dataset-root /Users/trevorcui/Desktop/微软脱敏数据 --limit 300 --offset 0 --output-dir outputs/microsoft_anonymized_1_300_mock_current_verify_20260522
```

真实 LLM 运行时，先在本地 shell export 环境变量，再执行同一命令。不要把真实 key 写进命令示例、文档或 Git。

## Phase Status

- Phase 1：最小 CSV / Excel 解析、字段画像和 backend service 已可测。
- Phase 2：LLM 单 Agent MVP 已可测，保留为 fallback。
- Phase 3：Benchmark runner、metrics、error_analysis 已可测；禁止单题硬编码和伪泛化补丁，标准答案只用于评分。
- Phase 4：Microsoft Agent Framework adapter 已作为可选承载层验证，不污染 `data_agent_core`。
- Phase 5：受控 Tool Calling 契约、ToolDispatcher timeout 边界、tool trace 摘要、内部工具 catalog 和 provider-native mock loop 已建立。
- Phase 6：最小多 Agent workflow 已启用，backend 默认 `multi_agent`；DABstep dev 前 10 当前可复现 9/10，`single_agent` 保留为 fallback。
- Phase 7：泛化验证与 Provider 原生工具链增强阶段。当前已完成 DABstep public all 1-450 mock 执行覆盖 450/450、Microsoft 脱敏数据 1-300 mock 离线 scorer 300/300、桌面 VDS `问题汇总.xlsx` 五个真实问题 sheet 共 95 题 smoke 95/95；当前分支已新增 VDS 标准答案离线 scorer 并验证 `95/95` 正确。当前增强重点是 provider-native 真实 tool loop、DuckDB runtime、复杂并行/多轮自纠、ACI associated cost 和更复杂中文 BI 泛化能力。
- Phase 7.1：DABstep Submission Quality Gate and Easy Capability Closure。重点是提交文件绑定 commit / report / prediction hash、无空答案、无格式泄漏、无旧 Desktop 文件误传，并按 counting、top/ranking、fraud ratio、yes/no、null check、field values、outlier、quantile、schema/missing-column 等能力族闭环 Easy 风险；当前 easy recovery 真实 DeepSeek 后验 proxy 观察为 `69/72`，mock 离线回归为 `72/72`，仍不代表 hidden official score。
- Phase 7.2：Agent Generalization and Executor Semantic Parity。重点是能力族优先、Planner / Verifier 泛化、Capability Registry、Executor 覆盖率与一致性报告；Pandas / SQL / DuckDB 语义统一只作为执行层可信度和回归判断支撑。当前新增 output `answer_target`、field/filter binding、grouped fraud metrics、denominator/share/quantile 和 deterministic fee monotonic 规则，禁止按 task_id 或 proxy answer 特调。
- Phase 7.2G：Uploaded Table Generalization Gap Closure。作为 Phase 7.2 下的上传表泛化专项，聚焦字段角色绑定、Planner / Verifier 语义契约和 capability family 覆盖，不新增 Phase 7.4。
- Phase 7.3：Evaluation-Driven Robustness and Output Contract Hardening。重点是最终答案 canonicalizer、output validator、validation-driven retry、submission provenance、真实 provider 分段回归和统一 risk taxonomy。
- Phase 7.5：Controlled Tool Hardening and Safety Boundary。重点是 ToolDispatcher、schema、allowed_roles、timeout、trace-safe summary、白名单和执行边界。
- Phase 7.6：Provider-native Tool Loop Real Smoke。真实 OpenAI / DeepSeek tool loop 只能作为 opt-in smoke，必须映射到内部 ToolCall 并经过 ToolDispatcher，不作为生产默认链路。
- Phase 7.7：DuckDB Read-only Runtime。DuckDB 作为 SQL 目标执行层，sqlite 仅保留 fallback；必须保持只读、单语句、SELECT / CTE、Result Normalizer、Verifier 和 trace 边界。
- Phase 7.8：Multi-Agent Parallel Executor and Bounded Correction。先做 Pandas / SQL / DuckDB executor 有限并行和 bounded retry，不并行 Planner / Verifier / Correction 的核心决策。
- Phase 7.9：Microsoft Agent Framework Adapter Demo。MAF 只作为可选承载层映射 AgentRole、ToolDefinition 和 WorkflowState，不成为强依赖，不承载核心算法。
- Phase 7.10：ACI Associated Cost and Complex BI Expansion。继续补齐 `best_fraud_aci_choice`、associated cost、fee what-if candidate table 和复杂中文 BI 能力，禁止按题号、proxy 或固定样本特调。
- Phase 8：Core Algorithm Review, Multi-file / Multi-table Generalization Closure。已完成 8A-8E，多文件路由、多表 join 和三类基准非退步门禁通过。
- Phase 8 Guardrail：已完成阶段的多文件 / 多表 / join non-regression 守护；后续不重开 Phase 8 主体。
- Phase 9：Frontend Productization After Core Algorithm Freeze。已完成首版静态 workbench；前端只负责上传、无文件对话入口、确认、澄清、展示和评测面板，不承载核心计算。
- Phase 9.1：Workbench Confirmation and Review Panels。后续增强字段确认、join key 确认、低置信度澄清和评测回看面板，前端仍不实现指标公式、join、排序、聚合或评分。
- Phase 10：Visualization, Insight, Data Quality and Safe Process View。已完成 ChartSpec v2、InsightResult v2、DataQualityReport、reasoning_trace_view、process_view_v2 和 workbench 展示；前端只渲染后端契约，不做核心计算或 raw CoT 展示，并将质量、warnings/errors、verification 和 join trace 作为后端审计信息处理，不在主界面直接展示。
- Phase 11：Conversation Isolation and Session Persistence。首个轻量实现已落地：`conversation_id`、本地 JSON conversation store、历史列表载入、旧消息恢复、历史重命名持久化，以及普通上传表基于持久化源文件的跨进程恢复；真实登录、鉴权、多租户隔离和 URL 自动会话恢复仍是后续工作。
- Phase 12：GPT-like General Answer / Insight / Activity Stream。首轮已落地：`overview_report`、enhanced insight、safe `execution_artifacts`、dataset overview 活动流、semantic chart planning guard 和规则文件自动绑定；Phase 12.1 已加入 streaming activity view、general overview no raw dump、cleaning guidance no raw dump、raw detail exit guard、frontend render guard、process code placement 和 insight cards。
- Phase 13：Project Workspace / Shared Files / Project Memory。首轮已落地本地 JSON Project Store、project-only memory、project source upload、project-scoped conversations 和 GPT-like Workbench Project sidebar + Project home；前端仍只渲染后端契约，不实现检索、join、聚合、评分或数据清洗，且不得把 Project 做成左侧历史过滤器。

后续 TODO：

- Phase 7.5 先硬化 Tool / safety 边界，再进入真实 provider smoke；所有工程分支必须保持 DABstep、Microsoft 和 VDS 三数据集不退步。
- Phase 7.6 接真实 OpenAI / DeepSeek tool loop smoke，但不作为生产默认链路；没有 key 时只能跑 mock，不能冒充 real score。
- Phase 7.7 推进 DuckDB read-only runtime，sqlite 保留 fallback。
- Phase 7.8 推进有限并行 executor 和 bounded correction retry，不能牺牲 WorkflowState、trace 和 Verifier 边界。
- Phase 7.9 在不改写 `data_agent_core` 的前提下完善 Microsoft Agent Framework demo / workflow 承载层。
- Phase 7.10 增强通用 `best_fraud_aci_choice`、ACI associated cost、fee what-if candidate table 和复杂中文 BI 能力，禁止按题号、题面、固定样本值或当前错误形态特判。
- Phase 8 Guardrail 后续继续在代码变更后补跑 staged / full real 回归，记录 provider、model、cost / latency、report hash 和失败归因；当前 Phase 10 after-fix full real 已完成，但 DABstep public all 仍不能本地计算 hidden official accuracy。
- Phase 9.1 持续扩展字段确认、join key 确认、澄清交互和评测回看面板，但核心指标公式、join 和数据计算仍必须留在后端 / data_agent_core。
- Phase 10 后续只做体验和契约回归增强；如要自动清洗数据，必须开新 Phase 并要求用户确认清洗动作，不能在 Phase 10 自动改原始数据。
- Phase 11 后续继续补 URL 会话恢复、多窗口同步、真实登录鉴权和多租户隔离。
- Phase 12 后续继续扩展 general 报告模板、Insight evidence 结构、代码 artifact 覆盖、主页面 SSE activity stream 和图表语义测试；任何增强都必须保持 DABstep、Microsoft、VDS 95、中文 BI、多文件 / join、conversation、monitor、output contract、hardcoding scan、secret scan 和 dependency boundary 不退步。`comparison.md` 或真实 Workbench 中如果再出现把原始明细拼接成主答案，必须按 Phase 12.1 blocker 处理。
- Phase 13 后续继续补 Project instructions 编辑、saved response source、conversation summary memory、URL project restore、真实登录鉴权和多租户隔离；当前不得宣称具备真实多人共享或企业权限。任何 Project UX 变更都必须对照 ChatGPT Project 截图或冻结参考，左侧全局历史不得因进入 Project 消失。
- 所有用户可见体验增强都必须补 GPT-like parity review 记录：参考来源、主要差距、接受差异和被打回重写的点；没有实时 GPT 参考时必须说明使用的是标准 GPT answer workbook、冻结截图或 repo 内参考 artifact。
