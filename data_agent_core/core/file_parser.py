"""File parser for CSV, Excel, and DABstep context files."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from data_agent_core.contracts.dataset_contracts import DatasetProfile
from data_agent_core.core.schema_profiler import profile_tables


@dataclass
class ParsedDataset:
    """Parsed file tables plus stable profile metadata."""

    tables: dict[str, pd.DataFrame]
    profile: DatasetProfile


def read_csv(path: str | Path) -> pd.DataFrame:
    """Read a CSV file with conservative defaults."""

    return pd.read_csv(path, encoding="utf-8-sig")


def read_excel(path: str | Path) -> dict[str, pd.DataFrame]:
    """Read every sheet from an Excel workbook."""

    return pd.read_excel(path, sheet_name=None)


def parse_dataset_file(path: str | Path, dataset_id: str | None = None) -> ParsedDataset:
    """Parse one uploaded CSV / Excel file and return tables plus DatasetProfile."""

    source_path = Path(path)
    dataset_id = dataset_id or _new_dataset_id()
    warnings: list[str] = []
    suffix = source_path.suffix.lower()
    if suffix == ".csv":
        tables = {source_path.stem or "table": read_csv(source_path)}
    elif suffix in {".xlsx", ".xls"}:
        tables = read_excel(source_path)
        if len(tables) > 1:
            warnings.append("Multiple Excel sheets were parsed as separate tables.")
    else:
        raise ValueError(f"Unsupported file type: {source_path.suffix}")

    for table_name, df in tables.items():
        if df.empty:
            warnings.append(f"Table {table_name} is empty.")
        unnamed = [str(column) for column in df.columns if str(column).startswith("Unnamed")]
        if unnamed:
            warnings.append(f"Table {table_name} has uncertain header columns: {', '.join(unnamed)}.")

    table_profiles = list(profile_tables(tables).values())
    profile = DatasetProfile(
        dataset_id=dataset_id,
        file_name=source_path.name,
        status="ready" if not warnings else "ready_with_warnings",
        tables=table_profiles,
        created_at=datetime.now(timezone.utc).isoformat(),
        warnings=warnings,
        errors=[],
    )
    return ParsedDataset(tables=tables, profile=profile)


def read_json_records(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSON file that contains a list of records."""

    data = json.loads(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON list records in {path}")
    return data


def load_dabstep_context(context_dir: str | Path) -> dict[str, Any]:
    """Load the DABstep context without exposing benchmark answers."""

    root = Path(context_dir)
    return {
        "payments": read_csv(root / "payments.csv"),
        "merchant_category_codes": read_csv(root / "merchant_category_codes.csv"),
        "acquirer_countries": read_csv(root / "acquirer_countries.csv"),
        "fees": read_json_records(root / "fees.json"),
        "merchant_data": read_json_records(root / "merchant_data.json"),
        "context_dir": root,
    }


def _new_dataset_id() -> str:
    return "ds_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
