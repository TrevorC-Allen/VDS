# 2026-06-06 13:10 CST - UK retail real API semantic binding smoke

## 测试目标

验证真实 HTTP API 在 UK retail Excel 数据上的通用语义绑定修复：商品/客户/国家/月度维度推断、显式 `Quantity * UnitPrice` 公式、退货负数量口径、订单 distinct count、连续追问继承 Top 商品上下文，以及语义失败不再暴露为 HTTP 500。

## 环境

- 仓库：`/Users/trevorcui/Documents/VDS-canonical-semantic-contract`
- 分支：`codex/vds-canonical-semantic-contract`
- 服务：`http://127.0.0.1:8876`
- 启动命令：`VDS_WORKBENCH_PORT=8876 VDS_WORKBENCH_HOST=127.0.0.1 VDS_LLM_PROVIDER=mock ./scripts/run_workbench_server.sh`
- 数据：`/Users/trevorcui/Desktop/验证数据集/UK retail/Online Retail.xlsx`
- 结果文件：`/tmp/vds-uk-retail-api-20260606-130839/results_after_fix.json`

## 测试问题与结果

| 模式 | 问题 | HTTP | success | semantic_status | 关键结果 |
| --- | --- | ---: | --- | --- | --- |
| 独立 | 这个 UK retail 数据的总销售额是多少？销售额按 Quantity * UnitPrice 算。 | 200 | true | passed | `Sales=9,747,747.93`，无维度，trace formula=`Quantity * UnitPrice` |
| 独立 | 销售额最高的前5个商品是什么？销售额按 Quantity * UnitPrice 算。 | 200 | true | passed | `dimension=Description`，Top5 商品返回，trace formula=`Quantity * UnitPrice` |
| 独立 | 订单数量最多的前5个客户是谁？ | 200 | true | passed | `dimension=CustomerID`，`metric=InvoiceNo`，`aggregation=nunique` |
| 独立 | 退货数量最多的前5个商品是什么？ | 200 | true | passed | `dimension=Description`，`Quantity < 0`，`aggregation=sum_abs` |
| 独立 | 按月份看整体销售额趋势，哪些月份最高？ | 200 | true | passed | `dimension=month`，`time_column=InvoiceDate`，trace formula=`Quantity * UnitPrice` |
| 独立 | 按 Description 分组，销售额最高的前5个 Description 是什么？销售额按 Quantity * UnitPrice 算。 | 200 | true | passed | 显式字段探针继续通过 |
| 连续 1 | 先看一下这个 UK retail 数据，告诉我有哪些主要字段、行数，以及明显的数据质量问题。 | 200 | true | passed | overview/quality 输出成功 |
| 连续 2 | 销售额最高的前5个商品是什么？销售额按 Quantity * UnitPrice 算。 | 200 | true | passed | Top5 商品输出成功 |
| 连续 3 | 这些 Top 商品主要卖给哪些国家？分别列出主要国家和销售额。 | 200 | true | passed | `referent_dimension=Description`，`dimension=Country`，答案为“Top5 产品内，国家销售额排名” |

## GPT-like 判定

- 语义：符合 GPT Data Analysis 对同类问题的基本口径，应把“商品”绑定到可读商品标签，销售额按用户显式公式计算，并在追问里继承上一轮 Top 商品集合。
- 结构：返回直接结果、口径和可复核字段；没有用 `success=true` 掩盖 verifier failure。
- 可读性：追问答案已避免把 Top 商品误写为“城市”，但部分通用文案仍保留 `Sales`、`Quantity` 等字段名，属于后续本地化润色空间。

## Not Applicable / 能力族归因

- 本次不涉及 benchmark runner、官方 scorer 或标准答案。
- 能力族：generic semantic binding、explicit formula、ranking dimension inference、return quantity ranking、monthly time-series、drilldown follow-up、API error mapping。

## 后续动作

- 继续保留 RFM、国家 Quantity 贡献、CustomerID 缺失影响等 Retail Product Floor 既有 xfail，不在本轮扩大范围。
- 如后续要进一步 GPT-like 化，可单独收敛销售额/退货数量/月份趋势的中文标签和第一屏格式。
