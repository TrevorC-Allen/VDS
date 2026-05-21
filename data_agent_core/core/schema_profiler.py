"""Schema profiler for field understanding."""

from __future__ import annotations

from typing import Any

import pandas as pd

from data_agent_core.contracts.dataset_contracts import ColumnProfile, TableProfile


def infer_column_type(series: pd.Series) -> str:
    """Infer a simple stable column type."""

    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "category" if series.nunique(dropna=True) <= max(50, len(series) * 0.2) else "text"


def semantic_hints(name: str, series: pd.Series) -> list[str]:
    """Return lightweight semantic hints based on names and values."""

    lowered = name.lower()
    hints: list[str] = []
    if "date" in lowered or "day" in lowered or "year" in lowered or "month" in lowered:
        hints.append("time")
    if "amount" in lowered or "fee" in lowered or "volume" in lowered or "rate" in lowered:
        hints.append("metric")
    if "country" in lowered:
        hints.append("country")
    if "id" in lowered or lowered.endswith("_reference"):
        hints.append("id")
    if series.nunique(dropna=True) <= max(20, len(series) * 0.05):
        hints.append("category")
    return sorted(set(hints))


def profile_table(table_name: str, df: pd.DataFrame) -> TableProfile:
    """Build a TableProfile for one DataFrame."""

    columns: list[ColumnProfile] = []
    row_count = len(df)
    for name in df.columns:
        series = df[name]
        samples = [v for v in series.dropna().head(5).tolist()]
        columns.append(
            ColumnProfile(
                name=str(name),
                inferred_type=infer_column_type(series),
                missing_rate=0.0 if row_count == 0 else float(series.isna().mean()),
                unique_count=int(series.nunique(dropna=True)),
                sample_values=samples,
                semantic_hints=semantic_hints(str(name), series),
            )
        )
    return TableProfile(
        table_name=table_name,
        row_count=row_count,
        column_count=len(df.columns),
        columns=columns,
    )


def profile_tables(tables: dict[str, pd.DataFrame]) -> dict[str, TableProfile]:
    """Profile a mapping of table names to DataFrames."""

    return {name: profile_table(name, df) for name, df in tables.items()}
