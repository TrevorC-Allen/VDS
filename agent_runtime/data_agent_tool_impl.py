"""Executable internal Data Agent tool implementations.

These functions wrap existing framework-neutral core modules. They do not
grant raw Python, raw SQL, shell, network, or arbitrary file access.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from data_agent_core.contracts.analysis_contracts import AnalysisPlan, LogicForm
from data_agent_core.contracts.dataset_contracts import DatasetProfile
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.data_quality import build_data_quality_report, report_to_dict
from data_agent_core.core.schema_profiler import profile_tables
from data_agent_core.executors import pandas_executor, sql_executor
from data_agent_core.output.chart_planner import build_chart_spec
from data_agent_core.output.insight_generator import generate_insight
from data_agent_core.verifier.result_comparator import compare_results
from data_agent_core.verifier.rule_checker import verify_execution


class DataAgentToolRuntime:
    """State holder used by controlled tools during one runtime session."""

    def __init__(
        self,
        *,
        dataset_contexts: dict[str, dict[str, Any]] | None = None,
        dataset_profiles: dict[str, DatasetProfile | dict[str, Any]] | None = None,
    ) -> None:
        self.dataset_contexts = dataset_contexts or {}
        self.dataset_profiles = dataset_profiles or {}

    def register_dataset(
        self,
        dataset_id: str,
        context: dict[str, Any],
        profile: DatasetProfile | dict[str, Any] | None = None,
    ) -> None:
        """Register one dataset context and optional profile for tools."""

        self.dataset_contexts[dataset_id] = context
        if profile is not None:
            self.dataset_profiles[dataset_id] = profile

    def tool_overrides(self) -> dict[str, Any]:
        """Return callable overrides for the canonical Data Agent tool catalog."""

        return build_data_agent_tool_overrides(self)


def build_data_agent_tool_overrides(runtime: DataAgentToolRuntime) -> dict[str, Any]:
    """Build callable overrides bound to one runtime state holder."""

    return {
        "profile_schema": runtime_profile_schema(runtime),
        "build_analysis_plan": runtime_build_analysis_plan(runtime),
        "execute_pandas_plan": runtime_execute_pandas_plan(runtime),
        "execute_sql_plan": runtime_execute_sql_plan(runtime),
        "verify_results": runtime_verify_results(),
        "build_chart_spec": runtime_build_chart_spec(),
        "generate_insight": runtime_generate_insight(),
    }


def runtime_profile_schema(runtime: DataAgentToolRuntime) -> Any:
    """Return a tool callable for dataset schema profile summaries."""

    def profile_schema(arguments: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(arguments["dataset_id"])
        profile = runtime.dataset_profiles.get(dataset_id)
        if profile is None:
            tables = _tables_from_context(_context_for(runtime, dataset_id))
            table_profiles = list(profile_tables(tables).values())
            profile = DatasetProfile(
                dataset_id=dataset_id,
                file_name="runtime_dataset",
                status="ready",
                tables=table_profiles,
            )
        return _json_ready(profile)

    return profile_schema


def runtime_build_analysis_plan(runtime: DataAgentToolRuntime) -> Any:
    """Return a tool callable for building AnalysisPlan from LogicForm payloads."""

    def build_plan(arguments: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(arguments["dataset_id"])
        _context_for(runtime, dataset_id)
        intent = dict(arguments["intent"])
        column_mapping = dict(arguments["column_mapping"])
        logic_form = _logic_form_from_payload(intent.get("logic_form") or intent, column_mapping)
        plan = build_analysis_plan(logic_form)
        return {"dataset_id": dataset_id, "logic_form": asdict(logic_form), "analysis_plan": asdict(plan)}

    return build_plan


def runtime_execute_pandas_plan(runtime: DataAgentToolRuntime) -> Any:
    """Return a tool callable for executing a validated plan with Pandas."""

    def execute(arguments: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(arguments["dataset_id"])
        plan = _analysis_plan_from_payload(arguments["analysis_plan"])
        result = pandas_executor.execute_plan(plan, _context_for(runtime, dataset_id))
        return _execution_payload(result)

    return execute


def runtime_execute_sql_plan(runtime: DataAgentToolRuntime) -> Any:
    """Return a tool callable for executing a validated plan with SQL/DuckDB path."""

    def execute(arguments: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(arguments["dataset_id"])
        plan = _analysis_plan_from_payload(arguments["analysis_plan"])
        result = sql_executor.execute_plan(plan, _context_for(runtime, dataset_id))
        return _execution_payload(result)

    return execute


def runtime_verify_results() -> Any:
    """Return a tool callable for Pandas/SQL comparison and verification."""

    def verify(arguments: dict[str, Any]) -> dict[str, Any]:
        pandas_result = _execution_result_from_payload(arguments["pandas_result"])
        sql_result = _execution_result_from_payload(arguments["sql_result"])
        comparison = compare_results(pandas_result, sql_result)
        verification = verify_execution(pandas_result, comparison)
        return {
            "comparison": _json_ready(comparison),
            "verification": _json_ready(verification),
            "pandas_result": _execution_payload(pandas_result),
            "sql_result": _execution_payload(sql_result),
        }

    return verify


def runtime_build_chart_spec() -> Any:
    """Return a tool callable for a conservative frontend-neutral chart spec."""

    def build_chart(arguments: dict[str, Any]) -> dict[str, Any]:
        plan = _analysis_plan_from_payload(arguments["analysis_plan"])
        verified_result = dict(arguments["verified_result"])
        return _json_ready(
            build_chart_spec(
                plan=plan,
                execution_result=verified_result.get("pandas_result") or verified_result,
                verification_passed=_verification_passed(verified_result),
            )
        )

    return build_chart


def runtime_generate_insight() -> Any:
    """Return a tool callable for safe baseline insight from verified results."""

    def generate(arguments: dict[str, Any]) -> dict[str, Any]:
        question = str(arguments["question"])
        verified_result = dict(arguments["verified_result"])
        return _json_ready(
            generate_insight(
                question=question,
                plan=arguments.get("analysis_plan"),
                execution_result=verified_result.get("pandas_result") or verified_result,
                verification_passed=_verification_passed(verified_result),
                quality_report=verified_result.get("quality_report"),
            )
        )

    return generate


def execute_data_quality_report(context: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-ready quality report for all available tables."""

    report = build_data_quality_report(_tables_from_context(context), generated_from="analysis_request")
    payload = report_to_dict(report) or {}
    payload["answer"] = payload.get("summary") or "数据质量扫描完成。"
    return payload


def _context_for(runtime: DataAgentToolRuntime, dataset_id: str) -> dict[str, Any]:
    try:
        return runtime.dataset_contexts[dataset_id]
    except KeyError as exc:
        raise KeyError(f"Unknown dataset_id for tool runtime: {dataset_id}") from exc


def _tables_from_context(context: dict[str, Any]) -> dict[str, Any]:
    if "tables" in context:
        return context["tables"]
    if "payments" in context:
        return {"payments": context["payments"]}
    raise ValueError("Dataset context must contain tables or payments.")


def _logic_form_from_payload(payload: dict[str, Any], column_mapping: dict[str, Any]) -> LogicForm:
    parameters = dict(payload.get("parameters") or {})
    mapped_columns = dict(column_mapping.get("mapped_columns") or {})
    for key in ("metric", "dimension", "group_by"):
        if key not in parameters and key in mapped_columns:
            parameters[key] = mapped_columns[key]
    if "table" not in parameters and column_mapping.get("table"):
        parameters["table"] = column_mapping["table"]
    return LogicForm(
        task_type=str(payload.get("task_type") or "unsupported"),
        operation=str(payload.get("operation") or payload.get("task_type") or "not_applicable"),
        metric=payload.get("metric"),
        metric_definition=dict(payload.get("metric_definition") or {}),
        numerator=dict(payload.get("numerator") or {}),
        denominator=dict(payload.get("denominator") or {}),
        entity_grain=dict(payload.get("entity_grain") or {}),
        time_window=dict(payload.get("time_window") or {}),
        candidate_set=dict(payload.get("candidate_set") or {}),
        group_by=payload.get("group_by"),
        objective=payload.get("objective"),
        options=dict(payload.get("options") or {}),
        filters=dict(payload.get("filters") or {}),
        parameters=parameters,
        source_tables=list(payload.get("source_tables") or parameters.get("source_tables") or []),
        table_selection_reason=str(payload.get("table_selection_reason") or parameters.get("table_selection_reason") or ""),
        join_plan=dict(payload.get("join_plan") or parameters.get("join_plan") or {}),
        answer_target=payload.get("answer_target") or dict(payload.get("output_format") or {}).get("answer_target"),
        output_format=dict(payload.get("output_format") or {}),
        output_contract=dict(payload.get("output_contract") or {}),
    )


def _analysis_plan_from_payload(payload: dict[str, Any]) -> AnalysisPlan:
    data = dict(payload)
    logic_payload = data.get("logic_form")
    logic_form = logic_payload if isinstance(logic_payload, LogicForm) else _logic_form_from_payload(dict(logic_payload or {}), {})
    return AnalysisPlan(
        plan_id=str(data.get("plan_id") or "plan_tool_runtime"),
        logic_form=logic_form,
        steps=list(data.get("steps") or []),
        expected_result_shape=str(data.get("expected_result_shape") or "scalar"),
        constraints=dict(data.get("constraints") or {}),
    )


def _execution_result_from_payload(payload: dict[str, Any]) -> ExecutionResult:
    data = dict(payload)
    return ExecutionResult(
        backend=str(data.get("backend") or "unknown"),
        success=bool(data.get("success")),
        columns=list(data.get("columns") or []),
        rows=list(data.get("rows") or []),
        value=data.get("value"),
        summary=str(data.get("summary") or ""),
        latency_ms=data.get("latency_ms"),
        warnings=list(data.get("warnings") or []),
        errors=list(data.get("errors") or []),
        debug=dict(data.get("debug") or {}),
    )


def _execution_payload(result: ExecutionResult) -> dict[str, Any]:
    return _json_ready(result)


def _verification_passed(payload: dict[str, Any]) -> bool:
    verification = payload.get("verification") if isinstance(payload.get("verification"), dict) else payload
    return bool(verification.get("passed", payload.get("success", False)))


def _rows_and_columns(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    result = payload.get("pandas_result") or payload.get("execution_result") or payload.get("result") or payload
    if isinstance(result, dict):
        rows = list(result.get("rows") or [])
        columns = list(result.get("columns") or [])
        if not columns and rows:
            columns = list(rows[0])
        return rows, columns
    return [], []


def _json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value
