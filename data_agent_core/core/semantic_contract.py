"""Canonical semantic contract for schema-aware analysis planning.

This layer is intentionally provider-neutral and domain-agnostic. It turns
parser/LLM/schema signals into one serializable contract that can be attached to
LogicForm, AnalysisPlan, verifier debug, and traces.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
import re
from typing import Any, Mapping


CONTRACT_VERSION = 1


@dataclass
class ResolvedMetric:
    metric_id: str | None = None
    display_name: str = ""
    source_text: str | None = None
    semantic_type: str = "metric"
    aggregation: str | None = None
    formula: dict[str, Any] | str | None = None
    resolved_columns: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolvedDimension:
    dimension_id: str | None = None
    display_name: str = ""
    source_text: str | None = None
    semantic_type: str = "dimension"
    resolved_column: str | None = None
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolvedFilter:
    dimension_id: str | None = None
    display_name: str = ""
    source_text: str | None = None
    resolved_column: str | None = None
    operator: str = "eq"
    values: list[Any] = field(default_factory=list)
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolvedComparison:
    type: str = ""
    metric_ref: str | None = None
    dimension_ref: str | None = None
    left: dict[str, Any] | None = None
    right: dict[str, Any] | None = None
    operator: str | None = None
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolvedTimeSpec:
    time_column: str | None = None
    grain: str | None = None
    range: dict[str, Any] | None = None
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolvedRanking:
    order: str = "desc"
    limit: int | None = None
    metric_ref: str | None = None
    dimension_ref: str | None = None
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CanonicalSemanticContract:
    contract_version: int = CONTRACT_VERSION
    route: str = "analysis"
    task_type: str = "unknown"
    capability_family: str = "unknown"
    physical_operation: str | None = None
    metrics: list[ResolvedMetric] = field(default_factory=list)
    dimensions: list[ResolvedDimension] = field(default_factory=list)
    filters: list[ResolvedFilter] = field(default_factory=list)
    comparison: ResolvedComparison | None = None
    time: ResolvedTimeSpec | None = None
    ranking: ResolvedRanking | None = None
    dataset_semantics: dict[str, Any] | None = None
    grain: dict[str, Any] | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    ambiguities: list[dict[str, Any]] = field(default_factory=list)
    validation_issues: list[dict[str, Any]] = field(default_factory=list)
    needs_clarification: bool = False
    confidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "route": self.route,
            "task_type": self.task_type,
            "capability_family": self.capability_family,
            "physical_operation": self.physical_operation,
            "metrics": [item.to_dict() for item in self.metrics],
            "dimensions": [item.to_dict() for item in self.dimensions],
            "filters": [item.to_dict() for item in self.filters],
            "comparison": None if self.comparison is None else self.comparison.to_dict(),
            "time": None if self.time is None else self.time.to_dict(),
            "ranking": None if self.ranking is None else self.ranking.to_dict(),
            "dataset_semantics": self.dataset_semantics,
            "grain": self.grain,
            "evidence": self.evidence,
            "ambiguities": self.ambiguities,
            "validation_issues": self.validation_issues,
            "needs_clarification": self.needs_clarification,
            "confidence": self.confidence,
        }


def build_lightweight_schema_semantic_profile(
    context: Mapping[str, Any] | None = None,
    dataset_profile: Any | None = None,
) -> dict[str, Any]:
    """Build a compact semantic profile available to Planner before Data Engineer.

    The profile is deliberately lightweight: column names, coarse types, hints,
    low-cardinality values, and candidate roles. It does not execute analysis.
    """

    profile_payload = _to_plain_dict(dataset_profile)
    tables_payload: list[dict[str, Any]] = []
    if profile_payload:
        for table in profile_payload.get("tables") or []:
            if isinstance(table, Mapping):
                tables_payload.append(_table_profile_from_contract(table))
    if not tables_payload and context:
        tables = context.get("tables")
        if isinstance(tables, Mapping):
            for table_name, df in tables.items():
                tables_payload.append(_table_profile_from_dataframe(str(table_name), df))
        elif context.get("payments") is not None:
            tables_payload.append(_table_profile_from_dataframe("payments", context["payments"]))

    candidates = _schema_candidates(tables_payload)
    return {
        "profile_version": 1,
        "tables": tables_payload,
        "candidates": candidates,
        "column_index": _column_index(tables_payload),
    }


def build_canonical_semantic_contract(
    *,
    question: str,
    route: str = "analysis",
    selected_logic_form: Any | None = None,
    deterministic_logic_form: Any | None = None,
    llm_logic_form: Any | None = None,
    llm_intent: Mapping[str, Any] | None = None,
    llm_plan: Mapping[str, Any] | None = None,
    schema_profile: Mapping[str, Any] | None = None,
    column_mapping: Mapping[str, Any] | None = None,
) -> CanonicalSemanticContract:
    """Arbitrate parser/LLM/schema signals into one canonical contract."""

    selected = selected_logic_form or deterministic_logic_form or llm_logic_form
    candidate_payloads = _semantic_candidate_payloads(
        selected_logic_form=selected_logic_form,
        deterministic_logic_form=deterministic_logic_form,
        llm_logic_form=llm_logic_form,
        llm_intent=llm_intent,
        llm_plan=llm_plan,
    )
    physical_operation = _first_text(_field(selected, "operation"), _field(deterministic_logic_form, "operation"), _field(llm_logic_form, "operation"))
    task_type = _canonical_task_type(question, selected, physical_operation)
    capability_family = _canonical_capability_family(question, selected, task_type, physical_operation)
    metrics = _resolve_metrics(question, selected, schema_profile or {}, column_mapping or {})
    dimensions = _resolve_dimensions(question, selected, schema_profile or {}, column_mapping or {})
    filters = _resolve_filters(question, selected, schema_profile or {}, column_mapping or {})
    comparison = _resolve_comparison(question, metrics, dimensions, filters, selected)
    time = _resolve_time_spec(question, selected, schema_profile or {})
    ranking = _resolve_ranking(question, metrics, dimensions, selected, task_type)
    grain = _grain_from_logic(selected)
    validation_issues = _validate_contract(
        task_type=task_type,
        capability_family=capability_family,
        metrics=metrics,
        dimensions=dimensions,
        filters=filters,
        comparison=comparison,
        ranking=ranking,
    )
    confidence = _confidence(candidate_payloads, metrics, dimensions, filters)
    return CanonicalSemanticContract(
        route=route,
        task_type=task_type,
        capability_family=capability_family,
        physical_operation=physical_operation or None,
        metrics=metrics,
        dimensions=dimensions,
        filters=filters,
        comparison=comparison,
        time=time,
        ranking=ranking,
        dataset_semantics=_compact_dataset_semantics(schema_profile or {}),
        grain=grain,
        evidence={
            "question": question,
            "candidate_sources": [candidate["source"] for candidate in candidate_payloads],
            "candidates": candidate_payloads,
            "arbitration": {
                "selected_logic_form_is_execution_seed": selected_logic_form is not None,
                "deterministic_parser_is_candidate": deterministic_logic_form is not None,
                "llm_intent_is_candidate": llm_intent is not None,
                "llm_plan_is_candidate": llm_logic_form is not None or llm_plan is not None,
                "schema_profile_used": bool(schema_profile),
            },
        },
        ambiguities=_ambiguities(metrics, dimensions, filters),
        validation_issues=validation_issues,
        needs_clarification=any(issue.get("severity") == "needs_clarification" for issue in validation_issues),
        confidence=confidence,
    )


def ensure_canonical_semantic_contract(value: Any) -> CanonicalSemanticContract | None:
    """Return a CanonicalSemanticContract from a dataclass or dict payload."""

    if value is None:
        return None
    if isinstance(value, CanonicalSemanticContract):
        return value
    if not isinstance(value, Mapping) or not value:
        return None
    return CanonicalSemanticContract(
        contract_version=int(value.get("contract_version") or CONTRACT_VERSION),
        route=str(value.get("route") or "analysis"),
        task_type=str(value.get("task_type") or "unknown"),
        capability_family=str(value.get("capability_family") or "unknown"),
        physical_operation=value.get("physical_operation"),
        metrics=[_metric_from_payload(item) for item in value.get("metrics") or [] if isinstance(item, Mapping)],
        dimensions=[_dimension_from_payload(item) for item in value.get("dimensions") or [] if isinstance(item, Mapping)],
        filters=[_filter_from_payload(item) for item in value.get("filters") or [] if isinstance(item, Mapping)],
        comparison=_comparison_from_payload(value.get("comparison")),
        time=_time_from_payload(value.get("time")),
        ranking=_ranking_from_payload(value.get("ranking")),
        dataset_semantics=dict(value.get("dataset_semantics") or {}) if isinstance(value.get("dataset_semantics"), Mapping) else None,
        grain=dict(value.get("grain") or {}) if isinstance(value.get("grain"), Mapping) else None,
        evidence=dict(value.get("evidence") or {}),
        ambiguities=[dict(item) for item in value.get("ambiguities") or [] if isinstance(item, Mapping)],
        validation_issues=[dict(item) for item in value.get("validation_issues") or [] if isinstance(item, Mapping)],
        needs_clarification=bool(value.get("needs_clarification")),
        confidence=dict(value.get("confidence") or {}) if isinstance(value.get("confidence"), Mapping) else None,
    )


def semantic_contract_payload(value: Any) -> dict[str, Any]:
    contract = ensure_canonical_semantic_contract(value)
    return {} if contract is None else contract.to_dict()


def apply_semantic_contract_to_logic_form(logic_form: Any, contract: Any) -> Any:
    """Copy contract-derived canonical fields into a LogicForm-compatible object."""

    canonical = ensure_canonical_semantic_contract(contract)
    if canonical is None:
        return logic_form
    logic = logic_form
    payload = canonical.to_dict()
    if hasattr(logic, "semantic_contract"):
        setattr(logic, "semantic_contract", payload)
    params = _dict_field(logic, "parameters")
    output_contract = _dict_field(logic, "output_contract")
    if canonical.task_type and canonical.task_type != "unknown":
        setattr(logic, "task_type", canonical.task_type)
    params["capability_family"] = canonical.capability_family
    output_contract["capability_family"] = canonical.capability_family
    metric = canonical.metrics[0] if canonical.metrics else None
    if metric is not None:
        metric_column = metric.resolved_columns[0] if metric.resolved_columns else None
        metric_value = metric_column or metric.display_name
        if metric_value and not _sentinel_metric(metric_value):
            existing_metric = getattr(logic, "metric", None)
            if not existing_metric or (metric.semantic_type == "entity_count" and _sentinel_metric(str(existing_metric))):
                setattr(logic, "metric", metric_value)
            if metric.semantic_type == "entity_count" and _sentinel_metric(str(params.get("metric") or "")):
                params["metric"] = metric_value
            else:
                params.setdefault("metric", metric_value)
        elif metric.display_name and metric.semantic_type in {"row_count", "entity_count"}:
            params.setdefault("metric_semantic_type", metric.semantic_type)
        if metric.aggregation:
            if metric.semantic_type == "entity_count" and str(params.get("aggregation") or "") == "count":
                params["aggregation"] = metric.aggregation
            else:
                params.setdefault("aggregation", metric.aggregation)
        metric_definition = _dict_field(logic, "metric_definition")
        metric_definition.setdefault("name", metric.display_name or metric_column or "")
        metric_definition.setdefault("capability_family", canonical.capability_family)
        if metric.aggregation:
            metric_definition.setdefault("aggregation", metric.aggregation)
        if metric.formula:
            metric_definition.setdefault("formula", metric.formula)
            params.setdefault("derived_metric", {"name": metric.display_name, "formula": metric.formula})
    dimension = canonical.dimensions[0] if canonical.dimensions else None
    if dimension is not None and dimension.resolved_column:
        if not getattr(logic, "group_by", None):
            setattr(logic, "group_by", dimension.resolved_column)
        params.setdefault("dimension", dimension.resolved_column)
        params.setdefault("group_by", dimension.resolved_column)
        entity_grain = _dict_field(logic, "entity_grain")
        entity_grain.setdefault("field", dimension.resolved_column)
        entity_grain.setdefault("role", dimension.semantic_type or "dimension")
    filters = _dict_field(logic, "filters")
    for item in canonical.filters:
        if not item.resolved_column:
            continue
        value: Any
        if item.operator == "in" or len(item.values) > 1:
            value = list(item.values)
        else:
            value = item.values[0] if item.values else None
        if value not in (None, [], ""):
            filters.setdefault(item.resolved_column, value)
    if canonical.comparison is not None:
        params.setdefault("comparison", canonical.comparison.to_dict())
        if canonical.comparison.type in {"pairwise_gap", "category_pair_gap"}:
            params.setdefault("requires_gap_comparison", True)
    if canonical.time is not None:
        if canonical.time.time_column:
            params.setdefault("time_column", canonical.time.time_column)
        if canonical.time.grain:
            params.setdefault("time_bucket", canonical.time.grain)
            params.setdefault("time_grain", canonical.time.grain)
    if canonical.ranking is not None:
        params.setdefault("sort_order", canonical.ranking.order)
        if canonical.ranking.limit is not None:
            params.setdefault("limit", canonical.ranking.limit)
    return logic


def build_execution_spec_from_semantic_contract(contract: Any, logic_form: Any | None = None) -> dict[str, Any]:
    """Build a normalized executor-facing spec from the canonical contract."""

    canonical = ensure_canonical_semantic_contract(contract)
    logic = _logic_payload(logic_form)
    params = dict(logic.get("parameters") or {})
    if canonical is None:
        return {}
    metric_specs = []
    for metric in canonical.metrics:
        metric_specs.append(
            {
                "metric_id": metric.metric_id,
                "display_name": metric.display_name,
                "semantic_type": metric.semantic_type,
                "aggregation": metric.aggregation,
                "formula": metric.formula,
                "resolved_columns": list(metric.resolved_columns),
                "depends_on": list(metric.depends_on),
            }
        )
    dimension_specs = [
        {
            "dimension_id": dimension.dimension_id,
            "display_name": dimension.display_name,
            "semantic_type": dimension.semantic_type,
            "resolved_column": dimension.resolved_column,
        }
        for dimension in canonical.dimensions
    ]
    filters = [
        {
            "column": item.resolved_column,
            "operator": item.operator or "eq",
            "values": list(item.values),
            "source_text": item.source_text,
        }
        for item in canonical.filters
        if item.resolved_column
    ]
    ranking = canonical.ranking.to_dict() if canonical.ranking is not None else {}
    time_spec = canonical.time.to_dict() if canonical.time is not None else {}
    operation = canonical.physical_operation or _first_text(logic.get("operation"), canonical.task_type)
    metric_columns = _spec_metric_columns(metric_specs, params)
    dimensions = [str(item["resolved_column"]) for item in dimension_specs if item.get("resolved_column")]
    return {
        "spec_version": 1,
        "operation": operation,
        "task_type": canonical.task_type,
        "capability_family": canonical.capability_family,
        "metrics": metric_specs,
        "metric_columns": metric_columns,
        "dimensions": dimensions,
        "filters": filters,
        "comparison": canonical.comparison.to_dict() if canonical.comparison is not None else {},
        "time": time_spec,
        "ranking": ranking,
        "physical_operation": canonical.physical_operation or operation,
        "aggregation": _spec_aggregation(metric_specs, params),
        "formula": _spec_formula(metric_specs, params),
    }


def verify_semantic_contract_coverage(
    contract: Any,
    logic_form: Any,
    execution_result: Any,
) -> dict[str, Any]:
    """Check whether the executed plan covers the canonical semantic contract."""

    canonical = ensure_canonical_semantic_contract(contract)
    if canonical is None:
        return {"passed": True, "status": "legacy_unverified", "issues": [], "notes": ["No canonical semantic contract attached."]}
    params = _dict_field(logic_form, "parameters")
    referent_dimension = _normalize_name(str(params.get("referent_dimension") or ""))
    trace = _execution_trace_payload(execution_result)
    issues: list[dict[str, Any]] = []
    notes: list[str] = [f"Canonical semantic contract checked as {canonical.capability_family}."]
    if not trace:
        issue = _coverage_issue(
            "missing_execution_trace",
            "Execution result has no execution_trace; canonical semantic coverage cannot be proven.",
            correction_action="legacy_unverified",
        )
        return {
            "passed": False,
            "status": "failed",
            "issues": [issue],
            "notes": notes,
            "correction_action": _correction_action_for_issue(issue),
        }
    trace_source = str(trace.get("trace_source") or "").strip().lower()
    if trace_source != "actual_executor" or trace.get("trace_is_actual") is False:
        issues.append(
            _coverage_issue(
                "trace_not_actual",
                f"Execution trace source is {trace.get('trace_source') or 'missing'}, not actual_executor.",
                correction_action="legacy_unverified",
            )
        )
    trace_status = str(trace.get("trace_status") or "").strip().lower()
    if trace_status == "unsupported":
        issues.append(
            _coverage_issue(
                "unsupported_execution_trace",
                "Executor marked semantic trace as unsupported.",
                correction_action="legacy_unverified",
            )
        )
    if canonical.needs_clarification:
        issues.append(_coverage_issue("contract_needs_clarification", "Canonical contract needs clarification.", severity="needs_clarification", correction_action="ask_clarification"))
    for metric in canonical.metrics:
        if metric.semantic_type in {"row_count", "record_count"} and not metric.resolved_columns:
            notes.append(f"Metric {metric.display_name or metric.semantic_type} is row-count-like and needs no source column.")
            continue
        metric_issue = _trace_metric_issue(metric, trace)
        if metric_issue is not None:
            issues.append(metric_issue)
    for dimension in canonical.dimensions:
        if _scalar_count_operation(canonical, trace):
            continue
        if canonical.capability_family == "drilldown_followup" and referent_dimension and _normalize_name(str(dimension.resolved_column or "")) == referent_dimension:
            notes.append(f"Referent dimension {dimension.resolved_column} is carried as filter scope for drilldown, not as an output grouping.")
            continue
        if dimension.resolved_column and not _trace_dimension_covered(dimension, trace):
            issues.append(_coverage_issue("missing_groupby", f"Execution trace does not group by {dimension.resolved_column}.", correction_action="add_missing_groupby_and_rerun", dimension=dimension.to_dict()))
    for item in canonical.filters:
        if item.resolved_column and not _trace_filter_covered(item, trace):
            issues.append(_coverage_issue("missing_filter", f"Execution trace does not apply filter {item.resolved_column} {item.operator} {item.values}.", correction_action="add_missing_filter_and_rerun", filter=item.to_dict()))
    issues.extend(_trace_filter_result_sanity_issues(trace, execution_result))
    if canonical.comparison is not None and canonical.comparison.type:
        if not _trace_comparison_covered(canonical.comparison, trace):
            issues.append(_coverage_issue("wrong_comparison_type", f"Execution trace comparison type {trace.get('comparison_type')} does not match contract {canonical.comparison.type}.", correction_action="fix_comparison_type_and_rerun", comparison=canonical.comparison.to_dict()))
    if canonical.ranking is not None and canonical.task_type == "ranking":
        ranking_issue = _trace_ranking_issue(canonical.ranking, trace)
        if ranking_issue is not None:
            issues.append(ranking_issue)
    if canonical.time is not None:
        time_issue = _trace_time_issue(canonical.time, trace)
        if time_issue is not None:
            issues.append(time_issue)
    row_columns = _execution_columns(execution_result)
    for dimension in canonical.dimensions:
        if _scalar_count_operation(canonical, trace):
            continue
        if canonical.capability_family == "drilldown_followup" and referent_dimension and _normalize_name(str(dimension.resolved_column or "")) == referent_dimension:
            continue
        if dimension.resolved_column and row_columns and not _result_dimension_covered(dimension, row_columns, trace):
            if canonical.task_type in {"ranking", "trend", "aggregation"} and len(row_columns) > 1:
                issues.append(_coverage_issue("dimension_not_in_result", f"Execution result does not expose requested dimension {dimension.resolved_column}.", correction_action="add_missing_groupby_and_rerun"))
    warning_only = False
    if trace_status == "partial" and not any(issue.get("severity") in {"error", "needs_clarification"} for issue in issues):
        issues.append(_coverage_issue("partial_execution_trace", "Executor marked semantic trace as partial; covered fields match but coverage is not full.", severity="warning", correction_action="legacy_unverified"))
        warning_only = True
    expected_trace = _expected_trace_payload(execution_result)
    expected_issue = _expected_actual_trace_warning(expected_trace, trace)
    if expected_issue is not None and not any(issue.get("severity") in {"error", "needs_clarification"} for issue in issues):
        issues.append(expected_issue)
        warning_only = True
    passed = not any(issue.get("severity") in {"error", "needs_clarification"} for issue in issues)
    status = "passed" if passed and not warning_only else "warning" if passed else "failed"
    action_issue = next((issue for issue in issues if issue.get("severity") in {"error", "needs_clarification"}), issues[0] if issues else None)
    return {
        "passed": passed,
        "status": status,
        "issues": issues,
        "notes": notes,
        "correction_action": _correction_action_for_issue(action_issue),
        "execution_trace": trace,
    }


def _spec_metric_columns(metric_specs: list[dict[str, Any]], params: Mapping[str, Any]) -> list[str]:
    columns: list[str] = []
    for metric in metric_specs:
        for column in metric.get("resolved_columns") or []:
            text = str(column or "").strip()
            if text and text not in columns:
                columns.append(text)
    for key in ("metric", "field"):
        text = str(params.get(key) or "").strip()
        if text and text not in {"__row_count__", "row_count"} and text not in columns:
            columns.append(text)
    return columns


def _spec_aggregation(metric_specs: list[dict[str, Any]], params: Mapping[str, Any]) -> str | None:
    for metric in metric_specs:
        aggregation = str(metric.get("aggregation") or "").strip()
        if aggregation:
            return aggregation
    aggregation = str(params.get("aggregation") or "").strip()
    return aggregation or None


def _spec_formula(metric_specs: list[dict[str, Any]], params: Mapping[str, Any]) -> Any:
    for metric in metric_specs:
        formula = metric.get("formula")
        if formula not in (None, "", {}, []):
            return formula
    derived_metric = params.get("derived_metric")
    if isinstance(derived_metric, Mapping):
        return derived_metric.get("formula") or derived_metric
    return None


def _execution_trace_payload(execution_result: Any) -> dict[str, Any]:
    trace = _field(execution_result, "execution_trace")
    if isinstance(trace, Mapping) and trace:
        return dict(trace)
    debug = _field(execution_result, "debug")
    if isinstance(debug, Mapping):
        debug_trace = debug.get("execution_trace")
        if isinstance(debug_trace, Mapping) and debug_trace:
            return dict(debug_trace)
    if isinstance(execution_result, Mapping):
        payload_trace = execution_result.get("execution_trace")
        if isinstance(payload_trace, Mapping) and payload_trace:
            return dict(payload_trace)
    return {}


def _expected_trace_payload(execution_result: Any) -> dict[str, Any]:
    trace = _field(execution_result, "expected_trace")
    if isinstance(trace, Mapping) and trace:
        return dict(trace)
    debug = _field(execution_result, "debug")
    if isinstance(debug, Mapping):
        debug_trace = debug.get("expected_trace")
        if isinstance(debug_trace, Mapping) and debug_trace:
            return dict(debug_trace)
    if isinstance(execution_result, Mapping):
        payload_trace = execution_result.get("expected_trace")
        if isinstance(payload_trace, Mapping) and payload_trace:
            return dict(payload_trace)
    return {}


def _coverage_issue(
    issue_type: str,
    message: str,
    *,
    severity: str = "error",
    correction_action: str = "legacy_unverified",
    **payload: Any,
) -> dict[str, Any]:
    return {
        "type": issue_type,
        "code": issue_type,
        "severity": severity,
        "message": message,
        "correction_action": correction_action,
        **payload,
    }


def _scalar_count_operation(canonical: CanonicalSemanticContract, trace: Mapping[str, Any]) -> bool:
    operation = str(canonical.physical_operation or trace.get("operation") or "").strip()
    return operation in {"distinct_count", "row_count"}


def _correction_action_for_issue(issue: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not issue:
        return None
    action = str(issue.get("correction_action") or "legacy_unverified")
    return {
        "action": action,
        "issue_type": str(issue.get("type") or issue.get("code") or ""),
        "reason": str(issue.get("message") or ""),
    }


def _trace_metric_issue(metric: ResolvedMetric, trace: Mapping[str, Any]) -> dict[str, Any] | None:
    trace_columns = {_normalize_name(item) for item in _trace_metric_columns(trace)}
    expected_columns = {_normalize_name(item) for item in metric.resolved_columns if item}
    aggregation = _normalize_aggregation(trace.get("aggregation"))
    semantic_type = str(metric.semantic_type or "")
    if semantic_type == "entity_count" and expected_columns:
        if not expected_columns.issubset(trace_columns):
            return _coverage_issue("wrong_metric_formula", f"Execution trace does not count distinct entity column(s) {metric.resolved_columns}.", correction_action="fix_metric_formula_and_rerun", metric=metric.to_dict())
        if aggregation not in {"nunique", "distinct_count", "count_distinct"}:
            return _coverage_issue("wrong_metric_formula", f"Contract expects count_distinct but trace aggregation is {trace.get('aggregation')}.", correction_action="fix_metric_formula_and_rerun", metric=metric.to_dict())
        return None
    if metric.formula not in (None, "", {}, []):
        if trace.get("formula") in (None, "", {}, []):
            return _coverage_issue("wrong_metric_formula", f"Contract expects derived metric formula for {metric.display_name}, but trace has no formula.", correction_action="fix_metric_formula_and_rerun", metric=metric.to_dict())
        return None
    if expected_columns and not expected_columns.issubset(trace_columns):
        return _coverage_issue("missing_metric", f"Execution trace metric columns {list(trace_columns)} do not cover {metric.resolved_columns}.", correction_action="fix_metric_formula_and_rerun", metric=metric.to_dict())
    expected_aggregation = _normalize_aggregation(metric.aggregation)
    if expected_aggregation and aggregation and expected_aggregation != aggregation:
        return _coverage_issue("wrong_metric_formula", f"Contract aggregation {metric.aggregation} does not match trace aggregation {trace.get('aggregation')}.", correction_action="fix_metric_formula_and_rerun", metric=metric.to_dict())
    return None


def _trace_metric_columns(trace: Mapping[str, Any]) -> list[str]:
    columns = trace.get("metric_columns")
    if isinstance(columns, list):
        return [str(item) for item in columns if str(item)]
    return []


def _trace_dimension_covered(dimension: ResolvedDimension, trace: Mapping[str, Any]) -> bool:
    expected = _normalize_name(str(dimension.resolved_column or dimension.display_name or ""))
    groupby = {_normalize_name(str(item)) for item in trace.get("groupby_columns") or [] if str(item)}
    if expected and expected in groupby:
        return True
    return _month_bucket_covers_dimension(expected, groupby, trace)


def _result_dimension_covered(dimension: ResolvedDimension, row_columns: list[str], trace: Mapping[str, Any]) -> bool:
    expected = _normalize_name(str(dimension.resolved_column or dimension.display_name or ""))
    result_columns = {_normalize_name(str(item)) for item in row_columns if str(item)}
    if expected and expected in result_columns:
        return True
    return _month_bucket_covers_dimension(expected, result_columns, trace)


def _month_bucket_covers_dimension(expected: str, available_columns: set[str], trace: Mapping[str, Any]) -> bool:
    time_grain = str(trace.get("time_grain") or "").strip().lower()
    time_column = _normalize_name(str(trace.get("time_column") or ""))
    return bool(time_grain == "month" and expected and expected == time_column and "month" in available_columns)


def _trace_filter_covered(item: ResolvedFilter, trace: Mapping[str, Any]) -> bool:
    expected_column = _normalize_name(str(item.resolved_column or ""))
    expected_values = {str(value) for value in item.values}
    for applied in trace.get("filters_applied") or []:
        if not isinstance(applied, Mapping):
            continue
        if _normalize_name(str(applied.get("column") or "")) != expected_column:
            continue
        values = applied.get("values")
        actual_values = values if isinstance(values, (list, tuple, set)) else [values]
        if expected_values.issubset({str(value) for value in actual_values}):
            return True
    return False


def _trace_filter_result_sanity_issues(trace: Mapping[str, Any], execution_result: Any) -> list[dict[str, Any]]:
    rows = _execution_rows(execution_result)
    if not rows:
        return []
    issues: list[dict[str, Any]] = []
    for applied in trace.get("filters_applied") or []:
        if not isinstance(applied, Mapping):
            continue
        column = str(applied.get("column") or "").strip()
        if not column:
            continue
        operator = str(applied.get("operator") or "eq").strip().lower()
        if operator not in {"eq", "=", "in"}:
            continue
        values = applied.get("values")
        expected_values = {str(value) for value in (values if isinstance(values, (list, tuple, set)) else [values])}
        if not expected_values:
            continue
        mismatches = [
            row.get(column)
            for row in rows
            if isinstance(row, Mapping) and column in row and str(row.get(column)) not in expected_values
        ]
        if mismatches:
            issues.append(
                _coverage_issue(
                    "contract_execution_mismatch",
                    f"Execution trace says filter {column}={sorted(expected_values)} was applied, but result rows still contain other values.",
                    correction_action="add_missing_filter_and_rerun",
                    filter={"column": column, "operator": operator, "values": sorted(expected_values)},
                )
            )
    return issues


def _expected_actual_trace_warning(expected_trace: Mapping[str, Any], actual_trace: Mapping[str, Any]) -> dict[str, Any] | None:
    if not expected_trace or not actual_trace:
        return None
    checks = [
        ("metric_columns", tuple(str(item) for item in expected_trace.get("metric_columns") or []), tuple(str(item) for item in actual_trace.get("metric_columns") or [])),
        ("groupby_columns", tuple(str(item) for item in expected_trace.get("groupby_columns") or []), tuple(str(item) for item in actual_trace.get("groupby_columns") or [])),
        ("comparison_type", str(expected_trace.get("comparison_type") or ""), str(actual_trace.get("comparison_type") or "")),
        ("time_column", str(expected_trace.get("time_column") or ""), str(actual_trace.get("time_column") or "")),
        ("time_grain", str(expected_trace.get("time_grain") or ""), str(actual_trace.get("time_grain") or "")),
    ]
    mismatched = [field for field, expected, actual in checks if expected and expected != actual]
    if not mismatched:
        return None
    return _coverage_issue(
        "contract_execution_mismatch",
        "Expected trace and actual execution trace differ for: " + ", ".join(mismatched),
        severity="warning",
        correction_action="legacy_unverified",
        mismatched_fields=mismatched,
    )


def _trace_comparison_covered(comparison: ResolvedComparison, trace: Mapping[str, Any]) -> bool:
    expected = _normalize_comparison_type(comparison.type)
    actual = _normalize_comparison_type(str(trace.get("comparison_type") or ""))
    if not expected:
        return True
    return actual == expected


def _trace_ranking_issue(ranking: ResolvedRanking, trace: Mapping[str, Any]) -> dict[str, Any] | None:
    payload = trace.get("ranking") if isinstance(trace.get("ranking"), Mapping) else {}
    if ranking.order and str(payload.get("order") or "").lower() != ranking.order.lower():
        return _coverage_issue("ranking_mismatch", f"Ranking order {payload.get('order')} does not match contract {ranking.order}.", correction_action="fix_ranking_and_rerun", ranking=ranking.to_dict())
    if ranking.limit is not None:
        try:
            actual_limit = int(payload.get("limit"))
        except (TypeError, ValueError):
            actual_limit = None
        if actual_limit != int(ranking.limit):
            return _coverage_issue("ranking_mismatch", f"Ranking limit {actual_limit} does not match contract {ranking.limit}.", correction_action="fix_ranking_and_rerun", ranking=ranking.to_dict())
    return None


def _trace_time_issue(time_spec: ResolvedTimeSpec, trace: Mapping[str, Any]) -> dict[str, Any] | None:
    if time_spec.time_column and _normalize_name(str(trace.get("time_column") or "")) != _normalize_name(str(time_spec.time_column)):
        return _coverage_issue("missing_time_column", f"Trace time column {trace.get('time_column')} does not match contract {time_spec.time_column}.", correction_action="fix_time_grain_and_rerun", time=time_spec.to_dict())
    if time_spec.grain and str(trace.get("time_grain") or "").lower() != str(time_spec.grain).lower():
        return _coverage_issue("time_grain_mismatch", f"Trace time grain {trace.get('time_grain')} does not match contract {time_spec.grain}.", correction_action="fix_time_grain_and_rerun", time=time_spec.to_dict())
    return None


def _normalize_aggregation(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"nunique", "distinct", "distinct_count", "count_distinct"}:
        return "count_distinct"
    if text in {"row_count", "count_rows"}:
        return "count"
    return text


def _normalize_comparison_type(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"comparison", "pairwise_gap", "category_pair_gap", "category_comparison", "pairwise_category_gap"}:
        return "category_comparison"
    if text in {"time_adjacent_diff", "lag", "adjacent_diff", "time_comparison"}:
        return "time_adjacent_diff"
    return text


def _metric_from_payload(payload: Mapping[str, Any]) -> ResolvedMetric:
    return ResolvedMetric(
        metric_id=payload.get("metric_id"),
        display_name=str(payload.get("display_name") or ""),
        source_text=payload.get("source_text"),
        semantic_type=str(payload.get("semantic_type") or "metric"),
        aggregation=payload.get("aggregation"),
        formula=payload.get("formula"),
        resolved_columns=[str(item) for item in payload.get("resolved_columns") or []],
        depends_on=[str(item) for item in payload.get("depends_on") or []],
        confidence=float(payload.get("confidence") or 0.0),
        evidence=[str(item) for item in payload.get("evidence") or []],
    )


def _dimension_from_payload(payload: Mapping[str, Any]) -> ResolvedDimension:
    return ResolvedDimension(
        dimension_id=payload.get("dimension_id"),
        display_name=str(payload.get("display_name") or ""),
        source_text=payload.get("source_text"),
        semantic_type=str(payload.get("semantic_type") or "dimension"),
        resolved_column=payload.get("resolved_column"),
        confidence=float(payload.get("confidence") or 0.0),
        evidence=[str(item) for item in payload.get("evidence") or []],
    )


def _filter_from_payload(payload: Mapping[str, Any]) -> ResolvedFilter:
    return ResolvedFilter(
        dimension_id=payload.get("dimension_id"),
        display_name=str(payload.get("display_name") or ""),
        source_text=payload.get("source_text"),
        resolved_column=payload.get("resolved_column"),
        operator=str(payload.get("operator") or "eq"),
        values=list(payload.get("values") or []),
        confidence=float(payload.get("confidence") or 0.0),
        evidence=[str(item) for item in payload.get("evidence") or []],
    )


def _comparison_from_payload(payload: Any) -> ResolvedComparison | None:
    if not isinstance(payload, Mapping) or not payload:
        return None
    return ResolvedComparison(
        type=str(payload.get("type") or ""),
        metric_ref=payload.get("metric_ref"),
        dimension_ref=payload.get("dimension_ref"),
        left=dict(payload.get("left") or {}) if isinstance(payload.get("left"), Mapping) else None,
        right=dict(payload.get("right") or {}) if isinstance(payload.get("right"), Mapping) else None,
        operator=payload.get("operator"),
        confidence=float(payload.get("confidence") or 0.0),
        evidence=[str(item) for item in payload.get("evidence") or []],
    )


def _time_from_payload(payload: Any) -> ResolvedTimeSpec | None:
    if not isinstance(payload, Mapping) or not payload:
        return None
    return ResolvedTimeSpec(
        time_column=payload.get("time_column"),
        grain=payload.get("grain"),
        range=dict(payload.get("range") or {}) if isinstance(payload.get("range"), Mapping) else None,
        confidence=float(payload.get("confidence") or 0.0),
        evidence=[str(item) for item in payload.get("evidence") or []],
    )


def _ranking_from_payload(payload: Any) -> ResolvedRanking | None:
    if not isinstance(payload, Mapping) or not payload:
        return None
    limit = payload.get("limit")
    return ResolvedRanking(
        order=str(payload.get("order") or "desc"),
        limit=int(limit) if isinstance(limit, int) or (isinstance(limit, str) and limit.isdigit()) else None,
        metric_ref=payload.get("metric_ref"),
        dimension_ref=payload.get("dimension_ref"),
        confidence=float(payload.get("confidence") or 0.0),
        evidence=[str(item) for item in payload.get("evidence") or []],
    )


def _to_plain_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _table_profile_from_contract(table: Mapping[str, Any]) -> dict[str, Any]:
    columns = []
    for column in table.get("columns") or []:
        if not isinstance(column, Mapping):
            continue
        columns.append(
            {
                "name": str(column.get("name") or ""),
                "inferred_type": str(column.get("inferred_type") or "unknown"),
                "missing_rate": column.get("missing_rate"),
                "unique_count": column.get("unique_count"),
                "sample_values": list(column.get("sample_values") or [])[:10],
                "semantic_hints": list(column.get("semantic_hints") or []),
                "semantic_type": _column_semantic_type(str(column.get("name") or ""), str(column.get("inferred_type") or ""), list(column.get("semantic_hints") or [])),
            }
        )
    return {
        "table_name": str(table.get("table_name") or table.get("name") or ""),
        "row_count": int(table.get("row_count") or 0),
        "column_count": int(table.get("column_count") or len(columns)),
        "columns": columns,
        "table_role": str(table.get("table_role") or "data_table"),
    }


def _table_profile_from_dataframe(table_name: str, df: Any) -> dict[str, Any]:
    columns = []
    row_count = _safe_len(df)
    raw_columns = getattr(df, "columns", [])
    for name in list(raw_columns):
        series = None
        try:
            series = df[name]
        except Exception:  # noqa: BLE001 - profile must be best effort.
            series = None
        inferred_type = _infer_series_type(series)
        sample_values = _series_values(series, limit=10)
        low_cardinality_values = _series_values(series, limit=80, unique=True)
        unique_count = len(low_cardinality_values)
        hints = _semantic_hints(str(name), inferred_type, unique_count=unique_count, row_count=row_count)
        columns.append(
            {
                "name": str(name),
                "inferred_type": inferred_type,
                "unique_count": unique_count,
                "sample_values": sample_values,
                "low_cardinality_values": low_cardinality_values if unique_count <= 80 else [],
                "semantic_hints": hints,
                "semantic_type": _column_semantic_type(str(name), inferred_type, hints),
            }
        )
    return {"table_name": table_name, "row_count": row_count, "column_count": len(columns), "columns": columns, "table_role": "data_table"}


def _safe_len(value: Any) -> int:
    try:
        return int(len(value))
    except Exception:  # noqa: BLE001
        return 0


def _infer_series_type(series: Any) -> str:
    if series is None:
        return "unknown"
    dtype = str(getattr(series, "dtype", "")).lower()
    if "datetime" in dtype or "date" in dtype:
        return "datetime"
    if "bool" in dtype:
        return "boolean"
    if any(token in dtype for token in ("int", "float", "double", "decimal", "number")):
        return "number"
    values = _series_values(series, limit=25)
    if values and sum(1 for item in values if _looks_like_date_value(item)) >= max(1, int(len(values) * 0.7)):
        return "datetime"
    return "category" if len(set(map(str, values))) <= max(20, int(max(1, len(values)) * 0.5)) else "text"


def _series_values(series: Any, *, limit: int, unique: bool = False) -> list[Any]:
    if series is None:
        return []
    try:
        source = series.dropna()
    except Exception:  # noqa: BLE001
        source = series
    try:
        values = source.unique().tolist() if unique and hasattr(source, "unique") else source.head(limit).tolist()
    except Exception:  # noqa: BLE001
        try:
            values = list(source)[:limit]
        except Exception:  # noqa: BLE001
            values = []
    output: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        key = str(value)
        if unique and key in seen:
            continue
        seen.add(key)
        output.append(value)
        if len(output) >= limit:
            break
    return output


def _looks_like_date_value(value: Any) -> bool:
    text = str(value)
    return bool(re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", text))


def _semantic_hints(name: str, inferred_type: str, *, unique_count: int, row_count: int) -> list[str]:
    lowered = name.lower()
    normalized = _normalize_name(name)
    hints: list[str] = []
    if inferred_type == "datetime" or any(token in lowered for token in ("date", "time", "month", "year", "day")) or any(token in name for token in ("日期", "时间", "月份", "年月")):
        hints.append("time")
        hints.append("time_dimension")
    if inferred_type == "number" or any(token in lowered for token in ("amount", "sales", "revenue", "profit", "price", "cost", "qty", "quantity", "volume", "rate", "fee")) or any(token in name for token in ("金额", "销售", "收入", "营收", "利润", "数量", "价格", "费用", "费率", "率")):
        hints.append("metric")
    if any(token in lowered for token in ("amount", "sales", "revenue")) or any(token in name for token in ("金额", "销售额", "收入", "营收")):
        hints.append("amount_measure")
    if any(token in lowered for token in ("qty", "quantity", "volume")) or any(token in name for token in ("数量", "销量", "销售量", "件数")):
        hints.append("quantity_measure")
        hints.append("return_quantity_evidence")
    if any(token in lowered for token in ("unitprice", "unit_price", "unit price", "price")) or any(token in name for token in ("单价", "价格")):
        hints.append("unit_price_measure")
    if any(token in lowered for token in ("city", "region", "country", "province", "area", "district")) or any(token in name for token in ("城市", "地区", "区域", "省份", "国家")):
        hints.append("location")
        hints.append("geography_dimension")
    if any(token in lowered for token in ("description", "product_name", "item_name", "sku_name", "product_label")) or any(token in name for token in ("品名", "商品名称", "产品名称", "描述")):
        hints.append("product_label")
    if any(token in lowered for token in ("stockcode", "stock_code", "sku", "product_id", "item_id")) or any(token in name for token in ("商品编码", "产品编码", "物料编码")):
        hints.append("product_key")
    if any(token in lowered for token in ("customerid", "customer_id", "cust_id", "client_id", "user_id", "buyer_id")) or any(token in name for token in ("客户编号", "客户ID", "用户ID", "买家ID")):
        hints.append("customer_key")
    if any(token in lowered for token in ("invoice", "order_id", "orderid", "transaction_id", "transactionid", "receipt")) or any(token in name for token in ("订单号", "订单编号", "发票号", "交易号", "流水号", "单号")):
        hints.append("transaction_key")
        hints.append("invoice_or_order_key")
    if normalized.endswith("id") or "id" in re.split(r"[^a-z0-9]+", lowered) or any(token in name for token in ("编号", "代码", "ID")):
        hints.append("id")
    if inferred_type in {"category", "text"} and 0 < unique_count <= max(20, int(max(1, row_count) * 0.2)):
        hints.append("category")
    return sorted(set(hints))


def _column_semantic_type(name: str, inferred_type: str, hints: list[str]) -> str:
    for semantic_type in (
        "product_label",
        "product_key",
        "customer_key",
        "transaction_key",
        "invoice_or_order_key",
        "geography_dimension",
        "time_dimension",
        "quantity_measure",
        "unit_price_measure",
        "amount_measure",
    ):
        if semantic_type in hints:
            return semantic_type
    if "time" in hints:
        return "time"
    if "metric" in hints and inferred_type == "number":
        return "metric"
    if "id" in hints:
        return "entity_id"
    if "location" in hints:
        return "location"
    if "category" in hints:
        return "category"
    if inferred_type == "number":
        return "measure"
    return "dimension"


def _schema_candidates(tables: list[dict[str, Any]]) -> dict[str, list[str]]:
    candidates = {
        "metrics": [],
        "dimensions": [],
        "filters": [],
        "time": [],
        "entity_ids": [],
        "product_labels": [],
        "product_keys": [],
        "customer_keys": [],
        "transaction_keys": [],
        "geography": [],
        "quantity_measures": [],
        "unit_price_measures": [],
        "amount_measures": [],
    }
    for column in _iter_columns(tables):
        name = str(column.get("name") or "")
        semantic_type = str(column.get("semantic_type") or "")
        if semantic_type in {"metric", "measure", "quantity_measure", "unit_price_measure", "amount_measure"} and name not in candidates["metrics"]:
            candidates["metrics"].append(name)
        if semantic_type in {"dimension", "category", "location", "product_label", "product_key", "customer_key", "geography_dimension"} and name not in candidates["dimensions"]:
            candidates["dimensions"].append(name)
            candidates["filters"].append(name)
        if semantic_type in {"time", "time_dimension"} and name not in candidates["time"]:
            candidates["time"].append(name)
        if semantic_type in {"entity_id", "product_key", "customer_key", "transaction_key", "invoice_or_order_key"} and name not in candidates["entity_ids"]:
            candidates["entity_ids"].append(name)
        role_targets = {
            "product_label": "product_labels",
            "product_key": "product_keys",
            "customer_key": "customer_keys",
            "transaction_key": "transaction_keys",
            "invoice_or_order_key": "transaction_keys",
            "geography_dimension": "geography",
            "quantity_measure": "quantity_measures",
            "unit_price_measure": "unit_price_measures",
            "amount_measure": "amount_measures",
        }
        bucket = role_targets.get(semantic_type)
        if bucket and name not in candidates[bucket]:
            candidates[bucket].append(name)
    return candidates


def _column_index(tables: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for table in tables:
        table_name = str(table.get("table_name") or "")
        for column in table.get("columns") or []:
            if not isinstance(column, Mapping):
                continue
            key = _normalize_name(str(column.get("name") or ""))
            if key:
                index.setdefault(key, {"table": table_name, **dict(column)})
    return index


def _iter_columns(profile: Mapping[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    tables = profile if isinstance(profile, list) else profile.get("tables") if isinstance(profile, Mapping) else []
    columns: list[dict[str, Any]] = []
    for table in tables or []:
        if not isinstance(table, Mapping):
            continue
        for column in table.get("columns") or []:
            if isinstance(column, Mapping):
                columns.append(dict(column))
    return columns


def _semantic_candidate_payloads(**kwargs: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source, value in kwargs.items():
        if value is None:
            continue
        if source.endswith("_logic_form"):
            output.append(_candidate_from_logic_form(source.replace("_logic_form", ""), value))
        elif isinstance(value, Mapping):
            output.append({"source": source, "payload": _safe_candidate_payload(value)})
    return output


def _candidate_from_logic_form(source: str, logic: Any) -> dict[str, Any]:
    params = _dict_field(logic, "parameters")
    return {
        "source": source,
        "task_type": _field(logic, "task_type"),
        "operation": _field(logic, "operation"),
        "metric": _field(logic, "metric") or params.get("metric"),
        "dimension": _field(logic, "group_by") or params.get("dimension") or params.get("group_by"),
        "filters": _dict_field(logic, "filters"),
        "parameters": {key: params.get(key) for key in sorted(params) if key in _SAFE_CANDIDATE_PARAMETER_KEYS},
    }


_SAFE_CANDIDATE_PARAMETER_KEYS = {
    "aggregation",
    "candidate_filter",
    "comparison",
    "dimension",
    "entity_field",
    "field",
    "group_by",
    "limit",
    "metric",
    "metric_specs",
    "metrics",
    "requires_gap_comparison",
    "sort_order",
    "source_time_field",
    "table",
    "time_bucket",
    "time_column",
    "time_dimension",
}


def _safe_candidate_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    safe = {}
    for key in ("task_type", "operation", "intent_summary", "filters", "metrics", "dimensions", "confidence", "reasoning_summary"):
        if key in payload:
            safe[key] = payload[key]
    return safe


def _canonical_task_type(question: str, logic: Any, physical_operation: str) -> str:
    params = _dict_field(logic, "parameters")
    task_type = _first_text(_field(logic, "task_type"), params.get("task_type"))
    lowered = question.lower()
    if _asks_pairwise_comparison(question):
        return "comparison"
    if task_type == "trend" or params.get("time_bucket") or any(token in lowered for token in ("trend", "monthly", "by month")) or any(token in question for token in ("趋势", "按月", "月度", "每月")):
        return "trend"
    if task_type:
        return task_type
    if physical_operation in {"ranking", "filtered_metric_ranking", "top_count", "growth_ranking"}:
        return "ranking"
    return physical_operation or "unknown"


def _canonical_capability_family(question: str, logic: Any, task_type: str, physical_operation: str) -> str:
    params = _dict_field(logic, "parameters")
    metric_definition = _dict_field(logic, "metric_definition")
    output_contract = _dict_field(logic, "output_contract")
    explicit = _first_text(params.get("capability_family"), metric_definition.get("capability_family"), output_contract.get("capability_family"))
    if explicit:
        return explicit
    if task_type == "trend":
        return "time_series"
    if task_type == "comparison":
        return "pairwise_comparison" if _asks_pairwise_comparison(question) else "comparison"
    if task_type == "ranking":
        return "metric_ranking"
    if physical_operation in {"row_count", "distinct_count", "top_count"}:
        return "counting"
    return task_type or physical_operation or "unknown"


def _resolve_metrics(
    question: str,
    logic: Any,
    schema_profile: Mapping[str, Any],
    column_mapping: Mapping[str, Any],
) -> list[ResolvedMetric]:
    candidates = _metric_candidates(logic)
    entity_count = _entity_count_metric_from_question(question, schema_profile)
    if entity_count is not None:
        if not candidates or all(_candidate_is_row_count_like(candidate) for candidate in candidates):
            candidates = [entity_count] + [candidate for candidate in candidates if not _candidate_is_row_count_like(candidate)]
        else:
            candidates.append(entity_count)
    metrics: list[ResolvedMetric] = []
    for candidate in candidates:
        display_name = str(candidate.get("name") or candidate.get("field") or candidate.get("source_text") or "").strip()
        if not display_name:
            continue
        resolved = _resolve_column_reference(display_name, schema_profile, column_mapping, preferred_role="metric")
        depends_on = [str(item) for item in candidate.get("depends_on") or [] if item]
        formula = candidate.get("formula")
        if not depends_on and isinstance(formula, Mapping):
            depends_on.extend(str(item) for item in (formula.get("depends_on") or formula.get("columns") or []) if item)
        metric = ResolvedMetric(
            metric_id=_stable_id("metric", display_name),
            display_name=display_name,
            source_text=candidate.get("source_text") or display_name,
            semantic_type=str(candidate.get("semantic_type") or _metric_semantic_type(display_name, candidate)),
            aggregation=candidate.get("aggregation"),
            formula=formula,
            resolved_columns=resolved,
            depends_on=depends_on,
            confidence=0.92 if resolved or display_name in {"__row_count__", "row_count"} else 0.65,
            evidence=[str(item) for item in candidate.get("evidence") or []] + (["schema_column_match"] if resolved else []),
        )
        if not any(_same_metric(metric, existing) for existing in metrics):
            metrics.append(metric)
    return metrics


def _candidate_is_row_count_like(candidate: Mapping[str, Any]) -> bool:
    display_name = str(candidate.get("name") or candidate.get("field") or candidate.get("source_text") or "")
    return _metric_semantic_type(display_name, candidate) == "row_count"


def _metric_candidates(logic: Any) -> list[dict[str, Any]]:
    params = _dict_field(logic, "parameters")
    candidates: list[dict[str, Any]] = []
    aggregation = _first_text(params.get("aggregation"))
    for value, source in (
        (_field(logic, "metric"), "logic_form.metric"),
        (params.get("metric"), "parameters.metric"),
        (params.get("ranking_metric"), "parameters.ranking_metric"),
        (params.get("share_metric"), "parameters.share_metric"),
    ):
        text = _first_text(value)
        if text:
            candidates.append({"name": text, "field": text, "aggregation": aggregation, "evidence": [source]})
    metrics = params.get("metrics")
    if isinstance(metrics, (list, tuple)):
        for metric in metrics:
            text = _first_text(metric)
            if text:
                candidates.append({"name": text, "field": text, "aggregation": aggregation, "evidence": ["parameters.metrics"]})
    metric_specs = params.get("metric_specs")
    if isinstance(metric_specs, (list, tuple)):
        for spec in metric_specs:
            if not isinstance(spec, Mapping):
                continue
            name = _first_text(spec.get("name"), spec.get("field"))
            field_name = _first_text(spec.get("field"), name)
            if name:
                candidates.append(
                    {
                        "name": name,
                        "field": field_name,
                        "aggregation": _first_text(spec.get("aggregation"), aggregation),
                        "formula": spec.get("formula"),
                        "evidence": ["parameters.metric_specs"],
                    }
                )
    derived = params.get("derived_metric")
    if isinstance(derived, Mapping):
        name = _first_text(derived.get("name"), derived.get("display_name"))
        if name:
            depends_on = [str(derived.get(key)) for key in ("numerator", "denominator") if derived.get(key)]
            candidates.append(
                {
                    "name": name,
                    "field": name,
                    "semantic_type": "derived_metric",
                    "aggregation": aggregation,
                    "formula": derived.get("formula") or dict(derived),
                    "depends_on": depends_on,
                    "evidence": ["parameters.derived_metric"],
                }
            )
    return _dedupe_candidate_dicts(candidates)


def _entity_count_metric_from_question(question: str, schema_profile: Mapping[str, Any]) -> dict[str, Any] | None:
    if not re.search(r"(?:数量|个数|数\b|count of|number of|how many)", question, re.I):
        return None
    normalized_question = _normalize_text(question)
    best: tuple[int, str] | None = None
    for column in _iter_columns(schema_profile):
        if str(column.get("semantic_type") or "") not in {
            "entity_id",
            "product_key",
            "customer_key",
            "transaction_key",
            "invoice_or_order_key",
        }:
            continue
        name = str(column.get("name") or "")
        score = _overlap_score(name, normalized_question)
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, name)
    if best is None:
        return None
    return {
        "name": f"distinct_{best[1]}",
        "field": best[1],
        "semantic_type": "entity_count",
        "aggregation": "nunique",
        "evidence": ["schema_entity_id_linked_to_count_question"],
    }


def _resolve_dimensions(
    question: str,
    logic: Any,
    schema_profile: Mapping[str, Any],
    column_mapping: Mapping[str, Any],
) -> list[ResolvedDimension]:
    params = _dict_field(logic, "parameters")
    candidates: list[tuple[str, str]] = []
    for value, source in (
        (_field(logic, "group_by"), "logic_form.group_by"),
        (params.get("dimension"), "parameters.dimension"),
        (params.get("series_dimension"), "parameters.series_dimension"),
        (params.get("group_by"), "parameters.group_by"),
        (params.get("entity"), "parameters.entity"),
        (params.get("entity_field"), "parameters.entity_field"),
        (params.get("field"), "parameters.field"),
    ):
        text = _first_text(value)
        if text and not _sentinel_metric(text):
            candidates.append((text, source))
    entity_grain = _dict_field(logic, "entity_grain")
    field_name = _first_text(entity_grain.get("field"), entity_grain.get("dimension"), entity_grain.get("group_by"))
    if field_name and field_name not in {"__table__", "__row__"}:
        candidates.append((field_name, "entity_grain"))
    dimensions: list[ResolvedDimension] = []
    for text, source in candidates:
        resolved = _resolve_column_reference(text, schema_profile, column_mapping, preferred_role="dimension")
        resolved_column = resolved[0] if resolved else text
        semantic_type = _semantic_type_for_column(resolved_column, schema_profile) or "dimension"
        dimension = ResolvedDimension(
            dimension_id=_stable_id("dimension", resolved_column),
            display_name=resolved_column,
            source_text=text,
            semantic_type=semantic_type,
            resolved_column=resolved_column,
            confidence=0.92 if resolved or resolved_column == text else 0.65,
            evidence=[source] + (["schema_column_match"] if resolved else []),
        )
        if not any(item.resolved_column == dimension.resolved_column for item in dimensions):
            dimensions.append(dimension)
    return dimensions


def _resolve_filters(
    question: str,
    logic: Any,
    schema_profile: Mapping[str, Any],
    column_mapping: Mapping[str, Any],
) -> list[ResolvedFilter]:
    filters: list[ResolvedFilter] = []
    for column, value in _dict_field(logic, "filters").items():
        if value in (None, "", []):
            continue
        if _is_semantic_noop_filter(column, value):
            continue
        operator = "in" if isinstance(value, (list, tuple, set)) else "eq"
        if isinstance(value, Mapping) and "operator" in value:
            operator = str(value.get("operator") or "eq")
            if "values" in value and isinstance(value.get("values"), (list, tuple, set)):
                values = list(value.get("values") or [])
            else:
                values = [value.get("value")]
        else:
            values = list(value) if isinstance(value, (list, tuple, set)) else [value]
        resolved = _resolve_column_reference(str(column), schema_profile, column_mapping, preferred_role="dimension")
        resolved_column = resolved[0] if resolved else str(column)
        filters.append(
            ResolvedFilter(
                dimension_id=_stable_id("filter", resolved_column),
                display_name=resolved_column,
                source_text=str(column),
                resolved_column=resolved_column,
                operator=operator if operator not in {"", "in"} else ("in" if len(values) > 1 else "eq"),
                values=values,
                confidence=0.95,
                evidence=["logic_form.filters"] + (["schema_column_match"] if resolved else []),
            )
        )
    for linked in _link_filter_values_from_question(question, schema_profile):
        if any(item.resolved_column == linked.resolved_column and set(map(str, item.values)) >= set(map(str, linked.values)) for item in filters):
            continue
        existing = next((item for item in filters if item.resolved_column == linked.resolved_column and item.evidence == ["question_value_link"]), None)
        if existing is not None:
            for value in linked.values:
                if str(value) not in {str(item) for item in existing.values}:
                    existing.values.append(value)
            existing.operator = "in" if len(existing.values) > 1 else "eq"
        else:
            filters.append(linked)
    return filters


def _is_semantic_noop_filter(column: Any, value: Any) -> bool:
    column_text = str(column or "").strip().lower()
    if column_text == "conditions" and isinstance(value, list):
        return True
    if column_text == "type" and str(value or "").strip().lower() in {"none", "null", "not_required"}:
        return True
    return False


def _link_filter_values_from_question(question: str, schema_profile: Mapping[str, Any]) -> list[ResolvedFilter]:
    normalized_question = _normalize_text(question)
    linked: list[ResolvedFilter] = []
    for column in _iter_columns(schema_profile):
        values = column.get("low_cardinality_values") or column.get("sample_values") or []
        column_name = str(column.get("name") or "")
        semantic_type = str(column.get("semantic_type") or "")
        if semantic_type in {"metric", "measure", "time"}:
            continue
        for value in values:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                continue
            text = str(value).strip()
            if len(text) < 2:
                continue
            normalized_value = _normalize_text(text)
            if _question_mentions_filter_value(question, normalized_question, text, normalized_value):
                linked.append(
                    ResolvedFilter(
                        dimension_id=_stable_id("filter", column_name),
                        display_name=column_name,
                        source_text=text,
                        resolved_column=column_name,
                        operator="eq",
                        values=[value],
                        confidence=0.9,
                        evidence=["question_value_link"],
                    )
                )
    return linked


def _question_mentions_filter_value(question: str, normalized_question: str, raw_value: str, normalized_value: str) -> bool:
    if not normalized_value:
        return False
    if re.fullmatch(r"[A-Za-z0-9]{1,2}", raw_value):
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(raw_value)}(?![A-Za-z0-9_])"
        return re.search(pattern, question, flags=re.I) is not None
    return normalized_value in normalized_question


def _resolve_comparison(
    question: str,
    metrics: list[ResolvedMetric],
    dimensions: list[ResolvedDimension],
    filters: list[ResolvedFilter],
    logic: Any,
) -> ResolvedComparison | None:
    params = _dict_field(logic, "parameters")
    if isinstance(params.get("comparison"), Mapping):
        payload = params["comparison"]
        return ResolvedComparison(
            type=str(payload.get("type") or "comparison"),
            metric_ref=_metric_ref(metrics),
            dimension_ref=str(payload.get("dimension") or _dimension_ref(dimensions) or ""),
            left=dict(payload.get("left") or {}) if isinstance(payload.get("left"), Mapping) else None,
            right=dict(payload.get("right") or {}) if isinstance(payload.get("right"), Mapping) else None,
            operator=payload.get("operator"),
            confidence=0.9,
            evidence=["parameters.comparison"],
        )
    if not _asks_pairwise_comparison(question):
        return None
    for item in filters:
        if len(item.values) >= 2 and item.resolved_column:
            return ResolvedComparison(
                type="pairwise_gap" if _asks_gap(question) else "category_pair_comparison",
                metric_ref=_metric_ref(metrics),
                dimension_ref=item.resolved_column,
                left={"column": item.resolved_column, "value": item.values[0]},
                right={"column": item.resolved_column, "value": item.values[1]},
                operator="difference" if _asks_gap(question) else "compare",
                confidence=0.9,
                evidence=["question_comparison_language", "linked_filter_values"],
            )
    return ResolvedComparison(
        type="comparison",
        metric_ref=_metric_ref(metrics),
        dimension_ref=_dimension_ref(dimensions),
        operator="difference" if _asks_gap(question) else "compare",
        confidence=0.55,
        evidence=["question_comparison_language"],
    )


def _resolve_time_spec(question: str, logic: Any, schema_profile: Mapping[str, Any]) -> ResolvedTimeSpec | None:
    params = _dict_field(logic, "parameters")
    time_column = _first_text(params.get("time_column"), params.get("source_time_field"), params.get("time_dimension"))
    grain = _first_text(params.get("time_bucket"), params.get("time_grain"))
    if not grain and any(token in question.lower() for token in ("monthly", "by month")) or any(token in question for token in ("按月", "每月", "月度")):
        grain = "month"
    if not time_column:
        time_candidates = (schema_profile.get("candidates") or {}).get("time") if isinstance(schema_profile, Mapping) else []
        time_column = str(time_candidates[0]) if time_candidates else None
    if not time_column and not grain:
        return None
    return ResolvedTimeSpec(
        time_column=time_column,
        grain=grain,
        range={key: value for key, value in params.items() if key in {"current_period", "previous_period", "month_range", "year", "month"} and value is not None} or None,
        confidence=0.9 if time_column or grain else 0.0,
        evidence=["parameters.time"] if time_column or grain else [],
    )


def _resolve_ranking(
    question: str,
    metrics: list[ResolvedMetric],
    dimensions: list[ResolvedDimension],
    logic: Any,
    task_type: str,
) -> ResolvedRanking | None:
    params = _dict_field(logic, "parameters")
    ranking_signal = task_type == "ranking" or _asks_ranking(question)
    if not ranking_signal:
        return None
    limit = _positive_int(params.get("limit") or params.get("top_n") or params.get("k")) or _limit_from_question(question)
    order = _first_text(params.get("sort_order")) or ("asc" if _asks_lowest(question) else "desc")
    return ResolvedRanking(
        order=order,
        limit=limit,
        metric_ref=_metric_ref(metrics),
        dimension_ref=_dimension_ref(dimensions),
        confidence=0.88,
        evidence=["task_type_or_question_ranking_signal"],
    )


def _validate_contract(
    *,
    task_type: str,
    capability_family: str,
    metrics: list[ResolvedMetric],
    dimensions: list[ResolvedDimension],
    filters: list[ResolvedFilter],
    comparison: ResolvedComparison | None,
    ranking: ResolvedRanking | None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if task_type in {"ranking", "trend"} and not dimensions:
        issues.append({"code": "semantic_dimension_missing", "severity": "warning", "message": f"{task_type} usually needs a dimension."})
    if task_type in {"ranking", "aggregation", "trend", "comparison"} and not metrics:
        issues.append({"code": "semantic_metric_missing", "severity": "warning", "message": f"{task_type} has no resolved metric."})
    if comparison is not None and comparison.type in {"pairwise_gap", "category_pair_gap"} and not comparison.left:
        issues.append({"code": "comparison_sides_missing", "severity": "needs_clarification", "message": "Pairwise comparison lacks two resolved sides."})
    if ranking is not None and not ranking.dimension_ref:
        issues.append({"code": "ranking_dimension_missing", "severity": "warning", "message": "Ranking lacks a resolved dimension."})
    if capability_family == "unknown":
        issues.append({"code": "capability_family_unknown", "severity": "warning"})
    if len(filters) > 1:
        duplicate_columns = [column for column in {item.resolved_column for item in filters} if column and sum(1 for item in filters if item.resolved_column == column) > 1]
        for column in duplicate_columns:
            issues.append({"code": "filter_values_merged", "severity": "info", "column": column})
    return issues


def _confidence(
    candidates: list[dict[str, Any]],
    metrics: list[ResolvedMetric],
    dimensions: list[ResolvedDimension],
    filters: list[ResolvedFilter],
) -> dict[str, Any]:
    values = [item.confidence for item in metrics] + [item.confidence for item in dimensions] + [item.confidence for item in filters]
    return {
        "overall": round(sum(values) / len(values), 3) if values else 0.5,
        "candidate_count": len(candidates),
        "metric_count": len(metrics),
        "dimension_count": len(dimensions),
        "filter_count": len(filters),
    }


def _ambiguities(
    metrics: list[ResolvedMetric],
    dimensions: list[ResolvedDimension],
    filters: list[ResolvedFilter],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for label, items in (("metrics", metrics), ("dimensions", dimensions), ("filters", filters)):
        low = [item.to_dict() for item in items if item.confidence < 0.7]
        if low:
            output.append({"field": label, "candidates": low, "reason": "low_confidence_resolution"})
    return output


def _compact_dataset_semantics(schema_profile: Mapping[str, Any]) -> dict[str, Any] | None:
    if not schema_profile:
        return None
    tables = []
    for table in schema_profile.get("tables") or []:
        if not isinstance(table, Mapping):
            continue
        tables.append(
            {
                "table_name": table.get("table_name"),
                "row_count": table.get("row_count"),
                "column_count": table.get("column_count"),
            }
        )
    return {"profile_version": schema_profile.get("profile_version"), "tables": tables, "candidates": dict(schema_profile.get("candidates") or {})}


def _grain_from_logic(logic: Any) -> dict[str, Any] | None:
    grain = _dict_field(logic, "entity_grain")
    return grain or None


def _resolve_column_reference(
    value: str,
    schema_profile: Mapping[str, Any],
    column_mapping: Mapping[str, Any],
    *,
    preferred_role: str,
) -> list[str]:
    if not value:
        return []
    mapped = (column_mapping.get("mapped_columns") or {}).get(value) if isinstance(column_mapping.get("mapped_columns"), Mapping) else None
    if mapped:
        return [str(mapped)]
    columns = _iter_columns(schema_profile)
    exact = [str(column.get("name")) for column in columns if str(column.get("name")) == value]
    if exact:
        return exact[:1]
    normalized = _normalize_name(value)
    normalized_matches = [str(column.get("name")) for column in columns if _normalize_name(str(column.get("name") or "")) == normalized]
    if normalized_matches:
        return normalized_matches[:1]
    best: tuple[int, str] | None = None
    for column in columns:
        name = str(column.get("name") or "")
        score = _column_match_score(value, name)
        semantic_type = str(column.get("semantic_type") or "")
        if preferred_role == "metric" and semantic_type in {"metric", "measure"}:
            score += 10
        if preferred_role == "dimension" and semantic_type in {"dimension", "category", "location", "entity_id"}:
            score += 10
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, name)
    return [best[1]] if best is not None and best[0] >= 55 else []


def _semantic_type_for_column(column_name: str, schema_profile: Mapping[str, Any]) -> str | None:
    normalized = _normalize_name(column_name)
    for column in _iter_columns(schema_profile):
        if _normalize_name(str(column.get("name") or "")) == normalized:
            return str(column.get("semantic_type") or "")
    return None


def _metric_semantic_type(display_name: str, candidate: Mapping[str, Any]) -> str:
    if candidate.get("semantic_type"):
        return str(candidate["semantic_type"])
    if display_name in {"__row_count__", "row_count", "record_count", "transaction_count", "count"}:
        return "row_count"
    if candidate.get("formula"):
        return "derived_metric"
    aggregation = str(candidate.get("aggregation") or "")
    if aggregation in {"count", "nunique", "distinct_count"}:
        return "entity_count" if aggregation in {"nunique", "distinct_count"} else "row_count"
    return "measure"


def _same_metric(left: ResolvedMetric, right: ResolvedMetric) -> bool:
    if left.display_name and right.display_name and _normalize_name(left.display_name) == _normalize_name(right.display_name):
        return True
    return bool(set(left.resolved_columns) & set(right.resolved_columns))


def _dedupe_candidate_dicts(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = _normalize_name(str(candidate.get("name") or candidate.get("field") or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(candidate)
    return output


def _field(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _dict_field(value: Any, name: str) -> dict[str, Any]:
    raw = _field(value, name)
    return raw if isinstance(raw, dict) else {}


def _logic_payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
        elif not isinstance(value, (list, tuple, dict, set)):
            text = str(value).strip()
            if text:
                return text
    return ""


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _limit_from_question(question: str) -> int | None:
    match = re.search(r"(?:top|前)\s*(\d+)", question, re.I)
    return int(match.group(1)) if match else None


def _asks_ranking(question: str) -> bool:
    lowered = question.lower()
    return any(token in lowered for token in ("top", "highest", "lowest", "largest", "smallest", "rank")) or any(
        token in question for token in ("最高", "最低", "最大", "最小", "最多", "最少", "排名", "排行", "前")
    )


def _asks_lowest(question: str) -> bool:
    lowered = question.lower()
    return any(token in lowered for token in ("lowest", "smallest", "least", "bottom")) or any(token in question for token in ("最低", "最小", "最少", "后"))


def _asks_pairwise_comparison(question: str) -> bool:
    lowered = question.lower()
    explicit_english = any(token in lowered for token in (" vs ", " versus ", "compare", "comparison", "difference between"))
    english_pair_gap = " and " in lowered and any(token in lowered for token in ("gap", "difference", "delta", "compare"))
    explicit_chinese = any(token in question for token in ("差多少", "相差", "差距", "对比", "比较"))
    chinese_pair_gap = "和" in question and any(token in question for token in ("差", "相差", "差距", "对比", "比较"))
    return explicit_english or english_pair_gap or explicit_chinese or chinese_pair_gap


def _asks_gap(question: str) -> bool:
    lowered = question.lower()
    return any(token in lowered for token in ("gap", "difference", "delta")) or any(token in question for token in ("差多少", "相差", "差距"))


def _metric_ref(metrics: list[ResolvedMetric]) -> str | None:
    return metrics[0].metric_id if metrics else None


def _dimension_ref(dimensions: list[ResolvedDimension]) -> str | None:
    return dimensions[0].dimension_id if dimensions else None


def _sentinel_metric(value: str) -> bool:
    return value in {"__row_count__", "row_count", "record_count", "transaction_count", "count"}


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}:{_normalize_name(value) or 'unknown'}"


def _normalize_name(value: str) -> str:
    text = str(value or "").lower()
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return "".join(char for char in text if char.isalnum() or "\u4e00" <= char <= "\u9fff")


def _normalize_text(value: str) -> str:
    return _normalize_name(value)


def _column_match_score(requested: str, column_name: str) -> int:
    requested_norm = _normalize_name(requested)
    column_norm = _normalize_name(column_name)
    if not requested_norm or not column_norm:
        return 0
    if requested_norm == column_norm:
        return 120
    if requested_norm in column_norm or column_norm in requested_norm:
        return 80
    return _overlap_score(column_name, requested_norm)


def _overlap_score(column_name: str, normalized_question_or_requested: str) -> int:
    tokens = [token for token in re.split(r"[^A-Za-z0-9]+", column_name.lower()) if token and token not in {"id", "no", "num", "code"}]
    score = 0
    for token in tokens:
        if token and token in normalized_question_or_requested:
            score += 50
    chinese = "".join(char for char in column_name if "\u4e00" <= char <= "\u9fff")
    if chinese and chinese in normalized_question_or_requested:
        score += 80
    return score


def _metric_covered(metric: ResolvedMetric, logic: dict[str, Any], params: dict[str, Any]) -> bool:
    names = {
        _normalize_name(metric.display_name),
        *[_normalize_name(column) for column in metric.resolved_columns],
    }
    plan_values = {
        _normalize_name(str(logic.get("metric") or "")),
        _normalize_name(str(params.get("metric") or "")),
        *[_normalize_name(str(item)) for item in params.get("metrics") or [] if item],
    }
    metric_specs = params.get("metric_specs")
    if isinstance(metric_specs, list):
        for spec in metric_specs:
            if isinstance(spec, Mapping):
                plan_values.add(_normalize_name(str(spec.get("name") or "")))
                plan_values.add(_normalize_name(str(spec.get("field") or "")))
    derived_metric = params.get("derived_metric")
    if isinstance(derived_metric, Mapping):
        plan_values.add(_normalize_name(str(derived_metric.get("name") or "")))
    return bool((names - {""}) & (plan_values - {""}))


def _dimension_covered(dimension: ResolvedDimension, logic: dict[str, Any], params: dict[str, Any]) -> bool:
    expected = _normalize_name(dimension.resolved_column or dimension.display_name)
    values = {
        _normalize_name(str(logic.get("group_by") or "")),
        _normalize_name(str(params.get("dimension") or "")),
        _normalize_name(str(params.get("group_by") or "")),
        _normalize_name(str(params.get("entity") or "")),
        _normalize_name(str(params.get("entity_field") or "")),
    }
    entity_grain = logic.get("entity_grain")
    if isinstance(entity_grain, Mapping):
        values.add(_normalize_name(str(entity_grain.get("field") or "")))
    return bool(expected and expected in values)


def _filter_covered(item: ResolvedFilter, filters: dict[str, Any]) -> bool:
    if item.resolved_column not in filters:
        return False
    actual = filters.get(item.resolved_column)
    actual_values = actual if isinstance(actual, (list, tuple, set)) else [actual]
    return set(map(str, item.values)).issubset(set(map(str, actual_values)))


def _execution_columns(execution_result: Any) -> set[str]:
    if execution_result is None:
        return set()
    columns = getattr(execution_result, "columns", None)
    if isinstance(columns, list) and columns:
        return {str(item) for item in columns}
    rows = getattr(execution_result, "rows", None)
    if isinstance(rows, list) and rows and isinstance(rows[0], Mapping):
        return {str(item) for item in rows[0].keys()}
    if isinstance(execution_result, Mapping):
        raw_columns = execution_result.get("columns")
        if isinstance(raw_columns, list):
            return {str(item) for item in raw_columns}
    return set()


def _execution_rows(execution_result: Any) -> list[Mapping[str, Any]]:
    rows = getattr(execution_result, "rows", None)
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, Mapping)]
    value = getattr(execution_result, "value", None)
    if isinstance(value, list):
        return [row for row in value if isinstance(row, Mapping)]
    if isinstance(value, Mapping):
        candidate_table = value.get("candidate_table")
        if isinstance(candidate_table, list):
            return [row for row in candidate_table if isinstance(row, Mapping)]
        value_rows = value.get("rows")
        if isinstance(value_rows, list):
            return [row for row in value_rows if isinstance(row, Mapping)]
    if isinstance(execution_result, Mapping):
        raw_rows = execution_result.get("rows")
        if isinstance(raw_rows, list):
            return [row for row in raw_rows if isinstance(row, Mapping)]
    return []
