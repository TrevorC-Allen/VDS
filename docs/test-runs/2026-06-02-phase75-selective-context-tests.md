# Phase 7 selective phase75 context regression

日期：2026-06-02

分支：`codex/merge-phase75-selective-context-tests`

基线：本地 `dev`，commit `b6478d6`

## 范围

本轮没有整体 merge `codex/vds-phase75-plus-impl`。该分支只作为能力来源，选择性移植当前 `dev` 缺失且可复用的低风险能力。

已移植或修复：

- data quality 扫描：布尔/类布尔字段不进入数值离群值扫描，负值样例在缺失值后保持索引对齐，IQR 离群值边界改为 1.5 倍。
- DuckDB runtime：新增只读 SELECT/CTE 校验、危险关键字/外部读取拦截、内存表注册、结果行数限制和可用性探测。
- provider-native tool loop：新增 OpenAI-compatible `/chat/completions` tool smoke client、env loader、reasoning 字段剥离。
- tool dispatcher 安全边界：新增嵌套 schema/enum 校验、危险 argument key 拦截、敏感 trace/output/error 脱敏。
- Microsoft Agent Framework adapter：新增 adapter-only demo plan，明确 adapter 不拥有 parser/executor/scorer 等核心算法。
- multi-agent correction：新增可配置 bounded correction attempts，默认仍为 1 次，保留当前 monitor/activity trace/cancel 行为。
- DABstep fee engine：新增 fraud ACI associated-cost 明细方法，默认 ACI 候选边界仍保持 D/E。
- 随机多轮追问 eval：支持 smoke 模式按实际 turn budget 裁剪 required capability family，不再用完整场景要求误杀 `max-followups=1`。
- 随机多轮追问 eval：将 `dataset_source_overview` 纳入 `dataset_overview` 等价操作，适配真实 LLM 对数据源概览的合法命名。
- 通用金额排名追问：`订单总额/金额排名 + 各自客户数量/客户总数` 保持主指标为金额，客户数作为 supplemental metric，不误转为 grouped child ranking 或 count 主指标。
- LLM planner：直接 `plan_with_llm` / `complete_stage_with_llm` 遇到 provider JSON 失败时降级为不泄漏 provider 原文的 fallback，同时保留当前 redaction 边界。
- LLM planner allowlist：补齐当前 VDS BI executor/registry 已支持但 planner 未接受的 operation，避免真实 API 规划结果被误降级为 `not_applicable`。

未移植：

- 未整体覆盖 `frontend/*`。
- 未修改 `README`、`MAIN_GOAL.md`、`CHANGELOG_AI.md`。
- 未移植 `phase75` 中会删除当前 `dev` 能力或降低 reasoning trace redaction 的变更。

## 已合入分支确认

`codex/vds-fix-download-artifacts-button`：

- `git merge-base --is-ancestor codex/vds-fix-download-artifacts-button dev` 返回 0。
- `git rev-list --count dev..codex/vds-fix-download-artifacts-button` 返回 0。

`codex/vds-p0-file-semantic-correction`：

- `git merge-base --is-ancestor codex/vds-p0-file-semantic-correction dev` 返回 0。
- `git rev-list --count dev..codex/vds-p0-file-semantic-correction` 返回 0。

因此这两个分支本轮只作为回归基线，没有产生重复 merge commit。

## 验证命令与结果

综合回归：

```bash
rtk test /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_tests.py tests.core.test_data_quality tests.core.test_duckdb_runtime tests.backend.test_data_agent_api_status tests.backend.test_p0_workspace_runtime tests.backend.test_workbench_static_assets tests.benchmark.test_agent_random_conversation_eval tests.core.test_uploaded_table_agent tests.agent_runtime.test_tool_calling_contracts tests.ms_agent_framework_adapter.test_framework_adapter tests.multi_agent_workflows.test_phase6_multi_agent_workflow tests.core.test_generic_capability_operations
```

结果：

- Ran 286 tests
- OK
- skipped=10

补充 LLM planner 回归：

```bash
rtk test /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_tests.py tests.core.test_llm_planner tests.core.test_llm_client
```

结果：

- Ran 6 tests
- OK

补充综合回归：

```bash
rtk test /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_tests.py tests.core.test_data_quality tests.core.test_duckdb_runtime tests.backend.test_data_agent_api_status tests.backend.test_p0_workspace_runtime tests.backend.test_workbench_static_assets tests.benchmark.test_agent_random_conversation_eval tests.core.test_uploaded_table_agent tests.agent_runtime.test_tool_calling_contracts tests.ms_agent_framework_adapter.test_framework_adapter tests.multi_agent_workflows.test_phase6_multi_agent_workflow tests.core.test_generic_capability_operations tests.core.test_llm_planner tests.core.test_llm_client
```

结果：

- Ran 292 tests
- OK
- skipped=10

随机多轮追问 smoke：

```bash
rtk test /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_agent_random_conversation_eval.py --seed 20260602 --scenario-count 1 --runs-per-scenario 1 --max-followups 1 --min-pass-rate 0.95 --min-conversations 1 --min-capability-families 1 --min-followup-turns 1 --min-structured-action-turns 1 --output-dir /tmp/vds-phase75-random-eval/smoke-seed-20260602 --simulator-provider deterministic --agent-provider mock --print-summary
```

结果：

- pass_rate=100%
- conversation_count=1
- missing_context_turns=0

随机多轮追问全量：

```bash
rtk test /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_agent_random_conversation_eval.py --seed 20260602 --scenario-count 0 --runs-per-scenario 3 --max-followups 5 --min-pass-rate 0.95 --min-conversations 9 --min-capability-families 3 --min-followup-turns 9 --min-structured-action-turns 9 --output-dir /tmp/vds-phase75-random-eval/full-seed-20260602 --simulator-provider deterministic --agent-provider mock --print-summary
```

结果：

- pass_rate=100%
- conversation_count=9
- scenario_count=3
- runs_per_scenario=3
- contextualized_turns=30
- missing_context_turns=0

稳定性 seed：

- seed `20260603`：pass_rate=100%，conversation_count=9，missing_context_turns=0。
- seed `20260604`：pass_rate=100%，conversation_count=9，missing_context_turns=0。

真实 API 随机多轮追问：

环境：

- `VDS_LLM_PROVIDER=deepseek`
- `DEEPSEEK_API_KEY` 存在，未记录密钥内容。

smoke：

```bash
rtk test /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_agent_random_conversation_eval.py --seed 20260602 --scenario-count 1 --runs-per-scenario 1 --max-followups 1 --min-pass-rate 0.95 --min-conversations 1 --min-capability-families 1 --min-followup-turns 1 --min-structured-action-turns 1 --output-dir /tmp/vds-phase75-random-eval-real/smoke-seed-20260602 --simulator-provider deterministic --agent-provider env --print-summary
```

结果：

- pass_rate=100%
- conversation_count=1
- missing_context_turns=0

全量 5 轮：

```bash
rtk test /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_agent_random_conversation_eval.py --seed 20260602 --scenario-count 0 --runs-per-scenario 5 --max-followups 5 --min-pass-rate 0.95 --min-conversations 15 --min-capability-families 3 --min-followup-turns 15 --min-structured-action-turns 15 --output-dir /tmp/vds-phase75-random-eval-real/full-seed-20260602-runs5-v2 --simulator-provider deterministic --agent-provider env --print-summary
```

结果：

- passed=true
- pass_rate=100%
- passed_count=15
- conversation_count=15
- scenario_count=3
- runs_per_scenario=5
- contextualized_turns=50
- followup_turns=35
- missing_context_turns=0
- global_issues=[]
- 覆盖 capability families：derived_metric_followup, multi_file_overview, multi_table_join_ranking, overview, quality, ranking, ranking_followup, trend_followup。
- 覆盖 operations：aggregation, cleaning_policy, dataset_overview, dataset_source_overview, quality_summary, ranking。

补充全量 5 轮：

```bash
rtk test /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_agent_random_conversation_eval.py --seed 20260602 --scenario-count 0 --runs-per-scenario 5 --max-followups 5 --min-pass-rate 0.95 --min-conversations 15 --min-capability-families 3 --min-followup-turns 15 --min-structured-action-turns 15 --output-dir /tmp/vds-phase75-random-eval-real/full-seed-20260602-runs5-v3 --simulator-provider deterministic --agent-provider env --print-summary
```

结果：

- passed=true
- pass_rate=100%
- passed_count=15
- conversation_count=15
- turn_count=65
- requested_followup_turns=35
- followup_turns=35
- missing_followup_context_turns=0
- contextualized_post_initial_turns=50
- missing_post_initial_context_turns=0
- structured_action_turns=51
- structured_answer_turns=65
- elapsed_seconds=710.028
- global_issues=[]
- HTML 报告：`/tmp/vds-phase75-random-eval-real/full-seed-20260602-runs5-v3/index.html`

## 边界和风险

- 本轮已执行 deterministic simulator + mock agent provider，也执行 deterministic simulator + env agent provider 真实 API 验证。
- DuckDB 是可选依赖；单测覆盖了未安装时抛出 `DuckDBRuntimeUnavailable` 的边界。
- LLM planner fallback 只记录错误类型，不记录 provider 原始内容、raw prompt、hidden reasoning 或 benchmark 答案字段。
- `phase75` 大量删除/覆盖项未移植，后续如继续挑选能力，应继续逐文件按当前 `dev` 结构移植。
