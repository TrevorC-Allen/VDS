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
    "retail_distribution_ranking",
    "retail_target_lookup",
    "retail_target_entity_count",
    "retail_target_achievement_rate",
    "retail_route_store_count",
    "retail_route_history_category_top",
    "retail_display_item_top",
    "retail_contract_store_count",
    "retail_service_customer_count",
    "retail_service_contract_store_rate",
    "retail_today_partial_sign_exists",
    "retail_today_category_top",
    "retail_today_distribution_ranking",
    "retail_visit_success_count",
    "retail_visit_success_rate",
    "retail_daily_progress_rate",
    "retail_route_history_sum",
    "retail_route_contract_product_quantity",
    "retail_fiscal_product_quantity",
    "retail_new_contract_store_names",
    "retail_display_signed_store_count",
    "retail_display_record_count",
    "retail_display_fee_rate",
    "retail_display_pass_rate",
    "retail_multi_metric_summary",
    "retail_active_sku_top",
    "retail_customer_feature_count",
    "retail_visit_record_count",
    "retail_history_field_values",
}


def is_chinese_retail_operation(operation: str) -> bool:
    """Return whether an operation belongs to the Chinese retail capability set."""

    return operation in CHINESE_RETAIL_OPERATIONS


def execute_chinese_retail_operation(logic: LogicForm, context: dict[str, Any]) -> Any:
    """Execute a Chinese retail LogicForm against uploaded tables."""

    op = logic.operation
    params = logic.parameters
    tables = context["tables"]
    if op == "retail_distribution_sum":
        return _retail_distribution_sum(tables, params)
    if op == "retail_distribution_ranking":
        return _retail_distribution_ranking(tables, params)
    if op == "retail_target_lookup":
        return _retail_target_lookup(tables, params)
    if op == "retail_target_entity_count":
        return _retail_target_entity_count(tables, params)
    if op == "retail_target_achievement_rate":
        return _retail_target_achievement_rate(tables, params)
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
    raise ValueError(f"Unsupported Chinese retail operation: {op}")


def _retail_distribution_sum(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    hist = _history_table(tables)
    data = _filter_ym(hist, "sign_time", params.get("ym"))
    data = _filter_person(data, params.get("person"), params.get("role"))
    if data.empty:
        return "Not Applicable"
    return _sum(data, str(params.get("metric") or "sign_amt"))


def _retail_distribution_ranking(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    hist = _history_table(tables)
    data = _filter_ym(hist, "sign_time", params.get("ym"))
    if data.empty:
        return "Not Applicable"
    dimension = _first_existing_column(data, str(params.get("dimension") or "emp_name"), ("sku_name", "cmdt_name", "sku_code"))
    metric = str(params.get("metric") or "sign_amt")
    if dimension not in data.columns or metric not in data.columns:
        return "Not Applicable"
    ranking = data.groupby(dimension, dropna=True)[metric].sum().sort_values(ascending=False)
    if ranking.empty:
        return "Not Applicable"
    limit = int(params.get("limit") or 1)
    if limit == 1:
        return str(ranking.index[0])
    if not params.get("include_metric"):
        return ", ".join(str(name) for name in ranking.head(limit).index)
    return ", ".join(f"{name}:{value:.2f}" for name, value in ranking.head(limit).items())


def _retail_target_lookup(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    person = params.get("person")
    ym = params.get("ym")
    if not person or not ym:
        return "Not Applicable"
    if params.get("role") == "manager":
        target = _table_with_columns(tables, {"stat_month", "mgr_name", "target_amt"})
        data = target[(target["stat_month"].astype(int) == int(ym)) & (target["mgr_name"].astype(str) == str(person))]
        return "Not Applicable" if data.empty else float(pd.to_numeric(data["target_amt"], errors="coerce").sum())
    target = _table_with_columns(tables, {"stat_month", "emp_name", "target"})
    data = target[(target["stat_month"].astype(int) == int(ym)) & (target["emp_name"].astype(str) == str(person))]
    return "Not Applicable" if data.empty else float(pd.to_numeric(data["target"], errors="coerce").sum())


def _retail_target_entity_count(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> int | str:
    ym = params.get("ym")
    if not ym:
        return "Not Applicable"
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
        return "Not Applicable"
    hist = _filter_ym(_history_table(tables), "sign_time", ym)
    hist = _filter_person(hist, person, params.get("role"))
    actual = _sum(hist, "sign_amt")
    target = _retail_target_lookup(tables, params)
    if target == "Not Applicable" or float(target) == 0.0:
        return "Not Applicable"
    return actual / float(target) * 100


def _retail_route_store_count(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> int:
    route = _route_rows(tables, params)
    return int(route["cust_code"].dropna().astype(str).nunique())


def _retail_route_history_category_top(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    route_codes = _route_customer_codes(tables, params)
    if not route_codes:
        return "Not Applicable"
    hist = _filter_ym(_history_table(tables), "sign_time", params.get("ym"))
    if "ctg_name" not in hist.columns:
        return "Not Applicable"
    data = hist[hist["cust_code"].dropna().astype(str).isin(route_codes)]
    ranking = data.groupby("ctg_name", dropna=True)["sign_amt"].sum().sort_values(ascending=False)
    if ranking.empty:
        return "Not Applicable"
    if params.get("include_metric"):
        return f"{ranking.index[0]}:{_format_decimal(float(ranking.iloc[0]), int(params.get('decimals') or 2))}"
    return str(ranking.index[0])


def _retail_display_item_top(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    display = _display_plan_table(tables)
    data = _filter_execute_ym(display, params.get("ym"))
    counts = data["dsp_name"].dropna().astype(str).value_counts()
    return "Not Applicable" if counts.empty else str(counts.index[0])


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
        return "Not Applicable"
    service_codes = set(customer["终端客户编码"].dropna().astype(str))
    contract_codes = set(customer.loc[customer["是否合约店"].astype(str) == "是", "终端客户编码"].dropna().astype(str))
    return 0.0 if not service_codes else len(contract_codes) / len(service_codes) * 100


def _retail_today_partial_sign_exists(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    today = _today_table(tables)
    data = _filter_date(today, "sign_time", params.get("date"))
    statuses = data["ord_status_name"].dropna().astype(str)
    return "yes" if statuses.str.contains("部分签收", regex=False).any() else "no"


def _retail_today_category_top(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    today = _today_table(tables)
    data = _filter_date(today, "sign_time", params.get("date"))
    counts = data["ctg_name"].dropna().astype(str).value_counts()
    return "Not Applicable" if counts.empty else str(counts.index[0])


def _retail_today_distribution_ranking(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> str:
    today = _today_table(tables)
    data = _filter_date(today, "sign_time", params.get("date"))
    if data.empty:
        return "Not Applicable"
    dimension = str(params.get("dimension") or "emp_name")
    metric = str(params.get("metric") or "sign_amt")
    if dimension not in data.columns or metric not in data.columns:
        return "Not Applicable"
    ranking = data.groupby(dimension, dropna=True)[metric].sum().sort_values(ascending=False)
    if ranking.empty:
        return "Not Applicable"
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
        return "Not Applicable"
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
        return "Not Applicable"
    month_target = float(pd.to_numeric(target_rows["target"], errors="coerce").sum())
    day_count = float(pd.to_numeric(day_rows["dist_day_cnt"], errors="coerce").dropna().max())
    return 0.0 if month_target == 0 or day_count == 0 else amount / (month_target / day_count) * 100


def _retail_route_history_sum(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    cust_codes = _route_customer_codes(tables, params)
    hist = _filter_ym(_history_table(tables), "sign_time", params.get("ym"))
    data = hist[hist["cust_code"].dropna().astype(str).isin(cust_codes)]
    return "Not Applicable" if data.empty else _sum(data, "sign_amt")


def _retail_route_contract_product_quantity(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    route_codes = _route_customer_codes(tables, params)
    if not route_codes:
        return "Not Applicable"
    contract_codes = _contract_customer_codes(tables, params.get("ym"))
    hist = _filter_ym(_history_table(tables), "sign_time", params.get("ym"))
    data = hist[hist["cust_code"].dropna().astype(str).isin(route_codes & contract_codes)]
    data = _filter_product(data, params.get("product"))
    return _sum(data, "sign_box_cnt")


def _retail_fiscal_product_quantity(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    fiscal_year = int(params.get("fiscal_year") or 0)
    if not fiscal_year:
        return "Not Applicable"
    hist = _history_table(tables)
    dates = pd.to_datetime(hist["sign_time"], errors="coerce")
    start = pd.Timestamp(year=fiscal_year - 1, month=12, day=1)
    end = pd.Timestamp(year=fiscal_year, month=11, day=30, hour=23, minute=59, second=59)
    data = hist[(dates >= start) & (dates <= end)]
    data = _filter_person(data, params.get("person"), params.get("role"))
    data = _filter_product(data, params.get("product"))
    return "Not Applicable" if data.empty else _sum(data, "sign_box_cnt")


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
    status = params.get("status")
    if status and "check_result_name" in display.columns:
        display = display[display["check_result_name"].astype(str) == str(status)]
    return int(len(display))


def _retail_display_fee_rate(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    display = _filter_execute_ym(_display_plan_table(tables), params.get("ym"))
    display = _filter_person(display, params.get("person"), params.get("role"))
    numerator = _sum(display, "confirm_amt")
    hist = _filter_ym(_history_table(tables), "sign_time", params.get("ym"))
    hist = _filter_person(hist, params.get("person"), params.get("role"))
    denominator = _sum(hist, "sign_amt")
    return "Not Applicable" if denominator == 0 else numerator / denominator * 100


def _retail_display_pass_rate(tables: dict[str, pd.DataFrame], params: dict[str, Any]) -> float | str:
    display = _filter_execute_ym(_display_plan_table(tables), params.get("ym"))
    item = params.get("display_item")
    if item:
        display = display[display["dsp_name"].astype(str) == str(item)]
    checked = display[display["check_result_name"].notna()]
    if checked.empty:
        return "Not Applicable"
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
    data = hist[
        (_numeric(hist["sign_box_cnt"]) > 0)
        & (hist["cmdt_tag_name"].astype(str).isin({"活动本品", "普通本品", "特价商品"}))
        & (~hist["ord_type_name"].astype(str).isin({"分销退货", "库存盘点"}))
    ]
    counts = data.groupby("cust_name", dropna=True)["sku_code"].nunique().sort_values(ascending=False)
    if counts.empty:
        return "Not Applicable"
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
        inactive_tokens = ("停用", "终止", "无效", "失效", "关闭", "取消")
        status = customer[status_column].fillna("").astype(str)
        active_mask = ~status.apply(lambda value: any(token in value for token in inactive_tokens))
        customer = customer[active_mask]
    return customer


def _filter_product(data: pd.DataFrame, product: Any) -> pd.DataFrame:
    if not product:
        return data
    text = str(product)
    product_columns = [column for column in ("ctg_name", "brand_name", "sales_ana_type_name", "cmdt_name", "sku_name") if column in data.columns]
    if not product_columns:
        return data
    mask = pd.Series(False, index=data.index)
    for column in product_columns:
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


def _split_ym(ym: Any) -> tuple[int | None, int | None]:
    if ym is None:
        return None, None
    text = str(int(ym))
    if len(text) != 6:
        return None, None
    return int(text[:4]), int(text[4:])


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
