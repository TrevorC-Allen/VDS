"""File parser for CSV, Excel, Parquet, and DABstep context files."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from data_agent_core.contracts.dataset_contracts import DatasetProfile
from data_agent_core.core.data_quality import build_data_quality_report, report_to_dict
from data_agent_core.core.schema_profiler import profile_tables


@dataclass
class ParsedDataset:
    """Parsed file tables plus stable profile metadata."""

    tables: dict[str, pd.DataFrame]
    profile: DatasetProfile
    table_metadata: dict[str, dict[str, Any]] | None = None


def read_csv(path: str | Path) -> pd.DataFrame:
    """Read a CSV file with conservative defaults."""

    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return pd.read_csv(path, encoding=encoding, low_memory=False)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return pd.read_csv(path, encoding="utf-8-sig", low_memory=False)


def read_excel(path: str | Path) -> dict[str, pd.DataFrame]:
    """Read every sheet from an Excel workbook."""

    return pd.read_excel(path, sheet_name=None)


def read_parquet(path: str | Path) -> pd.DataFrame:
    """Read Parquet with a DuckDB fallback for runtimes without pyarrow."""

    try:
        return pd.read_parquet(path)
    except (ImportError, ValueError) as exc:
        message = str(exc).lower()
        if "pyarrow" not in message and "fastparquet" not in message and "parquet" not in message:
            raise
        try:
            import duckdb
        except ImportError as duckdb_exc:  # pragma: no cover - environment dependent.
            raise exc from duckdb_exc
        with duckdb.connect(database=":memory:") as con:
            return con.execute("SELECT * FROM read_parquet(?)", [str(Path(path))]).fetchdf()


def parse_dataset_file(
    path: str | Path,
    dataset_id: str | None = None,
    *,
    source_name: str | None = None,
) -> ParsedDataset:
    """Parse one uploaded CSV / Excel file and return tables plus DatasetProfile."""

    source_path = Path(path)
    display_name = source_name or source_path.name
    display_path = Path(display_name)
    dataset_id = dataset_id or _new_dataset_id()
    warnings: list[str] = []
    suffix = source_path.suffix.lower()
    if suffix == ".csv":
        tables = {display_path.stem or source_path.stem or "table": read_csv(source_path)}
    elif suffix in {".xlsx", ".xls"}:
        tables = read_excel(source_path)
        if len(tables) > 1:
            warnings.append("Multiple Excel sheets were parsed as separate tables.")
    elif suffix == ".json":
        records = read_json_records(source_path)
        tables = {display_path.stem or source_path.stem or "table": pd.DataFrame(records)}
    elif suffix == ".parquet":
        tables = {display_path.stem or source_path.stem or "table": read_parquet(source_path)}
    elif suffix in {".arrow", ".feather"}:
        tables = {display_path.stem or source_path.stem or "table": pd.read_feather(source_path)}
    else:
        raise ValueError(f"Unsupported file type: {source_path.suffix}")

    table_metadata: dict[str, dict[str, Any]] = {}
    for table_name, df in tables.items():
        metadata = {
            "source_file": display_name,
            "sheet": table_name if suffix in {".xlsx", ".xls"} else None,
            "table_name": table_name,
        }
        df.attrs.update({key: value for key, value in metadata.items() if value is not None})
        table_metadata[table_name] = metadata

    for table_name, df in tables.items():
        if df.empty:
            warnings.append(f"Table {table_name} is empty.")
        unnamed = [str(column) for column in df.columns if str(column).startswith("Unnamed")]
        if unnamed:
            warnings.append(f"Table {table_name} has uncertain header columns: {', '.join(unnamed)}.")

    table_profiles = list(profile_tables(tables, table_metadata=table_metadata).values())
    quality_report = build_data_quality_report(tables, generated_from="upload_profile")
    profile = DatasetProfile(
        dataset_id=dataset_id,
        file_name=display_name,
        status="ready" if not warnings else "ready_with_warnings",
        tables=table_profiles,
        created_at=datetime.now(timezone.utc).isoformat(),
        warnings=warnings,
        errors=[],
        quality_report=report_to_dict(quality_report),
    )
    return ParsedDataset(tables=tables, profile=profile, table_metadata=table_metadata)


def parse_dataset_files(
    paths: list[str | Path],
    dataset_id: str | None = None,
    *,
    source_names: list[str | None] | None = None,
) -> ParsedDataset:
    """Parse multiple uploaded CSV / Excel files into one auditable dataset."""

    if not paths:
        raise ValueError("At least one file is required for a multi-file dataset.")
    if source_names is not None and len(source_names) != len(paths):
        raise ValueError("source_names must have the same length as paths.")

    dataset_id = dataset_id or _new_dataset_id()
    combined_tables: dict[str, pd.DataFrame] = {}
    combined_metadata: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    display_source_names: list[str] = []
    for index, path in enumerate(paths):
        source_path = Path(path)
        display_name = None if source_names is None else source_names[index]
        parsed = parse_dataset_file(source_path, dataset_id=dataset_id, source_name=display_name)
        display_source_names.append(display_name or source_path.name)
        warnings.extend(parsed.profile.warnings)
        for original_name, df in parsed.tables.items():
            metadata = dict((parsed.table_metadata or {}).get(original_name) or {})
            table_source_path = Path(display_name or source_path.name)
            table_name = _unique_table_name(combined_tables, _table_name_for_source(table_source_path, original_name, len(parsed.tables)))
            metadata["table_name"] = table_name
            df.attrs.update({key: value for key, value in metadata.items() if value is not None})
            combined_tables[table_name] = df
            combined_metadata[table_name] = metadata
    if len(combined_tables) > 1:
        warnings.append("Multiple source files or sheets were parsed as separate tables.")

    table_profiles = list(profile_tables(combined_tables, table_metadata=combined_metadata).values())
    quality_report = build_data_quality_report(combined_tables, generated_from="upload_profile")
    profile = DatasetProfile(
        dataset_id=dataset_id,
        file_name=", ".join(display_source_names),
        status="ready" if not warnings else "ready_with_warnings",
        tables=table_profiles,
        created_at=datetime.now(timezone.utc).isoformat(),
        warnings=warnings,
        errors=[],
        quality_report=report_to_dict(quality_report),
    )
    return ParsedDataset(tables=combined_tables, profile=profile, table_metadata=combined_metadata)


def read_json_records(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSON file that contains a list of records."""

    data = json.loads(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON list records in {path}")
    return data


def load_dabstep_context(context_dir: str | Path) -> dict[str, Any]:
    """Load the DABstep context without exposing benchmark answers."""

    root = Path(context_dir)
    payments = read_csv(root / "payments.csv")
    merchant_category_codes = read_csv(root / "merchant_category_codes.csv")
    acquirer_countries = read_csv(root / "acquirer_countries.csv")
    tables = {
        "payments": payments,
        "merchant_category_codes": merchant_category_codes,
        "acquirer_countries": acquirer_countries,
    }
    for table_name, df in tables.items():
        source_file = f"{table_name}.csv"
        metadata = {"source_file": source_file, "sheet": None, "table_name": table_name}
        df.attrs.update(metadata)
    return {
        "payments": payments,
        "merchant_category_codes": merchant_category_codes,
        "acquirer_countries": acquirer_countries,
        "fees": read_json_records(root / "fees.json"),
        "merchant_data": read_json_records(root / "merchant_data.json"),
        "context_dir": root,
        "tables": tables,
        "primary_table": "payments",
    }


def _new_dataset_id() -> str:
    return "ds_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]


def _table_name_for_source(path: Path, table_name: str, table_count: int) -> str:
    if path.suffix.lower() == ".csv" or table_count == 1:
        return path.stem or table_name
    return f"{path.stem}__{table_name}"


def _unique_table_name(existing: dict[str, Any], preferred: str) -> str:
    candidate = preferred or "table"
    if candidate not in existing:
        return candidate
    index = 2
    while f"{candidate}_{index}" in existing:
        index += 1
    return f"{candidate}_{index}"
