"""HTTP execution target for real-user evaluation evidence runs."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
import time
from typing import Any, Mapping, Sequence
import urllib.error
import urllib.request
import uuid

from scripts.real_user_eval.targets import (
    AgentResult,
    TargetRequest,
    agent_result_from_response,
    coerce_target_request,
    service_message_payload,
)


class HttpTargetError(RuntimeError):
    """HTTP target request failure with optional status code evidence."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class UrllibHttpClient:
    """Small JSON/multipart client used by HttpEvalTarget."""

    def request_json(
        self,
        method: str,
        url: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        data = None
        headers: dict[str, str] = {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        return _open_json(request, timeout=timeout)

    def multipart_upload(
        self,
        url: str,
        files: Sequence[tuple[str, Path, str]],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        boundary = "----vdsrealuser" + uuid.uuid4().hex
        body = bytearray()
        for field, path, filename in files:
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode())
            body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
            body.extend(Path(path).read_bytes())
            body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())
        request = urllib.request.Request(
            url,
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        return _open_json(request, timeout=timeout)


class HttpEvalTarget:
    """Ask VDS through the real HTTP API and persist run-id evidence."""

    target_name = "http"

    def __init__(
        self,
        base_url: str,
        *,
        client: Any | None = None,
        timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 1.0,
        max_poll_seconds: float = 180.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client if client is not None else UrllibHttpClient()
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_poll_seconds = max_poll_seconds

    def run(
        self,
        request: TargetRequest | Mapping[str, Any] | str | None = None,
        *,
        file_paths: Sequence[str | Path] | None = None,
        files: Sequence[str | Path] | None = None,
        resume_run_id: str = "",
        **kwargs: Any,
    ) -> AgentResult:
        target_request = coerce_target_request(request, file_paths=file_paths, files=files, **kwargs)
        run_id = str(resume_run_id or target_request.run_id or "")
        dataset_id = target_request.dataset_id
        upload_metadata: dict[str, Any] = {}
        if not run_id:
            dataset_id, upload_issues, upload_metadata = self._upload_files(target_request)
            if upload_issues:
                return AgentResult(
                    target=self.target_name,
                    success=False,
                    status="failed",
                    dataset_id=dataset_id,
                    issues=tuple(upload_issues),
                    metadata=upload_metadata,
                )
            job_payload = service_message_payload(_with_dataset_id(target_request, dataset_id))
            job = self._request_json("POST", "/message/jobs", job_payload)
            if isinstance(job, AgentResult):
                return job
            run = job.get("run") if isinstance(job.get("run"), Mapping) else None
            run_id = str(run.get("run_id") or "") if run else ""
            if not run_id:
                return AgentResult(
                    target=self.target_name,
                    success=False,
                    status="failed",
                    dataset_id=dataset_id,
                    issues=("http_job_missing_run_id: expected body['run']['run_id']",),
                    raw_response=job,
                    metadata=upload_metadata,
                )

        status_payload = self._poll_run(run_id)
        if isinstance(status_payload, AgentResult):
            return status_payload
        run_status = _run_status(status_payload)
        if run_status in {"failed", "cancelled"}:
            return AgentResult(
                target=self.target_name,
                success=False,
                status=run_status,
                run_id=run_id,
                dataset_id=dataset_id,
                evidence_id=run_id,
                raw_response=status_payload,
                issues=(f"http_run_{run_status}: {_failure_reason(status_payload)}",),
                metadata=upload_metadata,
            )

        result_payload = self._request_json("GET", f"/runs/{run_id}/result")
        if isinstance(result_payload, AgentResult):
            return result_payload
        result = result_payload.get("result")
        if not isinstance(result, Mapping):
            return AgentResult(
                target=self.target_name,
                success=False,
                status="failed",
                run_id=run_id,
                dataset_id=dataset_id,
                evidence_id=run_id,
                raw_response=result_payload,
                issues=("http_result_missing: expected body['result'] after completed run",),
                metadata=upload_metadata,
            )
        return agent_result_from_response(
            target=self.target_name,
            response=result,
            fallback_run_id=run_id,
            fallback_dataset_id=dataset_id,
            status=run_status or None,
            metadata=upload_metadata,
        )

    def execute(self, request: TargetRequest | Mapping[str, Any] | str | None = None, **kwargs: Any) -> AgentResult:
        return self.run(request, **kwargs)

    def ask(self, question: str, **kwargs: Any) -> AgentResult:
        return self.run(question, **kwargs)

    def _upload_files(self, request: TargetRequest) -> tuple[str, list[str], dict[str, Any]]:
        if not request.file_paths:
            return request.dataset_id, [], {}
        upload_files = [("files", Path(path), Path(path).name) for path in request.file_paths]
        upload = self._multipart_upload("/upload-batch", upload_files)
        if isinstance(upload, AgentResult):
            return request.dataset_id, list(upload.issues), {}
        dataset_id = str(upload.get("dataset_id") or request.dataset_id or "")
        if upload.get("success") is False or not dataset_id:
            return dataset_id, [f"http_upload_failed: {_brief(upload)}"], {"upload": upload}
        return dataset_id, [], {"upload": upload}

    def _poll_run(self, run_id: str) -> dict[str, Any] | AgentResult:
        deadline = time.monotonic() + self.max_poll_seconds
        last_payload: dict[str, Any] = {}
        while True:
            payload = self._request_json("GET", f"/runs/{run_id}")
            if isinstance(payload, AgentResult):
                return payload
            last_payload = payload
            status = _run_status(payload)
            if status in {"completed", "failed", "cancelled"}:
                return payload
            if time.monotonic() >= deadline:
                return AgentResult(
                    target=self.target_name,
                    success=False,
                    status="timeout",
                    run_id=run_id,
                    evidence_id=run_id,
                    raw_response=last_payload,
                    issues=(f"http_poll_timeout: run {run_id} did not complete within {self.max_poll_seconds:g}s",),
                )
            time.sleep(max(0.0, self.poll_interval_seconds))

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | AgentResult:
        url = self._url(path)
        try:
            return self.client.request_json(method, url, payload, timeout=self.timeout_seconds)
        except HttpTargetError as exc:
            return _http_failure_result(self.target_name, method, path, exc)
        except Exception as exc:  # noqa: BLE001 - target must return comparable failure data.
            return AgentResult(
                target=self.target_name,
                success=False,
                status="failed",
                issues=(f"http_request_failed: {method} {path}: {exc}",),
            )

    def _multipart_upload(self, path: str, files: Sequence[tuple[str, Path, str]]) -> dict[str, Any] | AgentResult:
        try:
            return self.client.multipart_upload(self._url(path), files, timeout=self.timeout_seconds)
        except HttpTargetError as exc:
            return _http_failure_result(self.target_name, "POST", path, exc)
        except Exception as exc:  # noqa: BLE001 - target must return comparable failure data.
            return AgentResult(
                target=self.target_name,
                success=False,
                status="failed",
                issues=(f"http_upload_request_failed: POST {path}: {exc}",),
            )

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/data-agent{path}"


def _open_json(request: urllib.request.Request, *, timeout: float) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise HttpTargetError(f"HTTP {exc.code}: {body[:500]}", status_code=exc.code) from exc
    except urllib.error.URLError as exc:
        raise HttpTargetError(f"HTTP request unavailable: {exc}", status_code=None) from exc
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as exc:
        raise HttpTargetError(f"Invalid JSON response: {data[:500]}") from exc
    if not isinstance(parsed, dict):
        raise HttpTargetError(f"Expected JSON object response, got {type(parsed).__name__}")
    return parsed


def _with_dataset_id(request: TargetRequest, dataset_id: str) -> TargetRequest:
    return TargetRequest(
        question=request.question,
        file_paths=request.file_paths,
        dataset_id=dataset_id,
        conversation_id=request.conversation_id,
        project_id=request.project_id,
        owner_id=request.owner_id,
        tenant_id=request.tenant_id,
        owner_context=request.owner_context,
        execution_mode=request.execution_mode,
        guidelines=request.guidelines,
        agent_mode=request.agent_mode,
        user_rule_file_id=request.user_rule_file_id,
        monitor_run_id=request.monitor_run_id,
        run_id=request.run_id,
        metadata=request.metadata,
    )


def _http_failure_result(target: str, method: str, path: str, exc: HttpTargetError) -> AgentResult:
    prefix = f"HTTP {exc.status_code}" if exc.status_code else "HTTP unavailable"
    return AgentResult(
        target=target,
        success=False,
        status="failed",
        issues=(f"http_error: {method} {path}: {prefix}: {exc}",),
    )


def _run_status(payload: Mapping[str, Any]) -> str:
    run = payload.get("run") if isinstance(payload.get("run"), Mapping) else {}
    return str(run.get("status") or payload.get("status") or "")


def _failure_reason(payload: Mapping[str, Any]) -> str:
    run = payload.get("run") if isinstance(payload.get("run"), Mapping) else {}
    reason = run.get("failure_reason") or run.get("error_message") or run.get("latest_summary") or payload.get("error")
    return str(reason or "no failure reason returned")


def _brief(value: Mapping[str, Any]) -> str:
    errors = value.get("errors")
    if errors:
        return str(errors)
    return str({key: value.get(key) for key in ("success", "dataset_id", "error", "message") if key in value})


HttpTarget = HttpEvalTarget
