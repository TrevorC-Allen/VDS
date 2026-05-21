# VDS Data Agent

本仓库用于从头构建可评测、可复现、可扩展的数据分析 Agent 内核。

当前阶段是 Phase 0：只建立项目规则、核心目录骨架、契约、错误体系、运行追踪、最小后端 API、内部 Agent 抽象、Microsoft Agent Framework 适配层预留、多 Agent workflow 预留和架构边界测试骨架。

当前不实现复杂业务逻辑，不引入新依赖，不安装 Microsoft Agent Framework，不修改旧 BigCat / VDS 主流程。

当前 Agent 已包含 LLM 单 Agent 链路：

用户问题
→ LLM Intent Parser
→ LLM + 规则 Column Mapping
→ LLM Analysis Planner
→ 代码 Pandas Executor
→ 代码 SQL / DuckDB Executor
→ 代码 Result Normalizer
→ 规则 + LLM Verifier / Critic
→ 规则 + LLM Correction Planner
→ LLM Insight Generator
→ LLM + 规则 Chart Planner
→ 后端返回 JSON

Prompt 文件在：

```text
data_agent_core/prompts/data_agent_system_prompt.md
```

API key 只允许通过环境变量提供，不写入仓库。参考 `.env.example`，真实 `.env` / `.env.local` 已在 `.gitignore` 中忽略。

## Core Test

当前可用 Codex bundled Python 运行核心测试：

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_dabstep_core
```

当前可用 mock LLM 跑 DABstep dev 前 10 题，验证核心算法和链路字段：

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --output-dir outputs/dabstep_core_mvp_llm_chain
```

真实 LLM 运行时，先在本地 shell export 环境变量，再执行同一命令。不要把真实 key 写进命令示例、文档或 Git。

按 BM 要求生成 all.jsonl 前 10 题预测：

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 10 --output-dir outputs/dabstep_core_mvp_llm_chain
```

TODO:
- Phase 1 实现 CSV / Excel 文件解析、字段画像和最小 API。
- Phase 2 实现单 Agent MVP。
- Phase 3 接入 Benchmark 评测，但禁止单题硬编码。
- Phase 4 验证 Microsoft Agent Framework adapter 不污染核心算法。
