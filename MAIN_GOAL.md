# MAIN GOAL

## 项目主目标

本项目的核心目标是从头构建一个可评测、可复现、可扩展的数据分析 Agent 内核。

系统需要支持用户上传 CSV / Excel 文件，Agent 自动解析文件结构和字段含义，根据用户自然语言问题生成分析计划，并通过 Pandas / NumPy 和 SQL / DuckDB 两条执行路径完成数据分析。

执行结果需要经过自查、自纠和一致性校验。确认结果可信后，再生成解释、建议和可视化图表配置，最终通过后端 API 返回给前端展示。

## 当前阶段目标

当前阶段基线已完成并继续增强：

1. 已搭建 data_agent_core 核心算法目录
2. 已搭建 data_agent_core/contracts 数据契约目录
3. 已搭建 data_agent_core/errors 错误体系目录
4. 已搭建 data_agent_core/tracing 运行追踪目录
5. 已搭建最小 backend API 目录
6. 已搭建 agent_runtime 内部 Agent 抽象目录
7. 已搭建 ms_agent_framework_adapter 微软框架适配层目录
8. 已搭建 multi_agent_workflows Phase 6 最小多 Agent 工作流目录
9. 已搭建 docs 工程文档目录
10. 已搭建 tests/architecture 架构边界测试目录
11. 已定义文件解析、字段画像、问题理解、分析计划、执行器、校验器、解释器、图表规划器的模块边界
12. 已具备 CSV / Excel 最小解析入口；编码识别、复杂表头和多 sheet 策略仍是增强项
13. 已具备 Pandas / NumPy 最小执行路径
14. 已具备 SQL fallback 最小执行路径；DuckDB runtime 仍未生产化
15. 已具备 Pandas 与 SQL 结果对比和 Result Normalizer 基线
16. 已具备基础 Verifier、Correction Planner 和一次受控重跑基线
17. 已具备 Benchmark Runner、分段运行、trace、metrics 和错误归因基线
18. 已提供最小后端接口壳，供前端上传文件、提交问题、获取结构化结果
19. 已从单 Agent 平滑迁移到 Phase 6 最小多 Agent 默认链路，single_agent 保留为 fallback
20. 已具备 Phase 5 受控 Tool Calling 基线：字段画像、计划构建、Pandas / SQL 执行、结果校验、图表规划和解释生成已包装为白名单工具；模型仍不能直接执行任意代码、SQL、shell、网络请求或外部文件访问
21. 当前继续增强真实 provider-native tool loop、DuckDB runtime、复杂并行/多轮自纠、ACI associated cost 通用口径和更大范围中英文真实数据回归

## 当前实现状态

2026-05-21 更新：

1. 已建立 Phase 0 项目规则和目录骨架。
2. 已新增可运行的核心算法 MVP，用于本地核心算法测试。
3. 已支持 DABstep 风格的业务表和规则知识库输入：payments.csv 作为业务数据库表，manual.md / fees.json / merchant_data.json 作为文档和规则知识库。
4. 已支持 DABstep dev 前 10 题本地评测，当前验证结果为 9/10，准确率 90%。
5. all.jsonl 已可生成 1-450 题预测文件；本地 all.jsonl 的 answer 字段为空，因此只能验证执行覆盖，不能本地计算 hidden official accuracy。
6. 该实现不使用 task_id、标准答案、固定题面、固定数据值或只适配当前失败样本的补丁进入分析链路。
7. 已新增 LLM 单 Agent 链路，Intent Parser、Column Mapping、Analysis Planner、Verifier / Critic、Correction Planner、Insight Generator 和 Chart Planner 均预留 LLM 参与；确定性代码负责文件/规则读取、执行、结果标准化、规则校验和评分。
8. LLM key 只能通过环境变量提供，禁止写入仓库、文档、trace 或 CHANGELOG。
9. 已进入 Phase 1 / Phase 2 / Phase 3 最小可测状态：支持上传 CSV / Excel 文件解析入口、DatasetProfile、UploadedDatasetAgent、最小 backend service upload/profile/analyze、Benchmark metrics 和 error_analysis 聚合。
10. 当前最小后端 API 仍是调用壳，核心 Pandas / SQL / Verifier / Insight / Chart 逻辑仍在 data_agent_core。
11. public all.jsonl 的 answer 字段为空，不能本地计算完整 450 题官方准确率；dev 前 10 题仍用于本地可复现 smoke benchmark。
12. Phase 5 受控 Tool Calling 已完成 provider-neutral 基线：ToolRegistry / ToolDispatcher / 内部工具 callable / Microsoft tool mapping 已可测；当前仍不把真实 OpenAI / DeepSeek 原生 tool loop 作为生产默认链路。
13. 已补充 Phase 5 受控 Tool Calling 的 provider-neutral 契约和本地执行层：ToolDefinition、ToolCall、ToolResult、ToolTraceEvent、ToolDispatcher、Data Agent tool catalog、DataAgentToolRuntime、Microsoft adapter tool mapping 和 provider-native adapter mock loop；真实执行仍必须经过 ToolDispatcher。
14. 已开始实现 Microsoft Agent Framework adapter 和真实内部工具 callable：工具 callable 位于 agent_runtime，调用既有 data_agent_core 核心模块；Microsoft adapter 只做可选 function tool、agent factory 和 sequential workflow builder，不让 data_agent_core 依赖 Microsoft Agent Framework。
15. 已切换到 Phase 6 最小可运行多 Agent workflow：backend analyze 默认走 multi_agent；DABstep 多 Agent runner 可运行 dev 前 10 题并保持 9/10；data_agent_core 仍不依赖 multi_agent_workflows。
16. 已开始把多 Agent 从顺序角色编排升级为业务口径驱动的计划、校验和自纠闭环：LogicForm 支持 metric、metric_definition、numerator、denominator、group_by、objective 和 options；Verifier 能识别 top fraud 使用 raw count 的语义错误，并要求修正为 fraud_volume_rate。
17. 当前 9/10 的主要瓶颈不是多 Agent 框架或 Microsoft adapter，而是 ACI incentive 类问题的 associated cost 费用口径仍未完全对齐；该问题必须按通用 fee what-if / ACI candidate table 能力继续修复，禁止只针对当前 DABstep 样本、当前字段值或当前问法补坑。
18. DABstep public all 1-450 已可运行 mock 多 Agent 执行覆盖；本地 public all.jsonl 的 answer 字段为空，因此只能验证执行率和 trace，不能本地计算官方准确率。
19. Provider 原生 Tool Calling Adapter 已完成 OpenAI / DeepSeek 兼容 schema、tool call 解析和 mock/fake client loop；下一步是真实 OpenAI / DeepSeek 网络 tool loop smoke，不改变本地 ToolDispatcher 作为唯一受控执行入口。
20. 项目必须以中文数据分析体验为第一优先级，同时保留英文问题、英文字段和英文 Benchmark 的兼容能力；任何新能力、prompt、字段映射、测试和文档都不能只按英文设计。
21. 已开始实现 `Not Applicable` 能力缺口闭环：FinalResponse / debug / trace / benchmark report 可区分 `true_unsupported` 和 `capability_gap`；新增基础通用能力族 `row_count`、`distinct_count`、`repeat_entity_percentage`、`outlier_count`、`top_k_share`、`filtered_metric_ranking`，并用中英文合成用例验证。
22. 已补齐上一阶段遗留的第二批通用能力：`null_check`、英文/中文季度表达、fraud likelihood 多维排名、fee what-if candidate table，以及 OpenAI / DeepSeek 兼容的 provider-native tool calling adapter 骨架；真实执行仍经 ToolDispatcher，不允许 provider adapter 实现核心算法。
23. DABstep all 100-130 真实 LLM 执行覆盖记录：`outputs/dabstep_all_100_130_real_llm_20260521_175125/all_100_to_130_report.json` 中 total=31、success_count=29、capability_gap=2；public all answer 为空，official accuracy 仍不能本地计算。public proxy 观察文件 `outputs/dabstep_all_100_130_real_llm_20260521_175125/all_100_to_130_public_proxy_observation.json` 仅 9 题可进入 accepted-answer pool，其中 3 题匹配，proxy accuracy=33.33%，该结果只能用于能力缺口归因，不能进入核心分析链路。
24. Microsoft 脱敏数据 21-40 真实 LLM 基线记录：`outputs/microsoft_anonymized_21_40_real_llm_20260521_175247/report.json` 中 total=20、correct=5、accuracy=0.25，主要缺口是中文零售 `retail_target_lookup / aggregation / ranking / row_count` 及相关服务客户、目标达成率、拜访、陈列和字段枚举能力。下一步已明确为按中文零售能力族修复，不允许按题号、标准答案或固定输出优化。
25. 已补齐 Microsoft 21-40 暴露的第一批中文零售能力族：服务客户数、服务客户合约店占比、分销目标人数、分销目标达成率、今日分销排名、历史 SKU / 品类排名、拜访成功率、陈列/拜访记录数、冰柜客户数和历史字段枚举；配套合成中文测试，不使用 Microsoft 标准答案作为测试 fixture。
26. 已补齐 DABstep 100-130 中两个 hour-of-day capability_gap：新增通用 `top_count` hour-of-day 解析和 `top_outlier_group` 能力，支持 “哪个小时交易最多” 和 “哪个小时离群交易最多（Z-Score > 3）”。mock 多 Agent 回归 `outputs/dabstep_all_100_130_mock_after_hour_group/all_100_to_130_report.json` 显示 total=31、success_count=31、unexpected_not_applicable=0、accuracy=null；accuracy 仍为 null 是因为 public all answer 为空。
27. Microsoft 脱敏数据 21-40 已通过中文零售能力族自然覆盖：mock 回归 `outputs/microsoft_anonymized_21_40_mock_after_retail_20260521_204756/report.json` 为 20/20，真实 LLM 回归 `outputs/microsoft_anonymized_21_40_real_llm_after_retail_20260521_204819/report.json` 为 20/20；标准答案只用于离线 scorer，未传入 Agent workflow。
28. 已补安全治理缺口：ToolDispatcher 对工具 timeout_seconds 执行 POSIX timeout 边界；架构测试新增 tracked-file secret scan，并扩大 Benchmark 硬编码扫描到 agent_runtime、backend、ms_agent_framework_adapter 和 multi_agent_workflows 的核心源码范围。
29. 已补齐 DABstep all 131-180 暴露的下一批执行能力缺口：missing/null 过滤 Top count 的 SQL fallback 与 Pandas 一致，outlier / high-value 问题能把年份识别为过滤条件而不是指标列；mock 多 Agent 回归 `outputs/dabstep_all_131_180_mock_after_gap_fix_20260522/all_131_to_180_report.json` 为 total=50、success_count=50、unexpected_not_applicable=0、accuracy=null，accuracy 仍因 public all answer 为空不可本地计算。
30. 已新增 Microsoft 脱敏数据离线 runner `multi_agent_workflows/microsoft_anonymized_benchmark_runner.py`，标准答案只在 response 生成后用于 scorer，不进入 Agent workflow；Microsoft 41-60 mock 回归 `outputs/microsoft_anonymized_41_60_mock_after_fix_20260522/report.json` 为 20/20。
31. 已新增 VDS 中文 BI 周期比较能力族 `vds_period_rank_change`、`vds_period_delta_top`、`vds_period_growth_count_share`、`vds_period_threshold_count`、`vds_period_rate_top`、`vds_current_threshold_top`、`vds_peer_anomaly`，覆盖销售、教育、医疗、物流、SaaS 五域的周环比排名、TopN、增长数量占比、阈值筛选、同圈层异常和城市维度环比增长率；桌面 VDS `问题汇总.xlsx` 五域全部 95 题 smoke 为 95/95 成功，输出 `outputs/vds_desktop_question_summary_full_mock_20260522.json`。
32. 已补齐 DABstep public all 1-450 的剩余执行失败：`metric_per_distinct_entity` 能区分“平均交易金额 / unique entity”和“平均交易次数 / unique entity”，Pandas 与 SQL 双路径一致；mock 多 Agent 全量回归 `outputs/dabstep_all_1_450_mock_after_metric_per_entity_fix_20260522/all_1_to_450_report.json` 为 total=450、success_count=450、unexpected_not_applicable=0、failure_count=0、accuracy=null。
33. Microsoft 脱敏数据 1-300 已通过离线 scorer 全量回归：`outputs/microsoft_anonymized_1_300_mock_after_true_unsupported_fix_20260522/report.json` 为 total=300、correct=300、accuracy=1.0、success_count=300；标准答案只在 response 生成后用于 scorer，未进入 Agent workflow。
34. 桌面 VDS `问题汇总.xlsx` 五域全部 95 题已通过 mock 多 Agent 执行覆盖：`outputs/vds_desktop_question_summary_full_mock_20260522.json` 为 total=95、success_count=95、failure_count=0；该结果验证问题理解、能力路由和执行成功，不使用标准答案优化。

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
15. 所有 analyze 请求必须生成 run_id
16. 所有 API 响应必须包含 response_version
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
29. Provider 原生工具循环只能把模型生成的 tool call 转换为内部 ToolCall；任何 OpenAI / DeepSeek tool call 都必须经过 ToolDispatcher 的白名单、角色、schema、超时和摘要校验后才能执行
30. 中文优先是核心产品规则：中文问题理解、中文字段名、中文业务术语、中文日期表达、中文输出格式和中文表结构必须优先支持；英文能力不能放松，但不能以牺牲中文能力为代价。
31. 新增或修改任何 Intent Parser、Column Mapping、Planner、Executor、Verifier、Correction、Insight、Chart、Benchmark 或 Tool 能力时，必须同时评估中文场景；如果只覆盖英文，必须明确记录为阶段性限制，不能标记为通用能力完成。
32. 多语言能力必须通过稳定契约表达，不能靠在 prompt 或 executor 中散落的临时中英文关键词补丁冒充泛化。

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
17. 在本轮把 provider-native adapter 作为生产默认链路、接入真实 OpenAI / DeepSeek 网络调用、启用 DeepSeek thinking mode 工具回填或 OpenAI Responses API 专有 reasoning 循环

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
2. ToolDispatcher 负责工具名、角色、JSON 参数、timeout_seconds 执行边界和 trace-safe 摘要。
3. Microsoft Agent Framework adapter 可以把内部工具包装为 function tool，但仅作为可选适配层。
4. Provider-native adapter 已具备 OpenAI / DeepSeek 兼容 schema、tool call 解析和 mock/fake client loop；真实 OpenAI / DeepSeek 网络 tool loop 尚未作为生产默认链路启用，模型仍不允许获得 raw Python、raw SQL、shell、网络或任意文件访问。

## Phase 7：Provider 原生 Tool Calling Adapter

Phase 7 的目标不是替换本地工具层，而是把 OpenAI / DeepSeek 的原生 tool calling 能力接到现有 provider-neutral 工具契约上。当前已完成 schema / tool call 解析 / mock loop 基线；下一步是真实 provider 网络 smoke 和更完整失败恢复，但不能改变真实执行、权限、参数校验、超时、trace 摘要和错误归一化仍由本地 ToolDispatcher 负责的边界。

阶段顺序：

1. 已实现 OpenAI / DeepSeek 兼容工具循环 adapter 基线，把 provider tool schema / tool call / tool result 映射到内部 ToolDefinition、ToolCall 和 ToolResult。
2. OpenAI adapter 必须复用现有 ToolRegistry / ToolDispatcher / ToolTraceEvent，不允许在 provider adapter 中实现 DatasetProfile、Pandas、SQL、Verifier、Chart 或 Insight 逻辑。
3. 已跑通 mock/fake provider 单元测试；仍需补真实 OpenAI / DeepSeek key 下的 uploaded dataset smoke，且 key 只能来自 ignored env 文件或运行环境。
4. DeepSeek provider 特化只处理 DeepSeek 与 OpenAI-compatible chat completions / tool calls 的协议差异；不得 fork 内部工具契约。
5. DeepSeek thinking mode 或其他 reasoning 字段只能由 provider adapter 内部维护，用于必要的续传或工具回填，不进入稳定 trace、debug 或 API 响应。
6. Provider 原生并行 tool calls 如后续启用，必须先证明不会破坏工具顺序依赖、WorkflowState 一致性和 trace 可复现性。

Provider-native 调用链必须保持为：

OpenAI / DeepSeek native tool loop
↓
provider adapter
↓
内部 ToolDefinition / ToolCall
↓
ToolDispatcher 白名单、角色、schema、超时和 trace-safe 校验
↓
受控本地工具 callable
↓
data_agent_core 确定性执行、Verifier 和 Response Builder

验收标准：

1. OpenAI 原生 tool loop 可在不改变 data_agent_core 核心算法的前提下完成 profile_schema、build_analysis_plan、execute_pandas_plan、execute_sql_plan、verify_results、build_chart_spec 和 generate_insight 的闭环。
2. Tool call 失败必须进入 ToolResult.errors / warnings，并能被 Verifier 或 Correction Planner 消化，不能由模型自然语言掩盖。
3. Trace 只记录工具名、step_id、requested_by、参数摘要、结果摘要、错误和耗时，不记录完整 Chain of Thought、raw reasoning tokens、API key 或敏感原始数据。
4. OpenAI 和 DeepSeek 的差异必须限制在 data_agent_core/llm 或独立 provider adapter 内；内部 ToolDefinition、ToolCall、ToolResult、ToolTraceEvent 和 ToolDispatcher 不因 provider 改变。
5. 本地固定流程仍可作为 fallback；启用 provider-native tool loop 不能降低现有 multi_agent smoke benchmark、uploaded-file API 和 mock provider 测试的可复现性。

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

## Phase 6 质量提升：业务口径驱动的多 Agent 泛化能力

该阶段不是继续更换 Agent 框架，也不是按 Benchmark 题号补规则，更不是把每次看到的错误补成只适配当前数据和当前问法的局部坑，而是让多 Agent 真正参与业务语义判断、计划修正、结果校验和跨数据集泛化能力建设。

Rule NO.1：

1. 禁止针对单个 Benchmark 题目、题号、task_id、固定题面、标准答案、隐藏答案推测或 public proxy 答案池写任何特调逻辑。
2. 禁止伪泛化：如果一个补丁虽然没有直接引用题号或答案，但它依赖当前数据集的固定字段值、固定候选项、固定问法、固定排序结果、固定错误形态或当前 benchmark slice 才能工作，也视为特调。
3. public proxy answer pool 只能用于回归观察、能力缺口归因和趋势判断，不能进入 Planner、Executor、Verifier、Correction、prompt、测试 fixture 或任何核心分析链路。
4. 任何改动必须先被表述为能力族，例如字段枚举、比例计算、重复检测、设备欺诈排名、ACI 极值选择、fee what-if、影响商户分析；不能被表述为“修某一道题”或“修这次错误”。
5. 新能力必须至少有一个非 Benchmark 或合成通用用例验证其泛化边界；DABstep 只能作为后验回归观察。
6. 新能力必须说明为什么能迁移到其他数据集、其他列名、其他候选值或其他同类问法；如果不能说明，只能记录为临时局限或实验假设，不能记为能力提升。
7. 任何让当前题目变对但降低旧代表用例、上传文件场景或同类 benchmark slice 通过率的改动，默认视为泛化能力下降，必须回滚或重新设计。
8. 中文能力优先级高于英文能力：中文问题、中文字段名、中文业务口径和中文输出格式不能被英文 Benchmark 或英文 prompt 设计挤出主路径；英文能力必须保留并持续回归，但不能成为唯一验收口径。

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

## Phase 6 质量提升状态

已完成的第一批基线：

1. Planner / Data Engineer 已能把 LLM 草案和规则 guardrail 合并为结构化 LogicForm，并保留 metric、metric_definition、numerator、denominator、group_by、objective 和 options。
2. Verifier 已能识别部分业务口径错误，例如 top fraud 使用 raw count 而应切换为 fraud volume rate 的情况。
3. Correction Agent 已能输出结构化 corrected LogicForm，并触发一次受控 Pandas / SQL 重跑；修正仍经过 ToolDispatcher、Executor 和 Verifier。
4. Trace / debug 已记录 metric_definition、candidate_table_summary、selected_candidate、semantic_verification_notes、correction_attempts 和 tool_call_summary，不记录完整 Chain of Thought、raw reasoning tokens、API key 或敏感原始数据。
5. 已补第一批 21-50 / Not Applicable 暴露出的通用能力族：字段枚举、比例/百分比、重复检测、空值检查、异常值、Top-K 占比、过滤排名、欺诈维度比较、ACI / MCC fee extreme、fee restriction 影响分析和 public proxy 后验报告标注。
6. 已补 DABstep 100-130 暴露出的 hour-of-day top group / outlier group 能力。
7. 已补 Microsoft 21-40 暴露出的第一批中文零售能力族，并用合成中文用例验证。
8. 已补架构治理测试：tracked-file secret scan、扩大后的 Benchmark 硬编码扫描、data_agent_core import 边界测试。

仍遗留且不能宣称完成的项目：

1. ACI associated cost / best_fraud_aci_choice 的费用口径仍需继续做通用 fee what-if candidate table 和 associated cost 语义增强，不能按 DABstep dev 单题补丁处理。
2. DuckDB runtime 尚未生产化；当前 SQL 路径仍以 sqlite fallback / SQL-compatible operation 为主。
3. Provider-native adapter 已有 mock/fake client loop，但真实 OpenAI / DeepSeek 网络 tool loop 尚未作为生产默认链路启用。
4. 多 Agent 当前是内部顺序 workflow，复杂并行 executor、真实 Microsoft cloud workflow 和多轮代码级自纠仍属后续增强。
5. DABstep public all answer 为空，all 100-130 / 131+ 的 official 本地准确率仍不可计算；public proxy 只能后验观察，不能进入核心链路。
6. 已完成 DABstep public all 1-450 mock 执行覆盖、Microsoft 脱敏数据 1-300 mock 离线 scorer 和桌面 VDS 95 题 smoke；仍需继续做真实 LLM 大规模回归、更多中文真实业务表、更多字段别名、多表场景和更复杂中文 BI 能力验证。
7. 真实 LLM 多 Agent 评测耗时仍偏长，后续可优化 provider 调用次数和 stage 缓存，但不能牺牲 trace、Verifier 和受控工具边界。

## `Not Applicable` 能力缺口闭环状态

该闭环目标不是简单减少 `Not Applicable` 字面输出，也不是换更强 LLM 后期待自动解决，而是把 `Not Applicable` 拆成可审计的真实不适用和可补齐的通用能力缺口。LLM planner 可以理解问题，但最终执行仍必须落到结构化 LogicForm、受控 Executor、Verifier 和 Response Builder，不能直接根据自然语言生成最终答案。

当前已完成第一批闭环：`true_unsupported` / `capability_gap` 归因、`CAPABILITY_GAP` 错误类型、trace/debug/benchmark report 摘要、row_count、distinct_count、repeat_entity_percentage、outlier_count、top_k_share、filtered_metric_ranking、null_check、季度表达、fraud likelihood 多维比较和 fee what-if candidate table。仍需继续扩大到更多中文真实数据、更多字段别名、多表场景和更完整 DuckDB runtime。

1. `Not Applicable` 归因改造
   - 将 `Not Applicable` 至少区分为 `true_unsupported` 和 `capability_gap`。
   - `true_unsupported` 只用于上传规则、manual、schema 或业务知识确实没有定义的问题，例如未定义 fine / danger 阈值时不能臆造答案。
   - `capability_gap` 用于问题本身可以由数据或规则回答，但当前 Planner / Parser / Executor 还没有通用能力覆盖的情况。
   - Trace、debug 和 benchmark report 必须记录归因原因、命中的 parser 分支、LLM proposed operation、最终 selected operation，以及是否被 guardrail 降级。

2. Benchmark 和报告语义修正
   - all split 没有 expected answer 时，不能因为 `response.success=true` 就把 `Not Applicable` 当成无问题结果。
   - 报告必须单独统计 unexpected `Not Applicable`、true unsupported、capability gap，并按能力族聚合。
   - Public proxy / hidden scorer 只能用于观察趋势；不能把题号、固定题面、固定答案或当前输出写进核心链路。

3. Planner 与 guardrail 协同升级
   - Guardrail parser 继续作为安全边界，但不能把所有未命中的可回答问题直接吞成普通 `not_applicable`。
   - 当 LLM planner 给出受支持 operation、字段能由 schema/profile 映射、参数可验证时，可以进入受控候选 LogicForm 验证流程，而不是无条件回退到 guardrail 兜底。
   - 如果 LLM proposed operation 不在受支持集合或缺少必要字段，必须输出结构化 capability gap，而不是伪装成真实不适用。

4. 基础表分析能力补齐
   - 已新增或扩展通用 `row_count`：回答总行数、总交易数、record count。
   - 已新增或扩展通用 `distinct_count`：回答唯一 merchant、唯一 shopper、唯一字段值数量。
   - 已新增可配置 `repeat_entity_percentage`：按 email、shopper id、customer id 等字段计算 repeat customer / repeat shopper 占比。
   - 这些能力必须适用于上传表和 DABstep payments，不依赖固定列值；列名只能通过 schema/profile/alias 映射解析。

5. 通用统计和数据质量能力补齐
   - 已新增 `outlier_count`：支持 Z-Score、IQR 等明确方法，必须输出 metric、threshold、target column 和 count。
   - 数据质量问题必须优先落到 `duplicate_check`、`null_check`、`distinct_count`、`outlier_count` 等通用能力，不应直接落入 `Not Applicable`。

6. Top-K 占比和过滤排名能力补齐
   - 已新增 `top_k_share`：支持“top N group by metric volume 占整体百分比”，例如 top merchants by amount volume share。
   - 已新增或扩展 `filtered_metric_ranking`：支持在 merchant、card scheme、country、quarter、last quarter 等过滤条件下按 average / sum / count 排名。
   - 时间解析必须支持 quarter、last quarter of year、month range，并以结构化 filters 写入 LogicForm。

7. 布尔维度比例和 fraud likelihood 比较
   - 已扩展 `fraud_rate_comparison`，不只支持 Ecommerce vs POS，也支持 credit vs debit、device type、country、merchant 等布尔或枚举维度。
   - 必须明确 fraud likelihood 的口径是 fraudulent transaction rate 还是 fraudulent volume rate，并由 question / manual / guidelines 决定。
   - Verifier 必须检查 numerator、denominator、group_by 和输出 yes/no 是否与问题一致。

8. Fee 极值维度扩展
   - 已将 ACI 极值能力抽象为更通用的 `fee_extreme_by_dimension`，支持 ACI、MCC、card scheme 等维度。
   - 支持 cheapest / most expensive、average scenario、transaction value、credit/debit、card scheme 过滤和 tie list 输出。
   - 输出必须包含候选表或候选摘要，记录每个候选的 matched fee IDs、fee components、total fee 和 tie-break 规则。

9. 泛化验收标准
   - 每个新增能力族至少包含一个合成或非 Benchmark 用例、一个同类问法变体、一个已有代表回归用例。
   - DABstep all 51-100 暴露出的 `Not Applicable` 只能作为后验回归观察，不能作为单题修复入口。
   - 如果一个改动只让当前失败样本变对，但无法迁移到其他表、其他列名、其他候选值或同类自然语言问法，不能计入能力提升。
   - 验收报告必须给出 capability family、supported examples、unsupported examples、remaining gaps 和 trace 证据。

## DABstep 100-130 与中文零售 21-40 能力闭环状态

该闭环目标是把真实回归暴露的问题归纳为可复用能力族，继续提高泛化能力，而不是按题号、标准答案、public proxy 或当前脱敏数据固定值优化。当前 DABstep 100-130 的 hour-of-day capability_gap 已按通用能力族修复；Microsoft 21-40 的第一批中文零售能力族已通过 mock 和真实 LLM 回归，并已扩展到 Microsoft 脱敏数据 1-300 mock 离线 scorer 全量通过。仍不能把这些回归等同于 hidden benchmark 官方满分或全部未来真实业务表能力完成。

1. DABstep 100-130
   - official 本地准确率仍不可计算，因为 public all answer 为空。
   - public proxy 只能作为后验观察，不能进入 Planner、Executor、Verifier、Correction、prompt、测试 fixture 或核心逻辑。
   - 已补齐本轮暴露的 hour-of-day top group / outlier group；后续 131+ 仍必须归为 capability_gap 归因、数据质量、过滤聚合、费用 what-if 和字段语义等能力族，而不是题号列表。

2. 中文零售 21-40
   - 已补齐第一批中文真实数据能力族：`retail_target_lookup`、`aggregation`、`ranking`、`row_count`、服务客户、目标达成率、拜访成功率、陈列记录、订单状态枚举、今日分销和路线客户关联。
   - 所有实现必须基于 schema、字段语义、LogicForm 和受控 Executor，不能把 Microsoft 标准答案、task_id、固定姓名、固定品类或固定输出写入核心链路。
   - 新能力必须配套合成或非 Benchmark 中文用例，并保留 DABstep 英文回归，确保中文优先和英文兼容同时成立。
   - 已通过 Microsoft 脱敏数据 1-300 mock 离线 scorer 回归；后续更多中文真实表、真实 LLM 大规模回归、更多字段别名、多表 join 或跨数据源仍必须走 schema/业务术语泛化。

3. 验收标准
   - Microsoft 21-40 的改进必须来自通用中文零售能力自然覆盖。
   - DABstep 100-130 的报告必须继续区分 official unknown、public proxy observation 和真实执行覆盖。
   - secret scan 必须确认 LLM key 未进入仓库文件。
   - hardcoding scan 必须确认没有 task_id / expected_answer / proxy answer / accepted answer 进入核心源码或测试 fixture。
   - data_agent_core 仍不得 import backend、ms_agent_framework_adapter、multi_agent_workflows 或 agent_framework。

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
19. 不允许把中文支持当作可选增强；中文问题理解、字段映射、业务术语、日期/金额/百分比格式和最终回答必须作为主路径能力设计。
20. 不允许只用英文样例、英文字段或英文 Benchmark 声称能力完成；英文必须持续支持，但中文必须优先验收。
21. 不允许为中文能力写只适配当前脱敏数据、当前字段值或当前问法的伪泛化补丁；中文能力同样必须抽象为可复用能力族并有合成/非 Benchmark 验证。
