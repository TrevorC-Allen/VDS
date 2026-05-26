# FEATURE BACKLOG

## 当前阶段

后续新增功能点统一记录在这里。新功能不能只散落在聊天记录里。

## 功能记录格式

每个功能点需要记录：

1. 目标
2. 影响模块
3. 优先级
4. 验收标准
5. 风险
6. 泛化验证方式
7. 是否影响 contracts
8. 是否影响 API_CONTRACT
9. 是否影响 tracing
10. 是否影响 errors

## Backlog

### DABstep 核心算法 MVP

目标：支持把 payments.csv 作为业务数据库表，把 manual.md / fees.json / merchant_data.json 作为文档和规则知识库，运行 DABstep 前 10 题核心算法测试。

影响模块：data_agent_core/core、data_agent_core/executors、data_agent_core/verifier、data_agent_core/output、data_agent_core/benchmark、tests/core。

优先级：P0。

验收标准：DABstep dev 前 10 题本地评测准确率不低于 80%，且分析链路不接收 task_id、标准答案、固定题面或只适配当前样本的条件分支。

风险：当前已覆盖 DABstep public all 1-450 的 mock 执行路径，但 public all answer 为空，不能据此宣称 hidden official accuracy；剩余公开 dev 失败仍是 ACI associated cost 通用语义缺口。

状态：2026-05-22 已完成 MVP 和 Phase 6 多 Agent 基线；当前进入 Phase 7 业务口径和泛化验证增强。dev 前 10 题当前验证结果为 9/10，DABstep public all 1-450 mock 执行覆盖为 450/450。

### LLM Single Agent Chain

目标：Agent 必须按固定链路调用 LLM 和代码模块：LLM Intent Parser、LLM + 规则 Column Mapping、LLM Analysis Planner、代码 Pandas Executor、代码 SQL / DuckDB Executor、代码 Result Normalizer、规则 + LLM Verifier / Critic、规则 + LLM Correction Planner、LLM Insight Generator、LLM + 规则 Chart Planner，最后由后端返回 JSON。

影响模块：data_agent_core/llm、data_agent_core/prompts、data_agent_core/agent/single_agent.py、tracing、docs。

优先级：P0。

验收标准：没有环境变量 key 时真实 LLM 模式应失败；mock LLM 模式可用于单元测试；真实 key 只能通过环境变量提供，不进入 Git；trace/debug 中能看到各 LLM 阶段摘要；执行、标准化和评分仍由代码完成。

风险：LLM 输出不稳定，必须通过本地 schema guardrail 限制到受支持 operation，不允许把标准答案或 task_id 传给 LLM。

状态：2026-05-21 已完成 LLM client、stage helper、prompt 文件、单 Agent 阶段 trace 和 mock 测试 wiring。

### CSV / Excel 文件解析

目标：支持上传文件解析并生成 DatasetProfile。

影响模块：data_agent_core/core/file_parser.py、schema_profiler.py、backend。

优先级：P1。

验收标准：能对 csv / xlsx 返回稳定字段画像。

风险：表头识别、编码识别、多 sheet 处理。

状态：2026-05-21 已完成 Phase 1 最小 CSV / Excel 解析入口、DatasetProfile 生成、上传表核心测试；2026-05-25 已补齐 Workbench 完整 DAB context 包上传，JSON / MD 只在完整规则包中作为后端知识库使用；后续仍需增强编码识别、表头不确定处理和多 sheet 策略。

### Rule Mode And Benchmark Rule Upload

目标：在不破坏普通数据上传体验的前提下，显式区分 dataset、用户分析规则和 Benchmark 规则。

影响模块：backend/storage、backend/services、backend/routers、frontend、docs/API_CONTRACT.md、docs/BENCHMARK_RULES.md、tests/backend。

优先级：P1。

验收标准：旧上传无 `file_role` 时默认 dataset；规则文件必须显式 `file_role=rule` 且带 `rule_scope`；user_analysis rule 只在显式 `user_rule_file_id` 下合并到本次 guidelines；benchmark rule 只能通过独立 Benchmark runner 使用；规则文件不进入 DatasetProfile / DataFrame / 字段画像。

风险：不能把 Benchmark rule 混入普通 Chat；不能把用户分析规则当评分规则；不能为此重写上传系统或前端核心体验。

泛化验证方式：用合成 CSV/JSON dataset、user_analysis markdown/yaml rule、benchmark JSON rule 覆盖 role-aware validation，并保留旧上传、DAB context、conversation 和 backend analyze 回归。

状态：2026-05-25 已完成最小实现和后端聚焦测试；后续可继续增强 YAML 复杂结构、Benchmark report 展示和生产级规则持久化。

### Phase 13 Project Workspace / Shared Files / Project Memory

目标：把 Workbench 从单会话历史升级为 GPT-like Project 工作区，让同一 project 内的 chats、共享文件、项目说明和 project-only memory 共享同一后端上下文边界。

影响模块：backend/storage/project_store.py、backend/services/data_agent_service.py、backend/routers/data_agent.py、backend/storage/conversation_store.py、frontend、docs/API_CONTRACT.md、tests/backend、tests/architecture。

优先级：P1，阶段：Phase 13。

验收标准：Project CRUD、project source upload / delete、project memory CRUD、conversation 挂 project、conversation 后端置顶、`/message project_id`、Project home 内按 project 展示 chats / sources / memories、左侧全局历史不按 project 过滤和 project-only 隔离负例必须有测试；无 `project_id` 时现有 `/message`、conversation、upload-batch、rule auto-bind、multi-file/join、monitor 和输出契约不得退步。

风险：当前是本地匿名 JSON Project Store，不代表真实多人协作、鉴权或多租户权限；Project memory 不能变成全局 memory；conversation 置顶不能变成前端 localStorage 假状态；前端不能实现检索、join、聚合、评分、图表选择或数据清洗；Project UX 不能退化成 sidebar history filter，必须保持 ChatGPT Project-like sidebar + main project home。

泛化验证方式：用项目内/项目外对照测试验证 memory/source/conversation 隔离；用 `.md/.txt/.yaml/.yml` 说明文件验证文本 source 不进入 DatasetProfile / DataFrame；用 dataset + user rule 混合上传验证既有 TempFileStore、rule file 和 dataset store 行为不退化。

状态：2026-05-25 已完成首个落点：本地 JSON Project Store、Project API、project source upload、project memory CRUD、project-scoped conversations 和 GPT-like Workbench Project sidebar + Project home；后续继续补 Project instructions 编辑、saved response source、conversation summary memory、URL project restore、真实登录鉴权和多租户隔离。

### 双执行路径

目标：支持 Pandas / NumPy 和 SQL / DuckDB 两条执行路径。

影响模块：executors、verifier、contracts。

优先级：P1。

验收标准：两条路径能返回可比较的标准 ExecutionResult。

风险：数值精度、排序、空值和日期标准化。

状态：2026-05-21 已为上传单表的 aggregation / ranking 增加 Pandas 和 SQL fallback 双路径测试；后续需要补 DuckDB runtime、更多过滤/趋势/对比能力和更严格的标准化。

### Benchmark Runner

目标：接入 450 题 Benchmark 评测和错误归因。

影响模块：benchmark、errors、tracing。

优先级：P3。

验收标准：输出按错误类型统计的评测报告。

风险：禁止标准答案泄漏、单题硬编码和伪泛化补丁；Benchmark 失败只能转成能力族缺口，不能转成当前样本专用逻辑。

状态：2026-05-22 已支持分段运行、dev 前 10 题评分、all offset 预测、metrics 和 error_analysis 聚合；DABstep public all 1-450 mock 多 Agent 执行覆盖为 450/450，public all.jsonl answer 为空，不能本地计算 hidden official accuracy。

### Minimal Backend API Shell

目标：提供 upload / analyze / profile 的最小后端调用壳，供前端未来接入。

影响模块：backend/services、backend/storage、backend/schemas、backend/routers、tests/backend。

优先级：P1。

验收标准：backend 只调用 data_agent_core，不实现 Pandas / SQL / Verifier 核心逻辑；响应包含 response_version、errors、warnings；analyze 包含 run_id。

风险：当前 TempFileStore 只适合本地和 Phase 1 测试，进程重启后不会恢复 DataFrame tables，后续服务化需要明确 retention 和重新加载策略。

状态：2026-05-21 已完成最小服务壳和测试。

### Controlled Tool Calling Layer

目标：在 Phase 5 引入受控 Tool Calling，把 profile_schema、build_analysis_plan、execute_pandas_plan、execute_sql_plan、verify_results、build_chart_spec、generate_insight 等内部能力包装成模型可选择但代码受控执行的白名单工具。

影响模块：agent_runtime/tool_registry.py、data_agent_core/configs/tool_whitelist.yaml、data_agent_core/llm、data_agent_core/agent、data_agent_core/tracing、ms_agent_framework_adapter/tool_mapping.py、tests/agent_runtime。

优先级：P2，阶段：Phase 5。

验收标准：每个工具必须有稳定名称、JSON schema、参数校验、allowed_roles、timeout、result_policy 和测试覆盖；mock tool-calling 可离线运行；OpenAI / DeepSeek 差异只出现在 provider adapter；trace 只记录工具调用摘要，不记录完整 Chain of Thought 或 raw reasoning tokens。

风险：如果过早启用自由工具调用，模型可能绕过确定性执行器和 Verifier；如果工具 schema 不严格，容易出现参数漂移、隐式任意 SQL、敏感数据泄露或不可复现结果。

状态：2026-05-22 已完成 provider-neutral 契约、本地 dispatcher、timeout_seconds 执行边界、真实内部工具 callable 测试和 OpenAI / DeepSeek 兼容 provider-native mock loop，包括 profile_schema、build_analysis_plan、execute_pandas_plan、execute_sql_plan、verify_results、build_chart_spec、generate_insight；仍未把真实 OpenAI / DeepSeek 网络 tool loop 作为生产默认链路。

### Microsoft Agent Framework Adapter

目标：把内部 AgentRole、ToolDefinition、ToolDispatcher 和 WorkflowState 映射到 Microsoft Agent Framework function tool、Agent 和 sequential workflow。

影响模块：ms_agent_framework_adapter、agent_runtime、tests/ms_agent_framework_adapter、docs。

优先级：P2，阶段：Phase 4/5 到 Phase 6 过渡。

验收标准：adapter 可选导入 `agent_framework`；本地没有安装时有清晰错误；fake framework 测试能验证 function tool 包装和 workflow builder；data_agent_core 不 import Microsoft Agent Framework；adapter 不实现核心算法。

风险：如果让 adapter 承载核心算法，会导致未来无法切换 LangGraph / CrewAI / 自研 runtime。

状态：2026-05-21 已新增 framework_tools、framework_agents、framework_workflow 的可选适配实现和测试，并新增 requirements-ms-agent.txt 作为独立可选依赖入口。

### Phase Gate And Multi-Agent Migration

目标：按 Phase 1 到 Phase 7.1 的门槛推进，先补核心泛化能力、防硬编码测试和防伪泛化验收，再接 Microsoft Agent Framework adapter、Phase 5 受控 Tool Calling、Phase 6 多 Agent workflow 基线、Phase 7 泛化验证 / provider 工具链增强和 Phase 7.1 submission gate。

影响模块：docs、agent_runtime、ms_agent_framework_adapter、multi_agent_workflows、tests/architecture。

优先级：P0。

验收标准：docs/PHASE_GATES.md 明确每个阶段的进入/退出条件；agent_runtime 提供框架无关 AgentTask / AgentResult / WorkflowState；adapter 映射不 import Microsoft Agent Framework；防 Benchmark 硬编码测试通过；新能力必须用合成/非 Benchmark 用例证明不是只修当前样本。

风险：如果跳过 Phase gate 直接做 Microsoft workflow，容易把核心算法绑死在具体框架里。

状态：2026-05-21 已落地 Phase 6 最小可运行多 Agent workflow。backend 默认 multi_agent；DABstep 多 Agent runner 可跑 dev 前 10，当前回归为 9/10。复杂并行、多轮纠错、ACI associated cost 通用口径、真实 provider tool loop 和真实 Microsoft cloud workflow 统一归入 Phase 7。

### Phase 6 Multi-Agent Runtime

目标：把主 analyze 链路从单 Agent 编排切换为多 Agent 顺序 workflow。

影响模块：agent_runtime/data_analysis_roles.py、multi_agent_workflows/end_to_end_data_analysis_workflow.py、multi_agent_workflows/dabstep_benchmark_runner.py、backend/services、benchmark wrapper、tests。

优先级：P0。

验收标准：Planner、Data Engineer、Pandas Executor、SQL Executor、Verifier、Correction、Insight、Visualization、Response Builder 都进入 debug.multi_agent_roles；trace 包含 tool_call_summary，debug 包含 tool_call_summaries；DABstep dev 前 10 题仍不低于 80%；data_agent_core 不依赖 multi_agent_workflows。

风险：当前为顺序多 Agent，尚未实现复杂并行、真实 Microsoft cloud execution 和多轮自纠执行。

状态：2026-05-21 已完成最小可运行版本。

### Business Semantic Verification Loop

目标：让 Planner、Data Engineer、Verifier 和 Correction 围绕业务指标定义、候选表和中间计算证据工作，而不是只判断执行是否成功。

影响模块：data_agent_core/contracts、data_agent_core/core/intent_parser.py、data_agent_core/executors、data_agent_core/verifier、data_agent_core/tracing、agent_runtime/data_analysis_roles.py、multi_agent_workflows、tests/core。

优先级：P0，阶段：Phase 7。

验收标准：LogicForm 能表达 metric_definition、numerator、denominator、group_by、objective 和 options；Verifier 能识别业务口径错误并输出 correction_action；Correction 能生成 corrected LogicForm 并触发受控重跑；trace 能记录 semantic_verification_notes、candidate_table_summary 和 selected_candidate。

风险：如果把 Benchmark dev 题面、答案、固定字段值、固定候选项或当前错误形态写入判断，会破坏泛化能力；如果只比较 Pandas / SQL 一致性，可能出现两条路径一致但业务口径错误。

泛化验证方式：每个新业务语义能力必须至少包含一个合成/非 Benchmark 用例、一个同类变体用例和一个旧代表回归用例；DABstep 只能作为后验回归观察。

状态：2026-05-22 已完成 fraud volume rate ranking、Verifier semantic correction action、受控重跑 wiring、trace 证据、合成能力测试、Not Applicable 第一/二批能力族、DABstep hour-of-day 和 Microsoft 21-40 中文零售能力闭环。DABstep dev 前 10 回归为 9/10。ACI associated cost / best_fraud_aci_choice 仍需继续按通用 fee what-if candidate table 和 associated cost 语义增强，不能只修当前失败样本。

### Chinese-First Multilingual Data Analysis

目标：把中文问题理解、中文字段映射、中文业务术语、中文日期/金额/百分比格式和中文最终回答作为核心主路径，同时保持英文问题、英文字段和英文 Benchmark 的兼容能力。

影响模块：data_agent_core/core、data_agent_core/llm、data_agent_core/prompts、data_agent_core/executors、data_agent_core/verifier、agent_runtime、multi_agent_workflows、tests/core、tests/benchmark、docs。

优先级：P0。

验收标准：能力类改动必须优先说明中文场景验收方式；Intent Parser / Column Mapping / Planner 必须支持中文业务术语和中文字段名；Response Builder 必须保留中文输出格式；英文 DABstep 回归不能退化；任何只覆盖英文的能力必须明确标记为阶段性限制。

风险：如果只围绕英文 Benchmark、英文 prompt 或英文字段设计，会导致实际中文使用场景不可用；如果为中文写固定字段值、固定问法或当前脱敏数据专用规则，会变成伪泛化补丁。

泛化验证方式：每个中文能力族至少包含一个合成/非 Benchmark 中文用例，并保留一个英文或中英混合回归用例；涉及字段映射的能力应覆盖中文字段名、英文字段名和别名表达。

状态：2026-05-21 已将中文优先、英文兼容写入 MAIN_GOAL、BRANCH_RULES、ARCHITECTURE、API_CONTRACT 和 PHASE_GATES；后续能力开发必须按该规则验收。

### Not Applicable Capability Gap Closure

目标：把 `Not Applicable` 拆成可审计的 `true_unsupported` 与 `capability_gap`，并把可回答问题优先路由到可复用能力族，而不是普通兜底。

影响模块：data_agent_core/core/intent_parser.py、data_agent_core/executors、data_agent_core/output/response_builder.py、data_agent_core/tracing、data_agent_core/benchmark、agent_runtime/data_analysis_roles.py、multi_agent_workflows、tests/core、docs/API_CONTRACT.md。

优先级：P0，阶段：Phase 7。

验收标准：FinalResponse debug / trace / benchmark report 能记录 not_applicable_attribution；`capability_gap` 必须进入 errors 字段并使用 `CAPABILITY_GAP`；新增基础能力族 row_count、distinct_count、repeat_entity_percentage、outlier_count、top_k_share、filtered_metric_ranking 能在合成中英文用例上运行；DABstep / proxy 只作为后验观察。

风险：如果只是把当前 benchmark 失败题的 Not Applicable 改成固定答案或固定字段值，就是伪泛化；如果把所有 Not Applicable 都判为失败，会破坏真正未定义业务概念的安全兜底。

泛化验证方式：每个能力族至少有合成/非 Benchmark 用例，并覆盖中文问题或中文字段名；同时保留英文上传表或 DABstep 回归。

状态：2026-05-22 已完成第一批能力族、Not Applicable 归因、CAPABILITY_GAP 错误类型、trace/debug/report 摘要和合成中英文测试。已继续补齐 null_check、更多英文/中文季度表达、fraud likelihood 多维排名、fee what-if candidate table 和 provider-native tool calling adapter 骨架。DABstep official 本地准确率仍不可计算，public proxy 仅用于后验观察；DABstep 100-130 暴露的 hour-of-day top group / outlier group 已按通用能力族补齐。Microsoft 21-40 中文零售 target / aggregation / ranking / row_count 等能力缺口已用中文零售能力族和合成中文用例闭环。

2026-05-22 追加状态：DABstep all 131-180 的 `outlier_rate_comparison` 和 null-filtered `top_count` 执行缺口已按通用能力族修复，mock 多 Agent 回归 total=50、success_count=50、unexpected_not_applicable=0；official accuracy 仍因 public all answer 为空不可本地计算。

### Chinese Retail 21-40 Capability Closure

目标：修复 Microsoft 脱敏数据 21-40 暴露的中文零售能力缺口，并把能力沉淀为可复用 operation，而不是围绕题号、标准答案或固定字段值优化。

影响模块：data_agent_core/core/chinese_retail_intent.py、data_agent_core/executors/chinese_retail_executor.py、tests/core/test_chinese_retail_capabilities.py、benchmark report、docs。

优先级：P0，阶段：Phase 7。

验收标准：支持服务客户数、合约店占比、目标人数、目标达成率、今日分销排名、历史 SKU / 品类排名、拜访成功率、陈列/拜访记录数、冰柜客户数和历史字段枚举；每项能力至少有合成中文用例；标准答案只用于离线 scorer。

风险：如果将脱敏数据中的固定姓名、固定品类、固定答案或 task_id 写入 parser/executor/test fixture，会形成伪泛化补丁。

泛化验证方式：使用合成中文零售表验证同类操作，并保留英文 DABstep / 通用能力回归；Microsoft 21-40 只作为后验回归观察。

状态：2026-05-21 已新增 executor 能力和合成测试；Microsoft 21-40 mock 与真实 LLM 回归均为 20/20。标准答案只用于离线 scorer，未进入 Agent workflow。

2026-05-22 追加状态：已新增 Microsoft 脱敏数据离线 runner，可按 offset / limit 复跑问题切片；Microsoft 41-60 mock 回归为 20/20。新增能力包括陈列计划记录按人员过滤、服务客户排除“已不合作”、历史分销金额按商品/品类过滤，均有合成中文测试覆盖。

### VDS Chinese BI Period Comparison

目标：补齐桌面 VDS 测试数据中销售、教育、医疗、物流、SaaS 五域的中文周环比 BI 问题能力族。

影响模块：data_agent_core/core/vds_bi_intent.py、data_agent_core/executors/vds_bi_executor.py、data_agent_core/llm/planner.py、tests/core/test_vds_bi_capabilities.py、multi_agent_workflows。

优先级：P0，阶段：Phase 7。

验收标准：支持本周/上周/上上周周期比较；支持周环比排名下降/上升、TopN 增加/减少、增长数量和占比、环比阈值计数、城市/区域等维度环比增长率 Top、当前期阈值 Top、当前期过滤指标 TopN、各组 Top 实体、状态影响、三周期 TopN、同圈层平均值倍数异常；同一能力族必须能迁移到门店、校区、院区、站点、客户等实体。

风险：如果把 O01/E01 等题号、固定文件名、固定门店/校区/客户或标准答案写入 parser/executor，会形成伪泛化补丁；如果只按单一销售域实现，会削弱中文泛化能力。

泛化验证方式：使用合成 VDS BI 表覆盖销售、SaaS、学习等变体；用桌面真实 VDS `问题汇总.xlsx` 五域全部 95 题做 smoke 和离线标准答案 scorer。标准答案只能在 response 生成后评分，不传入 Agent workflow、prompt、Planner、Executor、Verifier、Correction 或 trace。

状态：2026-05-25 已恢复并扩展 VDS 标准答案所需中文 BI 能力族；合成能力测试通过；桌面真实 VDS `问题汇总.xlsx` 五域全部 95 题标准答案 scorer 为 `95/95`，报告为 `outputs/vds_standard_answer_recheck_20260525_core_fix_v2/report.json`。后续继续扩展更多中文真实业务表、字段别名、多表场景和真实 provider 大规模回归。

### DABstep Hour-Of-Day Group Capability

目标：补齐 DABstep 100-130 暴露的小时分组能力缺口，支持“哪个小时交易最多”和“哪个小时离群交易最多”这类通用问题。

影响模块：data_agent_core/core/intent_parser.py、data_agent_core/executors/pandas_executor.py、tests/core/test_generic_capability_operations.py、benchmark report。

优先级：P0，阶段：Phase 7。

验收标准：支持按 `hour_of_day` 分组统计交易数；支持按 Z-Score 或 IQR 识别 outlier 后再按小时分组排名；不依赖 DABstep task_id、题面或答案。

风险：如果把能力写成只处理当前两个 task_id，就会形成伪泛化补丁。

泛化验证方式：使用合成 payments 表验证 hour-of-day top count 和 top outlier group；DABstep 100-130 只作为后验执行覆盖观察。

状态：2026-05-21 已完成。DABstep all 100-130 mock 多 Agent 回归 total=31、success_count=31、unexpected_not_applicable=0；official accuracy 仍因 public all answer 为空而不可本地计算。

### DABstep Submission Quality Gate and Easy Capability Closure

目标：在 Phase 7.1 建立提交治理和 Easy 泛化能力闭环，确保 DABstep submission 文件与当前代码、报告和预测产物一致，并把 Easy 低分风险归因到可复用能力族，而不是按题号或 proxy answer 优化。

影响模块：benchmark runner、response builder、tests、docs、submission tooling。

优先级：P0，阶段：Phase 7.1。

验收标准：submission gate 能校验行数、task_id 覆盖、必填字段、`agent_answer` 格式、空答案、对象泄漏、debug / trace 泄漏、API key 泄漏和旧 Desktop 文件误传；submission 文件必须绑定当前 commit hash、report hash、prediction hash 和生成命令；Easy / Hard 风险报告必须生成，并明确不是 hidden official accuracy。

风险：禁止 task_id、hidden answer、public proxy answer、固定题面、固定样本值、历史 accepted-answer pool 或当前 leaderboard 反馈进入核心链路；禁止把外部 leaderboard 结果写成本地可复现官方准确率。

泛化验证方式：每个 Easy 能力族至少使用一个合成或非 Benchmark 用例验证，中文优先并保留英文 DABstep 回归；能力族包括 counting、top/ranking、fraud ratio、boolean yes/no、null check、field values、outlier、quantile、schema/missing-column。

是否影响 contracts：当前文档阶段不影响；未来如果 submission gate 需要新增报告 metadata，必须先更新契约说明。

是否影响 API_CONTRACT：当前文档阶段不影响；submission tooling 不应改变稳定后端 API。

是否影响 tracing：当前文档阶段不影响；未来可增加 submission/report metadata，但不得记录完整 Chain of Thought、API key、hidden answer 或 proxy answer。

是否影响 errors：当前文档阶段不影响；未来如果新增 submission gate 错误类型，必须同步 errors 文档和测试。

状态：2026-05-22 新增为下一阶段目标；本轮只做文档补录和阶段状态统一，不实现新算法、不修改 benchmark scoring 链路、不引入 Microsoft Agent Framework 依赖。

### Phase 8 Multi-file / Multi-table Generalization Closure

目标：补齐多文件精准路由、多表 join、表关系发现、澄清机制、Executor / Verifier / trace 闭环，保证上传表多文件、多表问题不再静默退回 `primary_table`。

影响模块：backend、data_agent_core/contracts、data_agent_core/core、data_agent_core/executors、data_agent_core/verifier、data_agent_core/tracing、multi_agent_workflows、tests。

优先级：P0，阶段：Phase 8。

验收标准：支持一次上传多文件；profile 保留 `source_file`、`sheet`、`table_name`；销售 / 库存两表精准路由；订单 + 客户按城市聚合通过可信 join；无 join key 返回澄清或标准错误；多对多 join 不静默成功；旧单表能力不退化。

风险：如果只按当前文件名、当前字段值或当前测试样本写规则，会形成伪泛化补丁；join 如果未经过唯一性、值重叠率和 many-to-many 风险校验，会把错误聚合伪装成成功。

泛化验证方式：合成销售 / 库存、订单 / 客户、无 join key、多对多 join 和旧单表回归；同时复跑 DABstep dev 1-10、DABstep public all 1-450、微软脱敏数据 1-300 和原本 VDS 95 smoke。

是否影响 contracts：是。`LogicForm` / `AnalysisPlan` 增加 `source_tables`、`table_selection_reason`、`join_plan`。

是否影响 API_CONTRACT：是。新增 `/api/data-agent/upload-batch`，并记录多文件 profile 和 join trace 展示字段。

是否影响 tracing：是。RunTrace 增加 `source_tables`、`table_selection_reason`、`join_plan`、`join_execution_summary`。

是否影响 errors：是。无可信 join key、多对多风险、多表未 join 和 ID fallback 必须通过 verification / correction_action / warnings / errors 表达。

状态：2026-05-23 已完成。全量 unittest 已随 Phase 10 收口更新到 `147 tests OK`；Phase 8 mock / 离线门禁为 DABstep dev `9/10`、DABstep public all `450/450`、微软脱敏数据 `300/300`、原本 VDS `95/95`，关键风险指标为 0。真实 DeepSeek representative 已补跑：DABstep dev `9/10`、微软脱敏数据 1-20 `20/20`、原本 VDS 五域 15 题 `15/15`；Phase 10 after-fix full real 已补跑三数据集，DABstep public all `450/450` 执行覆盖、Microsoft `300/300`、VDS 95 smoke `95/95`。

### Phase 9 Frontend Workbench

目标：在 Phase 8 核心算法和 API 契约通过后，交付前端产品化首版，把多文件、多表、澄清和结果契约展示为可操作 workbench。

影响模块：frontend、backend/main.py、README.md、docs/API_CONTRACT.md。

优先级：P0，阶段：Phase 9。

验收标准：支持单文件 / 多文件上传、DAB context 包上传、文件 / sheet / table profile 预览、问题提交、结果表格、verification、warnings、errors、join plan trace、join execution summary 和 run history；前端不实现指标公式、join、排序聚合、评分、规则解析或核心数据计算。

风险：如果前端开始自行计算指标或 join，会破坏 Phase 8 已冻结的后端契约和 Verifier 安全边界；如果前端依赖 debug 进行业务计算，会导致稳定契约漂移。

泛化验证方式：用 mocked API route 做桌面 / 移动浏览器 smoke，确认页面能展示多文件 profile、join trace、warnings / errors / verification；核心算法继续以后端单元测试和 benchmark 门禁验证。

是否影响 contracts：否。首版前端只消费既有契约。

是否影响 API_CONTRACT：是。记录 `/workbench`、`/frontend`、`upload-batch` 和 join trace 展示边界。

是否影响 tracing：否。首版只展示 Phase 8 trace 字段。

是否影响 errors：否。首版只展示后端 errors。

状态：2026-05-23 已完成首版。`backend/main.py` 挂载 `/frontend` 和 `/workbench`；前端 smoke 无 console / page error，截图为 `outputs/phase9_workbench_desktop_20260523.png` 和 `outputs/phase9_workbench_mobile_20260523.png`。2026-05-25 已允许网页端选择 `.json` / `.md`，完整 DAB context 包由后端识别为 `dabstep_context` dataset，前端仍只上传和展示。

### Phase 7.5 Tool / Safety

目标：硬化受控工具层和安全边界，使 ToolDispatcher、工具 schema、角色权限、timeout、错误归一化和 trace-safe summary 能支撑真实 provider tool loop。

影响模块：agent_runtime、data_agent_core/configs、data_agent_core/executors、data_agent_core/tracing、tests/agent_runtime、tests/architecture。

优先级：P0，阶段：Phase 7.5。

验收标准：未知工具、缺参数、类型错误、角色越权、timeout 和 callable failure 都返回结构化 ToolResult；Pandas / NumPy 白名单、SQL / DuckDB read-only 限制、文件访问根目录策略明确；工具 trace 不含完整 Chain of Thought、raw reasoning tokens、API key 或敏感原始数据。

风险：如果工具层过早开放自由 Python、自由 SQL、shell、网络或外部文件访问，会破坏可复现性和安全边界。

泛化验证方式：工具 focused tests、architecture tests、DABstep dev 1-10、DABstep public all 1-450 mock、Microsoft 1-300 mock scorer 和 VDS 95 smoke 均不退步。

是否影响 contracts：可能影响内部 Tool contract；如字段变更必须同步 agent_runtime docs。

是否影响 API_CONTRACT：否，后端稳定 API 不因工具硬化变更。

是否影响 tracing：是。只允许扩展 trace-safe 工具摘要，不记录敏感内容。

是否影响 errors：可能影响工具错误归一化；新增错误类型必须同步测试和文档。

### Phase 7.6 Provider-native Smoke

目标：接入真实 OpenAI / DeepSeek provider-native tool loop smoke，验证 provider tool call 能映射为内部 ToolCall 并经过 ToolDispatcher。

影响模块：agent_runtime/provider_native_tool_adapter.py、data_agent_core/llm、agent_runtime/tool_dispatcher.py、tests/agent_runtime。

优先级：P0，阶段：Phase 7.6。

验收标准：真实 smoke 可完成 profile_schema、build_analysis_plan、execute_pandas_plan、execute_sql_plan、verify_results、build_chart_spec、generate_insight 的闭环；记录 provider、model、latency、cost、prediction hash 和 report hash；没有 key 时只运行 mock，不冒充真实 provider 结果。

风险：如果把 provider-native adapter 设为生产默认链路，或绕过 ToolDispatcher，会让模型获得不受控执行能力。

泛化验证方式：mock provider loop 和真实 provider smoke 分开记录；三数据集 non-regression gate 必须通过。

是否影响 contracts：不应改变内部 ToolDefinition / ToolCall / ToolResult 契约。

是否影响 API_CONTRACT：否。

是否影响 tracing：是。新增真实 provider smoke metadata 时必须保持 trace-safe。

是否影响 errors：否，除非新增 provider transient failure 归一化类型。

### Phase 7.7 DuckDB Runtime

目标：把 DuckDB 作为 SQL 目标执行层，sqlite 仅保留 fallback，增强执行层可信度、覆盖率和可审计性。

影响模块：data_agent_core/executors、data_agent_core/core/capability_registry.py、data_agent_core/verifier、data_agent_core/tracing、tests/core。

优先级：P1，阶段：Phase 7.7。

验收标准：DuckDB 只允许 read-only SELECT / CTE、单语句、受控 limit / preview；结果必须经过 Result Normalizer、Verifier 和 trace 摘要；sqlite fallback 不退化。

风险：如果把模型输出的 raw SQL 直接执行，或让 DuckDB 路径复制 Pandas / Verifier 业务逻辑，会破坏安全边界和一致性。

泛化验证方式：合成 SQL-compatible 用例、Pandas / DuckDB covered-subset consistency、DABstep / Microsoft / VDS 三数据集回归。

是否影响 contracts：可能影响 executor capability metadata。

是否影响 API_CONTRACT：否。

是否影响 tracing：是。需要记录 DuckDB execution summary，但不得记录敏感原始数据。

是否影响 errors：可能新增 read-only SQL guardrail 失败归因。

### Phase 7.8 Multi-Agent Parallel / Retry

目标：在当前顺序 multi-agent 基线之上，增加 executor 有限并行和 bounded correction retry。

影响模块：agent_runtime、multi_agent_workflows、data_agent_core/verifier、data_agent_core/tracing、tests/multi_agent_workflows。

优先级：P1，阶段：Phase 7.8。

验收标准：Pandas / SQL / DuckDB executor 可有限并行；Planner、Verifier、Correction 的核心决策不并行；semantic mismatch、tool error、format mismatch 和 capability_gap 分开触发固定最大轮数的 correction retry；所有 attempt 写入 trace。

风险：如果并行破坏 WorkflowState 一致性、trace 可复现性或 Verifier 边界，会导致不可审计的 Agent 行为。

泛化验证方式：每个 Agent 独立测试、WorkflowState 序列化测试、三数据集 non-regression gate。

是否影响 contracts：可能影响 WorkflowState / AgentResult 内部字段。

是否影响 API_CONTRACT：否。

是否影响 tracing：是。必须记录并行 executor 和 retry 摘要。

是否影响 errors：可能影响 retry reason 分类。

### Phase 7.9 MAF Demo

目标：验证 Microsoft Agent Framework 作为可选承载层映射 AgentRole、ToolDefinition、ToolCall、ToolResult 和 WorkflowState。

影响模块：ms_agent_framework_adapter、agent_runtime、requirements-ms-agent.txt、tests/ms_agent_framework_adapter。

优先级：P2，阶段：Phase 7.9。

验收标准：真实 MAF demo 或 cloud workflow 能承载内部角色和白名单工具映射；本地未安装 agent-framework 时仍给出清晰错误；data_agent_core 不 import ms_agent_framework_adapter 或 agent_framework。

风险：如果 adapter 承载核心算法，会导致未来无法替换框架；如果把 agent-framework 变成核心依赖，会破坏依赖边界。

泛化验证方式：fake framework tests、真实 demo smoke、dependency boundary test、三数据集 non-regression gate。

是否影响 contracts：不应改变核心数据契约；只允许 adapter mapping。

是否影响 API_CONTRACT：否。

是否影响 tracing：仅可记录 adapter / workflow 摘要。

是否影响 errors：否。

### Phase 7.10 ACI / Complex BI

目标：补齐 `best_fraud_aci_choice`、ACI associated cost、fee what-if candidate table、candidate-pair / rule semantics，以及 VDS 趋势、状态影响、毛利率、支付 / 配送 / 付费方式等复杂中文 BI 问法。

影响模块：data_agent_core/core、data_agent_core/executors、data_agent_core/verifier、agent_runtime、multi_agent_workflows、tests/core、tests/benchmark。

优先级：P0，阶段：Phase 7.10。

验收标准：每个新增能力族有合成或非 Benchmark 用例、同类变体、中文字段 / 中文问题用例和旧代表回归；DABstep dev 1-10、DABstep public all 1-450 mock、Microsoft 1-300、VDS 95 smoke 和当前分支 VDS 标准答案 scorer 不退步。

风险：如果按 task_id、题面、public proxy、accepted answer、hidden answer、固定样本值或当前错误形态修复，就是伪泛化补丁。

泛化验证方式：能力族报告必须说明 supported inputs、unsupported boundaries、合成/同类验证和三数据集回归。

是否影响 contracts：可能影响 LogicForm / AnalysisPlan 能力字段。

是否影响 API_CONTRACT：通常否；如新增稳定前端展示字段必须先更新 API_CONTRACT。

是否影响 tracing：是。需要记录 candidate table / selected candidate / semantic verification 摘要。

是否影响 errors：可能新增 capability gap 或 semantic mismatch 细分。

### Phase 9.1 Workbench Confirmation

目标：在 Phase 9 首版 workbench 后新增字段确认、join key 确认、低置信度澄清交互和评测回看面板。

影响模块：frontend、backend API 调用壳、docs/API_CONTRACT.md、tests/backend、浏览器 smoke。

优先级：P1，阶段：Phase 9.1。

验收标准：前端只收集用户确认和展示后端结果；不实现指标公式、join、排序、聚合或评分；桌面 / 移动 smoke 无 console error。

风险：如果前端依赖 debug 字段做业务计算，或把核心计算搬到浏览器，会破坏 Phase 8 / Phase 9 边界。

泛化验证方式：mocked API route 的桌面 / 移动 smoke，后端仍用三数据集 non-regression gate 守护核心算法。

是否影响 contracts：否，除非确认交互需要新增稳定请求字段。

是否影响 API_CONTRACT：可能影响；新增稳定确认字段前必须先更新 API_CONTRACT。

是否影响 tracing：否。首版只展示 trace-safe 字段。

是否影响 errors：否。只展示后端 errors / warnings。

### Phase 10 Visualization / Insight / Quality / Process View

目标：让 verified result 具备自动图表、洞察建议、数据质量报告和安全过程可视化。

影响模块：data_agent_core/contracts、data_agent_core/output、data_agent_core/core、agent_runtime、multi_agent_workflows、backend、frontend、tests/core、docs/API_CONTRACT.md。

优先级：P0，阶段：Phase 10。

状态：2026-05-23 已完成首版并完成 after-fix full real 收口。ChartSpec v2 支持 bar / horizontal_bar / line / pie / donut / histogram / KPI；InsightResult v2 支持 key_numbers、anomaly_findings、volatility_findings、business_suggestions、caveats；DataQualityReport 支持 upload/profile 和 analyze 响应，且上传表质量报告已缓存到 dataset profile；reasoning_trace_view 只展示结构化过程摘要，不暴露完整 Chain of Thought。验收结果：Full unittest `147 tests OK`，DABstep dev `9/10`，DABstep public all mock `450/450`，Microsoft 1-300 mock `300/300`，VDS 95 smoke `95/95`；真实 DeepSeek full 为 DABstep public all `450/450` 执行覆盖、Microsoft `300/300`、VDS 95 smoke `95/95`，汇总在 `outputs/phase10_full_real_three_dataset_deepseek_20260523_summary_after_fix.json`。

验收标准：前端只渲染后端契约；用户问“文件有什么问题”时返回质量扫描报告；图表自动选择不由前端计算；trace view 不包含 `chain_of_thought`、`cot`、`hidden_reasoning`、`full_reasoning`、API key 或 hidden answer。

风险：如果前端自行实现图表选择、异常规则或清洗逻辑，会破坏核心算法在后端 / data_agent_core 的边界；如果展示 raw CoT，会破坏 trace redaction 安全边界。

泛化验证方式：中文上传表合成用例、chart / insight / quality / trace 单元测试、backend service smoke、DABstep / Microsoft / VDS 三数据集 non-regression gate。

是否影响 contracts：是。扩展 FinalResponse、ChartSpec、InsightResult，并新增 DataQualityReport / ReasoningTraceStep。

是否影响 API_CONTRACT：是。新增 `quality_report`、`reasoning_trace_view` 和 chart / insight v2 字段说明。

是否影响 tracing：是。RunTrace 增加 quality_report 和 reasoning_trace_view。

是否影响 errors：否。首版复用现有 warnings / errors，不新增错误类型。

### Phase 11 Conversation Isolation / Session Persistence / Quiet Process UX

目标：把 Workbench 从单页内存状态升级为可恢复的 GPT-like 会话式数据分析体验，支持会话隔离、历史续聊、多窗口独立对话和未来用户隔离升级。

影响模块：backend、backend/storage、backend/routers、frontend、docs/API_CONTRACT.md、tests/backend、浏览器 smoke。

优先级：P0，阶段：Phase 11。

状态：First implementation landed。已新增本地 JSON conversation store、`conversation_id`、conversation list / get / rename endpoints，`/message` 自动追加 user / assistant turn，Workbench 可从后端历史列表载入旧消息并持久化重命名；2026-05-25 已新增 `monitor_run_id` 和 SSE 安全事件流，用于本地 Agent 监看。URL 恢复、多窗口实时同步、普通 CSV / Excel 跨进程 DataFrame 恢复、真实登录鉴权和多租户隔离仍未完成。

验收标准：新增 `conversation_id` 会话层；每个会话独立保存消息、当前 dataset、runs 和最近结果；无 `conversation_id` 的新消息默认创建独立会话；历史 Chat 从后端会话列表加载；旧 `dataset_id` analyze / upload 调用继续兼容。未完成项继续要求 URL `conversation_id` 恢复、多窗口同会话同步和跨进程 dataset 表恢复。

UX 验收标准：过程展示默认只占一行，使用小号浅灰文字展示最新安全摘要，例如“用户提到了‘城市订单金额’，我会先确认城市字段和金额字段。”；右侧或末尾提供 `查看过程` / `查看 N 步` 点击提示；展开后只显示用户可理解的结构化步骤，不展示后端审计 JSON、quality_report、warnings、verification、join trace 或完整 Chain of Thought。

未来用户隔离预留：conversation schema 当前预留 `owner_id`、`tenant_id` 和 `owner_context`；v1 可使用 local anonymous scope，但所有 list / get / update / upload / analyze 的服务层接口都要保留 backend owner filter 边界，不能只靠前端隐藏历史。

风险：如果只用 browser localStorage 存完整历史，会导致多窗口、重启和未来多用户隔离不可控；如果把 raw CoT 或后端术语直接展示给用户，会破坏安全边界和 GPT-like 体验；如果前端根据历史自行做 join、聚合、排序或评分，会破坏核心算法边界。

测试方式：backend 单测覆盖 create/list/get/update conversation、message 追加到正确会话、旧无 `conversation_id` 调用兼容；前端静态测试覆盖 conversation list、history get、rename PATCH、旧消息恢复和安静过程展开。后续还需浏览器 smoke 覆盖两个窗口上传不同 CSV 并提问、回到历史会话继续提问、URL 恢复同一会话。

是否影响 contracts：是。新增 conversation schema 和可选 `conversation_id` / owner 字段。

是否影响 API_CONTRACT：是。已记录当前 endpoints、response extension 和后续边界。

是否影响 tracing：是。只能复用或派生 trace-safe `reasoning_trace_view` 摘要，不新增 raw CoT、raw prompt 或 raw reasoning token 暴露面。

是否影响 errors：可能。实现时可复用现有 errors；如新增 conversation not found / owner mismatch 等稳定错误类型，必须先写入 API_CONTRACT 和 tests。

### Phase 12 GPT-like General Answer / Insight / Activity Stream

目标：把 Workbench 从“能展示结果”升级为“像 GPT / ChatGPT Data Analysis 一样自然解释数据、展示安全过程、展示可复现代码和给出有业务价值洞察”的体验，并把 GPT-like parity review 作为红线。

影响模块：data_agent_core/output、data_agent_core/core/file_parser.py、data_agent_core/core/schema_profiler.py、backend/services、frontend、docs/EVALUATION_GATE.md、tests/core、tests/backend、tests/architecture、浏览器 smoke。

优先级：P0，阶段：Phase 12。

状态：First implementation landed。已落地 `overview_report`、enhanced insight、safe `execution_artifacts`、dataset overview 活动流、semantic chart planning guard 和规则文件自动绑定；后续继续扩展文件解析、回答模板、图表语义和 Workbench 排版体验。

验收标准：general / overview 问法必须生成结构化数据报告；Insight 必须带 observation / evidence / recommended action；图表不能把 ID / reference / bin / year / hour 等字段误当指标；Workbench 必须展示主回答、表格/图表、活动流和代码 artifact；每次体验类修改都必须执行 GPT-like parity review，对比 GPT / ChatGPT Data Analysis 同类结果或冻结标准 GPT 参考结果。

风险：如果只按当前截图、当前字段、固定文件名、固定问法或当前样本值调整，就是伪泛化补丁；如果只看单测和 smoke，不对照 GPT 结果，就可能交付“能跑但不像 GPT”的文件解析、回答结构、排版样式和交互体验。

泛化验证方式：至少覆盖一个非 payments 合成表、一个中文真实业务表或同类变体、一个浏览器可见 Workbench smoke，并在汇报中记录参考来源、主要差距、接受差异和被打回重写的点；GPT-like parity 差距很大时必须重写后再测。

是否影响 contracts：是。体验增强必须优先落到后端稳定契约，不能只改前端临时拼接。

是否影响 API_CONTRACT：可能。新增或改变稳定响应字段时必须同步 API_CONTRACT。

是否影响 tracing：是。只能使用 trace-safe `process_view_v2` / `reasoning_trace_view` / execution artifact 摘要，不暴露完整 Chain of Thought。

是否影响 errors：可能。若新增体验验收相关错误类型，必须同步 API_CONTRACT 和测试。

## TODO

- 新功能进入开发前，先确认是否影响 contracts / API_CONTRACT / tracing / errors。
- Phase 7.5 - 7.10 必须按编号推进，且每个工程阶段都要通过 DABstep、Microsoft 和 VDS 三数据集 non-regression gate。
- Phase 8 后续只做 Guardrail，不重开 Phase 8 主体；Phase 9 后续按 Phase 9.1 做确认和回看面板，不把核心计算搬到前端。
- Phase 11 后续继续补 URL conversation_id 恢复、多窗口同步、跨进程 dataset 表恢复和 owner filter 强制校验；不得把本地匿名会话误写成已实现登录权限。
- Phase 12 后续所有文件解析、回答、排版、图表、过程流和代码 artifact 改动都必须执行 GPT-like parity review；差距很大直接打回重写。
