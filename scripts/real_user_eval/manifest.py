"""Manifest schema helpers for real-user VDS evaluation cases."""

from __future__ import annotations

from copy import deepcopy
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
SUPPORTED_CONTRACT_FAMILIES = {
    "topn",
    "gap",
    "trend",
    "contribution",
    "share",
    "contribution_followup",
    "followup_referent",
    "overview",
    "multi_file_overview",
    "data_quality",
}
SUPPORTED_GAP_TYPES = {"", "pairwise", "adjacent"}
GAP_TYPE_ALIASES = {
    "rank_pair": "pairwise",
    "adjacent_and_to_leader": "adjacent",
}
SUPPORTED_CONTEXT_REFERENCES = {
    "",
    "previous_top_objects",
    "previous_result_set",
    "previous_quality_findings",
}
CONTEXT_REFERENCE_ALIASES = {
    "previous_top_set": "previous_top_objects",
}

EXPECTED_CONTRACT_DEFAULTS: dict[str, Any] = {
    "schema_version": 1,
    "contract_family": "",
    "answer_type": "",
    "required_row_count": None,
    "min_row_count": None,
    "allow_insufficient_data_explanation": False,
    "required_dimensions": [],
    "required_metrics": [],
    "required_sort": None,
    "required_gap_type": "",
    "required_context_reference": "",
    "required_all_files_covered": False,
    "required_tables_covered": [],
    "required_join_keys": [],
    "required_field_level_quality": False,
    "required_duplicate_check": False,
    "required_outlier_check": False,
    "requires_direct_answer_first": False,
    "requires_artifact_summary": False,
    "violation_codes_expected_absent": [],
}


@dataclass(frozen=True)
class ManifestCase:
    case_id: str
    dataset: str
    capability_family: str
    canonical_question: str
    question_variants: tuple[str, ...]
    expected_contract: Any
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
    expected_contract: Any
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
    normalized = normalize_manifest(data)
    validate_manifest(normalized)
    return normalized


def normalize_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return a manifest copy with structured expected_contract defaults filled."""

    normalized = deepcopy(dict(manifest))
    cases = normalized.get("cases")
    if isinstance(cases, list):
        normalized_cases = []
        for raw_case in cases:
            if isinstance(raw_case, Mapping):
                case = dict(raw_case)
                case_id = str(case.get("case_id") or "<unknown case>")
                case["expected_contract"] = normalize_expected_contract(
                    case.get("expected_contract"), field_name=f"{case_id}.expected_contract"
                )
                normalized_cases.append(case)
            else:
                normalized_cases.append(raw_case)
        normalized["cases"] = normalized_cases
    conversations = normalized.get("conversations")
    if isinstance(conversations, list):
        normalized_conversations = []
        for raw_conversation in conversations:
            if not isinstance(raw_conversation, Mapping):
                normalized_conversations.append(raw_conversation)
                continue
            conversation = dict(raw_conversation)
            conversation_id = str(conversation.get("conversation_id") or "<unknown conversation>")
            turns = conversation.get("turns")
            if isinstance(turns, list):
                normalized_turns = []
                for index, raw_turn in enumerate(turns, start=1):
                    if isinstance(raw_turn, Mapping):
                        turn = dict(raw_turn)
                        turn_id = str(turn.get("turn_id") or f"turn_{index:02d}")
                        turn["expected_contract"] = normalize_expected_contract(
                            turn.get("expected_contract"),
                            field_name=f"{conversation_id}.{turn_id}.expected_contract",
                        )
                        normalized_turns.append(turn)
                    else:
                        normalized_turns.append(raw_turn)
                conversation["turns"] = normalized_turns
            normalized_conversations.append(conversation)
        normalized["conversations"] = normalized_conversations
    return normalized


def normalize_expected_contract(value: Any, *, field_name: str = "expected_contract") -> str | dict[str, Any]:
    """Normalize structured semantic contracts while preserving legacy text contracts."""

    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field_name} must be a non-empty string or object")
        return text
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a non-empty string or object")

    normalized = deepcopy(EXPECTED_CONTRACT_DEFAULTS)
    normalized.update(dict(value))
    family = _required_contract_text(normalized.get("contract_family"), f"{field_name}.contract_family")
    if family not in SUPPORTED_CONTRACT_FAMILIES:
        supported = ", ".join(sorted(SUPPORTED_CONTRACT_FAMILIES))
        raise ValueError(f"{field_name}.contract_family is unsupported: {family!r}; supported: {supported}")
    normalized["schema_version"] = _optional_positive_int(normalized.get("schema_version"), f"{field_name}.schema_version") or 1
    normalized["contract_family"] = family
    normalized["answer_type"] = _optional_text(normalized.get("answer_type"), f"{field_name}.answer_type")
    normalized["required_row_count"] = _optional_non_negative_int(
        normalized.get("required_row_count"), f"{field_name}.required_row_count"
    )
    normalized["min_row_count"] = _optional_non_negative_int(normalized.get("min_row_count"), f"{field_name}.min_row_count")
    normalized["allow_insufficient_data_explanation"] = _bool(
        normalized.get("allow_insufficient_data_explanation"), f"{field_name}.allow_insufficient_data_explanation"
    )
    normalized["required_dimensions"] = _text_list_or_empty(
        normalized.get("required_dimensions"), f"{field_name}.required_dimensions"
    )
    normalized["required_metrics"] = _text_list_or_empty(normalized.get("required_metrics"), f"{field_name}.required_metrics")
    normalized["required_sort"] = _normalize_required_sort(normalized.get("required_sort"), f"{field_name}.required_sort")
    normalized["required_gap_type"] = _optional_text(normalized.get("required_gap_type"), f"{field_name}.required_gap_type")
    normalized["required_gap_type"] = GAP_TYPE_ALIASES.get(normalized["required_gap_type"], normalized["required_gap_type"])
    if normalized["required_gap_type"] not in SUPPORTED_GAP_TYPES:
        raise ValueError(f"{field_name}.required_gap_type is unsupported: {normalized['required_gap_type']!r}")
    normalized["required_context_reference"] = _normalize_context_reference(
        normalized.get("required_context_reference"), f"{field_name}.required_context_reference"
    )
    normalized["required_all_files_covered"] = _bool(
        normalized.get("required_all_files_covered"), f"{field_name}.required_all_files_covered"
    )
    normalized["required_tables_covered"] = _text_list_or_empty(
        normalized.get("required_tables_covered"), f"{field_name}.required_tables_covered"
    )
    normalized["required_join_keys"] = _text_list_or_empty(normalized.get("required_join_keys"), f"{field_name}.required_join_keys")
    normalized["required_field_level_quality"] = _bool(
        normalized.get("required_field_level_quality"), f"{field_name}.required_field_level_quality"
    )
    normalized["required_duplicate_check"] = _bool(
        normalized.get("required_duplicate_check"), f"{field_name}.required_duplicate_check"
    )
    normalized["required_outlier_check"] = _bool(normalized.get("required_outlier_check"), f"{field_name}.required_outlier_check")
    normalized["requires_direct_answer_first"] = _bool(
        normalized.get("requires_direct_answer_first"), f"{field_name}.requires_direct_answer_first"
    )
    normalized["requires_artifact_summary"] = _bool(
        normalized.get("requires_artifact_summary"), f"{field_name}.requires_artifact_summary"
    )
    normalized["violation_codes_expected_absent"] = _text_list_or_empty(
        normalized.get("violation_codes_expected_absent"), f"{field_name}.violation_codes_expected_absent"
    )
    return normalized


def expected_contract_runtime_hints(value: Any) -> dict[str, Any]:
    """Map structured expected_contract fields to current runtime contract terms.

    This adapter intentionally does not participate in LLM judging. It gives
    deterministic eval/report code a single place to translate manifest schema
    fields into TaskExecutionContract-style names when that wiring is needed.
    """

    if not isinstance(value, Mapping):
        return {}
    contract = normalize_expected_contract(value)
    if not isinstance(contract, Mapping):
        return {}
    required_sort = contract.get("required_sort") if isinstance(contract.get("required_sort"), Mapping) else {}
    context_reference = contract.get("required_context_reference")
    context_values = context_reference if isinstance(context_reference, list) else [context_reference]
    metric = str(required_sort.get("metric") or _first_item(contract.get("required_metrics")) or "")
    dimension = str(_first_item(contract.get("required_dimensions")) or "")
    gap_mode = ""
    if contract.get("required_gap_type") == "pairwise":
        gap_mode = "rank_pair"
    elif contract.get("required_gap_type") == "adjacent":
        gap_mode = "adjacent_and_to_leader"
    output_columns = [
        *[str(item) for item in contract.get("required_dimensions") or []],
        *[str(item) for item in contract.get("required_metrics") or []],
    ]
    return {
        "task_family": contract.get("contract_family") or "unknown",
        "required_n": contract.get("required_row_count"),
        "minimum_required_objects": contract.get("min_row_count"),
        "metric": metric,
        "dimension": dimension,
        "sort_order": required_sort.get("order") or "",
        "gap_mode": gap_mode,
        "requires_previous_artifact": any(
            item in {"previous_top_objects", "previous_result_set", "previous_quality_findings"} for item in context_values
        ),
        "required_output_columns": list(dict.fromkeys(column for column in output_columns if column)),
        "verification_rules": {
            "expected_contract_schema_version": contract.get("schema_version"),
            "allow_insufficient_data_explanation": contract.get("allow_insufficient_data_explanation"),
            "required_all_files_covered": contract.get("required_all_files_covered"),
            "required_tables_covered": list(contract.get("required_tables_covered") or []),
            "required_join_keys": list(contract.get("required_join_keys") or []),
            "required_field_level_quality": contract.get("required_field_level_quality"),
            "required_duplicate_check": contract.get("required_duplicate_check"),
            "required_outlier_check": contract.get("required_outlier_check"),
            "requires_direct_answer_first": contract.get("requires_direct_answer_first"),
            "requires_artifact_summary": contract.get("requires_artifact_summary"),
            "violation_codes_expected_absent": list(contract.get("violation_codes_expected_absent") or []),
        },
    }


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
        expected_contract=normalize_expected_contract(value.get("expected_contract"), field_name=f"{case_id}.expected_contract"),
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
        expected_contract=normalize_expected_contract(
            value.get("expected_contract"), field_name=f"{conversation_id}.{turn_id}.expected_contract"
        ),
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


def _text_list_or_empty(value: Any, field_name: str) -> list[str]:
    if value in (None, ""):
        return []
    return _text_list(value, field_name)


def _required_contract_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must be a non-empty string")
    return text


def _optional_text(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value.strip()


def _optional_text_or_text_list(value: Any, field_name: str) -> str | list[str]:
    if value in (None, ""):
        return ""
    if isinstance(value, list):
        return _text_list(value, field_name)
    if isinstance(value, str):
        return value.strip()
    raise ValueError(f"{field_name} must be a string or array")


def _normalize_context_reference(value: Any, field_name: str) -> str | list[str]:
    references = _optional_text_or_text_list(value, field_name)
    if isinstance(references, list):
        normalized = [_normalize_one_context_reference(item, field_name) for item in references]
        return normalized
    return _normalize_one_context_reference(references, field_name)


def _normalize_one_context_reference(value: str, field_name: str) -> str:
    reference = CONTEXT_REFERENCE_ALIASES.get(value, value)
    if reference not in SUPPORTED_CONTEXT_REFERENCES:
        supported = ", ".join(sorted(item for item in SUPPORTED_CONTEXT_REFERENCES if item))
        raise ValueError(f"{field_name} is unsupported: {reference!r}; supported: {supported}")
    return reference


def _bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _optional_positive_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _optional_non_negative_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _normalize_required_sort(value: Any, field_name: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    result = dict(value)
    metric = _optional_text(result.get("metric"), f"{field_name}.metric")
    if metric:
        result["metric"] = metric
    if "by" in result:
        by = result.get("by")
        if isinstance(by, str):
            result["by"] = [by.strip()] if by.strip() else []
        else:
            result["by"] = _text_list_or_empty(by, f"{field_name}.by")
    elif metric:
        result["by"] = [metric]
    if not metric and result.get("by"):
        result["metric"] = result["by"][0]
    order = result.get("order")
    if order is not None:
        order_text = str(order).strip().lower()
        if order_text not in {"asc", "desc"}:
            raise ValueError(f"{field_name}.order must be 'asc' or 'desc'")
        result["order"] = order_text
    return result


def _first_item(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return None


def _reject_leaked_prompt_tokens(case_id: str, text: str) -> None:
    lowered = text.lower()
    for token in FORBIDDEN_VARIANT_TOKENS:
        if token in lowered:
            raise ValueError(f"{case_id}: question text contains forbidden token {token!r}")
