# Activity Trace v2 Workbench 验收

## 测试目标

验证 Workbench 不再用固定文案伪装过程，而是通过后端 `activity_trace_v2`、SSE `activity_trace_delta` 和 `execution_artifacts` 展示真实、可审计、可复现的活动链路。重点覆盖主界面 SQL / Pandas 代码展示、右侧活动抽屉、SSE 合并、安全脱敏和移动端覆盖层。

## 运行环境

- 日期时间：2026-05-26 15:23 CST
- 分支：`codex/rule-mode-benchmark-upload`
- 服务：`VDS_WORKBENCH_PORT=8002 VDS_LLM_PROVIDER=mock scripts/run_workbench_server.sh`
- 页面：`http://127.0.0.1:8002/workbench`
- 数据：临时 CSV `city,sales`，问题 `Which city has the highest sales?`

## 预期

- API payload 包含 `activity_trace_v2`。
- trace 至少包含 Planner、Pandas、SQL 或 skipped reason、Verifier、artifact 节点。
- 主界面过程区域和右侧抽屉都能展示 Python / Pandas 与 SQL 代码卡。
- 点击活动入口后右侧抽屉出现，桌面为右栏，移动端为覆盖层。
- 不出现 raw Chain of Thought、raw prompt、reasoning tokens、API key、task_id、标准答案、proxy 或 scorer。

## 实际结果

- API 上传和分析返回 `has_activity_trace_v2: true`，roles 包含 planner、data_engineer、pandas_executor、sql_executor、verifier、correction、insight、visualization、code_artifact、response_builder。
- 主回答显示 `Shanghai`。
- 主界面过程详情包含 Python `import pandas as pd` 和 SQL `SELECT` 代码。
- 点击“打开活动详情”后，右侧抽屉可见 Planner、Pandas、SQL、Verifier 和代码卡。
- 移动端 390x844 视口复测通过：活动抽屉作为覆盖层打开，宽度 390px，backdrop 可见，包含 Planner、Pandas、SQL、Verifier、Python 和 SQL 代码。
- 浏览器安全检查 `blockedLeak: false`，console error / warn 为空。
- 桌面截图：`/tmp/vds-activity-drawer-desktop.png`。
- 移动端截图：`/tmp/vds-activity-drawer-mobile.png`。

## 自动化验证

- `/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check frontend/app.js`
- `/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.backend.test_data_agent_service.DataAgentServiceTest tests.core.test_phase10_result_experience.Phase10ResultExperienceTest tests.backend.test_workbench_static_assets.WorkbenchStaticAssetsTest`
- `git diff --check`

## 测试结果

- JS syntax check 通过。
- targeted unittest：82 tests OK。
- `git diff --check` 通过。
- Browser smoke 通过。

## GPT-like 判定

通过。当前结果不是展示 raw CoT，而是展示真实活动链路：角色、工具调用摘要、执行摘要、代码 artifact 和校验摘要。交互形态接近 ChatGPT 的活动详情抽屉，且安全边界清晰。

## 后续动作

- 后续接入 provider-native OpenAI / DeepSeek tool call 时复用 `activity_trace_v2`，继续经过内部 ToolDispatcher、Verifier 和安全摘要。
- 可补更大数据集与真实 provider 的浏览器 smoke，但不阻塞本轮 Activity Trace v2 功能验收。
