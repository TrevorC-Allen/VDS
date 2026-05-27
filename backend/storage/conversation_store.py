"""Lightweight persistent conversation store for the workbench shell."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import uuid

from backend.schemas.data_agent_schema import to_json_ready


class ConversationStore:
    """JSON-backed conversation metadata and message history.

    This stays in the backend shell layer. It stores user-visible turns and
    response payloads, but it does not perform analysis, scoring, or recovery.
    """

    def __init__(self, root: str | Path = "storage/conversations") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create_conversation(
        self,
        *,
        title: str = "",
        dataset_id: str = "",
        project_id: str = "",
        owner_id: str = "",
        tenant_id: str = "",
        owner_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create and persist an empty conversation."""

        now = _now_iso()
        conversation_id = _new_conversation_id()
        record = {
            "conversation_id": conversation_id,
            "title": _clean_title(title) or "新对话",
            "dataset_id": str(dataset_id or ""),
            "project_id": _safe_project_id(project_id),
            "owner_id": str(owner_id or ""),
            "tenant_id": str(tenant_id or ""),
            "owner_context": to_json_ready(owner_context or {}),
            "pinned": False,
            "pinned_at": "",
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }
        self._write(record)
        return deepcopy(record)

    def append_turn(
        self,
        *,
        conversation_id: str = "",
        question: str,
        response: dict[str, Any],
        dataset_id: str = "",
        project_id: str = "",
        owner_id: str = "",
        tenant_id: str = "",
        owner_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append one user turn and one assistant response."""

        record = self.get_conversation(conversation_id) if conversation_id else None
        if record is None:
            record = self.create_conversation(
                title=_derive_title(question),
                dataset_id=dataset_id or str(response.get("dataset_id") or ""),
                project_id=project_id,
                owner_id=owner_id,
                tenant_id=tenant_id,
                owner_context=owner_context,
            )

        now = _now_iso()
        effective_dataset_id = str(response.get("dataset_id") or dataset_id or record.get("dataset_id") or "")
        record["dataset_id"] = effective_dataset_id
        if project_id:
            record["project_id"] = _safe_project_id(project_id)
        if owner_id:
            record["owner_id"] = str(owner_id)
        if tenant_id:
            record["tenant_id"] = str(tenant_id)
        if owner_context:
            record["owner_context"] = to_json_ready(owner_context)
        if not _has_user_title(record) and not record.get("messages"):
            record["title"] = _derive_title(question)
        record.setdefault("messages", []).extend(
            [
                {
                    "message_id": _new_message_id(),
                    "role": "user",
                    "content": question,
                    "created_at": now,
                },
                {
                    "message_id": _new_message_id(),
                    "role": "assistant",
                    "content": str(response.get("answer") or ""),
                    "created_at": now,
                    "run_id": response.get("run_id"),
                    "answer_type": response.get("answer_type"),
                    "success": bool(response.get("success")),
                    "payload": to_json_ready(_strip_conversation_metadata(response)),
                },
            ]
        )
        record["updated_at"] = now
        self._write(record)
        return deepcopy(record)

    def list_conversations(
        self,
        *,
        limit: int = 50,
        owner_id: str = "",
        tenant_id: str = "",
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent conversation summaries."""

        records = []
        safe_project_id = None if project_id is None else _safe_project_id(project_id)
        for path in self.root.glob("conv_*.json"):
            try:
                record = self._read(path)
            except (OSError, json.JSONDecodeError):
                continue
            if owner_id and str(record.get("owner_id") or "") != owner_id:
                continue
            if tenant_id and str(record.get("tenant_id") or "") != tenant_id:
                continue
            if project_id is not None and str(record.get("project_id") or "") != str(safe_project_id or ""):
                continue
            records.append(_conversation_summary(record))
        records.sort(
            key=lambda item: (
                bool(item.get("pinned")),
                str(item.get("pinned_at") or item.get("updated_at") or ""),
                str(item.get("updated_at") or ""),
            ),
            reverse=True,
        )
        return records[: max(1, min(int(limit or 50), 200))]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """Return a full conversation record if it exists."""

        safe_id = _safe_conversation_id(conversation_id)
        if not safe_id:
            return None
        path = self.root / f"{safe_id}.json"
        if not path.exists():
            return None
        try:
            return self._read(path)
        except (OSError, json.JSONDecodeError):
            return None

    def save_conversation(self, record: dict[str, Any]) -> dict[str, Any]:
        """Persist a full conversation record after service-level repairs."""

        self._write(record)
        return deepcopy(record)

    def rename_conversation(self, conversation_id: str, title: str) -> dict[str, Any] | None:
        """Persist a user-provided conversation title."""

        record = self.get_conversation(conversation_id)
        clean = _clean_title(title)
        if record is None or not clean:
            return None
        record["title"] = clean
        record["user_title"] = True
        record["updated_at"] = _now_iso()
        self._write(record)
        return deepcopy(record)

    def update_conversation(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        project_id: str | None = None,
        pinned: bool | None = None,
    ) -> dict[str, Any] | None:
        """Update editable conversation metadata."""

        record = self.get_conversation(conversation_id)
        if record is None:
            return None
        if title is not None:
            clean = _clean_title(title)
            if clean:
                record["title"] = clean
                record["user_title"] = True
        if project_id is not None:
            record["project_id"] = _safe_project_id(project_id)
        if pinned is not None:
            record["pinned"] = bool(pinned)
            record["pinned_at"] = _now_iso() if pinned else ""
        record["updated_at"] = _now_iso()
        self._write(record)
        return deepcopy(record)

    def delete_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """Delete one conversation record."""

        safe_id = _safe_conversation_id(conversation_id)
        if not safe_id:
            return None
        path = self.root / f"{safe_id}.json"
        if not path.exists():
            return None
        record = self.get_conversation(safe_id)
        path.unlink()
        return record

    def _read(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, record: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        conversation_id = _safe_conversation_id(str(record.get("conversation_id") or ""))
        if not conversation_id:
            raise ValueError("conversation_id is required.")
        path = self.root / f"{conversation_id}.json"
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(to_json_ready(record), ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)


def _conversation_summary(record: dict[str, Any]) -> dict[str, Any]:
    messages = record.get("messages") or []
    last_message = messages[-1] if messages else {}
    last_assistant = next((message for message in reversed(messages) if message.get("role") == "assistant"), {})
    return {
        "conversation_id": record.get("conversation_id"),
        "title": record.get("title") or "新对话",
        "dataset_id": record.get("dataset_id") or "",
        "project_id": record.get("project_id") or "",
        "pinned": bool(record.get("pinned")),
        "pinned_at": record.get("pinned_at") or "",
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "message_count": len(messages),
        "last_role": last_message.get("role"),
        "last_answer_type": last_assistant.get("answer_type"),
        "last_success": last_assistant.get("success"),
        "last_message": last_message.get("content") or "",
    }


def _strip_conversation_metadata(response: dict[str, Any]) -> dict[str, Any]:
    payload = dict(response)
    payload.pop("conversation_id", None)
    payload.pop("conversation", None)
    return payload


def _has_user_title(record: dict[str, Any]) -> bool:
    return bool(record.get("user_title")) and bool(_clean_title(str(record.get("title") or "")))


def _derive_title(question: str) -> str:
    clean = " ".join(str(question or "").strip().split())
    return _clean_title(clean[:40]) or "新对话"


def _clean_title(title: str) -> str:
    return " ".join(str(title or "").strip().split())[:80]


def _safe_conversation_id(conversation_id: str) -> str:
    value = str(conversation_id or "").strip()
    if not value.startswith("conv_"):
        return ""
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    return value if all(char in allowed for char in value) else ""


def _safe_project_id(project_id: str) -> str:
    value = str(project_id or "").strip()
    if not value.startswith("proj_"):
        return ""
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    return value if all(char in allowed for char in value) else ""


def _new_conversation_id() -> str:
    return "conv_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]


def _new_message_id() -> str:
    return "msg_" + uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
