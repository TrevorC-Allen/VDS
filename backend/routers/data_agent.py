"""Data Agent API router boundary.

The router is intentionally thin: it accepts request payloads and delegates all
file parsing, analysis, verification, and response building to the service/core.
"""

from __future__ import annotations

import asyncio
import json
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
        user_rule_file_id=str(payload.get("user_rule_file_id") or ""),
        monitor_run_id=str(payload.get("monitor_run_id") or ""),
    )


def chat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Non-FastAPI helper mirroring POST /api/data-agent/chat."""

    return service.chat_without_dataset(
        question=str(payload.get("question") or ""),
        agent_mode=str(payload.get("agent_mode") or "multi_agent"),
        user_rule_file_id=str(payload.get("user_rule_file_id") or ""),
        monitor_run_id=str(payload.get("monitor_run_id") or ""),
    )


def message_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Non-FastAPI helper mirroring POST /api/data-agent/message."""

    return service.respond_to_message(
        dataset_id=str(payload.get("dataset_id") or ""),
        conversation_id=str(payload.get("conversation_id") or ""),
        project_id=str(payload.get("project_id") or ""),
        owner_id=str(payload.get("owner_id") or ""),
        tenant_id=str(payload.get("tenant_id") or ""),
        owner_context=payload.get("owner_context") if isinstance(payload.get("owner_context"), dict) else None,
        question=str(payload.get("question") or ""),
        execution_mode=str(payload.get("execution_mode") or "dual"),
        guidelines=str(payload.get("guidelines") or ""),
        agent_mode=str(payload.get("agent_mode") or "multi_agent"),
        user_rule_file_id=str(payload.get("user_rule_file_id") or ""),
        monitor_run_id=str(payload.get("monitor_run_id") or ""),
    )


def _http_status_for_response(response: dict[str, Any]) -> int:
    if response.get("success") is not False:
        return 200
    errors = response.get("errors") if isinstance(response.get("errors"), list) else []
    first_error = errors[0] if errors and isinstance(errors[0], dict) else {}
    error_type = str(first_error.get("error_type") or "")
    message = str(first_error.get("error_message") or "")
    message_lower = message.lower()
    if "dataset not found" in message_lower or "project not found" in message_lower:
        return 404
    if error_type in {"VERIFICATION_FAILED", "PANDAS_EXECUTION_ERROR"} and response.get("answer"):
        return 200
    if error_type in {
        "FILE_PARSE_ERROR",
        "LOGIC_FORM_ERROR",
        "OUTPUT_CONTRACT_VALIDATION_FAILED",
        "CHART_CONFIG_ERROR",
        "CAPABILITY_GAP",
    }:
        return 422
    return 500


def benchmark_run_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Non-FastAPI helper mirroring POST /api/data-agent/benchmark/run."""

    return service.run_benchmark_from_rule(
        dataset_id=str(payload.get("dataset_id") or ""),
        benchmark_rule_file_id=str(payload.get("benchmark_rule_file_id") or ""),
        user_rule_file_id=str(payload.get("user_rule_file_id") or ""),
        execution_mode=str(payload.get("execution_mode") or "auto"),
        agent_mode=str(payload.get("agent_mode") or "multi_agent"),
        limit=payload.get("limit") if isinstance(payload.get("limit"), int) else None,
    )


def create_conversation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Non-FastAPI helper mirroring POST /api/data-agent/conversations."""

    return service.create_conversation(
        title=str(payload.get("title") or ""),
        dataset_id=str(payload.get("dataset_id") or ""),
        project_id=str(payload.get("project_id") or ""),
        owner_id=str(payload.get("owner_id") or ""),
        tenant_id=str(payload.get("tenant_id") or ""),
        owner_context=payload.get("owner_context") if isinstance(payload.get("owner_context"), dict) else None,
    )


def conversations_payload(limit: int = 50, offset: int = 0, project_id: str | None = "") -> dict[str, Any]:
    """Non-FastAPI helper mirroring GET /api/data-agent/conversations."""

    return service.list_conversations(limit=limit, offset=offset, project_id=project_id)


def conversation_payload(conversation_id: str) -> dict[str, Any]:
    """Non-FastAPI helper mirroring GET /api/data-agent/conversations/{id}."""

    return service.get_conversation(conversation_id)


def rename_conversation_payload(conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Non-FastAPI helper mirroring PATCH /api/data-agent/conversations/{id}."""

    return service.update_conversation(
        conversation_id,
        title=str(payload.get("title")) if payload.get("title") is not None else None,
        project_id=str(payload.get("project_id")) if payload.get("project_id") is not None else None,
        pinned=bool(payload.get("pinned")) if payload.get("pinned") is not None else None,
    )


def create_project_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Non-FastAPI helper mirroring POST /api/data-agent/projects."""

    return service.create_project(
        name=str(payload.get("name") or ""),
        description=str(payload.get("description") or ""),
        instructions=str(payload.get("instructions") or ""),
        owner_id=str(payload.get("owner_id") or ""),
        tenant_id=str(payload.get("tenant_id") or ""),
        owner_context=payload.get("owner_context") if isinstance(payload.get("owner_context"), dict) else None,
    )


def projects_payload(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Non-FastAPI helper mirroring GET /api/data-agent/projects."""

    return service.list_projects(limit=limit, offset=offset)


def monitor_summary_payload(monitor_run_id: str = GLOBAL_MONITOR_RUN_ID) -> dict[str, Any]:
    """Non-FastAPI helper mirroring GET /api/data-agent/monitor/summary."""

    run_id = normalize_monitor_run_id(monitor_run_id) or GLOBAL_MONITOR_RUN_ID
    history = live_run_monitor.history(run_id)
    latest = history[-1] if history else {}
    status_counts: dict[str, int] = {}
    stage_counts: dict[str, int] = {}
    for event in history:
        status = str(event.get("status") or "unknown")
        stage = str(event.get("stage") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
    return {
        "success": True,
        "monitor_run_id": run_id,
        "total": len(history),
        "latest_event_type": str(latest.get("event_type") or ""),
        "latest_event_at": str(latest.get("created_at") or ""),
        "status_counts": status_counts,
        "stage_counts": stage_counts,
    }


def monitor_health_payload(monitor_run_id: str = GLOBAL_MONITOR_RUN_ID) -> dict[str, Any]:
    """Non-FastAPI helper mirroring GET /api/data-agent/monitor/health."""

    run_id = normalize_monitor_run_id(monitor_run_id) or GLOBAL_MONITOR_RUN_ID
    history = live_run_monitor.history(run_id)
    latest = history[-1] if history else {}
    return {
        "success": True,
        "status": "ok",
        "monitor_run_id": run_id,
        "transport": "in_memory_sse",
        "event_count": len(history),
        "latest_event_type": str(latest.get("event_type") or ""),
        "latest_event_at": str(latest.get("created_at") or ""),
    }


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
    from fastapi import APIRouter, File, Form, UploadFile
    from pydantic import BaseModel
    from starlette.responses import JSONResponse, StreamingResponse

    router = APIRouter(prefix="/api/data-agent", tags=["data-agent"])

    class AnalyzePayload(BaseModel):
        dataset_id: str
        question: str
        execution_mode: str = "dual"
        guidelines: str = ""
        agent_mode: str = "multi_agent"
        user_rule_file_id: str = ""
        monitor_run_id: str = ""

    class ChatPayload(BaseModel):
        question: str
        agent_mode: str = "multi_agent"
        monitor_run_id: str = ""

    class MessagePayload(BaseModel):
        question: str
        dataset_id: str = ""
        conversation_id: str = ""
        project_id: str = ""
        owner_id: str = ""
        tenant_id: str = ""
        owner_context: dict[str, Any] | None = None
        execution_mode: str = "dual"
        guidelines: str = ""
        agent_mode: str = "multi_agent"
        user_rule_file_id: str = ""
        monitor_run_id: str = ""

    class BenchmarkRunPayload(BaseModel):
        dataset_id: str
        benchmark_rule_file_id: str
        user_rule_file_id: str = ""
        execution_mode: str = "auto"
        agent_mode: str = "multi_agent"
        limit: int | None = None

    class CreateConversationPayload(BaseModel):
        title: str = ""
        dataset_id: str = ""
        project_id: str = ""
        owner_id: str = ""
        tenant_id: str = ""
        owner_context: dict[str, Any] | None = None

    class UpdateConversationPayload(BaseModel):
        title: str | None = None
        project_id: str | None = None
        pinned: bool | None = None

    class CreateProjectPayload(BaseModel):
        name: str = ""
        description: str = ""
        instructions: str = ""
        owner_id: str = ""
        tenant_id: str = ""
        owner_context: dict[str, Any] | None = None

    class UpdateProjectPayload(BaseModel):
        name: str | None = None
        description: str | None = None
        instructions: str | None = None
        default_dataset_id: str | None = None

    class ProjectSourcePayload(BaseModel):
        source_type: str = "note"
        title: str = ""
        content: str = ""
        dataset_id: str = ""
        file_id: str = ""
        metadata: dict[str, Any] | None = None

    class ProjectMemoryPayload(BaseModel):
        content: str = ""
        memory_type: str = "pinned"
        title: str = ""
        metadata: dict[str, Any] | None = None

    class UpdateProjectMemoryPayload(BaseModel):
        content: str | None = None
        memory_type: str | None = None
        title: str | None = None

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
    async def upload(
        file: UploadFile = File(...),
        file_role: str = Form("dataset"),
        rule_scope: str = Form(""),
        bind_dataset_id: str = Form(""),
    ) -> dict[str, Any]:
        suffix = Path(file.filename or "").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(await file.read())
            temp_path = Path(temp_file.name)
        try:
            return service.upload_dataset(
                temp_path,
                original_filename=file.filename,
                file_role=file_role,
                rule_scope=rule_scope,
                bind_dataset_id=bind_dataset_id,
            )
        finally:
            temp_path.unlink(missing_ok=True)

    @router.post("/upload-batch")
    async def upload_batch(
        files: list[UploadFile] = File(...),
        file_role: str = Form("dataset"),
        rule_scope: str = Form(""),
        bind_dataset_id: str = Form(""),
    ) -> dict[str, Any]:
        temp_paths: list[Path] = []
        original_filenames: list[str | None] = []
        try:
            for upload_file in files:
                suffix = Path(upload_file.filename or "").suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                    temp_file.write(await upload_file.read())
                    temp_paths.append(Path(temp_file.name))
                    original_filenames.append(upload_file.filename)
            return service.upload_datasets(
                temp_paths,
                original_filenames=original_filenames,
                file_role=file_role,
                rule_scope=rule_scope,
                bind_dataset_id=bind_dataset_id,
            )
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
            user_rule_file_id=payload.user_rule_file_id,
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
    def message(payload: MessagePayload) -> JSONResponse:
        response = service.respond_to_message(
            question=payload.question,
            dataset_id=payload.dataset_id,
            conversation_id=payload.conversation_id,
            project_id=payload.project_id,
            owner_id=payload.owner_id,
            tenant_id=payload.tenant_id,
            owner_context=payload.owner_context,
            execution_mode=payload.execution_mode,
            guidelines=payload.guidelines,
            agent_mode=payload.agent_mode,
            user_rule_file_id=payload.user_rule_file_id,
            monitor_run_id=payload.monitor_run_id,
        )
        return JSONResponse(content=response, status_code=_http_status_for_response(response))

    @router.post("/benchmark/run")
    def benchmark_run(payload: BenchmarkRunPayload) -> dict[str, Any]:
        return service.run_benchmark_from_rule(
            dataset_id=payload.dataset_id,
            benchmark_rule_file_id=payload.benchmark_rule_file_id,
            user_rule_file_id=payload.user_rule_file_id,
            execution_mode=payload.execution_mode,
            agent_mode=payload.agent_mode,
            limit=payload.limit,
        )

    @router.post("/conversations")
    def create_conversation(payload: CreateConversationPayload) -> dict[str, Any]:
        return service.create_conversation(
            title=payload.title,
            dataset_id=payload.dataset_id,
            project_id=payload.project_id,
            owner_id=payload.owner_id,
            tenant_id=payload.tenant_id,
            owner_context=payload.owner_context,
        )

    @router.get("/conversations")
    def conversations(limit: int = 50, offset: int = 0, project_id: str | None = "") -> dict[str, Any]:
        return service.list_conversations(limit=limit, offset=offset, project_id=project_id)

    @router.get("/conversations/{conversation_id}")
    def conversation(conversation_id: str) -> dict[str, Any]:
        return service.get_conversation(conversation_id)

    @router.patch("/conversations/{conversation_id}")
    def update_conversation(conversation_id: str, payload: UpdateConversationPayload) -> dict[str, Any]:
        return service.update_conversation(
            conversation_id,
            title=payload.title,
            project_id=payload.project_id,
            pinned=payload.pinned,
        )

    @router.delete("/conversations/{conversation_id}")
    def delete_conversation(conversation_id: str) -> dict[str, Any]:
        return service.delete_conversation(conversation_id)

    @router.post("/projects")
    def create_project(payload: CreateProjectPayload) -> dict[str, Any]:
        return service.create_project(
            name=payload.name,
            description=payload.description,
            instructions=payload.instructions,
            owner_id=payload.owner_id,
            tenant_id=payload.tenant_id,
            owner_context=payload.owner_context,
        )

    @router.get("/projects")
    def projects(limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return service.list_projects(limit=limit, offset=offset)

    @router.get("/projects/{project_id}")
    def project(project_id: str) -> dict[str, Any]:
        return service.get_project(project_id)

    @router.patch("/projects/{project_id}")
    def update_project(project_id: str, payload: UpdateProjectPayload) -> dict[str, Any]:
        return service.update_project(
            project_id,
            name=payload.name,
            description=payload.description,
            instructions=payload.instructions,
            default_dataset_id=payload.default_dataset_id,
        )

    @router.delete("/projects/{project_id}")
    def delete_project(project_id: str) -> dict[str, Any]:
        return service.delete_project(project_id)

    @router.post("/projects/{project_id}/sources")
    def create_project_source(project_id: str, payload: ProjectSourcePayload) -> dict[str, Any]:
        return service.create_project_source(
            project_id,
            source_type=payload.source_type,
            title=payload.title,
            content=payload.content,
            dataset_id=payload.dataset_id,
            file_id=payload.file_id,
            metadata=payload.metadata,
        )

    @router.post("/projects/{project_id}/sources/upload")
    async def upload_project_sources(
        project_id: str,
        files: list[UploadFile] = File(...),
        file_role: str = Form("dataset"),
        rule_scope: str = Form(""),
        bind_dataset_id: str = Form(""),
    ) -> dict[str, Any]:
        temp_paths: list[Path] = []
        original_filenames: list[str | None] = []
        try:
            for upload_file in files:
                suffix = Path(upload_file.filename or "").suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                    temp_file.write(await upload_file.read())
                    temp_paths.append(Path(temp_file.name))
                    original_filenames.append(upload_file.filename)
            return service.upload_project_sources(
                project_id,
                temp_paths,
                original_filenames=original_filenames,
                file_role=file_role,
                rule_scope=rule_scope,
                bind_dataset_id=bind_dataset_id,
            )
        finally:
            for temp_path in temp_paths:
                temp_path.unlink(missing_ok=True)

    @router.delete("/projects/{project_id}/sources/{source_id}")
    def delete_project_source(project_id: str, source_id: str) -> dict[str, Any]:
        return service.delete_project_source(project_id, source_id)

    @router.post("/projects/{project_id}/memories")
    def create_project_memory(project_id: str, payload: ProjectMemoryPayload) -> dict[str, Any]:
        return service.create_project_memory(
            project_id,
            content=payload.content,
            memory_type=payload.memory_type,
            title=payload.title,
            metadata=payload.metadata,
        )

    @router.patch("/projects/{project_id}/memories/{memory_id}")
    def update_project_memory(project_id: str, memory_id: str, payload: UpdateProjectMemoryPayload) -> dict[str, Any]:
        return service.update_project_memory(
            project_id,
            memory_id,
            content=payload.content,
            title=payload.title,
            memory_type=payload.memory_type,
        )

    @router.delete("/projects/{project_id}/memories/{memory_id}")
    def delete_project_memory(project_id: str, memory_id: str) -> dict[str, Any]:
        return service.delete_project_memory(project_id, memory_id)

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

    @router.get("/monitor/summary")
    def monitor_summary(monitor_run_id: str = GLOBAL_MONITOR_RUN_ID) -> dict[str, Any]:
        return monitor_summary_payload(monitor_run_id)

    @router.get("/monitor/health")
    def monitor_health(monitor_run_id: str = GLOBAL_MONITOR_RUN_ID) -> dict[str, Any]:
        return monitor_health_payload(monitor_run_id)

except ImportError:
    router = None
