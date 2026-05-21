# AI CHANGELOG

## 使用规则

每次 Codex 修改代码后，必须追加一条记录。

本文件只记录真实发生过的修改，不允许虚构历史记录，不允许补写不存在的修改。

每次记录必须包含：

1. 日期时间
2. 本次目标
3. 修改文件
4. 修改内容
5. 测试方式
6. 测试结果
7. 遗留问题
8. 是否影响主流程
9. 是否涉及 Benchmark
10. 是否涉及 Microsoft Agent Framework
11. 是否影响未来多 Agent 迁移
12. 是否修改核心数据契约
13. 是否修改 API 契约
14. 是否新增或修改错误类型
15. 是否新增或修改运行追踪逻辑

日期时间规则：

1. 新增记录必须使用 `YYYY-MM-DD HH:MM TZ` 格式，精确到分钟。
2. 默认使用当前本地时区时间。
3. 禁止只写日期，不写具体时间。
4. 禁止为了补齐格式而给历史记录编造分钟级时间；历史记录如果原本只有日期，必须保留原样。

## 模板

### 日期时间

YYYY-MM-DD HH:MM TZ

### 本次目标

### 修改文件

### 修改内容

### 测试方式

### 测试结果

### 遗留问题

### 是否影响主流程

### 是否涉及 Benchmark

### 是否涉及 Microsoft Agent Framework

### 是否影响未来多 Agent 迁移

### 是否修改核心数据契约

### 是否修改 API 契约

### 是否新增或修改错误类型

### 是否新增或修改运行追踪逻辑

---

### 日期时间

2026-05-21 11:59 CST

### 本次目标

按 Phase 计划继续推进到 Phase 4 前置状态：建立 Phase gate、补内部 Agent runtime 契约、补 Microsoft Agent Framework 适配层声明式映射、补多 Agent workflow 任务序列，并通过防 Benchmark 硬编码测试保证后续只提升泛化能力，不按题目优化。

### 修改文件

- docs/PHASE_GATES.md
- docs/FEATURE_BACKLOG.md
- agent_runtime/agent_role.py
- agent_runtime/agent_task.py
- agent_runtime/agent_result.py
- agent_runtime/workflow_state.py
- agent_runtime/runtime_interfaces.py
- agent_runtime/tool_registry.py
- data_agent_core/contracts/agent_contracts.py
- data_agent_core/core/dabstep_fee_engine.py
- data_agent_core/core/intent_parser.py
- data_agent_core/executors/pandas_executor.py
- data_agent_core/llm/planner.py
- data_agent_core/output/response_builder.py
- ms_agent_framework_adapter/adapter.py
- ms_agent_framework_adapter/agent_mapping.py
- ms_agent_framework_adapter/workflow_mapping.py
- ms_agent_framework_adapter/tool_mapping.py
- ms_agent_framework_adapter/state_mapping.py
- multi_agent_workflows/end_to_end_data_analysis_workflow.py
- multi_agent_workflows/planner_workflow.py
- multi_agent_workflows/dual_executor_workflow.py
- multi_agent_workflows/verification_workflow.py
- tests/architecture/test_dependency_boundaries.py
- tests/architecture/test_no_benchmark_hardcoding.py
- tests/agent_runtime/test_runtime_contracts.py
- tests/__init__.py
- tests/core/__init__.py
- tests/architecture/__init__.py
- tests/agent_runtime/__init__.py
- CHANGELOG_AI.md

### 修改内容

- 新增 docs/PHASE_GATES.md，明确 Phase 1 到 Phase 5+ 的进入/退出条件和禁止按 Benchmark 题目优化的红线。
- 将 agent_runtime 从 docstring 草案推进为轻量 dataclass / Enum / Protocol 契约。
- 将 Microsoft Agent Framework adapter 继续保持无框架依赖，只提供声明式 role / workflow / tool / state mapping。
- 将 multi_agent_workflows 推进为 framework-neutral AgentTask 序列构建器，不承载核心算法。
- 新增架构测试，检查 data_agent_core 不能 import 外层 adapter / workflow / backend，adapter 当前不能 import Microsoft 框架。
- 新增防 Benchmark 硬编码测试，检查核心分析模块不引用 Benchmark 泄漏字段，并验证 runner 只把 question / guidelines / execution_mode 传给 agent。
- 新增 agent_runtime 契约测试和 unittest discover 支持。
- 补通用分析能力：fraud_rate_comparison、year-level best_fraud_aci_choice、cheapest_card_scheme_for_transaction、card_scheme 输出格式。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/dabstep_phase_gate_dev_1_10
- source .env.local 后运行 /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/dabstep_phase_gate_real_dev_1_10
- source .env.local 后运行 /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 10 --offset 10 --output-dir outputs/dabstep_phase_gate_real_11_20
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- rg -n "^\\s*(from|import)\\s+(backend|ms_agent_framework_adapter|multi_agent_workflows|agent_framework)" data_agent_core
- rg secret-pattern scan against repository files excluding outputs/

### 测试结果

- unittest discover 通过：Ran 11 tests in 8.738s，OK。
- DABstep dev 1-10 mock：8/10，accuracy=0.8。
- DABstep dev 1-10 真实 LLM：8/10，accuracy=0.8。
- DABstep all 11-20 真实 LLM：可生成 10 条预测，public all.jsonl 无 answer，因此 accuracy=null。
- DABstep all 11-20 真实 LLM 的 10 条预测均 success=True。
- compileall 通过。
- data_agent_core 禁止 import 边界检查未发现实际 import 匹配。
- secret 扫描未发现提供过的 key 或 key 片段进入仓库文件；.env.local 仍为 ignored 文件。

### 遗留问题

- all.jsonl 没有本地标准答案，无法本地计算 11-20 的真实准确率。
- Microsoft Agent Framework 仍未安装、未接入真实 workflow；当前只是 Phase 4 前置 adapter plan。
- 后续进入 Phase 4 时仍必须保证 data_agent_core 不依赖 Microsoft Agent Framework。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端或复杂后端业务。

### 是否涉及 Benchmark

是。使用 DABstep 进行分段验证，但新增了防硬编码测试，且标准答案只在 evaluator 评分阶段使用，不进入核心分析链路或 LLM。

### 是否涉及 Microsoft Agent Framework

是，但仅限适配层声明式映射和 Phase gate 文档；未安装、未 import、未实现真实 Microsoft Agent Framework workflow。

### 是否影响未来多 Agent 迁移

是，正向影响。新增 agent_runtime 契约、adapter mapping 和 multi_agent workflow task builders，为 Phase 4+ 多 Agent 编排做准备。

### 是否修改核心数据契约

是。agent_contracts.py 说明更新为与 agent_runtime 契约对齐；未修改 FinalResponse 稳定 API 字段。

### 是否修改 API 契约

否。本轮未修改 API 稳定字段。

### 是否新增或修改错误类型

否。本轮未新增错误类型。

### 是否新增或修改运行追踪逻辑

否。本轮未新增 trace 字段。

---

### 日期时间

2026-05-21 11:30 CST

### 本次目标

修改 AI CHANGELOG 记录规则，要求未来每次修改记录的时间精确到分钟，避免只写日期导致记录粒度过粗。

### 修改文件

- CHANGELOG_AI.md
- MAIN_GOAL.md
- BRANCH_RULES.md

### 修改内容

- 将 CHANGELOG_AI.md 的必填项从“日期”调整为“日期时间”。
- 新增日期时间格式规则：`YYYY-MM-DD HH:MM TZ`，精确到分钟。
- 明确未来新增记录禁止只写日期。
- 明确历史记录不允许为了补齐格式而编造分钟级时间。
- 在 MAIN_GOAL.md 和 BRANCH_RULES.md 中同步记录 changelog 时间粒度规则。

### 测试方式

- sed -n 读取 MAIN_GOAL.md、CHANGELOG_AI.md、BRANCH_RULES.md

### 测试结果

- 已完成规则文件读取。
- 本轮为文档规则修改，无代码测试。

### 遗留问题

- 历史 CHANGELOG 记录仍保留原始日期格式，未补造分钟级时间。

### 是否影响主流程

否。仅修改项目规则文档。

### 是否涉及 Benchmark

否。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

否。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

---

### 日期

2026-05-21

### 本次目标

按用户要求将 Agent 从纯确定性核心改为必须包含 LLM planning layer；明确 prompt 存放位置，支持 DeepSeek / OpenAI-compatible Chat Completions，通过环境变量读取 key，且禁止把 key 写入 Git。

### 修改文件

- .gitignore
- .env.example
- README.md
- MAIN_GOAL.md
- README.md
- docs/ARCHITECTURE.md
- docs/API_CONTRACT.md
- docs/BENCHMARK_RULES.md
- docs/FEATURE_BACKLOG.md
- docs/SECURITY_BOUNDARIES.md
- data_agent_core/llm/__init__.py
- data_agent_core/llm/client.py
- data_agent_core/llm/planner.py
- data_agent_core/prompts/data_agent_system_prompt.md
- data_agent_core/agent/single_agent.py
- data_agent_core/tracing/run_trace.py
- tests/core/test_dabstep_core.py

### 修改内容

- 新增 data_agent_core/llm，用标准库 urllib 实现 OpenAI-compatible /chat/completions client。
- 支持 VDS_LLM_PROVIDER=deepseek / openai / mock。
- 真实 key 仅从 DEEPSEEK_API_KEY 或 OPENAI_API_KEY 环境变量读取，不写入仓库。
- 新增 prompt 文件 data_agent_core/prompts/data_agent_system_prompt.md。
- DataAnalysisAgent 初始化时必须加载 LLM client，analyze 时先调用 LLM 生成结构化 LogicForm 草案。
- 本地 deterministic parser 保留为 schema guardrail，限制 LLM 输出到受支持 operation，防止非法结构或 Benchmark 信息泄漏。
- RunTrace 增加 llm_plan_summary，只记录 operation、confidence、reasoning_summary，不记录完整 prompt、key 或完整 Chain of Thought。
- tests 使用 MockLLMClient / VDS_LLM_PROVIDER=mock 验证 LLM wiring，不依赖真实 key。
- README 和 docs 更新 prompt 路径、环境变量方式、key 不进 Git 的约束。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_dabstep_core
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --output-dir outputs/dabstep_core_mvp_llm
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 10 --output-dir outputs/dabstep_core_mvp_llm
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core tests/core tests/architecture
- secret pattern scan over repo files excluding outputs

### 测试结果

- unittest 通过：Ran 2 tests in 1.735s，OK。
- mock LLM wiring 下 DABstep dev 前 10：total=10，scored=10，correct=8，accuracy=0.8。
- mock LLM wiring 下 DABstep all 前 10 已生成预测文件；本地 all.jsonl answer 为空，accuracy=null。
- compileall 通过。
- 仓库扫描未发现用户提供的真实 key 片段。

### 遗留问题

- 未在工具命令中注入用户提供的真实 key，避免 key 出现在命令记录或输出中；真实运行需要用户在本机 shell 或 .env.local 中设置环境变量。
- 真实 LLM 输出可能波动，当前通过本地 schema guardrail 固定到受支持的 LogicForm / operation。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端或复杂后端业务。

### 是否涉及 Benchmark

是。benchmark runner 继续支持 dev/all 前 10；不会把 task_id 或 answer 字段传给 LLM。

### 是否涉及 Microsoft Agent Framework

否。新增的是普通 OpenAI-compatible LLM client，不安装、不 import Microsoft Agent Framework。

### 是否影响未来多 Agent 迁移

是，正向影响。LLM planning layer 仍在 data_agent_core 内，后续可被 agent_runtime 或 adapter 编排。

### 是否修改核心数据契约

是。RunTrace 增加 llm_plan_summary，Agent 调试输出增加 llm_used / llm_operation / llm_confidence。

### 是否修改 API 契约

是。docs/API_CONTRACT.md 说明 debug 中可能包含 LLM 调试字段，但前端不能依赖 debug。

### 是否新增或修改错误类型

否。未新增错误类型。

### 是否新增或修改运行追踪逻辑

是。RunTrace 记录 LLM plan 摘要，不记录 key、完整 prompt 或完整 Chain of Thought。

---

### 日期

2026-05-21

### 本次目标

继续推进核心算法 MVP，使项目可以进行核心算法测试，并能按 BM 要求将 payments.csv 作为业务数据库表、manual.md / fees.json / merchant_data.json 作为文档和规则知识库，运行 DABstep 前 10 题；要求 dev 前 10 题达到 80% 正确率，禁止按题目优化。

### 修改文件

- .gitignore
- README.md
- MAIN_GOAL.md
- BRANCH_RULES.md
- docs/ARCHITECTURE.md
- docs/API_CONTRACT.md
- docs/BENCHMARK_RULES.md
- docs/FEATURE_BACKLOG.md
- data_agent_core/contracts/dataset_contracts.py
- data_agent_core/contracts/analysis_contracts.py
- data_agent_core/contracts/execution_contracts.py
- data_agent_core/contracts/verification_contracts.py
- data_agent_core/contracts/response_contracts.py
- data_agent_core/errors/error_types.py
- data_agent_core/errors/error_result.py
- data_agent_core/tracing/run_trace.py
- data_agent_core/tracing/trace_writer.py
- data_agent_core/core/file_parser.py
- data_agent_core/core/schema_profiler.py
- data_agent_core/core/date_utils.py
- data_agent_core/core/dabstep_fee_engine.py
- data_agent_core/core/intent_parser.py
- data_agent_core/core/logic_form.py
- data_agent_core/core/analysis_planner.py
- data_agent_core/core/result_schema.py
- data_agent_core/executors/pandas_executor.py
- data_agent_core/executors/sql_executor.py
- data_agent_core/verifier/result_normalizer.py
- data_agent_core/verifier/result_comparator.py
- data_agent_core/verifier/rule_checker.py
- data_agent_core/output/response_builder.py
- data_agent_core/agent/single_agent.py
- data_agent_core/benchmark/evaluator.py
- data_agent_core/benchmark/benchmark_runner.py
- tests/core/test_dabstep_core.py

### 修改内容

- 将核心 contracts 从注释草案推进为轻量 dataclass。
- 将 errors 和 tracing 推进为可引用错误类型、结构化错误结果、RunTrace 和 trace.json 写入函数。
- 实现 DABstep 上下文加载，明确 payments.csv 是业务数据库表，manual.md / fees.json / merchant_data.json 是规则知识库。
- 实现通用 DABstep fee-rule engine，覆盖费用规则匹配、月度 volume/fraud、适用 fee IDs、总费用、费率变更 delta、MCC 变更 delta、card scheme steering、fraud ACI what-if 等通用能力。
- 实现通用 intent parser，不使用 task_id、标准答案或单题硬编码。
- 实现 Pandas 执行路径和 sqlite SQL fallback，用于 SQL-compatible 聚合类任务。
- 实现结果标准化、执行结果比较、基础 verifier 和 FinalResponse 构建。
- 实现 benchmark runner 和 evaluator；runner 只在评分阶段读取 answer 字段，核心分析链路只接收 question、guidelines 和上下文数据。
- 新增 unittest 核心测试，固定 DABstep dev 前 10 题准确率不低于 80%。
- 更新工程文档、README 和 backlog，记录当前核心算法 MVP 与 BM 运行命令。

### 测试方式

- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_dabstep_core
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --output-dir outputs/dabstep_core_mvp
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 10 --output-dir outputs/dabstep_core_mvp
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core tests/core tests/architecture
- rg -n "^\\s*(from|import)\\s+(backend|ms_agent_framework_adapter|multi_agent_workflows|agent_framework)" data_agent_core

### 测试结果

- unittest 通过：Ran 2 tests in 2.063s，OK。
- DABstep dev 前 10 题通过本地评分：total=10，scored=10，correct=8，accuracy=0.8。
- DABstep all 前 10 题已生成预测文件：outputs/dabstep_core_mvp/all_first10_predictions.jsonl。本地 all.jsonl 的 answer 字段为空，因此 scored=0，accuracy=null。
- compileall 通过。
- data_agent_core 禁止 import 边界检查未发现实际 import 匹配。

### 遗留问题

- 当前仅覆盖核心算法 MVP 和 DABstep 前 10 题通用问题形态，尚未覆盖完整 450 题。
- 本机系统 Python 缺少 pandas / numpy / duckdb / pytest；本轮使用 Codex bundled Python 运行测试。DuckDB 未安装，因此 SQL 路径当前使用 sqlite fallback。
- 远端 dev 分支仍不存在，首次 commit / push 后需要补齐 dev 和 feature 分支流程。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端或复杂后端业务。

### 是否涉及 Benchmark

是。新增 DABstep runner 和 evaluator，用于 dev/all 前 10 题本地运行。标准答案只在 evaluator 评分阶段使用，不进入核心分析链路。

### 是否涉及 Microsoft Agent Framework

否。未安装、未 import、未实现 Microsoft Agent Framework workflow。

### 是否影响未来多 Agent 迁移

是，正向影响。核心算法保持在 data_agent_core 中，仍与 agent framework 解耦，后续可由 agent_runtime 或 adapter 编排。

### 是否修改核心数据契约

是。contracts 草案被推进为轻量 dataclass，包括 DatasetProfile、LogicForm、AnalysisPlan、ExecutionResult、VerificationResult 和 FinalResponse 等。

### 是否修改 API 契约

是。FinalResponse 增加 answer 字段，docs/API_CONTRACT.md 已同步记录。

### 是否新增或修改错误类型

是。error_types.py 改为可引用常量，error_result.py 增加结构化 ErrorResult。

### 是否新增或修改运行追踪逻辑

是。新增 RunTrace dataclass 和 trace_writer.write_trace，runner 会写入 trace.json；trace 只包含可审计执行摘要，不包含完整 Chain of Thought。

---

### 日期

2026-05-21

### 本次目标

初始化项目规则文件、Data Agent 核心目录骨架、最小后端 API 骨架、内部 Agent 抽象层骨架、Microsoft Agent Framework 适配层骨架、多 Agent workflow 预留目录、数据契约骨架、错误体系骨架、运行追踪骨架、文档骨架和架构边界测试骨架。

### 修改文件

- MAIN_GOAL.md
- CHANGELOG_AI.md
- BRANCH_RULES.md
- README.md
- docs/ARCHITECTURE.md
- docs/API_CONTRACT.md
- docs/DATASET_LIFECYCLE.md
- docs/BENCHMARK_RULES.md
- docs/SECURITY_BOUNDARIES.md
- docs/FEATURE_BACKLOG.md
- data_agent_core/README.md
- data_agent_core/configs/tool_whitelist.yaml
- data_agent_core/configs/benchmark_config.yaml
- data_agent_core/configs/model_config.yaml
- data_agent_core/contracts/*.py
- data_agent_core/errors/*.py
- data_agent_core/tracing/*.py
- data_agent_core/core/*.py
- data_agent_core/executors/*.py
- data_agent_core/verifier/*.py
- data_agent_core/output/*.py
- data_agent_core/agent/*.py
- data_agent_core/benchmark/*.py
- backend/**/*.py
- agent_runtime/*.py
- ms_agent_framework_adapter/*.py
- multi_agent_workflows/*.py
- tests/architecture/test_dependency_boundaries.py
- tests/*/.gitkeep

### 修改内容

- 创建项目主目标、AI 修改记录和分支规则文档。
- 创建 docs 工程文档骨架，覆盖架构、API 契约、数据集生命周期、Benchmark 规则、安全边界和功能 backlog。
- 创建 data_agent_core 目录和核心模块边界，只包含 docstring、TODO 和契约草案。
- 创建 contracts、errors、tracing 草案，预留稳定数据契约、错误类型和运行追踪字段。
- 创建 backend 最小 API 调用壳骨架，不包含核心分析逻辑。
- 创建 agent_runtime 内部 Agent 抽象层骨架。
- 创建 ms_agent_framework_adapter 适配层骨架，不安装、不依赖、不实现 Microsoft Agent Framework workflow。
- 创建 multi_agent_workflows 多 Agent 编排预留骨架。
- 创建 tests/architecture 架构边界测试骨架和空测试目录占位。

### 测试方式

- python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests/architecture
- python3 -m pytest tests/architecture
- rg -n "^\\s*(from|import)\\s+(backend|ms_agent_framework_adapter|multi_agent_workflows|agent_framework)" data_agent_core

### 测试结果

- compileall 通过，所有 Python 骨架文件语法有效。
- pytest 未执行成功，本机 python3 环境未安装 pytest：No module named pytest。
- data_agent_core 禁止 import 边界检查未发现实际 import 匹配。

### 遗留问题

- 远端仓库当前没有任何分支；本地已配置 origin 并创建 feature/project-rules-and-data-agent-skeleton，后续需要在首次 commit 后再推送 dev / feature 分支。
- 当前只完成 Phase 0 骨架，不包含真实文件解析、执行、校验、后端接口业务逻辑或 Benchmark 评测逻辑。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程。

### 是否涉及 Benchmark

仅新增 Benchmark 规则文档和骨架文件，未读取、修改或依赖 Benchmark 数据。

### 是否涉及 Microsoft Agent Framework

仅新增适配层骨架和说明文档，未安装依赖，未实现 workflow，核心算法不依赖 Microsoft Agent Framework。

### 是否影响未来多 Agent 迁移

是，正向预留 agent_runtime、ms_agent_framework_adapter 和 multi_agent_workflows 边界；未启用复杂多 Agent。

### 是否修改核心数据契约

是，新增 contracts 草案文件，用于后续稳定交互契约。

### 是否修改 API 契约

是，新增 docs/API_CONTRACT.md 和 backend schema 骨架。

### 是否新增或修改错误类型

是，新增 data_agent_core/errors/error_types.py 错误类型草案。

### 是否新增或修改运行追踪逻辑

是，新增 run_trace.py 和 trace_writer.py 的运行追踪草案；未实现真实写入逻辑。

---

### 日期

2026-05-21

### 本次目标

按项目主目标把单 Agent 核心链路明确调整为 LLM + 规则 + 代码分工：LLM Intent Parser、LLM + 规则 Column Mapping、LLM Analysis Planner、代码 Pandas / SQL 执行、代码 Result Normalizer、规则 + LLM Verifier / Critic、规则 + LLM Correction Planner、LLM Insight Generator、LLM + 规则 Chart Planner，最后返回 JSON；同时把该链路映射到未来多 Agent 角色。

### 修改文件

- MAIN_GOAL.md
- docs/ARCHITECTURE.md
- docs/API_CONTRACT.md
- docs/FEATURE_BACKLOG.md
- data_agent_core/README.md
- data_agent_core/prompts/data_agent_system_prompt.md
- data_agent_core/llm/client.py
- data_agent_core/llm/planner.py
- data_agent_core/agent/single_agent.py
- data_agent_core/core/analysis_planner.py
- data_agent_core/tracing/run_trace.py
- agent_runtime/README.md
- ms_agent_framework_adapter/README.md
- multi_agent_workflows/README.md
- tests/core/test_dabstep_core.py
- CHANGELOG_AI.md

### 修改内容

- 将 MAIN_GOAL.md 的核心工作流改为用户指定的 LLM / 规则 / 代码链路。
- 更新 README，说明 prompt 路径、单 Agent 链路和 mock / 真实 LLM 的运行方式。
- 在架构文档中补充单 Agent 每个阶段的职责分工，以及未来多 Agent 的角色映射。
- 更新 API 契约，说明 debug 可包含 single_agent_chain、llm_stage_summaries、column_mapping，但前端不能依赖 debug 作为稳定展示契约。
- 更新 prompt，明确 LLM 只服务当前 stage，不输出完整 Chain of Thought，不使用 Benchmark task_id 或标准答案。
- 增加通用 LLM stage helper，用于 intent_parser、column_mapping、verifier_critic、correction_planner、insight_generator、chart_planner 等阶段。
- 更新单 Agent 编排，使 trace/debug 中可看到完整单 Agent 链路和各 LLM 阶段摘要。
- 扩展 RunTrace 字段，记录 intent、column mapping、analysis planner、result normalizer、verifier critic、correction planner、insight、chart plan 等摘要。
- 更新 agent_runtime、ms_agent_framework_adapter、multi_agent_workflows README，使未来多 Agent 角色与当前主目标一致。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_dabstep_core
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --output-dir outputs/dabstep_core_mvp_llm_chain
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- rg -n "^\\s*(from|import)\\s+(backend|ms_agent_framework_adapter|multi_agent_workflows|agent_framework)" data_agent_core
- rg secret-pattern scan against repository files excluding outputs/

### 测试结果

- unittest 通过：Ran 2 tests in 1.825s，OK。
- DABstep dev 前 10 题通过本地评分：total=10，scored=10，correct=8，accuracy=0.8。
- compileall 通过。
- data_agent_core 禁止 import 边界检查未发现实际 import 匹配。
- secret 扫描未发现提供过的 key 或 key 片段进入仓库文件。

### 遗留问题

- 当前 LLM stage 已接入链路和 trace，但真实 DeepSeek / OpenAI 运行需要用户在本地 shell 通过环境变量提供 key。
- 当前 dev 前 10 题达到 80%，尚未验证完整 450 题。
- 远端 dev 分支仍不存在，后续需要补齐 dev 和 feature 分支推送流程。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端或复杂后端业务。

### 是否涉及 Benchmark

是。继续使用 DABstep dev 前 10 题验证核心算法正确率；标准答案只在 evaluator 评分阶段使用，不进入核心分析链路或 LLM 输入。

### 是否涉及 Microsoft Agent Framework

仅更新适配层 README 的未来映射说明；未安装、未 import、未实现 Microsoft Agent Framework workflow。

### 是否影响未来多 Agent 迁移

是，正向影响。当前单 Agent 阶段已和未来 Planner、Data Engineer、Executor、Verifier、Correction、Insight、Visualization、Benchmark Agent 的职责对齐。

### 是否修改核心数据契约

是。扩展 RunTrace 运行追踪契约；未破坏 FinalResponse 稳定字段。

### 是否修改 API 契约

是。docs/API_CONTRACT.md 补充 debug 中的 LLM 阶段摘要字段，并继续声明前端不能依赖 debug。

### 是否新增或修改错误类型

否。本轮未新增错误类型。

### 是否新增或修改运行追踪逻辑

是。新增单 Agent 各阶段 trace 摘要，仍只记录 structured analysis plan、reasoning summary、execution trace、verification notes，不记录完整 Chain of Thought。

---

### 日期时间

2026-05-21 11:41 CST

### 本次目标

按用户要求补齐 dev 分支、把 LLM key 写入本地 ignored env 文件以便服务器运行、对照 DABstep 官方 scorer 地址，并单独检查 all.jsonl 第 11 到 20 题。

### 修改文件

- BRANCH_RULES.md
- docs/BENCHMARK_RULES.md
- data_agent_core/benchmark/benchmark_runner.py
- data_agent_core/agent/single_agent.py
- data_agent_core/core/intent_parser.py
- data_agent_core/output/response_builder.py
- tests/core/test_dabstep_core.py
- CHANGELOG_AI.md

### 修改内容

- 从 origin/main 创建 origin/dev，并创建本地 tracking 分支 dev。
- 创建本地 .env.local 保存 DeepSeek / OpenAI 运行配置；该文件被 .gitignore 的 .env.* 规则忽略，不进入 Git。
- 对照 DABstep 官方 scorer 地址记录 benchmark scorer 来源。
- benchmark runner 新增 offset 参数，用于运行 all.jsonl 的指定区间，例如第 11 到 20 题。
- 修复 LLM LogicForm guardrail：LLM 不再覆盖确定性 output_format，只能补充缺失字段。
- 修复 response formatter 在执行值为 None 时的失败，统一返回 Not Applicable。
- 增加 grouped by aci 等通用 group_by 解析，避免固定写成 shopper_interaction。
- 增加测试覆盖 all split offset=10 对应第 11 到 20 题。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_dabstep_core
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/dabstep_core_mvp_dev_after_offset_fix
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 10 --offset 10 --output-dir outputs/dabstep_core_mvp_mock_11_20
- source .env.local 后运行 /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 10 --offset 10 --output-dir outputs/dabstep_core_mvp_llm_real_11_20_after_fix
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- rg -n "^\\s*(from|import)\\s+(backend|ms_agent_framework_adapter|multi_agent_workflows|agent_framework)" data_agent_core
- rg secret-pattern scan against repository files excluding outputs/

### 测试结果

- unittest 通过：Ran 3 tests in 8.048s，OK。
- DABstep dev 前 10 题仍为 8/10，accuracy=0.8。
- DABstep all 第 11 到 20 题可生成真实 LLM 预测，但 public all.jsonl 的 answer 字段为空，因此 scored=0，accuracy=null。
- all 第 11 到 20 题真实 LLM 输出文件：outputs/dabstep_core_mvp_llm_real_11_20_after_fix/all_11_to_20_predictions.jsonl。
- compileall 通过。
- data_agent_core 禁止 import 边界检查未发现实际 import 匹配。
- secret 扫描未发现提供过的 key 或 key 片段进入仓库文件；.env.local 为 ignored 文件。

### 遗留问题

- all.jsonl 第 11 到 20 题没有本地标准答案，不能计算真实准确率。
- 第 15 题当前返回 Not Applicable 且 success=false，需要后续做通用 best_fraud_aci_choice 能力分析，不能按单题特判。
- 第 20 题当前为 not_applicable，需要后续补充通用 cheapest-card-scheme average scenario 能力，不能按单题特判。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端或复杂后端业务。

### 是否涉及 Benchmark

是。新增 offset 支持并检查 DABstep all 第 11 到 20 题；未把 task_id 或 answer 传入核心分析链路或 LLM。

### 是否涉及 Microsoft Agent Framework

否。未安装、未 import、未实现 Microsoft Agent Framework workflow。

### 是否影响未来多 Agent 迁移

是，正向影响。LLM 输出被 guardrail 限制，便于未来 Planner Agent 和 Data Engineer Agent 分工。

### 是否修改核心数据契约

否。本轮未新增核心 contract 字段。

### 是否修改 API 契约

否。本轮未修改 API 稳定字段。

### 是否新增或修改错误类型

否。本轮未新增错误类型。

### 是否新增或修改运行追踪逻辑

否。本轮未新增 trace 字段，但第 11 到 20 题生成了新的 trace 输出。

---
