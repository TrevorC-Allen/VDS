# ARCHITECTURE

## 当前阶段

当前只定义 Data Agent 的工程边界和扩展方向，不实现复杂业务逻辑。

## 层次边界

1. data_agent_core 是核心算法层。
2. backend 是调用壳，只负责接收请求、临时文件管理、调用核心层和返回结构化 JSON。
3. agent_runtime 是项目内部 Agent 抽象层。
4. ms_agent_framework_adapter 是未来 Microsoft Agent Framework 适配层。
5. multi_agent_workflows 是未来多 Agent 编排目录。
6. docs 是工程契约和扩展需求管理目录。

## 依赖规则

1. data_agent_core 不依赖 backend。
2. data_agent_core 不依赖 ms_agent_framework_adapter。
3. data_agent_core 不依赖 multi_agent_workflows。
4. data_agent_core 不依赖 Microsoft Agent Framework。
5. 核心算法保持框架无关。
6. Microsoft Agent Framework 适配层可以调用 agent_runtime 和 data_agent_core，但不能承载核心算法。
7. multi_agent_workflows 可以组合 agent_runtime 角色，但不能把核心算法写进 workflow。

## 核心链路

用户上传 CSV / Excel
↓
文件解析
↓
字段画像
↓
用户问题理解
↓
structured analysis plan
↓
Pandas / NumPy 执行路径
↓
SQL / DuckDB 执行路径
↓
结果标准化和一致性校验
↓
reasoning summary、execution trace、verification notes
↓
解释、建议和图表配置
↓
后端 API 返回结构化 JSON

## TODO

- 定义 Phase 1 最小服务入口。
- 实现架构边界测试。
- 在不引入框架依赖的前提下验证核心模块可导入。
