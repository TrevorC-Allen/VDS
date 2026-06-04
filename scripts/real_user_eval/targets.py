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
    semantic_status: str = "not_available"
    contract_satisfied: bool | None = None
    contract_family: str = ""
    violations: tuple[Mapping[str, Any], ...] = ()
    contract_report: Mapping[str, Any] = field(default_factory=dict)
    oracle_result: Mapping[str, Any] = field(default_factory=dict)
    oracle_available: bool | None = None
    oracle_passed: bool | None = None
    oracle_issue_codes: tuple[str, ...] = ()
    semantic_evidence_available: bool = False
    semantic_evidence_missing_reason: str = "semantic_oracle_fields_not_available"

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
    semantic_evidence = extract_runtime_semantic_evidence(response)
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
        semantic_status=semantic_evidence["semantic_status"],
        contract_satisfied=semantic_evidence["contract_satisfied"],
        contract_family=semantic_evidence["contract_family"],
        violations=tuple(semantic_evidence["violations"]),
        contract_report=semantic_evidence["contract_report"],
        oracle_result=semantic_evidence["oracle_result"],
        oracle_available=semantic_evidence["oracle_available"],
        oracle_passed=semantic_evidence["oracle_passed"],
        oracle_issue_codes=tuple(semantic_evidence["oracle_issue_codes"]),
        semantic_evidence_available=semantic_evidence["semantic_evidence_available"],
        semantic_evidence_missing_reason=semantic_evidence["semantic_evidence_missing_reason"],
    )


def extract_runtime_semantic_evidence(response: Mapping[str, Any]) -> dict[str, Any]:
    """Extract semantic contract/oracle evidence from current and legacy response shapes."""

    verification = response.get("verification") if isinstance(response.get("verification"), Mapping) else {}
    debug = response.get("debug") if isinstance(response.get("debug"), Mapping) else {}
    payloads = (response, verification, debug)
    contract_report = _first_mapping(payloads, "contract_report")
    oracle_result = _first_mapping(payloads, "oracle_result")
    semantic_status = _first_text(payloads, "semantic_status") or "not_available"
    contract_satisfied = _first_bool(payloads, "contract_satisfied")
    contract_family = _first_text(payloads, "contract_family") or str(contract_report.get("task_family") or "")
    violations = _violations_from_payloads(payloads, contract_report)
    oracle_available = _first_bool(payloads, "oracle_available")
    oracle_passed = _first_bool(payloads, "oracle_passed")
    if oracle_available is None and "oracle_available" in oracle_result:
        oracle_available = bool(oracle_result.get("oracle_available"))
    if oracle_passed is None and isinstance(oracle_result.get("passed"), bool):
        oracle_passed = bool(oracle_result.get("passed"))
    oracle_issue_codes = _oracle_issue_codes(payloads, oracle_result)
    evidence_available = any(
        (
            semantic_status != "not_available",
            contract_satisfied is not None,
            bool(contract_family),
            bool(violations),
            bool(contract_report),
            bool(oracle_result),
            oracle_available is not None,
            oracle_passed is not None,
            bool(oracle_issue_codes),
        )
    )
    missing_parts = []
    if semantic_status == "not_available":
        missing_parts.append("semantic_status")
    if contract_satisfied is None:
        missing_parts.append("contract_satisfied")
    if not contract_report:
        missing_parts.append("contract_report")
    if not oracle_result and oracle_available is None and oracle_passed is None and not oracle_issue_codes:
        missing_parts.append("oracle_result")
    return {
        "semantic_status": semantic_status,
        "contract_satisfied": contract_satisfied,
        "contract_family": contract_family,
        "violations": violations,
        "contract_report": contract_report,
        "oracle_result": oracle_result,
        "oracle_available": oracle_available,
        "oracle_passed": oracle_passed,
        "oracle_issue_codes": oracle_issue_codes,
        "semantic_evidence_available": evidence_available,
        "semantic_evidence_missing_reason": "not_available:" + ",".join(missing_parts) if missing_parts else "",
    }


def _first_mapping(payloads: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    for payload in payloads:
        value = payload.get(key)
        if isinstance(value, Mapping) and value:
            return dict(value)
    return {}


def _first_text(payloads: Sequence[Mapping[str, Any]], key: str) -> str:
    for payload in payloads:
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _first_bool(payloads: Sequence[Mapping[str, Any]], key: str) -> bool | None:
    for payload in payloads:
        value = payload.get(key)
        if isinstance(value, bool):
            return value
    return None


def _violations_from_payloads(payloads: Sequence[Mapping[str, Any]], contract_report: Mapping[str, Any]) -> list[dict[str, Any]]:
    for payload in payloads:
        value = payload.get("violations")
        if isinstance(value, list):
            return [_dict_violation(item) for item in value]
    value = contract_report.get("violations")
    if isinstance(value, list):
        return [_dict_violation(item) for item in value]
    return []


def _dict_violation(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {"code": str(value)}


def _oracle_issue_codes(payloads: Sequence[Mapping[str, Any]], oracle_result: Mapping[str, Any]) -> list[str]:
    for key in ("oracle_issue_codes", "issue_codes"):
        for payload in payloads:
            value = payload.get(key)
            if isinstance(value, list):
                return [str(item) for item in value if str(item)]
    value = oracle_result.get("issue_codes")
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []


def _normalize_payload_key(key: object) -> str:
    chars: list[str] = []
    for char in str(key).strip():
        if char.isupper() and chars:
            chars.append("_")
        chars.append(char.lower() if char.isalnum() else "_")
    return "_".join(part for part in "".join(chars).split("_") if part)
