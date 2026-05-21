"""Temporary file store boundary for uploaded datasets."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from backend.schemas.data_agent_schema import to_json_ready
from data_agent_core.contracts.dataset_contracts import DatasetProfile
from data_agent_core.core.file_parser import ParsedDataset
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
