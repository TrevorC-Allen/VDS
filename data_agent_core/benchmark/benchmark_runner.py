"""DABstep benchmark runner for core algorithm testing.

The runner reads expected answers only after the core agent has produced an
answer. The agent receives question and guidelines, never task_id or answer.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from data_agent_core.agent.single_agent import DataAnalysisAgent
from data_agent_core.benchmark.evaluator import question_scorer
from data_agent_core.benchmark.error_analysis import summarize_failures
from data_agent_core.benchmark.metrics import benchmark_error_type, executor_report_fields, summarize_details
from data_agent_core.benchmark.provenance import build_submission_provenance, command_line, stamp_report_provenance
from data_agent_core.output.output_contract import validate_final_answer
from data_agent_core.tracing.trace_writer import write_trace


def load_tasks(tasks_path: str | Path, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
    """Load benchmark tasks from JSONL."""

    tasks: list[dict[str, Any]] = []
    with Path(tasks_path).open() as f:
        for index, line in enumerate(f):
            if index < offset:
                continue
            if line.strip():
                tasks.append(json.loads(line))
                if limit is not None and len(tasks) >= limit:
                    break
    return tasks


def run_dabstep_benchmark(
    *,
    dataset_root: str | Path,
    split: str = "dev",
    limit: int = 10,
    offset: int = 0,
    output_dir: str | Path = "outputs/dabstep",
    agent_factory: Any | None = None,
    agent_mode: str = "single_agent",
    max_output_contract_retries: int = 1,
) -> dict[str, Any]:
    """Run the core agent against DABstep tasks."""

    dataset_root = Path(dataset_root)
    context_dir = dataset_root / "data" / "context"
    tasks_path = dataset_root / "data" / "tasks" / f"{split}.jsonl"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = output_dir / "traces"

    agent = agent_factory(context_dir) if agent_factory is not None else DataAnalysisAgent(context_dir=context_dir)
    tasks = load_tasks(tasks_path, limit=limit, offset=offset)
    predictions: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    scored = 0
    correct = 0
    start = time.perf_counter()

    for task in tasks:
        response, trace, output_validation, retry_events = _analyze_with_output_contract_retry(
            agent,
            question=task["question"],
            guidelines=task.get("guidelines", ""),
            execution_mode="auto",
            max_retries=max_output_contract_retries,
        )
        trace_path = write_trace(trace, trace_dir)
        agent_answer = "" if response.answer is None else str(response.answer)
        prediction = {
            "task_id": task["task_id"],
            "agent_answer": agent_answer,
            "reasoning_trace": (
                f"structured analysis plan: {response.debug.get('operation')}; "
                f"agent_mode: {response.debug.get('agent_mode', agent_mode)}; "
                f"not_applicable: {_not_applicable_category(response)}; trace: {trace_path}"
            ),
        }
        predictions.append(prediction)

        expected = task.get("answer")
        expected_available = expected is not None and (split == "dev" or expected != "")
        is_correct = None
        if expected_available:
            scored += 1
            is_correct = question_scorer(str(expected), agent_answer)
            correct += int(is_correct)
        error_type = benchmark_error_type(response, is_correct)
        executor_fields = executor_report_fields(response, trace, error_type)
        details.append(
            {
                "task_id": task["task_id"],
                "question": task["question"],
                "agent_answer": agent_answer,
                "expected_available": expected_available,
                "correct": is_correct,
                "operation": response.debug.get("operation"),
                "not_applicable_category": _not_applicable_category(response),
                "success": response.success,
                "error_type": error_type,
                "output_contract_passed": output_validation["passed"],
                "output_contract_issues": output_validation["issues"],
                "output_risk_flags": output_validation["risk_flags"],
                "output_contract_retry_count": len(retry_events),
                "output_contract_retry_events": retry_events,
                "latency_ms": getattr(trace, "latency_ms", None),
                **executor_fields,
            }
        )

    start_number = offset + 1
    end_number = offset + len(tasks)
    predictions_path = output_dir / f"{split}_{start_number}_to_{end_number}_predictions.jsonl"
    with predictions_path.open("w") as f:
        for row in predictions:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    elapsed_seconds = round(time.perf_counter() - start, 3)
    metrics = summarize_details(details)
    summary = {
        "split": split,
        "limit": limit,
        "offset": offset,
        "task_range": [start_number, end_number],
        "total": len(tasks),
        "scored": scored,
        "correct": correct,
        "accuracy": None if scored == 0 else correct / scored,
        "success_count": metrics["success_count"],
        "unexpected_not_applicable": metrics["unexpected_not_applicable"],
        "true_unsupported": metrics["true_unsupported"],
        "not_applicable_counts": metrics["not_applicable_counts"],
        "predictions_path": str(predictions_path),
        "trace_dir": str(trace_dir),
        "agent_mode": agent_mode,
        "max_output_contract_retries": max_output_contract_retries,
        "elapsed_seconds": elapsed_seconds,
        "details": details,
        "metrics": metrics,
        "risk_taxonomy": metrics["risk_taxonomy"],
        "error_analysis": summarize_failures(details),
    }
    summary["provenance"] = build_submission_provenance(
        predictions_path=predictions_path,
        command=command_line(),
        benchmark="dabstep",
        split=split,
        task_range=[start_number, end_number],
        elapsed_seconds=elapsed_seconds,
    )
    stamp_report_provenance(summary)
    report_path = output_dir / f"{split}_{start_number}_to_{end_number}_report.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    summary["report_path"] = str(report_path)
    return summary


def _analyze_with_output_contract_retry(
    agent: Any,
    *,
    question: str,
    guidelines: str,
    execution_mode: str,
    max_retries: int,
) -> tuple[Any, Any, dict[str, Any], list[dict[str, Any]]]:
    retry_events: list[dict[str, Any]] = []
    attempts = max(0, max_retries) + 1
    for attempt_index in range(attempts):
        response, trace = agent.analyze(question=question, guidelines=guidelines, execution_mode=execution_mode)
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


def main() -> None:
    """CLI entrypoint."""

    parser = argparse.ArgumentParser(description="Run DABstep core benchmark.")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--split", default="dev", choices=["dev", "all"])
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--output-dir", default="outputs/dabstep")
    parser.add_argument("--agent-mode", default="single_agent", choices=["single_agent"])
    parser.add_argument("--max-output-contract-retries", type=int, default=1)
    args = parser.parse_args()

    summary = run_dabstep_benchmark(
        dataset_root=args.dataset_root,
        split=args.split,
        limit=args.limit,
        offset=args.offset,
        output_dir=args.output_dir,
        agent_mode=args.agent_mode,
        max_output_contract_retries=args.max_output_contract_retries,
    )
    printable = {key: value for key, value in summary.items() if key != "details"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
