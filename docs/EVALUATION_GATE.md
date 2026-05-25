# VDS Evaluation Gate

## 目标

VDS 每次修改后必须先通过数据集无关的通用门禁，再按数据集业务场景追加专项门禁。通用门禁覆盖真实用户开场问题和技术挑毛病问题，防止只修某个 benchmark 或某个演示数据集。

## 两层门禁

### 1. Generic Dataset Gate

适用于任何上传数据集。它不假设出租车、销售、库存、订阅或其他业务主题。

覆盖问题按 A-E 五组验收：

1. A 无文件 general 问答：你好、你能做什么、没有数据能否给建议、是否支持多文件。
2. B 上传后 general / 基础理解：看一下这个数据、数据主要讲什么、行列数、字段含义、缺失字段、字段一致性。
3. C 模糊问题：帮我看看哪里有问题、这个数据正常吗、给我一个结论、这个数据能不能用。
4. D General 到正式分析路由：从概览转到核心指标、分组分析、趋势/同比可行性、多文件 join / 对比候选。
5. E 技术挑毛病专项：重复行、缺失、数值负值/0 值、IQR 极端值、日期解析、泄密防线、字段不确定性、外部维表边界、清洗确认边界。

运行示例：

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_generic_dataset_eval.py \
  --dataset-name my_dataset \
  --files /path/to/file1.csv /path/to/file2.xlsx \
  --output-dir outputs/eval_gate/my_dataset_generic
```

支持输入：

- CSV
- XLSX / XLS
- JSON
- Parquet

输出：

- `summary.json`
- `summary.md`
- `standard_answers.json`
- `standard_answers.jsonl`
- `standard_answers.md`
- `comparison.json`
- `comparison.jsonl`
- `comparison.md`

标准答案由源文件画像生成，只用于离线评估，不得传入 Planner、Executor、Verifier、Correction、prompt 或 trace。

`comparison.md` 会把每个问题、预期路由、我的标准回复、VDS 实际回复和对比状态放在一起。未传入 VDS 实际回答时，它仍会完整列出我的标准回复；传入 `--candidate-answers` 后会自动填充 VDS 回复并给出逐题 pass/fail。

也可以让脚本直接调用本地 VDS service 生成实际回复：

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_generic_dataset_eval.py \
  --dataset-name my_dataset \
  --files /path/to/file1.csv /path/to/file2.xlsx \
  --generate-vds-answers \
  --output-dir outputs/eval_gate/my_dataset_generic
```

这会额外输出 `vds_answers.jsonl`、`vds_answers.json`，并把实际回复自动写进 `comparison.md`。

### 每个验证数据集脚本

这些脚本默认会真实上传数据并调用本地 VDS service，输出我的标准回复、VDS 实际回复和逐题 comparison：

```bash
bash scripts/test_dataset_uk_retail.sh
bash scripts/test_dataset_health.sh
bash scripts/test_dataset_nyc_taxi.sh
bash scripts/test_dataset_brazilian_ecommerce.sh
bash scripts/test_dataset_microsoft_anonymized.sh
bash scripts/test_dataset_vds_sales.sh
bash scripts/test_dataset_vds_learning.sh
bash scripts/test_dataset_vds_medical.sh
bash scripts/test_dataset_vds_logistics.sh
bash scripts/test_dataset_vds_saas.sh
```

原 VDS 五份数据可以一次跑完：

```bash
bash scripts/test_dataset_vds_original_5.sh
```

全量验证数据集可以一次跑完：

```bash
bash scripts/test_all_validation_datasets.sh
```

如果只想快速验证标准答案、A-E 用例和报告结构，不调用 VDS 实际回复，可以加：

```bash
GENERATE_VDS=0 bash scripts/test_dataset_health.sh
```

微软脱敏数据还可以追加原 300 题标准 benchmark：

```bash
RUN_STANDARD_BENCHMARK=1 bash scripts/test_dataset_microsoft_anonymized.sh
```

### 1.5 GPT-like Parity Review

适用于所有会影响用户实际体验的修改，包括文件解析、字段画像、general 回答、正式分析回答、Insight、图表/表格、过程流、代码 artifact、Workbench 布局样式、按钮/面板密度和用户可见文案。

红线：验收人必须把 VDS 实际结果和 GPT / ChatGPT Data Analysis 的同类结果或已冻结的标准 GPT 参考结果并排看一遍，逐项回答：

1. GPT 会这样识别文件、sheet、表头、字段含义和数据质量问题吗？
2. GPT 会这样组织主回答、先后顺序、段落密度、表格/列表和下一步建议吗？
3. GPT 会选择这样的图表、代码展示、过程流和解释颗粒度吗？
4. Workbench 当前排版、间距、字体层级、展开态和移动端布局是否接近 GPT 的数据分析体验？

硬门槛：如果事实理解、回答结构、视觉层级、交互形态或可读性与 GPT 参考结果差距很大，本轮直接判失败，必须重写后再测。mock 单测、离线 scorer、browser smoke 和 `comparison.md` pass 只能作为证据之一，不能替代这一步人工/参考对比。

记录要求：提交或阶段汇报里必须写明参考来源、主要差距、已接受的差异和被打回重写的点；没有真实 GPT 参考时，必须明确使用的是标准 GPT answer workbook、冻结截图或 repo 内参考 artifact，不能冒充实时 GPT 结果。

### 2. Domain Extension Gate

当数据集有明确业务主题时，在 Generic Gate 通过后追加业务专项门禁。例如出租车双年度文件可以追加：

1. 同比分析：订单量、总收入、平均订单金额、增长驱动拆解。
2. 业务分析：热门上车区域、支付方式占比、机场相关订单、CBD 拥堵费。
3. 领域清洗策略：负金额、0 里程、非正时长、极端金额对同比结论的影响。

运行出租车专项示例：

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_taxi_dual_year_eval.py \
  --config configs/eval_gate/taxi_dual_year_eval.json \
  --output-dir outputs/eval_gate/taxi_domain
```

出租车专项只是一个 extension 示例，不代表所有数据集都必须具备机场、CBD、上车区域或支付方式字段。

## 验收维度

每条 case 不只看答案像不像，还要看：

- `route_correct`：是否走对 chat / overview / analysis / cleaning_simulation 路由。
- `grounded`：是否基于真实文件、字段、行列、缺失和统计事实。
- `user_value`：真实用户是否知道下一步怎么问。
- `risk_free`：无编造、无泄密、无 benchmark 标准答案混入、无自动清洗。
- `followup_ready`：是否能承接后续正式分析。
- `gpt_like_parity`：文件理解、回答结构、图表/表格、过程流和 Workbench 排版是否接近 GPT / ChatGPT Data Analysis 的同类体验。

硬门槛：

1. 无文件时不能编造数据结论。
2. 多文件时不能只看第一个文件。
3. 字段含义不确定时必须标记推测或需要业务确认。
4. 清洗只能模拟影响，不能直接修改源数据。
5. 标准答案只能在 response 生成后用于离线评分。
6. 领域专项必须在通用门禁后运行，不能替代通用门禁。
7. GPT-like parity review 差距很大时必须打回重写，不能把“功能跑通”当作体验完成。

## 当前 smoke 验证

2026-05-25 本地已验证：

- `outputs/eval_gate/script-smoke-final-uk_retail_generic`：35 cases，读取 541,909 行。
- `outputs/eval_gate/script-smoke-final-health_generic`：35 cases，读取 57,262 行。
- `outputs/eval_gate/script-smoke-final-nyc_taxi_generic`：35 cases，读取 7,200,115 行。
- `outputs/eval_gate/script-smoke-final-brazilian_ecommerce_generic`：35 cases，读取 1,550,922 行。
- `outputs/eval_gate/script-smoke-final-microsoft_anonymized_generic`：35 cases，读取 31,019 行。
- `outputs/eval_gate/script-smoke-final-vds_sales_generic`：35 cases，读取 1,200 行。
- `outputs/eval_gate/script-smoke-final-vds_learning_generic`：35 cases，读取 1,000 行。
- `outputs/eval_gate/script-smoke-final-vds_medical_generic`：35 cases，读取 720 行。
- `outputs/eval_gate/script-smoke-final-vds_logistics_generic`：35 cases，读取 720 行。
- `outputs/eval_gate/script-smoke-final-vds_saas_generic`：35 cases，读取 720 行。

以上 smoke 使用 `GENERATE_VDS=0`，只证明脚本能读取数据、生成 A-E 用例、生成标准回复和 comparison 结构。

2026-05-25 还完成了实际 VDS 回复模式验证：

- `outputs/eval_gate/actual-final-health_generic`：35 条 VDS 实际回复，严格规则得分 2/35。
- `outputs/eval_gate/actual-final-microsoft_anonymized_generic`：35 条 VDS 实际回复，严格规则得分 2/35。
- `outputs/eval_gate/actual-final-vds_sales_generic`：35 条 VDS 实际回复，严格规则得分 2/35。
- `outputs/eval_gate/actual-final-vds_learning_generic`：35 条 VDS 实际回复，严格规则得分 2/35。
- `outputs/eval_gate/actual-final-vds_medical_generic`：35 条 VDS 实际回复，严格规则得分 2/35。
- `outputs/eval_gate/actual-final-vds_logistics_generic`：35 条 VDS 实际回复，严格规则得分 2/35。
- `outputs/eval_gate/actual-final-vds_saas_generic`：35 条 VDS 实际回复，严格规则得分 2/35。

严格规则得分偏低时，优先打开对应 `comparison.md` 看逐题差距；当前 scorer 是关键词/数值门禁，不等同于语义 GPT judge。
