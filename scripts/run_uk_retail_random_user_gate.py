#!/usr/bin/env python3
"""Run the UK Retail fixed and random real-user gate through the HTTP API."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import math
import mimetypes
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence
import urllib.error
import urllib.parse
import urllib.request
import uuid


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = "/Users/trevorcui/Desktop/验证数据集/UK retail/Online Retail.xlsx"
DEFAULT_BASE_URL = "http://127.0.0.1:8876"

PASS_STATUSES = {"passed", "corrected_passed", "passed_with_insufficient_data"}
SAFE_FAIL_STATUSES = {"failed", "warning", "needs_clarification", "need_clarification"}
BLOCKED_ANSWER_MARKERS = (
    "暂时不能可靠回答",
    "不能直接给出数据结论",
    "不能把这个结果标记为成功",
    "不能编造字段",
    "需要补充",
    "当前还缺少",
    "尚未形成可计算口径",
    "无法可靠回答",
)


@dataclass(frozen=True)
class ExpectedContract:
    category: str
    answerable: bool = True
    safe_failure_expected: bool = False
    min_rows: int = 0
    required_columns: tuple[str, ...] = ()
    allowed_dimensions: tuple[str, ...] = ()
    allowed_metrics: tuple[str, ...] = ()
    forbidden_columns: tuple[str, ...] = ()
    require_formula: bool = False
    require_share: bool = False
    require_month_bucket: bool = False
    require_distinct_order: bool = False
    require_topn: bool = False
    expected_n: int = 0


@dataclass(frozen=True)
class GateQuestion:
    question: str
    expected: ExpectedContract
    gate: str
    conversation_key: str = ""
    turn_index: int = 1


@dataclass
class HttpPayload:
    status_code: int
    body: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    elapsed_ms: int = 0


@dataclass
class TurnScore:
    score: str
    hard_reasons: list[str] = field(default_factory=list)
    soft_reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.score == "pass"


class HttpClient:
    def __init__(self, base_url: str, *, timeout: float = 300.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_json(self, path: str) -> HttpPayload:
        request = urllib.request.Request(self._url(path), method="GET")
        return self._open(request)

    def post_json(self, path: str, payload: Mapping[str, Any]) -> HttpPayload:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._url(path),
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        return self._open(request)

    def multipart_upload(self, path: str, files: Sequence[tuple[str, Path, str]]) -> HttpPayload:
        boundary = "----vdsukretailgate" + uuid.uuid4().hex
        body = bytearray()
        for field, file_path, filename in files:
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode("utf-8"))
            body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
            body.extend(file_path.read_bytes())
            body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("utf-8"))
        request = urllib.request.Request(
            self._url(path),
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        return self._open(request)

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}{path}"

    def _open(self, request: urllib.request.Request) -> HttpPayload:
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                status_code = int(response.status)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            return HttpPayload(
                status_code=int(exc.code),
                body=_parse_json_object(raw),
                error=raw[:1000],
                elapsed_ms=_elapsed_ms(started),
            )
        except Exception as exc:  # noqa: BLE001 - gate evidence must record transport failures.
            return HttpPayload(
                status_code=0,
                error=f"{type(exc).__name__}: {exc}",
                elapsed_ms=_elapsed_ms(started),
            )
        return HttpPayload(
            status_code=status_code,
            body=_parse_json_object(raw),
            error="" if raw.strip().startswith("{") else raw[:1000],
            elapsed_ms=_elapsed_ms(started),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run UK Retail fixed and random real-user analysis gates over HTTP.")
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
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
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()

    dataset = Path(args.dataset).expanduser()
    if not dataset.exists():
        raise SystemExit(f"Dataset not found: {dataset}")
    if args.cycles <= 0:
        raise SystemExit("--cycles must be positive")
    if args.random_questions < 80:
        raise SystemExit("--random-questions must be at least 80")

    output_dir = Path(args.output_dir) if args.output_dir else Path("/tmp") / f"vds-uk-retail-random-stability-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    output_dir.mkdir(parents=True, exist_ok=True)

    client = HttpClient(args.base_url, timeout=args.timeout)
    service_process = ensure_service(client, args.base_url, output_dir, mode=args.start_service, timeout=args.service_start_timeout)
    try:
        summary = run_cycles(
            client=client,
            dataset=dataset,
            cycles=args.cycles,
            random_questions=args.random_questions,
            seeds=args.seeds,
            output_dir=output_dir,
            execution_mode=args.execution_mode,
            agent_mode=args.agent_mode,
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
        print(f"stability_report={summary['stability_report']}")
    if not summary["passed"]:
        raise SystemExit(1)


def run_cycles(
    *,
    client: HttpClient,
    dataset: Path,
    cycles: int,
    random_questions: int,
    seeds: Sequence[int],
    output_dir: Path,
    execution_mode: str,
    agent_mode: str,
) -> dict[str, Any]:
    cycle_summaries = []
    for cycle_index in range(1, cycles + 1):
        seed = int(seeds[cycle_index - 1]) if cycle_index <= len(seeds) else 2026060700 + cycle_index
        cycle_summary = run_cycle(
            client=client,
            dataset=dataset,
            cycle_index=cycle_index,
            seed=seed,
            random_questions=random_questions,
            output_dir=output_dir,
            execution_mode=execution_mode,
            agent_mode=agent_mode,
        )
        cycle_summaries.append(cycle_summary)
        write_cycle_report(output_dir / f"cycle_{cycle_index}_report.md", cycle_summary)
        if not cycle_summary["cycle_passed"]:
            break

    passed = len(cycle_summaries) == cycles and all(item["cycle_passed"] for item in cycle_summaries)
    summary = {
        "gate_name": "UK Retail Random Real User Analysis Gate",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "passed": passed,
        "cycles_total": cycles,
        "cycles_completed": len(cycle_summaries),
        "cycles_passed": sum(1 for item in cycle_summaries if item["cycle_passed"]),
        "cycle_summaries": cycle_summaries,
    }
    stability_report = output_dir / "stability_report.md"
    summary["stability_report"] = str(stability_report)
    (output_dir / "stability_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_stability_report(stability_report, summary)
    return summary


def run_cycle(
    *,
    client: HttpClient,
    dataset: Path,
    cycle_index: int,
    seed: int,
    random_questions: int,
    output_dir: Path,
    execution_mode: str,
    agent_mode: str,
) -> dict[str, Any]:
    upload = upload_dataset(client, dataset)
    dataset_id = str(upload.body.get("dataset_id") or "")
    if upload.status_code != 200 or not dataset_id or upload.body.get("success") is False:
        cycle_summary = {
            "cycle": cycle_index,
            "seed": seed,
            "cycle_passed": False,
            "dataset_id": dataset_id,
            "upload": asdict(upload),
            "fixed_summary": _empty_gate_summary("fixed", ["upload_failed"]),
            "random_summary": _empty_gate_summary("random", ["skipped_fixed_failed"]),
            "fixed_results_file": "",
            "random_results_file": "",
        }
        return cycle_summary

    fixed_turns = run_fixed_gate(
        client=client,
        dataset_id=dataset_id,
        cycle_index=cycle_index,
        execution_mode=execution_mode,
        agent_mode=agent_mode,
    )
    fixed_summary = summarize_turns(fixed_turns, fixed=True)
    fixed_results_file = output_dir / f"cycle_{cycle_index}_fixed_gate.json"
    write_json(fixed_results_file, {"cycle": cycle_index, "seed": seed, "dataset_id": dataset_id, "turns": fixed_turns, "summary": fixed_summary})

    random_turns: list[dict[str, Any]] = []
    random_summary = _empty_gate_summary("random", ["skipped_fixed_failed"])
    random_results_file = output_dir / f"cycle_{cycle_index}_random_gate.json"
    if fixed_summary["passed"]:
        random_cases = generate_random_gate(seed=seed, total_questions=random_questions)
        random_turns = run_question_cases(
            client=client,
            dataset_id=dataset_id,
            cases=random_cases,
            conversation_prefix=f"cycle{cycle_index}_random_{seed}",
            execution_mode=execution_mode,
            agent_mode=agent_mode,
        )
        random_summary = summarize_turns(random_turns, fixed=False)
    write_json(random_results_file, {"cycle": cycle_index, "seed": seed, "dataset_id": dataset_id, "turns": random_turns, "summary": random_summary})

    cycle_passed = bool(fixed_summary["passed"] and random_summary["passed"])
    return {
        "cycle": cycle_index,
        "seed": seed,
        "cycle_passed": cycle_passed,
        "dataset_id": dataset_id,
        "upload": {"status_code": upload.status_code, "elapsed_ms": upload.elapsed_ms},
        "fixed_summary": fixed_summary,
        "random_summary": random_summary,
        "fixed_results_file": str(fixed_results_file),
        "random_results_file": str(random_results_file),
    }


def run_fixed_gate(
    *,
    client: HttpClient,
    dataset_id: str,
    cycle_index: int,
    execution_mode: str,
    agent_mode: str,
) -> list[dict[str, Any]]:
    cases = fixed_gate_cases()
    return run_question_cases(
        client=client,
        dataset_id=dataset_id,
        cases=cases,
        conversation_prefix=f"cycle{cycle_index}_fixed",
        execution_mode=execution_mode,
        agent_mode=agent_mode,
    )


def run_question_cases(
    *,
    client: HttpClient,
    dataset_id: str,
    cases: Sequence[GateQuestion],
    conversation_prefix: str,
    execution_mode: str,
    agent_mode: str,
) -> list[dict[str, Any]]:
    conversation_ids: dict[str, str] = {}
    turns = []
    for index, case in enumerate(cases, start=1):
        conversation_id = ""
        if case.conversation_key:
            conversation_id = conversation_ids.setdefault(case.conversation_key, f"conv_{conversation_prefix}_{case.conversation_key}_{uuid.uuid4().hex[:8]}")
        payload = {
            "dataset_id": dataset_id,
            "conversation_id": conversation_id,
            "question": case.question,
            "execution_mode": execution_mode,
            "agent_mode": agent_mode,
        }
        http = client.post_json("/api/data-agent/message", payload)
        response = http.body if isinstance(http.body, dict) else {}
        if case.conversation_key and response.get("conversation_id"):
            conversation_ids[case.conversation_key] = str(response.get("conversation_id"))
        score = score_response(
            question=case.question,
            response=response,
            http_status=http.status_code,
            expected=case.expected,
            http_error=http.error,
        )
        turns.append(
            {
                "index": index,
                "gate": case.gate,
                "conversation_key": case.conversation_key,
                "turn_index": case.turn_index,
                "question": case.question,
                "expected": asdict(case.expected),
                "http_status": http.status_code,
                "elapsed_ms": http.elapsed_ms,
                "success": response.get("success"),
                "semantic_status": _semantic_status(response),
                "score": score.score,
                "hard_reasons": score.hard_reasons,
                "soft_reasons": score.soft_reasons,
                "answer_summary": _answer_summary(response),
                "contract": _compact_contract(response),
                "execution_spec": _compact_mapping((response.get("debug") or {}).get("execution_spec") if isinstance(response.get("debug"), Mapping) else {}),
                "execution_trace": _compact_mapping((response.get("debug") or {}).get("execution_trace") if isinstance(response.get("debug"), Mapping) else {}),
                "semantic_issues": _semantic_issues(response),
                "result_columns": _result_columns(response),
                "result_row_count": len(_result_rows(response)),
                "response": response,
            }
        )
    return turns


def score_response(
    *,
    question: str,
    response: Mapping[str, Any],
    http_status: int,
    expected: ExpectedContract,
    http_error: str = "",
) -> TurnScore:
    hard: list[str] = []
    soft: list[str] = []
    if http_status == 0:
        hard.append(f"http_unavailable:{http_error[:120]}")
    elif http_status >= 500:
        hard.append(f"http_5xx:{http_status}")
    elif http_status != 200:
        hard.append(f"http_non_200:{http_status}")

    answer = str(response.get("answer") or "")
    success = response.get("success") is True
    semantic_status = _semantic_status(response)
    rows = _result_rows(response)
    columns = _result_columns(response)
    params = _logic_params(response)
    trace = _execution_trace(response)
    blocked = _looks_like_blocked_answer(answer)

    if blocked and semantic_status in PASS_STATUSES:
        hard.append("false_semantic_passed_blocked_answer")
    if response.get("success") is False and semantic_status in PASS_STATUSES:
        hard.append("false_semantic_passed_success_false")

    if expected.safe_failure_expected:
        if semantic_status in PASS_STATUSES:
            hard.append("safe_failure_marked_passed")
        if success and rows:
            hard.append("safe_failure_fabricated_result")
        if not hard:
            if semantic_status in SAFE_FAIL_STATUSES or response.get("success") is False:
                return TurnScore("soft_fail", soft_reasons=["expected_safe_failure"])
            return TurnScore("soft_fail", soft_reasons=["safe_failure_no_clear_status"])

    if expected.answerable:
        if not success:
            hard.append("answerable_success_false")
        if semantic_status not in PASS_STATUSES:
            hard.append(f"semantic_not_passed:{semantic_status}")
        if expected.require_topn and expected.expected_n and len(rows) < expected.expected_n:
            hard.append(f"topn_row_count_below_expected:{len(rows)}<{expected.expected_n}")
        if expected.min_rows and len(rows) < expected.min_rows:
            hard.append(f"row_count_below_min:{len(rows)}<{expected.min_rows}")

    missing_columns = [column for column in expected.required_columns if not _has_column(columns, column)]
    if missing_columns:
        hard.append(f"required_columns_missing:{','.join(missing_columns)}")
    forbidden_present = [column for column in expected.forbidden_columns if _has_column(columns, column)]
    if forbidden_present:
        hard.append(f"forbidden_columns_present:{','.join(forbidden_present)}")
    if expected.allowed_dimensions and not _matches_any_dimension(expected.allowed_dimensions, columns, params, trace):
        hard.append(f"dimension_mismatch:expected_one_of={','.join(expected.allowed_dimensions)}")
    if expected.allowed_metrics and not _matches_any_metric(expected.allowed_metrics, columns, params, trace):
        hard.append(f"metric_mismatch:expected_one_of={','.join(expected.allowed_metrics)}")
    if expected.require_formula and not _has_sales_formula(params, trace, rows):
        hard.append("sales_formula_missing")
    if expected.require_share:
        if not any(_has_column(columns, column) for column in ("Sales_share", "share", "share_percent", "contribution_rate")):
            hard.append("share_column_missing")
        if not any(_has_column(columns, column) for column in ("total_Sales", "total_metric_value")):
            hard.append("share_denominator_missing")
    if expected.require_month_bucket:
        time_grain = str(trace.get("time_grain") or params.get("time_bucket") or "").lower()
        dimension = str(params.get("dimension") or params.get("time_dimension") or "").lower()
        if not (_has_column(columns, "month") or time_grain == "month" or dimension == "month"):
            hard.append("month_bucket_missing")
        if _has_column(columns, "InvoiceDate") and not _has_column(columns, "month"):
            hard.append("raw_invoice_date_returned")
    if expected.require_distinct_order:
        metric = str(params.get("metric") or "")
        aggregation = str(params.get("aggregation") or trace.get("aggregation") or "").lower()
        trace_metrics = {str(item) for item in trace.get("metric_columns") or [] if item}
        if (metric != "InvoiceNo" and "InvoiceNo" not in trace_metrics) or aggregation not in {"nunique", "distinct_count"}:
            hard.append("order_count_not_distinct_invoiceno")

    if hard:
        return TurnScore("hard_fail", hard_reasons=hard, soft_reasons=soft)
    if soft:
        return TurnScore("soft_fail", soft_reasons=soft)
    return TurnScore("pass")


def summarize_turns(turns: Sequence[Mapping[str, Any]], *, fixed: bool) -> dict[str, Any]:
    total = len(turns)
    pass_count = sum(1 for turn in turns if turn.get("score") == "pass")
    soft_count = sum(1 for turn in turns if turn.get("score") == "soft_fail")
    hard_count = sum(1 for turn in turns if turn.get("score") == "hard_fail")
    http_5xx = sum(1 for turn in turns if int(turn.get("http_status") or 0) >= 500)
    false_semantic_passed = sum(
        1
        for turn in turns
        if any("false_semantic_passed" in str(reason) or "safe_failure_marked_passed" in str(reason) for reason in turn.get("hard_reasons") or [])
    )
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    for turn in turns:
        expected = turn.get("expected") if isinstance(turn.get("expected"), Mapping) else {}
        by_category[str(expected.get("category") or "unknown")][str(turn.get("score") or "unknown")] += 1
    pass_rate = pass_count / total if total else 0.0
    pass_soft_rate = (pass_count + soft_count) / total if total else 0.0
    if fixed:
        passed = bool(total == 16 and pass_count == 16 and hard_count == 0 and http_5xx == 0 and false_semantic_passed == 0)
    else:
        passed = bool(total >= 80 and hard_count == 0 and pass_rate >= 0.90 and pass_soft_rate >= 0.95 and http_5xx == 0 and false_semantic_passed == 0)
    return {
        "gate": "fixed" if fixed else "random",
        "passed": passed,
        "total": total,
        "pass": pass_count,
        "soft_fail": soft_count,
        "hard_fail": hard_count,
        "pass_rate": pass_rate,
        "pass_plus_soft_rate": pass_soft_rate,
        "http_5xx": http_5xx,
        "false_semantic_passed": false_semantic_passed,
        "by_category": {category: dict(counter) for category, counter in sorted(by_category.items())},
        "failed_questions": [
            {
                "question": turn.get("question"),
                "score": turn.get("score"),
                "hard_reasons": turn.get("hard_reasons"),
                "soft_reasons": turn.get("soft_reasons"),
                "http_status": turn.get("http_status"),
                "semantic_status": turn.get("semantic_status"),
                "answer_summary": turn.get("answer_summary"),
            }
            for turn in turns
            if turn.get("score") != "pass"
        ],
    }


def fixed_gate_cases() -> list[GateQuestion]:
    cases: list[GateQuestion] = []
    conv = "fixed_a"
    gate_a = [
        ("先看一下这个 UK retail 数据，告诉我有哪些主要字段、行数，以及明显的数据质量问题。", _overview()),
        ("销售额最高的前5个商品是什么？销售额按 Quantity * UnitPrice 算。", _product_topn(5)),
        ("第一名和第二名差多少？", _gap()),
        ("前5商品按月份趋势怎么看？", _product_month_trend()),
        ("这些 Top 商品主要卖给哪些国家？分别列出主要国家和销售额。", _country_sales_drilldown()),
        ("这些国家分别占总销售额的比例是多少？", _country_share(min_rows=1)),
        ("订单数量最多的前5个客户是谁？", _customer_order_count(5)),
        ("这些客户的销售额分别是多少？销售额按 Quantity * UnitPrice 算。", _customer_sales()),
    ]
    for index, (question, expected) in enumerate(gate_a, start=1):
        cases.append(GateQuestion(question=question, expected=expected, gate="fixed_a", conversation_key=conv, turn_index=index))
    gate_b = [
        ("这个 UK retail 数据的总销售额是多少？销售额按 Quantity * UnitPrice 算。", _sales_total()),
        ("销售额最高的前5个商品是什么？销售额按 Quantity * UnitPrice 算。", _product_topn(5)),
        ("按 Description 分组，销售额最高的前5个 Description 是什么？销售额按 Quantity * UnitPrice 算。", _description_topn(5)),
        ("销售额最高的前5个国家是哪些？销售额按 Quantity * UnitPrice 算。", _country_topn(5)),
        ("Country 销售额占比是多少？销售额按 Quantity * UnitPrice 算。", _country_share(min_rows=5)),
        ("订单数量最多的前5个客户是谁？", _customer_order_count(5)),
        ("退货数量最多的前5个商品是什么？", _return_product_topn(5)),
        ("按月份看整体销售额趋势，哪些月份最高？", _month_trend()),
    ]
    for index, (question, expected) in enumerate(gate_b, start=1):
        cases.append(GateQuestion(question=question, expected=expected, gate="fixed_b", conversation_key="", turn_index=index))
    return cases


def generate_random_gate(*, seed: int, total_questions: int) -> list[GateQuestion]:
    rng = random.Random(seed)
    single_count = max(45, total_questions - 35)
    conversation_count = 7
    cases = _random_single_questions(rng, single_count)
    conversations = _random_conversations(rng, conversation_count)
    for conversation in conversations:
        cases.extend(conversation)
    return cases


def _random_single_questions(rng: random.Random, count: int) -> list[GateQuestion]:
    builders = [
        _single_overview,
        _single_count_distinct,
        _single_sales_formula,
        _single_product_topn,
        _single_country,
        _single_customer,
        _single_time_trend,
        _single_share,
        _single_ambiguous,
    ]
    cases: list[GateQuestion] = []
    while len(cases) < count:
        builder = builders[len(cases) % len(builders)] if len(cases) < len(builders) else rng.choice(builders)
        question, expected = builder(rng)
        cases.append(GateQuestion(question=question, expected=expected, gate="random_single", turn_index=len(cases) + 1))
    rng.shuffle(cases)
    return cases


def _random_conversations(rng: random.Random, conversation_count: int) -> list[list[GateQuestion]]:
    chains = [
        _product_chain,
        _country_chain,
        _customer_chain,
        _invalid_context_chain,
        _time_chain,
        _stockcode_chain,
        _overview_to_topn_chain,
    ]
    conversations: list[list[GateQuestion]] = []
    for index in range(conversation_count):
        builder = chains[index % len(chains)]
        conversation_key = f"random_conv_{index + 1}"
        conversations.append(builder(rng, conversation_key))
    return conversations


def _single_overview(rng: random.Random) -> tuple[str, ExpectedContract]:
    questions = [
        "看一下整体表格数据，告诉我行数、字段和明显数据质量问题。",
        "这个数据有多少行多少列？有哪些主要字段？",
        "用一句话总结这个 UK retail 数据集，并指出缺失较明显的字段。",
        "这个数据集里有哪些字段、字段类型和明显异常值？",
    ]
    return rng.choice(questions), _overview()


def _single_count_distinct(rng: random.Random) -> tuple[str, ExpectedContract]:
    options = [
        ("这个数据集有多少订单？按 InvoiceNo 去重算。", _count_distinct("InvoiceNo")),
        ("有多少个客户？按 CustomerID 去重算。", _count_distinct("CustomerID")),
        ("每个国家有多少客户？按 CustomerID 去重。", ExpectedContract("count distinct", min_rows=3, required_columns=("Country", "count"), allowed_dimensions=("Country",), allowed_metrics=("CustomerID",))),
        ("每个商品被多少订单购买过？按 InvoiceNo 去重。", ExpectedContract("count distinct", min_rows=3, allowed_dimensions=("Description", "StockCode"), allowed_metrics=("InvoiceNo",), require_distinct_order=True)),
    ]
    return rng.choice(options)


def _single_sales_formula(rng: random.Random) -> tuple[str, ExpectedContract]:
    questions = [
        "这个数据集的总销售额是多少？销售额按 Quantity * UnitPrice 算。",
        "total revenue 是多少？revenue = quantity times unit price。",
        "用数量乘单价算金额，总金额是多少？",
        "Sales 总额是多少，公式用 Quantity * UnitPrice。",
    ]
    return rng.choice(questions), _sales_total()


def _single_product_topn(rng: random.Random) -> tuple[str, ExpectedContract]:
    n = rng.choice([3, 5, 7, 10])
    options = [
        (f"销售额最高的前{n}个商品是什么？销售额按 Quantity * UnitPrice 算。", _product_topn(n)),
        (f"按 Description 看销售额 Top{n}，销售额按 Quantity * UnitPrice 算。", _description_topn(n)),
        (f"按 StockCode 看销售额最高的前{n}个商品。", _stockcode_topn(n)),
        (f"卖得最多的前{n}个商品是什么？", ExpectedContract("product TopN", min_rows=n, allowed_dimensions=("Description", "StockCode"), allowed_metrics=("Quantity",), require_topn=True, expected_n=n)),
        (f"退货数量最多的前{n}个商品是什么？退货按 Quantity<0 统计。", _return_product_topn(n)),
    ]
    return rng.choice(options)


def _single_country(rng: random.Random) -> tuple[str, ExpectedContract]:
    n = rng.choice([3, 5, 8])
    options = [
        (f"销售额最高的前{n}个国家是哪些？销售额按 Quantity * UnitPrice 算。", _country_topn(n)),
        ("Country 销售额占比是多少？销售额按 Quantity * UnitPrice 算。", _country_share(min_rows=5)),
        ("按国家看数量和销售额表现。", ExpectedContract("country share", min_rows=3, allowed_dimensions=("Country",))),
        ("按国家看客户数，客户按 CustomerID 去重。", ExpectedContract("country share", min_rows=3, required_columns=("Country",), allowed_dimensions=("Country",), allowed_metrics=("CustomerID",))),
    ]
    return rng.choice(options)


def _single_customer(rng: random.Random) -> tuple[str, ExpectedContract]:
    n = rng.choice([3, 5, 10])
    options = [
        (f"订单数量最多的前{n}个客户是谁？", _customer_order_count(n)),
        (f"销售额最高的前{n}个客户是谁？销售额按 Quantity * UnitPrice 算。", ExpectedContract("customer", min_rows=n, required_columns=("CustomerID", "Sales"), allowed_dimensions=("CustomerID",), allowed_metrics=("Sales",), require_formula=True, require_topn=True, expected_n=n)),
        ("客户购买次数最多的是哪些？购买次数按 InvoiceNo 去重。", _customer_order_count(5)),
    ]
    return rng.choice(options)


def _single_time_trend(rng: random.Random) -> tuple[str, ExpectedContract]:
    options = [
        ("按月份看整体销售额趋势，销售额按 Quantity * UnitPrice 算。", _month_trend()),
        ("每月销售额变化如何？金额按 Quantity * UnitPrice 算。", _month_trend()),
        ("按月看退货数量趋势，退货按 Quantity<0 统计。", ExpectedContract("time trend", min_rows=3, allowed_metrics=("Quantity",), require_month_bucket=True, forbidden_columns=("InvoiceDate",))),
        ("哪些月份销售额最高？销售额按 Quantity * UnitPrice 算。", _month_trend()),
    ]
    return rng.choice(options)


def _single_share(rng: random.Random) -> tuple[str, ExpectedContract]:
    options = [
        ("各商品销售额占比是多少？销售额按 Quantity * UnitPrice 算。", ExpectedContract("share", min_rows=3, allowed_dimensions=("Description", "StockCode"), allowed_metrics=("Sales",), require_formula=True, require_share=True)),
        ("前5商品占总销售额多少？销售额按 Quantity * UnitPrice 算。", ExpectedContract("share", min_rows=1, allowed_metrics=("Sales",), require_formula=True)),
        ("Country, Sales, total_Sales, Sales_share 分别是多少？", _country_share(min_rows=5)),
    ]
    return rng.choice(options)


def _single_ambiguous(rng: random.Random) -> tuple[str, ExpectedContract]:
    options: list[tuple[str, ExpectedContract]] = [
        ("销售额最大的店家是谁？", ExpectedContract("ambiguous / dirty input", answerable=False, safe_failure_expected=True)),
        ("找最有意义的5个客户。", ExpectedContract("ambiguous / dirty input", answerable=False, safe_failure_expected=True)),
        ("列出不存在字段 top5。", ExpectedContract("ambiguous / dirty input", answerable=False, safe_failure_expected=True)),
        ("按 FooBar 看销售额。", ExpectedContract("ambiguous / dirty input", answerable=False, safe_failure_expected=True)),
        ("最近两年销售变化最好？", ExpectedContract("ambiguous / dirty input", answerable=False, safe_failure_expected=True)),
        ("把所有字段汇总成一句话。", _overview()),
    ]
    return rng.choice(options)


def _product_chain(rng: random.Random, conversation_key: str) -> list[GateQuestion]:
    n = rng.choice([3, 5])
    questions = [
        (f"销售额最高的前{n}个商品是谁？销售额按 Quantity * UnitPrice 算。", _product_topn(n)),
        ("第一名和第二名差多少？", _gap()),
        ("前5商品按月份趋势怎么变动？", _product_month_trend()),
        ("这前5商品主要卖给哪些国家？", _country_sales_drilldown()),
        ("这些国家占比呢？返回 Country, Sales, total_Sales, Sales_share。", _country_share(min_rows=1)),
    ]
    return _conversation_cases(questions, "follow-up drilldown", conversation_key)


def _country_chain(rng: random.Random, conversation_key: str) -> list[GateQuestion]:
    n = rng.choice([3, 5])
    questions = [
        (f"先给我看国家销售额最高的前{n}个国家。", _country_topn(n)),
        ("这些国家占比是多少？", _country_share(min_rows=1)),
        ("按国家再看销售趋势，月粒度。", ExpectedContract("time trend", min_rows=3, allowed_dimensions=("month",), allowed_metrics=("Sales",), require_formula=True, require_month_bucket=True)),
        ("按这些国家看订单数量前5。", ExpectedContract("customer", min_rows=5, allowed_dimensions=("CustomerID", "Country"), allowed_metrics=("InvoiceNo",), require_distinct_order=True)),
        ("这些国家里销售额第二名和第三名差多少？", _gap()),
    ]
    return _conversation_cases(questions, "follow-up gap", conversation_key)


def _customer_chain(rng: random.Random, conversation_key: str) -> list[GateQuestion]:
    questions = [
        ("订单数量最多的前5个客户是谁？", _customer_order_count(5)),
        ("这些客户的销售额分别是多少？销售额按 Quantity * UnitPrice 算。", _customer_sales()),
        ("这5个客户在哪些月份最活跃？", ExpectedContract("time trend", min_rows=3, allowed_dimensions=("month",), require_month_bucket=True)),
        ("这5个客户里谁买得最多？", ExpectedContract("customer", min_rows=1, required_columns=("CustomerID",), allowed_dimensions=("CustomerID",))),
        ("列出这5个客户买最多的前5个商品。", ExpectedContract("follow-up drilldown", min_rows=5, allowed_dimensions=("Description", "StockCode"), require_topn=True, expected_n=5)),
    ]
    return _conversation_cases(questions, "customer", conversation_key)


def _invalid_context_chain(rng: random.Random, conversation_key: str) -> list[GateQuestion]:
    questions = [
        ("列出一个不存在的字段 top5。", ExpectedContract("ambiguous / dirty input", answerable=False, safe_failure_expected=True)),
        ("销售额最高的前5个国家是什么？销售额按 Quantity * UnitPrice 算。", _country_topn(5)),
        ("这些国家占比是多少？", _country_share(min_rows=1)),
        ("销售额最高的前5个商品是什么？销售额按 Quantity * UnitPrice 算。", _product_topn(5)),
        ("第一名和第二名差多少？", _gap()),
    ]
    return _conversation_cases(questions, "ambiguous / dirty input", conversation_key)


def _time_chain(rng: random.Random, conversation_key: str) -> list[GateQuestion]:
    questions = [
        ("按月份看整体销售额趋势，销售额按 Quantity * UnitPrice 算。", _month_trend()),
        ("哪些月份最高？", ExpectedContract("time trend", min_rows=3, allowed_dimensions=("month",), allowed_metrics=("Sales",), require_formula=True, require_month_bucket=True)),
        ("这些高月份里销售额最高的国家是哪些？", _country_topn(5)),
        ("这些国家占总销售额比例是多少？", _country_share(min_rows=1)),
        ("第一名和第二名相差多少？", _gap()),
    ]
    return _conversation_cases(questions, "time trend", conversation_key)


def _stockcode_chain(rng: random.Random, conversation_key: str) -> list[GateQuestion]:
    questions = [
        ("按 StockCode 查看销售额最高的前5个商品。", _stockcode_topn(5)),
        ("这些 StockCode 按月份趋势怎么看？", ExpectedContract("time trend", min_rows=3, required_columns=("month", "StockCode", "Sales"), allowed_dimensions=("month", "StockCode"), allowed_metrics=("Sales",), require_formula=True, require_month_bucket=True)),
        ("这些商品主要卖给哪些国家？", _country_sales_drilldown()),
        ("这些国家占比是多少？返回 Country, Sales, total_Sales, Sales_share。", _country_share(min_rows=1)),
        ("第二名比第一名少多少？", _gap()),
    ]
    return _conversation_cases(questions, "follow-up drilldown", conversation_key)


def _overview_to_topn_chain(rng: random.Random, conversation_key: str) -> list[GateQuestion]:
    questions = [
        ("先看一下这个数据，告诉我字段和数据质量问题。", _overview()),
        ("销售额最高的前5个商品是什么？销售额按 Quantity * UnitPrice 算。", _product_topn(5)),
        ("这些 Top 商品主要卖给哪些国家？分别列出主要国家和销售额。", _country_sales_drilldown()),
        ("这些国家分别占总销售额的比例是多少？", _country_share(min_rows=1)),
        ("订单数量最多的前5个客户是谁？", _customer_order_count(5)),
    ]
    return _conversation_cases(questions, "overview", conversation_key)


def _conversation_cases(items: Sequence[tuple[str, ExpectedContract]], gate: str, conversation_key: str) -> list[GateQuestion]:
    return [
        GateQuestion(question=question, expected=expected, gate=f"random_conversation:{gate}", conversation_key=conversation_key, turn_index=index)
        for index, (question, expected) in enumerate(items, start=1)
    ]


def _overview() -> ExpectedContract:
    return ExpectedContract("overview", min_rows=1)


def _sales_total() -> ExpectedContract:
    return ExpectedContract("sales formula", min_rows=1, required_columns=("Sales",), allowed_metrics=("Sales",), require_formula=True)


def _count_distinct(metric: str) -> ExpectedContract:
    return ExpectedContract("count distinct", min_rows=1, allowed_metrics=(metric,), require_distinct_order=metric == "InvoiceNo")


def _product_topn(n: int) -> ExpectedContract:
    return ExpectedContract("product TopN", min_rows=n, required_columns=("Sales",), allowed_dimensions=("Description", "StockCode"), allowed_metrics=("Sales",), require_formula=True, require_topn=True, expected_n=n)


def _description_topn(n: int) -> ExpectedContract:
    return ExpectedContract("product TopN", min_rows=n, required_columns=("Description", "Sales"), allowed_dimensions=("Description",), allowed_metrics=("Sales",), require_formula=True, require_topn=True, expected_n=n)


def _stockcode_topn(n: int) -> ExpectedContract:
    return ExpectedContract("product TopN", min_rows=n, required_columns=("StockCode", "Sales"), allowed_dimensions=("StockCode",), allowed_metrics=("Sales",), require_formula=True, require_topn=True, expected_n=n)


def _return_product_topn(n: int) -> ExpectedContract:
    return ExpectedContract("product TopN", min_rows=n, required_columns=("Quantity",), allowed_dimensions=("Description", "StockCode"), allowed_metrics=("Quantity",), require_topn=True, expected_n=n)


def _country_topn(n: int) -> ExpectedContract:
    return ExpectedContract("country share", min_rows=n, required_columns=("Country", "Sales"), allowed_dimensions=("Country",), allowed_metrics=("Sales",), require_formula=True, require_topn=True, expected_n=n)


def _country_share(*, min_rows: int) -> ExpectedContract:
    return ExpectedContract("country share", min_rows=min_rows, required_columns=("Country", "Sales", "total_Sales", "Sales_share"), allowed_dimensions=("Country",), allowed_metrics=("Sales",), require_formula=True, require_share=True)


def _customer_order_count(n: int) -> ExpectedContract:
    return ExpectedContract("customer", min_rows=n, required_columns=("CustomerID", "count"), allowed_dimensions=("CustomerID",), allowed_metrics=("InvoiceNo",), require_distinct_order=True, require_topn=True, expected_n=n)


def _customer_sales() -> ExpectedContract:
    return ExpectedContract("customer", min_rows=1, required_columns=("CustomerID", "Sales"), allowed_dimensions=("CustomerID",), allowed_metrics=("Sales",), require_formula=True)


def _month_trend() -> ExpectedContract:
    return ExpectedContract("time trend", min_rows=3, required_columns=("month", "Sales"), allowed_dimensions=("month",), allowed_metrics=("Sales",), forbidden_columns=("InvoiceDate",), require_formula=True, require_month_bucket=True)


def _product_month_trend() -> ExpectedContract:
    return ExpectedContract("time trend", min_rows=3, required_columns=("month", "Sales"), allowed_dimensions=("month", "Description", "StockCode"), allowed_metrics=("Sales",), forbidden_columns=("InvoiceDate",), require_formula=True, require_month_bucket=True)


def _country_sales_drilldown() -> ExpectedContract:
    return ExpectedContract("follow-up drilldown", min_rows=1, required_columns=("Country", "Sales"), allowed_dimensions=("Country",), allowed_metrics=("Sales",), require_formula=True)


def _gap() -> ExpectedContract:
    return ExpectedContract("follow-up gap", min_rows=2, require_formula=True)


def upload_dataset(client: HttpClient, dataset: Path) -> HttpPayload:
    return client.multipart_upload("/api/data-agent/upload-batch", [("files", dataset, dataset.name)])


def ensure_service(
    client: HttpClient,
    base_url: str,
    output_dir: Path,
    *,
    mode: str,
    timeout: float,
) -> subprocess.Popen[bytes] | None:
    if mode != "always" and service_ready(client):
        return None
    if mode == "never":
        raise SystemExit(f"Service is not reachable at {base_url}; rerun with --start-service auto or start it manually.")
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    log_path = output_dir / "service.log"
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", host, "--port", str(port)],
        cwd=str(REPO_ROOT),
        stdout=log_path.open("ab"),
        stderr=subprocess.STDOUT,
        env=env,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"Service exited during startup; see {log_path}")
        if service_ready(client):
            return process
        time.sleep(1)
    process.terminate()
    raise SystemExit(f"Service did not become ready within {timeout:g}s; see {log_path}")


def service_ready(client: HttpClient) -> bool:
    health = client.get_json("/api/monitor/health")
    return health.status_code == 200


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_cycle_report(path: Path, cycle: Mapping[str, Any]) -> None:
    lines = [
        f"# Cycle {cycle['cycle']} Report",
        "",
        f"- seed: `{cycle['seed']}`",
        f"- dataset_id: `{cycle.get('dataset_id') or ''}`",
        f"- cycle_passed: `{cycle['cycle_passed']}`",
        "",
        "## Fixed Gate",
        *_gate_summary_lines(cycle["fixed_summary"]),
        "",
        "## Random Gate",
        *_gate_summary_lines(cycle["random_summary"]),
        "",
        f"- fixed_results_file: `{cycle.get('fixed_results_file') or ''}`",
        f"- random_results_file: `{cycle.get('random_results_file') or ''}`",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_stability_report(path: Path, summary: Mapping[str, Any]) -> None:
    lines = [
        "# UK Retail Random Real User Analysis Gate",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- passed: `{summary['passed']}`",
        f"- cycles: `{summary['cycles_passed']}/{summary['cycles_total']}`",
        "",
    ]
    for cycle in summary.get("cycle_summaries") or []:
        lines.extend(
            [
                f"## Cycle {cycle['cycle']}",
                "",
                f"- seed: `{cycle['seed']}`",
                f"- cycle_passed: `{cycle['cycle_passed']}`",
                f"- fixed_results_file: `{cycle.get('fixed_results_file') or ''}`",
                f"- random_results_file: `{cycle.get('random_results_file') or ''}`",
                "",
                "### Fixed",
                *_gate_summary_lines(cycle["fixed_summary"]),
                "",
                "### Random",
                *_gate_summary_lines(cycle["random_summary"]),
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _gate_summary_lines(summary: Mapping[str, Any]) -> list[str]:
    lines = [
        f"- passed: `{summary.get('passed')}`",
        f"- total/pass/soft/hard: `{summary.get('total')}/{summary.get('pass')}/{summary.get('soft_fail')}/{summary.get('hard_fail')}`",
        f"- pass_rate: `{float(summary.get('pass_rate') or 0):.3f}`",
        f"- pass_plus_soft_rate: `{float(summary.get('pass_plus_soft_rate') or 0):.3f}`",
        f"- http_5xx: `{summary.get('http_5xx')}`",
        f"- false_semantic_passed: `{summary.get('false_semantic_passed')}`",
    ]
    failed = summary.get("failed_questions") or []
    if failed:
        lines.append("- failed_questions:")
        for item in failed[:20]:
            reason = ", ".join(str(reason) for reason in item.get("hard_reasons") or item.get("soft_reasons") or [])
            lines.append(f"  - `{item.get('score')}` {item.get('question')} | {reason}")
    return lines


def _empty_gate_summary(gate: str, reasons: Sequence[str]) -> dict[str, Any]:
    return {
        "gate": gate,
        "passed": False,
        "total": 0,
        "pass": 0,
        "soft_fail": 0,
        "hard_fail": 0,
        "pass_rate": 0.0,
        "pass_plus_soft_rate": 0.0,
        "http_5xx": 0,
        "false_semantic_passed": 0,
        "by_category": {},
        "failed_questions": [{"question": "", "score": "hard_fail", "hard_reasons": list(reasons), "soft_reasons": []}],
    }


def _parse_json_object(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _elapsed_ms(started: float) -> int:
    return max(0, int(round((time.perf_counter() - started) * 1000)))


def _semantic_status(response: Mapping[str, Any]) -> str:
    verification = response.get("verification") if isinstance(response.get("verification"), Mapping) else {}
    debug = response.get("debug") if isinstance(response.get("debug"), Mapping) else {}
    return str(response.get("semantic_status") or verification.get("semantic_status") or debug.get("semantic_status") or "not_available")


def _result_rows(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = response.get("result") if isinstance(response.get("result"), Mapping) else {}
    rows = result.get("rows")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    value = result.get("value")
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _result_columns(response: Mapping[str, Any]) -> list[str]:
    result = response.get("result") if isinstance(response.get("result"), Mapping) else {}
    columns = result.get("columns")
    if isinstance(columns, list):
        return [str(column) for column in columns]
    rows = _result_rows(response)
    if rows:
        return [str(column) for column in rows[0].keys()]
    value = result.get("value")
    if isinstance(value, dict):
        return [str(column) for column in value.keys()]
    return []


def _logic_params(response: Mapping[str, Any]) -> dict[str, Any]:
    logic = response.get("logic_form") if isinstance(response.get("logic_form"), Mapping) else {}
    params = dict(logic.get("parameters") or {}) if isinstance(logic.get("parameters"), Mapping) else {}
    for key in ("metric", "group_by", "operation"):
        if logic.get(key) not in (None, "", [], {}):
            params.setdefault("metric" if key == "metric" else "dimension" if key == "group_by" else key, logic.get(key))
    return params


def _execution_trace(response: Mapping[str, Any]) -> dict[str, Any]:
    debug = response.get("debug") if isinstance(response.get("debug"), Mapping) else {}
    trace = debug.get("execution_trace") if isinstance(debug.get("execution_trace"), Mapping) else {}
    return dict(trace)


def _has_column(columns: Sequence[str], expected: str) -> bool:
    expected_lower = expected.lower()
    return any(str(column).lower() == expected_lower for column in columns)


def _matches_any_dimension(allowed: Sequence[str], columns: Sequence[str], params: Mapping[str, Any], trace: Mapping[str, Any]) -> bool:
    values = {str(params.get("dimension") or ""), str(params.get("time_dimension") or "")}
    values.update(str(item) for item in trace.get("groupby_columns") or [] if item)
    values.update(columns)
    return any(str(value).lower() == str(allowed_value).lower() for value in values for allowed_value in allowed)


def _matches_any_metric(allowed: Sequence[str], columns: Sequence[str], params: Mapping[str, Any], trace: Mapping[str, Any]) -> bool:
    values = {str(params.get("metric") or ""), str(params.get("ranking_metric") or ""), str(params.get("share_metric") or "")}
    values.update(str(item) for item in trace.get("metric_columns") or [] if item)
    values.update(columns)
    count_allowed = {"count", "row_count", "transaction_count", "psp_reference"}
    if any(str(allowed_value).lower() in count_allowed for allowed_value in allowed):
        operation_values = {str(params.get("operation") or ""), str(trace.get("operation") or "")}
        if any(value.lower() == "row_count" for value in operation_values):
            return True
    return any(str(value).lower() == str(allowed_value).lower() for value in values for allowed_value in allowed)


def _has_sales_formula(params: Mapping[str, Any], trace: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> bool:
    candidates: list[str] = []
    derived = params.get("derived_metric") if isinstance(params.get("derived_metric"), Mapping) else {}
    candidates.extend(
        str(value)
        for value in (
            trace.get("formula"),
            params.get("metric_formula"),
            derived.get("formula"),
        )
        if value
    )
    for row in rows[:3]:
        if row.get("metric_formula"):
            candidates.append(str(row.get("metric_formula")))
    normalized = {_normalize_formula(value) for value in candidates}
    return "quantity*unitprice" in normalized


def _normalize_formula(value: str) -> str:
    return re.sub(r"[^a-z0-9*]+", "", str(value).lower())


def _looks_like_blocked_answer(answer: str) -> bool:
    compact = "".join(str(answer or "").split())
    return any(marker in compact for marker in BLOCKED_ANSWER_MARKERS)


def _answer_summary(response: Mapping[str, Any]) -> str:
    answer = str(response.get("answer") or "")
    compact = re.sub(r"\s+", " ", answer).strip()
    return compact[:500]


def _compact_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    keep = {
        "operation",
        "metric",
        "metric_columns",
        "formula",
        "aggregation",
        "groupby_columns",
        "filters_applied",
        "time_column",
        "time_grain",
        "ranking",
        "trace_status",
        "task_type",
        "capability_family",
        "physical_operation",
    }
    return {key: value.get(key) for key in keep if key in value}


def _compact_contract(response: Mapping[str, Any]) -> dict[str, Any]:
    verification = response.get("verification") if isinstance(response.get("verification"), Mapping) else {}
    debug = response.get("debug") if isinstance(response.get("debug"), Mapping) else {}
    contract = response.get("task_contract") or verification.get("task_contract") or debug.get("task_contract")
    return _compact_mapping(contract) if isinstance(contract, Mapping) else {}


def _semantic_issues(response: Mapping[str, Any]) -> list[Any]:
    debug = response.get("debug") if isinstance(response.get("debug"), Mapping) else {}
    verification = response.get("verification") if isinstance(response.get("verification"), Mapping) else {}
    issues = response.get("semantic_issues") or debug.get("semantic_issues") or verification.get("semantic_issues") or []
    return list(issues) if isinstance(issues, list) else []


if __name__ == "__main__":
    main()
