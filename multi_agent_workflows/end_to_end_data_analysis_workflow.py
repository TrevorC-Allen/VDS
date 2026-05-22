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
from data_agent_core.core.file_parser import load_dabstep_context
from data_agent_core.llm.client import LLMClient
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
        return cls(dataset_id=dataset_id, context=context, dataset_profile=dataset_profile, llm_client=llm_client)

    def analyze(self, question: str, guidelines: str = "", execution_mode: str = "auto") -> tuple[FinalResponse, RunTrace]:
        """Run the canonical Phase 6 role sequence and return stable outputs."""

        result = self.run(question=question, guidelines=guidelines, execution_mode=execution_mode)
        return result.response, result.trace

    def run(self, question: str, guidelines: str = "", execution_mode: str = "auto") -> MultiAgentWorkflowResult:
        """Run all internal AgentRole steps."""

        start = time.perf_counter()
        run_id = "run_" + uuid.uuid4().hex[:16]
        state = build_initial_state(self.dataset_id, question)
        task_results: list[AgentResult] = []
        task_by_role = {task.role: task for task in build_end_to_end_tasks(self.dataset_id, question)}

        planner_result = self.runtime.run_planner(task_by_role[AgentRole.PLANNER], state, guidelines=guidelines)
        task_results.append(planner_result)
        task_results.append(self.runtime.run_data_engineer(task_by_role[AgentRole.DATA_ENGINEER], state))
        task_results.append(self.runtime.run_pandas_executor(task_by_role[AgentRole.PANDAS_EXECUTOR], state))
        task_results.append(self.runtime.run_sql_executor(task_by_role[AgentRole.SQL_EXECUTOR], state, execution_mode=execution_mode))
        verifier_result = self.runtime.run_verifier(task_by_role[AgentRole.VERIFIER], state, guidelines=guidelines)
        task_results.append(verifier_result)
        correction_result = self.runtime.run_correction(task_by_role[AgentRole.CORRECTION], state, guidelines=guidelines)
        task_results.append(correction_result)
        corrected_logic_form = correction_result.output_payload.get("corrected_logic_form") if isinstance(correction_result.output_payload, dict) else None
        if corrected_logic_form:
            self.runtime.apply_corrected_logic_form(state, corrected_logic_form)
            state.correction_attempts[-1]["rerun_triggered"] = True
            task_results.append(self.runtime.run_pandas_executor(task_by_role[AgentRole.PANDAS_EXECUTOR], state))
            task_results.append(self.runtime.run_sql_executor(task_by_role[AgentRole.SQL_EXECUTOR], state, execution_mode=execution_mode))
            verifier_result = self.runtime.run_verifier(task_by_role[AgentRole.VERIFIER], state, guidelines=guidelines)
            task_results.append(verifier_result)
        task_results.append(self.runtime.run_insight(task_by_role[AgentRole.INSIGHT], state, guidelines=guidelines))
        task_results.append(self.runtime.run_visualization(task_by_role[AgentRole.VISUALIZATION], state, guidelines=guidelines))

        response_task = task_by_role[AgentRole.RESPONSE_BUILDER]
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
        state.trace = trace.to_dict()
        return MultiAgentWorkflowResult(response=response, trace=trace, state=state, task_results=task_results)


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
        final_response={"answer": response.answer, "success": response.success, "agent_mode": "multi_agent"},
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
    }


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
