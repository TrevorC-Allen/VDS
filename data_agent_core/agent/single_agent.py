"""Framework-neutral single Agent orchestration for the MVP phase."""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
import re
from typing import Any

from data_agent_core.contracts.analysis_contracts import UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.response_contracts import ChartSpec, FinalResponse, InsightResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.capability_registry import coverage_summary_for_logic_form
from data_agent_core.core.data_quality import build_data_quality_report, report_to_dict
from data_agent_core.core.file_parser import load_dabstep_context
from data_agent_core.core.intent_parser import parse_generic_table_question, parse_question
from data_agent_core.core.planner_guardrails import available_columns_by_table_from_context, validate_logic_form_with_guardrails
from data_agent_core.core.semantic_contract import (
    build_canonical_semantic_contract,
    build_lightweight_schema_semantic_profile,
    semantic_contract_payload,
)
from data_agent_core.executors import pandas_executor, sql_executor
from data_agent_core.llm.client import LLMClient, load_llm_client_from_env
from data_agent_core.llm.planner import LLMPlanResult, LLMStageResult, complete_stage_with_llm, plan_with_llm
from data_agent_core.output.activity_trace import build_activity_trace_v2
from data_agent_core.output.chart_planner import build_chart_spec
from data_agent_core.output.chart_renderer import attach_rendered_chart
from data_agent_core.output.insight_generator import generate_insight
from data_agent_core.output.process_narrative import build_process_view_v2
from data_agent_core.output.reasoning_trace_view import build_reasoning_trace_view
from data_agent_core.output.response_builder import build_response, classify_not_applicable
from data_agent_core.task_contract_builder import apply_referent_contract_from_guidelines
from data_agent_core.tracing.run_trace import RunTrace
from data_agent_core.verifier.result_comparator import compare_results
from data_agent_core.verifier.result_normalizer import normalize_value
from data_agent_core.verifier.rule_checker import verify_execution


SINGLE_AGENT_CHAIN = [
    "llm_intent_parser",
    "llm_rules_column_mapping",
    "llm_analysis_planner",
    "code_pandas_executor",
    "code_sql_duckdb_executor",
    "code_result_normalizer",
    "rules_llm_verifier_critic",
    "rules_llm_correction_planner",
    "llm_insight_generator",
    "llm_rules_chart_planner",
    "backend_json_response",
]


class DataAnalysisAgent:
    """Single framework-neutral agent for core algorithm testing."""

    def __init__(
        self,
        context_dir: str | Path,
        dataset_id: str = "dabstep_context",
        llm_client: LLMClient | None = None,
    ) -> None:
        self.context_dir = Path(context_dir)
        self.dataset_id = dataset_id
        self.context = load_dabstep_context(self.context_dir)
        self.llm_client = llm_client or load_llm_client_from_env()

    def analyze(self, question: str, guidelines: str = "", execution_mode: str = "auto") -> tuple[FinalResponse, RunTrace]:
        """Analyze one question using structured plan, execution, verification, and response contracts."""

        start = time.perf_counter()
        run_id = "run_" + uuid.uuid4().hex[:16]
        context_summary = self._context_summary()
        user_question = UserQuestion(
            dataset_id=self.dataset_id,
            question=question,
            execution_mode=execution_mode,
            guidelines=guidelines,
        )
        llm_intent = self._llm_intent_stage(question, guidelines, context_summary)
        guardrail_logic_form = parse_question(question, guidelines, self.context)
        column_mapping = self._rule_column_mapping(guardrail_logic_form)
        llm_column_mapping = self._llm_column_mapping_stage(
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            llm_intent=llm_intent,
            rule_column_mapping=column_mapping,
        )
        llm_plan = self._safe_plan_with_llm(
            question=question,
            guidelines=guidelines,
            context_summary=context_summary | {"rule_column_mapping": column_mapping},
            guardrail_logic_form=guardrail_logic_form,
        )
        logic_form = self._validated_logic_form(llm_plan.logic_form, guardrail_logic_form)
        logic_form = apply_referent_contract_from_guidelines(logic_form, guidelines)
        schema_semantics = build_lightweight_schema_semantic_profile(self.context, self.dataset_profile if hasattr(self, "dataset_profile") else None)
        semantic_contract = build_canonical_semantic_contract(
            question=question,
            route="single_agent",
            selected_logic_form=logic_form,
            deterministic_logic_form=guardrail_logic_form,
            llm_logic_form=llm_plan.logic_form,
            llm_intent=llm_intent.raw,
            llm_plan=llm_plan.raw,
            schema_profile=schema_semantics,
            column_mapping=column_mapping,
        )
        plan = build_analysis_plan(logic_form, question=question, semantic_contract=semantic_contract)
        logic_form = plan.logic_form
        pandas_result = pandas_executor.execute_plan(plan, self.context)
        not_applicable_attribution = classify_not_applicable(pandas_result.value, plan)
        sql_result = None
        comparison = None
        sql_coverage = coverage_summary_for_logic_form(
            logic_form,
            available_columns=self._available_columns_for_logic_form(logic_form),
        )
        if execution_mode in {"auto", "dual", "sql"} and sql_coverage["native_sql_supported"]:
            sql_result = sql_executor.execute_plan(plan, self.context)
            comparison = compare_results(pandas_result, sql_result)
        normalizer_summary = self._result_normalizer_summary(pandas_result, sql_result, comparison)
        verification = verify_execution(pandas_result, comparison, plan=plan, user_question=user_question)
        llm_verifier_critic = self._llm_verifier_critic_stage(
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            plan=plan,
            pandas_result=pandas_result,
            sql_result=sql_result,
            verification=verification,
        )
        llm_correction_plan = self._llm_correction_stage(
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            verification=verification,
            verifier_critic=llm_verifier_critic,
        )
        formatted_answer = str(pandas_result.value)
        llm_insight = self._llm_insight_stage(
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            answer=formatted_answer,
            verification=verification,
        )
        rule_chart = self._rule_chart_spec(plan, pandas_result, verification.passed)
        llm_chart = self._llm_chart_stage(
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            plan=plan,
            rule_chart=rule_chart,
            verification=verification,
        )
        quality_report = self._quality_report_payload()
        stage_summaries = {
            "intent_parser": self._stage_summary(llm_intent),
            "column_mapping": self._stage_summary(llm_column_mapping),
            "analysis_planner": {
                "stage_name": "analysis_planner",
                "confidence": llm_plan.confidence,
                "reasoning_summary": self._short_text(llm_plan.reasoning_summary),
                "llm_operation": llm_plan.logic_form.operation,
                "selected_operation": logic_form.operation,
                "guardrail_applied": llm_plan.logic_form.operation != logic_form.operation,
            },
            "verifier_critic": self._stage_summary(llm_verifier_critic),
            "correction_planner": self._stage_summary(llm_correction_plan),
            "insight_generator": self._stage_summary(llm_insight),
            "chart_planner": self._stage_summary(llm_chart),
        }
        response = build_response(
            run_id=run_id,
            user_question=user_question,
            plan=plan,
            execution_result=pandas_result,
            verification=verification,
            debug={
                "pandas_success": pandas_result.success,
                "sql_success": None if sql_result is None else sql_result.success,
                "operation": logic_form.operation,
                "source_tables": list(logic_form.source_tables),
                "table_selection_reason": logic_form.table_selection_reason,
                "join_plan": logic_form.join_plan,
                "join_execution_summary": pandas_result.debug.get("join_execution_summary") if isinstance(pandas_result.debug, dict) else None,
                "capability": sql_coverage,
                "llm_used": True,
                "llm_operation": llm_plan.logic_form.operation,
                "llm_confidence": llm_plan.confidence,
                "single_agent_chain": SINGLE_AGENT_CHAIN,
                "llm_stage_summaries": stage_summaries,
                "column_mapping": column_mapping,
                "semantic_contract": semantic_contract_payload(plan.semantic_contract),
            },
            quality_report=quality_report,
        )
        response.insight = self._insight_from_stage(
            response.answer,
            verification.passed,
            llm_insight,
            question=question,
            plan=plan,
            execution_result=pandas_result,
            quality_report=quality_report,
        )
        response.chart = self._chart_from_stage(rule_chart, llm_chart, verification.passed)
        trace = RunTrace(
            run_id=run_id,
            dataset_id=self.dataset_id,
            question=question,
            intent_summary=stage_summaries["intent_parser"],
            column_mapping_summary={
                "rule_mapping": column_mapping,
                "llm_summary": stage_summaries["column_mapping"],
            },
            analysis_planner_summary=stage_summaries["analysis_planner"],
            logic_form=response.logic_form,
            metric_definition=logic_form.metric_definition,
            numerator=logic_form.numerator,
            denominator=logic_form.denominator,
            entity_grain=logic_form.entity_grain,
            time_window=logic_form.time_window,
            candidate_set=logic_form.candidate_set,
            source_tables=list(logic_form.source_tables),
            table_selection_reason=logic_form.table_selection_reason,
            join_plan=logic_form.join_plan,
            join_execution_summary=pandas_result.debug.get("join_execution_summary") if isinstance(pandas_result.debug, dict) else None,
            output_contract=logic_form.output_contract,
            analysis_plan={"plan_id": plan.plan_id, "steps": plan.steps},
            semantic_contract=semantic_contract_payload(plan.semantic_contract),
            llm_plan_summary={
                "llm_operation": llm_plan.logic_form.operation,
                "selected_operation": logic_form.operation,
                "guardrail_applied": llm_plan.logic_form.operation != logic_form.operation,
                "confidence": llm_plan.confidence,
                "reasoning_summary": self._short_text(llm_plan.reasoning_summary),
            },
            pandas_result_summary={"success": pandas_result.success, "value": pandas_result.value},
            sql_result_summary=_sql_trace_summary(sql_result, sql_coverage, execution_mode),
            result_normalizer_summary=normalizer_summary,
            verification_result=response.verification,
            verifier_critic_summary=stage_summaries["verifier_critic"],
            not_applicable_attribution=response.debug.get("not_applicable_attribution") or not_applicable_attribution,
            correction_plan_summary=stage_summaries["correction_planner"],
            final_response={
                "answer": response.answer,
                "success": response.success,
                "output_contract_passed": response.debug.get("output_contract_validation", {}).get("passed"),
            },
            insight_summary=stage_summaries["insight_generator"],
            chart_plan_summary=stage_summaries["chart_planner"],
            quality_report=quality_report,
            latency_ms=(time.perf_counter() - start) * 1000,
            errors=response.errors,
            warnings=response.warnings,
        )
        trace.reasoning_trace_view = build_reasoning_trace_view(trace)
        response.reasoning_trace_view = trace.reasoning_trace_view
        trace.process_view_v2 = build_process_view_v2(trace, response)
        response.process_view_v2 = trace.process_view_v2
        response.activity_trace_v2 = build_activity_trace_v2(trace, response)
        return response, trace

    def _context_summary(self) -> dict[str, Any]:
        payments = self.context["payments"]
        merchants = self.context.get("merchant_data") or []
        return {
            "tables": {
                "payments": {
                    "columns": list(payments.columns),
                    "row_count": int(len(payments)),
                }
            },
            "knowledge_files": ["manual.md", "fees.json", "merchant_data.json"],
            "merchant_names": [row["merchant"] for row in merchants if isinstance(row, dict) and "merchant" in row],
        }

    def _available_columns_for_logic_form(self, logic_form: Any) -> list[str] | None:
        params = getattr(logic_form, "parameters", {}) or {}
        table_name = str(params.get("table") or self.context.get("primary_table") or "payments")
        if table_name == "payments" and "payments" in self.context:
            return [str(column) for column in self.context["payments"].columns]
        tables = self.context.get("tables")
        if isinstance(tables, dict) and table_name in tables:
            return [str(column) for column in tables[table_name].columns]
        if isinstance(tables, dict) and tables:
            table = next(iter(tables.values()))
            return [str(column) for column in table.columns]
        return None

    def _llm_intent_stage(
        self,
        question: str,
        guidelines: str,
        context_summary: dict[str, Any],
    ) -> LLMStageResult:
        return self._safe_complete_stage_with_llm(
            stage_name="intent_parser",
            stage_goal="Convert the user's natural-language data question into a structured intent draft.",
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            payload={"input_contract": "UserQuestion"},
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

    def _llm_column_mapping_stage(
        self,
        *,
        question: str,
        guidelines: str,
        context_summary: dict[str, Any],
        llm_intent: LLMStageResult,
        rule_column_mapping: dict[str, Any],
    ) -> LLMStageResult:
        return self._safe_complete_stage_with_llm(
            stage_name="column_mapping",
            stage_goal="Map intent fields to uploaded dataset columns and rule-knowledge fields using LLM semantics plus rule guardrails.",
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            payload={
                "llm_intent_summary": self._stage_summary(llm_intent),
                "rule_column_mapping": rule_column_mapping,
            },
            required_output={
                "mapped_columns": "object",
                "unmapped_terms": "array",
                "warnings": "array",
                "confidence": "number between 0 and 1",
                "reasoning_summary": "short summary, not chain of thought",
            },
        )

    def _llm_verifier_critic_stage(
        self,
        *,
        question: str,
        guidelines: str,
        context_summary: dict[str, Any],
        plan: Any,
        pandas_result: Any,
        sql_result: Any,
        verification: Any,
    ) -> LLMStageResult:
        return self._safe_complete_stage_with_llm(
            stage_name="verifier_critic",
            stage_goal="Critique the rule-based verification notes and flag unsupported or suspicious conclusions without changing execution results.",
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            payload={
                "analysis_plan": self._to_jsonable(plan),
                "pandas_result_summary": {"success": pandas_result.success, "value": pandas_result.value},
                "sql_result_summary": None if sql_result is None else {"success": sql_result.success, "value": sql_result.value},
                "rule_verification": self._to_jsonable(verification),
            },
            required_output={
                "passed": "boolean",
                "issues": "array",
                "verification_notes": "array",
                "confidence": "number between 0 and 1",
                "reasoning_summary": "short summary, not chain of thought",
            },
        )

    def _llm_correction_stage(
        self,
        *,
        question: str,
        guidelines: str,
        context_summary: dict[str, Any],
        verification: Any,
        verifier_critic: LLMStageResult,
    ) -> LLMStageResult:
        return self._safe_complete_stage_with_llm(
            stage_name="correction_planner",
            stage_goal="Plan bounded correction directions when verification fails; do not execute code and do not fabricate a final answer.",
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            payload={
                "rule_verification": self._to_jsonable(verification),
                "verifier_critic_summary": self._stage_summary(verifier_critic),
                "max_attempts": 2,
            },
            required_output={
                "needs_correction": "boolean",
                "correction_targets": "array",
                "max_attempts": 2,
                "confidence": "number between 0 and 1",
                "reasoning_summary": "short summary, not chain of thought",
            },
        )

    def _llm_insight_stage(
        self,
        *,
        question: str,
        guidelines: str,
        context_summary: dict[str, Any],
        answer: str,
        verification: Any,
    ) -> LLMStageResult:
        return self._safe_complete_stage_with_llm(
            stage_name="insight_generator",
            stage_goal="Generate concise insight only from verified data results; if verification failed, state that no trusted insight should be generated.",
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            payload={
                "trusted_result": bool(verification.passed),
                "answer": answer,
                "verification": self._to_jsonable(verification),
            },
            required_output={
                "summary": "short answer-grounded insight",
                "suggestions": "array",
                "caveats": "array",
                "confidence": "number between 0 and 1",
                "reasoning_summary": "short summary, not chain of thought",
            },
        )

    def _llm_chart_stage(
        self,
        *,
        question: str,
        guidelines: str,
        context_summary: dict[str, Any],
        plan: Any,
        rule_chart: ChartSpec,
        verification: Any,
    ) -> LLMStageResult:
        return self._safe_complete_stage_with_llm(
            stage_name="chart_planner",
            stage_goal="Select a frontend-neutral chart spec using LLM semantics and rule-based chart constraints.",
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            payload={
                "analysis_plan": self._to_jsonable(plan),
                "rule_chart": self._to_jsonable(rule_chart),
                "trusted_result": bool(verification.passed),
            },
            required_output={
                "chart_type": "bar | horizontal_bar | line | combo_column_line | pie | donut | histogram | box | scatter | none",
                "x": "field name or null",
                "y": "field name or null",
                "title": "string or null",
                "reason": "short summary, not chain of thought",
                "confidence": "number between 0 and 1",
                "reasoning_summary": "short summary, not chain of thought",
            },
        )

    def _safe_complete_stage_with_llm(self, **kwargs: Any) -> LLMStageResult:
        try:
            return complete_stage_with_llm(llm_client=self.llm_client, **kwargs)
        except Exception as exc:  # noqa: BLE001 - provider failures must not block rule-backed execution.
            return self._fallback_stage_result(str(kwargs.get("stage_name") or "llm_stage"), exc)

    def _safe_plan_with_llm(
        self,
        *,
        question: str,
        guidelines: str,
        context_summary: dict[str, Any],
        guardrail_logic_form: Any,
    ) -> LLMPlanResult:
        try:
            return plan_with_llm(
                llm_client=self.llm_client,
                question=question,
                guidelines=guidelines,
                context_summary=context_summary,
            )
        except Exception as exc:  # noqa: BLE001 - fall back to deterministic parser when provider is unavailable.
            return LLMPlanResult(
                logic_form=guardrail_logic_form,
                raw=self._fallback_stage_result("analysis_planner", exc).raw,
                confidence=0.0,
                reasoning_summary=f"LLM planner unavailable; used deterministic guardrail plan ({type(exc).__name__}).",
            )

    def _fallback_stage_result(self, stage_name: str, exc: Exception) -> LLMStageResult:
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

    def _validated_logic_form(self, llm_logic_form: Any, guardrail_logic_form: Any) -> Any:
        """Use LLM planning with deterministic schema guardrails."""

        return validate_logic_form_with_guardrails(
            llm_logic_form,
            guardrail_logic_form,
            available_columns_by_table=available_columns_by_table_from_context(self.context),
        )

    def _rule_column_mapping(self, logic_form: Any) -> dict[str, Any]:
        payments = self.context["payments"]
        available_columns = list(payments.columns)
        available = set(available_columns)
        mapped_columns: dict[str, str] = {}
        for key, value in logic_form.parameters.items():
            if isinstance(value, str) and value in available:
                mapped_columns[key] = value
        for key in logic_form.filters:
            if key in available:
                mapped_columns[key] = key
        return {
            "table": "payments",
            "available_columns": available_columns,
            "mapped_columns": mapped_columns,
            "knowledge_fields": ["manual.md", "fees.json", "merchant_data.json"],
            "unmapped_terms": [],
        }

    def _result_normalizer_summary(self, pandas_result: Any, sql_result: Any, comparison: Any) -> dict[str, Any]:
        return {
            "pandas_value": normalize_value(pandas_result.value),
            "sql_value": None if sql_result is None else normalize_value(sql_result.value),
            "comparison_consistent": None if comparison is None else comparison.consistent,
        }

    def _rule_chart_spec(self, plan: Any, execution_result: Any, trusted: bool) -> ChartSpec:
        return build_chart_spec(plan=plan, execution_result=execution_result, verification_passed=trusted)

    def _insight_from_stage(
        self,
        answer: Any,
        trusted: bool,
        stage: LLMStageResult,
        *,
        question: str = "",
        plan: Any = None,
        execution_result: Any = None,
        quality_report: dict[str, Any] | None = None,
    ) -> InsightResult:
        if not trusted:
            return InsightResult(caveats=["No insight generated because verification did not pass."])
        base = (
            generate_insight(
                question=question,
                plan=plan,
                execution_result=execution_result,
                verification_passed=trusted,
                quality_report=quality_report,
            )
            if execution_result is not None
            else InsightResult(summary=str(answer or ""))
        )
        raw = stage.raw
        suggestions = _filter_chinese_user_facing_list(raw.get("suggestions") if isinstance(raw.get("suggestions"), list) else [])
        caveats = _filter_chinese_user_facing_list(raw.get("caveats") if isinstance(raw.get("caveats"), list) else [])
        raw_summary = str(raw.get("summary") or "")
        summary = str(base.summary or answer or "")
        if _is_chinese_user_facing_text(raw_summary) and not _under_covers_multi_series_trend(raw_summary, execution_result):
            summary = raw_summary
        existing_caveats = list(base.caveats)
        for caveat in caveats:
            if caveat not in existing_caveats:
                existing_caveats.append(caveat)
        return InsightResult(
            summary=summary,
            key_numbers=base.key_numbers,
            anomaly_findings=base.anomaly_findings,
            volatility_findings=base.volatility_findings,
            suggestions=(base.suggestions if base.suggestions else suggestions)[:1],
            business_suggestions=(base.business_suggestions if base.business_suggestions else suggestions)[:1],
            caveats=existing_caveats,
            next_questions=base.next_questions,
            next_actions=base.next_actions,
            evidence_rows=base.evidence_rows,
            confidence=max(base.confidence, stage.confidence),
        )

    def _chart_from_stage(self, rule_chart: ChartSpec, stage: LLMStageResult, trusted: bool) -> ChartSpec:
        if not trusted:
            return rule_chart
        if not rule_chart.chart_type or rule_chart.fallback_reason in {"detail_rows_prefer_table", "unsafe_metric_column"}:
            return rule_chart
        raw = stage.raw
        chart_type = raw.get("chart_type")
        if _should_preserve_rule_chart(rule_chart, chart_type):
            return attach_rendered_chart(rule_chart)
        if chart_type and chart_type != "none" and not _unsafe_chart_metric(str(raw.get("y") or "")):
            x = raw.get("x") or rule_chart.x
            y = raw.get("y") or rule_chart.y
            if not _chart_fields_match_data(rule_chart.data, str(x or ""), str(y or ""), str(chart_type)):
                return attach_rendered_chart(rule_chart)
            return attach_rendered_chart(
                ChartSpec(
                    chart_type=str(chart_type),
                    x=x,
                    y=y,
                    title=raw.get("title") or rule_chart.title,
                    data=rule_chart.data,
                    reason=str(raw.get("reason") or raw.get("reasoning_summary") or rule_chart.reason),
                    encoding=rule_chart.encoding,
                    series=rule_chart.series,
                    confidence=max(rule_chart.confidence, stage.confidence),
                    selection_reason=rule_chart.selection_reason,
                    fallback_reason=rule_chart.fallback_reason,
                )
            )
        return attach_rendered_chart(rule_chart)

    def _quality_report_payload(self) -> dict[str, Any] | None:
        tables = self.context.get("tables") if isinstance(self.context, dict) else None
        if isinstance(tables, dict):
            return report_to_dict(build_data_quality_report(tables, generated_from="analysis_runtime"))
        return None

    def _stage_summary(self, stage: LLMStageResult) -> dict[str, Any]:
        return {
            "stage_name": stage.stage_name,
            "confidence": stage.confidence,
            "reasoning_summary": self._short_text(stage.reasoning_summary),
            "output": self._safe_stage_output(stage.raw),
        }

    def _safe_stage_output(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            key: self._short_text(value) if isinstance(value, str) else value
            for key, value in raw.items()
            if key not in {"chain_of_thought", "cot", "hidden_reasoning", "full_reasoning"}
        }

    def _to_jsonable(self, value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        return value

    def _short_text(self, value: Any, limit: int = 500) -> str:
        text = str(value or "")
        return text if len(text) <= limit else text[:limit] + "..."


class UploadedDatasetAgent(DataAnalysisAgent):
    """Single-agent workflow for user-uploaded CSV / Excel tables."""

    def __init__(
        self,
        tables: dict[str, Any],
        dataset_id: str,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.context_dir = Path(".")
        self.dataset_id = dataset_id
        self.context = {"tables": tables, "primary_table": self._primary_table_name(tables)}
        self.llm_client = llm_client or load_llm_client_from_env()

    def analyze(self, question: str, guidelines: str = "", execution_mode: str = "auto") -> tuple[FinalResponse, RunTrace]:
        """Analyze a question over uploaded tables using the standard chain."""

        start = time.perf_counter()
        run_id = "run_" + uuid.uuid4().hex[:16]
        context_summary = self._context_summary()
        user_question = UserQuestion(
            dataset_id=self.dataset_id,
            question=question,
            execution_mode=execution_mode,
            guidelines=guidelines,
        )
        llm_intent = self._llm_intent_stage(question, guidelines, context_summary)
        guardrail_logic_form = parse_generic_table_question(question, self.context["tables"], guidelines)
        column_mapping = self._rule_column_mapping(guardrail_logic_form)
        llm_column_mapping = self._llm_column_mapping_stage(
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            llm_intent=llm_intent,
            rule_column_mapping=column_mapping,
        )
        llm_plan = self._safe_plan_with_llm(
            question=question,
            guidelines=guidelines,
            context_summary=context_summary | {"rule_column_mapping": column_mapping},
            guardrail_logic_form=guardrail_logic_form,
        )
        logic_form = self._validated_logic_form(llm_plan.logic_form, guardrail_logic_form)
        logic_form = apply_referent_contract_from_guidelines(logic_form, guidelines)
        schema_semantics = build_lightweight_schema_semantic_profile(self.context, None)
        semantic_contract = build_canonical_semantic_contract(
            question=question,
            route="single_agent_generic",
            selected_logic_form=logic_form,
            deterministic_logic_form=guardrail_logic_form,
            llm_logic_form=llm_plan.logic_form,
            llm_intent=llm_intent.raw,
            llm_plan=llm_plan.raw,
            schema_profile=schema_semantics,
            column_mapping=column_mapping,
        )
        plan = build_analysis_plan(logic_form, question=question, semantic_contract=semantic_contract)
        logic_form = plan.logic_form
        pandas_result = pandas_executor.execute_plan(plan, self.context)
        not_applicable_attribution = classify_not_applicable(pandas_result.value, plan)
        sql_result = None
        comparison = None
        sql_coverage = coverage_summary_for_logic_form(
            logic_form,
            available_columns=self._available_columns_for_logic_form(logic_form),
        )
        if execution_mode in {"auto", "dual", "sql"} and sql_coverage["native_sql_supported"]:
            sql_result = sql_executor.execute_plan(plan, self.context)
            comparison = compare_results(pandas_result, sql_result)
        normalizer_summary = self._result_normalizer_summary(pandas_result, sql_result, comparison)
        verification = verify_execution(pandas_result, comparison, plan=plan, user_question=user_question)
        llm_verifier_critic = self._llm_verifier_critic_stage(
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            plan=plan,
            pandas_result=pandas_result,
            sql_result=sql_result,
            verification=verification,
        )
        llm_correction_plan = self._llm_correction_stage(
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            verification=verification,
            verifier_critic=llm_verifier_critic,
        )
        llm_insight = self._llm_insight_stage(
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            answer=str(pandas_result.value),
            verification=verification,
        )
        rule_chart = self._rule_chart_spec(plan, pandas_result, verification.passed)
        llm_chart = self._llm_chart_stage(
            question=question,
            guidelines=guidelines,
            context_summary=context_summary,
            plan=plan,
            rule_chart=rule_chart,
            verification=verification,
        )
        quality_report = self._quality_report_payload()
        stage_summaries = {
            "intent_parser": self._stage_summary(llm_intent),
            "column_mapping": self._stage_summary(llm_column_mapping),
            "analysis_planner": {
                "stage_name": "analysis_planner",
                "confidence": llm_plan.confidence,
                "reasoning_summary": self._short_text(llm_plan.reasoning_summary),
                "llm_operation": llm_plan.logic_form.operation,
                "selected_operation": logic_form.operation,
                "guardrail_applied": llm_plan.logic_form.operation != logic_form.operation,
            },
            "verifier_critic": self._stage_summary(llm_verifier_critic),
            "correction_planner": self._stage_summary(llm_correction_plan),
            "insight_generator": self._stage_summary(llm_insight),
            "chart_planner": self._stage_summary(llm_chart),
        }
        response = build_response(
            run_id=run_id,
            user_question=user_question,
            plan=plan,
            execution_result=pandas_result,
            verification=verification,
            debug={
                "pandas_success": pandas_result.success,
                "sql_success": None if sql_result is None else sql_result.success,
                "operation": logic_form.operation,
                "source_tables": list(logic_form.source_tables),
                "table_selection_reason": logic_form.table_selection_reason,
                "join_plan": logic_form.join_plan,
                "join_execution_summary": pandas_result.debug.get("join_execution_summary") if isinstance(pandas_result.debug, dict) else None,
                "capability": sql_coverage,
                "llm_used": True,
                "llm_operation": llm_plan.logic_form.operation,
                "llm_confidence": llm_plan.confidence,
                "single_agent_chain": SINGLE_AGENT_CHAIN,
                "llm_stage_summaries": stage_summaries,
                "column_mapping": column_mapping,
                "semantic_contract": semantic_contract_payload(plan.semantic_contract),
            },
            quality_report=quality_report,
        )
        response.insight = self._insight_from_stage(
            response.answer,
            verification.passed,
            llm_insight,
            question=question,
            plan=plan,
            execution_result=pandas_result,
            quality_report=quality_report,
        )
        response.chart = self._chart_from_stage(rule_chart, llm_chart, verification.passed)
        trace = RunTrace(
            run_id=run_id,
            dataset_id=self.dataset_id,
            question=question,
            intent_summary=stage_summaries["intent_parser"],
            column_mapping_summary={"rule_mapping": column_mapping, "llm_summary": stage_summaries["column_mapping"]},
            analysis_planner_summary=stage_summaries["analysis_planner"],
            logic_form=response.logic_form,
            metric_definition=logic_form.metric_definition,
            numerator=logic_form.numerator,
            denominator=logic_form.denominator,
            entity_grain=logic_form.entity_grain,
            time_window=logic_form.time_window,
            candidate_set=logic_form.candidate_set,
            source_tables=list(logic_form.source_tables),
            table_selection_reason=logic_form.table_selection_reason,
            join_plan=logic_form.join_plan,
            join_execution_summary=pandas_result.debug.get("join_execution_summary") if isinstance(pandas_result.debug, dict) else None,
            output_contract=logic_form.output_contract,
            analysis_plan={"plan_id": plan.plan_id, "steps": plan.steps},
            semantic_contract=semantic_contract_payload(plan.semantic_contract),
            llm_plan_summary={
                "llm_operation": llm_plan.logic_form.operation,
                "selected_operation": logic_form.operation,
                "guardrail_applied": llm_plan.logic_form.operation != logic_form.operation,
                "confidence": llm_plan.confidence,
                "reasoning_summary": self._short_text(llm_plan.reasoning_summary),
            },
            pandas_result_summary={"success": pandas_result.success, "value": pandas_result.value},
            sql_result_summary=_sql_trace_summary(sql_result, sql_coverage, execution_mode),
            result_normalizer_summary=normalizer_summary,
            verification_result=response.verification,
            verifier_critic_summary=stage_summaries["verifier_critic"],
            not_applicable_attribution=response.debug.get("not_applicable_attribution") or not_applicable_attribution,
            correction_plan_summary=stage_summaries["correction_planner"],
            insight_summary=stage_summaries["insight_generator"],
            chart_plan_summary=stage_summaries["chart_planner"],
            quality_report=quality_report,
            final_response={
                "answer": response.answer,
                "success": response.success,
                "output_contract_passed": response.debug.get("output_contract_validation", {}).get("passed"),
            },
            latency_ms=(time.perf_counter() - start) * 1000,
            errors=response.errors,
            warnings=response.warnings,
        )
        trace.reasoning_trace_view = build_reasoning_trace_view(trace)
        response.reasoning_trace_view = trace.reasoning_trace_view
        trace.process_view_v2 = build_process_view_v2(trace, response)
        response.process_view_v2 = trace.process_view_v2
        response.activity_trace_v2 = build_activity_trace_v2(trace, response)
        return response, trace

    def _context_summary(self) -> dict[str, Any]:
        return {
            "tables": {
                name: {"columns": list(df.columns), "row_count": int(len(df))}
                for name, df in self.context["tables"].items()
            },
            "knowledge_files": [],
        }

    def _rule_column_mapping(self, logic_form: Any) -> dict[str, Any]:
        tables = self.context["tables"]
        table_name = str(logic_form.parameters.get("table") or self.context["primary_table"])
        df = tables[table_name]
        available_columns = list(df.columns)
        available = set(available_columns)
        mapped_columns: dict[str, str] = {}
        for key, value in logic_form.parameters.items():
            if isinstance(value, str) and value in available:
                mapped_columns[key] = value
        return {
            "table": table_name,
            "available_columns": available_columns,
            "mapped_columns": mapped_columns,
            "knowledge_fields": [],
            "unmapped_terms": [],
        }

    def _primary_table_name(self, tables: dict[str, Any]) -> str:
        if not tables:
            raise ValueError("UploadedDatasetAgent requires at least one table.")
        return max(tables.items(), key=lambda item: (len(item[1]), len(item[1].columns)))[0]


def _sql_trace_summary(sql_result: Any, coverage: dict[str, Any], execution_mode: str) -> dict[str, Any]:
    base = {
        "sql_support": coverage.get("sql_support"),
        "capability_family": coverage.get("capability_family"),
        "coverage_gap": coverage.get("coverage_gap"),
        "native_sql_supported": coverage.get("native_sql_supported"),
    }
    if sql_result is not None:
        return {
            "success": sql_result.success,
            "backend": sql_result.backend,
            "value": sql_result.value,
            "skipped": False,
            **base,
        }
    reason = coverage.get("reason") or "Operation is not covered by the current native SQL path."
    if execution_mode not in {"auto", "dual", "sql"}:
        reason = f"Execution mode {execution_mode} does not request SQL execution."
    return {
        "success": None,
        "backend": None,
        "value": None,
        "skipped": True,
        "reason": reason,
        **base,
    }


def _unsafe_chart_metric(column: str) -> bool:
    lowered = column.lower()
    compact = lowered.replace("_", "").replace("-", "").replace(" ", "")
    if compact in {"id", "ids", "number", "cardnumber"} or compact.endswith("id") or compact.endswith("ids"):
        return True
    return any(token in lowered for token in ("reference", "psp", "bin", "编号", "代码", "流水", "卡号", "year", "hour", "minute", "day_of_year"))


def _filter_chinese_user_facing_list(values: list[Any]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and _is_chinese_user_facing_text(text):
            cleaned.append(text)
    return cleaned


def _is_chinese_user_facing_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if not re.search(r"[\u3400-\u9fff]", value):
        return False
    return not _looks_like_english_prose_leak(value)


def _looks_like_english_prose_leak(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    segments = [
        segment.strip()
        for segment in re.split(r"[；;。！？!?]\s*|(?:观察|风险|边界|依据|建议|下一步)[:：]", value)
        if segment.strip()
    ] or [value]
    return any(_segment_looks_like_english_prose_leak(segment) for segment in segments)


def _segment_looks_like_english_prose_leak(text: str) -> bool:
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", text))
    latin_words = re.findall(r"[A-Za-z][A-Za-z_'-]*", text)
    if not latin_words:
        return False
    prose_tokens = {
        "are",
        "based",
        "by",
        "compare",
        "countries",
        "country",
        "data",
        "followed",
        "full",
        "include",
        "includes",
        "is",
        "leading",
        "next",
        "not",
        "only",
        "present",
        "ranked",
        "ranking",
        "result",
        "results",
        "show",
        "shows",
        "step",
        "the",
        "this",
        "that",
    }
    prose_count = sum(1 for word in latin_words if word.lower().strip("_'") in prose_tokens)
    if cjk_count == 0:
        return prose_count >= 2 or (len(latin_words) >= 5 and prose_count >= 1)
    return prose_count >= 3 and cjk_count < 6


def _chart_fields_match_data(data: list[dict[str, Any]], x: str, y: str, chart_type: str) -> bool:
    if chart_type == "kpi":
        return True
    if not data:
        return False
    sample_keys = set(data[0])
    if not x or not y:
        return False
    return x in sample_keys and y in sample_keys


def _under_covers_multi_series_trend(summary: str, execution_result: Any) -> bool:
    rows = execution_result.rows if isinstance(execution_result, ExecutionResult) else []
    if not rows:
        return False
    columns = list(rows[0].keys())
    time_column = next((column for column in columns if re.search(r"month|date|week|time|月份|日期|周", str(column), re.I)), None)
    if not time_column:
        return False
    series_columns = [
        str(column)
        for column in columns
        if column != time_column and any(_coerce_float(row.get(column)) is not None for row in rows)
    ]
    if len(series_columns) < 2:
        return False
    mentioned = sum(1 for column in series_columns if str(column) and str(column) in summary)
    return mentioned < min(2, len(series_columns))


def _should_preserve_rule_chart(rule_chart: ChartSpec, chart_type: Any) -> bool:
    requested = str(chart_type or "").strip()
    if not requested:
        return False
    if rule_chart.selection_reason in {"combo_target_actual_rate", "explicit_horizontal_ranking"} and requested != rule_chart.chart_type:
        return True
    return False


def _coerce_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
