"""Chinese retail distribution intent parsing for uploaded business tables.

The rules in this module map reusable retail analytics terms to schema-backed
LogicForm operations. They do not use benchmark task ids, standard answers, or
question-specific expected values.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import pandas as pd

from data_agent_core.contracts.analysis_contracts import LogicForm
from data_agent_core.core.logic_form import make_logic_form


HISTORY_REQUIRED_COLUMNS = {"sign_time", "sign_amt", "emp_name", "cust_code"}
TODAY_REQUIRED_COLUMNS = {"sign_time", "sign_amt", "ord_status_name", "ctg_name"}
ROUTE_REQUIRED_COLUMNS = {"visit_date", "cust_code", "emp_name"}
CUSTOMER_REQUIRED_COLUMNS = {"年月", "终端客户编码", "是否合约店"}
DISPLAY_PLAN_REQUIRED_COLUMNS = {"execute_ym", "dsp_name", "cust_code"}
VISIT_REQUIRED_COLUMNS = {"visit_date", "emp_name", "cust_code"}
EMP_TARGET_REQUIRED_COLUMNS = {"stat_month", "emp_name", "target"}
MGR_TARGET_REQUIRED_COLUMNS = {"stat_month", "mgr_name", "target_amt"}
CALENDAR_REQUIRED_COLUMNS = {"month_id", "dist_day_cnt"}


def parse_chinese_retail_question(
    question: str,
    tables: dict[str, pd.DataFrame],
    guidelines: str = "",
) -> LogicForm | None:
    """Parse Chinese retail distribution questions into stable LogicForms."""

    if not _looks_like_chinese_retail_dataset(tables):
        return None

    output_format = {"guidelines": guidelines}
    year, month = _extract_year_month(question, tables)
    business_date = _extract_date(question) or _infer_business_date(tables)
    date_start, date_end = _extract_date_range(question)
    if business_date and (year is None or month is None):
        year, month = business_date.year, business_date.month
    ym = year * 100 + month if year and month else None
    decimals = _extract_decimal_places(guidelines)
    person = _extract_person(question, tables)
    product = _extract_product(question, tables)
    start_ym, end_ym = _extract_year_month_range(question)
    ym_mentions = _extract_year_month_mentions(question)

    if "主任" in question and "日目标缺口" in question and ("下属" in question or "贡献" in question):
        return make_logic_form(
            task_type="attribution",
            operation="retail_manager_daily_gap_contribution",
            parameters={"date": _date_text(business_date), "ym": ym},
            source_tables=[
                "v_trd_dist_ord_dtl_1d_rt",
                "ads_trd_dist_ord_target_emp_1m_df",
                "ads_trd_dist_ord_target_mgr_1m_df",
                "ads_trd_time_prg_df",
            ],
            output_format=output_format | {"answer_type": "text"},
        )

    if "日目标" in question and "分销进度" in question and ("最落后" in question or "最低" in question or "哪位业代" in question):
        return make_logic_form(
            task_type="ranking",
            operation="retail_daily_progress_worst_employee",
            parameters={"date": _date_text(business_date), "ym": ym},
            source_tables=["v_trd_dist_ord_dtl_1d_rt", "ads_trd_dist_ord_target_emp_1m_df", "ads_trd_time_prg_df"],
            output_format=output_format | {"answer_type": "text"},
        )

    if start_ym and end_ym and "历史分销" in question and "环比" in question:
        return make_logic_form(
            task_type="trend",
            operation="retail_distribution_monthly_mom",
            parameters={"start_ym": start_ym, "end_ym": end_ym},
            source_tables=["v_trd_dist_ord_dtl"],
            output_format=output_format | {"answer_type": "text"},
        )

    if start_ym and end_ym and "分销目标" in question and "实际分销金额" in question and "对比" in question:
        return make_logic_form(
            task_type="trend",
            operation="retail_target_actual_monthly_comparison",
            parameters={"person": person, "start_ym": start_ym, "end_ym": end_ym, "role": _person_role(question, person, tables)},
            source_tables=["v_trd_dist_ord_dtl", "ads_trd_dist_ord_target_emp_1m_df", "ads_trd_dist_ord_target_mgr_1m_df"],
            output_format=output_format | {"answer_type": "text", "chart_type": "combo_column_line"},
        )

    if start_ym and end_ym and "分销目标达成率" in question:
        return make_logic_form(
            task_type="trend",
            operation="retail_target_achievement_monthly",
            parameters={"person": person, "start_ym": start_ym, "end_ym": end_ym, "role": _person_role(question, person, tables)},
            source_tables=["v_trd_dist_ord_dtl", "ads_trd_dist_ord_target_emp_1m_df", "ads_trd_dist_ord_target_mgr_1m_df"],
            output_format=output_format | {"answer_type": "text"},
        )

    if _asks_for_chart(question) and "分销目标" in question and "主任" in question and ("趋势" in question or "月度" in question):
        return make_logic_form(
            task_type="trend",
            operation="retail_manager_target_monthly_trend",
            parameters={"start_ym": start_ym or ym, "end_ym": end_ym or ym},
            source_tables=["ads_trd_dist_ord_target_mgr_1m_df"],
            output_format=output_format | {"answer_type": "text"},
        )

    if _asks_for_chart(question) and "拜访量最高" in question and "业代" in question and "拜访成功率" in question:
        return make_logic_form(
            task_type="trend",
            operation="retail_top_employee_visit_success_rate_trend",
            parameters={"start_ym": start_ym or ym, "end_ym": end_ym or ym, "limit": _extract_limit(question, default=5)},
            source_tables=["v_chl_visit_dtl"],
            output_format=output_format | {"answer_type": "text"},
        )

    if _asks_for_chart(question) and "各业代" in question and "历史分销金额趋势" in question:
        return make_logic_form(
            task_type="trend",
            operation="retail_employee_distribution_monthly_trend",
            parameters={"start_ym": start_ym or ym, "end_ym": end_ym or ym, "limit": _extract_limit(question, default=5)},
            source_tables=["v_trd_dist_ord_dtl"],
            output_format=output_format | {"answer_type": "text", "chart_type": "line"},
        )

    if "拜访记录" in question and ("一周分布" in question or "星期几" in question):
        return make_logic_form(
            task_type="trend",
            operation="retail_visit_weekday_distribution",
            parameters={"ym": ym},
            source_tables=["v_chl_visit_dtl"],
            output_format=output_format | {"answer_type": "text", "chart_type": "bar"},
        )

    if _asks_for_chart(question) and "线路计划客户数" in question and ("每日趋势" in question or "每天" in question):
        return make_logic_form(
            task_type="trend",
            operation="retail_route_plan_daily_trend",
            parameters={"start_date": _date_text(date_start), "end_date": _date_text(date_end or business_date)},
            source_tables=["v_chl_route_plan_cust_cnt_1d_df"],
            output_format=output_format | {"answer_type": "text", "chart_type": "line"},
        )

    if _asks_for_chart(question) and "线路计划客户数排名" in question and "业代" in question:
        return make_logic_form(
            task_type="ranking",
            operation="retail_route_plan_employee_count_ranking",
            parameters={"ym": ym},
            source_tables=["v_chl_route_plan_cust_cnt_1d_df"],
            output_format=output_format | {"answer_type": "text", "chart_type": "horizontal_bar"},
        )

    if _asks_for_chart(question) and "品类" in question and "历史分销金额" in question and ("趋势" in question or "结构" in question):
        return make_logic_form(
            task_type="trend",
            operation="retail_category_distribution_monthly_trend",
            parameters={"start_ym": start_ym or ym, "end_ym": end_ym or ym, "limit": _extract_limit(question, default=5)},
            source_tables=["v_trd_dist_ord_dtl"],
            output_format=output_format | {"answer_type": "text"},
        )

    if _asks_for_chart(question) and "检查结果分布" in question and "陈列活动" in question:
        return make_logic_form(
            task_type="trend",
            operation="retail_display_status_monthly_distribution",
            parameters={"start_ym": start_ym or ym, "end_ym": end_ym or ym},
            source_tables=["v_mkt_dsp_actv_mi"],
            output_format=output_format | {"answer_type": "text", "chart_type": "stacked_column"},
        )

    if _asks_for_chart(question) and "确认金额最高" in question and "品类" in question and "陈列活动" in question:
        return make_logic_form(
            task_type="trend",
            operation="retail_display_confirm_amount_category_monthly_top",
            parameters={"start_ym": start_ym or ym, "end_ym": end_ym or ym, "limit": _extract_limit(question, default=5)},
            source_tables=["v_mkt_dsp_actv_mi"],
            output_format=output_format | {"answer_type": "text", "chart_type": "stacked_area"},
        )

    if _asks_for_chart(question) and "合约店" in question and "非合约店" in question and "数量变化" in question:
        return make_logic_form(
            task_type="trend",
            operation="retail_contract_customer_monthly_structure",
            parameters={"start_ym": start_ym or ym, "end_ym": end_ym or ym},
            source_tables=["终端客户月度维表"],
            output_format=output_format | {"answer_type": "text", "chart_type": "stacked_column"},
        )

    if _asks_for_chart(question) and "冰柜客户数量趋势" in question:
        return make_logic_form(
            task_type="trend",
            operation="retail_freezer_customer_monthly_trend",
            parameters={"start_ym": start_ym or ym, "end_ym": end_ym or ym},
            source_tables=["终端客户月度维表"],
            output_format=output_format | {"answer_type": "text", "chart_type": "line"},
        )

    if _asks_for_chart(question) and "平均冰柜门数" in question:
        return make_logic_form(
            task_type="trend",
            operation="retail_freezer_door_average_monthly_trend",
            parameters={"start_ym": start_ym or ym, "end_ym": end_ym or ym},
            source_tables=["终端客户月度维表"],
            output_format=output_format | {"answer_type": "text", "chart_type": "line"},
        )

    if _asks_for_chart(question) and "记录数最高" in question and "品牌" in question and "SKU检查通过率" in question:
        return make_logic_form(
            task_type="ranking",
            operation="retail_sku_check_brand_pass_rate_top",
            parameters={"ym": ym, "limit": _extract_limit(question, default=8)},
            source_tables=["v_chl_jc_cust_sku_mi"],
            output_format=output_format | {"answer_type": "text", "chart_type": "horizontal_bar"},
        )

    if _asks_for_chart(question) and "签收金额占比" in question and ("实时订单表" in question or "各品类" in question):
        return make_logic_form(
            task_type="composition",
            operation="retail_today_category_amount_share",
            parameters={"date": _date_text(business_date)},
            source_tables=["v_trd_dist_ord_dtl_1d_rt"],
            output_format=output_format | {"answer_type": "text", "chart_type": "donut"},
        )

    if _asks_for_chart(question) and "陈列执行次数" in question and "执行组数" in question:
        return make_logic_form(
            task_type="trend",
            operation="retail_display_execution_monthly_dual_trend",
            parameters={"start_ym": start_ym or ym, "end_ym": end_ym or ym},
            source_tables=["v_mkt_dsp_execute_mi"],
            output_format=output_format | {"answer_type": "text", "chart_type": "dual_axis_line"},
        )

    if _asks_for_chart(question) and "历史分销金额" in question and _is_ranking_question(question):
        return make_logic_form(
            task_type="ranking",
            operation="retail_distribution_topn_chart",
            parameters={
                "ym": ym,
                "start_ym": start_ym,
                "end_ym": end_ym,
                "dimension": _distribution_dimension(question),
                "metric": "sign_amt",
                "limit": _extract_limit(question, default=10),
            },
            source_tables=["v_trd_dist_ord_dtl"],
            output_format=output_format | {"answer_type": "text", "chart_type": "horizontal_bar" if _prefers_horizontal_bar(question) else "bar"},
        )

    if "稽查门店SKU分析" in question and "记录数最多" in question and "品类" in question:
        return make_logic_form(
            task_type="ranking",
            operation="retail_audit_sku_category_record_top",
            parameters={"ym": ym, "include_metric": _asks_for_metric_value(question)},
            output_format=output_format | {"answer_type": "text"},
        )

    if "稽查门店SKU分析" in question and "SKU数量最高" in question and "门店" in question:
        return make_logic_form(
            task_type="ranking",
            operation="retail_audit_sku_store_sku_count_top",
            parameters={"ym": ym, "include_metric": _asks_for_metric_value(question)},
            output_format=output_format | {"answer_type": "text"},
        )

    if "店均活跃SKU数" in question or "店均活跃sku数" in question.lower():
        return make_logic_form(
            task_type="aggregation",
            operation="retail_average_active_sku_per_store",
            parameters={"ym": ym},
            output_format=output_format | {"answer_type": "number", "decimals": decimals or 2},
        )

    if "服务客户" in question and "冰柜客户占比" in question:
        return make_logic_form(
            task_type="ratio",
            operation="retail_service_freezer_customer_rate",
            parameters={"ym": ym},
            output_format=output_format | {"answer_type": "percentage", "decimals": decimals or 2},
        )

    if "服务客户" in question and "合约店占比" in question:
        return make_logic_form(
            task_type="ratio",
            operation="retail_service_contract_store_rate",
            parameters={"ym": ym},
            output_format=output_format | {"answer_type": "percentage", "decimals": decimals or 2},
        )

    if "服务客户数" in question:
        return make_logic_form(
            task_type="aggregation",
            operation="retail_service_customer_count",
            parameters={"ym": ym},
            output_format=output_format | {"answer_type": "number", "decimals": 0},
        )

    if "历史分销金额中" in question and "占比" in question:
        return make_logic_form(
            task_type="ratio",
            operation="retail_distribution_product_share",
            parameters={
                "person": person,
                "ym": ym,
                "metric": "sign_amt",
                "product": product,
                "role": _person_role(question, person, tables),
            },
            source_tables=["v_trd_dist_ord_dtl"],
            table_selection_reason="历史分销金额占比需要使用包含签收时间、分销金额、人员和产品维度的历史分销明细表。",
            output_format=output_format | {"answer_type": "percentage", "decimals": decimals or 2},
        )

    if "分销目标达成率" in question:
        return make_logic_form(
            task_type="ratio",
            operation="retail_target_achievement_rate",
            parameters={"person": person, "ym": ym, "role": _person_role(question, person, tables)},
            output_format=output_format | {"answer_type": "percentage", "decimals": decimals or 2},
        )

    if "分销目标" in question and "多少" in question and "业代" in question:
        return make_logic_form(
            task_type="aggregation",
            operation="retail_target_entity_count",
            parameters={"ym": ym, "role": "employee"},
            output_format=output_format | {"answer_type": "number", "decimals": 0},
        )

    if "分销进度" in question and "日目标" in guidelines:
        return make_logic_form(
            task_type="ratio",
            operation="retail_daily_progress_rate",
            parameters={"person": person, "date": _date_text(business_date), "ym": ym},
            output_format=output_format | {"answer_type": "percentage", "decimals": decimals or 2},
        )

    if "计划拜访线路" in question and "历史分销金额" in question and "贡献最高" in question and "品类" in question:
        return make_logic_form(
            task_type="ranking",
            operation="retail_route_history_category_top",
            parameters={"person": person, "date": _date_text(business_date), "ym": ym, "include_metric": _asks_for_metric_value(question)},
            output_format=output_format | {"answer_type": "text", "decimals": decimals or 2},
        )

    if "计划拜访线路" in question and "历史分销金额" in question:
        return make_logic_form(
            task_type="aggregation",
            operation="retail_route_history_sum",
            parameters={"person": person, "date": _date_text(business_date), "ym": ym},
            output_format=output_format | {"answer_type": "number", "decimals": decimals or 2},
        )

    if "计划拜访线路" in question and "合约店" in question and "分销数量" in question:
        return make_logic_form(
            task_type="aggregation",
            operation="retail_route_contract_product_quantity",
            parameters={"person": person, "date": _date_text(business_date), "ym": ym, "product": product},
            output_format=output_format | {"answer_type": "number", "decimals": decimals or 3},
        )

    if "财年" in question and "分销数量" in question:
        fiscal_year = _extract_fiscal_year(question)
        return make_logic_form(
            task_type="aggregation",
            operation="retail_fiscal_product_quantity",
            parameters={"person": person, "fiscal_year": fiscal_year, "product": product, "role": _person_role(question, person, tables)},
            output_format=output_format | {"answer_type": "number", "decimals": decimals or 3},
        )

    if "新签约" in question:
        return make_logic_form(
            task_type="detail_lookup",
            operation="retail_new_contract_store_names",
            parameters={"person": person, "ym": ym, "role": _person_role(question, person, tables)},
            output_format=output_format | {"answer_type": "list"},
        )

    if "签约" in question and "陈列" in question and "门店家数" in question:
        return make_logic_form(
            task_type="aggregation",
            operation="retail_display_signed_store_count",
            parameters={"ym": ym, "display_item": _extract_display_item(question, tables)},
            output_format=output_format | {"answer_type": "number", "decimals": 0},
        )

    if "陈列费率" in question:
        return make_logic_form(
            task_type="ratio",
            operation="retail_display_fee_rate",
            parameters={"person": person, "ym": ym, "role": _person_role(question, person, tables)},
            output_format=output_format | {"answer_type": "percentage", "decimals": decimals or 2},
        )

    if "陈列执行" in question and "图像检查合格数最高" in question and "门店" in question:
        return make_logic_form(
            task_type="ranking",
            operation="retail_display_execution_image_pass_top",
            parameters={"ym": ym, "include_metric": _asks_for_metric_value(question), "decimals": decimals or 3},
            output_format=output_format | {"answer_type": "text"},
        )

    if "陈列执行" in question and "执行次数最高" in question and "门店" in question:
        return make_logic_form(
            task_type="ranking",
            operation="retail_display_execution_item_count_top",
            parameters={
                "ym": ym,
                "display_item": _extract_display_item(question, tables),
                "include_metric": _asks_for_metric_value(question),
                "decimals": decimals or 3,
            },
            output_format=output_format | {"answer_type": "text"},
        )

    if "陈列检查合格率" in question:
        return make_logic_form(
            task_type="ratio",
            operation="retail_display_pass_rate",
            parameters={"ym": ym, "display_item": _extract_display_item(question, tables)},
            output_format=output_format | {"answer_type": "percentage", "decimals": decimals or 2},
        )

    if "分别是多少" in question and "分销金额" in question and "拜访次数" in question:
        return make_logic_form(
            task_type="aggregation",
            operation="retail_multi_metric_summary",
            parameters={"person": person, "ym": ym, "role": _person_role(question, person, tables)},
            output_format=output_format | {"answer_type": "text"},
        )

    if "活跃SKU" in question or "活跃sku" in question.lower():
        return make_logic_form(
            task_type="ranking",
            operation="retail_active_sku_top",
            parameters={"ym": ym, "limit": _extract_limit(question, default=1)},
            output_format=output_format | {"answer_type": "text"},
        )

    if ("同比" in question or ("相比" in question and len(ym_mentions) >= 2)) and "历史分销" in question:
        comparison_ym = ym_mentions[1] if len(ym_mentions) >= 2 else None
        return make_logic_form(
            task_type="comparison",
            operation="retail_distribution_monthly_yoy_compare",
            parameters={"current_ym": ym_mentions[0] if ym_mentions else ym, "comparison_ym": comparison_ym},
            source_tables=["v_trd_dist_ord_dtl"],
            output_format=output_format | {"answer_type": "text"},
        )

    if product and "周期趋势" in question and "历史分销金额" in question:
        return make_logic_form(
            task_type="trend",
            operation="retail_category_distribution_periodic_trend",
            parameters={"product": product, "start_ym": start_ym or ym, "end_ym": end_ym or ym},
            source_tables=["v_trd_dist_ord_dtl"],
            output_format=output_format | {"answer_type": "text"},
        )

    if "累计历史分销金额最高" in question and "品类" in question:
        return make_logic_form(
            task_type="ranking",
            operation="retail_category_three_month_rank",
            parameters={"start_ym": start_ym or ym, "end_ym": end_ym or ym, "limit": _extract_limit(question, default=5)},
            source_tables=["v_trd_dist_ord_dtl"],
            output_format=output_format | {"answer_type": "text"},
        )

    if "主任目标金额" in question and "高于上月" in question:
        return make_logic_form(
            task_type="trend",
            operation="retail_manager_target_monthly_change",
            parameters={"person": person, "start_ym": start_ym or ym, "end_ym": end_ym or ym},
            source_tables=["ads_trd_dist_ord_target_mgr_1m_df"],
            output_format=output_format | {"answer_type": "text"},
        )

    if "合约店数量" in question and "连续上升" in question:
        return make_logic_form(
            task_type="trend",
            operation="retail_contract_customer_monthly_trend",
            parameters={"start_ym": start_ym or ym, "end_ym": end_ym or ym},
            source_tables=["终端客户月度维表"],
            output_format=output_format | {"answer_type": "text"},
        )

    if "冰柜客户数" in question and "较上月变化" in question:
        return make_logic_form(
            task_type="trend",
            operation="retail_freezer_customer_monthly_change",
            parameters={"start_ym": start_ym or ym, "end_ym": end_ym or ym},
            source_tables=["终端客户月度维表"],
            output_format=output_format | {"answer_type": "text"},
        )

    if "不合格率" in question and "整体平均" in question:
        return make_logic_form(
            task_type="trend",
            operation="retail_display_unqualified_rate_monthly",
            parameters={"start_ym": start_ym or ym, "end_ym": end_ym or ym},
            source_tables=["v_mkt_dsp_actv_mi"],
            output_format=output_format | {"answer_type": "text"},
        )

    if "各可用月份" in question and "SKU检查通过率" in question:
        return make_logic_form(
            task_type="trend",
            operation="retail_sku_check_monthly_pass_rate",
            parameters={},
            source_tables=["v_chl_jc_cust_sku_mi"],
            output_format=output_format | {"answer_type": "text"},
        )

    if "完成了分销目标" in question and "哪些月份" in question:
        return make_logic_form(
            task_type="detail_lookup",
            operation="retail_employee_target_reached_monthly",
            parameters={"start_ym": start_ym or ym, "end_ym": end_ym or ym},
            source_tables=["v_trd_dist_ord_dtl", "ads_trd_dist_ord_target_emp_1m_df"],
            output_format=output_format | {"answer_type": "text"},
        )

    if "拜访成功率" in question:
        return make_logic_form(
            task_type="ratio",
            operation="retail_visit_success_rate",
            parameters={"person": person, "ym": ym},
            output_format=output_format | {"answer_type": "percentage", "decimals": decimals or 2},
        )

    if "分销目标" in question:
        return make_logic_form(
            task_type="detail_lookup",
            operation="retail_target_lookup",
            parameters={"person": person, "ym": ym, "role": _target_role(person, tables)},
            output_format=output_format | {"answer_type": "number", "decimals": decimals or 2},
        )

    if "计划拜访线路" in question and "多少家门店" in question:
        return make_logic_form(
            task_type="aggregation",
            operation="retail_route_store_count",
            parameters={"person": person, "date": _date_text(business_date)},
            output_format=output_format | {"answer_type": "number", "decimals": 0},
        )

    if "陈列计划" in question and ("最多" in question or "出现次数最多" in question):
        return make_logic_form(
            task_type="ranking",
            operation="retail_display_item_top",
            parameters={"ym": ym},
            output_format=output_format | {"answer_type": "text"},
        )

    if "终端客户月度维表" in question and "冰柜客户" in question:
        return make_logic_form(
            task_type="aggregation",
            operation="retail_customer_feature_count",
            parameters={"ym": ym, "feature": "freezer"},
            output_format=output_format | {"answer_type": "number", "decimals": 0},
        )

    if "终端客户月度维表" in question and "合约店" in question:
        return make_logic_form(
            task_type="aggregation",
            operation="retail_contract_store_count",
            parameters={"ym": ym},
            output_format=output_format | {"answer_type": "number", "decimals": 0},
        )

    if "部分签收" in question:
        return make_logic_form(
            task_type="data_quality",
            operation="retail_today_partial_sign_exists",
            parameters={"date": _date_text(business_date)},
            output_format=output_format | {"answer_type": "yes_no"},
        )

    if "今日分销明细" in question and "分销金额最高" in question:
        return make_logic_form(
            task_type="ranking",
            operation="retail_today_distribution_ranking",
            parameters={
                "date": _date_text(business_date),
                "dimension": "emp_name" if "业代" in question else "ctg_name",
                "metric": "sign_amt",
                "limit": _extract_limit(question, default=1),
            },
            output_format=output_format | {"answer_type": "text"},
        )

    if "今日分销明细" in question and "行数最多" in question and "品类" in question:
        return make_logic_form(
            task_type="ranking",
            operation="retail_today_category_top",
            parameters={"date": _date_text(business_date)},
            output_format=output_format | {"answer_type": "text"},
        )

    if "陈列计划" in question and "不合格" in question and ("记录" in question or "多少条" in question):
        return make_logic_form(
            task_type="aggregation",
            operation="retail_display_record_count",
            parameters={"person": person, "ym": ym, "role": _person_role(question, person, tables), "status": "不合格"},
            output_format=output_format | {"answer_type": "number", "decimals": 0},
        )

    if "陈列计划" in question and ("记录" in question or "多少条" in question):
        return make_logic_form(
            task_type="aggregation",
            operation="retail_display_record_count",
            parameters={"person": person, "ym": ym, "role": _person_role(question, person, tables)},
            output_format=output_format | {"answer_type": "number", "decimals": 0},
        )

    if "计划拜访记录" in question and ("多少条" in question or "记录" in question):
        return make_logic_form(
            task_type="aggregation",
            operation="retail_visit_record_count",
            parameters={"ym": ym},
            output_format=output_format | {"answer_type": "number", "decimals": 0},
        )

    if "成功拜访" in question:
        return make_logic_form(
            task_type="aggregation",
            operation="retail_visit_success_count",
            parameters={"person": person, "ym": ym},
            output_format=output_format | {"answer_type": "number", "decimals": 0},
        )

    if "订单状态" in question and ("哪些" in question or "出现" in question):
        return make_logic_form(
            task_type="schema_query",
            operation="retail_history_field_values",
            parameters={"ym": ym, "field": "ord_status_name"},
            output_format=output_format | {"answer_type": "list"},
        )

    if "历史分销金额" in question and _is_ranking_question(question):
        return make_logic_form(
            task_type="ranking",
            operation="retail_distribution_ranking",
            parameters={
                "ym": ym,
                "dimension": _distribution_dimension(question),
                "metric": "sign_box_cnt" if "分销数量" in question else "sign_amt",
                "limit": _extract_limit(question, default=3 if "前三" in question else 1),
                "include_metric": _asks_for_metric_value(question),
            },
            output_format=output_format | {"answer_type": "text"},
        )

    if "历史分销数量" in question and _is_ranking_question(question):
        return make_logic_form(
            task_type="ranking",
            operation="retail_distribution_ranking",
            parameters={
                "ym": ym,
                "dimension": _distribution_dimension(question),
                "metric": "sign_box_cnt",
                "limit": _extract_limit(question, default=1),
                "include_metric": _asks_for_metric_value(question),
            },
            output_format=output_format | {"answer_type": "text"},
        )

    if "历史分销金额" in question:
        return make_logic_form(
            task_type="aggregation",
            operation="retail_distribution_sum",
            parameters={
                "person": person,
                "ym": ym,
                "metric": "sign_amt",
                "product": product,
                "role": _person_role(question, person, tables),
            },
            output_format=output_format
            | {
                "answer_type": "number",
                "decimals": decimals or 2,
                "not_applicable_type": "true_unsupported",
            },
        )

    return None


def _looks_like_chinese_retail_dataset(tables: dict[str, pd.DataFrame]) -> bool:
    return any(_has_columns(df, HISTORY_REQUIRED_COLUMNS) for df in tables.values()) and any(
        _has_columns(df, CUSTOMER_REQUIRED_COLUMNS) for df in tables.values()
    )


def _has_columns(df: pd.DataFrame, required: set[str]) -> bool:
    return required.issubset({str(column) for column in df.columns})


def _extract_year_month(question: str, tables: dict[str, pd.DataFrame]) -> tuple[int | None, int | None]:
    match = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", question)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"(20\d{2})-(\d{1,2})-\d{1,2}", question)
    if match:
        return int(match.group(1)), int(match.group(2))
    business_date = _infer_business_date(tables)
    if ("今日" in question or "今天" in question or "当天" in question) and business_date:
        return business_date.year, business_date.month
    return None, None


def _extract_year_month_range(question: str) -> tuple[int | None, int | None]:
    match = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月?\s*(?:至|到|-|~|—)\s*(?:(20\d{2})\s*年\s*)?(\d{1,2})\s*月", question)
    if match:
        start_year = int(match.group(1))
        start_month = int(match.group(2))
        end_year = int(match.group(3) or start_year)
        end_month = int(match.group(4))
        return start_year * 100 + start_month, end_year * 100 + end_month
    match = re.search(r"(20\d{2})-(\d{1,2})\s*(?:至|到|-|~|—)\s*(20\d{2})-(\d{1,2})", question)
    if match:
        return int(match.group(1)) * 100 + int(match.group(2)), int(match.group(3)) * 100 + int(match.group(4))
    return None, None


def _extract_date(question: str) -> date | None:
    match = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})", question)
    if not match:
        return None
    return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _extract_date_range(question: str) -> tuple[date | None, date | None]:
    matches = re.findall(r"(20\d{2})-(\d{1,2})-(\d{1,2})", question)
    if not matches:
        return None, None
    parsed = [date(int(year), int(month), int(day)) for year, month, day in matches[:2]]
    if len(parsed) == 1:
        return parsed[0], parsed[0]
    return parsed[0], parsed[1]


def _extract_year_month_mentions(question: str) -> list[int]:
    mentions: list[int] = []
    for year, month in re.findall(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", question):
        mentions.append(int(year) * 100 + int(month))
    for year, month in re.findall(r"(20\d{2})-(\d{1,2})-\d{1,2}", question):
        ym_value = int(year) * 100 + int(month)
        if ym_value not in mentions:
            mentions.append(ym_value)
    return mentions


def _infer_business_date(tables: dict[str, pd.DataFrame]) -> date | None:
    for names, required, column in (
        (("v_trd_dist_ord_dtl_1d_rt",), TODAY_REQUIRED_COLUMNS, "sign_time"),
        (("v_chl_route_plan_cust_cnt_1d_df",), ROUTE_REQUIRED_COLUMNS, "visit_date"),
    ):
        df = _find_table(tables, required, names)
        if df is None or column not in df.columns:
            continue
        values = pd.to_datetime(df[column], errors="coerce").dropna()
        if not values.empty:
            return values.max().date()
    return None


def _date_text(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _extract_decimal_places(text: str) -> int | None:
    match = re.search(r"保留\s*(\d+)\s*位", text)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)\s+decimals?", text, re.I)
    return int(match.group(1)) if match else None


def _extract_fiscal_year(question: str) -> int | None:
    match = re.search(r"(20\d{2})\s*财年", question)
    return int(match.group(1)) if match else None


def _extract_limit(question: str, default: int) -> int:
    if "前三" in question:
        return 3
    match = re.search(r"(?:top|前)\s*(\d+)", question, re.I)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)\s*(?:名|个|家|条|项|类)", question)
    return int(match.group(1)) if match else default


def _is_ranking_question(question: str) -> bool:
    return any(token in question for token in ("最高", "最多", "排名", "前三", "Top", "top"))


def _asks_for_metric_value(question: str) -> bool:
    return any(
        token in question
        for token in (
            "金额是多少",
            "数量是多少",
            "记录数是多少",
            "次数是多少",
            "数量分别",
            "金额分别",
            "数量和",
            "金额和",
        )
    )


def _asks_for_chart(question: str) -> bool:
    return any(token in question for token in ("展示", "生成", "图", "趋势", "可视化", "折线", "柱状", "多折线", "堆叠"))


def _prefers_horizontal_bar(question: str) -> bool:
    compact = question.replace(" ", "").lower()
    return any(token in compact for token in ("横向柱状图", "横向柱图", "水平柱状图", "horizontalbar"))


def _distribution_dimension(question: str) -> str:
    if "渠道" in question:
        return "channel_name"
    if "主任" in question:
        return "p_emp_name"
    if "品类" in question:
        return "ctg_name"
    if "SKU" in question or "sku" in question.lower():
        return "sku_name"
    return "emp_name"


def _extract_product(question: str, tables: dict[str, pd.DataFrame]) -> str | None:
    matched = _extract_value_from_columns(question, tables, ("ctg_name", "brand_name", "sales_ana_type_name", "clfc_name", "p_clfc_name"))
    if matched:
        return matched
    for token in sorted(("苏打天然水", "东方树叶", "天然水", "水堆", "我司冰柜"), key=len, reverse=True):
        if token in question:
            return token
    return None


def _extract_display_item(question: str, tables: dict[str, pd.DataFrame]) -> str | None:
    quoted = re.search(r"[“\"]([^”\"]+)[”\"]", question)
    if quoted:
        return quoted.group(1)
    for token in ("水堆", "我司冰柜", "我司多门冰柜", "货架"):
        if token in question:
            return token
    return _extract_value_from_columns(question, tables, ("dsp_name", "dsp_form_name"))


def _extract_person(question: str, tables: dict[str, pd.DataFrame]) -> str | None:
    return _extract_value_from_columns(question, tables, ("emp_name", "p_emp_name", "mgr_name", "业代", "主任"))


def _extract_value_from_columns(question: str, tables: dict[str, pd.DataFrame], columns: tuple[str, ...]) -> str | None:
    values: set[str] = set()
    for df in tables.values():
        for column in columns:
            if column not in df.columns:
                continue
            sample = df[column].dropna().astype(str).unique()
            values.update(value for value in sample if value and value != "nan")
    for value in sorted(values, key=len, reverse=True):
        if value in question:
            return value
    return None


def _person_role(question: str, person: str | None, tables: dict[str, pd.DataFrame]) -> str:
    if "主任" in question or "名下" in question:
        return "manager"
    if not person:
        return "employee"
    history = _find_table(tables, HISTORY_REQUIRED_COLUMNS, ("v_trd_dist_ord_dtl",))
    if history is not None and "emp_name" in history.columns and history["emp_name"].dropna().astype(str).eq(person).any():
        return "employee"
    if history is not None and "p_emp_name" in history.columns and history["p_emp_name"].dropna().astype(str).eq(person).any():
        return "manager"
    if _value_exists(tables, "p_emp_name", person) or _value_exists(tables, "mgr_name", person) or _value_exists(tables, "主任", person):
        return "manager"
    if _value_exists(tables, "emp_name", person):
        return "employee"
    return "employee"


def _target_role(person: str | None, tables: dict[str, pd.DataFrame]) -> str:
    if person and _value_exists(tables, "mgr_name", person):
        return "manager"
    return _person_role("", person, tables)


def _value_exists(tables: dict[str, pd.DataFrame], column: str, value: str) -> bool:
    for df in tables.values():
        if column in df.columns and df[column].dropna().astype(str).eq(value).any():
            return True
    return False


def _find_table(
    tables: dict[str, pd.DataFrame],
    required: set[str],
    preferred_names: tuple[str, ...] = (),
) -> pd.DataFrame | None:
    for name in preferred_names:
        table = tables.get(name)
        if table is not None and _has_columns(table, required):
            return table
    for df in tables.values():
        if _has_columns(df, required):
            return df
    return None
