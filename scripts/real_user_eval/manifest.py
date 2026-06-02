"""Manifest schema helpers for real-user VDS evaluation cases."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


REQUIRED_CASE_FIELDS = {
    "case_id",
    "dataset",
    "capability_family",
    "canonical_question",
    "question_variants",
    "expected_contract",
    "oracle_type",
    "oracle_query_or_formula",
    "answer_requirements",
    "severity",
    "tags",
}

FORBIDDEN_VARIANT_TOKENS = (
    "raw_prompt",
    "standard_answer",
    "expected_answer",
    "answer_key",
    "task_id",
)

SUPPORTED_ORACLE_TYPES = {"duckdb_sql", "literal", "none"}


@dataclass(frozen=True)
class ManifestCase:
    case_id: str
    dataset: str
    capability_family: str
    canonical_question: str
    question_variants: tuple[str, ...]
    expected_contract: str
    oracle_type: str
    oracle_query_or_formula: Any
    answer_requirements: Mapping[str, Any]
    severity: str
    tags: tuple[str, ...]
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class ConversationTurn:
    turn_id: str
    question: str
    expected_contract: str
    oracle_type: str
    oracle_query_or_formula: Any
    answer_requirements: Mapping[str, Any]


@dataclass(frozen=True)
class ConversationCase:
    conversation_id: str
    dataset: str
    capability_family: str
    severity: str
    tags: tuple[str, ...]
    turns: tuple[ConversationTurn, ...]
    metadata: Mapping[str, Any]


def load_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("real-user manifest must be a JSON object")
    validate_manifest(data)
    return data


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    datasets = manifest.get("datasets")
    cases = manifest.get("cases")
    if not isinstance(datasets, dict) or not datasets:
        raise ValueError("manifest.datasets must be a non-empty object")
    if not isinstance(cases, list) or not cases:
        raise ValueError("manifest.cases must be a non-empty array")
    for name, dataset in datasets.items():
        _validate_dataset(str(name), dataset)
    seen_case_ids: set[str] = set()
    for raw_case in cases:
        case = _coerce_case(raw_case)
        if case.dataset not in datasets:
            raise ValueError(f"{case.case_id}: unknown dataset {case.dataset!r}")
        if case.case_id in seen_case_ids:
            raise ValueError(f"duplicate case_id: {case.case_id}")
        seen_case_ids.add(case.case_id)
    for raw_conversation in manifest.get("conversations", []) or []:
        conversation = _coerce_conversation(raw_conversation)
        if conversation.dataset not in datasets:
            raise ValueError(f"{conversation.conversation_id}: unknown dataset {conversation.dataset!r}")


def coverage_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    cases = manifest_cases(manifest)
    conversations = manifest_conversations(manifest)
    datasets = sorted({case.dataset for case in cases} | {conversation.dataset for conversation in conversations})
    cases_by_dataset: dict[str, int] = {dataset: 0 for dataset in datasets}
    variants_by_case = {}
    for case in cases:
        cases_by_dataset[case.dataset] = cases_by_dataset.get(case.dataset, 0) + 1
        variants_by_case[case.case_id] = len(case.question_variants)
    return {
        "dataset_count": len(datasets),
        "datasets": datasets,
        "case_count": len(cases),
        "cases_by_dataset": cases_by_dataset,
        "min_cases_per_dataset": min(cases_by_dataset.values()) if cases_by_dataset else 0,
        "min_variants_per_case": min(variants_by_case.values()) if variants_by_case else 0,
        "conversation_count": len(conversations),
        "min_turns_per_conversation": min((len(item.turns) for item in conversations), default=0),
    }


def validate_v1_coverage(
    manifest: Mapping[str, Any],
    *,
    min_datasets: int = 6,
    min_cases_per_dataset: int = 8,
    min_variants_per_case: int = 5,
    min_conversations: int = 20,
    min_turns_per_conversation: int = 3,
) -> dict[str, Any]:
    summary = coverage_summary(manifest)
    failures = []
    if summary["dataset_count"] < min_datasets:
        failures.append(f"dataset_count {summary['dataset_count']} < {min_datasets}")
    if summary["min_cases_per_dataset"] < min_cases_per_dataset:
        failures.append(f"min_cases_per_dataset {summary['min_cases_per_dataset']} < {min_cases_per_dataset}")
    if summary["min_variants_per_case"] < min_variants_per_case:
        failures.append(f"min_variants_per_case {summary['min_variants_per_case']} < {min_variants_per_case}")
    if summary["conversation_count"] < min_conversations:
        failures.append(f"conversation_count {summary['conversation_count']} < {min_conversations}")
    if summary["min_turns_per_conversation"] < min_turns_per_conversation:
        failures.append(
            f"min_turns_per_conversation {summary['min_turns_per_conversation']} < {min_turns_per_conversation}"
        )
    if failures:
        raise ValueError("real-user v1 coverage failed: " + "; ".join(failures))
    return summary


def manifest_cases(manifest: Mapping[str, Any]) -> list[ManifestCase]:
    validate_manifest(manifest)
    return [_coerce_case(raw_case) for raw_case in manifest.get("cases", [])]


def manifest_conversations(manifest: Mapping[str, Any]) -> list[ConversationCase]:
    validate_manifest(manifest)
    return [_coerce_conversation(raw_case) for raw_case in manifest.get("conversations", []) or []]


def dataset_file_paths(manifest: Mapping[str, Any], dataset_name: str) -> list[Path]:
    datasets = manifest.get("datasets")
    if not isinstance(datasets, Mapping) or dataset_name not in datasets:
        raise ValueError(f"unknown dataset {dataset_name!r}")
    dataset = datasets[dataset_name]
    if not isinstance(dataset, Mapping):
        raise ValueError(f"dataset {dataset_name!r} must be an object")
    return [Path(path).expanduser() for path in dataset.get("files", []) or []]


def _validate_dataset(name: str, dataset: Any) -> None:
    if not isinstance(dataset, Mapping):
        raise ValueError(f"dataset {name!r} must be an object")
    files = dataset.get("files")
    if not isinstance(files, list):
        raise ValueError(f"dataset {name!r}.files must be an array")
    for item in files:
        if not str(item).strip():
            raise ValueError(f"dataset {name!r}.files contains an empty path")


def _coerce_case(value: Any) -> ManifestCase:
    if not isinstance(value, Mapping):
        raise ValueError("manifest case must be an object")
    missing = sorted(REQUIRED_CASE_FIELDS - set(value.keys()))
    if missing:
        raise ValueError(f"case is missing required fields: {', '.join(missing)}")
    case_id = _required_text(value, "case_id")
    variants = _text_list(value.get("question_variants"), f"{case_id}.question_variants")
    if not variants:
        raise ValueError(f"{case_id}.question_variants must not be empty")
    canonical = _required_text(value, "canonical_question")
    for text in [canonical, *variants]:
        _reject_leaked_prompt_tokens(case_id, text)
    oracle_type = _required_text(value, "oracle_type")
    if oracle_type not in SUPPORTED_ORACLE_TYPES:
        raise ValueError(f"{case_id}.oracle_type is unsupported: {oracle_type}")
    requirements = value.get("answer_requirements")
    if not isinstance(requirements, Mapping):
        raise ValueError(f"{case_id}.answer_requirements must be an object")
    return ManifestCase(
        case_id=case_id,
        dataset=_required_text(value, "dataset"),
        capability_family=_required_text(value, "capability_family"),
        canonical_question=canonical,
        question_variants=tuple(variants),
        expected_contract=_required_text(value, "expected_contract"),
        oracle_type=oracle_type,
        oracle_query_or_formula=value.get("oracle_query_or_formula"),
        answer_requirements=dict(requirements),
        severity=_required_text(value, "severity"),
        tags=tuple(_text_list(value.get("tags"), f"{case_id}.tags")),
        metadata=dict(value.get("metadata") or {}),
    )


def _coerce_conversation(value: Any) -> ConversationCase:
    if not isinstance(value, Mapping):
        raise ValueError("conversation case must be an object")
    conversation_id = _required_text(value, "conversation_id")
    raw_turns = value.get("turns")
    if not isinstance(raw_turns, list) or not raw_turns:
        raise ValueError(f"{conversation_id}.turns must be a non-empty array")
    turns = tuple(_coerce_turn(conversation_id, index, raw_turn) for index, raw_turn in enumerate(raw_turns, start=1))
    return ConversationCase(
        conversation_id=conversation_id,
        dataset=_required_text(value, "dataset"),
        capability_family=_required_text(value, "capability_family"),
        severity=_required_text(value, "severity"),
        tags=tuple(_text_list(value.get("tags"), f"{conversation_id}.tags")),
        turns=turns,
        metadata=dict(value.get("metadata") or {}),
    )


def _coerce_turn(conversation_id: str, index: int, value: Any) -> ConversationTurn:
    if not isinstance(value, Mapping):
        raise ValueError(f"{conversation_id}.turns[{index}] must be an object")
    turn_id = str(value.get("turn_id") or f"turn_{index:02d}")
    question = _required_text(value, "question")
    _reject_leaked_prompt_tokens(f"{conversation_id}.{turn_id}", question)
    oracle_type = _required_text(value, "oracle_type")
    if oracle_type not in SUPPORTED_ORACLE_TYPES:
        raise ValueError(f"{conversation_id}.{turn_id}.oracle_type is unsupported: {oracle_type}")
    requirements = value.get("answer_requirements")
    if not isinstance(requirements, Mapping):
        raise ValueError(f"{conversation_id}.{turn_id}.answer_requirements must be an object")
    return ConversationTurn(
        turn_id=turn_id,
        question=question,
        expected_contract=_required_text(value, "expected_contract"),
        oracle_type=oracle_type,
        oracle_query_or_formula=value.get("oracle_query_or_formula"),
        answer_requirements=dict(requirements),
    )


def _required_text(value: Mapping[str, Any], key: str) -> str:
    text = str(value.get(key) or "").strip()
    if not text:
        raise ValueError(f"{key} must be a non-empty string")
    return text


def _text_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    result = [str(item).strip() for item in value if str(item).strip()]
    if len(result) != len(value):
        raise ValueError(f"{field_name} contains an empty item")
    return result


def _reject_leaked_prompt_tokens(case_id: str, text: str) -> None:
    lowered = text.lower()
    for token in FORBIDDEN_VARIANT_TOKENS:
        if token in lowered:
            raise ValueError(f"{case_id}: question text contains forbidden token {token!r}")
