"""Execution contracts for Pandas, NumPy, SQL, and DuckDB paths."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from data_agent_core.contracts.analysis_contracts import AnalysisPlan


@dataclass
class ExecutionResult:
    """Standard output contract for every execution backend."""

    backend: str
    success: bool
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    value: Any = None
    summary: str = ""
    latency_ms: float | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[Any] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)
    execution_trace: dict[str, Any] = field(default_factory=dict)
    expected_trace: dict[str, Any] = field(default_factory=dict)


def prepare_execution_plan_for_backend(plan: AnalysisPlan, *, source: str) -> tuple[AnalysisPlan, dict[str, Any], list[str]]:
    """Apply contract-derived execution_spec before executor dispatch and build a planned trace."""

    spec = dict(getattr(plan, "execution_spec", {}) or {})
    logic = plan.logic_form
    legacy_params = dict(getattr(logic, "parameters", {}) or {})
    params = dict(legacy_params)
    filters = dict(getattr(logic, "filters", {}) or {})
    warnings: list[str] = []
    operation = str(getattr(logic, "operation", "") or "not_applicable")
    task_type = str(getattr(logic, "task_type", "") or "unknown")
    trace_source = "legacy_logic_form"
    if spec:
        trace_source = "execution_spec"
        operation = str(spec.get("physical_operation") or spec.get("operation") or operation)
        task_type = str(spec.get("task_type") or task_type)
        metric_columns = [str(item) for item in spec.get("metric_columns") or [] if str(item)]
        dimensions = [str(item) for item in spec.get("dimensions") or [] if str(item)]
        ranking = spec.get("ranking") if isinstance(spec.get("ranking"), Mapping) else {}
        if metric_columns:
            _record_mismatch(warnings, "metric", legacy_params.get("metric"), metric_columns[0])
            params["metric"] = metric_columns[0]
            if _spec_primary_metric_semantic_type(spec) == "entity_count" and not dimensions and not ranking:
                _record_mismatch(warnings, "operation", getattr(logic, "operation", None), "distinct_count")
                operation = "distinct_count"
                params["field"] = metric_columns[0]
        aggregation = spec.get("aggregation")
        if aggregation:
            _record_mismatch(warnings, "aggregation", legacy_params.get("aggregation"), aggregation)
            params["aggregation"] = aggregation
        formula = spec.get("formula")
        if formula not in (None, "", {}, []):
            params.setdefault("derived_metric", _derived_metric_payload(spec, formula))
        if dimensions:
            _record_mismatch(warnings, "dimension", legacy_params.get("dimension") or getattr(logic, "group_by", None), dimensions[0])
            params["dimension"] = dimensions[0]
            params["group_by"] = dimensions[0]
        spec_filters = _filters_from_spec(spec.get("filters"))
        if spec_filters:
            for column, expected in spec_filters.items():
                if column in filters and filters[column] != expected:
                    warnings.append(f"execution_spec mismatch: filter {column} overrides legacy value {filters[column]!r}")
            filters = {**filters, **spec_filters}
        time_spec = spec.get("time") if isinstance(spec.get("time"), Mapping) else {}
        if time_spec:
            if time_spec.get("time_column"):
                params["time_column"] = time_spec.get("time_column")
            if time_spec.get("grain"):
                params["time_grain"] = time_spec.get("grain")
                params["time_bucket"] = time_spec.get("grain")
        if ranking:
            if ranking.get("order"):
                params["sort_order"] = ranking.get("order")
            if ranking.get("limit") is not None:
                params["limit"] = ranking.get("limit")
        if not spec.get("metric_columns") and legacy_params.get("metric"):
            trace_source = "mixed"
    effective_logic = replace(
        logic,
        task_type=task_type,
        operation=operation,
        metric=params.get("metric") or getattr(logic, "metric", None),
        group_by=params.get("dimension") or params.get("group_by") or getattr(logic, "group_by", None),
        filters=filters,
        parameters=params,
    )
    effective_plan = replace(plan, logic_form=effective_logic)
    trace = build_expected_execution_trace(effective_plan, source=source, trace_source=trace_source, trace_status="partial" if trace_source == "mixed" else "complete")
    if warnings:
        trace["trace_warnings"] = list(warnings)
    return effective_plan, trace, warnings


def build_expected_execution_trace(
    plan: AnalysisPlan,
    *,
    source: str,
    trace_source: str = "planned",
    trace_status: str = "complete",
) -> dict[str, Any]:
    logic = plan.logic_form
    params = dict(getattr(logic, "parameters", {}) or {})
    filters = dict(getattr(logic, "filters", {}) or {})
    ranking_limit = params.get("limit") if params.get("limit") is not None else params.get("rank_position")
    return {
        "operation": str(getattr(logic, "operation", "") or ""),
        "metric_columns": _trace_metric_columns(logic, params),
        "aggregation": params.get("aggregation"),
        "formula": _trace_formula(logic, params),
        "groupby_columns": _trace_groupby_columns(logic, params),
        "filters_applied": _trace_filters(filters),
        "comparison_type": _trace_comparison_type(params),
        "time_column": params.get("time_column") or params.get("source_time_field"),
        "time_grain": params.get("time_grain") or params.get("time_bucket"),
        "ranking": {
            "order": params.get("sort_order") or ("asc" if str(getattr(logic, "objective", "")).lower() in {"min", "lowest"} else "desc"),
            "limit": ranking_limit,
        },
        "source": source,
        "trace_status": trace_status,
        "trace_source": trace_source,
        "trace_is_actual": False,
    }


def build_execution_trace(
    plan: AnalysisPlan,
    *,
    source: str,
    trace_source: str = "planned",
    trace_status: str = "complete",
) -> dict[str, Any]:
    """Backward-compatible alias for planned trace construction."""

    return build_expected_execution_trace(plan, source=source, trace_source=trace_source, trace_status=trace_status)


def build_actual_execution_trace(
    plan: AnalysisPlan,
    *,
    source: str,
    operation: str | None = None,
    trace_status: str = "complete",
    include_metrics: bool = False,
    include_aggregation: bool = False,
    include_formula: bool = False,
    include_groupby: bool = False,
    include_filters: bool = False,
    include_comparison: bool = False,
    include_time: bool = False,
    include_ranking: bool = False,
    extra_filters: list[dict[str, Any]] | None = None,
    trace_warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build an actual executor trace from fields a branch confirms it used."""

    logic = plan.logic_form
    params = dict(getattr(logic, "parameters", {}) or {})
    filters = dict(getattr(logic, "filters", {}) or {})
    trace = empty_actual_execution_trace(
        operation=operation or str(getattr(logic, "operation", "") or ""),
        source=source,
        trace_status=trace_status,
    )
    if include_metrics:
        trace["metric_columns"] = _trace_metric_columns(logic, params)
    if include_aggregation:
        trace["aggregation"] = params.get("aggregation")
    if include_formula:
        trace["formula"] = _trace_formula(logic, params)
    if include_groupby:
        trace["groupby_columns"] = _trace_groupby_columns(logic, params)
    if include_filters:
        trace["filters_applied"] = _trace_filters(filters) + list(extra_filters or [])
    elif extra_filters:
        trace["filters_applied"] = list(extra_filters)
    if include_comparison:
        trace["comparison_type"] = _trace_comparison_type(params)
    if include_time:
        trace["time_column"] = params.get("time_column") or params.get("source_time_field")
        trace["time_grain"] = params.get("time_grain") or params.get("time_bucket")
    if include_ranking:
        ranking_limit = params.get("limit") if params.get("limit") is not None else params.get("rank_position")
        trace["ranking"] = {
            "order": params.get("sort_order") or ("asc" if str(getattr(logic, "objective", "")).lower() in {"min", "lowest"} else "desc"),
            "limit": ranking_limit,
        }
    if trace_warnings:
        trace["trace_warnings"] = list(trace_warnings)
    return trace


def empty_actual_execution_trace(*, operation: str, source: str, trace_status: str = "unsupported") -> dict[str, Any]:
    """Return a stable empty actual trace for branches with limited evidence."""

    return {
        "operation": str(operation or ""),
        "metric_columns": [],
        "aggregation": None,
        "formula": None,
        "groupby_columns": [],
        "filters_applied": [],
        "comparison_type": None,
        "time_column": None,
        "time_grain": None,
        "ranking": {"order": None, "limit": None},
        "source": source,
        "trace_status": trace_status,
        "trace_source": "actual_executor",
        "trace_is_actual": True,
    }


def _record_mismatch(warnings: list[str], field_name: str, legacy_value: Any, spec_value: Any) -> None:
    if legacy_value in (None, "", [], {}):
        return
    if str(legacy_value) != str(spec_value):
        warnings.append(f"execution_spec mismatch: {field_name} {spec_value!r} overrides legacy value {legacy_value!r}")


def _filters_from_spec(raw_filters: Any) -> dict[str, Any]:
    output: dict[str, Any] = {}
    if not isinstance(raw_filters, list):
        return output
    for item in raw_filters:
        if not isinstance(item, Mapping):
            continue
        column = str(item.get("column") or "").strip()
        if not column:
            continue
        values = list(item.get("values") or [])
        operator = str(item.get("operator") or "eq")
        if operator in {"in", "contains_any"} or len(values) > 1:
            output[column] = values
        elif operator not in {"eq", "="}:
            output[column] = {"operator": operator, "value": values[0] if values else None}
        else:
            output[column] = values[0] if values else None
    return output


def _derived_metric_payload(spec: Mapping[str, Any], formula: Any) -> dict[str, Any]:
    metrics = [item for item in spec.get("metrics") or [] if isinstance(item, Mapping)]
    metric = metrics[0] if metrics else {}
    columns = [str(item) for item in metric.get("resolved_columns") or [] if str(item)]
    return {
        "name": metric.get("display_name") or "derived_metric",
        "formula": formula,
        "columns": columns,
    }


def _spec_primary_metric_semantic_type(spec: Mapping[str, Any]) -> str:
    metrics = [item for item in spec.get("metrics") or [] if isinstance(item, Mapping)]
    if not metrics:
        return ""
    return str(metrics[0].get("semantic_type") or "")


def _trace_metric_columns(logic: Any, params: Mapping[str, Any]) -> list[str]:
    columns: list[str] = []
    for value in [params.get("metric"), getattr(logic, "metric", None), params.get("field")]:
        text = str(value or "").strip()
        if text and text not in {"__row_count__", "row_count"} and text not in columns:
            columns.append(text)
    for item in params.get("metrics") or []:
        text = str(item or "").strip()
        if text and text not in columns:
            columns.append(text)
    for spec in params.get("metric_specs") or []:
        if isinstance(spec, Mapping):
            text = str(spec.get("field") or spec.get("name") or "").strip()
            if text and text not in columns:
                columns.append(text)
    derived = params.get("derived_metric")
    if isinstance(derived, Mapping):
        for key in ("numerator", "denominator"):
            text = str(derived.get(key) or "").strip()
            if text and text not in columns:
                columns.append(text)
        for item in derived.get("columns") or []:
            text = str(item or "").strip()
            if text and text not in columns:
                columns.append(text)
    return columns


def _trace_formula(logic: Any, params: Mapping[str, Any]) -> Any:
    derived = params.get("derived_metric")
    if isinstance(derived, Mapping) and derived:
        return derived.get("formula") or derived
    metric_definition = getattr(logic, "metric_definition", None)
    if isinstance(metric_definition, Mapping):
        return metric_definition.get("formula")
    return None


def _trace_groupby_columns(logic: Any, params: Mapping[str, Any]) -> list[str]:
    if str(getattr(logic, "operation", "") or "") in {"distinct_count", "row_count"}:
        return []
    time_grain = str(params.get("time_grain") or params.get("time_bucket") or "").strip().lower()
    time_column = str(params.get("time_column") or params.get("source_time_field") or "").strip()
    columns: list[str] = []
    for value in [
        params.get("dimension"),
        params.get("group_by"),
        params.get("series_dimension"),
        getattr(logic, "group_by", None),
        params.get("entity"),
        params.get("entity_field"),
    ]:
        text = str(value or "").strip()
        if time_grain == "month" and time_column and text == time_column:
            text = "month"
        if text and text not in columns:
            columns.append(text)
    return columns


def _trace_filters(filters: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for column, expected in filters.items():
        if expected is None:
            continue
        if isinstance(expected, Mapping) and "operator" in expected:
            output.append({"column": str(column), "operator": str(expected.get("operator") or "="), "values": [expected.get("value")]})
            continue
        if isinstance(expected, (list, tuple, set)):
            output.append({"column": str(column), "operator": "in", "values": list(expected)})
            continue
        output.append({"column": str(column), "operator": "eq", "values": [expected]})
    return output


def _trace_comparison_type(params: Mapping[str, Any]) -> str | None:
    comparison = params.get("comparison")
    if isinstance(comparison, Mapping) and comparison.get("type"):
        return str(comparison.get("type"))
    if params.get("requires_gap_comparison"):
        return "category_comparison"
    if params.get("growth_mode") or params.get("lag"):
        return "time_adjacent_diff"
    return None
