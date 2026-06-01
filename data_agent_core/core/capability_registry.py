"""Capability metadata shared by planner, executors, verifier, and reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


SQL_SUPPORT_NATIVE = "native_sql"
SQL_SUPPORT_SHARED_RULE_ENGINE = "shared_rule_engine"
SQL_SUPPORT_UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class CapabilityMetadata:
    """Stable capability-family metadata for one operation."""

    operation: str
    capability_family: str
    input_contract: str
    output_contract: str
    supports_pandas: bool
    sql_support: str
    supports_chinese: bool
    supports_english: bool
    requires_rule_context: bool = False
    support_boundary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready metadata payload."""

        return asdict(self)


SQL_NATIVE_OPERATIONS = frozenset(
    {
        "aggregation",
        "ranking",
        "row_count",
        "distinct_count",
        "metric_per_distinct_entity",
        "repeat_entity_percentage",
        "repeat_entity_count",
        "null_check",
        "top_k_share",
        "filtered_metric_ranking",
        "rank_by_metric",
        "top_count",
        "group_average",
        "field_values",
        "boolean_percentage",
        "boolean_count_ratio",
        "fraud_rate_filtered",
        "not_applicable",
    }
)

RULE_ENGINE_OPERATIONS = frozenset(
    {
        "average_fee_for_filters",
        "fee_ids_for_filters",
        "applicable_fee_ids",
        "total_fees",
        "fee_rate_delta",
        "card_scheme_steering",
        "cheapest_card_scheme_for_transaction",
        "fee_restriction_affected_merchants",
        "mcc_change_delta",
        "best_fraud_aci_choice",
        "aci_fee_extreme",
        "fee_extreme_by_dimension",
        "fee_factor_direction",
        "fee_volume_threshold",
    }
)

VDS_BI_OPERATIONS = frozenset(
    {
        "vds_period_rank_change",
        "vds_period_delta_top",
        "vds_period_growth_count_share",
        "vds_period_threshold_count",
        "vds_period_rate_top",
        "vds_current_threshold_top",
        "vds_current_category_share_top",
        "vds_current_filtered_metric_top",
        "vds_peer_anomaly",
        "vds_period_group_comparison",
        "vds_current_rank_with_period_change",
        "vds_group_top_entities",
        "vds_status_impact_top",
        "vds_current_share_top",
        "vds_current_top",
        "vds_three_period_top",
    }
)

CHINESE_RETAIL_OPERATIONS = frozenset(
    {
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
        "retail_route_scope_metric_summary",
        "retail_route_scope_difference_reason",
        "retail_route_scope_employee_ranking",
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
        "retail_employee_distribution_monthly_trend",
        "retail_visit_weekday_distribution",
        "retail_route_plan_daily_trend",
        "retail_route_plan_employee_count_ranking",
        "retail_display_status_monthly_distribution",
        "retail_display_confirm_amount_category_monthly_top",
        "retail_contract_customer_monthly_structure",
        "retail_freezer_customer_monthly_trend",
        "retail_freezer_door_average_monthly_trend",
        "retail_sku_check_brand_pass_rate_top",
        "retail_today_category_amount_share",
        "retail_display_execution_monthly_dual_trend",
        "retail_distribution_monthly_yoy_compare",
        "retail_category_distribution_periodic_trend",
        "retail_category_three_month_rank",
        "retail_manager_target_monthly_change",
        "retail_contract_customer_monthly_trend",
        "retail_freezer_customer_monthly_change",
        "retail_display_unqualified_rate_monthly",
        "retail_sku_check_monthly_pass_rate",
        "retail_employee_target_reached_monthly",
    }
)


_REGISTRY: dict[str, CapabilityMetadata] = {
    "aggregation": CapabilityMetadata(
        operation="aggregation",
        capability_family="metric_aggregation",
        input_contract="table, metric, aggregation, optional dimension and filters",
        output_contract="scalar or grouped rows",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=True,
        supports_english=True,
    ),
    "ranking": CapabilityMetadata(
        operation="ranking",
        capability_family="ranking",
        input_contract="table, dimension, metric, aggregation, sort order, limit",
        output_contract="ordered grouped rows",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=True,
        supports_english=True,
    ),
    "filtered_metric_ranking": CapabilityMetadata(
        operation="filtered_metric_ranking",
        capability_family="filtered_ranking",
        input_contract="table, filters, dimension, metric, aggregation, sort order, limit",
        output_contract="ordered grouped rows after filters",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=True,
        supports_english=True,
    ),
    "rank_by_metric": CapabilityMetadata(
        operation="rank_by_metric",
        capability_family="metric_definition",
        input_contract="metric definition, numerator, denominator, group_by, objective, optional choices",
        output_contract="selected entity plus auditable candidate table",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=True,
        supports_english=True,
        support_boundary="Native SQL currently covers fraud rate metric definitions implemented in sqlite fallback.",
    ),
    "row_count": CapabilityMetadata(
        operation="row_count",
        capability_family="counting",
        input_contract="table and optional filters",
        output_contract="integer count",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=True,
        supports_english=True,
    ),
    "distinct_count": CapabilityMetadata(
        operation="distinct_count",
        capability_family="counting",
        input_contract="table, field, optional filters",
        output_contract="integer distinct count",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=True,
        supports_english=True,
    ),
    "repeat_entity_percentage": CapabilityMetadata(
        operation="repeat_entity_percentage",
        capability_family="entity_grain",
        input_contract="table, entity field, optional filters",
        output_contract="percentage of repeated entities",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=True,
        supports_english=True,
    ),
    "repeat_entity_count": CapabilityMetadata(
        operation="repeat_entity_count",
        capability_family="entity_grain",
        input_contract="table, entity field, minimum count, optional filters",
        output_contract="integer entity count",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=True,
        supports_english=True,
    ),
    "metric_per_distinct_entity": CapabilityMetadata(
        operation="metric_per_distinct_entity",
        capability_family="denominator_selection",
        input_contract="table, metric, entity field, aggregation, optional filters",
        output_contract="metric divided by unique entity denominator",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=True,
        supports_english=True,
    ),
    "top_count": CapabilityMetadata(
        operation="top_count",
        capability_family="ranking",
        input_contract="table, group_by, optional filters and choices",
        output_contract="top group value or choice label",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=True,
        supports_english=True,
    ),
    "group_average": CapabilityMetadata(
        operation="group_average",
        capability_family="group_metric",
        input_contract="table, group_by, metric, optional filters",
        output_contract="grouped average rows",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=False,
        supports_english=True,
        support_boundary="Currently tuned for DABstep payment fields.",
    ),
    "top_k_share": CapabilityMetadata(
        operation="top_k_share",
        capability_family="share_of_total",
        input_contract="table, dimension, metric or count denominator, top k, optional filters",
        output_contract="percentage share",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=True,
        supports_english=True,
    ),
    "field_values": CapabilityMetadata(
        operation="field_values",
        capability_family="field_alias_and_values",
        input_contract="table field or shared rule-engine knowledge field",
        output_contract="sorted unique values",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=True,
        supports_english=True,
        support_boundary="Native SQL covers table columns; rule knowledge fields remain shared-rule-engine coverage.",
    ),
    "schema_field_lookup": CapabilityMetadata(
        operation="schema_field_lookup",
        capability_family="field_alias_and_values",
        input_contract="semantic concept and available schema",
        output_contract="matched field name",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_UNSUPPORTED,
        supports_chinese=True,
        supports_english=True,
    ),
    "null_check": CapabilityMetadata(
        operation="null_check",
        capability_family="data_quality",
        input_contract="table, optional field, missing-value mode, optional filters",
        output_contract="count, rate, field name, or yes/no payload",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=True,
        supports_english=True,
    ),
    "missing_columns_choice": CapabilityMetadata(
        operation="missing_columns_choice",
        capability_family="data_quality",
        input_contract="candidate fields and multiple-choice options",
        output_contract="choice label or field list",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_UNSUPPORTED,
        supports_chinese=False,
        supports_english=True,
    ),
    "duplicate_check": CapabilityMetadata(
        operation="duplicate_check",
        capability_family="data_quality",
        input_contract="table and optional duplicate subset",
        output_contract="yes/no payload plus duplicate row count",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_UNSUPPORTED,
        supports_chinese=True,
        supports_english=True,
    ),
    "data_quality_report": CapabilityMetadata(
        operation="data_quality_report",
        capability_family="data_quality",
        input_contract="dataset tables and column profiles",
        output_contract="quality score, issue list, and cleaning suggestions",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_UNSUPPORTED,
        supports_chinese=True,
        supports_english=True,
        support_boundary="Reports likely issues and suggested cleaning actions only; it does not mutate uploaded data.",
    ),
    "boolean_percentage": CapabilityMetadata(
        operation="boolean_percentage",
        capability_family="boolean_ratio",
        input_contract="table, boolean field, expected value, optional filters",
        output_contract="percentage",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=True,
        supports_english=True,
    ),
    "boolean_count_ratio": CapabilityMetadata(
        operation="boolean_count_ratio",
        capability_family="boolean_ratio",
        input_contract="table, boolean field, left and right values, optional filters",
        output_contract="ratio or not applicable",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=True,
        supports_english=True,
    ),
    "fraud_rate_filtered": CapabilityMetadata(
        operation="fraud_rate_filtered",
        capability_family="metric_definition",
        input_contract="fraud metric definition plus filters",
        output_contract="fraudulent volume percentage",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=False,
        supports_english=True,
    ),
    "fraud_rate_fluctuation": CapabilityMetadata(
        operation="fraud_rate_fluctuation",
        capability_family="metric_definition",
        input_contract="fraud metric definition, group_by, time period, objective, optional filters",
        output_contract="selected entity plus auditable period-rate std candidate table",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_UNSUPPORTED,
        supports_chinese=False,
        supports_english=True,
    ),
    "fraud_rate_comparison": CapabilityMetadata(
        operation="fraud_rate_comparison",
        capability_family="metric_definition",
        input_contract="two filtered populations and fraud-rate metric definition",
        output_contract="yes/no comparison",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_UNSUPPORTED,
        supports_chinese=False,
        supports_english=True,
    ),
    "worst_fraud_segment": CapabilityMetadata(
        operation="worst_fraud_segment",
        capability_family="metric_definition",
        input_contract="fraud-rate metric definition and candidate dimensions",
        output_contract="selected segment plus candidate table",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_UNSUPPORTED,
        supports_chinese=False,
        supports_english=True,
    ),
    "outlier_count": CapabilityMetadata(
        operation="outlier_count",
        capability_family="outlier_detection",
        input_contract="table, numeric metric, outlier method, optional filters",
        output_contract="integer count",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_UNSUPPORTED,
        supports_chinese=True,
        supports_english=True,
    ),
    "top_outlier_group": CapabilityMetadata(
        operation="top_outlier_group",
        capability_family="outlier_detection",
        input_contract="table, numeric metric, group_by, outlier method, optional filters",
        output_contract="group value with most outliers",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_UNSUPPORTED,
        supports_chinese=True,
        supports_english=True,
    ),
    "quantile_percentage": CapabilityMetadata(
        operation="quantile_percentage",
        capability_family="distribution_threshold",
        input_contract="table, numeric metric, quantile, direction, optional filters",
        output_contract="percentage above or below quantile",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_UNSUPPORTED,
        supports_chinese=False,
        supports_english=True,
    ),
    "outlier_target_percentage": CapabilityMetadata(
        operation="outlier_target_percentage",
        capability_family="outlier_detection",
        input_contract="outlier metric plus boolean target field",
        output_contract="target percentage among outliers",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_UNSUPPORTED,
        supports_chinese=False,
        supports_english=True,
    ),
    "outlier_rate_comparison": CapabilityMetadata(
        operation="outlier_rate_comparison",
        capability_family="outlier_detection",
        input_contract="outlier metric, target field, comparison direction",
        output_contract="yes/no comparison",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_UNSUPPORTED,
        supports_chinese=False,
        supports_english=True,
    ),
    "correlation_threshold": CapabilityMetadata(
        operation="correlation_threshold",
        capability_family="correlation",
        input_contract="numeric metric, target field, threshold",
        output_contract="yes/no payload with correlation",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_UNSUPPORTED,
        supports_chinese=False,
        supports_english=True,
    ),
    "detail_lookup": CapabilityMetadata(
        operation="detail_lookup",
        capability_family="record_lookup",
        input_contract="table and limit",
        output_contract="sample rows",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_UNSUPPORTED,
        supports_chinese=True,
        supports_english=True,
    ),
    "filtering": CapabilityMetadata(
        operation="filtering",
        capability_family="record_filtering",
        input_contract="table, conditions, limit",
        output_contract="filtered rows",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_UNSUPPORTED,
        supports_chinese=True,
        supports_english=True,
    ),
    "not_applicable": CapabilityMetadata(
        operation="not_applicable",
        capability_family="unsupported_boundary",
        input_contract="unsupported reason and attribution",
        output_contract="not applicable answer",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_NATIVE,
        supports_chinese=True,
        supports_english=True,
    ),
}

for _operation in RULE_ENGINE_OPERATIONS:
    _REGISTRY[_operation] = CapabilityMetadata(
        operation=_operation,
        capability_family="business_rule_what_if",
        input_contract="payments data plus manual, fee rules, and merchant rule context",
        output_contract="business-rule scalar, selected candidate, or candidate table",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_SHARED_RULE_ENGINE,
        supports_chinese=False,
        supports_english=True,
        requires_rule_context=True,
        support_boundary="Short term uses the shared deterministic fee-rule engine; DuckDB table-form rules are a future target.",
    )

for _operation in VDS_BI_OPERATIONS:
    _REGISTRY[_operation] = CapabilityMetadata(
        operation=_operation,
        capability_family="vds_period_comparison",
        input_contract="Chinese BI table, metric, entity grain, current period, previous period, filters, threshold or top-k settings",
        output_contract="table, count, percentage, or text summary depending on the BI operation",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_UNSUPPORTED,
        supports_chinese=True,
        supports_english=False,
        support_boundary="Current implementation is Pandas-backed for uploaded Chinese BI sheets; DuckDB parity is future work.",
    )

for _operation in CHINESE_RETAIL_OPERATIONS:
    _REGISTRY[_operation] = CapabilityMetadata(
        operation=_operation,
        capability_family="chinese_retail_business_metric",
        input_contract="Chinese retail uploaded tables, business month or date, role/person/product filters, metric definition",
        output_contract="number, percentage, ranked text, list, or multi-metric summary",
        supports_pandas=True,
        sql_support=SQL_SUPPORT_UNSUPPORTED,
        supports_chinese=True,
        supports_english=False,
        support_boundary="Current implementation is Pandas-backed and schema-aware; SQL/DuckDB parity is future work.",
    )


def capability_for_operation(operation: str | None) -> CapabilityMetadata:
    """Return metadata for an operation without introducing benchmark-specific routing."""

    normalized = str(operation or "unknown")
    return _REGISTRY.get(
        normalized,
        CapabilityMetadata(
            operation=normalized,
            capability_family="unknown",
            input_contract="unknown",
            output_contract="unknown",
            supports_pandas=False,
            sql_support=SQL_SUPPORT_UNSUPPORTED,
            supports_chinese=False,
            supports_english=False,
        ),
    )


def capability_summary_for_operation(operation: str | None) -> dict[str, Any]:
    """Return a compact JSON-ready capability summary for reports and traces."""

    metadata = capability_for_operation(operation)
    return metadata.to_dict()


def sql_support_for_operation(operation: str | None) -> str:
    """Return SQL support classification for an operation."""

    return capability_for_operation(operation).sql_support


def is_native_sql_operation(operation: str | None) -> bool:
    """Return whether the operation is covered by the current native SQL path."""

    return sql_support_for_operation(operation) == SQL_SUPPORT_NATIVE


def native_sql_support_for_logic_form(logic_form: Any, *, available_columns: Iterable[str] | None = None) -> bool:
    """Return whether native SQL should run for the concrete logic form."""

    operation = _operation_from_logic_form(logic_form)
    if _has_join_plan(logic_form):
        return False
    if _has_derived_metric(logic_form):
        return False
    if not is_native_sql_operation(operation):
        return False
    if operation == "field_values" and available_columns is not None:
        field = _field_from_logic_form(logic_form)
        if field and field not in set(available_columns):
            return False
    return True


def coverage_summary_for_logic_form(logic_form: Any, *, available_columns: Iterable[str] | None = None) -> dict[str, Any]:
    """Return capability and SQL coverage metadata for a concrete logic form."""

    operation = _operation_from_logic_form(logic_form)
    metadata = capability_for_operation(operation)
    sql_support = metadata.sql_support
    native_supported = native_sql_support_for_logic_form(logic_form, available_columns=available_columns)
    reason = ""
    if _has_join_plan(logic_form):
        reason = "Current native SQL path does not materialize uploaded-table join plans."
    elif _has_derived_metric(logic_form):
        reason = "Current native SQL path does not materialize uploaded-table derived ratio metrics."
    elif sql_support == SQL_SUPPORT_SHARED_RULE_ENGINE:
        reason = "Current native SQL path does not cover shared rule-engine operations."
    elif sql_support == SQL_SUPPORT_UNSUPPORTED:
        reason = "Current native SQL path does not cover this capability family."
    elif not native_supported:
        reason = "Current native SQL path covers field_values only when the requested field is a table column."
    return {
        "operation": operation,
        "capability_family": metadata.capability_family,
        "sql_support": sql_support,
        "native_sql_supported": native_supported,
        "coverage_gap": not native_supported,
        "reason": reason,
        "requires_rule_context": metadata.requires_rule_context,
    }


def _operation_from_logic_form(logic_form: Any) -> str:
    if isinstance(logic_form, Mapping):
        return str(logic_form.get("operation") or "unknown")
    return str(getattr(logic_form, "operation", "unknown") or "unknown")


def _field_from_logic_form(logic_form: Any) -> str | None:
    params: Any
    if isinstance(logic_form, Mapping):
        params = logic_form.get("parameters") or {}
    else:
        params = getattr(logic_form, "parameters", {}) or {}
    if isinstance(params, Mapping) and params.get("field"):
        return str(params["field"])
    return None


def _has_join_plan(logic_form: Any) -> bool:
    if isinstance(logic_form, Mapping):
        join_plan = logic_form.get("join_plan") or (logic_form.get("parameters") or {}).get("join_plan")
    else:
        join_plan = getattr(logic_form, "join_plan", None) or (getattr(logic_form, "parameters", {}) or {}).get("join_plan")
    return bool(join_plan)


def _has_derived_metric(logic_form: Any) -> bool:
    if isinstance(logic_form, Mapping):
        derived_metric = (logic_form.get("parameters") or {}).get("derived_metric")
    else:
        derived_metric = (getattr(logic_form, "parameters", {}) or {}).get("derived_metric")
    return bool(derived_metric)
