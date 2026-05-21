# API CONTRACT

## 当前阶段

当前只定义 API 契约骨架，不实现完整接口业务逻辑。

2026-05-21 更新：核心算法 MVP 已能返回 FinalResponse dataclass。后端 API 仍未实现业务接口，但未来 response schema 应与 FinalResponse 对齐。

2026-05-21 更新：Agent 已新增 LLM 单 Agent 链路。API 响应的 debug 可包含 llm_used、llm_operation、llm_confidence、single_agent_chain、llm_stage_summaries 等调试字段，但前端不能依赖 debug 字段作为稳定契约。

## 全局响应规则

1. 所有 API 返回必须包含 response_version。
2. 所有 analyze 请求必须生成 run_id。
3. 所有错误必须进入 errors 字段。
4. 所有警告必须进入 warnings 字段。
5. 前端只能依赖稳定字段，不依赖 debug 字段。
6. debug 字段仅用于调试，不作为稳定展示契约。

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

目标：接收 dataset_id、用户问题和 execution_mode，返回分析结果、校验信息、解释建议和图表配置。

execution_mode 预留：

- auto
- pandas
- sql
- dual

默认建议：dual。

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

debug 当前可能包含：

- llm_used
- llm_operation
- llm_confidence
- single_agent_chain
- llm_stage_summaries
- column_mapping
- pandas_success
- sql_success

llm_stage_summaries 只允许包含 structured analysis plan、reasoning summary、execution trace、verification notes 等摘要，不能包含完整 Chain of Thought。

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

- Phase 1 用后端 schema 和 response_contracts.py 对齐这些字段。
- 增加失败响应示例。
- 增加错误类型到 errors 字段的映射说明。
