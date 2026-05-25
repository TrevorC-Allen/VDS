"""Run trace contract for analyze requests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RunTrace:
    """Auditable execution summary for one analyze request."""

    run_id: str
    dataset_id: str
    question: str
    intent_summary: Any = None
    column_mapping_summary: Any = None
    analysis_planner_summary: Any = None
    llm_plan_summary: Any = None
    logic_form: Any = None
    metric_definition: Any = None
    numerator: Any = None
    denominator: Any = None
    entity_grain: Any = None
    time_window: Any = None
    candidate_set: Any = None
    source_tables: list[str] = field(default_factory=list)
    table_selection_reason: str = ""
    join_plan: Any = None
    join_execution_summary: Any = None
    output_contract: Any = None
    analysis_plan: Any = None
    pandas_result_summary: Any = None
    sql_result_summary: Any = None
    result_normalizer_summary: Any = None
    verification_result: Any = None
    verifier_critic_summary: Any = None
    semantic_verification_notes: list[str] = field(default_factory=list)
    not_applicable_attribution: Any = None
    correction_plan_summary: Any = None
    correction_attempts: list[Any] = field(default_factory=list)
    candidate_table_summary: Any = None
    selected_candidate: Any = None
    tool_call_summary: list[Any] = field(default_factory=list)
    insight_summary: Any = None
    chart_plan_summary: Any = None
    quality_report: Any = None
    reasoning_trace_view: list[Any] = field(default_factory=list)
    process_view_v2: dict[str, Any] = field(default_factory=dict)
    final_response: Any = None
    latency_ms: float | None = None
    errors: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready trace dict."""

        return asdict(self)
