# Git Clean Regression - 2026-06-01

- Status: passed
- Branch: `codex/vds-fix-download-artifacts-button`
- CWD: `/Users/trevorcui/Documents/VDS`
- Runtime verified: targeted unittest modules
- URL: not applicable
- Generated at: 2026-06-01 13:23 CST

## Scope

本轮按用户要求收口当前 dirty worktree，并在提交前验证当前未提交业务改动。

实际修复的回归点：

- 显式 dataset overview / shape 问法优先进入 overview，避免被新增 calculation / quality diagnostic 语义误路由到 table analysis。
- fee calculation 问法继续进入 analysis，避免被 `fees.json` source overview 抢走。
- 英文月份解析改为独立词匹配，避免 `Martinis_Fine_Steakhouse` 中的 `mar` 被误判为 March。
- 明确写在问题里的派生指标列名优先级高于泛化 sales / amount 偏好，保证项目净销售额按已应用项目公式排序。
- 结构化 follow-up actions 贯穿 insight、runtime、conversation store，保证 clean checkout 中引用模块完整。

## Focused Checks

```bash
python3 scripts/run_tests.py tests.backend.test_data_agent_service.DataAgentServiceTest.test_broad_dataset_readiness_questions_do_not_return_row_count_only tests.backend.test_data_agent_service.DataAgentServiceTest.test_multi_file_shape_question_returns_gpt_like_counts_not_value_dump tests.backend.test_data_agent_service.DataAgentServiceTest.test_project_memory_formula_affects_dataset_calculation tests.backend.test_data_agent_service.DataAgentServiceTest.test_card_scheme_steering_monthly_scope_question_2644_passes_verifier tests.backend.test_data_agent_service.DataAgentServiceTest.test_card_scheme_steering_monthly_scope_with_explicit_year_passes_verifier
```

Result: `Ran 5 tests in 12.694s - OK`.

```bash
python3 scripts/run_tests.py tests.backend.test_data_agent_service.DataAgentServiceTest.test_dabstep_total_fees_question_uses_analysis_not_source_overview
```

Result: `Ran 1 test in 1.454s - OK`.

```bash
python3 scripts/run_tests.py tests.backend.test_data_agent_api_status tests.backend.test_data_agent_message_semantics tests.backend.test_data_agent_service tests.backend.test_p0_workspace_runtime tests.backend.test_workbench_static_assets tests.core.test_chinese_retail_capabilities tests.core.test_phase10_result_experience tests.core.test_phase8_multitable_capabilities tests.core.test_text_answer_framework
```

Result: `Ran 220 tests in 146.764s - OK (skipped=5)`.

```bash
python3 scripts/run_tests.py tests.agent_runtime.test_runtime_contracts tests.backend.test_data_agent_message_semantics tests.core.test_phase10_result_experience
```

Result: `Ran 46 tests in 18.007s - OK`.

```bash
python3 scripts/run_tests.py tests.backend.test_data_agent_service tests.backend.test_data_agent_api_status tests.backend.test_data_agent_message_semantics tests.core.test_phase10_result_experience
```

Result: `Ran 121 tests in 197.360s - OK (skipped=5)`.

```bash
python3 scripts/run_tests.py tests.backend.test_workbench_static_assets tests.backend.test_data_agent_message_semantics tests.core.test_phase10_result_experience
```

Result: `Ran 72 tests in 35.492s - OK`.

## Pending Gates

- Full `scripts/run_tests.py` discover across every test module.
- Browser runtime validation for `/workbench`.
- Benchmark comparison scorer artifacts.

## Residual Risks

- 本轮没有扩大到 benchmark scorer 或浏览器端人工验证。
- 当前提交包含此前已存在的多模块 dirty diff；本测试证据覆盖本轮收口前的主要后端/core/frontend static 回归模块。
