#!/usr/bin/env python3
"""Build the committed VDS real-user case manifest v1."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.real_user_eval.manifest import validate_v1_coverage


DEFAULT_OUTPUT = REPO_ROOT / "configs" / "eval_gate" / "real_user_case_manifest_v1.json"


DATASETS: dict[str, dict[str, Any]] = {
    "uk_retail": {
        "files": ["/Users/trevorcui/Desktop/验证数据集/UK retail/Online Retail.xlsx"],
        "table_names": ["uk_retail"],
        "domain": "retail",
    },
    "brazilian_ecommerce": {
        "files": [
            "/Users/trevorcui/Desktop/验证数据集/Brazilian E-Commerce Public Dataset/olist_customers_dataset.csv",
            "/Users/trevorcui/Desktop/验证数据集/Brazilian E-Commerce Public Dataset/olist_order_items_dataset.csv",
            "/Users/trevorcui/Desktop/验证数据集/Brazilian E-Commerce Public Dataset/olist_orders_dataset.csv",
            "/Users/trevorcui/Desktop/验证数据集/Brazilian E-Commerce Public Dataset/olist_products_dataset.csv",
            "/Users/trevorcui/Desktop/验证数据集/Brazilian E-Commerce Public Dataset/olist_order_payments_dataset.csv",
        ],
        "table_names": ["customers", "order_items", "orders", "products", "payments"],
        "domain": "ecommerce",
    },
    "nyc_taxi": {
        "files": [
            "/Users/trevorcui/Desktop/验证数据集/NYC Taxi/yellow_tripdata_2025-01.parquet",
            "/Users/trevorcui/Desktop/验证数据集/NYC Taxi/yellow_tripdata_2026-01.parquet",
        ],
        "table_names": ["taxi_2025_01", "taxi_2026_01"],
        "domain": "transportation",
    },
    "health_history": {
        "files": [
            "/Users/trevorcui/Desktop/验证数据集/Health历史数据_5.9/daily_metrics.csv",
            "/Users/trevorcui/Desktop/验证数据集/Health历史数据_5.9/workouts.csv",
            "/Users/trevorcui/Desktop/验证数据集/Health历史数据_5.9/monthly_metrics.csv",
        ],
        "table_names": ["daily_metrics", "workouts", "monthly_metrics"],
        "domain": "health",
    },
    "vds_sales": {
        "files": ["/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/数据/QueryGPT_销售数据_单表版.xlsx"],
        "table_names": ["vds_sales"],
        "domain": "sales",
    },
    "vds_saas": {
        "files": ["/Users/trevorcui/Desktop/Virtual Data Scientist测试数据/数据/QueryGPT_SaaS订阅数据_单表版.xlsx"],
        "table_names": ["vds_saas"],
        "domain": "saas",
    },
    "microsoft_anonymized": {
        "files": [
            "/Users/trevorcui/Desktop/微软脱敏数据/ads_trd_dist_ord_target_emp_1m_df.csv",
            "/Users/trevorcui/Desktop/微软脱敏数据/ads_trd_dist_ord_target_mgr_1m_df.csv",
            "/Users/trevorcui/Desktop/微软脱敏数据/v_trd_dist_ord_dtl.csv",
            "/Users/trevorcui/Desktop/微软脱敏数据/终端客户月度维表.csv",
        ],
        "table_names": ["emp_targets", "mgr_targets", "order_detail", "customer_month"],
        "domain": "enterprise_sales",
    },
}


def _case(
    slug: str,
    contract: str,
    family: str,
    sql: str,
    canonical: str,
    variants: list[str],
) -> dict[str, Any]:
    return {
        "case_id": slug,
        "capability_family": family,
        "canonical_question": canonical,
        "question_variants": variants,
        "expected_contract": contract,
        "oracle_type": "duckdb_sql",
        "oracle_query_or_formula": sql,
        "answer_requirements": {
            "answerability": "answerable",
            "must_use_oracle": True,
            "required_terms": [],
            "expected_numbers": [],
        },
        "severity": "p0" if family in {"join", "growth", "trend", "quality"} else "p1",
        "tags": [contract, family, "real_user_v1"],
        "metadata": {"expected_route": "real_user_analysis"},
    }


CASE_SPECS: dict[str, list[dict[str, Any]]] = {
    "uk_retail": [
        _case("overview_rows", "上传后概览", "overview", "SELECT count(*) AS row_count, count(DISTINCT InvoiceNo) AS invoice_count FROM {table_0}", "这个零售数据有多少行和多少订单？", ["这个表大概多少行？", "订单量是多少？", "先告诉我数据规模", "这个 retail 文件有多少记录？", "上传后先看行数和订单数"]),
        _case("top_country_revenue", "TopN", "topn_single_table", "SELECT Country, round(sum(Quantity * UnitPrice), 2) AS revenue FROM {table_0} GROUP BY Country ORDER BY revenue DESC LIMIT 5", "收入最高的国家是哪些？", ["哪个国家贡献最多销售额？", "按国家看 Top5 收入", "国家收入排行给我", "哪个 market 卖得最好？", "top country by revenue"]),
        _case("monthly_revenue", "趋势", "trend", "SELECT strftime(InvoiceDate, '%Y-%m') AS month, round(sum(Quantity * UnitPrice), 2) AS revenue FROM {table_0} GROUP BY month ORDER BY month LIMIT 12", "按月份看销售额趋势。", ["换成月份看收入", "销售额月度走势", "每个月 revenue 是多少？", "看一下月趋势", "month by month sales"]),
        _case("top_product_quantity", "TopN", "topn_single_table", "SELECT StockCode, Description, sum(Quantity) AS quantity FROM {table_0} GROUP BY StockCode, Description ORDER BY quantity DESC LIMIT 10", "卖出数量最多的商品是什么？", ["哪个 SKU 最热？", "Top product by quantity", "数量最多的商品排行", "最畅销产品是什么", "按销量列前十"]),
        _case("cancelled_orders", "质量检查", "quality", "SELECT count(*) AS cancelled_line_count FROM {table_0} WHERE CAST(InvoiceNo AS VARCHAR) LIKE 'C%'", "有多少取消订单记录？", ["取消订单有多少？", "InvoiceNo 以 C 开头的记录数", "退单/取消情况", "cancelled lines count", "看一下取消单规模"]),
        _case("negative_quantity", "清洗边界", "quality", "SELECT count(*) AS negative_quantity_rows FROM {table_0} WHERE Quantity < 0", "哪些记录数量为负，需要如何解释？", ["负数量有多少行？", "Quantity 小于 0 的情况", "这些负数是不是退货？", "清洗前先看负值数量", "negative quantity rows"]),
        _case("customer_concentration", "占比", "share", "SELECT CustomerID, round(sum(Quantity * UnitPrice), 2) AS revenue FROM {table_0} WHERE CustomerID IS NOT NULL GROUP BY CustomerID ORDER BY revenue DESC LIMIT 5", "收入最高的客户是谁？", ["Top 客户有哪些？", "客户收入排行", "哪个 CustomerID 贡献最高？", "top customers by revenue", "这些高价值客户是谁"]),
        _case("field_readiness", "字段识别", "field_mapping", "SELECT count(DISTINCT Country) AS country_count, count(DISTINCT StockCode) AS sku_count FROM {table_0}", "这个数据适合按哪些字段分析？", ["字段怎么分维度指标？", "能按国家和商品分析吗？", "有哪些维度可用？", "识别一下指标和维度", "哪些字段适合做下钻"]),
    ],
    "brazilian_ecommerce": [
        _case("order_status", "上传后概览", "overview", "SELECT order_status, count(*) AS orders FROM {table_2} GROUP BY order_status ORDER BY orders DESC", "订单状态分布是什么？", ["各状态订单数", "delivered/canceled 分别多少？", "先看订单状态", "订单履约状态分布", "status breakdown"]),
        _case("top_state_orders", "TopN", "join", "SELECT c.customer_state, count(*) AS orders FROM {table_2} o JOIN {table_0} c ON o.customer_id = c.customer_id GROUP BY c.customer_state ORDER BY orders DESC LIMIT 10", "哪个州订单最多？", ["按州看订单 Top10", "哪个 state 需求最大？", "客户州分布排行", "state order ranking", "订单最多的地区"]),
        _case("gmv", "指标汇总", "single_table_aggregation", "SELECT round(sum(price), 2) AS item_gmv, round(sum(freight_value), 2) AS freight FROM {table_1}", "商品金额和运费总额是多少？", ["GMV 和 freight 各多少？", "订单明细金额汇总", "总销售额是多少", "item price sum", "运费规模"]),
        _case("top_category", "多文件 join", "join", "SELECT p.product_category_name, round(sum(i.price), 2) AS revenue FROM {table_1} i JOIN {table_3} p ON i.product_id = p.product_id GROUP BY p.product_category_name ORDER BY revenue DESC LIMIT 10", "收入最高的商品类目是什么？", ["Top category by revenue", "品类销售额排行", "哪个类目最赚钱？", "product category top10", "按品类看销售额"]),
        _case("delivery_delay", "质量检查", "quality", "SELECT count(*) AS late_orders FROM {table_2} WHERE order_delivered_customer_date > order_estimated_delivery_date", "有多少订单晚于预计送达？", ["延迟交付订单数", "late delivery 有多少", "哪些订单超过预计日期？", "配送时效问题", "late orders count"]),
        _case("delivery_days", "趋势/时长", "trend", "SELECT round(avg(date_diff('day', order_purchase_timestamp::TIMESTAMP, order_delivered_customer_date::TIMESTAMP)), 2) AS avg_delivery_days FROM {table_2} WHERE order_delivered_customer_date IS NOT NULL", "平均配送天数是多少？", ["平均多久送到？", "下单到签收几天", "delivery days average", "履约周期均值", "送达时长"]),
        _case("payment_mix", "占比", "share", "SELECT payment_type, count(*) AS payments, round(sum(payment_value), 2) AS value FROM {table_4} GROUP BY payment_type ORDER BY value DESC", "不同支付方式金额占比如何？", ["支付方式结构", "信用卡和 boleto 哪个多？", "payment mix", "按 payment_type 汇总", "支付金额排行"]),
        _case("multi_file_keys", "多文件 join", "join", "SELECT count(DISTINCT order_id) AS order_ids_in_items, count(DISTINCT product_id) AS products_in_items FROM {table_1}", "这些文件可以用哪些 key 关联？", ["多文件怎么 join？", "order_id product_id 能连哪些表？", "关联键检查", "join key readiness", "多表关系怎么看"]),
    ],
    "nyc_taxi": [
        _case("row_compare", "上传后概览", "overview", "SELECT '2025-01' AS month, count(*) AS trips FROM {table_0} UNION ALL SELECT '2026-01', count(*) FROM {table_1}", "2025 年 1 月和 2026 年 1 月各有多少行程？", ["两年一月行程量对比", "2025 vs 2026 trip count", "哪个月记录更多？", "两份 taxi 文件规模", "行程数对比"]),
        _case("revenue_compare", "增长", "growth", "SELECT '2025-01' AS month, round(sum(total_amount), 2) AS total_amount FROM {table_0} UNION ALL SELECT '2026-01', round(sum(total_amount), 2) FROM {table_1}", "两年 1 月 total_amount 对比如何？", ["总金额同比看一下", "2026 比 2025 多多少？", "total amount comparison", "出租车收入对比", "金额增长"]),
        _case("top_pickup", "TopN", "topn_single_table", "SELECT PULocationID, count(*) AS trips FROM {table_1} GROUP BY PULocationID ORDER BY trips DESC LIMIT 10", "2026 年最热门上车区域是哪里？", ["Top pickup zones", "PULocationID 排行", "哪个上车点最多？", "2026 pickup top10", "热门上车区域"]),
        _case("payment_type", "占比", "share", "SELECT payment_type, count(*) AS trips, round(sum(total_amount), 2) AS total_amount FROM {table_1} GROUP BY payment_type ORDER BY trips DESC", "2026 年支付方式分布是什么？", ["payment_type 结构", "现金和刷卡占比", "支付方式排行", "按 payment type 汇总", "payment mix"]),
        _case("avg_tip", "指标汇总", "single_table_aggregation", "SELECT round(avg(tip_amount), 2) AS avg_tip, round(avg(total_amount), 2) AS avg_total FROM {table_1}", "平均小费和平均总金额是多少？", ["avg tip 是多少", "平均 total_amount", "小费水平", "每单平均金额", "tip amount average"]),
        _case("long_trips", "过滤", "filtering", "SELECT count(*) AS long_trip_count FROM {table_1} WHERE trip_distance >= 20", "20 英里以上长途行程有多少？", ["长距离行程数量", "trip_distance >=20", "long trips count", "长途订单", "筛选 20 miles 以上"]),
        _case("negative_amount", "质量检查", "quality", "SELECT count(*) AS negative_total_rows FROM {table_1} WHERE total_amount < 0", "是否有 total_amount 为负的异常记录？", ["负金额记录数", "total_amount < 0", "异常金额检查", "退款或冲正有多少", "negative total rows"]),
        _case("airport_fee", "字段识别", "field_mapping", "SELECT count(*) AS airport_fee_rows, round(sum(Airport_fee), 2) AS airport_fee_sum FROM {table_1} WHERE Airport_fee > 0", "Airport_fee 字段反映了什么规模？", ["机场费有多少记录", "Airport_fee 总额", "机场相关费用", "airport fee rows", "这个字段怎么理解"]),
    ],
    "health_history": [
        _case("daily_range", "上传后概览", "overview", "SELECT min(date) AS start_date, max(date) AS end_date, count(*) AS days FROM {table_0}", "健康日指标覆盖什么时间范围？", ["这些 health 数据从哪天到哪天？", "日数据有多少天", "时间范围", "daily metrics range", "覆盖周期"]),
        _case("steps_month", "趋势", "trend", "SELECT month, round(avg(steps), 2) AS avg_steps FROM {table_2} WHERE steps IS NOT NULL GROUP BY month ORDER BY month LIMIT 12", "每月平均步数趋势如何？", ["月度步数走势", "steps by month", "哪个月步数高？", "平均步数趋势", "换成月份看"]),
        _case("active_energy", "指标汇总", "single_table_aggregation", "SELECT round(avg(active_energy_kcal), 2) AS avg_active_energy FROM {table_0} WHERE active_energy_kcal IS NOT NULL", "平均每日活动能量是多少？", ["active energy 平均值", "每天消耗多少活动热量", "活动能量均值", "avg active kcal", "健康能量指标"]),
        _case("sleep_quality", "字段识别", "field_mapping", "SELECT round(avg(sleep_asleep_hours), 2) AS avg_sleep_asleep, round(avg(sleep_in_bed_hours), 2) AS avg_sleep_in_bed FROM {table_0} WHERE sleep_asleep_hours IS NOT NULL", "平均睡眠时长是多少？", ["睡眠数据怎么看？", "asleep hours 平均", "睡了多久", "sleep average", "睡眠概览"]),
        _case("workout_type", "TopN", "topn_single_table", "SELECT type, count(*) AS workouts, round(sum(duration_min), 2) AS total_minutes FROM {table_1} GROUP BY type ORDER BY workouts DESC LIMIT 10", "最多的运动类型是什么？", ["workout 类型排行", "哪种运动最多", "运动次数 Top", "type by workouts", "运动结构"]),
        _case("heart_rate", "指标汇总", "single_table_aggregation", "SELECT round(avg(heart_rate_bpm_avg), 2) AS avg_hr, round(min(heart_rate_bpm_min), 2) AS min_hr, round(max(heart_rate_bpm_max), 2) AS max_hr FROM {table_0}", "心率指标大概是什么水平？", ["平均心率", "heart rate summary", "最低最高心率", "心率概览", "hr 指标"]),
        _case("missing_sleep", "质量检查", "quality", "SELECT count(*) AS missing_sleep_days FROM {table_0} WHERE sleep_asleep_hours IS NULL", "睡眠字段缺失了多少天？", ["睡眠缺失天数", "sleep_asleep_hours 为空", "数据质量检查", "missing sleep", "哪些天没睡眠数据"]),
        _case("distance_workouts", "过滤", "filtering", "SELECT count(*) AS distance_workouts, round(sum(distance_km), 2) AS total_distance FROM {table_1} WHERE distance_km > 0", "有距离记录的运动有多少，总距离多少？", ["有里程的 workouts", "distance_km 汇总", "运动距离总计", "distance workouts", "跑步骑行距离"]),
    ],
    "vds_sales": [
        _case("sales_overview", "上传后概览", "overview", "SELECT count(*) AS rows, round(sum(\"销售额\"), 2) AS sales, round(sum(\"利润\"), 2) AS profit FROM {table_0}", "销售数据整体规模和金额是多少？", ["总销售额和利润", "先看销售概览", "这个销售表多少行", "sales overview", "整体营收"]),
        _case("region_sales", "TopN", "topn_single_table", "SELECT \"区域\", round(sum(\"销售额\"), 2) AS sales FROM {table_0} GROUP BY \"区域\" ORDER BY sales DESC LIMIT 10", "哪个区域销售额最高？", ["区域销售排行", "Top region by sales", "按区域汇总销售额", "哪个地区卖得最好", "区域 TopN"]),
        _case("city_profit", "TopN", "topn_single_table", "SELECT \"城市\", round(sum(\"利润\"), 2) AS profit FROM {table_0} GROUP BY \"城市\" ORDER BY profit DESC LIMIT 10", "利润最高的城市是哪些？", ["城市利润排行", "top city by profit", "哪些城市最赚钱", "按城市看利润", "利润 Top 城市"]),
        _case("channel_sales", "占比", "share", "SELECT \"来源渠道\", round(sum(\"销售额\"), 2) AS sales FROM {table_0} GROUP BY \"来源渠道\" ORDER BY sales DESC", "不同来源渠道销售额如何？", ["渠道销售额占比", "来源渠道排行", "channel performance", "哪个渠道贡献高", "按渠道汇总"]),
        _case("monthly_sales", "趋势", "trend", "SELECT \"月份\", round(sum(\"销售额\"), 2) AS sales FROM {table_0} GROUP BY \"月份\" ORDER BY \"月份\"", "按月份看销售额趋势。", ["月销售趋势", "换成月份看", "monthly sales", "每月销售额", "月份走势"]),
        _case("discount_effect", "过滤", "filtering", "SELECT round(avg(\"折扣率\"), 4) AS avg_discount, round(sum(\"销售额\"), 2) AS sales FROM {table_0}", "折扣率整体水平和销售额是什么关系？", ["平均折扣率", "discount 情况", "折扣和销售", "折扣水平", "折扣字段怎么看"]),
        _case("status_sales", "字段识别", "field_mapping", "SELECT \"状态\", count(*) AS records, round(sum(\"销售额\"), 2) AS sales FROM {table_0} GROUP BY \"状态\" ORDER BY records DESC", "不同状态的记录分布是什么？", ["状态字段分布", "完成和未完成多少", "按状态看销售额", "status breakdown", "状态口径"]),
        _case("profit_margin", "增长/占比", "share", "SELECT round(sum(\"利润\") / nullif(sum(\"销售额\"), 0), 4) AS profit_margin FROM {table_0}", "整体利润率是多少？", ["毛利率/利润率", "利润除以销售额", "profit margin", "整体赚钱效率", "利润率口径"]),
    ],
    "vds_saas": [
        _case("saas_overview", "上传后概览", "overview", "SELECT count(*) AS rows, round(sum(\"订阅收入\"), 2) AS revenue, round(sum(\"毛利\"), 2) AS gross_profit FROM {table_0}", "SaaS 订阅数据整体收入和毛利是多少？", ["SaaS 概览", "订阅收入总额", "这个表规模", "revenue and gross profit", "收入毛利汇总"]),
        _case("product_line", "TopN", "topn_single_table", "SELECT \"产品线\", round(sum(\"订阅收入\"), 2) AS revenue FROM {table_0} GROUP BY \"产品线\" ORDER BY revenue DESC LIMIT 10", "哪个产品线订阅收入最高？", ["产品线收入排行", "top product line", "按产品线汇总", "哪个产品线最强", "产品线 TopN"]),
        _case("customer_type", "占比", "share", "SELECT \"客户类型\", count(*) AS customers, round(sum(\"订阅收入\"), 2) AS revenue FROM {table_0} GROUP BY \"客户类型\" ORDER BY revenue DESC", "不同客户类型收入结构如何？", ["客户类型占比", "企业客户和个人客户", "customer type mix", "按客户类型看收入", "客户结构"]),
        _case("channel_revenue", "TopN", "topn_single_table", "SELECT \"获客渠道\", round(sum(\"订阅收入\"), 2) AS revenue FROM {table_0} GROUP BY \"获客渠道\" ORDER BY revenue DESC", "获客渠道收入排行是什么？", ["渠道收入", "获客渠道 top", "channel revenue", "哪个渠道带来收入", "渠道结构"]),
        _case("monthly_revenue", "趋势", "trend", "SELECT \"月份\", round(sum(\"订阅收入\"), 2) AS revenue FROM {table_0} GROUP BY \"月份\" ORDER BY \"月份\"", "按月份看订阅收入趋势。", ["月度订阅收入", "换成月份看 revenue", "monthly saas revenue", "收入走势", "月份趋势"]),
        _case("nps", "字段识别", "field_mapping", "SELECT round(avg(\"NPS评分\"), 2) AS avg_nps FROM {table_0} WHERE \"NPS评分\" IS NOT NULL", "NPS 平均水平是多少？", ["平均 NPS", "客户满意度", "NPS score", "评分水平", "NPS 字段怎么看"]),
        _case("subscription_status", "过滤", "filtering", "SELECT \"订阅状态\", count(*) AS records, round(sum(\"订阅收入\"), 2) AS revenue FROM {table_0} GROUP BY \"订阅状态\" ORDER BY records DESC", "不同订阅状态的收入和记录数是什么？", ["订阅状态分布", "活跃和流失多少", "subscription status", "按状态看收入", "状态口径"]),
        _case("gross_margin", "占比", "share", "SELECT round(sum(\"毛利\") / nullif(sum(\"订阅收入\"), 0), 4) AS gross_margin FROM {table_0}", "整体毛利率是多少？", ["毛利率", "毛利除以订阅收入", "gross margin", "SaaS 盈利效率", "整体 margin"]),
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build real-user case manifest v1.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()
    manifest = build_manifest()
    summary = validate_v1_coverage(manifest)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.print_summary:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"output": str(output), **summary}, ensure_ascii=False))


def build_manifest() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for dataset, specs in CASE_SPECS.items():
        for spec in specs:
            cases.append({**spec, "case_id": f"{dataset}__{spec['case_id']}", "dataset": dataset})
    return {
        "name": "real_user_case_manifest_v1",
        "version": 1,
        "policy": {
            "surface": "api_or_service_only",
            "oracle_visibility": "offline_only_never_sent_to_agent",
            "random_testing_role": "exploratory_fuzz_not_acceptance_evidence",
        },
        "datasets": DATASETS,
        "cases": cases,
        "conversations": _conversation_flows(),
    }


def _conversation_flows() -> list[dict[str, Any]]:
    flows = []
    for dataset, specs in CASE_SPECS.items():
        selected = specs[:4]
        for index, first_case in enumerate(selected, start=1):
            second_case = specs[(index + 1) % len(specs)]
            third_case = specs[(index + 3) % len(specs)]
            flows.append(
                {
                    "conversation_id": f"{dataset}_flow_{index:02d}",
                    "dataset": dataset,
                    "capability_family": "followup_context",
                    "severity": "p0",
                    "tags": ["conversation", "followup", "real_user_v1"],
                    "turns": [
                        _turn("turn_01", first_case["canonical_question"], first_case),
                        _turn("turn_02", "这个结果换一个相关维度继续看。", second_case),
                        _turn("turn_03", "刚才口径不够清楚，按源文件重新验算后给结论和边界。", third_case),
                    ],
                    "metadata": {
                        "expected_context_reuse": True,
                        "requires_same_conversation_id": True,
                    },
                }
            )
    return flows


def _turn(turn_id: str, question: str, case: dict[str, Any]) -> dict[str, Any]:
    return {
        "turn_id": turn_id,
        "question": question,
        "expected_contract": case["expected_contract"],
        "oracle_type": case["oracle_type"],
        "oracle_query_or_formula": case["oracle_query_or_formula"],
        "answer_requirements": case["answer_requirements"],
    }


if __name__ == "__main__":
    main()
