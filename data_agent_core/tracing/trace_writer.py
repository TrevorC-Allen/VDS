"""Trace writer for trace.json persistence."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return str(value)


def write_trace(trace: Any, output_dir: str | Path) -> Path:
    """Write an auditable trace summary to {output_dir}/{run_id}/trace.json."""

    data = trace.to_dict() if hasattr(trace, "to_dict") else trace
    run_id = data["run_id"]
    run_dir = Path(output_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "trace.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=_json_default))
    return path
