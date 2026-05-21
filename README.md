# VDS Data Agent

本仓库用于从头构建可评测、可复现、可扩展的数据分析 Agent 内核。

当前阶段是 Phase 0：只建立项目规则、核心目录骨架、契约、错误体系、运行追踪、最小后端 API、内部 Agent 抽象、Microsoft Agent Framework 适配层预留、多 Agent workflow 预留和架构边界测试骨架。

当前不实现复杂业务逻辑，不引入新依赖，不安装 Microsoft Agent Framework，不修改旧 BigCat / VDS 主流程。

TODO:
- Phase 1 实现 CSV / Excel 文件解析、字段画像和最小 API。
- Phase 2 实现单 Agent MVP。
- Phase 3 接入 Benchmark 评测，但禁止单题硬编码。
- Phase 4 验证 Microsoft Agent Framework adapter 不污染核心算法。
