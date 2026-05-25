"""Data Agent API router boundary.

The router is intentionally thin: it accepts request payloads and delegates all
file parsing, analysis, verification, and response building to the service/core.
"""

from __future__ import annotations

import asyncio
import queue
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.services.data_agent_service import DataAgentService
from data_agent_core.tracing.live_monitor import GLOBAL_MONITOR_RUN_ID, format_sse, live_run_monitor, normalize_monitor_run_id


service = DataAgentService()


def upload_file_path(file_path: str | Path, original_filename: str | None = None) -> dict[str, Any]:
    """Non-FastAPI helper for tests or CLI callers."""

    return service.upload_dataset(file_path, original_filename=original_filename)


def analyze_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Non-FastAPI helper mirroring POST /api/data-agent/analyze."""

    return service.analyze_dataset(
        dataset_id=str(payload.get("dataset_id") or ""),
        question=str(payload.get("question") or ""),
        execution_mode=str(payload.get("execution_mode") or "dual"),
        guidelines=str(payload.get("guidelines") or ""),
        agent_mode=str(payload.get("agent_mode") or "multi_agent"),
        monitor_run_id=str(payload.get("monitor_run_id") or ""),
    )


def chat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Non-FastAPI helper mirroring POST /api/data-agent/chat."""

    return service.chat_without_dataset(
        question=str(payload.get("question") or ""),
        agent_mode=str(payload.get("agent_mode") or "multi_agent"),
        monitor_run_id=str(payload.get("monitor_run_id") or ""),
    )


def message_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Non-FastAPI helper mirroring POST /api/data-agent/message."""

    return service.respond_to_message(
        dataset_id=str(payload.get("dataset_id") or ""),
        conversation_id=str(payload.get("conversation_id") or ""),
        owner_id=str(payload.get("owner_id") or ""),
        tenant_id=str(payload.get("tenant_id") or ""),
        owner_context=payload.get("owner_context") if isinstance(payload.get("owner_context"), dict) else None,
        question=str(payload.get("question") or ""),
        execution_mode=str(payload.get("execution_mode") or "dual"),
        guidelines=str(payload.get("guidelines") or ""),
        agent_mode=str(payload.get("agent_mode") or "multi_agent"),
        monitor_run_id=str(payload.get("monitor_run_id") or ""),
    )


def create_conversation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Non-FastAPI helper mirroring POST /api/data-agent/conversations."""

    return service.create_conversation(
        title=str(payload.get("title") or ""),
        dataset_id=str(payload.get("dataset_id") or ""),
        owner_id=str(payload.get("owner_id") or ""),
        tenant_id=str(payload.get("tenant_id") or ""),
        owner_context=payload.get("owner_context") if isinstance(payload.get("owner_context"), dict) else None,
    )


def conversations_payload(limit: int = 50) -> dict[str, Any]:
    """Non-FastAPI helper mirroring GET /api/data-agent/conversations."""

    return service.list_conversations(limit=limit)


def conversation_payload(conversation_id: str) -> dict[str, Any]:
    """Non-FastAPI helper mirroring GET /api/data-agent/conversations/{id}."""

    return service.get_conversation(conversation_id)


def rename_conversation_payload(conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Non-FastAPI helper mirroring PATCH /api/data-agent/conversations/{id}."""

    return service.rename_conversation(conversation_id, title=str(payload.get("title") or ""))


def profile_payload(dataset_id: str) -> dict[str, Any]:
    """Non-FastAPI helper mirroring GET profile."""

    return service.get_dataset_profile(dataset_id)


def run_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Non-FastAPI helper mirroring POST /api/data-agent/run."""

    return service.run_agent_with_inline_tables(
        question=str(payload.get("question") or ""),
        tables=payload.get("tables"),
        execution_mode=str(payload.get("execution_mode") or "dual"),
        guidelines=str(payload.get("guidelines") or ""),
        agent_mode=str(payload.get("agent_mode") or "multi_agent"),
        dataset_id=payload.get("dataset_id"),
        request_id=payload.get("request_id"),
        source_name=str(payload.get("source_name") or "api_inline_tables"),
        monitor_run_id=str(payload.get("monitor_run_id") or ""),
    )


try:
    from fastapi import APIRouter, File, UploadFile
    from pydantic import BaseModel
    from starlette.responses import StreamingResponse

    router = APIRouter(prefix="/api/data-agent", tags=["data-agent"])

    class AnalyzePayload(BaseModel):
        dataset_id: str
        question: str
        execution_mode: str = "dual"
        guidelines: str = ""
        agent_mode: str = "multi_agent"
        monitor_run_id: str = ""

    class ChatPayload(BaseModel):
        question: str
        agent_mode: str = "multi_agent"
        monitor_run_id: str = ""

    class MessagePayload(BaseModel):
        question: str
        dataset_id: str = ""
        conversation_id: str = ""
        owner_id: str = ""
        tenant_id: str = ""
        owner_context: dict[str, Any] | None = None
        execution_mode: str = "dual"
        guidelines: str = ""
        agent_mode: str = "multi_agent"
        monitor_run_id: str = ""

    class CreateConversationPayload(BaseModel):
        title: str = ""
        dataset_id: str = ""
        owner_id: str = ""
        tenant_id: str = ""
        owner_context: dict[str, Any] | None = None

    class RenameConversationPayload(BaseModel):
        title: str

    class RunPayload(BaseModel):
        question: str
        tables: Any
        execution_mode: str = "dual"
        guidelines: str = ""
        agent_mode: str = "multi_agent"
        dataset_id: str | None = None
        request_id: str | None = None
        source_name: str = "api_inline_tables"
        monitor_run_id: str = ""

    @router.post("/upload")
    async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
        suffix = Path(file.filename or "").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(await file.read())
            temp_path = Path(temp_file.name)
        try:
            return service.upload_dataset(temp_path, original_filename=file.filename)
        finally:
            temp_path.unlink(missing_ok=True)

    @router.post("/upload-batch")
    async def upload_batch(files: list[UploadFile] = File(...)) -> dict[str, Any]:
        temp_paths: list[Path] = []
        original_filenames: list[str | None] = []
        try:
            for upload_file in files:
                suffix = Path(upload_file.filename or "").suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                    temp_file.write(await upload_file.read())
                    temp_paths.append(Path(temp_file.name))
                    original_filenames.append(upload_file.filename)
            return service.upload_datasets(temp_paths, original_filenames=original_filenames)
        finally:
            for temp_path in temp_paths:
                temp_path.unlink(missing_ok=True)

    @router.post("/analyze")
    def analyze(payload: AnalyzePayload) -> dict[str, Any]:
        return service.analyze_dataset(
            dataset_id=payload.dataset_id,
            question=payload.question,
            execution_mode=payload.execution_mode,
            guidelines=payload.guidelines,
            agent_mode=payload.agent_mode,
            monitor_run_id=payload.monitor_run_id,
        )

    @router.post("/chat")
    def chat(payload: ChatPayload) -> dict[str, Any]:
        return service.chat_without_dataset(
            question=payload.question,
            agent_mode=payload.agent_mode,
            monitor_run_id=payload.monitor_run_id,
        )

    @router.post("/message")
    def message(payload: MessagePayload) -> dict[str, Any]:
        return service.respond_to_message(
            question=payload.question,
            dataset_id=payload.dataset_id,
            conversation_id=payload.conversation_id,
            owner_id=payload.owner_id,
            tenant_id=payload.tenant_id,
            owner_context=payload.owner_context,
            execution_mode=payload.execution_mode,
            guidelines=payload.guidelines,
            agent_mode=payload.agent_mode,
            monitor_run_id=payload.monitor_run_id,
        )

    @router.post("/conversations")
    def create_conversation(payload: CreateConversationPayload) -> dict[str, Any]:
        return service.create_conversation(
            title=payload.title,
            dataset_id=payload.dataset_id,
            owner_id=payload.owner_id,
            tenant_id=payload.tenant_id,
            owner_context=payload.owner_context,
        )

    @router.get("/conversations")
    def conversations(limit: int = 50) -> dict[str, Any]:
        return service.list_conversations(limit=limit)

    @router.get("/conversations/{conversation_id}")
    def conversation(conversation_id: str) -> dict[str, Any]:
        return service.get_conversation(conversation_id)

    @router.patch("/conversations/{conversation_id}")
    def rename_conversation(conversation_id: str, payload: RenameConversationPayload) -> dict[str, Any]:
        return service.rename_conversation(conversation_id, payload.title)

    @router.post("/run")
    def run(payload: RunPayload) -> dict[str, Any]:
        return service.run_agent_with_inline_tables(
            question=payload.question,
            tables=payload.tables,
            execution_mode=payload.execution_mode,
            guidelines=payload.guidelines,
            agent_mode=payload.agent_mode,
            dataset_id=payload.dataset_id,
            request_id=payload.request_id,
            source_name=payload.source_name,
            monitor_run_id=payload.monitor_run_id,
        )

    @router.get("/datasets/{dataset_id}/profile")
    def profile(dataset_id: str) -> dict[str, Any]:
        return service.get_dataset_profile(dataset_id)

    @router.get("/monitor/stream")
    async def monitor_stream(monitor_run_id: str = GLOBAL_MONITOR_RUN_ID) -> StreamingResponse:
        run_id = normalize_monitor_run_id(monitor_run_id) or GLOBAL_MONITOR_RUN_ID

        async def event_stream():
            with live_run_monitor.subscribe(run_id) as events:
                connected = {
                    "event_id": "evt_connected",
                    "monitor_run_id": run_id,
                    "event_type": "monitor_connected",
                    "title": "监看已连接",
                    "summary": "实时事件通道已打开。",
                    "role": "",
                    "stage": "monitor",
                    "status": "active",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "elapsed_ms": 0,
                    "payload": {"monitor_run_id": run_id},
                }
                yield format_sse(connected)
                while True:
                    try:
                        event = await asyncio.to_thread(events.get, True, 15)
                    except queue.Empty:
                        yield ": keepalive\n\n"
                    else:
                        yield format_sse(event)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

except ImportError:
    router = None
