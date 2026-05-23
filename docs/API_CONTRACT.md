# API CONTRACT

## 当前阶段

当前已实现最小 API 调用壳和稳定响应契约，尚未实现复杂后端业务系统。

2026-05-21 更新：核心算法 MVP 已能返回 FinalResponse dataclass。后端 API 已有最小 upload / analyze / profile 调用壳，response schema 与 FinalResponse 对齐；复杂部署、权限、持久化和任务队列仍不在当前范围。

2026-05-21 更新：Agent 已新增 LLM 单 Agent 链路。API 响应的 debug 可包含 llm_used、llm_operation、llm_confidence、single_agent_chain、llm_stage_summaries 等调试字段，但前端不能依赖 debug 字段作为稳定契约。

2026-05-21 更新：Phase 1 最小后端调用壳已落地。backend 通过 DataAgentService 调用 data_agent_core，支持上传 CSV / Excel 后返回 DatasetProfile、按 dataset_id 分析问题、获取 profile。router 仍只做请求转发，不包含 Pandas / SQL / Verifier 核心逻辑。

2026-05-21 更新：Phase 5 工具调用 trace 契约已落地。API 稳定字段不变；debug 可包含 tool_call_summaries，但前端仍不能依赖 debug。

2026-05-21 更新：内部工具 callable 和 Microsoft Agent Framework adapter 已开始实现。该变化不修改 upload/analyze/profile 的稳定 API 字段；如果 adapter 参与运行，只能把工具调用摘要放入 debug / trace，不允许新增前端必须依赖的字段。

2026-05-21 更新：analyze 默认切换为 multi_agent。请求可选 agent_mode，支持 multi_agent / single_agent；该字段用于内部运行模式选择，不改变稳定响应字段。默认 multi_agent 不要求安装 Microsoft Agent Framework，不引入前端强依赖字段。

2026-05-21 更新：`Not Applicable` 不再只作为普通字符串处理。analyze 的 debug / trace / benchmark report 可记录 not_applicable_attribution，用于区分 `true_unsupported` 和 `capability_gap`；如果属于 `capability_gap`，errors 必须包含 `CAPABILITY_GAP`，前端仍只依赖稳定的 answer、warnings、errors、verification 字段。

2026-05-22 更新：Phase 1 Backend API Shell 新增 `POST /api/data-agent/run` 外部一次性调用入口。该接口把调用方传入的 JSON 表格转成临时 dataset，然后复用现有 analyze / multi_agent 链路；它不是新的核心算法 Phase，不属于 Phase 5 Tool Calling，也不属于 Phase 7 Provider 原生 tool loop。

2026-05-23 更新：Phase 8 多文件 / 多表核心算法闭环已落地。新增 `POST /api/data-agent/upload-batch`；DatasetProfile / TableProfile 稳定保留 `source_file`、`sheet`、`table_name`；`logic_form`、analysis plan、debug 和 trace 可包含 `source_tables`、`table_selection_reason`、`join_plan`、`join_execution_summary`。无可信 join key、多对多风险、多表未 join 或 named dimension 退回 ID 聚合必须进入 verification / warnings / errors / correction_action，不允许伪成功。

2026-05-23 更新：Phase 9 首版前端 workbench 已落地。`backend/main.py` 在存在 `frontend/` 目录时挂载 `/frontend` 静态资源并提供 `/workbench`；该页面只消费稳定后端 API 和 trace-safe 展示字段，不在前端实现指标公式、join 或数据计算。

2026-05-23 更新：Phase 10 首版结果体验增强已落地。analyze 响应稳定返回或预留 `chart`、`insight`、`quality_report`、`reasoning_trace_view`；upload/profile 响应可返回 `quality_report`。`reasoning_trace_view` 只允许展示结构化阶段摘要，不允许返回完整 Chain of Thought、raw reasoning tokens、raw prompt、API key 或 hidden benchmark answer。

2026-05-23 更新：Phase 11 会话隔离、历史续聊和 GPT-like 安静过程展示已进入 planned contract。本节新增的 conversation endpoints、`conversation_id` 和 owner 隔离字段均为计划契约，当前尚未实现；旧的 `dataset_id` 调用方式必须继续兼容。

## 全局响应规则

1. 所有 API 返回必须包含 response_version。
2. 所有 analyze 请求必须生成 run_id。
3. 所有错误必须进入 errors 字段。
4. 所有警告必须进入 warnings 字段。
5. 前端只能依赖稳定字段，不依赖 debug 字段。
6. debug 字段仅用于调试，不作为稳定展示契约。
7. API 稳定字段保持语言中立，但问题、answer、insight、chart title 和 warnings/errors 的可读文本必须优先支持中文使用场景，同时保留英文输入和英文输出兼容。
8. 前端不能依赖 debug 中的英文/中文内部阶段摘要；稳定展示只能依赖 answer、result、verification、insight、chart、warnings、errors 等契约字段。
9. Phase 9 前端可以展示 `logic_form.source_tables`、`logic_form.table_selection_reason`、`logic_form.join_plan` 和 debug / trace 中的 `join_execution_summary`，但不得把 debug 字段作为业务计算输入。
10. 多文件 / 多表场景中，后端必须显式返回或记录表选择和 join 依据；低置信度路由、无可信 join key 或多对多风险必须以结构化 warning / error / verification 体现。
11. Phase 10 前端只能渲染后端 `chart`、`insight`、`quality_report`、`reasoning_trace_view` 字段，不得自行推断图表类型、异常规则、清洗动作或分析过程。
12. `reasoning_trace_view` 是安全过程视图，不是完整 Chain of Thought；任何 `chain_of_thought`、`cot`、`hidden_reasoning`、`full_reasoning` 字段都不得进入稳定响应。
13. Phase 11 planned conversation API 必须以后端 `conversation_id` 作为会话连续性主键；前端不得用本地内存 run history 冒充可恢复历史。
14. Phase 11 planned owner 字段只用于预留未来隔离边界；v1 本地匿名实现不得宣称已经具备真实登录、鉴权、多租户或企业级权限。
15. GPT-like 过程展示只能使用安全摘要字段，默认显示单行浅灰小字摘要，点击后展开结构化步骤；不得在主界面展示 raw CoT、后端审计 JSON、quality_report、warnings、verification 或 join trace。

## Planned Phase 11 Conversation APIs

目标：为 Workbench 提供可恢复的会话层，使每个对话、窗口和历史 Chat 都能通过 `conversation_id` 明确隔离。该能力当前为计划契约，尚未实现。

计划 endpoints：

- `POST /api/data-agent/conversations`
- `GET /api/data-agent/conversations`
- `GET /api/data-agent/conversations/{conversation_id}`
- `PATCH /api/data-agent/conversations/{conversation_id}`

计划中的 conversation 字段：

- conversation_id
- title
- active_dataset_id
- messages
- runs
- created_at
- updated_at
- owner_type
- owner_id
- tenant_id
- created_by

计划中的 owner 语义：

- v1 可使用 `owner_type=local_anonymous` 表示本地匿名会话。
- `owner_id`、`tenant_id`、`created_by` 和 `owner_context` 只作为未来用户隔离预留字段。
- 未来接入真实认证后，所有 list / get / update / upload / analyze 都必须通过 backend owner filter 过滤，不能只靠前端隐藏历史记录。

兼容策略：

- 现有只传 `dataset_id` 的 upload / analyze / profile / run 调用继续可用。
- `conversation_id` 在 Phase 11 初始实现中应为可选字段；由 Workbench UI 优先创建并传入。
- 老客户端不传 `conversation_id` 时，后端不得破坏当前数据分析链路。

Quiet Process UX 契约：

- `reasoning_trace_view` 继续只返回安全结构化摘要。
- 前端可从最新 step 派生 `latest_process_summary`，例如“用户提到了‘城市订单金额’，我会先确认城市字段和金额字段。”。
- 展开详情只能展示用户可理解步骤，例如理解问题、定位数据、选择分析方式、生成结果、核对回答。
- API 不得新增或透传 `chain_of_thought`、`cot`、`hidden_reasoning`、`full_reasoning`、raw prompt 或 raw reasoning tokens。

## POST /api/data-agent/upload

目标：接收 CSV / Excel 文件，返回 dataset_id、文件信息、字段画像、warnings 和 errors。

稳定字段草案：

- response_version
- success
- dataset_id
- file_name
- status
- tables
- quality_report
- warnings
- errors

tables 中每个 table profile 当前稳定包含：

- table_name
- row_count
- column_count
- source_file
- sheet
- columns

columns 中每个 column profile 当前稳定包含：

- name
- inferred_type
- missing_rate
- unique_count
- sample_values
- semantic_hints

quality_report 当前可包含：

- status
- quality_score
- scanned_tables
- issue_count
- summary
- issues
- generated_from

Phase 11 planned request extension：

- conversation_id，可选；用于把上传结果绑定到指定会话。
- owner_type，可选；v1 可为 `local_anonymous`。
- owner_id，可选；未来由认证层注入或校验。
- tenant_id，可选；未来由认证层注入或校验。

## POST /api/data-agent/upload-batch

目标：一次接收多个 CSV / Excel 文件，解析为同一个 dataset，返回可审计的多文件 DatasetProfile。

请求：

- multipart/form-data
- 字段名：files
- 类型：一个或多个 UploadFile

稳定响应字段与 `/upload` 一致：

- response_version
- success
- dataset_id
- file_name
- status
- tables
- created_at
- quality_report
- warnings
- errors

多文件 profile 规则：

- `file_name` 为源文件名列表的逗号拼接摘要。
- 每个 table 必须保留 `source_file`。
- Excel sheet 必须保留 `sheet`。
- table_name 必须在一个 dataset 内唯一；CSV 默认使用源文件 stem，Excel 多 sheet 默认使用 `文件stem__sheet`。
- 旧单文件 `/upload` 仍保持原契约。

Phase 11 planned request extension：

- conversation_id，可选；用于把多文件 dataset 绑定到指定会话。
- owner_type / owner_id / tenant_id，可选；仅作为未来用户隔离预留，不代表当前已实现鉴权。

## POST /api/data-agent/analyze

目标：接收 dataset_id、用户问题、execution_mode 和可选 agent_mode，返回分析结果、校验信息、解释建议和图表配置。

execution_mode 预留：

- auto
- pandas
- sql
- dual

默认建议：dual。

agent_mode 预留：

- multi_agent
- single_agent

默认建议：multi_agent。

Phase 11 planned request extension：

- conversation_id，可选；用于把用户问题、assistant 结果、run_id、dataset_id 和过程摘要追加到指定会话。
- owner_type / owner_id / tenant_id，可选；未来应由 backend owner_context 统一解析，不能信任前端自报字段完成权限隔离。

稳定字段草案：

- response_version
- success
- run_id
- dataset_id
- question
- answer_type
- execution_mode
- answer
- logic_form
- result
- verification
- insight
- chart
- quality_report
- reasoning_trace_view
- warnings
- errors
- debug

chart v2 当前可包含：

- chart_type：`bar`、`horizontal_bar`、`line`、`pie`、`donut`、`histogram`、`box`、`scatter`、`kpi` 或 null
- x
- y
- title
- data
- reason
- encoding
- series
- confidence
- selection_reason
- fallback_reason

insight v2 当前可包含：

- summary
- key_numbers
- anomaly_findings
- volatility_findings
- suggestions
- business_suggestions
- caveats
- next_questions
- evidence_rows
- confidence

reasoning_trace_view 当前为数组，每个 step 可包含：

- step_id
- name
- status
- summary
- confidence
- inputs_summary
- outputs_summary
- warnings

logic_form 当前可包含：

- task_type
- operation
- metric
- group_by
- filters
- parameters
- source_tables
- table_selection_reason
- join_plan
- answer_target
- output_contract

join_plan 当前可包含：

- trusted
- reason
- left_table
- right_table
- left_key
- right_key
- relationship
- join_type
- confidence
- overlap_ratio
- many_to_many_risk

join_plan v1 只允许可信一对一 / 多对一 join。无可信 key、值重叠不足或多对多风险时，后端必须返回 clarification / standard error / verification correction action，不允许静默使用 primary table 或退回 ID 聚合。

verification 当前可包含：

- passed
- confidence
- pandas_sql_consistent
- semantic_passed
- issues
- notes
- semantic_verification_notes
- correction_action

debug 当前可能包含：

- llm_used
- llm_operation
- llm_confidence
- single_agent_chain
- llm_stage_summaries
- column_mapping
- pandas_success
- sql_success
- trace_path
- tool_call_summaries
- not_applicable_attribution
- agent_mode
- workflow_mode
- multi_agent_roles
- agent_task_results
- source_tables
- table_selection_reason
- join_plan
- join_execution_summary

trace 当前可包含：

- metric_definition
- numerator
- denominator
- semantic_verification_notes
- correction_attempts
- candidate_table_summary
- selected_candidate
- tool_call_summary
- not_applicable_attribution
- source_tables
- table_selection_reason
- join_plan
- join_execution_summary

llm_stage_summaries 只允许包含 structured analysis plan、reasoning summary、execution trace、verification notes 等摘要，不能包含完整 Chain of Thought。

tool_call_summaries 只允许包含 tool_name、step_id、requested_by、arguments_summary、result_summary、success、latency_ms、error，不允许包含完整 Chain of Thought、raw reasoning tokens、API key 或敏感原始数据。

not_applicable_attribution 只允许包含 category、reason、operation、message 等归因摘要。`true_unsupported` 表示上传规则、manual、schema 或业务知识没有定义；`capability_gap` 表示问题原则上可由数据或规则回答，但当前通用能力族还未覆盖。该字段仍属于 debug / trace 调试信息，前端展示应以 warnings / errors 为准。

join_execution_summary 只允许包含 join 类型、左右表、join key、输入/输出行数、unmatched keys、relationship 和风险摘要；不得包含完整原始数据或敏感样本。

失败响应必须包含：

- response_version
- success=false
- warnings
- errors
- run_id（analyze 请求）

errors 中的元素必须包含 error_type、error_message、failed_step、recoverable、suggested_fix。

## POST /api/data-agent/run

目标：供外部系统一次性调用现有 Data Agent。调用方直接传入 JSON 表格和自然语言问题；backend 创建临时 dataset 后复用 `analyze_dataset` 和当前默认 `multi_agent` workflow。

该接口属于 Phase 1 Backend API Shell 扩展，只提供接入面，不实现 Pandas / SQL / Verifier / Benchmark 核心逻辑。

请求字段：

- request_id，可选，调用方侧请求 ID，响应原样返回
- question，必填，自然语言问题，中文优先并兼容英文
- tables，必填，JSON 表格数据
- execution_mode，可选，auto / pandas / sql / dual，默认 dual
- agent_mode，可选，multi_agent / single_agent，默认 multi_agent
- guidelines，可选，输出约束或业务提示
- dataset_id，可选，调用方希望指定的临时 dataset_id

tables 支持两种稳定形态：

```json
[
  {
    "table_name": "销售",
    "rows": [
      {"城市": "上海", "销售额": 100},
      {"城市": "北京", "销售额": 150}
    ]
  }
]
```

```json
{
  "sales": {
    "rows": [
      {"city": "Shanghai", "sales": 100},
      {"city": "Beijing", "sales": 150}
    ]
  }
}
```

inline table 对象也可携带 `source_file` 和 `sheet`，用于 Phase 8 多文件路由与 trace 展示：

```json
[
  {
    "table_name": "库存文件",
    "source_file": "库存文件.csv",
    "sheet": null,
    "rows": [
      {"产品": "A", "库存量": 10},
      {"产品": "C", "库存量": 80}
    ]
  }
]
```

响应字段沿用 analyze 稳定契约：

- response_version
- success
- request_id（如果请求提供）
- run_id
- dataset_id
- question
- answer_type
- execution_mode
- answer
- logic_form
- result
- verification
- insight
- chart
- warnings
- errors
- debug

失败响应必须包含 response_version、success=false、run_id、warnings、errors；如果请求提供 request_id，必须原样返回。

`/run` 与 `/upload` + `/analyze` 的区别：

- `/run`：适合外部系统已经有 JSON 表格数据，需要一次性调用 Agent。
- `/upload` + `/analyze`：适合文件上传后多次复用同一个 dataset_id。

## GET /api/data-agent/datasets/{dataset_id}/profile

目标：返回指定数据集的文件信息、字段画像和状态。

稳定字段草案：

- response_version
- success
- dataset_id
- file_name
- tables
- created_at
- status
- warnings
- errors

## GET /workbench

目标：提供 Phase 9 首版静态前端 workbench。

契约边界：

- 仅在 backend 运行且 repo 存在 `frontend/` 目录时可用。
- `/workbench` 返回 `frontend/index.html`。
- `/frontend/*` 返回静态资源。
- 前端只调用 `/api/data-agent/upload`、`/api/data-agent/upload-batch`、`/api/data-agent/analyze`。
- 前端不得实现指标公式、join、排序聚合或评分逻辑；这些逻辑必须保留在 backend / data_agent_core。

Phase 11 planned behavior：

- URL 使用 `/workbench?conversation_id=...` 定位当前会话。
- 无 `conversation_id` 的新窗口默认创建独立会话。
- 左侧历史 Chat 从 conversation API 加载，不再只依赖前端内存。
- 过程展示默认只显示一条小号浅灰摘要，点击后展开安全结构化步骤。

## TODO

- 后续如引入真实 FastAPI 部署配置，需要保持 router 只调用 service，不写核心算法。
- 后续补充更多失败响应示例。
- 后续补充 storage retention 和最大文件大小的可配置项。
- 后续如把字段确认、join key 确认或澄清交互升级为稳定产品能力，必须先扩展 API_CONTRACT，再实现前端。
- Phase 11 实现前，必须先落地 conversation store、owner_context 过滤边界和旧 `dataset_id` 调用兼容测试。
