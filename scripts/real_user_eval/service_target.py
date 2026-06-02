"""Local service execution target for real-user evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.real_user_eval.targets import (
    AgentResult,
    TargetRequest,
    agent_result_from_response,
    coerce_target_request,
    service_message_payload,
)


class ServiceEvalTarget:
    """Ask VDS through an in-process DataAgentService instance."""

    target_name = "service"

    def __init__(self, service: Any | None = None) -> None:
        self.service = service if service is not None else self._default_service()

    def run(
        self,
        request: TargetRequest | Mapping[str, Any] | str | None = None,
        *,
        file_paths: Sequence[str | Path] | None = None,
        files: Sequence[str | Path] | None = None,
        **kwargs: Any,
    ) -> AgentResult:
        target_request = coerce_target_request(request, file_paths=file_paths, files=files, **kwargs)
        dataset_id, upload_issues, upload_metadata = self._upload_files(target_request)
        if upload_issues:
            return AgentResult(
                target=self.target_name,
                success=False,
                status="failed",
                dataset_id=dataset_id,
                evidence_id=target_request.run_id or "",
                issues=tuple(upload_issues),
                metadata=upload_metadata,
            )

        payload = service_message_payload(
            TargetRequest(
                question=target_request.question,
                file_paths=target_request.file_paths,
                dataset_id=dataset_id,
                conversation_id=target_request.conversation_id,
                project_id=target_request.project_id,
                owner_id=target_request.owner_id,
                tenant_id=target_request.tenant_id,
                owner_context=target_request.owner_context,
                execution_mode=target_request.execution_mode,
                guidelines=target_request.guidelines,
                agent_mode=target_request.agent_mode,
                user_rule_file_id=target_request.user_rule_file_id,
                monitor_run_id=target_request.monitor_run_id,
                run_id=target_request.run_id,
                metadata=target_request.metadata,
            )
        )
        if target_request.run_id:
            payload["run_id"] = target_request.run_id
        try:
            response = self.service.respond_to_message(**payload)
        except Exception as exc:  # noqa: BLE001 - target must return comparable failure data.
            return AgentResult(
                target=self.target_name,
                success=False,
                status="failed",
                dataset_id=dataset_id,
                evidence_id=target_request.run_id or "",
                issues=(f"service_error: {exc}",),
                metadata=upload_metadata,
            )
        return agent_result_from_response(
            target=self.target_name,
            response=response if isinstance(response, Mapping) else {"success": False, "answer": str(response)},
            fallback_run_id=target_request.run_id or "",
            fallback_dataset_id=dataset_id,
            metadata=upload_metadata,
        )

    def execute(self, request: TargetRequest | Mapping[str, Any] | str | None = None, **kwargs: Any) -> AgentResult:
        return self.run(request, **kwargs)

    def ask(self, question: str, **kwargs: Any) -> AgentResult:
        return self.run(question, **kwargs)

    def _upload_files(self, request: TargetRequest) -> tuple[str, list[str], dict[str, Any]]:
        if not request.file_paths:
            return request.dataset_id, [], {}
        file_paths = [Path(path) for path in request.file_paths]
        original_filenames = [path.name for path in file_paths]
        try:
            upload = self.service.upload_datasets(file_paths, original_filenames=original_filenames)
        except Exception as exc:  # noqa: BLE001 - target must keep failure evidence explicit.
            return request.dataset_id, [f"service_upload_error: {exc}"], {}
        if not isinstance(upload, Mapping):
            return request.dataset_id, [f"service_upload_failed: unexpected upload response {upload!r}"], {}
        dataset_id = str(upload.get("dataset_id") or request.dataset_id or "")
        if upload.get("success") is False or not dataset_id:
            return dataset_id, [f"service_upload_failed: {_brief(upload)}"], {"upload": dict(upload)}
        return dataset_id, [], {"upload": dict(upload)}

    @staticmethod
    def _default_service() -> Any:
        from backend.services.data_agent_service import DataAgentService

        return DataAgentService()


def _brief(value: Mapping[str, Any]) -> str:
    errors = value.get("errors")
    if errors:
        return str(errors)
    return str({key: value.get(key) for key in ("success", "dataset_id", "error", "message") if key in value})


ServiceTarget = ServiceEvalTarget
