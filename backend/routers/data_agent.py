"""Data Agent API router boundary.

The router is intentionally thin: it accepts request payloads and delegates all
file parsing, analysis, verification, and response building to the service/core.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from backend.services.data_agent_service import DataAgentService


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
    )


def chat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Non-FastAPI helper mirroring POST /api/data-agent/chat."""

    return service.chat_without_dataset(
        question=str(payload.get("question") or ""),
        agent_mode=str(payload.get("agent_mode") or "multi_agent"),
    )


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
    )


try:
    from fastapi import APIRouter, File, UploadFile
    from pydantic import BaseModel

    router = APIRouter(prefix="/api/data-agent", tags=["data-agent"])

    class AnalyzePayload(BaseModel):
        dataset_id: str
        question: str
        execution_mode: str = "dual"
        guidelines: str = ""
        agent_mode: str = "multi_agent"

    class ChatPayload(BaseModel):
        question: str
        agent_mode: str = "multi_agent"

    class RunPayload(BaseModel):
        question: str
        tables: Any
        execution_mode: str = "dual"
        guidelines: str = ""
        agent_mode: str = "multi_agent"
        dataset_id: str | None = None
        request_id: str | None = None
        source_name: str = "api_inline_tables"

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
        )

    @router.post("/chat")
    def chat(payload: ChatPayload) -> dict[str, Any]:
        return service.chat_without_dataset(
            question=payload.question,
            agent_mode=payload.agent_mode,
        )

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
        )

    @router.get("/datasets/{dataset_id}/profile")
    def profile(dataset_id: str) -> dict[str, Any]:
        return service.get_dataset_profile(dataset_id)

except ImportError:
    router = None
