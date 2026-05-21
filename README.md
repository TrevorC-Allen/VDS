# VDS Data Agent

本仓库用于从头构建可评测、可复现、可扩展的数据分析 Agent 内核。

当前已经推进到 Phase 6 最小可运行多 Agent workflow：backend analyze 默认使用 `agent_mode=multi_agent`，由内部 runtime 编排 Planner、Data Engineer、Pandas Executor、SQL Executor、Verifier、Correction、Insight、Visualization 和 Response Builder。`single_agent` 仍保留为 fallback。

当前仍不做复杂前端、登录权限、数据库持久化、异步队列、微服务或旧 BigCat / VDS 主流程重构。Microsoft Agent Framework 只作为可选 adapter 承载层，轻量依赖入口在 `requirements-ms-agent.txt`，核心算法不依赖它。

当前默认多 Agent 链路：

用户问题
→ Planner Agent：LLM 为主
→ Data Engineer Agent：代码为主，LLM 辅助字段语义
→ Pandas Executor Agent：代码为主
→ SQL Executor Agent：代码为主
→ Verifier Agent：规则为主，LLM 辅助
→ Correction Agent：LLM 生成修正方向，代码执行
→ Insight Agent：LLM 为主
→ Visualization Agent：规则 + LLM
→ Response Builder
→ 后端返回 JSON

Prompt 文件在：

```text
data_agent_core/prompts/data_agent_system_prompt.md
```

API key 只允许通过环境变量提供，不写入仓库、文档、trace 或 CHANGELOG。参考 `.env.example`，真实 `.env` / `.env.local` 已在 `.gitignore` 中忽略。

运行追踪只记录 structured analysis plan、reasoning summary、execution trace、verification notes 和工具摘要，不记录完整 Chain of Thought。

## Core Test

当前可用 Codex bundled Python 运行核心测试：

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_dabstep_core
```

当前可用 mock LLM 跑 DABstep dev 前 10 题，验证核心算法和链路字段：

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --output-dir outputs/dabstep_core_mvp_llm_chain
```

当前可用 mock LLM 跑 DABstep dev 前 10 题的多 Agent 链路：

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/phase6_multi_agent_dev_verify_final
```

真实 LLM 运行时，先在本地 shell export 环境变量，再执行同一命令。不要把真实 key 写进命令示例、文档或 Git。

按 BM 要求生成 all.jsonl 前 10 题预测：

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 10 --output-dir outputs/dabstep_core_mvp_llm_chain
```

## Phase Status

- Phase 1：最小 CSV / Excel 解析、字段画像和 backend service 已可测。
- Phase 2：LLM 单 Agent MVP 已可测，保留为 fallback。
- Phase 3：Benchmark runner、metrics、error_analysis 已可测；禁止单题硬编码，标准答案只用于评分。
- Phase 4：Microsoft Agent Framework adapter 已作为可选承载层验证，不污染 `data_agent_core`。
- Phase 5：受控 Tool Calling 契约、ToolDispatcher、tool trace 摘要和内部工具 catalog 已建立。
- Phase 6：最小多 Agent workflow 已启用，backend 默认 `multi_agent`，DABstep dev 前 10 当前可复现 8/10。

后续 TODO：

- 增强通用 `top_count` 和 `best_fraud_aci_choice` 能力缺口，禁止按题号或题面特判。
- 接入 provider 原生 OpenAI / DeepSeek tool loop，同时保持工具白名单、超时、trace 摘要和核心算法框架无关。
- 在不改写 `data_agent_core` 的前提下，继续完善 Microsoft Agent Framework workflow 承载层。
