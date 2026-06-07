#!/usr/bin/env python3
"""Run the UK Retail frontend manual gate through the real HTTP API."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence
import uuid

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.run_multi_dataset_real_user_gate import collect_recommended_questions, infer_recommendation_expected
from scripts.run_uk_retail_random_user_gate import (
    DEFAULT_DATASET,
    HttpClient,
    HttpPayload,
    PASS_STATUSES,
    _answer_summary,
    _execution_trace,
    _has_sales_formula,
    _logic_params,
    _result_columns,
    _result_rows,
    _semantic_status,
    ensure_service,
    score_response,
    upload_dataset,
)


DEFAULT_BASE_URL = "http://127.0.0.1:8879"


@dataclass(frozen=True)
class ManualCase:
    gate: str
    question: str
    expected: str
    conversation_key: str = ""


def frontend_manual_cases() -> list[ManualCase]:
    return [
        ManualCase("A", "看一下整体表格数据", "overview", "a"),
        ManualCase("A", "按 Country 看 Quantity 的 Top 排名", "country_quantity_topn", "a"),
        ManualCase("A", "这些国家差值是多少", "country_quantity_gap", "a"),
        ManualCase("A", "把排名靠前的Country按InvoiceDate继续下钻", "country_invoice_date_month_drilldown", "a"),
        ManualCase("A", "比较 Top 结果之间的Quantity差距有多大", "country_quantity_gap", "a"),
        ManualCase("A", "销售额最大的店家", "store_safe_failure", "a"),
        ManualCase("B", "提供invoice no 536365的所有数据航", "invoice_lookup", ""),
        ManualCase("B", "提供 InvoiceNo 为 536365 的所有数据行", "invoice_lookup", ""),
        ManualCase("B", "show all rows for invoice no 536365", "invoice_lookup", ""),
        ManualCase("C", "提供custom id为17850的消费总数", "customer_spend", ""),
        ManualCase("C", "提供 customer id 为 17850 的消费总额", "customer_spend", ""),
        ManualCase("C", "CustomerID=17850 的销售额是多少？", "customer_spend", "c_follow"),
        ManualCase("C", "这个客户一共消费多少？", "customer_spend", "c_follow"),
    ]


def run_cycle(
    *,
    client: HttpClient,
    dataset_id: str,
    cycle_index: int,
    execution_mode: str,
    agent_mode: str,
) -> dict[str, Any]:
    conversations: dict[str, str] = {}
    turns: list[dict[str, Any]] = []
    responses_for_recommendations: list[tuple[int, str, Mapping[str, Any]]] = []
    for index, case in enumerate(frontend_manual_cases(), start=1):
        conversation_id = ""
        if case.conversation_key:
            conversation_id = conversations.setdefault(case.conversation_key, f"manual_{cycle_index}_{case.conversation_key}_{uuid.uuid4().hex[:8]}")
        http, turn = _ask_and_score(
            client=client,
            dataset_id=dataset_id,
            question=case.question,
            conversation_id=conversation_id,
            execution_mode=execution_mode,
            agent_mode=agent_mode,
            expected=case.expected,
            gate=case.gate,
            index=index,
        )
        response = http.body if isinstance(http.body, dict) else {}
        if case.conversation_key and response.get("conversation_id"):
            conversations[case.conversation_key] = str(response.get("conversation_id"))
        responses_for_recommendations.append((index, conversations.get(case.conversation_key, conversation_id), response))
        turns.append(turn)

    recommendation_turns = _run_recommendation_gate(
        client=client,
        dataset_id=dataset_id,
        source_responses=responses_for_recommendations,
        execution_mode=execution_mode,
        agent_mode=agent_mode,
        cycle_index=cycle_index,
    )
    summary = summarize_manual_turns(turns, recommendation_turns)
    return {
        "cycle": cycle_index,
        "dataset_id": dataset_id,
        "turns": turns,
        "recommendation_turns": recommendation_turns,
        "summary": summary,
        "cycle_passed": bool(summary["passed"]),
    }


def _ask_and_score(
    *,
    client: HttpClient,
    dataset_id: str,
    question: str,
    conversation_id: str,
    execution_mode: str,
    agent_mode: str,
    expected: str,
    gate: str,
    index: int,
) -> tuple[HttpPayload, dict[str, Any]]:
    payload = {
        "dataset_id": dataset_id,
        "conversation_id": conversation_id,
        "question": question,
        "execution_mode": execution_mode,
        "agent_mode": agent_mode,
    }
    http = client.post_json("/api/data-agent/message", payload)
    response = http.body if isinstance(http.body, dict) else {}
    hard_reasons = _score_manual_response(question=question, response=response, http_status=http.status_code, expected=expected, http_error=http.error)
    return http, _turn_record(
        index=index,
        gate=gate,
        question=question,
        expected=expected,
        http=http,
        response=response,
        hard_reasons=hard_reasons,
        conversation_id=str(response.get("conversation_id") or conversation_id or ""),
    )


def _run_recommendation_gate(
    *,
    client: HttpClient,
    dataset_id: str,
    source_responses: Sequence[tuple[int, str, Mapping[str, Any]]],
    execution_mode: str,
    agent_mode: str,
    cycle_index: int,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    candidates: list[tuple[int, str, str]] = []
    for source_index, conversation_id, response in source_responses:
        for question in collect_recommended_questions(response):
            normalized = " ".join(str(question or "").split())
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            candidates.append((source_index, conversation_id, normalized))
    turns: list[dict[str, Any]] = []
    for index, (source_index, conversation_id, question) in enumerate(candidates, start=1):
        payload = {
            "dataset_id": dataset_id,
            "conversation_id": conversation_id or f"manual_{cycle_index}_recommendation_{index}_{uuid.uuid4().hex[:8]}",
            "question": question,
            "execution_mode": execution_mode,
            "agent_mode": agent_mode,
        }
        http = client.post_json("/api/data-agent/message", payload)
        response = http.body if isinstance(http.body, dict) else {}
        manual_expected = _manual_recommendation_expected(question)
        if manual_expected:
            hard_reasons = _score_manual_response(
                question=question,
                response=response,
                http_status=http.status_code,
                expected=manual_expected,
                http_error=http.error,
            )
            score_name = "hard_fail" if hard_reasons else "pass"
            expected_label = f"recommendation:{manual_expected}"
            soft_reasons: list[str] = []
        else:
            expected = infer_recommendation_expected(question)
            score = score_response(question=question, response=response, http_status=http.status_code, expected=expected, http_error=http.error)
            hard_reasons = list(score.hard_reasons) if score.score == "hard_fail" else []
            soft_reasons = list(score.soft_reasons) if score.score == "soft_fail" else []
            score_name = score.score
            expected_label = f"recommendation:{expected.category}"
        turns.append(
            _turn_record(
                index=index,
                gate="D",
                question=question,
                expected=expected_label,
                http=http,
                response=response,
                hard_reasons=hard_reasons,
                soft_reasons=soft_reasons,
                conversation_id=str(response.get("conversation_id") or payload["conversation_id"]),
                extra={"source_turn_index": source_index, "score": score_name},
            )
        )
    return turns


def _manual_recommendation_expected(question: str) -> str:
    text = str(question or "")
    lowered = text.lower()
    if "quantity" in lowered and "top" in lowered and (
        any(token in text for token in ("差", "差距", "差值", "相差")) or "gap" in lowered
    ):
        return "country_quantity_gap"
    if "country" in lowered and "quantity" in lowered:
        if any(token in text for token in ("差", "差距", "差值", "相差")) or "gap" in lowered:
            return "country_quantity_gap"
        if any(token in lowered for token in ("invoice", "date", "month")) or any(token in text for token in ("月份", "按月", "时间", "日期")):
            return "country_invoice_date_month_drilldown"
        return "country_quantity_topn"
    if "invoice" in lowered and re.search(r"\b536365\b", lowered):
        return "invoice_lookup"
    plural_customer_reference = any(token in text for token in ("这些客户", "这几个客户", "这5个客户", "这五个客户")) or any(
        token in lowered for token in ("these customers", "those customers")
    )
    if not plural_customer_reference and (
        any(token in lowered for token in ("customer", "custom", "cust", "customerid")) or any(token in text for token in ("客户", "顾客"))
    ):
        if any(token in lowered for token in ("spend", "sales", "amount")) or any(token in text for token in ("消费", "销售额", "消费总额", "消费总数")):
            return "customer_spend"
    return ""


def _score_manual_response(*, question: str, response: Mapping[str, Any], http_status: int, expected: str, http_error: str = "") -> list[str]:
    hard: list[str] = []
    if http_status == 0:
        hard.append(f"http_unavailable:{http_error[:120]}")
    elif http_status >= 500:
        hard.append(f"http_5xx:{http_status}")
    elif http_status != 200:
        hard.append(f"http_non_200:{http_status}")

    answer = str(response.get("answer") or "")
    status = _semantic_status(response)
    rows = _result_rows(response)
    columns = _result_columns(response)
    params = _logic_params(response)
    trace = _execution_trace(response)
    success = response.get("success") is True

    if response.get("success") is False and status in PASS_STATUSES:
        hard.append("false_semantic_passed_success_false")
    if _looks_blocked(answer) and status in PASS_STATUSES:
        hard.append("false_semantic_passed_blocked_answer")

    if expected == "store_safe_failure":
        if status in PASS_STATUSES:
            hard.append("store_missing_dimension_marked_passed")
        if success and rows:
            hard.append("store_missing_dimension_fabricated_rows")
        if _dimension_is(params, trace, columns, "InvoiceNo"):
            hard.append("store_missing_dimension_fell_back_to_invoice_no")
        return hard

    if not success:
        hard.append("answerable_success_false")
    if status not in PASS_STATUSES:
        hard.append(f"semantic_not_passed:{status}")

    if expected == "overview":
        return hard
    if expected == "country_quantity_topn":
        _require_columns(columns, ("Country", "Quantity"), hard)
        _require_min_rows(rows, 3, hard)
        _require_dimension(params, trace, columns, ("Country",), hard)
        _require_metric(params, trace, columns, ("Quantity",), hard)
        _forbid_dimension(params, trace, columns, "InvoiceNo", hard)
    elif expected == "country_quantity_gap":
        _require_dimension(params, trace, columns, ("Country",), hard)
        _require_metric(params, trace, columns, ("Quantity",), hard)
        _forbid_dimension(params, trace, columns, "InvoiceNo", hard)
        if not _has_gap_evidence(response):
            hard.append("gap_evidence_missing")
    elif expected == "country_invoice_date_month_drilldown":
        _require_columns(columns, ("month", "Country", "Quantity"), hard)
        _require_dimension(params, trace, columns, ("month",), hard)
        _require_metric(params, trace, columns, ("Quantity",), hard)
        if str(params.get("series_dimension") or "") != "Country":
            hard.append("series_dimension_not_country")
        if str(params.get("time_column") or trace.get("time_column") or "") != "InvoiceDate":
            hard.append("time_column_not_invoice_date")
        if str(params.get("time_bucket") or trace.get("time_grain") or "") != "month":
            hard.append("month_bucket_missing")
        if not _trace_has_filter(trace, "Country"):
            hard.append("country_filter_missing")
        _forbid_dimension(params, trace, columns, "InvoiceNo", hard)
    elif expected == "invoice_lookup":
        _require_min_rows(rows, 1, hard)
        bad = [row.get("InvoiceNo") for row in rows if not _same_filter_value(row.get("InvoiceNo"), "536365")]
        if bad:
            hard.append("invoice_filter_mismatch:" + ",".join(str(value) for value in bad[:5]))
        if not _trace_has_filter(trace, "InvoiceNo", "536365"):
            hard.append("invoice_filter_trace_missing")
    elif expected == "customer_spend":
        _require_metric(params, trace, columns, ("Sales",), hard)
        if not _has_sales_formula(params, trace, rows):
            hard.append("sales_formula_missing")
        if not _trace_has_filter(trace, "CustomerID", "17850"):
            hard.append("customer_filter_trace_missing")
        metric = str(params.get("metric") or "")
        if metric == "Quantity" or ("Quantity" in columns and "Sales" not in columns):
            hard.append("customer_spend_returned_quantity_not_sales")
    else:
        hard.append(f"unknown_expected:{expected}")
    return hard


def summarize_manual_turns(turns: Sequence[Mapping[str, Any]], recommendation_turns: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    all_turns = [*turns, *recommendation_turns]
    total = len(all_turns)
    hard_fail = sum(1 for turn in all_turns if turn.get("score") == "hard_fail")
    soft_fail = sum(1 for turn in all_turns if turn.get("score") == "soft_fail")
    pass_count = sum(1 for turn in all_turns if turn.get("score") == "pass")
    http_5xx = sum(1 for turn in all_turns if int(turn.get("http_status") or 0) >= 500)
    false_semantic_passed = sum(
        1
        for turn in all_turns
        if any("false_semantic_passed" in str(reason) or "marked_passed" in str(reason) for reason in turn.get("hard_reasons") or [])
    )
    by_gate: dict[str, Counter[str]] = defaultdict(Counter)
    for turn in all_turns:
        by_gate[str(turn.get("gate") or "unknown")][str(turn.get("score") or "unknown")] += 1
    recommendation_total = len(recommendation_turns)
    recommendation_pass = sum(1 for turn in recommendation_turns if turn.get("score") == "pass")
    return {
        "passed": hard_fail == 0 and soft_fail == 0 and http_5xx == 0 and false_semantic_passed == 0,
        "total": total,
        "pass": pass_count,
        "soft_fail": soft_fail,
        "hard_fail": hard_fail,
        "http_5xx": http_5xx,
        "false_semantic_passed": false_semantic_passed,
        "by_gate": {gate: dict(counter) for gate, counter in sorted(by_gate.items())},
        "recommendation_total": recommendation_total,
        "recommendation_pass": recommendation_pass,
        "recommendation_fail": recommendation_total - recommendation_pass,
        "failed_questions": [
            {
                "gate": turn.get("gate"),
                "question": turn.get("question"),
                "score": turn.get("score"),
                "hard_reasons": turn.get("hard_reasons"),
                "soft_reasons": turn.get("soft_reasons"),
                "semantic_status": turn.get("semantic_status"),
                "answer_summary": turn.get("answer_summary"),
            }
            for turn in all_turns
            if turn.get("score") != "pass"
        ],
    }


def _turn_record(
    *,
    index: int,
    gate: str,
    question: str,
    expected: str,
    http: HttpPayload,
    response: Mapping[str, Any],
    hard_reasons: list[str],
    soft_reasons: list[str] | None = None,
    conversation_id: str = "",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    soft = list(soft_reasons or [])
    score = "hard_fail" if hard_reasons else "soft_fail" if soft else "pass"
    record = {
        "index": index,
        "gate": gate,
        "question": question,
        "expected": expected,
        "conversation_id": conversation_id,
        "http_status": http.status_code,
        "elapsed_ms": http.elapsed_ms,
        "success": response.get("success"),
        "semantic_status": _semantic_status(response),
        "score": score,
        "hard_reasons": hard_reasons,
        "soft_reasons": soft,
        "answer_summary": _answer_summary(response),
        "result_columns": _result_columns(response),
        "result_row_count": len(_result_rows(response)),
        "logic_params": _logic_params(response),
        "execution_trace": _execution_trace(response),
        "response": response,
    }
    if extra:
        record.update(dict(extra))
    return record


def _require_columns(columns: Sequence[str], required: Sequence[str], hard: list[str]) -> None:
    missing = [column for column in required if not any(str(actual).lower() == str(column).lower() for actual in columns)]
    if missing:
        hard.append("required_columns_missing:" + ",".join(missing))


def _require_min_rows(rows: Sequence[Mapping[str, Any]], minimum: int, hard: list[str]) -> None:
    if len(rows) < minimum:
        hard.append(f"row_count_below_min:{len(rows)}<{minimum}")


def _require_dimension(params: Mapping[str, Any], trace: Mapping[str, Any], columns: Sequence[str], allowed: Sequence[str], hard: list[str]) -> None:
    if not any(_dimension_is(params, trace, columns, dimension) for dimension in allowed):
        hard.append("dimension_mismatch:expected_one_of=" + ",".join(allowed))


def _require_metric(params: Mapping[str, Any], trace: Mapping[str, Any], columns: Sequence[str], allowed: Sequence[str], hard: list[str]) -> None:
    values = {str(params.get("metric") or ""), str(params.get("ranking_metric") or ""), str(params.get("share_metric") or "")}
    values.update(str(item) for item in trace.get("metric_columns") or [] if item)
    values.update(str(column) for column in columns)
    if not any(value.lower() == expected.lower() for value in values for expected in allowed):
        hard.append("metric_mismatch:expected_one_of=" + ",".join(allowed))


def _forbid_dimension(params: Mapping[str, Any], trace: Mapping[str, Any], columns: Sequence[str], forbidden: str, hard: list[str]) -> None:
    if _dimension_is(params, trace, columns, forbidden):
        hard.append(f"forbidden_dimension_present:{forbidden}")


def _dimension_is(params: Mapping[str, Any], trace: Mapping[str, Any], columns: Sequence[str], expected: str) -> bool:
    values = {str(params.get("dimension") or ""), str(params.get("time_dimension") or ""), str(params.get("group_by") or "")}
    values.update(str(item) for item in trace.get("groupby_columns") or [] if item)
    values.update(str(column) for column in columns)
    return any(value.lower() == expected.lower() for value in values)


def _trace_has_filter(trace: Mapping[str, Any], column: str, value: str | None = None) -> bool:
    for item in trace.get("filters_applied") or []:
        if not isinstance(item, Mapping) or str(item.get("column") or "").lower() != column.lower():
            continue
        if value is None:
            return True
        if any(_same_filter_value(raw, value) for raw in item.get("values") or []):
            return True
    return False


def _same_filter_value(actual: Any, expected: str) -> bool:
    actual_text = str(actual).strip()
    expected_text = str(expected).strip()
    if actual_text == expected_text:
        return True
    try:
        return float(actual_text) == float(expected_text)
    except (TypeError, ValueError):
        return False


def _has_gap_evidence(response: Mapping[str, Any]) -> bool:
    debug = response.get("debug") if isinstance(response.get("debug"), Mapping) else {}
    artifacts = debug.get("result_artifacts") if isinstance(debug.get("result_artifacts"), Mapping) else {}
    gap_rows = artifacts.get("gap_rows") if isinstance(artifacts.get("gap_rows"), list) else []
    if len(gap_rows) >= 2 and any("adjacent_gap" in row or "gap_to_leader" in row for row in gap_rows if isinstance(row, Mapping)):
        return True
    rows = _result_rows(response)
    return len(rows) >= 2 and any("adjacent_gap" in row or "gap_to_leader" in row for row in rows)


def _looks_blocked(answer: str) -> bool:
    return any(token in answer for token in ("暂时不能可靠回答", "当前还缺少", "需要补充", "不能编造字段", "无法可靠回答"))


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_stability_report(path: Path, summary: Mapping[str, Any]) -> None:
    lines = [
        "# UK Retail Frontend Manual Gate",
        "",
        f"- generated_at: `{summary.get('generated_at')}`",
        f"- passed: `{summary.get('passed')}`",
        f"- cycles: `{summary.get('cycles_passed')}/{summary.get('cycles_total')}`",
        "",
    ]
    for cycle in summary.get("cycle_summaries") or []:
        cycle_summary = cycle.get("summary") or {}
        lines.extend(
            [
                f"## Cycle {cycle.get('cycle')}",
                "",
                f"- cycle_passed: `{cycle.get('cycle_passed')}`",
                f"- result_file: `{cycle.get('result_file')}`",
                f"- total/pass/soft/hard: `{cycle_summary.get('total')}/{cycle_summary.get('pass')}/{cycle_summary.get('soft_fail')}/{cycle_summary.get('hard_fail')}`",
                f"- http_5xx: `{cycle_summary.get('http_5xx')}`",
                f"- false_semantic_passed: `{cycle_summary.get('false_semantic_passed')}`",
                f"- recommendation_total/pass/fail: `{cycle_summary.get('recommendation_total')}/{cycle_summary.get('recommendation_pass')}/{cycle_summary.get('recommendation_fail')}`",
                "",
            ]
        )
        failed = cycle_summary.get("failed_questions") or []
        if failed:
            lines.append("### Failed Questions")
            for item in failed[:30]:
                reasons = ", ".join(str(reason) for reason in item.get("hard_reasons") or item.get("soft_reasons") or [])
                lines.append(f"- `{item.get('score')}` Gate {item.get('gate')} {item.get('question')} | {reasons}")
            lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run UK Retail Frontend Manual Gate over real HTTP.")
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--start-service", choices=("auto", "always", "never"), default="auto")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--service-start-timeout", type=float, default=90.0)
    parser.add_argument("--execution-mode", default="dual")
    parser.add_argument("--agent-mode", default="multi_agent")
    parser.add_argument("--stop-on-failure", action="store_true", default=False)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()

    dataset = Path(args.dataset).expanduser()
    if not dataset.exists():
        raise SystemExit(f"Dataset not found: {dataset}")
    output_dir = Path(args.output_dir) if args.output_dir else Path(f"/tmp/vds-uk-retail-frontend-manual-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    output_dir.mkdir(parents=True, exist_ok=True)

    client = HttpClient(args.base_url, timeout=args.timeout)
    process: subprocess.Popen[bytes] | None = None
    cycle_summaries: list[dict[str, Any]] = []
    try:
        process = ensure_service(client, args.base_url, output_dir, mode=args.start_service, timeout=args.service_start_timeout)
        for cycle_index in range(1, args.cycles + 1):
            upload = upload_dataset(client, dataset)
            if upload.status_code != 200 or not upload.body.get("dataset_id"):
                cycle = {
                    "cycle": cycle_index,
                    "dataset_id": "",
                    "turns": [],
                    "recommendation_turns": [],
                    "summary": {
                        "passed": False,
                        "total": 0,
                        "pass": 0,
                        "soft_fail": 0,
                        "hard_fail": 1,
                        "http_5xx": 1 if upload.status_code >= 500 else 0,
                        "false_semantic_passed": 0,
                        "failed_questions": [{"gate": "upload", "question": str(dataset), "score": "hard_fail", "hard_reasons": [f"upload_failed:{upload.status_code}:{upload.error[:120]}"]}],
                    },
                    "cycle_passed": False,
                }
            else:
                cycle = run_cycle(
                    client=client,
                    dataset_id=str(upload.body["dataset_id"]),
                    cycle_index=cycle_index,
                    execution_mode=args.execution_mode,
                    agent_mode=args.agent_mode,
                )
            result_file = output_dir / f"cycle_{cycle_index}_results.json"
            write_json(result_file, cycle)
            cycle_summaries.append({"cycle": cycle_index, "cycle_passed": cycle.get("cycle_passed"), "result_file": str(result_file), "summary": cycle.get("summary")})
            if args.print_summary:
                print(f"cycle={cycle_index} passed={cycle.get('cycle_passed')} result={result_file}", flush=True)
            if args.stop_on_failure and not cycle.get("cycle_passed"):
                break
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "passed": len(cycle_summaries) == args.cycles and all(cycle.get("cycle_passed") for cycle in cycle_summaries),
        "cycles_total": args.cycles,
        "cycles_passed": sum(1 for cycle in cycle_summaries if cycle.get("cycle_passed")),
        "output_dir": str(output_dir),
        "cycle_summaries": cycle_summaries,
    }
    write_json(output_dir / "stability_report.json", summary)
    write_stability_report(output_dir / "stability_report.md", summary)
    if args.print_summary:
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
