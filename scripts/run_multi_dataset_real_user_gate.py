#!/usr/bin/env python3
"""Run real-user analysis gates, including recommendation answerability."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime
import json
import mimetypes
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence
import uuid

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

import scripts.run_uk_retail_random_user_gate as uk


DEFAULT_BASE_URL = "http://127.0.0.1:8876"
DATASET_STAGE_ORDER = (
    "vds_original_5",
    "dab_bm",
    "brazilian_ecommerce",
    "microsoft_anonymized",
    "nyc_taxi",
)
SAFE_RECOMMENDATION_PREFIXES = (
    "告诉我应该使用哪个字段",
    "补充时间范围",
    "上传或指定维表",
    "生成一份不覆盖原始数据",
    "确认哪些字段需要删除",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run multi-dataset real-user gates over the HTTP API.")
    parser.add_argument("--dataset-path", default="")
    parser.add_argument("--dataset-dir", default="")
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--random-questions", type=int, default=80)
    parser.add_argument("--seeds", nargs="*", type=int, default=[])
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--start-service", choices=("auto", "always", "never"), default="auto")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--service-start-timeout", type=float, default=90.0)
    parser.add_argument("--execution-mode", default="dual")
    parser.add_argument("--agent-mode", default="multi_agent")
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--skip-random", action="store_true")
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()

    dataset_path = resolve_dataset_input(args.dataset_path, args.dataset_dir)
    if not dataset_path.exists():
        raise SystemExit(f"Dataset path not found: {dataset_path}")
    if args.cycles <= 0:
        raise SystemExit("--cycles must be positive")
    if not args.skip_random and args.random_questions < 80:
        raise SystemExit("--random-questions must be at least 80 unless --skip-random is used")

    output_dir = Path(args.output_dir) if args.output_dir else Path("/tmp") / f"vds-real-user-gates-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{args.dataset_name}"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_dataset_manifest(dataset_path, dataset_name=args.dataset_name)
    write_json(output_dir / "dataset_manifest.json", manifest)

    client = uk.HttpClient(args.base_url, timeout=args.timeout)
    service_process = uk.ensure_service(client, args.base_url, output_dir, mode=args.start_service, timeout=args.service_start_timeout)
    try:
        summary = run_dataset_cycles(
            client=client,
            dataset_path=dataset_path,
            dataset_name=args.dataset_name,
            manifest=manifest,
            cycles=args.cycles,
            random_questions=args.random_questions,
            seeds=args.seeds,
            output_dir=output_dir,
            execution_mode=args.execution_mode,
            agent_mode=args.agent_mode,
            stop_on_failure=args.stop_on_failure,
            skip_random=args.skip_random,
        )
    finally:
        if service_process is not None:
            service_process.terminate()
            try:
                service_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                service_process.kill()

    if args.print_summary:
        print(f"output_dir={output_dir}")
        print(f"passed={summary['passed']}")
        print(f"cycles_passed={summary['cycles_passed']}/{summary['cycles_total']}")
        print(f"dataset_report={summary['dataset_stability_report']}")
    if not summary["passed"]:
        raise SystemExit(1)


def resolve_dataset_input(dataset_path: str, dataset_dir: str) -> Path:
    if dataset_path and dataset_dir:
        raise SystemExit("Use only one of --dataset-path or --dataset-dir.")
    if dataset_dir:
        return Path(dataset_dir).expanduser()
    if dataset_path:
        return Path(dataset_path).expanduser()
    raise SystemExit("Provide --dataset-path or --dataset-dir.")


def build_dataset_manifest(dataset_path: Path, *, dataset_name: str) -> dict[str, Any]:
    files = dataset_files(dataset_path)
    tables: list[dict[str, Any]] = []
    row_counts: dict[str, int] = {}
    columns: dict[str, list[str]] = {}
    detected_keys: dict[str, list[str]] = {}
    detected_time_columns: dict[str, list[str]] = {}
    detected_measures: dict[str, list[str]] = {}
    detected_dimensions: dict[str, list[str]] = {}
    for file_path in files:
        for table_name, frame in load_table_samples(file_path):
            table_id = table_name
            cols = [str(col) for col in frame.columns]
            tables.append({"table": table_id, "file": str(file_path), "sampled_rows": int(len(frame)), "column_count": len(cols)})
            row_counts[table_id] = int(len(frame))
            columns[table_id] = cols
            detected_keys[table_id] = [col for col in cols if looks_like_key(col)]
            detected_time_columns[table_id] = [col for col in cols if looks_like_time(col)]
            detected_measures[table_id] = [col for col in cols if looks_like_measure(col, frame)]
            detected_dimensions[table_id] = [col for col in cols if looks_like_dimension(col, frame)]
    return {
        "dataset_name": dataset_name,
        "dataset_type": "folder" if dataset_path.is_dir() else ("multi_csv" if len(files) > 1 else "single_file"),
        "dataset_path": str(dataset_path),
        "files": [str(path) for path in files],
        "tables": tables,
        "row_counts": row_counts,
        "columns": columns,
        "detected_keys": detected_keys,
        "detected_time_columns": detected_time_columns,
        "detected_measures": detected_measures,
        "detected_dimensions": detected_dimensions,
        "potential_relationships": detect_relationships(columns, detected_keys),
        "known_limitations": manifest_limitations(files, tables),
    }


def dataset_files(dataset_path: Path) -> list[Path]:
    if dataset_path.is_file():
        return [dataset_path]
    patterns = ("*.csv", "*.xlsx", "*.xls", "*.parquet")
    files: list[Path] = []
    for pattern in patterns:
        files.extend(sorted(dataset_path.glob(pattern)))
    return [path for path in files if path.is_file() and not path.name.startswith("~$")]


def load_table_samples(file_path: Path) -> list[tuple[str, pd.DataFrame]]:
    suffix = file_path.suffix.lower()
    try:
        if suffix == ".csv":
            return [(file_path.stem, pd.read_csv(file_path, nrows=500))]
        if suffix in {".xlsx", ".xls"}:
            sheets = pd.read_excel(file_path, sheet_name=None, nrows=500)
            return [(f"{file_path.stem}:{name}", frame) for name, frame in sheets.items()]
        if suffix == ".parquet":
            return [(file_path.stem, pd.read_parquet(file_path).head(500))]
    except Exception as exc:  # noqa: BLE001 - manifest should report limitations, not crash.
        return [(file_path.stem, pd.DataFrame({"manifest_error": [f"{type(exc).__name__}: {exc}"]}))]
    return []


def looks_like_key(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in ("id", "key", "code", "no", "编号", "编码", "单号", "客户", "商品"))


def looks_like_time(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in ("date", "time", "month", "year", "日期", "时间", "月份", "年度"))


def looks_like_measure(column: str, frame: pd.DataFrame) -> bool:
    lowered = column.lower()
    if any(token in lowered for token in ("amount", "sales", "revenue", "price", "qty", "quantity", "金额", "销售", "收入", "数量", "价格", "费用")):
        return True
    if re.search(r"(^|[_\W])count($|[_\W])", lowered):
        return True
    return bool(column in frame and pd.api.types.is_numeric_dtype(frame[column]))


def looks_like_dimension(column: str, frame: pd.DataFrame) -> bool:
    if column not in frame or looks_like_measure(column, frame) or looks_like_time(column):
        return False
    series = frame[column].dropna()
    return bool(len(series) and series.astype(str).nunique() <= max(50, len(series) // 2))


def detect_relationships(columns: Mapping[str, list[str]], keys: Mapping[str, list[str]]) -> list[dict[str, str]]:
    relationships: list[dict[str, str]] = []
    table_items = list(columns.items())
    for index, (left_table, left_columns) in enumerate(table_items):
        left_keys = set(keys.get(left_table) or left_columns)
        for right_table, right_columns in table_items[index + 1 :]:
            shared = sorted(left_keys.intersection(keys.get(right_table) or right_columns))
            for column in shared[:5]:
                relationships.append({"left_table": left_table, "right_table": right_table, "left_key": column, "right_key": column, "confidence": "name_match"})
    return relationships


def manifest_limitations(files: Sequence[Path], tables: Sequence[Mapping[str, Any]]) -> list[str]:
    limitations: list[str] = []
    if not files:
        limitations.append("No supported CSV, Excel, or Parquet files were found.")
    if any("manifest_error" in str(table.get("table")) for table in tables):
        limitations.append("At least one file could not be sampled for manifest generation.")
    return limitations


def run_dataset_cycles(
    *,
    client: uk.HttpClient,
    dataset_path: Path,
    dataset_name: str,
    manifest: Mapping[str, Any],
    cycles: int,
    random_questions: int,
    seeds: Sequence[int],
    output_dir: Path,
    execution_mode: str,
    agent_mode: str,
    stop_on_failure: bool,
    skip_random: bool,
) -> dict[str, Any]:
    cycle_summaries: list[dict[str, Any]] = []
    for cycle_index in range(1, cycles + 1):
        seed = int(seeds[cycle_index - 1]) if cycle_index <= len(seeds) else 2026060800 + cycle_index
        cycle = run_dataset_cycle(
            client=client,
            dataset_path=dataset_path,
            dataset_name=dataset_name,
            manifest=manifest,
            cycle_index=cycle_index,
            seed=seed,
            random_questions=random_questions,
            output_dir=output_dir,
            execution_mode=execution_mode,
            agent_mode=agent_mode,
            skip_random=skip_random,
        )
        cycle_summaries.append(cycle)
        write_cycle_report(output_dir / f"cycle_{cycle_index}_results.md", cycle)
        if stop_on_failure and not cycle["cycle_passed"]:
            write_failure_report(output_dir / "failure_report.md", dataset_name, cycle)
            break
    passed = len(cycle_summaries) == cycles and all(item["cycle_passed"] for item in cycle_summaries)
    summary = {
        "gate_name": "Multi Dataset Real User Analysis Gate",
        "dataset_name": dataset_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "passed": passed,
        "cycles_total": cycles,
        "cycles_completed": len(cycle_summaries),
        "cycles_passed": sum(1 for item in cycle_summaries if item["cycle_passed"]),
        "cycle_summaries": cycle_summaries,
    }
    report = output_dir / "dataset_stability_report.md"
    summary["dataset_stability_report"] = str(report)
    write_json(output_dir / "dataset_stability_summary.json", summary)
    write_dataset_report(report, summary)
    return summary


def run_dataset_cycle(
    *,
    client: uk.HttpClient,
    dataset_path: Path,
    dataset_name: str,
    manifest: Mapping[str, Any],
    cycle_index: int,
    seed: int,
    random_questions: int,
    output_dir: Path,
    execution_mode: str,
    agent_mode: str,
    skip_random: bool,
) -> dict[str, Any]:
    upload = upload_dataset(client, dataset_path)
    dataset_id = str(upload.body.get("dataset_id") or "")
    if upload.status_code != 200 or not dataset_id or upload.body.get("success") is False:
        return {
            "cycle": cycle_index,
            "seed": seed,
            "cycle_passed": False,
            "dataset_id": dataset_id,
            "upload": asdict(upload),
            "overview_summary": empty_summary("overview", "upload_failed"),
            "recommendation_summary": empty_recommendation_summary("upload_failed"),
            "correction_summary": empty_summary("correction", "upload_failed"),
            "random_summary": empty_summary("random", "upload_failed"),
        }

    source_cases = source_gate_cases(dataset_name, manifest)
    source_turns = run_cases_with_conversations(
        client=client,
        dataset_id=dataset_id,
        cases=source_cases,
        conversation_prefix=f"cycle{cycle_index}_source_{seed}",
        execution_mode=execution_mode,
        agent_mode=agent_mode,
    )
    overview_summary = summarize_named_turns(source_turns, gate_name="overview", min_total=len(source_cases), require_all_pass=True)
    write_json(output_dir / f"cycle_{cycle_index}_source_gate.json", {"cycle": cycle_index, "seed": seed, "dataset_id": dataset_id, "turns": source_turns, "summary": overview_summary})

    recommendation_records = run_recommendation_answerability_gate(
        client=client,
        dataset_id=dataset_id,
        source_turns=source_turns,
        execution_mode=execution_mode,
        agent_mode=agent_mode,
    )
    recommendation_summary = summarize_recommendations(recommendation_records)
    write_json(output_dir / f"cycle_{cycle_index}_recommendation_gate.json", {"cycle": cycle_index, "seed": seed, "dataset_id": dataset_id, "recommendations": recommendation_records, "summary": recommendation_summary})

    correction_turns = run_cases_with_conversations(
        client=client,
        dataset_id=dataset_id,
        cases=correction_gate_cases(dataset_name, manifest),
        conversation_prefix=f"cycle{cycle_index}_correction_{seed}",
        execution_mode=execution_mode,
        agent_mode=agent_mode,
    )
    correction_summary = summarize_named_turns(correction_turns, gate_name="correction", min_total=len(correction_turns), require_all_pass=True)
    write_json(output_dir / f"cycle_{cycle_index}_correction_gate.json", {"cycle": cycle_index, "seed": seed, "dataset_id": dataset_id, "turns": correction_turns, "summary": correction_summary})

    random_turns: list[dict[str, Any]] = []
    random_summary = empty_summary("random", "skipped")
    if not skip_random and overview_summary["passed"] and recommendation_summary["passed"] and correction_summary["passed"]:
        random_cases = random_gate_cases(dataset_name, manifest, seed=seed, total_questions=random_questions)
        random_turns = run_cases_with_conversations(
            client=client,
            dataset_id=dataset_id,
            cases=random_cases,
            conversation_prefix=f"cycle{cycle_index}_random_{seed}",
            execution_mode=execution_mode,
            agent_mode=agent_mode,
        )
        random_summary = uk.summarize_turns(random_turns, fixed=False)
    write_json(output_dir / f"cycle_{cycle_index}_random_gate.json", {"cycle": cycle_index, "seed": seed, "dataset_id": dataset_id, "turns": random_turns, "summary": random_summary})

    cycle_passed = bool(
        overview_summary["passed"]
        and recommendation_summary["passed"]
        and correction_summary["passed"]
        and (skip_random or random_summary["passed"])
    )
    return {
        "cycle": cycle_index,
        "seed": seed,
        "cycle_passed": cycle_passed,
        "dataset_id": dataset_id,
        "upload": {"status_code": upload.status_code, "elapsed_ms": upload.elapsed_ms},
        "source_results_file": str(output_dir / f"cycle_{cycle_index}_source_gate.json"),
        "recommendation_results_file": str(output_dir / f"cycle_{cycle_index}_recommendation_gate.json"),
        "correction_results_file": str(output_dir / f"cycle_{cycle_index}_correction_gate.json"),
        "random_results_file": str(output_dir / f"cycle_{cycle_index}_random_gate.json"),
        "overview_summary": overview_summary,
        "recommendation_summary": recommendation_summary,
        "correction_summary": correction_summary,
        "random_summary": random_summary,
    }


def upload_dataset(client: uk.HttpClient, dataset_path: Path) -> uk.HttpPayload:
    files = dataset_files(dataset_path)
    return client.multipart_upload("/api/data-agent/upload-batch", [("files", path, path.name) for path in files])


def source_gate_cases(dataset_name: str, manifest: Mapping[str, Any]) -> list[uk.GateQuestion]:
    if dataset_name == "uk_retail":
        return uk.fixed_gate_cases()
    overview = uk.ExpectedContract("overview", min_rows=1)
    cases = [
        uk.GateQuestion("先看一下这个数据，告诉我表、字段、行数和明显数据质量问题。", overview, "overview", "overview", 1),
    ]
    metric = first_manifest_value(manifest, "detected_measures")
    dimension = first_manifest_value(manifest, "detected_dimensions")
    time_col = first_manifest_value(manifest, "detected_time_columns")
    key_col = first_manifest_value(manifest, "detected_keys")
    if metric:
        cases.append(uk.GateQuestion(f"{metric} 总量是多少？", uk.ExpectedContract("sales formula", min_rows=1, allowed_metrics=(metric,)), "independent", "", 1))
    if dimension and metric:
        cases.append(uk.GateQuestion(f"按{dimension}看{metric}排名前5。", uk.ExpectedContract("product TopN", min_rows=1, allowed_dimensions=(dimension,), allowed_metrics=(metric,)), "independent", "", 1))
    if time_col and metric:
        cases.append(uk.GateQuestion(f"按月份看{metric}趋势。", uk.ExpectedContract("time trend", min_rows=1, allowed_metrics=(metric,), require_month_bucket=True), "independent", "", 1))
    if key_col:
        cases.append(uk.GateQuestion(f"有多少个不同的{key_col}？", uk.ExpectedContract("count distinct", min_rows=1, allowed_metrics=(key_col,)), "independent", "", 1))
    return cases


def correction_gate_cases(dataset_name: str, manifest: Mapping[str, Any]) -> list[uk.GateQuestion]:
    if dataset_name == "uk_retail":
        return [
            uk.GateQuestion("销售额最高的前5个商品是什么？销售额按 Quantity * UnitPrice 算。", uk._product_topn(5), "correction", "corr_product", 1),
            uk.GateQuestion("前5商品按月份趋势怎么看？", uk._product_month_trend(), "correction", "corr_product", 2),
            uk.GateQuestion("订单数量最多的前5个客户是谁？", uk._customer_order_count(5), "correction", "corr_customer", 1),
            uk.GateQuestion("这些客户的销售额分别是多少？销售额按 Quantity * UnitPrice 算。", uk._customer_sales(), "correction", "corr_customer", 2),
        ]
    metric = first_manifest_value(manifest, "detected_measures") or ""
    dimension = first_manifest_value(manifest, "detected_dimensions") or ""
    if metric and dimension:
        return [uk.GateQuestion(f"按{dimension}看{metric}排名前5。", uk.ExpectedContract("correction", min_rows=1, allowed_dimensions=(dimension,), allowed_metrics=(metric,)), "correction", "corr_generic", 1)]
    return [uk.GateQuestion("看一下这个数据整体情况。", uk.ExpectedContract("overview", min_rows=1), "correction", "corr_generic", 1)]


def random_gate_cases(dataset_name: str, manifest: Mapping[str, Any], *, seed: int, total_questions: int) -> list[uk.GateQuestion]:
    if dataset_name == "uk_retail":
        return uk.generate_random_gate(seed=seed, total_questions=total_questions)
    rng = random.Random(seed)
    base = source_gate_cases(dataset_name, manifest)
    cases: list[uk.GateQuestion] = []
    while len(cases) < total_questions:
        case = rng.choice(base)
        cases.append(uk.GateQuestion(case.question, case.expected, "random", f"random_{len(cases) // 6}" if len(cases) >= 30 else "", len(cases) + 1))
    return cases


def run_cases_with_conversations(
    *,
    client: uk.HttpClient,
    dataset_id: str,
    cases: Sequence[uk.GateQuestion],
    conversation_prefix: str,
    execution_mode: str,
    agent_mode: str,
) -> list[dict[str, Any]]:
    conversation_ids: dict[str, str] = {}
    turns: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        conversation_id = ""
        if case.conversation_key:
            conversation_id = conversation_ids.setdefault(case.conversation_key, f"conv_{conversation_prefix}_{case.conversation_key}_{uuid.uuid4().hex[:8]}")
        http = ask_question(client, dataset_id, case.question, conversation_id=conversation_id, execution_mode=execution_mode, agent_mode=agent_mode)
        response = http.body if isinstance(http.body, dict) else {}
        if case.conversation_key and response.get("conversation_id"):
            conversation_ids[case.conversation_key] = str(response.get("conversation_id"))
        score = uk.score_response(question=case.question, response=response, http_status=http.status_code, expected=case.expected, http_error=http.error)
        turns.append(turn_record(index=index, case=case, http=http, response=response, score=score, conversation_id=str(response.get("conversation_id") or conversation_id)))
    return turns


def ask_question(
    client: uk.HttpClient,
    dataset_id: str,
    question: str,
    *,
    conversation_id: str,
    execution_mode: str,
    agent_mode: str,
) -> uk.HttpPayload:
    return client.post_json(
        "/api/data-agent/message",
        {
            "dataset_id": dataset_id,
            "conversation_id": conversation_id,
            "question": question,
            "execution_mode": execution_mode,
            "agent_mode": agent_mode,
        },
    )


def turn_record(
    *,
    index: int,
    case: uk.GateQuestion,
    http: uk.HttpPayload,
    response: Mapping[str, Any],
    score: uk.TurnScore,
    conversation_id: str,
) -> dict[str, Any]:
    return {
        "index": index,
        "gate": case.gate,
        "conversation_key": case.conversation_key,
        "conversation_id": conversation_id,
        "turn_index": case.turn_index,
        "question": case.question,
        "expected": asdict(case.expected),
        "http_status": http.status_code,
        "elapsed_ms": http.elapsed_ms,
        "success": response.get("success"),
        "semantic_status": uk._semantic_status(response),
        "score": score.score,
        "hard_reasons": score.hard_reasons,
        "soft_reasons": score.soft_reasons,
        "answer_summary": uk._answer_summary(response),
        "contract": uk._compact_contract(response),
        "execution_spec": uk._compact_mapping((response.get("debug") or {}).get("execution_spec") if isinstance(response.get("debug"), Mapping) else {}),
        "execution_trace": uk._compact_mapping((response.get("debug") or {}).get("execution_trace") if isinstance(response.get("debug"), Mapping) else {}),
        "semantic_issues": uk._semantic_issues(response),
        "result_columns": uk._result_columns(response),
        "result_row_count": len(uk._result_rows(response)),
        "recommended_questions": collect_recommended_questions(response),
        "response": dict(response),
    }


def collect_recommended_questions(response: Mapping[str, Any]) -> list[str]:
    candidates: list[str] = []
    insight = response.get("insight") if isinstance(response.get("insight"), Mapping) else {}
    for key in ("next_questions", "follow_up_questions", "recommended_questions"):
        values = insight.get(key)
        if isinstance(values, list):
            candidates.extend(str(item) for item in values)
    sections = response.get("structured_answer_sections") if isinstance(response.get("structured_answer_sections"), Mapping) else {}
    for key in ("next_questions", "下一步可继续分析"):
        values = sections.get(key)
        if isinstance(values, list):
            candidates.extend(str(item) for item in values)
    debug = response.get("debug") if isinstance(response.get("debug"), Mapping) else {}
    for key in ("suggested_questions", "next_questions", "recommended_questions"):
        values = debug.get(key)
        if isinstance(values, list):
            candidates.extend(str(item) for item in values)
    result: list[str] = []
    for item in candidates:
        text = normalize_question(item)
        if not text or text in result:
            continue
        if any(text.startswith(prefix) for prefix in SAFE_RECOMMENDATION_PREFIXES):
            continue
        result.append(text)
        if len(result) >= 3:
            break
    return result


def normalize_question(value: str) -> str:
    text = str(value or "").strip().strip("。；;")
    text = re.sub(r"^\d+[.、]\s*", "", text)
    return text


def run_recommendation_answerability_gate(
    *,
    client: uk.HttpClient,
    dataset_id: str,
    source_turns: Sequence[Mapping[str, Any]],
    execution_mode: str,
    agent_mode: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source_index, source in enumerate(source_turns, start=1):
        expected = source.get("expected") if isinstance(source.get("expected"), Mapping) else {}
        source_answerable = bool(expected.get("answerable", True)) and not bool(expected.get("safe_failure_expected"))
        source_passed = source.get("score") == "pass" and source.get("success") is True
        if not source_answerable or not source_passed:
            continue
        questions = list(source.get("recommended_questions") or [])
        if not questions:
            records.append(
                {
                    "source_index": source_index,
                    "source_question": source.get("question"),
                    "source_answer_summary": source.get("answer_summary"),
                    "recommended_question": "",
                    "score": "hard_fail",
                    "hard_reasons": ["missing_recommended_question"],
                    "soft_reasons": [],
                    "failure_layer": "recommendation_generation",
                }
            )
            continue
        for rec_index, question in enumerate(questions, start=1):
            expected_contract = infer_recommendation_expected(question)
            http = ask_question(
                client,
                dataset_id,
                question,
                conversation_id=str(source.get("conversation_id") or ""),
                execution_mode=execution_mode,
                agent_mode=agent_mode,
            )
            response = http.body if isinstance(http.body, dict) else {}
            score = uk.score_response(question=question, response=response, http_status=http.status_code, expected=expected_contract, http_error=http.error)
            records.append(
                {
                    "source_index": source_index,
                    "recommendation_index": rec_index,
                    "source_question": source.get("question"),
                    "source_answer_summary": source.get("answer_summary"),
                    "recommended_question": question,
                    "recommended_question_result": {
                        "http_status": http.status_code,
                        "elapsed_ms": http.elapsed_ms,
                        "success": response.get("success"),
                        "semantic_status": uk._semantic_status(response),
                        "answer_summary": uk._answer_summary(response),
                        "contract": uk._compact_contract(response),
                        "execution_trace": uk._compact_mapping((response.get("debug") or {}).get("execution_trace") if isinstance(response.get("debug"), Mapping) else {}),
                        "result_columns": uk._result_columns(response),
                        "result_row_count": len(uk._result_rows(response)),
                    },
                    "score": score.score,
                    "hard_reasons": score.hard_reasons,
                    "soft_reasons": score.soft_reasons,
                    "failure_layer": failure_layer(score),
                    "response": response,
                }
            )
    return records


def infer_recommendation_expected(question: str) -> uk.ExpectedContract:
    text = str(question or "").lower().replace(" ", "")
    if any(token in text for token in ("差多少", "相差", "差距", "第一名和第二名", "第二名比第一名")):
        if any(token in text for token in ("数量", "退货", "订单", "quantity", "count")):
            return uk.ExpectedContract("follow-up gap", min_rows=2)
        return uk._gap()
    if any(token in text for token in ("占比", "占总", "比例", "share", "contribution")):
        return uk._country_share(min_rows=1) if "国家" in text or "country" in text else uk.ExpectedContract("share", min_rows=1, require_share=True)
    if any(token in text for token in ("月份", "按月", "趋势", "最活跃", "trend")):
        return uk.ExpectedContract("time trend", min_rows=1, require_month_bucket=True)
    if any(token in text for token in ("国家", "country")):
        return uk._country_sales_drilldown()
    if any(token in text for token in ("客户", "customer")) and any(token in text for token in ("销售额", "sales", "revenue")):
        return uk._customer_sales()
    if any(token in text for token in ("商品", "产品", "stockcode", "description")):
        if any(token in text for token in ("销售额", "sales", "revenue")):
            return uk._product_topn(5)
        if any(token in text for token in ("数量", "退货", "quantity")):
            return uk.ExpectedContract("product TopN", min_rows=1, allowed_dimensions=("Description", "StockCode"), allowed_metrics=("Quantity",))
        return uk.ExpectedContract("follow-up drilldown", min_rows=1, allowed_dimensions=("Description", "StockCode"))
    return uk.ExpectedContract("recommendation", min_rows=0)


def failure_layer(score: uk.TurnScore) -> str:
    reasons = score.hard_reasons + score.soft_reasons
    joined = " ".join(reasons)
    if "http" in joined:
        return "http"
    if "semantic" in joined or "false_semantic" in joined:
        return "semantic_verifier"
    if "required_columns" in joined or "dimension" in joined or "metric" in joined:
        return "execution_contract"
    if "missing_recommended_question" in joined:
        return "recommendation_generation"
    return "answerability"


def summarize_recommendations(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(records)
    pass_count = sum(1 for item in records if item.get("score") == "pass")
    soft_count = sum(1 for item in records if item.get("score") == "soft_fail")
    hard_count = sum(1 for item in records if item.get("score") == "hard_fail")
    http_5xx = sum(1 for item in records if int(((item.get("recommended_question_result") or {}).get("http_status") or 0)) >= 500)
    false_semantic_passed = sum(1 for item in records if any("false_semantic_passed" in str(reason) or "safe_failure_marked_passed" in str(reason) for reason in item.get("hard_reasons") or []))
    passed = bool(total > 0 and pass_count == total and hard_count == 0 and soft_count == 0 and http_5xx == 0 and false_semantic_passed == 0)
    return {
        "gate": "recommendation_answerability",
        "passed": passed,
        "total": total,
        "pass": pass_count,
        "soft_fail": soft_count,
        "hard_fail": hard_count,
        "answerability_rate": pass_count / total if total else 0.0,
        "http_5xx": http_5xx,
        "false_semantic_passed": false_semantic_passed,
        "failed_questions": [
            {
                "source_question": item.get("source_question"),
                "recommended_question": item.get("recommended_question"),
                "score": item.get("score"),
                "hard_reasons": item.get("hard_reasons"),
                "soft_reasons": item.get("soft_reasons"),
                "failure_layer": item.get("failure_layer"),
            }
            for item in records
            if item.get("score") != "pass"
        ],
    }


def summarize_named_turns(turns: Sequence[Mapping[str, Any]], *, gate_name: str, min_total: int, require_all_pass: bool) -> dict[str, Any]:
    summary = uk.summarize_turns(turns, fixed=False)
    summary["gate"] = gate_name
    if require_all_pass:
        summary["passed"] = bool(len(turns) >= min_total and summary["pass"] == len(turns) and summary["hard_fail"] == 0 and summary["http_5xx"] == 0 and summary["false_semantic_passed"] == 0)
    return summary


def empty_summary(gate: str, reason: str) -> dict[str, Any]:
    summary = uk._empty_gate_summary(gate, [reason])
    summary["gate"] = gate
    return summary


def empty_recommendation_summary(reason: str) -> dict[str, Any]:
    return {
        "gate": "recommendation_answerability",
        "passed": False,
        "total": 0,
        "pass": 0,
        "soft_fail": 0,
        "hard_fail": 1,
        "answerability_rate": 0.0,
        "http_5xx": 0,
        "false_semantic_passed": 0,
        "failed_questions": [{"recommended_question": "", "score": "hard_fail", "hard_reasons": [reason], "soft_reasons": []}],
    }


def first_manifest_value(manifest: Mapping[str, Any], key: str) -> str:
    values_by_table = manifest.get(key) if isinstance(manifest.get(key), Mapping) else {}
    for values in values_by_table.values():
        if isinstance(values, list) and values:
            return str(values[0])
    return ""


def write_cycle_report(path: Path, cycle: Mapping[str, Any]) -> None:
    lines = [
        f"# Cycle {cycle['cycle']} Results",
        "",
        f"- seed: `{cycle['seed']}`",
        f"- dataset_id: `{cycle.get('dataset_id') or ''}`",
        f"- cycle_passed: `{cycle['cycle_passed']}`",
        "",
    ]
    for key, title in (
        ("overview_summary", "Overview / Source Gate"),
        ("recommendation_summary", "Recommendation Answerability Gate"),
        ("correction_summary", "Correction Gate"),
        ("random_summary", "Random Gate"),
    ):
        lines.append(f"## {title}")
        lines.extend(summary_lines(cycle.get(key) or {}))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_dataset_report(path: Path, summary: Mapping[str, Any]) -> None:
    lines = [
        f"# {summary['dataset_name']} Real User Stability Gate",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- passed: `{summary['passed']}`",
        f"- cycles: `{summary['cycles_passed']}/{summary['cycles_total']}`",
        "",
    ]
    for cycle in summary.get("cycle_summaries") or []:
        lines.append(f"## Cycle {cycle['cycle']}")
        lines.append(f"- cycle_passed: `{cycle['cycle_passed']}`")
        for key in ("overview_summary", "recommendation_summary", "correction_summary", "random_summary"):
            lines.append(f"### {key}")
            lines.extend(summary_lines(cycle.get(key) or {}))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def summary_lines(summary: Mapping[str, Any]) -> list[str]:
    return [
        f"- passed: `{summary.get('passed')}`",
        f"- total/pass/soft/hard: `{summary.get('total')}/{summary.get('pass')}/{summary.get('soft_fail')}/{summary.get('hard_fail')}`",
        f"- pass_rate: `{float(summary.get('pass_rate') or summary.get('answerability_rate') or 0):.3f}`",
        f"- http_5xx: `{summary.get('http_5xx')}`",
        f"- false_semantic_passed: `{summary.get('false_semantic_passed')}`",
    ]


def write_failure_report(path: Path, dataset_name: str, cycle: Mapping[str, Any]) -> None:
    failures: list[dict[str, Any]] = []
    for key in ("overview_summary", "recommendation_summary", "correction_summary", "random_summary"):
        for item in (cycle.get(key) or {}).get("failed_questions") or []:
            failures.append({"gate": key, **item})
    lines = [
        f"# Failure Report: {dataset_name}",
        "",
        f"- failed_cycle: `{cycle.get('cycle')}`",
        f"- dataset_id: `{cycle.get('dataset_id') or ''}`",
        "",
        "## Failures",
    ]
    for item in failures[:50]:
        lines.append(f"- `{item.get('gate')}` `{item.get('score')}` {item.get('question') or item.get('recommended_question') or ''} | {item.get('hard_reasons') or item.get('soft_reasons')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
