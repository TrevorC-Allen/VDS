"""Temporary file store boundary for uploaded datasets."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
import uuid

import pandas as pd

from backend.schemas.data_agent_schema import (
    BENCHMARK_RULE_SCOPE,
    DATASET_FILE_EXTENSIONS,
    DATASET_FILE_ROLE,
    RULE_FILE_EXTENSIONS,
    RULE_FILE_ROLE,
    USER_ANALYSIS_RULE_SCOPE,
    VALID_RULE_SCOPES,
    to_json_ready,
)
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
SOURCE_ONLY_DATASET_KIND = "uploaded_sources"
TEXT_SOURCE_SUFFIXES = (".md", ".txt", ".yaml", ".yml", ".rtf", ".html", ".htm")
DOCUMENT_SOURCE_SUFFIXES = (".doc", ".docx", ".docm", ".odt", ".pdf", ".pages")
SOURCE_DOCUMENT_SUFFIXES = TEXT_SOURCE_SUFFIXES + DOCUMENT_SOURCE_SUFFIXES


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


@dataclass
class StoredRuleFile:
    """Stored rule file metadata kept separate from parsed datasets."""

    file_id: str
    file_name: str
    rule_scope: str
    raw_text: str
    parsed_rule: Any
    storage_path: Path
    created_at: str
    dataset_id: str = ""
    file_role: str = RULE_FILE_ROLE
    warnings: list[str] = field(default_factory=list)
    errors: list[Any] = field(default_factory=list)


class TempFileStore:
    """Minimal local store for Phase 1 upload/profile/analyze flows."""

    def __init__(self, root: str | Path = "storage") -> None:
        self.root = Path(root)
        self.datasets_root = self.root / "datasets"
        self.rules_root = self.root / "rules"
        self.runs_root = self.root / "runs"
        self._datasets: dict[str, StoredDataset] = {}
        self._rule_files: dict[str, StoredRuleFile] = {}

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
        stored_file_names: list[str] = []
        stored_file_by_display_name: dict[str, str] = {}
        for index, source_path in enumerate(source_paths):
            source = Path(source_path)
            stored_source = source_dir / source.name
            if source.resolve() != stored_source.resolve():
                shutil.copy2(source, stored_source)
            original_filename = None if original_filenames is None else original_filenames[index]
            display_name = str(original_filename or stored_source.name)
            stored_sources.append(display_name)
            stored_file_names.append(stored_source.name)
            stored_file_by_display_name[display_name] = stored_source.name

        profile_path = dataset_dir / "profile.json"
        profile_path.write_text(
            json.dumps(to_json_ready(parsed.profile), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        source_marker = dataset_dir / "multi_source.json"
        source_file_map = []
        for table_name, metadata in (parsed.table_metadata or {}).items():
            source_file = str(metadata.get("source_file") or "")
            source_file_map.append(
                {
                    "table_name": table_name,
                    "source_file": source_file,
                    "stored_file": stored_file_by_display_name.get(source_file, ""),
                }
            )
        source_marker.write_text(
            json.dumps(
                {
                    "source_files": stored_sources,
                    "stored_files": stored_file_names,
                    "table_names": list(parsed.tables.keys()),
                    "source_file_map": source_file_map,
                },
                ensure_ascii=False,
                indent=2,
            ),
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

    def save_source_only_files(
        self,
        file_paths: list[str | Path],
        *,
        dataset_id: str | None = None,
        original_filenames: list[str | None] | None = None,
    ) -> StoredDataset:
        """Persist standalone readable source files without forcing DataFrame parsing."""

        if not file_paths:
            raise ValueError("At least one source file is required.")
        if original_filenames is not None and len(original_filenames) != len(file_paths):
            raise ValueError("original_filenames must have the same length as file_paths.")

        dataset_id = dataset_id or _new_dataset_id()
        dataset_dir = self.datasets_root / dataset_id
        source_dir = dataset_dir / "source_file"
        source_dir.mkdir(parents=True, exist_ok=True)
        stored_sources: list[str] = []
        stored_file_names: list[str] = []
        warnings: list[str] = []
        for index, source_path in enumerate(file_paths):
            source = Path(source_path)
            original_filename = None if original_filenames is None else original_filenames[index]
            display_name = Path(str(original_filename or source.name)).name
            stored_source = source_dir / source.name
            if source.resolve() != stored_source.resolve():
                shutil.copy2(source, stored_source)
            stored_sources.append(display_name)
            stored_file_names.append(stored_source.name)
            suffix = Path(display_name).suffix.lower() or stored_source.suffix.lower()
            if not _read_source_text(stored_source, suffix=suffix).strip():
                warnings.append(f"{display_name} 已保存，但未抽取到可展示正文。")

        quality_report = build_data_quality_report({}, generated_from="source_only_profile")
        profile = DatasetProfile(
            dataset_id=dataset_id,
            file_name=", ".join(stored_sources),
            status="ready" if not warnings else "ready_with_warnings",
            tables=[],
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
        source_marker = dataset_dir / "multi_source.json"
        source_marker.write_text(
            json.dumps(
                {
                    "dataset_kind": SOURCE_ONLY_DATASET_KIND,
                    "source_files": stored_sources,
                    "stored_files": stored_file_names,
                    "table_names": [],
                    "source_file_map": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        record = StoredDataset(
            dataset_id=dataset_id,
            profile=profile,
            tables={},
            source_path=source_marker,
            analysis_context=_analysis_context_for_tables({}),
            dataset_kind=SOURCE_ONLY_DATASET_KIND,
        )
        self._datasets[dataset_id] = record
        return record

    def save_rule_file(
        self,
        file_path: str | Path,
        *,
        rule_scope: str,
        original_filename: str | None = None,
        dataset_id: str = "",
    ) -> StoredRuleFile:
        """Persist one user or benchmark rule file without parsing it as data."""

        scope = _normalize_rule_scope(rule_scope)
        source = Path(file_path)
        display_name = Path(str(original_filename or source.name)).name
        suffix = Path(display_name).suffix.lower() or source.suffix.lower()
        if suffix not in RULE_FILE_EXTENSIONS:
            raise ValueError(
                f"Unsupported rule file type: {suffix or '(none)'}. "
                "Rule/source files must use yaml, yml, json, txt, md, Word, RTF, ODT, PDF, Pages, or HTML."
            )
        if dataset_id and self.get_profile(dataset_id) is None:
            raise ValueError(f"Cannot bind rule file to missing dataset_id: {dataset_id}")

        raw_text = _read_text_file(source, suffix=suffix)
        parsed_rule, warnings = _parse_rule_text(raw_text, suffix=suffix, rule_scope=scope)
        _validate_rule_payload(parsed_rule, rule_scope=scope)

        file_id = _new_rule_file_id()
        rule_dir = self.rules_root / file_id
        source_dir = rule_dir / "source_file"
        source_dir.mkdir(parents=True, exist_ok=True)
        stored_source = source_dir / display_name
        if source.resolve() != stored_source.resolve():
            shutil.copy2(source, stored_source)

        record = StoredRuleFile(
            file_id=file_id,
            file_name=display_name,
            rule_scope=scope,
            raw_text=raw_text,
            parsed_rule=parsed_rule,
            storage_path=stored_source,
            created_at=datetime.now(timezone.utc).isoformat(),
            dataset_id=dataset_id,
            warnings=warnings,
        )
        self._write_rule_record(record, rule_dir / "record.json")
        self._rule_files[file_id] = record
        if dataset_id:
            self._bind_rule_file(dataset_id=dataset_id, rule_file_id=file_id, rule_scope=scope)
        return record

    def save_rule_files(
        self,
        file_paths: list[str | Path],
        *,
        rule_scope: str,
        original_filenames: list[str | None] | None = None,
        dataset_id: str = "",
    ) -> list[StoredRuleFile]:
        """Persist multiple rule files under one explicit scope."""

        if not file_paths:
            raise ValueError("At least one rule file is required.")
        if original_filenames is not None and len(original_filenames) != len(file_paths):
            raise ValueError("original_filenames must have the same length as file_paths.")
        return [
            self.save_rule_file(
                file_path,
                rule_scope=rule_scope,
                original_filename=None if original_filenames is None else original_filenames[index],
                dataset_id=dataset_id,
            )
            for index, file_path in enumerate(file_paths)
        ]

    def save_dabstep_context_files(
        self,
        file_paths: list[str | Path],
        *,
        dataset_id: str | None = None,
        original_filenames: list[str | None] | None = None,
    ) -> StoredDataset:
        """Persist a DABstep-style context package uploaded through the workbench."""

        file_map, extra_upload_names = _dabstep_file_map(file_paths, original_filenames)
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

        extra_source_files: list[str] = []
        ignored_names: list[str] = []
        if extra_upload_names:
            source_dir = dataset_dir / "source_file"
            source_dir.mkdir(parents=True, exist_ok=True)
            for index, file_path in enumerate(file_paths):
                display_name = Path(
                    str((None if original_filenames is None else original_filenames[index]) or Path(file_path).name)
                ).name
                if display_name.lower() in DABSTEP_CONTEXT_REQUIRED_FILES:
                    continue
                suffix = Path(display_name).suffix.lower() or Path(file_path).suffix.lower()
                if suffix not in DATASET_FILE_EXTENSIONS and suffix not in RULE_FILE_EXTENSIONS:
                    ignored_names.append(display_name)
                    continue
                source = Path(file_path)
                stored_source = _unique_child_path(source_dir, display_name)
                if source.resolve() != stored_source.resolve():
                    shutil.copy2(source, stored_source)
                extra_source_files.append(stored_source.name)

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
        if extra_source_files:
            warnings.append("已额外保存非 DAB 必需来源文件：" + ", ".join(extra_source_files) + "。")
        if ignored_names:
            warnings.append("已忽略暂不支持的非 DAB context 文件：" + ", ".join(ignored_names) + "。")
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
                    "extra_source_files": extra_source_files,
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
        if record is None:
            record = self._load_uploaded_table_record_from_disk(dataset_id)
        return None if record is None else record.tables

    def get_analysis_context(self, dataset_id: str) -> dict[str, Any] | None:
        """Return the executor context for a stored dataset."""

        record = self._datasets.get(dataset_id)
        if record is None:
            record = self._load_dabstep_record_from_disk(dataset_id)
        if record is None:
            record = self._load_uploaded_table_record_from_disk(dataset_id)
        if record is None:
            return None
        if record.analysis_context is not None:
            return record.analysis_context
        return _analysis_context_for_tables(record.tables)

    def get_rule_file(self, file_id: str) -> StoredRuleFile | None:
        """Return one stored rule file by explicit file id."""

        if not file_id:
            return None
        record = self._rule_files.get(file_id)
        if record is not None:
            return record
        record_path = self.rules_root / file_id / "record.json"
        if not record_path.exists():
            return None
        data = json.loads(record_path.read_text(encoding="utf-8"))
        record = StoredRuleFile(
            file_id=str(data.get("file_id") or file_id),
            file_name=str(data.get("file_name") or ""),
            file_role=str(data.get("file_role") or RULE_FILE_ROLE),
            rule_scope=str(data.get("rule_scope") or ""),
            raw_text=str(data.get("raw_text") or ""),
            parsed_rule=data.get("parsed_rule"),
            storage_path=Path(str(data.get("storage_path") or "")),
            created_at=str(data.get("created_at") or ""),
            dataset_id=str(data.get("dataset_id") or ""),
            warnings=list(data.get("warnings") or []),
            errors=list(data.get("errors") or []),
        )
        self._rule_files[file_id] = record
        return record

    def get_rule_context(self, file_id: str, *, expected_scope: str) -> dict[str, Any]:
        """Return a validated rule context for analysis or benchmark execution."""

        record = self.get_rule_file(file_id)
        if record is None:
            raise ValueError(f"Rule file not found: {file_id}")
        expected_scope = _normalize_rule_scope(expected_scope)
        if record.rule_scope != expected_scope:
            raise ValueError(
                f"Rule file {file_id} has rule_scope={record.rule_scope}; expected {expected_scope}."
            )
        return {
            "enabled": True,
            "file_id": record.file_id,
            "file_name": record.file_name,
            "file_role": record.file_role,
            "rule_scope": record.rule_scope,
            "raw_text": record.raw_text,
            "parsed_rule": record.parsed_rule,
            "warnings": list(record.warnings),
        }

    def get_bound_rule_file_ids(self, dataset_id: str, *, rule_scope: str) -> list[str]:
        """Return rule file ids previously bound to a dataset."""

        if not dataset_id:
            return []
        scope = _normalize_rule_scope(rule_scope)
        bindings_path = self.datasets_root / dataset_id / "rule_bindings.json"
        if not bindings_path.exists():
            return []
        try:
            bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        values = bindings.get(scope)
        if not isinstance(values, list):
            return []
        return [str(value) for value in values if str(value)]

    def get_dataset_kind(self, dataset_id: str) -> str:
        """Return the dataset kind used to select the analysis context."""

        record = self._datasets.get(dataset_id)
        if record is None:
            record = self._load_dabstep_record_from_disk(dataset_id)
        if record is None:
            record = self._load_uploaded_table_record_from_disk(dataset_id)
        return "uploaded_tables" if record is None else record.dataset_kind

    def get_context_dir(self, dataset_id: str) -> Path | None:
        """Return a persisted context directory for rule-package datasets."""

        record = self._datasets.get(dataset_id)
        if record is None:
            record = self._load_dabstep_record_from_disk(dataset_id)
        if record is None:
            record = self._load_uploaded_table_record_from_disk(dataset_id)
        return None if record is None else record.context_dir

    def get_dataset_sources(self, dataset_id: str) -> dict[str, Any]:
        """Return user-answerable source files attached to a dataset."""

        record = self._datasets.get(dataset_id)
        if record is None:
            record = self._load_dabstep_record_from_disk(dataset_id)
        if record is None:
            record = self._load_uploaded_table_record_from_disk(dataset_id)
        profile = self.get_profile(dataset_id)
        sources: list[dict[str, Any]] = []
        sources_by_file: dict[str, dict[str, Any]] = {}
        dataset_dir = self.datasets_root / dataset_id
        stored_display_names = _stored_display_names(dataset_dir / "multi_source.json")

        def add_or_update(entry: dict[str, Any]) -> None:
            file_name = str(entry.get("file_name") or entry.get("source_file") or "").strip()
            if not file_name:
                return
            existing = sources_by_file.get(file_name)
            if existing is None:
                sources_by_file[file_name] = entry
                sources.append(entry)
                return
            existing.update({key: value for key, value in entry.items() if value not in (None, "", [])})

        for table in _profile_tables(profile):
            table_name = str(table.get("table_name") or table.get("name") or "").strip()
            source_file = str(table.get("source_file") or table.get("file_name") or table_name).strip()
            row_count = _safe_int(table.get("row_count"))
            column_count = _safe_int(table.get("column_count"))
            columns = [
                str(column.get("name") or "")
                for column in table.get("columns") or []
                if isinstance(column, dict) and str(column.get("name") or "").strip()
            ]
            add_or_update(
                {
                    "file_name": source_file,
                    "source_type": "table",
                    "source_role": _source_role_for_file(source_file, table_name=table_name),
                    "read_status": "read",
                    "table_name": table_name,
                    "row_count": row_count,
                    "column_count": column_count,
                    "key_fields": columns[:8],
                    "purpose": _source_purpose_for_file(source_file, table_name=table_name),
                    "content_summary": f"已解析为表 {table_name or source_file}，{row_count:,} 行、{column_count} 列。",
                }
            )

        source_dir = dataset_dir / "source_file"
        if source_dir.exists():
            for path in sorted(item for item in source_dir.iterdir() if item.is_file()):
                display_name = stored_display_names.get(path.name, path.name)
                if display_name in sources_by_file:
                    sources_by_file[display_name]["storage_path"] = str(path)
                    continue
                entry = _source_entry_from_path(path, source_type="source")
                entry["file_name"] = display_name
                add_or_update(entry)

        context_marker = dataset_dir / "dab_context.json"
        context_dir = dataset_dir / "dab_context"
        ignored_files: list[str] = []
        if context_marker.exists() and context_dir.exists():
            try:
                marker = json.loads(context_marker.read_text(encoding="utf-8"))
                ignored_files = [str(value) for value in marker.get("ignored_files") or []]
                context_files = [str(value) for value in marker.get("context_files") or []]
            except Exception:
                context_files = sorted(DABSTEP_CONTEXT_REQUIRED_FILES)
            for file_name in context_files:
                path = context_dir / file_name
                if not path.exists():
                    continue
                entry = _source_entry_from_path(
                    path,
                    source_type="table" if file_name in DABSTEP_CONTEXT_TABLE_FILES else "knowledge",
                )
                existing = sources_by_file.get(file_name)
                if existing:
                    existing.update(
                        {
                            "storage_path": str(path),
                            "source_role": entry.get("source_role") or existing.get("source_role"),
                            "purpose": entry.get("purpose") or existing.get("purpose"),
                            "content_summary": existing.get("content_summary") or entry.get("content_summary"),
                            "content_excerpt": entry.get("content_excerpt") or existing.get("content_excerpt"),
                        }
                    )
                else:
                    add_or_update(entry)

        for rule_scope in (USER_ANALYSIS_RULE_SCOPE, BENCHMARK_RULE_SCOPE):
            for file_id in self.get_bound_rule_file_ids(dataset_id, rule_scope=rule_scope):
                rule = self.get_rule_file(file_id)
                if rule is None:
                    continue
                add_or_update(
                    {
                        "file_name": rule.file_name,
                        "source_type": "rule",
                        "source_role": "用户分析规则" if rule_scope == USER_ANALYSIS_RULE_SCOPE else "评测规则",
                        "read_status": "read",
                        "storage_path": str(rule.storage_path),
                        "rule_scope": rule_scope,
                        "purpose": _source_purpose_for_file(rule.file_name, source_type="rule"),
                        "content_summary": _text_source_summary(rule.raw_text, suffix=Path(rule.file_name).suffix.lower()),
                        "content_excerpt": _safe_excerpt(rule.raw_text),
                    }
                )

        return {
            "dataset_id": dataset_id,
            "dataset_kind": "uploaded_tables" if record is None else record.dataset_kind,
            "sources": sources,
            "ignored_files": ignored_files,
        }

    def write_run_trace(self, trace: Any) -> Path:
        """Write a trace summary under storage/runs/{run_id}/trace.json."""

        return write_trace(trace, self.runs_root)

    def write_benchmark_report(self, run_id: str, report: dict[str, Any]) -> Path:
        """Persist an internal benchmark report outside ordinary chat traces."""

        report_dir = self.root / "benchmarks" / run_id
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "report.json"
        report_path.write_text(json.dumps(to_json_ready(report), ensure_ascii=False, indent=2), encoding="utf-8")
        return report_path

    def _write_rule_record(self, record: StoredRuleFile, record_path: Path) -> None:
        record_path.write_text(
            json.dumps(
                {
                    "file_id": record.file_id,
                    "file_name": record.file_name,
                    "file_role": record.file_role,
                    "rule_scope": record.rule_scope,
                    "dataset_id": record.dataset_id,
                    "raw_text": record.raw_text,
                    "parsed_rule": record.parsed_rule,
                    "storage_path": str(record.storage_path),
                    "created_at": record.created_at,
                    "warnings": record.warnings,
                    "errors": record.errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _bind_rule_file(self, *, dataset_id: str, rule_file_id: str, rule_scope: str) -> None:
        dataset_dir = self.datasets_root / dataset_id
        dataset_dir.mkdir(parents=True, exist_ok=True)
        bindings_path = dataset_dir / "rule_bindings.json"
        if bindings_path.exists():
            bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
        else:
            bindings = {USER_ANALYSIS_RULE_SCOPE: [], BENCHMARK_RULE_SCOPE: []}
        scoped = list(bindings.get(rule_scope) or [])
        if rule_file_id not in scoped:
            scoped.append(rule_file_id)
        bindings[rule_scope] = scoped
        bindings_path.write_text(json.dumps(bindings, ensure_ascii=False, indent=2), encoding="utf-8")

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

    def _load_uploaded_table_record_from_disk(self, dataset_id: str) -> StoredDataset | None:
        """Restore ordinary uploaded CSV/Excel datasets from persisted source files."""

        dataset_dir = self.datasets_root / dataset_id
        profile = self.get_profile(dataset_id)
        source_dir = dataset_dir / "source_file"
        if profile is None or not source_dir.exists():
            return None
        source_paths = sorted(path for path in source_dir.iterdir() if path.is_file())
        if not source_paths:
            return None
        source_names: list[str | None] | None = None
        source_marker = dataset_dir / "multi_source.json"
        if source_marker.exists():
            marker = json.loads(source_marker.read_text(encoding="utf-8"))
            if str(marker.get("dataset_kind") or "") == SOURCE_ONLY_DATASET_KIND:
                record = StoredDataset(
                    dataset_id=dataset_id,
                    profile=profile,
                    tables={},
                    source_path=source_marker,
                    analysis_context=_analysis_context_for_tables({}),
                    dataset_kind=SOURCE_ONLY_DATASET_KIND,
                )
                self._datasets[dataset_id] = record
                return record
            restored_pairs = _restored_source_pairs_from_marker(source_dir, marker)
            if restored_pairs:
                source_paths = [pair[0] for pair in restored_pairs]
                source_names = [pair[1] for pair in restored_pairs]
            else:
                marker_names = [str(value) for value in marker.get("source_files") or []]
                inferred_names = _infer_legacy_source_names(source_paths, profile, marker_names)
                if inferred_names and len(inferred_names) == len(source_paths):
                    source_names = inferred_names
                elif len(marker_names) == len(source_paths):
                    source_names = marker_names
        elif isinstance(profile, dict):
            file_name = str(profile.get("file_name") or "")
            if file_name and len(source_paths) == 1:
                source_names = [file_name]

        try:
            parsed = parse_dataset_files(source_paths, dataset_id=dataset_id, source_names=source_names)
        except Exception:
            return None
        record = StoredDataset(
            dataset_id=dataset_id,
            profile=profile,
            tables=parsed.tables,
            source_path=source_marker if source_marker.exists() else source_paths[0],
            analysis_context=_analysis_context_for_tables(parsed.tables),
        )
        self._datasets[dataset_id] = record
        return record


def _profile_tables(profile: DatasetProfile | dict[str, Any] | None) -> list[dict[str, Any]]:
    tables = _profile_value(profile, "tables") or []
    result: list[dict[str, Any]] = []
    for table in tables:
        if isinstance(table, dict):
            result.append(table)
        elif table is not None:
            try:
                result.append(to_json_ready(table))
            except Exception:
                continue
    return result


def _stored_display_names(source_marker: Path) -> dict[str, str]:
    if not source_marker.exists():
        return {}
    try:
        marker = json.loads(source_marker.read_text(encoding="utf-8"))
    except Exception:
        return {}
    source_files = [str(value) for value in marker.get("source_files") or []]
    stored_files = [str(value) for value in marker.get("stored_files") or []]
    if source_files and stored_files and len(source_files) == len(stored_files):
        return {stored: source for stored, source in zip(stored_files, source_files)}
    return {}


def _unique_child_path(directory: Path, display_name: str) -> Path:
    candidate = directory / Path(display_name).name
    if not candidate.exists():
        return candidate
    stem = candidate.stem or "file"
    suffix = candidate.suffix
    index = 2
    while True:
        alternate = directory / f"{stem}-{index}{suffix}"
        if not alternate.exists():
            return alternate
        index += 1


def _source_entry_from_path(path: Path, *, source_type: str) -> dict[str, Any]:
    suffix = path.suffix.lower()
    text = _read_source_text(path, suffix=suffix)
    return {
        "file_name": path.name,
        "source_type": source_type,
        "source_role": _source_role_for_file(path.name, source_type=source_type),
        "read_status": "read" if text.strip() else "metadata_only",
        "storage_path": str(path),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "purpose": _source_purpose_for_file(path.name, source_type=source_type),
        "content_summary": _text_source_summary(text, suffix=suffix) if text.strip() else _metadata_only_summary(suffix),
        "content_excerpt": _safe_excerpt(text),
    }


def _source_role_for_file(file_name: str, *, table_name: str = "", source_type: str = "") -> str:
    name = Path(str(file_name or table_name)).name.lower()
    stem = Path(name).stem
    if name == "payments.csv" or stem == "payments":
        return "支付交易事实表"
    if name == "merchant_category_codes.csv" or stem == "merchant_category_codes":
        return "MCC 行业代码维表"
    if name == "acquirer_countries.csv" or stem == "acquirer_countries":
        return "收单国家/地区维表"
    if name == "fees.json":
        return "费率规则文件"
    if name == "merchant_data.json":
        return "商户属性文件"
    if name == "manual.md":
        return "业务说明手册"
    if source_type == "rule":
        return "用户规则/说明文件"
    if source_type == "knowledge":
        return "说明/知识文件"
    if any(token in name for token in ("manual", "guide", "readme", "说明", "手册")):
        return "说明文档"
    if any(token in name for token in ("rule", "fee", "口径", "规则")):
        return "规则文件"
    if name.endswith(SOURCE_DOCUMENT_SUFFIXES):
        return "文档说明"
    return "结构化数据表" if name.endswith((".csv", ".xlsx", ".xls", ".json", ".parquet", ".arrow", ".feather")) else "上传来源文件"


def _source_purpose_for_file(file_name: str, *, table_name: str = "", source_type: str = "") -> str:
    name = Path(str(file_name or table_name)).name.lower()
    stem = Path(name).stem
    if name == "payments.csv" or stem == "payments":
        return "承载每笔支付/交易记录，是后续金额、拒付、欺诈、ACI 等分析的主事实表。"
    if name == "merchant_category_codes.csv" or stem == "merchant_category_codes":
        return "解释 MCC 行业代码，把交易里的行业编码翻译成可读行业类别。"
    if name == "acquirer_countries.csv" or stem == "acquirer_countries":
        return "解释收单国家代码，支持按国家/地区维度做筛选、分组或规则判断。"
    if name == "fees.json":
        return "定义费用/费率规则，用来解释不同卡组织、账户类型、ACI 或跨境条件下的计费口径。"
    if name == "merchant_data.json":
        return "补充商户属性，例如账户类型、抓取延迟、MCC 等，用于把交易和商户规则对齐。"
    if name == "manual.md":
        return "提供业务手册和字段/规则说明，是回答字段含义、取值解释和约束边界的知识来源。"
    if source_type == "rule":
        return "作为用户上传的分析口径或业务说明，参与回答解释和后续分析约束。"
    if source_type == "knowledge":
        return "作为非表格知识来源，补充字段含义、业务口径或规则约束。"
    if name.endswith(SOURCE_DOCUMENT_SUFFIXES):
        return "补充说明文档，用于解释表字段、业务背景、规则或分析边界。"
    return "可解析的表格/结构化来源，用于计算、统计、join 或字段画像。"


def _read_source_text(path: Path, *, suffix: str | None = None) -> str:
    suffix = (suffix or path.suffix).lower()
    if suffix in {".docx", ".docm"}:
        return _read_docx_text(path)
    if suffix == ".doc":
        return _read_legacy_doc_text(path)
    if suffix == ".odt":
        return _read_odt_text(path)
    if suffix == ".pdf":
        return _read_pdf_text(path)
    if suffix == ".pages":
        return _read_pages_text(path)
    if suffix == ".rtf":
        return _read_rtf_text(path)
    if suffix in {".html", ".htm"}:
        return _read_html_text(path)
    if suffix in {".json", ".yaml", ".yml", ".txt", ".md", ".csv"}:
        return _read_plain_text_best_effort(path)
    return _read_plain_text_best_effort(path)


def _read_plain_text_best_effort(path: Path) -> str:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        return ""
    try:
        return path.read_text(encoding="utf-8-sig")
    except Exception:
        return ""


def _read_docx_text(path: Path) -> str:
    if not zipfile.is_zipfile(path):
        return ""
    try:
        with zipfile.ZipFile(path) as archive:
            xml_payload = archive.read("word/document.xml")
    except Exception:
        return ""
    try:
        root = ElementTree.fromstring(xml_payload)
    except Exception:
        return ""
    texts: list[str] = []
    for element in root.iter():
        if element.tag.endswith("}t") and element.text:
            texts.append(element.text)
    return _clean_whitespace(" ".join(texts))


def _read_legacy_doc_text(path: Path) -> str:
    try:
        return _clean_whitespace(_binary_text_strings(path.read_bytes()))
    except Exception:
        return ""


def _read_odt_text(path: Path) -> str:
    if not zipfile.is_zipfile(path):
        return ""
    try:
        with zipfile.ZipFile(path) as archive:
            xml_payload = archive.read("content.xml")
    except Exception:
        return ""
    try:
        root = ElementTree.fromstring(xml_payload)
    except Exception:
        return ""
    texts = [element.text for element in root.iter() if element.text]
    return _clean_whitespace(" ".join(texts))


def _read_pdf_text(path: Path) -> str:
    try:
        data = path.read_bytes()
    except Exception:
        return ""
    return _read_pdf_bytes(data)


def _read_pdf_bytes(data: bytes) -> str:
    chunks: list[str] = []
    for raw in re.findall(rb"\((.{1,300}?)\)\s*Tj", data, flags=re.DOTALL)[:80]:
        text = raw.replace(rb"\\(", b"(").replace(rb"\\)", b")")
        for encoding in ("utf-8", "latin-1"):
            try:
                decoded = text.decode(encoding, errors="ignore")
                break
            except Exception:
                decoded = ""
        if decoded:
            chunks.append(decoded)
    if chunks:
        return _clean_whitespace(" ".join(chunks))
    return _clean_whitespace(_binary_text_strings(data))


def _read_pages_text(path: Path) -> str:
    try:
        data = path.read_bytes()
    except Exception:
        return ""
    texts: list[str] = []
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    lowered = name.lower()
                    if not lowered.endswith((".txt", ".xml", ".json", ".plist", ".html")):
                        if lowered.endswith(".pdf") and archive.getinfo(name).file_size <= 5_000_000:
                            texts.append(_read_pdf_bytes(archive.read(name)))
                        continue
                    if archive.getinfo(name).file_size > 500_000:
                        continue
                    try:
                        texts.append(archive.read(name).decode("utf-8", errors="ignore"))
                    except Exception:
                        continue
        except Exception:
            pass
    if not texts:
        texts.append(_binary_text_strings(data))
    return _clean_whitespace(" ".join(texts))


def _read_rtf_text(path: Path) -> str:
    text = _read_plain_text_best_effort(path)
    if not text:
        return ""
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)
    text = text.replace("\\{", "{").replace("\\}", "}").replace("\\\\", "\\")
    text = re.sub(r"[{}]", " ", text)
    return _clean_whitespace(text)


def _read_html_text(path: Path) -> str:
    text = _read_plain_text_best_effort(path)
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    return _clean_whitespace(text)


def _binary_text_strings(data: bytes) -> str:
    decoded = data[:2_000_000].decode("utf-8", errors="ignore")
    chunks = re.findall(r"[\w\u4e00-\u9fff][\w\u4e00-\u9fff\s,.;:!?()/%\-]{3,}", decoded)
    return " ".join(chunk.strip() for chunk in chunks[:120])


def _text_source_summary(text: str, *, suffix: str) -> str:
    cleaned = _clean_whitespace(text)
    if not cleaned:
        return _metadata_only_summary(suffix)
    if suffix == ".json":
        return _json_source_summary(cleaned)
    if suffix in {".yaml", ".yml"}:
        first_lines = [line.strip() for line in cleaned.splitlines() if line.strip()][:4]
        return "YAML/规则文本；开头内容：" + "；".join(first_lines)
    line_count = len([line for line in text.splitlines() if line.strip()])
    return f"文本内容已读取，约 {line_count} 个非空行；开头内容：{_safe_excerpt(cleaned, limit=180)}"


def _json_source_summary(text: str) -> str:
    try:
        payload = json.loads(text)
    except Exception:
        return "JSON 文件已作为文本读取，但内容不是标准 JSON。"
    if isinstance(payload, list):
        sample = payload[0] if payload else {}
        keys = list(sample.keys())[:8] if isinstance(sample, dict) else []
        suffix = "；样例字段：" + "、".join(str(key) for key in keys) if keys else ""
        return f"JSON 数组，包含 {len(payload):,} 条记录{suffix}。"
    if isinstance(payload, dict):
        keys = list(payload.keys())[:10]
        return "JSON 对象；主要键：" + ("、".join(str(key) for key in keys) if keys else "无")
    return f"JSON {type(payload).__name__} 值。"


def _metadata_only_summary(suffix: str) -> str:
    if suffix == ".pages":
        return "已识别 Pages 文件，但当前只能抽取可读预览/元数据；若文件不含明文预览，需转换为 txt/docx/pdf 后读取全文。"
    if suffix == ".pdf":
        return "已识别 PDF 文件，并尝试抽取文本；扫描版或复杂编码 PDF 可能只能读取元数据。"
    if suffix in {".doc", ".docx", ".docm"}:
        return "已识别 Word 文档，但未抽取到正文文本；可能是空文档、受保护文档、旧版二进制 doc 或非标准 Word 文件。"
    if suffix == ".odt":
        return "已识别 ODT 文档，但未抽取到正文文本；可能是空文档或非标准 ODT 文件。"
    if suffix == ".rtf":
        return "已识别 RTF 文档，但未抽取到正文文本；可能是空文档或编码异常。"
    if suffix in {".html", ".htm"}:
        return "已识别 HTML 文件，但未抽取到正文文本；可能主要包含脚本、样式或不可读标记。"
    return "已识别来源文件，但未抽取到可展示文本。"


def _safe_excerpt(text: str, *, limit: int = 240) -> str:
    cleaned = _clean_whitespace(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def _clean_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _safe_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except Exception:
        return 0


def _restored_source_pairs_from_marker(source_dir: Path, marker: dict[str, Any]) -> list[tuple[Path, str]] | None:
    """Return persisted path/display-name pairs when the marker records them."""

    source_files = [str(value) for value in marker.get("source_files") or []]
    stored_files = [str(value) for value in marker.get("stored_files") or []]
    if source_files and stored_files and len(source_files) == len(stored_files):
        pairs = [(source_dir / stored_file, source_file) for stored_file, source_file in zip(stored_files, source_files)]
        if all(path.exists() for path, _ in pairs):
            return pairs

    records = marker.get("source_file_map")
    if not isinstance(records, list):
        return None
    stored_by_source: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        source_file = str(record.get("source_file") or "")
        stored_file = str(record.get("stored_file") or "")
        if source_file and stored_file and source_file not in stored_by_source:
            stored_by_source[source_file] = stored_file
    pairs = []
    seen_stored_files: set[str] = set()
    for source_file in source_files or list(stored_by_source):
        stored_file = stored_by_source.get(source_file)
        if not stored_file or stored_file in seen_stored_files:
            continue
        path = source_dir / stored_file
        if not path.exists():
            return None
        pairs.append((path, source_file))
        seen_stored_files.add(stored_file)
    return pairs or None


def _infer_legacy_source_names(
    source_paths: list[Path],
    profile: DatasetProfile | dict[str, Any] | None,
    marker_names: list[str],
) -> list[str | None] | None:
    """Recover old multi-file uploads whose marker lacks stored filename mapping."""

    table_headers = _profile_table_headers(profile, marker_names)
    if not table_headers:
        return None
    used_sources: set[str] = set()
    inferred: list[str | None] = []
    for path in source_paths:
        header = set(_read_header_columns(path))
        if not header:
            return None
        best: dict[str, Any] | None = None
        best_score = (-1, -999999)
        for candidate in table_headers:
            source_file = str(candidate["source_file"])
            if source_file in used_sources:
                continue
            columns = set(candidate["columns"])
            overlap = len(header & columns)
            if overlap <= 0:
                continue
            score = (overlap, -abs(len(header) - len(columns)))
            if score > best_score:
                best = candidate
                best_score = score
        if best is None:
            return None
        source_file = str(best["source_file"])
        inferred.append(source_file)
        used_sources.add(source_file)
    return inferred if len(inferred) == len(source_paths) else None


def _profile_table_headers(profile: DatasetProfile | dict[str, Any] | None, marker_names: list[str]) -> list[dict[str, Any]]:
    tables = _profile_value(profile, "tables") or []
    marker_set = set(marker_names)
    headers: list[dict[str, Any]] = []
    for table in tables:
        source_file = str(_profile_value(table, "source_file") or "")
        if not source_file or (marker_set and source_file not in marker_set):
            continue
        columns = []
        for column in _profile_value(table, "columns") or []:
            name = str(_profile_value(column, "name") or "")
            if name:
                columns.append(name)
        if columns:
            headers.append({"source_file": source_file, "columns": columns})
    return headers


def _profile_value(payload: Any, key: str) -> Any:
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)


def _read_header_columns(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        try:
            excel = pd.ExcelFile(path)
            if not excel.sheet_names:
                return []
            return [str(column) for column in pd.read_excel(path, sheet_name=excel.sheet_names[0], nrows=0).columns]
        except Exception:
            return []
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return [str(column) for column in pd.read_csv(path, encoding=encoding, nrows=0).columns]
        except UnicodeDecodeError:
            continue
        except Exception:
            return []
    return []


def _new_dataset_id() -> str:
    return "ds_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]


def _new_rule_file_id() -> str:
    return "rule_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]


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
    complete = DABSTEP_CONTEXT_REQUIRED_FILES.issubset(set(names))
    partial = not complete and bool(present)
    return {
        "complete": complete,
        "partial": partial,
        "missing": sorted(DABSTEP_CONTEXT_REQUIRED_FILES - set(names)),
    }


def _normalize_rule_scope(rule_scope: str) -> str:
    scope = (rule_scope or "").strip()
    if scope not in VALID_RULE_SCOPES:
        raise ValueError("Rule files require rule_scope=user_analysis or rule_scope=benchmark.")
    return scope


def _read_text_file(path: Path, *, suffix: str | None = None) -> str:
    text = _read_source_text(path, suffix=suffix or path.suffix.lower())
    if not text.strip():
        raise ValueError("Rule/source file content could not be extracted as text.")
    return text


def _parse_rule_text(raw_text: str, *, suffix: str, rule_scope: str) -> tuple[Any, list[str]]:
    warnings: list[str] = []
    if not raw_text.strip():
        raise ValueError("Rule file is empty.")
    if suffix == ".json":
        return json.loads(raw_text), warnings
    if suffix in {".yaml", ".yml"}:
        parsed = _parse_simple_yaml(raw_text)
        if parsed is None:
            warnings.append("YAML was stored as raw text because it is outside the supported simple YAML subset.")
            return {"raw_text": raw_text}, warnings
        return parsed, warnings
    return {"raw_text": raw_text}, warnings


def _validate_rule_payload(parsed_rule: Any, *, rule_scope: str) -> None:
    if rule_scope == USER_ANALYSIS_RULE_SCOPE:
        # User analysis rules are advisory context. The original raw text is
        # always stored, so JSON/YAML arrays or scalars can still constrain the
        # analysis chain without being treated as benchmark definitions.
        return
    if not isinstance(parsed_rule, dict):
        raise ValueError("Benchmark rule must parse to a JSON/YAML object.")
    questions = parsed_rule.get("questions") or parsed_rule.get("test_questions") or parsed_rule.get("cases")
    if not isinstance(questions, list) or not questions:
        raise ValueError("Benchmark rule must include a non-empty questions list.")
    for index, item in enumerate(questions, start=1):
        if isinstance(item, str) and item.strip():
            continue
        if isinstance(item, dict) and str(item.get("question") or "").strip():
            continue
        raise ValueError(f"Benchmark rule question {index} must be a string or an object with question.")


def _parse_simple_yaml(raw_text: str) -> dict[str, Any] | None:
    """Parse the simple YAML subset used by rule files without adding a dependency."""

    root: dict[str, Any] = {}
    current_key: str | None = None
    current_list_item: dict[str, Any] | None = None
    for raw_line in raw_text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if indent == 0:
            current_list_item = None
            if ":" not in line:
                return None
            key, value = line.split(":", 1)
            current_key = key.strip()
            value = value.strip()
            if not current_key:
                return None
            root[current_key] = _parse_scalar(value) if value else {}
            continue
        if current_key is None:
            return None
        container = root.setdefault(current_key, [])
        if line.startswith("- "):
            item_text = line[2:].strip()
            if not isinstance(container, list):
                container = []
                root[current_key] = container
            if ":" in item_text:
                key, value = item_text.split(":", 1)
                current_list_item = {key.strip(): _parse_scalar(value.strip())}
                container.append(current_list_item)
            else:
                current_list_item = None
                container.append(_parse_scalar(item_text))
            continue
        if isinstance(container, dict) and ":" in line:
            key, value = line.split(":", 1)
            child = container.setdefault(key.strip(), [] if not value.strip() else _parse_scalar(value.strip()))
            if child is container:
                return None
            continue
        if current_list_item is not None and ":" in line:
            key, value = line.split(":", 1)
            current_list_item[key.strip()] = _parse_scalar(value.strip())
            continue
        return None
    return root


def _parse_scalar(value: str) -> Any:
    if value == "":
        return ""
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value.strip("\"'")


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
