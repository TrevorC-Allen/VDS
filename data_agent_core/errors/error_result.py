"""Standard error result for all Data Agent modules."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class ErrorResult:
    """Structured error object returned through errors fields."""

    error_type: str
    error_message: str
    failed_step: str
    recoverable: bool = False
    suggested_fix: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready error dict."""

        return asdict(self)
