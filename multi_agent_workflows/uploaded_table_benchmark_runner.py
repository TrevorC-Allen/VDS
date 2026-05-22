"""Offline runner for generic uploaded-table benchmark sets.

The benchmark row answer is used only after the agent response has been
produced. The workflow receives question text, guidelines, and uploaded table
content only.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from data_agent_core.benchmark.evaluator import question_scorer
from data_agent_core.benchmark.metrics import benchmark_error_type, executor_report_fields, summarize_details
from data_agent_core.benchmark.provenance import build_submission_provenance, command_line, stamp_report_provenance
from data_agent_core.output.output_contract import validate_final_answer
from data_agent_core.tracing.trace_writer import write_trace
from multi_agent_workflows.end_to_end_data_analysis_workflow import DataAnalysisMultiAgentWorkflow


def run_uploaded_table_benchmark(
    *,
    dataset_root: str | Path,
    test_set: str | Path,
    limit: int | None = None,
    offset: int = 0,
    output_dir: str | Path = "outputs/uploaded_table_benchmark",
    execution_mode: str = "auto",
    max_output_contract_retries: int = 1,
    dataset_id: str = "uploaded_table_benchmark",
) -> dict[str, Any]:
    """Run DAB-style uploaded-table questions from a JSONL file."""

    dataset_root = Path(dataset_root)
    test_set_path = Path(test_set)
    if not test_set_path.is_absolute():
        test_set_path = dataset_root / test_set_path
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = output_dir / "traces"

    rows = load_jsonl_rows(test_set_path, limit=limit, offset=offset)
    workflow_cache: dict[tuple[str, str], DataAnalysisMultiAgentWorkflow] = {}
    details: list[dict[str, Any]] = []
    predictions: list[dict[str, Any]] = []
    start = time.perf_counter()

    for row in rows:
        workflow = _workflow_for_row(
            row,
            dataset_root=dataset_root,
            dataset_id=dataset_id,
            cache=workflow_cache,
        )
        response, trace, output_validation, retry_events = _analyze_with_output_contract_retry(
            workflow,
            question=str(row["question"]),
            guidelines=str(row.get("guidelines") or ""),
            execution_mode=execution_mode,
            max_retries=max_output_contract_retries,
        )
        trace_path = write_trace(trace, trace_dir)
        target = "" if row.get("answer") is None else str(row.get("answer"))
        predicted = "" if response.answer is None else str(response.answer)
        logic_form = getattr(response, "logic_form", {}) or {}
        result_payload = getattr(response, "result", {}) or {}
        value = result_payload.get("value") if isinstance(result_payload, dict) else None
        correct = _score_expected(target, predicted, value) if target else None
        error_type = benchmark_error_type(response, correct)
        executor_fields = executor_report_fields(response, trace, error_type)
        detail = {
            "task_id": row.get("task_id"),
            "level": row.get("level"),
            "dataset": row.get("dataset"),
            "source_file": row.get("source_file"),
            "sheet": row.get("sheet"),
            "capability_area": row.get("capability_area"),
            "capability_family": _capability_family(logic_form),
            "question": row.get("question"),
            "guidelines": row.get("guidelines"),
            "expected_available": bool(target),
            "expected": target,
            "agent_answer": predicted,
            "predicted": predicted,
            "raw_value": _json_safe(value),
            "correct": correct,
            "success": response.success,
            "operation": _operation(response, logic_form),
            "error_type": error_type,
            "not_applicable_category": _not_applicable_category(response),
            "output_contract_passed": output_validation["passed"],
            "output_contract_issues": output_validation["issues"],
            "output_risk_flags": output_validation["risk_flags"],
            "output_contract_retry_count": len(retry_events),
            "output_contract_retry_events": retry_events,
            "latency_ms": getattr(trace, "latency_ms", None),
            "verification": _json_safe(response.verification),
            "warnings": response.warnings,
            "errors": _json_safe(response.errors),
            "debug": _debug_summary(response.debug),
            "trace_path": str(trace_path),
            **executor_fields,
        }
        details.append(detail)
        predictions.append(
            {
                "task_id": row.get("task_id"),
                "agent_answer": predicted,
                "reasoning_trace": (
                    f"structured uploaded-table analysis plan: {detail['operation']}; "
                    f"agent_mode: {response.debug.get('agent_mode')}; trace: {trace_path}"
                ),
            }
        )

    scored = [row for row in details if row["correct"] is not None]
    correct_count = sum(1 for row in scored if row["correct"] is True)
    start_number = offset + 1
    end_number = offset + len(rows)
    predictions_path = output_dir / f"uploaded_table_{start_number}_to_{end_number}_predictions.jsonl"
    with predictions_path.open("w") as handle:
        for row in predictions:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    elapsed_seconds = round(time.perf_counter() - start, 3)
    metrics = summarize_details(details)
    report = {
        "dataset_root": str(dataset_root),
        "test_set": str(test_set_path),
        "output_dir": str(output_dir),
        "limit": limit,
        "offset": offset,
        "max_output_contract_retries": max_output_contract_retries,
        "task_range": [start_number, end_number],
        "total": len(rows),
        "scored": len(scored),
        "correct": correct_count,
        "accuracy": None if not scored else correct_count / len(scored),
        "success_count": sum(1 for row in details if row["success"] is True),
        "by_level": _summarize_by_key(details, "level"),
        "by_capability_area": _summarize_by_key(details, "capability_area"),
        "failure_buckets": _failure_buckets(details),
        "elapsed_seconds": elapsed_seconds,
        "note": "Answers from the JSONL row were used only by this offline scorer and were not passed to the agent workflow.",
        "predictions_path": str(predictions_path),
        "metrics": metrics,
        "risk_taxonomy": metrics["risk_taxonomy"],
        "details": details,
    }
    report["provenance"] = build_submission_provenance(
        predictions_path=predictions_path,
        command=command_line(),
        benchmark="uploaded_table_benchmark",
        split=None,
        task_range=[start_number, end_number],
        elapsed_seconds=elapsed_seconds,
    )
    stamp_report_provenance(report)
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    report["report_path"] = str(report_path)
    report["predictions_path"] = str(predictions_path)
    return report


def load_jsonl_rows(path: str | Path, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
    """Load a JSONL benchmark slice."""

    rows: list[dict[str, Any]] = []
    with Path(path).open() as handle:
        for index, line in enumerate(handle):
            if index < offset:
                continue
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _workflow_for_row(
    row: dict[str, Any],
    *,
    dataset_root: Path,
    dataset_id: str,
    cache: dict[tuple[str, str], DataAnalysisMultiAgentWorkflow],
) -> DataAnalysisMultiAgentWorkflow:
    source = str(row.get("source_file") or "")
    sheet = str(row.get("sheet") or "")
    table_path = _resolve_source_path(source, dataset_root)
    if table_path is None:
        cache_key = ("csv_root", str(dataset_root))
        if cache_key not in cache:
            cache[cache_key] = DataAnalysisMultiAgentWorkflow.from_uploaded_tables(
                _load_csv_tables(dataset_root),
                dataset_id=dataset_id,
            )
        return cache[cache_key]

    cache_key = (str(table_path), sheet)
    if cache_key not in cache:
        cache[cache_key] = DataAnalysisMultiAgentWorkflow.from_uploaded_tables(
            _load_file_tables(table_path, sheet=sheet),
            dataset_id=dataset_id,
        )
    return cache[cache_key]


def _resolve_source_path(source: str, dataset_root: Path) -> Path | None:
    if not source:
        return None
    path = Path(source)
    if path.is_absolute() and path.exists():
        return path
    candidate = dataset_root / path
    if candidate.exists():
        return candidate
    return None


def _load_file_tables(path: Path, *, sheet: str = "") -> dict[str, pd.DataFrame]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        if sheet:
            return {sheet: pd.read_excel(path, sheet_name=sheet)}
        loaded = pd.read_excel(path, sheet_name=None)
        return {str(name): frame for name, frame in loaded.items()}
    if suffix == ".csv":
        return {path.stem: _read_csv(path)}
    raise ValueError(f"Unsupported uploaded table file: {path}")


def _load_csv_tables(root: Path) -> dict[str, pd.DataFrame]:
    tables = {path.stem: _read_csv(path) for path in sorted(root.glob("*.csv"))}
    if not tables:
        raise ValueError(f"No CSV tables found under {root}")
    return tables


def _read_csv(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path)


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


def _score_expected(expected: str, predicted: str, raw_value: Any) -> bool:
    if question_scorer(expected, predicted):
        return True
    expected_structured = _parse_expected_literal(expected)
    if expected_structured is None:
        return False
    return _structured_equal(expected_structured, raw_value)


def _parse_expected_literal(expected: str) -> Any:
    text = expected.strip()
    if not text or text[0] not in "[{":
        return None
    for parser in (ast.literal_eval, json.loads):
        try:
            return parser(text)
        except (SyntaxError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return None


def _structured_equal(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict) and isinstance(actual, dict):
        if set(expected) != set(actual):
            return False
        return all(_structured_equal(expected[key], actual[key]) for key in expected)
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return False
        return all(_structured_equal(left, right) for left, right in zip(expected, actual))
    if _is_number_like(expected) and _is_number_like(actual):
        return _numbers_equal(float(expected), float(actual))
    return str(expected) == str(actual)


def _is_number_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value)
            return True
        except ValueError:
            return False
    return False


def _numbers_equal(left: float, right: float) -> bool:
    if left == right:
        return True
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)


def _debug_summary(debug: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_mode": debug.get("agent_mode"),
        "workflow_mode": debug.get("workflow_mode"),
        "operation": debug.get("operation"),
        "multi_agent_roles": debug.get("multi_agent_roles"),
        "not_applicable_attribution": debug.get("not_applicable_attribution"),
        "canonical_answer": debug.get("canonical_answer"),
    }


def _operation(response: Any, logic_form: Any) -> str | None:
    debug = getattr(response, "debug", {}) or {}
    if isinstance(debug, dict) and debug.get("operation"):
        return str(debug.get("operation"))
    if isinstance(logic_form, dict) and logic_form.get("operation"):
        return str(logic_form.get("operation"))
    return None


def _capability_family(logic_form: Any) -> str | None:
    if not isinstance(logic_form, dict):
        return None
    for key in ("metric_definition", "output_contract"):
        payload = logic_form.get(key)
        if isinstance(payload, dict) and payload.get("capability_family"):
            return str(payload.get("capability_family"))
    return None


def _analyze_with_output_contract_retry(
    workflow: DataAnalysisMultiAgentWorkflow,
    *,
    question: str,
    guidelines: str,
    execution_mode: str,
    max_retries: int,
) -> tuple[Any, Any, dict[str, Any], list[dict[str, Any]]]:
    retry_events: list[dict[str, Any]] = []
    attempts = max(0, max_retries) + 1
    for attempt_index in range(attempts):
        response, trace = workflow.analyze(question=question, guidelines=guidelines, execution_mode=execution_mode)
        validation = _response_output_validation(response, guidelines)
        if validation["passed"] or not validation.get("retryable") or attempt_index >= attempts - 1:
            return response, trace, validation, retry_events
        retry_events.append(
            {
                "trigger": "output_contract_validation",
                "attempt": attempt_index + 1,
                "issues": list(validation.get("issues") or []),
                "action": "rerun_agent_once",
            }
        )
    return response, trace, validation, retry_events


def _not_applicable_category(response: Any) -> str | None:
    debug = getattr(response, "debug", {}) or {}
    if not isinstance(debug, dict):
        return None
    attribution = debug.get("not_applicable_attribution")
    if not isinstance(attribution, dict):
        return None
    return attribution.get("category")


def _response_output_validation(response: Any, guidelines: str) -> dict[str, Any]:
    debug = getattr(response, "debug", {}) or {}
    validation = debug.get("output_contract_validation") if isinstance(debug, dict) else None
    if isinstance(validation, dict):
        return {
            "passed": bool(validation.get("passed")),
            "issues": list(validation.get("issues") or []),
            "risk_flags": dict(validation.get("risk_flags") or {}),
            "retryable": bool(validation.get("retryable", bool(validation.get("issues")))),
            "answer_type": str(validation.get("answer_type") or "text"),
        }
    output_format = _response_output_format(response, guidelines)
    fallback = validate_final_answer(getattr(response, "answer", None), output_format)
    payload = fallback.to_dict()
    payload["retryable"] = False
    return payload


def _response_output_format(response: Any, guidelines: str) -> dict[str, Any]:
    logic_form = getattr(response, "logic_form", {}) or {}
    if isinstance(logic_form, dict):
        output_format = logic_form.get("output_format")
        if isinstance(output_format, dict):
            return output_format
        output_contract = logic_form.get("output_contract")
        if isinstance(output_contract, dict):
            return output_contract | {"guidelines": guidelines}
    return {"guidelines": guidelines}


def _summarize_by_key(details: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in details:
        groups.setdefault(str(row.get(key) or "unknown"), []).append(row)
    return {name: _summarize_rows(rows) for name, rows in sorted(groups.items())}


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [row for row in rows if row.get("correct") is not None]
    correct = [row for row in scored if row.get("correct") is True]
    return {
        "total": len(rows),
        "scored": len(scored),
        "correct": len(correct),
        "accuracy": None if not scored else len(correct) / len(scored),
        "success_count": sum(1 for row in rows if row.get("success") is True),
    }


def _failure_buckets(details: list[dict[str, Any]]) -> dict[str, list[str]]:
    buckets = {
        "parser_miss": [],
        "role_binding_miss": [],
        "filter_loss": [],
        "metric_mismatch": [],
        "aggregation_mismatch": [],
        "mode_top_count_miss": [],
        "ranking_share_mismatch": [],
        "format_mismatch": [],
    }
    for row in details:
        if row.get("correct") is not False:
            continue
        task_ref = str(row.get("task_id") or "")
        operation = str(row.get("operation") or "")
        capability = str(row.get("capability_area") or "")
        if row.get("output_contract_passed") is False:
            buckets["format_mismatch"].append(task_ref)
        elif "most_common" in capability or operation == "top_count":
            buckets["mode_top_count_miss"].append(task_ref)
        elif "share" in capability or "ranking" in capability:
            buckets["ranking_share_mismatch"].append(task_ref)
        elif "row_count" in capability or operation == "row_count":
            buckets["filter_loss"].append(task_ref)
        elif "metric" in capability:
            buckets["metric_mismatch"].append(task_ref)
        elif "aggregation" in operation:
            buckets["aggregation_mismatch"].append(task_ref)
        else:
            buckets["parser_miss"].append(task_ref)
    return buckets


def main() -> None:
    parser = argparse.ArgumentParser(description="Run generic uploaded-table DAB-style benchmark.")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--test-set", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--output-dir", default="outputs/uploaded_table_benchmark")
    parser.add_argument("--execution-mode", default="auto")
    parser.add_argument("--max-output-contract-retries", type=int, default=1)
    parser.add_argument("--dataset-id", default="uploaded_table_benchmark")
    args = parser.parse_args()
    report = run_uploaded_table_benchmark(
        dataset_root=args.dataset_root,
        test_set=args.test_set,
        limit=args.limit,
        offset=args.offset,
        output_dir=args.output_dir,
        execution_mode=args.execution_mode,
        max_output_contract_retries=args.max_output_contract_retries,
        dataset_id=args.dataset_id,
    )
    print(json.dumps({key: value for key, value in report.items() if key != "details"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
