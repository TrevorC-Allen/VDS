# VDS Data Agent

本仓库用于从头构建可评测、可复现、可扩展的数据分析 Agent 内核。

当前阶段整理为 Phase 7：泛化验证与 Provider 原生工具链增强。Phase 6 的最小可运行多 Agent workflow 已经作为默认链路启用；Phase 7 负责继续收敛 Benchmark 覆盖、中文 BI、受控工具调用、能力缺口归因和回归治理。当前已定义 Phase 7.1 submission gate、Phase 7.2 Agent 泛化与执行层语义一致性、Phase 7.2G 上传表泛化专项、Phase 7.3 评测驱动鲁棒性与最终输出契约硬化。

最新状态速览：

- 默认 analyze 已使用 `agent_mode=multi_agent`，由内部 runtime 编排 Planner、Data Engineer、Pandas Executor、SQL Executor、Verifier、Correction、Insight、Visualization 和 Response Builder；`single_agent` 仅保留为 fallback。
- Phase 1 Backend API Shell 已补充外部系统一次性调用入口 `POST /api/data-agent/run`；该接口把调用方传入的 JSON 表格临时转成 dataset，再复用当前默认 `multi_agent` 链路，不新增核心算法能力。
- Phase 7.2 已完成 Capability Registry、Planner 泛化契约、Verifier 语义验收和 executor parity report 第一轮落点；SQL / Pandas / DuckDB 一致性只作为执行层可信度和回归判断支撑，不替代 Agent 泛化能力目标。
- Phase 7.2G 已归入上传表泛化专项，用于闭环 Microsoft 新增 100 与原始五域新增 100 之间的泛化断层；该专项不新增 Phase 7.4，也不覆盖 Phase 7.3。
- Phase 7.3 已完成 output contract、validation-driven retry、submission provenance 和 risk taxonomy 的 mock / 离线闭环；真实 provider representative / staged / full 回归仍需在有 OpenAI 或 DeepSeek API key 时执行。
- 当前工作目标为 DABstep Easy Accuracy Recovery，并按 Phase 职责拆分：Phase 7.1 记录 easy proxy baseline、目标门槛和 submission policy；Phase 7.2 记录对应泛化能力族实现。这不是替换原 Phase 7.1 / 7.2 定义。easy public proxy 已从 `50/72 = 69.44%` baseline 提升到真实 DeepSeek 后验观察 `69/72 = 95.83%`，mock 离线回归为 `72/72 = 100%`（均非 official hidden accuracy），public proxy policy 仍为 `not_used_in_core_chain`。
- DABstep public all 1-450 mock 多 Agent 执行覆盖已达到 450/450；public all answer 为空，所以该结果只代表执行覆盖和 trace，不代表 hidden official accuracy。
- Microsoft 脱敏数据 1-300 mock 离线 scorer 已达到 300/300；标准答案只在 response 生成后用于 scorer，不进入 Agent workflow、prompt、Planner、Executor、Verifier、Correction 或 trace。
- 桌面 VDS `问题汇总.xlsx` 五个真实问题 sheet 共 95 题 smoke 已达到 95/95，覆盖销售、教育、医疗、物流、SaaS 的周期比较和中文 BI 能力族。
- 外部 leaderboard 的 Easy / Hard 反馈只作为提交后风险信号，不写成本地可复现 hidden official accuracy；本地只能验证 submission gate、公开 dev、mock 覆盖、离线 scorer 和 trace。
- 仍遗留 DABstep dev `best_fraud_aci_choice` / ACI associated cost 语义口径，需要继续按通用 fee what-if candidate table 和 associated cost 能力建设，不能按单题或固定答案特判。

更完整的阶段记录不只在 README：

- `MAIN_GOAL.md`：项目主目标、当前阶段目标、实现状态和架构红线。
- `CHANGELOG_AI.md`：每轮真实修改、验证命令、验证结果和遗留问题。
- `docs/ARCHITECTURE.md`：主架构层、多 Agent 映射、Tool Calling、Benchmark 和上传文件链路。
- `docs/PHASE_GATES.md`：阶段门槛、禁止伪泛化补丁和中文优先要求。
- `docs/BENCHMARK_RULES.md`：Benchmark 数据、标准答案隔离、评分与回归边界。

README 是 GitHub 默认首页的状态摘要。以后任何阶段、状态、主目标、项目规则、API、Benchmark 口径或用户可见能力变更，都必须同步检查并更新根 `README.md`；如果本轮确认 README 不需要修改，必须在 `CHANGELOG_AI.md` 记录原因。

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
- Phase 6：最小多 Agent workflow 已启用，backend 默认 `multi_agent`；DABstep dev 前 10 当前可复现 9/10，`single_agent` 保留为 fallback。
- Phase 7：泛化验证与 Provider 原生工具链增强阶段。当前已完成 DABstep public all 1-450 mock 执行覆盖 450/450、Microsoft 脱敏数据 1-300 mock 离线 scorer 300/300、桌面 VDS `问题汇总.xlsx` 五个真实问题 sheet 共 95 题 smoke 95/95。当前增强重点是 provider-native 真实 tool loop、DuckDB runtime、复杂并行/多轮自纠、ACI associated cost 和更复杂中文 BI 泛化能力。
- Phase 7.1：DABstep Submission Quality Gate and Easy Capability Closure。重点是提交文件绑定 commit / report / prediction hash、无空答案、无格式泄漏、无旧 Desktop 文件误传，并按 counting、top/ranking、fraud ratio、yes/no、null check、field values、outlier、quantile、schema/missing-column 等能力族闭环 Easy 风险；当前 easy recovery 真实 DeepSeek 后验 proxy 观察为 `69/72`，mock 离线回归为 `72/72`，仍不代表 hidden official score。
- Phase 7.2：Agent Generalization and Executor Semantic Parity。重点是能力族优先、Planner / Verifier 泛化、Capability Registry、Executor 覆盖率与一致性报告；Pandas / SQL / DuckDB 语义统一只作为执行层可信度和回归判断支撑。当前新增 output `answer_target`、field/filter binding、grouped fraud metrics、denominator/share/quantile 和 deterministic fee monotonic 规则，禁止按 task_id 或 proxy answer 特调。
- Phase 7.2G：Uploaded Table Generalization Gap Closure。作为 Phase 7.2 下的上传表泛化专项，聚焦字段角色绑定、Planner / Verifier 语义契约和 capability family 覆盖，不新增 Phase 7.4。
- Phase 7.3：Evaluation-Driven Robustness and Output Contract Hardening。重点是最终答案 canonicalizer、output validator、validation-driven retry、submission provenance、真实 provider 分段回归和统一 risk taxonomy。

后续 TODO：

- 建立 DABstep submission gate 和 Easy / Hard 风险报告；禁止 task_id、隐藏答案、public proxy、固定题面或固定样本值优化。
- 增强通用 `best_fraud_aci_choice`、ACI associated cost 和 fee what-if candidate table 能力缺口；禁止按题号、题面、固定样本值或当前错误形态特判。
- 所有 benchmark 暴露的问题都必须转成可迁移能力族，并用合成/非 Benchmark 用例验证泛化能力没有下降。
- 将 provider 原生 OpenAI / DeepSeek tool loop 接入真实网络 smoke；当前已有兼容 schema、tool call 解析和 mock loop，但不作为生产默认链路。
- 在不改写 `data_agent_core` 的前提下，继续完善 Microsoft Agent Framework workflow 承载层。
