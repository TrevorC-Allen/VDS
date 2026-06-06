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
import uuid

from backend.services.export_service import resolve_export_artifact
from backend.services.data_agent_service import DataAgentService
from backend.schemas.data_agent_schema import VALID_AGENT_MODES, VALID_EXECUTION_MODES, error_response
from backend.storage.run_store import RunStore, public_run_status
from data_agent_core.errors.error_result import ErrorResult
from data_agent_core.errors.error_types import FILE_PARSE_ERROR, LOGIC_FORM_ERROR
from data_agent_core.tracing.live_monitor import GLOBAL_MONITOR_RUN_ID, format_sse, live_run_monitor, normalize_monitor_run_id


service = DataAgentService()
run_store = RunStore(service.file_store.runs_root)
_active_jobs: dict[str, asyncio.Task] = {}


class _FallbackJSONResponse:
    def __init__(self, content: Any, status_code: int = 200) -> None:
        self.status_code = status_code
        self.body = json.dumps(content, ensure_ascii=False).encode("utf-8")


JSONResponse = _FallbackJSONResponse


def _current_run_store() -> RunStore:
    """Return the RunStore bound to the active service storage root."""

    global run_store
    active_root = Path(service.file_store.runs_root)
    if Path(run_store.root) != active_root:
        run_store = RunStore(active_root)
    return run_store


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

    return _execute_message_sync(payload)


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
    semantic_status = str(response.get("semantic_status") or "").lower()
    if semantic_status in {"failed", "warning", "needs_clarification"} and response.get("answer"):
        return 200
    if response.get("answer") and not errors:
        return 200
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


def _new_run_id() -> str:
    return "run_" + uuid.uuid4().hex[:16]


def _message_request_dict(payload: Any) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if hasattr(payload, "dict"):
        return payload.dict()
    return dict(payload or {})


def _message_request_preflight_error(request: dict[str, Any]) -> dict[str, Any] | None:
    execution_mode = str(request.get("execution_mode") or "dual")
    if execution_mode not in VALID_EXECUTION_MODES:
        return error_response(
            dataset_id=str(request.get("dataset_id") or ""),
            error=ErrorResult(
                error_type=LOGIC_FORM_ERROR,
                error_message=f"Unsupported execution_mode: {execution_mode}",
                failed_step="message_preflight",
                recoverable=True,
                suggested_fix="Use one of auto, pandas, sql, or dual.",
            ),
        )
    agent_mode = str(request.get("agent_mode") or "multi_agent")
    if agent_mode not in VALID_AGENT_MODES:
        return error_response(
            dataset_id=str(request.get("dataset_id") or ""),
            error=ErrorResult(
                error_type=LOGIC_FORM_ERROR,
                error_message=f"Unsupported agent_mode: {agent_mode}",
                failed_step="message_preflight",
                recoverable=True,
                suggested_fix="Use multi_agent or single_agent.",
            ),
        )
    dataset_id = str(request.get("dataset_id") or "")
    if dataset_id and service.file_store.get_tables(dataset_id) is None:
        return error_response(
            dataset_id=dataset_id,
            error=ErrorResult(
                error_type=FILE_PARSE_ERROR,
                error_message=f"Dataset not found in temporary store: {dataset_id}",
                failed_step="message_preflight",
                recoverable=True,
                suggested_fix="Upload the dataset again before submitting an analysis question.",
            ),
        )
    return None


def _create_message_run_record(request: dict[str, Any], *, retry_of: str = "") -> tuple[str, dict[str, Any]]:
    run_id = _new_run_id()
    request["run_id"] = run_id
    store = _current_run_store()
    record = store.create_run(
        run_id,
        request=request,
        project_id=str(request.get("project_id") or ""),
        conversation_id=str(request.get("conversation_id") or ""),
        dataset_id=str(request.get("dataset_id") or ""),
        retry_of=retry_of,
    )
    return run_id, record


def _respond_to_message_request(
    request: dict[str, Any],
    *,
    run_id: str,
    cancel_checker: Any = None,
) -> dict[str, Any]:
    return service.respond_to_message(
        question=str(request.get("question") or ""),
        dataset_id=str(request.get("dataset_id") or ""),
        conversation_id=str(request.get("conversation_id") or ""),
        project_id=str(request.get("project_id") or ""),
        owner_id=str(request.get("owner_id") or ""),
        tenant_id=str(request.get("tenant_id") or ""),
        owner_context=request.get("owner_context") if isinstance(request.get("owner_context"), dict) else None,
        execution_mode=str(request.get("execution_mode") or "dual"),
        guidelines=str(request.get("guidelines") or ""),
        agent_mode=str(request.get("agent_mode") or "multi_agent"),
        user_rule_file_id=str(request.get("user_rule_file_id") or ""),
        monitor_run_id=str(request.get("monitor_run_id") or ""),
        run_id=run_id,
        cancel_checker=cancel_checker,
    )


def _mark_message_run_running(run_id: str, *, summary: str) -> None:
    _current_run_store().update_run(
        run_id,
        status="running",
        latest_stage="message",
        latest_summary=summary,
    )


def _complete_message_run(run_id: str, response: dict[str, Any], record: dict[str, Any]) -> None:
    store = _current_run_store()
    store.write_result(run_id, response)
    success = response.get("success") is not False
    errors = response.get("errors") if isinstance(response.get("errors"), list) else []
    first_error = errors[0] if errors and isinstance(errors[0], dict) else {}
    category = "" if success else _failure_category_from_error(
        str(first_error.get("error_message") or ""),
        failed_step=str(first_error.get("failed_step") or ""),
        error_type=str(first_error.get("error_type") or ""),
    )
    store.update_run(
        run_id,
        status="completed" if success else "failed",
        latest_stage="completed" if success else category,
        latest_summary="分析结果已生成。" if success else f"任务未完成：{_failure_category_label(category)}。",
        failure_category=category,
        failure_reason="" if success else str(first_error.get("error_message") or response.get("answer") or ""),
        error_message="" if success else str(first_error.get("error_message") or ""),
        result_available=True,
        conversation_id=response.get("conversation_id") or record.get("conversation_id") or "",
        dataset_id=response.get("dataset_id") or record.get("dataset_id") or "",
        artifacts_manifest=response.get("artifacts_manifest"),
    )


def _recover_missing_message_run(run_id: str) -> dict[str, Any] | None:
    """Backfill RunStore records for legacy sync /message runs that only wrote trace/history."""

    if not _is_safe_run_id(run_id):
        return None
    store = _current_run_store()
    existing = store.get_run(run_id)
    result = store.get_result(run_id)
    if existing is not None and result is not None:
        return existing

    recovered = _recover_message_result_payload(run_id)
    if recovered is None:
        return existing

    if result is None:
        store.write_result(run_id, recovered["result"])
    if existing is not None:
        return store.update_run(
            run_id,
            result_available=True,
            artifacts_manifest=recovered["result"].get("artifacts_manifest"),
        ) or existing

    result_payload = recovered["result"]
    request = {
        "run_id": run_id,
        "question": recovered.get("question") or result_payload.get("question") or "",
        "dataset_id": recovered.get("dataset_id") or result_payload.get("dataset_id") or "",
        "conversation_id": recovered.get("conversation_id") or result_payload.get("conversation_id") or "",
        "project_id": recovered.get("project_id") or "",
    }
    try:
        record = store.create_run(
            run_id,
            request=request,
            project_id=str(request.get("project_id") or ""),
            conversation_id=str(request.get("conversation_id") or ""),
            dataset_id=str(request.get("dataset_id") or ""),
        )
    except ValueError:
        return None

    success = result_payload.get("success") is not False
    errors = result_payload.get("errors") if isinstance(result_payload.get("errors"), list) else []
    first_error = errors[0] if errors and isinstance(errors[0], dict) else {}
    category = "" if success else _failure_category_from_error(
        str(first_error.get("error_message") or result_payload.get("answer") or ""),
        failed_step=str(first_error.get("failed_step") or ""),
        error_type=str(first_error.get("error_type") or ""),
    )
    return store.update_run(
        run_id,
        status="completed" if success else "failed",
        latest_stage="completed" if success else category,
        latest_summary="分析结果已生成。" if success else f"任务未完成：{_failure_category_label(category)}。",
        failure_category=category,
        failure_reason="" if success else str(first_error.get("error_message") or result_payload.get("answer") or ""),
        error_message="" if success else str(first_error.get("error_message") or ""),
        result_available=True,
        conversation_id=str(request.get("conversation_id") or ""),
        dataset_id=str(request.get("dataset_id") or ""),
        artifacts_manifest=result_payload.get("artifacts_manifest"),
    ) or record


def _recover_message_result_payload(run_id: str) -> dict[str, Any] | None:
    from_conversation = _recover_message_result_from_conversation(run_id)
    if from_conversation is not None:
        return from_conversation
    return _recover_message_result_from_trace(run_id)


def _recover_message_result_from_conversation(run_id: str) -> dict[str, Any] | None:
    root = Path(service.conversation_store.root)
    if not root.exists():
        return None
    for path in sorted(root.glob("conv_*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        messages = record.get("messages") if isinstance(record.get("messages"), list) else []
        for index, message in enumerate(messages):
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
            if str(message.get("run_id") or payload.get("run_id") or "") != run_id:
                continue
            result = dict(payload)
            result.setdefault("response_version", "v1")
            result.setdefault("success", bool(message.get("success")))
            result.setdefault("run_id", run_id)
            result.setdefault("conversation_id", record.get("conversation_id") or "")
            result.setdefault("message_id", message.get("message_id") or "")
            result.setdefault("answer", message.get("content") or "")
            if not result.get("artifacts_manifest"):
                manifest = _read_run_artifacts_manifest(run_id)
                if manifest is not None:
                    result["artifacts_manifest"] = manifest
            question = ""
            if index > 0 and isinstance(messages[index - 1], dict) and messages[index - 1].get("role") == "user":
                question = str(messages[index - 1].get("content") or "")
                result.setdefault("question", question)
            return {
                "result": result,
                "conversation_id": str(record.get("conversation_id") or ""),
                "project_id": str(record.get("project_id") or ""),
                "dataset_id": str(result.get("dataset_id") or record.get("dataset_id") or ""),
                "question": question or str(result.get("question") or ""),
            }
    return None


def _recover_message_result_from_trace(run_id: str) -> dict[str, Any] | None:
    trace_path = Path(service.file_store.runs_root) / run_id / "trace.json"
    if not trace_path.exists():
        return None
    try:
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    final_response = trace.get("final_response") if isinstance(trace.get("final_response"), dict) else {}
    pandas_result = trace.get("pandas_result_summary") if isinstance(trace.get("pandas_result_summary"), dict) else {}
    value = pandas_result.get("value")
    rows = value if isinstance(value, list) else []
    columns = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []
    result = {
        "response_version": "v1",
        "success": final_response.get("success", not bool(trace.get("errors"))),
        "run_id": run_id,
        "dataset_id": trace.get("dataset_id") or "",
        "question": trace.get("question") or "",
        "answer_type": "table" if rows else "text",
        "answer": final_response.get("answer") or "",
        "logic_form": trace.get("logic_form") or {},
        "result": {"columns": columns, "rows": rows, "value": value},
        "verification": trace.get("verification_result") or {},
        "insight": trace.get("insight_summary") or {},
        "chart": trace.get("chart_plan_summary") or {},
        "process_view_v2": trace.get("process_view_v2") or {},
        "errors": trace.get("errors") or [],
    }
    manifest = _read_run_artifacts_manifest(run_id)
    if manifest is not None:
        result["artifacts_manifest"] = manifest
    return {
        "result": result,
        "conversation_id": "",
        "project_id": "",
        "dataset_id": str(result.get("dataset_id") or ""),
        "question": str(result.get("question") or ""),
    }


def _read_run_artifacts_manifest(run_id: str) -> dict[str, Any] | None:
    if not _is_safe_run_id(run_id):
        return None
    manifest_path = Path(service.file_store.runs_root) / run_id / "exports" / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return manifest if isinstance(manifest, dict) else None


def _is_safe_run_id(run_id: str) -> bool:
    text = str(run_id or "")
    return bool(text) and len(text) <= 96 and all(char.isalnum() or char in {"_", "-"} for char in text)


def _mark_message_run_failed(run_id: str, exc: Exception) -> None:
    category = _failure_category_from_error(str(exc), failed_step="")
    _current_run_store().update_run(
        run_id,
        status="failed",
        latest_stage=category,
        latest_summary=f"任务失败：{_failure_category_label(category)}。",
        failure_category=category,
        failure_reason=str(exc),
        error_message=str(exc),
    )


def _execute_message_sync(payload: Any) -> dict[str, Any]:
    request = _message_request_dict(payload)
    preflight_error = _message_request_preflight_error(request)
    if preflight_error is not None:
        return preflight_error
    run_id, record = _create_message_run_record(request)
    _mark_message_run_running(run_id, summary="后端正在同步处理消息。")
    try:
        response = _respond_to_message_request(request, run_id=run_id)
    except Exception as exc:
        _mark_message_run_failed(run_id, exc)
        raise
    _complete_message_run(run_id, response, record)
    return response


async def _create_message_job(payload: Any, *, retry_of: str = "") -> dict[str, Any]:
    request = _message_request_dict(payload)
    preflight_error = _message_request_preflight_error(request)
    if preflight_error is not None:
        return preflight_error
    run_id, record = _create_message_run_record(request, retry_of=retry_of)
    task = asyncio.create_task(_execute_message_job(run_id))
    _active_jobs[run_id] = task
    task.add_done_callback(lambda _: _active_jobs.pop(run_id, None))
    return {"response_version": "v1", "success": True, "run": public_run_status(record)}


async def _execute_message_job(run_id: str) -> None:
    store = _current_run_store()
    record = store.get_run(run_id)
    if record is None:
        return
    request = record.get("request") if isinstance(record.get("request"), dict) else {}
    _mark_message_run_running(run_id, summary="后端已开始处理消息。")

    def cancel_checker() -> bool:
        return _current_run_store().is_cancel_requested(run_id)

    try:
        response = await asyncio.to_thread(
            _respond_to_message_request,
            request,
            run_id=run_id,
            cancel_checker=cancel_checker,
        )
    except RuntimeError as exc:
        if "cancelled" in str(exc).lower() or cancel_checker():
            store.update_run(
                run_id,
                status="cancelled",
                latest_stage="cancelled",
                latest_summary="任务已取消，未生成最终结果。",
                failure_category="cancelled",
                failure_reason="用户请求取消。",
                error_message="任务已取消。",
            )
            return
        store.update_run(
            run_id,
            status="failed",
            latest_stage="runtime",
            latest_summary="任务运行失败。",
            failure_category="unknown",
            failure_reason=str(exc),
            error_message=str(exc),
        )
        return
    except Exception as exc:  # noqa: BLE001 - background task must persist its failure.
        _mark_message_run_failed(run_id, exc)
        return

    if cancel_checker():
        store.update_run(
            run_id,
            status="cancelled",
            latest_stage="cancelled",
            latest_summary="任务已取消，未生成最终结果。",
            failure_category="cancelled",
            failure_reason="用户请求取消。",
            error_message="任务已取消。",
        )
        return

    _complete_message_run(run_id, response, record)


def _run_status_payload(run_id: str) -> dict[str, Any]:
    store = _current_run_store()
    record = store.get_run(run_id) or _recover_missing_message_run(run_id)
    if record is None:
        return {
            "response_version": "v1",
            "success": False,
            "errors": [{"error_type": "LOGIC_FORM_ERROR", "error_message": f"Run not found: {run_id}"}],
        }
    if record.get("status") in {"queued", "running", "cancel_requested"} and run_id not in _active_jobs:
        record = store.mark_orphaned_if_active(run_id) or record
    return {"response_version": "v1", "success": True, "run": public_run_status(record)}


def get_run(run_id: str) -> JSONResponse:
    """Non-FastAPI helper mirroring GET /api/data-agent/runs/{run_id}."""

    payload = _run_status_payload(run_id)
    return JSONResponse(content=payload, status_code=200 if payload.get("success") else 404)


def get_run_result(run_id: str) -> JSONResponse:
    """Non-FastAPI helper mirroring GET /api/data-agent/runs/{run_id}/result."""

    result = _current_run_store().get_result(run_id)
    if result is None:
        _recover_missing_message_run(run_id)
        result = _current_run_store().get_result(run_id)
    if result is None:
        return JSONResponse(
            content={
                "response_version": "v1",
                "success": False,
                "errors": [{"error_type": "LOGIC_FORM_ERROR", "error_message": f"Run result not available: {run_id}"}],
            },
            status_code=404,
        )
    return JSONResponse(content={"response_version": "v1", "success": True, "result": result})


def _failure_category_from_error(message: str, *, failed_step: str = "", error_type: str = "") -> str:
    text = f"{failed_step} {error_type} {message}".lower()
    if "cancel" in text:
        return "cancelled"
    if "dataset" in text and ("not found" in text or "restore" in text or "expired" in text or "过期" in text):
        return "dataset_restore"
    if "parse" in text or "file_parse" in text or "upload" in text:
        return "file_parse"
    if "planner" in text or "logic_form" in text:
        return "planner"
    if "executor" in text or "pandas" in text or "sql" in text:
        return "executor"
    if "verifier" in text or "verification" in text:
        return "verifier"
    if "timeout" in text or "timed out" in text or "provider" in text or "llm" in text:
        return "provider_timeout"
    return "unknown"


def _failure_category_label(category: str) -> str:
    labels = {
        "dataset_restore": "数据集恢复失败",
        "file_parse": "文件解析失败",
        "planner": "计划生成失败",
        "executor": "计算执行失败",
        "verifier": "结果校验失败",
        "provider_timeout": "模型或服务超时",
        "cancelled": "任务已取消",
        "unknown": "未知错误",
    }
    return labels.get(category or "unknown", "未知错误")


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
    from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse

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
        response = _execute_message_sync(payload)
        return JSONResponse(content=response, status_code=_http_status_for_response(response))

    @router.post("/message/jobs")
    async def create_message_job(payload: MessagePayload) -> Any:
        response = await _create_message_job(payload)
        if response.get("success") is False:
            return JSONResponse(content=response, status_code=_http_status_for_response(response))
        return response

    @router.get("/runs/{run_id}")
    def get_run(run_id: str) -> JSONResponse:
        payload = _run_status_payload(run_id)
        return JSONResponse(content=payload, status_code=200 if payload.get("success") else 404)

    @router.get("/runs/{run_id}/result")
    def get_run_result(run_id: str) -> JSONResponse:
        result = _current_run_store().get_result(run_id)
        if result is None:
            _recover_missing_message_run(run_id)
            result = _current_run_store().get_result(run_id)
        if result is None:
            return JSONResponse(
                content={
                    "response_version": "v1",
                    "success": False,
                    "errors": [{"error_type": "LOGIC_FORM_ERROR", "error_message": f"Run result not available: {run_id}"}],
                },
                status_code=404,
            )
        return JSONResponse(content={"response_version": "v1", "success": True, "result": result})

    @router.post("/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> JSONResponse:
        record = _current_run_store().request_cancel(run_id)
        if record is None:
            return JSONResponse(
                content={
                    "response_version": "v1",
                    "success": False,
                    "errors": [{"error_type": "LOGIC_FORM_ERROR", "error_message": f"Run not found: {run_id}"}],
                },
                status_code=404,
            )
        return JSONResponse(content={"response_version": "v1", "success": True, "run": public_run_status(record)})

    @router.post("/runs/{run_id}/retry")
    async def retry_run(run_id: str) -> JSONResponse:
        record = _current_run_store().get_run(run_id)
        if record is None:
            return JSONResponse(
                content={
                    "response_version": "v1",
                    "success": False,
                    "errors": [{"error_type": "LOGIC_FORM_ERROR", "error_message": f"Run not found: {run_id}"}],
                },
                status_code=404,
            )
        payload = await _create_message_job(record.get("request") if isinstance(record.get("request"), dict) else {}, retry_of=run_id)
        return JSONResponse(content=payload, status_code=_http_status_for_response(payload))

    @router.get("/runs/{run_id}/exports/{artifact_id}")
    def download_run_export(run_id: str, artifact_id: str) -> Response:
        resolved = resolve_export_artifact(service.file_store.runs_root, run_id, artifact_id)
        if resolved is None:
            return JSONResponse(
                content={
                    "response_version": "v1",
                    "success": False,
                    "errors": [{"error_type": "LOGIC_FORM_ERROR", "error_message": f"Export artifact not found: {artifact_id}"}],
                },
                status_code=404,
            )
        path, artifact = resolved
        return FileResponse(
            path,
            media_type=str(artifact.get("mime_type") or "application/octet-stream"),
            filename=str(artifact.get("download_name") or artifact.get("file_name") or path.name),
        )

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
