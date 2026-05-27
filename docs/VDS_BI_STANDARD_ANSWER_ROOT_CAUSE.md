# VDS BI 标准答案错误根因与修复计划

## 背景

本文件记录 2026-05-25 对桌面 VDS 中文 BI 错误的复盘、修复计划和验收红线。它用于防止以后再次把 `95/95 smoke`、离线标准答案正确率和当前分支真实能力混为一谈。

涉及数据集：

- 问题集：`/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/问题/问题汇总.xlsx`
- 标准答案：`/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/问题/标准GPT答案汇总.xlsx`
- 数据目录：`/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/数据`

## 错误现象

1. `本周Pro套餐CHR最高的Top10客户？` 这类客户级问题被回答成 `区域 / 订阅收入` 排名。
2. `本周流失和暂停对ARR影响最大的Top10客户？` 没有返回客户名称和状态影响结果，而是退回到默认区域聚合。
3. `看一下这个数据 / 看一下整体销售情况` 曾经返回行数、原始明细或过多字段，主答案不符合用户的概览意图。
4. 当前分支曾缺少 VDS 标准答案 runner / scorer，导致“之前 95/95”没有在当前代码上被直接验证。

## 根因

1. **分支能力回退**：当前分支只保留了较窄的 VDS BI parser / executor 子集，缺失上一版 95/95 所需的 `vds_period_group_comparison`、`vds_current_rank_with_period_change`、`vds_group_top_entities`、`vds_status_impact_top`、`vds_current_top`、`vds_three_period_top` 等通用能力族。
2. **粒度和指标未强绑定**：当问题明确说 `客户 / 门店 / 校区 / 院区 / 站点` 和 `_row` 指标时，旧链路仍可能落到通用 ranking 默认逻辑，从列顺序或宽泛关键词推到 `区域 / 订阅收入`。
3. **筛选语义不足**：`Pro套餐`、`暂停 / 流失 / 正常续费` 等枚举过滤没有统一抽象为可复用 value filters，导致当前期过滤指标 TopN 不能稳定命中实体粒度。
4. **输出层过度压缩**：TopN 结果曾被 Response Builder 压成第一名摘要，导致标准答案和用户期望的完整 Top10 列表丢失。
5. **门禁口径混淆**：`95/95 smoke` 只能证明执行成功，不能证明标准答案正确；标准答案 scorer 必须在当前分支后验复跑，且不能进入核心分析链路。

## 修复计划

### 已完成

1. 恢复并合并 VDS 标准答案所需中文 BI 能力族：
   - 周期排名变化
   - TopN 增加 / 减少
   - 增长数量占比
   - 环比阈值计数
   - 同圈层异常
   - 分组环比变化
   - 各组 Top 实体
   - 状态影响 TopN
   - 三周期 TopN
   - 当前期过滤指标 TopN
2. 扩展 `vds_current_filtered_metric_top`：
   - 按 schema 识别实体列，不靠固定题号或标准答案。
   - 按 `_row` 指标代码识别 `ARR / CHR / NRR / DAU` 等指标。
   - 按枚举值抽取 `Pro套餐`、`暂停`、`流失`、`正常续费` 等过滤条件。
   - 对单字枚举值增加上下文保护，避免把普通字误判为过滤条件。
3. 恢复 VDS 标准答案离线 scorer / runner：
   - 标准答案只在 response 生成后评分。
   - 不向 Agent workflow、prompt、Planner、Executor、Verifier、Correction 或 trace 传入标准答案。
4. 修正输出展示：
   - `candidate_table` 作为结果表格行返回。
   - 当前指标 TopN 主回答输出完整 TopN 列表，不再只输出第一名。
5. 补充架构测试，证明 VDS runner 不把 task_id 或标准答案传给 Agent。

### 后续计划

1. 将真实 provider 大规模 VDS 标准答案回归作为 Phase 7.6 / Phase 10 后续门禁，不能用 mock 结果冒充真实 provider 稳定性。
2. 对更多中文真实业务表扩展字段别名和指标口径，不把当前五个 Excel 的固定字段值当成唯一标准。
3. 将多表 / 多文件问题与单表 VDS BI 问题分开验收，避免把单表 95/95 误报为多表能力完成。
4. 对 Workbench 新增可视回归 smoke，重点覆盖“客户级 TopN 不退回区域”、“概览问题不输出原始明细”、“普通聊天不进入分析链路”。

## 红线

1. 禁止把题号、标准答案、固定文件名、固定客户名、固定门店名、固定输出顺序写入 parser、executor、verifier、prompt 或 trace。
2. 禁止把标准答案作为测试 fixture 去驱动核心逻辑；标准答案只能在 benchmark runner response 之后评分。
3. 禁止只修当前问法。新增逻辑必须抽象成能力族，并至少覆盖同类变体。
4. 禁止把 smoke 成功等同于标准答案正确率；报告必须明确区分 smoke、offline scorer、proxy observation 和 real provider run。
5. 禁止前端实现指标公式、排序、聚合或修正分析结果；前端只能展示后端结构化结果。

## 泛用性验收

当前验收结果：

- `tests.core.test_vds_bi_capabilities` 覆盖销售、学习、物流、SaaS 等合成/同类变体。
- `tests.core.test_vds_standard_scorer` 覆盖 count/share、同圈层异常、状态影响边界 tie 等标准答案后验评分等价性。
- `tests.architecture.test_no_benchmark_hardcoding` 覆盖标准答案隔离和 VDS runner 不泄漏 task_id / answer。
- `outputs/vds_standard_answer_recheck_20260525_core_fix_v2/report.json`：桌面 VDS 五域 95 题标准答案 scorer 为 `95/95`，`success_count=95/95`。

后续任何修改 VDS BI parser / executor / response builder / benchmark runner 的 PR，都必须至少复跑：

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_vds_bi_capabilities tests.core.test_vds_standard_scorer -v
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.architecture.test_dependency_boundaries tests.architecture.test_no_benchmark_hardcoding tests.architecture.test_no_secrets -v
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.vds_desktop_benchmark_runner --question-workbook "/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/问题/问题汇总.xlsx" --answer-workbook "/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/问题/标准GPT答案汇总.xlsx" --data-root "/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/数据" --output-dir outputs/vds_standard_answer_recheck_<date>
```
