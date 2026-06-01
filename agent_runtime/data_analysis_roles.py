"""Executable role handlers for the internal multi-agent data workflow."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from agent_runtime.agent_result import AgentResult
from agent_runtime.agent_role import AgentRole
from agent_runtime.agent_task import AgentTask
from agent_runtime.data_agent_tool_catalog import build_runtime_data_agent_tool_registry
from agent_runtime.data_agent_tool_impl import DataAgentToolRuntime
from agent_runtime.tool_contracts import ToolCall, ToolTraceEvent, to_json_ready
from agent_runtime.tool_dispatcher import ToolDispatcher
from agent_runtime.workflow_state import WorkflowState
from data_agent_core.contracts.analysis_contracts import AnalysisPlan, LogicForm, UserQuestion
from data_agent_core.contracts.dataset_contracts import DatasetProfile
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.response_contracts import ChartSpec, FinalResponse, InsightResult
from data_agent_core.contracts.verification_contracts import VerificationResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.capability_registry import coverage_summary_for_logic_form
from data_agent_core.core.data_quality import build_data_quality_report, report_to_dict
from data_agent_core.core.intent_parser import parse_generic_table_question, parse_question
from data_agent_core.core.planner_guardrails import available_columns_by_table_from_context, validate_logic_form_with_guardrails
from data_agent_core.llm.client import LLMClient, load_llm_client_from_env
from data_agent_core.llm.planner import LLMPlanResult, LLMStageResult, complete_stage_with_llm, plan_with_llm
from data_agent_core.output.chart_renderer import attach_rendered_chart
from data_agent_core.output.response_builder import build_response
from data_agent_core.verifier.result_comparator import compare_results
from data_agent_core.verifier.result_normalizer import normalize_value
from data_agent_core.verifier.rule_checker import verify_execution


class DataAnalysisRoleRuntime:
    """Runs one responsibility-bounded internal AgentRole at a time."""

    def __init__(
        self,
        *,
        dataset_id: str,
        context: dict[str, Any],
        dataset_profile: DatasetProfile | dict[str, Any] | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.dataset_id = dataset_id
        self.context = context
        self.dataset_profile = dataset_profile
        self.llm_client = llm_client or load_llm_client_from_env()
        tool_runtime = DataAgentToolRuntime(
            dataset_contexts={dataset_id: context},
            dataset_profiles={dataset_id: dataset_profile} if dataset_profile is not None else None,
        )
        self.dispatcher = ToolDispatcher(build_runtime_data_agent_tool_registry(tool_runtime))

    def run_data_engineer(self, task: AgentTask, state: WorkflowState) -> AgentResult:
        """Profile schema through the controlled tool layer."""

        result = self.dispatcher.dispatch(
            ToolCall(
                step_id=task.task_id,
                tool_name="profile_schema",
                arguments={"dataset_id": self.dataset_id},
                requested_by=AgentRole.DATA_ENGINEER,
            )
        )
        _append_tool_trace(state, result.trace_event)
        state.schema_profile = result.output_payload
        return _agent_result(task, result.success, result.output_payload, result.errors, confidence=1.0 if result.success else 0.0)

    def run_planner(self, task: AgentTask, state: WorkflowState, *, guidelines: str) -> AgentResult:
        """Run LLM intent, column mapping, and plan drafting with rule guardrails."""

        question = state.question
        context_summary = self.context_summary()
        llm_intent = self._safe_complete_stage_with_llm(
            stage_name="intent_parser",
            stage_goal="Planner Agent converts the user's data question into a structured intent draft.",
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            payload={"input_contract": "UserQuestion", "agent_role": AgentRole.PLANNER.value},
            required_output={
                "task_type": "ranking | aggregation | filtering | trend | comparison | fee_rule | unsupported",
                "intent_summary": "short summary, not chain of thought",
                "filters": "object",
                "metrics": "array",
                "dimensions": "array",
                "confidence": "number between 0 and 1",
                "reasoning_summary": "short summary, not chain of thought",
            },
        )
        guardrail_logic_form = self.guardrail_logic_form(question, guidelines)
        column_mapping = self.rule_column_mapping(guardrail_logic_form)
        llm_column_mapping = self._safe_complete_stage_with_llm(
            stage_name="column_mapping",
            stage_goal="Data Engineer semantics assist Planner Agent with field mapping while rules remain authoritative.",
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            payload={
                "llm_intent_summary": _stage_summary(llm_intent),
                "rule_column_mapping": column_mapping,
                "agent_role": AgentRole.PLANNER.value,
            },
            required_output={
                "mapped_columns": "object",
                "unmapped_terms": "array",
                "warnings": "array",
                "confidence": "number between 0 and 1",
                "reasoning_summary": "short summary, not chain of thought",
            },
        )
        llm_plan = self._safe_plan_with_llm(
            question=question,
            guidelines=guidelines,
            context_summary=context_summary | {"rule_column_mapping": column_mapping},
            guardrail_logic_form=guardrail_logic_form,
        )
        logic_form = _validated_logic_form(llm_plan.logic_form, guardrail_logic_form, self.context)
        tool_result = self.dispatcher.dispatch(
            ToolCall(
                step_id=task.task_id + "_tool",
                tool_name="build_analysis_plan",
                arguments={
                    "dataset_id": self.dataset_id,
                    "intent": _json_ready(logic_form),
                    "column_mapping": column_mapping,
                },
                requested_by=AgentRole.PLANNER,
            )
        )
        _append_tool_trace(state, tool_result.trace_event)
        if tool_result.success:
            state.logic_form = tool_result.output_payload["logic_form"]
            state.analysis_plan = tool_result.output_payload["analysis_plan"]
        else:
            plan = build_analysis_plan(logic_form)
            state.logic_form = _json_ready(logic_form)
            state.analysis_plan = _json_ready(plan)
        output = {
            "intent_parser": _stage_summary(llm_intent),
            "column_mapping": {"rule_mapping": column_mapping, "llm_summary": _stage_summary(llm_column_mapping)},
            "analysis_planner": {
                "stage_name": "analysis_planner",
                "confidence": llm_plan.confidence,
                "reasoning_summary": _short_text(llm_plan.reasoning_summary),
                "llm_operation": llm_plan.logic_form.operation,
                "selected_operation": logic_form.operation,
                "guardrail_applied": llm_plan.logic_form.operation != logic_form.operation,
            },
            "logic_form": state.logic_form,
            "analysis_plan": state.analysis_plan,
        }
        return _agent_result(task, True, output, confidence=max(llm_intent.confidence, llm_plan.confidence))

    def run_pandas_executor(self, task: AgentTask, state: WorkflowState) -> AgentResult:
        """Run the Pandas executor through the controlled tool layer."""

        result = self.dispatcher.dispatch(
            ToolCall(
                step_id=task.task_id,
                tool_name="execute_pandas_plan",
                arguments={"dataset_id": self.dataset_id, "analysis_plan": state.analysis_plan},
                requested_by=AgentRole.PANDAS_EXECUTOR,
            )
        )
        _append_tool_trace(state, result.trace_event)
        state.pandas_result = result.output_payload
        return _agent_result(task, result.success, result.output_payload, result.errors, confidence=1.0 if result.success else 0.0)

    def apply_corrected_logic_form(self, state: WorkflowState, corrected_logic_form: dict[str, Any]) -> None:
        """Apply a structured correction action and rebuild the analysis plan."""

        logic_form = _logic_form_from_payload(corrected_logic_form)
        plan = build_analysis_plan(logic_form)
        state.logic_form = _json_ready(logic_form)
        state.analysis_plan = _json_ready(plan)
        state.pandas_result = None
        state.sql_result = None
        state.verification = None

    def run_sql_executor(self, task: AgentTask, state: WorkflowState, *, execution_mode: str) -> AgentResult:
        """Run SQL executor when the plan is SQL-compatible."""

        operation = str((state.logic_form or {}).get("operation") or "")
        coverage = coverage_summary_for_logic_form(
            state.logic_form or {},
            available_columns=_available_columns_for_logic_form(self.context, state.logic_form),
        )
        if execution_mode not in {"auto", "dual", "sql"} or not coverage["native_sql_supported"]:
            reason = coverage.get("reason") or f"Operation {operation} is not SQL-compatible in the current MVP."
            if execution_mode not in {"auto", "dual", "sql"}:
                reason = f"Execution mode {execution_mode} does not request SQL execution."
            output = {"skipped": True, "reason": reason, **coverage}
            state.sql_result = output
            return _agent_result(task, True, output, confidence=1.0)
        result = self.dispatcher.dispatch(
            ToolCall(
                step_id=task.task_id,
                tool_name="execute_sql_plan",
                arguments={"dataset_id": self.dataset_id, "analysis_plan": state.analysis_plan},
                requested_by=AgentRole.SQL_EXECUTOR,
            )
        )
        _append_tool_trace(state, result.trace_event)
        state.sql_result = result.output_payload
        return _agent_result(task, result.success, result.output_payload, result.errors, confidence=1.0 if result.success else 0.0)

    def run_verifier(self, task: AgentTask, state: WorkflowState, *, guidelines: str) -> AgentResult:
        """Run rule-first verification plus LLM critique."""

        pandas_result = _execution_result_from_payload(state.pandas_result or {})
        plan = _analysis_plan_from_payload(state.analysis_plan or {})
        user_question = UserQuestion(dataset_id=self.dataset_id, question=state.question, execution_mode="auto", guidelines=guidelines)
        sql_payload = state.sql_result if isinstance(state.sql_result, dict) else {}
        if sql_payload and not sql_payload.get("skipped"):
            comparison = compare_results(pandas_result, _execution_result_from_payload(sql_payload))
            verification = verify_execution(pandas_result, comparison, plan=plan, user_question=user_question)
            comparison_summary = _json_ready(comparison)
        else:
            verification = verify_execution(pandas_result, plan=plan, user_question=user_question)
            comparison_summary = None
        state.verification = _json_ready(verification)
        critic = self._safe_complete_stage_with_llm(
            stage_name="verifier_critic",
            stage_goal="Verifier Agent critiques rule verification notes without changing execution results.",
            question=state.question,
            guidelines=guidelines,
            context_summary=self.context_summary(),
            payload={
                "analysis_plan": state.analysis_plan,
                "pandas_result_summary": _execution_summary(state.pandas_result),
                "sql_result_summary": _execution_summary(state.sql_result),
                "rule_verification": state.verification,
                "comparison": comparison_summary,
            },
            required_output={
                "passed": "boolean",
                "issues": "array",
                "verification_notes": "array",
                "confidence": "number between 0 and 1",
                "reasoning_summary": "short summary, not chain of thought",
            },
        )
        output = {"verification": state.verification, "verifier_critic": _stage_summary(critic)}
        return _agent_result(task, verification.passed, output, issues=verification.issues, confidence=verification.confidence)

    def run_correction(self, task: AgentTask, state: WorkflowState, *, guidelines: str) -> AgentResult:
        """Run bounded correction planning without executing arbitrary retries."""

        rule_action = (state.verification or {}).get("correction_action") if isinstance(state.verification, dict) else None
        if isinstance(rule_action, dict):
            rule_action = _action_with_runtime_available_columns(rule_action, self.context, state.logic_form)
        correction = self._safe_complete_stage_with_llm(
            stage_name="correction_planner",
            stage_goal="Correction Agent proposes bounded correction directions only; code remains responsible for execution.",
            question=state.question,
            guidelines=guidelines,
            context_summary=self.context_summary(),
            payload={"rule_verification": state.verification or {}, "rule_correction_action": rule_action, "max_attempts": 2},
            required_output={
                "needs_correction": "boolean",
                "correction_targets": "array",
                "max_attempts": 2,
                "confidence": "number between 0 and 1",
                "reasoning_summary": "short summary, not chain of thought",
            },
        )
        output = _stage_summary(correction)
        if isinstance(rule_action, dict):
            output["needs_correction"] = True
            output["correction_action"] = rule_action
            corrected_logic_form = _corrected_logic_form_payload(state.logic_form or {}, rule_action)
            if corrected_logic_form:
                output["corrected_logic_form"] = corrected_logic_form
        else:
            output["needs_correction"] = False
        state.correction_attempts.append(output)
        return _agent_result(task, True, output, confidence=correction.confidence)

    def run_insight(self, task: AgentTask, state: WorkflowState, *, guidelines: str) -> AgentResult:
        """Run Insight Agent after verification."""

        verified_result = _verified_result_payload(state, quality_report=self._quality_report_payload())
        tool_result = self.dispatcher.dispatch(
            ToolCall(
                step_id=task.task_id + "_tool",
                tool_name="generate_insight",
                arguments={"question": state.question, "analysis_plan": state.analysis_plan, "verified_result": verified_result},
                requested_by=AgentRole.INSIGHT,
            )
        )
        _append_tool_trace(state, tool_result.trace_event)
        llm_insight = self._safe_complete_stage_with_llm(
            stage_name="insight_generator",
            stage_goal="Insight Agent generates concise insight only from verified execution results.",
            question=state.question,
            guidelines=guidelines,
            context_summary=self.context_summary(),
            payload={"trusted_result": bool((state.verification or {}).get("passed")), "verified_result": verified_result},
            required_output={
                "summary": "short answer-grounded insight",
                "suggestions": "array",
                "caveats": "array",
                "confidence": "number between 0 and 1",
                "reasoning_summary": "short summary, not chain of thought",
            },
        )
        state.insight = _merge_insight(tool_result.output_payload, llm_insight)
        return _agent_result(task, tool_result.success, {"insight": state.insight, "llm_summary": _stage_summary(llm_insight)}, tool_result.errors, llm_insight.confidence)

    def run_visualization(self, task: AgentTask, state: WorkflowState, *, guidelines: str) -> AgentResult:
        """Run Visualization Agent with rule-first chart spec and LLM semantics."""

        verified_result = _verified_result_payload(state)
        tool_result = self.dispatcher.dispatch(
            ToolCall(
                step_id=task.task_id + "_tool",
                tool_name="build_chart_spec",
                arguments={"analysis_plan": state.analysis_plan, "verified_result": verified_result},
                requested_by=AgentRole.VISUALIZATION,
            )
        )
        _append_tool_trace(state, tool_result.trace_event)
        llm_chart = self._safe_complete_stage_with_llm(
            stage_name="chart_planner",
            stage_goal="Visualization Agent selects a frontend-neutral chart spec using verified results and rule constraints.",
            question=state.question,
            guidelines=guidelines,
            context_summary=self.context_summary(),
            payload={"analysis_plan": state.analysis_plan, "rule_chart": tool_result.output_payload, "trusted_result": bool((state.verification or {}).get("passed"))},
            required_output={
                "chart_type": "bar | line | pie | donut | histogram | box | scatter | none",
                "x": "field name or null",
                "y": "field name or null",
                "title": "string or null",
                "reason": "short summary, not chain of thought",
                "confidence": "number between 0 and 1",
                "reasoning_summary": "short summary, not chain of thought",
            },
        )
        state.chart = _merge_chart(tool_result.output_payload, llm_chart)
        return _agent_result(task, tool_result.success, {"chart": state.chart, "llm_summary": _stage_summary(llm_chart)}, tool_result.errors, llm_chart.confidence)

    def build_final_response(
        self,
        *,
        run_id: str,
        state: WorkflowState,
        guidelines: str,
        execution_mode: str,
        task_results: list[AgentResult],
    ) -> FinalResponse:
        """Build the stable final response from multi-agent state."""

        plan = _analysis_plan_from_payload(state.analysis_plan or {})
        pandas_result = _execution_result_from_payload(state.pandas_result or {})
        verification = _verification_result_from_payload(state.verification or {})
        response = build_response(
            run_id=run_id,
            user_question=UserQuestion(
                dataset_id=self.dataset_id,
                question=state.question,
                execution_mode=execution_mode,
                guidelines=guidelines,
            ),
            plan=plan,
            execution_result=pandas_result,
            verification=verification,
            debug={
                "agent_mode": "multi_agent",
                "workflow_mode": "phase6_internal_multi_agent",
                "operation": plan.logic_form.operation,
                "source_tables": list(plan.logic_form.source_tables),
                "table_selection_reason": plan.logic_form.table_selection_reason,
                "join_plan": plan.logic_form.join_plan,
                "join_execution_summary": pandas_result.debug.get("join_execution_summary") if isinstance(pandas_result.debug, dict) else None,
                "capability": coverage_summary_for_logic_form(
                    state.logic_form or {},
                    available_columns=_available_columns_for_logic_form(self.context, state.logic_form),
                ),
                "multi_agent_roles": _roles_with_response_builder(task_results),
                "agent_task_results": [_agent_summary(result) for result in task_results],
                "tool_call_summaries": state.tool_call_trace,
                "microsoft_adapter_ready": True,
            },
            quality_report=self._quality_report_payload(),
        )
        response.insight = _insight_from_payload(state.insight)
        response.chart = _chart_from_payload(state.chart)
        state.final_response = response.to_dict()
        return response

    def _quality_report_payload(self) -> dict[str, Any] | None:
        """Return profile quality report or build one from in-memory tables."""

        profile = self.dataset_profile
        if is_dataclass(profile):
            payload = asdict(profile)
        elif isinstance(profile, dict):
            payload = profile
        else:
            payload = {}
        report = payload.get("quality_report")
        if isinstance(report, dict):
            return report
        tables = self.context.get("tables")
        if isinstance(tables, dict):
            return report_to_dict(build_data_quality_report(tables, generated_from="analysis_runtime"))
        return None

    def _safe_complete_stage_with_llm(self, **kwargs: Any) -> LLMStageResult:
        try:
            return complete_stage_with_llm(llm_client=self.llm_client, **kwargs)
        except Exception as exc:  # noqa: BLE001 - provider failures must not block rule-backed execution.
            return _fallback_stage_result(str(kwargs.get("stage_name") or "llm_stage"), exc)

    def _safe_plan_with_llm(
        self,
        *,
        question: str,
        guidelines: str,
        context_summary: dict[str, Any],
        guardrail_logic_form: LogicForm,
    ) -> LLMPlanResult:
        try:
            return plan_with_llm(
                llm_client=self.llm_client,
                question=question,
                guidelines=guidelines,
                context_summary=context_summary,
            )
        except Exception as exc:  # noqa: BLE001 - use deterministic parser when provider is unavailable.
            return LLMPlanResult(
                logic_form=guardrail_logic_form,
                raw=_fallback_stage_result("analysis_planner", exc).raw,
                confidence=0.0,
                reasoning_summary=f"LLM planner unavailable; used deterministic guardrail plan ({type(exc).__name__}).",
            )

    def context_summary(self) -> dict[str, Any]:
        """Return a compact schema summary for LLM stages."""

        if "payments" in self.context:
            payments = self.context["payments"]
            merchants = self.context.get("merchant_data") or []
            return {
                "tables": {"payments": {"columns": list(payments.columns), "row_count": int(len(payments))}},
                "knowledge_files": ["manual.md", "fees.json", "merchant_data.json"],
                "merchant_names": [row["merchant"] for row in merchants if isinstance(row, dict) and "merchant" in row],
            }
        tables = self.context.get("tables") or {}
        return {"tables": {name: {"columns": list(df.columns), "row_count": int(len(df))} for name, df in tables.items()}, "knowledge_files": []}

    def guardrail_logic_form(self, question: str, guidelines: str) -> LogicForm:
        """Build deterministic guardrail LogicForm for the current dataset kind."""

        if "payments" in self.context:
            return parse_question(question, guidelines, self.context)
        return parse_generic_table_question(question, self.context.get("tables") or {}, guidelines)

    def rule_column_mapping(self, logic_form: LogicForm) -> dict[str, Any]:
        """Map selected logic fields to known dataset columns."""

        table_name = str(logic_form.parameters.get("table") or self._primary_table_name())
        df = (self.context.get("tables") or {}).get(table_name) if "tables" in self.context else self.context.get("payments")
        available_columns = list(df.columns) if df is not None else []
        available = set(available_columns)
        mapped_columns: dict[str, str] = {}
        for key, value in logic_form.parameters.items():
            if isinstance(value, str) and value in available:
                mapped_columns[key] = value
        for key in logic_form.filters:
            if key in available:
                mapped_columns[key] = key
        return {
            "table": table_name,
            "available_columns": available_columns,
            "mapped_columns": mapped_columns,
            "knowledge_fields": ["manual.md", "fees.json", "merchant_data.json"] if "payments" in self.context else [],
            "unmapped_terms": [],
        }

    def _primary_table_name(self) -> str:
        if "primary_table" in self.context:
            return str(self.context["primary_table"])
        tables = self.context.get("tables") or {}
        if tables:
            return max(tables.items(), key=lambda item: (len(item[1]), len(item[1].columns)))[0]
        return "payments"


def _available_columns_for_logic_form(context: dict[str, Any], logic_form: Any) -> list[str] | None:
    params = (logic_form or {}).get("parameters") if isinstance(logic_form, dict) else {}
    table_name = str((params or {}).get("table") or context.get("primary_table") or "payments")
    if table_name == "payments" and "payments" in context:
        return [str(column) for column in context["payments"].columns]
    tables = context.get("tables")
    if isinstance(tables, dict) and table_name in tables:
        return [str(column) for column in tables[table_name].columns]
    if isinstance(tables, dict) and tables:
        table = next(iter(tables.values()))
        return [str(column) for column in table.columns]
    return None


def _action_with_runtime_available_columns(action: dict[str, Any], context: dict[str, Any], logic_form: Any) -> dict[str, Any]:
    if action.get("action") != "repair_dimension_binding" or action.get("available_columns"):
        return action
    available_columns = _available_columns_for_logic_form(context, logic_form)
    if not available_columns:
        return action
    enriched = dict(action)
    enriched["available_columns"] = available_columns
    return enriched


def _agent_result(
    task: AgentTask,
    success: bool,
    output_payload: dict[str, Any],
    errors: list[Any] | None = None,
    confidence: float = 0.0,
    issues: list[str] | None = None,
) -> AgentResult:
    return AgentResult(
        task_id=task.task_id,
        role=task.role,
        success=success,
        output_payload=to_json_ready(output_payload),
        issues=issues or [str(error) for error in (errors or [])],
        confidence=confidence,
    )


def _append_tool_trace(state: WorkflowState, trace_event: ToolTraceEvent | None) -> None:
    if trace_event is not None:
        state.tool_call_trace.append(trace_event.to_dict())


def _validated_logic_form(llm_logic_form: LogicForm, guardrail_logic_form: LogicForm, context: dict[str, Any]) -> LogicForm:
    return validate_logic_form_with_guardrails(
        llm_logic_form,
        guardrail_logic_form,
        available_columns_by_table=available_columns_by_table_from_context(context),
    )


def _merge_optional_contract_fields(target: LogicForm, source: LogicForm) -> None:
    for field_name in (
        "metric_definition",
        "numerator",
        "denominator",
        "entity_grain",
        "time_window",
        "candidate_set",
        "output_contract",
        "options",
        "filters",
        "parameters",
        "source_tables",
        "join_plan",
        "output_format",
    ):
        source_value = getattr(source, field_name)
        target_value = getattr(target, field_name)
        if isinstance(source_value, dict) and isinstance(target_value, dict):
            for key, value in source_value.items():
                target_value.setdefault(key, value)
        elif isinstance(source_value, list) and isinstance(target_value, list) and not target_value:
            target_value.extend(source_value)
    for field_name in ("metric", "group_by", "objective"):
        if getattr(target, field_name) is None and getattr(source, field_name) is not None:
            setattr(target, field_name, getattr(source, field_name))
    if not target.table_selection_reason and source.table_selection_reason:
        target.table_selection_reason = source.table_selection_reason


def _analysis_plan_from_payload(payload: dict[str, Any]) -> AnalysisPlan:
    logic_form = _logic_form_from_payload(payload.get("logic_form") or {})
    return AnalysisPlan(
        plan_id=str(payload.get("plan_id") or "plan_multi_agent"),
        logic_form=logic_form,
        steps=list(payload.get("steps") or []),
        expected_result_shape=str(payload.get("expected_result_shape") or "scalar"),
        constraints=dict(payload.get("constraints") or {}),
    )


def _logic_form_from_payload(payload: dict[str, Any]) -> LogicForm:
    return LogicForm(
        task_type=str(payload.get("task_type") or "unknown"),
        operation=str(payload.get("operation") or "not_applicable"),
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
        parameters=dict(payload.get("parameters") or {}),
        source_tables=list(payload.get("source_tables") or []),
        table_selection_reason=str(payload.get("table_selection_reason") or ""),
        join_plan=dict(payload.get("join_plan") or {}),
        answer_target=payload.get("answer_target") or dict(payload.get("output_format") or {}).get("answer_target"),
        output_format=dict(payload.get("output_format") or {}),
        output_contract=dict(payload.get("output_contract") or {}),
    )


def _execution_result_from_payload(payload: dict[str, Any]) -> ExecutionResult:
    return ExecutionResult(
        backend=str(payload.get("backend") or "unknown"),
        success=bool(payload.get("success")),
        columns=list(payload.get("columns") or []),
        rows=list(payload.get("rows") or []),
        value=payload.get("value"),
        summary=str(payload.get("summary") or ""),
        latency_ms=payload.get("latency_ms"),
        warnings=list(payload.get("warnings") or []),
        errors=list(payload.get("errors") or []),
        debug=dict(payload.get("debug") or {}),
    )


def _verification_result_from_payload(payload: dict[str, Any]) -> VerificationResult:
    return VerificationResult(
        passed=bool(payload.get("passed")),
        confidence=float(payload.get("confidence") or 0.0),
        pandas_sql_consistent=payload.get("pandas_sql_consistent"),
        semantic_passed=payload.get("semantic_passed"),
        issues=list(payload.get("issues") or []),
        notes=list(payload.get("notes") or []),
        semantic_verification_notes=list(payload.get("semantic_verification_notes") or []),
        correction_action=payload.get("correction_action"),
    )


def _verified_result_payload(state: WorkflowState, quality_report: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "verification": state.verification,
        "pandas_result": state.pandas_result,
        "sql_result": state.sql_result,
    }
    if quality_report is not None:
        payload["quality_report"] = quality_report
    return payload


def _merge_insight(tool_payload: dict[str, Any], llm_stage: LLMStageResult) -> dict[str, Any]:
    raw = llm_stage.raw
    payload = dict(tool_payload or {})
    if raw.get("summary"):
        payload["summary"] = str(raw["summary"])
    if isinstance(raw.get("suggestions"), list):
        payload.setdefault("suggestions", raw["suggestions"])
        payload.setdefault("business_suggestions", raw["suggestions"])
    if isinstance(raw.get("caveats"), list):
        existing = list(payload.get("caveats") or [])
        payload["caveats"] = existing + [item for item in raw["caveats"] if item not in existing]
    payload.setdefault("confidence", llm_stage.confidence or payload.get("confidence") or 0.0)
    return payload


def _merge_chart(tool_payload: dict[str, Any], llm_stage: LLMStageResult) -> dict[str, Any]:
    raw = llm_stage.raw
    payload = dict(tool_payload or {})
    if not payload.get("chart_type") or payload.get("fallback_reason") in {"detail_rows_prefer_table", "unsafe_metric_column"}:
        return payload
    chart_type = raw.get("chart_type")
    raw_y = str(raw.get("y") or "")
    if chart_type and chart_type != "none" and not _unsafe_chart_metric(raw_y):
        payload["chart_type"] = str(chart_type)
        payload["x"] = raw.get("x") or payload.get("x")
        payload["y"] = raw.get("y") or payload.get("y")
        payload["title"] = raw.get("title") or payload.get("title")
        payload["reason"] = str(raw.get("reason") or raw.get("reasoning_summary") or payload.get("reason") or "")
        payload["confidence"] = max(float(payload.get("confidence") or 0.0), llm_stage.confidence)
    return payload


def _unsafe_chart_metric(column: str) -> bool:
    lowered = column.lower()
    compact = lowered.replace("_", "").replace("-", "").replace(" ", "")
    if compact in {"id", "ids", "number", "cardnumber"} or compact.endswith("id") or compact.endswith("ids"):
        return True
    return any(token in lowered for token in ("reference", "psp", "bin", "编号", "代码", "流水", "卡号", "year", "hour", "minute", "day_of_year"))


def _insight_from_payload(payload: Any) -> InsightResult:
    if not isinstance(payload, dict):
        return InsightResult()
    return InsightResult(
        summary=str(payload.get("summary") or ""),
        key_numbers=dict(payload.get("key_numbers") or {}),
        anomaly_findings=list(payload.get("anomaly_findings") or []),
        volatility_findings=list(payload.get("volatility_findings") or []),
        suggestions=list(payload.get("suggestions") or []),
        business_suggestions=list(payload.get("business_suggestions") or payload.get("suggestions") or []),
        caveats=list(payload.get("caveats") or []),
        next_questions=list(payload.get("next_questions") or []),
        next_actions=list(payload.get("next_actions") or []),
        evidence_rows=list(payload.get("evidence_rows") or []),
        confidence=float(payload.get("confidence") or 0.0),
    )


def _chart_from_payload(payload: Any) -> ChartSpec:
    if not isinstance(payload, dict):
        return ChartSpec()
    return attach_rendered_chart(
        ChartSpec(
            chart_type=payload.get("chart_type"),
            x=payload.get("x"),
            y=payload.get("y"),
            title=payload.get("title"),
            data=list(payload.get("data") or []),
            reason=str(payload.get("reason") or ""),
            encoding=dict(payload.get("encoding") or {}),
            series=list(payload.get("series") or []),
            confidence=float(payload.get("confidence") or 0.0),
            selection_reason=str(payload.get("selection_reason") or ""),
            fallback_reason=str(payload.get("fallback_reason") or ""),
        )
    )


def _fallback_stage_result(stage_name: str, exc: Exception) -> LLMStageResult:
    return LLMStageResult(
        stage_name=stage_name,
        raw={
            "stage_name": stage_name,
            "used": False,
            "fallback": "deterministic_guardrail",
            "error_type": type(exc).__name__,
            "error": str(exc)[:240],
        },
        confidence=0.0,
        reasoning_summary=f"LLM stage unavailable; used deterministic guardrails ({type(exc).__name__}).",
    )


def _stage_summary(stage: LLMStageResult) -> dict[str, Any]:
    return {
        "stage_name": stage.stage_name,
        "confidence": stage.confidence,
        "reasoning_summary": _short_text(stage.reasoning_summary),
        "output": _safe_stage_output(stage.raw),
    }


def _safe_stage_output(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _short_text(value) if isinstance(value, str) else value
        for key, value in raw.items()
        if key not in {"chain_of_thought", "cot", "hidden_reasoning", "full_reasoning"}
    }


def _execution_summary(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    return {"success": payload.get("success"), "value": normalize_value(payload.get("value")), "skipped": payload.get("skipped")}


def _agent_summary(result: AgentResult) -> dict[str, Any]:
    return {
        "task_id": result.task_id,
        "role": result.role.value,
        "success": result.success,
        "issues": result.issues,
        "confidence": result.confidence,
    }


def _roles_with_response_builder(task_results: list[AgentResult]) -> list[str]:
    roles = [result.role.value for result in task_results]
    if AgentRole.RESPONSE_BUILDER.value not in roles:
        roles.append(AgentRole.RESPONSE_BUILDER.value)
    return roles


def _json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return _json_ready(asdict(value))
    return to_json_ready(value)


def _short_text(value: Any, limit: int = 500) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "..."


DIMENSION_REPAIR_ALIASES = {
    "product": ("product", "product_name", "sku", "item", "goods", "产品", "商品", "品名", "商品名称", "产品名称"),
    "category": (
        "category",
        "category_name",
        "ctg",
        "ctg_name",
        "prod_category",
        "product_category",
        "product_line",
        "productline",
        "product_segment",
        "sku_category",
        "sku_cat",
        "cat",
        "type",
        "class",
        "classification",
        "line",
        "segment",
        "品类",
        "品类名称",
        "商品品类",
        "产品品类",
        "产品线",
        "商品线",
        "品项",
        "类别",
        "类别名称",
        "类目",
        "类目名称",
        "分类",
    ),
    "store": ("store", "shop", "branch", "门店", "店铺", "门店名称"),
    "city": ("city", "城市", "市"),
    "channel": ("channel", "channel_name", "sale_channel", "sales_channel", "source_channel", "source", "origin", "来源", "渠道", "渠道名称", "销售渠道", "来源渠道", "获客渠道", "通路", "通路名称"),
    "customer": ("customer", "cust", "client", "客户", "终端"),
    "month": ("month", "month_id", "month_code", "stat_month", "ym", "year_month", "biz_month", "period", "month_period", "period_month", "年月", "月份", "月度", "业务月份", "统计月份", "期间"),
    "time": ("date", "day", "week", "period", "日期", "时间", "周期", "业务日期", "统计日期"),
}


def _corrected_logic_form_payload(logic_payload: dict[str, Any], action: dict[str, Any]) -> dict[str, Any] | None:
    if action.get("action") == "repair_dimension_binding":
        return _repair_dimension_binding_logic_form(logic_payload, action)
    if action.get("action") != "replace_logic_form" or action.get("to_operation") != "rank_by_metric":
        return None
    corrected = dict(logic_payload)
    params = dict(corrected.get("parameters") or {})
    group_by = corrected.get("group_by") or params.get("group_by")
    options = dict(corrected.get("options") or params.get("options") or {})
    corrected.update(
        {
            "task_type": "ranking",
            "operation": "rank_by_metric",
            "metric": str(action.get("metric") or "fraud_volume_rate"),
            "metric_definition": {
                "name": str(action.get("metric") or "fraud_volume_rate"),
                "description": "Fraud is defined as fraudulent volume divided by total volume.",
                "aggregation": "ratio",
                "source": "manual.md section 7 and payments.csv",
            },
            "numerator": {"column": "eur_amount", "filter": {"has_fraudulent_dispute": True}, "aggregation": "sum"},
            "denominator": {"column": "eur_amount", "aggregation": "sum"},
            "group_by": group_by,
            "objective": "maximum",
            "options": options,
        }
    )
    params.update({"metric": corrected["metric"], "group_by": group_by, "sort_order": "desc", "limit": 1, "options": options})
    corrected["parameters"] = params
    return corrected


def _repair_dimension_binding_logic_form(logic_payload: dict[str, Any], action: dict[str, Any]) -> dict[str, Any] | None:
    if action.get("missing_dimension"):
        return None
    requested = [str(item) for item in action.get("requested_dimensions") or [] if str(item)]
    if not requested:
        return None
    candidates = _dimension_repair_candidates(logic_payload, action)
    repaired_dimension = _best_dimension_repair_candidate(requested, candidates)
    if not repaired_dimension:
        return None
    actual_dimension = str(action.get("actual_dimension") or "")
    if actual_dimension and _same_dimension_field(actual_dimension, repaired_dimension):
        return None

    corrected = dict(logic_payload)
    params = dict(corrected.get("parameters") or {})
    params["dimension"] = repaired_dimension
    if params.get("group_by") or corrected.get("group_by") or str(corrected.get("operation") or "") in {"top_count", "top_outlier_group"}:
        params["group_by"] = repaired_dimension
        corrected["group_by"] = repaired_dimension
    for key in ("entity", "entity_field", "primary_entity_field"):
        if actual_dimension and _same_dimension_field(str(params.get(key) or ""), actual_dimension):
            params[key] = repaired_dimension
    entity_grain = dict(corrected.get("entity_grain") or {})
    for key, value in list(entity_grain.items()):
        if actual_dimension and _same_dimension_field(str(value or ""), actual_dimension):
            entity_grain[key] = repaired_dimension
    if entity_grain:
        corrected["entity_grain"] = entity_grain
    output_format = dict(corrected.get("output_format") or {})
    if actual_dimension and _same_dimension_field(str(output_format.get("answer_target") or ""), actual_dimension):
        output_format["answer_target"] = repaired_dimension
        corrected["answer_target"] = repaired_dimension
    if output_format:
        corrected["output_format"] = output_format
    reason = str(corrected.get("table_selection_reason") or params.get("table_selection_reason") or "")
    marker = f"corrected_dimension_binding={repaired_dimension}"
    if marker not in reason:
        reason = "; ".join(part for part in (reason, marker) if part)
    corrected["table_selection_reason"] = reason
    params["table_selection_reason"] = reason
    corrected["parameters"] = params
    return corrected


def _dimension_repair_candidates(logic_payload: dict[str, Any], action: dict[str, Any]) -> list[str]:
    params = logic_payload.get("parameters") if isinstance(logic_payload.get("parameters"), dict) else {}
    sources = (
        action.get("available_columns"),
        params.get("available_columns") if isinstance(params, dict) else None,
        logic_payload.get("available_columns"),
    )
    candidates: list[str] = []
    for source in sources:
        if not isinstance(source, (list, tuple, set)):
            continue
        for item in source:
            text = str(item or "")
            if text and text not in candidates:
                candidates.append(text)
    return candidates


def _best_dimension_repair_candidate(requested_concepts: list[str], candidates: list[str]) -> str | None:
    best: tuple[int, int, str] | None = None
    for index, candidate in enumerate(candidates):
        scores = [
            _dimension_concept_score(candidate, concept)
            for concept in requested_concepts
            if _dimension_concept_score(candidate, concept) > 0
        ]
        if not scores:
            continue
        score = max(scores)
        if _dimension_identifier_like(candidate):
            score -= 20
        if best is None or (score, -index) > (best[0], -best[1]):
            best = (score, index, candidate)
    return best[2] if best is not None else None


def _dimension_concept_score(column_name: str, concept: str) -> int:
    aliases = DIMENSION_REPAIR_ALIASES.get(concept) or ()
    normalized_column = _normalize_dimension_token(column_name)
    if not normalized_column:
        return 0
    best = 0
    for alias in aliases:
        normalized_alias = _normalize_dimension_token(alias)
        if not normalized_alias:
            continue
        if normalized_column == normalized_alias:
            best = max(best, 120)
        elif normalized_alias in normalized_column:
            best = max(best, 100)
    return best


def _same_dimension_field(left: str, right: str) -> bool:
    return bool(left and right and _normalize_dimension_token(left) == _normalize_dimension_token(right))


def _dimension_identifier_like(column_name: str) -> bool:
    normalized = _normalize_dimension_token(column_name)
    return normalized.endswith("id") or normalized.endswith("编号") or normalized.endswith("代码")


def _normalize_dimension_token(value: str) -> str:
    text = str(value or "").lower()
    return "".join(char for char in text if char.isalnum() or "\u4e00" <= char <= "\u9fff")
