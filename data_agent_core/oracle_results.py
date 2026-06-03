"""Deterministic oracle result contracts for eval instrumentation."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping

from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.task_execution_contracts import TaskExecutionContract


@dataclass
class OracleResult:
    """Deterministic expected-vs-actual result for contract-aware eval."""

    oracle_available: bool
    expected_result: dict[str, Any] | list[Any] | None = None
    actual_result: dict[str, Any] | list[Any] | None = None
    passed: bool | None = None
    diff_summary: str | None = None
    issue_codes: list[str] = field(default_factory=list)


def build_oracle_result(
    contract: TaskExecutionContract | None,
    execution_result: ExecutionResult,
) -> OracleResult:
    """Build an oracle result when deterministic expected_result is available."""

    actual = _actual_payload(execution_result)
    if contract is None:
        return OracleResult(
            oracle_available=False,
            actual_result=actual,
            passed=None,
            diff_summary="No task contract is available for deterministic oracle evaluation.",
            issue_codes=["oracle_contract_missing"],
        )
    expected = contract.verification_rules.get("expected_result")
    if expected is None:
        return OracleResult(
            oracle_available=False,
            actual_result=actual,
            passed=None,
            diff_summary="No deterministic expected_result is defined for this contract.",
            issue_codes=["oracle_expected_result_missing"],
        )
    if _is_ranking_followup_gap_expected(expected):
        answer = ""
        if isinstance(execution_result.value, Mapping):
            answer = str(execution_result.value.get("answer") or "")
        return oracle_topn_followup_gap(expected, actual, answer=answer)
    passed = expected == actual
    return OracleResult(
        oracle_available=True,
        expected_result=expected,
        actual_result=actual,
        passed=passed,
        diff_summary=None if passed else "Deterministic actual_result differs from expected_result.",
        issue_codes=[] if passed else ["oracle_result_mismatch"],
    )


def oracle_trend_followup_series(time_series: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Build deterministic trend oracle payload for follow-up trend checks."""

    points = _coerce_trend_series_points(time_series)
    if not points:
        return {
            "series": [],
            "trend_shape": "insufficient_periods_for_trend",
            "trend_description": "无法判断趋势",
            "peak": None,
            "low": None,
            "max_change": None,
            "forbidden_descriptions": ["整体上升", "单调上升", "持续上升"],
        }
    shape = _trend_shape_from_numeric_points(points)
    has_enough_periods = len(points) > 1
    return {
        "series": [{"month": item["month"], "value": item["value"]} for item in points],
        "trend_shape": shape,
        "trend_description": _trend_description_from_shape(shape),
        "peak": _peak_or_low_point(points, compare=max) if has_enough_periods else None,
        "low": _peak_or_low_point(points, compare=min) if has_enough_periods else None,
        "max_change": _max_delta_change(points) if has_enough_periods else None,
        "forbidden_descriptions": ["整体上升", "单调上升", "持续上升"],
    }


def _actual_payload(execution_result: ExecutionResult) -> dict[str, Any] | list[Any] | None:
    if execution_result.rows:
        return execution_result.rows
    if isinstance(execution_result.value, (dict, list)):
        return execution_result.value
    if execution_result.value is None:
        return None
    return {"value": execution_result.value}


def _is_ranking_followup_gap_expected(expected: Any) -> bool:
    return isinstance(expected, Mapping) and all(key in expected for key in ("top_objects", "adjacent_gaps", "gap_to_leader"))


def oracle_topn_followup_gap(expected: Any, actual: Any, *, answer: str = "") -> OracleResult:
    expected_payload = _coerce_gap_payload(expected)
    actual_payload = _coerce_gap_payload(actual)
    if expected_payload is None or actual_payload is None:
        return OracleResult(
            oracle_available=True,
            expected_result=expected if isinstance(expected, (dict, list)) else None,
            actual_result=actual if isinstance(actual, (dict, list)) else None,
            passed=False,
            diff_summary="TopN follow-up gap expected/actual payload is malformed.",
            issue_codes=["gap_oracle_payload_invalid"],
        )

    issue_codes: list[str] = []
    expected_top = expected_payload["top_objects"]
    actual_top = actual_payload["top_objects"]

    if len(expected_top) < 2 or len(actual_top) < 2:
        issue_codes.append("insufficient_objects_for_gap")

    if any(_oracle_float(item.get("metric_value")) is None for item in actual_top):
        issue_codes.append("gap_metric_value_missing")

    matched = _compare_top_objects(expected_top, actual_top) and _compare_gap_values(
        expected_payload["adjacent_gaps"],
        actual_payload["adjacent_gaps"],
    ) and _compare_gap_values(expected_payload["gap_to_leader"], actual_payload["gap_to_leader"])

    if not matched or issue_codes:
        return OracleResult(
            oracle_available=True,
            expected_result=expected_payload,
            actual_result=actual_payload,
            passed=False,
            diff_summary="Deterministic gap result differs from expected gap payload.",
            issue_codes=sorted(set(issue_codes)) or ["oracle_result_mismatch"],
        )

    if answer and not _answer_mentions_gap(answer):
        return OracleResult(
            oracle_available=True,
            expected_result=expected_payload,
            actual_result=actual_payload,
            passed=True,
            diff_summary="answer text misses explicit gap summary (warning).",
            issue_codes=["topn_followup_gap_answer_summary_missing_warning"],
        )

    return OracleResult(
        oracle_available=True,
        expected_result=expected_payload,
        actual_result=actual_payload,
        passed=True,
        diff_summary=None,
        issue_codes=[],
    )


def _coerce_gap_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    top_objects = []
    for item in value.get("top_objects", []):
        if not isinstance(item, Mapping):
            continue
        top_objects.append(
            {
                "rank": item.get("rank"),
                "value": item.get("value"),
                "metric_value": item.get("metric_value"),
            }
        )
    return {
        "top_objects": top_objects,
        "adjacent_gaps": list(value.get("adjacent_gaps") or []),
        "gap_to_leader": list(value.get("gap_to_leader") or []),
    }


def _compare_top_objects(expected_top: list[dict[str, Any]], actual_top: list[dict[str, Any]]) -> bool:
    if len(expected_top) != len(actual_top):
        return False
    for index, (expected_row, actual_row) in enumerate(zip(expected_top, actual_top)):
        if str(expected_row.get("value")) != str(actual_row.get("value")):
            return False
        expected_rank = _parse_rank(expected_row.get("rank"), index + 1)
        actual_rank = _parse_rank(actual_row.get("rank"), index + 1)
        if expected_rank != actual_rank:
            return False
        if not _compare_gap_values([expected_row.get("metric_value")], [actual_row.get("metric_value")]):
            return False
    return True


def _compare_gap_values(expected: list[Any], actual: list[Any]) -> bool:
    if len(expected) != len(actual):
        return False
    for expected_value, actual_value in zip(expected, actual):
        expected_float = _oracle_float(expected_value)
        actual_float = _oracle_float(actual_value)
        if expected_float is None or actual_float is None:
            if expected_float is not None or actual_float is not None:
                return False
            if str(expected_value) != str(actual_value):
                return False
            continue
        if not math.isclose(expected_float, actual_float, rel_tol=1e-6, abs_tol=0.01):
            return False
    return True


def _parse_rank(value: Any, fallback: int) -> int:
    try:
        value_int = int(value)
        return value_int
    except (TypeError, ValueError):
        return fallback


def _oracle_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _round_oracle_value(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 4)


def _coerce_trend_series_points(time_series: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for item in time_series:
        if not isinstance(item, Mapping):
            continue
        month = str(item.get("month") or item.get("time") or item.get("period") or item.get("date") or "")
        if not month:
            continue
        value = _oracle_float(item.get("value"))
        if value is None and "value" not in item:
            numeric_candidates = [v for key, v in item.items() if key not in {"month", "time", "period", "date"} and _oracle_float(v) is not None]
            if numeric_candidates:
                value = _oracle_float(numeric_candidates[0])
        if value is None:
            continue
        points.append({"month": month, "value": value})
    return points


def _trend_shape_from_numeric_points(points: list[Mapping[str, Any]]) -> str:
    if len(points) <= 1:
        return "insufficient_periods_for_trend"
    values = [item.get("value") for item in points]
    deltas = [next_value - current for current, next_value in zip(values[:-1], values[1:])]
    if not deltas:
        return "insufficient_periods_for_trend"
    if all(delta >= 0 for delta in deltas) and any(delta > 0 for delta in deltas):
        return "increasing"
    if all(delta <= 0 for delta in deltas) and any(delta < 0 for delta in deltas):
        return "decreasing"
    if len(deltas) >= 2 and deltas[0] > 0 and any(delta < 0 for delta in deltas[1:]):
        return "up_then_down"
    if len(deltas) >= 2 and deltas[0] < 0 and any(delta > 0 for delta in deltas[1:]):
        return "down_then_up"
    return "fluctuation"


def _trend_description_from_shape(shape: str) -> str:
    if shape == "increasing":
        return "上升"
    if shape == "decreasing":
        return "下降"
    if shape == "up_then_down":
        return "先升后降"
    if shape == "down_then_up":
        return "先降后升"
    if shape == "fluctuation":
        return "波动"
    if shape == "insufficient_periods_for_trend":
        return "无法判断趋势"
    return "无法判断趋势"


def _peak_or_low_point(points: list[dict[str, Any]], *, compare) -> dict[str, Any] | None:
    if not points:
        return None
    key_item = max(points, key=lambda item: float(item["value"])) if compare is max else min(points, key=lambda item: float(item["value"]))
    return {"month": key_item["month"], "value": key_item["value"]}


def _max_delta_change(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(points) <= 1:
        return None
    values = [point["value"] for point in points]
    deltas = [next_value - current for current, next_value in zip(values[:-1], values[1:])]
    max_index = max(range(len(deltas)), key=lambda index: abs(float(deltas[index])) if float(deltas[index]) is not None else 0.0)
    return {
        "from": points[max_index]["month"],
        "to": points[max_index + 1]["month"],
        "delta": _round_oracle_value(deltas[max_index]),
    }


def _answer_mentions_gap(answer_text: str) -> bool:
    compact = "".join(str(answer_text or "").split())
    lowered = str(answer_text or "").lower()
    return any(token in compact for token in ("差距", "相差", "差额")) or any(token in lowered for token in ("gap", "difference"))
