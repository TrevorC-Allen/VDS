"""Schema profiler for field understanding."""

from __future__ import annotations

import re
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
    if _looks_datetime(series):
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
    if "sales" in lowered or "revenue" in lowered or "销售" in lowered or "金额" in lowered:
        hints.append("metric")
    if "country" in lowered:
        hints.append("country")
    if "city" in lowered or "城市" in lowered:
        hints.append("location")
    if "id" in lowered or lowered.endswith("_reference"):
        hints.append("id")
    if series.nunique(dropna=True) <= max(20, len(series) * 0.05):
        hints.append("category")
    return sorted(set(hints))


def _looks_datetime(series: pd.Series) -> bool:
    sample = series.dropna().astype(str).head(50)
    if sample.empty:
        return False
    date_like = sample.map(
        lambda value: bool(
            re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", value)
            or re.search(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", value)
        )
    )
    if float(date_like.mean()) < 0.8:
        return False
    parsed = pd.to_datetime(sample, errors="coerce")
    return float(parsed.notna().mean()) >= 0.8


def profile_table(
    table_name: str,
    df: pd.DataFrame,
    *,
    source_file: str | None = None,
    sheet: str | None = None,
    source_kind: str | None = None,
    range_ref: str | None = None,
    header_rows: list[int] | None = None,
    table_role: str | None = None,
    role_confidence: float | None = None,
    parse_diagnostics: dict[str, Any] | None = None,
) -> TableProfile:
    """Build a TableProfile for one DataFrame."""

    columns: list[ColumnProfile] = []
    row_count = len(df)
    source_file = source_file if source_file is not None else _attr_text(df, "source_file")
    sheet = sheet if sheet is not None else _attr_text(df, "sheet")
    source_kind = source_kind if source_kind is not None else _attr_text(df, "source_kind") or "table"
    range_ref = range_ref if range_ref is not None else _attr_text(df, "range_ref") or ""
    table_role = table_role if table_role is not None else _attr_text(df, "table_role") or "data_table"
    role_confidence = role_confidence if role_confidence is not None else _attr_float(df, "role_confidence", 0.0)
    header_rows = header_rows if header_rows is not None else _attr_list(df, "header_rows")
    parse_diagnostics = parse_diagnostics if parse_diagnostics is not None else _attr_dict(df, "parse_diagnostics")
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
        source_file=source_file,
        sheet=sheet,
        source_kind=source_kind,
        range_ref=range_ref,
        header_rows=header_rows,
        table_role=table_role,
        role_confidence=float(role_confidence or 0.0),
        parse_diagnostics=parse_diagnostics,
    )


def profile_tables(
    tables: dict[str, pd.DataFrame],
    table_metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, TableProfile]:
    """Profile a mapping of table names to DataFrames."""

    table_metadata = table_metadata or {}
    return {
        name: profile_table(
            name,
            df,
            source_file=table_metadata.get(name, {}).get("source_file"),
            sheet=table_metadata.get(name, {}).get("sheet"),
            source_kind=table_metadata.get(name, {}).get("source_kind"),
            range_ref=table_metadata.get(name, {}).get("range_ref"),
            header_rows=table_metadata.get(name, {}).get("header_rows"),
            table_role=table_metadata.get(name, {}).get("table_role"),
            role_confidence=table_metadata.get(name, {}).get("role_confidence"),
            parse_diagnostics=table_metadata.get(name, {}).get("parse_diagnostics"),
        )
        for name, df in tables.items()
    }


def _attr_text(df: pd.DataFrame, key: str) -> str | None:
    value = df.attrs.get(key)
    if value in {None, ""}:
        return None
    return str(value)


def _attr_float(df: pd.DataFrame, key: str, default: float) -> float:
    value = df.attrs.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _attr_list(df: pd.DataFrame, key: str) -> list[Any]:
    value = df.attrs.get(key)
    return list(value) if isinstance(value, (list, tuple)) else []


def _attr_dict(df: pd.DataFrame, key: str) -> dict[str, Any]:
    value = df.attrs.get(key)
    return dict(value) if isinstance(value, dict) else {}
