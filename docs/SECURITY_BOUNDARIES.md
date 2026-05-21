# SECURITY BOUNDARIES

## 当前阶段

当前不执行危险代码，不开放任意 Python / SQL / shell / 网络访问。受控工具层已有白名单、参数校验、timeout_seconds 执行边界和 trace-safe 摘要；生产级资源隔离沙箱仍未实现。

## 安全要求草案

1. 当前不执行危险代码。
2. Python 执行必须有白名单、超时和资源限制。
3. 禁止网络请求。
4. 禁止访问非工作目录文件。
5. 上传文件需要大小限制。
6. 敏感字段后续需要脱敏策略。
7. 执行器未来必须运行在更严格的受控环境。
8. LLM API key 只能通过环境变量提供，不允许写入仓库、文档、trace、CHANGELOG 或测试输出。
9. benchmark runner 不允许把 task_id 或 answer 字段传给 LLM。

## TODO

- 定义 Pandas / NumPy 白名单函数。
- 定义 SQL / DuckDB 查询限制。
- 定义文件访问根目录。
- 继续增强执行资源限制；当前 ToolDispatcher 已有 timeout_seconds 执行边界，但未实现 CPU / 内存级隔离。
