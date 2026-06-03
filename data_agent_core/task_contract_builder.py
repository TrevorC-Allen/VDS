"""Helpers for injecting referent contracts into LogicForm objects."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping


REFERENT_CONTRACT_MARKER = "REFERENT_CONTRACT_JSON="


def referent_contract_guideline(contract: dict[str, Any]) -> str:
    """Serialize a referent contract into a guidelines-safe marker."""

    payload = json.dumps(contract, ensure_ascii=False, sort_keys=True)
    return f"{REFERENT_CONTRACT_MARKER}{payload}"


def apply_referent_contract_from_guidelines(logic_form: Any, guidelines: str) -> Any:
    """Inject referent filters and contract fields into a LogicForm."""

    contract = extract_referent_contract(guidelines)
    if not contract:
        return logic_form
    return apply_referent_contract(logic_form, contract)


def apply_referent_contract(logic_form: Any, contract: dict[str, Any]) -> Any:
    """Apply a referent contract to LogicForm filters, params, and task contract."""

    dimension = str(contract.get("referent_dimension") or "").strip()
    values = [value for value in contract.get("referent_values") or [] if value not in (None, "")]
    if not dimension or not values:
        return logic_form
    params = dict(getattr(logic_form, "parameters", {}) or {})
    filters = dict(getattr(logic_form, "filters", {}) or {})
    inherited = _mapping(contract.get("inherited_parameters"))
    action_parameters = _mapping(contract.get("action_parameters"))
    auto_expand = bool(contract.get("auto_expand_topn_if_needed") or action_parameters.get("auto_expand_topn_if_needed"))
    for key in ("table", "join_plan", "table_selection_reason", "available_columns", "source_tables"):
        value = inherited.get(key)
        if value not in (None, "", [], {}):
            params[key] = value
    if auto_expand:
        filters.pop(dimension, None)
        preferred_top_n = _positive_int(contract.get("preferred_top_n") or action_parameters.get("preferred_top_n")) or 3
        for key in ("metric", "dimension", "aggregation", "sort_order"):
            value = action_parameters.get(key) or inherited.get(key)
            if value not in (None, "", [], {}):
                params[key] = value
        params["dimension"] = str(params.get("dimension") or dimension)
        params["limit"] = max(preferred_top_n, _positive_int(action_parameters.get("minimum_required_objects")) or 2)
        params["top_n"] = params["limit"]
        params["requires_gap_comparison"] = True
        params["minimum_required_objects"] = _positive_int(action_parameters.get("minimum_required_objects")) or 2
        params["preferred_top_n"] = preferred_top_n
        params["auto_expand_topn_if_needed"] = True
        params["expansion_source"] = str(action_parameters.get("expansion_source") or contract.get("expansion_source") or "previous_metric_dimension_context")
        setattr(logic_form, "operation", "ranking")
        setattr(logic_form, "task_type", "ranking")
        setattr(logic_form, "metric", str(params.get("metric") or getattr(logic_form, "metric", "") or ""))
        setattr(logic_form, "group_by", str(params.get("dimension") or dimension))
        output_format = dict(getattr(logic_form, "output_format", {}) or {})
        output_format.setdefault("answer_type", "table")
        setattr(logic_form, "output_format", output_format)
    else:
        filters[dimension] = values
    setattr(logic_form, "filters", filters)
    candidate_set = dict(getattr(logic_form, "candidate_set", {}) or {})
    candidate_set.update(
        {
            "source": "previous_result_auto_expand_topn" if auto_expand else "previous_result_referent",
            "dimension": dimension,
            "values": values,
            "filters": {} if auto_expand else {dimension: values},
            "referent_artifact_id": str(contract.get("referent_artifact_id") or ""),
        }
    )
    setattr(logic_form, "candidate_set", candidate_set)
    params.update(
        {
            **{key: value for key, value in action_parameters.items() if key in {"metric", "dimension", "metrics", "aggregation", "time_column", "time_dimension"} and value not in (None, "", [], {})},
            "requires_previous_artifact": True,
            "referent_artifact_id": str(contract.get("referent_artifact_id") or ""),
            "referent_dimension": dimension,
            "referent_values": values,
            "referent_policy": str(contract.get("referent_policy") or action_parameters.get("referent_policy") or "must_filter_to_previous_result_objects"),
            "referent_source": str(contract.get("referent_source") or "result_artifact"),
        }
    )
    current_dimension = str(params.get("dimension") or getattr(logic_form, "group_by", None) or "")
    if current_dimension and current_dimension != dimension:
        params.setdefault("series_dimension", dimension)
    setattr(logic_form, "parameters", params)
    source_tables = params.get("source_tables")
    if isinstance(source_tables, list):
        setattr(logic_form, "source_tables", [str(item) for item in source_tables if str(item)])
    if isinstance(params.get("join_plan"), dict):
        setattr(logic_form, "join_plan", dict(params.get("join_plan") or {}))
    if params.get("table_selection_reason"):
        setattr(logic_form, "table_selection_reason", str(params.get("table_selection_reason") or ""))
    task_contract = dict(getattr(logic_form, "task_contract", {}) or {})
    task_contract.update(
        {
            "requires_previous_artifact": True,
            "referent_artifact_id": str(contract.get("referent_artifact_id") or ""),
            "referent_dimension": dimension,
            "referent_values": values,
            "referent_policy": str(contract.get("referent_policy") or action_parameters.get("referent_policy") or "must_filter_to_previous_result_objects"),
            "referent_source": str(contract.get("referent_source") or "result_artifact"),
            **(
                {
                    "requires_gap_comparison": True,
                    "minimum_required_objects": params.get("minimum_required_objects"),
                    "preferred_top_n": params.get("preferred_top_n"),
                    "auto_expand_topn_if_needed": True,
                    "expansion_source": params.get("expansion_source"),
                }
                if auto_expand
                else {}
            ),
        }
    )
    setattr(logic_form, "task_contract", task_contract)
    return logic_form


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def extract_referent_contract(guidelines: str) -> dict[str, Any]:
    """Extract the last referent contract marker from guidelines."""

    matches = re.findall(rf"{re.escape(REFERENT_CONTRACT_MARKER)}(\{{.*?\}})(?:\s|$)", str(guidelines or ""))
    for raw in reversed(matches):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def build_topn_gap_trend_task_contract(question: str, logic_form: Any) -> dict[str, Any]:
    """Build a task-level TopN/Gap/Trend contract payload from question and LogicForm."""

    question_text = str(question or "")
    params = dict(getattr(logic_form, "parameters", {}) or {})
    metric = str(getattr(logic_form, "metric", None) or params.get("metric") or "")
    dimension = str(params.get("dimension") or params.get("group_by") or getattr(logic_form, "group_by", None) or "")
    if _contract_asks_gap(question_text):
        return {
            "task_family": "gap",
            "gap_mode": "rank_pair" if _contract_asks_rank_pair(question_text) else "adjacent_and_to_leader",
            "metric": metric,
            "dimension": dimension,
            "must_compute_absolute_gap": True,
            "must_compute_percent_gap": _contract_asks_percent_gap(question_text),
            "required_answer_elements": ["direct_gap_summary"],
            "verification_rules": ["gap_absolute_required", "gap_to_leader_required", "direct_gap_summary"],
        }
    if _contract_asks_trend(question_text):
        time_dimension = str(params.get("time_column") or params.get("time_dimension") or dimension)
        return {
            "task_family": "trend",
            "time_dimension": time_dimension,
            "metric": metric,
            "required_output_columns": [column for column in (time_dimension, metric) if column],
            "verification_rules": ["trend_time_series_required", "trend_description_matches_values"],
        }
    if _contract_asks_topn(question_text, logic_form):
        required_n = _contract_required_n(question_text) or _positive_int(params.get("limit")) or 1
        return {
            "task_family": "topn",
            "required_n": required_n,
            "metric": metric,
            "dimension": dimension,
            "sort_order": str(params.get("sort_order") or ("asc" if _contract_asks_lowest(question_text) else "desc")),
            "required_output_columns": [column for column in (dimension, metric) if column],
            "verification_rules": [
                "topn_required_rows",
                "topn_sort_order",
                "topn_required_columns",
                "topn_insufficient_explanation",
            ],
        }
    return {}


def _contract_asks_topn(question: str, logic_form: Any) -> bool:
    lowered = question.lower()
    compact = re.sub(r"\s+", "", question)
    return str(getattr(logic_form, "task_type", "") or "") == "ranking" or bool(
        re.search(r"\btop\s*\d+", lowered)
        or re.search(r"(?:排名)?前\s*(?:\d+|[一二两三四五六七八九十]+)", compact)
        or any(token in compact for token in ("最高", "最低", "最大", "最小", "最多", "最少"))
    )


def _contract_asks_gap(question: str) -> bool:
    lowered = question.lower()
    compact = re.sub(r"\s+", "", question)
    return any(token in compact for token in ("差多少", "差距", "相差", "差额")) or any(token in lowered for token in ("gap", "difference"))


def _contract_asks_trend(question: str) -> bool:
    lowered = question.lower()
    compact = re.sub(r"\s+", "", question)
    return any(token in compact for token in ("趋势", "按月份", "随时间", "月度变化", "峰值", "低点", "波动")) or any(
        token in lowered for token in ("trend", "monthly", "over time", "peak", "fluctuat")
    )


def _contract_asks_rank_pair(question: str) -> bool:
    compact = re.sub(r"\s+", "", question)
    return any(token in compact for token in ("第一名和第二名", "第1名和第2名", "第一和第二"))


def _contract_asks_percent_gap(question: str) -> bool:
    lowered = question.lower()
    return any(token in question for token in ("百分比", "比例")) or any(token in lowered for token in ("percent", "%"))


def _contract_asks_lowest(question: str) -> bool:
    compact = re.sub(r"\s+", "", question)
    lowered = question.lower()
    return any(token in compact for token in ("最低", "最小", "最少", "从低到高")) or any(token in lowered for token in ("lowest", "smallest", "bottom", "ascending"))


def _contract_required_n(question: str) -> int | None:
    match = re.search(r"(?:top|前|排名前|最高的?|最低的?|最大的?|最小的?|最多的?|最少的?)\s*(\d+|[一二两三四五六七八九十]+)", question, re.I)
    if not match:
        return None
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    return _contract_small_chinese_number(raw)


def _contract_small_chinese_number(value: str) -> int | None:
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if value in digits:
        return digits[value]
    if value.startswith("十") and len(value) == 2:
        return 10 + digits.get(value[1], 0)
    if value.endswith("十") and len(value) == 2:
        return digits.get(value[0], 0) * 10
    if "十" in value and len(value) == 3:
        return digits.get(value[0], 0) * 10 + digits.get(value[2], 0)
    return None
