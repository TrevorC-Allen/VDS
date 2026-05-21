# BENCHMARK RULES

## 当前阶段

当前只创建 Benchmark 规则文档和骨架目录，不接入 450 题数据，不读取标准答案，不实现评测逻辑。

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

- Phase 3 实现 benchmark_runner.py。
- Phase 3 实现 evaluator.py 和 metrics.py。
- Phase 3 输出按错误类型聚合的 regression report。
