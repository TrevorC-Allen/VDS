"""Target primitives for real-user VDS evaluation runs.

Targets model only the user-visible act of asking VDS. They intentionally do
not carry oracle fields, expected facts, or benchmark answers into service or
HTTP payloads.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "answer_key",
        "expected_answer",
        "expected_facts",
        "oracle",
        "raw_prompt",
        "standard_answer",
        "task_id",
    }
)


@dataclass(frozen=True)
class TargetRequest:
    """One real-user style request sent to a VDS execution target."""

    question: str
    file_paths: tuple[Path, ...] = ()
    dataset_id: str = ""
    conversation_id: str = ""
    project_id: str = ""
    owner_id: str = ""
    tenant_id: str = ""
    owner_context: Mapping[str, Any] | None = None
    execution_mode: str = "dual"
    guidelines: str = ""
    agent_mode: str = "multi_agent"
    user_rule_file_id: str = ""
    monitor_run_id: str = ""
    run_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentResult:
    """Uniform result returned by service and HTTP real-user targets."""

    target: str
    success: bool
    status: str
    answer_text: str = ""
    run_id: str = ""
    conversation_id: str = ""
    dataset_id: str = ""
    evidence_id: str = ""
    raw_response: Mapping[str, Any] = field(default_factory=dict)
    issues: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvalTarget(Protocol):
    """Execution boundary consumed by the real-user runner."""

    def run(self, request: TargetRequest | Mapping[str, Any] | str, **kwargs: Any) -> AgentResult:
        """Ask VDS through the target and return a uniform result."""


def coerce_target_request(
    request: TargetRequest | Mapping[str, Any] | str | None = None,
    *,
    question: str | None = None,
    file_paths: Sequence[str | Path] | None = None,
    files: Sequence[str | Path] | None = None,
    **kwargs: Any,
) -> TargetRequest:
    """Normalize flexible test/runner input into a TargetRequest."""

    if isinstance(request, TargetRequest):
        base = request
        if not kwargs and question is None and file_paths is None and files is None:
            return base
        data = base.to_dict() if hasattr(base, "to_dict") else asdict(base)
    elif isinstance(request, Mapping):
        data = dict(request)
    elif isinstance(request, str):
        data = {"question": request}
    elif request is None:
        data = {}
    else:
        raise TypeError(f"Unsupported target request: {type(request)!r}")

    data.update(kwargs)
    if question is not None:
        data["question"] = question
    if file_paths is not None:
        data["file_paths"] = file_paths
    if files is not None:
        data["file_paths"] = files

    public_data = public_agent_payload(data)
    raw_question = (
        public_data.get("question")
        or public_data.get("user_intent")
        or public_data.get("user_goal")
        or ""
    )
    normalized_files = tuple(Path(path) for path in public_data.get("file_paths", ()) or ())
    metadata = public_data.get("metadata") if isinstance(public_data.get("metadata"), Mapping) else {}
    owner_context = public_data.get("owner_context") if isinstance(public_data.get("owner_context"), Mapping) else None
    return TargetRequest(
        question=str(raw_question),
        file_paths=normalized_files,
        dataset_id=str(public_data.get("dataset_id") or ""),
        conversation_id=str(public_data.get("conversation_id") or ""),
        project_id=str(public_data.get("project_id") or ""),
        owner_id=str(public_data.get("owner_id") or ""),
        tenant_id=str(public_data.get("tenant_id") or ""),
        owner_context=owner_context,
        execution_mode=str(public_data.get("execution_mode") or "dual"),
        guidelines=str(public_data.get("guidelines") or ""),
        agent_mode=str(public_data.get("agent_mode") or "multi_agent"),
        user_rule_file_id=str(public_data.get("user_rule_file_id") or ""),
        monitor_run_id=str(public_data.get("monitor_run_id") or ""),
        run_id=str(public_data["run_id"]) if public_data.get("run_id") else None,
        metadata=dict(metadata),
    )


def public_agent_payload(value: Any) -> Any:
    """Return a copy with oracle/answer-bearing fields removed recursively."""

    if isinstance(value, Mapping):
        public: dict[str, Any] = {}
        for key, child in value.items():
            normalized_key = _normalize_payload_key(key)
            if normalized_key in FORBIDDEN_PAYLOAD_KEYS:
                continue
            public[str(key)] = public_agent_payload(child)
        return public
    if isinstance(value, list):
        return [public_agent_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(public_agent_payload(item) for item in value)
    return value


def service_message_payload(request: TargetRequest) -> dict[str, Any]:
    """Build the safe payload shape accepted by DataAgentService/message APIs."""

    payload = {
        "question": request.question,
        "dataset_id": request.dataset_id,
        "conversation_id": request.conversation_id,
        "project_id": request.project_id,
        "owner_id": request.owner_id,
        "tenant_id": request.tenant_id,
        "owner_context": dict(request.owner_context) if request.owner_context else None,
        "execution_mode": request.execution_mode,
        "guidelines": request.guidelines,
        "agent_mode": request.agent_mode,
        "user_rule_file_id": request.user_rule_file_id,
        "monitor_run_id": request.monitor_run_id,
    }
    return {key: value for key, value in public_agent_payload(payload).items() if value not in ("", None)}


def agent_result_from_response(
    *,
    target: str,
    response: Mapping[str, Any],
    fallback_run_id: str = "",
    fallback_dataset_id: str = "",
    status: str | None = None,
    issues: Sequence[str] = (),
    metadata: Mapping[str, Any] | None = None,
) -> AgentResult:
    """Normalize a service or HTTP result response into AgentResult."""

    answer_text = str(response.get("answer") or response.get("answer_text") or "")
    run_id = str(response.get("run_id") or fallback_run_id or "")
    conversation_id = str(response.get("conversation_id") or "")
    dataset_id = str(response.get("dataset_id") or fallback_dataset_id or "")
    success = response.get("success") is not False and not issues
    normalized_status = status or ("completed" if success else "failed")
    if not success and normalized_status == "completed":
        normalized_status = "failed"
    return AgentResult(
        target=target,
        success=success,
        status=normalized_status,
        answer_text=answer_text,
        run_id=run_id,
        conversation_id=conversation_id,
        dataset_id=dataset_id,
        evidence_id=run_id,
        raw_response=dict(response),
        issues=tuple(issues),
        metadata=dict(metadata or {}),
    )


def _normalize_payload_key(key: object) -> str:
    chars: list[str] = []
    for char in str(key).strip():
        if char.isupper() and chars:
            chars.append("_")
        chars.append(char.lower() if char.isalnum() else "_")
    return "_".join(part for part in "".join(chars).split("_") if part)
