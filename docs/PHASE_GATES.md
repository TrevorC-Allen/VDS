# PHASE GATES

## 目标

本文件定义从 Phase 1 到 Phase 7.1 的推进门槛，避免为了 Benchmark 单题得分牺牲泛化能力。这里的“特调”不仅指题号、答案或固定题面硬编码，也包括只能修当前数据集、当前字段值、当前问法或当前错误样本的伪泛化补丁。

## 总红线

1. 禁止根据 Benchmark task_id、题号、标准答案或隐藏答案优化。
2. 禁止把标准答案传入 Intent Parser、Column Mapping、Planner、Executor、Verifier、Correction、Insight 或 Chart Planner。
3. 禁止让 Microsoft Agent Framework 成为 data_agent_core 的依赖。
4. 禁止把核心算法写进 backend、ms_agent_framework_adapter 或 multi_agent_workflows。
5. 禁止伪泛化补丁：不允许用固定字段值、固定候选项、固定问法、固定错误形态或当前数据分布来冒充通用能力。
6. 所有能力提升必须归入通用模块，例如字段画像、意图识别、执行器、结果标准化、校验、自纠和解释。
7. 每个能力提升必须说明可迁移边界，并至少用一个非 Benchmark 或合成用例证明泛化能力没有下降。
8. 禁止把 Tool Calling 变成任意代码、任意 SQL、shell、网络请求或外部文件访问入口；工具只能来自内部白名单和受控执行器。
9. 中文优先是阶段门槛：中文问题、中文字段名、中文业务术语、中文日期/金额/百分比格式和中文最终回答必须作为主路径验收；英文能力必须保留回归，但不能替代中文验收。
10. 禁止只用英文 Benchmark、英文 prompt 或英文字段证明能力完成；中英文能力都必须纳入可复现测试或明确记录阶段限制。
11. GPT-like parity redline：凡是修改文件解析、字段画像、最终回答、Insight、图表/表格、过程流、代码 artifact、Workbench 布局样式或用户可见文案，退出阶段前必须对照 GPT / ChatGPT Data Analysis 同类结果或已冻结标准 GPT 参考结果。验收结论必须明确“GPT 会不会这样解析、这样组织、这样排版、这样回答”；差距很大时直接打回重写，不能用单测通过、mock 通过或 smoke 通过替代。

## Phase 1：核心算法 + 最小 API

目标：

1. CSV / Excel 文件解析。
2. DatasetProfile / TableProfile / ColumnProfile 稳定返回。
3. 最小 backend API 调用 data_agent_core。
4. analyze 返回 response_version、run_id、errors、warnings、trace 摘要。

进入下一阶段前必须满足：

1. 单文件 CSV / Excel 解析测试通过。
2. schema profiler 能识别数值、日期、分类、ID、金额候选字段。
3. backend router 不包含 Pandas / SQL 核心分析逻辑。
4. 架构边界测试通过。

当前状态（2026-05-21）：已达到最小可测状态。CSV 解析、DatasetProfile、backend service upload/profile/analyze、run_id、trace_path、errors/warnings 均已有测试覆盖；Excel 和多 sheet 仍属于增强项。

## Phase 2：单 Agent MVP

目标：

1. 单 Agent 按固定链路运行：LLM Intent Parser → LLM + 规则 Column Mapping → LLM Analysis Planner → 代码执行 → 代码标准化 → 规则 + LLM 校验 → 修正计划 → Insight → Chart。
2. Planner 生成可序列化 LogicForm / AnalysisPlan。
3. Pandas / SQL 执行器不重新理解用户问题。
4. Verifier 不能被绕过。

进入下一阶段前必须满足：

1. 单 Agent trace 中包含每个阶段的结构化摘要。
2. mock LLM 和真实 LLM 都能运行同一条 analyze 链路。
3. DABstep 或其他 Benchmark 只用于评估，不改变核心输入。
4. 防硬编码测试通过。

当前状态（2026-05-21）：已达到最小可测状态。单 Agent 链路包含 LLM stages、代码执行、结果标准化、校验、解释和图表规划；mock LLM 可运行单测，真实 LLM 可通过本地环境变量运行。

## Phase 3：Benchmark 评测与错误归因

目标：

1. Benchmark runner 支持分段运行、报告、trace、错误类型统计。
2. evaluator 对齐官方 scorer。
3. 错误归因输出通用模块缺口，而不是单题补丁或只适配当前错误样本的伪泛化补丁。

进入下一阶段前必须满足：

1. runner 不把 task_id、question_id、answer、expected_answer 传入 agent.analyze。
2. 报告按 operation、error_type、backend、verification issue 聚合。
3. 修复项必须指向通用能力，例如字段映射、日期解析、聚合口径、TopN 排序、费用规则执行。
4. 修复项必须至少附带一个非 Benchmark 或合成通用用例；只在当前失败题目上变好不算通过。

当前状态（2026-05-22）：已达到可回归状态。runner 支持 limit/offset、predictions、trace、metrics、error_analysis；dev 前 10 题可本地评分并保持 9/10；DABstep public all 1-450 mock 多 Agent 执行覆盖为 450/450，public all split 因 answer 为空不能本地计算 hidden official accuracy。

## Phase 4：Microsoft Agent Framework Adapter 实验

目标：

1. ms_agent_framework_adapter 只映射 agent_runtime 的 AgentRole、AgentTask、AgentResult 和 WorkflowState。
2. adapter 只负责编排，不实现文件解析、Pandas、SQL、Verifier、Benchmark。
3. data_agent_core 不 import Microsoft Agent Framework。
4. backend 仍调用统一服务入口，不依赖具体 Agent 框架。

进入 Phase 5 前必须满足：

1. adapter 的映射测试通过。
2. Microsoft 依赖只允许出现在 adapter 或独立 demo 中。
3. 不引入任何 data_agent_core → adapter 的反向依赖。
4. 同一 AgentTask 能由自研 runtime 或 Microsoft adapter 映射。

当前状态（2026-05-21）：已新增 Microsoft Agent Framework 可选适配实现。adapter 可以包装内部工具为 function tool、创建按角色分配工具的 Agent，并按内部角色顺序构建 sequential workflow；本地没有 `agent-framework` 时返回清晰错误；requirements-ms-agent.txt 作为独立可选依赖入口；data_agent_core 仍不依赖 Microsoft Agent Framework。

## Phase 5：受控 Tool Calling 层

目标：

1. 将字段画像、计划构建、Pandas 执行、SQL / DuckDB 执行、结果校验、图表规划和解释生成包装为内部白名单工具。
2. ToolRegistry 支持稳定工具名、JSON schema、参数校验、allowed_roles、timeout、result_policy 和审计摘要。
3. LLM client 增加 provider-neutral 的工具调用循环，可适配 OpenAI Responses API、OpenAI-compatible chat completions 和 DeepSeek tool calls。
4. 工具调用只能发生在受控 stage 内，不能绕过 LogicForm、AnalysisPlan、Executor、Result Normalizer、Verifier 或 Response Builder。
5. thinking / reasoning 相关 provider 字段只在 provider adapter 内部用于续传，不写入稳定 trace、debug 或 API 响应。

进入 Phase 6 前必须满足：

1. mock tool-calling 流程可在无真实 key 环境下完成单元测试。
2. 每个工具都有 JSON schema、白名单声明、参数校验和失败响应。
3. 工具调用 trace 只记录工具名、参数摘要、结果摘要、错误、耗时和 step id，不记录完整 Chain of Thought 或 raw reasoning tokens。
4. OpenAI / DeepSeek provider 差异被限制在 data_agent_core/llm 或 provider adapter 内，data_agent_core 核心契约保持 provider-neutral。
5. 工具调用失败必须进入 errors / warnings，并可由 Verifier 或 Correction Planner 处理。

当前状态（2026-05-22）：已完成 provider-neutral 契约、本地 dispatcher、timeout_seconds 执行边界、内部工具 callable 测试和 OpenAI / DeepSeek 兼容 provider-native mock loop。当前包含 ToolDefinition、ToolCall、ToolResult、ToolTraceEvent、Data Agent tool catalog、tool whitelist、DataAgentToolRuntime、Microsoft adapter function tool mapping 和 ProviderNativeToolLoopAdapter；真实 OpenAI / DeepSeek 网络 tool loop 仍不得作为生产默认链路启用。

## Phase 6：多 Agent Workflow 基线

目标：

1. Planner Agent：LLM 为主。
2. Data Engineer Agent：代码为主，LLM 辅助字段语义。
3. Pandas Executor Agent：代码为主。
4. SQL Executor Agent：代码为主。
5. Verifier Agent：规则为主，LLM 辅助。
6. Correction Agent：LLM 生成修正方向，代码执行。
7. Insight Agent：LLM 为主。
8. Visualization Agent：规则 + LLM。
9. Benchmark Agent：代码为主，LLM 辅助错误归因。

验收标准：

1. 多 Agent 只改变编排方式，不改变核心算法位置。
2. 每个 Agent 可独立测试。
3. WorkflowState 可序列化、可追踪、可回归。
4. 可替换为 LangGraph、CrewAI 或自研 runtime，而不重写 data_agent_core。
5. 业务能力改动必须通过泛化验收：合成/非 Benchmark 用例、同类变体用例和旧代表回归用例都不能退化。

当前状态（2026-05-22）：Phase 6 最小可运行状态已完成。backend analyze 默认使用 multi_agent；DABstep 多 Agent runner 可运行 dev 前 10 题并保持 9/10；agent_runtime 负责角色执行和工具调用；multi_agent_workflows 负责编排；data_agent_core 不 import multi_agent_workflows 或 Microsoft Agent Framework。后续业务口径增强、全量回归、真实 provider tool loop 和复杂中文 BI 能力统一归入 Phase 7。

## Phase 7：泛化验证与 Provider 原生工具链增强

目标：

1. 将 Phase 6 基线后的业务语义校验、Not Applicable 能力缺口、中文 BI 能力族和大范围回归统一纳入一个清晰阶段。
2. Provider-native tool calling 只负责协议接入，真实执行仍必须经过内部 ToolDispatcher。
3. 用 DABstep public all、Microsoft 脱敏数据、桌面 VDS 真实问题和合成中英文用例验证泛化，而不是围绕单题补丁推进。
4. 推进 DuckDB runtime、复杂并行、多轮自纠、ACI associated cost 和更多中文真实数据能力。

验收标准：

1. DABstep / Microsoft / VDS 回归结果必须说明是执行覆盖、离线 scorer 还是 official accuracy，不能混写。
2. 标准答案、task_id、proxy answer 和固定样本值不能进入 Agent workflow、prompt、Planner、Executor、Verifier、Correction 或测试 fixture。
3. OpenAI / DeepSeek 原生 tool loop 必须映射到内部 ToolDefinition / ToolCall / ToolResult，并经过 ToolDispatcher 白名单、角色、schema、超时和 trace-safe 摘要校验。
4. 新能力必须有合成或非 Benchmark 用例、同类变体用例和旧代表回归用例。
5. 中文问题、中文字段名、中文业务术语和中文输出格式必须作为主路径验收。

当前状态（2026-05-25）：Not Applicable 归因已区分 true_unsupported / capability_gap，并补齐 row_count、distinct_count、repeat_entity_percentage、outlier_count、top_k_share、filtered_metric_ranking、null_check、季度过滤、fraud likelihood 多维比较、fee what-if candidate table、DABstep 131-180 的 outlier/null-filter 缺口、Microsoft 41-60 的中文零售过滤缺口和 VDS 中文 BI 周期比较能力。Provider-native tool calling adapter 已具备 OpenAI / DeepSeek 兼容 schema、tool call 解析、ToolDispatcher 分发和 mock loop 测试。Microsoft 脱敏数据 1-300 mock 离线 scorer 为 300/300；DABstep public all 1-450 mock 多 Agent 执行覆盖为 450/450，official accuracy 仍因 public all answer 为空而不可本地计算；VDS 桌面 `问题汇总.xlsx` 五域全部 95 题 smoke 为 95/95 成功，当前分支 VDS 标准答案离线 scorer 也已验证为 95/95 正确。tracked-file secret scan、扩大后的 Benchmark 硬编码扫描和 data_agent_core import 边界测试已纳入架构测试。下一步继续用真实 LLM 大规模回归、更多中文真实数据和复杂 BI 问法验证泛化稳定性。

## Phase 7.1：DABstep Submission Quality Gate and Easy Capability Closure

进入条件：

1. Phase 6 多 Agent 默认链路当前状态稳定，`single_agent` 仅作为 fallback。
2. Phase 7 已完成 DABstep public all 1-450 mock 执行覆盖，且执行覆盖可复现。
3. DABstep public all 的 hidden official answer 本地不可用，不能把 public proxy 或历史 accepted-answer pool 当作官方答案。
4. Microsoft 1-300、桌面 VDS 95 smoke 和当前分支 VDS 标准答案 scorer 作为回归基线，不允许因为 DABstep submission 治理退化。

目标：

1. 建立 DABstep submission gate，校验行数、task_id 覆盖、必填字段、`agent_answer` 格式、空答案、对象泄漏、debug 泄漏、trace 泄漏和 key 泄漏。
2. 将 submission 文件绑定当前 commit hash、report hash、prediction hash 和生成命令，避免旧 Desktop 文件误传。
3. 针对 Easy 低、Hard 高的外部 leaderboard 反馈生成能力族风险报告，但不把该反馈写成 hidden official accuracy。
4. 按 counting、top/ranking、fraud ratio、boolean yes/no、null check、field values、outlier、quantile、schema/missing-column 等能力族闭环，不按题号修复。

退出条件：

1. 新 DABstep submission JSONL 通过 submission gate。
2. 无空答案、无 final formatting 对象泄漏、无 debug / trace 泄漏、无旧 Desktop 文件误传。
3. 提交产物包含 commit hash、report hash、prediction hash 和生成命令。
4. Easy / Hard 风险报告生成，并明确 hidden official accuracy 只能由 Hugging Face leaderboard 返回，本地不能伪造。
5. 禁止 task_id、hidden answer、public proxy answer、固定题面、固定样本值进入 Agent workflow、prompt、Planner、Executor、Verifier、Correction、Response Builder 或测试 fixture。
6. DABstep public all 1-450 mock 覆盖不退化，DABstep dev 1-10 不低于 9/10，Microsoft 1-300、桌面 VDS 95 smoke 和当前分支 VDS 标准答案 scorer 不退化。

当前状态（2026-05-22）：Phase 7.1 已作为下一阶段目标写入文档；本轮只做阶段治理和验收定义，不实现 submission gate、Easy 能力族或 scorer 代码。
