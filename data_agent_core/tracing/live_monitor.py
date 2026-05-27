"""In-process live monitor events for workbench runs.

The monitor intentionally publishes safe summaries only. It is for local
operator visibility, not for carrying hidden reasoning, prompts, secrets, or
benchmark answers.
"""

from __future__ import annotations

import json
import queue
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Iterator


BLOCKED_KEYS = {
    "accepted_answer",
    "accepted_answers",
    "api_key",
    "authorization",
    "chain_of_thought",
    "cot",
    "full_reasoning",
    "hidden_answer",
    "hidden_reasoning",
    "password",
    "public_proxy",
    "raw_prompt",
    "raw_reasoning",
    "reasoning_trace_view",
    "reasoning_tokens",
    "scorer",
    "secret",
    "standard_answer",
    "task_id",
    "task_ids",
    "token",
}
BLOCKED_KEY_MARKERS = (
    "accepted_answer",
    "accepted_answers",
    "api_key",
    "authorization",
    "chain_of_thought",
    "full_reasoning",
    "hidden_answer",
    "hidden_reasoning",
    "public_proxy",
    "raw_prompt",
    "raw_reasoning",
    "reasoning_tokens",
    "scorer",
    "standard_answer",
    "task_id",
)
BLOCKED_TEXT_MARKERS = (
    "accepted-answer",
    "accepted answer",
    "accepted_answer",
    "api key",
    "api_key",
    "chain of thought",
    "chain_of_thought",
    "full reasoning",
    "full_reasoning",
    "hidden answer",
    "hidden_answer",
    "hidden benchmark",
    "hidden_reasoning",
    "public proxy",
    "public_proxy",
    "raw prompt",
    "raw reasoning",
    "raw_prompt",
    "raw_reasoning",
    "reasoning tokens",
    "reasoning_tokens",
    "scorer",
    "standard answer",
    "standard_answer",
    "task_id",
)
MAX_DICT_ITEMS = 80
MAX_LIST_ITEMS = 30
MAX_TEXT_LENGTH = 1600
MAX_HISTORY_EVENTS = 300
MAX_QUEUE_EVENTS = 500
GLOBAL_MONITOR_RUN_ID = "workbench_live"


class LiveRunMonitor:
    """Small thread-safe pub/sub monitor used by the FastAPI workbench."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._subscribers: dict[str, list[queue.Queue[dict[str, Any]]]] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._started_at: dict[str, float] = {}

    def publish(
        self,
        monitor_run_id: str,
        event_type: str,
        *,
        title: str = "",
        summary: str = "",
        role: str = "",
        stage: str = "",
        status: str = "completed",
        payload: Any = None,
    ) -> dict[str, Any] | None:
        """Publish one safe JSON event for a monitor run."""

        run_id = normalize_monitor_run_id(monitor_run_id)
        if not run_id:
            return None
        with self._lock:
            self._started_at.setdefault(run_id, time.perf_counter())
            elapsed_ms = round((time.perf_counter() - self._started_at[run_id]) * 1000, 2)
        event = {
            "event_id": "evt_" + uuid.uuid4().hex[:16],
            "monitor_run_id": run_id,
            "event_type": str(event_type or "event"),
            "title": str(title or event_type or "event"),
            "summary": _clip_text(summary),
            "role": str(role or ""),
            "stage": str(stage or ""),
            "status": str(status or "completed"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_ms": elapsed_ms,
            "payload": sanitize_monitor_payload(payload),
        }
        with self._lock:
            history = self._history.setdefault(run_id, [])
            history.append(event)
            if len(history) > MAX_HISTORY_EVENTS:
                del history[: len(history) - MAX_HISTORY_EVENTS]
            subscribers = list(self._subscribers.get(run_id, []))
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(event)
                except queue.Empty:
                    pass
        if run_id != GLOBAL_MONITOR_RUN_ID:
            with self._lock:
                global_history = self._history.setdefault(GLOBAL_MONITOR_RUN_ID, [])
                global_history.append(event)
                if len(global_history) > MAX_HISTORY_EVENTS:
                    del global_history[: len(global_history) - MAX_HISTORY_EVENTS]
                global_subscribers = list(self._subscribers.get(GLOBAL_MONITOR_RUN_ID, []))
            for subscriber in global_subscribers:
                try:
                    subscriber.put_nowait(event)
                except queue.Full:
                    try:
                        subscriber.get_nowait()
                        subscriber.put_nowait(event)
                    except queue.Empty:
                        pass
        return event

    @contextmanager
    def subscribe(self, monitor_run_id: str) -> Iterator[queue.Queue[dict[str, Any]]]:
        """Subscribe to future events and receive recent history first."""

        run_id = normalize_monitor_run_id(monitor_run_id)
        events: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=MAX_QUEUE_EVENTS)
        with self._lock:
            for event in self._history.get(run_id, []):
                events.put_nowait(event)
            self._subscribers.setdefault(run_id, []).append(events)
        try:
            yield events
        finally:
            with self._lock:
                subscribers = self._subscribers.get(run_id, [])
                if events in subscribers:
                    subscribers.remove(events)
                if not subscribers:
                    self._subscribers.pop(run_id, None)

    def history(self, monitor_run_id: str) -> list[dict[str, Any]]:
        """Return recent events for tests or non-streaming callers."""

        run_id = normalize_monitor_run_id(monitor_run_id)
        with self._lock:
            return list(self._history.get(run_id, []))

    def clear(self, monitor_run_id: str | None = None) -> None:
        """Clear monitor history, primarily for tests."""

        with self._lock:
            if monitor_run_id:
                run_id = normalize_monitor_run_id(monitor_run_id)
                self._history.pop(run_id, None)
                self._started_at.pop(run_id, None)
            else:
                self._history.clear()
                self._started_at.clear()


live_run_monitor = LiveRunMonitor()


def normalize_monitor_run_id(value: str | None) -> str:
    """Return a bounded id suitable for in-memory routing."""

    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"[^A-Za-z0-9_.:-]", "_", text)
    return text[:120]


def emit_monitor_event(
    monitor_run_id: str | None,
    event_type: str,
    *,
    title: str = "",
    summary: str = "",
    role: str = "",
    stage: str = "",
    status: str = "completed",
    payload: Any = None,
) -> dict[str, Any] | None:
    """Publish a monitor event when monitoring is enabled."""

    return live_run_monitor.publish(
        monitor_run_id or "",
        event_type,
        title=title,
        summary=summary,
        role=role,
        stage=stage,
        status=status,
        payload=payload,
    )


def format_sse(event: dict[str, Any]) -> str:
    """Format one event as an SSE frame."""

    event_name = str(event.get("event_type") or "message")
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.get('event_id', '')}\nevent: {event_name}\ndata: {data}\n\n"


def sanitize_monitor_payload(value: Any) -> Any:
    """Recursively redact and bound monitor payloads."""

    if is_dataclass(value):
        return sanitize_monitor_payload(asdict(value))
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_DICT_ITEMS:
                result["_truncated_keys"] = max(len(value) - MAX_DICT_ITEMS, 0)
                break
            key_text = str(key)
            if _blocked_key(key_text):
                continue
            result[key_text] = sanitize_monitor_payload(item)
        return result
    if isinstance(value, (list, tuple)):
        items = [sanitize_monitor_payload(item) for item in list(value)[:MAX_LIST_ITEMS]]
        if len(value) > MAX_LIST_ITEMS:
            items.append({"_truncated_items": len(value) - MAX_LIST_ITEMS})
        return items
    if hasattr(value, "item"):
        try:
            return sanitize_monitor_payload(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    if isinstance(value, str):
        return _clip_text(_redact_text(value))
    return value


def _clip_text(value: Any) -> str:
    text = str(value or "")
    if len(text) <= MAX_TEXT_LENGTH:
        return text
    return text[:MAX_TEXT_LENGTH] + f"... [truncated {len(text) - MAX_TEXT_LENGTH} chars]"


def _blocked_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in BLOCKED_KEYS or any(marker in lowered for marker in BLOCKED_KEY_MARKERS)


def _redact_text(text: str) -> str:
    result = str(text or "")
    for marker in BLOCKED_TEXT_MARKERS:
        result = re.sub(re.escape(marker), "[redacted]", result, flags=re.IGNORECASE)
    return result
