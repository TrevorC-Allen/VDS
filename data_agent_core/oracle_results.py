"""Deterministic oracle result contracts for eval instrumentation."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
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
    issue_metadata: dict[str, Any] | None = None


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
        answer = _answer_text_from_execution_result(execution_result)
        expected_result, issue_metadata = _build_missing_expected_result_oracle_payload(
            contract=contract, actual=actual, answer=answer
        )
        if _is_contribution_share_expected(expected_result):
            return oracle_contribution_share(expected_result, actual, tolerance=_share_tolerance(contract))
        if _is_trend_constraint_expected(expected_result):
            actual_summary = _build_trend_constraint_actual_summary(expected_result, actual)
            issue_codes = _trend_constraint_issue_codes(expected_result, actual_summary)
            return OracleResult(
                oracle_available=True,
                expected_result=expected_result,
                actual_result=actual_summary,
                passed=not issue_codes,
                diff_summary=None if not issue_codes else "Trend follow-up actual_result does not satisfy oracle constraints.",
                issue_codes=issue_codes,
                issue_metadata=issue_metadata,
            )
        if _is_gap_insufficient_expected(expected_result):
            return oracle_topn_followup_gap(expected_result, actual, answer=answer)
        if _is_ranking_followup_gap_expected(expected_result):
            return oracle_topn_followup_gap(expected_result, actual, answer=answer)
        return OracleResult(
            oracle_available=False,
            expected_result=expected_result,
            actual_result=actual,
            passed=None,
            diff_summary="No deterministic expected_result is defined for this contract.",
            issue_codes=["oracle_expected_result_missing"],
            issue_metadata=issue_metadata,
        )
    if _is_ranking_followup_gap_expected(expected):
        answer = ""
        if isinstance(execution_result.value, Mapping):
            answer = str(execution_result.value.get("answer") or "")
        return oracle_topn_followup_gap(expected, actual, answer=answer)
    if _is_contribution_share_expected(expected) or _is_contribution_share_contract(contract):
        return oracle_contribution_share(expected, actual, tolerance=_share_tolerance(contract))
    if _is_multi_table_join_ranking_expected(expected):
        return oracle_multi_table_join_ranking(expected, actual)
    passed = expected == actual
    if _looks_like_quality_oracle_expected(expected):
        return oracle_quality_field_counts(expected, actual)
    return OracleResult(
        oracle_available=True,
        expected_result=expected,
        actual_result=actual,
        passed=passed,
        diff_summary=None if passed else "Deterministic actual_result differs from expected_result.",
        issue_codes=[] if passed else ["oracle_result_mismatch"],
    )


def oracle_quality_field_counts(expected: Any, actual: Any) -> OracleResult:
    """Build deterministic oracle result for quality field-level counts."""

    expected_payload = _coerce_quality_oracle_expected_payload(expected)
    if expected_payload is None:
        return OracleResult(
            oracle_available=False,
            actual_result=None,
            passed=False,
            diff_summary="Invalid expected_result payload for quality field-level oracle.",
            issue_codes=["oracle_expected_result_invalid"],
        )

    actual_payload = _coerce_quality_oracle_actual_payload(actual)
    if actual_payload is None:
        return OracleResult(
            oracle_available=True,
            expected_result=expected_payload,
            actual_result=None,
            passed=False,
            diff_summary="Invalid actual_result payload for quality field-level oracle.",
            issue_codes=["quality_field_level_missing"],
        )

    issue_codes: list[str] = []
    expected_fields = expected_payload.get("fields") or []
    actual_fields = actual_payload.get("fields") or []
    if not actual_fields:
        issue_codes.append("quality_field_level_missing")

    def _expected_field_map() -> dict[str, dict[str, Any]]:
        mapping: dict[str, dict[str, Any]] = {}
        for row in expected_fields:
            normalized_name = _normalized_identifier(str(row.get("name") or "").strip())
            if normalized_name:
                mapping[normalized_name] = row
        return mapping

    def _actual_field_map() -> dict[str, dict[str, Any]]:
        mapping: dict[str, dict[str, Any]] = {}
        for row in actual_fields:
            normalized_name = _normalized_identifier(str(row.get("name") or "").strip())
            if normalized_name:
                mapping[normalized_name] = row
        return mapping

    expected_field_map = _expected_field_map()
    actual_field_map = _actual_field_map()
    for field_name in expected_field_map:
        expected_row = expected_field_map[field_name]
        actual_row = actual_field_map.get(field_name)
        if actual_row is None:
            issue_codes.append(f"quality_field_count_missing:{field_name}")
            continue

        for count_key in ("missing_count", "type_issue_count", "outlier_count"):
            expected_value = _quality_int_value(expected_row.get(count_key))
            if expected_value is None:
                continue
            actual_value = _quality_int_value(actual_row.get(count_key))
            if actual_value is None or expected_value != actual_value:
                issue_codes.append(f"quality_field_count_mismatch:{field_name}:{count_key}")

        expected_rate = _quality_rate_value(expected_row.get("missing_rate"))
        if expected_rate is not None:
            actual_rate = _quality_rate_value(actual_row.get("missing_rate"))
            if actual_rate is None or not math.isclose(expected_rate, actual_rate, rel_tol=1e-6, abs_tol=1e-9):
                issue_codes.append(f"quality_field_rate_mismatch:{field_name}:missing_rate")

    expected_duplicate_check = expected_payload.get("duplicate_checks") or {}
    expected_duplicate_count = _quality_int_value(expected_duplicate_check.get("full_row_duplicate_count")) if expected_duplicate_check else None
    actual_duplicate_count = (
        _quality_int_value(actual_payload.get("duplicate_checks", {}).get("full_row_duplicate_count")) if actual_payload.get("duplicate_checks") else None
    )
    if expected_duplicate_count is not None and expected_duplicate_count >= 0:
        if actual_payload.get("duplicate_checks") is None:
            issue_codes.append("quality_duplicate_rule_missing")
        elif actual_duplicate_count is None or expected_duplicate_count != actual_duplicate_count:
            issue_codes.append("quality_duplicate_count_mismatch")
    elif actual_payload.get("duplicate_checks") is None:
        issue_codes.append("quality_duplicate_rule_missing")

    expected_outlier_rules = _coerce_quality_rules(expected_payload.get("outlier_rules"))
    actual_outlier_rules = _coerce_quality_rules(actual_payload.get("outlier_rules"))
    if expected_outlier_rules and not actual_outlier_rules:
        issue_codes.append("quality_outlier_rules_missing")
    elif expected_outlier_rules:
        for rule in expected_outlier_rules:
            if rule not in actual_outlier_rules:
                issue_codes.append("quality_outlier_rules_missing")
                break

    return OracleResult(
        oracle_available=True,
        expected_result=expected_payload,
        actual_result=actual_payload,
        passed=not issue_codes,
        diff_summary=None if not issue_codes else "Quality field-level output differs from expected values.",
        issue_codes=sorted(set(issue_codes)),
    )


def oracle_contribution_share(expected: Any, actual: Any, *, tolerance: float = 0.01) -> OracleResult:
    """Build deterministic oracle result for per-referent contribution/share follow-ups."""

    expected_payload = _coerce_contribution_payload(expected)
    actual_payload = _coerce_contribution_payload(actual, expected=expected_payload)
    if expected_payload is None:
        return OracleResult(
            oracle_available=False,
            actual_result=actual_payload,
            passed=False,
            diff_summary="Invalid expected_result payload for contribution/share oracle.",
            issue_codes=["oracle_expected_result_invalid"],
        )
    if actual_payload is None:
        return OracleResult(
            oracle_available=True,
            expected_result=expected_payload,
            actual_result=actual_payload,
            passed=False,
            diff_summary="Contribution/share actual_result is missing per-referent rows.",
            issue_codes=["contribution_referent_missing"],
        )

    issue_codes: list[str] = []
    expected_items = [item for item in expected_payload.get("items") or [] if isinstance(item, Mapping)]
    actual_items = [item for item in actual_payload.get("items") or [] if isinstance(item, Mapping)]
    actual_by_value = {str(item.get("value")): item for item in actual_items if item.get("value") not in (None, "")}

    for expected_item in expected_items:
        value = str(expected_item.get("value") or "")
        actual_item = actual_by_value.get(value)
        if actual_item is None:
            issue_codes.append("contribution_referent_missing")
            continue
        if expected_item.get("metric_value") is not None and not _numbers_close(expected_item.get("metric_value"), actual_item.get("metric_value")):
            issue_codes.append("contribution_metric_mismatch")
        if expected_item.get("total_metric_value") is not None:
            if actual_item.get("total_metric_value") is None:
                issue_codes.append("contribution_denominator_missing")
            elif not _numbers_close(expected_item.get("total_metric_value"), actual_item.get("total_metric_value")):
                issue_codes.append("contribution_denominator_mismatch")
        if expected_item.get("share") is not None:
            if actual_item.get("share") is None:
                issue_codes.append("contribution_share_missing")
            else:
                expected_share = _oracle_float(expected_item.get("share"))
                actual_share = _oracle_float(actual_item.get("share"))
                if expected_share is None or actual_share is None or not math.isclose(expected_share, actual_share, rel_tol=1e-6, abs_tol=tolerance):
                    issue_codes.append("contribution_share_mismatch")

    expected_values = {str(item.get("value")) for item in expected_items if item.get("value") not in (None, "")}
    actual_values = {str(item.get("value")) for item in actual_items if item.get("value") not in (None, "")}
    if expected_values and not expected_values.issubset(actual_values):
        issue_codes.append("contribution_referent_missing")
    if any(item.get("share") is None for item in actual_items):
        issue_codes.append("contribution_share_missing")
    if any(item.get("total_metric_value") is None for item in actual_items):
        issue_codes.append("contribution_denominator_missing")

    issue_codes = sorted(set(issue_codes))
    return OracleResult(
        oracle_available=True,
        expected_result=expected_payload,
        actual_result=actual_payload,
        passed=not issue_codes,
        diff_summary=None if not issue_codes else "Contribution/share actual_result differs from expected per-referent shares.",
        issue_codes=issue_codes,
    )


def _is_contribution_share_contract(contract: TaskExecutionContract | None) -> bool:
    if contract is None:
        return False
    family = str(contract.task_family or "")
    operation = str(contract.verification_rules.get("operation") or "")
    capability_family = str(contract.verification_rules.get("capability_family") or "")
    return family in {"contribution", "share", "contribution_followup"} or operation == "top_k_share" or capability_family in {"contribution_followup", "share_followup"}


def _is_contribution_share_expected(value: Any) -> bool:
    return isinstance(value, Mapping) and str(value.get("task_family") or "") in {"contribution", "share", "contribution_followup", "topn_contribution"} and isinstance(value.get("items"), list)


def _share_tolerance(contract: TaskExecutionContract | None) -> float:
    if contract is None:
        return 0.01
    raw = contract.verification_rules.get("share_tolerance")
    try:
        tolerance = float(raw)
    except (TypeError, ValueError):
        return 0.01
    return tolerance if tolerance >= 0 else 0.01


def _coerce_contribution_payload(value: Any, *, expected: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        rows = _extract_tabular_rows(value)
        if not rows:
            return None
        value = {"rows": rows}
    if _is_contribution_share_expected(value):
        return {
            "task_family": "contribution_followup",
            "dimension": str(value.get("dimension") or (expected or {}).get("dimension") or ""),
            "metric": str(value.get("metric") or (expected or {}).get("metric") or ""),
            "total_metric_value": _round_oracle_value(_oracle_float(value.get("total_metric_value"))),
            "items": [_coerce_contribution_item(item, expected=value) for item in value.get("items") or [] if isinstance(item, Mapping)],
        }
    rows = _extract_tabular_rows(value)
    if not rows:
        return None
    dimension = str(value.get("dimension") or (expected or {}).get("dimension") or "")
    metric = str(value.get("metric") or (expected or {}).get("metric") or "")
    dimension_column = _infer_referent_dimension(rows, preferred=dimension, excluded=set())
    metric_column = _find_contribution_column(rows, ("metric_value", metric, "value", "amount", "sales", "销售额"), excluded={dimension_column or ""})
    total_column = _find_contribution_column(rows, ("total_metric_value", f"total_{metric}" if metric else "", "total", "denominator", "总销售额", "总体", "合计"), excluded={dimension_column or "", metric_column or ""})
    share_column = _find_contribution_column(
        rows,
        ("share", "percent", "ratio", "contribution", "contribution_rate", "share_percent", f"{metric}_share" if metric else "", "占比", "贡献率", "比例"),
        excluded={dimension_column or "", metric_column or "", total_column or ""},
        require_numeric=False,
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        referent = _value_for_column(row, dimension_column)
        if referent in (None, ""):
            continue
        metric_value = _oracle_float(_value_for_column(row, metric_column))
        total_value = _oracle_float(_value_for_column(row, total_column))
        share_value = _normalize_share_value(_value_for_column(row, share_column))
        items.append(
            {
                "value": referent,
                "metric_value": _round_oracle_value(metric_value),
                "total_metric_value": _round_oracle_value(total_value),
                "share": _round_oracle_value(share_value),
            }
        )
    if not items:
        return None
    return {
        "task_family": "contribution_followup",
        "dimension": dimension_column or dimension,
        "metric": metric_column or metric,
        "total_metric_value": next((item.get("total_metric_value") for item in items if item.get("total_metric_value") is not None), None),
        "items": items,
    }


def _coerce_contribution_item(item: Mapping[str, Any], *, expected: Mapping[str, Any]) -> dict[str, Any]:
    dimension = str(expected.get("dimension") or "")
    metric = str(expected.get("metric") or "")
    return {
        "value": item.get("value") or item.get(dimension) or item.get("dimension_value") or item.get("referent") or item.get("name"),
        "metric_value": _round_oracle_value(_oracle_float(_first_present(item.get("metric_value"), item.get(metric), item.get("value_metric")))),
        "total_metric_value": _round_oracle_value(_oracle_float(_first_present(item.get("total_metric_value"), item.get(f"total_{metric}" if metric else ""), item.get("total")))),
        "share": _round_oracle_value(_normalize_share_value(_first_present(item.get("share"), item.get("percent"), item.get("ratio"), item.get("contribution"), item.get("contribution_rate"), item.get("share_percent"), item.get(f"{metric}_share" if metric else "")))),
    }


def _find_contribution_column(rows: list[Mapping[str, Any]], candidates: tuple[str, ...], *, excluded: set[str], require_numeric: bool = True) -> str | None:
    columns = _available_row_columns(rows)
    excluded = {column for column in excluded if column}
    for candidate in candidates:
        if not candidate:
            continue
        if _column_present_in_names(candidate, columns):
            matched = _matching_column_name(candidate, columns)
            if matched not in excluded:
                return matched
    for column in columns:
        if column in excluded:
            continue
        if require_numeric and not any(_oracle_float(row.get(column)) is not None for row in rows):
            continue
        lowered = column.lower()
        if any(str(candidate).lower() in lowered for candidate in candidates if candidate):
            return str(column)
    return None


def _normalize_share_value(value: Any) -> float | None:
    number = _oracle_float(value)
    if number is None:
        return None
    text = str(value)
    if "%" not in text and abs(number) <= 1:
        return number * 100
    return number


def _looks_like_quality_oracle_expected(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if "fields" in value and isinstance(value["fields"], list):
        return True
    return bool(
        any(key in value for key in ("field_level_table", "field_level_quality", "duplicate_rules", "outlier_rules", "duplicate_checks"))
        and "tables" not in value
    )


def _build_missing_expected_result_oracle_payload(
    *, contract: TaskExecutionContract, actual: dict[str, Any] | list[Any] | None, answer: str = ""
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    family = str(contract.task_family or "")
    metadata_reason_map = {
        "topn": "missing_expected_result_for_ranking_top_rows",
        "gap": "missing_expected_result_for_ranking_gap_followup",
        "trend": "missing_expected_result_for_time_series_trend",
        "overview": "missing_expected_result_for_overview_schema",
        "multi_file_overview": "missing_expected_result_for_multi_file_overview_schema",
    }
    required_family = family in {"topn", "gap", "trend", "overview", "multi_file_overview"}
    if not required_family:
        return None, None

    capability_family_map = {
        "topn": "ranking",
        "gap": "ranking_followup",
        "trend": "trend_followup",
        "overview": "overview",
        "multi_file_overview": "multi_file_overview",
    }
    operation_map = {
        "topn": "ranking",
        "gap": "ranking",
        "trend": "aggregation",
        "overview": "dataset_overview",
        "multi_file_overview": "multi_table_dataset_overview",
    }
    reason = metadata_reason_map[family]
    issue_metadata = {
        "task_family": family,
        "capability_family": capability_family_map[family],
        "operation": operation_map[family],
        "reason": reason,
    }
    if family == "topn":
        dimension = str(contract.dimension or "").strip()
        metric = str(contract.metric or "").strip()
        rows = _coerce_top_rows(actual, dimension, metric)
        if rows:
            if _is_topn_gap_followup_contract(contract=contract, answer=answer):
                gap_payload = _build_topn_gap_expected_payload(actual=actual, dimension=dimension, metric=metric)
                if gap_payload:
                    return gap_payload, issue_metadata
            return {"_oracle_expected_result_missing": "topn", "row_count": len(rows)}, issue_metadata
        return None, issue_metadata
    if family == "gap":
        gap_payload = _coerce_gap_payload(actual, dimension=contract.dimension or "", metric=contract.metric or "")
        has_gap_followup = False
        if gap_payload and gap_payload.get("top_objects"):
            if len(gap_payload.get("top_objects") or []) == 1:
                return (
                    {
                        "task_family": "gap_or_ranking_followup",
                        "comparison_possible": False,
                        "reason": "only_one_top_object",
                        "minimum_required_objects": 2,
                        "actual_object_count": 1,
                        "object_dimension": contract.dimension,
                        "metric": contract.metric,
                    },
                    issue_metadata,
                )
            if gap_payload.get("adjacent_gaps") or gap_payload.get("gap_to_leader"):
                has_gap_followup = True
        if has_gap_followup:
            adjacent_gaps = gap_payload.get("adjacent_gaps") or []
            gap_to_leader = gap_payload.get("gap_to_leader") or []
            return (
                {
                    "_oracle_expected_result_missing": "gap",
                    "top_row_count": len(gap_payload["top_objects"]),
                    "adjacent_gap_count": len(adjacent_gaps),
                    "gap_to_leader_count": len(gap_to_leader),
                },
                issue_metadata,
            )
        return None, issue_metadata
    if family == "trend":
        trend_expected = _build_trend_constraint_expected_result(contract=contract, actual=actual)
        if trend_expected:
            return trend_expected, issue_metadata
        return None, issue_metadata
    if family in {"overview", "multi_file_overview"}:
        actual_payload = _coerce_overview_payload(actual or {}, allow_join_keys=family == "multi_file_overview")
        if actual_payload:
            return (
                {
                    "_oracle_expected_result_missing": "overview",
                    "table_count": len(actual_payload.get("tables") or []),
                    "profile_fields_count": sum(len(item.get("fields") or []) for item in actual_payload.get("tables") or []),
                },
                issue_metadata,
            )
    return None, issue_metadata


def _is_topn_gap_followup_contract(contract: TaskExecutionContract, answer: str) -> bool:
    """Whether a topn payload should be evaluated with ranking-gap followup logic."""

    operation = str(contract.verification_rules.get("operation") or "").strip()
    capability_family = str(contract.verification_rules.get("capability_family") or "").strip()
    return (
        operation in {"ranking", "filtered_metric_ranking"}
        and (
            capability_family in {"ranking_followup", "growth_ranking_followup", "derived_metric_followup"}
            or contract.requires_previous_artifact
            or operation == "filtered_metric_ranking"
            or _answer_mentions_gap(answer)
        )
    )


def _build_topn_gap_expected_payload(
    *, actual: dict[str, Any] | list[Any] | None, dimension: str, metric: str
) -> dict[str, Any] | None:
    """Normalize bare top rows into ranking-gap expected payload."""

    rows = _extract_tabular_rows(actual)
    if not rows:
        return None

    normalized_dimension = _infer_referent_dimension(rows, preferred=dimension, excluded=set())
    normalized_dimension = normalized_dimension or dimension or "value"
    normalized_metric = _infer_metric_column(rows, preferred=metric, excluded={normalized_dimension} if normalized_dimension else set())
    normalized_metric = normalized_metric or metric or "metric_value"

    gap_payload = _coerce_gap_payload(actual, dimension=normalized_dimension, metric=normalized_metric)
    top_objects = gap_payload.get("top_objects") if isinstance(gap_payload, Mapping) else None
    if not top_objects:
        return None

    canonical_top_objects: list[Mapping[str, Any]] = [item for item in top_objects if isinstance(item, Mapping)]
    if not canonical_top_objects:
        return None

    top_rows = [
        {
            "rank": _parse_rank(top.get("rank"), index + 1),
            normalized_dimension: top.get("value"),
            normalized_metric: top.get("metric_value"),
        }
        for index, top in enumerate(canonical_top_objects)
    ]
    object_count = len(canonical_top_objects)
    if object_count <= 1:
        return {
            "task_family": "ranking_followup_gap",
            "comparison_possible": False,
            "reason": "only_one_top_object",
            "minimum_required_objects": 2,
            "actual_object_count": object_count,
            "dimension": normalized_dimension,
            "metric": normalized_metric,
            "top_rows": top_rows,
        }

    metric_values = [_oracle_float(top.get("metric_value")) for top in canonical_top_objects]
    adjacent_gaps: list[float | None] = []
    for current, next_value in zip(metric_values, metric_values[1:]):
        if current is None or next_value is None:
            adjacent_gaps.append(None)
        else:
            adjacent_gaps.append(_round_oracle_value(current - next_value))
    leader_value = metric_values[0]
    gap_to_leader: list[float | None] = []
    for value in metric_values:
        if leader_value is None or value is None:
            gap_to_leader.append(None)
        else:
            gap_to_leader.append(_round_oracle_value(leader_value - value))

    return {
        "task_family": "ranking_followup_gap",
        "comparison_possible": True,
        "actual_object_count": object_count,
        "dimension": normalized_dimension,
        "metric": normalized_metric,
        "adjacent_gaps": adjacent_gaps,
        "gap_to_leader": gap_to_leader,
        "top_rows": top_rows,
        "top_objects": [
            {"rank": _parse_rank(top.get("rank"), index + 1), "value": top.get("value"), "metric_value": top.get("metric_value")}
            for index, top in enumerate(canonical_top_objects)
        ],
    }


def _coerce_oracle_trend_points(actual: dict[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    extracted_rows = _extract_tabular_rows(actual)
    if extracted_rows:
        rows = extracted_rows
    if not rows:
        return []
    return _coerce_trend_series_points(rows)


def _build_trend_constraint_expected_result(
    *, contract: TaskExecutionContract, actual: dict[str, Any] | list[Any] | None
) -> dict[str, Any] | None:
    rows = _extract_tabular_rows(actual)
    if not rows:
        return None
    time_dimension = _infer_time_dimension(rows, preferred=contract.time_dimension or contract.dimension)
    if not time_dimension:
        return None
    metric = _infer_metric_column(rows, preferred=contract.metric, excluded={time_dimension, contract.referent_dimension or ""})
    if not metric:
        return None
    referent_dimension = _infer_referent_dimension(
        rows,
        preferred=contract.referent_dimension,
        excluded={time_dimension, metric},
    )
    referent_values = [str(value) for value in contract.referent_values if value not in (None, "")]
    referent_values_source = "contract" if referent_values else ""
    if not referent_values and referent_dimension:
        referent_values = _unique_text_values(row.get(referent_dimension) for row in rows)
        referent_values_source = "actual_result"
    series_by_referent = _trend_series_by_referent(
        rows,
        time_dimension=time_dimension,
        metric=metric,
        referent_dimension=referent_dimension,
    )
    point_count = sum(len(points) for points in series_by_referent.values()) if series_by_referent else len(_coerce_trend_series_points(rows))
    if point_count <= 0:
        return None
    shape_summary = _shape_summary_from_series_by_referent(series_by_referent)
    required_columns = [column for column in [time_dimension, referent_dimension, metric] if column]
    return {
        "task_family": "trend_followup",
        "metric": metric,
        "time_dimension": time_dimension,
        "referent_dimension": referent_dimension,
        "referent_values": referent_values,
        "referent_values_source": referent_values_source,
        "required_columns": required_columns,
        "expected_point_count": point_count,
        "point_count": point_count,
        "shape_summary": shape_summary,
        "series_by_referent": series_by_referent,
        "constraints": {
            "required_columns_present": True,
            "point_count_matches_actual": True,
            "time_dimension_present": True,
            "referent_values_covered": bool(referent_values) if referent_dimension else None,
            "no_extra_referent_outside_expected": referent_values_source == "contract" if referent_values and referent_dimension else None,
        },
    }


def _is_trend_constraint_expected(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("task_family") in {"trend_followup", "trend"} and "expected_point_count" in value


def _build_trend_constraint_actual_summary(expected: Any, actual: dict[str, Any] | list[Any] | None) -> dict[str, Any]:
    if not isinstance(expected, Mapping):
        return {}
    rows = _extract_tabular_rows(actual)
    time_dimension = str(expected.get("time_dimension") or "")
    metric = str(expected.get("metric") or "")
    referent_dimension = str(expected.get("referent_dimension") or "")
    available_columns = _available_row_columns(rows)
    series_by_referent = _trend_series_by_referent(
        rows,
        time_dimension=time_dimension,
        metric=metric,
        referent_dimension=referent_dimension or None,
    )
    point_count = sum(len(points) for points in series_by_referent.values()) if series_by_referent else 0
    actual_referent_values = _unique_text_values(row.get(referent_dimension) for row in rows) if referent_dimension else []
    return {
        "available_columns": sorted(available_columns),
        "point_count": point_count,
        "time_dimension_present": bool(time_dimension and _column_present_in_names(time_dimension, available_columns)),
        "metric_present": bool(metric and _column_present_in_names(metric, available_columns)),
        "referent_dimension_present": bool(referent_dimension and _column_present_in_names(referent_dimension, available_columns)) if referent_dimension else None,
        "referent_values": actual_referent_values,
        "shape_summary": _shape_summary_from_series_by_referent(series_by_referent),
        "series_by_referent": series_by_referent,
    }


def _trend_constraint_issue_codes(expected: Any, actual_summary: Mapping[str, Any]) -> list[str]:
    if not isinstance(expected, Mapping):
        return ["trend_constraint_expected_invalid"]
    issue_codes: list[str] = []
    available_columns = set(str(column) for column in actual_summary.get("available_columns") or [])
    for column in expected.get("required_columns") or []:
        if not _column_present_in_names(str(column), available_columns):
            issue_codes.append(f"trend_required_column_missing:{column}")
    if expected.get("expected_point_count") != actual_summary.get("point_count"):
        issue_codes.append("trend_point_count_mismatch")
    if expected.get("time_dimension") and not actual_summary.get("time_dimension_present"):
        issue_codes.append("trend_time_dimension_missing")
    expected_referents = [str(value) for value in expected.get("referent_values") or []]
    actual_referents = [str(value) for value in actual_summary.get("referent_values") or []]
    if expected_referents:
        missing = [value for value in expected_referents if value not in actual_referents]
        if missing:
            issue_codes.append("trend_referent_values_missing")
        if expected.get("referent_values_source") == "contract":
            extra = [value for value in actual_referents if value not in expected_referents]
            if extra:
                issue_codes.append("trend_extra_referent_values")
    return sorted(set(issue_codes))


def _extract_tabular_rows(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, Mapping)]
    if not isinstance(value, Mapping):
        return []
    candidates: list[Any] = [
        value.get("rows"),
        value.get("time_series"),
        value.get("series"),
        value.get("data"),
    ]
    for nested_key in ("result", "value", "actual_result"):
        nested = value.get(nested_key)
        if isinstance(nested, Mapping):
            candidates.extend([nested.get("rows"), nested.get("time_series"), nested.get("series"), nested.get("data")])
        elif isinstance(nested, list):
            candidates.append(nested)
    for candidate in candidates:
        if isinstance(candidate, list):
            rows = [row for row in candidate if isinstance(row, Mapping)]
            if rows:
                return rows
    if value and all(not isinstance(item, (list, dict)) for item in value.values()):
        return [value]
    return []


def _infer_time_dimension(rows: list[Mapping[str, Any]], *, preferred: str | None = None) -> str | None:
    columns = _available_row_columns(rows)
    if preferred and _column_present_in_names(preferred, columns):
        return _matching_column_name(preferred, columns)
    preferred_tokens = ("month", "date", "time", "period", "day", "week", "year", "月份", "日期", "时间", "周期", "年份", "周")
    for column in columns:
        lowered = str(column).lower()
        if any(token in lowered for token in preferred_tokens):
            return str(column)
    return None


def _infer_metric_column(rows: list[Mapping[str, Any]], *, preferred: str | None = None, excluded: set[str] | None = None) -> str | None:
    columns = _available_row_columns(rows)
    excluded = {str(item) for item in excluded or set() if item}
    if preferred and _column_present_in_names(preferred, columns):
        return _matching_column_name(preferred, columns)
    metric_tokens = ("sales", "revenue", "amount", "profit", "margin", "rate", "销售额", "销售", "收入", "金额", "利润", "利润率")
    numeric_columns: list[str] = []
    for column in columns:
        if any(_dimension_matches(column, excluded_column) for excluded_column in excluded):
            continue
        values = [row.get(column) for row in rows if column in row]
        if any(_oracle_float(value) is not None for value in values):
            numeric_columns.append(str(column))
    for token in metric_tokens:
        for column in numeric_columns:
            if token.lower() in column.lower():
                return column
    return numeric_columns[0] if numeric_columns else None


def _infer_referent_dimension(
    rows: list[Mapping[str, Any]], *, preferred: str | None = None, excluded: set[str] | None = None
) -> str | None:
    columns = _available_row_columns(rows)
    excluded = {str(item) for item in excluded or set() if item}
    if preferred and _column_present_in_names(preferred, columns):
        return _matching_column_name(preferred, columns)
    dimension_tokens = ("city", "product", "category", "region", "customer", "store", "城市", "产品", "品类", "地区", "客户", "门店")
    candidates: list[str] = []
    for column in columns:
        if any(_dimension_matches(column, excluded_column) for excluded_column in excluded):
            continue
        values = [row.get(column) for row in rows if column in row]
        if values and any(_oracle_float(value) is None for value in values if value not in (None, "")):
            candidates.append(str(column))
    for token in dimension_tokens:
        for column in candidates:
            if token.lower() in column.lower():
                return column
    return candidates[0] if candidates else None


def _trend_series_by_referent(
    rows: list[Mapping[str, Any]], *, time_dimension: str, metric: str, referent_dimension: str | None
) -> dict[str, list[dict[str, Any]]]:
    series: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        time_value = _value_for_column(row, time_dimension)
        metric_value = _oracle_float(_value_for_column(row, metric))
        if time_value in (None, "") or metric_value is None:
            continue
        referent = str(_value_for_column(row, referent_dimension) if referent_dimension else "all")
        if not referent or referent == "None":
            referent = "all"
        series.setdefault(referent, []).append({"time": str(time_value), "value": _round_oracle_value(metric_value)})
    for points in series.values():
        points.sort(key=lambda item: str(item.get("time") or ""))
    return series


def _shape_summary_from_series_by_referent(series_by_referent: Mapping[str, list[Mapping[str, Any]]]) -> str:
    shapes = [_trend_shape_summary(points) for points in series_by_referent.values() if points]
    if not shapes:
        return "unknown"
    unique_shapes = sorted(set(shapes))
    return unique_shapes[0] if len(unique_shapes) == 1 else "mixed"


def _trend_shape_summary(points: list[Mapping[str, Any]]) -> str:
    values = [_oracle_float(point.get("value")) for point in points]
    values = [value for value in values if value is not None]
    if len(values) <= 1:
        return "unknown"
    deltas = [next_value - current for current, next_value in zip(values[:-1], values[1:])]
    if all(math.isclose(delta, 0.0, abs_tol=1e-9) for delta in deltas):
        return "flat"
    if all(delta >= 0 for delta in deltas) and any(delta > 0 for delta in deltas):
        return "up"
    if all(delta <= 0 for delta in deltas) and any(delta < 0 for delta in deltas):
        return "down"
    if deltas[0] > 0 and any(delta < 0 for delta in deltas[1:]):
        return "up_then_down"
    if deltas[0] < 0 and any(delta > 0 for delta in deltas[1:]):
        return "down_then_up"
    return "mixed"


def _available_row_columns(rows: list[Mapping[str, Any]]) -> set[str]:
    columns: set[str] = set()
    for row in rows:
        columns.update(str(column) for column in row.keys())
    return columns


def _column_present_in_names(column: str, names: set[str]) -> bool:
    return any(_dimension_matches(column, candidate) for candidate in names)


def _matching_column_name(column: str, names: set[str]) -> str:
    for candidate in names:
        if _dimension_matches(column, candidate):
            return str(candidate)
    return str(column)


def _value_for_column(row: Mapping[str, Any], column: str | None) -> Any | None:
    if not column:
        return None
    for key, value in row.items():
        if _dimension_matches(str(column), str(key)):
            return value
    return None


def _unique_text_values(values: Any) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in (None, ""):
            continue
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _coerce_quality_oracle_expected_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    if "field_level_table" in value or "field_level_quality" in value:
        return _coerce_quality_report_payload(value)
    fields_payload = _quality_rows_payload(value.get("fields"))
    if not fields_payload:
        return None
    return {
        "fields": fields_payload,
        "duplicate_checks": _coerce_quality_duplicate_checks(value.get("duplicate_checks")),
        "outlier_rules": _coerce_quality_rules(value.get("outlier_rules")),
    }


def _coerce_quality_oracle_actual_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    candidates: list[Any] = [value]
    quality_report = value.get("quality_report") if isinstance(value.get("quality_report"), Mapping) else None
    if quality_report is not None:
        candidates.append(quality_report)
    result = value.get("result") if isinstance(value.get("result"), Mapping) else None
    if result is not None:
        candidates.append(result)
        if isinstance(result.get("value"), Mapping):
            candidates.append(result.get("value"))
        if isinstance(result.get("quality_report"), Mapping):
            candidates.append(result.get("quality_report"))
    verification = value.get("verification") if isinstance(value.get("verification"), Mapping) else None
    if verification is not None:
        candidates.append(verification)
        if isinstance(verification.get("quality_report"), Mapping):
            candidates.append(verification.get("quality_report"))
    debug = value.get("debug") if isinstance(value.get("debug"), Mapping) else None
    if debug is not None:
        candidates.append(debug)
        if isinstance(debug.get("quality_report"), Mapping):
            candidates.append(debug.get("quality_report"))
        if isinstance(debug.get("result"), Mapping):
            candidates.append(debug.get("result"))

    for candidate in candidates:
        payload = _coerce_quality_report_payload(candidate)
        if payload is not None:
            return payload
    return None


def _coerce_quality_report_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    fields_payload = _quality_rows_payload(value.get("field_level_table") or value.get("field_level_quality"))
    if not isinstance(fields_payload, list):
        return None

    return {
        "fields": fields_payload,
        "duplicate_checks": _coerce_quality_duplicate_checks(value.get("duplicate_rules") or value.get("duplicate_checks")),
        "outlier_rules": _coerce_quality_rules(value.get("outlier_rules")),
    }


def _coerce_quality_duplicate_checks(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        full_row_duplicate_count = value.get("full_row_duplicate_count")
        if full_row_duplicate_count is not None:
            return {"full_row_duplicate_count": full_row_duplicate_count}
        return _coerce_quality_duplicate_checks(_quality_total_duplicates(value))
    if isinstance(value, (list, tuple)):
        return {"full_row_duplicate_count": _quality_total_duplicates(value)}
    if isinstance(value, (int, float)):
        return {"full_row_duplicate_count": int(value)}
    return None


def _quality_total_duplicates(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("full_row_duplicate_count", 0)
    total = 0
    if isinstance(value, (list, tuple)):
        for item in value:
            if not isinstance(item, Mapping):
                continue
            count = item.get("full_row_duplicate_count")
            if count is not None:
                try:
                    total += int(float(count))
                except (TypeError, ValueError):
                    continue
    return total


def _coerce_quality_rules(value: Any) -> list[str]:
    if not value:
        return []
    rows: list[str] = []
    if isinstance(value, str):
        value = [value]
    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, Mapping):
                row_rule = item.get("rule")
                if row_rule:
                    rows.append(_normalized_identifier(str(row_rule)))
            elif item is not None:
                rows.append(_normalized_identifier(str(item)))
    return rows


def _first_present(*candidates: Any) -> Any | None:
    for candidate in candidates:
        if candidate is not None and candidate != "":
            return candidate
    return None


def _quality_rows_payload(rows: Any) -> list[dict[str, Any]] | None:
    if not isinstance(rows, (list, tuple)):
        return None
    payload: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        field_name = (
            str(
                item.get("name")
                or item.get("字段")
                or item.get("field")
                or item.get("column")
                or item.get("column_name")
                or item.get("columnName")
                or item.get("field_name")
                or item.get("table")
                or ""
            )
            .strip()
        )
        if not field_name:
            continue
        if "." in field_name:
            field_name = str(field_name).split(".")[-1].strip()
        payload.append(
            {
                "name": field_name,
                "missing_count": _quality_int_value(
                    _first_present(item.get("missing_count"), item.get("missing_count_total"), item.get("缺失数"))
                ),
                "missing_rate": _quality_rate_value(
                    _first_present(item.get("missing_rate"), item.get("missing_rate_value"), item.get("缺失率"))
                ),
                "type_issue_count": _quality_int_value(
                    _first_present(
                        item.get("type_issue_count"),
                        item.get("类型异常数"),
                        item.get("parse_failure_count"),
                        item.get("类型检测异常数"),
                        item.get("type_parse_failures"),
                    )
                ),
                "outlier_count": _quality_int_value(
                    _first_present(
                        item.get("outlier_count"),
                        item.get("异常值数"),
                        item.get("异常数量"),
                        item.get("outlier_count_value"),
                        item.get("anomaly_count"),
                    )
                ),
            }
        )
    return payload


def _quality_int_value(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _quality_rate_value(value: Any) -> float | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("%"):
        text = text[:-1]
    try:
        number = float(text.replace(",", ""))
    except (TypeError, ValueError):
        return None
    if "%" in str(value):
        return number / 100
    if number > 1 and number <= 100:
        return number / 100
    return number


def oracle_multi_table_join_ranking(expected: Any, actual: Any) -> OracleResult:
    """Build deterministic oracle result for multi-table join ranking tasks."""

    expected_payload = _coerce_multi_table_join_ranking_payload(expected)
    actual_payload = _coerce_multi_table_join_ranking_payload(actual)
    if expected_payload is None:
        return OracleResult(
            oracle_available=False,
            actual_result=actual_payload,
            passed=False,
            diff_summary="Invalid expected_result payload for multi-table join ranking oracle.",
            issue_codes=["oracle_expected_result_invalid"],
        )
    if actual_payload is None:
        return OracleResult(
            oracle_available=True,
            expected_result=expected_payload,
            actual_result=actual_payload,
            passed=False,
            diff_summary="Invalid actual_result payload for multi-table join ranking oracle.",
            issue_codes=["oracle_actual_result_invalid"],
        )

    issue_codes: list[str] = []
    actual_tables = set(_as_string_list(actual_payload.get("source_tables")))
    expected_tables = set(_as_string_list(expected_payload.get("source_tables")))
    if expected_tables and not expected_tables.issubset(actual_tables):
        issue_codes.append("multi_table_join_ranking_source_tables_missing")
        issue_codes.append("join_scope_missing")

    if _join_key_present(expected_payload.get("join_key")) and not _join_key_present(actual_payload.get("join_key")):
        issue_codes.append("join_key_missing")
        issue_codes.append("join_plan_missing")
        issue_codes.append("join_keys_missing")
    elif not _join_key_present(expected_payload.get("join_key")):
        issue_codes.append("join_key_missing")
        issue_codes.append("join_plan_missing")
        issue_codes.append("join_keys_missing")
    elif not _join_key_compatible(expected_payload.get("join_key"), actual_payload.get("join_key")):
        issue_codes.append("join_key_mismatch")

    expected_dimension = str(expected_payload.get("dimension") or "")
    actual_dimension = str(actual_payload.get("dimension") or "")
    if expected_dimension and actual_dimension and not _dimension_matches(expected_dimension, actual_dimension):
        issue_codes.append("join_ranking_dimension_mismatch")
        issue_codes.append("join_ranking_wrong_dimension")

    expected_metric = str(expected_payload.get("metric") or "")
    actual_metric = str(actual_payload.get("metric") or "")
    if expected_metric and actual_metric and not _metric_matches(expected_metric, actual_metric):
        issue_codes.append("join_ranking_metric_mismatch")

    expected_top_object = _ensure_dict(expected_payload.get("top_object"))
    actual_top_object = _ensure_dict(actual_payload.get("top_object"))
    if not expected_top_object:
        issue_codes.append("join_ranking_top_object_missing")
    elif not actual_top_object:
        issue_codes.append("join_ranking_top_object_missing")
    else:
        expected_dimension = expected_payload.get("dimension") or ""
        expected_metric = expected_payload.get("metric") or ""
        expected_dimension_value = _extract_value_like(
            expected_top_object,
            key="dimension",
            dimension=str(expected_dimension),
            metric=str(expected_metric),
        )
        actual_dimension_value = _extract_value_like(
            actual_top_object,
            key="dimension",
            dimension=str(expected_dimension),
            metric=str(expected_metric),
        )
        expected_metric_value = _extract_value_like(
            expected_top_object,
            key="metric",
            dimension=str(expected_dimension),
            metric=str(expected_metric),
        )
        actual_metric_value = _extract_value_like(
            actual_top_object,
            key="metric",
            dimension=str(expected_dimension),
            metric=str(expected_metric),
        )
        if not _dimension_match(expected_dimension_value, actual_dimension_value):
            issue_codes.append("join_ranking_top_object_mismatch")
        if not _numbers_close(expected_metric_value, actual_metric_value):
            issue_codes.append("join_ranking_top_object_mismatch")
    if not expected_top_object or not actual_top_object:
        expected_top_value = expected_payload.get("top_value")
        actual_top_value = actual_payload.get("top_value")
    else:
        expected_top_value = expected_payload.get("top_value")
        actual_top_value = actual_payload.get("top_value")
    if expected_top_value is None or actual_top_value is None:
        issue_codes.append("join_ranking_top_value_missing")
    elif not _numbers_close(expected_top_value, actual_top_value):
        issue_codes.append("join_ranking_top_value_mismatch")

    actual_rows = _coerce_top_rows(actual_payload.get("ranking_rows"), expected_payload.get("dimension"), expected_payload.get("metric"))
    expected_rows = _coerce_top_rows(expected_payload.get("ranking_rows"), expected_payload.get("dimension"), expected_payload.get("metric"))
    if expected_top_object and not _top_object_in_rows(
        expected_top_object,
        actual_rows,
        dimension=str(expected_payload.get("dimension") or ""),
        metric=str(expected_payload.get("metric") or ""),
    ):
        issue_codes.append("join_ranking_rows_missing_top_object")

    if not actual_rows:
        issue_codes.append("join_ranking_actual_rows_missing")

    required_n = _positive_int(expected_payload.get("required_n"))
    actual_distinct_count = _positive_int(actual_payload.get("distinct_count"))
    expected_distinct_count = _positive_int(expected_payload.get("distinct_count")) or len(expected_rows)
    if required_n and expected_distinct_count and expected_distinct_count < required_n:
        answer_text = str(actual_payload.get("answer") or "")
        if actual_distinct_count is None or not _answer_mentions_distinct_shortfall(
            answer_text,
            distinct_count=actual_distinct_count,
            required_n=required_n,
        ):
            issue_codes.append("topn_insufficient_without_distinct_count")
            issue_codes.append("topn_insufficient_distinct_explanation_missing")

    if issue_codes:
        return OracleResult(
            oracle_available=True,
            expected_result=expected_payload,
            actual_result=actual_payload,
            passed=False,
            diff_summary="Deterministic multi-table join ranking result differs from expected.",
            issue_codes=sorted(set(issue_codes)),
        )

    return OracleResult(
        oracle_available=True,
        expected_result=expected_payload,
        actual_result=actual_payload,
        passed=True,
        diff_summary=None,
        issue_codes=[],
    )


def oracle_overview_schema_field_coverage(expected: Any, actual: Any) -> OracleResult:
    """Build deterministic oracle result for single-table overview schema coverage."""

    expected_payload = _coerce_overview_payload(expected)
    actual_payload = _coerce_overview_payload(actual)
    if expected_payload is None:
        return OracleResult(
            oracle_available=False,
            actual_result=actual_payload,
            passed=False,
            diff_summary="Invalid expected_result payload for overview schema oracle.",
            issue_codes=["oracle_overview_expected_result_invalid"],
        )
    if actual_payload is None:
        return OracleResult(
            oracle_available=True,
            expected_result=expected_payload,
            actual_result=actual_payload,
            passed=False,
            diff_summary="Invalid actual_result payload for overview schema oracle.",
            issue_codes=["oracle_overview_actual_result_invalid"],
        )

    issue_codes: list[str] = []
    warning_codes: list[str] = []

    expected_tables = {
        str(item.get("name")): item
        for item in expected_payload.get("tables", [])
        if isinstance(item, dict) and str(item.get("name"))
    }
    actual_tables = {
        str(item.get("name")): item
        for item in actual_payload.get("tables", [])
        if isinstance(item, dict) and str(item.get("name"))
    }

    for expected_name in expected_tables:
        if expected_name not in actual_tables:
            issue_codes.append(f"overview_required_table_missing:{expected_name}")
            continue

        expected_table = expected_tables[expected_name]
        actual_table = actual_tables[expected_name]
        expected_fields = _coerce_text_list(expected_table.get("required_fields"))
        if not expected_fields:
            expected_fields = [
                item.get("name") for item in _coerce_overview_table_fields(expected_table.get("fields"))
            ]
        actual_fields = [item.get("name") for item in _coerce_overview_table_fields(actual_table.get("fields"))]

        missing_fields = _missing_items(expected_fields, actual_fields)
        if missing_fields:
            issue_codes.append(f"overview_required_field_missing:{expected_name}={','.join(missing_fields)}")

        expected_field_map = {
            str(item.get("name")): item
            for item in _coerce_overview_table_fields(expected_table.get("fields"))
            if item.get("name")
        }
        actual_field_map = {
            str(item.get("name")): item
            for item in _coerce_overview_table_fields(actual_table.get("fields"))
            if item.get("name")
        }
        for field_name, expected_field in expected_field_map.items():
            actual_field = actual_field_map.get(field_name)
            if not actual_field:
                continue
            expected_role = str(expected_field.get("role") or "").strip()
            expected_type = str(expected_field.get("type") or "").strip()
            actual_role = str(actual_field.get("role") or "").strip()
            actual_type = str(actual_field.get("type") or "").strip()
            if expected_role and actual_role and _normalized_identifier(expected_role) != _normalized_identifier(actual_role):
                warning_codes.append("overview_field_role_warning")
            if expected_type and actual_type and _normalized_identifier(expected_type) != _normalized_identifier(actual_type):
                warning_codes.append("overview_field_type_warning")

    expected_metrics = _coerce_text_list(expected_payload.get("metric_candidates"))
    actual_metrics = _coerce_text_list(actual_payload.get("metric_candidates"))
    if expected_metrics and _missing_items(expected_metrics, actual_metrics):
        issue_codes.append("overview_metric_candidates_missing")

    expected_dimensions = _coerce_text_list(expected_payload.get("dimension_candidates"))
    actual_dimensions = _coerce_text_list(actual_payload.get("dimension_candidates"))
    if expected_dimensions and _missing_items(expected_dimensions, actual_dimensions):
        issue_codes.append("overview_dimension_candidates_missing")

    expected_time = _coerce_text_list(expected_payload.get("time_columns"))
    actual_time = _coerce_text_list(actual_payload.get("time_columns"))
    if expected_time and _missing_items(expected_time, actual_time):
        issue_codes.append("overview_time_columns_missing")

    expected_references = _coerce_text_list(
        expected_payload.get("analysis_references")
        or expected_payload.get("analysis_directions")
        or expected_payload.get("metric_candidates")
        or expected_payload.get("dimension_candidates")
        or expected_payload.get("time_columns")
    )
    if not _analysis_direction_references_expected_field(
        _coerce_text_list(actual_payload.get("analysis_directions")),
        expected_references,
    ):
        issue_codes.append("overview_analysis_direction_missing_field_reference")

    fail_codes = sorted(set(issue_codes))
    warning_codes = sorted(set(warning_codes))
    all_codes = list(fail_codes) + warning_codes
    passed = not fail_codes

    return OracleResult(
        oracle_available=True,
        expected_result=expected_payload,
        actual_result=actual_payload,
        passed=passed,
        diff_summary=None if passed else "Deterministic overview schema result differs from expected.",
        issue_codes=all_codes,
    )


def oracle_multi_file_dataset_overview(expected: Any, actual: Any) -> OracleResult:
    """Build deterministic oracle result for multi-table overview schema coverage."""

    expected_payload = _coerce_overview_payload(expected, allow_join_keys=True)
    actual_payload = _coerce_overview_payload(actual, allow_join_keys=True)
    if expected_payload is None:
        return OracleResult(
            oracle_available=False,
            actual_result=actual_payload,
            passed=False,
            diff_summary="Invalid expected_result payload for multi-file overview schema oracle.",
            issue_codes=["oracle_overview_expected_result_invalid"],
        )
    if actual_payload is None:
        return OracleResult(
            oracle_available=True,
            expected_result=expected_payload,
            actual_result=actual_payload,
            passed=False,
            diff_summary="Invalid actual_result payload for multi-file overview schema oracle.",
            issue_codes=["oracle_overview_actual_result_invalid"],
        )

    issue_codes: list[str] = []
    warning_codes: list[str] = []

    expected_tables = {
        str(item.get("name")): item
        for item in expected_payload.get("tables", [])
        if isinstance(item, dict) and str(item.get("name"))
    }
    actual_tables = {
        str(item.get("name")): item
        for item in actual_payload.get("tables", [])
        if isinstance(item, dict) and str(item.get("name"))
    }

    for expected_name in expected_tables:
        if expected_name not in actual_tables:
            issue_codes.append(f"overview_required_table_missing:{expected_name}")
            continue

        expected_table = expected_tables[expected_name]
        actual_table = actual_tables[expected_name]
        expected_fields = _coerce_text_list(expected_table.get("required_fields"))
        if not expected_fields:
            expected_fields = [
                item.get("name") for item in _coerce_overview_table_fields(expected_table.get("fields"))
            ]
        actual_fields = [item.get("name") for item in _coerce_overview_table_fields(actual_table.get("fields"))]

        missing_fields = _missing_items(expected_fields, actual_fields)
        if missing_fields:
            issue_codes.append(f"overview_required_field_missing:{expected_name}={','.join(missing_fields)}")

        expected_field_map = {
            str(item.get("name")): item
            for item in _coerce_overview_table_fields(expected_table.get("fields"))
            if item.get("name")
        }
        actual_field_map = {
            str(item.get("name")): item
            for item in _coerce_overview_table_fields(actual_table.get("fields"))
            if item.get("name")
        }
        for field_name, expected_field in expected_field_map.items():
            actual_field = actual_field_map.get(field_name)
            if not actual_field:
                continue
            expected_role = str(expected_field.get("role") or "").strip()
            expected_type = str(expected_field.get("type") or "").strip()
            actual_role = str(actual_field.get("role") or "").strip()
            actual_type = str(actual_field.get("type") or "").strip()
            if expected_role and actual_role and _normalized_identifier(expected_role) != _normalized_identifier(actual_role):
                warning_codes.append("overview_field_role_warning")
            if expected_type and actual_type and _normalized_identifier(expected_type) != _normalized_identifier(actual_type):
                warning_codes.append("overview_field_type_warning")

    expected_metrics = _coerce_text_list(expected_payload.get("metric_candidates"))
    actual_metrics = _coerce_text_list(actual_payload.get("metric_candidates"))
    if expected_metrics and _missing_items(expected_metrics, actual_metrics):
        issue_codes.append("overview_metric_candidates_missing")

    expected_dimensions = _coerce_text_list(expected_payload.get("dimension_candidates"))
    actual_dimensions = _coerce_text_list(actual_payload.get("dimension_candidates"))
    if expected_dimensions and _missing_items(expected_dimensions, actual_dimensions):
        issue_codes.append("overview_dimension_candidates_missing")

    expected_time = _coerce_text_list(expected_payload.get("time_columns"))
    actual_time = _coerce_text_list(actual_payload.get("time_columns"))
    if expected_time and _missing_items(expected_time, actual_time):
        issue_codes.append("overview_time_columns_missing")

    expected_join_keys = _coerce_join_key_records(expected_payload.get("join_keys"))
    actual_join_keys = _coerce_join_key_records(actual_payload.get("join_keys"))
    for expected_key in expected_join_keys:
        if not any(_join_key_compatible(expected_key, actual_key) for actual_key in actual_join_keys):
            expected_left = str(expected_key.get("left") or "")
            expected_right = str(expected_key.get("right") or "")
            if expected_left or expected_right:
                issue_codes.append(f"overview_join_key_missing:{expected_left}->{expected_right}")
            else:
                issue_codes.append("overview_join_key_missing")

    expected_references = _coerce_text_list(
        expected_payload.get("analysis_references")
        or expected_payload.get("analysis_directions")
        or expected_payload.get("metric_candidates")
        or expected_payload.get("dimension_candidates")
        or expected_payload.get("time_columns")
    )
    if not _analysis_direction_references_expected_field(
        _coerce_text_list(actual_payload.get("analysis_directions")),
        expected_references,
    ):
        issue_codes.append("overview_analysis_direction_missing_field_reference")

    fail_codes = sorted(set(issue_codes))
    warning_codes = sorted(set(warning_codes))
    all_codes = list(fail_codes) + warning_codes
    passed = not fail_codes

    return OracleResult(
        oracle_available=True,
        expected_result=expected_payload,
        actual_result=actual_payload,
        passed=passed,
        diff_summary=None if passed else "Deterministic multi-file overview schema result differs from expected.",
        issue_codes=all_codes,
    )


def _coerce_overview_payload(value: Any, allow_join_keys: bool = False) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    tables = _coerce_overview_tables(value.get("tables"))
    if not tables:
        return None
    return {
        "tables": tables,
        "required_fields": _coerce_text_list(value.get("required_fields")),
        "metric_candidates": _coerce_text_list(value.get("metric_candidates")),
        "dimension_candidates": _coerce_text_list(value.get("dimension_candidates")),
        "time_columns": _coerce_text_list(value.get("time_columns")),
        "analysis_references": _coerce_text_list(
            value.get("analysis_references")
            or value.get("analysis_directions")
            or value.get("metric_candidates")
            or value.get("dimension_candidates")
            or value.get("time_columns")
        ),
        "analysis_directions": _coerce_text_list(value.get("analysis_directions"))
        or _coerce_text_list(value.get("analysis_references"))
        or _coerce_text_list(value.get("metric_candidates"))
        or _coerce_text_list(value.get("dimension_candidates"))
        or _coerce_text_list(value.get("time_columns")),
        "join_keys": _coerce_join_key_records(value.get("join_keys")) if allow_join_keys else [],
    }


def _coerce_overview_tables(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    tables: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or item.get("table") or item.get("table_name") or "").strip()
        if not name:
            continue
        fields = _coerce_overview_table_fields(item.get("fields"))
        table: dict[str, Any] = {"name": name, "fields": fields}
        required_fields = _coerce_text_list(item.get("required_fields"))
        if required_fields:
            table["required_fields"] = required_fields
        elif fields:
            table["required_fields"] = [field.get("name") for field in fields if field.get("name")]
        tables.append(table)
    return tables


def _coerce_overview_table_fields(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    fields: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or item.get("field") or item.get("field_name") or "").strip()
        if not name:
            continue
        role = str(item.get("role") or "").strip()
        field_type = str(item.get("type") or item.get("field_type") or "").strip()
        fields.append({"name": name, "role": role, "type": field_type})
    return fields


def _coerce_text_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _missing_items(expected: list[str], actual: list[str]) -> list[str]:
    if not expected:
        return []
    actual_set = {_normalized_identifier(item) for item in actual if item}
    missing: list[str] = []
    for item in expected:
        if not item:
            continue
        if _normalized_identifier(item) not in actual_set:
            missing.append(item)
    return missing


def _coerce_join_key_records(value: Any) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if not value:
        return records
    items = value if isinstance(value, list) else [value]
    for item in items:
        parsed = _coerce_join_key_payload(item)
        if parsed is not None and parsed.get("left") and parsed.get("right"):
            if parsed not in records:
                records.append(parsed)
            continue
        if not isinstance(item, Mapping):
            continue
        left = str(item.get("left") or item.get("left_table") or "").strip()
        right = str(item.get("right") or item.get("right_table") or "").strip()
        left_key = str(item.get("left_field") or item.get("left_key") or item.get("left_column") or "").strip()
        right_key = str(item.get("right_field") or item.get("right_key") or item.get("right_column") or "").strip()
        candidate = {
            "left": left if "." not in left else left,
            "right": right if "." not in right else right,
        }
        if left and left_key and "." not in left:
            candidate["left"] = f"{left}.{left_key}"
        if right and right_key and "." not in right:
            candidate["right"] = f"{right}.{right_key}"
        if not candidate.get("left") and left_key:
            candidate["left"] = left_key
        if not candidate.get("right") and right_key:
            candidate["right"] = right_key
        if candidate.get("left") and candidate.get("right") and candidate not in records:
            records.append({"left": candidate["left"], "right": candidate["right"]})
    return records


def _analysis_direction_references_expected_field(directions: list[str], field_names: list[str]) -> bool:
    if not directions:
        return False
    if not field_names:
        return True

    normalized_refs: set[str] = set()
    for item in field_names:
        if not item:
            continue
        identifier = _normalized_identifier(item)
        if identifier:
            normalized_refs.add(identifier)
        for piece in re.split(r"[^a-z0-9]+", identifier):
            if piece:
                normalized_refs.add(piece)

    for direction in directions:
        direction_text = _normalized_identifier(str(direction or ""))
        for reference in normalized_refs:
            if reference and reference in direction_text:
                return True
    return False

def _coerce_multi_table_join_ranking_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    dimension = str(value.get("dimension") or "").strip()
    metric = str(value.get("metric") or "").strip()
    source_tables = _as_string_list(value.get("source_tables") or value.get("tables") or value.get("source_table"))
    ranking_rows = _coerce_top_rows(value.get("ranking_rows"), dimension, metric)
    if not ranking_rows:
        ranking_rows = _coerce_top_rows(value.get("rows"), dimension, metric)
    top_object = _coerce_top_object(value.get("top_object"), ranking_rows, dimension=dimension, metric=metric)
    if not top_object and ranking_rows:
        top_object = _coerce_top_object(None, ranking_rows, dimension=dimension, metric=metric)
    top_value = value.get("top_value")
    if top_value is None and top_object:
        top_value = _extract_value_like(top_object, key="metric", dimension=dimension, metric=metric)
    return {
        "source_tables": source_tables,
        "join_key": _coerce_join_key_payload(value.get("join_key")),
        "dimension": dimension,
        "metric": metric,
        "required_n": _positive_int(value.get("required_n") or value.get("top_n") or value.get("limit")),
        "distinct_count": _positive_int(value.get("distinct_count")),
        "answer": str(value.get("answer") or ""),
        "ranking_rows": ranking_rows,
        "top_object": top_object if isinstance(top_object, dict) else {},
        "top_value": _round_oracle_value(top_value),
    }


def _answer_mentions_distinct_shortfall(answer: str, *, distinct_count: int, required_n: int) -> bool:
    compact = str(answer or "").replace(" ", "")
    if not compact:
        return False
    count_texts = {str(distinct_count), _small_number_zh(distinct_count)}
    top_texts = {f"Top{required_n}", f"top{required_n}", f"前{required_n}"}
    has_count = any(f"只有{text}个" in compact or f"共{text}个" in compact or f"{text}个城市" in compact for text in count_texts)
    has_top = any(text in compact for text in top_texts) or "不足" in compact or "无法返回" in compact
    return has_count and has_top


def _small_number_zh(value: int) -> str:
    mapping = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}
    return mapping.get(value, str(value))


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _coerce_join_key_payload(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        left = str(value.get("left") or value.get("left_table") or value.get("left_source") or "").strip()
        right = str(value.get("right") or value.get("right_table") or value.get("right_source") or "").strip()
        left_key = str(value.get("left_key") or value.get("left_field") or value.get("left_column") or "").strip()
        right_key = str(value.get("right_key") or value.get("right_field") or value.get("right_column") or "").strip()
        text = str(value.get("text") or "").strip()

        if left and not "." in left and left_key:
            left = f"{left}.{left_key}"
        elif not left and left_key:
            left = left_key

        if right and not "." in right and right_key:
            right = f"{right}.{right_key}"
        elif not right and right_key:
            right = right_key

        if left and right:
            return {"left": left, "right": right}

        if text:
            parsed = _coerce_join_key_payload(text)
            if parsed is not None:
                return parsed
        return None

    if isinstance(value, str):
        text = str(value).strip()
        if not text:
            return None
        if "->" in text:
            left, right = [item.strip() for item in text.split("->", 1)]
            if left and right:
                return {"left": left, "right": right}
        if "=" in text:
            left, right = [item.strip() for item in text.split("=", 1)]
            if left and right:
                return {"left": left, "right": right}
    return None


def _coerce_top_rows(value: Any, dimension: str, metric: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, Mapping):
            continue
        dimension_key = _coerce_first_matching_key(item, expected=dimension, matcher=_dimension_matches)
        metric_key = _coerce_first_matching_key(item, expected=metric, matcher=_metric_matches)
        if dimension_key is None and "value" in item:
            dimension_key = "value"
        if metric_key is None and "metric_value" in item:
            metric_key = "metric_value"
        if not dimension_key and not metric_key:
            continue
        dimension_value = item.get(dimension_key) if dimension_key is not None else None
        metric_value = item.get(metric_key) if metric_key is not None else None
        if str(dimension_value).strip() == "":
            continue
        row: dict[str, Any] = {}
        if dimension and dimension_key:
            row[dimension] = dimension_value
        elif dimension:
            row[dimension] = item.get("value")
        else:
            # pragma: no cover - defensive for malformed payloads
            row.update(item)
            rows.append(row)
            continue
        if metric:
            row[metric] = _round_oracle_value(metric_value)
        else:
            row[metric] = _round_oracle_value(metric_value)
        rows.append(row)
        if len(rows) == index:
            # keep deterministic order while allowing callers to compare by position
            rows[-1]["rank"] = index
    return rows


def _coerce_first_matching_key(row: dict[str, Any], *, expected: str, matcher) -> str | None:
    for key in row:
        if isinstance(key, str) and matcher(expected, key):
            return str(key)
    if expected and expected in row:
        return str(expected)
    return None


def _coerce_top_object(
    value: Any,
    rows: list[dict[str, Any]],
    *,
    dimension: str,
    metric: str,
) -> dict[str, Any] | None:
    payload = _ensure_dict(value)
    if payload:
        canonical = {}
        for key, item_value in payload.items():
            if key in {"rank", "value", "metric_value"}:
                continue
            canonical_key = str(key)
            canonical[canonical_key] = item_value
        if dimension and dimension in payload:
            canonical.pop("value", None)
        if metric and metric in payload:
            canonical.pop("metric_value", None)
        if canonical:
            if "rank" in payload:
                payload_value = dict(payload)
                payload_value["value"] = payload_value.get("value")
                payload = payload_value
            return canonical

    if rows:
        first = rows[0]
        if isinstance(first, Mapping):
            if dimension and metric and dimension in first and metric in first:
                return {dimension: first.get(dimension), metric: first.get(metric)}
            if "value" in first:
                value = first["value"]
                metric_value = first.get("metric_value")
                if metric:
                    return {metric: metric_value, dimension: value} if dimension else {"value": value, metric: metric_value}
    return None


def _extract_value_like(value: Mapping[str, Any], *, key: str, dimension: str, metric: str) -> Any | None:
    if key == "metric" and metric:
        for candidate, candidate_value in value.items():
            if isinstance(candidate, str) and _metric_matches(metric, candidate):
                return candidate_value
    for candidate, candidate_value in value.items():
        if isinstance(candidate, str) and _dimension_matches(dimension, candidate):
            if candidate == dimension and candidate != key:
                continue
        return candidate_value
    return value.get("value") if "value" in value else value.get("metric_value")


def _ensure_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if value:
        return [str(value).strip()] if str(value).strip() else []
    return []


def _join_key_present(value: Any) -> bool:
    mapping = value if isinstance(value, Mapping) else None
    if not isinstance(mapping, Mapping):
        return False
    left = str(mapping.get("left") or mapping.get("left_table") or "").strip()
    right = str(mapping.get("right") or mapping.get("right_table") or "").strip()
    return bool(left and right)


def _join_key_compatible(expected: Any, actual: Any) -> bool:
    expected_key = _normalize_join_key(expected)
    actual_key = _normalize_join_key(actual)
    if not expected_key or not actual_key:
        return False

    (exp_left_table, exp_left_key, exp_right_table, exp_right_key) = expected_key
    (act_left_table, act_left_key, act_right_table, act_right_key) = actual_key

    direct = _join_side_compatible(exp_left_table, exp_left_key, act_left_table, act_left_key) and _join_side_compatible(
        exp_right_table,
        exp_right_key,
        act_right_table,
        act_right_key,
    )
    swapped = _join_side_compatible(exp_left_table, exp_left_key, act_right_table, act_right_key) and _join_side_compatible(
        exp_right_table,
        exp_right_key,
        act_left_table,
        act_left_key,
    )
    return bool(direct or swapped)


def _join_side_compatible(expected_table: str, expected_key: str, actual_table: str, actual_key: str) -> bool:
    table_match = True
    if expected_table and actual_table:
        table_match = _normalized_identifier(expected_table) == _normalized_identifier(actual_table)
    key_match = True
    if expected_key and actual_key:
        key_match = _normalized_identifier(expected_key) == _normalized_identifier(actual_key)
    return table_match and key_match


def _normalized_identifier(value: str) -> str:
    return str(value).strip().lower().replace(" ", "")


def _normalize_join_key(value: Any) -> tuple[str, str, str, str] | None:
    if not isinstance(value, Mapping):
        return None
    left = str(value.get("left") or value.get("left_table") or "").strip()
    right = str(value.get("right") or value.get("right_table") or "").strip()
    if not left or not right:
        return None
    left_key = ""
    right_key = ""
    for candidate in ("left_key", "left_field", "left_column"):
        if value.get(candidate):
            left_key = str(value.get(candidate) or "").strip()
            break
    for candidate in ("right_key", "right_field", "right_column"):
        if value.get(candidate):
            right_key = str(value.get(candidate) or "").strip()
            break
    if "." in left and not left_key:
        left, left_key = [item.strip() for item in left.rsplit(".", 1)]
    if "." in right and not right_key:
        right, right_key = [item.strip() for item in right.rsplit(".", 1)]
    return left, left_key, right, right_key


def _dimension_matches(expected: str, actual: str) -> bool:
    return _dimension_aliases_match(expected, actual)


def _metric_matches(expected: str, actual: str) -> bool:
    return _metric_aliases_match(expected, actual)


def _dimension_aliases_match(expected: str, actual: str) -> bool:
    expected_aliases = _dimension_aliases(expected)
    actual_aliases = _dimension_aliases(actual)
    return bool(expected_aliases & actual_aliases)


def _metric_aliases_match(expected: str, actual: str) -> bool:
    expected_aliases = _metric_aliases(expected)
    actual_aliases = _metric_aliases(actual)
    return bool(expected_aliases & actual_aliases)


def _dimension_aliases(value: str) -> set[str]:
    key = str(value or "").strip().lower()
    aliases = {
        "city": {"city", "城市"},
        "customer_id": {"customer_id", "customer", "cust_id", "客户"},
        "product": {"product", "product_name", "sku", "sku_name", "产品"},
        "service_line": {"service_line", "business_line", "服务线", "业务线"},
        "segment": {"segment", "客群"},
        "month": {"month", "月份", "月度"},
        "region": {"region", "区域", "地区"},
    }
    canonical = _normalized_identifier(key)
    for _, values in aliases.items():
        if canonical in {_normalized_identifier(item) for item in values}:
            return {_normalized_identifier(item) for item in values}
        if canonical in values:
            return values
    return {canonical} if canonical else set()


def _metric_aliases(value: str) -> set[str]:
    key = str(value or "").strip().lower()
    aliases = {
        "amount": {"amount", "revenue", "sales", "金额", "订单金额", "订单额", "订单总金额", "订单总额", "总额", "收入", "营收", "销售额", "销售金额"},
        "sales": {"sales", "amount", "revenue", "销售额", "销售金额", "金额"},
        "profit": {"profit", "利润", "毛利"},
        "利润率": {"利润率", "毛利率", "profit_margin", "profit margin", "margin"},
    }
    canonical = _normalized_identifier(key)
    normalized_aliases = {k: {_normalized_identifier(item) for item in values} for k, values in aliases.items()}
    for _, values in normalized_aliases.items():
        if canonical in values:
            return values | {canonical}
    return {canonical} if canonical else set()


def _top_object_in_rows(
    top_object: Mapping[str, Any],
    rows: list[dict[str, Any]],
    *,
    dimension: str,
    metric: str,
) -> bool:
    if not rows:
        return False
    expected_dimension = _extract_value_like(top_object, key="dimension", dimension=dimension, metric=metric)
    expected_metric = _extract_value_like(top_object, key="metric", dimension=dimension, metric=metric)
    if expected_dimension is None or expected_metric is None:
        return False
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        row_dimension = row.get(dimension)
        if dimension and not _dimension_match(row_dimension, expected_dimension):
            continue
        row_metric = row.get(metric)
        if _numbers_close(row_metric, expected_metric):
            return True
    return False


def _dimension_match(expected: Any, actual: Any) -> bool:
    return _dimension_matches(str(expected or ""), str(actual or ""))


def _numbers_close(expected: Any, actual: Any) -> bool:
    expected_value = _oracle_float(expected)
    actual_value = _oracle_float(actual)
    if expected_value is None or actual_value is None:
        return str(expected) == str(actual)
    return math.isclose(expected_value, actual_value, rel_tol=1e-6, abs_tol=0.01)


def _extract_value_like(value: Mapping[str, Any], *, key: str, dimension: str, metric: str) -> Any | None:
    if key == "dimension" and dimension:
        for candidate, candidate_value in value.items():
            if isinstance(candidate, str) and _dimension_matches(dimension, candidate):
                return candidate_value
    if key == "metric" and metric:
        for candidate, candidate_value in value.items():
            if isinstance(candidate, str) and _metric_matches(metric, candidate):
                return candidate_value
    if key == "metric" and "metric_value" in value:
        return value.get("metric_value")
    if "value" in value:
        return value.get("value")
    return next(iter(value.values())) if value else None


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
    if isinstance(execution_result, Mapping):
        return dict(execution_result)
    if isinstance(execution_result, list):
        return execution_result
    if execution_result.rows:
        return execution_result.rows
    if isinstance(execution_result.value, (dict, list)):
        return execution_result.value
    if execution_result.value is None:
        return None
    return {"value": execution_result.value}


def _is_ranking_followup_gap_expected(expected: Any) -> bool:
    return (
        isinstance(expected, Mapping)
        and (
            expected.get("task_family") == "ranking_followup_gap"
            or all(key in expected for key in ("top_objects", "adjacent_gaps", "gap_to_leader"))
        )
    ) or _is_gap_insufficient_expected(expected)


def _is_gap_insufficient_expected(expected: Any) -> bool:
    return (
        isinstance(expected, Mapping)
        and expected.get("comparison_possible") is False
        and str(expected.get("task_family")) in {"gap_or_ranking_followup", "ranking_followup_gap"}
    )


def _is_multi_table_join_ranking_expected(expected: Any) -> bool:
    if not isinstance(expected, Mapping):
        return False
    if not isinstance(expected.get("source_tables"), (list, tuple, str, set)):
        return False
    dimension = str(expected.get("dimension") or "")
    metric = str(expected.get("metric") or "")
    if not dimension or not metric:
        return False
    has_rows = bool(expected.get("ranking_rows"))
    has_top = bool(expected.get("top_object"))
    has_value = expected.get("top_value") is not None
    return has_rows or has_top or has_value


def oracle_topn_followup_gap(expected: Any, actual: Any, *, answer: str = "") -> OracleResult:
    if _is_gap_insufficient_expected(expected):
        return _oracle_gap_insufficient_objects(expected, actual, answer=answer)
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

    if isinstance(expected, Mapping):
        expected_payload = dict(expected_payload)
        for key in (
            "task_family",
            "comparison_possible",
            "actual_object_count",
            "dimension",
            "metric",
            "minimum_required_objects",
            "reason",
            "top_rows",
            "top_objects",
            "object_dimension",
        ):
            if key in expected:
                if key == "top_objects":
                    if expected_payload.get("top_objects"):
                        continue
                expected_payload[key] = expected[key]

    issue_codes: list[str] = []
    expected_top = expected_payload["top_objects"]
    actual_top = actual_payload["top_objects"]

    if len(expected_top) < 2 or len(actual_top) < 2:
        issue_codes.append("insufficient_objects_for_gap")

    if any(_oracle_float(item.get("metric_value")) is None for item in actual_top):
        issue_codes.append("gap_metric_value_missing")

    adjacent_gap_matched = _compare_gap_values(
        expected_payload["adjacent_gaps"],
        actual_payload["adjacent_gaps"],
    )
    gap_to_leader_matched = _compare_gap_values(
        expected_payload["gap_to_leader"],
        actual_payload["gap_to_leader"],
    )
    if not adjacent_gap_matched:
        issue_codes.append("gap_mismatch:adjacent_gaps")
    if not gap_to_leader_matched:
        issue_codes.append("gap_mismatch:gap_to_leader")

    matched = _compare_top_objects(expected_top, actual_top) and adjacent_gap_matched and gap_to_leader_matched

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


def _oracle_gap_insufficient_objects(expected: Any, actual: Any, *, answer: str = "") -> OracleResult:
    actual_payload = _coerce_gap_payload(
        actual,
        dimension=str(expected.get("object_dimension") or expected.get("dimension") or ""),
        metric=str(expected.get("metric") or ""),
    )
    actual_count = len(actual_payload.get("top_objects") or []) if actual_payload else 0
    expected_payload = dict(expected) if isinstance(expected, Mapping) else {}
    if actual_count and expected_payload.get("actual_object_count") != actual_count:
        expected_payload["actual_object_count"] = actual_count
    explained = _answer_explains_insufficient_gap(answer)
    issue_code = "gap_insufficient_objects_not_explained"
    return OracleResult(
        oracle_available=True,
        expected_result=expected_payload,
        actual_result=actual_payload or actual,
        passed=explained,
        diff_summary=None if explained else "Only one top object is available, but the answer does not clearly explain that comparison is impossible.",
        issue_codes=[] if explained else [issue_code],
    )


def _coerce_gap_payload(value: Any, *, dimension: str = "", metric: str = "") -> dict[str, Any] | None:
    rows = _extract_tabular_rows(value)
    if not isinstance(value, Mapping):
        if rows:
            top_objects = _top_objects_from_rows(rows, dimension=dimension, metric=metric)
            if not top_objects:
                return None
            metric_values = [_oracle_float(item.get("metric_value")) for item in top_objects]
            adjacent_gaps: list[float | None] = []
            for current, next_value in zip(metric_values, metric_values[1:]):
                if current is None or next_value is None:
                    adjacent_gaps.append(None)
                else:
                    adjacent_gaps.append(_round_oracle_value(current - next_value))
            leader_value = metric_values[0] if metric_values else None
            gap_to_leader: list[float | None] = []
            for value in metric_values:
                if leader_value is None or value is None:
                    gap_to_leader.append(None)
                else:
                    gap_to_leader.append(_round_oracle_value(leader_value - value))
            return {
                "top_objects": top_objects,
                "adjacent_gaps": adjacent_gaps,
                "gap_to_leader": gap_to_leader,
            }
        return None
    raw_top_objects = value.get("top_objects", [])
    if not raw_top_objects and rows:
        top_objects = _top_objects_from_rows(rows, dimension=dimension, metric=metric)
        if not top_objects:
            return None
        metric_values = [_oracle_float(item.get("metric_value")) for item in top_objects]
        adjacent_gaps = []
        for current, next_value in zip(metric_values, metric_values[1:]):
            if current is None or next_value is None:
                adjacent_gaps.append(None)
            else:
                adjacent_gaps.append(_round_oracle_value(current - next_value))
        leader_value = metric_values[0] if metric_values else None
        gap_to_leader = []
        for value in metric_values:
            if leader_value is None or value is None:
                gap_to_leader.append(None)
            else:
                gap_to_leader.append(_round_oracle_value(leader_value - value))
        return {
            "top_objects": top_objects,
            "adjacent_gaps": adjacent_gaps,
            "gap_to_leader": gap_to_leader,
        }
    top_objects = []
    for item in raw_top_objects:
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


def _top_objects_from_rows(rows: list[Mapping[str, Any]], *, dimension: str = "", metric: str = "") -> list[dict[str, Any]]:
    if not rows:
        return []
    dimension_column = _infer_referent_dimension(rows, preferred=dimension, excluded={metric} if metric else set())
    metric_column = _infer_metric_column(rows, preferred=metric, excluded={dimension_column or ""})
    if not dimension_column or not metric_column:
        return []
    top_objects: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        value = _value_for_column(row, dimension_column)
        metric_value = _oracle_float(_value_for_column(row, metric_column))
        if value in (None, ""):
            continue
        top_objects.append(
            {
                "rank": _parse_rank(row.get("rank") or row.get("排名"), index),
                "value": value,
                "metric_value": _round_oracle_value(metric_value),
            }
        )
    return top_objects


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


def _answer_explains_insufficient_gap(answer_text: str) -> bool:
    compact = "".join(str(answer_text or "").split())
    lowered = str(answer_text or "").lower()
    chinese_tokens = (
        "无法比较",
        "不能比较",
        "没法比较",
        "无法对比",
        "不能对比",
        "没法对比",
        "无法计算差距",
        "不能计算差距",
        "没法计算差距",
        "无法算差距",
        "不能算差距",
        "没法算差距",
        "没法算相邻差距",
        "没有第二名",
        "只有一个",
        "仅有一个",
        "只有1个",
        "仅有1个",
        "只有一条",
        "仅有一条",
        "不足两个",
        "少于两个",
    )
    english_tokens = (
        "only one",
        "only 1",
        "single",
        "insufficient",
        "not enough",
        "cannot compare",
        "can't compare",
        "unable to compare",
        "no second",
    )
    return any(token in compact for token in chinese_tokens) or any(token in lowered for token in english_tokens)


def _answer_text_from_execution_result(execution_result: ExecutionResult) -> str:
    if isinstance(execution_result, Mapping):
        return str(execution_result.get("answer") or "")
    if isinstance(execution_result.value, Mapping):
        return str(execution_result.value.get("answer") or execution_result.value.get("text") or "")
    return ""
