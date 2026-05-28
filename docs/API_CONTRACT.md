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

2026-05-23 更新：Phase 11 会话隔离、历史续聊和 GPT-like 安静过程展示已进入 planned contract。旧的 `dataset_id` 调用方式必须继续兼容。

2026-05-24 更新：Workbench UX hardening 新增已实现接口 `POST /api/data-agent/chat`，用于没有上传 dataset 时的普通 VDS 对话；该接口不生成业务结论，且直接调用 `/chat` 时不自动创建 conversation。Workbench 主路径使用 `/message`，由 `/message` 负责 Phase 11 conversation 持久化。针对概览类问题，Response Builder 可把明细型执行结果收敛为汇总指标表和短回答，避免主答案直接展示原始明细行。

2026-05-24 更新：Workbench 新增统一消息入口 `POST /api/data-agent/message`。前端不再根据 `dataset_id` 自行决定 chat/analyze；后端统一判断普通聊天、数据概览或正式分析。有 dataset 时，“你好 / 你是什么模型”等普通对话返回 `answer_type=chat`；“看一下这个数据”等泛概览请求返回 `answer_type=overview` 和 `指标 / 数值` 汇总表；正式分析问题继续复用 analyze 链路。

2026-05-25 更新：Phase 11 首个会话持久化落点已实现。新增本地 JSON conversation store，`POST /api/data-agent/message` 可选接收并返回 `conversation_id`，历史列表、历史详情、新建会话和重命名接口已可用。`owner_id`、`tenant_id`、`owner_context` 仅为未来隔离预留；当前不代表真实登录、鉴权或多租户权限。

2026-05-25 更新：Workbench 网页端 DAB context 包上传已实现。`POST /api/data-agent/upload-batch` 在收到完整 `payments.csv`、`merchant_category_codes.csv`、`acquirer_countries.csv`、`fees.json`、`merchant_data.json`、`manual.md` 时返回普通 DatasetProfile，同时在后端存储 `dabstep_context` 分析上下文；后续 `/message` 或 `/analyze` 复用既有 DAB parser / executor / fee engine。JSON / MD 只允许作为完整 DAB context 包的一部分进入上传链路，`all.jsonl`、`dev.jsonl`、标准答案或 task_id 仍不得进入 Agent workflow。

2026-05-25 更新：分析请求新增可选 `monitor_run_id`，并预留 `GET /api/data-agent/monitor/stream` SSE 安全过程事件流。monitor 只发布已脱敏的阶段摘要、角色状态、工具摘要和最终响应摘要，不作为前端业务计算输入，不返回完整 Chain of Thought、raw prompt、API key 或 hidden benchmark answer。

2026-05-25 更新：新增 Rule Mode / Benchmark 规则上传最小契约。上传接口可接收 `file_role` 和 `rule_scope` metadata；旧请求不传 `file_role` 时默认视为 `dataset`。`file_role=rule` 必须显式提供 `rule_scope=user_analysis` 或 `rule_scope=benchmark`，规则文件不会进入 DatasetProfile、字段画像、DataFrame 解析或普通 Chat 数据上下文。`user_analysis` 规则只有在 `/analyze` 或 `/message` 请求显式传入 `user_rule_file_id` 时才会合并到本次 `guidelines`；`benchmark` 规则只能通过独立 `POST /api/data-agent/benchmark/run` 使用。

2026-05-25 更新：新增 `process_view_v2` 安全过程叙事契约。`process_view_v2` 与旧 `reasoning_trace_view` 并存，前端优先渲染 v2，缺失时 fallback 到旧字段。v2 只使用安全 stage summary、执行摘要和 response contract，按 chat、dataset_overview、metric_lookup、ranking_topn、comparison_or_trend、multi_table_join、diagnostic_or_anomaly、clarification_or_not_applicable 生成差异化过程，不暴露完整 Chain of Thought、raw reasoning tokens、raw prompt、API key、task_id、标准答案、hidden answer、public proxy 或 scorer 信息。Monitor SSE 最终事件只发送 run 状态和 `process_view_v2` 摘要，不发送完整 response / trace payload。

2026-05-25 更新：Phase 12 首轮 GPT-like general / insight / activity stream 契约已落地。General / overview 问法可返回 `overview_report`、安全 `execution_artifacts`、增强后的 `insight` 和 dataset overview 活动流；普通 Workbench 混合上传可把 `.md/.txt/.yaml/.yml` 说明文件和规则型 `.json` 自动绑定为本 dataset 的 `user_analysis` knowledge。前端只渲染这些后端契约，不实现公式、join、聚合、图表选择、评分或数据清洗。

2026-05-25 更新：Phase 12.1 将“流式过程”和“防原始明细倾倒”合并为硬契约。Workbench 主页面可消费 monitor SSE 白名单事件（如 `data_scan_note`、`plan_note`、`dependency_note`、`code_artifact_ready`、`answer_outline_ready`），默认只显示一行 activity summary，详情中展示结构化步骤和安全代码 artifact。`overview` 和 `cleaning_simulation` 只能返回紧凑结果表；`这个数据主要讲什么`、`这几个表什么意思，有什么字段`、`每个文件分别有多少行、多少列`、清洗策略和是否修改原始数据等说明型问题不得返回原始明细行拼接文本。正式分析出口还必须具备 raw detail guard：若最终 `answer` 呈现为 CSV / 明细行拼接或短日期/数值串，后端必须改写成安全 overview 或澄清，并清空主结果明细。

2026-05-25 更新：Phase 13 首个 Project 工作区契约已落地。新增本地 JSON Project Store，Project API 支持 project CRUD、project source upload / delete、project memory CRUD；`POST /api/data-agent/message`、conversation create/list/record 增加可选 `project_id`。Project memory 为 `project_only`，只在同一 project 内注入；共享 dataset/rule 文件仍复用既有 upload / rule / dataset store；前端只渲染后端 Project 契约，不实现检索、join、聚合、评分或数据清洗。Workbench 左侧全局历史不得带 `project_id` 过滤；Project home 内的聊天列表才使用 project-scoped conversation query。

2026-05-26 更新：Activity Trace v2 已落地。最终响应可返回 `activity_trace_v2`，SSE 可发送 `activity_trace_delta`、`agent_failed` 和 `correction_rerun_started`，Workbench 右侧活动抽屉用这些安全节点展示真实 Planner、Pandas、SQL、Verifier、代码 artifact 和校验摘要。该契约只暴露工具调用摘要、执行摘要、代码 artifact 和 verifier 摘要，不暴露 raw Chain of Thought、raw prompt、reasoning tokens、API key、task_id、标准答案、hidden answer、public proxy 或 scorer。

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
11. Phase 10 前端只能渲染后端 `chart`、`insight`、`quality_report`、`reasoning_trace_view` 和 `process_view_v2` 字段，不得自行推断图表类型、异常规则、清洗动作或分析过程。
12. `reasoning_trace_view` 是安全过程视图，不是完整 Chain of Thought；任何 `chain_of_thought`、`cot`、`hidden_reasoning`、`full_reasoning` 字段都不得进入稳定响应。
13. Phase 11 conversation API 必须以后端 `conversation_id` 作为会话连续性主键；前端不得用本地内存 run history 冒充可恢复历史。
14. Phase 11 owner 字段只用于预留未来隔离边界；v1 本地匿名实现不得宣称已经具备真实登录、鉴权、多租户或企业级权限。
15. GPT-like 过程展示只能使用 `process_view_v2` 或安全摘要字段，默认显示单行浅灰小字摘要，点击后展开结构化步骤；不得在主界面展示 raw CoT、后端审计 JSON、quality_report、warnings、verification 或 join trace。
16. 无 dataset 对话只能进入 `/message` 或 `/chat` 的辅助回复路径；如果用户要求真实业务结论，必须提示需要上传相关数据，不能根据空上下文编造指标结果。
17. Workbench 前端不得用 `dataset_id` 存在与否自行把文本判成分析问题；普通聊天、数据概览和正式分析的路由必须由 backend / data_agent_core 决定。
18. Phase 12 `overview_report`、`execution_artifacts` 和自动规则绑定均为后端契约；前端不得根据字段名自行生成概览、代码、洞察、图表选择或规则应用。
19. Phase 12.1 前端必须对 general / overview / cleaning_simulation 问法执行主界面渲染熔断：只展示紧凑契约表，不展示宽明细表；代码 artifact 只能出现在过程详情中，不作为主答案区独立面板。
20. Phase 12.1 后端必须在 `respond_to_message` / `analyze_dataset` 出口前执行 raw detail answer guard；该 guard 不替代正式 planner / executor / verifier，只负责阻断“最终答案本身已经像原始明细倾倒”的用户体验事故。
21. Phase 13 Project memory 必须保持 project-only；不得跨 project 读取 conversation、memory 或 file，也不得把浏览器 localStorage 冒充共享项目存储。
22. Phase 13 Workbench Project UI 必须保持 ChatGPT-like：左侧全局导航、Project 列表和最近历史始终可见；进入 Project 只切换主区域 Project home，不得把全局 history API 或 sidebar 当成 project-only filter。
23. Activity Trace v2 是用户可见活动链路契约，不是 raw CoT 容器。前端只能渲染 `activity_trace_v2`、`activity_trace_delta` 和 `execution_artifacts` 中已脱敏字段，不得把 debug、完整 trace JSON、prompt、reasoning tokens、标准答案或 scorer 作为活动抽屉内容。

## Phase 11 Conversation APIs

目标：为 Workbench 提供可恢复的会话层，使每个对话和历史 Chat 都能通过 `conversation_id` 明确隔离。当前已实现本地 JSON conversation store、历史列表、历史详情、重命名和 `/message` 自动追加消息；URL 恢复、多窗口实时同步、真实登录和多租户隔离仍是后续工作。

当前 endpoints：

- `POST /api/data-agent/conversations`
- `GET /api/data-agent/conversations`
- `GET /api/data-agent/conversations/{conversation_id}`
- `PATCH /api/data-agent/conversations/{conversation_id}`

当前 conversation 字段：

- conversation_id
- title
- dataset_id
- project_id
- pinned
- pinned_at
- messages
- created_at
- updated_at
- owner_id
- tenant_id
- owner_context

assistant message payload 当前保存：

- run_id
- answer_type
- success
- payload：后端稳定响应快照，用于历史消息恢复

owner 语义：

- v1 为空 owner 时表示本地匿名会话。
- `owner_id`、`tenant_id` 和 `owner_context` 只作为未来用户隔离预留字段。
- 未来接入真实认证后，所有 list / get / update / upload / analyze 都必须通过 backend owner filter 过滤，不能只靠前端隐藏历史记录。

兼容策略：

- 现有只传 `dataset_id` 的 upload / analyze / profile / run 调用继续可用。
- `conversation_id` 在当前实现中为可选字段；未传入时，`/message` 自动创建新会话并在响应里返回。
- 老客户端不传 `conversation_id` 时，后端不得破坏当前数据分析链路。
- `PATCH /api/data-agent/conversations/{conversation_id}` 可更新 `title`、可选 `project_id` 和可选 `pinned`；`project_id` 为空字符串表示把对话移出 Project，`pinned=true/false` 表示置顶或取消置顶。
- `DELETE /api/data-agent/conversations/{conversation_id}` 删除一条对话，并同步从 Project 的 `conversation_ids` 中移除。

`POST /api/data-agent/message` 当前 request extension：

- conversation_id，可选；为空时后端自动创建。
- project_id，可选；为空时保持无 Project 的旧行为。
- user_rule_file_id，可选；只接受 `rule_scope=user_analysis` 的规则文件，语义同 `/analyze`。
- owner_id，可选；未来由认证层注入或校验。
- tenant_id，可选；未来由认证层注入或校验。
- owner_context，可选；仅保存 JSON-safe 摘要，不参与权限判断。

`POST /api/data-agent/message` 当前 response extension：

- conversation_id
- project_id：当请求在 Project 中执行时返回。
- project：当请求在 Project 中执行时返回 project_id、name、memory_mode、source_count、memory_count、default_dataset_id。
- conversation：包含 conversation_id、title、dataset_id、project_id、pinned、pinned_at、updated_at、message_count。

Quiet Process UX 契约：

- `reasoning_trace_view` 继续只返回安全结构化摘要。
- `process_view_v2` 是主界面优先使用的安全过程叙事字段，结构固定为 `version`、`summary`、`mode`、`steps[]`。
- 前端可从最新 step 派生 `latest_process_summary`，例如“用户提到了‘城市订单金额’，我会先确认城市字段和金额字段。”。
- 展开详情只能展示用户可理解步骤，例如理解问题、定位数据、选择分析方式、生成结果、核对回答。
- API 不得新增或透传 `chain_of_thought`、`cot`、`hidden_reasoning`、`full_reasoning`、raw prompt 或 raw reasoning tokens。

## Phase 13 Project APIs

目标：为 Workbench 提供 GPT-like Project 工作区，使 Project 内 conversations、shared files、instructions 和 project memory 共享同一个后端上下文边界。

当前 endpoints：

- `POST /api/data-agent/projects`
- `GET /api/data-agent/projects`
- `GET /api/data-agent/projects/{project_id}`
- `PATCH /api/data-agent/projects/{project_id}`
- `DELETE /api/data-agent/projects/{project_id}`
- `POST /api/data-agent/projects/{project_id}/sources`
- `POST /api/data-agent/projects/{project_id}/sources/upload`
- `DELETE /api/data-agent/projects/{project_id}/sources/{source_id}`
- `POST /api/data-agent/projects/{project_id}/memories`
- `PATCH /api/data-agent/projects/{project_id}/memories/{memory_id}`
- `DELETE /api/data-agent/projects/{project_id}/memories/{memory_id}`

Project 稳定字段：

- project_id
- name
- description
- instructions
- memory_mode：当前固定为 `project_only`
- default_dataset_id
- sources
- memories
- conversation_ids
- owner_id / tenant_id / owner_context：仅为未来隔离预留
- created_at / updated_at

Project source 类型：

- dataset：引用既有 dataset_id，不复制 DataFrame 解析逻辑。
- rule：引用既有 rule file_id，不进入 DatasetProfile / DataFrame。
- note：项目文本说明，只作为安全文本上下文。
- saved_response：后续用于保存 assistant 可见回答摘要，只作为安全文本上下文。

Project memory 类型：

- pinned：用户显式保存或编辑的项目内 memory。
- conversation_summary：后续从项目内对话生成的安全摘要。

Project 边界：

- `project_id` 为空时，所有旧 conversation / upload / analyze 行为保持兼容。
- `GET /api/data-agent/conversations` 无 `project_id` 时返回全局最近会话，用于 Workbench 左侧最近历史；Workbench 左侧不得因为当前 Project 自动追加 `project_id`。
- `GET /api/data-agent/conversations?project_id=...` 只用于主区域 Project home 的 `聊天` tab，不得替代左侧全局最近历史。
- Conversation 置顶属于后端 conversation metadata；列表返回 `pinned / pinned_at` 并按置顶优先排序。Workbench 只能通过 PATCH 切换置顶，不得用前端 localStorage 冒充持久化置顶。
- 删除 Project 只删除 Project metadata、sources 和 memories，并把关联 conversation 移出 Project；不会删除既有 dataset / rule 文件。对话本身通过 conversation DELETE 单独删除。
- Project 上传文件使用 `sources/upload`，后端先复用 upload-batch / rule store，再把 dataset_id / file_id 作为 Project Source 记录。
- Project context 注入顺序为 project instructions、显式本轮 guidelines、project memory、project text sources、当前 conversation dataset / rule context。
- Project memory / source 不允许保存 raw Chain of Thought、raw prompt、raw reasoning tokens、API key、task_id、标准答案、hidden answer、proxy answer 或 scorer 信息。

## POST /api/data-agent/upload

目标：接收 dataset 文件，返回 dataset_id、文件信息、字段画像、warnings 和 errors；或在显式 `file_role=rule` 时接收规则文件并返回 rule file metadata。

请求：

- multipart/form-data
- `file`：上传文件
- `file_role`：可选，`dataset` 或 `rule`；缺省为 `dataset`
- `rule_scope`：当 `file_role=rule` 时必填，支持 `user_analysis` / `benchmark`
- `bind_dataset_id`：可选，仅用于记录规则文件与当前 dataset 的弱绑定；普通分析仍必须显式传 `user_rule_file_id`

稳定字段草案：

- response_version
- success
- dataset_id
- file_role
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

规则上传响应字段：

- response_version
- success
- file_id
- file_name
- file_role：固定为 `rule`
- rule_scope
- dataset_id：可为空
- status
- rule_summary
- warnings
- errors

## POST /api/data-agent/upload-batch

目标：一次接收多个 dataset 文件，或接收完整 DAB context 规则包，解析为同一个 dataset，返回可审计的多文件 DatasetProfile；当显式 `file_role=rule` 时，一次接收多个同 scope 规则文件并返回 rule file ids。

请求：

- multipart/form-data
- 字段名：files
- 类型：一个或多个 UploadFile
- `file_role`：可选，`dataset` 或 `rule`；缺省为 `dataset`
- `rule_scope`：当 `file_role=rule` 时必填，支持 `user_analysis` / `benchmark`
- `bind_dataset_id`：可选，仅用于记录规则文件与当前 dataset 的弱绑定

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
- 如果上传文件集合完整包含 `payments.csv`、`merchant_category_codes.csv`、`acquirer_countries.csv`、`fees.json`、`merchant_data.json`、`manual.md`，后端将 dataset 标记为 `dabstep_context`，表格 profile 只展示三个 CSV 表；JSON / MD 文件只作为后端规则知识库，不作为前端表格解析。
- 如果只上传规则侧 DAB context 文件且没有 dataset 文件，必须返回标准错误并提示缺失文件，不能把 JSON / MD 当作普通表格解析。
- 普通 Workbench 混合上传中，dataset 文件可以和 `.md/.txt/.yaml/.yml` 说明文件或规则型 `.json` 一起提交；后端会把这些文件保存为 `rule_scope=user_analysis` 并绑定到当前 dataset，响应可包含 `auto_bound_user_rule_file_ids` 和 `auto_bound_rule_files`。

Phase 11 planned request extension：

- conversation_id，可选；用于把多文件 dataset 绑定到指定会话。
- owner_type / owner_id / tenant_id，可选；仅作为未来用户隔离预留，不代表当前已实现鉴权。

## POST /api/data-agent/analyze

目标：接收 dataset_id、用户问题、execution_mode、可选 agent_mode 和可选 user_rule_file_id，返回分析结果、校验信息、解释建议和图表配置。

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

用户规则扩展：

- `user_rule_file_id`：可选。必须指向 `file_role=rule, rule_scope=user_analysis` 的规则文件。
- 后端会把显式 `user_rule_file_id` 以及当前 dataset 已自动绑定的 `user_analysis` 规则合并为本次 guidelines 扩展，不把规则文件加入 dataset tables、profile、field_profiles、DataFrame 分析或普通文件列表。
- 如果传入 benchmark scope 的规则文件，必须返回标准错误，不允许把 Benchmark 规则注入普通 Agent 上下文。

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
- process_view_v2
- activity_trace_v2
- overview_report
- execution_artifacts
- warnings
- errors
- debug

概览类问题展示规则：

- 当用户问题明显是“看一下这个数据 / 整体情况 / 总体概览 / 这个数据主要讲什么 / 这几个表什么意思 / 有什么字段 / overall summary”时，后端可以返回 `answer_type=overview` 的数据概览，或由 Response Builder 把多行多列明细结果转换为用户可读的汇总展示。
- Workbench `message` 入口的泛概览可直接基于已上传、已解析的内存表生成全表概览；目标是避免把行数、前 20 行明细或后端审计字段当作最终回答。正式指标分析仍必须走 Planner、Executor 和 Verifier。
- 单表 `overview_report` 当前包含 report_type、table、source_file、row_count、column_count、metric_column、dimension_column、period_column、field_meanings、metric_summary、categorical_distributions、boolean_rates、answerable_questions 和 missing_boundaries。多表 overview 可返回 overview_scope、table_count、total_row_count、total_column_count 和 tables_summary。
- `execution_artifacts` 当前是安全展示用代码卡片数组，可包含 Python / Pandas 和只读 SQL 参考口径；它们从结构化 plan / verified result 生成，不是 raw executor code，不开放浏览器执行，不包含 raw prompt、完整 Chain of Thought、API key、task_id、hidden answer、standard answer、public proxy 或 scorer。
- `activity_trace_v2` 当前是安全活动节点数组，可包含 role、title、status、summary、actions、inputs、outputs、metrics、artifacts 和 timing_ms，用于 Workbench 右侧活动抽屉；节点来自 RunTrace、tool call trace、Pandas / SQL result、verification 和 `execution_artifacts` 的脱敏摘要，不是 raw backend trace。
- API 可在 `debug.user_experience_shaping` 记录是否发生展示收敛、原始行列数和使用的指标/维度字段；前端不得把该 debug 字段作为计算输入。
- 展示结果建议使用 `["指标", "数值"]` 这样的短表，避免把原始明细行作为主答案或主结果表。
- 多表概览展示结果必须使用 `["表名", "来源", "行数", "列数", "可能含义", "关键字段"]` 这样的紧凑表，不得把任意一张源表的前 50 行作为结果表。

清洗策略类问题展示规则：

- 当用户问题涉及“建议清洗规则 / 影响行数 / 影响比例 / 缺失字段删除填充保留 / 是否直接修改原始数据 / 用户确认”时，后端可以返回 `answer_type=cleaning_simulation` 或边界型 `answer_type=chat`。
- 清洗策略响应必须是模拟和建议，不得修改源文件；必须说明规则、影响行数、影响比例和用户确认边界。
- 清洗策略响应的 `result.columns` 建议为 `["表名", "规则", "影响行数", "影响比例", "建议"]`；不得返回命中的原始明细行或样例明细拼接文本。

## POST /api/data-agent/benchmark/run

目标：独立运行上传式 Benchmark 规则，不进入普通 Chat 主流程。

请求字段：

- dataset_id：必须指向已上传 dataset。
- benchmark_rule_file_id：必须指向 `file_role=rule, rule_scope=benchmark`。
- user_rule_file_id：可选；必须指向 `file_role=rule, rule_scope=user_analysis`，仅用于测试 Agent 在该用户规则约束下的表现。
- execution_mode：默认 `auto`。
- agent_mode：默认 `multi_agent`。
- limit：可选，限制规则中的问题数量。

响应字段：

- response_version
- success
- run_id
- dataset_id
- benchmark_rule_file_id
- user_rule_file_id
- benchmark
- total
- scored
- correct
- accuracy
- details
- report_path
- warnings
- errors

边界：

- Benchmark rule 的 expected output、metrics、threshold 只用于 runner/report，不传入 ordinary Chat，也不作为 Agent prompt / Planner / Executor / Verifier 输入。
- Runner 只把每个 case 的 question、case guidelines 和显式 user_analysis rule 传入 Agent。
- `details` 可以记录 case_id、question、agent_answer、correct 和 trace_path，但不能把 hidden answer、标准答案或完整规则原文暴露给普通 Chat。

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
- image_data_uri：后端渲染的图表图片 data URI。Workbench 有 chart rows / encoding 时优先按 chart spec 渲染前端交互图；该字段只作为数据不足或编码缺失时的静态兜底。
- image_format：当前可为 `svg`
- render_engine：当前可为 `python_svg`；`matplotlib` 已作为可视化可选依赖加入，可用于后续后端 renderer / 导出能力，但前端不应依赖具体 renderer 名称做计算。

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

Phase 12 insight 要求：

- `business_suggestions` 不能只返回泛化模板；每条建议应尽量包含观察、依据、边界或推荐动作。
- Insight 只能基于 verified result、overview report、质量报告、图表和字段语义摘要，不读取 benchmark 标准答案、proxy/scorer 或 raw trace。

reasoning_trace_view 当前为数组，每个 step 可包含：

- step_id
- name
- status
- summary
- confidence
- inputs_summary
- outputs_summary
- warnings

process_view_v2 当前为对象：

- version：当前为 `v2`
- summary：本次过程的一句话安全摘要
- mode：`chat`、`dataset_overview`、`metric_lookup`、`ranking_topn`、`comparison_or_trend`、`multi_table_join`、`diagnostic_or_anomaly`、`clarification_or_not_applicable`
- steps：数组；每个 step 只允许包含 `title`、`summary`、`status`、`evidence`、`assumptions`、`caveats`、`confidence`、`source`

`process_view_v2` 边界：

- 不包含 raw prompt、raw reasoning tokens、完整 Chain of Thought、API key、task_id、标准答案、hidden answer、public proxy、scorer、完整 verification/debug、完整工具参数或完整 join trace。
- 多表问题只能展示表选择和 join 摘要，不展示完整 `join_plan` 或 `join_execution_summary`。
- `single_agent`、`multi_agent`、`/chat`、普通聊天、dataset overview 和正式分析都应返回该字段。

activity_trace_v2 当前为数组，每个 node 可包含：

- node_id
- role
- title
- status
- summary
- actions
- inputs
- outputs
- metrics
- artifacts
- timing_ms

`activity_trace_v2` 边界：

- 不包含 raw prompt、raw reasoning tokens、完整 Chain of Thought、API key、task_id、标准答案、hidden answer、public proxy、scorer、完整 verification/debug、完整工具参数或完整 join trace。
- Pandas / SQL 代码只能来自安全 `execution_artifacts`，作为可复现展示，不代表浏览器可执行代码入口。
- SQL coverage gap 或 skipped reason 必须以摘要展示，不能把 skipped 误渲染成 SQL 算错。
- 最终响应到达后，前端必须以最终 `activity_trace_v2` 覆盖 SSE 临时状态。

主页面 monitor SSE 消费契约：

- Workbench 可在发送 `/message` 前创建 `monitor_run_id` 并订阅 `/api/data-agent/monitor/stream?monitor_run_id=...`。
- 允许主界面消费的安全事件类型包括：`monitor_connected`、`message_requested`、`analysis_requested`、`workflow_started`、`agent_started`、`agent_completed`、`agent_failed`、`workflow_completed`、`response_ready`、`analysis_failed`、`correction_rerun_started`、`activity_trace_delta`、`thought_delta`、`tool_considered`、`dependency_note`、`data_scan_note`、`plan_note`、`code_artifact_ready`、`answer_outline_ready`。
- 主界面只能展示事件的安全 title / summary 派生文案；不得展示完整 payload、raw trace、raw prompt、Chain of Thought、API key、task_id、standard answer、hidden answer、proxy 或 scorer。
- 最终 `/message` JSON 到达后，主界面必须以 `process_view_v2`、`activity_trace_v2`、`answer`、`insight`、`chart`、`result` 和 `execution_artifacts` 为权威结果；SSE 只负责实时活动感，不负责核心分析逻辑。

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

## POST /api/data-agent/chat

目标：没有上传 dataset 时，允许 Workbench 仍然像聊天一样向 VDS 提问，用于讨论分析目标、指标口径、字段设计或使用方式。

请求：

- question：必填，自然语言问题。
- agent_mode：可选，保留 `multi_agent` / `single_agent` 兼容字段；当前只用于输入校验，不触发数据分析 workflow。

稳定响应字段：

- response_version
- success
- run_id
- dataset_id：固定为空字符串
- question
- answer_type：固定为 `chat`
- execution_mode：固定为 `chat`
- answer
- logic_form：null
- result：空 columns / rows
- verification
- insight：null
- chart：null
- quality_report：null
- reasoning_trace_view
- process_view_v2
- warnings
- errors
- debug

边界：

- `/chat` 不读取临时 dataset store，不运行 Pandas / SQL / Verifier，不生成业务数据结论。
- 用户要求真实销售、收入、订单、经营等结论时，回答必须说明需要上传相关数据。
- `/chat` 不是 Phase 11 conversation persistence；不会创建可恢复会话、owner 过滤或历史续聊记录。

## POST /api/data-agent/message

目标：Workbench 的统一消息入口。前端只上传文件、提交文本和展示结果；是否普通聊天、数据概览或正式分析由后端判断。

请求：

- question：必填，自然语言消息。
- dataset_id：可选；为空时等价于无文件聊天。
- execution_mode：可选，默认 `dual`；仅正式分析使用。
- guidelines：可选；仅正式分析使用。
- agent_mode：可选，默认 `multi_agent`。

响应：

- 普通聊天：返回 `answer_type=chat`、`execution_mode=chat`、空 result。
- 数据概览：返回 `answer_type=overview`、`execution_mode=overview`、`result.columns=["指标","数值"]`，`debug.message_intent=dataset_overview`。
- 正式分析：返回与 `/api/data-agent/analyze` 相同的稳定响应字段；三类响应都应带 `process_view_v2`。

边界：

- `/message` 不创建 Phase 11 conversation，不提供可恢复历史。
- 有 dataset 的普通聊天不得调用 Pandas / SQL / Verifier。
- 数据概览由 backend / data_agent_core 基于已解析表生成；前端不得实现指标计算、排序、聚合、join 或评分。

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
- 前端只调用 `/api/data-agent/upload`、`/api/data-agent/upload-batch` 和 `/api/data-agent/message`。
- 前端不得实现指标公式、join、排序聚合或评分逻辑；这些逻辑必须保留在 backend / data_agent_core。

Phase 11 current / future behavior：

- 当前左侧历史 Chat 从 conversation API 加载，不再只依赖前端内存。
- 当前无 `conversation_id` 的 `/message` 会自动创建独立会话。
- 后续 URL 使用 `/workbench?conversation_id=...` 定位当前会话。
- 过程展示默认只显示一条小号浅灰摘要，点击后展开安全结构化步骤。

## TODO

- 后续如引入真实 FastAPI 部署配置，需要保持 router 只调用 service，不写核心算法。
- 后续补充更多失败响应示例。
- 后续补充 storage retention 和最大文件大小的可配置项。
- 后续如把字段确认、join key 确认或澄清交互升级为稳定产品能力，必须先扩展 API_CONTRACT，再实现前端。
- Phase 11 实现前，必须先落地 conversation store、owner_context 过滤边界和旧 `dataset_id` 调用兼容测试。
