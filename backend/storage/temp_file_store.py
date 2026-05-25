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
from data_agent_core.core.file_parser import ParsedDataset, load_dabstep_context, parse_dataset_files
from data_agent_core.core.schema_profiler import profile_tables
from data_agent_core.tracing.trace_writer import write_trace


DABSTEP_CONTEXT_REQUIRED_FILES = frozenset(
    {
        "payments.csv",
        "merchant_category_codes.csv",
        "acquirer_countries.csv",
        "fees.json",
        "merchant_data.json",
        "manual.md",
    }
)
DABSTEP_CONTEXT_TABLE_FILES = ("payments.csv", "merchant_category_codes.csv", "acquirer_countries.csv")
DABSTEP_CONTEXT_KNOWLEDGE_FILES = ("fees.json", "merchant_data.json", "manual.md")
DABSTEP_DATASET_KIND = "dabstep_context"


@dataclass
class StoredDataset:
    """In-process handle for one parsed uploaded dataset."""

    dataset_id: str
    profile: DatasetProfile | dict[str, Any]
    tables: dict[str, pd.DataFrame]
    source_path: Path
    analysis_context: dict[str, Any] | None = None
    dataset_kind: str = "uploaded_tables"
    context_dir: Path | None = None


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
            analysis_context=_analysis_context_for_tables(parsed.tables),
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
            analysis_context=_analysis_context_for_tables(parsed.tables),
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

        if original_filenames is not None and len(original_filenames) != len(file_paths):
            raise ValueError("original_filenames must have the same length as file_paths.")
        dabstep_state = _inspect_dabstep_upload(file_paths, original_filenames)
        if dabstep_state["complete"]:
            return self.save_dabstep_context_files(
                file_paths,
                dataset_id=dataset_id,
                original_filenames=original_filenames,
            )
        if dabstep_state["partial"]:
            missing = ", ".join(dabstep_state["missing"])
            raise ValueError(
                "DABstep context package is incomplete. "
                "Upload these files together from the web workbench: "
                "payments.csv, merchant_category_codes.csv, acquirer_countries.csv, "
                f"fees.json, merchant_data.json, manual.md. Missing: {missing}."
            )

        parsed = parse_dataset_files(file_paths, dataset_id=dataset_id, source_names=original_filenames)
        return self.save_parsed_dataset_files(file_paths, parsed, original_filenames=original_filenames)

    def save_dabstep_context_files(
        self,
        file_paths: list[str | Path],
        *,
        dataset_id: str | None = None,
        original_filenames: list[str | None] | None = None,
    ) -> StoredDataset:
        """Persist a DABstep-style context package uploaded through the workbench."""

        file_map, ignored_names = _dabstep_file_map(file_paths, original_filenames)
        missing = sorted(DABSTEP_CONTEXT_REQUIRED_FILES - set(file_map))
        if missing:
            raise ValueError(f"DABstep context package is incomplete. Missing: {', '.join(missing)}.")

        dataset_id = dataset_id or _new_dataset_id()
        dataset_dir = self.datasets_root / dataset_id
        context_dir = dataset_dir / "dab_context"
        context_dir.mkdir(parents=True, exist_ok=True)
        for filename in sorted(DABSTEP_CONTEXT_REQUIRED_FILES):
            source = file_map[filename]
            stored_source = context_dir / filename
            if source.resolve() != stored_source.resolve():
                shutil.copy2(source, stored_source)

        context = load_dabstep_context(context_dir)
        tables = dict(context["tables"])
        table_metadata = {
            table_name: {"source_file": f"{table_name}.csv", "sheet": None, "table_name": table_name}
            for table_name in tables
        }
        for table_name, df in tables.items():
            df.attrs.update(table_metadata[table_name])

        warnings = [
            "已识别 DABstep 规则上下文包；manual.md、fees.json、merchant_data.json 会作为后端规则知识库参与分析。",
        ]
        if ignored_names:
            warnings.append("已忽略非 DAB context 必需文件：" + ", ".join(ignored_names) + "。")
        table_profiles = list(profile_tables(tables, table_metadata=table_metadata).values())
        quality_report = build_data_quality_report(tables, generated_from="dabstep_context_upload")
        profile = DatasetProfile(
            dataset_id=dataset_id,
            file_name="DABstep context package: " + ", ".join(
                [*DABSTEP_CONTEXT_TABLE_FILES, *DABSTEP_CONTEXT_KNOWLEDGE_FILES]
            ),
            status="ready_with_warnings" if warnings else "ready",
            tables=table_profiles,
            created_at=datetime.now(timezone.utc).isoformat(),
            warnings=warnings,
            errors=[],
            quality_report=report_to_dict(quality_report),
        )

        profile_path = dataset_dir / "profile.json"
        profile_path.write_text(
            json.dumps(to_json_ready(profile), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        source_marker = dataset_dir / "dab_context.json"
        source_marker.write_text(
            json.dumps(
                {
                    "dataset_kind": DABSTEP_DATASET_KIND,
                    "context_files": sorted(DABSTEP_CONTEXT_REQUIRED_FILES),
                    "table_names": list(tables.keys()),
                    "ignored_files": ignored_names,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        context["dataset_kind"] = DABSTEP_DATASET_KIND
        record = StoredDataset(
            dataset_id=dataset_id,
            profile=profile,
            tables=tables,
            source_path=source_marker,
            analysis_context=context,
            dataset_kind=DABSTEP_DATASET_KIND,
            context_dir=context_dir,
        )
        self._datasets[dataset_id] = record
        return record

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
            analysis_context=_analysis_context_for_tables(tables),
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
        if record is None:
            record = self._load_dabstep_record_from_disk(dataset_id)
        return None if record is None else record.tables

    def get_analysis_context(self, dataset_id: str) -> dict[str, Any] | None:
        """Return the executor context for a stored dataset."""

        record = self._datasets.get(dataset_id)
        if record is None:
            record = self._load_dabstep_record_from_disk(dataset_id)
        if record is None:
            return None
        if record.analysis_context is not None:
            return record.analysis_context
        return _analysis_context_for_tables(record.tables)

    def get_dataset_kind(self, dataset_id: str) -> str:
        """Return the dataset kind used to select the analysis context."""

        record = self._datasets.get(dataset_id)
        if record is None:
            record = self._load_dabstep_record_from_disk(dataset_id)
        return "uploaded_tables" if record is None else record.dataset_kind

    def get_context_dir(self, dataset_id: str) -> Path | None:
        """Return a persisted context directory for rule-package datasets."""

        record = self._datasets.get(dataset_id)
        if record is None:
            record = self._load_dabstep_record_from_disk(dataset_id)
        return None if record is None else record.context_dir

    def write_run_trace(self, trace: Any) -> Path:
        """Write a trace summary under storage/runs/{run_id}/trace.json."""

        return write_trace(trace, self.runs_root)

    def _load_dabstep_record_from_disk(self, dataset_id: str) -> StoredDataset | None:
        """Restore a DABstep context package from persisted source files."""

        dataset_dir = self.datasets_root / dataset_id
        source_marker = dataset_dir / "dab_context.json"
        context_dir = dataset_dir / "dab_context"
        if not source_marker.exists() or not context_dir.exists():
            return None
        profile = self.get_profile(dataset_id)
        if profile is None:
            return None
        context = load_dabstep_context(context_dir)
        context["dataset_kind"] = DABSTEP_DATASET_KIND
        record = StoredDataset(
            dataset_id=dataset_id,
            profile=profile,
            tables=dict(context["tables"]),
            source_path=source_marker,
            analysis_context=context,
            dataset_kind=DABSTEP_DATASET_KIND,
            context_dir=context_dir,
        )
        self._datasets[dataset_id] = record
        return record


def _new_dataset_id() -> str:
    return "ds_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]


def _analysis_context_for_tables(tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    return {"tables": tables, "primary_table": _primary_table_name(tables)}


def _primary_table_name(tables: dict[str, pd.DataFrame]) -> str:
    if not tables:
        return ""
    return max(tables.items(), key=lambda item: (len(item[1]), len(item[1].columns)))[0]


def _inspect_dabstep_upload(
    file_paths: list[str | Path],
    original_filenames: list[str | None] | None,
) -> dict[str, Any]:
    names = [_upload_basename(path, None if original_filenames is None else original_filenames[index]) for index, path in enumerate(file_paths)]
    present = set(names) & DABSTEP_CONTEXT_REQUIRED_FILES
    has_json_or_markdown = any(Path(name).suffix.lower() in {".json", ".md", ".markdown"} for name in names)
    complete = DABSTEP_CONTEXT_REQUIRED_FILES.issubset(set(names))
    partial = not complete and (bool(present) or has_json_or_markdown)
    return {
        "complete": complete,
        "partial": partial,
        "missing": sorted(DABSTEP_CONTEXT_REQUIRED_FILES - set(names)),
    }


def _dabstep_file_map(
    file_paths: list[str | Path],
    original_filenames: list[str | None] | None,
) -> tuple[dict[str, Path], list[str]]:
    file_map: dict[str, Path] = {}
    ignored_names: list[str] = []
    for index, file_path in enumerate(file_paths):
        name = _upload_basename(file_path, None if original_filenames is None else original_filenames[index])
        path = Path(file_path)
        if name in DABSTEP_CONTEXT_REQUIRED_FILES:
            if name in file_map:
                raise ValueError(f"Duplicate DABstep context file: {name}")
            file_map[name] = path
        else:
            ignored_names.append(name)
    return file_map, ignored_names


def _upload_basename(file_path: str | Path, original_filename: str | None) -> str:
    return Path(str(original_filename or Path(file_path).name)).name.lower()


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
