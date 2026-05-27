"""Response contracts for API-facing final results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class InsightResult:
    """Concise explanation generated only after verification passes."""

    summary: str = ""
    key_numbers: dict[str, Any] = field(default_factory=dict)
    anomaly_findings: list[dict[str, Any]] = field(default_factory=list)
    volatility_findings: list[dict[str, Any]] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    business_suggestions: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    next_questions: list[str] = field(default_factory=list)
    evidence_rows: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class ChartSpec:
    """Frontend-neutral chart specification."""

    chart_type: str | None = None
    x: str | None = None
    y: str | None = None
    title: str | None = None
    data: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    encoding: dict[str, Any] = field(default_factory=dict)
    series: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    selection_reason: str = ""
    fallback_reason: str = ""
    image_data_uri: str = ""
    image_format: str = ""
    render_engine: str = ""


@dataclass
class DataQualityIssue:
    """One trace-safe data quality finding."""

    severity: str
    issue_type: str
    message: str
    table_name: str | None = None
    column_name: str | None = None
    affected_rows: int | None = None
    sample_values: list[Any] = field(default_factory=list)
    suggested_cleaning_actions: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class DataQualityReport:
    """Dataset/table/column quality scan for upload and analyze responses."""

    status: str = "not_scanned"
    quality_score: float = 100.0
    scanned_tables: list[str] = field(default_factory=list)
    issue_count: int = 0
    summary: str = ""
    issues: list[DataQualityIssue] = field(default_factory=list)
    generated_from: str = "dataframe_scan"


@dataclass
class ReasoningTraceStep:
    """Safe process visualization step. This is not full Chain of Thought."""

    step_id: str
    name: str
    status: str
    summary: str
    confidence: float | None = None
    inputs_summary: dict[str, Any] = field(default_factory=dict)
    outputs_summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class FinalResponse:
    """Stable final response contract for analyze requests."""

    response_version: str
    success: bool
    run_id: str
    dataset_id: str
    question: str
    answer_type: str
    execution_mode: str
    answer: Any = None
    logic_form: Any = None
    result: Any = None
    verification: Any = None
    insight: InsightResult | None = None
    chart: ChartSpec | None = None
    quality_report: DataQualityReport | dict[str, Any] | None = None
    reasoning_trace_view: list[ReasoningTraceStep] | list[dict[str, Any]] = field(default_factory=list)
    process_view_v2: dict[str, Any] = field(default_factory=dict)
    overview_report: dict[str, Any] = field(default_factory=dict)
    activity_trace_v2: list[dict[str, Any]] = field(default_factory=list)
    execution_artifacts: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[Any] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready dict for CLI, tests, and backend shells."""

        return asdict(self)
