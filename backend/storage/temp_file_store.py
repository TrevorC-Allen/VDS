"""Temporary file store boundary for uploaded datasets."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid

import pandas as pd

from backend.schemas.data_agent_schema import to_json_ready
from data_agent_core.contracts.dataset_contracts import DatasetProfile
from data_agent_core.core.data_quality import build_data_quality_report, report_to_dict
from data_agent_core.core.file_parser import ParsedDataset, parse_dataset_files
from data_agent_core.core.schema_profiler import profile_tables
from data_agent_core.tracing.trace_writer import write_trace


@dataclass
class StoredDataset:
    """In-process handle for one parsed uploaded dataset."""

    dataset_id: str
    profile: DatasetProfile
    tables: dict[str, pd.DataFrame]
    source_path: Path


class TempFileStore:
    """Minimal local store for Phase 1 upload/profile/analyze flows."""

    def __init__(self, root: str | Path = "storage") -> None:
        self.root = Path(root)
        self.datasets_root = self.root / "datasets"
        self.runs_root = self.root / "runs"
        self._datasets: dict[str, StoredDataset] = {}

    def save_parsed_dataset(self, source_path: str | Path, parsed: ParsedDataset) -> StoredDataset:
        """Persist a copied source file and profile, keeping tables in memory."""

        source = Path(source_path)
        dataset_id = parsed.profile.dataset_id
        dataset_dir = self.datasets_root / dataset_id
        source_dir = dataset_dir / "source_file"
        source_dir.mkdir(parents=True, exist_ok=True)
        stored_source = source_dir / source.name
        if source.resolve() != stored_source.resolve():
            shutil.copy2(source, stored_source)

        profile_path = dataset_dir / "profile.json"
        profile_path.write_text(
            json.dumps(to_json_ready(parsed.profile), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        record = StoredDataset(
            dataset_id=dataset_id,
            profile=parsed.profile,
            tables=parsed.tables,
            source_path=stored_source,
        )
        self._datasets[dataset_id] = record
        return record

    def save_parsed_dataset_files(
        self,
        source_paths: list[str | Path],
        parsed: ParsedDataset,
        *,
        original_filenames: list[str | None] | None = None,
    ) -> StoredDataset:
        """Persist copied source files for a multi-file dataset."""

        dataset_id = parsed.profile.dataset_id
        dataset_dir = self.datasets_root / dataset_id
        source_dir = dataset_dir / "source_file"
        source_dir.mkdir(parents=True, exist_ok=True)
        stored_sources: list[str] = []
        for index, source_path in enumerate(source_paths):
            source = Path(source_path)
            stored_source = source_dir / source.name
            if source.resolve() != stored_source.resolve():
                shutil.copy2(source, stored_source)
            original_filename = None if original_filenames is None else original_filenames[index]
            stored_sources.append(str(original_filename or stored_source))

        profile_path = dataset_dir / "profile.json"
        profile_path.write_text(
            json.dumps(to_json_ready(parsed.profile), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        source_marker = dataset_dir / "multi_source.json"
        source_marker.write_text(
            json.dumps({"source_files": stored_sources, "table_names": list(parsed.tables.keys())}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        record = StoredDataset(
            dataset_id=dataset_id,
            profile=parsed.profile,
            tables=parsed.tables,
            source_path=source_marker,
        )
        self._datasets[dataset_id] = record
        return record

    def save_uploaded_files(
        self,
        file_paths: list[str | Path],
        *,
        dataset_id: str | None = None,
        original_filenames: list[str | None] | None = None,
    ) -> StoredDataset:
        """Parse and store multiple uploaded files as one dataset."""

        parsed = parse_dataset_files(file_paths, dataset_id=dataset_id, source_names=original_filenames)
        return self.save_parsed_dataset_files(file_paths, parsed, original_filenames=original_filenames)

    def save_inline_tables(
        self,
        tables: dict[str, pd.DataFrame],
        *,
        dataset_id: str | None = None,
        source_name: str = "api_inline_tables",
        warnings: list[str] | None = None,
        table_metadata: dict[str, dict[str, Any]] | None = None,
    ) -> StoredDataset:
        """Persist profile metadata for API-supplied tables and keep frames in memory."""

        if not tables:
            raise ValueError("At least one inline table is required.")

        dataset_id = dataset_id or _new_dataset_id()
        dataset_dir = self.datasets_root / dataset_id
        dataset_dir.mkdir(parents=True, exist_ok=True)
        table_metadata = table_metadata or {
            name: {"source_file": source_name, "sheet": None, "table_name": name}
            for name in tables
        }
        for table_name, df in tables.items():
            metadata = dict(table_metadata.get(table_name) or {})
            metadata.setdefault("source_file", source_name)
            metadata.setdefault("table_name", table_name)
            df.attrs.update({key: value for key, value in metadata.items() if value is not None})
            table_metadata[table_name] = metadata
        table_profiles = list(profile_tables(tables, table_metadata=table_metadata).values())
        quality_report = build_data_quality_report(tables, generated_from="inline_profile")
        profile_warnings = list(warnings or [])
        for table_name, df in tables.items():
            if df.empty:
                profile_warnings.append(f"Table {table_name} is empty.")
        profile = DatasetProfile(
            dataset_id=dataset_id,
            file_name=source_name,
            status="ready" if not profile_warnings else "ready_with_warnings",
            tables=table_profiles,
            created_at=datetime.now(timezone.utc).isoformat(),
            warnings=profile_warnings,
            errors=[],
            quality_report=report_to_dict(quality_report),
        )

        profile_path = dataset_dir / "profile.json"
        profile_path.write_text(
            json.dumps(to_json_ready(profile), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        source_marker = dataset_dir / "inline_source.json"
        source_marker.write_text(
            json.dumps(
                {
                    "source": source_name,
                    "table_names": list(tables.keys()),
                    "row_counts": {name: int(len(df)) for name, df in tables.items()},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        record = StoredDataset(
            dataset_id=dataset_id,
            profile=profile,
            tables=tables,
            source_path=source_marker,
        )
        self._datasets[dataset_id] = record
        return record

    def save_inline_table_payload(
        self,
        tables_payload: Any,
        *,
        dataset_id: str | None = None,
        source_name: str = "api_inline_tables",
    ) -> StoredDataset:
        """Normalize an external JSON table payload and store it as an inline dataset."""

        tables, warnings, table_metadata = _inline_tables_from_payload(tables_payload, source_name=source_name)
        return self.save_inline_tables(
            tables,
            dataset_id=dataset_id,
            source_name=source_name,
            warnings=warnings,
            table_metadata=table_metadata,
        )

    def get_profile(self, dataset_id: str) -> DatasetProfile | dict[str, Any] | None:
        """Return the in-memory profile or a profile.json dict when available."""

        record = self._datasets.get(dataset_id)
        if record is not None:
            return record.profile
        profile_path = self.datasets_root / dataset_id / "profile.json"
        if profile_path.exists():
            return json.loads(profile_path.read_text(encoding="utf-8"))
        return None

    def get_tables(self, dataset_id: str) -> dict[str, pd.DataFrame] | None:
        """Return parsed tables for the current process."""

        record = self._datasets.get(dataset_id)
        return None if record is None else record.tables

    def write_run_trace(self, trace: Any) -> Path:
        """Write a trace summary under storage/runs/{run_id}/trace.json."""

        return write_trace(trace, self.runs_root)


def _new_dataset_id() -> str:
    return "ds_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]


def _inline_tables_from_payload(
    tables_payload: Any,
    *,
    source_name: str = "api_inline_tables",
) -> tuple[dict[str, pd.DataFrame], list[str], dict[str, dict[str, Any]]]:
    """Convert external JSON table payloads into DataFrames without analyzing them."""

    if isinstance(tables_payload, dict):
        items = [
            _table_item_from_mapping(table_name, table_payload)
            for table_name, table_payload in tables_payload.items()
        ]
    elif isinstance(tables_payload, list):
        items = list(tables_payload)
    else:
        raise ValueError("tables must be either a list of table objects or an object keyed by table name.")

    if not items:
        raise ValueError("At least one table must be provided.")

    tables: dict[str, pd.DataFrame] = {}
    table_metadata: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Table item {index} must be an object.")
        table_name = str(item.get("table_name") or item.get("name") or f"table_{index}").strip() or f"table_{index}"
        if table_name in tables:
            raise ValueError(f"Duplicate table_name in inline payload: {table_name}")
        metadata = {
            "source_file": str(item.get("source_file") or source_name),
            "sheet": item.get("sheet"),
            "table_name": table_name,
        }
        rows = item.get("rows", item.get("records"))
        columns = item.get("columns")
        if columns is not None and not isinstance(columns, list):
            raise ValueError(f"columns for table {table_name} must be a list when provided.")
        if rows is None:
            raise ValueError(f"rows are required for table {table_name}.")
        if not isinstance(rows, list):
            raise ValueError(f"rows for table {table_name} must be a list.")
        if not rows:
            warnings.append(f"Table {table_name} has no rows.")
            tables[table_name] = pd.DataFrame(columns=columns or [])
            tables[table_name].attrs.update({key: value for key, value in metadata.items() if value is not None})
            table_metadata[table_name] = metadata
            continue
        if all(isinstance(row, dict) for row in rows):
            tables[table_name] = pd.DataFrame(rows, columns=columns)
            tables[table_name].attrs.update({key: value for key, value in metadata.items() if value is not None})
            table_metadata[table_name] = metadata
            continue
        if columns is None:
            raise ValueError(f"columns are required when rows for table {table_name} are arrays.")
        if not all(isinstance(row, list) for row in rows):
            raise ValueError(f"rows for table {table_name} must be all objects or all arrays.")
        for row_number, row in enumerate(rows, start=1):
            if len(row) != len(columns):
                raise ValueError(
                    f"Row {row_number} in table {table_name} has {len(row)} values but {len(columns)} columns were provided."
                )
        tables[table_name] = pd.DataFrame(rows, columns=columns)
        tables[table_name].attrs.update({key: value for key, value in metadata.items() if value is not None})
        table_metadata[table_name] = metadata
    return tables, warnings, table_metadata


def _table_item_from_mapping(table_name: str, table_payload: Any) -> dict[str, Any]:
    """Normalize {'sales': [...]} and {'sales': {'rows': [...]}} table maps."""

    if isinstance(table_payload, dict) and ("rows" in table_payload or "records" in table_payload):
        normalized = dict(table_payload)
        normalized.setdefault("table_name", table_name)
        return normalized
    return {"table_name": table_name, "rows": table_payload}
