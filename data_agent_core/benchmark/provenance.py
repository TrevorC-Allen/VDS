"""Trace-safe benchmark provenance helpers.

The helpers record how an artifact was generated without storing secrets,
hidden answers, public-proxy answer pools, or raw reasoning.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


REPORT_SELF_HASH_KEYS = {"report_content_sha256"}


def command_line() -> str:
    """Return a shell-quoted command line for provenance records."""

    return " ".join(shlex.quote(part) for part in sys.argv)


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 hash of a file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(payload: Any) -> str:
    """Hash a JSON payload using stable key ordering."""

    encoded = json.dumps(_strip_report_self_hash(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_submission_provenance(
    *,
    predictions_path: str | Path | None = None,
    command: str | None = None,
    cwd: str | Path | None = None,
    benchmark: str,
    split: str | None = None,
    task_range: list[int] | tuple[int, int] | None = None,
    elapsed_seconds: float | None = None,
) -> dict[str, Any]:
    """Build provenance for benchmark predictions and reports."""

    path = Path(predictions_path) if predictions_path is not None else None
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "benchmark": benchmark,
        "split": split,
        "task_range": list(task_range) if task_range is not None else None,
        "command": command or command_line(),
        "cwd": str(Path(cwd or Path.cwd())),
        "git": _git_state(Path(cwd or Path.cwd())),
        "runtime": _runtime_metadata(),
        "prediction_file": None
        if path is None
        else {
            "path": str(path),
            "sha256": sha256_file(path),
        },
        "report_content_sha256": None,
        "elapsed_seconds": elapsed_seconds,
        "public_proxy_policy": "not_used_in_core_chain",
        "official_hidden_policy": "not_available_locally",
    }


def stamp_report_provenance(report: dict[str, Any]) -> dict[str, Any]:
    """Add a self-excluding content hash to report['provenance']."""

    provenance = dict(report.get("provenance") or {})
    report["provenance"] = provenance
    provenance["report_content_sha256"] = canonical_json_sha256(report)
    return report


def _runtime_metadata() -> dict[str, Any]:
    provider_env = os.environ.get("VDS_LLM_PROVIDER") or "auto"
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "llm_provider_env": provider_env,
        "model_env": {
            "VDS_LLM_MODEL": os.environ.get("VDS_LLM_MODEL"),
            "OPENAI_MODEL": os.environ.get("OPENAI_MODEL"),
            "DEEPSEEK_MODEL": os.environ.get("DEEPSEEK_MODEL"),
        },
        "api_key_presence": {
            "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
            "DEEPSEEK_API_KEY": bool(os.environ.get("DEEPSEEK_API_KEY")),
        },
    }


def _git_state(cwd: Path) -> dict[str, Any]:
    root = _run_git(cwd, "rev-parse", "--show-toplevel")
    commit = _run_git(cwd, "rev-parse", "HEAD")
    branch = _run_git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    dirty = _run_git(cwd, "status", "--porcelain")
    return {
        "root": root,
        "branch": branch,
        "commit": commit,
        "dirty": bool(dirty),
        "dirty_file_count": 0 if not dirty else len([line for line in dirty.splitlines() if line.strip()]),
    }


def _run_git(cwd: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    output = completed.stdout.strip()
    return output or None


def _strip_report_self_hash(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _strip_report_self_hash(item) for key, item in value.items() if key not in REPORT_SELF_HASH_KEYS}
    if isinstance(value, list):
        return [_strip_report_self_hash(item) for item in value]
    return value
