# ARCHITECTURE

## 当前阶段

当前只定义 Data Agent 的工程边界和扩展方向，不实现复杂业务逻辑。

2026-05-21 更新：当前已新增核心算法 MVP，可在本地直接运行 DABstep 风格数据分析任务。该 MVP 仍保持框架无关，不依赖 Microsoft Agent Framework。

2026-05-21 更新：当前已新增 LLM 单 Agent 链路。Intent Parser、Column Mapping、Analysis Planner、Verifier / Critic、Correction Planner、Insight Generator、Chart Planner 都显式经过 LLM 阶段；代码路径负责 Pandas / SQL 执行、Result Normalizer、规则校验和 Benchmark 评分。

## 层次边界

1. data_agent_core 是核心算法层。
2. backend 是调用壳，只负责接收请求、临时文件管理、调用核心层和返回结构化 JSON。
3. agent_runtime 是项目内部 Agent 抽象层。
4. ms_agent_framework_adapter 是未来 Microsoft Agent Framework 适配层。
5. multi_agent_workflows 是未来多 Agent 编排目录。
6. docs 是工程契约和扩展需求管理目录。

## 依赖规则

1. data_agent_core 不依赖 backend。
2. data_agent_core 不依赖 ms_agent_framework_adapter。
3. data_agent_core 不依赖 multi_agent_workflows。
4. data_agent_core 不依赖 Microsoft Agent Framework。
5. 核心算法保持框架无关。
6. Microsoft Agent Framework 适配层可以调用 agent_runtime 和 data_agent_core，但不能承载核心算法。
7. multi_agent_workflows 可以组合 agent_runtime 角色，但不能把核心算法写进 workflow。
8. LLM client 位于 data_agent_core/llm，不依赖 Microsoft Agent Framework。
9. prompt 位于 data_agent_core/prompts/data_agent_system_prompt.md。
10. API key 只从环境变量读取，不进入 Git、trace、文档或 CHANGELOG。

## 核心链路

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

## 单 Agent 职责分工

1. LLM Intent Parser：根据用户问题和 guidelines 输出结构化意图摘要。
2. LLM + 规则 Column Mapping：结合字段语义和代码规则，把指标、维度、过滤条件映射到上传表字段或规则知识库字段。
3. LLM Analysis Planner：生成可序列化 LogicForm 草案。
4. 代码 Pandas Executor：只执行 AnalysisPlan，不重新理解用户问题。
5. 代码 SQL / DuckDB Executor：提供第二条执行路径，当前本地缺少 DuckDB 时使用 sqlite fallback。
6. 代码 Result Normalizer：标准化 Pandas 和 SQL 结果，供比较和 trace 使用。
7. 规则 + LLM Verifier / Critic：规则先判定执行成功、一致性和空结果，LLM 只做辅助审查。
8. 规则 + LLM Correction Planner：最多预留两次修正方向，不能绕过 Verifier 输出结论。
9. LLM Insight Generator：只在结果可信后生成解释和建议。
10. LLM + 规则 Chart Planner：规则先约束图表类型，LLM 辅助选择展示语义。

## 未来多 Agent 映射

1. Planner Agent：LLM 为主。
2. Data Engineer Agent：代码为主，LLM 辅助字段语义。
3. Pandas Executor Agent：代码为主。
4. SQL Executor Agent：代码为主。
5. Verifier Agent：规则为主，LLM 辅助。
6. Correction Agent：LLM 生成修正方向，代码执行。
7. Insight Agent：LLM 为主。
8. Visualization Agent：规则 + LLM。
9. Benchmark Agent：代码为主，LLM 辅助错误归因。

这些角色后续由 agent_runtime 表达，Microsoft Agent Framework adapter 只负责把角色映射到 workflow，不承载核心算法。

## DABstep 本地测试链路

当前 DABstep 测试按以下边界处理：

1. payments.csv 是业务数据库表。
2. manual.md 是业务规则文档。
3. fees.json 是结构化费用规则知识库。
4. merchant_data.json 是商户元数据知识库。
5. all.jsonl / dev.jsonl 中的问题只提供 question 和 guidelines 给核心分析链路。
6. answer 字段只允许在 benchmark evaluator 中用于评分，不允许进入 intent parser、executor、verifier 或 response builder。
7. 运行 trace 记录 structured analysis plan、execution trace 和 verification notes，不记录完整 Chain of Thought。

## TODO

- 定义 Phase 1 最小服务入口。
- 实现架构边界测试。
- 在不引入框架依赖的前提下验证核心模块可导入。
