#!/usr/bin/env python3
"""Run VDS Workbench GPT-like quality-gate cases with an LLM judge.

The runner deliberately sends only public, user-facing response fields to the
judge. It does not include raw trace, debug payloads, standard answers, task
ids, hidden answers, proxy answers, raw prompts, or API keys.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CASE_FILE = REPO_ROOT / "configs" / "eval_gate" / "workbench_gpt_like_cases.jsonl"
DEFAULT_DOC_DIR = REPO_ROOT / "docs" / "test-runs"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "outputs" / "llm_quality_gate"
FORBIDDEN_REPORT_MARKERS = (
    "api_key",
    "raw prompt:",
    "raw_prompt",
    "chain_of_thought",
    "hidden_answer",
    "standard_answer",
    "proxy_answer",
    "task_id",
)
SEVERITY_ORDER = {"none": 0, "P3": 1, "P2": 2, "P1": 3, "P0": 4}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run VDS Workbench GPT-like LLM quality gate.")
    parser.add_argument("--suite", choices=("quick", "full", "api", "ui"), default="quick")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--provider", choices=("auto", "deepseek", "openai"), default="auto")
    parser.add_argument("--case-file", default=str(DEFAULT_CASE_FILE))
    parser.add_argument("--output-dir")
    parser.add_argument("--doc-dir", default=str(DEFAULT_DOC_DIR))
    parser.add_argument("--run-id")
    parser.add_argument("--fail-on", choices=("p0", "p1", "score"), default="p0")
    parser.add_argument(
        "--allow-mock-judge",
        action="store_true",
        help="Test-only escape hatch. Formal quality-gate runs must use a real provider.",
    )
    args = parser.parse_args()

    configure_provider(args.provider)
    run_id = args.run_id or build_run_id(args.suite)
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_ROOT / run_id
    output_dir = output_dir if output_dir.is_absolute() else REPO_ROOT / output_dir
    doc_dir = Path(args.doc_dir) if Path(args.doc_dir).is_absolute() else REPO_ROOT / args.doc_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    doc_dir.mkdir(parents=True, exist_ok=True)

    cases = select_cases(load_cases(Path(args.case_file)), args.suite)
    if not cases:
        raise SystemExit(f"No cases selected for suite={args.suite}.")
    judge_client = load_quality_judge_client(allow_mock=args.allow_mock_judge)
    summary = run_quality_gate(
        cases=cases,
        base_url=args.base_url.rstrip("/"),
        output_dir=output_dir,
        doc_dir=doc_dir,
        run_id=run_id,
        suite=args.suite,
        judge_client=judge_client,
    )
    print(json.dumps({"run_id": run_id, "output_dir": str(output_dir), "status": summary["status"]}, ensure_ascii=False))
    if should_fail(summary, args.fail_on):
        raise SystemExit(1)


def build_run_id(suite: str) -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M") + f"-{suite}-gpt-like"


def configure_provider(provider: str) -> None:
    if provider != "auto":
        os.environ["VDS_LLM_PROVIDER"] = provider
        return
    if os.environ.get("VDS_LLM_PROVIDER"):
        return
    if os.environ.get("DEEPSEEK_API_KEY"):
        os.environ["VDS_LLM_PROVIDER"] = "deepseek"
    elif os.environ.get("OPENAI_API_KEY"):
        os.environ["VDS_LLM_PROVIDER"] = "openai"


def load_quality_judge_client(*, allow_mock: bool = False) -> Any:
    from data_agent_core.llm.client import MissingLLMConfigError, MockLLMClient, load_llm_client_from_env

    try:
        client = load_llm_client_from_env()
    except MissingLLMConfigError as exc:
        raise SystemExit(
            "A real LLM judge is required. Set VDS_LLM_PROVIDER=deepseek/openai and provide the matching API key."
        ) from exc
    if isinstance(client, MockLLMClient) and not allow_mock:
        raise SystemExit("VDS_LLM_PROVIDER=mock is only allowed for unit tests, not formal GPT-like quality gates.")
    return client


def load_cases(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL case at {path}:{line_number}") from exc
        if not isinstance(row, dict) or not row.get("id") or not row.get("question"):
            raise ValueError(f"Case at {path}:{line_number} must include id and question.")
        rows.append(row)
    return rows


def select_cases(cases: list[dict[str, Any]], suite: str) -> list[dict[str, Any]]:
    if suite == "full":
        return list(cases)
    selected = []
    for case in cases:
        tags = {str(tag) for tag in case.get("tags", [])}
        case_suite = str(case.get("suite") or "full")
        if suite == "quick" and case_suite == "quick":
            selected.append(case)
        elif suite in tags:
            selected.append(case)
    return selected


def run_quality_gate(
    *,
    cases: list[dict[str, Any]],
    base_url: str,
    output_dir: Path,
    doc_dir: Path,
    run_id: str,
    suite: str,
    judge_client: Any,
) -> dict[str, Any]:
    started = time.perf_counter()
    owner_id = "llm_quality_gate_" + uuid.uuid4().hex[:10]
    created_conversations: list[str] = []
    created_projects: list[str] = []
    with tempfile.TemporaryDirectory(prefix="vds_quality_gate_") as temp_dir:
        fixture_context = prepare_fixture_contexts(
            base_url=base_url,
            needed={str(case.get("dataset_fixture") or "no_dataset") for case in cases},
            temp_root=Path(temp_dir),
            created_projects=created_projects,
        )
        case_results = []
        for case in cases:
            result = run_one_case(
                base_url=base_url,
                case=case,
                owner_id=owner_id,
                fixture_context=fixture_context,
                judge_client=judge_client,
            )
            if result.get("conversation_id"):
                created_conversations.append(str(result["conversation_id"]))
            case_results.append(result)

    cleanup_runtime_artifacts(base_url, created_conversations, created_projects)
    summary = build_summary(
        run_id=run_id,
        suite=suite,
        base_url=base_url,
        output_dir=output_dir,
        cases=case_results,
        elapsed_seconds=round(time.perf_counter() - started, 3),
    )
    write_quality_artifacts(summary, case_results, output_dir, doc_dir)
    return summary


def prepare_fixture_contexts(
    *,
    base_url: str,
    needed: set[str],
    temp_root: Path,
    created_projects: list[str],
) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {"no_dataset": {"dataset_id": "", "project_id": ""}}
    for fixture in sorted(needed):
        if fixture in contexts:
            continue
        if fixture == "sales_cn":
            contexts[fixture] = upload_single_fixture(base_url, temp_root, "sales_cn.csv", sales_csv())
        elif fixture == "dirty_retail":
            contexts[fixture] = upload_single_fixture(base_url, temp_root, "dirty_retail.csv", dirty_retail_csv())
        elif fixture == "payments_context":
            contexts[fixture] = upload_single_fixture(base_url, temp_root, "payments.csv", payments_csv())
        elif fixture == "orders_customers":
            contexts[fixture] = upload_batch_fixture(
                base_url,
                temp_root,
                {
                    "orders.csv": orders_csv(),
                    "customers.csv": customers_csv(),
                },
            )
        elif fixture == "project_smoke":
            project = request_json(
                "POST",
                base_url + "/api/data-agent/projects",
                {
                    "name": "LLM Quality Gate Project",
                    "description": "Temporary quality-gate project.",
                    "instructions": "项目说明：这是 GPT-like 自动化测试项目，只能使用本项目上下文回答。",
                },
            )
            project_id = str((project.get("project") or {}).get("project_id") or project.get("project_id") or "")
            if project_id:
                created_projects.append(project_id)
            contexts[fixture] = {"dataset_id": "", "project_id": project_id}
        else:
            raise ValueError(f"Unsupported dataset_fixture: {fixture}")
    return contexts


def upload_single_fixture(base_url: str, temp_root: Path, filename: str, content: str) -> dict[str, Any]:
    path = temp_root / filename
    path.write_text(content, encoding="utf-8")
    upload = multipart_upload(base_url + "/api/data-agent/upload", [("file", path, filename)])
    dataset_id = str(upload.get("dataset_id") or "")
    if not upload.get("success") or not dataset_id:
        raise RuntimeError(f"Fixture upload failed for {filename}: {json.dumps(upload, ensure_ascii=False)[:500]}")
    return {"dataset_id": dataset_id, "project_id": ""}


def upload_batch_fixture(base_url: str, temp_root: Path, files: dict[str, str]) -> dict[str, Any]:
    upload_files = []
    for filename, content in files.items():
        path = temp_root / filename
        path.write_text(content, encoding="utf-8")
        upload_files.append(("files", path, filename))
    upload = multipart_upload(base_url + "/api/data-agent/upload-batch", upload_files)
    dataset_id = str(upload.get("dataset_id") or "")
    if not upload.get("success") or not dataset_id:
        raise RuntimeError(f"Batch fixture upload failed: {json.dumps(upload, ensure_ascii=False)[:500]}")
    return {"dataset_id": dataset_id, "project_id": ""}


def run_one_case(
    *,
    base_url: str,
    case: dict[str, Any],
    owner_id: str,
    fixture_context: dict[str, dict[str, Any]],
    judge_client: Any,
) -> dict[str, Any]:
    started = time.perf_counter()
    fixture = str(case.get("dataset_fixture") or "no_dataset")
    context = fixture_context.get(fixture, {})
    payload = {
        "question": str(case.get("question") or ""),
        "dataset_id": str(context.get("dataset_id") or ""),
        "project_id": str(context.get("project_id") or ""),
        "owner_id": owner_id,
        "agent_mode": "multi_agent",
        "execution_mode": "dual",
    }
    response = request_json("POST", base_url + "/api/data-agent/message", payload, timeout=180)
    public_response = public_response_snapshot(response)
    deterministic = deterministic_checks(case, public_response)
    judgement = judge_public_response(case, public_response, deterministic, judge_client)
    severity = max_severity([deterministic.get("severity", "none"), judgement.get("severity", "none")])
    overall = final_overall(deterministic, judgement)
    return {
        "case_id": case["id"],
        "suite": case.get("suite", ""),
        "tags": case.get("tags", []),
        "question": case.get("question", ""),
        "dataset_fixture": fixture,
        "capability_family": case.get("capability_family", ""),
        "expected_answer_type": case.get("expected_answer_type", ""),
        "gpt_like_expectation": case.get("gpt_like_expectation", ""),
        "conversation_id": response.get("conversation_id", ""),
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "public_response": public_response,
        "deterministic": deterministic,
        "llm_judgement": judgement,
        "severity": severity,
        "overall": overall,
    }


def public_response_snapshot(response: dict[str, Any]) -> dict[str, Any]:
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    insight = response.get("insight") if isinstance(response.get("insight"), dict) else {}
    chart = response.get("chart") if isinstance(response.get("chart"), dict) else {}
    process = response.get("process_view_v2") if isinstance(response.get("process_view_v2"), dict) else {}
    rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    steps = process.get("steps") if isinstance(process.get("steps"), list) else []
    return {
        "success": bool(response.get("success")),
        "answer_type": response.get("answer_type", ""),
        "answer": truncate_text(response.get("answer", ""), limit=4000),
        "result": {
            "columns": result.get("columns") if isinstance(result.get("columns"), list) else [],
            "rows_head": rows[:5],
            "value": result.get("value"),
        },
        "chart": {
            "present": bool(chart),
            "type": chart.get("type") or chart.get("chart_type") if chart else "",
            "title": chart.get("title", "") if chart else "",
        },
        "insight": {
            "summary": truncate_text(insight.get("summary", ""), limit=1200),
            "next_questions": insight.get("next_questions", [])[:3] if isinstance(insight.get("next_questions"), list) else [],
            "business_suggestions": insight.get("business_suggestions", [])[:2]
            if isinstance(insight.get("business_suggestions"), list)
            else [],
        },
        "process": {
            "mode": process.get("mode", ""),
            "summary": truncate_text(process.get("summary", ""), limit=1200),
            "step_titles": [str(step.get("title", "")) for step in steps[:8] if isinstance(step, dict)],
        },
        "warnings": response.get("warnings", []) if isinstance(response.get("warnings"), list) else [],
        "errors": response.get("errors", []) if isinstance(response.get("errors"), list) else [],
    }


def deterministic_checks(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    serialized = json.dumps(response, ensure_ascii=False, default=str)
    answer = str(response.get("answer") or "")
    expected_answer_type = str(case.get("expected_answer_type") or "")
    if not response.get("success"):
        issues.append({"severity": "P1", "issue": "success_false"})
    if expected_answer_type and response.get("answer_type") != expected_answer_type:
        issues.append(
            {
                "severity": str(case.get("severity_on_fail") or "P1"),
                "issue": f"answer_type_mismatch:{response.get('answer_type')} != {expected_answer_type}",
            }
        )
    if "Not Applicable" in answer or answer.strip() == "Not Applicable":
        issues.append({"severity": str(case.get("severity_on_fail") or "P1"), "issue": "unexpected_not_applicable"})
    for token in case.get("must_include", []) or []:
        if str(token) not in serialized:
            issues.append({"severity": str(case.get("severity_on_fail") or "P1"), "issue": f"missing_required:{token}"})
    for token in case.get("must_not_include", []) or []:
        if str(token) in serialized:
            severity = "P0" if _forbidden_token_is_internal(str(token)) else str(case.get("severity_on_fail") or "P1")
            issues.append({"severity": severity, "issue": f"forbidden_token:{token}"})
    if "No specific data question detected" in serialized:
        issues.append({"severity": "P0", "issue": "not_applicable_template_leaked"})
    if looks_like_raw_detail_dump(answer):
        issues.append({"severity": "P0", "issue": "raw_detail_dump_risk"})
    severity = max_severity([item["severity"] for item in issues] or ["none"])
    return {
        "passed": not issues,
        "severity": severity,
        "issues": issues,
    }


def _forbidden_token_is_internal(token: str) -> bool:
    lowered = token.lower()
    return any(marker in lowered for marker in ("standard", "task_id", "raw", "hidden", "proxy", "api_key"))


def judge_public_response(
    case: dict[str, Any],
    public_response: dict[str, Any],
    deterministic: dict[str, Any],
    judge_client: Any,
) -> dict[str, Any]:
    payload = {
        "case": {
            "id": case.get("id"),
            "question": case.get("question"),
            "dataset_fixture": case.get("dataset_fixture"),
            "expected_answer_type": case.get("expected_answer_type", ""),
            "capability_family": case.get("capability_family", ""),
            "gpt_like_expectation": case.get("gpt_like_expectation", ""),
        },
        "deterministic_checks": deterministic,
        "public_response": public_response,
    }
    assert_judge_payload_is_safe(payload)
    messages = [
        {
            "role": "system",
            "content": (
                "你是 VDS Workbench 的严格 GPT-like 质量评审。只评估用户可见输出是否像 ChatGPT Data Analysis "
                "一样真正解决用户问题。不要要求或输出推理过程。只返回 JSON 对象。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请按 0-5 分评分：problem_understanding, data_grounding, answer_usefulness, "
                "gpt_like_structure, safety_boundary。"
                "同时返回 overall=pass|risk|fail, severity=P0|P1|P2|P3|none, reason, required_followup。"
                "如果 deterministic_checks 已有 P0/P1，不能判为 pass。输入如下：\n"
                + json.dumps(payload, ensure_ascii=False)
            ),
        },
    ]
    try:
        raw = judge_client.complete_json(messages, temperature=0.0)
    except Exception as exc:  # pragma: no cover - network/provider dependent.
        return {
            "overall": "fail",
            "severity": "P1",
            "reason": f"LLM judge failed: {type(exc).__name__}: {str(exc)[:240]}",
            "required_followup": "Rerun with a working LLM judge.",
            "scores": empty_scores(),
        }
    return normalize_judgement(raw)


def normalize_judgement(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    scores = {
        key: clamp_score(raw.get(key))
        for key in ("problem_understanding", "data_grounding", "answer_usefulness", "gpt_like_structure", "safety_boundary")
    }
    overall = str(raw.get("overall") or "risk").lower()
    if overall not in {"pass", "risk", "fail"}:
        overall = "risk"
    severity = str(raw.get("severity") or "none")
    if severity not in SEVERITY_ORDER:
        severity = "P2" if overall == "risk" else "P1" if overall == "fail" else "none"
    if overall == "fail" and severity == "none":
        severity = "P1"
    return {
        "overall": overall,
        "severity": severity,
        "reason": truncate_text(raw.get("reason", ""), limit=1000),
        "required_followup": truncate_text(raw.get("required_followup", ""), limit=1000),
        "scores": scores,
    }


def empty_scores() -> dict[str, float]:
    return {
        "problem_understanding": 0.0,
        "data_grounding": 0.0,
        "answer_usefulness": 0.0,
        "gpt_like_structure": 0.0,
        "safety_boundary": 0.0,
    }


def clamp_score(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(5.0, number)), 2)


def final_overall(deterministic: dict[str, Any], judgement: dict[str, Any]) -> str:
    severity = max_severity([deterministic.get("severity", "none"), judgement.get("severity", "none")])
    if severity in {"P0", "P1"}:
        return "fail"
    if severity in {"P2", "P3"}:
        return "risk"
    return str(judgement.get("overall") or "pass")


def build_summary(
    *,
    run_id: str,
    suite: str,
    base_url: str,
    output_dir: Path,
    cases: list[dict[str, Any]],
    elapsed_seconds: float,
) -> dict[str, Any]:
    counts = {
        "case_count": len(cases),
        "pass_count": sum(1 for case in cases if case["overall"] == "pass"),
        "risk_count": sum(1 for case in cases if case["overall"] == "risk"),
        "fail_count": sum(1 for case in cases if case["overall"] == "fail"),
        "p0_count": sum(1 for case in cases if case["severity"] == "P0"),
        "p1_count": sum(1 for case in cases if case["severity"] == "P1"),
        "p2_count": sum(1 for case in cases if case["severity"] == "P2"),
        "p3_count": sum(1 for case in cases if case["severity"] == "P3"),
    }
    status = "fail" if counts["p0_count"] or counts["p1_count"] else "risk" if counts["risk_count"] else "pass"
    return {
        "run_id": run_id,
        "suite": suite,
        "base_url": base_url,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": elapsed_seconds,
        "provider": provider_summary(),
        "repo": repo_state(),
        "output_dir": str(output_dir),
        "status": status,
        "counts": counts,
        "case_ids": [case["case_id"] for case in cases],
    }


def provider_summary() -> dict[str, Any]:
    provider = os.environ.get("VDS_LLM_PROVIDER", "")
    return {
        "provider": provider,
        "openai_model": os.environ.get("OPENAI_MODEL", ""),
        "deepseek_model": os.environ.get("DEEPSEEK_MODEL", ""),
        "openai_key_present": bool(os.environ.get("OPENAI_API_KEY")),
        "deepseek_key_present": bool(os.environ.get("DEEPSEEK_API_KEY")),
    }


def repo_state() -> dict[str, Any]:
    def git(args: list[str]) -> str:
        try:
            return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""

    return {
        "root": str(REPO_ROOT),
        "branch": git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "commit": git(["rev-parse", "HEAD"]),
        "status_short": git(["status", "--short"]),
    }


def write_quality_artifacts(summary: dict[str, Any], cases: list[dict[str, Any]], output_dir: Path, doc_dir: Path) -> None:
    write_json(output_dir / "summary.json", {**summary, "cases": cases})
    write_jsonl(output_dir / "responses.jsonl", response_rows(cases))
    write_jsonl(output_dir / "llm_judgements.jsonl", judgement_rows(cases))
    failures = [case for case in cases if case["overall"] != "pass" or case["severity"] in {"P0", "P1"}]
    (output_dir / "failures.md").write_text(failures_markdown(summary, failures), encoding="utf-8")
    report = report_markdown(summary, cases)
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    doc_path = doc_dir / f"{summary['run_id']}.md"
    doc_path.write_text(test_run_markdown(summary, cases), encoding="utf-8")


def response_rows(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": case["case_id"],
            "question": case["question"],
            "capability_family": case["capability_family"],
            "severity": case["severity"],
            "overall": case["overall"],
            "public_response": case["public_response"],
        }
        for case in cases
    ]


def judgement_rows(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": case["case_id"],
            "deterministic": case["deterministic"],
            "llm_judgement": case["llm_judgement"],
            "severity": case["severity"],
            "overall": case["overall"],
        }
        for case in cases
    ]


def report_markdown(summary: dict[str, Any], cases: list[dict[str, Any]]) -> str:
    lines = [
        f"# VDS GPT-like Quality Gate - {summary['run_id']}",
        "",
        f"- Suite: {summary['suite']}",
        f"- Status: {summary['status']}",
        f"- Base URL: {summary['base_url']}",
        f"- Generated at: {summary['generated_at']}",
        f"- Provider: {summary['provider']['provider']}",
        f"- Counts: {json.dumps(summary['counts'], ensure_ascii=False)}",
        "",
        "## Cases",
        "",
    ]
    for case in cases:
        lines.extend(case_markdown(case))
    return "\n".join(lines).rstrip() + "\n"


def failures_markdown(summary: dict[str, Any], failures: list[dict[str, Any]]) -> str:
    lines = [f"# Failures - {summary['run_id']}", ""]
    if not failures:
        lines.append("No failures or risks.")
    for case in failures:
        lines.extend(case_markdown(case))
    return "\n".join(lines).rstrip() + "\n"


def test_run_markdown(summary: dict[str, Any], cases: list[dict[str, Any]]) -> str:
    return report_markdown(summary, cases) + "\n## Test Run Documentation\n\nThis file is the required durable test evidence for this run.\n"


def case_markdown(case: dict[str, Any]) -> list[str]:
    deterministic_issues = ", ".join(item["issue"] for item in case["deterministic"].get("issues", [])) or "-"
    answer_excerpt = truncate_text(case["public_response"].get("answer", ""), limit=800).replace("\n", " ")
    return [
        f"### {case['case_id']} - {case['capability_family']}",
        "",
        f"- Overall: {case['overall']}",
        f"- Severity: {case['severity']}",
        f"- Question: {case['question']}",
        f"- Expected answer_type: {case.get('expected_answer_type') or '-'}",
        f"- Actual answer_type: {case['public_response'].get('answer_type') or '-'}",
        f"- Deterministic issues: {deterministic_issues}",
        f"- LLM reason: {case['llm_judgement'].get('reason') or '-'}",
        f"- Required follow-up: {case['llm_judgement'].get('required_followup') or '-'}",
        f"- Answer excerpt: {answer_excerpt}",
        "",
    ]


def should_fail(summary: dict[str, Any], fail_on: str) -> bool:
    counts = summary["counts"]
    if fail_on == "p0":
        return counts["p0_count"] > 0
    if fail_on == "p1":
        return counts["p0_count"] > 0 or counts["p1_count"] > 0
    return summary["status"] != "pass"


def max_severity(values: list[str]) -> str:
    return max((value if value in SEVERITY_ORDER else "none" for value in values), key=lambda item: SEVERITY_ORDER[item])


def looks_like_raw_detail_dump(answer: str) -> bool:
    if len(answer) < 300:
        return False
    comma_rows = sum(1 for line in answer.splitlines() if line.count(",") >= 5)
    compact_date_values = len(re.findall(r"\d{4}-\d{2}-\d{2}[^,\n]*,\s*[-+]?\d", answer))
    return comma_rows >= 4 or compact_date_values >= 4


def assert_judge_payload_is_safe(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False).lower()
    for marker in FORBIDDEN_REPORT_MARKERS:
        if marker in text:
            raise ValueError(f"Forbidden marker in LLM judge payload: {marker}")


def request_json(method: str, url: str, payload: dict[str, Any] | None = None, timeout: int = 60) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {} if payload is None else {"Content-Type": "application/json; charset=utf-8"}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"success": False, "http_status": exc.code, "errors": [{"error_message": body[:500]}]}


def multipart_upload(url: str, files: list[tuple[str, Path, str]]) -> dict[str, Any]:
    boundary = "----vdsquality" + uuid.uuid4().hex
    body = bytearray()
    for field, path, filename in files:
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode())
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
        body.extend(path.read_bytes())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(url, data=bytes(body), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def cleanup_runtime_artifacts(base_url: str, conversation_ids: list[str], project_ids: list[str]) -> None:
    for conversation_id in dict.fromkeys(conversation_ids):
        request_json("DELETE", f"{base_url}/api/data-agent/conversations/{conversation_id}", timeout=20)
    for project_id in dict.fromkeys(project_ids):
        request_json("DELETE", f"{base_url}/api/data-agent/projects/{project_id}", timeout=20)


def sales_csv() -> str:
    return (
        "日期,城市,区域,销售额,订单数,客户\n"
        "2026-01-01,上海,华东,100,2,A\n"
        "2026-01-02,北京,华北,150,3,B\n"
        "2026-02-01,上海,华东,250,1,C\n"
        "2026-02-05,广州,华南,80,2,D\n"
        "2026-03-01,北京,华北,50,1,E\n"
    )


def dirty_retail_csv() -> str:
    return (
        "InvoiceNo,StockCode,Description,Quantity,InvoiceDate,UnitPrice,CustomerID,Country\n"
        "536365,85123A,WHITE HANGING HEART T-LIGHT HOLDER,6,2026-01-01,2.55,17850,United Kingdom\n"
        "536365,85123A,WHITE HANGING HEART T-LIGHT HOLDER,6,2026-01-01,2.55,17850,United Kingdom\n"
        "536366,22633,HAND WARMER UNION JACK,-1,bad-date,1.85,,United Kingdom\n"
        "536367,22632,HAND WARMER RED POLKA DOT,10000,2026-01-03,0,13047,United Kingdom\n"
    )


def orders_csv() -> str:
    return (
        "order_id,customer_id,amount,order_month\n"
        "O1,C1,100,2026-01\n"
        "O2,C2,200,2026-01\n"
        "O3,C1,150,2026-02\n"
        "O4,C3,50,2026-02\n"
        "O5,C4,300,2026-03\n"
    )


def customers_csv() -> str:
    return (
        "customer_id,segment,city\n"
        "C1,VIP,Shanghai\n"
        "C2,Normal,Beijing\n"
        "C3,Normal,Guangzhou\n"
        "C4,VIP,Shanghai\n"
    )


def payments_csv() -> str:
    return (
        "psp_reference,merchant,card_scheme,year,hour_of_day,minute_of_hour,day_of_year,is_credit,eur_amount,ip_country,issuing_country,device_type,has_fraudulent_dispute,is_refused_by_adyen\n"
        "P1,Crossfit_Hanna,visa,2026,10,1,10,true,120.5,NL,NL,desktop,false,false\n"
        "P2,Rafa_AI,mc,2026,11,2,10,false,80,IT,IT,mobile,true,false\n"
        "P3,Crossfit_Hanna,visa,2026,12,3,11,true,200,NL,NL,mobile,false,false\n"
        "P4,Belles_cookbook_store,amex,2026,13,4,12,true,30,BE,BE,desktop,false,true\n"
        "P5,Rafa_AI,visa,2026,14,5,12,false,90,IT,IT,mobile,false,false\n"
    )


def truncate_text(value: Any, *, limit: int) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
