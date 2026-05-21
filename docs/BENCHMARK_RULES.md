# BENCHMARK RULES

## 当前阶段

当前只创建 Benchmark 规则文档和骨架目录，不接入 450 题数据，不读取标准答案，不实现评测逻辑。

2026-05-21 更新：已新增 DABstep 本地前 10 题 runner。runner 只在评分阶段读取 answer 字段；核心分析链路只接收 question、guidelines 和上下文数据。

2026-05-21 更新：Agent 已新增 LLM planning layer。benchmark runner 不会把 task_id 或 answer 字段传给 LLM；LLM 只接收 question、guidelines、context_summary 和 supported_operations。

2026-05-21 更新：DABstep public scorer 地址为 https://huggingface.co/spaces/adyen/DABstep/blob/main/dabstep_benchmark/evaluation/scorer.py。本地 evaluator 的 question_scorer 需要保持与该 scorer 的归一化、数字容差、列表比较和字符串相似度规则一致。

2026-05-21 更新：Phase 3 最小 metrics 和 error_analysis 已落地。报告按 operation 和 error_type 聚合，只输出通用能力缺口，不生成单题修复建议。

## 使用原则

1. Benchmark 只能用于评测和错误归因。
2. 禁止单题硬编码。
3. 禁止把标准答案泄漏给分析 Agent。
4. Benchmark 结果必须按错误类型统计。
5. Benchmark 优化必须修通用模块。
6. Benchmark 不参与线上用户请求。

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

Benchmark 只能帮助发现通用问题，例如字段识别、时间解析、TopN 排序、聚合口径、多表合并和中文字段别名识别。

## TODO

- 继续对齐官方 scorer 的边界行为。
- 增加 backend、verification issue、latency 的聚合维度。
- 当有官方隐藏答案或提交反馈时，只把结果用于通用模块改进，不按题号优化。

## 本地运行命令

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --output-dir outputs/dabstep_core_mvp
```

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 10 --offset 10 --output-dir outputs/dabstep_core_mvp_11_20
```

真实 LLM 运行时，先在本地 shell source 被 Git 忽略的 .env.local，再执行同一 benchmark 命令。不要把真实 key 写进命令、文档、trace 或 Git。
