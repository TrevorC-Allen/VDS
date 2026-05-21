"""Response contracts for API-facing final results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class InsightResult:
    """Concise explanation generated only after verification passes."""

    summary: str = ""
    key_numbers: dict[str, Any] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    next_questions: list[str] = field(default_factory=list)


@dataclass
class ChartSpec:
    """Frontend-neutral chart specification."""

    chart_type: str | None = None
    x: str | None = None
    y: str | None = None
    title: str | None = None
    data: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""


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
    warnings: list[str] = field(default_factory=list)
    errors: list[Any] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready dict for CLI, tests, and backend shells."""

        return asdict(self)
