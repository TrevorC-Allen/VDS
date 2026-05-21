"""Internal Agent roles for framework-neutral orchestration."""

from __future__ import annotations

from enum import Enum


class AgentRole(str, Enum):
    """Stable internal role names used before any framework adapter."""

    PLANNER = "planner"
    DATA_ENGINEER = "data_engineer"
    PANDAS_EXECUTOR = "pandas_executor"
    SQL_EXECUTOR = "sql_executor"
    VERIFIER = "verifier"
    CORRECTION = "correction"
    INSIGHT = "insight"
    VISUALIZATION = "visualization"
    BENCHMARK = "benchmark"
    RESPONSE_BUILDER = "response_builder"
