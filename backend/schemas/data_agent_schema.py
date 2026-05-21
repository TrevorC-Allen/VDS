"""Backend API schema helpers for the minimal Data Agent shell."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

from data_agent_core.contracts.dataset_contracts import DatasetProfile


RESPONSE_VERSION = "v1"
VALID_EXECUTION_MODES = {"auto", "pandas", "sql", "dual"}
VALID_AGENT_MODES = {"multi_agent", "single_agent"}


@dataclass
class AnalyzeRequest:
    """Stable analyze request shape used by service tests and optional routers."""

    dataset_id: str
    question: str
    execution_mode: str = "dual"
    guidelines: str = ""
    agent_mode: str = "multi_agent"


def dataset_profile_response(profile: DatasetProfile | dict[str, Any]) -> dict[str, Any]:
    """Build the stable profile response returned by upload/profile endpoints."""

    data = to_json_ready(profile)
    return {
        "response_version": RESPONSE_VERSION,
        "success": True,
        "dataset_id": data.get("dataset_id"),
        "file_name": data.get("file_name"),
        "tables": data.get("tables", []),
        "created_at": data.get("created_at"),
        "status": data.get("status", "unknown"),
        "warnings": data.get("warnings", []),
        "errors": data.get("errors", []),
    }


def error_response(
    *,
    error: Any,
    success: bool = False,
    dataset_id: str | None = None,
    run_id: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build a stable error response with errors/warnings fields."""

    response: dict[str, Any] = {
        "response_version": RESPONSE_VERSION,
        "success": success,
        "warnings": warnings or [],
        "errors": [to_json_ready(error)],
    }
    if dataset_id is not None:
        response["dataset_id"] = dataset_id
    if run_id is not None:
        response["run_id"] = run_id
    return response


def to_json_ready(value: Any) -> Any:
    """Recursively convert dataclasses and scalar-like values to JSON-safe data."""

    if is_dataclass(value):
        return to_json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [to_json_ready(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value
