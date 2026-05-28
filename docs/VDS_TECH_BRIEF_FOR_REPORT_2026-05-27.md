# VDS 技术汇报速览：技术问答版

生成时间：2026-05-27

代码基线：`/Users/trevorcui/Documents/VDS`，当前分支 `dev`

说明：本文面向懂技术的老板或技术评审，目标不是介绍页面功能，而是让汇报人能解释清楚架构选择、边界、验证方式和当前风险。当前 worktree 仍有未提交前端 / eval / test 改动，所以本文只按当前仓库代码阅读整理，不声称未提交改动已经发布。

## 1. 汇报主线

VDS 当前不是一个“把文件丢给大模型让它猜”的聊天机器人，而是一个 dataset-grounded data analysis agent：

- 文件解析、表画像、数据质量扫描、Pandas / SQL 执行、结果归一化、校验、响应契约都由后端 deterministic code 控制。
- LLM 主要用于 intent / semantic mapping / planning / critique / correction direction / explanation / chart semantics。
- Provider 原生 tool call 不是执行入口；无论 OpenAI / DeepSeek 怎么接，真实工具执行都要映射到内部 `ToolCall` 并经过 `ToolDispatcher`。
- 前端 Workbench 只做上传、提问、渲染和活动展示，不承担计算、join、图表语义判断、benchmark 评分或清洗决策。

对外一句话：

> VDS 的核心价值是把 LLM 的语义理解能力和后端可控的数据执行链路拆开：模型负责理解和组织，系统负责计算、校验、审计和稳定输出。

## 2. 当前架构一图看懂

```text
/workbench
  -> frontend/app.js
      上传、提问、会话、结果渲染
  -> backend/routers/data_agent.py
      API 薄路由
  -> backend/services/data_agent_service.py
      路由普通 chat / 数据概览 / 清洗建议 / 完整分析
  -> data_agent_core/core/file_parser.py
      CSV / Excel / JSON / Parquet 解析，生成 tables + profile + quality report
  -> multi_agent_workflows/end_to_end_data_analysis_workflow.py
      Planner -> Data Engineer -> Pandas -> SQL -> Verifier -> Correction -> Insight -> Visualization -> Response
  -> agent_runtime/tool_dispatcher.py
      工具白名单、角色权限、schema 校验、timeout、trace-safe summary
  -> data_agent_core/output/*
      answer / result / verification / insight / chart / process / activity / artifact 契约
```

如果被问“核心代码在哪里”，可以直接指：

- 主编排：`backend/services/data_agent_service.py`
- 多 Agent workflow：`multi_agent_workflows/end_to_end_data_analysis_workflow.py`
- 工具层：`agent_runtime/data_agent_tool_catalog.py`、`agent_runtime/tool_dispatcher.py`
- 核心算法：`data_agent_core/`
- Prompt 控制点：`data_agent_core/prompts/data_agent_system_prompt.md`，由 `data_agent_core/llm/planner.py` 读取。
- 前端入口：`frontend/app.js`，静态 Workbench，不是 Next / Vite。

## 3. 关键技术决策和取舍

### 3.1 为什么不是直接让 LLM 写 Python

直接让模型写代码的问题是不可控：容易读错字段、跑错口径、泄漏 prompt、产生不可审计逻辑，也不方便做 regression。

VDS 的设计是：模型输出结构化意图和计划，执行器只接受受控 plan。Pandas / SQL 代码路径在后端实现，结果再经过 Verifier。这样牺牲了一点自由度，但换来可测试、可回归、可定位。

### 3.2 为什么要多 Agent，而不是一个大 prompt

多 Agent 在这里不是营销概念，实际作用是分离责任：

- Planner 负责语义和计划，不负责最终结论。
- Executor 负责执行，不决定业务解释。
- Verifier 负责阻断不可信结果。
- Correction 只做有边界修正，不随意改答案。
- Insight / Visualization 只能基于已验证结果输出。

这样出了问题能定位是选表问题、字段映射问题、执行问题、校验问题，还是表达问题。一个大 prompt 很难做到这种故障隔离。

### 3.3 为什么需要 ToolDispatcher

`ToolDispatcher` 是安全和治理边界。它做：

- 工具必须注册在 `data_agent_tool_catalog`。
- 每个工具有 `allowed_roles`，例如 `build_chart_spec` 只能由 Visualization 调。
- 参数按 schema 校验，不接受随意 JSON。
- 工具有 timeout。
- 工具约束禁止网络、shell、外部文件、raw Python、raw SQL、benchmark answer access。

所以即使将来接 provider-native tool calling，provider 也只是产生一个“请求调用工具”的消息，真实执行仍由内部 dispatcher 控制。

### 3.4 为什么前端不能算

前端算指标、join 或图表语义会导致三类问题：

- 同一问题在 API、benchmark、Workbench 上结果不一致。
- 前端逻辑无法复用 Verifier / Correction。
- 很难证明没有 benchmark patch 或展示层伪泛化。

当前前端只消费 `FinalResponse` 里的稳定字段：`answer`、`result`、`verification`、`insight`、`chart`、`process_view_v2`、`activity_trace_v2`、`execution_artifacts`。

## 4. 重点技术点

### 4.1 文件解析和多文件语义

实现：`data_agent_core/core/file_parser.py`

当前文件进入后会变成：

- `tables`：一个 dataset 下的多张 DataFrame。
- `DatasetProfile`：表名、字段、类型、样例、质量信息。
- `table_metadata`：`source_file`、`sheet`、`table_name`。

这点很重要：多文件不是简单合成一个 file list，而是带 source metadata 的 table set。后续选表、来源解释和 join 都依赖这个 metadata。

边界要讲清楚：当前能做表识别、来源概览、部分多表分析；复杂 join 仍依赖字段匹配、join plan 和 Verifier，不应承诺“所有业务 join 自动正确”。

### 4.2 分析正确性怎么保证

主要靠四层：

1. 计划层：LogicForm / AnalysisPlan 把问题转成结构化口径。
2. 执行层：Pandas 是主执行路径，SQL / DuckDB 在可支持时做复算或交叉核对。
3. 校验层：Verifier 检查执行成功、Pandas/SQL 一致性和语义问题。
4. 输出层：`output_contract` 和 `response_builder` 保证最终回答符合契约，不把 raw detail 或不可信结果直接吐给用户。

这不是数学证明，但比单 prompt 直接回答更可审计、更能回归。

### 4.3 图表怎么做

实现：

- `data_agent_core/output/chart_planner.py`
- `data_agent_core/output/chart_renderer.py`
- `frontend/app.js`

后端先生成前端中立 `ChartSpec`：`chart_type`、`x`、`y`、`data`、`encoding`、`series`、`reason`。选择规则偏保守：

- 校验失败不画图。
- 明细结果优先表格。
- ID / reference / bin / year / hour / minute / day_of_year 这类字段不当作指标。
- 趋势用 line，长排名用 horizontal bar，占比用 pie / donut。

后端还可以把 ChartSpec 渲染成 SVG data URI：`image_data_uri = data:image/svg+xml;base64,...`。Workbench 有足够 chart rows / encoding 时优先渲染交互 SVG；数据不够时 fallback 到后端图片。图表语义不在前端决定。

### 4.4 所谓“节点可视化”应怎么讲

不要把它当卖点。更准确的说法是 observability / audit view：

- `activity_trace_v2`：让研发和用户看到 Planner、Pandas、SQL、Verifier 等安全摘要。
- `process_view_v2`：给主页面一个不泄漏 CoT 的过程说明。
- `execution_artifacts`：展示安全复现口径，帮助解释“这个数怎么算的”。

价值不是“节点好看”，而是出问题时能回答：用了哪个表、走了哪个 executor、SQL 是否跳过、Verifier 有没有通过、是否生成了安全复现代码。

### 4.5 评测口径

不要只报 smoke 数字。当前应该按三类看：

- 单元/架构测试：工具契约、chart renderer、activity trace、process view、安全红线。
- GPT-like gate：看用户可见回答是否接近 ChatGPT Data Analysis 的结构和质量。
- comparison scoring：正式 benchmark 结论优先看 `comparison.*`、`comparison_scored.*` 和 `scripts/score_comparison_answers.py`。

如果数字异常，先区分：

- smoke coverage：流程有没有跑通。
- proxy / accepted-answer observation：是否只是公共代理或答案观察。
- offline scorer correctness：离线评分是否真的可代表正确性。

## 5. 技术老板可能反问的问题

### Q1：这和 ChatGPT Data Analysis / Code Interpreter 有什么区别？

答法：ChatGPT Data Analysis 是通用交互式分析能力；VDS 是把类似体验工程化到我们自己的数据、契约、评测和安全边界里。我们控制文件解析、字段画像、执行器、Verifier、结果契约、trace 和前端渲染，因此能做可回归、可审计、可集成的企业侧能力。

### Q2：为什么不用 LangChain / PandasAI 直接搭？

答法：可以借鉴编排思想，但不能把核心 correctness 交给框架黑箱。VDS 当前更重视内部契约：LogicForm、ToolDispatcher、Verifier、output contract、comparison scoring。外部框架可作为 adapter，但不应该替代核心算法和安全边界。

### Q3：多 Agent 是不是只是把一个流程拆成多个名字？

答法：不是。它对应可测试边界：Planner 输出计划，Executor 输出结果，Verifier 决定能否进入回答，Correction 只在有明确问题时修正并重跑。每一层都有不同输入输出和失败定位价值。

### Q4：怎么证明答案对？

答法：短期靠结构化执行 + 双路径复核 + Verifier + benchmark / GPT-like gate；长期要扩充同族问题、真实业务数据、comparison scored artifacts。不能只说“没有 task_id 泄漏”，也不能用一个 benchmark 分数证明泛化。

### Q5：如果 Pandas 和 SQL 算出来不一致怎么办？

答法：Verifier 会把一致性作为信号；不可信结果不能直接进入最终回答。Correction 可以生成有边界的修正并触发一次重跑；不能修正时应返回可解释错误或能力边界，而不是强答。

### Q6：多文件 join 能力现在强到什么程度？

答法：当前基础是多文件 metadata、表画像、表选择和部分 join plan。能处理部分有清晰 key 和语义关系的问题，但复杂业务 join 仍是风险区，需要字段语义、候选 key、join cardinality、缺失/重复 key 和结果验证共同判断。

### Q7：会不会被 prompt injection 或用户规则文件影响？

答法：用户文件可以作为数据或规则上下文，但不应获得执行权。工具层禁止 shell、网络、外部文件、raw Python / SQL；benchmark 规则和普通 chat 主路径也要隔离。后续还要继续强化规则文件绑定和权限边界。

### Q8：图表选错怎么办？

答法：图表选择有后端规则防线，优先避免把 ID / 时间桶当指标；明细结果宁可展示表格也不强行可视化。图表错误不会改变计算结果，但会影响 GPT-like 用户体验，所以需要在 evaluation gate 里单独验。

### Q9：为什么要保留 process / activity trace？

答法：不是为了展示“思考过程”，而是为了可审计和 debug。它回答的是工程问题：哪个节点失败、调用了哪个工具、SQL 为什么跳过、Verifier 是否通过、代码 artifact 是否生成。展示层必须脱敏，不能泄漏 raw CoT。

### Q10：性能和规模怎么办？

答法：当前重点是 correctness 和可控执行。执行层已经有 Pandas / SQL / DuckDB 方向；后续规模化要看数据大小、并发、缓存、异步队列、文件存储和执行隔离。现在不能把 demo 级响应时间包装成生产级 SLA。

### Q11：接 DeepSeek / OpenAI 会改变核心逻辑吗？

答法：不应改变。Provider 差异限制在 LLM transport / provider adapter；内部 `ToolDefinition`、`ToolCall`、`ToolResult`、`ToolDispatcher`、Verifier 和 output contract 不随 provider 改变。

### Q12：当前最大技术风险是什么？

答法：泛化稳定性。尤其是字段语义、多表 join、复杂业务指标、图表语义、中文真实业务问法和 GPT-like 表达质量。下一阶段不能靠题面特调，要按可复用能力族推进，并用同族回归证明没有伤害旧能力。

## 6. 建议汇报结构

3 分钟版本：

1. 我们做的是 dataset-grounded data analysis agent，不是纯聊天。
2. 架构上把 LLM semantic reasoning 和 deterministic execution 分开。
3. ToolDispatcher / Verifier / output contract 是核心安全和正确性边界。
4. Workbench 的图表、洞察、过程和代码 artifact 都来自后端稳定契约。
5. 当前风险在泛化：多文件 join、复杂指标、真实业务数据、GPT-like 体验，需要持续 comparison scoring 和回归。

10 分钟版本：

1. 先讲主链路：上传 -> profile -> plan -> execute -> verify -> insight/chart -> response。
2. 再讲为什么这样设计：可控、可测、可回归、可审计。
3. 讲两三个技术亮点：ToolDispatcher、Verifier/Correction、ChartSpec/output contract。
4. 主动讲边界：不是所有 join 自动完美，不开放自由代码，不拿 benchmark patch 当能力。
5. 最后讲下一步：真实数据回归、业务指标语义、join correctness、provider-native tool smoke、GPT-like parity。

## 7. 不建议汇报时强调的点

- 不要把“节点可视化”当核心卖点，它只是 observability。
- 不要说已经无限接近 GPT，只能说以 GPT-like parity 作为验收标准，并持续用 comparison artifacts 验证。
- 不要说多文件 join 已经完全解决，应说基础链路存在，复杂 join 是下一阶段重点。
- 不要报单一 benchmark 分数当结论，要说明 scorer、数据集、运行模式和失败家族。
- 不要说 provider-native tool calling 是生产默认链路；当前安全口径是 provider call 映射到内部 dispatcher。
