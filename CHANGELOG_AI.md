# AI CHANGELOG

## 使用规则

每次 Codex 修改代码、文档或项目规则后，必须追加一条记录。

本文件只记录真实发生过的修改，不允许虚构历史记录，不允许补写不存在的修改。

每次记录必须包含：

1. 日期时间
2. 本次目标
3. 修改文件
4. 修改内容
5. 测试方式
6. 测试结果
7. 遗留问题
8. 是否影响主流程
9. 是否涉及 Benchmark
10. 是否涉及 Microsoft Agent Framework
11. 是否影响未来多 Agent 迁移
12. 是否修改核心数据契约
13. 是否修改 API 契约
14. 是否新增或修改错误类型
15. 是否新增或修改运行追踪逻辑
16. 是否已同步 README

日期时间规则：

1. 新增记录必须使用 `YYYY-MM-DD HH:MM TZ` 格式，精确到分钟。
2. 默认使用当前本地时区时间。
3. 禁止只写日期，不写具体时间。
4. 禁止为了补齐格式而给历史记录编造分钟级时间；历史记录如果原本只有日期，必须保留原样。

## 模板

### 日期时间

YYYY-MM-DD HH:MM TZ

### 本次目标

### 修改文件

### 修改内容

### 测试方式

### 测试结果

### 遗留问题

### 是否影响主流程

### 是否涉及 Benchmark

### 是否涉及 Microsoft Agent Framework

### 是否影响未来多 Agent 迁移

### 是否修改核心数据契约

### 是否修改 API 契约

### 是否新增或修改错误类型

### 是否新增或修改运行追踪逻辑

### 是否已同步 README

2026-05-24 18:27 CST

### 本次目标

按用户反馈纠正 Workbench 图表“前端手写 SVG 太丑”的实现路径，恢复为后端 Python 渲染图像优先展示。

### 修改文件

- data_agent_core/contracts/response_contracts.py
- data_agent_core/output/chart_renderer.py
- data_agent_core/agent/single_agent.py
- agent_runtime/data_analysis_roles.py
- frontend/app.js
- frontend/index.html
- frontend/styles.css
- frontend/README.md
- tests/core/test_phase10_result_experience.py
- tests/backend/test_workbench_static_assets.py
- docs/API_CONTRACT.md
- README.md
- MAIN_GOAL.md
- CHANGELOG_AI.md

### 修改内容

- `ChartSpec` 新增 `image_data_uri`、`image_format`、`render_engine` 字段。
- 新增 `data_agent_core/output/chart_renderer.py`，在后端把已验证的 chart spec 渲染为 SVG data URI；当前 runtime 未安装 matplotlib / seaborn / plotly / altair，因此先使用无外部依赖的 `python_svg` renderer，后续可在同一 renderer 层替换为 matplotlib / seaborn。
- `single_agent` 和 `multi_agent` 最终响应阶段调用 `attach_rendered_chart()`，避免把大图像 data URI 放进 LLM chart planning 输入。
- Workbench 前端优先显示 `chart.image_data_uri` 的 `<img class="chart-image">`；旧手写 SVG 只作为没有后端图片时的 fallback。
- 静态资源版本更新为 `?v=20260524-python-chart`，避免浏览器继续使用旧 CSS / JS。
- README、MAIN_GOAL、frontend README 和 API_CONTRACT 同步记录后端渲染图像字段及前端边界。

### 测试方式

- `/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3` 检查当前 runtime 是否安装 matplotlib / seaborn / plotly / altair。
- `/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check frontend/app.js`
- `VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_phase10_result_experience tests.backend.test_workbench_static_assets`
- `VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime backend tests/core tests/backend`
- `VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'`
- `git diff --check`
- `scripts/sync_workbench_runtime.sh`
- `launchctl kickstart -k gui/$(id -u)/com.trevorcui.vds.workbench`
- `curl http://127.0.0.1:8001/workbench`
- `curl http://127.0.0.1:8001/api/data-agent/run` 使用内联销售表验证后端 API 返回 `chart.image_data_uri`。
- Playwright CLI 打开 `http://127.0.0.1:8001/workbench?qa=python-chart`，上传 `/tmp/vds_sales_chart.csv`，提问“按城市汇总销售额排名”，验证页面显示 `.chart-image`。

### 测试结果

- 当前 runtime 未安装 matplotlib / seaborn / plotly / altair；本轮没有假设它们存在，也没有把缺失依赖硬编码进主流程。
- `node --check frontend/app.js` 通过。
- Focused tests 通过：Ran 15 tests，OK。
- compileall 通过。
- Full unittest 通过：Ran 164 tests，OK。
- `git diff --check` 通过。
- runtime 已同步并重启，`/workbench` 返回 `styles.css?v=20260524-python-chart` 和 `app.js?v=20260524-python-chart`。
- API 验证通过：多行销售排名响应 `chart_type=bar`、`render_engine=python_svg`，`image_data_uri` 以 `data:image/svg+xml;base64,` 开头。
- Playwright Workbench 验证通过：页面显示 `.chart-image`，没有 fallback `.chart-svg`；图像实际尺寸约 820 x 411；console error/warn 为 0；截图 `.playwright-cli/page-2026-05-24T10-27-04-959Z.png`。

### 遗留问题

- 当前环境没有 matplotlib / seaborn 等第三方 Python 绘图库；如后续要指定 matplotlib/seaborn 作为强依赖，需要新增依赖安装和部署规则。本轮先用后端 `python_svg` renderer 解决前端手写图表丑和职责错位问题。
- 本轮不处理“本周Pro套餐CHR最高Top10客户”被路由成区域订阅收入的问题；那是分析语义命中问题，需另做核心路由修复。

### 是否影响主流程

是。影响最终 `chart` 响应和 Workbench 图表显示，但不改变 Planner / Executor / Verifier 的分析计算逻辑。

### 是否涉及 Benchmark

否。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

是，正向影响。后端渲染在 ChartSpec 最终响应层完成，multi_agent 与 single_agent 都可复用，不绑定具体 provider 或 Agent framework。

### 是否修改核心数据契约

是。`ChartSpec` 新增可选展示字段 `image_data_uri`、`image_format`、`render_engine`。

### 是否修改 API 契约

是。`docs/API_CONTRACT.md` 已补充 chart v2 的后端图像字段。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

### 是否已同步 README

是。README 已同步 Workbench 优先展示后端 Python 渲染 SVG 图像、前端只保留 fallback 的边界。

2026-05-24 18:08 CST

### 本次目标

修复 Workbench 图表可视化被压成极小色块的问题，让柱状图 / 折线图 SVG 按图表区域正常展开。

### 修改文件

- frontend/app.js
- frontend/index.html
- frontend/styles.css
- tests/backend/test_workbench_static_assets.py
- CHANGELOG_AI.md

### 修改内容

- `frontend/styles.css` 让 `.chart-svg` 明确覆盖全局图标 `svg { width: 18px; height: 18px; }`：设置 `display: block`、`height: auto`、`max-height: none`、`min-height: 230px`，并让 `.chart-panel` 保持足够高度且不裁剪。
- `frontend/app.js` 让柱状图按实际显示的条数计算柱宽，避免结果行数多时柱子被压细。
- `frontend/index.html` 更新静态资源版本为 `?v=20260524-chart-size`，确保当前浏览器拿到新 CSS / JS。
- 静态测试补充图表 SVG 覆盖全局图标尺寸、柱宽按显示条数计算和资源版本号断言。

### 测试方式

- `/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check frontend/app.js`
- `VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.backend.test_workbench_static_assets`
- `git diff --check`
- `scripts/sync_workbench_runtime.sh`
- `launchctl kickstart -k gui/$(id -u)/com.trevorcui.vds.workbench`
- `curl http://127.0.0.1:8001/workbench`
- `curl http://127.0.0.1:8001/frontend/styles.css?v=20260524-chart-size`
- Browser 插件尝试在 Workbench 页面直接注入测试图表；因浏览器插件只读策略阻止 DOM 写入，改用 Playwright CLI fallback。
- Playwright CLI 在同源 `/workbench` 页面加载真实 8001 CSS 并渲染图表 SVG fixture，测量实际尺寸。

### 测试结果

- `node --check frontend/app.js` 通过。
- `tests.backend.test_workbench_static_assets` 通过：Ran 8 tests，OK。
- `git diff --check` 通过。
- runtime 已同步并重启，`/workbench` 返回 `styles.css?v=20260524-chart-size` 和 `app.js?v=20260524-chart-size`。
- 版本化 CSS 返回 200 且包含 `.chart-svg { height: auto; max-height: none; min-height: 230px; }`。
- Playwright CLI 渲染测量通过：在 820px 宽图表区域内，`.chart-svg` 实际宽度 820px、高度 304px，`cssMaxHeight=none`，不再是 18px 高；console error/warn 为 0。

### 遗留问题

无。用户截图中的“图表极小”来自前端 CSS 尺寸继承，已修复；本轮不处理后端把“Pro 套餐 CHR Top10 客户”误答成区域订阅收入的分析路由问题。

### 是否影响主流程

是。影响 Workbench 图表展示尺寸和静态资源版本，不改变后端分析链路。

### 是否涉及 Benchmark

否。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

否。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

### 是否已同步 README

否。本轮只修复 Workbench 前端图表展示尺寸，不改变阶段目标、API 使用方式或 GitHub 首页摘要。

2026-05-24 17:55 CST

### 本次目标

修复 Workbench 在用户浏览器中仍可能保留旧 `app.js` 导致 Enter 继续换行的问题，从源头避免静态资源缓存挡住键盘交互修复。

### 修改文件

- backend/main.py
- frontend/index.html
- tests/backend/test_workbench_static_assets.py
- CHANGELOG_AI.md

### 修改内容

- `frontend/index.html` 将 `styles.css` 和 `app.js` 改为带版本号的 `/frontend/*?v=20260524-enter-cache` 资源地址。
- `backend/main.py` 新增 `NO_CACHE_HEADERS` 和 `NoCacheStaticFiles`，让 `/workbench` 与 `/frontend/*` 返回 `Cache-Control: no-store, max-age=0`、`Pragma: no-cache`、`Expires: 0`。
- 静态测试补充资源版本号和后端 no-cache 头的断言，防止以后交互修复再次被旧缓存遮挡。

### 测试方式

- `/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check frontend/app.js`
- `VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.backend.test_workbench_static_assets`
- `git diff --check`
- `scripts/sync_workbench_runtime.sh`
- `launchctl kickstart -k gui/$(id -u)/com.trevorcui.vds.workbench`
- `curl -D - http://127.0.0.1:8001/workbench`
- `curl -D - 'http://127.0.0.1:8001/frontend/app.js?v=20260524-enter-cache'`
- Browser 插件打开 `http://127.0.0.1:8001/workbench?qa=enter-cache-20260524` 后验证 Enter / Shift+Enter。

### 测试结果

- `node --check frontend/app.js` 通过。
- `tests.backend.test_workbench_static_assets` 通过：Ran 7 tests，OK。
- `git diff --check` 通过。
- runtime 已同步并重启，`/workbench` 返回 200，响应头包含 no-cache，HTML 引用 `styles.css?v=20260524-enter-cache` 和 `app.js?v=20260524-enter-cache`。
- 版本化 `app.js` 返回 200，响应头包含 no-cache，内容包含 `handleQuestionKeydown()`。
- Browser 验证通过：输入 `回车发送验证` 后按 Enter，状态 `已回复`，`userMessages=1`，`assistantMessages=1`，输入框清空；新聊天后输入 `第一行`，按 `Shift+Enter` 再输入 `第二行`，未发送，输入框保留 `第一行\n第二行`；随后按 Enter 成功发送；console error/warn 为 0。

### 遗留问题

无。已从后端响应头和资源 URL 两层处理浏览器旧缓存。

### 是否影响主流程

是。影响 Workbench 静态资源加载和消息输入交互，不改变数据分析、概览或聊天路由逻辑。

### 是否涉及 Benchmark

否。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

否。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。仅修改静态资源 URL 和静态文件缓存响应头，不改变 JSON API。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

### 是否已同步 README

否。本轮只修复 Workbench 静态资源缓存与输入键盘交互，不改变阶段目标、API 使用方式或 GitHub 首页摘要。

2026-05-24 17:45 CST

### 本次目标

按用户要求把 Workbench 对话输入框改成 `Enter` 直接发送消息，同时保留 `Shift+Enter` 换行，避免中文输入法组合输入时误发送。

### 修改文件

- frontend/app.js
- tests/backend/test_workbench_static_assets.py
- CHANGELOG_AI.md

### 修改内容

- `frontend/app.js` 为 `#question-input` 新增 `keydown` 监听。
- `handleQuestionKeydown()` 在 `Enter` 且非 `Shift+Enter`、非 IME composing 时 `preventDefault()` 并调用现有 `runAnalysis()`。
- 静态测试补充 Enter 发送、Shift+Enter 换行和 composing 防误触的代码断言。

### 测试方式

- `/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check frontend/app.js`
- `VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.backend.test_workbench_static_assets`
- `git diff --check`
- `scripts/sync_workbench_runtime.sh`
- `launchctl kickstart -k gui/$(id -u)/com.trevorcui.vds.workbench`
- `curl http://127.0.0.1:8001/workbench`
- Browser 插件尝试输入框验证；因插件虚拟剪贴板能力缺失导致 `locator.fill failed for selector #question-input`，改用 Playwright CLI fallback。
- Playwright CLI 验证 Enter 发送、Shift+Enter 不发送。

### 测试结果

- `node --check frontend/app.js` 通过。
- `tests.backend.test_workbench_static_assets` 通过：Ran 6 tests，OK。
- `git diff --check` 通过。
- runtime 已同步并重启，`/workbench` 返回 200。
- Playwright CLI 验证通过：输入 `回车发送测试` 后按 Enter，状态 `已回复`，`userCount=1`，`assistantCount=1`，输入框清空；新聊天后输入 `第一行`，按 `Shift+Enter` 再输入 `第二行`，未发送，输入框保留 `第一行\n第二行`；随后按 Enter 成功发送，状态 `已回复`，console issue 为 0；截图 `/tmp/vds_enter_send_20260524.png`。

### 遗留问题

- 无。

### 是否影响主流程

是。影响 Workbench 消息提交交互，不改变后端分析、概览或聊天路由。

### 是否涉及 Benchmark

否。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

否。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

### 是否已同步 README

否。本轮只改前端输入键盘交互，不改变对外 API、阶段目标或部署说明。

### 日期

2026-05-21

### 本次目标

按用户要求将 Agent 从纯确定性核心改为必须包含 LLM planning layer；明确 prompt 存放位置，支持 DeepSeek / OpenAI-compatible Chat Completions，通过环境变量读取 key，且禁止把 key 写入 Git。

### 修改文件

- .gitignore
- .env.example
- README.md
- MAIN_GOAL.md
- README.md
- docs/ARCHITECTURE.md
- docs/API_CONTRACT.md
- docs/BENCHMARK_RULES.md
- docs/FEATURE_BACKLOG.md
- docs/SECURITY_BOUNDARIES.md
- data_agent_core/llm/__init__.py
- data_agent_core/llm/client.py
- data_agent_core/llm/planner.py
- data_agent_core/prompts/data_agent_system_prompt.md
- data_agent_core/agent/single_agent.py
- data_agent_core/tracing/run_trace.py
- tests/core/test_dabstep_core.py

### 修改内容

- 新增 data_agent_core/llm，用标准库 urllib 实现 OpenAI-compatible /chat/completions client。
- 支持 VDS_LLM_PROVIDER=deepseek / openai / mock。
- 真实 key 仅从 DEEPSEEK_API_KEY 或 OPENAI_API_KEY 环境变量读取，不写入仓库。
- 新增 prompt 文件 data_agent_core/prompts/data_agent_system_prompt.md。
- DataAnalysisAgent 初始化时必须加载 LLM client，analyze 时先调用 LLM 生成结构化 LogicForm 草案。
- 本地 deterministic parser 保留为 schema guardrail，限制 LLM 输出到受支持 operation，防止非法结构或 Benchmark 信息泄漏。
- RunTrace 增加 llm_plan_summary，只记录 operation、confidence、reasoning_summary，不记录完整 prompt、key 或完整 Chain of Thought。
- tests 使用 MockLLMClient / VDS_LLM_PROVIDER=mock 验证 LLM wiring，不依赖真实 key。
- README 和 docs 更新 prompt 路径、环境变量方式、key 不进 Git 的约束。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_dabstep_core
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --output-dir outputs/dabstep_core_mvp_llm
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 10 --output-dir outputs/dabstep_core_mvp_llm
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core tests/core tests/architecture
- secret pattern scan over repo files excluding outputs

### 测试结果

- unittest 通过：Ran 2 tests in 1.735s，OK。
- mock LLM wiring 下 DABstep dev 前 10：total=10，scored=10，correct=8，accuracy=0.8。
- mock LLM wiring 下 DABstep all 前 10 已生成预测文件；本地 all.jsonl answer 为空，accuracy=null。
- compileall 通过。
- 仓库扫描未发现用户提供的真实 key 片段。

### 遗留问题

- 未在工具命令中注入用户提供的真实 key，避免 key 出现在命令记录或输出中；真实运行需要用户在本机 shell 或 .env.local 中设置环境变量。
- 真实 LLM 输出可能波动，当前通过本地 schema guardrail 固定到受支持的 LogicForm / operation。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端或复杂后端业务。

### 是否涉及 Benchmark

是。benchmark runner 继续支持 dev/all 前 10；不会把 task_id 或 answer 字段传给 LLM。

### 是否涉及 Microsoft Agent Framework

否。新增的是普通 OpenAI-compatible LLM client，不安装、不 import Microsoft Agent Framework。

### 是否影响未来多 Agent 迁移

是，正向影响。LLM planning layer 仍在 data_agent_core 内，后续可被 agent_runtime 或 adapter 编排。

### 是否修改核心数据契约

是。RunTrace 增加 llm_plan_summary，Agent 调试输出增加 llm_used / llm_operation / llm_confidence。

### 是否修改 API 契约

是。docs/API_CONTRACT.md 说明 debug 中可能包含 LLM 调试字段，但前端不能依赖 debug。

### 是否新增或修改错误类型

否。未新增错误类型。

### 是否新增或修改运行追踪逻辑

是。RunTrace 记录 LLM plan 摘要，不记录 key、完整 prompt 或完整 Chain of Thought。


### 日期时间

2026-05-22 13:07 CST

### 本次目标

按 Phase 1 Backend API Shell 扩展实现外部系统一次性调用现有 VDS Agent 的接口，让调用方可以通过 API 传入 JSON 表格和自然语言问题，并复用当前 Phase 6+ 默认 `multi_agent` 链路完成数据处理。

### 修改文件

- README.md
- MAIN_GOAL.md
- docs/API_CONTRACT.md
- backend/routers/data_agent.py
- backend/schemas/data_agent_schema.py
- backend/services/data_agent_service.py
- backend/storage/temp_file_store.py
- tests/backend/test_data_agent_service.py
- CHANGELOG_AI.md

### 修改内容

- 新增 `POST /api/data-agent/run` FastAPI 路由和非 FastAPI helper，供外部系统一次性提交 inline JSON 表格和问题。
- 新增 `run_agent_with_inline_tables` service 入口：只负责校验请求、创建临时 dataset、调用既有 `analyze_dataset()`，不实现 Pandas / SQL / Verifier / Benchmark 核心逻辑。
- 在 `TempFileStore` 增加 inline table payload 标准化和临时 profile 存储能力，支持列表表格和按表名映射两种 JSON 形态。
- 响应沿用 analyze 契约，并在请求提供时原样返回 `request_id`。
- README / MAIN_GOAL / API_CONTRACT 同步说明该能力归属 Phase 1 Backend API Shell 扩展，服务于当前 Phase 6+ 默认多 Agent 链路，不属于 Phase 5 Tool Calling 或 Phase 7 Provider 原生 tool loop。
- backend 测试新增中文 inline 表格、英文 inline 表格、request_id 和非法 payload 标准错误覆盖。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.backend.test_data_agent_service
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.architecture.test_dependency_boundaries
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- git diff --check

### 测试结果

- backend service 测试通过：Ran 5 tests，OK。
- architecture dependency boundary 测试通过：Ran 3 tests，OK。
- 全量 unittest 通过：Ran 89 tests in 27.304s，OK。
- git diff --check 通过。

### 遗留问题

- 本轮只实现外部 API 接入面，不做鉴权、限流、多租户、异步任务、复杂持久化、WebSocket 或微服务拆分。
- inline table 当前仍使用 Phase 1 临时存储策略，进程重启后不恢复 DataFrame tables；长期服务化仍需后续设计 retention 和持久化策略。

### 是否影响主流程

否。新增的是外部系统一次性调用入口，现有 upload / analyze / profile 接口保持不变，不修改旧 BigCat / VDS 主流程，不修改前端。

### 是否涉及 Benchmark

否。未修改 Benchmark 数据、runner、scorer 或标准答案链路，未读取 hidden answer、task_id 或 public proxy 答案池。

### 是否涉及 Microsoft Agent Framework

否。未安装 Microsoft Agent Framework，未新增依赖，未把核心算法写入 adapter。

### 是否影响未来多 Agent 迁移

是，正向影响。外部 API 复用现有 `multi_agent` workflow 和稳定响应契约，不把具体 Agent 框架写入 backend 接口。

### 是否修改核心数据契约

否。未修改 data_agent_core contracts。

### 是否修改 API 契约

是。新增 `POST /api/data-agent/run` 外部一次性调用契约；现有 upload / analyze / profile 契约不变。

### 是否新增或修改错误类型

否。复用现有 FILE_PARSE_ERROR 和 LOGIC_FORM_ERROR。

### 是否新增或修改运行追踪逻辑

否。未修改 RunTrace；仅在 API debug 中增加 trace-safe 的 `api_source`，并返回调用方提供的 `request_id`。

### 日期时间

2026-05-23 23:10 CST

### 本次目标

按用户要求把 Phase 11 会话隔离、历史续聊、多窗口独立会话、未来用户隔离预留和 GPT-like 安静过程展示写入 MAIN_GOAL 及相关文档，方便后续随时 follow up；本轮只同步计划和边界，不实现功能。

### 修改文件

- MAIN_GOAL.md
- README.md
- docs/API_CONTRACT.md
- docs/FEATURE_BACKLOG.md
- docs/ARCHITECTURE.md
- CHANGELOG_AI.md

### 修改内容

- MAIN_GOAL.md 新增 Phase 11：Conversation Isolation, Session Persistence and Quiet Process UX，状态标记为 Planned / Not implemented yet。
- README.md 增加 Phase 11 简短状态说明，明确 conversation endpoints 当前尚未实现。
- docs/API_CONTRACT.md 新增 planned conversation API、planned request extension、owner 字段预留、旧 dataset_id 兼容策略和 quiet process UX 安全边界。
- docs/FEATURE_BACKLOG.md 新增 Phase 11 backlog 条目，记录目标、验收标准、UX 验收、风险和测试方式。
- docs/ARCHITECTURE.md 新增 planned Conversation Store / Conversation Service 架构位置，明确其只能管理会话和调用已有 upload / analyze，不承载核心数据分析逻辑。
- 文档统一要求过程展示默认只是一条小号浅灰安全摘要，点击后展开结构化步骤；不展示完整 Chain of Thought、raw reasoning tokens、raw prompt、quality_report、warnings、verification 或 join trace。

### 测试方式

- git diff --check
- rg -n "Phase 11|Conversation Isolation|conversation_id|owner_context|owner_id|tenant_id|Quiet Process|安静过程|Planned / Not implemented yet" MAIN_GOAL.md README.md docs/API_CONTRACT.md docs/FEATURE_BACKLOG.md docs/ARCHITECTURE.md
- rg -n "Phase 11.*已完成|conversation endpoints.*已实现|已支持.*conversation_id|已落地.*conversation|真实登录|企业级权限" MAIN_GOAL.md README.md docs/API_CONTRACT.md docs/FEATURE_BACKLOG.md docs/ARCHITECTURE.md
- git diff --stat -- MAIN_GOAL.md README.md docs/API_CONTRACT.md docs/FEATURE_BACKLOG.md docs/ARCHITECTURE.md CHANGELOG_AI.md

### 测试结果

- git diff --check 通过。
- Phase 11、conversation_id、owner_context、安静过程展示和 Planned / Not implemented yet 关键词均在 MAIN_GOAL、README、API_CONTRACT、FEATURE_BACKLOG 和 ARCHITECTURE 中命中。
- 误实现口径扫描未发现 Phase 11 被写成已完成；`真实登录` / `企业级权限` 仅出现在未来预留或禁止误宣称的上下文。
- diff stat 确认本轮相关文档已更新；当前 worktree 仍有本轮之前已存在的其他未提交改动，本轮未回滚或整理无关文件。

### 遗留问题

- 本轮只做计划文档同步，尚未实现 Conversation Store / Service、conversation endpoints、前端历史 Chat 恢复或安静过程 UX。
- Phase 11 实现前仍需补后端会话持久化、owner_context 过滤边界、旧 dataset_id 调用兼容测试和浏览器多窗口 smoke。
- 当前 worktree 已有大量未提交代码和前端改动，本轮只修改文档文件，不处理无关 dirty 文件。

### 是否影响主流程

否。仅文档计划同步，不改 backend / frontend runtime，不改变当前 upload / analyze / workbench 行为。

### 是否涉及 Benchmark

否。未修改 Benchmark 数据、runner、scorer、标准答案、public proxy 或核心分析链路。

### 是否涉及 Microsoft Agent Framework

否。未修改 MAF adapter 或相关依赖。

### 是否影响未来多 Agent 迁移

是，正向影响。文档明确会话层只保存对话上下文和引用，不承载 Planner / Executor / Verifier / Insight / Chart 核心逻辑，可被当前 multi_agent workflow 和未来 adapter 复用。

### 是否修改核心数据契约

否。本轮未修改代码 contracts；仅记录 planned conversation schema。

### 是否修改 API 契约

是。docs/API_CONTRACT.md 新增 planned Phase 11 conversation APIs、可选 conversation_id / owner 字段和兼容策略，但明确尚未实现。

### 是否新增或修改错误类型

否。本轮只记录如果未来新增 conversation not found / owner mismatch 等错误类型，必须先写入 API_CONTRACT 和 tests。

### 是否新增或修改运行追踪逻辑

否。本轮不改 trace 代码；文档只要求后续 quiet process UX 复用 trace-safe reasoning_trace_view 摘要，不暴露 raw CoT。

### 是否已同步 README

是。README 已同步 Phase 11 已规划但尚未实现的状态，并避免把 planned API 写成可用能力。

---

### 日期时间

2026-05-24 13:50 CST

### 本次目标

按用户复测反馈继续自查 Workbench 普通消息链路：已有 dataset 时 `你好` / `你是什么模型` 必须在主对话区有可见回复；`看一下这个数据` 必须返回有意义的数据概览，不能返回单个 `720` 或 `answer=720` 表；修复必须从路由和展示源头处理，不能继续逐句补丁。

### 修改文件

- data_agent_core/core/message_intent.py
- data_agent_core/output/dataset_overview.py
- data_agent_core/output/response_builder.py
- backend/services/data_agent_service.py
- backend/routers/data_agent.py
- frontend/app.js
- frontend/styles.css
- tests/backend/test_data_agent_service.py
- tests/backend/test_workbench_static_assets.py
- README.md
- frontend/README.md
- docs/API_CONTRACT.md
- MAIN_GOAL.md
- CHANGELOG_AI.md

### 修改内容

- 新增 `data_agent_core/core/message_intent.py`：统一判断 Workbench 消息是普通聊天、泛数据概览还是正式分析；有 dataset 时普通问候和模型身份问题不再被强制送入 analyze。
- 新增 `data_agent_core/output/dataset_overview.py`：针对“看一下这个数据 / 看一下整体销售情况”生成全表概览，返回行列规模、主要字段、优先数值指标、合计/平均/最高/最低、最高维度和下钻方向，避免把行数或前几行明细当答案。
- `DataAgentService.analyze_dataset()` 对泛概览问题先走 core 概览响应；新增 `respond_to_message()` 和 `chat_with_dataset()`；router 新增 `POST /api/data-agent/message`。
- Workbench 前端提交统一改为 `/api/data-agent/message`，不再用 `state.datasetId ? analyze : chat` 在浏览器里做语义路由。
- 前端每一轮 `renderProgress()` 都 clone 一个独立 assistant result message，避免复用 `#result-message` 导致旧回复从主聊天区消失。
- `response_builder` 的概览识别扩展到“看一下这个数据 / 这个表 / dataset overview”等非销售特定表达。
- 文档同步说明：`/message` 是当前 Workbench 统一入口；`/chat` 仍保留为无文件辅助对话接口；Phase 11 conversation persistence 仍未实现。

### 测试方式

- `/Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check frontend/app.js` 通过。
- `VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.backend.test_data_agent_service tests.backend.test_workbench_static_assets` 通过：Ran 16 tests，OK。
- `VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_output_contract tests.core.test_phase10_result_experience` 通过：Ran 13 tests，OK。
- `VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'`
- `git diff --check`
- `scripts/sync_workbench_runtime.sh`
- `launchctl kickstart -k gui/$(id -u)/com.trevorcui.vds.workbench`
- Browser 插件打开 `http://127.0.0.1:8001/workbench` 做首屏、title、console 检查。
- Playwright CLI fallback 做文件上传和多轮消息验证；fallback 原因：Browser 插件当前受控 API 不暴露本地文件选择 / `setInputFiles`。

### 测试结果

- `node --check frontend/app.js` 通过。
- 目标后端 / 核心测试通过：Ran 29 tests，OK。
- 完整 unittest 通过：Ran 159 tests，OK。
- `git diff --check` 通过。
- runtime 已同步到 `/Users/trevorcui/.vds-workbench-runtime/VDS` 并重启；`127.0.0.1:8001` 新 PID `17679` 监听，`GET /workbench` 返回 200。
- Browser 插件首屏检查通过：URL/title 正确，页面非空，无框架 overlay，console warning/error 为 0。
- 上传 SaaS Excel 后连续发送 `你好`、`你是什么模型`、`看一下这个数据`：`/upload` 200，`/message` 3 次 200；主聊天区 `userCount=3`、`assistantCount=3`；前两条 assistant 为 `VDS / 已回复` 且无表格；第三条为 `分析结果 / 已完成`，表头为 `["指标","数值"]`，答案包含 `订阅收入合计 17,353,545.69`，不是 `answer=720`，无 `SS2025...` 原始明细倾倒，console issue 为 0；截图 `/tmp/vds_workbench_message_fix_20260524.png`。
- 追加验证 `看一下整体销售情况`：`/upload` 200，`/message` 200；答案包含 `订阅收入合计 17,353,545.69`，表头为 `["指标","数值"]`，`single720=false`，`rawRecord=false`，console issue 为 0。
- 无文件聊天复测：新聊天后发送 `没有文件时你能做什么？`，`/message` 200，状态 `已回复`，`datasetChip=未上传数据`，`assistantCount=1`，表格隐藏，console issue 为 0；截图 `/tmp/vds_workbench_no_file_message_20260524.png`。

### 是否影响主流程

是。影响 Workbench 消息入口、普通聊天、泛数据概览和多轮展示；核心计算仍在 backend / data_agent_core，前端仍不承载指标、join、排序、聚合或评分。

### 是否涉及 Benchmark

不涉及 benchmark 题目或 scorer；新增的是 Workbench 普通消息路由和泛概览体验能力。

2026-05-24 13:13 CST

### 本次目标

按用户反馈自查并修正 Workbench 两个核心体验问题：`看一下整体销售情况` 不能把原始多字段明细行直接作为主答案返回；没有上传文件时也必须能像 GPT-like 对话一样和 VDS 直接聊天。

### 修改文件

- data_agent_core/output/response_builder.py
- backend/services/data_agent_service.py
- backend/routers/data_agent.py
- frontend/app.js
- tests/backend/test_data_agent_service.py
- tests/backend/test_workbench_static_assets.py
- README.md
- frontend/README.md
- docs/API_CONTRACT.md
- MAIN_GOAL.md
- CHANGELOG_AI.md

### 修改内容

- Response Builder 新增概览类问题展示收敛：当问题命中“整体 / 总体 / 概览 / overall summary”且执行结果是多行多列明细时，把主答案收敛为短业务概览，把主结果表收敛为 `指标 / 数值` 汇总表，并在 debug 记录 `user_experience_shaping` 证据。
- 新增 `DataAgentService.chat_without_dataset()` 和 `POST /api/data-agent/chat`：无 dataset 时允许 VDS 直接回应分析思路、字段设计、指标口径和使用方式；涉及真实销售/收入/经营结论时明确需要上传数据，不编造业务结果。
- Workbench 提交逻辑改为只要求有问题文本即可发送；有待上传文件时先静默上传再 analyze，没有 dataset 时调用 `/api/data-agent/chat`。
- 无文件 chat 结果隐藏表格、图表和洞察面板，只显示 VDS 回复和轻量过程摘要。
- 概览收敛结果隐藏原始明细图表和洞察建议，避免出现空白图表区、数据质量建议或后端审计语气。
- 用户首次发送消息后隐藏欢迎语，减少首屏占用，让结果更接近 GPT-like 对话排版。
- 静态测试补充 Workbench 必须包含 `/api/data-agent/chat` 且不能再以缺失 dataset 禁用发送按钮。
- README、frontend README、API_CONTRACT 和 MAIN_GOAL 同步说明：无文件 chat 已实现；完整 conversation persistence 仍是 Phase 11 planned；前端仍不承载指标、join、排序、聚合或评分。

### 测试方式

- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check frontend/app.js
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.backend.test_data_agent_service tests.backend.test_workbench_static_assets tests.core.test_output_contract tests.core.test_phase10_result_experience
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- git diff --check
- scripts/sync_workbench_runtime.sh
- launchctl kickstart -k gui/$(id -u)/com.trevorcui.vds.workbench
- curl 验证 `GET /workbench` 返回 200。
- Browser 插件验证无文件对话：输入 `没有文件时你能做什么？`，确认发送按钮启用、状态为 `已回复`、表格/洞察隐藏、console warning/error 为 0。
- Playwright CLI fallback 验证本地文件上传：上传 `/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/数据/QueryGPT_SaaS订阅数据_单表版.xlsx`，输入 `看一下整体销售情况`，等待 `/upload` 和 `/analyze` 均返回 200。

### 测试结果

- `node --check frontend/app.js` 通过。
- 目标后端/核心测试通过：Ran 26 tests，OK。
- 完整 unittest 通过：Ran 156 tests，OK。
- `git diff --check` 通过。
- 运行副本已同步并重启，`127.0.0.1:8001` 当前由 LaunchAgent 监听，`/workbench` 返回 200。
- 无文件 chat smoke：`POST /api/data-agent/chat` 返回 200；发送按钮 `sendEnabled=true`；状态 `已回复`；无 `Dataset not found`；表格、图表、洞察面板均隐藏；console warning/error 为 0；截图 `/tmp/vds_workbench_no_file_chat_20260524_v2.png`。
- 上传 SaaS Excel 概览 smoke：`POST /api/data-agent/upload` 和 `/api/data-agent/analyze` 均返回 200；答案长度 117；结果表头为 `["指标", "数值"]`，6 行汇总；不包含 `SS2025000001` 或 `SaaS订阅, SS2025000001` 原始明细前缀；不包含 `数据质量` / `高严重度`；图表和洞察面板隐藏；欢迎语隐藏；截图 `/tmp/vds_workbench_overview_fix_20260524_v3.png`。

### 遗留问题

- 当前 `/api/data-agent/chat` 是无 dataset 的轻量对话入口，不是 Phase 11 会话持久化；历史续聊、conversation store、多窗口隔离和 owner_context 过滤仍按 Phase 11 计划处理。
- 概览收敛是结果展示层能力；更复杂的业务口径解释、趋势/维度自动下钻仍需要继续在 Planner / Executor / Insight 能力族里增强，不能放到前端计算。
- `.playwright-cli/` 仍是本地 Playwright 运行目录，本轮不纳入 Git。

### 是否影响主流程

是。影响 Workbench 用户可见提问、无文件对话和概览类结果展示；核心执行仍由 data_agent_core / backend 完成。

### 是否涉及 Benchmark

否。没有修改 Benchmark runner、scorer、task_id、标准答案或 proxy 观察逻辑。

### 是否涉及 Microsoft Agent Framework

否。未修改 MAF adapter 或相关依赖。

### 是否影响未来多 Agent 迁移

否。无文件 chat 是 backend shell 的辅助入口；上传后 analyze 仍走当前 multi_agent workflow。概览收敛位于 Response Builder，不改变 Planner / Executor / Verifier 的职责边界。

### 是否修改核心数据契约

是。稳定响应字段未删改，但新增已实现的 `/chat` 响应形态；analyze 的 `result` 在概览类问题下可能从明细表收敛为展示汇总表。

### 是否修改 API 契约

是。新增 `POST /api/data-agent/chat` 并同步 docs/API_CONTRACT.md；明确它不等于 Phase 11 conversation APIs。

### 是否新增或修改错误类型

否。继续复用现有 `LOGIC_FORM_ERROR` 做空 question 或非法 agent_mode 的标准错误。

### 是否新增或修改运行追踪逻辑

否。只新增无 dataset chat 的安全 `reasoning_trace_view` 摘要；不新增 raw CoT 或后端审计展示。

### 是否已同步 README

是。README、frontend README、API_CONTRACT 和 MAIN_GOAL 均已同步。

---

### 日期时间

2026-05-24 11:49 CST

### 本次目标

修复真实 `/workbench` 前端可见回归：上传 Excel 失败、发送按钮不可点、上传后主界面乱跳结果、消息顺序不符合 GPT-like 对话，以及本地 `8001` 端口需要能直接打开使用。

### 修改文件

- backend/schemas/data_agent_schema.py
- tests/backend/test_data_agent_service.py
- frontend/index.html
- frontend/app.js
- frontend/styles.css
- frontend/README.md
- README.md
- scripts/run_workbench_server.sh
- scripts/sync_workbench_runtime.sh
- CHANGELOG_AI.md

### 修改内容

- 后端 `to_json_ready()` 增加 pandas / numpy scalar、非有限 float、datetime / Timestamp 的 JSON-safe 递归转换，修复 Excel 字段样例里 `Timestamp` 导致上传返回 500 的问题。
- 新增 Excel datetime profile 回归测试，确保上传响应可以被 `json.dumps()` 序列化。
- 前端发送按钮逻辑改为：有问题且已有 dataset 或待上传附件时可发送；发送时自动先上传待上传文件，再调用 analyze。
- 上传选择和上传成功保持静默：只更新底部 composer 附件状态，不展示 profile 卡片、结果面板、warnings、quality 或 verification 术语。
- 移除主界面上传失败结果面板；上传失败只在底部附件状态和顶部轻量状态中提示。
- 把过程展示改成 GPT-like 安静样式：默认只显示一行小号浅灰摘要，`查看处理过程` 点击后才展开结构化步骤，不展示 raw Chain of Thought。
- 修复结果消息 DOM 顺序：每次提问后把 assistant 结果消息移动到当前 user 消息之后，避免出现“先回答、后显示用户问题”。
- 结果区减少占位噪音：无图表、无表格、无洞察时隐藏对应区域；非成功结果不再展示可能混入数据质量/警告语气的洞察面板。
- 顶部长文件名状态做单行截断，避免多文件上传后挤乱 topbar。
- 新增 `scripts/run_workbench_server.sh` 和 `scripts/sync_workbench_runtime.sh`，配合本机 LaunchAgent 让 `http://127.0.0.1:8001/workbench` 可直接打开；由于 macOS TCC 限制，LaunchAgent 使用 `~/.vds-workbench-runtime/VDS` 运行副本。
- README / frontend README 同步本地 Workbench 启动、运行副本和端口说明。

### 测试方式

- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check frontend/app.js
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.backend.test_data_agent_service tests.backend.test_workbench_static_assets
- git diff --check
- curl 验证 `GET /workbench`、`GET /frontend/app.js`、`GET /frontend/styles.css` 均返回 200。
- 同步运行副本并重启 LaunchAgent：`scripts/sync_workbench_runtime.sh && launchctl kickstart -k gui/$(id -u)/com.trevorcui.vds.workbench`
- Browser 插件打开 `http://127.0.0.1:8001/workbench`，检查页面标题、首屏、console errors/warnings 和静默初始状态。
- Playwright fallback 在真实 `8001/workbench` 选择 5 个本地 Excel 文件，输入 `哪个城市销售额最高？`，点击发送并等待 upload-batch / analyze 响应。

### 测试结果

- `node --check frontend/app.js` 通过。
- Backend/static asset unittest 通过：Ran 10 tests，OK。
- `git diff --check` 通过。
- curl 结果：`/workbench`、`/frontend/app.js`、`/frontend/styles.css` 均为 200。
- LaunchAgent 正在运行，`127.0.0.1:8001` 有监听；当前运行副本已同步到 `~/.vds-workbench-runtime/VDS`。
- Browser 检查：页面标题为 `Virtual Data Scientist Workbench`，console errors/warnings 为 0；初始状态 `resultHidden=true`、`profileHidden=true`、无 `.upload-card` / `#dropzone`。
- Playwright 5-Excel smoke：选择文件后 `fileSummary=5 个文件已附加`、`resultHidden=true`、`profileHidden=true`；输入问题后发送按钮可点；`POST /api/data-agent/upload-batch` 返回 200，`POST /api/data-agent/analyze` 返回 200；最终 `fileSummary=5 个文件已就绪`、`historyCount=1`、消息顺序为 welcome -> user -> assistant，console/page issues 为空。

### 遗留问题

- 当前 smoke 使用 `VDS_LLM_PROVIDER=mock`；mock 结果质量仍由后端当前分析链路决定，本轮只修复上传、前端交互、排版和本地端口可用性，不改核心分析、join、排序、聚合或评分逻辑。
- `.playwright-cli/` 仍是本地 Playwright 运行目录，本轮不纳入 Git。
- 多会话隔离、历史续聊和未来用户隔离仍按 Phase 11 文档规划，尚未实现。

### 是否影响主流程

是。影响 Workbench 用户可见上传和提问流程，但不修改核心分析算法。

### 是否涉及 Benchmark

否。没有修改 Benchmark runner、scorer、task_id、标准答案或 proxy 观察逻辑。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

否。前端仍只调用 upload / analyze API，不承载 Agent 编排、join、聚合、排序或评分逻辑。

### 是否修改核心数据契约

否。只增强响应序列化安全性，不改变稳定字段形态。

### 是否修改 API 契约

否。未新增或删除 API 字段。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。过程展示只使用已有 safe summary，不展示 raw Chain of Thought。

### 是否已同步 README

是。README 和 frontend README 已同步本地 Workbench 端口、LaunchAgent / runtime copy 和验证说明。

---

### 日期时间

2026-05-24 11:11 CST

### 本次目标

让本机打开 `http://127.0.0.1:8001/workbench` 时可以直接使用，不再依赖手动临时启动进程。

### 修改文件

- scripts/run_workbench_server.sh
- scripts/sync_workbench_runtime.sh
- README.md
- CHANGELOG_AI.md
- /Users/trevorcui/Library/LaunchAgents/com.trevorcui.vds.workbench.plist

### 修改内容

- 新增 `scripts/run_workbench_server.sh`，固定从 `/Users/trevorcui/Documents/VDS` 启动 `backend.main:app`，默认监听 `127.0.0.1:8001`。
- 新增 `scripts/sync_workbench_runtime.sh`，用于把当前仓库同步到 `~/.vds-workbench-runtime/VDS` 常驻服务目录。
- 启动脚本会读取 `.env.local`，没有显式 provider 配置时默认 `VDS_LLM_PROVIDER=mock`；脚本会检查并安装缺失的 `fastapi`、`uvicorn`、`python-multipart` 服务依赖。
- 新增用户级 macOS LaunchAgent `com.trevorcui.vds.workbench`，`RunAtLoad` + `KeepAlive` 保活 8001 服务。
- 由于 macOS 后台进程无法直接访问 `Documents/VDS`，LaunchAgent 实际从 `~/.vds-workbench-runtime/VDS` runtime 副本启动；当前已同步本仓库内容到该 runtime。
- README 记录本机 LaunchAgent、runtime 副本和启动脚本，说明以后打开 `/workbench` 应可直接使用。

### 测试方式

- bash -n scripts/run_workbench_server.sh
- bash -n scripts/sync_workbench_runtime.sh
- bash -n /Users/trevorcui/.vds-workbench-runtime/VDS/scripts/run_workbench_server.sh
- plutil -lint /Users/trevorcui/Library/LaunchAgents/com.trevorcui.vds.workbench.plist
- launchctl bootstrap / bootout / kickstart 用户级 LaunchAgent
- launchctl print gui/$(id -u)/com.trevorcui.vds.workbench
- lsof -iTCP:8001 -sTCP:LISTEN -nP
- curl -sS -D - --max-time 5 http://127.0.0.1:8001/workbench -o /tmp/vds-workbench.html
- curl -I --max-time 5 http://127.0.0.1:8001/frontend/app.js
- KeepAlive smoke：kill 当前 uvicorn pid，等待 launchd 自动重启，再访问 `/workbench`
- git diff --check

### 测试结果

- repo 启动脚本和 runtime 启动脚本 `bash -n` 通过。
- runtime 同步脚本 `bash -n` 通过。
- LaunchAgent plist `plutil -lint` 通过。
- LaunchAgent 已成功 bootstrap / kickstart，`launchctl print` 显示 `state = running`。
- 8001 监听正常，当前由 launchd 管理的 uvicorn 进程监听 `127.0.0.1:8001`。
- `/workbench` 返回 `HTTP/1.1 200 OK`，HTML 正确引用 `/frontend/styles.css` 和 `/frontend/app.js`。
- `/frontend/app.js` 和 `/frontend/styles.css` 均返回 200。
- KeepAlive smoke 通过：kill 当前 uvicorn 后，launchd 自动拉起新 pid，`/workbench` 仍返回 200。

### 遗留问题

- 当前 LaunchAgent 是本机用户级配置，不是跨机器部署方案。
- 如果要使用真实 provider，必须确认 `.env.local` 中 provider 和 key 配置正确；否则脚本默认使用 mock。

### 是否影响主流程

是。影响本机 Workbench 启动方式，但不修改后端 API 行为或核心分析逻辑。

### 是否涉及 Benchmark

否。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

否。只是本地服务启动方式。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

### 是否已同步 README

是。README 已记录本机常驻 8001 的启动脚本和 LaunchAgent。

---

### 日期时间

2026-05-24 11:07 CST

### 本次目标

修复 Workbench 选择文件并输入问题后发送按钮仍不可点击的问题；让 GPT-like composer 支持直接发送，前端自动先上传待选文件，再提交分析请求。

### 修改文件

- frontend/app.js
- frontend/README.md
- README.md
- CHANGELOG_AI.md

### 修改内容

- `updateRunButton()` 改为在“已有 dataset”或“存在待上传文件”时都允许发送，不再强制用户先点击小型上传按钮。
- `runAnalysis()` 在存在待上传文件时先调用上传 API，上传成功后再追加用户消息并调用 `/api/data-agent/analyze`。
- 增加 `state.hasPendingUpload`、`state.isUploading`、`state.isAnalyzing`，避免重复点击和重新选文件后误用旧 dataset。
- 上传成功后禁用并隐藏独立上传按钮，文件状态显示“已上传”；重新选择文件后再次进入待上传状态。
- README / frontend README 同步说明 composer 会先上传待选文件再分析，前端仍不实现核心计算。

### 测试方式

- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check frontend/app.js
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.backend.test_workbench_static_assets
- git diff --check
- Playwright smoke：打开 `http://127.0.0.1:8001/workbench`，上传 `/tmp/vds_sales_smoke.csv` 和 `/tmp/vds_city_smoke.csv`，输入“哪个城市销售额最高？”，检查发送按钮 `disabled=false`，点击发送后等待自动 `upload-batch` 和 `analyze` 完成。
- Playwright console / network 检查。

### 测试结果

- node syntax check 通过。
- backend static workbench tests 通过：Ran 3 tests，OK。
- git diff --check 通过。
- Playwright 发送按钮状态验证通过：选中文件并输入问题后 `disabled=false`。
- Playwright 自动上传并分析通过：`POST /api/data-agent/upload-batch` 200，`POST /api/data-agent/analyze` 200，状态为“分析完成”，答案为“北京, 250”，历史数量为 1。
- Browser console 检查：0 errors，0 warnings。

### 遗留问题

- 当前本地 8001 服务仍以 `VDS_LLM_PROVIDER=mock` 运行；真实 provider 链路需要用真实环境变量重启。
- `.playwright-cli/` 仍是本地未跟踪目录，本轮未纳入 Git。

### 是否影响主流程

是。修复 Workbench 用户提交路径，但只改变前端调用顺序和按钮状态；后端 upload / analyze 核心契约不变。

### 是否涉及 Benchmark

否。未修改 Benchmark 数据、runner、scorer 或核心能力逻辑。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

否。前端仍只调用后端稳定 API，不接触 multi_agent workflow 内部实现。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。仍使用既有 `/api/data-agent/upload`、`/api/data-agent/upload-batch` 和 `/api/data-agent/analyze`。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

### 是否已同步 README

是。README 已同步说明选择文件后可直接发送，前端会先上传再分析。

---

### 日期时间

2026-05-23 17:41 CST

### 本次目标

按用户反馈继续把 `/workbench` PC 前端视觉向 ChatGPT 桌面体验靠拢，并恢复用户正在访问的 `127.0.0.1:8001/workbench` 本地服务。

### 修改文件

- frontend/index.html
- frontend/styles.css
- frontend/app.js
- CHANGELOG_AI.md

### 修改内容

- 恢复 `8001` uvicorn 服务，使用 `.env.local` 的真实 provider 环境启动，避免 Edge 访问 `127.0.0.1:8001/workbench` 出现 `ERR_CONNECTION_REFUSED`。
- 重写 `/workbench` 主要视觉系统：弱化后台面板感，采用浅灰侧栏、白色聊天画布、居中内容列、底部悬浮 composer、小圆形发送按钮和更接近 ChatGPT 的信息密度。
- 隐藏执行模式 / Agent 下拉控件，保留默认后端调用参数，减少用户主界面干扰。
- 简化字段预览表，只展示字段、类型、样例，去掉缺失率 / 唯一值 / 语义等偏审计信息。
- 结果态改成开放式回答：答案优先、单条结果不强行绘制图表，保留结果表、简要结论和用户可读过程。
- 将分析过程从后端阶段日志压缩成 6 个用户可理解步骤：理解问题、选择数据、匹配字段、关联数据、执行分析、生成回答。
- 洞察列表不再展示 caveat / 注意类文案，避免主界面出现 warning 式信息。

### 测试方式

- `node --check frontend/app.js`
- `PYTHONPATH=/tmp/vds-fastapi-deps312:$PWD /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.backend.test_workbench_static_assets`
- `git diff --check`
- curl smoke：`/workbench`、`/frontend/styles.css`、`/frontend/app.js`、`/frontend/favicon.svg`
- Browser smoke：打开 `http://127.0.0.1:8001/workbench`，检查 title、console warn/error、首屏和禁止审计字段。
- Playwright PC smoke：1365x768 访问 `http://127.0.0.1:8001/workbench`，上传 `订单表.csv / 客户表.csv / 库存文件.csv`，提问“哪个城市订单金额最高？”，检查答案、过程、禁止词和截图。

### 测试结果

- `node --check frontend/app.js` 通过。
- `tests.backend.test_workbench_static_assets` 3/3 通过。
- `git diff --check` 通过。
- `8001` 当前监听中；`/workbench` 返回 `200 text/html`，CSS / JS / favicon 均返回 200。
- Browser smoke：页面 title 正确，console warn/error 为空，主界面不含“数据质量”、“Warnings / Errors”、“Join / Verification”、“dataset_id:”、“source_tables”、“join_plan”。
- Playwright PC smoke：答案为 `北京, 200`；单条结果 chart 已隐藏；主界面不含审计禁止词；过程压缩为 6 步；截图保存在 `/tmp/vds-gpt-redesign-current/01-desktop-initial.png` 和 `/tmp/vds-gpt-redesign-current/05-desktop-result.png`。

### 遗留问题

- 本轮按用户要求聚焦 PC 网页端，未做移动端适配优化。
- 当前视觉是 GPT-like 产品骨架，不是复制 OpenAI 受保护品牌资产；保留 VDS 自有名称和蓝色图标。

### 是否影响主流程

是，仅影响 `/workbench` 前端展示和本地测试服务恢复；不影响后端分析逻辑。

### 是否涉及 Benchmark

否。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

否。前端仍只调用后端 API，不承载 Agent 编排。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。只修改前端对过程摘要的用户化展示。

### 是否已同步 README

否。本轮是 `/workbench` 视觉审美重排和本地服务恢复，未改变阶段定义、API 契约、Benchmark 口径或 README 已记录的主能力边界。

---

### 日期时间

2026-05-23 13:56 CST

### 本次目标

按用户反馈把 `/workbench` PC 主界面从后端审计面板改为 GPT-like 用户可读过程体验：不再直接展示数据质量、Warnings / Errors、Join / Verification、dataset_id、run_id 或 join trace JSON，只展示当前正在理解什么、选择哪些数据、如何分析以及最终答案。

### 修改文件

- README.md
- MAIN_GOAL.md
- frontend/README.md
- frontend/index.html
- frontend/styles.css
- frontend/app.js
- tests/backend/test_workbench_static_assets.py
- CHANGELOG_AI.md

### 修改内容

- 从主界面删除数据质量、Join / Verification、Warnings / Errors 等用户不可读审计面板。
- 将 `reasoning_trace_view` 转译为用户可读分析过程：读取上传数据、理解问题、选择相关数据、匹配字段含义、制定分析方式、判断多表关联、执行分析、核对结果、选择展示方式、整理结论、生成回答。
- 分析请求期间展示 live progress：理解问题、选择相关数据、匹配字段含义、制定分析方式、执行分析、生成回答。
- 顶部状态与历史记录去技术化：不再显示 `dataset_id:`、`run_id`、`success / run_xxx`，改为“未上传数据 / 数据已上传 / 已完成分析”等用户语言。
- 图表区域不再显示后端英文 chart selection reason，只展示图表本身或自然语言提示。
- README、MAIN_GOAL 和 frontend README 同步说明：质量报告、warnings/errors、verification、join trace 保留在后端/API，不在主界面直接展示；前端仍不实现计算、join、排序、聚合或评分。
- 静态测试增加断言，防止 `/workbench` HTML 再次出现用户不可读审计面板文字。

### 测试方式

- `node --check frontend/app.js`
- `PYTHONPATH=/tmp/vds-fastapi-deps312:$PWD /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.backend.test_workbench_static_assets`
- `git diff --check`
- curl smoke：`/workbench`、`/frontend/styles.css`、`/frontend/app.js`、`/frontend/favicon.svg`
- Browser shell smoke：打开 `http://127.0.0.1:8004/workbench`，检查页面身份、console warn/error、首屏状态和审计面板隐藏状态。
- Playwright PC smoke：真实访问 `http://127.0.0.1:8004/workbench`，上传 `订单表.csv / 客户表.csv / 库存文件.csv`，提问“哪个城市订单金额最高？”，检查处理中过程、最终过程、答案、历史记录和禁止词。

### 测试结果

- `node --check frontend/app.js` 通过。
- `tests.backend.test_workbench_static_assets` 3/3 通过。
- `git diff --check` 通过。
- `/workbench` 返回 `200 text/html`；`/frontend/styles.css` 返回 `200 text/css`；`/frontend/app.js` 返回 `200 text/javascript`；`/frontend/favicon.svg` 返回 `200 image/svg+xml`。
- Browser shell smoke：title 为 `Virtual Data Scientist Workbench`；console warn/error 为空；首屏 `准备就绪 / 未上传数据`；`.upload-card` / `.dropzone` 为 0；首屏不含“数据质量”、“Warnings / Errors”、“Join / Verification”。
- Playwright PC smoke：上传后显示 `3 张表，8 行`；处理中显示“理解你的问题 / 选择相关数据 / 匹配字段含义 / 制定分析方式 / 执行分析 / 生成回答”；最终答案为 `北京, 200`；过程显示“已选择 订单表、客户表”、“按 客户ID 关联后再回答”；主界面禁止词为空，未显示 `dataset_id:`、`run_id`、`source_tables`、`join_plan` 或英文 chart reason。
- PC 截图与报告：`/tmp/vds-workbench-pc-process-current/04-pc-processing-steps.png`、`/tmp/vds-workbench-pc-process-current/05-pc-result-process.png`、`/tmp/vds-workbench-pc-process-current/report-final.json`。

### 遗留问题

- 本轮按用户要求暂不处理移动端验收。
- 前端展示的是后端安全结构化摘要的用户化表达，不展示完整 Chain of Thought、raw reasoning tokens、raw prompt 或后端审计 JSON。

### 是否影响主流程

是，仅影响 `/workbench` PC 主界面展示体验和文档说明；不影响后端分析逻辑。

### 是否涉及 Benchmark

否。未修改 Benchmark、runner、scorer、标准答案或 public proxy。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

否。前端仍只调用稳定后端 API 并展示后端契约摘要，不承载 Agent 编排或核心计算。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。后端仍返回 quality_report、warnings、errors、verification、debug 和 join trace；只是前端主界面不直接展示这些审计字段。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。只修改前端对 `reasoning_trace_view` 的用户化展示。

### 是否已同步 README

是。已同步 README.md、MAIN_GOAL.md 和 frontend/README.md，说明主界面不再直接展示后端审计明细。

---

### 日期时间

2026-05-23 13:05 CST

### 本次目标

按用户要求把 `/workbench` 上传入口改为 GPT-like 底部 composer 左下角交互，并切换为浅色蓝色主视觉；删除首屏上方上传卡片，避免页面上半区出现上传框。

### 修改文件

- frontend/index.html
- frontend/styles.css
- frontend/app.js
- frontend/favicon.svg
- tests/backend/test_workbench_static_assets.py
- CHANGELOG_AI.md

### 修改内容

- 删除首条 assistant 消息中的 `upload-card` / `dropzone` 上传大框。
- 将 `file-input`、纸夹选择按钮、上传按钮和文件状态移动到底部 composer 左侧。
- 将 workbench token 从深色侧栏 / 绿色 accent 调整为浅蓝侧栏 / 蓝色 accent，按钮、图标、selected state 和 chart 颜色同步蓝色体系。
- 新增 `/frontend/favicon.svg` 蓝色网页 icon，并在 HTML 中引用。
- JS 删除对 `dropzone` 的依赖，文件选择后只更新底部 compact status；上传和分析仍只调用后端 API，不在前端实现计算、join、排序、聚合或评分。
- 静态测试新增 favicon、底部 upload-controls、无 `upload-card` / `dropzone` 断言。

### 测试方式

- node --check frontend/app.js
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.backend.test_workbench_static_assets
- git diff --check -- frontend/index.html frontend/styles.css frontend/app.js frontend/favicon.svg tests/backend/test_workbench_static_assets.py CHANGELOG_AI.md
- curl smoke: `/workbench`、`/frontend/styles.css`、`/frontend/app.js`、`/frontend/favicon.svg`、`/styles.css`、`/app.js`
- Browser / Playwright smoke: 真实访问 `http://127.0.0.1:8001/workbench`，检查 console、桌面截图、移动视口、选择 CSV、上传 profile。

### 测试结果

- `node --check frontend/app.js` 通过。
- `tests.backend.test_workbench_static_assets` 2/2 通过。
- `git diff --check` 通过。
- `/workbench` 返回 `200 text/html`；`/frontend/styles.css` 返回 `200 text/css`；`/frontend/app.js` 返回 `200 text/javascript`；`/frontend/favicon.svg` 返回 `200 image/svg+xml`。
- `/styles.css` 和 `/app.js` 仍返回 404，但页面 HTML 不再引用它们。
- Browser desktop smoke：console warning / error 为空；首屏为浅色蓝色左侧历史 Chat + 中间 chat + 底部 composer；`.upload-card` 和 `#dropzone` 不存在；favicon href 为 `/frontend/favicon.svg`。
- Playwright mobile smoke：选择 CSV 后底部状态为 `1 个文件待上传`，上传后 profile 显示 `1 张表，3 行`，上方上传框数量为 0。
- 真实 provider analyze smoke 未完成：当前 shell 初始未 export key；随后确认 `.env.local` 存在真实 key，但当前 8001 uvicorn 进程仍未在 analyze 路径读取到 provider 配置，返回 `Set VDS_LLM_PROVIDER=openai or deepseek...`。本轮不把该后端启动环境问题记为前端通过项。

### 遗留问题

- 需要单独收敛本地 8001 的真实 provider 启动方式，确保 uvicorn 进程实际继承 `.env.local` 后再跑完整真实 analyze UI smoke。
- 当前 worktree 已有大量无关 dirty 文件，本轮只触碰上述前端、静态测试和 changelog 文件，不回滚、不覆盖其他改动。

### 是否影响主流程

是，仅影响 `/workbench` 用户界面布局和静态资源；不影响后端分析逻辑。

### 是否涉及 Benchmark

否。本轮不改 Benchmark、runner、scorer、标准答案或 public proxy。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

否。前端仍只调用后端 API 并展示契约结果。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

### 是否已同步 README

否。本轮只是既有 `/workbench` 的视觉和上传入口调整，不改变项目阶段、主目标、API 契约、Benchmark 口径或 GitHub 首页能力摘要。

---

### 日期时间

2026-05-23 12:47 CST

### 本次目标

按用户要求在 Phase 9 之后继续实施 Phase 10：结果图表自动展示、洞察建议、数据质量扫描和安全过程可视化；同时用 mock full gate 和真实 DeepSeek representative 验证模型能力 / 泛化能力不退步，并整理 git。

### 修改文件

- README.md
- MAIN_GOAL.md
- docs/API_CONTRACT.md
- docs/FEATURE_BACKLOG.md
- CHANGELOG_AI.md
- backend/main.py
- backend/routers/data_agent.py
- backend/schemas/data_agent_schema.py
- backend/services/data_agent_service.py
- backend/storage/temp_file_store.py
- agent_runtime/data_agent_tool_impl.py
- agent_runtime/data_analysis_roles.py
- multi_agent_workflows/end_to_end_data_analysis_workflow.py
- data_agent_core/contracts/analysis_contracts.py
- data_agent_core/contracts/dataset_contracts.py
- data_agent_core/contracts/response_contracts.py
- data_agent_core/core/analysis_planner.py
- data_agent_core/core/capability_registry.py
- data_agent_core/core/data_quality.py
- data_agent_core/core/file_parser.py
- data_agent_core/core/intent_parser.py
- data_agent_core/core/logic_form.py
- data_agent_core/core/schema_profiler.py
- data_agent_core/executors/pandas_executor.py
- data_agent_core/llm/planner.py
- data_agent_core/output/chart_planner.py
- data_agent_core/output/insight_generator.py
- data_agent_core/output/reasoning_trace_view.py
- data_agent_core/output/response_builder.py
- data_agent_core/tracing/run_trace.py
- data_agent_core/verifier/rule_checker.py
- frontend/index.html
- frontend/styles.css
- frontend/app.js
- frontend/README.md
- tests/backend/test_data_agent_service.py
- tests/backend/test_workbench_static_assets.py
- tests/core/test_phase8_multitable_capabilities.py
- tests/core/test_phase10_result_experience.py
- tests/core/test_semantic_metric_verification.py

### 修改内容

- Phase 10 增加后端稳定输出契约：`chart`、`insight`、`quality_report`、`reasoning_trace_view`。
- Chart planner 自动选择 bar / horizontal_bar / line / pie / donut / histogram / KPI；前端只根据后端 `chart_type` 渲染，不做图表选择和指标计算。
- Insight generator 基于 verified result 和质量报告生成摘要、异常、波动、建议和 caveats，不读取 benchmark 标准答案。
- 新增数据质量扫描：缺失值、重复行、疑似表头、常量列、混合数值类型、离群值、可疑负值、非法日期、高基数分类和 join key 重复风险。
- 用户问“我的文件有什么问题”等数据质量问题时，intent / planner / executor 可进入 `data_quality_report`。
- `reasoning_trace_view` 只展示阶段摘要、意图识别、执行和验证信息，不暴露完整 Chain of Thought、raw reasoning、raw prompt、API key 或 hidden benchmark answer。
- Workbench 增加图表、洞察、质量报告和过程时间线展示；前端仍禁止实现核心分析逻辑、join、排序、聚合、异常规则或清洗逻辑。
- 修复 Phase 10 回归暴露的 `data_quality.py` 负值样本索引不对齐问题。
- 上传表 workflow 在 `from_uploaded_tables` 阶段生成 dataset profile 和质量报告缓存，避免 Microsoft / VDS 多题回归中每题重复扫描整套表。
- README、MAIN_GOAL、FEATURE_BACKLOG 和 API_CONTRACT 同步 Phase 10 已完成状态、验收结果、真实 DeepSeek representative 和 full real 未执行限制。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_phase10_result_experience
- node --check frontend/app.js
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime multi_agent_workflows backend tests
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.backend.test_data_agent_service tests.core.test_generic_capability_operations tests.core.test_output_contract tests.core.test_semantic_metric_verification tests.core.test_phase8_multitable_capabilities
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- git diff --check
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/phase10_dabstep_dev_1_10_mock_20260523
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 450 --offset 0 --output-dir outputs/phase10_dabstep_all_1_450_mock_20260523
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.microsoft_anonymized_benchmark_runner --dataset-root /Users/trevorcui/Desktop/微软脱敏数据 --limit 300 --offset 0 --output-dir outputs/phase10_microsoft_1_300_mock_20260523
- VDS_LLM_PROVIDER=mock inline runner for `/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/问题/问题汇总.xlsx`, output `outputs/phase10_vds_question_summary_95_mock_20260523.json`
- set -a; . ./.env.local; set +a; VDS_LLM_PROVIDER=deepseek /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/phase10_dabstep_dev_1_10_deepseek_real_20260523
- set -a; . ./.env.local; set +a; VDS_LLM_PROVIDER=deepseek /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.microsoft_anonymized_benchmark_runner --dataset-root /Users/trevorcui/Desktop/微软脱敏数据 --limit 20 --offset 0 --output-dir outputs/phase10_microsoft_1_20_deepseek_real_20260523
- set -a; . ./.env.local; set +a; VDS_LLM_PROVIDER=deepseek inline runner for VDS 五域各前三题，output `outputs/phase10_vds_question_summary_15_deepseek_real_20260523.json`

### 测试结果

- Phase 10 focused tests 通过：Ran 5 tests，OK。
- Targeted backend / core regression 通过：Ran 77 tests，OK。
- Full unittest 通过：Ran 142 tests in 10.799s，OK。
- compileall 通过。
- `node --check frontend/app.js` 通过。
- `git diff --check` 通过。
- DABstep dev 1-10 mock：correct=9/10，success_count=10，format_risk=0，submission_risk=0，trace_redaction_risk=0。
- DABstep public all 1-450 mock：success_count=450/450，unexpected_not_applicable=0，true_unsupported=3，format_risk=0，submission_risk=0，trace_redaction_risk=0。
- Microsoft 脱敏数据 1-300 mock scorer：correct=300/300，accuracy=1.0，success_count=300，format_risk=0，semantic_risk=0，submission_risk=0，trace_redaction_risk=0。
- 原本 VDS `问题汇总.xlsx` 95 题 mock smoke：total=95，success_count=95，failure_count=0，output_contract_failure_count=0，trace_redaction_risk=0。
- 真实 DeepSeek DABstep dev 1-10：correct=9/10，success_count=10，format_risk=0，submission_risk=0，trace_redaction_risk=0；剩余失败仍为既有 `best_fraud_aci_choice` / associated cost 语义口径。
- 真实 DeepSeek Microsoft 1-20：correct=20/20，accuracy=1.0，success_count=20，format_risk=0，submission_risk=0，trace_redaction_risk=0。
- 真实 DeepSeek VDS 五域 15 题：success_count=15/15，failure_count=0，output_contract_failure_count=0，trace_redaction_risk=0。

### 遗留问题

- 完整 450 / 300 / 95 真实 provider full 回归仍未执行；当前真实 provider 只代表 representative，不得冒充 full real score。
- DABstep dev 仍有既有 `best_fraud_aci_choice` / ACI associated cost 语义口径缺口，后续应按通用 fee candidate table / associated cost 能力族修复，不能按 task_id 或固定答案特调。
- Phase 10 只输出数据质量问题和清洗建议，不自动修改用户原始数据；自动清洗必须另开新 Phase 并要求用户确认。
- `.playwright-cli/` 仍是本地既有未跟踪目录，本轮不纳入 Git。

### 是否影响主流程

是。默认 analyze / upload / workbench 返回和展示的结果体验字段增加，但核心计算仍在 data_agent_core / backend，前端只渲染后端契约。

### 是否涉及 Benchmark

是。复跑 DABstep、Microsoft 和原本 VDS 三类门禁；标准答案、public proxy、accepted answer、hidden answer 和 task_id 仍只用于 response 之后的离线评分 / 风险观察，未进入 Planner、Executor、Verifier、Correction、prompt、trace 或测试 fixture。

### 是否涉及 Microsoft Agent Framework

否。未修改 ms_agent_framework_adapter，也未把 MAF 作为核心依赖。

### 是否影响未来多 Agent 迁移

是，正向影响。`chart`、`insight`、`quality_report` 和 `reasoning_trace_view` 都是 provider-neutral / adapter-neutral 的稳定输出，可由当前 internal multi-agent workflow 和未来 adapter 复用。

### 是否修改核心数据契约

是。扩展 `FinalResponse`、`ChartSpec`、`InsightResult`，新增 `DataQualityReport`、`DataQualityIssue`、`ReasoningTraceStep`，并让 `DatasetProfile` 可携带 `quality_report`。

### 是否修改 API 契约

是。`docs/API_CONTRACT.md` 已同步 Phase 10 响应字段和 trace-safe 过程展示边界。

### 是否新增或修改错误类型

否。首版数据质量能力复用现有 warnings / errors 和质量报告字段，不新增 error_type。

### 是否新增或修改运行追踪逻辑

是。RunTrace 增加 `quality_report` 和 `reasoning_trace_view`；过程展示只保留结构化摘要，不记录完整 Chain of Thought。

### 是否已同步 README

是。README 已同步 Phase 10 完成状态、mock full gate、真实 DeepSeek representative、profile 缓存修复和 full real 未执行限制。

---

### 日期时间

2026-05-23 11:41 CST

### 本次目标

回应“必须用真实 DeepSeek 跑，否则无法判断模型能力是否下降”的问题：使用 `.env.local` 中的 DeepSeek 配置补跑 Phase 8/9 representative 回归，发现并修复原本 VDS 真实 provider 下的 candidate_set 契约归一化问题，再同步 README / MAIN_GOAL / FEATURE_BACKLOG。

### 修改文件

- MAIN_GOAL.md
- README.md
- docs/FEATURE_BACKLOG.md
- CHANGELOG_AI.md
- data_agent_core/core/analysis_planner.py
- tests/core/test_semantic_metric_verification.py

### 修改内容

- 使用真实 DeepSeek 跑 DABstep dev 1-10、Microsoft 脱敏数据 1-20、原本 VDS 五域代表集 15 题。
- 初次 VDS 15 题真实 DeepSeek 为 `5/15`，失败原因是 LLM 输出的 `candidate_set` 只有自然语言描述、没有稳定 `source` 字段，Verifier 正确判为候选集契约不完整。
- 在 `complete_generalization_contract()` 中新增 candidate_set 归一化：当 LLM 给出候选集描述但缺少 `source` 时，按结构化 `entity` / `dimension` / `field` 或 group field 补为 `source=data`，不放宽 Verifier，不改业务计算，不使用题号、标准答案、固定样本值或 public proxy。
- 新增单元测试，覆盖 LLM candidate_set 无 source 时归一化为 verifier-safe 契约。
- 文档同步：当前状态改为已跑真实 DeepSeek representative；同时明确完整 450 / 300 / 95 full real 回归仍未执行，不能用 representative 冒充 full real score。

### 测试方式

- set -a; . ./.env.local; set +a; VDS_LLM_PROVIDER=deepseek /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/phase8_dabstep_dev_1_10_deepseek_real_20260523
- set -a; . ./.env.local; set +a; VDS_LLM_PROVIDER=deepseek /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.microsoft_anonymized_benchmark_runner --dataset-root /Users/trevorcui/Desktop/微软脱敏数据 --limit 20 --offset 0 --output-dir outputs/phase8_microsoft_1_20_deepseek_real_20260523
- set -a; . ./.env.local; set +a; VDS_LLM_PROVIDER=deepseek 原本 VDS `问题汇总.xlsx` 五域各取前三题代表集，输出 `outputs/phase8_vds_question_summary_15_deepseek_real_after_candidate_fix_20260523.json`
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_semantic_metric_verification
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall backend frontend data_agent_core agent_runtime multi_agent_workflows tests
- node --check frontend/app.js
- git diff --check

### 测试结果

- DABstep dev 1-10 真实 DeepSeek：correct=9/10，accuracy=0.9，保住当前 `9/10` 基线；剩余失败仍为既有 `best_fraud_aci_choice` / associated cost 语义口径。
- Microsoft 脱敏数据 1-20 真实 DeepSeek：correct=20/20，accuracy=1.0。
- 原本 VDS 五域 15 题真实 DeepSeek：初次 `5/15`；candidate_set 归一化修复后 `15/15`，output_contract_failure_count=0。
- focused semantic tests 通过：Ran 14 tests，OK。
- 全量 unittest 通过：Ran 136 tests，OK。
- compileall 通过。
- node --check frontend/app.js 通过。
- git diff --check 通过。

### 遗留问题

- 真实 DeepSeek full 回归仍未执行：DABstep public all 1-450、Microsoft 1-300、原本 VDS 95 全量都还只是 mock / 离线 full 通过，真实 provider 当前只有 representative。
- DABstep dev 仍保留 `best_fraud_aci_choice` / ACI associated cost 通用语义口径后续项。
- `.playwright-cli/` 仍是本地既有未跟踪目录，本轮未纳入变更。

### 是否影响主流程

是。修复真实 provider 下 Planner generalization contract 的 candidate_set 归一化，影响 Verifier 前的稳定契约补全。

### 是否涉及 Benchmark

是。涉及 DABstep dev、Microsoft 脱敏数据和原本 VDS representative；标准答案只在 response 之后用于离线评分，未进入 Agent workflow、prompt、Planner、Executor、Verifier、Correction 或 trace。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

是，正向影响。candidate_set 归一化让真实 provider 输出更稳定地进入 multi_agent workflow 和后续 adapter。

### 是否修改核心数据契约

是。规范了已有 `candidate_set` 字段的结构补全规则。

### 是否修改 API 契约

否。未修改外部 API 字段。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。trace 会自然记录归一化后的 `candidate_set`。

### 是否已同步 README

是。README 已同步真实 DeepSeek representative 结果和 full real 未执行限制。

---

### 日期时间

2026-05-23 12:16 CST

### 本次目标

修复真实 `/workbench` 入口下前端 CSS / JS 资源路径错误导致页面退化为裸 HTML 的问题，并补充防回归测试和真实浏览器 smoke。

### 修改文件

- frontend/index.html
- tests/backend/test_workbench_static_assets.py
- CHANGELOG_AI.md

### 修改内容

- 将 workbench 页面资源引用从相对路径 `./styles.css` / `./app.js` 改为后端实际挂载路径 `/frontend/styles.css` / `/frontend/app.js`。
- 新增静态单测，防止 `/workbench` 再次返回无法加载样式和脚本的 HTML。
- 保持前端只负责上传、提问和展示，不新增指标公式、join、排序、聚合、评分或后端核心分析逻辑。

### 测试方式

- curl 验证 `GET /workbench`、`GET /frontend/styles.css`、`GET /frontend/app.js`
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.backend.test_workbench_static_assets
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check frontend/app.js
- Browser smoke 真实访问 `http://127.0.0.1:8001/workbench`，检查页面标题、DOM、console、桌面截图、移动截图和上传按钮交互
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.backend.test_data_agent_service tests.backend.test_workbench_static_assets
- curl 上传 `/tmp/vds-workbench-smoke.csv` 到 `POST /api/data-agent/upload`
- VDS_LLM_PROVIDER=mock 直接运行 backend service 上传 + analyze smoke
- git diff --check

### 测试结果

- `/workbench` 返回 `200 text/html`，HTML 内资源已指向 `/frontend/styles.css` 和 `/frontend/app.js`。
- `/frontend/styles.css` 返回 `200 text/css`，`/frontend/app.js` 返回 `200 text/javascript`。
- 新增 workbench 静态资源测试通过：Ran 1 test，OK。
- backend service + workbench 静态测试通过：Ran 7 tests，OK。
- `node --check frontend/app.js` 通过。
- Browser smoke：页面标题为 `Virtual Data Scientist Workbench`，console warning / error 为空，桌面视口恢复左侧深色导航、主工作区卡片和右侧审计栏；移动视口资源加载正常。
- 上传按钮空文件交互正常显示 `请选择文件`，未产生 console error。
- API 上传 smoke 成功：`success=True`，1 张表，2 行，2 列。
- mock analyze smoke 成功：上传 3 行 CSV 后返回 `success=True`，首行结果为 `{'city': 'Shanghai', 'amount': 150}`。
- git diff --check 通过。

### 遗留问题

- 本轮只修复真实 workbench 入口资源路径和首屏渲染，不重做产品设计。
- Browser 插件当前未执行真实文件选择上传；文件上传通过 API smoke 和 backend service mock analyze 验证。

### 是否影响主流程

是。影响用户访问 `/workbench` 的前端展示入口，但不改变后端分析主流程。

### 是否涉及 Benchmark

否。未修改 Benchmark 数据、runner、scorer、标准答案或 public proxy 观察链路。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

否。仅修复前端静态资源入口，不改 multi_agent workflow、agent_runtime 或 adapter。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。`/workbench` 与 `/frontend/*` 既有契约不变，只修复 HTML 资源引用。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

### 是否已同步 README

否。本轮不改变项目阶段、API 契约、Benchmark 口径或用户可见能力范围，只修复既有 `/workbench` 入口资源加载错误，因此 README 首页状态无需更新。

---

### 日期时间

2026-05-23 12:27 CST

### 本次目标

按用户要求将 VDS Workbench 从仪表盘式三栏卡片改为 GPT 类聊天界面：左侧历史 Chat，中间消息流，底部固定对话输入。

### 修改文件

- frontend/index.html
- frontend/styles.css
- frontend/app.js
- tests/backend/test_workbench_static_assets.py
- CHANGELOG_AI.md

### 修改内容

- 重构 workbench HTML 为聊天壳：左侧保留品牌、新分析入口和历史 Chat；主区域改为 assistant / user 消息流；底部 composer 承载问题输入、文件入口、执行模式、Agent 模式和发送按钮。
- 将数据画像、分析结果、图表、洞察、质量、Join / Verification、过程和 warnings/errors 放入 assistant 消息内的结构化块，不再使用旧的仪表盘 `work-grid` / `inspector` 首屏。
- 调整前端状态编排：上传成功后展示数据画像消息；发送问题时追加用户消息；后端结果返回后展示 assistant 结果消息并写入左侧历史 Chat。
- 保留既有 `/api/data-agent/upload`、`/api/data-agent/upload-batch`、`/api/data-agent/analyze` 调用，不在前端实现指标公式、join、排序、聚合或评分。
- 扩展静态测试，锁定 chat-first shell 并防止回退到旧 `work-grid` / `inspector` 布局。

### 测试方式

- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check frontend/app.js
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.backend.test_workbench_static_assets
- curl 验证 `GET /workbench` 返回 chat shell 和 `/frontend/*` 资源路径
- Browser smoke 真实访问 `http://127.0.0.1:8001/workbench`，检查 console、桌面截图、移动截图、旧布局节点不存在和空文件上传交互

### 测试结果

- `node --check frontend/app.js` 通过。
- workbench 静态测试通过：Ran 2 tests，OK。
- `/workbench` 返回 `200 text/html`，包含 `历史 Chat`、`chat-messages`、`composer-shell` 和 `/frontend/styles.css` / `/frontend/app.js`。
- Browser desktop smoke：console warning / error 为空；左侧为历史 Chat，中间为 VDS assistant 消息，底部为固定 composer；旧 `.work-grid`、`.inspector`、`.question-panel` 不存在。
- Browser mobile smoke：390px 视口无横向溢出，历史 Chat、消息区和 composer 均可见，console warning / error 为空。
- 上传按钮空文件交互正常显示 `请选择文件`，未产生 console error。

### 遗留问题

- Browser 插件当前未执行真实文件选择上传；文件上传和 analyze 能力仍由 API smoke / backend service smoke 覆盖。
- 本轮是 chat-first 信息架构重做，不涉及更复杂的多会话持久化、会话删除、会话重命名或历史恢复。

### 是否影响主流程

是。影响 `/workbench` 用户界面和前端状态展示方式，但不改变后端分析主流程。

### 是否涉及 Benchmark

否。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

否。仅改前端展示和本地状态编排。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

### 是否已同步 README

否。README 已描述 Phase 9 workbench 的上传、提问和展示能力；本轮只调整界面布局为 chat-first，不改变阶段状态、API 契约或能力范围。

---

### 日期时间

2026-05-23 02:45 CST

### 本次目标

按照 Phase 8/9 实施计划推进到 Phase 9 完成：先完成 Phase 8A-8E 核心算法闭环，再在 Phase 8 完整门禁通过后交付 Phase 9 前端 workbench，并把 MAIN_GOAL、README、API_CONTRACT、FEATURE_BACKLOG 同步为已完成状态。

### 修改文件

- MAIN_GOAL.md
- README.md
- docs/API_CONTRACT.md
- docs/FEATURE_BACKLOG.md
- CHANGELOG_AI.md
- backend/main.py
- backend/routers/data_agent.py
- backend/services/data_agent_service.py
- backend/storage/temp_file_store.py
- agent_runtime/data_agent_tool_impl.py
- agent_runtime/data_analysis_roles.py
- data_agent_core/agent/single_agent.py
- data_agent_core/contracts/analysis_contracts.py
- data_agent_core/contracts/dataset_contracts.py
- data_agent_core/core/analysis_planner.py
- data_agent_core/core/capability_registry.py
- data_agent_core/core/file_parser.py
- data_agent_core/core/intent_parser.py
- data_agent_core/core/logic_form.py
- data_agent_core/core/schema_profiler.py
- data_agent_core/executors/pandas_executor.py
- data_agent_core/tracing/run_trace.py
- data_agent_core/verifier/rule_checker.py
- multi_agent_workflows/end_to_end_data_analysis_workflow.py
- tests/backend/test_data_agent_service.py
- tests/core/test_phase8_multitable_capabilities.py
- frontend/index.html
- frontend/styles.css
- frontend/app.js
- frontend/README.md

### 修改内容

- Phase 8A：新增多文件 dataset 装配能力和 `POST /api/data-agent/upload-batch`；DatasetProfile / TableProfile 保留 `source_file`、`sheet`、`table_name`、字段画像和样例值；inline table payload 也支持 `source_file` / `sheet` metadata。
- Phase 8B：增强问题到表路由，按文件名、表名、字段名、语义别名和样例值打分；销售 / 库存多表问题不再静默选 `primary_table`。
- Phase 8C：扩展 `LogicForm` / `AnalysisPlan`，稳定携带 `source_tables`、`table_selection_reason`、`join_plan`；基于同名字段、归一化 ID 字段、唯一性和值重叠率推断一对一 / 多对一 join key。
- Phase 8D：Pandas executor 在可信 join plan 下先受控 materialize join，再执行聚合 / 排序 / 过滤；Verifier 阻断无可信 join key、多对多风险、多表未 join 和 ID fallback 伪成功；RunTrace / debug 记录 join 证据。
- Phase 8E：复跑 DABstep、微软脱敏数据和原本 VDS 三类非退步门禁；无真实 provider key 时只记录 mock / 离线结果，不冒充真实模型能力。
- Phase 9：新增 `frontend/` 静态 workbench，并在 `backend/main.py` 挂载 `/frontend` 和 `/workbench`；前端支持单/多文件上传、profile 预览、问题提交、结果展示、verification、warnings、errors、join trace 和 run history，不实现指标公式、join 或数据计算。
- 文档同步：MAIN_GOAL、README、API_CONTRACT、FEATURE_BACKLOG 均更新为 Phase 8/9 已完成状态，并记录后续真实 provider 回归限制。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall backend frontend data_agent_core agent_runtime multi_agent_workflows tests
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_phase8_multitable_capabilities tests.backend.test_data_agent_service tests.core.test_uploaded_table_agent tests.multi_agent_workflows.test_phase6_multi_agent_workflow
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- DABstep dev 1-10 mock：`outputs/phase8_dev_1_10_mock_20260523/dev_1_to_10_report.json`
- DABstep public all 1-450 mock：`outputs/phase8_dabstep_all_1_450_mock_20260523/all_1_to_450_report.json`
- Microsoft 脱敏数据 1-300 mock scorer：`outputs/phase8_microsoft_1_300_mock_20260523/report.json`
- 原本 VDS `问题汇总.xlsx` 95 题 smoke：`outputs/phase8_vds_question_summary_95_mock_20260523.json`
- Phase 9 browser smoke：mocked API route 桌面 / 移动视口，截图 `outputs/phase9_workbench_desktop_20260523.png`、`outputs/phase9_workbench_mobile_20260523.png`
- node --check frontend/app.js
- git diff --check

### 测试结果

- compileall 通过。
- Phase 8 focused / backend / baseline 子集通过：Ran 14 tests，OK。
- 全量 unittest 通过：Ran 135 tests，OK。
- DABstep dev 1-10：correct=9/10，success_count=10，unexpected_not_applicable=0，format_risk=0，submission_risk=0，trace_redaction_risk=0。
- DABstep public all 1-450 mock：success_count=450/450，unexpected_not_applicable=0，format_risk=0，submission_risk=0，trace_redaction_risk=0；public all answer 为空，不能本地计算 hidden official accuracy。
- Microsoft 脱敏数据 1-300 mock scorer：correct=300/300，success_count=300，format_risk=0，submission_risk=0，trace_redaction_risk=0。
- 原本 VDS `问题汇总.xlsx` 95 题 smoke：total=95，success_count=95，failure_count=0，output_contract_failure_count=0。
- Phase 9 browser smoke：console/page errors 为空；桌面和移动截图已生成。
- node --check frontend/app.js 通过。
- git diff --check 通过。

### 遗留问题

- 当前环境 `OPENAI_API_KEY=absent`、`DEEPSEEK_API_KEY=absent`，所以本轮没有真实 OpenAI / DeepSeek representative / staged 回归；后续有 key 时必须补跑，不能用 mock 冒充真实模型能力。
- Phase 9 首版 workbench 已能展示后端契约和 trace，但字段确认、join key 确认、低置信度澄清的交互还可继续产品化；这些后续增强仍不得在前端实现核心计算。
- DABstep dev 仍保留既有 `best_fraud_aci_choice` / ACI associated cost 通用语义口径后续项，不能按单题或固定答案特判。
- `.playwright-cli/` 是本地既有未跟踪目录，本轮未纳入变更。

### 是否影响主流程

是。Phase 8 修改核心上传表、多文件、多表 join、Verifier 和 trace 链路；Phase 9 新增前端 workbench。但旧单文件上传、inline table、single_agent fallback 和默认 multi_agent 基线均已回归。

### 是否涉及 Benchmark

是。复跑 DABstep dev、DABstep public all、Microsoft 脱敏数据和原本 VDS 95 smoke。标准答案、public proxy、accepted answer、hidden answer 和 task_id 仍只用于 response 之后的离线评分 / 风险观察，未进入 Planner、Executor、Verifier、Correction、prompt、trace 或测试 fixture。

### 是否涉及 Microsoft Agent Framework

否。未引入 Microsoft Agent Framework 依赖，未把核心算法写入 adapter。

### 是否影响未来多 Agent 迁移

是，正向影响。多文件 profile、表路由、join plan、join execution summary 和 verification 风险都通过稳定契约表达，可被当前 multi_agent workflow 和未来 framework adapter 复用。

### 是否修改核心数据契约

是。DatasetProfile / TableProfile 增加并使用 `source_file`、`sheet`、`table_name`；LogicForm / AnalysisPlan 增加 `source_tables`、`table_selection_reason`、`join_plan`。

### 是否修改 API 契约

是。新增 `POST /api/data-agent/upload-batch`，并在 API_CONTRACT 中记录多文件 profile、join plan、join execution summary 和 `/workbench` 边界。

### 是否新增或修改错误类型

是。未新增 error_type 常量，但修改了错误 / verification 语义：无可信 join key、多对多风险、多表未 join 和 ID fallback 必须通过 verification / correction_action / warnings / errors 体现，不能伪成功。

### 是否新增或修改运行追踪逻辑

是。RunTrace 增加 `source_tables`、`table_selection_reason`、`join_plan`、`join_execution_summary`；debug 同步暴露 trace-safe join 摘要。

### 是否已同步 README

是。README 已同步 Phase 8/9 完成状态、`upload-batch`、`/workbench`、非退步门禁、真实 provider 限制和前端不得实现核心计算的边界。

---

### 日期时间

2026-05-23 01:12 CST

### 本次目标

按用户要求把 Phase 8 / Phase 9 实施计划和“下一阶段 Goal 滚动更新机制”正式写入项目主目标：Phase 8 作为核心算法回看与多文件/多表泛化闭环的新阶段，Phase 9 作为 Phase 8 完成后的前端产品化阶段。

### 修改文件

- MAIN_GOAL.md
- README.md
- CHANGELOG_AI.md

### 修改内容

- MAIN_GOAL.md 新增 Phase 8 / Phase 9 到当前阶段目标和统一 Phase 状态表。
- MAIN_GOAL.md 新增 Phase 8 详细治理规则：进入新 Phase 或 8A-8E 子阶段前必须更新当前 Goal 并预写下一阶段 Goal，阶段结束后必须回看验收结果并更新后续 Goal。
- MAIN_GOAL.md 新增 Phase 8A-8E 实施顺序：多文件 dataset 装配、问题到表精准路由、多表关系与 join plan、Executor / Verifier / trace 闭环、DABstep / 微软脱敏数据 / 原本 VDS 三类基准完整回归。
- MAIN_GOAL.md 明确 Phase 8 硬门槛：模型能力和泛化能力不得低于当前 DABstep、微软脱敏数据和原本 VDS 基线；Phase 9 必须等待 Phase 8 退出后启动。
- README.md 同步 GitHub 首页摘要，补充 Phase 8 / Phase 9 定位和前端不得承载核心计算的边界。

### 测试方式

- git diff --check
- rg -n "Phase 8|Phase 9|8A|8B|8C|8D|8E|滚动 Goal" MAIN_GOAL.md README.md CHANGELOG_AI.md

### 测试结果

- git diff --check 通过。
- Phase 8 / Phase 9 / 8A-8E / 滚动 Goal 关键词均已在 MAIN_GOAL.md、README.md、CHANGELOG_AI.md 中可检索。

### 遗留问题

- 本轮只落地文档计划和治理规则，不实现 Phase 8 代码。
- Phase 8A 进入实现前仍需按本次规则再次更新 MAIN_GOAL.md 当前 Goal 和 Phase 8B 下一阶段 Goal。
- `.playwright-cli/` 仍是本地既有未跟踪目录，本轮未使用、未修改、未纳入变更。

### 是否影响主流程

否。本轮只修改文档和阶段治理规则，不修改 data_agent_core、backend、agent_runtime、multi_agent_workflows 或前端代码。

### 是否涉及 Benchmark

是，文档层面涉及。新增 Phase 8 非退步门禁明确要求 DABstep、微软脱敏数据和原本 VDS 三类回归不得退步；未修改 benchmark runner、scorer、prompt、测试 fixture 或核心分析链路。

### 是否涉及 Microsoft Agent Framework

否。未修改 ms_agent_framework_adapter，也未引入 Microsoft Agent Framework 依赖。

### 是否影响未来多 Agent 迁移

是，正向影响。Phase 8 将多文件、多表、join、Verifier 和 trace 作为核心算法契约完善目标，后续多 Agent 或框架适配必须复用这些稳定契约。

### 是否修改核心数据契约

否。本轮只写计划；`source_tables`、`table_selection_reason`、`join_plan` 等契约扩展留到 Phase 8 实现时再落地。

### 是否修改 API 契约

否。本轮只写计划；`upload-batch`、inline table metadata、selected_tables、join_summary 等 API 契约变化留到 Phase 8 实现时再同步 docs/API_CONTRACT.md。

### 是否新增或修改错误类型

否。本轮未新增错误类型。

### 是否新增或修改运行追踪逻辑

否。本轮未新增 trace 字段；Phase 8D 才会实现 join trace / table selection trace。

### 是否已同步 README

是。README 已同步 Phase 8 / Phase 9 摘要、非退步门禁和前端后置边界。

## 2026-05-22 - DeepSeek transport retry for offset benchmark runs

### 修改内容

- `data_agent_core/llm/client.py` 增加 OpenAI-compatible LLM transport retry：对 `IncompleteRead`、remote disconnect、timeout、URL 连接错误以及 408/409/425/429/5xx 做有限指数退避重试。
- 新增 `VDS_LLM_MAX_RETRIES`、`VDS_LLM_RETRY_BACKOFF_SECONDS` 运行参数，默认保持通用 provider 行为，不改变 Planner / Executor / Verifier 语义。
- 新增 `tests/core/test_llm_client.py`，覆盖 DeepSeek/OpenAI-compatible transient chunk 断流、429 retry 和 400 non-retry 边界。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_llm_client tests.core.test_generic_capability_operations tests.core.test_output_contract

### 测试结果

- focused tests 通过：Ran 55 tests，OK。
- 真实 DeepSeek 450 首次 10-way offset 并发因 provider/proxy HTTP chunked response `IncompleteRead` 在 LLM 阶段全部断流，未产生 trace；该问题属于 transport robustness，不是 DABstep logic/proxy correctness failure。

### 是否影响主流程

是。增强真实 LLM provider 的 benchmark 稳定性；不修改前端、不修改 benchmark answer policy、不引入 task_id/proxy answer/hidden answer 到核心链路。

### 是否涉及 Benchmark

是。用于真实 DeepSeek offset 分片 benchmark 的网络稳定性；public proxy 仍只用于 response 后验观察。

---

### 日期

2026-05-21

### 本次目标

继续推进核心算法 MVP，使项目可以进行核心算法测试，并能按 BM 要求将 payments.csv 作为业务数据库表、manual.md / fees.json / merchant_data.json 作为文档和规则知识库，运行 DABstep 前 10 题；要求 dev 前 10 题达到 80% 正确率，禁止按题目优化。

### 修改文件

- .gitignore
- README.md
- MAIN_GOAL.md
- BRANCH_RULES.md
- docs/ARCHITECTURE.md
- docs/API_CONTRACT.md
- docs/BENCHMARK_RULES.md
- docs/FEATURE_BACKLOG.md
- data_agent_core/contracts/dataset_contracts.py
- data_agent_core/contracts/analysis_contracts.py
- data_agent_core/contracts/execution_contracts.py
- data_agent_core/contracts/verification_contracts.py
- data_agent_core/contracts/response_contracts.py
- data_agent_core/errors/error_types.py
- data_agent_core/errors/error_result.py
- data_agent_core/tracing/run_trace.py
- data_agent_core/tracing/trace_writer.py
- data_agent_core/core/file_parser.py
- data_agent_core/core/schema_profiler.py
- data_agent_core/core/date_utils.py
- data_agent_core/core/dabstep_fee_engine.py
- data_agent_core/core/intent_parser.py
- data_agent_core/core/logic_form.py
- data_agent_core/core/analysis_planner.py
- data_agent_core/core/result_schema.py
- data_agent_core/executors/pandas_executor.py
- data_agent_core/executors/sql_executor.py
- data_agent_core/verifier/result_normalizer.py
- data_agent_core/verifier/result_comparator.py
- data_agent_core/verifier/rule_checker.py
- data_agent_core/output/response_builder.py
- data_agent_core/agent/single_agent.py
- data_agent_core/benchmark/evaluator.py
- data_agent_core/benchmark/benchmark_runner.py
- tests/core/test_dabstep_core.py

### 修改内容

- 将核心 contracts 从注释草案推进为轻量 dataclass。
- 将 errors 和 tracing 推进为可引用错误类型、结构化错误结果、RunTrace 和 trace.json 写入函数。
- 实现 DABstep 上下文加载，明确 payments.csv 是业务数据库表，manual.md / fees.json / merchant_data.json 是规则知识库。
- 实现通用 DABstep fee-rule engine，覆盖费用规则匹配、月度 volume/fraud、适用 fee IDs、总费用、费率变更 delta、MCC 变更 delta、card scheme steering、fraud ACI what-if 等通用能力。
- 实现通用 intent parser，不使用 task_id、标准答案或单题硬编码。
- 实现 Pandas 执行路径和 sqlite SQL fallback，用于 SQL-compatible 聚合类任务。
- 实现结果标准化、执行结果比较、基础 verifier 和 FinalResponse 构建。
- 实现 benchmark runner 和 evaluator；runner 只在评分阶段读取 answer 字段，核心分析链路只接收 question、guidelines 和上下文数据。
- 新增 unittest 核心测试，固定 DABstep dev 前 10 题准确率不低于 80%。
- 更新工程文档、README 和 backlog，记录当前核心算法 MVP 与 BM 运行命令。

### 测试方式

- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_dabstep_core
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --output-dir outputs/dabstep_core_mvp
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 10 --output-dir outputs/dabstep_core_mvp
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core tests/core tests/architecture
- rg -n "^\\s*(from|import)\\s+(backend|ms_agent_framework_adapter|multi_agent_workflows|agent_framework)" data_agent_core

### 测试结果

- unittest 通过：Ran 2 tests in 2.063s，OK。
- DABstep dev 前 10 题通过本地评分：total=10，scored=10，correct=8，accuracy=0.8。
- DABstep all 前 10 题已生成预测文件：outputs/dabstep_core_mvp/all_first10_predictions.jsonl。本地 all.jsonl 的 answer 字段为空，因此 scored=0，accuracy=null。
- compileall 通过。
- data_agent_core 禁止 import 边界检查未发现实际 import 匹配。

### 遗留问题

- 当前仅覆盖核心算法 MVP 和 DABstep 前 10 题通用问题形态，尚未覆盖完整 450 题。
- 本机系统 Python 缺少 pandas / numpy / duckdb / pytest；本轮使用 Codex bundled Python 运行测试。DuckDB 未安装，因此 SQL 路径当前使用 sqlite fallback。
- 远端 dev 分支仍不存在，首次 commit / push 后需要补齐 dev 和 feature 分支流程。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端或复杂后端业务。

### 是否涉及 Benchmark

是。新增 DABstep runner 和 evaluator，用于 dev/all 前 10 题本地运行。标准答案只在 evaluator 评分阶段使用，不进入核心分析链路。

### 是否涉及 Microsoft Agent Framework

否。未安装、未 import、未实现 Microsoft Agent Framework workflow。

### 是否影响未来多 Agent 迁移

是，正向影响。核心算法保持在 data_agent_core 中，仍与 agent framework 解耦，后续可由 agent_runtime 或 adapter 编排。

### 是否修改核心数据契约

是。contracts 草案被推进为轻量 dataclass，包括 DatasetProfile、LogicForm、AnalysisPlan、ExecutionResult、VerificationResult 和 FinalResponse 等。

### 是否修改 API 契约

是。FinalResponse 增加 answer 字段，docs/API_CONTRACT.md 已同步记录。

### 是否新增或修改错误类型

是。error_types.py 改为可引用常量，error_result.py 增加结构化 ErrorResult。

### 是否新增或修改运行追踪逻辑

是。新增 RunTrace dataclass 和 trace_writer.write_trace，runner 会写入 trace.json；trace 只包含可审计执行摘要，不包含完整 Chain of Thought。

---

### 日期

2026-05-21

### 本次目标

初始化项目规则文件、Data Agent 核心目录骨架、最小后端 API 骨架、内部 Agent 抽象层骨架、Microsoft Agent Framework 适配层骨架、多 Agent workflow 预留目录、数据契约骨架、错误体系骨架、运行追踪骨架、文档骨架和架构边界测试骨架。

### 修改文件

- MAIN_GOAL.md
- CHANGELOG_AI.md
- BRANCH_RULES.md
- README.md
- docs/ARCHITECTURE.md
- docs/API_CONTRACT.md
- docs/DATASET_LIFECYCLE.md
- docs/BENCHMARK_RULES.md
- docs/SECURITY_BOUNDARIES.md
- docs/FEATURE_BACKLOG.md
- data_agent_core/README.md
- data_agent_core/configs/tool_whitelist.yaml
- data_agent_core/configs/benchmark_config.yaml
- data_agent_core/configs/model_config.yaml
- data_agent_core/contracts/*.py
- data_agent_core/errors/*.py
- data_agent_core/tracing/*.py
- data_agent_core/core/*.py
- data_agent_core/executors/*.py
- data_agent_core/verifier/*.py
- data_agent_core/output/*.py
- data_agent_core/agent/*.py
- data_agent_core/benchmark/*.py
- backend/**/*.py
- agent_runtime/*.py
- ms_agent_framework_adapter/*.py
- multi_agent_workflows/*.py
- tests/architecture/test_dependency_boundaries.py
- tests/*/.gitkeep

### 修改内容

- 创建项目主目标、AI 修改记录和分支规则文档。
- 创建 docs 工程文档骨架，覆盖架构、API 契约、数据集生命周期、Benchmark 规则、安全边界和功能 backlog。
- 创建 data_agent_core 目录和核心模块边界，只包含 docstring、TODO 和契约草案。
- 创建 contracts、errors、tracing 草案，预留稳定数据契约、错误类型和运行追踪字段。
- 创建 backend 最小 API 调用壳骨架，不包含核心分析逻辑。
- 创建 agent_runtime 内部 Agent 抽象层骨架。
- 创建 ms_agent_framework_adapter 适配层骨架，不安装、不依赖、不实现 Microsoft Agent Framework workflow。
- 创建 multi_agent_workflows 多 Agent 编排预留骨架。
- 创建 tests/architecture 架构边界测试骨架和空测试目录占位。

### 测试方式

- python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests/architecture
- python3 -m pytest tests/architecture
- rg -n "^\\s*(from|import)\\s+(backend|ms_agent_framework_adapter|multi_agent_workflows|agent_framework)" data_agent_core

### 测试结果

- compileall 通过，所有 Python 骨架文件语法有效。
- pytest 未执行成功，本机 python3 环境未安装 pytest：No module named pytest。
- data_agent_core 禁止 import 边界检查未发现实际 import 匹配。

### 遗留问题

- 远端仓库当前没有任何分支；本地已配置 origin 并创建 feature/project-rules-and-data-agent-skeleton，后续需要在首次 commit 后再推送 dev / feature 分支。
- 当前只完成 Phase 0 骨架，不包含真实文件解析、执行、校验、后端接口业务逻辑或 Benchmark 评测逻辑。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程。

### 是否涉及 Benchmark

仅新增 Benchmark 规则文档和骨架文件，未读取、修改或依赖 Benchmark 数据。

### 是否涉及 Microsoft Agent Framework

仅新增适配层骨架和说明文档，未安装依赖，未实现 workflow，核心算法不依赖 Microsoft Agent Framework。

### 是否影响未来多 Agent 迁移

是，正向预留 agent_runtime、ms_agent_framework_adapter 和 multi_agent_workflows 边界；未启用复杂多 Agent。

### 是否修改核心数据契约

是，新增 contracts 草案文件，用于后续稳定交互契约。

### 是否修改 API 契约

是，新增 docs/API_CONTRACT.md 和 backend schema 骨架。

### 是否新增或修改错误类型

是，新增 data_agent_core/errors/error_types.py 错误类型草案。

### 是否新增或修改运行追踪逻辑

是，新增 run_trace.py 和 trace_writer.py 的运行追踪草案；未实现真实写入逻辑。

---

### 日期

2026-05-21

### 本次目标

按项目主目标把单 Agent 核心链路明确调整为 LLM + 规则 + 代码分工：LLM Intent Parser、LLM + 规则 Column Mapping、LLM Analysis Planner、代码 Pandas / SQL 执行、代码 Result Normalizer、规则 + LLM Verifier / Critic、规则 + LLM Correction Planner、LLM Insight Generator、LLM + 规则 Chart Planner，最后返回 JSON；同时把该链路映射到未来多 Agent 角色。

### 修改文件

- MAIN_GOAL.md
- docs/ARCHITECTURE.md
- docs/API_CONTRACT.md
- docs/FEATURE_BACKLOG.md
- data_agent_core/README.md
- data_agent_core/prompts/data_agent_system_prompt.md
- data_agent_core/llm/client.py
- data_agent_core/llm/planner.py
- data_agent_core/agent/single_agent.py
- data_agent_core/core/analysis_planner.py
- data_agent_core/tracing/run_trace.py
- agent_runtime/README.md
- ms_agent_framework_adapter/README.md
- multi_agent_workflows/README.md
- tests/core/test_dabstep_core.py
- CHANGELOG_AI.md

### 修改内容

- 将 MAIN_GOAL.md 的核心工作流改为用户指定的 LLM / 规则 / 代码链路。
- 更新 README，说明 prompt 路径、单 Agent 链路和 mock / 真实 LLM 的运行方式。
- 在架构文档中补充单 Agent 每个阶段的职责分工，以及未来多 Agent 的角色映射。
- 更新 API 契约，说明 debug 可包含 single_agent_chain、llm_stage_summaries、column_mapping，但前端不能依赖 debug 作为稳定展示契约。
- 更新 prompt，明确 LLM 只服务当前 stage，不输出完整 Chain of Thought，不使用 Benchmark task_id 或标准答案。
- 增加通用 LLM stage helper，用于 intent_parser、column_mapping、verifier_critic、correction_planner、insight_generator、chart_planner 等阶段。
- 更新单 Agent 编排，使 trace/debug 中可看到完整单 Agent 链路和各 LLM 阶段摘要。
- 扩展 RunTrace 字段，记录 intent、column mapping、analysis planner、result normalizer、verifier critic、correction planner、insight、chart plan 等摘要。
- 更新 agent_runtime、ms_agent_framework_adapter、multi_agent_workflows README，使未来多 Agent 角色与当前主目标一致。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_dabstep_core
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --output-dir outputs/dabstep_core_mvp_llm_chain
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- rg -n "^\\s*(from|import)\\s+(backend|ms_agent_framework_adapter|multi_agent_workflows|agent_framework)" data_agent_core
- rg secret-pattern scan against repository files excluding outputs/

### 测试结果

- unittest 通过：Ran 2 tests in 1.825s，OK。
- DABstep dev 前 10 题通过本地评分：total=10，scored=10，correct=8，accuracy=0.8。
- compileall 通过。
- data_agent_core 禁止 import 边界检查未发现实际 import 匹配。
- secret 扫描未发现提供过的 key 或 key 片段进入仓库文件。

### 遗留问题

- 当前 LLM stage 已接入链路和 trace，但真实 DeepSeek / OpenAI 运行需要用户在本地 shell 通过环境变量提供 key。
- 当前 dev 前 10 题达到 80%，尚未验证完整 450 题。
- 远端 dev 分支仍不存在，后续需要补齐 dev 和 feature 分支推送流程。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端或复杂后端业务。

### 是否涉及 Benchmark

是。继续使用 DABstep dev 前 10 题验证核心算法正确率；标准答案只在 evaluator 评分阶段使用，不进入核心分析链路或 LLM 输入。

### 是否涉及 Microsoft Agent Framework

仅更新适配层 README 的未来映射说明；未安装、未 import、未实现 Microsoft Agent Framework workflow。

### 是否影响未来多 Agent 迁移

是，正向影响。当前单 Agent 阶段已和未来 Planner、Data Engineer、Executor、Verifier、Correction、Insight、Visualization、Benchmark Agent 的职责对齐。

### 是否修改核心数据契约

是。扩展 RunTrace 运行追踪契约；未破坏 FinalResponse 稳定字段。

### 是否修改 API 契约

是。docs/API_CONTRACT.md 补充 debug 中的 LLM 阶段摘要字段，并继续声明前端不能依赖 debug。

### 是否新增或修改错误类型

否。本轮未新增错误类型。

### 是否新增或修改运行追踪逻辑

是。新增单 Agent 各阶段 trace 摘要，仍只记录 structured analysis plan、reasoning summary、execution trace、verification notes，不记录完整 Chain of Thought。

---

### 日期时间

2026-05-21 11:30 CST

### 本次目标

修改 AI CHANGELOG 记录规则，要求未来每次修改记录的时间精确到分钟，避免只写日期导致记录粒度过粗。

### 修改文件

- CHANGELOG_AI.md
- MAIN_GOAL.md
- BRANCH_RULES.md

### 修改内容

- 将 CHANGELOG_AI.md 的必填项从“日期”调整为“日期时间”。
- 新增日期时间格式规则：`YYYY-MM-DD HH:MM TZ`，精确到分钟。
- 明确未来新增记录禁止只写日期。
- 明确历史记录不允许为了补齐格式而编造分钟级时间。
- 在 MAIN_GOAL.md 和 BRANCH_RULES.md 中同步记录 changelog 时间粒度规则。

### 测试方式

- sed -n 读取 MAIN_GOAL.md、CHANGELOG_AI.md、BRANCH_RULES.md

### 测试结果

- 已完成规则文件读取。
- 本轮为文档规则修改，无代码测试。

### 遗留问题

- 历史 CHANGELOG 记录仍保留原始日期格式，未补造分钟级时间。

### 是否影响主流程

否。仅修改项目规则文档。

### 是否涉及 Benchmark

否。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

否。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

---

### 日期时间

2026-05-22 13:04 CST

### 本次目标

实现 Phase 7.2G：Uploaded Table Generalization Gap Closure，把原始五域新增 100 从基线 `58/100` 提升到验收线以上，同时确认 Microsoft 新增 100 不退化；修复必须按上传表通用能力族推进，不按 task_id、标准答案、固定字段值、固定问法或当前错误样本特调。

### 修改文件

- MAIN_GOAL.md
- CHANGELOG_AI.md
- data_agent_core/core/intent_parser.py
- data_agent_core/core/analysis_planner.py
- data_agent_core/core/dabstep_fee_engine.py
- data_agent_core/executors/pandas_executor.py
- data_agent_core/verifier/rule_checker.py
- multi_agent_workflows/uploaded_table_benchmark_runner.py
- tests/architecture/test_no_benchmark_hardcoding.py
- tests/benchmark/test_uploaded_table_benchmark_runner.py
- tests/core/test_semantic_metric_verification.py

### 修改内容

- 新增通用 uploaded-table benchmark runner：按 JSONL 中的 source_file / sheet 或 CSV root 构造 uploaded-table workflow，输出 overall、easy、hard、capability_area、failure_buckets、risk_taxonomy 和 provenance。
- runner 只把 question / guidelines 传入 workflow；标准答案只在 response 生成后用于离线 scorer，并新增结构化 raw value 等价评分，避免表格/list 类正确结果被安全 final-answer 字符串格式误判。
- 修复上传表 top_count 使用 `_analysis_dataframe`，不再假设 DABstep `payments` 表。
- 修复上传表字段角色绑定：显式 filter 优先于 dimension；`区域为华北` 绑定为 filter，group-by 通过 `按...统计/分组/汇总` 解析。
- 修复 record count / metric 聚合语义：`记录数/条数/笔数/次数` 绑定 count，`销售额总和` 保持 sum，`平均值` 保持 mean。
- 修复中文输出契约：支持 `保留2位小数` 解析到 decimals，避免 `0.46964` 这类 raw float 直接进入最终答案。
- 收紧隐式 filter：只有明确过滤语境才把中文值绑定为 filter，避免把数据集名称里的领域词或单字值误绑定为过滤条件。
- 修复 repeat_entity_percentage 的 denominator planner contract 为 unique entity，避免 Verifier 误判分母。
- 修复 Verifier 对 VDS 周期对比 count/share 的误判：`vds_period_growth_count_share` 是先比较业务 metric，再输出实体数量和占比，不应被强制要求 metric_definition=count。
- 优化 DABstep fee-rule engine：按 card scheme 预分组 fee rules，并缓存 merchant-period payments、monthly stats 和 merchant/month candidate rules，避免 `card_scheme_steering` 大商户全量扫描超时。
- 在 `MAIN_GOAL.md` 的 Phase 7.2G 下补充当前闭环结果、报告路径和唯一剩余标准答案口径待复核项。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.uploaded_table_benchmark_runner --dataset-root /Users/trevorcui/Desktop/Virtual\ Data\ Scientist测试数据 --test-set /Users/trevorcui/Desktop/Virtual\ Data\ Scientist测试数据/VDS_DAB风格新增泛化100_20260522/原始数据集_DAB风格新增泛化100_问题和标准答案.jsonl --limit 100 --offset 0 --output-dir outputs/phase72g_original_new100_uploaded_runner_final_20260522 --dataset-id vds_original_generalized_new100
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.uploaded_table_benchmark_runner --dataset-root /Users/trevorcui/Desktop/微软脱敏数据 --test-set /Users/trevorcui/Desktop/微软脱敏数据/VDS_DAB风格新增泛化100_20260522/微软数据集_DAB风格新增泛化100_问题和标准答案.jsonl --limit 100 --offset 0 --output-dir outputs/phase72g_microsoft_new100_uploaded_runner_final_20260522 --dataset-id microsoft_anonymized_generalized_new100
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/phase72g_dabstep_dev_1_10_final_20260522
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 450 --offset 0 --output-dir outputs/phase72g_dabstep_all_1_450_final2_20260522
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.microsoft_anonymized_benchmark_runner --dataset-root /Users/trevorcui/Desktop/微软脱敏数据 --limit 300 --offset 0 --output-dir outputs/phase72g_microsoft_1_300_20260522
- VDS_LLM_PROVIDER=mock inline runner for `/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/问题/问题汇总.xlsx`, output `outputs/phase72g_vds_question_summary_95_20260522.json`
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.benchmark.test_uploaded_table_benchmark_runner tests.architecture.test_no_benchmark_hardcoding tests.core.test_generic_capability_operations tests.core.test_semantic_metric_verification tests.benchmark.test_benchmark_metrics
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime multi_agent_workflows tests
- rg hardcoding boundary scan over data_agent_core / agent_runtime / multi_agent_workflows / backend / ms_agent_framework_adapter / tests

### 测试结果

- 原始五域新增 100：total=100，correct=99，accuracy=0.99，easy `40/40`，hard `59/60`；报告路径 `outputs/phase72g_original_new100_uploaded_runner_final_20260522/report.json`。
- Microsoft 新增 100：total=100，correct=100，accuracy=1.0，easy `40/40`，hard `60/60`；报告路径 `outputs/phase72g_microsoft_new100_uploaded_runner_final_20260522/report.json`。
- DABstep dev 1-10 mock：total=10，correct=9，accuracy=0.9，success_count=10；报告路径 `outputs/phase72g_dabstep_dev_1_10_final_20260522/dev_1_to_10_report.json`。
- DABstep public all 1-450 mock：total=450，success_count=450，unexpected_not_applicable=0，true_unsupported=3，accuracy=null；public all answer 为空，不能本地计算 official accuracy；报告路径 `outputs/phase72g_dabstep_all_1_450_final2_20260522/all_1_to_450_report.json`。
- Microsoft 1-300 mock 离线 scorer：total=300，correct=300，accuracy=1.0，success_count=232；报告路径 `outputs/phase72g_microsoft_1_300_20260522/report.json`。
- 桌面 VDS `问题汇总.xlsx` 五个真实问题 sheet 共 95 题 mock smoke：total=95，success_count=95，failure_count=0；报告路径 `outputs/phase72g_vds_question_summary_95_20260522.json`。
- Targeted unittest 通过：Ran 55 tests，OK。
- Full unittest 通过：Ran 117 tests，OK。
- compileall 通过。
- hardcoding boundary scan 仅命中允许的 benchmark runner / provenance / metrics / guardrail test 文本；核心链路未新增 task_id、标准答案、hidden answer、proxy answer 或 public proxy 输入。

### 遗留问题

- 原始五域唯一剩余失败为 `ORG_H010`：源表重算 top3 filtered metric share 为 `45.63692666600649%`，agent answer 为 `45.64%`，标准答案为 `45.70%`。该项按标准答案生成口径待复核处理，不能做单题补丁。
- 仍有部分表格/列表类问题的 `success_count` 低于 scorer correct，因为 FinalResponse success 还受 Verifier / output contract 组合判断影响；本轮验收以离线 scorer correctness 为准，后续可在 Phase 7.3 output contract hardening 中继续收敛。
- DABstep public all 本地 answer 为空，`accuracy=null` 是数据集限制；该回归只验证 mock 执行覆盖、Not Applicable 归因、trace 和输出风险。

### 是否影响主流程

是，影响上传表 intent parser、planner contract、Pandas executor、Verifier、DABstep fee-rule engine 和 benchmark runner；不修改前端、不改变后端稳定 API、不引入新外部依赖。

### 是否涉及 Benchmark

是。新增通用 uploaded-table 离线 runner 和结构化 scorer，但标准答案仅用于 response 之后的 scorer；未把 task_id、标准答案、proxy answer、accepted answer 或 hidden answer 写入 Agent workflow、prompt、Planner、Executor、Verifier、Correction、测试 fixture 或核心逻辑。

### 是否涉及 Microsoft Agent Framework

否。未安装 Microsoft Agent Framework，未新增 adapter 依赖，未把核心算法写入 adapter。

### 是否影响未来多 Agent 迁移

是，正向影响。7.2G 把通用上传表能力收敛到字段角色绑定、聚合口径、输出契约和 runner provenance，后续多 Agent / provider / DuckDB 路径可以复用同一上传表语义契约。

### 是否修改核心数据契约

是，扩展 benchmark report metadata 和 uploaded-table runner 输出字段；不修改后端 API request / response 稳定字段。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

---

### 日期时间

2026-05-21 11:41 CST

### 本次目标

按用户要求补齐 dev 分支、把 LLM key 写入本地 ignored env 文件以便服务器运行、对照 DABstep 官方 scorer 地址，并单独检查 all.jsonl 第 11 到 20 题。

### 修改文件

- BRANCH_RULES.md
- docs/BENCHMARK_RULES.md
- data_agent_core/benchmark/benchmark_runner.py
- data_agent_core/agent/single_agent.py
- data_agent_core/core/intent_parser.py
- data_agent_core/output/response_builder.py
- tests/core/test_dabstep_core.py
- CHANGELOG_AI.md

### 修改内容

- 从 origin/main 创建 origin/dev，并创建本地 tracking 分支 dev。
- 创建本地 .env.local 保存 DeepSeek / OpenAI 运行配置；该文件被 .gitignore 的 .env.* 规则忽略，不进入 Git。
- 对照 DABstep 官方 scorer 地址记录 benchmark scorer 来源。
- benchmark runner 新增 offset 参数，用于运行 all.jsonl 的指定区间，例如第 11 到 20 题。
- 修复 LLM LogicForm guardrail：LLM 不再覆盖确定性 output_format，只能补充缺失字段。
- 修复 response formatter 在执行值为 None 时的失败，统一返回 Not Applicable。
- 增加 grouped by aci 等通用 group_by 解析，避免固定写成 shopper_interaction。
- 增加测试覆盖 all split offset=10 对应第 11 到 20 题。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_dabstep_core
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/dabstep_core_mvp_dev_after_offset_fix
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 10 --offset 10 --output-dir outputs/dabstep_core_mvp_mock_11_20
- source .env.local 后运行 /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 10 --offset 10 --output-dir outputs/dabstep_core_mvp_llm_real_11_20_after_fix
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- rg -n "^\\s*(from|import)\\s+(backend|ms_agent_framework_adapter|multi_agent_workflows|agent_framework)" data_agent_core
- rg secret-pattern scan against repository files excluding outputs/

### 测试结果

- unittest 通过：Ran 3 tests in 8.048s，OK。
- DABstep dev 前 10 题仍为 8/10，accuracy=0.8。
- DABstep all 第 11 到 20 题可生成真实 LLM 预测，但 public all.jsonl 的 answer 字段为空，因此 scored=0，accuracy=null。
- all 第 11 到 20 题真实 LLM 输出文件：outputs/dabstep_core_mvp_llm_real_11_20_after_fix/all_11_to_20_predictions.jsonl。
- compileall 通过。
- data_agent_core 禁止 import 边界检查未发现实际 import 匹配。
- secret 扫描未发现提供过的 key 或 key 片段进入仓库文件；.env.local 为 ignored 文件。

### 遗留问题

- all.jsonl 第 11 到 20 题没有本地标准答案，不能计算真实准确率。
- 第 15 题当前返回 Not Applicable 且 success=false，需要后续做通用 best_fraud_aci_choice 能力分析，不能按单题特判。
- 第 20 题当前为 not_applicable，需要后续补充通用 cheapest-card-scheme average scenario 能力，不能按单题特判。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端或复杂后端业务。

### 是否涉及 Benchmark

是。新增 offset 支持并检查 DABstep all 第 11 到 20 题；未把 task_id 或 answer 传入核心分析链路或 LLM。

### 是否涉及 Microsoft Agent Framework

否。未安装、未 import、未实现 Microsoft Agent Framework workflow。

### 是否影响未来多 Agent 迁移

是，正向影响。LLM 输出被 guardrail 限制，便于未来 Planner Agent 和 Data Engineer Agent 分工。

### 是否修改核心数据契约

否。本轮未新增核心 contract 字段。

### 是否修改 API 契约

否。本轮未修改 API 稳定字段。

### 是否新增或修改错误类型

否。本轮未新增错误类型。

### 是否新增或修改运行追踪逻辑

否。本轮未新增 trace 字段，但第 11 到 20 题生成了新的 trace 输出。

---

### 日期时间

2026-05-21 11:59 CST

### 本次目标

按 Phase 计划继续推进到 Phase 4 前置状态：建立 Phase gate、补内部 Agent runtime 契约、补 Microsoft Agent Framework 适配层声明式映射、补多 Agent workflow 任务序列，并通过防 Benchmark 硬编码测试保证后续只提升泛化能力，不按题目优化。

### 修改文件

- docs/PHASE_GATES.md
- docs/FEATURE_BACKLOG.md
- agent_runtime/agent_role.py
- agent_runtime/agent_task.py
- agent_runtime/agent_result.py
- agent_runtime/workflow_state.py
- agent_runtime/runtime_interfaces.py
- agent_runtime/tool_registry.py
- data_agent_core/contracts/agent_contracts.py
- data_agent_core/core/dabstep_fee_engine.py
- data_agent_core/core/intent_parser.py
- data_agent_core/executors/pandas_executor.py
- data_agent_core/llm/planner.py
- data_agent_core/output/response_builder.py
- ms_agent_framework_adapter/adapter.py
- ms_agent_framework_adapter/agent_mapping.py
- ms_agent_framework_adapter/workflow_mapping.py
- ms_agent_framework_adapter/tool_mapping.py
- ms_agent_framework_adapter/state_mapping.py
- multi_agent_workflows/end_to_end_data_analysis_workflow.py
- multi_agent_workflows/planner_workflow.py
- multi_agent_workflows/dual_executor_workflow.py
- multi_agent_workflows/verification_workflow.py
- tests/architecture/test_dependency_boundaries.py
- tests/architecture/test_no_benchmark_hardcoding.py
- tests/agent_runtime/test_runtime_contracts.py
- tests/__init__.py
- tests/core/__init__.py
- tests/architecture/__init__.py
- tests/agent_runtime/__init__.py
- CHANGELOG_AI.md

### 修改内容

- 新增 docs/PHASE_GATES.md，明确 Phase 1 到 Phase 5+ 的进入/退出条件和禁止按 Benchmark 题目优化的红线。
- 将 agent_runtime 从 docstring 草案推进为轻量 dataclass / Enum / Protocol 契约。
- 将 Microsoft Agent Framework adapter 继续保持无框架依赖，只提供声明式 role / workflow / tool / state mapping。
- 将 multi_agent_workflows 推进为 framework-neutral AgentTask 序列构建器，不承载核心算法。
- 新增架构测试，检查 data_agent_core 不能 import 外层 adapter / workflow / backend，adapter 当前不能 import Microsoft 框架。
- 新增防 Benchmark 硬编码测试，检查核心分析模块不引用 Benchmark 泄漏字段，并验证 runner 只把 question / guidelines / execution_mode 传给 agent。
- 新增 agent_runtime 契约测试和 unittest discover 支持。
- 补通用分析能力：fraud_rate_comparison、year-level best_fraud_aci_choice、cheapest_card_scheme_for_transaction、card_scheme 输出格式。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/dabstep_phase_gate_dev_1_10
- source .env.local 后运行 /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/dabstep_phase_gate_real_dev_1_10
- source .env.local 后运行 /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 10 --offset 10 --output-dir outputs/dabstep_phase_gate_real_11_20
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- rg -n "^\\s*(from|import)\\s+(backend|ms_agent_framework_adapter|multi_agent_workflows|agent_framework)" data_agent_core
- rg secret-pattern scan against repository files excluding outputs/

### 测试结果

- unittest discover 通过：Ran 11 tests in 8.738s，OK。
- DABstep dev 1-10 mock：8/10，accuracy=0.8。
- DABstep dev 1-10 真实 LLM：8/10，accuracy=0.8。
- DABstep all 11-20 真实 LLM：可生成 10 条预测，public all.jsonl 无 answer，因此 accuracy=null。
- DABstep all 11-20 真实 LLM 的 10 条预测均 success=True。
- compileall 通过。
- data_agent_core 禁止 import 边界检查未发现实际 import 匹配。
- secret 扫描未发现提供过的 key 或 key 片段进入仓库文件；.env.local 仍为 ignored 文件。

### 遗留问题

- all.jsonl 没有本地标准答案，无法本地计算 11-20 的真实准确率。
- Microsoft Agent Framework 仍未安装、未接入真实 workflow；当前只是 Phase 4 前置 adapter plan。
- 后续进入 Phase 4 时仍必须保证 data_agent_core 不依赖 Microsoft Agent Framework。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端或复杂后端业务。

### 是否涉及 Benchmark

是。使用 DABstep 进行分段验证，但新增了防硬编码测试，且标准答案只在 evaluator 评分阶段使用，不进入核心分析链路或 LLM。

### 是否涉及 Microsoft Agent Framework

是，但仅限适配层声明式映射和 Phase gate 文档；未安装、未 import、未实现真实 Microsoft Agent Framework workflow。

### 是否影响未来多 Agent 迁移

是，正向影响。新增 agent_runtime 契约、adapter mapping 和 multi_agent workflow task builders，为 Phase 4+ 多 Agent 编排做准备。

### 是否修改核心数据契约

是。agent_contracts.py 说明更新为与 agent_runtime 契约对齐；未修改 FinalResponse 稳定 API 字段。

### 是否修改 API 契约

否。本轮未修改 API 稳定字段。

### 是否新增或修改错误类型

否。本轮未新增错误类型。

### 是否新增或修改运行追踪逻辑

否。本轮未新增 trace 字段。

---

### 日期时间

2026-05-21 13:23 CST

### 本次目标

按用户要求调整 MAIN_GOAL 和路线图，把 Tool Calling 明确放到 Phase 5 后置阶段，避免在当前 Phase 1/2/3 或 Phase 4 adapter 阶段过早启用模型原生工具循环。

### 修改文件

- MAIN_GOAL.md
- docs/PHASE_GATES.md
- docs/FEATURE_BACKLOG.md
- CHANGELOG_AI.md

### 修改内容

- MAIN_GOAL 增加 Phase 5 受控 Tool Calling 目标、架构原则、当前不做事项和工具调用阶段说明。
- PHASE_GATES 新增 Phase 5：受控 Tool Calling 层，并将原多 Agent Workflow 后移为 Phase 6+。
- PHASE_GATES 增加工具调用总红线：禁止任意代码、任意 SQL、shell、网络请求或外部文件访问。
- FEATURE_BACKLOG 新增 Controlled Tool Calling Layer，记录工具形式、影响模块、验收标准、风险和当前未实现状态。
- 明确 OpenAI / DeepSeek / Microsoft Agent Framework 只作为 provider / framework 适配层，内部工具契约保持 provider-neutral。

### 测试方式

- 未运行自动化测试；本轮仅修改项目目标和路线图文档。

### 测试结果

- 不适用，文档-only 修改。

### 遗留问题

- Phase 5 Tool Calling 仍未实现；后续需要补 ToolDefinition schema、tool dispatcher、provider adapter、mock tool-calling 测试和 trace 摘要字段。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改执行代码。

### 是否涉及 Benchmark

否。未修改 Benchmark runner、evaluator 或测试数据。

### 是否涉及 Microsoft Agent Framework

仅文档层面说明 Microsoft Agent Framework 不能承载核心工具实现；未安装、未 import、未实现 framework workflow。

### 是否影响未来多 Agent 迁移

是，正向影响。路线图调整为 Phase 5 先建立 provider-neutral 工具层，Phase 6+ 再做多 Agent workflow。

### 是否修改核心数据契约

否。本轮未修改 contracts dataclass。

### 是否修改 API 契约

否。本轮未修改 API 稳定字段。

### 是否新增或修改错误类型

否。本轮未新增错误类型。

### 是否新增或修改运行追踪逻辑

否。本轮只规定未来工具调用 trace 摘要原则，未修改 trace 代码。

---

### 日期时间

2026-05-21 13:24 CST

### 本次目标

按 Phase 1 / Phase 2 / Phase 3 继续推进到最小可测完成状态：上传文件核心算法测试可运行，最小后端调用壳可用，单 Agent 链路可用真实 LLM 跑 DABstep dev 前 10 题并保持 80% 正确率，Benchmark 报告支持通用 metrics 和 error_analysis 聚合。

### 修改文件

- .gitignore
- MAIN_GOAL.md
- BRANCH_RULES.md
- docs/API_CONTRACT.md
- docs/ARCHITECTURE.md
- docs/BENCHMARK_RULES.md
- docs/FEATURE_BACKLOG.md
- docs/PHASE_GATES.md
- backend/main.py
- backend/routers/data_agent.py
- backend/schemas/data_agent_schema.py
- backend/services/data_agent_service.py
- backend/storage/temp_file_store.py
- data_agent_core/agent/single_agent.py
- data_agent_core/benchmark/benchmark_runner.py
- data_agent_core/benchmark/error_analysis.py
- data_agent_core/benchmark/metrics.py
- data_agent_core/core/file_parser.py
- data_agent_core/core/intent_parser.py
- data_agent_core/core/schema_profiler.py
- data_agent_core/executors/pandas_executor.py
- data_agent_core/executors/sql_executor.py
- data_agent_core/llm/planner.py
- tests/architecture/test_dependency_boundaries.py
- tests/backend/__init__.py
- tests/backend/test_data_agent_service.py
- tests/benchmark/__init__.py
- tests/benchmark/test_benchmark_metrics.py
- tests/core/test_uploaded_table_agent.py

### 修改内容

- 新增 ParsedDataset 和 parse_dataset_file，支持 CSV / Excel 解析入口、DatasetProfile 生成、多 sheet warning、空表 warning 和不确定表头 warning。
- 增强 Schema Profiler 的日期、金额/销售、城市/位置语义 hint，避免普通文本列触发日期解析 warning。
- 新增 UploadedDatasetAgent，复用固定 LLM 单 Agent 链路分析用户上传单表数据。
- 新增通用上传表 LogicForm guardrail，支持 detail_lookup、filtering、aggregation、ranking 的最小解析。
- 扩展 Pandas Executor 和 SQL fallback Executor，使上传单表的 aggregation / ranking 可双路径执行并可比较。
- SQL fallback 对动态列名增加标识符 quoting，降低上传字段名包含空格、中文或特殊字符时的 SQL 失败风险。
- 新增 backend 最小调用壳：DataAgentService、TempFileStore、API schema helper、可选 FastAPI router、main app。
- backend 支持 upload/profile/analyze 的最小本地流程，analyze 返回 run_id、response_version、warnings、errors 和 debug.trace_path。
- 新增 Benchmark metrics 和 error_analysis 聚合，按 operation 和 error_type 输出通用能力缺口，不输出单题修复建议。
- 扩展架构边界测试，确保 backend router 不 import Pandas / SQL / Verifier / Benchmark 核心逻辑。
- 更新 MAIN_GOAL、BRANCH_RULES、API_CONTRACT、ARCHITECTURE、BENCHMARK_RULES、FEATURE_BACKLOG、PHASE_GATES，记录 Phase 1/2/3 当前完成边界。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/dabstep_phase123_dev_verify_after_sql_quote
- source .env.local 后运行 /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/dabstep_phase123_dev_real_llm_verify_final
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- rg -n "^\\s*(from|import)\\s+(backend|ms_agent_framework_adapter|multi_agent_workflows|agent_framework)" data_agent_core
- rg secret-pattern scan against repository files excluding outputs、storage 和 .env*

### 测试结果

- unittest 通过：Ran 17 tests in 9.145s，OK。
- DABstep dev 前 10 题 mock LLM 路径：total=10，scored=10，correct=8，accuracy=0.8。
- DABstep dev 前 10 题真实 LLM 路径：total=10，scored=10，correct=8，accuracy=0.8。
- 真实 LLM 输出文件：outputs/dabstep_phase123_dev_real_llm_verify_final/dev_1_to_10_predictions.jsonl。
- compileall 通过。
- data_agent_core 禁止 import 边界检查未发现实际 import 匹配。
- secret 扫描未发现 API key 进入仓库文件；.env.local 仍为 ignored 文件。

### 遗留问题

- 当前 TempFileStore 只适合 Phase 1 本地测试，进程重启后不会恢复 DataFrame tables。
- Excel 多 sheet、编码识别、复杂表头识别、趋势/对比/复杂过滤仍需后续增强。
- public all.jsonl 的 answer 字段为空，不能本地计算完整 450 题官方准确率。
- DABstep dev 前 10 的 2 个失败点需要后续做通用 top_count 和 best_fraud_aci_choice 能力分析，禁止按题号或题面特判。
- 当前 SQL 路径是 sqlite fallback，后续需要接入 DuckDB runtime。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端或复杂后端业务。

### 是否涉及 Benchmark

是。新增 Benchmark metrics 和 error_analysis，并用 DABstep dev 前 10 做 mock 和真实 LLM 验证；标准答案只在 evaluator 评分阶段使用，不进入核心分析链路或 LLM 输入。

### 是否涉及 Microsoft Agent Framework

否。未安装、未 import、未实现 Microsoft Agent Framework workflow。

### 是否影响未来多 Agent 迁移

是，正向影响。当前 UploadedDatasetAgent、backend service、Benchmark 聚合都保持框架无关，未来可映射到 agent_runtime 和 Microsoft adapter。

### 是否修改核心数据契约

否。未新增或破坏 contracts dataclass 字段；新增 ParsedDataset 是 file_parser 内部返回结构。

### 是否修改 API 契约

是。最小 backend upload/profile/analyze 响应已落地并同步 docs/API_CONTRACT.md，保持 response_version、run_id、warnings、errors。

### 是否新增或修改错误类型

否。未新增错误类型；backend service 使用既有 FILE_PARSE_ERROR 和 LOGIC_FORM_ERROR，Benchmark 归因使用既有 BENCHMARK_EVALUATION_ERROR 和 VERIFICATION_FAILED。

### 是否新增或修改运行追踪逻辑

是。UploadedDatasetAgent 生成 RunTrace，backend service 写入 storage/runs/{run_id}/trace.json，并在 debug.trace_path 中暴露调试路径；trace 不记录完整 Chain of Thought。

---

### 日期时间

2026-05-21 13:32 CST

### 本次目标

根据用户更新后的 MAIN_GOAL，同步 Phase 5 受控 Tool Calling 和 Phase 6+ 多 Agent 路线，并实现 provider-neutral 工具契约、工具注册、工具 dispatcher、工具 trace 摘要和 Microsoft adapter 工具映射骨架。

### 修改文件

- MAIN_GOAL.md
- BRANCH_RULES.md
- docs/API_CONTRACT.md
- docs/ARCHITECTURE.md
- docs/FEATURE_BACKLOG.md
- docs/PHASE_GATES.md
- agent_runtime/README.md
- agent_runtime/tool_contracts.py
- agent_runtime/tool_registry.py
- agent_runtime/tool_dispatcher.py
- agent_runtime/data_agent_tool_catalog.py
- agent_runtime/runtime_interfaces.py
- agent_runtime/workflow_state.py
- data_agent_core/configs/tool_whitelist.yaml
- data_agent_core/contracts/agent_contracts.py
- data_agent_core/tracing/run_trace.py
- ms_agent_framework_adapter/README.md
- ms_agent_framework_adapter/adapter.py
- ms_agent_framework_adapter/tool_mapping.py
- multi_agent_workflows/README.md
- tests/agent_runtime/test_runtime_contracts.py
- tests/agent_runtime/test_tool_calling_contracts.py
- CHANGELOG_AI.md

### 修改内容

- 新增 ToolCall、ToolResult、ToolTraceEvent 和 provider-neutral to_json_ready 工具契约。
- 扩展 ToolDefinition，补 input_schema、allowed_roles、timeout_seconds、result_policy、constraints 和 provider schema 输出。
- 新增 ToolDispatcher，支持工具名查找、角色白名单校验、required/type 参数校验、callable 执行、标准错误和 trace-safe 摘要。
- 新增 Data Agent 白名单工具 catalog：profile_schema、build_analysis_plan、execute_pandas_plan、execute_sql_plan、verify_results、build_chart_spec、generate_insight。
- 更新 tool_whitelist.yaml，声明允许工具、blocked operations、schema validation、role whitelist 和 timeout 要求。
- 更新 WorkflowState 和 RunTrace，预留 tool_call_trace / tool_call_summary。
- 更新 Microsoft adapter 的 tool_mapping 和 adapter plan，使其只声明内部工具到 Microsoft function tool 的映射，不实现工具逻辑、不 import Microsoft 包。
- 更新 docs 和 README，明确 Phase 5 先建立受控工具层，Phase 6+ 再进入多 Agent workflow。
- 新增工具契约测试，覆盖工具元数据、角色校验、参数校验、trace 摘要和 adapter tool mapping。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- rg -n "^\\s*(from|import)\\s+(backend|ms_agent_framework_adapter|multi_agent_workflows|agent_framework)" data_agent_core
- rg secret-pattern scan against repository files excluding outputs、storage 和 .env*
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/tool_layer_dev_verify

### 测试结果

- unittest 通过：Ran 20 tests in 9.135s，OK。
- compileall 通过。
- data_agent_core 禁止 import 边界检查未发现实际 import 匹配。
- secret 扫描未发现 API key 进入仓库文件；.env.local 仍为 ignored 文件。
- DABstep dev 前 10 题 mock LLM 路径：total=10，scored=10，correct=8，accuracy=0.8。

### 遗留问题

- 当前工具层仍是 Phase 5 契约和本地 dispatcher 骨架，尚未接 OpenAI / DeepSeek provider 原生 tool call loop。
- 当前 dispatcher 不执行真实超时中断，只记录每个工具的 timeout_seconds 契约；后续 provider/runtime 层需要补受控超时执行。
- 当前工具 callable 通过 runtime 注入，尚未把 profile_schema 等工具接到真实 data_agent_core 函数。
- Phase 6+ 多 Agent workflow 仍是任务序列骨架，未启用 Microsoft Agent Framework 实际 workflow。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端或复杂后端业务。

### 是否涉及 Benchmark

是，仅运行 DABstep dev 前 10 题回归验证；未修改 Benchmark 数据、未读取 all split 标准答案、未做单题特判。

### 是否涉及 Microsoft Agent Framework

是，仅涉及适配层声明式 tool mapping；未安装、未 import、未实现 Microsoft Agent Framework workflow。

### 是否影响未来多 Agent 迁移

是，正向影响。Phase 5 provider-neutral 工具契约可被 Phase 6+ 多 Agent workflow、Microsoft adapter 或自研 runtime 复用。

### 是否修改核心数据契约

是。新增 agent_runtime 工具契约，并在 data_agent_core/contracts/agent_contracts.py 记录 ToolDefinition / ToolCall / ToolResult 稳定形状。

### 是否修改 API 契约

是。docs/API_CONTRACT.md 预留 debug.tool_call_summaries 的摘要字段，但 API 稳定字段不变，前端仍不能依赖 debug。

### 是否新增或修改错误类型

否。未新增 data_agent_core/errors 错误类型；ToolDispatcher 内部返回 TOOL_DISPATCH_ERROR 作为工具层标准错误 payload。

### 是否新增或修改运行追踪逻辑

是。RunTrace 预留 tool_call_summary，WorkflowState 预留 tool_call_trace，ToolTraceEvent 只记录工具名、角色、参数摘要、结果摘要、错误和耗时，不记录完整 Chain of Thought。

---

### 日期时间

2026-05-21 13:52 CST

### 本次目标

实现受控内部工具 callable，并把 Microsoft Agent Framework 从声明式骨架推进到可选 adapter：支持 function tool 包装、按 AgentRole 创建 Microsoft Agent、按内部角色顺序构建 sequential workflow，同时保持 data_agent_core 框架无关。

### 修改文件

- MAIN_GOAL.md
- BRANCH_RULES.md
- docs/API_CONTRACT.md
- docs/ARCHITECTURE.md
- docs/FEATURE_BACKLOG.md
- docs/PHASE_GATES.md
- requirements-ms-agent.txt
- agent_runtime/README.md
- agent_runtime/data_agent_tool_catalog.py
- agent_runtime/data_agent_tool_impl.py
- data_agent_core/configs/tool_whitelist.yaml
- ms_agent_framework_adapter/README.md
- ms_agent_framework_adapter/adapter.py
- ms_agent_framework_adapter/framework_tools.py
- ms_agent_framework_adapter/framework_agents.py
- ms_agent_framework_adapter/framework_workflow.py
- ms_agent_framework_adapter/tool_mapping.py
- tests/agent_runtime/test_data_agent_tool_impl.py
- tests/agent_runtime/test_runtime_contracts.py
- tests/architecture/test_dependency_boundaries.py
- tests/ms_agent_framework_adapter/__init__.py
- tests/ms_agent_framework_adapter/test_framework_adapter.py

### 修改内容

- 新增 DataAgentToolRuntime 和真实内部工具 callable，覆盖 profile_schema、build_analysis_plan、execute_pandas_plan、execute_sql_plan、verify_results、build_chart_spec、generate_insight。
- 工具 callable 只调用既有 data_agent_core 模块，不开放 raw Python、raw SQL、shell、网络或任意外部文件访问。
- 新增 Microsoft Agent Framework 可选 adapter：framework_tools 负责 function tool 包装，framework_agents 负责按 AgentRole 创建 Agent，framework_workflow 负责 sequential workflow builder。
- 新增 requirements-ms-agent.txt，作为独立可选依赖入口，未把 agent-framework 写入 core/backend 强依赖。
- 更新架构边界测试：允许 agent_framework 只在 ms_agent_framework_adapter 或 tests 中出现，继续禁止 data_agent_core import Microsoft Framework。
- 更新 MAIN_GOAL、BRANCH_RULES、ARCHITECTURE、API_CONTRACT、FEATURE_BACKLOG、PHASE_GATES 和 README，明确 Microsoft adapter 当前实现边界。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- rg -n "^\\s*(from|import)\\s+(backend|ms_agent_framework_adapter|multi_agent_workflows|agent_framework)" data_agent_core
- rg -n "sk-proj-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{20,}" --glob '!outputs/**' --glob '!storage/**' --glob '!.env*' .
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/ms_tool_adapter_dev_verify_final

### 测试结果

- unittest 通过：Ran 25 tests in 8.760s，OK。
- compileall 通过。
- data_agent_core 禁止 import 边界检查未发现匹配。
- secret 扫描未发现 sk-* 或 sk-proj-* key 进入仓库文件。
- DABstep dev 前 10 题 mock LLM 路径：total=10，scored=10，correct=8，accuracy=0.8。

### 遗留问题

- 当前 Microsoft adapter 使用 fake framework 单测验证包装逻辑；未在本轮安装真实 agent-framework 包运行 Azure Foundry client。
- 当前仍未启用 OpenAI / DeepSeek provider 原生 tool call loop。
- requirements-ms-agent.txt 是可选依赖入口，服务器运行真实 Microsoft adapter 前需要单独安装。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端或复杂后端业务。

### 是否涉及 Benchmark

是，仅运行 DABstep dev 前 10 题回归验证；未修改 Benchmark 数据，未把 task_id 或标准答案传入核心分析链路，未做单题特判。

### 是否涉及 Microsoft Agent Framework

是。新增 Microsoft Agent Framework 可选 adapter 和独立可选依赖文件；data_agent_core 不依赖 Microsoft Agent Framework。

### 是否影响未来多 Agent 迁移

是，正向影响。AgentRole、ToolDefinition、ToolDispatcher 和 WorkflowState 现在可以映射到 Microsoft function tool、Agent 和 sequential workflow，同时保留未来替换 LangGraph / CrewAI / 自研 runtime 的空间。

### 是否修改核心数据契约

否。未修改 data_agent_core/contracts 中的稳定 dataclass 字段；本轮新增的是 agent_runtime 工具 callable 和 Microsoft adapter 映射测试。

### 是否修改 API 契约

是。仅更新 docs/API_CONTRACT.md，说明 adapter 参与运行时只能写入 debug / trace 摘要；稳定 upload/analyze/profile 字段未改变。

### 是否新增或修改错误类型

否。未新增 data_agent_core/errors 错误类型；Microsoft adapter 缺包时使用 adapter-local MicrosoftAgentFrameworkUnavailable 异常。

### 是否新增或修改运行追踪逻辑

否。沿用既有 ToolTraceEvent / tool_call_summary 摘要策略；本轮未修改 RunTrace 字段。

---

### 日期时间

2026-05-21 14:14 CST

### 本次目标

按 MAIN_GOAL 进入 Phase 6，把主 analyze 链路从单 Agent 编排切换为最小可运行多 Agent workflow，并保持核心算法框架无关、Benchmark 不泄漏标准答案、不针对题目优化。

### 修改文件

- MAIN_GOAL.md
- BRANCH_RULES.md
- docs/API_CONTRACT.md
- docs/ARCHITECTURE.md
- docs/FEATURE_BACKLOG.md
- docs/PHASE_GATES.md
- README.md
- agent_runtime/README.md
- agent_runtime/data_analysis_roles.py
- backend/routers/data_agent.py
- backend/schemas/data_agent_schema.py
- backend/services/data_agent_service.py
- data_agent_core/benchmark/benchmark_runner.py
- multi_agent_workflows/README.md
- multi_agent_workflows/dabstep_benchmark_runner.py
- multi_agent_workflows/end_to_end_data_analysis_workflow.py
- requirements-ms-agent.txt
- ms_agent_framework_adapter/README.md
- tests/architecture/test_no_benchmark_hardcoding.py
- tests/backend/test_data_agent_service.py
- tests/core/test_dabstep_core.py
- tests/multi_agent_workflows/__init__.py
- tests/multi_agent_workflows/test_phase6_multi_agent_workflow.py

### 修改内容

- 新增 DataAnalysisRoleRuntime，按 Planner、Data Engineer、Pandas Executor、SQL Executor、Verifier、Correction、Insight、Visualization、Response Builder 拆分职责。
- 新增 DataAnalysisMultiAgentWorkflow，作为 Phase 6 内部顺序多 Agent runner；workflow 只编排，不直接实现核心算法。
- backend analyze 默认切换为 agent_mode=multi_agent，single_agent 保留为 fallback。
- 新增 multi_agent_workflows.dabstep_benchmark_runner，DABstep 多 Agent runner 通过外层 wrapper 调用 core benchmark，避免 data_agent_core import multi_agent_workflows。
- 更新 benchmark runner 为 agent_factory 注入模式，保持核心 benchmark runner 框架无关。
- 更新 API / 架构 / Phase Gates / Backlog / README 文档，去掉“未来/预留”旧措辞，明确 Phase 6 最小多 Agent workflow 已启用，Microsoft adapter 仍为可选承载层。
- 新增多 Agent workflow 测试和 backend 默认 multi_agent 验证。
- 将 requirements-ms-agent.txt 调整为轻量 `agent-framework-core==1.5.0`，避免完整 `agent-framework` 元包默认拉取大量 provider extras；真实 provider extras 可按需另装。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/phase6_multi_agent_dev_verify_final
- rg -n "^\\s*(from|import)\\s+(backend|ms_agent_framework_adapter|multi_agent_workflows|agent_framework)" data_agent_core
- rg -n "sk-proj-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{20,}" --glob '!outputs/**' --glob '!storage/**' --glob '!.env*' .
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pip install -r requirements-ms-agent.txt
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 - <<'PY' from agent_framework import Agent, WorkflowBuilder, tool; print('agent_framework core import ok') PY
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 - <<'PY' build_microsoft_tool_functions smoke for 7 FunctionTool objects PY

### 测试结果

- unittest 通过：Ran 27 tests in 11.161s，OK，skipped=1（真实 agent_framework 已安装时跳过缺包错误测试）。
- compileall 通过。
- DABstep dev 前 10 题 multi_agent mock LLM 路径：total=10，scored=10，correct=8，accuracy=0.8。
- data_agent_core 禁止 import 边界检查未发现匹配。
- secret 扫描未发现 sk-* 或 sk-proj-* key 进入仓库文件。
- Microsoft Agent Framework 轻量可选依赖安装通过：agent-framework-core==1.5.0。
- Microsoft adapter import smoke 通过：Agent、WorkflowBuilder、tool 均可从 agent_framework 导入。
- Microsoft function tool smoke 通过：build_microsoft_tool_functions 返回 7 个 FunctionTool 对象，adapter plan 显示 imports_framework=True。

### 遗留问题

- 当前多 Agent 是顺序内部 workflow，尚未启用复杂并行 executor、真实 Microsoft cloud workflow 或多轮代码级自纠执行。
- backend service 当前是 single_agent / multi_agent 的运行模式选择点；router 仍保持薄转发。
- OpenAI / DeepSeek provider 原生 tool call loop 仍未启用。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端、权限、登录、数据库或部署。

### 是否涉及 Benchmark

是。运行 DABstep dev 前 10 做多 Agent 回归；未修改 Benchmark 数据，未把 task_id 或 answer 传入分析链路，未做单题特判。

### 是否涉及 Microsoft Agent Framework

是。Microsoft adapter 仍为可选承载层；当前默认 multi_agent 使用内部 runtime，不要求安装 Microsoft Agent Framework。

### 是否影响未来多 Agent 迁移

是，正向影响。主 analyze 链路已按多 Agent 职责拆分，未来可由 Microsoft Agent Framework、LangGraph、CrewAI 或自研 runtime 承载。

### 是否修改核心数据契约

否。未修改 data_agent_core/contracts 稳定 dataclass 字段。

### 是否修改 API 契约

是。新增可选 agent_mode，默认 multi_agent；稳定响应字段未破坏，新增信息只进入 debug / trace。

### 是否新增或修改错误类型

否。未新增 data_agent_core/errors 错误类型。

### 是否新增或修改运行追踪逻辑

是。多 Agent trace 汇总 tool_call_summary、agent_task_results、multi_agent_roles；仍不记录完整 Chain of Thought、raw reasoning tokens 或 API key。

---

### 日期时间

2026-05-21 14:50 CST

### 本次目标

按最新诊断结果更新 MAIN_GOAL，把下一阶段从“更换多 Agent 框架”明确调整为“业务口径驱动的多 Agent 质量提升”，并加入可执行 TODO，避免后续按 DABstep 单题修补。

### 修改文件

- MAIN_GOAL.md
- CHANGELOG_AI.md

### 修改内容

- 在当前实现状态中记录：DABstep dev 前 10 题保持 8/10 的瓶颈来自核心语义口径和费用模拟能力，不是 Microsoft adapter 或多 Agent 框架本身。
- 新增“下一阶段：业务口径驱动的多 Agent 质量提升”章节，明确 Planner、Data Engineer、Executor、Verifier、Correction、Response Builder 和 Microsoft adapter 的职责边界。
- 新增“下一阶段 TODO”，覆盖 Planner 语义指标增强、Data Engineer 业务定义落地、通用 Executor 能力、Verifier 语义校验、Correction 闭环重跑、trace/debug 证据、能力族回归测试和阶段验收标准。
- 明确下一阶段必须通过通用能力修复 DABstep dev 前 10 的已知失败类型，禁止按 task_id、题号、标准答案或固定题面写特判。

### 测试方式

- 文档规划变更，未运行代码测试。
- 只读检查 MAIN_GOAL.md、CHANGELOG_AI.md、BRANCH_RULES.md 和当前 git 状态。

### 测试结果

- 未运行自动化测试；本次未修改 Python、API、contracts、tracing 或 runtime 逻辑。

### 遗留问题

- 下一阶段仍需实际实现 Planner 语义指标、Verifier 语义校验、Correction 重跑和通用 executor 能力。
- DABstep dev 前 10 当前仍为 8/10，本次只记录下一阶段计划，不改变评测结果。

### 是否影响主流程

否。仅文档规划变更。

### 是否涉及 Benchmark

是。仅记录 DABstep dev 前 10 的已知能力缺口和下一阶段通用修复方向；未修改 Benchmark 数据、runner、评分器或标准答案。

### 是否涉及 Microsoft Agent Framework

是。仅文档说明 Microsoft adapter 仍只负责承载和映射，不承载业务语义、Pandas、SQL、Verifier 或 Benchmark 逻辑。

### 是否影响未来多 Agent 迁移

是。明确下一阶段多 Agent 迁移重点是业务口径校验、结构化修正和受控重跑，而不是继续更换框架。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。仅提出下一阶段 trace/debug 证据增强 TODO。

---

### 日期时间

2026-05-21 15:09 CST

### 本次目标

按用户明确要求，将“禁止针对题目特调”提升为下一阶段 Rule NO.1，并把 DABstep 21-50 public proxy 暴露的问题写成通用能力族目标，而不是题号修复计划。

### 修改文件

- MAIN_GOAL.md
- CHANGELOG_AI.md

### 修改内容

- 在 MAIN_GOAL 当前实现状态中补充：all 21-50 public proxy 只能作为阶段性回归观察，不能替代 hidden ground truth official score。
- 在架构原则中新增 Rule NO.1：禁止针对 Benchmark 题号、task_id、题面、标准答案、隐藏答案推测或 public proxy 答案池做单题特调；所有提升必须抽象为可复用能力族。
- 在“下一阶段：业务口径驱动的多 Agent 质量提升”中新增 Rule NO.1 专段，明确 public proxy answer pool 不能进入 Planner、Executor、Verifier、Correction、prompt、测试 fixture 或核心分析链路。
- 将 all 21-50 暴露出的失败归纳为能力族：字段枚举、比例和百分比、数据质量检查、欺诈维度排名、ACI 极值、Fee restriction 影响商户分析、Public proxy 回归报告。
- 在重要红线中将禁止单题特调调整为第 1 条。

### 测试方式

- 文档规划变更，未运行代码测试。
- 只读检查 MAIN_GOAL.md、CHANGELOG_AI.md 和当前 git 状态。

### 测试结果

- 未运行自动化测试；本次未修改 Python、API、contracts、tracing 或 runtime 逻辑。

### 遗留问题

- 当前工作区存在多个非本次修改的 Python 文件变更；本次未触碰、未回滚。
- 下一阶段仍需按能力族实现字段枚举、比例、重复检测、欺诈维度排名、ACI 极值和 fee restriction 影响分析。

### 是否影响主流程

否。仅文档规划变更。

### 是否涉及 Benchmark

是。仅明确 Benchmark / public proxy 的使用边界和禁止单题特调规则；未修改 Benchmark 数据、runner、评分器或标准答案。

### 是否涉及 Microsoft Agent Framework

否。未修改 Microsoft adapter 或框架接入逻辑。

### 是否影响未来多 Agent 迁移

是。将下一阶段多 Agent 迁移的首要约束明确为能力族泛化，不允许按题号或答案池特调。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

---

### 日期时间

2026-05-21 15:25 CST

### 本次目标

按用户更新后的 MAIN_GOAL 继续推进下一阶段：业务口径驱动的多 Agent 质量提升。重点增强 LogicForm 指标语义、fraud ranking 通用口径、Verifier 语义校验、Correction 结构化修正重跑、运行追踪证据和能力级测试，禁止按 DABstep 题号或标准答案优化。

### 修改文件

- MAIN_GOAL.md
- docs/API_CONTRACT.md
- docs/ARCHITECTURE.md
- docs/FEATURE_BACKLOG.md
- docs/PHASE_GATES.md
- agent_runtime/data_agent_tool_impl.py
- agent_runtime/data_analysis_roles.py
- data_agent_core/contracts/analysis_contracts.py
- data_agent_core/contracts/verification_contracts.py
- data_agent_core/core/intent_parser.py
- data_agent_core/core/logic_form.py
- data_agent_core/executors/pandas_executor.py
- data_agent_core/executors/sql_executor.py
- data_agent_core/output/response_builder.py
- data_agent_core/tracing/run_trace.py
- data_agent_core/verifier/result_comparator.py
- data_agent_core/verifier/rule_checker.py
- multi_agent_workflows/end_to_end_data_analysis_workflow.py
- tests/core/test_semantic_metric_verification.py
- CHANGELOG_AI.md

### 修改内容

- 扩展 LogicForm，新增 metric、metric_definition、numerator、denominator、group_by、objective 和 options，用于表达业务指标口径。
- 将 top fraud 类 ranking 从原始 transaction count 改为通用 fraud_volume_rate 指标，分子为 fraudulent eur_amount，分母为 total eur_amount，支持 multiple-choice candidate table。
- 扩展 Pandas / SQL 执行器，支持 rank_by_metric / fraud_volume_rate 双路径执行，返回 answer、selected、selected_option、metric、metric_definition、candidate_table。
- 扩展 Result Comparator，对 dict 结果优先比较最终 answer，避免候选表浮点细节导致 Pandas / SQL 一致答案被误判。
- 扩展 VerificationResult 和 Verifier，检查业务语义口径；当 fraud ranking 使用 raw count 时输出 correction_action。
- 扩展 Correction Agent 和 multi_agent workflow，能把 correction_action 转成 corrected LogicForm，并触发一次受控 Pandas / SQL / Verifier 重跑。
- 扩展 RunTrace，记录 metric_definition、numerator、denominator、semantic_verification_notes、candidate_table_summary 和 selected_candidate。
- 更新 response builder，使执行结果 value 为 dict 且包含 answer 时，最终 answer 使用该稳定字段。
- 新增合成测试，验证 fraud ranking 按 volume rate 而非 raw count，并验证 Verifier 能对错误口径发出结构化修正。
- 同步 MAIN_GOAL、ARCHITECTURE、API_CONTRACT、FEATURE_BACKLOG、PHASE_GATES，记录当前 dev 前 10 为 9/10，并明确 ACI associated cost 仍是通用能力缺口。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_semantic_metric_verification tests.core.test_dabstep_core tests.multi_agent_workflows.test_phase6_multi_agent_workflow
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/next_phase_semantic_tests_dev_1_10
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 50 --offset 0 --output-dir outputs/next_phase_semantic_all_1_50
- rg dependency-boundary scan for forbidden data_agent_core imports
- rg secret-pattern scan excluding outputs、storage 和 .env*
- rg hardcoding scan for task_id equality、DABstep dev answer literals and expected_answer usage

### 测试结果

- 针对性单测通过：Ran 7 tests，OK。
- 全量单测通过：Ran 29 tests，OK，skipped=1。
- compileall 通过。
- DABstep dev 前 10：total=10，scored=10，correct=9，accuracy=0.9，agent_mode=multi_agent。
- DABstep all 前 50：total=50，success_count=50，scored=0，accuracy=null；本地 public all.jsonl answer 字段为空，不能计算官方准确率。
- data_agent_core 禁止 import 边界检查未发现实际 import 匹配。
- secret 扫描未发现 API key 进入仓库文件。
- 硬编码扫描未发现 task_id 等值判断、dev 答案字面值或核心链路 expected_answer 使用；仅剩文档和架构测试中的禁止项说明。

### 遗留问题

- ACI incentive / associated cost 费用口径仍需继续作为通用 fee what-if candidate table 能力增强；当前不能为了 dev 单题写答案特判。
- 当前 SQL 路径仍是 sqlite fallback，后续需要接 DuckDB runtime。
- all split public 文件没有本地答案，不能用本地 public all.jsonl 计算官方完整 450 题准确率。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端或复杂后端业务。

### 是否涉及 Benchmark

是。使用 DABstep dev 前 10 和 public all 前 50 做回归与执行覆盖；标准答案只在 dev evaluator 评分阶段使用，不进入 Planner、Executor、Verifier、Correction、prompt 或 LLM 输入。

### 是否涉及 Microsoft Agent Framework

是，但只保持既有 adapter / multi-agent 映射边界。本轮没有安装 Microsoft Agent Framework，没有把核心算法写入 adapter，也没有让 data_agent_core 依赖 Microsoft Agent Framework。

### 是否影响未来多 Agent 迁移

是，正向影响。多 Agent WorkflowState、Verifier、Correction 和 trace 增强都保持框架无关，可继续映射到 Microsoft Agent Framework 或其他编排框架。

### 是否修改核心数据契约

是。扩展 LogicForm 和 VerificationResult，用于表达业务指标口径、语义校验结果和结构化 correction_action。

### 是否修改 API 契约

是。docs/API_CONTRACT.md 记录 verification 的 semantic_passed、semantic_verification_notes、correction_action，以及 trace 的 metric_definition、candidate_table_summary、selected_candidate 等调试字段；稳定响应主字段不变。

### 是否新增或修改错误类型

否。未新增 data_agent_core/errors 错误类型。

### 是否新增或修改运行追踪逻辑

是。RunTrace 新增指标定义、分子、分母、语义校验 notes、候选表摘要和选中候选记录；trace 仍不记录完整 Chain of Thought、raw reasoning tokens 或 API key。

---

### 日期时间

2026-05-21 15:35 CST

### 本次目标

按用户纠正更新项目口径：把“禁止特调”从只禁止题号、标准答案和固定题面硬编码，扩展为禁止任何只适配当前数据集、当前字段值、当前问法或当前错误样本的伪泛化补丁。

### 修改文件

- MAIN_GOAL.md
- README.md
- BRANCH_RULES.md
- docs/PHASE_GATES.md
- docs/BENCHMARK_RULES.md
- docs/ARCHITECTURE.md
- docs/FEATURE_BACKLOG.md
- CHANGELOG_AI.md

### 修改内容

- 在 MAIN_GOAL 中重写 Rule NO.1：特调不仅包括 Benchmark task_id / 题号 / 标准答案 / public proxy answer pool，也包括不能迁移到同类业务问题和其他数据集的伪泛化补丁。
- 在下一阶段规则中新增泛化验收：新能力必须说明迁移边界，并至少用非 Benchmark 或合成通用用例、同类变体和旧代表回归证明不是只修当前失败样本。
- 在 PHASE_GATES、BENCHMARK_RULES、ARCHITECTURE、FEATURE_BACKLOG 中同步“伪泛化补丁”红线，要求错误归因写成能力族缺口和泛化验证方式。
- 在 BRANCH_RULES 和 PR 模板中新增“硬编码或伪泛化风险”和“泛化验证方式”输出要求。
- 在 README 中把 Phase 6 当前状态同步为 dev 前 10 可复现 9/10，并把后续 TODO 改为 ACI associated cost / fee what-if candidate table 的通用能力增强。

### 测试方式

- 文档口径变更，未运行 Python 自动化测试。
- 检查 git diff，确认改动范围只包含项目文档和 CHANGELOG。

### 测试结果

- 未运行自动化测试；本次未修改 Python、API、contracts、tracing 或 runtime 逻辑。

### 遗留问题

- 当前仓库仍存在本次之前已有的 Python 和文档未提交变更；本次没有回滚或覆盖这些改动。
- 后续实现任何 benchmark 暴露问题时，必须配套合成/非 Benchmark 泛化用例，不能只依赖当前失败题目。

### 是否影响主流程

否。仅文档和项目规则口径变更。

### 是否涉及 Benchmark

是。仅调整 Benchmark 使用边界和泛化验收口径；未修改 Benchmark 数据、runner、evaluator 或标准答案。

### 是否涉及 Microsoft Agent Framework

否。未修改 Microsoft adapter 或框架接入逻辑。

### 是否影响未来多 Agent 迁移

是。明确多 Agent 质量提升必须以可迁移能力族为目标，禁止用伪泛化补丁替代 Planner / Data Engineer / Verifier / Correction 的真实能力建设。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

---

### 日期时间

2026-05-21 15:53 CST

### 本次目标

按用户要求把 Provider 原生 Tool Calling Adapter 明确为 MAIN_GOAL 的下一阶段 Phase：先接 OpenAI 原生工具循环，再把 DeepSeek 作为 provider 协议差异特化接入，同时保留本地 ToolDispatcher 作为唯一受控执行入口。

### 修改文件

- MAIN_GOAL.md
- CHANGELOG_AI.md

### 修改内容

- 在当前实现状态中新增下一阶段方向：Provider 原生 Tool Calling Adapter，OpenAI 先行，DeepSeek 后续特化。
- 在架构原则中新增 provider native tool call 必须转换为内部 ToolCall，并经过 ToolDispatcher 白名单、角色、schema、超时和 trace 摘要校验。
- 新增 `下一阶段 Phase 7：Provider 原生 Tool Calling Adapter`，定义目标、阶段顺序、标准调用链和验收标准。
- 将原来的“下一阶段：业务口径驱动的多 Agent 质量提升”改名为 Phase 6 质量提升，避免与新的下一阶段 Phase 冲突。

### 测试方式

- 文档口径变更，未运行 Python 自动化测试。
- 执行 git diff 检查改动范围和文档一致性。

### 测试结果

- 未运行自动化测试；本次未修改 Python 逻辑、API、contracts、runtime 执行代码或测试代码。

### 遗留问题

- Phase 7 仍是目标文档，尚未实现 OpenAI / DeepSeek provider 原生 tool loop adapter。
- 后续实现必须补 mock provider、OpenAI adapter、DeepSeek adapter 和回归测试。

### 是否影响主流程

否。仅文档目标和阶段定义变更。

### 是否涉及 Benchmark

否。未修改 Benchmark 数据、runner、evaluator 或评分逻辑；仅要求后续启用 provider-native tool loop 不能降低现有 smoke benchmark 可复现性。

### 是否涉及 Microsoft Agent Framework

否。未修改 Microsoft adapter；仅保留其作为可选协议/框架适配层的边界。

### 是否影响未来多 Agent 迁移

是。明确下一阶段 provider-native tool loop 必须挂接到内部 ToolDispatcher，不能替代 multi_agent workflow 或把核心算法迁入 provider adapter。

### 是否修改核心数据契约

否。仅文档说明，未修改 ToolDefinition、ToolCall、ToolResult 或 ToolTraceEvent 代码。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

---

### 日期时间

2026-05-21 16:16 CST

### 本次目标

按 MAIN_GOAL 下一阶段要求，以能力族方式补齐 DABstep all 21-50 暴露的通用缺口，并用 public proxy accepted pool 做后验观察；禁止把 proxy answer、task_id、标准答案或固定题面写入核心链路。

### 修改文件

- data_agent_core/core/intent_parser.py
- data_agent_core/executors/pandas_executor.py
- data_agent_core/executors/sql_executor.py
- data_agent_core/core/dabstep_fee_engine.py
- data_agent_core/output/response_builder.py
- data_agent_core/llm/planner.py
- data_agent_core/agent/single_agent.py
- agent_runtime/data_analysis_roles.py
- tests/core/test_generic_capability_operations.py
- CHANGELOG_AI.md

### 修改内容

- 新增通用字段枚举能力 `field_values`，从数据列去重生成候选值。
- 新增通用比例/百分比能力 `boolean_percentage`，用于 credit/debit 等布尔字段占比。
- 新增通用重复行检测能力 `duplicate_check`，返回标准 yes/no 和重复行计数摘要。
- 新增过滤后 fraud rate 能力 `fraud_rate_filtered`，按 fraudulent volume / total volume 输出百分比。
- 扩展 fraudulent transactions 维度排名解析，支持设备类型等维度的 most common 查询。
- 新增 ACI 极值能力 `aci_fee_extreme`，基于 fee rule 对指定 card scheme、credit/debit、transaction value 的 ACI 候选进行通用费用比较，并按字母顺序处理并列。
- 扩展 fee affected merchants 解析，支持 “which merchants were affected by Fee ID” 这类通用 fee impact 查询。
- 扩展 SQL-compatible operation 集合，使字段枚举、布尔百分比和过滤后 fraud rate 可走 SQL 路径对比。
- 新增合成/非 Benchmark 单元测试，覆盖上述能力族和 ACI tie-break，不使用 proxy answer 作为 fixture。

### 测试方式

- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_generic_capability_operations
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- rg -n "^\\s*(from|import)\\s+(backend|ms_agent_framework_adapter|multi_agent_workflows|agent_framework)" data_agent_core
- rg hardcoding/secret scan for task_id equality、proxy answer fields、expected_answer fields and API key patterns in source paths
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 50 --offset 0 --output-dir outputs/next_phase_capability_1_50_final

### 测试结果

- 新增能力测试通过：Ran 8 tests，OK。
- 全量 unittest 通过：Ran 37 tests in 12.495s，OK，skipped=1。
- compileall 通过。
- data_agent_core import 边界扫描未发现违规 import。
- 源码硬编码/secret 扫描未发现 task_id 等值判断、proxy answer 字段、expected_answer 字段或 API key 进入核心链路；仅命中文档式 benchmark metrics docstring。
- DABstep all 1-50 public split 可运行：success_count=50；public all.jsonl 无答案，官方本地 accuracy 仍为 null。
- 使用既有 public proxy accepted pool 做离线观察：1-10 为 10/10，21-50 为 27/30，1-50 为 47/50，proxy accuracy=94%。该结果不是 hidden official score。

### 遗留问题

- 剩余 proxy mismatch 集中在 fee_rate_delta 的小数口径微差，需后续按通用 fee delta 口径继续分析，不能按题号或 proxy 数值补丁。
- public all.jsonl 的 answer 字段为空，本地仍不能计算完整 450 题 official accuracy。
- proxy accepted pool 只能用于离线观察和能力缺口归因，不能进入 Planner、Executor、Verifier、Correction、prompt、测试 fixture 或核心逻辑。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端或复杂后端业务。

### 是否涉及 Benchmark

是。运行 DABstep all 1-50 和 public proxy 后验观察；未修改 Benchmark 数据、未读取 hidden answer、未将 proxy answer 写入核心链路或测试。

### 是否涉及 Microsoft Agent Framework

否。未安装、未引入或修改 Microsoft Agent Framework；仅保持现有 adapter 可选边界。

### 是否影响未来多 Agent 迁移

是，正向影响。新增能力仍位于 data_agent_core 和 agent_runtime SQL-compatible operation 列表，Phase 6 多 Agent workflow 可复用，核心算法不依赖 Microsoft adapter。

### 是否修改核心数据契约

否。未新增或修改 contracts dataclass 字段；仅新增 LogicForm operation 的受控实现。

### 是否修改 API 契约

否。API 稳定字段未变化。

### 是否新增或修改错误类型

否。未新增 data_agent_core/errors 错误类型。

### 是否新增或修改运行追踪逻辑

否。使用既有 RunTrace 和 reasoning_trace 输出；未新增 trace 字段，未记录完整 Chain of Thought。

---

### 日期时间

2026-05-21 16:40 CST

### 本次目标

按用户要求把刚才归因的 `Not Applicable` 问题加入 MAIN_GOAL，作为下一阶段目标，明确区分真实不适用和通用能力缺口，并列出基础表分析、统计质量、Top-K 占比、过滤排名、fraud likelihood 比较和 fee 极值维度扩展等能力族。

### 修改文件

- MAIN_GOAL.md
- CHANGELOG_AI.md

### 修改内容

- 新增“下一阶段目标：`Not Applicable` 能力缺口闭环”章节。
- 明确 `Not Applicable` 需要拆分为 `true_unsupported` 和 `capability_gap`。
- 增加 benchmark/report 语义修正目标，避免 all split 中 unexpected `Not Applicable` 被 success 状态掩盖。
- 增加 Planner 与 guardrail 协同升级目标，要求 LLM proposed operation 在受控验证后可进入候选 LogicForm 流程。
- 归纳下一阶段能力族：`row_count`、`distinct_count`、`repeat_entity_percentage`、`outlier_count`、`top_k_share`、`filtered_metric_ranking`、扩展 fraud rate comparison、`fee_extreme_by_dimension`。
- 补充每个能力族必须通过合成/非 Benchmark 用例、同类问法变体和代表回归用例验收。

### 测试方式

未运行测试；仅修改目标文档和变更记录。

### 测试结果

不适用，文档-only 修改。

### 遗留问题

后续仍需按新增目标实现对应 LogicForm、Parser/Planner、Executor、Verifier、Trace 和 benchmark report 改造。

### 是否影响主流程

否，本次只更新目标文档。

### 是否涉及 Benchmark

涉及 Benchmark 目标和报告语义说明，但未修改 benchmark 代码或读取标准答案。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

是，新增目标要求 Planner、Executor、Verifier、Correction 和 Trace 对 `Not Applicable` 缺口做结构化协同。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否，仅提出后续区分 `true_unsupported` 与 `capability_gap` 的目标。

### 是否新增或修改运行追踪逻辑

否，仅提出后续 Trace/debug 增强目标。

---

### 日期时间

2026-05-21 17:11 CST

### 本次目标

让核心算法在桌面 Microsoft 脱敏数据的 DAB 风格测试集上可用，并修复真实 LLM + 多 Agent 链路中中文零售分销问题的表选择、字段映射、日期过滤、门店集合关联、比率和多指标汇总能力。禁止按题号、标准答案或固定输出值优化。

### 修改文件

- data_agent_core/core/chinese_retail_intent.py
- data_agent_core/core/intent_parser.py
- data_agent_core/executors/chinese_retail_executor.py
- data_agent_core/executors/pandas_executor.py
- data_agent_core/output/response_builder.py
- data_agent_core/core/file_parser.py
- tests/core/test_chinese_retail_capabilities.py
- CHANGELOG_AI.md

### 修改内容

- 新增中文零售分销意图解析层，基于上传表 schema 和业务术语生成 `retail_*` LogicForm 操作。
- 新增中文零售执行器能力，覆盖历史分销金额、分销目标、计划拜访线路、合约店、今日分销明细、成功拜访、分销进度、财年数量、陈列签约、陈列费率、检查合格率、多指标汇总和活跃 SKU TopN。
- 修复同类列名导致今日分销明细误选历史表的问题，表选择优先使用语义表名，再回退到 schema。
- 修复主任/业代角色判定，优先按历史分销表中的 `emp_name` / `p_emp_name` 语义区分。
- `read_csv` 增加 `utf-8-sig`、`utf-8`、`gb18030`、`gbk` 编码 fallback，支持本地中文 CSV。
- `format_answer` 新增百分比输出和 half-up 小数格式，并修复字符串列表被拆成单字的问题。
- 新增合成单元测试，覆盖表选择、金额 half-up、门店集合 join、日目标进度、陈列合格率和签约陈列门店数；测试不使用 Microsoft 标准答案。

### 测试方式

- VDS_LLM_PROVIDER=mock PYTHONPATH=. /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 - <<'PY' ... Microsoft 22 题 mock LLM 本地评测
- set -a; source .env.local; set +a; PYTHONPATH=. /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 - <<'PY' ... Microsoft 22 题真实 LLM 本地评测
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_chinese_retail_capabilities
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- rg -n "^\\s*(from|import)\\s+(backend|ms_agent_framework_adapter|multi_agent_workflows|agent_framework)" data_agent_core
- rg hardcoding/secret scan for API key patterns, Microsoft task id literals, task_id equality, question_id equality, expected_answer and proxy answer in source/test paths
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/ms_retail_regression_dabstep_dev10

### 测试结果

- 修改前真实 LLM + 多 Agent Microsoft 脱敏 22 题基线：0/22，accuracy=0.0；主要失败原因为中文问题未映射到正确表和业务口径。
- 修改后 mock LLM Microsoft 脱敏 22 题：22/22，accuracy=1.0。
- 修改后真实 LLM Microsoft 脱敏 22 题：22/22，accuracy=1.0，报告目录 `outputs/microsoft_anonymized_eval_llm_20260521_165903`。
- 新增合成能力测试通过：Ran 4 tests，OK。
- 全量 unittest 通过：Ran 41 tests in 11.408s，OK，skipped=1。
- compileall 通过。
- data_agent_core 禁止 import 边界扫描未发现违规 import。
- 源码/测试硬编码和 secret 扫描未发现 API key、Microsoft task id 字面值、task_id 等值判断或 proxy answer 进入核心链路；仅命中架构测试中的禁止项说明。
- DABstep dev 前 10 题多 Agent mock LLM 回归：9/10，accuracy=0.9，剩余失败仍为既有 `best_fraud_aci_choice` 通用缺口。

### 遗留问题

- Microsoft 脱敏 22 题是本地 DAB 风格测试集，不代表 DABstep hidden 官方分数。
- 新增中文零售能力当前覆盖单区域单表/少量关联口径；后续如扩展到更多字段别名、多表 join 或跨数据源，需要继续走 schema/业务术语泛化，不允许按题目补丁。
- DABstep dev 前 10 题仍有 1 个既有 ACI fee 口径失败，需要按通用 fee what-if 能力继续修复。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端页面或复杂后端业务。

### 是否涉及 Benchmark

是。运行 Microsoft 脱敏 DAB 风格 22 题本地评测和 DABstep dev 前 10 题回归；标准答案只用于离线 scorer，不进入 prompt、Planner、Executor、Verifier、Correction、测试 fixture 或核心逻辑。

### 是否涉及 Microsoft Agent Framework

否。未安装、未 import、未修改 Microsoft Agent Framework adapter。

### 是否影响未来多 Agent 迁移

是，正向影响。新增能力位于 `data_agent_core`，通过 LogicForm 和 Pandas executor 被现有多 Agent runtime 调用；核心算法仍不依赖 Microsoft adapter。

### 是否修改核心数据契约

否。未修改 contracts dataclass 字段；新增的是 LogicForm operation 能力。

### 是否修改 API 契约

否。API 稳定字段未变化；仅改进最终 answer 的数字/百分比格式化。

### 是否新增或修改错误类型

否。未新增或修改 `data_agent_core/errors` 错误类型。

### 是否新增或修改运行追踪逻辑

否。沿用既有 RunTrace / tool trace 摘要，不记录完整 Chain of Thought。

---

### 日期时间

2026-05-21 17:16 CST

### 本次目标

根据用户要求，把“中文优先、英文兼容”写入项目红线、分支规则、架构规则、Phase Gate、API 契约说明和功能 Backlog，确保后续 Data Agent 能力开发以中文使用场景为主路径，同时保留英文 Benchmark 和英文字段兼容能力。

### 修改文件

- MAIN_GOAL.md
- BRANCH_RULES.md
- docs/ARCHITECTURE.md
- docs/FEATURE_BACKLOG.md
- docs/PHASE_GATES.md
- docs/API_CONTRACT.md
- CHANGELOG_AI.md

### 修改内容

- 在 MAIN_GOAL 当前实现状态、架构原则、Phase 6 Rule NO.1 和重要红线中增加中文优先、英文兼容规则。
- 在 BRANCH_RULES 禁止行为、完成后输出项、PR 规则和 PR 模板中增加中文优先与英文兼容检查项。
- 在 docs/ARCHITECTURE.md 增加语言优先级章节，明确中文问题、中文字段名、中文业务术语和中文输出格式属于核心主路径。
- 在 docs/FEATURE_BACKLOG.md 新增 Chinese-First Multilingual Data Analysis 功能项，记录目标、影响模块、验收标准、风险和泛化验证方式。
- 在 docs/PHASE_GATES.md 总红线中加入中文优先阶段门槛。
- 在 docs/API_CONTRACT.md 全局响应规则中说明稳定字段语言中立，但可读文本必须优先支持中文并保持英文兼容。

### 测试方式

- 文档规则更新，无代码执行逻辑变更。
- rg -n "中文优先|英文兼容|语言优先级|Chinese-First" MAIN_GOAL.md BRANCH_RULES.md docs/ARCHITECTURE.md docs/FEATURE_BACKLOG.md docs/PHASE_GATES.md docs/API_CONTRACT.md
- rg -n "sk-[A-Za-z0-9_-]{20,}" MAIN_GOAL.md BRANCH_RULES.md docs CHANGELOG_AI.md

### 测试结果

- 文档关键字检查通过，新增规则分布在 MAIN_GOAL、BRANCH_RULES、ARCHITECTURE、FEATURE_BACKLOG、PHASE_GATES 和 API_CONTRACT。
- 文档 secret 扫描未发现 API key。

### 遗留问题

- 本轮只更新治理规则，没有新增中文能力测试或核心算法实现。
- 后续能力类改动需要按新规则优先提供中文合成/非 Benchmark 验收，并保留英文回归。

### 是否影响主流程

否。仅文档和规则更新，不修改旧 BigCat / VDS 主流程。

### 是否涉及 Benchmark

否。未运行或修改 Benchmark；只增加后续中文优先和英文回归的治理要求。

### 是否涉及 Microsoft Agent Framework

否。未安装、未 import、未修改 Microsoft Agent Framework adapter。

### 是否影响未来多 Agent 迁移

是，正向影响。要求 Planner、Data Engineer、Verifier、Correction、Tool 和多 Agent workflow 后续都优先考虑中文场景，同时保持英文兼容。

### 是否修改核心数据契约

否。未修改 contracts dataclass 字段。

### 是否修改 API 契约

是。docs/API_CONTRACT.md 增加语言中立稳定字段、中文优先可读文本和 debug 不可依赖的说明；未改变实际 API 字段。

### 是否新增或修改错误类型

否。未修改错误类型。

### 是否新增或修改运行追踪逻辑

否。未修改运行追踪字段或逻辑。

---

### 日期时间

2026-05-21 17:41 CST

### 本次目标

按 MAIN_GOAL 下一阶段推进 `Not Applicable` 能力缺口闭环：区分 `true_unsupported` / `capability_gap`，补齐第一批基础表分析、数据质量、过滤排名和 fee extreme 通用能力族，并用中文优先和英文兼容的合成用例验证，禁止按 DABstep 题号、proxy answer 或当前样本固定值优化。

### 修改文件

- MAIN_GOAL.md
- docs/API_CONTRACT.md
- docs/ARCHITECTURE.md
- docs/FEATURE_BACKLOG.md
- docs/PHASE_GATES.md
- data_agent_core/errors/error_types.py
- data_agent_core/tracing/run_trace.py
- data_agent_core/output/response_builder.py
- data_agent_core/core/intent_parser.py
- data_agent_core/core/dabstep_fee_engine.py
- data_agent_core/executors/pandas_executor.py
- data_agent_core/executors/sql_executor.py
- data_agent_core/llm/planner.py
- data_agent_core/agent/single_agent.py
- data_agent_core/benchmark/benchmark_runner.py
- data_agent_core/benchmark/metrics.py
- data_agent_core/benchmark/error_analysis.py
- agent_runtime/data_analysis_roles.py
- multi_agent_workflows/end_to_end_data_analysis_workflow.py
- tests/core/test_generic_capability_operations.py
- CHANGELOG_AI.md

### 修改内容

- 新增 `CAPABILITY_GAP` 错误类型。
- Response Builder 对 `Not Applicable` 增加归因：`true_unsupported` 表示规则、manual、schema 或业务知识未定义；`capability_gap` 表示可回答但当前通用能力族未覆盖。
- `capability_gap` 会进入 errors / warnings，并使 response.success=false，避免 benchmark report 把 unexpected Not Applicable 视为正常成功。
- RunTrace、debug 和 benchmark report 增加 not_applicable_attribution 摘要，不记录完整 Chain of Thought、raw reasoning tokens、API key 或敏感原始数据。
- 新增或扩展通用能力族：`row_count`、`distinct_count`、`repeat_entity_percentage`、`outlier_count`、`top_k_share`、`filtered_metric_ranking`、credit/debit `fraud_rate_comparison`、`fee_extreme_by_dimension`。
- Pandas Executor 支持上述能力；SQL fallback 支持 row_count、distinct_count、repeat_entity_percentage、top_k_share、filtered_metric_ranking。
- DABstep fee engine 新增通用 MCC fee extreme 维度比较，支持 tied candidates list 和 candidate_table。
- Benchmark metrics / error_analysis 单独统计 unexpected Not Applicable、true unsupported 和 capability gap。
- 文档同步 API 契约、架构说明、Feature Backlog、Phase Gates 和 MAIN_GOAL 当前状态。
- 新增合成/非 Benchmark 单元测试，覆盖中文字段 row_count/distinct_count、英文 repeat/outlier/top share/filter ranking、credit/debit fraud likelihood、last quarter filtered ranking、MCC fee extreme tie list 和 Not Applicable 归因。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_generic_capability_operations
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- rg import-boundary scan for forbidden data_agent_core imports
- rg secret scan for API key patterns excluding outputs、storage 和 .env*
- rg hardcoding scan for task_id equality、expected_answer/proxy answer/public proxy/accepted answer patterns in source paths
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 50 --offset 50 --output-dir outputs/not_applicable_gap_51_100_after_mcc_extreme

### 测试结果

- 新增能力测试通过：Ran 16 tests，OK。
- 全量 unittest 通过：Ran 49 tests in 12.410s，OK，skipped=1。
- compileall 通过。
- data_agent_core 禁止 import 边界扫描未发现违规 import。
- secret 扫描未发现 API key 进入仓库文件。
- 硬编码扫描未发现 task_id 等值判断、expected_answer/proxy answer/public proxy/accepted answer 进入源码链路。
- DABstep all 51-100 public split 可运行：total=50，scored=0，accuracy=null，success_count=50，unexpected_not_applicable=0，true_unsupported=1。public all.jsonl answer 为空，因此该结果不是 official accuracy。

### 遗留问题

- public all.jsonl 无标准答案，本地仍不能计算 DABstep all 51-100 official accuracy。
- `true_unsupported=1` 为未定义 high-fraud fine / danger 阈值，当前保持安全兜底，不臆造答案。
- 后续还需继续扩展 null_check、季度/last quarter 更多表达、fraud likelihood 多维比较、fee what-if candidate table 和 provider-native tool calling adapter。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端或复杂后端业务。

### 是否涉及 Benchmark

是。运行 DABstep all 51-100 public split 作为后验执行覆盖和 Not Applicable 归因观察；未读取 hidden answer、未使用 proxy answer、未将 task_id 或标准答案写入核心链路或测试。

### 是否涉及 Microsoft Agent Framework

否。未安装、未引入或修改 Microsoft Agent Framework；保持既有 adapter 可选边界。

### 是否影响未来多 Agent 迁移

是，正向影响。新增能力通过 LogicForm、agent_runtime SQL-compatible operation、RunTrace 和 multi_agent workflow debug/trace 传递，data_agent_core 仍不依赖 multi_agent_workflows 或 Microsoft adapter。

### 是否修改核心数据契约

是。新增 `CAPABILITY_GAP` 错误类型，RunTrace 增加 not_applicable_attribution；LogicForm dataclass 字段未破坏，仅新增 operation 能力族。

### 是否修改 API 契约

是。docs/API_CONTRACT.md 记录 debug / trace 可包含 not_applicable_attribution；稳定 API 字段不变，前端仍不能依赖 debug。

### 是否新增或修改错误类型

是。新增 `CAPABILITY_GAP`，用于 answerable capability gap 的标准错误归因。

### 是否新增或修改运行追踪逻辑

是。RunTrace、debug 和 benchmark report 增加 Not Applicable 归因摘要；trace 仍不记录完整 Chain of Thought、raw reasoning tokens、API key 或敏感原始数据。

---

### 日期时间

2026-05-21 21:04 CST

### 本次目标

按用户要求执行方案 A 的 Git 清理，并处理上一条 CHANGELOG 遗留项：补齐 `null_check`、更多季度表达、fraud likelihood 多维比较、fee what-if candidate table、provider-native tool calling adapter；将 DABstep 100-130 与 Microsoft 脱敏数据 21-40 的结论加入 MAIN_GOAL 作为下一阶段能力闭环，并按通用能力族修复 DABstep hour-of-day 与中文零售 21-40 缺口，禁止按题号、标准答案或 proxy answer 优化。

### 修改文件

- MAIN_GOAL.md
- docs/ARCHITECTURE.md
- docs/FEATURE_BACKLOG.md
- docs/PHASE_GATES.md
- agent_runtime/README.md
- agent_runtime/provider_native_tool_adapter.py
- tests/agent_runtime/test_tool_calling_contracts.py
- data_agent_core/core/intent_parser.py
- data_agent_core/core/chinese_retail_intent.py
- data_agent_core/executors/pandas_executor.py
- data_agent_core/executors/sql_executor.py
- data_agent_core/executors/chinese_retail_executor.py
- data_agent_core/agent/single_agent.py
- agent_runtime/data_analysis_roles.py
- data_agent_core/llm/planner.py
- tests/core/test_generic_capability_operations.py
- tests/core/test_chinese_retail_capabilities.py
- CHANGELOG_AI.md

### 修改内容

- Git 方案 A 已执行：创建并推送 `backup/vds-dirty-before-dev-sync-20260521-1819` 备份分支，备份 commit 为 `351b752`；当前 feature 分支已 merge `origin/dev`，并用 `git cherry-pick -n 351b752` 恢复本地工作区，当前 feature 已不落后 `origin/dev`。
- 已解决上一条遗留的 `null_check`、季度/last quarter 更多表达、fraud likelihood 多维比较、fee what-if candidate table、provider-native OpenAI / DeepSeek 兼容 tool calling adapter 骨架；provider adapter 仍只映射 ToolCall 并通过 ToolDispatcher 执行，不实现核心算法。
- 将 DABstep 100-130 与 Microsoft 21-40 的基线结论写入 MAIN_GOAL，并同步 ARCHITECTURE、FEATURE_BACKLOG、PHASE_GATES。
- 新增通用 DABstep hour-of-day 能力：`top_count` 支持“哪个小时交易最多”，`top_outlier_group` 支持先按 Z-Score / IQR 识别 outlier 后再按小时或维度统计。
- 补齐 Microsoft 21-40 中文零售能力族：服务客户数、合约店占比、分销目标人数、目标达成率、今日分销排名、历史 SKU / 品类排名、拜访成功率、计划拜访记录数、陈列不合格记录数、冰柜客户数、订单状态枚举和路线品类贡献。
- 新增/扩展合成中英文测试，不使用 DABstep public proxy、Microsoft 标准答案或固定 task_id 作为测试 fixture。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_generic_capability_operations tests.core.test_chinese_retail_capabilities tests.agent_runtime.test_tool_calling_contracts
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- rg import-boundary scan for forbidden data_agent_core imports
- rg secret scan excluding outputs、storage、.env* 和 __pycache__
- rg source hardcoding scan for task_id equality、Microsoft task ids、expected answer/proxy answer leakage
- VDS_LLM_PROVIDER=mock ... Microsoft 脱敏数据 21-40 离线 scorer 回归
- source .env.local 后运行真实 LLM Microsoft 脱敏数据 21-40 离线 scorer 回归
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 31 --offset 99 --output-dir outputs/dabstep_all_100_130_mock_after_hour_group

### 测试结果

- targeted unittest 通过：Ran 33 tests，OK。
- full unittest 通过：Ran 60 tests in 10.638s，OK，skipped=1。
- compileall 通过。
- data_agent_core 禁止 import 边界扫描无命中。
- secret 扫描无命中，API key 未进入仓库文件。
- 源码 hardcoding 扫描无 task_id 等值判断、Microsoft task id、标准答案/proxy answer 泄漏命中。
- Microsoft 脱敏数据 21-40 mock 多 Agent 回归：20/20，accuracy=1.0，输出目录 `outputs/microsoft_anonymized_21_40_mock_after_retail_20260521_204756`。
- Microsoft 脱敏数据 21-40 真实 LLM 多 Agent 回归：20/20，accuracy=1.0，输出目录 `outputs/microsoft_anonymized_21_40_real_llm_after_retail_20260521_204819`。
- DABstep all 100-130 mock 多 Agent 回归：total=31，success_count=31，unexpected_not_applicable=0，accuracy=null，输出报告 `outputs/dabstep_all_100_130_mock_after_hour_group/all_100_to_130_report.json`；accuracy=null 是因为 public all answer 为空。

### 遗留问题

- 已解决：`null_check`、季度表达、fraud likelihood 多维比较、fee what-if candidate table、provider-native tool calling adapter 骨架、DABstep 100-130 hour-of-day capability_gap、Microsoft 21-40 中文零售能力缺口。
- 仍遗留：DABstep public all answer 为空，本地不能计算 all 100-130 official accuracy；public proxy 只能后验观察，不能进入核心链路。
- 仍遗留：更大范围 DABstep 131+、Microsoft 41+ 和更多中文真实数据未在本轮全部跑完，后续仍需按能力族继续验证。
- 仍遗留：真实 LLM 多 Agent 评测耗时较长，后续可优化 provider 调用次数和 stage 缓存，但不能牺牲 trace、Verifier 和受控工具边界。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端页面或复杂后端业务。

### 是否涉及 Benchmark

是。运行 DABstep 100-130 public split 执行覆盖、Microsoft 脱敏数据 21-40 离线 scorer 回归；标准答案只在离线 scorer 使用，未传入 Agent workflow、prompt、Planner、Executor、Verifier、Correction、测试 fixture 或核心逻辑。

### 是否涉及 Microsoft Agent Framework

否。未安装 Microsoft Agent Framework，未新增核心依赖；现有 Microsoft adapter 仍只是可选适配层边界。

### 是否影响未来多 Agent 迁移

是，正向影响。新增能力通过 LogicForm、受控 Executor、ToolDispatcher 和 multi_agent workflow 复用；核心算法仍不依赖 Microsoft adapter 或 multi_agent_workflows。

### 是否修改核心数据契约

否。未修改 contracts dataclass 稳定字段；新增的是 operation 能力族和 provider-native adapter 骨架测试。

### 是否修改 API 契约

否。稳定 API 字段未变化；文档仅同步下一阶段能力闭环和回归结论。

### 是否新增或修改错误类型

否。本轮未新增错误类型；沿用既有 CAPABILITY_GAP 和执行错误体系。

### 是否新增或修改运行追踪逻辑

否。本轮未新增 trace 字段；使用既有 reasoning_trace、tool trace 和 benchmark report 摘要，不记录完整 Chain of Thought、raw reasoning tokens、API key 或敏感原始数据。

---

### 日期时间

2026-05-22 00:46 CST

### 本次目标

按用户要求核查“上一轮遗留问题是否已处理”和“MAIN_GOAL 是否还有陈旧待做项”，把已解决项写成已解决，把真实未完成项保留为遗留；同时补齐本轮审计发现的最小治理缺口：工具 timeout 执行边界、tracked-file secret scan、扩大 Benchmark 硬编码扫描范围，以及 benchmark report 顶层执行统计。

### 修改文件

- MAIN_GOAL.md
- README.md
- docs/API_CONTRACT.md
- docs/ARCHITECTURE.md
- docs/DATASET_LIFECYCLE.md
- docs/FEATURE_BACKLOG.md
- docs/PHASE_GATES.md
- docs/SECURITY_BOUNDARIES.md
- agent_runtime/tool_dispatcher.py
- data_agent_core/benchmark/benchmark_runner.py
- tests/agent_runtime/test_tool_calling_contracts.py
- tests/architecture/test_no_benchmark_hardcoding.py
- tests/architecture/test_no_secrets.py
- CHANGELOG_AI.md

### 修改内容

- 将 MAIN_GOAL 当前阶段从“未来支持/待搭建”改为“已完成基线/继续增强”，明确 CSV / Excel、Pandas、SQL fallback、Benchmark Runner、最小 API、Phase 5 工具层和 Phase 6 多 Agent 已有可测基线。
- 将 Phase 6 TODO 改为完成状态与真实遗留项：已完成 Not Applicable 第一/二批能力、DABstep hour-of-day、Microsoft 21-40 中文零售、trace/debug 证据和治理测试；仍遗留 ACI associated cost、DuckDB runtime、真实 provider 网络 tool loop、复杂并行/多轮自纠、DABstep 131+、Microsoft 41+ 和更多中文真实数据验证。
- 明确 provider-native adapter 当前是 OpenAI / DeepSeek 兼容 schema、tool call 解析和 mock/fake client loop，不宣称生产真实 provider tool loop 已完成。
- ToolDispatcher 根据 ToolDefinition.timeout_seconds 增加 POSIX timeout 执行边界，超时失败进入标准 ToolResult.errors 和 trace_event.error。
- Benchmark report 顶层新增 success_count、unexpected_not_applicable、true_unsupported、not_applicable_counts，避免只在 metrics 子节点中查看执行覆盖。
- 架构测试新增 tracked-file secret scan，确认真实 key 不进入 Git tracked files；扩大 Benchmark 硬编码扫描到 agent_runtime、backend、ms_agent_framework_adapter 和 multi_agent_workflows 核心源码范围。
- 同步 API、Architecture、Dataset Lifecycle、Security Boundaries、Feature Backlog、Phase Gates 和 README 的阶段状态，移除“后端 API 仍未实现”“仅预留工具 trace”等陈旧表述。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.agent_runtime.test_tool_calling_contracts tests.architecture.test_no_benchmark_hardcoding tests.architecture.test_no_secrets
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- rg import-boundary scan for forbidden data_agent_core imports
- rg --pcre2 secret scan excluding outputs、storage、.env* 和 __pycache__
- rg source hardcoding scan excluding benchmark runner scoring wrapper
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/main_goal_sync_dev10_20260522_0040

### 测试结果

- targeted unittest 通过：Ran 9 tests，OK。
- full unittest 通过：Ran 62 tests in 11.705s，OK，skipped=1。
- compileall 通过。
- data_agent_core 禁止 import 边界扫描无命中。
- secret 扫描无命中，tracked-file secret scan 已纳入 unittest。
- 源码 hardcoding 扫描无 task_id 等值判断、expected_answer、standard_answer、hidden_answer、proxy answer、accepted answer 或 public proxy 泄漏命中。
- DABstep dev 1-10 mock 多 Agent 回归：total=10，scored=10，correct=9，accuracy=0.9，success_count=10，unexpected_not_applicable=0，true_unsupported=1；输出目录 `outputs/main_goal_sync_dev10_20260522_0040`。

### 遗留问题

- 已解决：上一轮列出的 `null_check`、季度表达、fraud likelihood 多维比较、fee what-if candidate table、provider-native adapter 骨架、DABstep 100-130 hour-of-day capability_gap、Microsoft 21-40 中文零售能力缺口，仍按已解决记录。
- 已解决：本轮发现的 secret scan 无测试入口、hardcoding scan 范围偏窄、ToolDispatcher 只有 timeout metadata 无执行边界、benchmark report 顶层缺少 success_count / unexpected_not_applicable 的问题。
- 仍遗留：ACI associated cost / best_fraud_aci_choice 费用口径需继续按通用 fee what-if candidate table 和 associated cost 语义增强，禁止按 DABstep dev 单题特判。
- 仍遗留：DuckDB runtime 尚未生产化，当前 SQL 路径仍以 sqlite fallback / SQL-compatible operation 为主。
- 仍遗留：真实 OpenAI / DeepSeek provider-native 网络 tool loop 尚未作为生产默认链路启用；当前是兼容 schema、解析和 mock/fake client loop。
- 仍遗留：DABstep public all answer 为空，本地不能计算 all split official accuracy；public proxy 只能后验观察，不能进入核心链路。
- 仍遗留：DABstep 131+、Microsoft 41+ 和更多中文真实数据未完成大范围验证。
- 仍遗留：当前多 Agent 是内部顺序 workflow，复杂并行 executor、真实 Microsoft cloud workflow 和多轮代码级自纠仍属后续增强。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端页面或复杂后端业务。

### 是否涉及 Benchmark

是。修改 benchmark report 汇总字段并运行 DABstep dev 1-10 mock 多 Agent 回归；标准答案只用于离线 scorer，未传入 Agent workflow、prompt、Planner、Executor、Verifier、Correction 或核心逻辑。

### 是否涉及 Microsoft Agent Framework

是，但仅涉及文档边界和硬编码扫描覆盖范围。未安装 Microsoft Agent Framework，未新增核心依赖，未让 data_agent_core 依赖 adapter。

### 是否影响未来多 Agent 迁移

是，正向影响。工具 timeout、secret scan、扩大硬编码扫描和文档状态同步强化了多 Agent / provider adapter 的受控边界；核心算法仍保持框架无关。

### 是否修改核心数据契约

否。未修改 contracts dataclass 稳定字段。

### 是否修改 API 契约

是。docs/API_CONTRACT.md 同步当前最小 API 已实现和 tool_call_summaries 当前可用状态；稳定 API 字段未变化。

### 是否新增或修改错误类型

否。未新增错误类型；ToolDispatcher 超时沿用 TOOL_DISPATCH_ERROR 标准结构。

### 是否新增或修改运行追踪逻辑

是。ToolDispatcher timeout 失败会进入 ToolResult.errors 和 trace_event.error；benchmark report 顶层新增执行覆盖/Not Applicable 归因汇总字段。未新增完整 Chain of Thought、raw reasoning tokens、API key 或敏感原始数据。

---

### 日期时间

2026-05-22 03:38 CST

### 本次目标

继续按 MAIN_GOAL Phase 6+ 自省自救：补齐 DABstep public all、Microsoft 脱敏数据和桌面 VDS 中文 BI 暴露的通用能力缺口，更新当前阶段文档状态，并用全量 mock 回归确认能力覆盖；禁止按题号、标准答案、proxy answer、固定字段值或固定输出优化。

### 修改文件

- MAIN_GOAL.md
- docs/ARCHITECTURE.md
- docs/FEATURE_BACKLOG.md
- docs/PHASE_GATES.md
- agent_runtime/data_analysis_roles.py
- data_agent_core/agent/single_agent.py
- data_agent_core/core/chinese_retail_intent.py
- data_agent_core/core/dabstep_fee_engine.py
- data_agent_core/core/intent_parser.py
- data_agent_core/core/vds_bi_intent.py
- data_agent_core/executors/chinese_retail_executor.py
- data_agent_core/executors/pandas_executor.py
- data_agent_core/executors/sql_executor.py
- data_agent_core/executors/vds_bi_executor.py
- data_agent_core/llm/planner.py
- multi_agent_workflows/microsoft_anonymized_benchmark_runner.py
- tests/architecture/test_no_benchmark_hardcoding.py
- tests/core/test_chinese_retail_capabilities.py
- tests/core/test_generic_capability_operations.py
- tests/core/test_vds_bi_capabilities.py
- CHANGELOG_AI.md

### 修改内容

- 修复 DABstep `metric_per_distinct_entity` 通用能力：区分“平均交易金额 / unique entity”和“平均交易次数 / unique entity”，避免把 shopper/email 误当指标列；Pandas 与 SQL 路径保持一致。
- 修复中文零售 `retail_distribution_sum` 在过滤后无数据时的 `Not Applicable` 归因，明确标为 `true_unsupported`，使正确不可回答场景不再被误算为 capability_gap。
- 新增 VDS 中文 BI 周期比较能力族：周环比排名变化、增减 TopN、增长数量占比、环比阈值计数、城市/区域等维度环比增长率、当前期阈值 Top 和同圈层异常，覆盖门店、校区、院区、站点、客户等实体。
- 新增 Microsoft 脱敏数据离线 runner，标准答案只在 response 生成后用于 scorer，不进入 Agent workflow、prompt、Planner、Executor、Verifier、Correction 或 trace。
- 更新文档状态：DABstep public all 1-450 mock 执行覆盖为 450/450；Microsoft 脱敏数据 1-300 mock 离线 scorer 为 300/300；桌面 VDS `问题汇总.xlsx` 五个真实问题 sheet 共 95 题 smoke 为 95/95。
- 修正文档中 “VDS 五域前 20 smoke 为 95/95” 的不准确表述，明确排除 `缩写口径说明` 说明页。
- 扩大 Benchmark 硬编码扫描范围，继续防止 task_id、expected answer、proxy answer、accepted answer 泄漏到核心源码或测试 fixture。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_generic_capability_operations tests.core.test_chinese_retail_capabilities tests.core.test_vds_bi_capabilities
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- rg import-boundary scan for forbidden data_agent_core imports
- rg secret scan excluding outputs、storage、.env* 和 __pycache__
- rg source hardcoding scan for task_id equality、expected_answer、proxy answer、public proxy、accepted answer、known dev answer strings
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/dev10_current_gap_check_20260522
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 450 --offset 0 --output-dir outputs/dabstep_all_1_450_mock_current_verify_20260522
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.microsoft_anonymized_benchmark_runner --dataset-root /Users/trevorcui/Desktop/微软脱敏数据 --limit 300 --offset 0 --output-dir outputs/microsoft_anonymized_1_300_mock_current_verify_20260522
- VDS_LLM_PROVIDER=mock inline runner for `/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/问题/问题汇总.xlsx` excluding `缩写口径说明`, output `outputs/vds_desktop_question_summary_95_mock_current_verify_20260522.json`

### 测试结果

- Targeted capability unittest 通过：Ran 52 tests，OK。
- Full unittest 通过：Ran 86 tests in 10.898s，OK，skipped=1。
- compileall 通过。
- data_agent_core 禁止 import 边界扫描无违规 import；唯一命中为 duckdb_runtime docstring 中的 backend routers 说明。
- secret 扫描无命中，API key 未进入仓库文件。
- hardcoding 扫描无 task_id 等值判断、标准答案、proxy answer 或 dev 2697 答案字符串进入核心源码；唯一命中为测试文件自身的禁止词清单。
- DABstep dev 1-10 mock 多 Agent 回归：total=10，correct=9，accuracy=0.9，success_count=10；剩余失败仍为 `best_fraud_aci_choice` associated cost 语义口径。
- DABstep public all 1-450 mock 多 Agent 回归：total=450，success_count=450，unexpected_not_applicable=0，true_unsupported=3，failure_count=0，accuracy=null；accuracy 为 null 是因为 public all answer 为空。
- Microsoft 脱敏数据 1-300 mock 离线 scorer：total=300，correct=300，accuracy=1.0，success_count=300，输出 `outputs/microsoft_anonymized_1_300_mock_current_verify_20260522/report.json`。
- 桌面 VDS `问题汇总.xlsx` 五个真实问题 sheet 共 95 题 mock smoke：success_count=95，failure_count=0，输出 `outputs/vds_desktop_question_summary_95_mock_current_verify_20260522.json`。

### 遗留问题

- 已解决：上一条记录中“更大范围 DABstep 131+、Microsoft 41+ 和更多中文真实数据未全部跑完”的阶段性验证缺口，本轮已扩展到 DABstep public all 1-450、Microsoft 脱敏数据 1-300 和桌面 VDS 95 题 smoke。
- 已解决：DABstep public all 的 `metric_per_distinct_entity` 执行失败缺口。
- 已解决：Microsoft 1-300 中正确 `Not Applicable` 被算作 capability_gap 的成功状态缺口。
- 仍遗留：DABstep dev 1-10 中 `best_fraud_aci_choice` / ACI associated cost 仍为 1 个公开 dev 失败；当前不能为了 dev 单题或已知答案写特调，必须继续按通用 fee what-if candidate table 和 associated cost 语义建模。
- 仍遗留：DABstep public all answer 为空，本地不能计算 hidden full benchmark official accuracy。
- 仍遗留：真实 OpenAI / DeepSeek provider-native 网络 tool loop、DuckDB runtime、复杂并行/多轮自纠、真实 Microsoft cloud workflow 和更多复杂中文 BI 问法仍需按能力族推进。

### 是否影响主流程

否。未修改旧 BigCat / VDS 主流程，未修改前端页面、复杂后端业务、权限、登录、部署或数据库持久化。

### 是否涉及 Benchmark

是。运行 DABstep dev 1-10、DABstep public all 1-450、Microsoft 脱敏数据 1-300 和桌面 VDS 问题 smoke 作为后验回归；标准答案只用于 dev/Microsoft 离线 scorer，未进入 Agent workflow、prompt、Planner、Executor、Verifier、Correction、测试 fixture 或核心逻辑。

### 是否涉及 Microsoft Agent Framework

否。未安装 Microsoft Agent Framework，未新增核心依赖；保持既有 adapter 可选边界。

### 是否影响未来多 Agent 迁移

是，正向影响。新增能力通过 LogicForm、受控 Executor、agent_runtime operation allowlist 和 multi_agent workflow 复用；data_agent_core 仍不依赖 multi_agent_workflows 或 Microsoft adapter。

### 是否修改核心数据契约

否。未修改 contracts dataclass 稳定字段；新增的是通用 operation 能力族、runner 和测试。

### 是否修改 API 契约

否。稳定 API 字段未变化；文档仅同步阶段状态和回归口径。

### 是否新增或修改错误类型

否。沿用既有错误体系和 `CAPABILITY_GAP` / `true_unsupported` 归因。

### 是否新增或修改运行追踪逻辑

否。使用既有 reasoning_trace、tool trace、candidate_table_summary 和 benchmark report 摘要，不记录完整 Chain of Thought、raw reasoning tokens、API key 或敏感原始数据。

---

### 日期时间

2026-05-22 06:28 CST

### 本次目标

修复项目治理文档可读性问题：将 CHANGELOG_AI.md 的真实修改记录按时间顺序重排，并同步 README / docs 中过期的 Phase Status，避免后续判断阶段状态时被旧的 DABstep / Microsoft / VDS 回归口径误导。

### 修改文件

- CHANGELOG_AI.md
- README.md
- data_agent_core/README.md
- agent_runtime/README.md
- multi_agent_workflows/README.md
- ms_agent_framework_adapter/README.md
- MAIN_GOAL.md
- docs/PHASE_GATES.md
- docs/FEATURE_BACKLOG.md
- docs/BENCHMARK_RULES.md

### 修改内容

- 将 CHANGELOG_AI.md 中 26 条真实记录按真实日期/时间升序重排；保留顶部模板，不把模板中的 `YYYY-MM-DD HH:MM TZ` 当成真实记录。
- 不修改历史记录内容，不补写不存在的历史，不编造历史时间；仅调整记录顺序和分隔符。
- 同步根 README 的 Phase Status、核心测试命令和当前 verified 状态。
- 同步 data_agent_core、agent_runtime、multi_agent_workflows、ms_agent_framework_adapter 的 Phase Status，明确当前是 Phase 6 内部多 Agent 默认链路，Microsoft adapter 仍只是可选承载层。
- 同步 MAIN_GOAL、PHASE_GATES、FEATURE_BACKLOG 和 BENCHMARK_RULES 中过期的 “all 前 50 / 前 10 / 尚未覆盖完整 450” 表述。
- 明确当前 verified 状态：DABstep public all 1-450 mock 执行覆盖 450/450，Microsoft 脱敏数据 1-300 mock 离线 scorer 300/300，桌面 VDS `问题汇总.xlsx` 五个真实问题 sheet 共 95 题 smoke 95/95。

### 测试方式

- 使用脚本检查 CHANGELOG_AI.md 真实记录时间顺序。
- rg stale status scan：检查 README / docs 中是否仍存在 `尚未覆盖完整 450`、`DABstep 本地前 10`、旧 `data_agent_core.benchmark.benchmark_runner` 命令、`all 前 50`、`前 20 smoke`、`Microsoft 41+`、`DABstep 181+` 等过期表述。
- git diff --check

### 测试结果

- CHANGELOG_AI.md 真实记录数量为 26，时间顺序检查通过：first=2026-05-21，last=2026-05-22 06:28 CST。
- stale status scan 无命中。
- git diff --check 通过。

### 遗留问题

- 本轮仅修复治理文档顺序和 Phase Status；未修复 ACI associated cost / best_fraud_aci_choice 语义缺口。
- 后续新增 CHANGELOG 记录仍必须追加到底部，并保持时间递增；如果以后需要整理历史，只允许按真实时间排序，不能改写历史内容。

### 是否影响主流程

否。仅文档治理修改，不影响旧 BigCat / VDS 主流程，不修改前端、后端业务或核心执行逻辑。

### 是否涉及 Benchmark

是，仅同步 Benchmark 回归状态和命令说明；未修改 Benchmark 数据，未读取 hidden answer，未将标准答案、task_id 或 proxy answer 写入核心链路。

### 是否涉及 Microsoft Agent Framework

是，仅同步 README 中的 adapter 状态说明；未安装 Microsoft Agent Framework，未新增依赖，未把核心算法写入 adapter。

### 是否影响未来多 Agent 迁移

是，正向影响。README / docs 现在更清楚地区分内部 Phase 6 workflow 与 Microsoft adapter 可选承载层，降低未来误把核心算法绑到框架里的风险。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

---

### 日期时间

2026-05-22 09:42 CST

### 本次目标

回应 GitHub README 首屏只显示 Phase 6、无法体现后续大量推进内容的问题，把根 README 调整为 Phase 6+ 当前增强状态，并明确详细阶段记录分布在 MAIN_GOAL、CHANGELOG_AI 和 docs 中。

### 修改文件

- README.md
- CHANGELOG_AI.md

### 修改内容

- 将 README 首段从“推进到 Phase 6 最小可运行多 Agent workflow”扩展为“Phase 6+ 增强阶段”。
- 在 README 首屏新增最新状态速览，直接展示 DABstep public all 1-450 执行覆盖 450/450、Microsoft 脱敏数据 1-300 离线 scorer 300/300、桌面 VDS 95 题 smoke 95/95，以及当前真实遗留的 ACI associated cost 语义口径问题。
- 在 README 中明确 `MAIN_GOAL.md`、`CHANGELOG_AI.md`、`docs/ARCHITECTURE.md`、`docs/PHASE_GATES.md`、`docs/BENCHMARK_RULES.md` 分别承载的详细内容，避免误以为 GitHub 首页没有展示就代表内容丢失。
- 将 Phase Status 中 Phase 6 改为 Phase 6+，补充当前增强重点。

### 测试方式

- git diff --check

### 测试结果

- git diff --check 通过。

### 遗留问题

- 本轮仅修复 README 展示层和治理记录，不修改核心算法。
- GitHub 默认页只展示根 README 的摘要，完整进展仍以 MAIN_GOAL、CHANGELOG_AI 和 docs 为主。

### 是否影响主流程

否。仅文档修改，不影响旧 BigCat / VDS 主流程，不修改前端、后端业务或核心执行逻辑。

### 是否涉及 Benchmark

是，仅同步 README 中的 Benchmark 回归状态；未修改 Benchmark 数据，未读取 hidden answer，未将标准答案、task_id 或 proxy answer 写入核心链路。

### 是否涉及 Microsoft Agent Framework

否。未安装 Microsoft Agent Framework，未新增依赖，未把核心算法写入 adapter。

### 是否影响未来多 Agent 迁移

是，正向影响。README 更清楚地区分当前内部 Phase 6+ 多 Agent 默认链路和后续 provider / Microsoft 承载层增强。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

---

### 日期时间

2026-05-22 09:54 CST

### 本次目标

按用户最新要求保留 Phase 7 大阶段口径，并把下一阶段规范化为 Phase 7.1：DABstep Submission Quality Gate and Easy Capability Closure；本轮只做阶段治理、状态统一和下一阶段定义，不实现新算法。

### 修改文件

- README.md
- MAIN_GOAL.md
- docs/PHASE_GATES.md
- docs/FEATURE_BACKLOG.md
- docs/ARCHITECTURE.md
- data_agent_core/README.md
- agent_runtime/README.md
- multi_agent_workflows/README.md
- ms_agent_framework_adapter/README.md
- CHANGELOG_AI.md

### 修改内容

- 将根 README 当前阶段改为 Phase 7：泛化验证与 Provider 原生工具链增强。
- 将 Phase 6 定义收敛为“最小多 Agent workflow 基线已完成”，把 DABstep 450/450、Microsoft 300/300、VDS 95/95、Not Applicable 能力闭环、中文 BI 能力族、provider-native tool loop、DuckDB runtime、复杂并行和多轮自纠统一归入 Phase 7。
- 在 MAIN_GOAL 中新增统一 Phase 状态表，明确 Phase 0 到 Phase 7 的已完成/当前状态，并把 Phase 7.1 写为下一阶段子目标。
- 在 MAIN_GOAL、PHASE_GATES、FEATURE_BACKLOG 和 README 中新增 Phase 7.1 的进入条件、退出条件、submission gate、Easy 能力族、leaderboard 反馈边界和禁止按题优化红线。
- 明确 Trevor 提交 Easy 低、Hard 高是外部提交反馈，不能写成本地可复现 hidden official accuracy；hidden official accuracy 只能由 Hugging Face leaderboard 返回。
- 明确 submission 文件必须绑定当前 commit hash、report hash、prediction hash 和生成命令。
- 同步 FEATURE_BACKLOG、ARCHITECTURE 和各模块 README 的阶段口径。

### 测试方式

- rg -n "Phase 6\\.1|Phase 6\\+" MAIN_GOAL.md README.md docs/PHASE_GATES.md docs/FEATURE_BACKLOG.md data_agent_core/README.md agent_runtime/README.md ms_agent_framework_adapter/README.md multi_agent_workflows/README.md docs/ARCHITECTURE.md
- rg -n "Phase 7\\.1|Submission Quality Gate|Easy Capability|leaderboard|current_verify" MAIN_GOAL.md docs/PHASE_GATES.md docs/FEATURE_BACKLOG.md README.md
- rg -n "Phase 7|Phase Status" MAIN_GOAL.md docs/PHASE_GATES.md docs/FEATURE_BACKLOG.md README.md
- rg secret scan excluding outputs、storage、.env* 和 __pycache__
- rg -n "hidden answer|expected answer|proxy answer|public proxy|task_id|固定题面|固定样本值" MAIN_GOAL.md docs/PHASE_GATES.md docs/FEATURE_BACKLOG.md README.md
- git diff --check
- git status --short --branch

### 测试结果

- current-doc `Phase 6.1` / `Phase 6+` scan 无命中；本轮按用户最新要求使用 Phase 7 / Phase 7.1。
- Phase 7.1 / Submission Quality Gate / Easy Capability / leaderboard / current_verify scan 有预期命中，集中在 MAIN_GOAL、PHASE_GATES、FEATURE_BACKLOG 和 README。
- Phase 7 / Phase Status scan 有预期命中，四份主文档口径一致。
- secret scan 无命中，未新增真实 API key。
- hidden answer / expected answer / proxy answer / public proxy / task_id 等扫描仅命中文档红线和禁止项描述，未新增允许进入核心链路的表述。
- git diff --check 通过。
- git status 显示当前分支为 feature/project-rules-and-data-agent-skeleton，存在本轮文档改动和未跟踪 `.playwright-cli/`，未提交、未推送。

### 遗留问题

- 本轮仅整理文档阶段口径，不修改核心算法、submission gate 代码或 benchmark scoring 链路。
- 本轮未提交、未推送、未开 PR、未合并 main；当前只是本地工作区改动。

### 是否影响主流程

否。仅文档修改，不影响旧 BigCat / VDS 主流程，不修改前端、后端业务或核心执行逻辑。

### 是否涉及 Benchmark

是，仅整理 Benchmark 回归结果所属阶段，并新增 DABstep submission gate / Easy 能力族下一阶段定义；未修改 Benchmark 数据、runner、scorer 或核心分析链路，未读取 hidden answer，未将标准答案、task_id 或 proxy answer 写入核心链路。

### 是否涉及 Microsoft Agent Framework

是，仅整理 adapter 和未来 demo 所属阶段；未安装 Microsoft Agent Framework，未新增依赖，未把核心算法写入 adapter。

### 是否影响未来多 Agent 迁移

是，正向影响。Phase 6 只表示已完成的内部多 Agent 基线；Phase 7 承载后续 provider、framework、并行和泛化验证增强；Phase 7.1 作为 Phase 7 下的 submission / Easy 能力子阶段，不改变核心算法位置。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

---

### 日期时间

2026-05-22 10:17 CST

### 本次目标

按用户要求把 Phase 7.2 写入 MAIN_GOAL，明确下一阶段以 Agent 泛化能力为主，Pandas / SQL / DuckDB 语义统一只作为执行层可信度、可审计性和回归判断支撑；不打断既有 Phase 7.1 submission gate。

### 修改文件

- MAIN_GOAL.md
- CHANGELOG_AI.md

### 修改内容

- 在 MAIN_GOAL 当前阶段目标和统一 Phase 状态表中追加 Phase 7.2：Agent Generalization and Executor Semantic Parity。
- 在 Phase 7 当前遗留项中补充 Pandas / SQL 当前差异主要是 coverage gap，不是 SQL correctness gap；同时记录更深层风险是 Agent 能力族抽象、Planner 泛化字段和 Verifier 语义验收仍需增强。
- 在 Phase 7.1 后新增 Phase 7.2 章节，明确能力族优先、Planner 泛化契约、Verifier 语义验收、Capability Registry、Executor parity 支撑指标和 DuckDB runtime 边界。
- 明确 public proxy 只能后验观察，task_id、expected answer、proxy answer、accepted answer 和 hidden answer 不得进入 Capability Registry、Planner、Executor、Verifier、Correction、prompt 或测试 fixture。

### 测试方式

- rg -n "Phase 7\\.2|Agent Generalization|Executor Semantic Parity|Capability Registry|coverage gap|semantic mismatch|shared rule engine" MAIN_GOAL.md CHANGELOG_AI.md
- git diff --check
- git status --short --branch

### 测试结果

- Phase 7.2 / Agent Generalization / Executor Semantic Parity / Capability Registry / coverage gap / semantic mismatch / shared rule engine scan 有预期命中，集中在 MAIN_GOAL 和本条 CHANGELOG。
- git diff --check 通过。
- git status 显示当前分支为 feature/project-rules-and-data-agent-skeleton，存在本轮文档改动、此前已有文档改动和未跟踪 `.playwright-cli/`，未提交、未推送。

### 遗留问题

- 本轮仅做文档目标追加，不修改 executor、benchmark runner、Capability Registry 代码或 DuckDB runtime。
- Phase 7.2 仍需后续实际实现 Capability Registry、Planner 泛化契约、Verifier 语义验收和 benchmark report 指标拆分。

### 是否影响主流程

否。仅文档修改，不影响旧 BigCat / VDS 主流程，不修改前端、后端业务或核心执行逻辑。

### 是否涉及 Benchmark

是，仅新增下一阶段 Benchmark 报告口径和泛化验收目标；未修改 Benchmark 数据、runner、scorer 或核心分析链路，未读取 hidden answer，未将标准答案、task_id 或 proxy answer 写入核心链路。

### 是否涉及 Microsoft Agent Framework

否。未安装 Microsoft Agent Framework，未新增依赖，未把核心算法写入 adapter。

### 是否影响未来多 Agent 迁移

是，正向影响。Phase 7.2 明确 Planner、Verifier、Executor parity 和 Capability Registry 的边界，使后续多 Agent 能力增强以泛化能力和稳定契约为中心，而不是单纯补 SQL 或按题优化。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

---

### 日期时间

2026-05-22 10:38 CST

### 本次目标

按用户确认的方案在 MAIN_GOAL 中追加 Phase 7.3：Evaluation-Driven Robustness and Output Contract Hardening，作为 Phase 7.2 之后的下一阶段；本轮只做文档增量，不改代码、不重排历史段落、不清理其他人的 dirty worktree。

### 修改文件

- MAIN_GOAL.md
- CHANGELOG_AI.md

### 修改内容

- 在 MAIN_GOAL 当前阶段目标中追加 Phase 7.3，明确聚焦最终 Output Contract、validation-driven retry、submission provenance、真实 provider 回归和 DA-agent 可借鉴工程模式。
- 在统一 Phase 状态表中追加 Phase 7.3，明确它不替代 Phase 7.1 submission gate，也不重做 Phase 7.2 Capability Registry。
- 在 Phase 7 当前遗留项中新增统一风险报告缺口，要求拆分 format risk、semantic risk、capability coverage、official hidden score 不可本地复现、public proxy observation、真实 provider cost / latency 和 submission provenance。
- 在 Phase 7.2 后新增 Phase 7.3 章节，记录可借鉴 DA-agent 的 schema / rule-first、DuckDB runtime materialization、read-only SQL guardrail、validation-driven retry、final answer only 和 deterministic rule engine 模式。
- 明确不借鉴 task_id 进 prompt、raw SQL 自由执行、任意文件读取、用 public proxy / leaderboard 反推答案、SQL-first benchmark 产品定位等模式。

### 测试方式

- rg -n "Phase 7\\.3|Evaluation-Driven Robustness|Output Contract|validation-driven|DA-agent|DuckDB|provenance|official hidden|public proxy" MAIN_GOAL.md CHANGELOG_AI.md
- git diff --check
- git diff -- MAIN_GOAL.md CHANGELOG_AI.md
- git status --short --branch

### 测试结果

- Phase 7.3 / Evaluation-Driven Robustness / Output Contract / validation-driven / DA-agent / DuckDB / provenance / official hidden / public proxy scan 有预期命中，集中在 MAIN_GOAL 和本条 CHANGELOG。
- git diff --check 通过。
- git diff -- MAIN_GOAL.md CHANGELOG_AI.md 已人工检查，仅包含本轮文档追加和既有未提交文档上下文。
- git status 显示当前分支为 feature/project-rules-and-data-agent-skeleton，工作区仍有大量既有未提交改动和未跟踪文件；本轮未 stage、未提交、未推送。
- 本轮是文档-only 变更，未运行 Python 单测。

### 遗留问题

- Phase 7.3 只是下一阶段目标记录；最终答案 canonicalizer、output validator、validation-driven retry loop、submission provenance、真实 provider 分段回归和风险 taxonomy 仍待后续实现。
- official hidden score 仍只能由 leaderboard 返回，本地 public all answer 为空，public proxy 只能后验观察，不能进入核心分析链路。

### 是否影响主流程

否。仅文档修改，不影响旧 BigCat / VDS 主流程，不修改前端、后端业务或核心执行逻辑。

### 是否涉及 Benchmark

是，仅新增下一阶段 Benchmark 输出契约、提交治理和风险报告目标；未修改 Benchmark 数据、runner、scorer 或核心分析链路，未读取 hidden answer，未将标准答案、task_id 或 proxy answer 写入核心链路。

### 是否涉及 Microsoft Agent Framework

否。未安装 Microsoft Agent Framework，未新增依赖，未把核心算法写入 adapter。

### 是否影响未来多 Agent 迁移

是，正向影响。Phase 7.3 把 Phase 7.1 submission gate 和 Phase 7.2 能力族 / Planner / Verifier 契约串成真实 provider、最终输出和提交 provenance 可验证的闭环，不改变核心算法位置。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

---

### 日期时间

2026-05-22 10:56 CST

### 本次目标

按 Phase 7.2 计划落地第一批代码实现：以 Agent 泛化能力为主线，新增 Capability Registry，并把 SQL/Pandas/DuckDB parity 改成执行层报告与验证指标，不把 SQL skipped 误算为 SQL correctness failure。

### 修改文件

- MAIN_GOAL.md
- CHANGELOG_AI.md
- data_agent_core/core/capability_registry.py
- data_agent_core/executors/sql_executor.py
- data_agent_core/agent/single_agent.py
- agent_runtime/data_analysis_roles.py
- multi_agent_workflows/end_to_end_data_analysis_workflow.py
- data_agent_core/benchmark/benchmark_runner.py
- data_agent_core/benchmark/metrics.py
- tests/core/test_capability_registry.py
- tests/benchmark/test_benchmark_metrics.py

### 修改内容

- 新增 `CapabilityMetadata` / Capability Registry，记录 operation、capability_family、input/output contract、Pandas 支持、SQL support、中文/英文支持、shared rule engine 依赖和适用边界。
- 将 fee-rule what-if 能力标记为 `shared_rule_engine`，短期继续共享 deterministic rule engine，不在 Pandas、SQL、Verifier 中复制三套业务逻辑。
- 多 Agent runtime 和 single_agent 的 SQL gate 改为读取 Capability Registry；SQL skipped payload 和 trace summary 输出 `sql_support`、`capability_family`、`coverage_gap`、`native_sql_supported` 和 reason。
- Benchmark detail / metrics 新增 `sql_coverage`、`sql_covered_subset_accuracy`、`pandas_sql_consistency`、`gap_counts`、`capability_family_metrics`，并拆分 coverage gap、semantic mismatch、executor mismatch、format mismatch。
- single_agent verifier 改为传入 plan 和 user_question，使业务口径语义校验与多 Agent 链路保持一致。
- 更新 MAIN_GOAL 当前实现状态，记录 Phase 7.2 首个代码落点和本轮回归输出。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.benchmark.test_benchmark_metrics tests.core.test_capability_registry tests.core.test_generic_capability_operations
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.agent_runtime.test_runtime_contracts tests.agent_runtime.test_data_agent_tool_impl tests.multi_agent_workflows.test_phase6_multi_agent_workflow tests.architecture.test_dependency_boundaries
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- git diff --check
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/phase72_capability_registry_dev_1_10_20260522
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 450 --offset 0 --output-dir outputs/phase72_capability_registry_dabstep_all_1_450_20260522
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.microsoft_anonymized_benchmark_runner --dataset-root /Users/trevorcui/Desktop/微软脱敏数据 --limit 300 --offset 0 --output-dir outputs/phase72_capability_registry_microsoft_1_300_20260522
- VDS_LLM_PROVIDER=mock inline runner for `/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/问题/问题汇总.xlsx` using `BI测试问题`, output `outputs/phase72_capability_registry_vds_question_summary_95_20260522.json`

### 测试结果

- Targeted capability / metrics / generic SQL-Pandas tests 通过：Ran 42 tests，OK。
- Runtime / multi-agent / import-boundary focused tests 通过：Ran 9 tests，OK。
- Full unittest 通过：Ran 91 tests in 11.567s，OK。
- compileall 通过。
- git diff --check 通过。
- DABstep dev 1-10 mock 多 Agent 回归：total=10，correct=9，accuracy=0.9，success_count=10；metrics 显示 SQL coverage=3/10，Pandas-SQL consistency=3/3，coverage_gap=7，semantic_mismatch=1，executor_mismatch=0，format_mismatch=0。
- DABstep public all 1-450 mock 多 Agent 回归：total=450，success_count=450，unexpected_not_applicable=0，true_unsupported=3，failure_count=0，accuracy=null；metrics 显示 SQL covered=70/450，Pandas-SQL consistency=70/70，coverage_gap=380。
- Microsoft 脱敏数据 1-300 mock 离线 scorer：total=300，correct=300，accuracy=1.0，success_count=300。
- 桌面 VDS `问题汇总.xlsx` 五个真实问题 sheet 共 95 题 mock smoke：total=95，success_count=95，failure_count=0；本轮使用 `BI测试问题` 真问题列，不使用标准答案优化。

### 遗留问题

- Phase 7.2 仍未完成 Planner 泛化契约全量字段强制输出和 DuckDB 表格化 rule engine；本轮只完成 Capability Registry、SQL gate 统一、trace/report gap 指标拆分和基础语义校验接入。
- `sql_covered_subset_accuracy` 只有当 runner 提供独立 `sql_correct` 时才计算；当前主 benchmark runner 仍以最终 Pandas response scorer 为主，SQL 子集主要通过 Pandas-SQL consistency 和 coverage 指标报告。
- DABstep dev 1-10 仍为 9/10，剩余失败继续归入 `best_fraud_aci_choice` / business-rule what-if 语义口径问题，不能按题号或答案补丁处理。

### 是否影响主流程

是，影响 data_agent_core、agent_runtime、multi_agent_workflows 和 benchmark report；不修改前端，不新增外部依赖，不改变 Microsoft Agent Framework adapter 的核心边界。

### 是否涉及 Benchmark

是。Benchmark expected answer 仍只在 response 生成后用于 scorer；task_id、expected answer、proxy answer、accepted answer 和 hidden answer 未进入 Capability Registry、Planner、Executor、Verifier、Correction 或 prompt。

### 是否涉及 Microsoft Agent Framework

否。未安装 Microsoft Agent Framework，未新增 adapter 依赖，未把核心算法写入 adapter。

### 是否影响未来多 Agent 迁移

是，正向影响。Capability Registry 使能力族、executor support 和 benchmark gap 报告成为共享契约，后续 Planner / Verifier / DuckDB 增强可以围绕同一语义层推进。

### 是否修改核心数据契约

是，新增 registry metadata 契约，但未修改既有 API request/response dataclass 字段。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

是。SQL trace summary 新增 coverage / support / capability family 字段，便于区分 coverage gap、semantic mismatch 和 executor mismatch。

---

### 日期时间

2026-05-22 11:06 CST

### 本次目标

按用户确认的方案把上传表泛化断层归入 Phase 7.2G，而不是新增 Phase 7.4；本轮只做文档/验收计划最小追加，不改 Phase 7.3 的 Output Contract / retry / provenance 方向，也不修改正在推进的 Phase 7.2 代码实现。

### 修改文件

- MAIN_GOAL.md
- CHANGELOG_AI.md

### 修改内容

- 在 MAIN_GOAL 的 Phase 7.2 下新增 `Phase 7.2G：Uploaded Table Generalization Gap Closure` 小节。
- 记录事实锚点：Microsoft 新增 100 为 `100/100`，easy `40/40`，hard `60/60`；原始五域新增 100 为 `58/100`，easy `18/40`，hard `40/60`。
- 明确 7.2G 归因到 Agent 泛化、字段角色绑定、Planner / Verifier 语义契约和 capability family 覆盖，不新增 Phase 7.4，不重写 Phase 7.3。
- 补充上传表泛化能力焦点：filter vs dimension、显式 metric、count vs sum、mode / top_count、Top-K metric share vs count share、筛选后排名和无效验收样本排除。
- 补充验收目标：原始五域新增 100 overall >= `85%`、easy >= `90%`、hard >= `80%`；Microsoft 新增 100 保持 >= `98%`；失败报告按 capability family 聚合。

### 测试方式

- rg -n "Phase 7\\.2G|Uploaded Table Generalization Gap Closure|原始五域新增 100|Microsoft 新增 100|58/100|100/100" MAIN_GOAL.md CHANGELOG_AI.md
- rg -n "^## Phase 7\\.4|^## Phase 7\\.3|^### Phase 7\\.2G" MAIN_GOAL.md
- git diff --check

### 测试结果

- Phase 7.2G / Uploaded Table Generalization / 原始五域新增 100 / Microsoft 新增 100 scan 有预期命中，集中在 MAIN_GOAL 和本条 CHANGELOG。
- Phase 标题 scan 显示 MAIN_GOAL 中新增的是 `### Phase 7.2G` 小节；未新增 `## Phase 7.4`，现有 `## Phase 7.3` 保持唯一。
- git diff --check 通过。

### 遗留问题

- 本轮只是文档/验收计划落地，不实现上传表泛化能力修复。
- 后续仍需在 Phase 7.2G 实现并复跑 Microsoft 新增 100、原始五域新增 100、DABstep dev 1-10、DABstep public all 1-450 mock、Microsoft 1-300 和桌面 VDS 95 smoke。

### 是否影响主流程

否。仅修改文档，不修改前端、后端、核心执行器、runtime 或 benchmark runner。

### 是否涉及 Benchmark

是。仅记录新增回归集和验收目标；标准答案仍只能用于离线 scorer，不能进入 Agent workflow、prompt、Planner、Executor、Verifier、Correction、测试 fixture 或核心逻辑。

### 是否涉及 Microsoft Agent Framework

否。未安装 Microsoft Agent Framework，未新增依赖，未把核心算法写入 adapter。

### 是否影响未来多 Agent 迁移

是，正向影响。7.2G 把上传表泛化断层纳入 Phase 7.2 的 Agent 泛化验收，避免把同类能力拆到新阶段造成重复。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

---

### 日期时间

2026-05-22 14:03 CST

### 本次目标

继续执行 Phase 7.2：把 Agent 泛化能力放在主线，修正 Planner / Verifier 语义契约和 benchmark report 口径，使 SQL/Pandas/DuckDB parity 只作为执行层支撑指标；同时确认不打断 Phase 7.1 submission gate、Phase 7.2G 上传表泛化专项和 Phase 7.3 Output Contract 进程。

### 修改文件

- MAIN_GOAL.md
- CHANGELOG_AI.md
- data_agent_core/core/analysis_planner.py
- data_agent_core/verifier/rule_checker.py
- data_agent_core/benchmark/metrics.py
- data_agent_core/benchmark/benchmark_runner.py
- multi_agent_workflows/microsoft_anonymized_benchmark_runner.py
- multi_agent_workflows/uploaded_table_benchmark_runner.py
- tests/core/test_semantic_metric_verification.py

### 修改内容

- Planner 泛化契约补齐继续收敛：中文零售 top-count 类 operation 默认带 count aggregation，避免“出现次数最多 / 记录数最多 / 行数最多”被记录成无 metric 语义。
- Verifier 语义检查增强：显式 filter 缺失、grouped count 误路由、count vs sum、mode/top_count、Top-K share denominator 继续作为 semantic mismatch；同时允许已结构化到 parameters / time_window 的中文 person/date/ym/product 等 filter context。
- 修复 Microsoft 1-300 中 `correct=300/300` 但 `success_count=232` 的 false-success：根因是 Verifier 把中文零售 business quantity / top-count / formula context 误判为非 count 或缺 filter，不是执行器算错。
- Benchmark metrics 新增统一 helper：`benchmark_error_type()` 和 `executor_report_fields()`，DABstep、Microsoft、uploaded-table runner 共享 error type、capability family、SQL coverage、Pandas-SQL consistency、coverage gap、semantic mismatch、executor mismatch、format mismatch 字段。
- `capability_family_metrics` 不再在全体同一能力族时折叠为空；Microsoft 1-300 最终报告会明确输出 `chinese_retail_business_metric` 聚合。
- 上传表 runner 补齐统一 executor/parity 字段，避免不同 benchmark report 的 Phase 7.2 口径分裂。
- 新增非 Benchmark 合成语义测试，覆盖中文零售 top-count、业务 quantity metric、以及 `陈列费率=陈列确认金额/分销金额` 这类公式加结构化 filter context。
- MAIN_GOAL 追加 Phase 7.2 当前落地状态和最终回归证据路径，不重排已有 Phase 7.1 / 7.2G / 7.3。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_semantic_metric_verification tests.benchmark.test_benchmark_metrics tests.benchmark.test_uploaded_table_benchmark_runner tests.benchmark.test_phase73_benchmark_runner
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.benchmark.test_benchmark_metrics tests.core.test_semantic_metric_verification
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.architecture.test_dependency_boundaries tests.architecture.test_no_benchmark_hardcoding
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.architecture.test_no_secrets
- git diff --check
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/phase72_generalization_contract_dev_1_10_final_20260522
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 450 --offset 0 --output-dir outputs/phase72_generalization_contract_dabstep_all_1_450_final_20260522
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.microsoft_anonymized_benchmark_runner --dataset-root /Users/trevorcui/Desktop/微软脱敏数据 --limit 300 --offset 0 --output-dir outputs/phase72_generalization_contract_microsoft_1_300_final_20260522
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 /private/tmp/vds_95_smoke.py

### 测试结果

- Targeted semantic / metrics / runner tests 通过：Ran 18 tests，OK。
- Targeted metrics / semantic tests 通过：Ran 15 tests，OK。
- Full unittest 通过：Ran 117 tests in 44.457s，OK。
- compileall 通过。
- import boundary + benchmark hardcoding tests 通过：Ran 7 tests，OK。
- tracked-file secret scan 通过：Ran 1 test，OK。
- git diff --check 通过。
- DABstep dev 1-10 final：total=10，correct=9，accuracy=0.9，success_count=10；SQL covered=3/10，Pandas-SQL consistency=3/3，coverage_gap=7，semantic_mismatch=1，executor_mismatch=0，format_mismatch=0；输出 `outputs/phase72_generalization_contract_dev_1_10_final_20260522/dev_1_to_10_report.json`。
- DABstep public all 1-450 final：total=450，success_count=450，unexpected_not_applicable=0，true_unsupported=3，failure_count=0，accuracy=null；SQL covered=70，Pandas-SQL consistency=70/70，coverage_gap=380，semantic_mismatch=0，executor_mismatch=0，format_mismatch=0；输出 `outputs/phase72_generalization_contract_dabstep_all_1_450_final_20260522/all_1_to_450_report.json`。
- Microsoft 脱敏数据 1-300 final：total=300，correct=300，accuracy=1.0，success_count=300；capability_family_metrics 输出 `chinese_retail_business_metric`；SQL covered=0，coverage_gap=300，semantic_mismatch=0，executor_mismatch=0，format_mismatch=0；输出 `outputs/phase72_generalization_contract_microsoft_1_300_final_20260522/report.json`。
- 桌面 VDS `问题汇总.xlsx` 95 题 smoke：total=95，success_count=95，failure_count=0；输出 `outputs/phase72_generalization_contract_vds_question_summary_95_final_20260522.json`。

### 遗留问题

- DABstep dev 1-10 仍有 1 个 `best_fraud_aci_choice` / associated cost 语义口径失败，继续归入 business-rule what-if / fee candidate table 能力族，不能按 task_id、标准答案或固定题面特调。
- SQL/Pandas 不等价仍主要是 coverage gap，不是 SQL correctness gap：DABstep all skipped=380，Microsoft 1-300 skipped=300；skipped 不计为 executor mismatch。
- `sql_covered_subset_accuracy` 仍只有 runner 提供独立 `sql_correct` 时才计算；当前主要用 Pandas-SQL consistency 验证 SQL covered 子集。
- DuckDB 表格化 rule engine、真实 provider-native tool loop、大规模真实 LLM 回归仍是后续阶段目标。

### 是否影响主流程

是。影响 Planner、Verifier、Benchmark metrics、DABstep/Microsoft/uploaded-table runner 的报告口径；不修改前端，不新增外部依赖，不改变 Microsoft Agent Framework adapter 的核心边界。

### 是否涉及 Benchmark

是。标准答案仍只在 response 生成后用于离线 scorer；task_id、expected answer、proxy answer、accepted answer 和 hidden answer 未进入 Capability Registry、Planner、Executor、Verifier、Correction、prompt、测试 fixture 或核心链路。

### 是否涉及 Microsoft Agent Framework

否。未新增 adapter 依赖，未把核心算法写入 Microsoft adapter。

### 是否影响未来多 Agent 迁移

是，正向影响。Planner 泛化契约、Verifier 语义 mismatch 和 executor parity report 字段现在可被多 Agent workflow、single_agent fallback 和 benchmark runners 共享。

### 是否修改核心数据契约

是。继续强化 LogicForm / AnalysisPlan 中的 generalization contract 字段使用；未修改对外 API request / response dataclass 字段。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

是。Benchmark detail/report 进一步统一 capability family、SQL coverage 和 mismatch 字段；既有 trace schema 未新增对外必填字段。

---

### 日期时间

2026-05-22 14:06 CST

### 本次目标

实施 Phase 7.3：Evaluation-Driven Robustness and Output Contract Hardening，把最终答案 canonicalizer、output validator、validation-driven retry、submission provenance、risk taxonomy 和 Phase 7.3 退出回归落到代码与文档；同时保持 Phase 7.1 submission gate、Phase 7.2 Capability Registry 和 Phase 7.2G 上传表泛化专项边界不被覆盖。

### 修改文件

- MAIN_GOAL.md
- CHANGELOG_AI.md
- data_agent_core/output/output_contract.py
- data_agent_core/output/response_builder.py
- data_agent_core/errors/error_types.py
- data_agent_core/benchmark/provenance.py
- data_agent_core/benchmark/metrics.py
- data_agent_core/benchmark/benchmark_runner.py
- data_agent_core/verifier/result_comparator.py
- data_agent_core/verifier/rule_checker.py
- data_agent_core/core/dabstep_fee_engine.py
- data_agent_core/core/intent_parser.py
- data_agent_core/agent/single_agent.py
- multi_agent_workflows/end_to_end_data_analysis_workflow.py
- multi_agent_workflows/microsoft_anonymized_benchmark_runner.py
- multi_agent_workflows/uploaded_table_benchmark_runner.py
- tests/core/test_output_contract.py
- tests/core/test_semantic_metric_verification.py
- tests/benchmark/test_benchmark_metrics.py
- tests/benchmark/test_phase73_benchmark_runner.py

### 修改内容

- 新增最终答案 canonicalizer / output validator，覆盖 number、percentage、yes/no、list、scheme fee、ACI、card scheme、grouped amounts、Not Applicable、空答案、对象 / 列表泄漏、debug / trace 泄漏和 SQL / markdown 泄漏。
- Response Builder 接入 canonicalizer；最终 `answer` 收敛为提交安全字符串，并把 `output_contract_validation`、`validation_driven_retry`、`canonical_answer` 写入 debug。输出契约失败会追加 recoverable `OUTPUT_CONTRACT_VALIDATION_FAILED`。
- DABstep、Microsoft 和 uploaded-table runner 统一加入 output-contract validation-driven retry、`output_contract_passed`、`output_risk_flags`、retry events、risk taxonomy 和 provenance。
- 新增 trace-safe benchmark provenance：记录 generated_at、command、cwd、git branch / commit / dirty count、runtime、provider env、prediction sha256 和 report content sha256；不记录 API key、hidden answer、public proxy answer pool 或 raw reasoning。
- Benchmark metrics 新增统一 risk taxonomy，拆分 format_risk、semantic_risk、capability_risk、submission_risk、official_hidden_unknown、public_proxy_observation、real_provider_cost_latency 和 trace_redaction_risk。
- RunTrace / multi-agent workflow / single_agent final_response 记录 `output_contract_passed`，便于真实 provider 分段回归和提交前审计。
- 修复 Phase 7.3 回归暴露的通用问题：Decimal / scientific zero canonicalization、distinct_count unique shopper verifier false reject、fee restriction affected merchants 全量扫描性能、intent parser 隐式 value filter 和 `by amount` group_by 误判。
- 修复 VDS 95 smoke 中 Pandas / SQL 浮点表示尾差：Result Comparator 对嵌套 list / dict 中的数值使用近似比较，避免 `600301.9199999999` 与 `600301.92` 这类非语义差异造成 verifier false failure。
- MAIN_GOAL 更新 Phase 7.3 当前代码落点、验收结果路径和真实 provider 前提说明。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_semantic_metric_verification
- VDS_LLM_PROVIDER=mock single-question S16 smoke for `/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/数据/QueryGPT_SaaS订阅数据_单表版.xlsx`
- VDS_LLM_PROVIDER=mock inline runner for `/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/问题/问题汇总.xlsx`, output `outputs/phase73_output_contract_vds_question_summary_95_final_20260522.json`
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_output_contract tests.core.test_semantic_metric_verification tests.benchmark.test_benchmark_metrics tests.benchmark.test_phase73_benchmark_runner
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime multi_agent_workflows tests
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --offset 0 --output-dir outputs/phase73_output_contract_dev_1_10_after_comparator_20260522
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 450 --offset 0 --output-dir outputs/phase73_output_contract_dabstep_all_1_450_after_comparator_20260522
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.microsoft_anonymized_benchmark_runner --dataset-root /Users/trevorcui/Desktop/微软脱敏数据 --limit 300 --offset 0 --output-dir outputs/phase73_output_contract_microsoft_1_300_after_comparator_20260522

### 测试结果

- Semantic verifier focused test 通过：Ran 13 tests，OK。
- S16 单题 smoke 通过：`本周毛利率下降最多的Top10客户？` 的 Pandas-SQL consistency 从 false failure 恢复为 true。
- Phase 7.3 focused tests 通过：Ran 24 tests，OK。
- Full unittest 通过：Ran 117 tests in 17.567s，OK。
- compileall 通过。
- 桌面 VDS `问题汇总.xlsx` 95 题 smoke：total=95，success_count=95，failure_count=0，output_contract_failure_count=0；报告路径 `outputs/phase73_output_contract_vds_question_summary_95_final_20260522.json`。
- DABstep dev 1-10 mock 多 Agent：total=10，correct=9，accuracy=0.9，success_count=10；format_risk=0，submission_risk=0，trace_redaction_risk=0；报告路径 `outputs/phase73_output_contract_dev_1_10_after_comparator_20260522/dev_1_to_10_report.json`。
- DABstep public all 1-450 mock 多 Agent：total=450，success_count=450，unexpected_not_applicable=0，true_unsupported=3，failure_count=0，accuracy=null；format_risk=0，semantic_risk=0，submission_risk=0，trace_redaction_risk=0；report_content_sha256 已生成；报告路径 `outputs/phase73_output_contract_dabstep_all_1_450_after_comparator_20260522/all_1_to_450_report.json`。
- Microsoft 脱敏数据 1-300 mock 离线 scorer：total=300，correct=300，accuracy=1.0，success_count=300；format_risk=0，semantic_risk=0，submission_risk=0，trace_redaction_risk=0；报告路径 `outputs/phase73_output_contract_microsoft_1_300_after_comparator_20260522/report.json`。

### 遗留问题

- 真实 OpenAI / DeepSeek provider representative / staged / full 回归本轮未执行，因为当前运行环境未提供 `OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY`；本轮已实现 provider / runtime / latency / provenance / retry 记录入口，后续有 key 后可按同一 runner 分段执行。
- DABstep dev 1-10 仍为 9/10，剩余失败继续归入 `best_fraud_aci_choice` / associated cost 语义口径，不能按 task_id、标准答案或固定题面特调。
- DABstep public all answer 为空，本地不能计算 hidden official accuracy；`official_hidden_unknown=true` 仅表示本地不可复现 official hidden score。
- DABstep all 1-450 本次全量耗时较长，report 已记录 elapsed_seconds=738.975；后续真实 provider 分段回归需要使用 staged / resume 策略。

### 是否影响主流程

是。影响 FinalResponse 构建、benchmark runner、risk report、provenance、Verifier comparison 和 trace final_response；不修改前端，不改变后端稳定 API，不新增外部依赖。

### 是否涉及 Benchmark

是。标准答案仍只在 response 生成后用于 scorer；task_id、expected answer、proxy answer、accepted answer、hidden answer 和 leaderboard feedback 未进入 prompt、Planner、Executor、Verifier、Correction、测试 fixture 或核心链路。

### 是否涉及 Microsoft Agent Framework

否。未新增 Microsoft Agent Framework 依赖，未把核心算法写入 adapter。

### 是否影响未来多 Agent 迁移

是，正向影响。最终输出契约、provenance、risk taxonomy 和 verifier 数值比较均在 provider-neutral / workflow-neutral 层实现，可被 single_agent、多 Agent workflow 和后续 provider-native loop 复用。

### 是否修改核心数据契约

是。新增 output contract validation debug payload、benchmark provenance 和 risk taxonomy metadata；未修改对外 API request / response 必填字段。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

是。新增 `OUTPUT_CONTRACT_VALIDATION_FAILED`，用于标记最终输出契约失败的 recoverable 错误。

### 是否新增或修改运行追踪逻辑

是。RunTrace final_response 增加 `output_contract_passed`，benchmark report 增加 provenance / risk taxonomy / retry events；trace 仍不记录完整 Chain of Thought、raw reasoning tokens、API key、hidden answer 或 public proxy answer pool。

---

### 日期时间

2026-05-22 14:17 CST

### 本次目标

完成 Phase 7.2 收口审计，修正 `MAIN_GOAL.md` 当前实现状态编号，并复核 Phase 7.2 目标已由当前代码、测试和文档证据覆盖；不改 executor 代码，不重排 Phase 7.1 / Phase 7.2G / Phase 7.3。

### 修改文件

- MAIN_GOAL.md
- CHANGELOG_AI.md

### 修改内容

- 修正 `MAIN_GOAL.md` 当前实现状态中 Phase 7.2 泛化契约落地项的重复编号，把第二个 `37.` 改为 `38.`。
- 复核 Phase 7.2 当前证据：Planner 泛化契约字段、Verifier semantic mismatch、Capability Registry、executor parity report、测试和文档均已落到当前 worktree。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.architecture.test_dependency_boundaries tests.architecture.test_no_benchmark_hardcoding tests.architecture.test_no_secrets
- git diff --check

### 测试结果

- Full unittest 通过：Ran 117 tests，OK。
- compileall 通过。
- 架构边界 / Benchmark hardcoding / secret scan 通过：Ran 8 tests，OK。
- git diff --check 通过。

### 遗留问题

- 无新增遗留问题；Phase 7.2 仍保留既有后续方向：SQL coverage gap、DuckDB/rule-engine 表格化、真实 provider 分段回归和 DABstep `best_fraud_aci_choice` associated cost 语义口径。

### 是否影响主流程

否。本次只做文档编号收口和审计记录。

### 是否涉及 Benchmark

是。只复核 Benchmark 报告口径和测试结果；未把 task_id、expected answer、proxy answer、accepted answer 或 hidden answer 引入核心链路。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

否。本次不改代码路径。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

---

### 日期时间

2026-05-22 14:57 CST

### 本次目标

按用户要求把 README 同步写入项目规则：以后阶段、状态、主目标、项目规则、API、Benchmark 口径或用户可见能力变更时，必须同步检查并更新 GitHub 首页读取的根 README；同时补齐当前 README 对 Phase 7.2 / 7.2G / 7.3 的摘要。

### 修改文件

- README.md
- MAIN_GOAL.md
- BRANCH_RULES.md
- CHANGELOG_AI.md

### 修改内容

- README 首屏同步 Phase 7.2、Phase 7.2G、Phase 7.3 当前状态，避免 GitHub 首页只停留在 Phase 7.1。
- README 新增同步规则说明，明确 README 是 GitHub 默认首页状态摘要。
- MAIN_GOAL 架构原则新增 README 同步治理规则。
- BRANCH_RULES 新增 README 同步规则，并把 README 同步状态加入修改完成输出项和 PR 检查项。
- CHANGELOG_AI 使用规则和模板新增“是否已同步 README”字段，覆盖代码、文档和项目规则修改。

### 测试方式

- rg -n "Phase 7\\.2|Phase 7\\.2G|Phase 7\\.3|README 同步|是否已同步 README" README.md MAIN_GOAL.md BRANCH_RULES.md CHANGELOG_AI.md
- git diff --check

### 测试结果

- README / MAIN_GOAL / BRANCH_RULES / CHANGELOG_AI 中 README 同步规则和 Phase 7.2 / 7.2G / 7.3 摘要均有预期命中。
- git diff --check 通过。

### 遗留问题

- 本轮是文档和规则同步，不执行核心算法、Benchmark 或真实 provider 回归。
- 该变更需要合并到 dev，再由 dev 合并到 main 后，GitHub 默认首页 README 才会直接显示更新后的内容。

### 是否影响主流程

否。仅修改项目文档、治理规则和 README 摘要。

### 是否涉及 Benchmark

是。仅同步 Benchmark 状态和 README 同步规则；未修改 Benchmark 数据、runner、scorer、标准答案隔离或核心分析链路。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

否。仅增强文档治理，避免未来多 Agent / provider / benchmark 状态只写入 MAIN_GOAL 或 CHANGELOG 而未同步 README。

### 是否修改核心数据契约

否。

### 是否修改 API 契约

否。

### 是否新增或修改错误类型

否。

### 是否新增或修改运行追踪逻辑

否。

### 是否已同步 README

是。README 已同步 Phase 7.2、Phase 7.2G、Phase 7.3 当前摘要，并写入后续每次状态类变更必须检查和更新 README 的规则。

---

### 日期时间

2026-05-22 16:39 CST

### 本次目标

按当前 goal 实施 DABstep Easy Accuracy Recovery：把目标按 Phase 7.1 验收和 Phase 7.2 泛化实现写入 MAIN_GOAL，不改写原 Phase 定义；借鉴 DA-agent 的 schema/tool-first、SQL guardrail、answer contract、deterministic rule engine 思路，但禁止 task_id、proxy answer、accepted answer 或 hidden answer 进入核心链路；使用真实 DeepSeek 分片验证 easy public proxy 必须超过 85%，优先超过 90%。

### 修改文件

- MAIN_GOAL.md
- README.md
- agent_runtime/data_agent_tool_impl.py
- agent_runtime/data_analysis_roles.py
- data_agent_core/contracts/analysis_contracts.py
- data_agent_core/core/analysis_planner.py
- data_agent_core/core/capability_registry.py
- data_agent_core/core/dabstep_fee_engine.py
- data_agent_core/core/intent_parser.py
- data_agent_core/core/logic_form.py
- data_agent_core/executors/pandas_executor.py
- data_agent_core/executors/sql_executor.py
- data_agent_core/output/output_contract.py
- tests/core/test_generic_capability_operations.py

### 修改内容

- MAIN_GOAL / README 明确当前 goal 是 DABstep Easy Accuracy Recovery，并按 Phase 职责拆分：Phase 7.1 记录 baseline、目标和 proxy policy；Phase 7.2 记录泛化能力族实现；这不是替换原 Phase 7.1 / 7.2 定义。
- LogicForm 新增 `answer_target`，并在 agent_runtime payload 重建、Planner output contract 和 final answer canonicalizer 中保留，支持 `metric_only`、`entity_only`、`entity_list_only`、`segment_vector`。
- Intent Parser 增强字段 / filter binding：补齐 account_type、issuer country、missing/null row count、fraud boolean、IP country、scalar amount extreme、top-k share ranking/share metric 拆分、repeat-customer quantile、grouped fraud rate max/min/std、combined fraud segment 和 decimal-place 解析。
- Pandas / SQL executor 同步增强 metric_per_distinct_entity、top_k_share、null_check、rank_by_metric selected_metric、combined worst_fraud_segment，并新增 `fraud_rate_fluctuation`；同时补齐通用 numeric range filter dict `{min,max}`，支持真实 provider 生成的范围 filter 形态。
- Fee engine 调整 deterministic fee monotonic 输出：increased 返回 monthly_volume / capture_delay，decreased 返回 monthly_fraud_level，volume threshold 返回规则区间 label，并从 manual.md 表格补 account_type 枚举。
- 新增同族泛化测试，覆盖字段改名、布尔 filter、grouped fraud metric answer target、period std fraud rate、top-k 按金额排序但按交易数占比、repeat entity quantile、numeric range filter 和 fee rule enum / direction。

### 测试方式

- VDS_LLM_PROVIDER=deepseek 分片运行 DABstep easy 72：offset 0/12/24/36/48/60，limit=12，输出到 `outputs/dabstep_easy_proxy_20260522_deepseek_real_chunks/*`
- 合并真实 DeepSeek 分片并用 public accepted pool 做后验 proxy observation：`outputs/dabstep_easy_proxy_20260522_deepseek_real_combined/all_1_to_72_public_proxy_observation.json`
- VDS_LLM_PROVIDER=mock DABstep easy 72 离线回归：`outputs/dabstep_easy_proxy_20260522_after_recovery/all_1_to_72_public_proxy_observation.json`
- VDS_LLM_PROVIDER=mock DABstep dev 1-10：`outputs/dabstep_dev_1_10_after_easy_recovery_range_filter_20260522/dev_1_to_10_report.json`
- VDS_LLM_PROVIDER=mock DABstep public all 1-450：`outputs/dabstep_all_1_450_after_easy_recovery_20260522/all_1_to_450_report.json`
- VDS_LLM_PROVIDER=mock Microsoft 1-300：`outputs/microsoft_anonymized_1_300_after_easy_recovery_20260522/report.json`
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_generic_capability_operations tests.core.test_output_contract
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.architecture.test_dependency_boundaries tests.architecture.test_no_benchmark_hardcoding tests.architecture.test_no_secrets tests.benchmark.test_phase73_benchmark_runner tests.core.test_dabstep_core
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime ms_agent_framework_adapter multi_agent_workflows backend tests
- git diff --check

### 测试结果

- 真实 DeepSeek easy 72 分片合并：public proxy 后验观察为 `69/72 = 95.83%`，超过 `>=62/72` 验收目标和 `>=65/72` 优先目标；`success_count=65/72`，Pandas-SQL consistency `49/49`，剩余 proxy failure 为 rank_by_metric 1、fee_factor_direction 2。
- mock easy 72 离线回归：`72/72 = 100%`，仅作为确定性能力族回归，不冒充真实 DeepSeek 或 official hidden accuracy。
- DABstep dev 1-10：correct=9/10，accuracy=0.9，success_count=10，unexpected_not_applicable=0。
- DABstep public all 1-450：success_count=450，unexpected_not_applicable=0，true_unsupported=3，failure_count=0，Pandas-SQL consistency 69/69。
- Microsoft 1-300：correct=300/300，accuracy=1.0，success_count=300。
- focused tests 通过：Ran 52 tests，OK。
- full unittest 通过：Ran 126 tests，OK。
- 架构 / hardcoding / secret / Phase 7.3 runner 子集通过：Ran 13 tests，OK。
- compileall 通过。
- git diff --check 通过。

### 遗留问题

- 真实 DeepSeek easy proxy 剩余 3 个 public-proxy mismatch：一个 grouped fraud metric 的 public pool 只接受两位小数，两个 fee boolean direction 与当前 deterministic rule-average 口径不同；后续若继续提升，应按通用 output rounding contract 和 fee candidate-pair / rule semantics 修复，不能按 task_id 或固定答案补丁。
- public proxy 不是 official hidden accuracy，只能作为 response 生成后的后验观察和能力族归因。
- `.playwright-cli/` 是本地未跟踪目录，本轮未使用、未修改、未纳入变更。

### 是否影响主流程

是。影响 data_agent_core / agent_runtime 的 DABstep-style table analysis、output contract、executor filter 和 fee rule 能力；不修改前端、不修改 backend API 契约。

### 是否涉及 Benchmark

是。涉及 DABstep easy/public/dev、Microsoft 1-300 和 public proxy observation；expected answer、public proxy、accepted answer 和 hidden answer 仍只用于 response 之后的离线 scorer / observation，未进入 Planner、Executor、Verifier、Correction、prompt、tests fixture 或核心源码。

### 是否涉及 Microsoft Agent Framework

否。未修改 ms_agent_framework_adapter 行为，也未引入 Microsoft Agent Framework 依赖。

### 是否影响未来多 Agent 迁移

是，正向影响。`answer_target`、output contract、capability family 和 executor semantic parity 都通过稳定契约表达，可被当前内部 multi-agent workflow 和未来 adapter 复用。

### 是否修改核心数据契约

是。LogicForm 新增 `answer_target`，output_contract 增加对应 answer target 信息。

### 是否修改 API 契约

否。未修改 backend 对外 API schema。

### 是否新增或修改错误类型

否。未新增错误类型。

### 是否新增或修改运行追踪逻辑

否。未新增 trace 字段；现有 trace 会随 LogicForm / output_contract payload 自然记录 `answer_target`。

### 是否已同步 README

是。README 已同步当前 Easy Recovery goal、真实 DeepSeek `69/72`、mock `72/72`、public proxy policy 和 Phase 7.1 / 7.2 职责拆分。

---

### 日期时间

2026-05-23 02:46 CST

### 本次目标

最终收口 Phase 8/9 实施：确认详细实现记录、阶段状态文档、API 契约、前端边界和回归结果已经同步到仓库文档，并在文末追加本次最终验收记录。

### 修改文件

- MAIN_GOAL.md
- README.md
- docs/API_CONTRACT.md
- docs/FEATURE_BACKLOG.md
- CHANGELOG_AI.md

### 修改内容

- MAIN_GOAL.md 标记 Phase 8A-8E 已完成，Phase 9 首版 workbench 已完成，并写明真实 provider key 缺失限制。
- README.md 同步 Phase 8/9 当前状态、`/api/data-agent/upload-batch`、`/workbench`、三类回归门禁和前端不承载核心计算边界。
- docs/API_CONTRACT.md 增补 `upload-batch`、多文件 profile 字段、`source_tables`、`table_selection_reason`、`join_plan`、`join_execution_summary` 和 `/workbench` 契约。
- docs/FEATURE_BACKLOG.md 增补 Phase 8 multi-file / multi-table closure 和 Phase 9 frontend workbench 的完成状态。
- CHANGELOG_AI.md 记录 Phase 8/9 实施与最终验证结果。

### 测试方式

- git diff --check
- node --check frontend/app.js
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall backend frontend data_agent_core agent_runtime multi_agent_workflows tests
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- rg -n "Phase 8 已|Phase 9 已|upload-batch|/workbench|source_tables|table_selection_reason|join_plan|join_execution_summary|OPENAI_API_KEY|DEEPSEEK_API_KEY" MAIN_GOAL.md README.md docs/API_CONTRACT.md docs/FEATURE_BACKLOG.md CHANGELOG_AI.md

### 测试结果

- git diff --check 通过。
- node --check frontend/app.js 通过。
- compileall 通过。
- 全量 unittest 通过：Ran 135 tests，OK。
- 文档关键词均命中，Phase 8/9 完成状态、API 契约、前端入口和真实 provider 限制已同步。

### 遗留问题

- 当前环境没有 `OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY`，真实 provider representative / staged 回归未执行。
- `.playwright-cli/` 仍是本地既有未跟踪目录，本轮未纳入变更。

### 是否影响主流程

是。记录并同步 Phase 8 核心算法闭环和 Phase 9 前端 workbench 完成状态。

### 是否涉及 Benchmark

是。文档记录 DABstep、微软脱敏数据和原本 VDS 回归门禁结果；未把标准答案、public proxy、accepted answer 或 hidden answer 引入核心链路。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

是，正向影响。多文件、多表和 join trace 契约可被当前 multi_agent workflow 和未来 adapter 复用。

### 是否修改核心数据契约

是。记录 Phase 8 中已落地的 DatasetProfile / LogicForm / AnalysisPlan / RunTrace 扩展。

### 是否修改 API 契约

是。API_CONTRACT 已同步 `upload-batch` 和 `/workbench`。

### 是否新增或修改错误类型

否。本次最终收口不新增 error_type。

### 是否新增或修改运行追踪逻辑

是。文档同步记录 Phase 8 已落地的 join trace 字段。

### 是否已同步 README

是。README 已同步 Phase 8/9 完成状态。

---

### 日期时间

2026-05-23 11:55 CST

### 本次目标

按用户要求把 VDS 后续计划从笼统的“Phase 7 后续增强”改为明确的 Phase 7.5 - 7.10 编号版，让后续工程项能清楚体现发生在 Phase 7.1 / 7.2 / 7.2G / 7.3 之后，同时不新增 Phase 7.4、不重开 Phase 8/9 主体。

### 修改文件

- MAIN_GOAL.md
- README.md
- docs/FEATURE_BACKLOG.md
- docs/ARCHITECTURE.md
- CHANGELOG_AI.md

### 修改内容

- MAIN_GOAL.md 在统一 Phase 状态表和 Phase 7.3 后新增 Phase 7.5+ 后续子阶段计划，覆盖 Tool / Safety、provider-native real smoke、DuckDB read-only runtime、multi-agent parallel / bounded correction、MAF demo、ACI / complex BI、Phase 8 Guardrail 和 Phase 9.1。
- README.md 将后续 TODO 改为 Phase 编号摘要，避免只写“复杂多 Agent / MAF / tool 后续增强”。
- docs/FEATURE_BACKLOG.md 新增 Phase 7.5、7.6、7.7、7.8、7.9、7.10 和 Phase 9.1 backlog 条目，并记录目标、影响模块、优先级、验收标准、风险、泛化验证方式、contract / API / tracing / errors 影响。
- docs/ARCHITECTURE.md 的 TODO 改为按 Phase 7.5 - 7.10 顺序推进，并明确 provider adapter 和 MAF adapter 都不能承载核心算法。
- CHANGELOG_AI.md 记录本次只是文档编号和执行计划同步，不做代码实现。

### 测试方式

- git diff --check
- rg -n "Phase 7\\.5|Phase 7\\.6|Phase 7\\.7|Phase 7\\.8|Phase 7\\.9|Phase 7\\.10|Phase 8 Guardrail|Phase 9\\.1|DABstep.*Microsoft.*VDS|codex/vds-phase75" MAIN_GOAL.md README.md docs/FEATURE_BACKLOG.md docs/ARCHITECTURE.md CHANGELOG_AI.md
- rg -n "Phase 7\\.4|MAF.*强依赖|前端实现.*join|provider-native adapter.*生产默认|provider-native.*生产默认链路" MAIN_GOAL.md README.md docs/FEATURE_BACKLOG.md docs/ARCHITECTURE.md

### 测试结果

- git diff --check 通过。
- Phase 7.5 / 7.6 / 7.7 / 7.8 / 7.9 / 7.10 / Phase 8 Guardrail / Phase 9.1 关键词扫描均有预期命中，集中在 MAIN_GOAL、README、FEATURE_BACKLOG、ARCHITECTURE 和本条 CHANGELOG。
- Phase 7.4 标题扫描无命中；未新增 `## Phase 7.4` 或 `### Phase 7.4`。
- provider-native / MAF / 前端 join 口径扫描只命中既有或本轮新增的禁止事项，例如“不作为生产默认链路”“不成为强依赖”“前端不实现 join”，未发现相反口径。

### 遗留问题

- 本轮只做文档计划同步，尚未实现 Phase 7.5 - 7.10 的代码。
- 当前工作区已有大量未提交代码和文档改动；本轮只触碰上述文档文件，不回滚、不覆盖其他人的改动。

### 是否影响主流程

否。仅修改文档中的阶段编号、后续计划和治理要求。

### 是否涉及 Benchmark

是。文档新增 Phase 7.5+ 的三数据集 non-regression gate：DABstep dev 1-10 不低于 9/10，DABstep public all 1-450 mock 保持 450/450 且 unexpected_not_applicable=0，Microsoft 1-300 mock scorer 保持 300/300，VDS 95 smoke 保持 95/95；未修改 Benchmark 数据、runner、scorer 或核心链路。

### 是否涉及 Microsoft Agent Framework

是，仅文档层面。新增 Phase 7.9 MAF demo 计划，并明确 MAF 只作为可选 adapter / workflow 承载层，不成为 data_agent_core 或 backend 强依赖，不承载核心算法。

### 是否影响未来多 Agent 迁移

是，正向影响。Phase 7.8 / 7.9 明确先做 Agent 独立测试、有限 executor 并行、bounded correction retry 和 adapter-only MAF demo，避免直接跳到不可审计的复杂编排。

### 是否修改核心数据契约

否。本轮不改代码和 contracts，只记录未来可能影响 contracts 的阶段。

### 是否修改 API 契约

否。本轮不改 API_CONTRACT；Phase 9.1 记录如果后续新增稳定确认字段，必须先更新 API_CONTRACT。

### 是否新增或修改错误类型

否。本轮只写计划。

### 是否新增或修改运行追踪逻辑

否。本轮只写计划；后续 Phase 7.5 / 7.6 / 7.7 / 7.8 可能扩展 trace-safe summary。

### 是否已同步 README

是。README 已同步 Phase 7.5 - 7.10、Phase 8 Guardrail 和 Phase 9.1 的编号摘要。

---
### 日期时间

2026-05-23 23:13 CST

### 本次目标

收口 Phase 10 full real after-fix：修复真实 DeepSeek 全量回归暴露的两个通用能力问题，补齐 VDS 95 中文 BI 当前周期占比能力，复跑三数据集真实 DeepSeek 汇总，并同步 Phase 10 验收状态。

### 修改文件

- data_agent_core/verifier/rule_checker.py
- data_agent_core/executors/sql_executor.py
- data_agent_core/executors/pandas_executor.py
- data_agent_core/core/vds_bi_intent.py
- data_agent_core/executors/vds_bi_executor.py
- data_agent_core/core/capability_registry.py
- data_agent_core/llm/planner.py
- tests/core/test_semantic_metric_verification.py
- tests/core/test_generic_capability_operations.py
- tests/core/test_vds_bi_capabilities.py
- README.md
- MAIN_GOAL.md
- docs/FEATURE_BACKLOG.md
- CHANGELOG_AI.md
- 本轮前序 Phase 10 体验文件仍在同一工作树中：frontend/app.js、frontend/index.html、frontend/styles.css、frontend/README.md、docs/API_CONTRACT.md、docs/ARCHITECTURE.md、tests/backend/test_workbench_static_assets.py

### 修改内容

- Verifier 对 `metric_per_distinct_entity` 的 row-count numerator + unique-entity denominator 做通用 count metric 认可，避免把“平均交易次数 / unique shopper”误判为非 count metric。
- SQL / Pandas executor 对 `day_of_year: [start, end]` 两端点列表统一按区间过滤，修复真实 DeepSeek 中 Q3 fraud rate 的 Pandas / SQL fallback 不一致。
- VDS 中文 BI 增加 `vds_current_category_share_top` 能力族，支持“本周某状态人数占比最高 TopN 校区/实体”等当前周期类别占比问题。
- 新增合成测试覆盖 count-per-unique-entity、day_of_year endpoint range filter 和当前周期类别占比 TopN，避免按 task_id 或固定题面特判。
- 生成 after-fix full real 汇总：DABstep public all 用旧 full offset 结果加 task 36 / task 58 after-fix 真实单题 replacement 合并，Microsoft 300 和 VDS 95 使用已完成的真实 DeepSeek full 汇总。
- README、MAIN_GOAL、FEATURE_BACKLOG 更新 Phase 10 full real 状态，明确 DABstep public all 本地没有 expected answer，不能宣称 hidden official accuracy。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_semantic_metric_verification tests.core.test_generic_capability_operations tests.core.test_vds_bi_capabilities tests.core.test_phase10_result_experience
- set -a; . ./.env.local; set +a; VDS_LLM_PROVIDER=deepseek VDS_LLM_MAX_RETRIES=6 VDS_LLM_RETRY_BACKOFF_SECONDS=2 /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 1 --offset 113 --output-dir outputs/phase10_full_real_dabstep_task36_deepseek_20260523_after_fix
- set -a; . ./.env.local; set +a; VDS_LLM_PROVIDER=deepseek VDS_LLM_MAX_RETRIES=6 VDS_LLM_RETRY_BACKOFF_SECONDS=2 /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.dabstep_benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 1 --offset 275 --output-dir outputs/phase10_full_real_dabstep_task58_deepseek_20260523_after_fix
- Python 汇总脚本生成 `outputs/phase10_full_real_dabstep_all_deepseek_20260523_combined_after_fix.json`
- Python 汇总脚本生成 `outputs/phase10_full_real_three_dataset_deepseek_20260523_summary_after_fix.json`
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core agent_runtime backend multi_agent_workflows tests
- node --check frontend/app.js
- git diff --check

### 测试结果

- Focused tests 通过：Ran 73 tests，OK。
- DABstep task 36 after-fix 真实 DeepSeek：total=1，success_count=1，pandas_sql_consistency=1/1，semantic_risk=0，submission_risk=0，trace_redaction_risk=0。
- DABstep task 58 after-fix 真实 DeepSeek：total=1，success_count=1，pandas_sql_consistency=1/1，semantic_risk=0，submission_risk=0，trace_redaction_risk=0。
- DABstep public all after-fix combined：total=450，success_count=450，unexpected_not_applicable=0，true_unsupported=3，format_risk=0，semantic_risk=0，submission_risk=0，trace_redaction_risk=0，accuracy=null。
- Microsoft 1-300 真实 DeepSeek combined：total=300，correct=300，accuracy=1.0，success_count=300，关键风险为 0。
- 原本 VDS 95 真实 DeepSeek combined：total=95，success_count=95，failure_count=0，output_contract_failure_count=0，关键风险为 0。
- 三数据集汇总 gate passed：`outputs/phase10_full_real_three_dataset_deepseek_20260523_summary_after_fix.json`。
- 全量 unittest 通过：Ran 147 tests，OK。
- compileall、`node --check frontend/app.js`、`git diff --check` 均通过。

### 遗留问题

- DABstep public all 的 expected answer 本地为空，因此 full real 只能证明真实 provider 执行覆盖、风险门禁、trace 和可比路径一致性，不能本地计算 hidden official accuracy。
- 90-179 分片 after-fix 重跑时曾遇到 DeepSeek HTTPS connection reset；已用更小 offset 的真实单题 replacement 验证并合并，不把网络中断当作逻辑失败。
- `.playwright-cli/` 仍是本地既有未跟踪目录，本轮未纳入 Git。

### 是否影响主流程

是。修复 Verifier 和 executor 的通用能力族，并更新 Phase 10 full real 验收状态。

### 是否涉及 Benchmark

是。涉及 DABstep public all、Microsoft 1-300 和原本 VDS 95 的真实 DeepSeek full 汇总；标准答案、public proxy、accepted answer、hidden answer 和 task_id 仍不进入 Planner、Executor、Verifier、Correction、prompt 或 trace。

### 是否涉及 Microsoft Agent Framework

否。

### 是否影响未来多 Agent 迁移

是，正向影响。Verifier count metric 语义和 executor filter 语义更加稳定，可被当前 multi_agent workflow 和未来 adapter 复用。

### 是否修改核心数据契约

是。新增 VDS BI operation 进入能力注册和 planner 支持集；未改变既有响应字段名称。

### 是否修改 API 契约

否。本轮修复核心能力和文档状态，未新增 API 请求/响应字段。

### 是否新增或修改错误类型

否。未新增 error_type。

### 是否新增或修改运行追踪逻辑

否。本轮没有新增 trace 字段；仅验证风险和 trace redaction gate。

### 是否已同步 README

是。README 已同步 Phase 10 full real after-fix 验收结果和 DABstep hidden accuracy 边界。

---
### 日期时间

2026-05-24 01:34 CST

### 本次目标

实现 DAB Hard Recovery v2：先统一 Phase 10 after-fix all-450 Easy/Hard proxy 口径，再补齐 Fee ID 列表格式、Fee / ACI candidate table 语义校验，并确保 DAB、Microsoft、VDS 和多文件/join 能力不退步。

### 修改文件

- data_agent_core/benchmark/dabstep_proxy_observation.py
- data_agent_core/output/output_contract.py
- data_agent_core/core/dabstep_fee_engine.py
- data_agent_core/core/intent_parser.py
- data_agent_core/verifier/rule_checker.py
- tests/benchmark/test_dabstep_proxy_observation.py
- tests/core/test_output_contract.py
- tests/core/test_generic_capability_operations.py
- tests/core/test_semantic_metric_verification.py
- README.md
- MAIN_GOAL.md
- CHANGELOG_AI.md

### 修改内容

- 新增 DABstep post-response proxy observation CLI，可从 Phase 10 after-fix report / predictions 和本地 task_scores 生成 all-450 Easy / Hard、operation、capability family、format/list-order 风险和 provenance hash。
- 用 Phase 10 after-fix full real report 重新生成 all-450 proxy observation：total `420/450 = 93.33%`，Easy `71/72 = 98.61%`，Hard `349/378 = 92.33%`；旧 all-450 proxy hard `75.40%` 只保留为历史风险样本。
- Output Contract 对数字型 list 做稳定 numeric sort；Fee ID output_format 显式标记 sort/dedupe；fee engine 对 fee IDs 和 matched fee IDs 返回稳定升序集合。
- Verifier 新增 Fee / ACI candidate table 检查：候选表必须存在、fee 字段必须可数值化、selected 必须来自 candidate dimension，失败时触发 bounded correction action。
- 新增 focused tests 覆盖 proxy observation、数字 list canonicalizer、applicable fee IDs 稳定排序和 Fee / ACI candidate table 语义拒绝。
- README / MAIN_GOAL 同步 DAB Hard Recovery v2 当前口径、输出路径、非回归门禁和 hidden accuracy 边界。

### 测试方式

- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_output_contract tests.core.test_generic_capability_operations tests.core.test_semantic_metric_verification tests.benchmark.test_dabstep_proxy_observation
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.dabstep_proxy_observation --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --report outputs/phase10_full_real_dabstep_all_deepseek_20260523_combined_after_fix.json --output outputs/dabstep_all_1_450_proxy_after_phase10_20260524/all_1_to_450_public_proxy_observation_after_fix.json --old-proxy outputs/dabstep_all_1_450_deepseek_real_combined_20260522/all_1_to_450_public_proxy_observation.json --external-easy-target 0.95 --external-hard-target 0.84
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.architecture.test_no_benchmark_hardcoding tests.architecture.test_no_secrets tests.architecture.test_dependency_boundaries
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall data_agent_core tests/core tests/benchmark tests/architecture
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split dev --limit 10 --output-dir outputs/dabstep_hard_recovery_v2_dev_mock
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m data_agent_core.benchmark.benchmark_runner --dataset-root /Users/trevorcui/Desktop/DABstep_download_20260520/dataset_DABstep --split all --limit 450 --output-dir outputs/dabstep_hard_recovery_v2_all_mock
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m multi_agent_workflows.microsoft_anonymized_benchmark_runner --dataset-root /Users/trevorcui/Desktop/微软脱敏数据 --limit 300 --offset 0 --output-dir outputs/dab_hard_recovery_v2_microsoft_1_300_mock_20260524
- VDS_LLM_PROVIDER=mock inline VDS 95 smoke runner for `/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/问题/问题汇总.xlsx`, output `outputs/dab_hard_recovery_v2_vds_question_summary_95_mock_20260524.json`
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_phase8_multitable_capabilities
- git diff --check
- VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -t . -p 'test*.py'

### 测试结果

- Focused tests 通过：Ran 73 tests，OK。
- Phase 10 after-fix all-450 proxy observation 已生成：total `420/450 = 93.33%`，Easy `71/72 = 98.61%`，Hard `349/378 = 92.33%`；source report sha256=`31db5c942c242b6aaee1874d1d7ae964e9f112f31d4cb52f28097c0269765c50`，report_content_sha256=`8c15be2323ddd965a857e7c1777bbf8284e26d921195bf8aa178e792eefcde50`。
- Architecture tests 通过：Ran 8 tests，OK。
- compileall 通过。
- DABstep dev 1-10 mock：total=10，correct=9，accuracy=0.9，success_count=10。
- DABstep all 1-450 mock：total=450，success_count=450，unexpected_not_applicable=0，true_unsupported=3，format_risk=0，submission_risk=0，trace_redaction_risk=0，accuracy=null。
- Microsoft 1-300 mock scorer：total=300，correct=300，accuracy=1.0，success_count=300，format_risk=0，semantic_risk=0，submission_risk=0，trace_redaction_risk=0。
- 原本 VDS `问题汇总.xlsx` 95 题 smoke：total=95，success_count=95，failure_count=0，output_contract_failure_count=0。
- Phase 8 multi-file/join focused：Ran 5 tests，OK。
- `git diff --check` 通过。
- Full unittest 通过：Ran 152 tests，OK。

### 遗留问题

- 当前新 proxy 已超过用户提供 Easy 95 / Hard 84 目标线，但仍是本地 task_scores 后验 proxy，不是 official hidden accuracy。
- 剩余 proxy false 仍集中在 `fee_extreme_by_dimension`、`fee_rate_delta`、`group_average`、`fee_restriction_affected_merchants`、`best_fraud_aci_choice`、`fraud_rate_filtered`、`aci_fee_extreme`；后续继续按能力族增强，不按题号或固定答案特调。
- `.playwright-cli/` 仍是本地既有未跟踪目录，本轮未纳入 Git。

### 是否影响主流程

是。修改 output canonicalizer、fee engine 和 verifier，但均为通用能力族增强，并已跑 DAB / Microsoft / VDS / 多文件 join 非回归门禁。

### 是否涉及 Benchmark

是。新增 DABstep proxy observation 工具和测试；task_scores / proxy 只用于 response 之后的后验观察和报告，不进入 Planner、Executor、Verifier、Correction、prompt 或 trace。

### 是否涉及 Microsoft Agent Framework

否。未修改 Microsoft Agent Framework adapter，也未引入相关依赖。

### 是否影响未来多 Agent 迁移

是，正向影响。输出规范化和 Verifier candidate table 检查位于核心通用链路，可被当前 multi_agent workflow 和未来 adapter 复用。

### 是否修改核心数据契约

否。未新增稳定 API 字段；只扩展 output_format 内部可选排序标记和 benchmark observation 报告结构。

### 是否修改 API 契约

否。未改后端 API 请求或响应契约。

### 是否新增或修改错误类型

否。未新增 error_type；Verifier 使用已有 correction_action 风格返回修复方向。

### 是否新增或修改运行追踪逻辑

否。未新增 trace 字段；proxy observation 工具不读取或写入核心 trace 逻辑。

### 是否已同步 README

是。README 已同步 DAB Hard Recovery v2 最新 proxy 口径、非回归门禁和 hidden accuracy 边界。

---
