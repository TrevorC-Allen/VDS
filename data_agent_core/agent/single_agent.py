"""Framework-neutral single Agent orchestration for the MVP phase."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from data_agent_core.contracts.analysis_contracts import UserQuestion
from data_agent_core.contracts.response_contracts import ChartSpec, FinalResponse, InsightResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.file_parser import load_dabstep_context
from data_agent_core.core.intent_parser import parse_generic_table_question, parse_question
from data_agent_core.executors import pandas_executor, sql_executor
from data_agent_core.llm.client import LLMClient, load_llm_client_from_env
from data_agent_core.llm.planner import LLMStageResult, complete_stage_with_llm, plan_with_llm
from data_agent_core.output.response_builder import build_response, classify_not_applicable
from data_agent_core.tracing.run_trace import RunTrace
from data_agent_core.verifier.result_comparator import compare_results
from data_agent_core.verifier.result_normalizer import normalize_value
from data_agent_core.verifier.rule_checker import verify_execution


SQL_COMPATIBLE_OPERATIONS = {
    "top_count",
    "group_average",
    "row_count",
    "distinct_count",
    "metric_per_distinct_entity",
    "repeat_entity_percentage",
    "repeat_entity_count",
    "null_check",
    "top_k_share",
    "filtered_metric_ranking",
    "boolean_percentage",
    "boolean_count_ratio",
    "fraud_rate_filtered",
    "not_applicable",
}
GENERIC_SQL_COMPATIBLE_OPERATIONS = {
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
    "boolean_percentage",
    "boolean_count_ratio",
    "fraud_rate_filtered",
    "not_applicable",
}

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
        llm_plan = plan_with_llm(
            llm_client=self.llm_client,
            question=question,
            guidelines=guidelines,
            context_summary=context_summary | {"rule_column_mapping": column_mapping},
        )
        logic_form = self._validated_logic_form(llm_plan.logic_form, guardrail_logic_form)
        plan = build_analysis_plan(logic_form)
        pandas_result = pandas_executor.execute_plan(plan, self.context)
        not_applicable_attribution = classify_not_applicable(pandas_result.value, plan)
        sql_result = None
        comparison = None
        if execution_mode in {"auto", "dual", "sql"} and logic_form.operation in SQL_COMPATIBLE_OPERATIONS:
            sql_result = sql_executor.execute_plan(plan, self.context)
            comparison = compare_results(pandas_result, sql_result)
        normalizer_summary = self._result_normalizer_summary(pandas_result, sql_result, comparison)
        verification = verify_execution(pandas_result, comparison)
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
                "llm_used": True,
                "llm_operation": llm_plan.logic_form.operation,
                "llm_confidence": llm_plan.confidence,
                "single_agent_chain": SINGLE_AGENT_CHAIN,
                "llm_stage_summaries": stage_summaries,
                "column_mapping": column_mapping,
            },
        )
        response.insight = self._insight_from_stage(response.answer, verification.passed, llm_insight)
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
            analysis_plan={"plan_id": plan.plan_id, "steps": plan.steps},
            llm_plan_summary={
                "llm_operation": llm_plan.logic_form.operation,
                "selected_operation": logic_form.operation,
                "guardrail_applied": llm_plan.logic_form.operation != logic_form.operation,
                "confidence": llm_plan.confidence,
                "reasoning_summary": self._short_text(llm_plan.reasoning_summary),
            },
            pandas_result_summary={"success": pandas_result.success, "value": pandas_result.value},
            sql_result_summary=None if sql_result is None else {"success": sql_result.success, "value": sql_result.value},
            result_normalizer_summary=normalizer_summary,
            verification_result=response.verification,
            verifier_critic_summary=stage_summaries["verifier_critic"],
            not_applicable_attribution=response.debug.get("not_applicable_attribution") or not_applicable_attribution,
            correction_plan_summary=stage_summaries["correction_planner"],
            final_response={"answer": response.answer, "success": response.success},
            insight_summary=stage_summaries["insight_generator"],
            chart_plan_summary=stage_summaries["chart_planner"],
            latency_ms=(time.perf_counter() - start) * 1000,
            errors=response.errors,
            warnings=response.warnings,
        )
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

    def _llm_intent_stage(
        self,
        question: str,
        guidelines: str,
        context_summary: dict[str, Any],
    ) -> LLMStageResult:
        return complete_stage_with_llm(
            llm_client=self.llm_client,
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
        return complete_stage_with_llm(
            llm_client=self.llm_client,
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
        return complete_stage_with_llm(
            llm_client=self.llm_client,
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
        return complete_stage_with_llm(
            llm_client=self.llm_client,
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
        return complete_stage_with_llm(
            llm_client=self.llm_client,
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
        return complete_stage_with_llm(
            llm_client=self.llm_client,
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
                "chart_type": "bar | line | pie | donut | histogram | box | scatter | none",
                "x": "field name or null",
                "y": "field name or null",
                "title": "string or null",
                "reason": "short summary, not chain of thought",
                "confidence": "number between 0 and 1",
                "reasoning_summary": "short summary, not chain of thought",
            },
        )

    def _validated_logic_form(self, llm_logic_form: Any, guardrail_logic_form: Any) -> Any:
        """Use LLM planning with deterministic schema guardrails."""

        if llm_logic_form.operation == guardrail_logic_form.operation:
            merged = guardrail_logic_form
            for key, value in llm_logic_form.output_format.items():
                merged.output_format.setdefault(key, value)
            return merged
        return guardrail_logic_form

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
        if not trusted:
            return ChartSpec(reason="No chart because verification did not pass.")
        if execution_result.rows and len(execution_result.columns) >= 2:
            return ChartSpec(
                chart_type="bar",
                x=execution_result.columns[0],
                y=execution_result.columns[1],
                title="Data comparison",
                data=execution_result.rows,
                reason="Rule planner selected a bar chart for a two-column comparison result.",
            )
        return ChartSpec(reason="No chart required for scalar or text answer.")

    def _insight_from_stage(self, answer: Any, trusted: bool, stage: LLMStageResult) -> InsightResult:
        if not trusted:
            return InsightResult(caveats=["No insight generated because verification did not pass."])
        raw = stage.raw
        suggestions = raw.get("suggestions") if isinstance(raw.get("suggestions"), list) else []
        caveats = raw.get("caveats") if isinstance(raw.get("caveats"), list) else []
        summary = str(raw.get("summary") or answer or "")
        return InsightResult(summary=summary, suggestions=suggestions, caveats=caveats)

    def _chart_from_stage(self, rule_chart: ChartSpec, stage: LLMStageResult, trusted: bool) -> ChartSpec:
        if not trusted:
            return rule_chart
        raw = stage.raw
        chart_type = raw.get("chart_type")
        if chart_type and chart_type != "none":
            return ChartSpec(
                chart_type=str(chart_type),
                x=raw.get("x") or rule_chart.x,
                y=raw.get("y") or rule_chart.y,
                title=raw.get("title") or rule_chart.title,
                data=rule_chart.data,
                reason=str(raw.get("reason") or raw.get("reasoning_summary") or rule_chart.reason),
            )
        return rule_chart

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
        llm_plan = plan_with_llm(
            llm_client=self.llm_client,
            question=question,
            guidelines=guidelines,
            context_summary=context_summary | {"rule_column_mapping": column_mapping},
        )
        logic_form = self._validated_logic_form(llm_plan.logic_form, guardrail_logic_form)
        plan = build_analysis_plan(logic_form)
        pandas_result = pandas_executor.execute_plan(plan, self.context)
        not_applicable_attribution = classify_not_applicable(pandas_result.value, plan)
        sql_result = None
        comparison = None
        if execution_mode in {"auto", "dual", "sql"} and logic_form.operation in GENERIC_SQL_COMPATIBLE_OPERATIONS:
            sql_result = sql_executor.execute_plan(plan, self.context)
            comparison = compare_results(pandas_result, sql_result)
        normalizer_summary = self._result_normalizer_summary(pandas_result, sql_result, comparison)
        verification = verify_execution(pandas_result, comparison)
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
                "llm_used": True,
                "llm_operation": llm_plan.logic_form.operation,
                "llm_confidence": llm_plan.confidence,
                "single_agent_chain": SINGLE_AGENT_CHAIN,
                "llm_stage_summaries": stage_summaries,
                "column_mapping": column_mapping,
            },
        )
        response.insight = self._insight_from_stage(response.answer, verification.passed, llm_insight)
        response.chart = self._chart_from_stage(rule_chart, llm_chart, verification.passed)
        trace = RunTrace(
            run_id=run_id,
            dataset_id=self.dataset_id,
            question=question,
            intent_summary=stage_summaries["intent_parser"],
            column_mapping_summary={"rule_mapping": column_mapping, "llm_summary": stage_summaries["column_mapping"]},
            analysis_planner_summary=stage_summaries["analysis_planner"],
            logic_form=response.logic_form,
            analysis_plan={"plan_id": plan.plan_id, "steps": plan.steps},
            llm_plan_summary={
                "llm_operation": llm_plan.logic_form.operation,
                "selected_operation": logic_form.operation,
                "guardrail_applied": llm_plan.logic_form.operation != logic_form.operation,
                "confidence": llm_plan.confidence,
                "reasoning_summary": self._short_text(llm_plan.reasoning_summary),
            },
            pandas_result_summary={"success": pandas_result.success, "value": pandas_result.value},
            sql_result_summary=None if sql_result is None else {"success": sql_result.success, "value": sql_result.value},
            result_normalizer_summary=normalizer_summary,
            verification_result=response.verification,
            verifier_critic_summary=stage_summaries["verifier_critic"],
            not_applicable_attribution=response.debug.get("not_applicable_attribution") or not_applicable_attribution,
            correction_plan_summary=stage_summaries["correction_planner"],
            insight_summary=stage_summaries["insight_generator"],
            chart_plan_summary=stage_summaries["chart_planner"],
            final_response={"answer": response.answer, "success": response.success},
            latency_ms=(time.perf_counter() - start) * 1000,
            errors=response.errors,
            warnings=response.warnings,
        )
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
