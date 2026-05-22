"""Benchmark metric aggregation focused on general capability gaps."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from data_agent_core.core.capability_registry import SQL_SUPPORT_NATIVE, capability_summary_for_operation
from data_agent_core.errors.error_types import BENCHMARK_EVALUATION_ERROR, VERIFICATION_FAILED
from data_agent_core.output.output_contract import validate_final_answer


SEMANTIC_CAPABILITY_FAMILIES = {
    "business_rule_what_if",
    "metric_definition",
    "denominator_selection",
    "entity_grain",
    "share_of_total",
}


def summarize_details(details: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate benchmark rows without creating task-specific optimization hints."""

    scored = [row for row in details if row.get("correct") is not None]
    correct = [row for row in scored if row.get("correct") is True]
    by_error_type = _count_key(details, "error_type")
    not_applicable_counts = _count_key([row for row in details if row.get("not_applicable_category")], "not_applicable_category")
    return {
        "total": len(details),
        "scored": len(scored),
        "correct": len(correct),
        "accuracy": None if not scored else len(correct) / len(scored),
        "success_count": sum(1 for row in details if row.get("success")),
        "unexpected_not_applicable": not_applicable_counts.get("capability_gap", 0),
        "true_unsupported": not_applicable_counts.get("true_unsupported", 0),
        "not_applicable_counts": not_applicable_counts,
        "sql_coverage": _summarize_sql_coverage(details),
        "sql_covered_subset_accuracy": _summarize_sql_covered_subset_accuracy(details),
        "pandas_sql_consistency": _summarize_pandas_sql_consistency(details),
        "gap_counts": _summarize_gap_counts(details),
        "operation_metrics": _summarize_by_key(details, "operation"),
        "capability_family_metrics": _summarize_by_key(details, "capability_family"),
        "error_type_counts": by_error_type,
        "risk_taxonomy": summarize_risk_taxonomy(details),
    }


def benchmark_error_type(response: Any, correct: bool | None) -> str | None:
    """Classify benchmark failures after a response has been produced."""

    if getattr(response, "success", False) and correct is not False:
        return None
    for error in getattr(response, "errors", []) or []:
        if isinstance(error, dict) and error.get("error_type"):
            return str(error["error_type"])
        if hasattr(error, "error_type"):
            return str(error.error_type)
    if not getattr(response, "success", False):
        return VERIFICATION_FAILED
    if correct is False:
        return BENCHMARK_EVALUATION_ERROR
    return None


def executor_report_fields(response: Any, trace: Any, error_type: str | None) -> dict[str, Any]:
    """Build unified executor/parity fields for benchmark detail rows."""

    debug = getattr(response, "debug", {}) or {}
    operation = str((debug or {}).get("operation") or _trace_operation(trace) or "unknown")
    capability = dict((debug or {}).get("capability") or capability_summary_for_operation(operation))
    sql_summary = _as_dict(getattr(trace, "sql_result_summary", None))
    verification = _as_dict(getattr(trace, "verification_result", None)) or _as_dict(getattr(response, "verification", None))
    sql_support = str(sql_summary.get("sql_support") or capability.get("sql_support") or SQL_SUPPORT_NATIVE)
    sql_skipped = sql_summary.get("skipped")
    if sql_skipped is None:
        sql_skipped = not bool(capability.get("native_sql_supported", sql_support == SQL_SUPPORT_NATIVE))
    sql_success = None if sql_skipped else sql_summary.get("success")
    pandas_sql_consistent = verification.get("pandas_sql_consistent")
    capability_family = str(capability.get("capability_family") or "unknown")
    executor_mismatch = pandas_sql_consistent is False
    semantic_mismatch = _semantic_mismatch(verification) or (
        error_type == BENCHMARK_EVALUATION_ERROR
        and not executor_mismatch
        and capability_family in SEMANTIC_CAPABILITY_FAMILIES
    )
    coverage_gap = bool(capability.get("coverage_gap")) or bool(sql_skipped) or sql_support != SQL_SUPPORT_NATIVE
    format_mismatch = error_type == BENCHMARK_EVALUATION_ERROR and not semantic_mismatch and not executor_mismatch
    return {
        "capability_family": capability_family,
        "sql_support": sql_support,
        "sql_skipped": bool(sql_skipped),
        "sql_success": sql_success,
        "pandas_sql_consistent": pandas_sql_consistent,
        "coverage_gap": coverage_gap,
        "semantic_mismatch": semantic_mismatch,
        "executor_mismatch": executor_mismatch,
        "format_mismatch": format_mismatch,
    }


def summarize_risk_taxonomy(details: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate submission quality risks from semantic and capability risks."""

    scored = [row for row in details if row.get("correct") is not None]
    format_rows = [row for row in details if _has_format_risk(row)]
    semantic_rows = [row for row in details if row.get("semantic_mismatch") is True]
    capability_rows = [
        row
        for row in details
        if row.get("coverage_gap") is True or row.get("not_applicable_category") == "capability_gap"
    ]
    submission_rows = [row for row in details if _has_submission_risk(row)]
    trace_rows = [row for row in details if _has_trace_redaction_risk(row)]
    return {
        "format_risk": _risk_bucket(format_rows, "output_contract or scorer format mismatch"),
        "semantic_risk": _risk_bucket(semantic_rows, "semantic verifier or scorer mismatch"),
        "capability_risk": _risk_bucket(capability_rows, "coverage gap or capability-gap Not Applicable"),
        "submission_risk": _risk_bucket(submission_rows, "empty, object/list, debug, SQL, markdown, or trace-like final answer"),
        "official_hidden_unknown": {
            "applies": bool(details) and not scored,
            "scored_locally": len(scored),
            "note": "True official hidden accuracy is not reproducible locally when expected answers are unavailable.",
        },
        "public_proxy_observation": {
            "used_in_core_chain": False,
            "status": "not_used_in_core_chain",
            "note": "Public proxy pools may be used only for post-response observation, never as planner/executor/verifier input.",
        },
        "real_provider_cost_latency": _summarize_provider_runtime(details),
        "trace_redaction_risk": _risk_bucket(trace_rows, "final answer appears to expose debug, trace, SQL, or markdown"),
    }


def _summarize_by_key(details: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in details:
        groups[str(row.get(key) or "unknown")].append(row)
    return {name: _summarize_group(rows) for name, rows in groups.items()}


def _count_key(details: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(row.get(key) or "none") for row in details)
    return dict(sorted(counts.items()))


def _summarize_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [row for row in rows if row.get("correct") is not None]
    correct = [row for row in scored if row.get("correct") is True]
    return {
        "total": len(rows),
        "scored": len(scored),
        "correct": len(correct),
        "accuracy": None if not scored else len(correct) / len(scored),
        "success_count": sum(1 for row in rows if row.get("success")),
        "sql_coverage": _summarize_sql_coverage(rows),
        "pandas_sql_consistency": _summarize_pandas_sql_consistency(rows),
        "gap_counts": _summarize_gap_counts(rows),
    }


def _summarize_sql_coverage(details: list[dict[str, Any]]) -> dict[str, Any]:
    covered = [row for row in details if _sql_was_attempted(row)]
    skipped = [row for row in details if _sql_was_skipped(row)]
    failed = [row for row in covered if row.get("sql_success") is False]
    native_supported = [row for row in details if row.get("sql_support") == "native_sql"]
    return {
        "total": len(details),
        "native_supported": len(native_supported),
        "covered": len(covered),
        "skipped": len(skipped),
        "failed": len(failed),
        "coverage_rate": None if not details else len(covered) / len(details),
        "native_support_rate": None if not details else len(native_supported) / len(details),
    }


def _summarize_sql_covered_subset_accuracy(details: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [row for row in details if row.get("sql_correct") is not None]
    correct = [row for row in scored if row.get("sql_correct") is True]
    return {
        "scored": len(scored),
        "correct": len(correct),
        "accuracy": None if not scored else len(correct) / len(scored),
        "note": "Only populated when the benchmark row includes sql_correct for an independently scored SQL answer.",
    }


def _summarize_pandas_sql_consistency(details: list[dict[str, Any]]) -> dict[str, Any]:
    comparable = [row for row in details if row.get("pandas_sql_consistent") is not None]
    consistent = [row for row in comparable if row.get("pandas_sql_consistent") is True]
    return {
        "both_available": len(comparable),
        "consistent": len(consistent),
        "rate": None if not comparable else len(consistent) / len(comparable),
    }


def _summarize_gap_counts(details: list[dict[str, Any]]) -> dict[str, int]:
    keys = ("coverage_gap", "semantic_mismatch", "executor_mismatch", "format_mismatch")
    return {key: sum(1 for row in details if row.get(key) is True) for key in keys}


def _risk_bucket(rows: list[dict[str, Any]], description: str) -> dict[str, Any]:
    return {
        "count": len(rows),
        "task_ids": [row.get("task_id") for row in rows if row.get("task_id") is not None],
        "description": description,
    }


def _has_format_risk(row: dict[str, Any]) -> bool:
    if row.get("format_mismatch") is True or row.get("output_contract_passed") is False:
        return True
    flags = row.get("output_risk_flags") if isinstance(row.get("output_risk_flags"), dict) else {}
    return any(
        bool(flags.get(key))
        for key in (
            "object_or_list_leak",
            "number_format_mismatch",
            "percentage_format_mismatch",
            "comma_list_format_mismatch",
        )
    )


def _has_submission_risk(row: dict[str, Any]) -> bool:
    answer = _answer_text(row)
    validation = validate_final_answer(answer, {})
    return any(
        validation.risk_flags.get(key)
        for key in ("empty_answer", "object_or_list_leak", "debug_or_trace_leak", "sql_or_markdown_leak")
    )


def _has_trace_redaction_risk(row: dict[str, Any]) -> bool:
    flags = row.get("output_risk_flags") if isinstance(row.get("output_risk_flags"), dict) else {}
    if flags.get("debug_or_trace_leak") or flags.get("sql_or_markdown_leak"):
        return True
    validation = validate_final_answer(_answer_text(row), {})
    return bool(validation.risk_flags.get("debug_or_trace_leak") or validation.risk_flags.get("sql_or_markdown_leak"))


def _answer_text(row: dict[str, Any]) -> str:
    for key in ("agent_answer", "predicted", "answer"):
        if key in row:
            return "" if row.get(key) is None else str(row.get(key))
    return ""


def _summarize_provider_runtime(details: list[dict[str, Any]]) -> dict[str, Any]:
    provider_counts = Counter(str(row.get("provider") or "unknown") for row in details)
    latencies = [float(row["latency_ms"]) for row in details if isinstance(row.get("latency_ms"), (int, float))]
    return {
        "provider_counts": dict(sorted(provider_counts.items())),
        "latency_observed": bool(latencies),
        "latency_ms": {
            "count": len(latencies),
            "total": None if not latencies else round(sum(latencies), 3),
            "average": None if not latencies else round(sum(latencies) / len(latencies), 3),
        },
        "cost_observed": any(row.get("provider_cost") is not None for row in details),
        "note": "Cost and latency are reported only when real provider metadata is captured by the runner.",
    }


def _trace_operation(trace: Any) -> str | None:
    logic_form = getattr(trace, "logic_form", None)
    if isinstance(logic_form, dict):
        return logic_form.get("operation")
    return None


def _semantic_mismatch(verification: dict[str, Any]) -> bool:
    if verification.get("semantic_passed") is False:
        return True
    issue_text = " ".join(str(item).lower() for item in verification.get("issues") or [])
    return "semantic" in issue_text or "metric definition" in issue_text


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sql_was_attempted(row: dict[str, Any]) -> bool:
    if row.get("sql_skipped") is True:
        return False
    if row.get("sql_skipped") is False:
        return True
    return row.get("sql_success") is not None


def _sql_was_skipped(row: dict[str, Any]) -> bool:
    if row.get("sql_skipped") is True:
        return True
    if row.get("sql_skipped") is False:
        return False
    return row.get("sql_success") is None and row.get("sql_support") != "native_sql"
