"""Runner for the local VDS desktop Chinese BI standard-answer workbook.

Questions and uploaded tables are passed to the agent workflow. Standard
answers are loaded only after a response is produced for offline scoring.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

from data_agent_core.benchmark.vds_standard_scorer import score_vds_standard_answer
from data_agent_core.output.output_contract import validate_final_answer
from data_agent_core.tracing.trace_writer import write_trace
from multi_agent_workflows.end_to_end_data_analysis_workflow import DataAnalysisMultiAgentWorkflow


SHEET_FILE_MAP = {
    "订单BI问题": "QueryGPT_销售数据_单表版.xlsx",
    "学习BI问题": "QueryGPT_教育学习数据_单表版.xlsx",
    "医疗BI问题": "QueryGPT_医疗服务数据_单表版.xlsx",
    "物流BI问题": "QueryGPT_物流配送数据_单表版.xlsx",
    "SaaSBI问题": "QueryGPT_SaaS订阅数据_单表版.xlsx",
}

TABLE_NAME_MAP = {
    "订单BI问题": "销售数据",
    "学习BI问题": "教育学习数据",
    "医疗BI问题": "医疗服务数据",
    "物流BI问题": "物流配送数据",
    "SaaSBI问题": "SaaS订阅数据",
}


def run_vds_desktop_benchmark(
    *,
    question_workbook: str | Path,
    answer_workbook: str | Path,
    data_root: str | Path,
    output_dir: str | Path,
    sheet: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    execution_mode: str = "auto",
) -> dict[str, Any]:
    """Run one or more VDS desktop benchmark sheets."""

    question_workbook = Path(question_workbook)
    answer_workbook = Path(answer_workbook)
    data_root = Path(data_root)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = output_dir / "traces"
    answer_by_id = _load_standard_answers(answer_workbook)

    requested_sheets = [sheet] if sheet else list(SHEET_FILE_MAP)
    details: list[dict[str, Any]] = []
    start = time.perf_counter()
    for sheet_name in requested_sheets:
        if sheet_name not in SHEET_FILE_MAP:
            raise ValueError(f"Unsupported VDS sheet: {sheet_name}")
        questions = pd.read_excel(question_workbook, sheet_name=sheet_name).fillna("")
        rows = questions.iloc[offset:]
        if limit is not None:
            rows = rows.head(limit)
        table_path = data_root / SHEET_FILE_MAP[sheet_name]
        table = pd.read_excel(table_path)
        workflow = DataAnalysisMultiAgentWorkflow.from_uploaded_tables(
            {TABLE_NAME_MAP[sheet_name]: table},
            dataset_id="vds_desktop_standard",
        )
        for _, row in rows.iterrows():
            details.append(
                _run_one(
                    workflow,
                    row=row,
                    sheet_name=sheet_name,
                    answer_by_id=answer_by_id,
                    trace_dir=trace_dir,
                    execution_mode=execution_mode,
                )
            )

    scored = [row for row in details if row["correct"] is not None]
    correct = sum(1 for row in scored if row["correct"] is True)
    report = {
        "benchmark": "vds_desktop_standard_answer",
        "provider": "real" if _provider_is_real() else "mock",
        "question_workbook": str(question_workbook),
        "answer_workbook": str(answer_workbook),
        "answer_sheet": "五类答案汇总",
        "data_root": str(data_root),
        "sheet": sheet,
        "limit": limit,
        "offset": offset,
        "total": len(details),
        "scored": len(scored),
        "correct": correct,
        "accuracy": None if not scored else correct / len(scored),
        "success_count": sum(1 for row in details if row["success"] is True),
        "format_risk": sum(1 for row in details if row["output_risk_flags"].get("format_risk")),
        "submission_risk": sum(1 for row in details if row["output_risk_flags"].get("submission_risk")),
        "trace_redaction_risk": sum(1 for row in details if row["output_risk_flags"].get("trace_redaction_risk")),
        "elapsed_seconds": round(time.perf_counter() - start, 3),
        "note": "Standard answers were used only by this offline scorer after agent responses were produced.",
        "details": details,
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def _run_one(
    workflow: DataAnalysisMultiAgentWorkflow,
    *,
    row: pd.Series,
    sheet_name: str,
    answer_by_id: dict[str, str],
    trace_dir: Path,
    execution_mode: str,
) -> dict[str, Any]:
    task_id = str(row.get("题号") or "").strip()
    question = str(row.get("BI测试问题") or "").strip()
    guidelines = str(row.get("口径提示") or "").strip()
    start = time.perf_counter()
    response, trace = workflow.analyze(question, guidelines=guidelines, execution_mode=execution_mode)
    trace_path = write_trace(trace, trace_dir)
    raw_value = response.result.get("value") if isinstance(response.result, dict) else None
    operation = str(response.debug.get("operation") or "") if isinstance(response.debug, dict) else ""
    expected = answer_by_id.get(task_id, "")
    predicted = "" if response.answer is None else str(response.answer)
    score = score_vds_standard_answer(expected, predicted, raw_value=raw_value, operation=operation) if expected else None
    output_format = response.logic_form.get("output_format") if isinstance(response.logic_form, dict) else {}
    validation = validate_final_answer(predicted, output_format)
    return {
        "task_id": task_id,
        "sheet": sheet_name,
        "source_file": SHEET_FILE_MAP[sheet_name],
        "question": question,
        "guidelines": guidelines,
        "expected_available": bool(expected),
        "expected": expected,
        "agent_answer": predicted,
        "correct": None if score is None else score.correct,
        "scorer": None if score is None else score.scorer,
        "success": response.success,
        "operation": operation,
        "latency_ms": round((time.perf_counter() - start) * 1000, 3),
        "output_contract_passed": validation.passed,
        "output_contract_issues": validation.issues,
        "output_risk_flags": validation.risk_flags,
        "errors": response.errors,
        "trace_path": str(trace_path),
    }


def _load_standard_answers(path: Path) -> dict[str, str]:
    answers = pd.read_excel(path, sheet_name="五类答案汇总").fillna("")
    return {
        str(row["题号"]).strip(): str(row["标准GPT答案"]).strip()
        for _, row in answers.iterrows()
        if str(row.get("题号") or "").strip()
    }


def _provider_is_real() -> bool:
    import os

    return os.environ.get("VDS_LLM_PROVIDER", "mock").lower() != "mock"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local VDS desktop standard-answer benchmark.")
    parser.add_argument("--question-workbook", required=True)
    parser.add_argument("--answer-workbook", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--sheet", choices=sorted(SHEET_FILE_MAP))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--execution-mode", default="auto")
    args = parser.parse_args()
    report = run_vds_desktop_benchmark(
        question_workbook=args.question_workbook,
        answer_workbook=args.answer_workbook,
        data_root=args.data_root,
        output_dir=args.output_dir,
        sheet=args.sheet,
        limit=args.limit,
        offset=args.offset,
        execution_mode=args.execution_mode,
    )
    print(json.dumps({key: report[key] for key in ("total", "correct", "accuracy", "success_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
