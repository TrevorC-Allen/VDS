# Phase 12 Correctness + Overview Hardening - 2026-05-28

- Status: pass
- Branch: `codex/vds-p0-p1-correctness-overview`
- CWD: `/Users/trevorcui/Documents/VDS`
- Runtime verified: `/Users/trevorcui/.vds-workbench-runtime/VDS`
- URL: `http://127.0.0.1:8001/workbench`
- Generated at: 2026-05-28 14:55 CST

## Scope

本轮是 Phase 12 后续 correctness + GPT-like hardening，重点不是只改 overview 模板，而是先守住语义正确性：

- P0：点名文件后不能串维度；`qa_store_b.csv里面哪个产品销售额最高？` 必须按 product 回答 `香蕉 90`。
- P0：利润率不能用 raw sales/profit 排名；必须按 `sum(profit)/sum(sales)` 或明确无法确认。
- P0：同结构多文件合并不能被 verifier 误杀；`A店和B店合起来哪个产品销售额最高？` 必须返回 `苹果 180`。
- P1：时间趋势图表必须按 month 聚合，图表 x 和 data 不能一边说 month 一边放 city。
- P1：缺失字段守卫不能把不存在的“渠道”替换成 city。
- P1：可信 join 和多跳 join 可执行；不可信 join 返回候选关联键和风险，不能 `success=true`。
- P2：overview 区分可计算事实表、维表、说明或元数据表；简单 Top1 回答去掉审计模板噪声。
- 红线：`success=true` 不能绕过语义错算；已修能力不得下降。

## Test Commands

```bash
/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_phase8_multitable_capabilities tests.backend.test_data_agent_message_semantics
```

Result: `Ran 34 tests in 0.539s OK`.

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_tests.py
```

Result: `Ran 347 tests in 36.364s OK (skipped=1)`.

```bash
node --check frontend/app.js
git diff --check
```

Result: no output, both passed.

## Benchmark Gates

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.vds_desktop_benchmark_runner \
  --question-workbook '/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/问题/问题汇总.xlsx' \
  --answer-workbook '/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/问题/标准GPT答案汇总.xlsx' \
  --data-root '/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/数据' \
  --output-dir outputs/phase12_correctness_vds95_20260528_1455
```

Result: `95/95`, accuracy `1.0`, success_count `95`.

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.microsoft_anonymized_benchmark_runner \
  --dataset-root '/Users/trevorcui/Desktop/微软脱敏数据' \
  --limit 300 --offset 0 \
  --output-dir outputs/phase12_correctness_microsoft300_20260528_1455
```

Result: `300/300`, accuracy `1.0`, success_count `300`, semantic_mismatch `0`, format_mismatch `0`.

## Non-DAB Regression Check

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.microsoft_anonymized_benchmark_runner \
  --dataset-root '/Users/trevorcui/Desktop/微软脱敏数据' \
  --test-set '/Users/trevorcui/Desktop/微软脱敏数据/VDS_可视化周期性问题_20260525/微软数据集_可视化和周期性问题_问题和标准答案.jsonl' \
  --output-dir outputs/phase12_correctness_non_dab_visual_periodic_20260528_1455 \
  --execution-mode auto
```

Result: `0/40`, success_count `29`; previous same-turn baseline was `0/40`, success_count `28`.

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.microsoft_anonymized_benchmark_runner \
  --dataset-root '/Users/trevorcui/Desktop/微软脱敏数据' \
  --test-set '/Users/trevorcui/Desktop/微软脱敏数据/VDS_高难推理问题_20260525/微软数据集_高难推理问题和标准答案.jsonl' \
  --output-dir outputs/phase12_correctness_non_dab_hard_reasoning_20260528_1455 \
  --execution-mode auto
```

Result: `3/30`, success_count `17`; unchanged from previous same-turn baseline.

## Runtime Validation

Runtime sync and restart:

```bash
scripts/sync_workbench_runtime.sh
launchctl kickstart -k gui/$(id -u)/com.trevorcui.vds.workbench
lsof -iTCP:8001 -sTCP:LISTEN -nP
```

Verified listener: `python3.1` on `127.0.0.1:8001`.

Browser DOM validation with Codex in-app Browser:

- Opened `http://127.0.0.1:8001/workbench`
- Page title: `Virtual Data Scientist Workbench`
- DOM contained `VDS` and upload controls.

Real API smoke on `http://127.0.0.1:8001`:

- `A店和B店合起来哪个产品销售额最高？`
  - HTTP 200, `success=true`, `verification.passed=true`
  - rows: `[{"product":"苹果","sales":180}]`
  - source_tables: `["qa_store_a","qa_store_b"]`
  - answer does not expose `__same_schema_union__`.
- `按月份展示销售额趋势，生成折线图。`
  - HTTP 200, `success=true`
  - dimension: `month`
  - rows/chart data: `2026-01=350`, `2026-02=180`
  - chart: `line`, x=`month`; chart data has no city column.
- `哪个渠道销售额最高？`
  - HTTP 200, `success=false`, `verification.passed=false`
  - answer explicitly says the question asks for `渠道` but the plan bound `城市`; no fake `北京 280` answer.
- `哪个品类总销售额最高？`
  - HTTP 200, `success=true`
  - rows: `[{"category":"水果","sales":180}]`
  - source_tables include `products`; join plan trusted.
- `北京哪个品类销售额最高？`
  - HTTP 200, `success=true`
  - filters: `{"city":"北京"}`
  - rows: `[{"category":"零食","sales":120}]`
  - source_tables: `orders/products/customers`; join plan has 2 trusted steps.

Earlier same-run API smoke also verified:

- `qa_store_b.csv里面哪个产品销售额最高？` returns `香蕉 90`, source table only `qa_store_b`, dimension=`product`.
- `哪个城市利润率最高？` returns `上海` with ratio `0.4`,口径为 `sum(profit)/sum(sales)`.
- trusted `orders.customer_id -> customers.customer_id` city sales join returns `北京 170`.
- untrusted join returns `success=false` and explains candidate join keys / overlap risk.
- overview identifies `1 个可计算表和 2 个说明/规则来源` and marks knowledge/structure xlsx as `说明或元数据表`.

## Residual Risks

- Non-DAB visual/periodic and hard-reasoning suites are still low-accuracy capability-gap suites; this run verifies no regression versus the same-turn baseline, not full support.
- SQL path still does not materialize uploaded-table join plans; trusted join execution remains Pandas-only by design.
- Some user-facing clarification wording is still heavier than ideal for simple failures, but it now preserves the requested missing dimension and does not silently answer a substitute field.
