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
8. 搭建 multi_agent_workflows 多 Agent 工作流预留目录
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
4. 已支持 DABstep dev 前 10 题本地评测，当前验证结果为 8/10，准确率 80%。
5. all.jsonl 可生成前 10 题预测文件，但本地 all.jsonl 的 answer 字段为空，因此不能本地计算准确率。
6. 该实现不使用 task_id、标准答案或单题硬编码进入分析链路。
7. 已新增 LLM 单 Agent 链路，Intent Parser、Column Mapping、Analysis Planner、Verifier / Critic、Correction Planner、Insight Generator 和 Chart Planner 均预留 LLM 参与；确定性代码负责文件/规则读取、执行、结果标准化、规则校验和评分。
8. LLM key 只能通过环境变量提供，禁止写入仓库、文档、trace 或 CHANGELOG。
9. 已进入 Phase 1 / Phase 2 / Phase 3 最小可测状态：支持上传 CSV / Excel 文件解析入口、DatasetProfile、UploadedDatasetAgent、最小 backend service upload/profile/analyze、Benchmark metrics 和 error_analysis 聚合。
10. 当前最小后端 API 仍是调用壳，核心 Pandas / SQL / Verifier / Insight / Chart 逻辑仍在 data_agent_core。
11. public all.jsonl 的 answer 字段为空，不能本地计算完整 450 题官方准确率；dev 前 10 题仍用于本地可复现 smoke benchmark。
12. Tool Calling 暂定为 Phase 5 后置能力；当前只保留 ToolRegistry / tool mapping 骨架，不在当前阶段启用模型原生工具循环或 thinking-mode 工具回填。
13. 已补充 Phase 5 受控 Tool Calling 的 provider-neutral 契约骨架：ToolDefinition、ToolCall、ToolResult、ToolTraceEvent、ToolDispatcher、Data Agent tool catalog 和 Microsoft adapter tool mapping；当前仍不启用 provider 原生工具循环。

## 架构原则

1. 核心算法必须放在 data_agent_core/ 中
2. 后端 backend/ 只作为调用壳，不承载核心数据分析逻辑
3. 前端只负责上传、提问和展示，不参与数据处理
4. Agent Framework 只能作为后续 workflow 编排层，不允许污染核心算法
5. Benchmark 只能用于评估、错误归因和回归测试，不允许针对单题硬编码
6. 先做单 Agent，再考虑多 Agent
7. 先保证核心算法稳定，再扩展外围工程
8. 所有模块必须可测试、可复现、可回归
9. 核心算法不依赖 Microsoft Agent Framework
10. Microsoft Agent Framework 适配层可以调用核心算法
11. 多 Agent 角色必须通过统一输入输出协议交互
12. 后续替换 Agent 框架时，不应重写核心算法
13. 所有核心模块必须基于 contracts 中的稳定契约交互
14. 所有 analyze 请求未来必须生成 run_id
15. 所有 API 响应未来必须包含 response_version
16. 所有错误必须进入 errors 字段
17. 所有警告必须进入 warnings 字段
18. 工程文档中不要求模型输出完整 Chain of Thought，只保留 structured analysis plan、reasoning summary、execution trace、verification notes
19. Agent 必须包含 LLM 单 Agent 链路；LLM 负责意图理解、字段语义映射、分析计划、校验辅助、修正方向、解释和图表语义规划，本地执行器负责确定性计算和校验
20. LLM API key 必须从环境变量读取，不允许提交到 Git
21. LLM 不能绕过代码执行器、Result Normalizer、Verifier 或 Correction Planner 直接输出最终结论
22. DABstep / Benchmark 的 task_id 和标准答案不能进入 LLM 输入或核心分析链路
23. Tool Calling 只能调用内部白名单工具，工具定义必须有稳定名称、JSON schema、参数校验、超时和结果摘要策略
24. Tool Calling 的工具实现仍然属于 data_agent_core 或 agent_runtime 的受控代码路径，不能把核心算法写进 provider adapter、Microsoft adapter 或多 Agent workflow
25. 模型可以选择工具和填写参数，但不能获得 raw Python、raw SQL、shell、网络访问或任意文件访问能力
26. 工具调用 trace 只能记录工具名、参数摘要、结果摘要、错误和耗时，不记录完整 Chain of Thought、raw reasoning tokens、API key 或敏感数据
27. OpenAI / DeepSeek / Microsoft Agent Framework 只能作为工具调用协议适配层；内部工具契约必须保持 provider-neutral

## Microsoft Agent Framework 策略

Microsoft Agent Framework 是后续多 Agent 编排的候选框架，但不是当前核心算法依赖。

当前阶段只做：

1. 创建 ms_agent_framework_adapter/ 目录
2. 创建适配层 README
3. 创建空的 adapter 文件
4. 在文档中说明未来如何把 Planner、Executor、Verifier、Insight、Visualization 等角色映射到 Microsoft Agent Framework workflow
5. 不安装框架包
6. 不实现复杂 workflow
7. 不把核心逻辑写入 adapter

未来迁移方式：

1. data_agent_core 提供稳定函数和类
2. agent_runtime 定义 AgentRole、AgentTask、AgentResult、WorkflowState
3. ms_agent_framework_adapter 将内部 AgentTask 映射为 Microsoft Agent Framework 的 agent / tool / workflow step
4. multi_agent_workflows 负责组合 Planner、Executor、Verifier 等角色
5. backend 仍然只调用统一服务入口，不直接依赖具体 Agent 框架

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
12. 针对 Benchmark 单题特判
13. 一上来做复杂多 Agent 编排
14. 在本轮引入 Microsoft Agent Framework 作为强依赖
15. 在本轮实现复杂 Agent workflow
16. 在本轮实现完整业务逻辑
17. 在本轮实现 provider 原生 Tool Calling、DeepSeek thinking mode 工具回填或 OpenAI Responses API 工具循环

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

## 未来多 Agent 工作流

Phase 6+ 多 Agent 目标结构：

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

## 最小 API 目标

当前后端至少需要支持：

1. POST /api/data-agent/upload

用于接收 CSV / Excel 文件，返回 dataset_id 和字段画像。

2. POST /api/data-agent/analyze

用于接收 dataset_id 和用户问题，返回分析结果、校验信息、解释建议和图表配置。

3. GET /api/data-agent/datasets/{dataset_id}/profile

用于返回指定数据集的文件信息、字段画像和状态。

## 重要红线

1. 不允许直接在 main 分支开发
2. 不允许修改旧系统主流程，除非任务明确要求
3. 不允许把核心算法写进 backend/router
4. 不允许把 Benchmark 题目写成硬编码规则
5. 不允许绕过 Verifier 直接输出最终结论
6. 不允许一次任务混合多个无关目标
7. 每次修改前必须读取 MAIN_GOAL.md、CHANGELOG_AI.md、BRANCH_RULES.md
8. 每次修改后必须更新 CHANGELOG_AI.md
9. 不允许核心算法依赖 Microsoft Agent Framework
10. 不允许在适配层中实现核心业务逻辑
11. 不允许每个模块随意返回不同结构的 dict
12. 不允许没有 run_id 的 analyze 链路
13. 不允许没有错误类型的失败结果
14. 不允许没有 trace 的分析链路设计
15. 不允许工程文档要求输出完整 Chain of Thought
16. CHANGELOG_AI.md 新增记录必须写日期时间，格式为 YYYY-MM-DD HH:MM TZ，精确到分钟
17. 不允许为了补齐格式而给历史 CHANGELOG 记录编造分钟级时间
