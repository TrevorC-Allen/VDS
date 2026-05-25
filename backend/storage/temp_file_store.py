"""Temporary file store boundary for uploaded datasets."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
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
                "Rule files must use yaml, yml, json, txt, or md."
            )
        if dataset_id and self.get_profile(dataset_id) is None:
            raise ValueError(f"Cannot bind rule file to missing dataset_id: {dataset_id}")

        raw_text = _read_text_file(source)
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


def _read_text_file(path: Path) -> str:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise ValueError(f"Rule file is not valid text: {last_error}") from last_error
    return path.read_text(encoding="utf-8-sig")


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
        if isinstance(parsed_rule, dict):
            return
        raise ValueError("User analysis rule must parse to a JSON/YAML object or raw text object.")
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
