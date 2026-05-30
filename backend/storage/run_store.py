"""Persistent run status store for workbench job execution."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from backend.schemas.data_agent_schema import to_json_ready


RUN_STATUSES = {"queued", "running", "cancel_requested", "cancelled", "completed", "failed"}


class RunStore:
    """JSON-backed status files under storage/runs/{run_id}/status.json."""

    def __init__(self, root: str | Path = "storage/runs") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create_run(
        self,
        run_id: str,
        *,
        request: dict[str, Any],
        project_id: str = "",
        conversation_id: str = "",
        dataset_id: str = "",
        retry_of: str = "",
    ) -> dict[str, Any]:
        safe_id = _safe_run_id(run_id)
        if not safe_id:
            raise ValueError("run_id is required.")
        now = _now_iso()
        retry_of_id = _safe_run_id(retry_of)
        previous_attempt = 0
        if retry_of_id:
            previous = self.get_run(retry_of_id)
            previous_attempt = _safe_int(previous.get("attempt"), 1) if previous else 0
        record = {
            "run_id": safe_id,
            "status": "queued",
            "project_id": str(project_id or ""),
            "conversation_id": str(conversation_id or ""),
            "dataset_id": str(dataset_id or ""),
            "request": to_json_ready(request or {}),
            "retry_of": retry_of_id,
            "attempt": previous_attempt + 1 if retry_of_id else 1,
            "created_at": now,
            "updated_at": now,
            "started_at": "",
            "completed_at": "",
            "cancel_requested_at": "",
            "latest_summary": "任务已进入队列。",
            "latest_stage": "queued",
            "failure_category": "",
            "failure_reason": "",
            "error_message": "",
            "result_available": False,
            "artifacts_manifest": None,
        }
        self._write(record)
        return deepcopy(record)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        safe_id = _safe_run_id(run_id)
        if not safe_id:
            return None
        path = self._status_path(safe_id)
        if not path.exists():
            return None
        try:
            return self._read(path)
        except (OSError, json.JSONDecodeError):
            return None

    def update_run(self, run_id: str, **updates: Any) -> dict[str, Any] | None:
        record = self.get_run(run_id)
        if record is None:
            return None
        now = _now_iso()
        if "status" in updates:
            status = str(updates["status"] or "")
            if status not in RUN_STATUSES:
                raise ValueError(f"Unsupported run status: {status}")
            record["status"] = status
            if status == "running" and not record.get("started_at"):
                record["started_at"] = now
            if status in {"cancelled", "completed", "failed"}:
                record["completed_at"] = now
        for key, value in updates.items():
            if key == "status":
                continue
            if key == "request":
                continue
            record[key] = to_json_ready(value)
        record["updated_at"] = now
        self._write(record)
        return deepcopy(record)

    def request_cancel(self, run_id: str) -> dict[str, Any] | None:
        record = self.get_run(run_id)
        if record is None:
            return None
        if record.get("status") in {"completed", "failed", "cancelled"}:
            return deepcopy(record)
        now = _now_iso()
        record["status"] = "cancel_requested"
        record["cancel_requested_at"] = now
        record["latest_stage"] = "cancel_requested"
        record["latest_summary"] = "已请求取消，后端会在下一个安全边界停止。"
        record["updated_at"] = now
        self._write(record)
        return deepcopy(record)

    def is_cancel_requested(self, run_id: str) -> bool:
        record = self.get_run(run_id)
        return bool(record and record.get("status") == "cancel_requested")

    def write_result(self, run_id: str, result: dict[str, Any]) -> Path:
        safe_id = _safe_run_id(run_id)
        if not safe_id:
            raise ValueError("run_id is required.")
        run_dir = self._run_dir(safe_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        result_path = run_dir / "result.json"
        temp_path = result_path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(to_json_ready(result), ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(result_path)
        return result_path

    def get_result(self, run_id: str) -> dict[str, Any] | None:
        safe_id = _safe_run_id(run_id)
        if not safe_id:
            return None
        result_path = self._run_dir(safe_id) / "result.json"
        if not result_path.exists():
            return None
        try:
            return json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def exports_dir(self, run_id: str) -> Path:
        safe_id = _safe_run_id(run_id)
        if not safe_id:
            raise ValueError("run_id is required.")
        path = self._run_dir(safe_id) / "exports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def mark_orphaned_if_active(self, run_id: str) -> dict[str, Any] | None:
        record = self.get_run(run_id)
        if record is None:
            return None
        if record.get("status") not in {"queued", "running", "cancel_requested"}:
            return deepcopy(record)
        return self.update_run(
            run_id,
            status="failed",
            latest_stage="service_restart",
            latest_summary="服务重启或任务进程已中断，可以重试该请求。",
            failure_category="unknown",
            failure_reason="任务状态存在，但当前进程没有对应的后台任务。",
            error_message="任务已中断，请重试。",
        )

    def _run_dir(self, run_id: str) -> Path:
        return self.root / run_id

    def _status_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "status.json"

    def _read(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, record: dict[str, Any]) -> None:
        safe_id = _safe_run_id(str(record.get("run_id") or ""))
        if not safe_id:
            raise ValueError("run_id is required.")
        run_dir = self._run_dir(safe_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        path = self._status_path(safe_id)
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(to_json_ready(record), ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)


def public_run_status(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    payload = deepcopy(record)
    payload.pop("request", None)
    return payload


def _safe_run_id(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", text):
        return ""
    return text


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
