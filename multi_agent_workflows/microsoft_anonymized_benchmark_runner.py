"""Offline runner for Microsoft anonymized Chinese retail questions.

Expected answers are used only after the agent response is produced. They are
never passed into the workflow, prompts, tools, executors, verifier, or trace.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from data_agent_core.benchmark.evaluator import question_scorer
from data_agent_core.tracing.trace_writer import write_trace
from multi_agent_workflows.end_to_end_data_analysis_workflow import DataAnalysisMultiAgentWorkflow


DEFAULT_TEST_SET = "VDS_DAB风格测试集_20260521/微软数据集_DAB风格问题和标准答案.jsonl"


def run_microsoft_anonymized_benchmark(
    *,
    dataset_root: str | Path,
    test_set: str | Path | None = None,
    limit: int | None = None,
    offset: int = 0,
    output_dir: str | Path = "outputs/microsoft_anonymized",
    execution_mode: str = "auto",
) -> dict[str, Any]:
    """Run Microsoft anonymized retail questions against uploaded-table workflow."""

    dataset_root = Path(dataset_root)
    test_set_path = Path(test_set) if test_set is not None else dataset_root / DEFAULT_TEST_SET
    if not test_set_path.is_absolute():
        test_set_path = dataset_root / test_set_path
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = output_dir / "traces"

    tables = load_csv_tables(dataset_root)
    workflow = DataAnalysisMultiAgentWorkflow.from_uploaded_tables(
        tables,
        dataset_id="microsoft_anonymized_desktop",
    )
    tasks = load_jsonl_tasks(test_set_path, limit=limit, offset=offset)
    details: list[dict[str, Any]] = []
    predictions: list[dict[str, Any]] = []
    start = time.perf_counter()

    for task in tasks:
        response, trace = workflow.analyze(
            question=str(task["question"]),
            guidelines=str(task.get("guidelines") or ""),
            execution_mode=execution_mode,
        )
        trace_path = write_trace(trace, trace_dir)
        expected = str(task.get("answer") or "")
        predicted = "" if response.answer is None else str(response.answer)
        correct = question_scorer(expected, predicted) if expected else None
        detail = {
            "task_id": task.get("task_id"),
            "level": task.get("level"),
            "question": task.get("question"),
            "guidelines": task.get("guidelines"),
            "expected_available": bool(expected),
            "predicted": predicted,
            "correct": correct,
            "success": response.success,
            "operation": response.debug.get("operation"),
            "verification": _json_safe(response.verification),
            "warnings": response.warnings,
            "errors": _json_safe(response.errors),
            "debug": _debug_summary(response.debug),
            "trace_path": str(trace_path),
        }
        details.append(detail)
        predictions.append(
            {
                "task_id": task.get("task_id"),
                "agent_answer": predicted,
                "reasoning_trace": (
                    f"structured analysis plan: {response.debug.get('operation')}; "
                    f"agent_mode: {response.debug.get('agent_mode')}; trace: {trace_path}"
                ),
            }
        )

    scored = [row for row in details if row["correct"] is not None]
    correct_count = sum(1 for row in scored if row["correct"] is True)
    start_number = offset + 1
    end_number = offset + len(tasks)
    predictions_path = output_dir / f"microsoft_{start_number}_to_{end_number}_predictions.jsonl"
    with predictions_path.open("w") as f:
        for row in predictions:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {
        "dataset_root": str(dataset_root),
        "test_set": str(test_set_path),
        "output_dir": str(output_dir),
        "limit": limit,
        "offset": offset,
        "task_range": [start_number, end_number],
        "total": len(tasks),
        "scored": len(scored),
        "correct": correct_count,
        "accuracy": None if not scored else correct_count / len(scored),
        "success_count": sum(1 for row in details if row["success"] is True),
        "elapsed_seconds": round(time.perf_counter() - start, 3),
        "note": "Expected answers were used only by this offline scorer and were not passed to the agent workflow.",
        "details": details,
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    report["report_path"] = str(report_path)
    report["predictions_path"] = str(predictions_path)
    return report


def load_csv_tables(dataset_root: str | Path) -> dict[str, pd.DataFrame]:
    """Load top-level CSV files as uploaded tables."""

    root = Path(dataset_root)
    tables: dict[str, pd.DataFrame] = {}
    for path in sorted(root.glob("*.csv")):
        tables[path.stem] = _read_csv(path)
    if not tables:
        raise ValueError(f"No CSV tables found under {root}")
    return tables


def load_jsonl_tasks(tasks_path: str | Path, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
    """Load a JSONL task slice."""

    tasks: list[dict[str, Any]] = []
    with Path(tasks_path).open() as f:
        for index, line in enumerate(f):
            if index < offset:
                continue
            if not line.strip():
                continue
            tasks.append(json.loads(line))
            if limit is not None and len(tasks) >= limit:
                break
    return tasks


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


def _debug_summary(debug: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_mode": debug.get("agent_mode"),
        "workflow_mode": debug.get("workflow_mode"),
        "operation": debug.get("operation"),
        "multi_agent_roles": debug.get("multi_agent_roles"),
        "not_applicable_attribution": debug.get("not_applicable_attribution"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Microsoft anonymized Chinese retail benchmark.")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--test-set", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--output-dir", default="outputs/microsoft_anonymized")
    parser.add_argument("--execution-mode", default="auto")
    args = parser.parse_args()
    report = run_microsoft_anonymized_benchmark(
        dataset_root=args.dataset_root,
        test_set=args.test_set,
        limit=args.limit,
        offset=args.offset,
        output_dir=args.output_dir,
        execution_mode=args.execution_mode,
    )
    print(json.dumps({key: value for key, value in report.items() if key != "details"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
