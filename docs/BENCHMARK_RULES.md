# BENCHMARK RULES

## 当前阶段

当前只创建 Benchmark 规则文档和骨架目录，不接入 450 题数据，不读取标准答案，不实现评测逻辑。

2026-05-22 更新：已新增 DABstep 多 Agent runner 和 Microsoft 脱敏数据离线 runner。runner 只在评分阶段读取 answer 字段；核心分析链路只接收 question、guidelines 和上下文数据。

2026-05-21 更新：Agent 已新增 LLM planning layer。benchmark runner 不会把 task_id 或 answer 字段传给 LLM；LLM 只接收 question、guidelines、context_summary 和 supported_operations。

2026-05-21 更新：DABstep public scorer 地址为 https://huggingface.co/spaces/adyen/DABstep/blob/main/dabstep_benchmark/evaluation/scorer.py。本地 evaluator 的 question_scorer 需要保持与该 scorer 的归一化、数字容差、列表比较和字符串相似度规则一致。

2026-05-21 更新：Phase 3 最小 metrics 和 error_analysis 已落地。报告按 operation 和 error_type 聚合，只输出通用能力缺口，不生成单题修复建议。

2026-05-21 更新：Benchmark 优化的禁止范围扩展为“禁止伪泛化补丁”。即使没有显式使用 task_id、题号或标准答案，只要补丁只能覆盖当前数据集、当前字段值、当前候选项、当前问法或当前错误样本，就不能算作能力提升。

2026-05-25 更新：新增上传式 Benchmark 规则最小链路。Benchmark 规则文件必须显式标记为 `file_role=rule, rule_scope=benchmark`，并只能通过独立 `POST /api/data-agent/benchmark/run` 读取。普通 Chat / `/message` 不会读取 benchmark rule；如果把 benchmark rule 当作 `user_rule_file_id` 传入普通分析，后端必须拒绝。

## 使用原则

1. Benchmark 只能用于评测和错误归因。
2. 禁止单题硬编码，也禁止只适配当前错误样本的伪泛化逻辑。
3. 禁止把标准答案泄漏给分析 Agent。
4. Benchmark 结果必须按错误类型统计。
5. Benchmark 优化必须修通用模块，并说明能力可迁移到哪些同类数据集、同类字段和同类问法。
6. Benchmark 不参与线上用户请求。
7. Benchmark rule、expected output、metrics 和 threshold 只允许进入 Benchmark Runner / report，不允许进入普通 Agent Analyst 上下文。
8. 用户分析规则只有在 Benchmark 任务显式传入 `user_rule_file_id` 时才作为 Agent 分析约束；不能被当作评分规则。

## 特调定义

以下都视为特调或伪泛化，不能进入核心链路：

1. 使用 task_id、题号、标准答案、隐藏答案推测或 public proxy answer pool。
2. 根据固定题面、固定关键词组合、固定候选项顺序或固定输出字面值写分支。
3. 根据当前数据集里的固定字段值、固定商户、固定国家、固定 ACI code、固定 fee id 或固定行分布写规则。
4. 只让当前失败题目变对，但无法解释如何迁移到其他上传数据集或同类 benchmark slice。
5. 通过放宽 verifier、降低校验标准、吞掉错误、返回 Not Applicable 或改格式来隐藏能力缺口。

可接受的改动必须满足：

1. 抽象为能力族，例如字段枚举、比例计算、候选表排序、fee what-if、ACI 极值选择、数据质量检查。
2. 使用 schema / LogicForm / metric_definition / candidate_table / verifier 证据驱动，而不是当前样本值驱动。
3. 至少包含一个非 Benchmark 或合成用例，证明同类数据和同类问法可以复用。
4. 旧代表用例不能退化。

## 指标草案

- exactness
- tolerance_match
- column_match
- row_match
- semantic_match
- execution_success
- correction_success
- latency
- error_type
- backend

## 错误归因方向

Benchmark 只能帮助发现通用问题，例如字段识别、时间解析、TopN 排序、聚合口径、多表合并和中文字段别名识别。错误归因必须写成“能力族缺口 + 泛化验证方式”，不能写成“某题应输出某答案”。

## TODO

- 继续对齐官方 scorer 的边界行为。
- 增加 backend、verification issue、latency 的聚合维度。
- 当有官方隐藏答案或提交反馈时，只把结果用于通用模块改进，不按题号、固定样本值或当前错误形态优化。
- 报告中增加“泛化验证建议”，要求每类失败至少对应一个合成/非 Benchmark 用例。

## 本地运行命令

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/dabstep_dev10_current
```

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 450 --offset 0 --output-dir outputs/dabstep_all_1_450_mock_current
```

真实 LLM 运行时，先在本地 shell source 被 Git 忽略的 .env.local，再执行同一 benchmark 命令。不要把真实 key 写进命令、文档、trace 或 Git。
