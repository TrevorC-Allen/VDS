"""Runnable framework-neutral end-to-end multi-agent workflow.

The workflow orchestrates internal AgentRole handlers. It does not import
Microsoft Agent Framework and does not implement core algorithms directly.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_runtime.agent_result import AgentResult
from agent_runtime.agent_role import AgentRole
from agent_runtime.agent_task import AgentTask
from agent_runtime.data_analysis_roles import DataAnalysisRoleRuntime
from agent_runtime.workflow_state import WorkflowState
from data_agent_core.contracts.dataset_contracts import DatasetProfile
from data_agent_core.contracts.response_contracts import FinalResponse
from data_agent_core.core.data_quality import build_data_quality_report, report_to_dict
from data_agent_core.core.file_parser import load_dabstep_context
from data_agent_core.core.schema_profiler import profile_tables
from data_agent_core.llm.client import LLMClient
from data_agent_core.output.process_narrative import build_process_view_v2
from data_agent_core.output.reasoning_trace_view import build_reasoning_trace_view
from data_agent_core.tracing.live_monitor import emit_monitor_event
from data_agent_core.tracing.run_trace import RunTrace


END_TO_END_ROLE_ORDER = [
    AgentRole.PLANNER,
    AgentRole.DATA_ENGINEER,
    AgentRole.PANDAS_EXECUTOR,
    AgentRole.SQL_EXECUTOR,
    AgentRole.VERIFIER,
    AgentRole.CORRECTION,
    AgentRole.INSIGHT,
    AgentRole.VISUALIZATION,
    AgentRole.RESPONSE_BUILDER,
]


def build_end_to_end_tasks(dataset_id: str, question: str) -> list[AgentTask]:
    """Build the canonical future multi-agent task sequence."""

    return [
        AgentTask(
            task_id=f"{index:02d}_{role.value}",
            role=role,
            input_payload={"dataset_id": dataset_id, "question": question},
            constraints={
                "no_benchmark_answer_access": True,
                "no_task_id_optimization": True,
                "core_algorithm_location": "data_agent_core",
            },
        )
        for index, role in enumerate(END_TO_END_ROLE_ORDER, start=1)
    ]


def build_initial_state(dataset_id: str, question: str) -> WorkflowState:
    """Create a serializable initial workflow state."""

    return WorkflowState(dataset_id=dataset_id, question=question)


@dataclass
class MultiAgentWorkflowResult:
    """Final multi-agent workflow output."""

    response: FinalResponse
    trace: RunTrace
    state: WorkflowState
    task_results: list[AgentResult]


class DataAnalysisMultiAgentWorkflow:
    """Phase 6 internal multi-agent workflow runner."""

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
        self.runtime = DataAnalysisRoleRuntime(
            dataset_id=dataset_id,
            context=context,
            dataset_profile=dataset_profile,
            llm_client=llm_client,
        )

    @classmethod
    def from_dabstep_context(
        cls,
        context_dir: str | Path,
        *,
        dataset_id: str = "dabstep_context",
        llm_client: LLMClient | None = None,
    ) -> "DataAnalysisMultiAgentWorkflow":
        """Create a multi-agent workflow for DABstep-style context files."""

        return cls(dataset_id=dataset_id, context=load_dabstep_context(context_dir), llm_client=llm_client)

    @classmethod
    def from_uploaded_tables(
        cls,
        tables: dict[str, Any],
        *,
        dataset_id: str,
        dataset_profile: DatasetProfile | dict[str, Any] | None = None,
        llm_client: LLMClient | None = None,
    ) -> "DataAnalysisMultiAgentWorkflow":
        """Create a multi-agent workflow for uploaded CSV / Excel tables."""

        context = {"tables": tables, "primary_table": _primary_table_name(tables)}
        if dataset_profile is None:
            dataset_profile = DatasetProfile(
                dataset_id=dataset_id,
                file_name="uploaded_tables",
                status="ready",
                tables=list(profile_tables(tables).values()),
                quality_report=report_to_dict(build_data_quality_report(tables, generated_from="upload_profile")),
            )
        return cls(dataset_id=dataset_id, context=context, dataset_profile=dataset_profile, llm_client=llm_client)

    def analyze(
        self,
        question: str,
        guidelines: str = "",
        execution_mode: str = "auto",
        *,
        monitor_run_id: str = "",
    ) -> tuple[FinalResponse, RunTrace]:
        """Run the canonical Phase 6 role sequence and return stable outputs."""

        result = self.run(question=question, guidelines=guidelines, execution_mode=execution_mode, monitor_run_id=monitor_run_id)
        return result.response, result.trace

    def run(
        self,
        question: str,
        guidelines: str = "",
        execution_mode: str = "auto",
        *,
        monitor_run_id: str = "",
    ) -> MultiAgentWorkflowResult:
        """Run all internal AgentRole steps."""

        start = time.perf_counter()
        run_id = "run_" + uuid.uuid4().hex[:16]
        state = build_initial_state(self.dataset_id, question)
        task_results: list[AgentResult] = []
        task_by_role = {task.role: task for task in build_end_to_end_tasks(self.dataset_id, question)}

        emit_monitor_event(
            monitor_run_id,
            "workflow_started",
            title="工作流开始",
            summary=f"已进入 multi-agent 分析链路：{question[:80]}",
            stage="workflow",
            status="active",
            payload={
                "dataset_id": self.dataset_id,
                "question": question,
                "execution_mode": execution_mode,
                "role_order": [role.value for role in END_TO_END_ROLE_ORDER],
            },
        )

        def run_role(role: AgentRole, runner: Any) -> AgentResult:
            task = task_by_role[role]
            before_tool_count = len(state.tool_call_trace)
            emit_monitor_event(
                monitor_run_id,
                "agent_started",
                title=f"{role.value} 开始",
                summary=f"{role.value} 正在处理输入并准备交给下一环节。",
                role=role.value,
                stage=role.value,
                status="active",
                payload={"task": _monitor_task_summary(task), "state_before": _monitor_state_summary(state)},
            )
            try:
                result = runner(task)
            except Exception as exc:
                emit_monitor_event(
                    monitor_run_id,
                    "agent_failed",
                    title=f"{role.value} 失败",
                    summary=str(exc),
                    role=role.value,
                    stage=role.value,
                    status="failed",
                    payload={"task": _monitor_task_summary(task), "state_before": _monitor_state_summary(state), "error": str(exc)},
                )
                raise
            new_tool_calls = state.tool_call_trace[before_tool_count:]
            emit_monitor_event(
                monitor_run_id,
                "agent_completed",
                title=f"{role.value} 完成",
                summary=_agent_result_summary(result),
                role=role.value,
                stage=role.value,
                status="completed" if result.success else "failed",
                payload={
                    "task": _monitor_task_summary(task),
                    "result": _monitor_result_summary(result),
                    "new_tool_calls": _compact_tool_calls(new_tool_calls),
                    "state_after": _monitor_state_summary(state),
                },
            )
            return result

        planner_result = run_role(AgentRole.PLANNER, lambda task: self.runtime.run_planner(task, state, guidelines=guidelines))
        task_results.append(planner_result)
        task_results.append(run_role(AgentRole.DATA_ENGINEER, lambda task: self.runtime.run_data_engineer(task, state)))
        task_results.append(run_role(AgentRole.PANDAS_EXECUTOR, lambda task: self.runtime.run_pandas_executor(task, state)))
        task_results.append(run_role(AgentRole.SQL_EXECUTOR, lambda task: self.runtime.run_sql_executor(task, state, execution_mode=execution_mode)))
        verifier_result = run_role(AgentRole.VERIFIER, lambda task: self.runtime.run_verifier(task, state, guidelines=guidelines))
        task_results.append(verifier_result)
        correction_result = run_role(AgentRole.CORRECTION, lambda task: self.runtime.run_correction(task, state, guidelines=guidelines))
        task_results.append(correction_result)
        corrected_logic_form = correction_result.output_payload.get("corrected_logic_form") if isinstance(correction_result.output_payload, dict) else None
        if corrected_logic_form:
            self.runtime.apply_corrected_logic_form(state, corrected_logic_form)
            state.correction_attempts[-1]["rerun_triggered"] = True
            emit_monitor_event(
                monitor_run_id,
                "correction_rerun_started",
                title="修正后重跑",
                summary="Correction Agent 产出了可执行修正，正在重新执行 Pandas / SQL / Verifier。",
                role=AgentRole.CORRECTION.value,
                stage=AgentRole.CORRECTION.value,
                status="active",
                payload={"corrected_logic_form": _compact_logic_form(corrected_logic_form), "state_after_correction": _monitor_state_summary(state)},
            )
            task_results.append(run_role(AgentRole.PANDAS_EXECUTOR, lambda task: self.runtime.run_pandas_executor(task, state)))
            task_results.append(run_role(AgentRole.SQL_EXECUTOR, lambda task: self.runtime.run_sql_executor(task, state, execution_mode=execution_mode)))
            verifier_result = run_role(AgentRole.VERIFIER, lambda task: self.runtime.run_verifier(task, state, guidelines=guidelines))
            task_results.append(verifier_result)
        task_results.append(run_role(AgentRole.INSIGHT, lambda task: self.runtime.run_insight(task, state, guidelines=guidelines)))
        task_results.append(run_role(AgentRole.VISUALIZATION, lambda task: self.runtime.run_visualization(task, state, guidelines=guidelines)))

        response_task = task_by_role[AgentRole.RESPONSE_BUILDER]
        emit_monitor_event(
            monitor_run_id,
            "agent_started",
            title="response_builder 开始",
            summary="Response Builder 正在把已验证结果整理成稳定 API 响应。",
            role=AgentRole.RESPONSE_BUILDER.value,
            stage=AgentRole.RESPONSE_BUILDER.value,
            status="active",
            payload={"task": _monitor_task_summary(response_task), "state_before": _monitor_state_summary(state)},
        )
        response = self.runtime.build_final_response(
            run_id=run_id,
            state=state,
            guidelines=guidelines,
            execution_mode=execution_mode,
            task_results=task_results,
        )
        response_result = AgentResult(
            task_id=response_task.task_id,
            role=response_task.role,
            success=response.success,
            output_payload={"response_version": response.response_version, "run_id": response.run_id, "success": response.success},
            issues=[] if response.success else ["Final response was not successful."],
            confidence=1.0 if response.success else 0.0,
        )
        task_results.append(response_result)
        emit_monitor_event(
            monitor_run_id,
            "agent_completed",
            title="response_builder 完成",
            summary=_agent_result_summary(response_result),
            role=AgentRole.RESPONSE_BUILDER.value,
            stage=AgentRole.RESPONSE_BUILDER.value,
            status="completed" if response_result.success else "failed",
            payload={
                "task": _monitor_task_summary(response_task),
                "result": _monitor_result_summary(response_result),
                "final_response": {
                    "run_id": response.run_id,
                    "success": response.success,
                    "answer_type": response.answer_type,
                },
                "state_after": _monitor_state_summary(state),
            },
        )
        trace = _build_trace(
            run_id=run_id,
            dataset_id=self.dataset_id,
            question=question,
            state=state,
            planner_output=planner_result.output_payload,
            verifier_output=verifier_result.output_payload,
            response=response,
            task_results=task_results,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
        trace.reasoning_trace_view = build_reasoning_trace_view(trace)
        response.reasoning_trace_view = trace.reasoning_trace_view
        trace.process_view_v2 = build_process_view_v2(trace, response)
        response.process_view_v2 = trace.process_view_v2
        state.final_response = response.to_dict()
        state.trace = trace.to_dict()
        emit_monitor_event(
            monitor_run_id,
            "workflow_completed",
            title="工作流完成",
            summary=f"multi-agent 分析完成，run_id={run_id}",
            stage="workflow",
            status="completed" if response.success else "failed",
            payload={
                "run_id": run_id,
                "dataset_id": self.dataset_id,
                "success": response.success,
                "latency_ms": trace.latency_ms,
                "answer_type": response.answer_type,
                "process_view_v2": response.process_view_v2,
            },
        )
        return MultiAgentWorkflowResult(response=response, trace=trace, state=state, task_results=task_results)


def _monitor_state_summary(state: WorkflowState) -> dict[str, Any]:
    """Return a compact handoff summary for live monitor events."""

    logic_form = state.logic_form if isinstance(state.logic_form, dict) else {}
    pandas_result = state.pandas_result if isinstance(state.pandas_result, dict) else {}
    sql_result = state.sql_result if isinstance(state.sql_result, dict) else {}
    verification = state.verification if isinstance(state.verification, dict) else {}
    return {
        "question": state.question,
        "dataset_id": state.dataset_id,
        "source_tables": list(logic_form.get("source_tables") or []),
        "operation": logic_form.get("operation"),
        "table_selection_reason": logic_form.get("table_selection_reason"),
        "join_summary": _compact_join_plan(logic_form.get("join_plan")),
        "has_analysis_plan": bool(state.analysis_plan),
        "pandas": _compact_execution_state(pandas_result),
        "sql": _compact_execution_state(sql_result),
        "verification": {
            "passed": verification.get("passed"),
            "confidence": verification.get("confidence"),
            "issues": list(verification.get("issues") or [])[:8],
        },
        "correction_attempt_count": len(state.correction_attempts),
        "tool_call_count": len(state.tool_call_trace),
        "has_insight": bool(state.insight),
        "has_chart": bool(state.chart),
    }


def _monitor_task_summary(task: Any) -> dict[str, Any]:
    input_payload = task.input_payload if isinstance(task.input_payload, dict) else {}
    context = task.context if isinstance(task.context, dict) else {}
    constraints = task.constraints if isinstance(task.constraints, dict) else {}
    return {
        "role": task.role.value,
        "input_payload": {
            "dataset_id": input_payload.get("dataset_id"),
            "question": input_payload.get("question"),
        },
        "context_summary": {
            "table_count": len(context.get("tables") or []) if isinstance(context.get("tables"), list) else None,
            "primary_table": context.get("primary_table"),
        },
        "constraints": {
            "output_contract": constraints.get("output_contract"),
            "llm_first": constraints.get("llm_first"),
            "no_task_id_optimization": constraints.get("no_task_id_optimization"),
        },
    }


def _monitor_result_summary(result: AgentResult) -> dict[str, Any]:
    return {
        "role": result.role.value,
        "success": result.success,
        "output_payload": _compact_output_payload(result.output_payload),
        "issues": list(result.issues or [])[:5],
        "confidence": result.confidence,
    }


def _compact_output_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    output: dict[str, Any] = {}
    logic_form = payload.get("logic_form") if isinstance(payload.get("logic_form"), dict) else None
    if logic_form:
        output["logic_form"] = _compact_logic_form(logic_form)
    analysis_plan = payload.get("analysis_plan") if isinstance(payload.get("analysis_plan"), dict) else None
    if analysis_plan:
        steps = analysis_plan.get("steps") if isinstance(analysis_plan.get("steps"), list) else []
        output["analysis_plan"] = {
            "step_count": len(steps),
            "steps": [
                step.get("name") or step.get("operation") or step.get("description")
                for step in steps[:4]
                if isinstance(step, dict)
            ],
        }
    if isinstance(payload.get("tables"), list):
        output["tables"] = [
            {
                "table_name": table.get("table_name") or table.get("name"),
                "row_count": table.get("row_count"),
                "column_count": table.get("column_count") or len(table.get("columns") or []),
            }
            for table in payload["tables"][:6]
            if isinstance(table, dict)
        ]
    if isinstance(payload.get("quality_report"), dict):
        output["quality_report"] = {
            "summary": payload["quality_report"].get("summary"),
            "quality_score": payload["quality_report"].get("quality_score"),
        }
    if payload.get("success") is not None or payload.get("backend"):
        output.update(_compact_execution_state(payload))
    if isinstance(payload.get("verification"), dict):
        verification = payload["verification"]
        output["verification"] = {
            "passed": verification.get("passed"),
            "confidence": verification.get("confidence"),
            "issues": list(verification.get("issues") or [])[:5],
            "pandas_sql_consistent": verification.get("pandas_sql_consistent"),
        }
    if payload.get("needs_correction") is not None:
        output["needs_correction"] = payload.get("needs_correction")
    if isinstance(payload.get("corrected_logic_form"), dict):
        output["corrected_logic_form"] = _compact_logic_form(payload["corrected_logic_form"])
    if isinstance(payload.get("insight"), dict):
        insight = payload["insight"]
        output["insight"] = {
            "summary": insight.get("summary"),
            "caveats": list(insight.get("caveats") or [])[:2],
            "suggestions": list(insight.get("suggestions") or insight.get("business_suggestions") or [])[:2],
        }
    if isinstance(payload.get("chart"), dict):
        chart = payload["chart"]
        output["chart"] = {
            "chart_type": chart.get("chart_type"),
            "title": chart.get("title"),
            "x": chart.get("x"),
            "y": chart.get("y"),
            "reason": chart.get("reason"),
        }
    for key in ("response_version", "run_id", "success", "answer_type"):
        if key in payload:
            output[key] = payload.get(key)
    return output


def _compact_logic_form(logic_form: Any) -> dict[str, Any]:
    if not isinstance(logic_form, dict):
        return {}
    return {
        "operation": logic_form.get("operation"),
        "task_type": logic_form.get("task_type"),
        "metric": logic_form.get("metric"),
        "group_by": logic_form.get("group_by"),
        "source_tables": list(logic_form.get("source_tables") or [])[:4],
        "table_selection_reason": logic_form.get("table_selection_reason"),
        "join_summary": _compact_join_plan(logic_form.get("join_plan")),
        "parameters": _compact_parameters(logic_form.get("parameters")),
    }


def _compact_parameters(parameters: Any) -> dict[str, Any]:
    if not isinstance(parameters, dict):
        return {}
    allowed = ("metric", "dimension", "aggregation", "limit", "time_field", "current_period", "previous_period")
    return {key: parameters.get(key) for key in allowed if key in parameters}


def _compact_join_plan(join_plan: Any) -> dict[str, Any]:
    if not isinstance(join_plan, dict):
        return {}
    return {
        "trusted": join_plan.get("trusted"),
        "left_table": join_plan.get("left_table"),
        "right_table": join_plan.get("right_table"),
        "join_type": join_plan.get("join_type"),
        "reason": join_plan.get("reason"),
    }


def _compact_tool_calls(tool_calls: list[Any]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for call in tool_calls[:8]:
        if not isinstance(call, dict):
            continue
        arguments = call.get("arguments_summary") if isinstance(call.get("arguments_summary"), dict) else {}
        result = call.get("result_summary") if isinstance(call.get("result_summary"), dict) else {}
        compact.append(
            {
                "requested_by": call.get("requested_by"),
                "tool_name": call.get("tool_name"),
                "success": call.get("success"),
                "latency_ms": call.get("latency_ms"),
                "argument_keys": list(arguments)[:8],
                "result_keys": list(result)[:8],
            }
        )
    return compact


def _compact_execution_state(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    return {
        "success": payload.get("success"),
        "backend": payload.get("backend"),
        "skipped": payload.get("skipped"),
        "reason": payload.get("reason"),
        "columns": list(payload.get("columns") or [])[:12],
        "row_count": len(payload.get("rows") or []) if isinstance(payload.get("rows"), list) else None,
        "value": payload.get("value"),
        "errors": list(payload.get("errors") or [])[:5],
    }


def _agent_result_summary(result: AgentResult) -> str:
    if result.success:
        return f"{result.role.value} 已完成，confidence={result.confidence:.2f}。"
    issues = "; ".join(str(issue) for issue in result.issues[:3])
    return f"{result.role.value} 未通过：{issues or '无详细错误'}"


def _build_trace(
    *,
    run_id: str,
    dataset_id: str,
    question: str,
    state: WorkflowState,
    planner_output: dict[str, Any],
    verifier_output: dict[str, Any],
    response: FinalResponse,
    task_results: list[AgentResult],
    latency_ms: float,
) -> RunTrace:
    return RunTrace(
        run_id=run_id,
        dataset_id=dataset_id,
        question=question,
        intent_summary=planner_output.get("intent_parser"),
        column_mapping_summary=planner_output.get("column_mapping"),
        analysis_planner_summary=planner_output.get("analysis_planner"),
        llm_plan_summary=planner_output.get("analysis_planner"),
        logic_form=state.logic_form,
        metric_definition=None if not isinstance(state.logic_form, dict) else state.logic_form.get("metric_definition"),
        numerator=None if not isinstance(state.logic_form, dict) else state.logic_form.get("numerator"),
        denominator=None if not isinstance(state.logic_form, dict) else state.logic_form.get("denominator"),
        entity_grain=None if not isinstance(state.logic_form, dict) else state.logic_form.get("entity_grain"),
        time_window=None if not isinstance(state.logic_form, dict) else state.logic_form.get("time_window"),
        candidate_set=None if not isinstance(state.logic_form, dict) else state.logic_form.get("candidate_set"),
        source_tables=[] if not isinstance(state.logic_form, dict) else list(state.logic_form.get("source_tables") or []),
        table_selection_reason="" if not isinstance(state.logic_form, dict) else str(state.logic_form.get("table_selection_reason") or ""),
        join_plan=None if not isinstance(state.logic_form, dict) else state.logic_form.get("join_plan"),
        join_execution_summary=_join_execution_summary(state.pandas_result),
        output_contract=None if not isinstance(state.logic_form, dict) else state.logic_form.get("output_contract"),
        analysis_plan=state.analysis_plan,
        pandas_result_summary=_execution_summary(state.pandas_result),
        sql_result_summary=_execution_summary(state.sql_result),
        result_normalizer_summary={
            "pandas_value": None if not isinstance(state.pandas_result, dict) else state.pandas_result.get("value"),
            "sql_value": None if not isinstance(state.sql_result, dict) else state.sql_result.get("value"),
        },
        verification_result=state.verification,
        verifier_critic_summary=verifier_output.get("verifier_critic"),
        semantic_verification_notes=[] if not isinstance(state.verification, dict) else list(state.verification.get("semantic_verification_notes") or []),
        not_applicable_attribution=response.debug.get("not_applicable_attribution"),
        correction_plan_summary=state.correction_attempts[-1] if state.correction_attempts else None,
        correction_attempts=state.correction_attempts,
        candidate_table_summary=_candidate_table_summary(state.pandas_result),
        selected_candidate=_selected_candidate(state.pandas_result),
        tool_call_summary=state.tool_call_trace,
        insight_summary=state.insight,
        chart_plan_summary=state.chart,
        quality_report=response.quality_report,
        final_response={
            "answer": response.answer,
            "success": response.success,
            "agent_mode": "multi_agent",
            "output_contract_passed": response.debug.get("output_contract_validation", {}).get("passed"),
        },
        latency_ms=latency_ms,
        errors=response.errors,
        warnings=response.warnings,
    )


def _execution_summary(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    return {
        "success": payload.get("success"),
        "backend": payload.get("backend"),
        "value": payload.get("value"),
        "skipped": payload.get("skipped"),
        "reason": payload.get("reason"),
        "sql_support": payload.get("sql_support"),
        "capability_family": payload.get("capability_family"),
        "coverage_gap": payload.get("coverage_gap"),
        "native_sql_supported": payload.get("native_sql_supported"),
    }


def _join_execution_summary(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return None
    debug = payload.get("debug")
    if not isinstance(debug, dict):
        return None
    return debug.get("join_execution_summary")


def _primary_table_name(tables: dict[str, Any]) -> str:
    if not tables:
        raise ValueError("At least one table is required for uploaded multi-agent workflow.")
    return max(tables.items(), key=lambda item: (len(item[1]), len(item[1].columns)))[0]


def _candidate_table_summary(payload: Any) -> Any:
    value = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(value, dict):
        return None
    table = value.get("candidate_table")
    if not isinstance(table, list):
        return None
    return {"row_count": len(table), "rows": table[:10]}


def _selected_candidate(payload: Any) -> Any:
    value = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(value, dict):
        return None
    return {"selected": value.get("selected"), "selected_option": value.get("selected_option"), "answer": value.get("answer")}
