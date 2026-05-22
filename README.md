# VDS Data Agent

本仓库用于从头构建可评测、可复现、可扩展的数据分析 Agent 内核。

当前不是只停在 Phase 6 起点，而是处在 Phase 6+ 增强阶段：最小可运行多 Agent workflow 已经作为默认链路启用，并继续补齐 Benchmark、中文 BI、受控工具调用、能力缺口归因和回归治理。

最新状态速览：

- 默认 analyze 已使用 `agent_mode=multi_agent`，由内部 runtime 编排 Planner、Data Engineer、Pandas Executor、SQL Executor、Verifier、Correction、Insight、Visualization 和 Response Builder；`single_agent` 仅保留为 fallback。
- Phase 1 Backend API Shell 已补充外部系统一次性调用入口 `POST /api/data-agent/run`；该接口把调用方传入的 JSON 表格临时转成 dataset，再复用当前默认 `multi_agent` 链路，不新增核心算法能力。
- DABstep public all 1-450 mock 多 Agent 执行覆盖已达到 450/450；public all answer 为空，所以该结果只代表执行覆盖和 trace，不代表 hidden official accuracy。
- Microsoft 脱敏数据 1-300 mock 离线 scorer 已达到 300/300；标准答案只在 response 生成后用于 scorer，不进入 Agent workflow、prompt、Planner、Executor、Verifier、Correction 或 trace。
- 桌面 VDS `问题汇总.xlsx` 五个真实问题 sheet 共 95 题 smoke 已达到 95/95，覆盖销售、教育、医疗、物流、SaaS 的周期比较和中文 BI 能力族。
- 仍遗留 DABstep dev `best_fraud_aci_choice` / ACI associated cost 语义口径，需要继续按通用 fee what-if candidate table 和 associated cost 能力建设，不能按单题或固定答案特判。

更完整的阶段记录不只在 README：

- `MAIN_GOAL.md`：项目主目标、当前阶段目标、实现状态和架构红线。
- `CHANGELOG_AI.md`：每轮真实修改、验证命令、验证结果和遗留问题。
- `docs/ARCHITECTURE.md`：主架构层、多 Agent 映射、Tool Calling、Benchmark 和上传文件链路。
- `docs/PHASE_GATES.md`：阶段门槛、禁止伪泛化补丁和中文优先要求。
- `docs/BENCHMARK_RULES.md`：Benchmark 数据、标准答案隔离、评分与回归边界。

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

## External Agent API

外部系统如果已经有 JSON 表格数据，可以直接调用 `POST /api/data-agent/run`，不必先走文件上传。该接口属于 Phase 1 Backend API Shell 扩展，只负责把 inline tables 转成临时 dataset，然后复用现有 Phase 6+ 默认多 Agent 分析链路。

最小请求示例：

```json
{
  "request_id": "external-001",
  "question": "哪个城市销售额最高？",
  "tables": [
    {
      "table_name": "销售",
      "rows": [
        {"城市": "上海", "销售额": 100},
        {"城市": "北京", "销售额": 150},
        {"城市": "上海", "销售额": 200}
      ]
    }
  ],
  "execution_mode": "dual",
  "agent_mode": "multi_agent"
}
```

响应继续沿用 analyze 契约，包含 `response_version`、`run_id`、`dataset_id`、`answer`、`result`、`verification`、`warnings`、`errors` 和 `debug`。`request_id` 会原样返回，便于外部系统对账。

该接口不改变 Benchmark、Microsoft adapter、Provider-native tool loop 或核心算法边界；文件上传复用场景仍使用 `/api/data-agent/upload` + `/api/data-agent/analyze`。

## Core Test

当前可用 Codex bundled Python 运行完整核心测试：

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
```

当前可用 mock LLM 跑 DABstep public all 1-450 执行覆盖，验证多 Agent 链路、trace 和能力路由：

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 450 --offset 0 --output-dir outputs/dabstep_all_1_450_mock_current_verify_20260522
```

当前可用 mock LLM 跑 Microsoft 脱敏数据 1-300 离线 scorer；标准答案只在 response 生成后评分，不进入 Agent workflow：

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.microsoft_anonymized_benchmark_runner --dataset-root /Users/trevorcui/Desktop/微软脱敏数据 --limit 300 --offset 0 --output-dir outputs/microsoft_anonymized_1_300_mock_current_verify_20260522
```

真实 LLM 运行时，先在本地 shell export 环境变量，再执行同一命令。不要把真实 key 写进命令示例、文档或 Git。

## Phase Status

- Phase 1：最小 CSV / Excel 解析、字段画像和 backend service 已可测。
- Phase 2：LLM 单 Agent MVP 已可测，保留为 fallback。
- Phase 3：Benchmark runner、metrics、error_analysis 已可测；禁止单题硬编码和伪泛化补丁，标准答案只用于评分。
- Phase 4：Microsoft Agent Framework adapter 已作为可选承载层验证，不污染 `data_agent_core`。
- Phase 5：受控 Tool Calling 契约、ToolDispatcher timeout 边界、tool trace 摘要、内部工具 catalog 和 provider-native mock loop 已建立。
- Phase 6+：最小多 Agent workflow 已启用，backend 默认 `multi_agent`；DABstep dev 前 10 当前可复现 9/10，DABstep public all 1-450 mock 执行覆盖 450/450，Microsoft 脱敏数据 1-300 mock 离线 scorer 300/300，桌面 VDS `问题汇总.xlsx` 五个真实问题 sheet 共 95 题 smoke 95/95。当前增强重点是 provider-native 真实 tool loop、DuckDB runtime、复杂并行/多轮自纠、ACI associated cost 和更复杂中文 BI 泛化能力。

后续 TODO：

- 增强通用 `best_fraud_aci_choice`、ACI associated cost 和 fee what-if candidate table 能力缺口；禁止按题号、题面、固定样本值或当前错误形态特判。
- 所有 benchmark 暴露的问题都必须转成可迁移能力族，并用合成/非 Benchmark 用例验证泛化能力没有下降。
- 将 provider 原生 OpenAI / DeepSeek tool loop 接入真实网络 smoke；当前已有兼容 schema、tool call 解析和 mock loop，但不作为生产默认链路。
- 在不改写 `data_agent_core` 的前提下，继续完善 Microsoft Agent Framework workflow 承载层。
