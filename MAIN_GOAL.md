# MAIN GOAL

## 项目主目标

本项目的核心目标是从头构建一个可评测、可复现、可扩展的数据分析 Agent 内核。

系统需要支持用户上传 CSV / Excel 文件，Agent 自动解析文件结构和字段含义，根据用户自然语言问题生成分析计划，并通过 Pandas / NumPy 和 SQL / DuckDB 两条执行路径完成数据分析。

执行结果需要经过自查、自纠和一致性校验。确认结果可信后，再生成解释、建议和可视化图表配置，最终通过后端 API 返回给前端展示。

## 当前阶段目标

当前 Phase 6 基线已完成，Phase 7 系列完成多 Agent、泛化验证、输出契约和 submission 风险治理基线；Phase 8 / Phase 9 已作为正式新阶段推进。Phase 8 已完成核心算法回看与多文件/多表泛化闭环，Phase 9 已在 Phase 8 通过后交付后端契约驱动的前端 workbench，Phase 10 已完成结果可视化、洞察建议、数据质量扫描和安全过程可视化首版闭环，并继续收敛 Workbench GPT-like 用户体验。Phase 11 已规划为会话隔离和历史续聊持久化阶段，当前状态为 Planned / Not implemented yet。

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
21. Phase 1 Backend API Shell 当前补充外部系统一次性调用入口，允许调用方通过 API 传入 JSON 表格和自然语言问题，再复用现有默认多 Agent 链路完成数据处理。
22. 当前进入 Phase 7 后续编号阶段：Phase 7.5 - 7.10 继续增强真实 provider-native tool loop、DuckDB runtime、复杂并行/多轮自纠、ACI associated cost 通用口径和更大范围中英文真实数据回归；这些阶段发生在 Phase 7.1 / 7.2 / 7.2G / 7.3 之后，不新增 Phase 7.4。
23. 当前新增 Phase 7.1 作为下一阶段子目标：DABstep Submission Quality Gate and Easy Capability Closure。
24. 当前新增 Phase 7.2 作为 Phase 7 下的后续子目标：Agent Generalization and Executor Semantic Parity；该阶段以 Agent 泛化能力为主目标，Pandas / SQL / DuckDB 语义统一只作为执行层可信度和回归判断支撑。
25. 当前新增 Phase 7.3 作为 Phase 7.2 之后的下一阶段子目标：Evaluation-Driven Robustness and Output Contract Hardening；该阶段聚焦最终 Output Contract、validation-driven retry、submission provenance、真实 provider 回归和 DA-agent 可借鉴工程模式。
26. Phase 8 已作为正式新阶段完成：Core Algorithm Review, Multi-file / Multi-table Generalization Closure。已补齐多文件 dataset 装配、问题到表路由、多表 join plan、Pandas join materialize、Verifier 校验和 trace 闭环；模型能力和泛化能力回归门禁未退步。
27. Phase 9 已作为 Phase 8 之后的正式前端阶段完成首版：Frontend Productization After Core Algorithm Freeze。已提供静态 workbench，多文件上传、profile 预览、分析提交、用户可读分析过程和历史回看均依赖后端 API 契约；前端不实现指标公式、join 或数据计算。
28. Phase 10 已作为 Phase 9 之后的正式结果体验阶段完成首版：Visualization, Insight, Data Quality and Safe Process View。后端稳定生成 `chart`、`insight`、`quality_report`、`reasoning_trace_view`；前端只把图表、洞察和安全过程摘要转成用户可读体验，不展示后端质量报告、warnings/errors、verification 细节、join trace，不实现核心计算、异常规则、清洗动作或完整 Chain of Thought。
29. Phase 11 已作为 Phase 10 之后的正式规划阶段：Conversation Isolation and Session Persistence。当前状态为 Planned / Not implemented yet；目标是每个 `conversation_id` 独立保存上下文，多窗口默认独立会话，可从历史 Chat 回到旧会话继续分析，并预留 `owner_id`、`tenant_id`、`owner_context` 以支持未来用户隔离。

## 统一 Phase 状态表

1. Phase 0：项目规则与目录骨架，已完成。
2. Phase 1：核心算法 + 最小 API，已完成基线；Backend API Shell 已补充外部 `POST /api/data-agent/run` 一次性调用入口，继续增强文件解析、编码识别、复杂表头和多 sheet 策略。
3. Phase 2：LLM 单 Agent，已完成基线，继续保留 `single_agent` 作为 fallback。
4. Phase 3：Benchmark Runner，已完成基线，继续增强 scorer 对齐、提交治理和错误归因报告。
5. Phase 4：Microsoft Agent Framework Adapter，已完成可选 adapter，不作为核心依赖。
6. Phase 5：受控 Tool Calling，已完成 provider-neutral 工具层和 mock provider loop。
7. Phase 6：内部多 Agent workflow，已作为默认 analyze 链路。
8. Phase 7：泛化验证与 Provider 原生工具链增强，已完成 DABstep public all 1-450 mock 执行覆盖、Microsoft 脱敏数据 1-300 mock 离线 scorer、桌面 VDS 95 题 smoke，仍持续增强。
9. Phase 7.1：DABstep Submission Quality Gate and Easy Capability Closure，新增为下一阶段；重点是提交文件治理、Easy 基础能力族闭环、最终答案格式收敛和风险报告，不实现单题优化。
10. Phase 7.2：Agent Generalization and Executor Semantic Parity，作为 Phase 7.1 之后的后续子目标；重点是能力族优先、Planner / Verifier 泛化、Capability Registry、Executor 覆盖率与一致性报告，不替代、不阻塞 Phase 7.1 submission gate。
11. Phase 7.3：Evaluation-Driven Robustness and Output Contract Hardening，作为 Phase 7.2 之后的后续子目标；重点是最终答案 canonicalizer、output validator、validation-driven retry、submission provenance、真实 provider 大规模回归和风险分类，不替代 Phase 7.1 submission gate，也不重做 Phase 7.2 Capability Registry。
12. Phase 7.5：Controlled Tool Hardening and Safety Boundary，作为 Phase 7.3 后的工具层硬化阶段；重点是 ToolDispatcher、schema、allowed_roles、timeout、trace-safe summary、Pandas / NumPy 白名单、SQL / DuckDB read-only 限制和文件访问边界。
13. Phase 7.6：Provider-native Tool Loop Real Smoke，作为真实 OpenAI / DeepSeek tool loop smoke 阶段；provider tool call 只能映射到内部 ToolCall 并经过 ToolDispatcher，不作为生产默认链路。
14. Phase 7.7：DuckDB Read-only Runtime，作为 SQL 目标执行层增强；sqlite 只保留 fallback，DuckDB 必须保持只读、单语句、SELECT / CTE、Result Normalizer、Verifier 和 trace 边界。
15. Phase 7.8：Multi-Agent Parallel Executor and Bounded Correction，作为复杂多 Agent 编排起步；先做 Pandas / SQL / DuckDB executor 有限并行和 bounded correction retry，不并行 Planner / Verifier / Correction 的核心决策。
16. Phase 7.9：Microsoft Agent Framework Adapter Demo，作为可选承载层 demo；MAF 只映射 AgentRole、ToolDefinition、WorkflowState，不成为强依赖，不承载核心算法。
17. Phase 7.10：ACI Associated Cost and Complex BI Expansion，继续补齐 best_fraud_aci_choice / associated cost / fee what-if candidate table 和复杂中文 BI 能力，禁止按题号、题面、固定样本值或 proxy answer 特调。
18. Phase 8 Guardrail：核心算法回看与多文件/多表泛化闭环已完成 8A-8E；后续只做 non-regression 守护，不重开 Phase 8 主体。
19. Phase 9.1：Workbench Confirmation and Review Panels，在 Phase 9 首版 workbench 后继续做字段确认、join key 确认、澄清交互和评测回看；前端仍不承载指标公式、join 或数据计算。
20. Phase 10：Visualization, Insight, Data Quality and Safe Process View，已完成 ChartSpec v2、InsightResult v2、DataQualityReport、safe `reasoning_trace_view` 和 workbench 渲染。自动清洗不属于 Phase 10，后续必须开新 Phase 并要求用户确认。
21. Phase 11：Conversation Isolation and Session Persistence，状态为 Planned / Not implemented yet。目标是新增 `conversation_id` 会话层、历史续聊、多窗口隔离和未来用户隔离字段预留；GPT-like 小号浅灰单行过程摘要 + 点击展开详情已作为 Workbench UX hardening 先行落地。

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
35. Phase 1 Backend API Shell 新增外部 Agent 调用入口 `POST /api/data-agent/run`：外部系统可一次性传入 JSON 表格、问题和可选 request_id；backend 只创建临时 dataset 并复用现有 Phase 6+ 默认 `multi_agent` 链路，不代表新增核心算法 Phase，不属于 Phase 5 Tool Calling，也不属于 Phase 7 Provider 原生 tool loop。
36. Phase 7.2 首个代码落点已完成：新增 Capability Registry，统一 operation -> capability family -> SQL support 边界；多 Agent 和 single_agent 的 SQL gate 改为读取 registry；Benchmark report 已输出 SQL coverage、Pandas-SQL consistency、coverage gap、semantic mismatch、executor mismatch、format mismatch 和 capability family metrics。回归输出包括 `outputs/phase72_capability_registry_dev_1_10_20260522/dev_1_to_10_report.json`、`outputs/phase72_capability_registry_dabstep_all_1_450_20260522/all_1_to_450_report.json`、`outputs/phase72_capability_registry_microsoft_1_300_20260522/report.json`、`outputs/phase72_capability_registry_vds_question_summary_95_20260522.json`。
37. Phase 7.3 首个代码落点已完成：新增最终答案 canonicalizer / output validator，Response Builder 会把最终答案统一收敛为提交安全字符串并记录 output_contract_validation；DABstep 和 Microsoft runner 已加入 output-contract validation-driven retry、submission provenance、prediction / report hash 和统一 risk taxonomy；RunTrace final_response 记录 output_contract_passed，用于后续真实 provider 分段回归。
38. Phase 7.3 mock / 离线闭环已完成：DABstep dev 1-10 为 9/10，DABstep public all 1-450 为 success_count=450、failure_count=0，Microsoft 1-300 为 300/300，桌面 VDS 95 smoke 为 95/95；上述报告均输出 provenance、risk_taxonomy，且 format_risk、submission_risk、trace_redaction_risk 为 0。真实 provider representative / staged / full 回归必须在存在 OpenAI 或 DeepSeek key 时执行，不以 mock 结果冒充真实 provider 结果；Phase 10 已完成 DeepSeek full real after-fix 汇总。
39. Phase 7.2 泛化契约第一轮实现已完成：Planner 会补齐 metric_definition、numerator、denominator、entity_grain、time_window、candidate_set 和 output_contract；Verifier 已按业务语义识别显式 filter、grouped count、count vs sum、mode/top_count、Top-K share denominator，并修正中文零售业务 quantity / count / formula 误判。最终回归输出包括 `outputs/phase72_generalization_contract_dev_1_10_final_20260522/dev_1_to_10_report.json`、`outputs/phase72_generalization_contract_dabstep_all_1_450_final_20260522/all_1_to_450_report.json`、`outputs/phase72_generalization_contract_microsoft_1_300_final_20260522/report.json`、`outputs/phase72_generalization_contract_vds_question_summary_95_final_20260522.json`。
40. 当前工作目标已切换到 DABstep Easy Accuracy Recovery，并按 Phase 职责拆分记录；这不是替换原 Phase 7.1 / 7.2 定义。Phase 7.1 记录 easy public proxy baseline `50/72 = 69.44%`、验收目标 `>=62/72 = 86.11%`、优先 `>=65/72 = 90.28%` 和 proxy policy；Phase 7.2 记录对应的泛化能力族实现。本轮真实 DeepSeek 后验 proxy 观察已达 `69/72 = 95.83%`（`outputs/dabstep_easy_proxy_20260522_deepseek_real_combined/all_1_to_72_public_proxy_observation.json`），mock 离线回归为 `72/72 = 100%`（`outputs/dabstep_easy_proxy_20260522_after_recovery/all_1_to_72_public_proxy_observation.json`）；public proxy 仍只作为 response 之后观察，不进入 Planner / Executor / Verifier / Correction / prompt / tests fixture。
41. 当前新增 Phase 8 / Phase 9 实施治理规则：每进入新 Phase 或 Phase 内子阶段，必须先在 MAIN_GOAL.md 更新当前阶段 Goal，并预写下一阶段 Goal；每完成一个阶段，必须回看验收结果并更新后续 Goal。Phase 8 期间模型能力和泛化能力不得低于 DABstep、微软脱敏数据和原本 VDS 当前基线；Phase 9 必须等待 Phase 8 完成后启动。
42. Phase 8 已完成 8A-8E：`POST /api/data-agent/upload-batch` 支持一次上传多文件；profile 保留 `source_file`、`sheet`、`table_name`；inline table 同步支持 metadata；LogicForm / AnalysisPlan / trace 增加 `source_tables`、`table_selection_reason`、`join_plan`；Pandas executor 可受控 materialize 可信 join；Verifier 对无可信 join key、多对多风险、多表未 join 和 ID fallback 进行阻断或澄清。
43. Phase 8 非退步门禁已通过：DABstep dev 1-10 为 `9/10`，DABstep public all 1-450 mock 执行覆盖为 `450/450`，微软脱敏数据 1-300 mock scorer 为 `300/300`，原本 VDS `问题汇总.xlsx` 95 题 smoke 为 `95/95`；`format_risk`、`submission_risk`、`trace_redaction_risk` 均为 0。
44. Phase 9 已完成首版前端 workbench：`frontend/` 提供静态页面，`backend/main.py` 挂载 `/frontend` 和 `/workbench`；页面只调用 `/api/data-agent/upload`、`/api/data-agent/upload-batch` 和统一消息入口 `/api/data-agent/message`，展示结果、用户可读过程和历史记录，不实现核心计算。
45. Phase 8/9 已补跑真实 DeepSeek representative 回归：DABstep dev 1-10 真实 DeepSeek 为 `9/10`；微软脱敏数据 1-20 真实 DeepSeek 为 `20/20`；原本 VDS `问题汇总.xlsx` 五域代表集 15 题真实 DeepSeek 在修复 LLM candidate_set 归一化后为 `15/15`，输出契约失败为 0。
46. Phase 10 已完成首版：`data_agent_core/output/chart_planner.py` 自动选择 bar / horizontal_bar / line / pie / donut / histogram / KPI；`insight_generator.py` 只基于已验证结果生成摘要、异常、波动和建议；`core/data_quality.py` 在上传和分析时扫描缺失、重复、类型、日期、离群和 key 风险；`reasoning_trace_view.py` 只展示结构化阶段摘要，不暴露完整 Chain of Thought。Workbench 已展示图表、洞察和用户可读过程时间线；质量报告、warnings/errors、verification 细节和 join trace 保留在后端/API，不在主界面直接展示。
47. Phase 10 当前验收已通过：Full unittest `147 tests OK`，compileall、`node --check frontend/app.js` 和 `git diff --check` 通过；DABstep dev `9/10`、DABstep public all mock `450/450`、Microsoft 1-300 mock `300/300`、原本 VDS 95 smoke `95/95`；真实 DeepSeek full 回归已完成，汇总为 DABstep public all `success_count=450/450`、Microsoft `correct=300/300`、原本 VDS 95 smoke `success_count=95/95`，输出 `outputs/phase10_full_real_three_dataset_deepseek_20260523_summary_after_fix.json`。DABstep public all answer 为空，不能据此宣称 hidden official accuracy。
48. DAB Hard Recovery v2 已完成第一轮代码落点：新增 DABstep all-450 post-response proxy observation 工具，可从 Phase 10 after-fix report 和本地 `task_scores` 重新生成 Easy / Hard、operation、capability family 和 format/list-order 风险口径；输出 `outputs/dabstep_all_1_450_proxy_after_phase10_20260524/all_1_to_450_public_proxy_observation_after_fix.json` 显示 total `420/450 = 93.33%`、Easy `71/72 = 98.61%`、Hard `349/378 = 92.33%`。代码层面补齐数字 fee ID list canonicalization、fee ID engine 稳定排序和 Fee / ACI candidate table 语义校验；非回归门禁通过 DAB dev `9/10`、DAB all mock `450/450`、Microsoft `300/300`、VDS 95 smoke `95/95`、Phase 8 multi-file/join focused `5 OK`、full unittest `152 OK`。该 proxy 仍只作为 response 之后风险观察，不代表 official hidden accuracy，也不进入 Planner / Executor / Verifier / Correction / prompt / trace。
49. Workbench UX hardening 已补齐普通消息路由和多轮展示缺口：前端统一调用 `POST /api/data-agent/message`，由后端判断无文件聊天、有文件普通聊天、泛数据概览或正式分析；“你好 / 你是什么模型”不会再因已有 dataset 被误送入分析链路；“看一下这个数据 / 看一下整体销售情况”由 `data_agent_core/output/dataset_overview.py` 或 Response Builder 收敛为全表汇总概览，防止主答案只返回行数或原始多字段明细行。前端每轮创建独立 assistant 回复，仍只负责调用 API 和展示，不实现指标计算、join、排序或聚合。

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
33. README.md 是 GitHub 默认首页状态摘要；任何阶段、主目标、项目规则、API、Benchmark 口径、验证状态或用户可见能力变化，都必须同步检查并更新根 README.md。如果本轮确认 README 不需要修改，必须在 CHANGELOG_AI.md 写明原因。

## Microsoft Agent Framework 策略

Microsoft Agent Framework 是多 Agent 编排的候选承载框架，但不是当前核心算法依赖。当前默认 Phase 6 workflow 使用内部 runtime；Phase 7 可继续验证 provider / framework 承载能力，但 Microsoft adapter 仍只是可选承载和映射层。

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
4. 在前端实现核心分析逻辑、指标公式、join 或数据计算
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
18. 在 Phase 10 自动修改、清洗或覆盖用户上传的原始数据；当前只输出质量问题和清洗建议
19. 在 API、debug、trace 或前端展示完整 Chain of Thought、raw reasoning tokens、raw prompt、API key 或 hidden benchmark answer

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

## Phase 7：泛化验证与 Provider 原生工具链增强

Phase 7 的目标不是在 Phase 6 后面继续加后缀，而是把已完成的多 Agent 基线之上的增强统一归类：更大范围 Benchmark / 中文真实数据泛化验证、Not Applicable 能力缺口闭环、中文 BI 能力族扩展、Provider 原生 tool calling 接入、DuckDB runtime、复杂并行和多轮自纠。

Phase 7 仍不能替换本地工具层。OpenAI / DeepSeek 的原生 tool calling 只能接到现有 provider-neutral 工具契约上；当前已完成 schema / tool call 解析 / mock loop 基线，下一步是真实 provider 网络 smoke 和更完整失败恢复。真实执行、权限、参数校验、超时、trace 摘要和错误归一化仍由本地 ToolDispatcher 负责。

阶段顺序：

1. 已完成 Phase 6 最小多 Agent 默认链路，backend analyze 默认走 `multi_agent`，single_agent 保留为 fallback。
2. 已完成 DABstep public all 1-450 mock 执行覆盖、Microsoft 脱敏数据 1-300 mock 离线 scorer 和桌面 VDS 95 题 smoke 的阶段性验证。
3. 已实现 OpenAI / DeepSeek 兼容工具循环 adapter 基线，把 provider tool schema / tool call / tool result 映射到内部 ToolDefinition、ToolCall 和 ToolResult。
4. OpenAI adapter 必须复用现有 ToolRegistry / ToolDispatcher / ToolTraceEvent，不允许在 provider adapter 中实现 DatasetProfile、Pandas、SQL、Verifier、Chart 或 Insight 逻辑。
5. 已跑通 mock/fake provider 单元测试；仍需补真实 OpenAI / DeepSeek key 下的 uploaded dataset smoke，且 key 只能来自 ignored env 文件或运行环境。
6. DeepSeek provider 特化只处理 DeepSeek 与 OpenAI-compatible chat completions / tool calls 的协议差异；不得 fork 内部工具契约。
7. DeepSeek thinking mode 或其他 reasoning 字段只能由 provider adapter 内部维护，用于必要的续传或工具回填，不进入稳定 trace、debug 或 API 响应。
8. Provider 原生并行 tool calls 如后续启用，必须先证明不会破坏工具顺序依赖、WorkflowState 一致性和 trace 可复现性。

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

## Phase 7 质量提升：业务口径驱动的多 Agent 泛化能力

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

## Phase 7 当前状态

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
8. 当前 Pandas / SQL 不等价主要是 coverage gap，不是 SQL correctness gap：SQL 仍是 sqlite fallback / SQL-compatible 子集，fee-rule 能力主要由 Pandas 路径和 shared rule engine 承载；更深层风险是 Agent 能力族抽象、Planner 泛化字段和 Verifier 语义验收还不够稳定，不能把 executor parity 误当成 Agent 泛化能力完成。
9. 当前还缺少统一风险报告，把 format risk、semantic risk、capability coverage、official hidden score 不可本地复现、public proxy observation、真实 provider cost / latency 和 submission provenance 分开记录；不能只用 success_count 或 mock 覆盖率代表可提交质量。

## Phase 7.1：DABstep Submission Quality Gate and Easy Capability Closure

Phase 7.1 是 Phase 7 下的下一阶段子目标，不是新的大阶段。该阶段只处理提交质量、Easy 基础能力族和最终答案格式收敛，不允许围绕 task_id、隐藏答案、public proxy 答案池、固定题面、固定样本值或当前 leaderboard 反馈写单题优化。

leaderboard 诊断：

1. Trevor 提交中 Easy 低、Hard 高不应被解释为框架整体失败；Hard 题可能受益于已实现的 fee engine、业务规则和多步推理能力。
2. Easy 低更可能暴露提交文件一致性、基础分析能力族、空答案、最终答案格式和 exact-match 风险。
3. 外部 leaderboard 的 Easy / Hard 反馈是提交后反馈，不等同于本地可复现 hidden official accuracy。
4. hidden official accuracy 只能由 Hugging Face leaderboard 返回；本地不能伪造、推断或把 public proxy 当作官方准确率。

Phase 7.1 当前验收目标：DABstep Easy Accuracy Recovery（2026-05-22）：

1. 以 `outputs/dabstep_easy_proxy_20260522_current_branch/all_1_to_72_public_proxy_observation.json` 记录的 `50/72 = 69.44% public proxy` 作为 Phase 7.1 easy recovery baseline；该数字不是 official hidden accuracy。
2. Phase 7.1 验收目标：DABstep easy public proxy 后验观察必须达到 `>=62/72 = 86.11%`，优先达到 `>=65/72 = 90.28%`。
3. 当前真实 provider 闭环结果：DeepSeek `deepseek-chat` 分片回归合并后，`outputs/dabstep_easy_proxy_20260522_deepseek_real_combined/all_1_to_72_public_proxy_observation.json` 为 `69/72 = 95.83% public proxy`，`success_count=65`、`unexpected_not_applicable=0`、`true_unsupported=3`、Pandas-SQL consistency `49/49`、`public_proxy_policy=not_used_in_core_chain`。
4. 当前 mock 离线回归结果：`outputs/dabstep_easy_proxy_20260522_after_recovery/all_1_to_72_public_proxy_observation.json` 为 `72/72 = 100% public proxy`，用于确定性能力族回归，不冒充真实 DeepSeek 或 official hidden accuracy。
5. public proxy 只能用于 response 生成后的后验评分、failure_by_operation、failure_by_capability_family 和 risk_taxonomy 观察；不能进入 Planner、Executor、Verifier、Correction、prompt、tests fixture 或核心源码。
6. 本轮问题归因不是 Hard 能力强就整体没问题，而是 Easy 集中暴露基础表分析语义：schema / field binding、filter extraction、grouped metric semantics、denominator selection 和 final answer target contract。
7. 仍需用 submission gate、dev 1-10、public all 1-450、Microsoft 1-300、桌面 VDS 95 和 Phase 7.2G uploaded-table 回归确认 easy 修复没有牺牲泛化。

下一阶段必须按能力族修复，而不是按题号修复：

1. counting
2. top / ranking
3. fraud ratio
4. boolean yes / no
5. null check
6. field values
7. outlier
8. quantile
9. schema / missing-column

Submission gate 要求：

1. 提交 JSONL 必须覆盖预期 task_id 集合，行数、字段名和 `agent_answer` 格式必须通过校验。
2. 禁止空答案、对象泄漏、debug 泄漏、trace 泄漏、API key 泄漏、旧 Desktop 文件误传和非本次生成文件误传。
3. 提交文件必须绑定当前 commit hash、report hash、prediction hash 和生成命令。
4. submission gate 只能检查提交质量和格式，不能读取 hidden answer，不能把 public proxy answer 注入核心链路。
5. 风险报告必须拆分 Easy / Hard 风险、格式风险、空答案风险、能力族风险和提交文件来源风险。

Phase 7.1 退出条件：

1. 新 DABstep submission JSONL 通过 submission gate。
2. 无空答案、无格式对象泄漏、无旧 Desktop 文件误传、无 key / hidden / proxy 内容泄漏。
3. 生成 Easy / Hard 风险报告，并明确它不是 hidden official accuracy。
4. DABstep public all 1-450 mock 覆盖不退化，unexpected Not Applicable 为 0。
5. DABstep dev 1-10 仍保持不低于 9/10，且没有单题特判。
6. Microsoft 1-300 和桌面 VDS 95 smoke 不退化。
7. secret scan、hardcoding scan、import boundary test 通过。

## Phase 7.2：Agent Generalization and Executor Semantic Parity

Phase 7.2 是 Phase 7 下的后续子目标，不替代、不阻塞 Phase 7.1 submission gate。该阶段的主目标是提升 Agent 面对新问题、新字段、新数据集和中英文真实业务表时的泛化能力；Pandas / SQL / DuckDB 统一只作为执行层可信度、可审计性和回归判断支撑，不能被包装成 Agent 泛化能力本身。

核心判断：

1. Pandas / SQL 分数差异首先要拆成 coverage gap、correctness gap 和 format gap；SQL skipped 不能被当成 SQL 算错。
2. 如果 Pandas / SQL 都输出一致但业务口径错误，仍然是 Agent 语义泛化失败，Verifier 必须判为需要修正。
3. Benchmark 暴露的问题必须归入可迁移能力族，例如指标定义、时间窗口、分母选择、候选集选择、字段别名、多表关联、业务规则 what-if，不能被表述为“修某题”。
4. DABstep fee-rule 能力短期可共享 deterministic rule engine；长期再把 `fees.json`、`manual.md` 和 `merchant_data.json` 的规则语义表格化并逐步 DuckDB 化，不能在 Pandas、SQL、Verifier 中复制三套业务逻辑。

阶段目标：

1. 建立 Capability Registry：每个能力族必须记录输入契约、适用边界、中文 / 英文支持、Pandas 支持、SQL / DuckDB 支持、是否依赖 shared rule engine、是否为 native SQL。
2. 强化 Planner 泛化契约：Planner 不能只选择 operation，还必须输出 metric_definition、numerator、denominator、entity_grain、time_window、candidate_set、filters 和 output_contract。
3. 强化 Verifier 语义验收：即使 Pandas / SQL 一致，只要 metric definition、entity grain、分母、时间窗口、候选集或输出格式不匹配问题，也必须判为 semantic mismatch 并触发修正方向。
4. 将 Executor parity 改为支撑层指标：Benchmark report 必须拆分 Pandas accuracy、SQL coverage、SQL covered-subset accuracy、Pandas-SQL consistency、coverage gap、semantic mismatch、executor mismatch 和 format mismatch。
5. DuckDB runtime 作为 SQL 目标执行层，sqlite 只保留 fallback；启用 DuckDB 不得绕过 ToolDispatcher、Result Normalizer、Verifier、trace 摘要和 secret / hardcoding 边界。

泛化验收：

1. 每个新能力族至少包含一个合成或非 Benchmark 用例、一个同类问法变体、一个中文字段 / 中文问题用例、一个已有代表回归用例。
2. DABstep dev 1-10 必须保持不低于 9/10；DABstep public all 1-450 mock 覆盖不退化；Microsoft 1-300 和桌面 VDS 95 smoke 不退化。
3. Public proxy 只能作为后验观察；task_id、expected answer、proxy answer、accepted answer 和 hidden answer 不得进入 Capability Registry、Planner、Executor、Verifier、Correction、prompt 或测试 fixture。
4. hardcoding scan、secret scan、import boundary test 必须继续通过；data_agent_core 不得 import backend、ms_agent_framework_adapter、multi_agent_workflows 或 agent_framework。

当前落地状态（2026-05-22）：

1. Planner 泛化契约已在 `build_analysis_plan()` 中成为默认补齐层，LogicForm 会稳定携带 metric_definition、numerator、denominator、entity_grain、time_window、candidate_set 和 output_contract；report 中同步输出 `generalization_contract` 完整性。
2. Verifier 不再只看 Pandas / SQL 一致性：显式 filter 缺失、grouped count 误路由、count 问题误用 sum、mode/top_count 误路由、Top-K metric share / count share denominator 混用都会进入 semantic mismatch；中文零售业务中的“分销数量 / SKU数量 / 执行次数 / 陈列费率=公式”按业务 quantity、top-count 或 formula context 处理，避免把正确业务 metric 误判成 executor failure。
3. Microsoft 脱敏数据 false-success 问题已归因并修复：之前 `correct=300/300` 但 `success_count=232` 是 Verifier 语义契约误杀，不是执行结果错误；最终回归 `outputs/phase72_generalization_contract_microsoft_1_300_final_20260522/report.json` 为 total=300、correct=300、accuracy=1.0、success_count=300、semantic_mismatch=0、executor_mismatch=0、format_mismatch=0。
4. DABstep final mock 回归保持不退化：dev 1-10 为 9/10，SQL covered=3/10，Pandas-SQL consistency=3/3，剩余 1 题仍归入 `best_fraud_aci_choice` / associated cost 语义口径；public all 1-450 为 success_count=450、unexpected_not_applicable=0、true_unsupported=3、SQL covered=70、Pandas-SQL consistency=70/70、coverage_gap=380。
5. 桌面 VDS `问题汇总.xlsx` 五个真实问题 sheet 共 95 题 smoke 继续为 total=95、success_count=95、failure_count=0；本轮使用 `BI测试问题` 真问题列，不使用标准答案优化。
6. 当前 SQL/Pandas 不等价仍主要是 coverage gap：DABstep all 的 skipped=380、Microsoft 1-300 的 skipped=300 都按 coverage gap 报告，不计为 SQL correctness failure；SQL covered 子集仍以 Pandas-SQL consistency 和未来独立 `sql_correct` 字段分开报告。
7. Phase 7.2 当前实现目标：DABstep Easy Accuracy Recovery 的修复必须落到泛化能力族，而不是单题补丁；本轮已新增 `answer_target` 输出契约，区分 `metric_only`、`entity_only`、`entity_list_only`、`segment_vector`；字段 / filter 解析接入 alias 优先级和 missing / null / fraud boolean / IP country / account_type 规则上下文；fraud grouped metric 支持 max / min / std、merchant / card_scheme / country / shopper_interaction 维度和年 / 季度过滤；denominator / share / quantile 支持 per unique email、top-k count share selected by amount volume、repeat-customer subset；fee what-if 使用 deterministic fee engine 返回 monotonic factor 和 volume range label。
8. 本轮借鉴 DA-agent 的边界只限 schema/tool-first evidence、DuckDB/read-only SQL guardrail、validation retry 和 deterministic rule engine；不引入 task_id、proxy answer、hidden answer、accepted answer，也不把 VDS 改成 SQL-first benchmark product framing。

### Phase 7.2G：Uploaded Table Generalization Gap Closure

Phase 7.2G 是 Phase 7.2 下的专项泛化验收，不是新的 Phase 7.4，也不替代 Phase 7.3 的 Output Contract、validation-driven retry 和 submission provenance。该专项把 Microsoft 新增 100 满分但原始五域新增 100 只有 58/100 的差距归入 Agent 泛化、字段角色绑定、Planner / Verifier 语义契约和 capability family 覆盖问题。

当前事实锚点：

1. Microsoft 新增 100：`100/100`，easy `40/40`，hard `60/60`。
2. 原始五域新增 100：`58/100`，easy `18/40`，hard `40/60`。
3. 结论：中文零售专用链路稳定，但通用上传表泛化仍不足。

当前闭环结果（2026-05-22）：

1. 已新增通用上传表离线 runner `multi_agent_workflows/uploaded_table_benchmark_runner.py`，支持按 JSONL 行的 `source_file` / `sheet` 或 CSV root 构造 uploaded-table workflow；标准答案只在 response 生成后用于 scorer，不传入 Agent workflow。
2. 原始五域新增 100 mock 回归已达标：`outputs/phase72g_original_new100_uploaded_runner_final_20260522/report.json` 为 `99/100`，easy `40/40`，hard `59/60`。
3. Microsoft 新增 100 mock 回归保持不退化：`outputs/phase72g_microsoft_new100_uploaded_runner_final_20260522/report.json` 为 `100/100`，easy `40/40`，hard `60/60`。
4. 本轮修复属于通用能力族：上传表 top_count 执行、filter vs dimension 绑定、显式 count / sum / mean 聚合、中文小数位输出契约、隐式 filter 安全语境、结构化 raw value 离线评分、VDS 周期对比 count/share 语义校验、DABstep fee-rule 候选规则缓存。
5. 唯一剩余原始五域失败为 filtered Top-K metric share：源表重算和 agent raw value 均为 `45.63692666600649%`，最终答案 `45.64%`；当前标准答案为 `45.70%`，归为标准答案生成口径待复核，不允许为该单题做执行层特调。
6. Phase 7.2 回归基线已复跑：DABstep dev 1-10 为 `9/10`（`outputs/phase72g_dabstep_dev_1_10_final_20260522/dev_1_to_10_report.json`）；DABstep public all 1-450 mock 为 `success_count=450/450`、`unexpected_not_applicable=0`、`accuracy=null`（public all answer 为空，`outputs/phase72g_dabstep_all_1_450_final2_20260522/all_1_to_450_report.json`）。
7. Microsoft 1-300 mock scorer 保持 `300/300`（`outputs/phase72g_microsoft_1_300_20260522/report.json`）；桌面 VDS `问题汇总.xlsx` 95 题 smoke 为 `95/95`（`outputs/phase72g_vds_question_summary_95_20260522.json`）。

能力聚焦：

1. 字段角色绑定：`区域为华北` 这类表达应绑定为 filter，不是 dimension。
2. 显式 metric：`销售额总和` 必须绑定 sum metric，不能退化成 row count。
3. 聚合口径：`按区域统计记录数` 必须是 count，不是默认 sum 销售额。
4. 众数 / top count：`最常见取值` 应路由到 mode / top_count，不应返回 Not Applicable。
5. Top-K share：必须区分 metric share 和 count share，不能混算。
6. 筛选后排名：必须先应用 filter，再按指定 metric 排名。
7. 无效验收样本排除：空实体列、全 0 指标、无意义答案不能作为泛化通过证据。

验收标准：

1. 原始五域新增 100：overall >= `85%`，easy >= `90%`，hard >= `80%`。
2. Microsoft 新增 100：保持 overall >= `98%`。
3. 失败报告必须按 capability family 聚合，至少包含 parser miss、role-binding miss、filter loss、metric mismatch、aggregation mismatch、mode/top_count miss、ranking/share mismatch 和 format mismatch。
4. 每个修复能力必须至少有一个非当前错误样本的同类变体，优先覆盖中文字段、英文字段、字段别名和不同字段值。
5. 禁止按 task_id、标准答案、固定字段值、固定问法、当前错误样本或当前 benchmark slice 特调。

回归要求：

1. 保留 Microsoft 新增 100 和原始五域新增 100 两套回归集，分别输出 overall、easy、hard 正确率。
2. 复跑现有 Phase 7.2 回归基线：DABstep dev 1-10、DABstep public all 1-450 mock、Microsoft 1-300 和桌面 VDS 95 smoke。
3. 新增或更新报告字段时，不改变后端稳定 API；只扩展 benchmark / report metadata。

## Phase 7.3：Evaluation-Driven Robustness and Output Contract Hardening

Phase 7.3 是 Phase 7.2 之后的下一阶段子目标，中文口径为“评测驱动鲁棒性与最终输出契约硬化”。该阶段不是重新定义 Agent 泛化能力，也不是把 DA-agent 的 SQL-first benchmark 产品定位搬进 VDS，而是把 Phase 7.1 的提交质量门禁和 Phase 7.2 的能力族 / Planner / Verifier 契约串成可复现、可审计、可真实 provider 回归的闭环。

核心判断：

1. DA-agent 的 Easy 表现提示我们，低风险基础题的差距很可能来自 schema / rule-first 工作流、最终答案格式、验证失败重试、提交文件治理和 runtime materialization，而不只是模型能力。
2. VDS 当前已经能跑通 DABstep public all 1-450 mock、Microsoft 1-300 mock scorer 和桌面 VDS 95 smoke；下一步必须证明真实 provider、最终输出字符串、提交 provenance 和风险报告同样稳定。
3. official hidden score 只能来自 leaderboard；public proxy、历史 task_scores 和本地 mock 覆盖只能用于后验观察、能力缺口归因和提交风险分类，不能进入核心分析链路。

可借鉴 DA-agent 的工程模式：

1. schema / rule-first：Planner 或工具循环在字段、规则、manual 不确定时必须先查 schema summary、field docs 和规则上下文，再构造 LogicForm。
2. DuckDB runtime materialization：上传 CSV / JSON / 文档规则可以被物化为 DuckDB table、view 和 metadata，供受控 Executor 使用；不得让模型直接获得 raw SQL、shell、网络或任意文件访问。
3. read-only SQL guardrail：SQL / DuckDB 路径必须保持只读、单语句、SELECT / CTE、参数校验、limit preview 和 Result Normalizer；任何 provider-native tool call 仍需经过 ToolDispatcher。
4. validation-driven retry：工具失败、Verifier semantic mismatch、output_contract mismatch、format mismatch 或 capability_gap 都应进入结构化重试原因和受控 correction，而不是直接生成自然语言兜底。
5. final answer only：Benchmark submission 的 `agent_answer` 必须来自已验证结果的 canonicalizer，不允许对象、列表、debug、trace、SQL、markdown、解释文字或中间候选表泄漏到最终答案。
6. deterministic fee / rule engine：复杂业务规则仍应沉淀为共享 deterministic rule engine 或规则表，不在 prompt、Pandas、SQL、Verifier 中复制多套不可审计逻辑。

明确不借鉴的模式：

1. 不把 task_id、expected answer、proxy answer、accepted answer、hidden answer 或 leaderboard 反馈写入 prompt、Planner、Executor、Verifier、Correction、测试 fixture 或核心源码。
2. 不给模型 raw SQL 自由执行权、不允许任意文件读取、不绕过 ToolDispatcher、不把 provider adapter 变成核心算法。
3. 不把 VDS 改成 SQL-first benchmark runner；VDS 仍是中文优先、上传数据集驱动、Pandas / SQL / DuckDB 双路径可校验的数据分析 Agent。
4. 不把 public proxy 命中率、mock success_count 或 Desktop 旧文件结果包装成 hidden official accuracy。

阶段目标：

1. 建立最终答案 canonicalizer 和 output validator：按 output_contract 处理数字、小数位、百分号、yes/no、逗号分隔、多值列表、Not Applicable 和空答案边界。
2. 建立 validation-driven retry loop：把工具错误、semantic mismatch、format mismatch、capability gap 和 provider transient failure 分开记录，并只触发受控重试或明确失败。
3. 建立 submission provenance：每个 DABstep JSONL 必须绑定 commit hash、生成命令、prediction hash、report hash、模型 / provider / runtime 元数据和生成时间，避免旧 Desktop artifact 误传。
4. 建立统一风险 taxonomy：风险报告必须拆分 format risk、semantic risk、capability risk、submission risk、official hidden unknown、public proxy observation、real-provider cost / latency 和 trace redaction risk。
5. 建立真实 provider 大规模回归策略：支持 representative / staged / full 三档，支持断点续跑、stage cache、rate limit / timeout 处理和 deterministic mock fallback，但不能牺牲 trace、Verifier 和安全边界。
6. 建立 trace 脱敏和证据最小化：trace 只保留工具名、参数摘要、结果摘要、错误、耗时、校验结论和 provenance，不记录完整 Chain of Thought、raw reasoning tokens、API key、hidden answer 或敏感原始数据。

当前代码落点：

1. `data_agent_core/output/output_contract.py` 负责 canonicalize 和 validate 最终答案，覆盖 number、percentage、yes/no、list、scheme fee、ACI、card scheme、grouped amounts、Not Applicable、空答案、对象 / 列表泄漏、debug / trace 泄漏和 SQL / markdown 泄漏。
2. `data_agent_core/output/response_builder.py` 已把 canonicalizer 接入 FinalResponse；output contract 不通过时返回 `OUTPUT_CONTRACT_VALIDATION_FAILED`，标记 recoverable，并进入 validation_driven_retry 结构化记录。
3. `data_agent_core/benchmark/provenance.py` 为 prediction / report 生成 trace-safe provenance：commit、branch、dirty 状态、命令、runtime、provider env、prediction hash、report content hash 和生成时间，不记录 API key 或 hidden answer。
4. DABstep / Microsoft benchmark runner 已把最终 `agent_answer` 固定为字符串，输出 output_contract_passed、output_risk_flags、output_contract_retry_events、risk_taxonomy 和 provenance；public proxy policy 固定为 `not_used_in_core_chain`。
5. `metrics.summarize_details` 已输出统一 risk taxonomy，拆分 format、semantic、capability、submission、official hidden unknown、public proxy observation、real-provider cost / latency 和 trace redaction risk。
6. `data_agent_core/verifier/result_comparator.py` 已支持嵌套 list / dict 中数值的近似比较，吸收 Pandas 与 SQL 后端之间的浮点表示尾差，避免 `600301.9199999999` vs `600301.92` 这类非语义差异造成 VDS 95 smoke 退化。

当前验收结果：

1. DABstep dev 1-10 mock 多 Agent：`outputs/phase73_output_contract_dev_1_10_after_comparator_20260522/dev_1_to_10_report.json`，total=10、correct=9、accuracy=0.9、success_count=10、format_risk=0、submission_risk=0、trace_redaction_risk=0。
2. DABstep public all 1-450 mock 多 Agent：`outputs/phase73_output_contract_dabstep_all_1_450_after_comparator_20260522/all_1_to_450_report.json`，total=450、success_count=450、failure_count=0、unexpected_not_applicable=0、true_unsupported=3、format_risk=0、semantic_risk=0、submission_risk=0、trace_redaction_risk=0、official_hidden_unknown=true。
3. Microsoft 脱敏数据 1-300 mock 离线 scorer：`outputs/phase73_output_contract_microsoft_1_300_after_comparator_20260522/report.json`，total=300、correct=300、accuracy=1.0、success_count=300、format_risk=0、semantic_risk=0、submission_risk=0、trace_redaction_risk=0。
4. 桌面 VDS `问题汇总.xlsx` 95 题 smoke：`outputs/phase73_output_contract_vds_question_summary_95_final_20260522.json`，total=95、success_count=95、failure_count=0、output_contract_failure_count=0，使用 `BI测试问题` 列，不使用标准答案、hidden answer 或 public proxy。

Phase 7.3 退出条件：

1. DABstep submission JSONL 无对象、列表、dict、debug、trace、SQL、markdown 或解释文字泄漏，且空答案和 `Not Applicable` 均有结构化归因。
2. 风险报告能独立展示 format / semantic / capability / submission / official hidden unknown / public proxy observation / real-provider cost latency 风险。
3. 真实 provider representative 回归可复现，记录 provider、model、cost / latency、失败重试原因、prediction hash 和 report hash。
4. DABstep public all 1-450 mock 覆盖不退化，DABstep dev 1-10 不低于 9/10，Microsoft 1-300 mock scorer 和桌面 VDS 95 smoke 不退化。
5. hardcoding scan、secret scan、import boundary test 继续通过；核心链路仍不使用 task_id、标准答案、proxy answer、accepted answer 或 hidden answer。

## Phase 7.5+ 后续子阶段计划

Phase 7.5+ 用于承接 Phase 7.1 / 7.2 / 7.2G / 7.3 之后的增强工作。这里不使用 Phase 7.4，避免和 7.2G / 7.3 既有口径混淆；所有 Phase 7.5+ 工程子阶段都必须保持三套数据不退步：DABstep dev 1-10 不低于 `9/10`，DABstep public all 1-450 mock 保持 `success_count=450/450` 且 `unexpected_not_applicable=0`，Microsoft 脱敏数据 1-300 mock scorer 保持 `300/300`，桌面 VDS `问题汇总.xlsx` 95 题 smoke 保持 `95/95`。`format_risk`、`submission_risk`、`trace_redaction_risk` 必须保持 0，secret scan、hardcoding scan 和 dependency boundary test 必须通过。

并发规则：因为本仓库可能多人同时修改代码，Phase 7.5+ 的工程实现必须使用独立 worktree / branch，例如 `codex/vds-phase75-tool-safety`、`codex/vds-phase76-provider-smoke`、`codex/vds-phase77-duckdb-runtime`、`codex/vds-phase78-multi-agent-retry`、`codex/vds-phase79-maf-demo`、`codex/vds-phase710-aci-bi` 和 `codex/vds-phase91-workbench-confirmation`。所有分支由 integrator 顺序合并；任一阶段导致 DABstep、Microsoft 或 VDS 数据回归退步，必须停止合并并回到对应阶段修复。

### Phase 7.5：Controlled Tool Hardening and Safety Boundary

目标：把已完成的 provider-neutral 工具层从可运行状态推进到可审计、可失败恢复、可真实 provider 调用的安全边界。

禁止事项：不新增自由 Python、自由 SQL、shell、网络请求或任意文件访问；不让 provider adapter 或 Microsoft adapter 实现核心算法。

进入条件：Phase 7.3 output contract / risk taxonomy 已完成；现有 ToolRegistry、ToolDispatcher、Data Agent tool catalog 和 provider-native mock loop 可测。

退出条件：Tool schema、allowed_roles、timeout、参数类型、错误归一化和 trace-safe summary 均有测试；Pandas / NumPy 白名单、SQL / DuckDB read-only 限制、文件访问根目录策略形成文档或测试边界；三数据集 non-regression gate 全部通过。

### Phase 7.6：Provider-native Tool Loop Real Smoke

目标：接入 OpenAI / DeepSeek 真实网络 tool loop smoke，验证 provider tool schema、tool call、tool result 与内部 ToolDefinition / ToolCall / ToolResult 的映射。

禁止事项：不把 provider-native adapter 作为生产默认链路；不绕过 ToolDispatcher；不把 DeepSeek thinking mode、OpenAI reasoning item、raw reasoning tokens 或 API key 写入 trace / debug / API 响应。

进入条件：Phase 7.5 工具层硬化通过；存在真实 `OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY` 时才能执行 real smoke，没有 key 时只能跑 mock。

退出条件：真实 smoke 可完成 profile_schema、build_analysis_plan、execute_pandas_plan、execute_sql_plan、verify_results、build_chart_spec、generate_insight 的闭环；记录 provider、model、latency、cost、prediction hash、report hash；mock 与真实 provider 结果不能混写。

### Phase 7.7：DuckDB Read-only Runtime

目标：把 DuckDB 作为 SQL 目标执行层，sqlite 仅保留 fallback，用于提升 SQL / Pandas / DuckDB 双路径可审计性。

禁止事项：不开放模型自由 SQL；不允许 DDL / DML / 多语句 / shell / 网络；不复制 Pandas、Verifier 或 rule engine 业务逻辑到 adapter。

进入条件：Phase 7.5 的 SQL / DuckDB read-only 边界已明确；当前 SQL coverage gap 和 covered-subset consistency 指标可复现。

退出条件：DuckDB 只读 SELECT / CTE、单语句、limit preview、Result Normalizer、Verifier、trace 摘要和 secret / hardcoding 边界都有测试；sqlite fallback 不退化；三数据集 non-regression gate 全部通过。

### Phase 7.8：Multi-Agent Parallel Executor and Bounded Correction

目标：在不改变核心算法位置的前提下，先做 Pandas / SQL / DuckDB executor 有限并行，再做 bounded correction retry。

禁止事项：不并行 Planner、Verifier、Correction 的核心决策；不让 executor 自己决定最终答案；不为了并行牺牲 WorkflowState 可序列化、trace 可复现或 Verifier 边界。

进入条件：每个 Agent 角色已有独立测试；WorkflowState、AgentTask、AgentResult 和 tool_call_trace 可序列化。

退出条件：Pandas / SQL / DuckDB 并行结果统一进入 Verifier；semantic mismatch、tool error、format mismatch、capability_gap 分开记录并触发固定最大轮数的 correction retry；所有 correction attempt 写入 trace；三数据集 non-regression gate 全部通过。

### Phase 7.9：Microsoft Agent Framework Adapter Demo

目标：验证 Microsoft Agent Framework 作为可选承载层可以映射 AgentRole、ToolDefinition、ToolCall、ToolResult 和 WorkflowState。

禁止事项：不让 MAF 成为 data_agent_core 或 backend 强依赖；不在 adapter 中实现文件解析、Pandas、SQL、Verifier、Benchmark、评分或业务规则。

进入条件：Phase 7.5 工具契约稳定；fake framework adapter 测试继续通过；requirements-ms-agent.txt 仍作为独立可选依赖入口。

退出条件：真实 MAF demo 或 cloud workflow 能承载内部角色和白名单工具映射；data_agent_core 不 import ms_agent_framework_adapter 或 agent_framework；三数据集 non-regression gate 全部通过。

### Phase 7.10：ACI Associated Cost and Complex BI Expansion

目标：继续补齐 `best_fraud_aci_choice`、ACI associated cost、fee what-if candidate table、candidate-pair / rule semantics，以及 VDS 趋势、状态影响、毛利率、支付 / 配送 / 付费方式等复杂中文 BI 问法。

禁止事项：不按 DABstep task_id、题面、public proxy、accepted answer、hidden answer、固定样本值或当前错误形态特调；不把中文能力写成只适配当前脱敏数据或当前 Excel 的规则。

进入条件：Phase 7.2 / 7.2G / 7.3 的 capability family、Planner 泛化契约、Verifier 语义验收和 output contract 继续有效。

退出条件：每个新增能力族至少有合成或非 Benchmark 用例、同类变体、中文字段 / 中文问题用例和旧代表回归；DABstep / Microsoft / VDS 三数据集不退步。

### Phase 8 Guardrail：Multi-file / Multi-table Non-regression

目标：Phase 8 已完成 8A-8E，后续只守护多文件、多表、join plan、Verifier 和 trace，不重开 Phase 8 主体。

退出条件：每次影响 dataset/profile/routing/join/executor/verifier/trace 的改动，都必须覆盖多文件路由、无 join key、多对多 warning、旧单表回归和三数据集 non-regression gate。

### Phase 9.1：Workbench Confirmation and Review Panels

目标：在 Phase 9 首版 workbench 之后增加字段确认、join key 确认、低置信度澄清交互和评测回看面板。

禁止事项：前端不实现指标公式、join、排序、聚合、评分或核心数据计算；前端不依赖 debug 字段做业务计算。

退出条件：桌面 / 移动 smoke 无 console error；所有计算仍来自 backend / data_agent_core；用户确认只作为后端稳定 API 的输入。

## Phase 8：核心算法回看与多文件/多表泛化闭环

Phase 8 是 Phase 7 系列之后的正式新阶段，不是 Phase 7.4。该阶段目标是回过头系统性审查并补齐当前核心算法中的多文件、多表和泛化能力缺口，在不牺牲既有模型能力、不降低泛化能力的前提下，完成多文件精准路由、多表 join、表关系发现、澄清机制、Verifier 校验和回归评测闭环。

Phase 8 必须先于前端产品化。Phase 8 未完成前，不启动复杂前端建设；前端只能在核心算法、API 契约和回归门禁稳定后进入 Phase 9。2026-05-23 当前状态：Phase 8A-8E 已完成并通过门禁，已允许进入 Phase 9。

Phase 8 的硬门槛：

1. 模型能力不能退步：DABstep dev 1-10 不低于当前 `9/10`；有 OpenAI / DeepSeek key 时补跑真实 provider representative / staged 回归，没有 key 时不能用 mock 冒充真实模型能力。
2. 泛化能力不能退步：DABstep public all 1-450 mock 必须保持 `success_count=450/450`、`unexpected_not_applicable=0`；微软脱敏数据 1-300 mock scorer 必须保持 `300/300`；原本 VDS `问题汇总.xlsx` 95 题 smoke 必须保持 `95/95`。
3. 风险指标不能退步：`format_risk`、`submission_risk`、`trace_redaction_risk` 不得上升；`semantic_risk` 和 `capability_risk` 如上升，必须阻塞进入下一子阶段并写明修复 Goal。
4. 任何新增多文件、多表、join 或路由能力都必须通过合成用例、同类变体用例和既有三类回归验证；禁止通过固定题号、固定文件名、固定字段值、标准答案或 public proxy answer 写特调补丁。

Phase 8 当前退出结果：

1. Phase 8A 已完成：多文件 dataset 装配层支持一个 dataset 包含多个源文件或 sheet；profile 保留 `source_file`、`sheet`、`table_name`、字段画像和样例值；旧单文件上传和 `/api/data-agent/run` inline table 基线不退化。
2. Phase 8B 已完成：表路由按文件名、表名、字段名、语义别名和样例值打分；销售 / 库存两表能分别命中正确表；显式“库存文件”能命中库存表；不再对上传表问题静默退回 `primary_table`。
3. Phase 8C 已完成：同名字段、归一化 ID 字段、唯一性和值重叠率用于推断可信 join key；`LogicForm` 和 `AnalysisPlan` 稳定携带 `source_tables`、`table_selection_reason`、`join_plan`；v1 只允许可信一对一 / 多对一 join。
4. Phase 8D 已完成：Pandas executor 受控 materialize join 后再执行聚合 / 排序 / 过滤；Verifier 能阻断无可信 join key、多对多风险、多表未 join 和命名维度退回 ID 的伪成功；trace / debug 记录 `join_execution_summary`。
5. Phase 8E 已完成：完整 mock / 离线门禁通过，输出文件为 `outputs/phase8_dev_1_10_mock_20260523/dev_1_to_10_report.json`、`outputs/phase8_dabstep_all_1_450_mock_20260523/all_1_to_450_report.json`、`outputs/phase8_microsoft_1_300_mock_20260523/report.json`、`outputs/phase8_vds_question_summary_95_mock_20260523.json`。
6. 真实 provider representative 已补跑 DeepSeek：`outputs/phase8_dabstep_dev_1_10_deepseek_real_20260523/dev_1_to_10_report.json` 为 `9/10`，`outputs/phase8_microsoft_1_20_deepseek_real_20260523/report.json` 为 `20/20`，`outputs/phase8_vds_question_summary_15_deepseek_real_after_candidate_fix_20260523.json` 为 `15/15`。
7. Phase 10 after-fix full real 已补跑 DeepSeek：DABstep public all、Microsoft 1-300 和 VDS 95 汇总文件为 `outputs/phase10_full_real_three_dataset_deepseek_20260523_summary_after_fix.json`。DABstep public all 仍只能验证执行覆盖和风险，不代表 hidden official accuracy。

### Phase 8 滚动 Goal 更新机制

每进入一个新 Phase 或 Phase 内子阶段，必须先更新 Goal，再开始实现；每完成一个阶段，必须回看当前验收结果，并更新后续 Goal。该规则持续到 Phase 8 核心算法闭环完成、Phase 9 前端产品化完成为止。

1. 阶段开始前：在 MAIN_GOAL.md 更新当前阶段 Goal，同时写清楚下一阶段 Goal，不允许只写当前任务；必须明确本阶段验收门槛、禁止事项和回归数据集。
2. 阶段实现中：每完成一个子目标，更新 CHANGELOG_AI.md；若影响用户可见能力或阶段状态，同步 README.md；若影响 API、trace、error、contract，同步对应 docs。
3. 阶段结束时：复跑阶段门禁，写清楚是否进入下一阶段；如果未通过，不进入下一阶段，只更新阻塞原因和修复 Goal。

### Phase 8A：多文件 Dataset 装配

当前 Goal：让一个 dataset 能表达多个文件、sheet 和 table，而不是把上传表隐式压成单一 primary table。状态：已完成。

下一阶段 Goal：Phase 8B 必须在 8A 的多文件 profile 基础上实现问题到表精准路由，禁止静默选择 `primary_table`。

实施重点：

1. 多文件 dataset 装配层支持一个 dataset 包含多个 `source_file` / `sheet` / `table_name`。
2. profile 保留字段画像、样例值、source_file、sheet 和 table_name；inline table 也支持同类 metadata。
3. 旧单文件上传和现有 `/api/data-agent/run` inline table 基线不得退化。

进入 Phase 8B 条件：

1. 多文件 profile 可审计。
2. 旧单文件上传、inline table 和现有 backend service 测试通过。
3. DABstep、微软脱敏数据和原本 VDS 最小回归不退步。

### Phase 8B：问题到表精准路由

当前 Goal：问题必须命中正确文件或表；当路由置信度不足时返回澄清，不能静默选最大表或 `primary_table`。状态：已完成。

下一阶段 Goal：Phase 8C 必须基于已选表和候选字段生成可审计 join plan，支持跨表问题。

实施重点：

1. 表路由器按文件名、表名、字段名、语义别名和样例值打分。
2. 支持显式文件名或表名表达，例如“库存文件里哪个产品库存量最高？”必须命中库存表。
3. 低置信度或多表同分时返回澄清候选，不输出看似成功但来自错误表的结果。

进入 Phase 8C 条件：

1. 销售 / 库存两表测试通过：“哪个产品销售额最高？”命中销售表；“哪个产品库存量最高？”命中库存表；显式“库存文件”命中库存表。
2. 旧单表 routing、中文 BI、DABstep、微软脱敏数据和原本 VDS 回归不退步。

### Phase 8C：多表关系发现与 Join Plan

当前 Goal：支持跨表问题，能从字段关系生成结构化 join plan，而不是只在 primary table 上寻找 metric 或 dimension。状态：已完成。

下一阶段 Goal：Phase 8D 必须让 Executor / Verifier / trace 真正执行并校验 join plan，避免错误退回 ID 聚合。

实施重点：

1. 基于同名字段、归一化字段名、唯一性和值重叠率推断 join key，例如 `客户ID`。
2. LogicForm / AnalysisPlan 增加 `source_tables`、`table_selection_reason` 和 `join_plan`。
3. v1 只允许可信的一对一 / 多对一 join；无可信 key 时返回澄清或标准错误。

进入 Phase 8D 条件：

1. 订单表 `(客户ID, 订单金额)` + 客户表 `(客户ID, 城市)` 测试通过。
2. “按城市统计订单金额”返回城市聚合，不返回客户 ID 聚合。
3. “哪个城市订单金额最高？”返回城市名，不返回客户 ID。

### Phase 8D：Executor / Verifier / Trace 闭环

当前 Goal：Executor 必须受控 materialize join 后再聚合或排序；Verifier 必须能发现 metric、dimension、filter 来自错误表或 join 不可信的情况。状态：已完成。

下一阶段 Goal：Phase 8E 必须用 DABstep、微软脱敏数据和原本 VDS 做完整非退步回归，并决定是否允许进入 Phase 9。

实施重点：

1. Pandas executor 先受控 materialize join，再执行 aggregation / ranking / filtering。
2. Verifier 校验 metric、dimension、filter 是否来自正确 source table，join key 是否可信，结果是否因为未 join 而退回 ID。
3. trace 记录 `table_selection_reason`、`join_summary`、unmatched keys、join confidence 和 many-to-many warning。

进入 Phase 8E 条件：

1. 无 join key 时返回澄清或标准错误，不伪造结果。
2. 多对多 join 输出 warning，默认不静默聚合。
3. 错误表、错误 join、错误字段来源必须进入 warnings / errors / verification，而不是自然语言掩盖。

### Phase 8E：三类基准完整回归

当前 Goal：确认 Phase 8 多文件和多表改造没有导致模型能力或泛化能力退步。状态：已完成。

下一阶段 Goal：只有 Phase 8E 完整通过后，才允许启动 Phase 9 前端产品化；如果未通过，必须写明阻塞原因和 Phase 8 修复 Goal。

完整门禁：

1. `VDS_LLM_PROVIDER=mock ... -m unittest discover` 通过。
2. DABstep dev 1-10 不低于当前 `9/10`。
3. DABstep public all 1-450 mock 保持 `success_count=450/450`、`unexpected_not_applicable=0`。
4. 微软脱敏数据 1-300 mock scorer 保持 `300/300`。
5. 原本 VDS `问题汇总.xlsx` 95 题 smoke 保持 `95/95`。
6. `format_risk`、`submission_risk`、`trace_redaction_risk` 不上升。
7. 有真实 OpenAI / DeepSeek key 时，补跑 representative / staged 回归；没有 key 时不得用 mock 冒充真实模型能力。

当前门禁结果：

1. Full unittest：`Ran 135 tests ... OK`。
2. Phase 8 focused / backend regression：`Ran 14 tests ... OK`，覆盖销售 / 库存精准路由、显式文件名命中、订单 + 客户城市 join、无 join key 澄清、多对多 warning 和旧单表回归。
3. DABstep dev 1-10：`correct=9/10`、`success_count=10`、risk taxonomy 关键风险为 0。
4. DABstep public all 1-450 mock：`success_count=450/450`、`unexpected_not_applicable=0`、risk taxonomy 关键风险为 0。
5. Microsoft 脱敏数据 1-300 mock scorer：`correct=300/300`。
6. 原本 VDS `问题汇总.xlsx` 95 题 smoke：`success_count=95/95`。
7. 真实 DeepSeek representative 回归已执行：DABstep dev 1-10 `9/10`，Microsoft 1-20 `20/20`，原本 VDS 五域 15 题 `15/15`。
8. Phase 10 after-fix full real 已完成：DABstep public all `success_count=450/450`，Microsoft 1-300 `correct=300/300`，原本 VDS 95 smoke `success_count=95/95`；汇总文件为 `outputs/phase10_full_real_three_dataset_deepseek_20260523_summary_after_fix.json`。

## Phase 10：Visualization / Insight / Quality / Safe Process View

当前 Goal：把结果可视化、洞察建议、数据质量扫描和安全过程可视化做成后端稳定契约，并在前端只展示用户可理解的结果与过程。状态：已完成首版，当前前端主界面已收敛为 GPT-like PC 体验。

已交付：

1. 后端生成 `chart`、`insight`、`quality_report` 和 `reasoning_trace_view` 稳定字段。
2. `chart` 自动选择 bar / horizontal_bar / line / pie / donut / histogram / KPI；选择逻辑在 `data_agent_core/output/chart_planner.py`，前端只渲染契约。
3. `insight` 只基于 verified result、质量报告和可解释统计生成摘要、异常、波动和建议，不臆造业务结论。
4. `quality_report` 扫描缺失、重复、类型、日期、离群、负值和 key 风险；只作为后端/API 审计字段，不在主界面直接展示，不自动修改原始数据。
5. `reasoning_trace_view` 展示结构化阶段摘要、意图识别、执行和校验结果；前端将其转译为用户可读过程，不暴露完整 Chain of Thought、raw prompt、API key 或隐藏 benchmark 答案。
6. 上传表质量报告已缓存到 dataset profile，避免 Microsoft / VDS 这类多题回归中每题重复扫描。

验收结果：

1. Full unittest：`Ran 147 tests ... OK`。
2. compileall：`data_agent_core agent_runtime multi_agent_workflows backend tests` 通过。
3. 前端语法：`node --check frontend/app.js` 通过。
4. `git diff --check` 通过。
5. DABstep dev 1-10 mock：`correct=9/10`，关键风险为 0。
6. DABstep public all 1-450 mock：`success_count=450/450`，`unexpected_not_applicable=0`，关键风险为 0。
7. Microsoft 脱敏数据 1-300 mock scorer：`correct=300/300`。
8. 原本 VDS `问题汇总.xlsx` 95 题 smoke：`success_count=95/95`，`output_contract_failure_count=0`。
9. 真实 DeepSeek representative：DABstep dev 1-10 `9/10`，Microsoft 1-20 `20/20`，原本 VDS 五域 15 题 `15/15`，关键风险为 0。
10. 真实 DeepSeek full：DABstep public all `450/450` 执行覆盖、Microsoft `300/300`、原本 VDS 95 smoke `95/95`；`format_risk / semantic_risk / submission_risk / trace_redaction_risk` 均为 0。DABstep public all 本地无 expected answer，accuracy 仍为 `null`，不代表 hidden official accuracy。

禁止事项：

1. Phase 10 不自动清洗、覆盖或保存用户原始数据。
2. 前端不实现图表选择、异常规则、指标公式、join、排序、聚合或数据清洗。
3. 过程可视化不能展示 raw CoT、raw reasoning tokens、raw prompt、API key、benchmark hidden answer，也不在主界面直接展示后端审计 JSON、warnings/errors、verification 细节或 join trace。
4. 不得把 DABstep public all full real 执行覆盖冒充 hidden official accuracy；public all 本地没有 expected answer，只能验证执行覆盖、风险门禁和 trace。

## Phase 11：Conversation Isolation / Session Persistence

当前 Goal：把 Workbench 从单页内存状态升级为可恢复的对话式数据分析体验。状态：Planned / Not implemented yet；本节只记录后续实现计划和边界，不代表功能已经落地。

目标：

1. 新增 `conversation_id` 作为 Workbench 的会话连续性主键，每个会话独立保存消息、当前数据集、运行摘要和最近结果。
2. 多窗口默认创建独立会话；如果 URL 显式带同一个 `conversation_id`，则进入同一条历史会话。
3. 左侧历史 Chat 从后端会话列表恢复，不再只依赖浏览器内存中的 run history。
4. 用户可以随时从历史 Chat 回到旧会话，继续上传、提问和分析。
5. 预留 `owner_id`、`tenant_id`、`owner_context`、`created_by` 等字段，为未来真实登录、多用户隔离和租户隔离升级做准备。
6. 过程展示已先行采用 GPT-like 安静形态：默认只显示一条小号浅灰的最新过程摘要，用户点击后再展开结构化步骤详情；Phase 11 后续只把它接入可恢复会话。

计划中的后端会话结构：

1. `conversation_id`
2. `title`
3. `active_dataset_id`
4. `messages`
5. `runs`
6. `created_at` / `updated_at`
7. `owner_type` / `owner_id` / `tenant_id` / `created_by`

计划中的前端行为：

1. 当前会话 URL 使用 `/workbench?conversation_id=...`。
2. 新建聊天时创建新的 `conversation_id` 并更新 URL。
3. 打开历史会话时恢复消息、当前数据集、最近分析结果和可继续提问状态。
4. 不同 `conversation_id` 的窗口互不影响；同一 `conversation_id` 的窗口显示同一会话，并在发送后刷新最新状态。
5. 过程摘要文案必须面向用户，例如“用户提到了‘城市订单金额’，我会先确认城市字段和金额字段。”，不能把后端 `join_plan`、`verification`、`quality_report`、warnings 或 raw trace JSON 直接放到主界面。

禁止事项：

1. 不展示完整 Chain of Thought、raw reasoning tokens、raw prompt、API key 或 hidden benchmark answer。
2. 不把数据质量、warnings、join verification、join trace 等后端审计术语放到主界面抢占空间。
3. 不让前端实现 join、聚合、排序、评分、图表选择或核心数据分析逻辑。
4. 不把 v1 本地匿名会话隔离写成已实现的真实登录、鉴权、多租户或企业级权限系统。

验收标准：

1. 文档能清楚区分 Phase 11 planned 与已实现能力。
2. 后续实现时，两个不同窗口的 dataset、消息和分析结果不能串线。
3. 回到历史会话后，用户能看到旧消息和最近结果，并能继续提问。
4. `reasoning_trace_view` 只作为安全过程摘要来源；前端默认只显示一条低占用过程摘要，点击后才展开详情。
5. API、存储和前端状态都为未来 `owner_context` 过滤预留边界。

## Phase 9：前端产品化

Phase 9 是 Phase 8 完成后的正式新阶段。Phase 9 的 Goal 是把已冻结的多文件、多表、澄清和结果契约做成前端产品体验，而不是在前端实现核心分析逻辑。2026-05-23 当前状态：首版静态 workbench 已完成并通过桌面 / 移动浏览器 smoke。

Phase 9 启动条件：

1. Phase 8A-8E 已完成并通过完整门禁。
2. API_CONTRACT 已冻结多文件、多表、selected tables、join summary、warnings、errors 和 verification 的稳定字段。
3. README.md、MAIN_GOAL.md、CHANGELOG_AI.md 已同步 Phase 8 完成状态和 Phase 9 当前 Goal。

Phase 9 范围：

1. 多文件上传 UI。
2. 文件 / sheet / table 预览。
3. 字段识别和 join key 确认。
4. 低置信度表选择和 join key 澄清交互。
5. 表格、图表、解释和用户可读过程展示；warnings、errors、verification、join trace 作为后端/API 审计字段保留，不在主界面直接展示。
6. 评测与回看面板。

当前已交付：

1. `frontend/index.html`、`frontend/styles.css`、`frontend/app.js`、`frontend/README.md` 提供首版静态 workbench。
2. `backend/main.py` 在存在 `frontend/` 目录时挂载 `/frontend` 静态资源，并提供 `/workbench`。
3. 前端支持单文件 / 多文件上传，单文件调用 `/api/data-agent/upload`，多文件调用 `/api/data-agent/upload-batch`，所有用户消息统一调用 `/api/data-agent/message`。
4. 前端支持问题提交、结果表格、自动图表、insight 摘要、用户可读安静过程和本地 run history；verification、warnings、errors、join plan trace、join execution summary 和 quality_report 保留在后端/API。
5. 前端 smoke 使用 mocked API route 验证桌面和移动视口无 console / page error，截图保存在 `outputs/phase9_workbench_desktop_20260523.png` 和 `outputs/phase9_workbench_mobile_20260523.png`。

Phase 9 禁止：

1. 在前端实现指标公式。
2. 在前端实现 join。
3. 在前端做数据分析计算。
4. 依赖 debug 字段作为稳定契约。
5. 绕过 `data_agent_core`、Verifier 或 backend API。

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

3. POST /api/data-agent/message

用于 Workbench 统一提交用户消息，由后端判断普通聊天、数据概览或正式分析。

4. POST /api/data-agent/chat

用于没有上传 dataset 时的 VDS 普通对话，只讨论分析思路、指标口径和字段设计；需要真实业务结论时必须上传数据。

5. GET /api/data-agent/datasets/{dataset_id}/profile

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
