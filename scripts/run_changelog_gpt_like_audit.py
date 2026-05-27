#!/usr/bin/env python3
"""Audit CHANGELOG_AI.md records against VDS GPT-like acceptance redlines."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CHANGELOG = REPO_ROOT / "CHANGELOG_AI.md"
DEFAULT_DOC_DIR = REPO_ROOT / "docs" / "test-runs"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "outputs" / "llm_quality_gate"
TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2} [A-Z]{2,5})$", re.M)
SEVERITY_ORDER = {"none": 0, "P3": 1, "P2": 2, "P1": 3, "P0": 4}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit CHANGELOG_AI.md GPT-like evidence.")
    parser.add_argument("--changelog", default=str(CHANGELOG))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--provider", choices=("auto", "deepseek", "openai"), default="auto")
    parser.add_argument("--output-dir")
    parser.add_argument("--doc-dir", default=str(DEFAULT_DOC_DIR))
    parser.add_argument("--run-id")
    parser.add_argument("--fail-on", choices=("p0", "p1", "score"), default="p0")
    parser.add_argument("--allow-mock-judge", action="store_true", help="Test-only escape hatch.")
    args = parser.parse_args()

    configure_provider(args.provider)
    run_id = args.run_id or datetime.now().strftime("%Y-%m-%d-%H%M") + "-changelog-gpt-like"
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_ROOT / run_id
    output_dir = output_dir if output_dir.is_absolute() else REPO_ROOT / output_dir
    doc_dir = Path(args.doc_dir) if Path(args.doc_dir).is_absolute() else REPO_ROOT / args.doc_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    doc_dir.mkdir(parents=True, exist_ok=True)

    judge_client = load_quality_judge_client(allow_mock=args.allow_mock_judge)
    report = run_changelog_audit(
        changelog_path=Path(args.changelog),
        limit=args.limit,
        output_dir=output_dir,
        doc_dir=doc_dir,
        run_id=run_id,
        judge_client=judge_client,
    )
    print(json.dumps({"run_id": run_id, "output_dir": str(output_dir), "status": report["status"]}, ensure_ascii=False))
    if should_fail(report, args.fail_on):
        raise SystemExit(1)


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
        raise SystemExit("VDS_LLM_PROVIDER=mock is only allowed for unit tests, not formal changelog audits.")
    return client


def run_changelog_audit(
    *,
    changelog_path: Path,
    limit: int,
    output_dir: Path,
    doc_dir: Path,
    run_id: str,
    judge_client: Any,
) -> dict[str, Any]:
    started = time.perf_counter()
    records = parse_changelog_records(changelog_path.read_text(encoding="utf-8"))[:limit]
    rows = [audit_record(record, judge_client) for record in records]
    counts = {
        "record_count": len(rows),
        "pass_count": sum(1 for row in rows if row["overall"] == "pass"),
        "risk_count": sum(1 for row in rows if row["overall"] == "risk"),
        "fail_count": sum(1 for row in rows if row["overall"] == "fail"),
        "p0_count": sum(1 for row in rows if row["severity"] == "P0"),
        "p1_count": sum(1 for row in rows if row["severity"] == "P1"),
        "p2_count": sum(1 for row in rows if row["severity"] == "P2"),
        "p3_count": sum(1 for row in rows if row["severity"] == "P3"),
    }
    status = "fail" if counts["p0_count"] or counts["p1_count"] else "risk" if counts["risk_count"] else "pass"
    report = {
        "run_id": run_id,
        "suite": "changelog",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "provider": provider_summary(),
        "repo": repo_state(),
        "changelog_path": str(changelog_path),
        "output_dir": str(output_dir),
        "status": status,
        "counts": counts,
        "records": rows,
    }
    write_json(output_dir / "summary.json", report)
    write_jsonl(output_dir / "changelog_audit.jsonl", rows)
    markdown = changelog_audit_markdown(report)
    (output_dir / "report.md").write_text(markdown, encoding="utf-8")
    (output_dir / "failures.md").write_text(changelog_audit_markdown({**report, "records": [row for row in rows if row["overall"] != "pass"]}), encoding="utf-8")
    (doc_dir / f"{run_id}.md").write_text(markdown + "\n## Test Run Documentation\n\nThis file is the required durable changelog-audit evidence.\n", encoding="utf-8")
    return report


def parse_changelog_records(text: str) -> list[dict[str, str]]:
    matches = list(TIMESTAMP_RE.finditer(text))
    records: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        records.append({"timestamp": match.group(1), "body": body})
    records.reverse()
    return records


def audit_record(record: dict[str, str], judge_client: Any) -> dict[str, Any]:
    deterministic = deterministic_record_audit(record)
    judgement = judge_changelog_record(record, deterministic, judge_client)
    severity = max_severity([deterministic["severity"], judgement["severity"]])
    overall = "fail" if severity in {"P0", "P1"} else "risk" if severity in {"P2", "P3"} else judgement["overall"]
    return {
        "timestamp": record["timestamp"],
        "title": record_title(record["body"]),
        "deterministic": deterministic,
        "llm_judgement": judgement,
        "severity": severity,
        "overall": overall,
    }


def deterministic_record_audit(record: dict[str, str]) -> dict[str, Any]:
    body = record["body"]
    issues: list[dict[str, str]] = []
    required_sections = (
        "### 本次目标",
        "### 修改文件",
        "### 修改内容",
        "### 测试方式",
        "### 测试结果",
        "### 是否已同步 README",
    )
    for section in required_sections:
        if section not in body or not section_has_content(body, section):
            issues.append({"severity": "P1", "issue": f"missing_or_empty_section:{section}"})
    if not TIMESTAMP_RE.match(record["timestamp"]):
        issues.append({"severity": "P1", "issue": "timestamp_not_minute_precision"})
    if not re.search(r"能力族|泛化|同类|非 Benchmark|用户体验|GPT-like|ChatGPT", body):
        issues.append({"severity": "P2", "issue": "missing_capability_or_experience_framing"})
    if not re.search(r"GPT-like|ChatGPT|GPT / ChatGPT|标准 GPT|冻结参考", body):
        issues.append({"severity": "P1", "issue": "missing_gpt_like_parity_evidence"})
    if not re.search(r"docs/test-runs|test-runs/", body):
        issues.append({"severity": "P1", "issue": "missing_test_run_document_reference"})
    if re.search(r"Browser|DOM|API smoke|Runtime|runtime|curl|127\.0\.0\.1|/workbench", body) is None and "前端" in body:
        issues.append({"severity": "P2", "issue": "missing_runtime_or_browser_evidence_for_frontend_change"})
    if "是否已同步 README" in body and not re.search(r"README", body):
        issues.append({"severity": "P2", "issue": "missing_readme_sync_statement"})
    severity = max_severity([item["severity"] for item in issues] or ["none"])
    return {"passed": not issues, "severity": severity, "issues": issues}


def judge_changelog_record(record: dict[str, str], deterministic: dict[str, Any], judge_client: Any) -> dict[str, Any]:
    payload = {
        "timestamp": record["timestamp"],
        "deterministic_checks": deterministic,
        "record_excerpt": truncate_text(record["body"], limit=6000),
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是 VDS 项目的 changelog 验收审计员。只判断记录是否证明改动达到 GPT-like、"
                "能力族、非退步和测试文档红线。不要输出推理过程，只返回 JSON。"
            ),
        },
        {
            "role": "user",
            "content": (
                "返回 JSON: overall=pass|risk|fail, severity=P0|P1|P2|P3|none, reason, required_followup。"
                "如果没有 docs/test-runs 测试文档证据，不能判为 pass。输入：\n"
                + json.dumps(payload, ensure_ascii=False)
            ),
        },
    ]
    try:
        raw = judge_client.complete_json(messages, temperature=0.0)
    except Exception as exc:  # pragma: no cover - provider dependent.
        return {
            "overall": "fail",
            "severity": "P1",
            "reason": f"LLM changelog judge failed: {type(exc).__name__}: {str(exc)[:240]}",
            "required_followup": "Rerun with a working LLM judge.",
        }
    return normalize_judgement(raw)


def normalize_judgement(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
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
    }


def record_title(body: str) -> str:
    target = extract_section(body, "### 本次目标")
    return truncate_text(target.replace("\n", " "), limit=120) or "Untitled changelog record"


def section_has_content(body: str, section: str) -> bool:
    return bool(extract_section(body, section).strip())


def extract_section(body: str, section: str) -> str:
    if section not in body:
        return ""
    after = body.split(section, 1)[1]
    next_section = re.search(r"\n### ", after)
    if next_section:
        after = after[: next_section.start()]
    return after.strip()


def changelog_audit_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Changelog GPT-like Audit - {report['run_id']}",
        "",
        f"- Status: {report['status']}",
        f"- Generated at: {report['generated_at']}",
        f"- Provider: {report['provider']['provider']}",
        f"- Counts: {json.dumps(report['counts'], ensure_ascii=False)}",
        "",
    ]
    for row in report["records"]:
        issues = ", ".join(issue["issue"] for issue in row["deterministic"].get("issues", [])) or "-"
        lines.extend(
            [
                f"## {row['timestamp']} - {row['overall']} / {row['severity']}",
                "",
                f"- Title: {row['title']}",
                f"- Deterministic issues: {issues}",
                f"- LLM reason: {row['llm_judgement'].get('reason') or '-'}",
                f"- Required follow-up: {row['llm_judgement'].get('required_followup') or '-'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def should_fail(report: dict[str, Any], fail_on: str) -> bool:
    counts = report["counts"]
    if fail_on == "p0":
        return counts["p0_count"] > 0
    if fail_on == "p1":
        return counts["p0_count"] > 0 or counts["p1_count"] > 0
    return report["status"] != "pass"


def max_severity(values: list[str]) -> str:
    return max((value if value in SEVERITY_ORDER else "none" for value in values), key=lambda item: SEVERITY_ORDER[item])


def provider_summary() -> dict[str, Any]:
    return {
        "provider": os.environ.get("VDS_LLM_PROVIDER", ""),
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
