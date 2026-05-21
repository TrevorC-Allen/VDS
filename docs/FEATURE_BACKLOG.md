# FEATURE BACKLOG

## 当前阶段

后续新增功能点统一记录在这里。新功能不能只散落在聊天记录里。

## 功能记录格式

每个功能点需要记录：

1. 目标
2. 影响模块
3. 优先级
4. 验收标准
5. 风险
6. 是否影响 contracts
7. 是否影响 API_CONTRACT
8. 是否影响 tracing
9. 是否影响 errors

## Backlog

### CSV / Excel 文件解析

目标：支持上传文件解析并生成 DatasetProfile。

影响模块：data_agent_core/core/file_parser.py、schema_profiler.py、backend。

优先级：P1。

验收标准：能对 csv / xlsx 返回稳定字段画像。

风险：表头识别、编码识别、多 sheet 处理。

### 双执行路径

目标：支持 Pandas / NumPy 和 SQL / DuckDB 两条执行路径。

影响模块：executors、verifier、contracts。

优先级：P1。

验收标准：两条路径能返回可比较的标准 ExecutionResult。

风险：数值精度、排序、空值和日期标准化。

### Benchmark Runner

目标：接入 450 题 Benchmark 评测和错误归因。

影响模块：benchmark、errors、tracing。

优先级：P3。

验收标准：输出按错误类型统计的评测报告。

风险：禁止标准答案泄漏和单题硬编码。

## TODO

- 新功能进入开发前，先确认是否影响 contracts / API_CONTRACT / tracing / errors。
