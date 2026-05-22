# multi_agent_workflows

本目录当前承载 Phase 6 最小多 Agent 编排。后续复杂并行、循环、真实 provider tool loop 和 Microsoft Agent Framework 承载 workflow 统一归入 Phase 7。

## 当前阶段

1. 当前已提供 Phase 6 最小可运行多 Agent workflow。
2. 当前不启用复杂并行/循环多 Agent，只启用顺序 role workflow。
3. 当前组合 Planner、Data Engineer、Pandas Executor、SQL Executor、Verifier、Correction、Insight、Visualization、Response Builder。
4. workflow 调用 agent_runtime，不直接写核心算法。
5. workflow 可以由 Microsoft Agent Framework adapter 承载，也可以由自研 runtime 承载。
6. 当前已提供 DABstep 多 Agent runner 和 Microsoft 脱敏数据离线 runner；标准答案只在 response 生成后评分，不进入 workflow。

## 未来结构

DataAnalysisSupervisor
├─ Planner Agent：LLM 为主
├─ Data Engineer Agent：代码为主，LLM 辅助字段语义
├─ Pandas Executor Agent：代码为主
├─ SQL Executor Agent：代码为主
├─ Verifier Agent：规则为主，LLM 辅助
├─ Correction Agent：LLM 生成修正方向，代码执行
├─ Insight Agent：LLM 为主
├─ Visualization Agent：规则 + LLM
└─ Benchmark Agent：代码为主，LLM 辅助错误归因

## Phase 关系

1. Phase 5 已建立受控 Tool Calling 层。
2. Phase 6 已启用内部多 Agent workflow。
3. 多 Agent 调用 agent_runtime 的 provider-neutral 工具契约，但不能直接写核心算法。

## Phase Status

- Phase 6 多 Agent 基线已完成，backend 默认走内部 workflow。
- Phase 7 当前承载更大范围回归和泛化验证：
- DABstep dev 1-10 mock 多 Agent 回归：9/10，剩余缺口为 `best_fraud_aci_choice` / ACI associated cost 通用语义。
- DABstep public all 1-450 mock 多 Agent 执行覆盖：450/450；public all answer 为空，不能本地计算 hidden official accuracy。
- Microsoft 脱敏数据 1-300 mock 离线 scorer：300/300；标准答案只在 scorer 阶段使用。
- 桌面 VDS `问题汇总.xlsx` 五个真实问题 sheet 共 95 题 smoke：95/95。

## TODO

- Phase 7 扩展 Microsoft Agent Framework 真实运行 demo。
- 为每个 Agent 增加更细的独立测试。
- 扩展并行 executor、多轮代码级自纠、真实 provider tool loop smoke 和更多中文复杂 BI 问法。
