"""Final answer canonicalization and output-contract validation."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


STRUCTURED_ANSWER_TYPES = {"scheme_fee", "aci", "aci_fee", "card_scheme", "grouped_amounts"}


@dataclass
class OutputContractValidation:
    """Trace-safe validation result for the final answer string."""

    passed: bool
    answer_type: str
    issues: list[str] = field(default_factory=list)
    risk_flags: dict[str, bool] = field(default_factory=dict)
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CanonicalAnswer:
    """Canonical answer string plus validation details."""

    answer: str
    validation: OutputContractValidation
    normalized_from: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["validation"] = self.validation.to_dict()
        return payload


def canonicalize_final_answer(value: Any, output_format: dict[str, Any] | None = None) -> CanonicalAnswer:
    """Return a benchmark-safe final answer string and validation payload."""

    output_format = dict(output_format or {})
    answer_type = str(output_format.get("answer_type") or "text")
    guidelines = str(output_format.get("guidelines") or "")
    scalar = _coerce_value_for_answer(value, answer_type, guidelines, output_format)
    answer = _format_scalar(scalar, answer_type, output_format, guidelines)
    validation = validate_final_answer(answer, output_format)
    return CanonicalAnswer(answer=answer, validation=validation, normalized_from=type(value).__name__)


def validate_final_answer(answer: Any, output_format: dict[str, Any] | None = None) -> OutputContractValidation:
    """Validate that the final answer is a compact answer string, not debug/state."""

    output_format = dict(output_format or {})
    answer_type = str(output_format.get("answer_type") or "text")
    guidelines = str(output_format.get("guidelines") or "")
    text = "" if answer is None else str(answer).strip()
    issues: list[str] = []
    flags = {
        "empty_answer": False,
        "object_or_list_leak": False,
        "debug_or_trace_leak": False,
        "sql_or_markdown_leak": False,
        "number_format_mismatch": False,
        "percentage_format_mismatch": False,
        "comma_list_format_mismatch": False,
    }

    allow_empty = _guidelines_request_empty_string_for_empty_list(guidelines) and answer_type in {"list", "table"}
    if not text and not allow_empty:
        flags["empty_answer"] = True
        issues.append("empty_answer")
    if _looks_like_object_or_list_leak(text):
        flags["object_or_list_leak"] = True
        issues.append("object_or_list_leak")
    if _looks_like_debug_or_trace_leak(text):
        flags["debug_or_trace_leak"] = True
        issues.append("debug_or_trace_leak")
    if _looks_like_sql_or_markdown_leak(text):
        flags["sql_or_markdown_leak"] = True
        issues.append("sql_or_markdown_leak")
    if text != "Not Applicable" and _expects_plain_number(answer_type, guidelines) and not _is_plain_number(text):
        flags["number_format_mismatch"] = True
        issues.append("number_format_mismatch")
    if text != "Not Applicable" and answer_type == "percentage" and not _guidelines_request_plain_number(guidelines) and not text.endswith("%"):
        flags["percentage_format_mismatch"] = True
        issues.append("percentage_format_mismatch")
    if _guidelines_request_comma_separated(guidelines) and ("[" in text or "]" in text):
        flags["comma_list_format_mismatch"] = True
        issues.append("comma_list_format_mismatch")

    return OutputContractValidation(
        passed=not issues,
        answer_type=answer_type,
        issues=issues,
        risk_flags=flags,
        retryable=bool(issues),
    )


def _coerce_value_for_answer(value: Any, answer_type: str, guidelines: str, output_format: dict[str, Any] | None = None) -> Any:
    output_format = dict(output_format or {})
    if value is None or _is_not_applicable_text(value):
        return "Not Applicable"
    if answer_type in STRUCTURED_ANSWER_TYPES:
        return value
    answer_target = str(output_format.get("answer_target") or "")
    if answer_target:
        targeted = _coerce_answer_target(value, answer_target, output_format)
        if targeted is not None:
            return targeted
    if isinstance(value, dict):
        return _coerce_mapping(value, answer_type, guidelines, output_format)
    if isinstance(value, (list, tuple)):
        return _coerce_sequence(value, answer_type, guidelines, output_format)
    return value


def _coerce_mapping(value: dict[str, Any], answer_type: str, guidelines: str, output_format: dict[str, Any] | None = None) -> Any:
    for key in ("answer", "selected", "selected_option", "value"):
        if key in value and value[key] is not None:
            return _coerce_value_for_answer(value[key], answer_type, guidelines, output_format)
    if answer_type in {"number", "percentage"} or _guidelines_request_plain_number(guidelines):
        numeric = _preferred_numeric(value)
        if numeric is not None:
            return numeric
    preferred_text_keys = (
        "merchant_name",
        "merchant",
        "country_code",
        "issuing_country",
        "card_scheme",
        "aci",
        "name",
        "label",
    )
    for key in preferred_text_keys:
        if key in value and value[key] not in {None, ""}:
            return value[key]
    scalar_values = [item for item in value.values() if _is_scalar(item)]
    if len(scalar_values) == 1:
        return scalar_values[0]
    if scalar_values:
        return ", ".join(str(item) for item in scalar_values)
    return "没有匹配记录" if answer_type in {"table", "list"} else "没有可用结果"


def _coerce_sequence(value: list[Any] | tuple[Any, ...], answer_type: str, guidelines: str, output_format: dict[str, Any] | None = None) -> Any:
    if not value:
        if _guidelines_request_empty_string_for_empty_list(guidelines) and answer_type in {"table", "list"}:
            return ""
        return "没有匹配记录" if answer_type in {"table", "list"} else "Not Applicable"
    if answer_type in {"number", "percentage"} or _guidelines_request_plain_number(guidelines):
        first_numeric = _first_numeric_from_sequence(value)
        if first_numeric is not None:
            return first_numeric
    coerced = [_coerce_value_for_answer(item, answer_type, guidelines, output_format) for item in value]
    if answer_type not in {"list", "table"} and len(coerced) == 1:
        return coerced[0]
    return [item for item in coerced if item not in {None, ""}]


def _is_not_applicable_text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip().lower()
    return text in {"not applicable", "n/a", "na"} or "not applicable" in text


def _coerce_answer_target(value: Any, answer_target: str, output_format: dict[str, Any]) -> Any:
    if answer_target == "metric_only":
        return _extract_metric_only(value, output_format)
    if answer_target == "entity_only":
        return _extract_entity_only(value, output_format)
    if answer_target == "entity_list_only":
        return _extract_entity_list_only(value, output_format)
    if answer_target == "segment_vector":
        return _extract_segment_vector(value, output_format)
    return None


def _extract_metric_only(value: Any, output_format: dict[str, Any]) -> Any:
    metric_field = str(output_format.get("metric_field") or "")
    metric_keys = tuple(
        key
        for key in (
            "selected_metric",
            "metric_value",
            metric_field,
            "value",
            "fraud_volume_rate",
            "fraud_transaction_rate",
            "fraud_rate_std",
            "rate",
            "percentage",
            "eur_amount",
            "amount",
            "fee",
            "count",
            "total",
        )
        if key
    )
    if isinstance(value, dict):
        for key in metric_keys:
            if key in value and _is_numeric(value[key]):
                return value[key]
        table = value.get("candidate_table")
        selected = value.get("selected")
        group_by = str(output_format.get("entity_field") or value.get("group_by") or "")
        if isinstance(table, list):
            for row in table:
                if not isinstance(row, dict):
                    continue
                if selected is not None and group_by and str(row.get(group_by)) != str(selected):
                    continue
                for key in metric_keys:
                    if key in row and _is_numeric(row[key]):
                        return row[key]
    if isinstance(value, (list, tuple)):
        for item in value:
            metric = _extract_metric_only(item, output_format)
            if metric is not None:
                return metric
    return None


def _extract_entity_only(value: Any, output_format: dict[str, Any]) -> Any:
    entity_field = str(output_format.get("entity_field") or "")
    if isinstance(value, dict):
        for key in (entity_field, "selected", "entity", "answer", "merchant", "merchant_name", "country_code", "issuing_country", "ip_country", "card_scheme"):
            if key and key in value and value[key] not in {None, ""}:
                return value[key]
    if isinstance(value, (list, tuple)):
        for item in value:
            entity = _extract_entity_only(item, output_format)
            if entity is not None:
                return entity
    if _is_scalar(value):
        return value
    return None


def _extract_entity_list_only(value: Any, output_format: dict[str, Any]) -> Any:
    if isinstance(value, dict) and isinstance(value.get("candidate_table"), list):
        value = value["candidate_table"]
    if isinstance(value, (list, tuple)):
        entities = [_extract_entity_only(item, output_format) for item in value]
        return [entity for entity in entities if entity not in {None, ""}]
    entity = _extract_entity_only(value, output_format)
    return [entity] if entity not in {None, ""} else None


def _extract_segment_vector(value: Any, output_format: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        values = value.get("values") or value.get("segment_values")
        if isinstance(values, (list, tuple)):
            return list(values)
        dimensions = output_format.get("dimensions") or value.get("dimensions") or []
        if isinstance(dimensions, (list, tuple)):
            extracted = [value.get(str(dimension)) for dimension in dimensions if value.get(str(dimension)) not in {None, ""}]
            if extracted:
                return extracted
    if isinstance(value, (list, tuple)):
        return list(value)
    return None


def _format_scalar(value: Any, answer_type: str, output_format: dict[str, Any], guidelines: str) -> str:
    decimals = output_format.get("decimals")
    if value is None or _is_not_applicable_text(value):
        return "Not Applicable"
    if answer_type == "number":
        try:
            return _format_number(float(value), decimals)
        except (TypeError, ValueError):
            return str(value)
    if answer_type == "percentage":
        try:
            number = _format_number(float(value), 2 if decimals is None else decimals)
        except (TypeError, ValueError):
            return str(value)
        return number if _guidelines_request_plain_number(guidelines) else f"{number}%"
    if answer_type == "yes_no":
        return _format_yes_no(value)
    if answer_type == "list":
        return _format_list(value, output_format)
    if answer_type == "scheme_fee" and isinstance(value, dict):
        return f"{value['card_scheme']}:{_format_number(float(value['fee']), decimals)}"
    if answer_type == "aci" and isinstance(value, dict):
        return str(value.get("aci") or value.get("answer") or "没有匹配记录")
    if answer_type == "aci_fee" and isinstance(value, dict):
        return f"{value['aci']}:{_format_number(float(value['fee']), decimals)}"
    if answer_type == "card_scheme" and isinstance(value, dict):
        return str(value["card_scheme"])
    if answer_type == "grouped_amounts":
        return _format_grouped_amounts(value, decimals)
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    return str(value)


def _format_list(value: Any, output_format: dict[str, Any]) -> str:
    items = _coerce_list_items(value)
    if items is None:
        return str(value)
    if not items and _guidelines_request_empty_string_for_empty_list(str(output_format.get("guidelines") or "")):
        return ""
    if output_format.get("dedupe_values"):
        deduped: list[Any] = []
        seen: set[str] = set()
        for item in items:
            key = _list_sort_text(item).lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        items = deduped
    sort_values = bool(output_format.get("sort_values")) or _all_integer_like(items)
    if sort_values:
        items = sorted(items, key=_list_sort_key)
    return ", ".join(_format_list_item(item) for item in items)


def _coerce_list_items(value: Any) -> list[Any] | None:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        stripped = re.sub(r"^\[|\]$", "", stripped)
        if "," in stripped or ";" in stripped:
            return [item.strip().strip("'\"") for item in re.split(r"[,;]", stripped) if item.strip()]
        return [stripped]
    if isinstance(value, (list, tuple)):
        return list(value)
    return None


def _format_list_item(item: Any) -> str:
    if _is_integer_like(item):
        return str(int(float(str(item).strip())))
    if isinstance(item, float) and math.isclose(item, round(item)):
        return str(int(round(item)))
    return str(item)


def _all_integer_like(items: list[Any]) -> bool:
    return bool(items) and all(_is_integer_like(item) for item in items)


def _is_integer_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value) and math.isclose(value, round(value))
    text = str(value).strip()
    return bool(re.fullmatch(r"-?\d+(?:\.0+)?", text))


def _list_sort_key(item: Any) -> tuple[int, float | str]:
    if _is_integer_like(item):
        return (0, float(str(item).strip()))
    return (1, _list_sort_text(item).lower())


def _list_sort_text(item: Any) -> str:
    return _format_list_item(item).strip()


def _preferred_numeric(value: dict[str, Any]) -> float | int | None:
    preferred = ("answer", "value", "amount", "eur_amount", "fee", "count", "total", "rate", "percentage")
    for key in preferred:
        if key in value and _is_numeric(value[key]):
            return value[key]
    numeric_values = [item for item in value.values() if _is_numeric(item)]
    if len(numeric_values) == 1:
        return numeric_values[0]
    return None


def _first_numeric_from_sequence(value: list[Any] | tuple[Any, ...]) -> Any:
    for item in value:
        if _is_numeric(item):
            return item
        if isinstance(item, dict):
            nested = _preferred_numeric(item)
            if nested is not None:
                return nested
    return None


def _format_number(value: float, decimals: int | None = None) -> str:
    if decimals is None:
        if math.isclose(value, round(value)):
            return str(int(round(value)))
        return str(value)
    return _format_decimal(value, decimals)


def _format_decimal(value: float, places: int) -> str:
    quantum = Decimal("1").scaleb(-places)
    return format(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP), "f")


def _format_grouped_amounts(rows: Any, decimals: int | None) -> str:
    if not rows:
        return "没有匹配记录"
    if not isinstance(rows, list) or not isinstance(rows[0], dict):
        return str(rows)
    group_key = next(key for key in rows[0] if key != "eur_amount")
    parts = [f"{row[group_key]}: {_format_number(float(row['eur_amount']), decimals)}" for row in rows]
    return "[" + ", ".join(parts) + "]"


def _looks_like_object_or_list_leak(text: str) -> bool:
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("[{") or stripped.startswith("[["):
        return True
    return bool(re.search(r"[\{\[]['\"][^'\"]+['\"]\s*:", stripped))


def _looks_like_debug_or_trace_leak(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "structured analysis plan:",
            "agent_mode:",
            "trace:",
            "debug:",
            "process_view_v2",
            "process view",
            "tool_call",
            "reasoning_trace",
        )
    )


def _looks_like_sql_or_markdown_leak(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "```",
            "|---",
            "| ---",
            "select ",
            " from ",
            " where ",
            "group by",
            "order by",
        )
    )


def _format_yes_no(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    lowered = str(value).strip().lower()
    if lowered in {"true", "1", "yes", "y"}:
        return "yes"
    if lowered in {"false", "0", "no", "n"}:
        return "no"
    return str(value)


def _expects_plain_number(answer_type: str, guidelines: str) -> bool:
    return answer_type == "number" or _guidelines_request_plain_number(guidelines)


def _guidelines_request_plain_number(guidelines: str) -> bool:
    lowered = guidelines.lower()
    return any(token in lowered for token in ("just a number", "return only a number", "only the number")) or any(
        token in guidelines for token in ("只返回数字", "只返回整数", "只需数字")
    )


def _guidelines_request_comma_separated(guidelines: str) -> bool:
    lowered = guidelines.lower()
    return "comma separated" in lowered or "comma-separated" in lowered or "英文逗号分隔" in guidelines


def _guidelines_request_empty_string_for_empty_list(guidelines: str) -> bool:
    lowered = guidelines.lower()
    return "if the answer is an empty list, reply with an empty string" in lowered or "空列表返回空字符串" in guidelines


def _is_plain_number(text: str) -> bool:
    return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", text.strip()))


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None
