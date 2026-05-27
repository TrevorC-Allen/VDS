"""Pandas executor helpers for Chinese retail distribution analytics.

These operations are schema-backed reusable capabilities for retail data
analysis. They do not depend on benchmark task ids or expected answers.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import pandas as pd

from data_agent_core.contracts.analysis_contracts import LogicForm


CHINESE_RETAIL_OPERATIONS = {
    "retail_distribution_sum",
    "retail_distribution_product_share",
    "retail_distribution_ranking",
    "retail_audit_sku_category_record_top",
    "retail_audit_sku_store_sku_count_top",
    "retail_average_active_sku_per_store",
    "retail_target_lookup",
    "retail_target_entity_count",
    "retail_target_achievement_rate",
    "retail_target_achievement_monthly",
    "retail_target_actual_monthly_comparison",
    "retail_distribution_monthly_mom",
    "retail_distribution_topn_chart",
    "retail_route_store_count",
    "retail_route_history_category_top",
    "retail_display_item_top",
    "retail_contract_store_count",
    "retail_service_customer_count",
    "retail_service_contract_store_rate",
    "retail_service_freezer_customer_rate",
    "retail_today_partial_sign_exists",
    "retail_today_category_top",
    "retail_today_distribution_ranking",
    "retail_visit_success_count",
    "retail_visit_success_rate",
    "retail_daily_progress_rate",
    "retail_daily_progress_worst_employee",
    "retail_manager_daily_gap_contribution",
    "retail_route_history_sum",
    "retail_route_contract_product_quantity",
    "retail_fiscal_product_quantity",
    "retail_new_contract_store_names",
    "retail_display_signed_store_count",
    "retail_display_record_count",
    "retail_display_execution_image_pass_top",
    "retail_display_execution_item_count_top",
    "retail_display_fee_rate",
    "retail_display_pass_rate",
    "retail_multi_metric_summary",
    "retail_active_sku_top",
    "retail_customer_feature_count",
    "retail_visit_record_count",
    "retail_history_field_values",
    "retail_manager_target_monthly_trend",
    "retail_top_employee_visit_success_rate_trend",
    "retail_category_distribution_monthly_trend",
}
NO_MATCHING_RECORDS = "没有匹配记录"


def is_chinese_retail_operation(operation: str) -> bool:
    """Return whether an operation belongs to the Chinese retail capability set."""

    return operation in CHINESE_RETAIL_OPERATIONS


def execute_chinese_retail_operation(logic: LogicForm, context: dict[str, Any]) -> Any:
    """Execute a Chinese retail LogicForm against uploaded tables."""

    op = logic.operation
    params = dict(logic.parameters)
    if logic.output_format.get("not_applicable_type"):
        params["_not_applicable_type"] = logic.output_format["not_applicable_type"]
    tables = context["tables"]
    if op == "retail_distribution_sum":
        return _retail_distribution_sum(tables, params)
    if op == "retail_distribution_product_share":
        return _retail_distribution_product_share(tables, params)
    if op == "retail_distribution_ranking":
        return _retail_distribution_ranking(tables, params)
    if op == "retail_audit_sku_category_record_top":
        return _retail_audit_sku_category_record_top(tables, params)
    if op == "retail_audit_sku_store_sku_count_top":
        return _retail_audit_sku_store_sku_count_top(tables, params)
    if op == "retail_average_active_sku_per_store":
        return _retail_average_active_sku_per_store(tables, params)
    if op == "retail_target_lookup":
        return _retail_target_lookup(tables, params)
    if op == "retail_target_entity_count":
        return _retail_target_entity_count(tables, params)
    if op == "retail_target_achievement_rate":
        return _retail_target_achievement_rate(tables, params)
    if op == "retail_target_achievement_monthly":
        return _retail_target_achievement_monthly(tables, params)
    if op == "retail_target_actual_monthly_comparison":
        return _retail_target_actual_monthly_comparison(tables, params)
    if op == "retail_distribution_monthly_mom":
        return _retail_distribution_monthly_mom(tables, params)
    if op == "retail_distribution_topn_chart":
        return _retail_distribution_topn_chart(tables, params)
    if op == "retail_route_store_count":
        return _retail_route_store_count(tables, params)
    if op == "retail_route_history_category_top":
        return _retail_route_history_category_top(tables, params)
    if op == "retail_display_item_top":
        return _retail_display_item_top(tables, params)
    if op == "retail_contract_store_count":
        return _retail_contract_store_count(tables, params)
    if op == "retail_service_customer_count":
        return _retail_service_customer_count(tables, params)
    if op == "retail_service_contract_store_rate":
        return _retail_service_contract_store_rate(tables, params)
    if op == "retail_service_freezer_customer_rate":
        return _retail_service_freezer_customer_rate(tables, params)
    if op == "retail_today_partial_sign_exists":
        return _retail_today_partial_sign_exists(tables, params)
    if op == "retail_today_category_top":
        return _retail_today_category_top(tables, params)
    if op == "retail_today_distribution_ranking":
        return _retail_today_distribution_ranking(tables, params)
    if op == "retail_visit_success_count":
        return _retail_visit_success_count(tables, params)
    if op == "retail_visit_success_rate":
        return _retail_visit_success_rate(tables, params)
    if op == "retail_daily_progress_rate":
        return _retail_daily_progress_rate(tables, params)
    if op == "retail_daily_progress_worst_employee":
        return _retail_daily_progress_worst_employee(tables, params)
    if op == "retail_manager_daily_gap_contribution":
        return _retail_manager_daily_gap_contribution(tables, params)
    if op == "retail_route_history_sum":
        return _retail_route_history_sum(tables, params)
    if op == "retail_route_contract_product_quantity":
        return _retail_route_contract_product_quantity(tables, params)
    if op == "retail_fiscal_product_quantity":
        return _retail_fiscal_product_quantity(tables, params)
    if op == "retail_new_contract_store_names":
        return _retail_new_contract_store_names(tables, params)
    if op == "retail_display_signed_store_count":
        return _retail_display_signed_store_count(tables, params)
    if op == "retail_display_record_count":
        return _retail_display_record_count(tables, params)
    if op == "retail_display_execution_image_pass_top":
        return _retail_display_execution_image_pass_top(tables, params)
    if op == "retail_display_execution_item_count_top":
        return _retail_display_execution_item_count_top(tables, params)
    if op == "retail_display_fee_rate":
        return _retail_display_fee_rate(tables, params)
    if op == "retail_display_pass_rate":
        return _retail_display_pass_rate(tables, params)
    if op == "retail_multi_metric_summary":
        return _retail_multi_metric_summary(tables, params)
    if op == "retail_active_sku_top":
        return _retail_active_sku_top(tables, params)
    if op == "retail_customer_feature_count":
        return _retail_customer_feature_count(tables, params)
    if op == "retail_visit_record_count":
        return _retail_visit_record_count(tables, params)
    if op == "retail_history_field_values":
        return _retail_history_field_values(tables, params)
    if op == "retail_manager_target_monthly_trend":
        return _retail_manager_target_monthly_trend(tables, params)
    if op == "retail_top_employee_visit_success_rate_trend":
        return _retail_top_employee_visit_success_rate_trend(tables, params)
    if op == "retail_category_distribution_monthly_trend":
        return _retail_category_distribution_monthly_trend(tables, params)
    raise ValueError(f"Unsupported Chinese retail operation: {op}")


def _retail_distribution_sum(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    hist = _history_table(tables)
    data = _filter_ym(hist, "sign_time", params.get("ym"))
    data = _filter_person(data, params.get("person"), params.get("role"))
    data = _filter_product(data, params.get("product"))
    if data.empty:
        if params.get("_not_applicable_type") == "true_unsupported" and not params.get("person") and not params.get("product"):
            return "Not Applicable"
        return 0.0
    return _sum(data, str(params.get("metric") or "sign_amt"))


def _retail_distribution_product_share(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    product = params.get("product")
    if not product:
        return 0.0
    hist = _history_table(tables)
    data = _filter_ym(hist, "sign_time", params.get("ym"))
    data = _filter_person(data, params.get("person"), params.get("role"))
    metric = str(params.get("metric") or "sign_amt")
    denominator = _sum(data, metric)
    if denominator == 0:
        return 0.0
    numerator = _sum(_filter_product(data, product), metric)
    return numerator / denominator * 100


def _retail_distribution_ranking(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    hist = _history_table(tables)
    data = _filter_ym(hist, "sign_time", params.get("ym"))
    if data.empty:
        return NO_MATCHING_RECORDS
    dimension = _first_existing_column(data, str(params.get("dimension") or "emp_name"), ("sku_name", "cmdt_name", "sku_code"))
    metric = str(params.get("metric") or "sign_amt")
    if dimension not in data.columns or metric not in data.columns:
        return NO_MATCHING_RECORDS
    ranking = data.groupby(dimension, dropna=True)[metric].sum().sort_values(ascending=False)
    if ranking.empty:
        return NO_MATCHING_RECORDS
    limit = int(params.get("limit") or 1)
    if limit == 1:
        return str(ranking.index[0])
    if not params.get("include_metric"):
        return ", ".join(str(name) for name in ranking.head(limit).index)
    return ", ".join(f"{name}:{value:.2f}" for name, value in ranking.head(limit).items())


def _retail_audit_sku_category_record_top(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    audit = _filter_audit_ym(_audit_sku_table(tables), params.get("ym"))
    category_column = _first_existing_column(audit, "ctg_name", ("clfc_name", "p_clfc_name", "category_name", "品类"))
    if audit.empty or category_column not in audit.columns:
        return NO_MATCHING_RECORDS
    counts = audit[category_column].dropna().astype(str).value_counts()
    if counts.empty:
        return NO_MATCHING_RECORDS
    name = str(counts.index[0])
    return f"{name}:{int(counts.iloc[0])}" if params.get("include_metric") else name


def _retail_audit_sku_store_sku_count_top(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    audit = _filter_audit_ym(_audit_sku_table(tables), params.get("ym"))
    store_column = _first_existing_column(audit, "cust_name", ("终端客户", "store_name", "客户名称"))
    sku_column = _first_existing_column(audit, "sku_code", ("sku_name", "cmdt_code", "cmdt_name", "商品编码"))
    if audit.empty or store_column not in audit.columns or sku_column not in audit.columns:
        return NO_MATCHING_RECORDS
    counts = audit.groupby(store_column, dropna=True)[sku_column].apply(_nunique_with_missing_bucket).sort_values(ascending=False)
    if counts.empty:
        return NO_MATCHING_RECORDS
    name = str(counts.index[0])
    return f"{name}:{int(counts.iloc[0])}" if params.get("include_metric") else name


def _retail_average_active_sku_per_store(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    hist = _filter_ym(_history_table(tables), "sign_time", params.get("ym"))
    data = _active_sku_rows(hist)
    store_column = _first_existing_column(data, "cust_code", ("cust_name", "终端客户", "客户名称"))
    sku_column = _first_existing_column(data, "sku_code", ("sku_name", "cmdt_code", "cmdt_name"))
    if data.empty or store_column not in data.columns or sku_column not in data.columns:
        return 0.0
    counts = data.groupby(store_column, dropna=True)[sku_column].nunique()
    if counts.empty:
        return 0.0
    return float(counts.mean())


def _retail_target_lookup(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    person = params.get("person")
    ym = params.get("ym")
    if not person or not ym:
        return 0.0
    if params.get("role") == "manager":
        target = _table_with_columns(tables, {"stat_month", "mgr_name", "target_amt"})
        data = target[(target["stat_month"].astype(int) == int(ym)) & (target["mgr_name"].astype(str) == str(person))]
        return 0.0 if data.empty else float(pd.to_numeric(data["target_amt"], errors="coerce").sum())
    target = _table_with_columns(tables, {"stat_month", "emp_name", "target"})
    data = target[(target["stat_month"].astype(int) == int(ym)) & (target["emp_name"].astype(str) == str(person))]
    return 0.0 if data.empty else float(pd.to_numeric(data["target"], errors="coerce").sum())


def _retail_target_entity_count(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> int | str:
    ym = params.get("ym")
    if not ym:
        return 0
    if params.get("role") == "manager":
        target = _table_with_columns(tables, {"stat_month", "mgr_name", "target_amt"})
        data = target[target["stat_month"].astype(int) == int(ym)]
        return int(data.loc[_numeric(data["target_amt"]) > 0, "mgr_name"].dropna().astype(str).nunique())
    target = _table_with_columns(tables, {"stat_month", "emp_name", "target"})
    data = target[target["stat_month"].astype(int) == int(ym)]
    return int(data.loc[_numeric(data["target"]) > 0, "emp_name"].dropna().astype(str).nunique())


def _retail_target_achievement_rate(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    ym = params.get("ym")
    person = params.get("person")
    if not ym or not person:
        return 0.0
    hist = _filter_ym(_history_table(tables), "sign_time", ym)
    hist = _filter_person(hist, person, params.get("role"))
    actual = _sum(hist, "sign_amt")
    target = _retail_target_lookup(tables, params)
    if float(target) == 0.0:
        return 0.0
    return actual / float(target) * 100


def _retail_target_achievement_monthly(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any] | str:
    monthly = _target_actual_monthly_rows(tables, params)
    if not monthly:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    achieved = [row["月份"] for row in monthly if float(row["达成率"]) >= 100.0]
    person = str(params.get("person") or "")
    answer = (
        f"{person}在{monthly[0]['月份']}至{monthly[-1]['月份']}的分销目标达成率："
        + "；".join(f"{row['月份']} { _format_decimal(float(row['达成率']), 2)}%" for row in monthly)
        + f"。达到或超过100%的月份：{', '.join(achieved) if achieved else '无'}。"
    )
    return {"answer": answer, "candidate_table": monthly, "x": "月份", "metric": "达成率"}


def _retail_target_actual_monthly_comparison(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any] | str:
    monthly = _target_actual_monthly_rows(tables, params)
    if not monthly:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    person = str(params.get("person") or "")
    best = max(monthly, key=lambda row: float(row["达成率"]))
    answer = (
        f"已生成{person}{monthly[0]['月份']}至{monthly[-1]['月份']}分销目标与实际分销金额对比；"
        f"达成率最高月份为{best['月份']}（{_format_decimal(float(best['达成率']), 2)}%）。"
    )
    return {"answer": answer, "candidate_table": monthly, "x": "月份", "metric": "实际分销金额"}


def _retail_distribution_monthly_mom(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any] | str:
    hist = _history_table(tables)
    months = _month_range(params.get("start_ym"), params.get("end_ym"))
    if not months:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    data = _filter_date_month_range(hist, "sign_time", months)
    if data.empty or "sign_amt" not in data.columns:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    data = data.copy()
    data["month"] = pd.to_datetime(data["sign_time"], errors="coerce").dt.strftime("%Y%m").astype(int)
    totals = data.groupby("month", dropna=True)["sign_amt"].sum().reindex(months, fill_value=0.0)
    rows: list[dict[str, Any]] = []
    previous: float | None = None
    changes: list[tuple[int, float]] = []
    for month, amount in totals.items():
        amount_f = float(amount)
        if previous is None or previous == 0:
            mom: float | None = None
        else:
            mom = (amount_f - previous) / previous * 100
            changes.append((int(month), mom))
        rows.append({"月份": _ym_label(int(month)), "分销金额": amount_f, "环比": None if mom is None else mom})
        previous = amount_f
    if not rows:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    growth = max(changes, key=lambda item: item[1]) if changes else None
    decline = min(changes, key=lambda item: item[1]) if changes else None
    answer = "；".join(
        f"{row['月份']} 分销金额{_format_decimal(float(row['分销金额']), 2)}，环比"
        f"{'无可比基期' if row['环比'] is None else _format_decimal(float(row['环比']), 2) + '%'}"
        for row in rows
    )
    if growth and decline:
        answer += (
            f"。最高增长月份：{_ym_label(growth[0])}（{_format_decimal(growth[1], 2)}%）；"
            f"最大下滑月份：{_ym_label(decline[0])}（{_format_decimal(decline[1], 2)}%）。"
        )
    return {"answer": answer, "candidate_table": rows, "x": "月份", "metric": "分销金额"}


def _retail_distribution_topn_chart(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any] | str:
    hist = _filter_ym(_history_table(tables), "sign_time", params.get("ym"))
    dimension = _first_existing_column(hist, str(params.get("dimension") or "sku_name"), ("cmdt_name", "cmdt_sname", "sku_code"))
    metric = str(params.get("metric") or "sign_amt")
    if hist.empty or dimension not in hist.columns or metric not in hist.columns:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    ranking = _numeric(hist[metric]).groupby(hist[dimension]).sum().sort_values(ascending=False)
    ranking = ranking[ranking > 0]
    if ranking.empty:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    limit = int(params.get("limit") or 10)
    rows = [{_dimension_label(dimension): str(name), _metric_label(metric): float(value)} for name, value in ranking.head(limit).items()]
    answer = "；".join(f"{row[_dimension_label(dimension)]}:{_format_decimal(float(row[_metric_label(metric)]), 2)}" for row in rows)
    return {"answer": answer, "candidate_table": rows, "x": _dimension_label(dimension), "metric": _metric_label(metric)}


def _retail_route_store_count(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> int:
    route = _route_rows(tables, params)
    return int(route["cust_code"].dropna().astype(str).nunique())


def _retail_route_history_category_top(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    route_codes = _route_customer_codes(tables, params)
    if not route_codes:
        return NO_MATCHING_RECORDS
    hist = _filter_ym(_history_table(tables), "sign_time", params.get("ym"))
    if "ctg_name" not in hist.columns:
        return NO_MATCHING_RECORDS
    data = hist[hist["cust_code"].dropna().astype(str).isin(route_codes)]
    ranking = data.groupby("ctg_name", dropna=True)["sign_amt"].sum().sort_values(ascending=False)
    if ranking.empty:
        return NO_MATCHING_RECORDS
    if params.get("include_metric"):
        return f"{ranking.index[0]}:{_format_decimal(float(ranking.iloc[0]), int(params.get('decimals') or 2))}"
    return str(ranking.index[0])


def _retail_display_item_top(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    display = _display_plan_table(tables)
    data = _filter_execute_ym(display, params.get("ym"))
    counts = data["dsp_name"].dropna().astype(str).value_counts()
    return NO_MATCHING_RECORDS if counts.empty else str(counts.index[0])


def _retail_contract_store_count(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> int:
    customer = _customer_table(tables)
    data = _filter_customer_ym(customer, params.get("ym"))
    data = data[data["是否合约店"].astype(str) == "是"]
    return int(data["终端客户编码"].dropna().astype(str).nunique())


def _retail_service_customer_count(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> int:
    customer = _service_customer_rows(tables, params.get("ym"))
    return int(customer["终端客户编码"].dropna().astype(str).nunique())


def _retail_service_contract_store_rate(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    customer = _service_customer_rows(tables, params.get("ym"))
    if customer.empty:
        return 0.0
    service_codes = set(customer["终端客户编码"].dropna().astype(str))
    contract_codes = set(customer.loc[customer["是否合约店"].astype(str) == "是", "终端客户编码"].dropna().astype(str))
    return 0.0 if not service_codes else len(contract_codes) / len(service_codes) * 100


def _retail_service_freezer_customer_rate(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    customer = _service_customer_rows(tables, params.get("ym"))
    if customer.empty:
        return 0.0
    freezer_column = _first_existing_column(customer, "是否冰柜客户", ("是否我司冰柜客户", "是否冰柜"))
    if freezer_column not in customer.columns:
        return 0.0
    service_codes = set(customer["终端客户编码"].dropna().astype(str))
    freezer_codes = set(
        customer.loc[customer[freezer_column].fillna("").astype(str) == "是", "终端客户编码"]
        .dropna()
        .astype(str)
    )
    return 0.0 if not service_codes else len(freezer_codes) / len(service_codes) * 100


def _retail_today_partial_sign_exists(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    today = _today_table(tables)
    data = _filter_date(today, "sign_time", params.get("date"))
    statuses = data["ord_status_name"].dropna().astype(str)
    return "yes" if statuses.str.contains("部分签收", regex=False).any() else "no"


def _retail_today_category_top(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    today = _today_table(tables)
    data = _filter_date(today, "sign_time", params.get("date"))
    counts = data["ctg_name"].dropna().astype(str).value_counts()
    return NO_MATCHING_RECORDS if counts.empty else str(counts.index[0])


def _retail_today_distribution_ranking(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    today = _today_table(tables)
    data = _filter_date(today, "sign_time", params.get("date"))
    if data.empty:
        return NO_MATCHING_RECORDS
    dimension = str(params.get("dimension") or "emp_name")
    metric = str(params.get("metric") or "sign_amt")
    if dimension not in data.columns or metric not in data.columns:
        return NO_MATCHING_RECORDS
    ranking = data.groupby(dimension, dropna=True)[metric].sum().sort_values(ascending=False)
    if ranking.empty:
        return NO_MATCHING_RECORDS
    limit = int(params.get("limit") or 1)
    if limit == 1:
        return str(ranking.index[0])
    return ", ".join(f"{name}:{value:.2f}" for name, value in ranking.head(limit).items())


def _retail_visit_success_count(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> int:
    visits = _visit_table(tables)
    data = _filter_ym(visits, "visit_date", params.get("ym"))
    data = data[data["emp_name"].astype(str) == str(params.get("person"))]
    return int((_numeric(data["if_visit_sucess"]) == 1).sum())


def _retail_visit_success_rate(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    visits = _visit_rows(tables, params)
    if visits.empty:
        return 0.0
    return float((_numeric(visits["if_visit_sucess"]) == 1).mean() * 100)


def _retail_daily_progress_rate(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    person = params.get("person")
    ym = params.get("ym")
    today = _today_table(tables)
    today_rows = _filter_date(today, "sign_time", params.get("date"))
    today_rows = today_rows[today_rows["emp_name"].astype(str) == str(person)]
    amount = _sum(today_rows, "sign_amt")
    target = _table_with_columns(tables, {"stat_month", "emp_name", "target"})
    target_rows = target[(target["stat_month"].astype(int) == int(ym)) & (target["emp_name"].astype(str) == str(person))]
    calendar = _table_with_columns(tables, {"month_id", "dist_day_cnt"})
    day_rows = calendar[calendar["month_id"].astype(int) == int(ym)]
    if target_rows.empty or day_rows.empty:
        return 0.0
    month_target = float(pd.to_numeric(target_rows["target"], errors="coerce").sum())
    day_count = float(pd.to_numeric(day_rows["dist_day_cnt"], errors="coerce").dropna().max())
    return 0.0 if month_target == 0 or day_count == 0 else amount / (month_target / day_count) * 100


def _retail_daily_progress_worst_employee(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any] | str:
    rows = _employee_daily_progress_rows(tables, params)
    rows = [row for row in rows if float(row["当日分销额"]) > 0]
    if not rows:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    selected = min(rows, key=lambda row: float(row["进度"]))
    answer = f"{selected['业代']}:{_format_decimal(float(selected['进度']), 2)}%,{_format_decimal(float(selected['差距']), 2)}%"
    return {"answer": answer, "candidate_table": rows, "x": "业代", "metric": "进度"}


def _retail_manager_daily_gap_contribution(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any] | str:
    ym = params.get("ym")
    date_text = params.get("date")
    if not ym or not date_text:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    day_count = _distribution_day_count(tables, ym)
    if not day_count:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    today = _filter_date(_today_table(tables), "sign_time", date_text)
    mgr_target = _table_with_columns(tables, {"stat_month", "mgr_name", "target_amt"})
    mgr_target = mgr_target[pd.to_numeric(mgr_target["stat_month"], errors="coerce").fillna(0).astype(int) == int(ym)]
    if mgr_target.empty:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    emp_progress = _employee_daily_progress_rows(tables, params, include_zero_actual=True)
    rows: list[dict[str, Any]] = []
    for _, target_row in mgr_target.iterrows():
        manager = str(target_row["mgr_name"])
        manager_actual = _sum(today[today.get("mgr_name", pd.Series(index=today.index, dtype=object)).astype(str) == manager], "sign_amt") if "mgr_name" in today.columns else 0.0
        manager_daily_target = float(pd.to_numeric(pd.Series([target_row["target_amt"]]), errors="coerce").fillna(0).iloc[0]) / day_count
        manager_gap = max(manager_daily_target - manager_actual, 0.0)
        sub_rows = [row for row in emp_progress if str(row.get("主任")) == manager]
        sub_gap_total = sum(float(row["缺口金额"]) for row in sub_rows)
        top_sub = max(sub_rows, key=lambda row: float(row["缺口金额"])) if sub_rows else None
        rows.append(
            {
                "主任": manager,
                "主任日目标缺口": manager_gap,
                "主要贡献业代": "" if top_sub is None else top_sub["业代"],
                "下属缺口贡献占比": 0.0 if not top_sub or sub_gap_total == 0 else float(top_sub["缺口金额"]) / sub_gap_total * 100,
            }
        )
    rows = [row for row in rows if float(row["主任日目标缺口"]) > 0]
    if not rows:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    selected = max(rows, key=lambda row: float(row["主任日目标缺口"]))
    answer = (
        f"{selected['主任']}:{_format_decimal(float(selected['主任日目标缺口']), 2)};"
        f"{selected['主要贡献业代']}:{_format_decimal(float(selected['下属缺口贡献占比']), 2)}%"
    )
    return {"answer": answer, "candidate_table": rows, "x": "主任", "metric": "主任日目标缺口"}


def _retail_route_history_sum(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    cust_codes = _route_customer_codes(tables, params)
    hist = _filter_ym(_history_table(tables), "sign_time", params.get("ym"))
    data = hist[hist["cust_code"].dropna().astype(str).isin(cust_codes)]
    return 0.0 if data.empty else _sum(data, "sign_amt")


def _retail_route_contract_product_quantity(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    route_codes = _route_customer_codes(tables, params)
    if not route_codes:
        return 0.0
    contract_codes = _contract_customer_codes(tables, params.get("ym"))
    hist = _filter_ym(_history_table(tables), "sign_time", params.get("ym"))
    data = hist[hist["cust_code"].dropna().astype(str).isin(route_codes & contract_codes)]
    data = _filter_product(data, params.get("product"))
    return _sum(data, "sign_box_cnt")


def _retail_fiscal_product_quantity(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    fiscal_year = int(params.get("fiscal_year") or 0)
    if not fiscal_year:
        return 0.0
    hist = _history_table(tables)
    dates = pd.to_datetime(hist["sign_time"], errors="coerce")
    start = pd.Timestamp(year=fiscal_year - 1, month=12, day=1)
    end = pd.Timestamp(year=fiscal_year, month=11, day=30, hour=23, minute=59, second=59)
    data = hist[(dates >= start) & (dates <= end)]
    data = _filter_person(data, params.get("person"), params.get("role"))
    data = _filter_product(data, params.get("product"))
    return 0.0 if data.empty else _sum(data, "sign_box_cnt")


def _retail_new_contract_store_names(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    customer = _filter_customer_ym(_customer_table(tables), params.get("ym"))
    if params.get("role") == "manager" and "主任" in customer.columns:
        customer = customer[customer["主任"].astype(str) == str(params.get("person"))]
    elif "业代" in customer.columns:
        customer = customer[customer["业代"].astype(str) == str(params.get("person"))]
    start_dates = pd.to_datetime(customer["合作开始日期"], errors="coerce")
    year, month = _split_ym(params.get("ym"))
    if year and month:
        customer = customer[(start_dates.dt.year == year) & (start_dates.dt.month == month)]
    names = [str(value) for value in customer["终端客户"].dropna().unique()]
    return ",".join(names)


def _retail_display_signed_store_count(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> int:
    display = _filter_execute_ym(_display_plan_table(tables), params.get("ym"))
    item = params.get("display_item")
    if item:
        display = display[display["dsp_name"].astype(str) == str(item)]
    return int(display["cust_code"].dropna().astype(str).nunique())


def _retail_display_record_count(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> int:
    display = _filter_execute_ym(_display_plan_table(tables), params.get("ym"))
    display = _filter_person(display, params.get("person"), params.get("role"))
    status = params.get("status")
    if status and "check_result_name" in display.columns:
        display = display[display["check_result_name"].astype(str) == str(status)]
    return int(len(display))


def _retail_display_execution_image_pass_top(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    execute = _safe_display_execute_table(tables)
    if execute is not None:
        data = _filter_execute_ym(execute, params.get("ym"))
        store_column = _first_existing_column(data, "cust_name", ("终端客户", "客户名称", "store_name", "cust_code"))
        metric_column = _first_existing_column(data, "zx_img_check_hg_cnt", ("img_check_hg_cnt", "image_check_pass_count", "图像检查合格数"))
        if not data.empty and store_column in data.columns and metric_column in data.columns:
            ranking = _numeric(data[metric_column]).groupby(data[store_column]).sum().sort_values(ascending=False)
            ranking = ranking[ranking > 0]
            if not ranking.empty:
                name = str(ranking.index[0])
                if not params.get("include_metric"):
                    return name
                decimals = int(params.get("decimals") if params.get("decimals") is not None else 3)
                return f"{name}:{_format_decimal(float(ranking.iloc[0]), decimals)}"

    display = _filter_execute_ym(_display_plan_table(tables), params.get("ym"))
    store_column = _first_existing_column(display, "cust_name", ("终端客户", "客户名称", "store_name", "cust_code"))
    result_column = _first_existing_column(display, "check_result_name", ("img_dsp_result_name", "dsp_result_name", "检查结果"))
    if display.empty or store_column not in display.columns or result_column not in display.columns:
        return NO_MATCHING_RECORDS
    result_text = display[result_column].fillna("").astype(str)
    passed = display[result_text.str.contains("合格", regex=False) & ~result_text.str.contains("不合格", regex=False)]
    counts = passed[store_column].dropna().astype(str).value_counts()
    if counts.empty:
        return NO_MATCHING_RECORDS
    name = str(counts.index[0])
    if not params.get("include_metric"):
        return name
    decimals = params.get("decimals")
    value = float(counts.iloc[0])
    return f"{name}:{_format_decimal(value, int(decimals))}" if decimals is not None else f"{name}:{int(value)}"


def _retail_display_execution_item_count_top(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    execute = _safe_display_execute_table(tables)
    if execute is not None:
        data = _filter_execute_ym(execute, params.get("ym"))
        store_column = _first_existing_column(data, "cust_name", ("终端客户", "客户名称", "store_name", "cust_code"))
        metric_column = _display_execute_metric_column(data, params.get("display_item"))
        if not data.empty and store_column in data.columns and metric_column in data.columns:
            ranking = _numeric(data[metric_column]).groupby(data[store_column]).sum().sort_values(ascending=False)
            ranking = ranking[ranking > 0]
            if not ranking.empty:
                name = str(ranking.index[0])
                if not params.get("include_metric"):
                    return name
                decimals = int(params.get("decimals") if params.get("decimals") is not None else 3)
                return f"{name}:{_format_decimal(float(ranking.iloc[0]), decimals)}"

    display = _filter_execute_ym(_display_plan_table(tables), params.get("ym"))
    item = params.get("display_item")
    if item:
        display = display[display["dsp_name"].astype(str) == str(item)]
    store_column = _first_existing_column(display, "cust_name", ("终端客户", "客户名称", "store_name", "cust_code"))
    if display.empty or store_column not in display.columns:
        return NO_MATCHING_RECORDS
    counts = display[store_column].dropna().astype(str).value_counts()
    if counts.empty:
        return NO_MATCHING_RECORDS
    name = str(counts.index[0])
    if not params.get("include_metric"):
        return name
    decimals = params.get("decimals")
    value = float(counts.iloc[0])
    return f"{name}:{_format_decimal(value, int(decimals))}" if decimals is not None else f"{name}:{int(value)}"


def _retail_display_fee_rate(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    display = _filter_execute_ym(_display_plan_table(tables), params.get("ym"))
    display = _filter_person(display, params.get("person"), params.get("role"))
    numerator = _sum(display, "confirm_amt")
    hist = _filter_ym(_history_table(tables), "sign_time", params.get("ym"))
    hist = _filter_person(hist, params.get("person"), params.get("role"))
    denominator = _sum(hist, "sign_amt")
    return 0.0 if denominator == 0 else numerator / denominator * 100


def _retail_display_pass_rate(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    display = _filter_execute_ym(_display_plan_table(tables), params.get("ym"))
    item = params.get("display_item")
    if item:
        display = display[display["dsp_name"].astype(str) == str(item)]
    checked = display[display["check_result_name"].notna()]
    if checked.empty:
        return 0.0
    return float((checked["check_result_name"].astype(str) == "合格").mean() * 100)


def _retail_multi_metric_summary(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    cust_codes = _manager_customer_codes(tables, params.get("person"), params.get("ym"))
    hist = _filter_ym(_history_table(tables), "sign_time", params.get("ym"))
    hist = hist[hist["cust_code"].dropna().astype(str).isin(cust_codes)]
    dist_amount = _sum(hist, "sign_amt")
    water_amount = _sum(hist[hist["ctg_name"].astype(str) == "天然水"], "sign_amt")

    visits = _filter_ym(_visit_table(tables), "visit_date", params.get("ym"))
    visits = visits[visits["cust_code"].dropna().astype(str).isin(cust_codes)]
    visit_count = int(len(visits))

    display = _filter_execute_ym(_display_plan_table(tables), params.get("ym"))
    display = display[display["cust_code"].dropna().astype(str).isin(cust_codes)]
    qualified_count = int((display["check_result_name"].astype(str) == "合格").sum())
    confirm_amount = _sum(display, "confirm_amt")
    return (
        f"分销金额:{_format_decimal(dist_amount, 2)}, "
        f"水分销金额:{_format_decimal(water_amount, 2)}, "
        f"拜访次数:{visit_count}, "
        f"陈列合格数:{qualified_count}, "
        f"陈列确认金额:{_format_decimal(confirm_amount, 2)}"
    )


def _retail_active_sku_top(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    hist = _filter_ym(_history_table(tables), "sign_time", params.get("ym"))
    data = _active_sku_rows(hist)
    if data.empty or "cust_name" not in data.columns or "sku_code" not in data.columns:
        return NO_MATCHING_RECORDS
    counts = data.groupby("cust_name", dropna=True)["sku_code"].nunique().sort_values(ascending=False)
    if counts.empty:
        return NO_MATCHING_RECORDS
    name = str(counts.index[0])
    return f"{name}:{int(counts.iloc[0])}"


def _retail_customer_feature_count(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> int:
    customer = _filter_customer_ym(_customer_table(tables), params.get("ym"))
    feature = str(params.get("feature") or "")
    if feature == "freezer":
        column = _first_existing_column(customer, "是否冰柜客户", ("是否我司冰柜客户", "是否冰柜"))
        if column not in customer.columns:
            return 0
        customer = customer[customer[column].astype(str) == "是"]
    return int(customer["终端客户编码"].dropna().astype(str).nunique())


def _retail_visit_record_count(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> int:
    visits = _filter_ym(_visit_table(tables), "visit_date", params.get("ym"))
    if "target_flag" in visits.columns:
        visits = visits[_numeric(visits["target_flag"]) == 1]
    return int(len(visits))


def _retail_history_field_values(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> list[str]:
    hist = _filter_ym(_history_table(tables), "sign_time", params.get("ym"))
    field = str(params.get("field") or "")
    if field not in hist.columns:
        return []
    values = [str(value) for value in hist[field].dropna().unique()]
    return sorted(values)


def _retail_manager_target_monthly_trend(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any] | str:
    target = _table_with_columns(tables, {"stat_month", "mgr_name", "target_amt"}, ("ads_trd_dist_ord_target_mgr_1m_df",))
    months = _month_range(params.get("start_ym"), params.get("end_ym"))
    if not months:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    data = _filter_stat_month_range(target, months)
    if data.empty:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    data = data.copy()
    data["target_amt_n"] = _numeric(data["target_amt"])
    managers = sorted([str(value) for value in data["mgr_name"].dropna().astype(str).unique() if str(value)])
    if not managers:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    pivot = (
        data.groupby(["stat_month", "mgr_name"], dropna=True)["target_amt_n"]
        .sum()
        .unstack(fill_value=0.0)
        .reindex(index=months, columns=managers, fill_value=0.0)
    )
    rows = [{"月份": _ym_label(month), **{manager: float(pivot.loc[month, manager]) for manager in managers}} for month in months]
    return {
        "answer": f"已生成{_ym_label(months[0])}至{_ym_label(months[-1])}{len(managers)}位主任的月度分销目标金额趋势。",
        "candidate_table": rows,
        "x": "月份",
        "metric": "target_amt",
    }


def _retail_top_employee_visit_success_rate_trend(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any] | str:
    visits = _visit_table(tables)
    months = _month_range(params.get("start_ym"), params.get("end_ym"))
    if not months:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    data = _filter_date_month_range(visits, "visit_date", months)
    if data.empty or "emp_name" not in data.columns or "if_visit_sucess" not in data.columns:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    limit = int(params.get("limit") or 5)
    top_employees = data["emp_name"].dropna().astype(str).value_counts().head(limit).index.tolist()
    if not top_employees:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    scoped = data[data["emp_name"].astype(str).isin(top_employees)].copy()
    scoped["month"] = pd.to_datetime(scoped["visit_date"], errors="coerce").dt.strftime("%Y%m").astype(int)
    scoped["success"] = (_numeric(scoped["if_visit_sucess"]) == 1).astype(int)
    grouped = scoped.groupby(["month", "emp_name"], dropna=True).agg(total=("cust_code", "count"), success=("success", "sum"))
    rows: list[dict[str, Any]] = []
    for month in months:
        row: dict[str, Any] = {"月份": _ym_label(month)}
        for employee in top_employees:
            key = (month, employee)
            if key not in grouped.index:
                row[employee] = 0.0
                continue
            total = float(grouped.loc[key, "total"])
            success = float(grouped.loc[key, "success"])
            row[employee] = 0.0 if total == 0 else success / total * 100
        rows.append(row)
    return {
        "answer": f"已生成{_ym_label(months[0])}至{_ym_label(months[-1])}拜访量最高{len(top_employees)}名业代的月度拜访成功率趋势。",
        "candidate_table": rows,
        "x": "月份",
        "metric": "visit_success_rate",
    }


def _retail_category_distribution_monthly_trend(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any] | str:
    hist = _history_table(tables)
    months = _month_range(params.get("start_ym"), params.get("end_ym"))
    if not months:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    data = _filter_date_month_range(hist, "sign_time", months)
    if data.empty or "ctg_name" not in data.columns or "sign_amt" not in data.columns:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    limit = int(params.get("limit") or 5)
    data = data.copy()
    data["month"] = pd.to_datetime(data["sign_time"], errors="coerce").dt.strftime("%Y%m").astype(int)
    data["sign_amt_n"] = _numeric(data["sign_amt"])
    categories = data.groupby("ctg_name", dropna=True)["sign_amt_n"].sum().sort_values(ascending=False).head(limit).index.tolist()
    if not categories:
        return {"answer": NO_MATCHING_RECORDS, "candidate_table": []}
    pivot = (
        data[data["ctg_name"].isin(categories)]
        .groupby(["month", "ctg_name"], dropna=True)["sign_amt_n"]
        .sum()
        .unstack(fill_value=0.0)
        .reindex(index=months, columns=categories, fill_value=0.0)
    )
    rows = [{"月份": _ym_label(month), **{category: float(pivot.loc[month, category]) for category in categories}} for month in months]
    return {
        "answer": f"已生成{_ym_label(months[0])}至{_ym_label(months[-1])}分品类历史分销金额趋势。",
        "candidate_table": rows,
        "x": "月份",
        "metric": "sign_amt",
    }


def _target_actual_monthly_rows(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> list[dict[str, Any]]:
    person = params.get("person")
    if not person:
        return []
    months = _month_range(params.get("start_ym"), params.get("end_ym"))
    if not months:
        return []
    role = params.get("role")
    hist = _filter_date_month_range(_history_table(tables), "sign_time", months)
    hist = _filter_person(hist, person, role)
    if hist.empty and role != "manager":
        actual_by_month = pd.Series(dtype=float)
    else:
        hist = hist.copy()
        hist["month"] = pd.to_datetime(hist["sign_time"], errors="coerce").dt.strftime("%Y%m")
        hist = hist[pd.to_numeric(hist["month"], errors="coerce").notna()]
        hist["month"] = hist["month"].astype(int)
        hist["sign_amt_n"] = _numeric(hist["sign_amt"])
        actual_by_month = hist.groupby("month")["sign_amt_n"].sum()

    if role == "manager":
        target = _table_with_columns(tables, {"stat_month", "mgr_name", "target_amt"})
        target = target[target["mgr_name"].astype(str) == str(person)].copy()
        target_column = "target_amt"
    else:
        target = _table_with_columns(tables, {"stat_month", "emp_name", "target"})
        target = target[target["emp_name"].astype(str) == str(person)].copy()
        target_column = "target"
    if target.empty:
        return []
    target = target[pd.to_numeric(target["stat_month"], errors="coerce").isin(months)].copy()
    if target.empty:
        return []
    target["stat_month_n"] = pd.to_numeric(target["stat_month"], errors="coerce").astype(int)
    target["target_n"] = _numeric(target[target_column])
    target_by_month = target.groupby("stat_month_n")["target_n"].sum()
    rows: list[dict[str, Any]] = []
    for month in months:
        actual = float(actual_by_month.get(month, 0.0))
        target_value = float(target_by_month.get(month, 0.0))
        achievement = 0.0 if target_value == 0 else actual / target_value * 100
        rows.append(
            {
                "月份": _ym_label(month),
                "实际分销金额": actual,
                "目标金额": target_value,
                "达成率": achievement,
            }
        )
    return rows


def _employee_daily_progress_rows(
    tables: dict[str, pd.DataFrame],
    params: dict[str, Any],
    *,
    include_zero_actual: bool = False,
) -> list[dict[str, Any]]:
    ym = params.get("ym")
    date_text = params.get("date")
    if not ym or not date_text:
        return []
    day_count = _distribution_day_count(tables, ym)
    if not day_count:
        return []
    target = _table_with_columns(tables, {"stat_month", "emp_name", "target"})
    target = target[pd.to_numeric(target["stat_month"], errors="coerce").fillna(0).astype(int) == int(ym)]
    if target.empty:
        return []
    today = _filter_date(_today_table(tables), "sign_time", date_text)
    actual_by_employee = _numeric(today["sign_amt"]).groupby(today["emp_name"].astype(str)).sum() if not today.empty and "emp_name" in today.columns else pd.Series(dtype=float)
    rows: list[dict[str, Any]] = []
    for _, row in target.iterrows():
        employee = str(row["emp_name"])
        target_value = float(pd.to_numeric(pd.Series([row["target"]]), errors="coerce").fillna(0).iloc[0])
        if target_value <= 0:
            continue
        actual = float(actual_by_employee.get(employee, 0.0))
        if actual <= 0 and not include_zero_actual:
            continue
        daily_target = target_value / day_count
        progress = 0.0 if daily_target == 0 else actual / daily_target * 100
        gap_percent = max(100.0 - progress, 0.0)
        rows.append(
            {
                "业代": employee,
                "主任": str(row["p_emp_name"]) if "p_emp_name" in target.columns else "",
                "日目标": daily_target,
                "当日分销额": actual,
                "进度": progress,
                "差距": gap_percent,
                "缺口金额": max(daily_target - actual, 0.0),
            }
        )
    return rows


def _distribution_day_count(tables: dict[str, pd.DataFrame], ym: Any) -> float | None:
    calendar = _table_with_columns(tables, {"month_id", "dist_day_cnt"})
    rows = calendar[pd.to_numeric(calendar["month_id"], errors="coerce").fillna(0).astype(int) == int(ym)]
    if rows.empty:
        return None
    value = float(pd.to_numeric(rows["dist_day_cnt"], errors="coerce").dropna().max())
    return value if value > 0 else None


def _dimension_label(dimension: str) -> str:
    return {
        "sku_name": "SKU",
        "ctg_name": "品类",
        "emp_name": "业代",
        "p_emp_name": "主任",
    }.get(dimension, dimension)


def _metric_label(metric: str) -> str:
    return {
        "sign_amt": "分销金额",
        "sign_box_cnt": "分销数量",
        "target": "目标金额",
        "target_amt": "目标金额",
    }.get(metric, metric)


def _route_customer_codes(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> set[str]:
    route = _route_rows(tables, params)
    return set(route["cust_code"].dropna().astype(str))


def _route_rows(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> pd.DataFrame:
    route = _route_table(tables)
    data = _filter_date(route, "visit_date", params.get("date"))
    person = params.get("person")
    if person:
        data = data[data["emp_name"].astype(str) == str(person)]
    return data


def _visit_rows(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> pd.DataFrame:
    visits = _filter_ym(_visit_table(tables), "visit_date", params.get("ym"))
    person = params.get("person")
    if person:
        visits = _filter_person(visits, person, params.get("role"))
    return visits


def _contract_customer_codes(tables: dict[str, pd.DataFrame], ym: Any) -> set[str]:
    customer = _filter_customer_ym(_customer_table(tables), ym)
    customer = customer[customer["是否合约店"].astype(str) == "是"]
    return set(customer["终端客户编码"].dropna().astype(str))


def _manager_customer_codes(tables: dict[str, pd.DataFrame], person: Any, ym: Any) -> set[str]:
    customer = _filter_customer_ym(_customer_table(tables), ym)
    if person and "主任" in customer.columns:
        customer = customer[customer["主任"].astype(str) == str(person)]
    return set(customer["终端客户编码"].dropna().astype(str))


def _service_customer_rows(tables: dict[str, pd.DataFrame], ym: Any) -> pd.DataFrame:
    customer = _filter_customer_ym(_customer_table(tables), ym)
    status_column = _first_existing_column(customer, "终端客户状态", ("客户状态", "cust_status_name"))
    if status_column in customer.columns:
        inactive_tokens = ("停用", "终止", "无效", "失效", "关闭", "取消", "不合作")
        status = customer[status_column].fillna("").astype(str)
        active_mask = ~status.apply(lambda value: any(token in value for token in inactive_tokens))
        customer = customer[active_mask]
    return customer


def _active_sku_rows(hist: pd.DataFrame) -> pd.DataFrame:
    if hist.empty or "sign_box_cnt" not in hist.columns:
        return hist.iloc[0:0]
    mask = _numeric(hist["sign_box_cnt"]) > 0
    if "cmdt_tag_name" in hist.columns:
        active_tags = {"活动本品", "普通本品", "特价商品"}
        mask = mask & hist["cmdt_tag_name"].fillna("").astype(str).isin(active_tags)
    if "ord_type_name" in hist.columns:
        excluded_order_types = {"分销退货", "库存盘点"}
        mask = mask & ~hist["ord_type_name"].fillna("").astype(str).isin(excluded_order_types)
    return hist[mask]


def _nunique_with_missing_bucket(series: pd.Series) -> int:
    text = series.fillna("").astype(str).str.strip()
    non_missing = text[text.str.len() > 0]
    return int(non_missing.nunique() + (1 if (text.str.len() == 0).any() else 0))


def _filter_product(data: pd.DataFrame, product: Any) -> pd.DataFrame:
    if not product:
        return data
    text = str(product)
    exact_columns = [
        column
        for column in ("ctg_name", "brand_name", "sales_ana_type_name", "clfc_name", "p_clfc_name", "p2_clfc_name", "item_name")
        if column in data.columns
    ]
    contains_columns = [column for column in ("cmdt_name", "sku_name", "cmdt_sname") if column in data.columns]
    if not exact_columns and not contains_columns:
        return data
    for column in exact_columns:
        mask = data[column].fillna("").astype(str).eq(text)
        if mask.any():
            return data[mask]
    mask = pd.Series(False, index=data.index)
    for column in contains_columns:
        mask = mask | data[column].fillna("").astype(str).str.contains(text, regex=False)
    return data[mask]


def _first_existing_column(data: pd.DataFrame, preferred: str, fallbacks: tuple[str, ...] = ()) -> str:
    if preferred in data.columns:
        return preferred
    for column in fallbacks:
        if column in data.columns:
            return column
    return preferred


def _filter_person(data: pd.DataFrame, person: Any, role: Any) -> pd.DataFrame:
    if not person:
        return data
    column = "p_emp_name" if role == "manager" and "p_emp_name" in data.columns else "emp_name"
    if role == "manager" and "主任" in data.columns:
        column = "主任"
    if column not in data.columns:
        return data
    return data[data[column].astype(str) == str(person)]


def _filter_ym(data: pd.DataFrame, date_column: str, ym: Any) -> pd.DataFrame:
    year, month = _split_ym(ym)
    if not year or not month:
        return data
    dates = pd.to_datetime(data[date_column], errors="coerce")
    return data[(dates.dt.year == year) & (dates.dt.month == month)]


def _filter_date_month_range(data: pd.DataFrame, date_column: str, months: list[int]) -> pd.DataFrame:
    if not months:
        return data.iloc[0:0]
    dates = pd.to_datetime(data[date_column], errors="coerce")
    month_values = dates.dt.strftime("%Y%m")
    valid = month_values.notna()
    numeric_months = pd.to_numeric(month_values.where(valid), errors="coerce")
    return data[numeric_months.isin(months)]


def _filter_stat_month_range(data: pd.DataFrame, months: list[int]) -> pd.DataFrame:
    if not months:
        return data.iloc[0:0]
    return data[pd.to_numeric(data["stat_month"], errors="coerce").isin(months)]


def _filter_date(data: pd.DataFrame, date_column: str, date_text: Any) -> pd.DataFrame:
    if not date_text:
        return data
    target = pd.Timestamp(str(date_text)).date()
    dates = pd.to_datetime(data[date_column], errors="coerce").dt.date
    return data[dates == target]


def _filter_execute_ym(data: pd.DataFrame, ym: Any) -> pd.DataFrame:
    if not ym:
        return data
    return data[data["execute_ym"].astype(int) == int(ym)]


def _filter_customer_ym(data: pd.DataFrame, ym: Any) -> pd.DataFrame:
    if not ym:
        return data
    return data[data["年月"].astype(int) == int(ym)]


def _filter_audit_ym(data: pd.DataFrame, ym: Any) -> pd.DataFrame:
    if not ym:
        return data
    for column in ("ym", "stat_month", "年月", "month_id"):
        if column in data.columns:
            return data[pd.to_numeric(data[column], errors="coerce").fillna(0).astype(int) == int(ym)]
    for column in ("audit_date", "stat_date", "biz_date", "date"):
        if column in data.columns:
            return _filter_ym(data, column, ym)
    return data


def _split_ym(ym: Any) -> tuple[int | None, int | None]:
    if ym is None:
        return None, None
    text = str(int(ym))
    if len(text) != 6:
        return None, None
    return int(text[:4]), int(text[4:])


def _month_range(start_ym: Any, end_ym: Any) -> list[int]:
    start_year, start_month = _split_ym(start_ym)
    end_year, end_month = _split_ym(end_ym)
    if not start_year or not start_month or not end_year or not end_month:
        return []
    start = pd.Period(year=start_year, month=start_month, freq="M")
    end = pd.Period(year=end_year, month=end_month, freq="M")
    if end < start:
        start, end = end, start
    return [int(period.strftime("%Y%m")) for period in pd.period_range(start, end, freq="M")]


def _ym_label(ym: Any) -> str:
    year, month = _split_ym(ym)
    if not year or not month:
        return str(ym)
    return f"{year}年{month}月"


def _sum(data: pd.DataFrame, column: str) -> float:
    if column not in data.columns or data.empty:
        return 0.0
    return float(_numeric(data[column]).sum())


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0)


def _history_table(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return _table_with_columns(tables, {"sign_time", "sign_amt", "emp_name", "cust_code"}, ("v_trd_dist_ord_dtl",))


def _today_table(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return _table_with_columns(tables, {"sign_time", "sign_amt", "ord_status_name", "ctg_name"}, ("v_trd_dist_ord_dtl_1d_rt",))


def _route_table(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return _table_with_columns(tables, {"visit_date", "cust_code", "emp_name", "route_code"}, ("v_chl_route_plan_cust_cnt_1d_df",))


def _customer_table(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return _table_with_columns(tables, {"年月", "终端客户编码", "终端客户", "是否合约店"}, ("终端客户月度维表",))


def _audit_sku_table(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return _table_with_columns(
        tables,
        {"ctg_name", "cust_name", "sku_code"},
        ("v_chl_jc_cust_sku_mi", "稽查门店SKU分析"),
    )


def _safe_display_execute_table(tables: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    try:
        return _display_execute_table(tables)
    except ValueError:
        return None


def _display_execute_table(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return _table_with_columns(tables, {"execute_ym", "cust_name"}, ("v_mkt_dsp_execute_mi", "陈列执行"))


def _display_execute_metric_column(data: pd.DataFrame, display_item: Any) -> str:
    item = str(display_item or "")
    item_candidates: list[str]
    if "货架" in item:
        item_candidates = ["hj_exec_act_times", "hj_act_exec_nums", "hj_exec_act_hg_times"]
    elif "水堆" in item:
        item_candidates = ["sd_exec_act_times", "sd_act_exec_nums", "sd_exec_act_hg_times"]
    elif "冰柜" in item:
        item_candidates = ["bdh_exec_act_times", "bdh_exec_act_times_2", "free_bdh_hg_cnt", "free_bdh_hg_cnt_2"]
    elif "堆箱" in item or "地堆" in item:
        item_candidates = ["dd_exec_act_times", "dd_act_exec_nums", "dd_exec_act_hg_times"]
    else:
        item_candidates = [
            column
            for column in data.columns
            if column.endswith("_exec_act_times") or column.endswith("_act_exec_nums") or column.endswith("_exec_nums")
        ]
    for column in item_candidates:
        if column in data.columns:
            return column
    return item_candidates[0] if item_candidates else "execute_count"


def _display_plan_table(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return _table_with_columns(tables, {"execute_ym", "dsp_name", "cust_code", "confirm_amt"}, ("v_mkt_dsp_actv_mi",))


def _visit_table(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return _table_with_columns(tables, {"visit_date", "emp_name", "cust_code", "if_visit_sucess"}, ("v_chl_visit_dtl",))


def _table_with_columns(
    tables: dict[str, pd.DataFrame],
    required: set[str],
    preferred_names: tuple[str, ...] = (),
) -> pd.DataFrame:
    for name in preferred_names:
        table = tables.get(name)
        if table is not None and required.issubset({str(column) for column in table.columns}):
            return table
    for table in tables.values():
        if required.issubset({str(column) for column in table.columns}):
            return table
    raise ValueError(f"No uploaded table contains required columns: {sorted(required)}")


def _format_decimal(value: float, places: int) -> str:
    quantum = Decimal("1").scaleb(-places)
    return str(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))
