"""Lightweight persistent project store for the workbench shell."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import uuid

from backend.schemas.data_agent_schema import to_json_ready


class ProjectStore:
    """JSON-backed project workspace metadata.

    This store owns project-scoped references and safe text context. It does
    not parse datasets, execute analysis, or decide business semantics.
    """

    def __init__(self, root: str | Path = "storage/projects") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create_project(
        self,
        *,
        name: str = "",
        description: str = "",
        instructions: str = "",
        owner_id: str = "",
        tenant_id: str = "",
        owner_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create and persist an empty project workspace."""

        now = _now_iso()
        record = {
            "project_id": _new_project_id(),
            "name": _clean_name(name) or "新项目",
            "description": _clean_text(description, 500),
            "instructions": _clean_text(instructions, 4000),
            "instructions_version": 1,
            "instructions_updated_at": now if _clean_text(instructions, 4000) else "",
            "content_hash": _content_hash(_clean_text(instructions, 4000)),
            "memory_mode": "project_only",
            "default_dataset_id": "",
            "owner_id": str(owner_id or ""),
            "tenant_id": str(tenant_id or ""),
            "owner_context": to_json_ready(owner_context or {}),
            "created_at": now,
            "updated_at": now,
            "sources": [],
            "memories": [],
            "conversation_ids": [],
        }
        self._write(record)
        return deepcopy(record)

    def list_projects(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        owner_id: str = "",
        tenant_id: str = "",
    ) -> list[dict[str, Any]]:
        """Return recent project summaries."""

        records = self._filtered_project_summaries(owner_id=owner_id, tenant_id=tenant_id)
        safe_limit = max(1, min(int(limit or 50), 200))
        safe_offset = max(0, int(offset or 0))
        return records[safe_offset : safe_offset + safe_limit]

    def count_projects(self, *, owner_id: str = "", tenant_id: str = "") -> int:
        """Return the full number of filtered projects before pagination."""

        return len(self._filtered_project_summaries(owner_id=owner_id, tenant_id=tenant_id))

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        """Return a full project record if it exists."""

        safe_id = _safe_project_id(project_id)
        if not safe_id:
            return None
        path = self.root / f"{safe_id}.json"
        if not path.exists():
            return None
        try:
            return self._read(path)
        except (OSError, json.JSONDecodeError):
            return None

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        default_dataset_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Update editable project metadata."""

        record = self.get_project(project_id)
        if record is None:
            return None
        if name is not None:
            clean = _clean_name(name)
            if clean:
                record["name"] = clean
        if description is not None:
            record["description"] = _clean_text(description, 500)
        if instructions is not None:
            clean_instructions = _clean_text(instructions, 4000)
            if clean_instructions != str(record.get("instructions") or ""):
                record["instructions_version"] = _safe_int(record.get("instructions_version"), 1) + 1
                record["instructions_updated_at"] = _now_iso()
                record["content_hash"] = _content_hash(clean_instructions)
            record["instructions"] = clean_instructions
        if default_dataset_id is not None:
            record["default_dataset_id"] = _safe_ref(default_dataset_id)
        record["updated_at"] = _now_iso()
        self._write(record)
        return deepcopy(record)

    def delete_project(self, project_id: str) -> bool:
        """Delete one project metadata file.

        Referenced dataset/rule files are intentionally not removed here.
        """

        safe_id = _safe_project_id(project_id)
        if not safe_id:
            return False
        path = self.root / f"{safe_id}.json"
        if not path.exists():
            return False
        path.unlink()
        return True

    def add_source(
        self,
        project_id: str,
        *,
        source_type: str,
        title: str = "",
        dataset_id: str = "",
        file_id: str = "",
        content: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Attach a dataset/rule/text source reference to a project."""

        record = self.get_project(project_id)
        if record is None:
            return None
        now = _now_iso()
        clean_content = _clean_text(content, 8000)
        metadata_payload = to_json_ready(metadata or {})
        replaces_source_id = _safe_source_id(str(metadata_payload.get("replaces_source_id") or ""))
        source_version = _source_version(record, replaces_source_id)
        source = {
            "source_id": _new_source_id(),
            "source_type": _normalize_source_type(source_type),
            "title": _clean_name(title) or _default_source_title(source_type, dataset_id, file_id),
            "dataset_id": _safe_ref(dataset_id),
            "file_id": _safe_ref(file_id),
            "content": clean_content,
            "metadata": metadata_payload,
            "source_version": source_version,
            "content_hash": _content_hash(
                {
                    "source_type": _normalize_source_type(source_type),
                    "title": _clean_name(title),
                    "dataset_id": _safe_ref(dataset_id),
                    "file_id": _safe_ref(file_id),
                    "content": clean_content,
                }
            ),
            "source_status": _normalize_source_status(str(metadata_payload.get("source_status") or "")),
            "replaces_source_id": replaces_source_id,
            "created_at": now,
            "updated_at": now,
        }
        if replaces_source_id:
            for existing in record.setdefault("sources", []):
                if existing.get("source_id") == replaces_source_id:
                    existing["source_status"] = "superseded"
                    existing["updated_at"] = now
        record.setdefault("sources", []).append(source)
        if source["dataset_id"] and not record.get("default_dataset_id"):
            record["default_dataset_id"] = source["dataset_id"]
        record["updated_at"] = now
        self._write(record)
        return deepcopy(source)

    def delete_source(self, project_id: str, source_id: str) -> dict[str, Any] | None:
        """Remove one source reference from a project."""

        record = self.get_project(project_id)
        safe_source_id = _safe_source_id(source_id)
        if record is None or not safe_source_id:
            return None
        sources = list(record.get("sources") or [])
        remaining = [source for source in sources if source.get("source_id") != safe_source_id]
        if len(remaining) == len(sources):
            return None
        record["sources"] = remaining
        if record.get("default_dataset_id") and not any(
            source.get("dataset_id") == record.get("default_dataset_id") for source in remaining
        ):
            record["default_dataset_id"] = next((source.get("dataset_id") for source in remaining if source.get("dataset_id")), "")
        record["updated_at"] = _now_iso()
        self._write(record)
        return deepcopy(record)

    def add_memory(
        self,
        project_id: str,
        *,
        content: str,
        memory_type: str = "pinned",
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Attach project-only memory to a project."""

        record = self.get_project(project_id)
        clean = _clean_text(content, 4000)
        if record is None or not clean:
            return None
        now = _now_iso()
        memory = {
            "memory_id": _new_memory_id(),
            "memory_type": _normalize_memory_type(memory_type),
            "title": _clean_name(title),
            "content": clean,
            "metadata": to_json_ready(metadata or {}),
            "created_at": now,
            "updated_at": now,
        }
        record.setdefault("memories", []).append(memory)
        record["updated_at"] = now
        self._write(record)
        return deepcopy(memory)

    def update_memory(
        self,
        project_id: str,
        memory_id: str,
        *,
        content: str | None = None,
        title: str | None = None,
        memory_type: str | None = None,
    ) -> dict[str, Any] | None:
        """Update one project memory."""

        record = self.get_project(project_id)
        safe_memory_id = _safe_memory_id(memory_id)
        if record is None or not safe_memory_id:
            return None
        for memory in record.get("memories") or []:
            if memory.get("memory_id") != safe_memory_id:
                continue
            if content is not None:
                clean = _clean_text(content, 4000)
                if not clean:
                    return None
                memory["content"] = clean
            if title is not None:
                memory["title"] = _clean_name(title)
            if memory_type is not None:
                memory["memory_type"] = _normalize_memory_type(memory_type)
            memory["updated_at"] = _now_iso()
            record["updated_at"] = memory["updated_at"]
            self._write(record)
            return deepcopy(memory)
        return None

    def delete_memory(self, project_id: str, memory_id: str) -> dict[str, Any] | None:
        """Remove one project memory."""

        record = self.get_project(project_id)
        safe_memory_id = _safe_memory_id(memory_id)
        if record is None or not safe_memory_id:
            return None
        memories = list(record.get("memories") or [])
        remaining = [memory for memory in memories if memory.get("memory_id") != safe_memory_id]
        if len(remaining) == len(memories):
            return None
        record["memories"] = remaining
        record["updated_at"] = _now_iso()
        self._write(record)
        return deepcopy(record)

    def attach_conversation(self, project_id: str, conversation_id: str) -> dict[str, Any] | None:
        """Remember that one conversation belongs to a project."""

        record = self.get_project(project_id)
        safe_conversation_id = _safe_ref(conversation_id)
        if record is None or not safe_conversation_id:
            return None
        conversation_ids = list(record.get("conversation_ids") or [])
        if safe_conversation_id not in conversation_ids:
            conversation_ids.append(safe_conversation_id)
            record["conversation_ids"] = conversation_ids
            record["updated_at"] = _now_iso()
            self._write(record)
        return deepcopy(record)

    def detach_conversation(self, project_id: str, conversation_id: str) -> dict[str, Any] | None:
        """Remove one conversation reference from a project."""

        record = self.get_project(project_id)
        safe_conversation_id = _safe_ref(conversation_id)
        if record is None or not safe_conversation_id:
            return None
        conversation_ids = list(record.get("conversation_ids") or [])
        if safe_conversation_id not in conversation_ids:
            return deepcopy(record)
        record["conversation_ids"] = [item for item in conversation_ids if item != safe_conversation_id]
        record["updated_at"] = _now_iso()
        self._write(record)
        return deepcopy(record)

    def _read(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, record: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        project_id = _safe_project_id(str(record.get("project_id") or ""))
        if not project_id:
            raise ValueError("project_id is required.")
        path = self.root / f"{project_id}.json"
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(to_json_ready(record), ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)

    def _filtered_project_summaries(self, *, owner_id: str = "", tenant_id: str = "") -> list[dict[str, Any]]:
        records = []
        for path in self.root.glob("proj_*.json"):
            try:
                record = self._read(path)
            except (OSError, json.JSONDecodeError):
                continue
            if owner_id and str(record.get("owner_id") or "") != owner_id:
                continue
            if tenant_id and str(record.get("tenant_id") or "") != tenant_id:
                continue
            records.append(_project_summary(record))
        records.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return records


def build_project_context(project: dict[str, Any]) -> dict[str, Any]:
    """Build safe, project-only context for message handling."""

    memories = list(project.get("memories") or [])
    sources = list(project.get("sources") or [])
    memory_lines = [
        f"- {memory.get('title') + ': ' if memory.get('title') else ''}{memory.get('content')}"
        for memory in memories[:8]
        if str(memory.get("content") or "").strip()
    ]
    text_source_lines = [
        f"- {source.get('title')}: {source.get('content')}"
        for source in sources[:8]
        if source.get("source_type") in {"note", "saved_response"} and str(source.get("content") or "").strip()
    ]
    instructions = str(project.get("instructions") or "").strip()
    instructions_guidelines = "Project instructions:\n" + instructions if instructions else ""
    memory_guidelines = "Project-only memory:\n" + "\n".join(memory_lines) if memory_lines else ""
    source_guidelines = "Project text sources:\n" + "\n".join(text_source_lines) if text_source_lines else ""
    derived_metrics = _project_derived_metrics(project)
    return {
        "enabled": True,
        "project_id": project.get("project_id") or "",
        "name": project.get("name") or "",
        "memory_mode": project.get("memory_mode") or "project_only",
        "default_dataset_id": project.get("default_dataset_id") or "",
        "source_count": len(sources),
        "memory_count": len(memories),
        "derived_metrics": derived_metrics,
        "instructions_guidelines": instructions_guidelines,
        "memory_guidelines": memory_guidelines,
        "source_guidelines": source_guidelines,
        "guidelines": "\n\n".join(
            part for part in (instructions_guidelines, memory_guidelines, source_guidelines) if part
        ),
    }


_PROJECT_FORMULA_PATTERN = re.compile(
    r"(?P<name>[\u4e00-\u9fffA-Za-z_][\u4e00-\u9fffA-Za-z0-9_\s]{0,40}?)\s*=\s*"
    r"(?P<expr>[\u4e00-\u9fffA-Za-z_][\u4e00-\u9fffA-Za-z0-9_]*(?:\s*[+\-*/]\s*(?:[\u4e00-\u9fffA-Za-z_][\u4e00-\u9fffA-Za-z0-9_]*|\d+(?:\.\d+)?))+)"
)
_PROJECT_FORMULA_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fffA-Za-z_][\u4e00-\u9fffA-Za-z0-9_]*|\d+(?:\.\d+)?")


def _project_derived_metrics(project: dict[str, Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    text_entries: list[tuple[str, str]] = []
    instructions = str(project.get("instructions") or "").strip()
    if instructions:
        text_entries.append(("instructions", instructions))
    for memory in project.get("memories") or []:
        content = str(memory.get("content") or "").strip()
        if not content:
            continue
        title = str(memory.get("title") or "memory").strip() or "memory"
        text_entries.append((f"memory:{title}", content))
    for source in project.get("sources") or []:
        if str(source.get("source_type") or "") not in {"note", "saved_response"}:
            continue
        content = str(source.get("content") or "").strip()
        if not content:
            continue
        title = str(source.get("title") or "source").strip() or "source"
        text_entries.append((f"source:{title}", content))
    for origin, text in text_entries:
        for match in _PROJECT_FORMULA_PATTERN.finditer(text):
            name = " ".join(str(match.group("name") or "").split()).strip("：:;,，。；")
            expression = " ".join(str(match.group("expr") or "").split()).strip("：:;,，。；")
            if not name or not expression:
                continue
            fields = [
                token
                for token in _PROJECT_FORMULA_TOKEN_PATTERN.findall(expression)
                if not re.fullmatch(r"\d+(?:\.\d+)?", token)
            ]
            if len(fields) < 2:
                continue
            key = (name, expression)
            if key in seen:
                continue
            seen.add(key)
            specs.append(
                {
                    "name": name,
                    "expression": expression,
                    "fields": fields,
                    "origin": origin,
                }
            )
    return specs


def _project_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": record.get("project_id"),
        "name": record.get("name") or "新项目",
        "description": record.get("description") or "",
        "memory_mode": record.get("memory_mode") or "project_only",
        "default_dataset_id": record.get("default_dataset_id") or "",
        "instructions_version": record.get("instructions_version") or 1,
        "instructions_updated_at": record.get("instructions_updated_at") or "",
        "content_hash": record.get("content_hash") or "",
        "source_count": len(record.get("sources") or []),
        "memory_count": len(record.get("memories") or []),
        "conversation_count": len(record.get("conversation_ids") or []),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _normalize_source_type(source_type: str) -> str:
    value = str(source_type or "").strip().lower()
    return value if value in {"dataset", "rule", "note", "saved_response"} else "note"


def _normalize_source_status(source_status: str) -> str:
    value = str(source_status or "").strip().lower()
    return value if value in {"active", "superseded", "deleted", "unavailable"} else "active"


def _source_version(record: dict[str, Any], replaces_source_id: str) -> int:
    if not replaces_source_id:
        return 1
    for source in record.get("sources") or []:
        if source.get("source_id") == replaces_source_id:
            return max(1, _safe_int(source.get("source_version"), 1) + 1)
    return 1


def _normalize_memory_type(memory_type: str) -> str:
    value = str(memory_type or "").strip().lower()
    return value if value in {"pinned", "conversation_summary"} else "pinned"


def _default_source_title(source_type: str, dataset_id: str, file_id: str) -> str:
    if dataset_id:
        return f"Dataset {dataset_id}"
    if file_id:
        return f"Rule {file_id}"
    return _normalize_source_type(source_type).replace("_", " ").title()


def _clean_name(value: str) -> str:
    return " ".join(str(value or "").strip().split())[:80]


def _clean_text(value: str, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _content_hash(value: Any) -> str:
    payload = json.dumps(to_json_ready(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_ref(value: str) -> str:
    text = str(value or "").strip()
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    return text if text and all(char in allowed for char in text) else ""


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_project_id(project_id: str) -> str:
    value = _safe_ref(project_id)
    return value if value.startswith("proj_") else ""


def _safe_source_id(source_id: str) -> str:
    value = _safe_ref(source_id)
    return value if value.startswith("src_") else ""


def _safe_memory_id(memory_id: str) -> str:
    value = _safe_ref(memory_id)
    return value if value.startswith("mem_") else ""


def _new_project_id() -> str:
    return "proj_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]


def _new_source_id() -> str:
    return "src_" + uuid.uuid4().hex[:12]


def _new_memory_id() -> str:
    return "mem_" + uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
