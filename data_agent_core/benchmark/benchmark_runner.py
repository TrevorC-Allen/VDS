"""DABstep benchmark runner for core algorithm testing.

The runner reads expected answers only after the core agent has produced an
answer. The agent receives question and guidelines, never task_id or answer.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_agent_core.agent.single_agent import DataAnalysisAgent
from data_agent_core.benchmark.evaluator import question_scorer
from data_agent_core.benchmark.error_analysis import summarize_failures
from data_agent_core.benchmark.metrics import summarize_details
from data_agent_core.errors.error_types import BENCHMARK_EVALUATION_ERROR, VERIFICATION_FAILED
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
) -> dict[str, Any]:
    """Run the core agent against DABstep tasks."""

    dataset_root = Path(dataset_root)
    context_dir = dataset_root / "data" / "context"
    tasks_path = dataset_root / "data" / "tasks" / f"{split}.jsonl"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = output_dir / "traces"

    agent = DataAnalysisAgent(context_dir=context_dir)
    tasks = load_tasks(tasks_path, limit=limit, offset=offset)
    predictions: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    scored = 0
    correct = 0

    for task in tasks:
        response, trace = agent.analyze(
            question=task["question"],
            guidelines=task.get("guidelines", ""),
            execution_mode="auto",
        )
        trace_path = write_trace(trace, trace_dir)
        prediction = {
            "task_id": task["task_id"],
            "agent_answer": response.answer,
            "reasoning_trace": f"structured analysis plan: {response.debug.get('operation')}; trace: {trace_path}",
        }
        predictions.append(prediction)

        expected = task.get("answer")
        expected_available = expected is not None and (split == "dev" or expected != "")
        is_correct = None
        if expected_available:
            scored += 1
            is_correct = question_scorer(str(expected), str(response.answer))
            correct += int(is_correct)
        error_type = _benchmark_error_type(response, is_correct)
        details.append(
            {
                "task_id": task["task_id"],
                "question": task["question"],
                "agent_answer": response.answer,
                "expected_available": expected_available,
                "correct": is_correct,
                "operation": response.debug.get("operation"),
                "success": response.success,
                "error_type": error_type,
            }
        )

    start_number = offset + 1
    end_number = offset + len(tasks)
    predictions_path = output_dir / f"{split}_{start_number}_to_{end_number}_predictions.jsonl"
    with predictions_path.open("w") as f:
        for row in predictions:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "split": split,
        "limit": limit,
        "offset": offset,
        "task_range": [start_number, end_number],
        "total": len(tasks),
        "scored": scored,
        "correct": correct,
        "accuracy": None if scored == 0 else correct / scored,
        "predictions_path": str(predictions_path),
        "trace_dir": str(trace_dir),
        "details": details,
        "metrics": summarize_details(details),
        "error_analysis": summarize_failures(details),
    }
    report_path = output_dir / f"{split}_{start_number}_to_{end_number}_report.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    summary["report_path"] = str(report_path)
    return summary


def _benchmark_error_type(response: Any, correct: bool | None) -> str | None:
    if response.success and correct is not False:
        return None
    for error in getattr(response, "errors", []) or []:
        if isinstance(error, dict) and error.get("error_type"):
            return str(error["error_type"])
        if hasattr(error, "error_type"):
            return str(error.error_type)
    if not response.success:
        return VERIFICATION_FAILED
    if correct is False:
        return BENCHMARK_EVALUATION_ERROR
    return None


def main() -> None:
    """CLI entrypoint."""

    parser = argparse.ArgumentParser(description="Run DABstep core benchmark.")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--split", default="dev", choices=["dev", "all"])
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--output-dir", default="outputs/dabstep")
    args = parser.parse_args()

    summary = run_dabstep_benchmark(
        dataset_root=args.dataset_root,
        split=args.split,
        limit=args.limit,
        offset=args.offset,
        output_dir=args.output_dir,
    )
    printable = {key: value for key, value in summary.items() if key != "details"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
