# API CONTRACT

## 当前阶段

当前只定义 API 契约骨架，不实现完整接口业务逻辑。

2026-05-21 更新：核心算法 MVP 已能返回 FinalResponse dataclass。后端 API 仍未实现业务接口，但未来 response schema 应与 FinalResponse 对齐。

2026-05-21 更新：Agent 已新增 LLM 单 Agent 链路。API 响应的 debug 可包含 llm_used、llm_operation、llm_confidence、single_agent_chain、llm_stage_summaries 等调试字段，但前端不能依赖 debug 字段作为稳定契约。

2026-05-21 更新：Phase 1 最小后端调用壳已落地。backend 通过 DataAgentService 调用 data_agent_core，支持上传 CSV / Excel 后返回 DatasetProfile、按 dataset_id 分析问题、获取 profile。router 仍只做请求转发，不包含 Pandas / SQL / Verifier 核心逻辑。

2026-05-21 更新：Phase 5 工具调用 trace 契约已预留。API 稳定字段不变；debug 未来可包含 tool_call_summaries，但前端仍不能依赖 debug。

2026-05-21 更新：内部工具 callable 和 Microsoft Agent Framework adapter 已开始实现。该变化不修改 upload/analyze/profile 的稳定 API 字段；如果 adapter 参与运行，只能把工具调用摘要放入 debug / trace，不允许新增前端必须依赖的字段。

2026-05-21 更新：analyze 默认切换为 multi_agent。请求可选 agent_mode，支持 multi_agent / single_agent；该字段用于内部运行模式选择，不改变稳定响应字段。默认 multi_agent 不要求安装 Microsoft Agent Framework，不引入前端强依赖字段。

2026-05-21 更新：`Not Applicable` 不再只作为普通字符串处理。analyze 的 debug / trace / benchmark report 可记录 not_applicable_attribution，用于区分 `true_unsupported` 和 `capability_gap`；如果属于 `capability_gap`，errors 必须包含 `CAPABILITY_GAP`，前端仍只依赖稳定的 answer、warnings、errors、verification 字段。

## 全局响应规则

1. 所有 API 返回必须包含 response_version。
2. 所有 analyze 请求必须生成 run_id。
3. 所有错误必须进入 errors 字段。
4. 所有警告必须进入 warnings 字段。
5. 前端只能依赖稳定字段，不依赖 debug 字段。
6. debug 字段仅用于调试，不作为稳定展示契约。
7. API 稳定字段保持语言中立，但问题、answer、insight、chart title 和 warnings/errors 的可读文本必须优先支持中文使用场景，同时保留英文输入和英文输出兼容。
8. 前端不能依赖 debug 中的英文/中文内部阶段摘要；稳定展示只能依赖 answer、result、verification、insight、chart、warnings、errors 等契约字段。

## POST /api/data-agent/upload

目标：接收 CSV / Excel 文件，返回 dataset_id、文件信息、字段画像、warnings 和 errors。

稳定字段草案：

- response_version
- success
- dataset_id
- file_name
- status
- tables
- warnings
- errors

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
- warnings
- errors
- debug

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

llm_stage_summaries 只允许包含 structured analysis plan、reasoning summary、execution trace、verification notes 等摘要，不能包含完整 Chain of Thought。

tool_call_summaries 只允许包含 tool_name、step_id、requested_by、arguments_summary、result_summary、success、latency_ms、error，不允许包含完整 Chain of Thought、raw reasoning tokens、API key 或敏感原始数据。

not_applicable_attribution 只允许包含 category、reason、operation、message 等归因摘要。`true_unsupported` 表示上传规则、manual、schema 或业务知识没有定义；`capability_gap` 表示问题原则上可由数据或规则回答，但当前通用能力族还未覆盖。该字段仍属于 debug / trace 调试信息，前端展示应以 warnings / errors 为准。

失败响应必须包含：

- response_version
- success=false
- warnings
- errors
- run_id（analyze 请求）

errors 中的元素必须包含 error_type、error_message、failed_step、recoverable、suggested_fix。

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

## TODO

- 后续如引入真实 FastAPI 部署配置，需要保持 router 只调用 service，不写核心算法。
- 后续补充更多失败响应示例。
- 后续补充 storage retention 和最大文件大小的可配置项。
