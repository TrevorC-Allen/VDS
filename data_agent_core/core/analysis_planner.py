"""Analysis planner for structured analysis plans."""

from __future__ import annotations

import hashlib

from data_agent_core.contracts.analysis_contracts import AnalysisPlan, LogicForm


def build_analysis_plan(logic_form: LogicForm) -> AnalysisPlan:
    """Build a backend-neutral AnalysisPlan from a LogicForm."""

    plan_seed = f"{logic_form.task_type}:{logic_form.operation}:{logic_form.filters}:{logic_form.parameters}"
    plan_id = "plan_" + hashlib.sha1(plan_seed.encode("utf-8")).hexdigest()[:12]
    return AnalysisPlan(
        plan_id=plan_id,
        logic_form=logic_form,
        steps=[
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
        ],
        expected_result_shape=str(logic_form.output_format.get("answer_type", "scalar")),
        constraints={"framework_neutral": True, "no_benchmark_answer_access": True},
    )
