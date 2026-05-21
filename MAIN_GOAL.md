# MAIN GOAL

## 项目主目标

本项目的核心目标是从头构建一个可评测、可复现、可扩展的数据分析 Agent 内核。

系统需要支持用户上传 CSV / Excel 文件，Agent 自动解析文件结构和字段含义，根据用户自然语言问题生成分析计划，并通过 Pandas / NumPy 和 SQL / DuckDB 两条执行路径完成数据分析。

执行结果需要经过自查、自纠和一致性校验。确认结果可信后，再生成解释、建议和可视化图表配置，最终通过后端 API 返回给前端展示。

## 当前阶段目标

当前阶段优先完成：

1. 搭建 data_agent_core 核心算法目录
2. 搭建 data_agent_core/contracts 数据契约目录
3. 搭建 data_agent_core/errors 错误体系目录
4. 搭建 data_agent_core/tracing 运行追踪目录
5. 搭建最小 backend API 目录
6. 搭建 agent_runtime 内部 Agent 抽象目录
7. 搭建 ms_agent_framework_adapter 微软框架适配层目录
8. 搭建 multi_agent_workflows Phase 6 最小多 Agent 工作流目录
9. 搭建 docs 工程文档目录
10. 搭建 tests/architecture 架构边界测试目录
11. 定义文件解析、字段画像、问题理解、分析计划、执行器、校验器、解释器、图表规划器的模块边界
12. 支持未来 CSV / Excel 文件解析
13. 支持未来 Pandas / NumPy 执行路径
14. 支持未来 SQL / DuckDB 执行路径
15. 支持未来 Pandas 与 SQL 结果对比
16. 支持未来基础自查自纠
17. 支持未来 Benchmark Runner
18. 提供最小后端接口，供前端上传文件、提交问题、获取结构化结果
19. 预留未来单 Agent 到多 Agent 的平滑迁移能力
20. 预留 Phase 5 受控 Tool Calling 能力，把字段画像、计划构建、Pandas / SQL 执行、结果校验和图表规划包装为白名单工具，但不允许模型直接执行任意代码、SQL、shell、网络请求或外部文件访问

## 当前实现状态

2026-05-21 更新：

1. 已建立 Phase 0 项目规则和目录骨架。
2. 已新增可运行的核心算法 MVP，用于本地核心算法测试。
3. 已支持 DABstep 风格的业务表和规则知识库输入：payments.csv 作为业务数据库表，manual.md / fees.json / merchant_data.json 作为文档和规则知识库。
4. 已支持 DABstep dev 前 10 题本地评测，当前验证结果为 9/10，准确率 90%。
5. all.jsonl 可生成前 10 题预测文件，但本地 all.jsonl 的 answer 字段为空，因此不能本地计算准确率。
6. 该实现不使用 task_id、标准答案、固定题面、固定数据值或只适配当前失败样本的补丁进入分析链路。
7. 已新增 LLM 单 Agent 链路，Intent Parser、Column Mapping、Analysis Planner、Verifier / Critic、Correction Planner、Insight Generator 和 Chart Planner 均预留 LLM 参与；确定性代码负责文件/规则读取、执行、结果标准化、规则校验和评分。
8. LLM key 只能通过环境变量提供，禁止写入仓库、文档、trace 或 CHANGELOG。
9. 已进入 Phase 1 / Phase 2 / Phase 3 最小可测状态：支持上传 CSV / Excel 文件解析入口、DatasetProfile、UploadedDatasetAgent、最小 backend service upload/profile/analyze、Benchmark metrics 和 error_analysis 聚合。
10. 当前最小后端 API 仍是调用壳，核心 Pandas / SQL / Verifier / Insight / Chart 逻辑仍在 data_agent_core。
11. public all.jsonl 的 answer 字段为空，不能本地计算完整 450 题官方准确率；dev 前 10 题仍用于本地可复现 smoke benchmark。
12. Tool Calling 暂定为 Phase 5 后置能力；当前只保留 ToolRegistry / tool mapping 骨架，不在当前阶段启用模型原生工具循环或 thinking-mode 工具回填。
13. 已补充 Phase 5 受控 Tool Calling 的 provider-neutral 契约骨架：ToolDefinition、ToolCall、ToolResult、ToolTraceEvent、ToolDispatcher、Data Agent tool catalog 和 Microsoft adapter tool mapping；当前仍不启用 provider 原生工具循环。
14. 已开始实现 Microsoft Agent Framework adapter 和真实内部工具 callable：工具 callable 位于 agent_runtime，调用既有 data_agent_core 核心模块；Microsoft adapter 只做可选 function tool、agent factory 和 sequential workflow builder，不让 data_agent_core 依赖 Microsoft Agent Framework。
15. 已切换到 Phase 6 最小可运行多 Agent workflow：backend analyze 默认走 multi_agent；DABstep 多 Agent runner 可运行 dev 前 10 题并保持 9/10；data_agent_core 仍不依赖 multi_agent_workflows。
16. 已开始把多 Agent 从顺序角色编排升级为业务口径驱动的计划、校验和自纠闭环：LogicForm 支持 metric、metric_definition、numerator、denominator、group_by、objective 和 options；Verifier 能识别 top fraud 使用 raw count 的语义错误，并要求修正为 fraud_volume_rate。
17. 当前 9/10 的主要瓶颈不是多 Agent 框架或 Microsoft adapter，而是 ACI incentive 类问题的 associated cost 费用口径仍未完全对齐；该问题必须按通用 fee what-if / ACI candidate table 能力继续修复，禁止只针对当前 DABstep 样本、当前字段值或当前问法补坑。
18. DABstep all 前 50 题可运行 public split 执行覆盖；本地 public all.jsonl 的 answer 字段为空，因此只能验证执行率和 trace，不能本地计算官方准确率。

## 架构原则

1. Rule NO.1：禁止伪泛化补丁。特调不只指按 Benchmark 题号、task_id、题面、标准答案或 public proxy 答案池写规则；凡是看到某个错误后写出的逻辑只能覆盖当前数据集、当前字段值、当前问法或当前 benchmark slice，不能迁移到同类业务问题和其他数据集，都视为特调。所有提升必须抽象为可复用能力族，说明适用边界，并用非 Benchmark 或合成通用用例证明泛化能力没有下降。
2. 核心算法必须放在 data_agent_core/ 中
3. 后端 backend/ 只作为调用壳，不承载核心数据分析逻辑
4. 前端只负责上传、提问和展示，不参与数据处理
5. Agent Framework 只能作为后续 workflow 编排层，不允许污染核心算法
6. Benchmark 只能用于评估、错误归因和回归测试，不允许针对单题硬编码，也不允许用看似通用但只服务当前样本的条件分支替代能力建设
7. 历史推进顺序为先做单 Agent，当前已切换为最小多 Agent 默认链路
8. 先保证核心算法稳定，再扩展外围工程
9. 所有模块必须可测试、可复现、可回归
10. 核心算法不依赖 Microsoft Agent Framework
11. Microsoft Agent Framework 适配层可以调用核心算法
12. 多 Agent 角色必须通过统一输入输出协议交互
13. 后续替换 Agent 框架时，不应重写核心算法
14. 所有核心模块必须基于 contracts 中的稳定契约交互
15. 所有 analyze 请求未来必须生成 run_id
16. 所有 API 响应未来必须包含 response_version
17. 所有错误必须进入 errors 字段
18. 所有警告必须进入 warnings 字段
19. 工程文档中不要求模型输出完整 Chain of Thought，只保留 structured analysis plan、reasoning summary、execution trace、verification notes
20. Agent 必须包含 LLM 单 Agent 链路；LLM 负责意图理解、字段语义映射、分析计划、校验辅助、修正方向、解释和图表语义规划，本地执行器负责确定性计算和校验
21. LLM API key 必须从环境变量读取，不允许提交到 Git
22. LLM 不能绕过代码执行器、Result Normalizer、Verifier 或 Correction Planner 直接输出最终结论
23. DABstep / Benchmark 的 task_id 和标准答案不能进入 LLM 输入或核心分析链路
24. Tool Calling 只能调用内部白名单工具，工具定义必须有稳定名称、JSON schema、参数校验、超时和结果摘要策略
25. Tool Calling 的工具实现仍然属于 data_agent_core 或 agent_runtime 的受控代码路径，不能把核心算法写进 provider adapter、Microsoft adapter 或多 Agent workflow
26. 模型可以选择工具和填写参数，但不能获得 raw Python、raw SQL、shell、网络访问或任意文件访问能力
27. 工具调用 trace 只能记录工具名、参数摘要、结果摘要、错误和耗时，不记录完整 Chain of Thought、raw reasoning tokens、API key 或敏感数据
28. OpenAI / DeepSeek / Microsoft Agent Framework 只能作为工具调用协议适配层；内部工具契约必须保持 provider-neutral

## Microsoft Agent Framework 策略

Microsoft Agent Framework 是多 Agent 编排的候选承载框架，但不是当前核心算法依赖。当前默认 Phase 6 workflow 使用内部 runtime；Microsoft adapter 只是可选承载和映射层。

当前实现方式：

1. ms_agent_framework_adapter/ 可以可选导入 `agent_framework`，但该依赖只允许出现在 adapter 内。
2. data_agent_core/ 永远不能 import Microsoft Agent Framework。
3. agent_runtime/ 定义 ToolDefinition、ToolCall、ToolResult、ToolDispatcher 和内部工具 callable。
4. ms_agent_framework_adapter/framework_tools.py 将内部白名单工具包装成 Microsoft Agent Framework function tool。
5. ms_agent_framework_adapter/framework_agents.py 将内部 AgentRole 映射成 Microsoft Agent Framework Agent。
6. ms_agent_framework_adapter/framework_workflow.py 将角色顺序映射为 sequential workflow。
7. 如果本地未安装 `agent-framework`，adapter 必须给出清晰错误；单测必须能用 fake framework 验证适配逻辑。
8. requirements-ms-agent.txt 作为独立可选依赖入口，不合入核心依赖。
9. 不把文件解析、Pandas、SQL、Verifier、Benchmark 或业务规则写入 adapter。
10. 不把 Microsoft Agent Framework 作为 data_agent_core 或 backend 的强依赖。

未来迁移方式：

1. data_agent_core 提供稳定函数和类
2. agent_runtime 定义 AgentRole、AgentTask、AgentResult、WorkflowState
3. agent_runtime 将字段画像、计划构建、Pandas / SQL 执行、校验、图表和解释包装为受控内部工具
4. ms_agent_framework_adapter 将内部 AgentTask、ToolDefinition 和 WorkflowState 映射为 Microsoft Agent Framework 的 agent / tool / workflow step
5. multi_agent_workflows 负责组合 Planner、Executor、Verifier 等角色
6. backend 仍然只调用统一服务入口，不直接依赖具体 Agent 框架

## 当前不做

当前阶段不做：

1. 用户登录
2. 权限系统
3. 多租户隔离
4. 复杂前端页面
5. 复杂后端业务系统
6. 数据库持久化复杂设计
7. WebSocket
8. 异步任务队列
9. 大规模部署工程
10. 微服务拆分
11. 旧 BigCat / VDS 主流程重构
12. 针对 Benchmark 单题特判，或只服务当前错误样本、无法迁移到同类数据集问题的伪泛化补丁
13. 一上来做复杂多 Agent 编排
14. 在本轮引入 Microsoft Agent Framework 作为强依赖
15. 在本轮实现复杂 Agent workflow
16. 在本轮实现完整业务逻辑
17. 在本轮实现 provider 原生 OpenAI / DeepSeek tool call loop、DeepSeek thinking mode 工具回填或 OpenAI Responses API 工具循环

## 核心工作流

用户问题
↓
LLM：Intent Parser
↓
LLM + 规则：Column Mapping
↓
LLM：Analysis Planner
↓
代码：Pandas Executor
↓
代码：SQL / DuckDB Executor
↓
代码：Result Normalizer
↓
规则 + LLM：Verifier / Critic
↓
规则 + LLM：Correction Planner
↓
LLM：Insight Generator
↓
LLM + 规则：Chart Planner
↓
后端返回 JSON

说明：

1. LLM 负责语义理解、计划草案、解释和辅助校验，不负责绕过执行器直接编造答案。
2. Pandas / SQL / DuckDB 执行、结果标准化、规则校验和 Benchmark 评分必须由代码完成。
3. Correction Planner 只能给出修正方向，真实修正仍由受控代码路径执行。
4. Trace 只记录 structured analysis plan、reasoning summary、execution trace、verification notes，不记录完整 Chain of Thought。

## Phase 5 受控 Tool Calling

Phase 5 的目标不是让模型自由执行代码，而是把已有受控能力包装成可审计工具：

1. profile_schema：读取 DatasetProfile / TableProfile / ColumnProfile，返回字段类型、语义 hint、缺失值和可分析列摘要。
2. build_analysis_plan：把已验证的意图和字段映射转为 LogicForm / AnalysisPlan 草案。
3. execute_pandas_plan：执行已经校验过的 Pandas / NumPy 分析计划。
4. execute_sql_plan：执行已经校验过的 SQL / DuckDB 分析计划。
5. verify_results：比较 Pandas / SQL 结果，输出可信度、错误类型和修正方向。
6. build_chart_spec：在结果可信后生成前端中立图表配置。
7. generate_insight：只基于已验证结果生成解释、建议和 caveat。

Phase 5 执行顺序：

用户问题
↓
LLM 选择白名单工具并填写 JSON 参数
↓
Tool Dispatcher 校验 schema、权限、超时和数据边界
↓
受控代码工具执行
↓
工具结果摘要回填给 LLM
↓
Verifier / Response Builder 生成最终结构化 JSON

注意：

1. 工具调用是单 Agent 能力增强，不等同于多 Agent。
2. 工具层必须先支持 mock provider 和本地单元测试，再接 OpenAI / DeepSeek provider adapter。
3. DeepSeek thinking mode 或 OpenAI reasoning item 只能由 provider adapter 内部维护，不进入稳定 trace 或 API 响应。
4. 工具调用失败必须进入 errors / warnings，不能由模型自然语言掩盖。

当前实现状态：

1. 内部工具 callable 已能调用 DatasetProfile 生成、AnalysisPlan 构建、Pandas 执行、SQL 执行、结果校验、ChartSpec 生成和 InsightResult 生成。
2. ToolDispatcher 负责工具名、角色、JSON 参数和 trace-safe 摘要。
3. Microsoft Agent Framework adapter 可以把内部工具包装为 function tool，但仅作为可选适配层。
4. 仍未启用 provider 原生 OpenAI / DeepSeek tool loop，仍不允许模型获得 raw Python、raw SQL、shell、网络或任意文件访问。

## 当前多 Agent 工作流

Phase 6 最小可运行多 Agent 结构：

用户问题
↓
Planner Agent：LLM 为主
↓
Data Engineer Agent：代码为主，LLM 辅助字段语义
↓
Pandas Executor Agent：代码为主
↓
SQL Executor Agent：代码为主
↓
Verifier Agent：规则为主，LLM 辅助
↓
Correction Agent：LLM 生成修正方向，代码执行
↓
Insight Agent：LLM 为主
↓
Visualization Agent：规则 + LLM
↓
Benchmark Agent：代码为主，LLM 辅助错误归因
↓
Response Builder：生成最终结构化 JSON

注意：

1. 每个 Agent 必须只负责一个明确职责
2. 每个 Agent 必须通过结构化输入输出交互
3. 每个 Agent 必须能独立测试
4. 多 Agent 只是编排方式，不改变核心算法位置
5. Microsoft Agent Framework 只负责 workflow orchestration
6. 当前 backend 默认走 multi_agent，single_agent 只作为 fallback
7. 当前 DABstep 多 Agent runner 位于 multi_agent_workflows/dabstep_benchmark_runner.py

## 下一阶段：业务口径驱动的多 Agent 质量提升

下一阶段不是继续更换 Agent 框架，也不是按 Benchmark 题号补规则，更不是把每次看到的错误补成只适配当前数据和当前问法的局部坑，而是让多 Agent 真正参与业务语义判断、计划修正、结果校验和跨数据集泛化能力建设。

Rule NO.1：

1. 禁止针对单个 Benchmark 题目、题号、task_id、固定题面、标准答案、隐藏答案推测或 public proxy 答案池写任何特调逻辑。
2. 禁止伪泛化：如果一个补丁虽然没有直接引用题号或答案，但它依赖当前数据集的固定字段值、固定候选项、固定问法、固定排序结果、固定错误形态或当前 benchmark slice 才能工作，也视为特调。
3. public proxy answer pool 只能用于回归观察、能力缺口归因和趋势判断，不能进入 Planner、Executor、Verifier、Correction、prompt、测试 fixture 或任何核心分析链路。
4. 任何改动必须先被表述为能力族，例如字段枚举、比例计算、重复检测、设备欺诈排名、ACI 极值选择、fee what-if、影响商户分析；不能被表述为“修某一道题”或“修这次错误”。
5. 新能力必须至少有一个非 Benchmark 或合成通用用例验证其泛化边界；DABstep 只能作为后验回归观察。
6. 新能力必须说明为什么能迁移到其他数据集、其他列名、其他候选值或其他同类问法；如果不能说明，只能记录为临时局限或实验假设，不能记为能力提升。
7. 任何让当前题目变对但降低旧代表用例、上传文件场景或同类 benchmark slice 通过率的改动，默认视为泛化能力下降，必须回滚或重新设计。

阶段目标：

1. Planner Agent 不只选择 operation，还必须输出 metric、metric_definition、numerator、denominator、group_by、filters、options、objective 和 output_format。
2. Data Engineer Agent 负责把 manual / guidelines / column profile 中的业务定义落到结构化字段和公式，例如 fraud 必须区分 fraud count、fraud transaction rate、fraud volume rate 和 monthly fraud level。
3. Executor Agent 只执行通用 LogicForm，不允许根据 task_id、题号、标准答案、固定题面、固定字段值或当前错误样本写分支。
4. Verifier Agent 不只检查 Pandas / SQL 是否一致，还必须检查业务口径是否匹配问题和文档定义；如果 Pandas / SQL 一致但指标定义错误，也必须判为需要修正。
5. Correction Agent 必须能生成修正后的 LogicForm 并触发受控重跑，而不是只写自然语言建议。
6. Response Builder 只允许基于已验证的执行结果、候选表和修正记录输出最终答案。
7. Microsoft Agent Framework adapter 仍只负责承载和映射，不承载业务语义、Pandas、SQL、Verifier 或 Benchmark 逻辑。
8. 将 all 21-50 public proxy 暴露出的 `Not Applicable` 缺口归纳为通用能力族补齐：字段可取值枚举、比例/百分比、重复行检测、欺诈交易维度排名、ACI 最贵/最便宜选择、fee restriction 影响商户解析。
9. 每个能力族必须配套泛化验收：至少一个非 Benchmark 或合成数据用例、一个同类变体用例、一个已有代表回归用例；不能只用当前失败题目证明成功。

## 下一阶段 TODO

1. Planner 语义指标增强
   - 为 ranking / top / highest / lowest 类问题增加 metric selection。
   - 将 `top fraud` 默认解析为明确的 fraud-rate 类 metric，而不是直接落到 raw count。
   - 保留 `highest number of transactions` 这类问题的 raw count 语义，避免把所有 top 都改成 rate。

2. Data Engineer 业务定义落地
   - 从 manual / payments-readme / guidelines 中提取指标定义，并写入 LogicForm。
   - 对 fraud 相关问题明确 numerator 和 denominator，例如 fraudulent volume / total volume。
   - 对 multiple choice 问题校验候选值是否存在于数据列中，并把候选集作为执行约束传递。

3. 通用 Executor 能力补齐
   - 新增或扩展通用 `rank_by_metric` / `top_rate` / `fraud_rate_by_dimension` 能力。
   - ACI incentive / what-if fee 场景必须输出候选表，包含 baseline、candidate fee、delta、匹配 fee IDs 和选择理由。
   - 所有新增能力必须服务一类问题，不能绑定 DABstep dev 前 10 的 task_id 或题面。

4. Verifier 语义校验升级
   - 检查问题语义、manual 定义、LogicForm 指标定义和执行结果是否一致。
   - 对 fraud、rate、level、top、lowest、delta、associated cost 等高风险词触发口径检查。
   - 对 multiple choice 输出检查最终字母和值是否来自候选表中的最优项。
   - 对 fee what-if 输出检查 baseline、candidate 和 delta / associated cost 的口径是否与 guidelines 一致。

5. Correction 闭环重跑
   - Correction Agent 输出结构化修正动作，例如 `top_count -> rank_by_metric(metric=fraud_volume_rate)`。
   - Workflow 支持一次或多次受控重跑，并在 trace 中记录 correction_attempts。
   - 修正仍必须经过 ToolDispatcher / Executor / Verifier，LLM 不能直接改最终答案。

6. Trace 和 debug 证据增强
   - Trace 中记录 metric_definition、numerator、denominator、candidate_table_summary、selected_candidate 和 semantic_verification_notes。
   - 对费用模拟记录命中的 fee rule 摘要，避免只有最终数字。
   - Trace 不记录完整 Chain of Thought、raw reasoning tokens、API key 或敏感原始数据。

7. 能力族回归测试
   - 按能力族新增测试：fraud rate ranking、raw count ranking、multiple choice ranking、ACI incentive、fee what-if、semantic correction rerun。
   - 测试命名和断言必须围绕业务能力，不围绕 task_id。
   - 每个能力族至少包含一个非 Benchmark 或合成数据用例，用来证明同类数据集和同类问法可以复用。
   - DABstep dev 前 10 只作为回归结果观察；分数提升必须来自通用能力自然改善，不允许写单题特判或伪泛化分支。

8. 阶段验收标准
   - DABstep dev 前 10 的已知失败点必须通过通用能力修复自然改善，而不是按题号、当前题面、当前数据值或当前错误现象修复。
   - DABstep all 21-50 的 public proxy 失败项必须通过通用能力族自然改善，而不是按题号、task_id、sample public answer、固定候选项或固定数据分布修复。
   - Verifier 能识别 Pandas / SQL 一致但业务口径错误的情况。
   - multi_agent trace 能说明一次计划、执行、语义校验、修正和重跑链路。
   - data_agent_core 仍不 import backend、ms_agent_framework_adapter、multi_agent_workflows 或 agent_framework。
   - 新能力在合成/非 Benchmark 用例、同类变体和旧代表用例上都不退化；如果只提升当前错误样本，不通过阶段验收。

9. 21-50 暴露出的下一阶段能力族
   - 字段枚举能力：回答字段可能取值，例如 ACI codes、card scheme、device type 等，必须从字段画像、manual 或数据列去重得到。
   - 比例和百分比能力：回答占比、百分比、credit/debit 分布、fraud rate 等，必须明确 numerator、denominator、单位和 rounding。
   - 数据质量检查能力：回答重复行、空值、唯一值、异常值等，不应落入 `Not Applicable`。
   - 欺诈维度排名能力：回答 fraudulent transactions 中某个维度的 most common / top / rate ranking，必须明确是 count、transaction rate 还是 volume rate。
   - ACI 极值能力：回答给定 card scheme、transaction value、credit/debit 条件下最贵或最便宜 ACI，必须支持 tie-break 规则和 list 输出。
   - Fee restriction 影响分析能力：回答 fee rule 限制条件变化会影响哪些 merchant，必须基于通用 rule matching 和 period simulation，不允许写固定 merchant 列表。
   - Public proxy 回归报告能力：报告必须清楚标注 proxy score 不是 official hidden ground truth，并输出按能力族聚合的缺口，而不是只列题号。

## 最小 API 目标

当前后端至少需要支持：

1. POST /api/data-agent/upload

用于接收 CSV / Excel 文件，返回 dataset_id 和字段画像。

2. POST /api/data-agent/analyze

用于接收 dataset_id 和用户问题，返回分析结果、校验信息、解释建议和图表配置。

3. GET /api/data-agent/datasets/{dataset_id}/profile

用于返回指定数据集的文件信息、字段画像和状态。

## 重要红线

1. Rule NO.1：不允许针对 Benchmark 题号、task_id、固定题面、标准答案、隐藏答案推测或 public proxy 答案池做单题特调；也不允许写只适配当前数据集、当前字段值、当前问法或当前错误样本的伪泛化补丁。
2. 不允许直接在 main 分支开发
3. 不允许修改旧系统主流程，除非任务明确要求
4. 不允许把核心算法写进 backend/router
5. 不允许把 Benchmark 题目写成硬编码规则，也不允许把当前失败样本包装成看似通用的特殊规则
6. 不允许绕过 Verifier 直接输出最终结论
7. 不允许一次任务混合多个无关目标
8. 每次修改前必须读取 MAIN_GOAL.md、CHANGELOG_AI.md、BRANCH_RULES.md
9. 每次修改后必须更新 CHANGELOG_AI.md
10. 不允许核心算法依赖 Microsoft Agent Framework
11. 不允许在适配层中实现核心业务逻辑
12. 不允许每个模块随意返回不同结构的 dict
13. 不允许没有 run_id 的 analyze 链路
14. 不允许没有错误类型的失败结果
15. 不允许没有 trace 的分析链路设计
16. 不允许工程文档要求输出完整 Chain of Thought
17. CHANGELOG_AI.md 新增记录必须写日期时间，格式为 YYYY-MM-DD HH:MM TZ，精确到分钟
18. 不允许为了补齐格式而给历史 CHANGELOG 记录编造分钟级时间
