"""Runner for real-user manifest cases and conversation flows."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from scripts.real_user_eval.manifest import (
    ConversationCase,
    ManifestCase,
    dataset_file_paths,
    manifest_cases,
    manifest_conversations,
)
from scripts.real_user_eval.oracle import evaluate_oracle
from scripts.real_user_eval.targets import AgentResult, EvalTarget, TargetRequest
from scripts.run_generic_dataset_eval import comparison_markdown, write_json, write_jsonl
from scripts.score_comparison_answers import WEIGHTS, score_markdown, score_rows, summarize


DEFAULT_SCORE_JUDGE = "llm"


def run_manifest(
    manifest: Mapping[str, Any],
    target: EvalTarget,
    *,
    output_dir: Path,
    max_variants_per_case: int | None = None,
    include_conversations: bool = True,
    score_judge: str = DEFAULT_SCORE_JUDGE,
    min_acceptable: float = 75.0,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    raw_results: list[dict[str, Any]] = []
    dataset_id_cache: dict[str, str] = {}

    for case in manifest_cases(manifest):
        for row, raw in run_case_variants(
            manifest,
            case,
            target,
            dataset_id_cache=dataset_id_cache,
            max_variants_per_case=max_variants_per_case,
        ):
            rows.append(row)
            raw_results.append(raw)
    if include_conversations:
        for conversation in manifest_conversations(manifest):
            for row, raw in run_conversation(manifest, conversation, target, dataset_id_cache=dataset_id_cache):
                rows.append(row)
                raw_results.append(raw)

    actual_judge, scored_rows = score_rows(rows, judge=score_judge, min_acceptable=min_acceptable)
    scored_rows = _merge_runtime_gate_fields_into_scored_rows(rows, scored_rows)
    scored_summary = summarize(scored_rows)
    runtime_gate_summary = _runtime_gate_summary(rows, scored_rows)
    summary = {
        "name": "real_user_case_eval",
        "dataset_name": manifest.get("name") or "real_user_case_manifest",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "case_count": len(rows),
        "passed": int(scored_summary.get("candidate_acceptable_count") or 0),
        "failed": max(0, len(rows) - int(scored_summary.get("candidate_acceptable_count") or 0)),
        "target": getattr(target, "target_name", target.__class__.__name__),
        "acceptance_source": f"comparison_scored:{actual_judge}",
        "runtime_acceptance_source": f"semantic_oracle_runtime+comparison_scored:{actual_judge}",
        **runtime_gate_summary,
        "scored_summary": scored_summary,
        "comparison": rows,
        "candidate_score": _candidate_score_from_scored_summary(scored_summary),
        "candidate_answer_generation": {
            "provider": getattr(target, "target_name", target.__class__.__name__),
            "model": "n/a",
            "formal_candidate_answers": True,
            "judge_mode": actual_judge,
        },
        "standard_answer_generation": {
            "source": "direct_computation",
            "label": "oracle",
            "model": "duckdb/literal",
            "policy": "Direct-computation oracle generated from source files; offline only, never sent to VDS.",
        },
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "summary.md").write_text(_runtime_gate_markdown(summary), encoding="utf-8")
    write_json(output_dir / "comparison.json", {"comparison": rows})
    write_jsonl(output_dir / "comparison.jsonl", rows)
    write_jsonl(output_dir / "agent_results.jsonl", raw_results)
    scored = {
        "source": str(output_dir / "comparison.jsonl"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "judge_mode": actual_judge,
        "weights": WEIGHTS,
        "min_acceptable": min_acceptable,
        "summary": scored_summary,
        "runtime_acceptance_source": summary["runtime_acceptance_source"],
        "runtime_gate_summary": runtime_gate_summary,
        "rows": scored_rows,
    }
    write_jsonl(output_dir / "failure_index.jsonl", _failure_rows_from_scored_rows(rows, scored_rows))
    (output_dir / "comparison.md").write_text(
        comparison_markdown(summary) + "\n\n" + _runtime_gate_markdown(summary),
        encoding="utf-8",
    )
    write_json(output_dir / "comparison_scored.json", scored)
    write_jsonl(output_dir / "comparison_scored.jsonl", scored_rows)
    (output_dir / "comparison_scored.md").write_text(score_markdown(scored), encoding="utf-8")
    return summary


def run_case_variants(
    manifest: Mapping[str, Any],
    case: ManifestCase,
    target: EvalTarget,
    *,
    dataset_id_cache: dict[str, str] | None = None,
    max_variants_per_case: int | None = None,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    files = dataset_file_paths(manifest, case.dataset)
    dataset_id_cache = dataset_id_cache if dataset_id_cache is not None else {}
    oracle = evaluate_oracle(
        oracle_type=case.oracle_type,
        oracle_query_or_formula=case.oracle_query_or_formula,
        file_paths=files,
        table_names=_dataset_table_names(manifest, case.dataset),
    )
    variants = list(case.question_variants)
    if max_variants_per_case is not None:
        variants = variants[: max(0, max_variants_per_case)]
    rows = []
    for index, question in enumerate(variants, start=1):
        cached_dataset_id = dataset_id_cache.get(case.dataset, "")
        result = target.run(
            TargetRequest(
                question=question,
                file_paths=tuple(files) if not cached_dataset_id else (),
                dataset_id=cached_dataset_id,
                metadata={"case_id": case.case_id, "variant_index": index},
            )
        )
        if result.dataset_id:
            dataset_id_cache[case.dataset] = result.dataset_id
        rows.append(
            _row_and_raw(
                case_id=f"{case.case_id}__v{index:02d}",
                category="real_user_variant",
                ae_group=f"real_user::{case.dataset}",
                question=question,
                expected_contract=case.expected_contract,
                expected_route=str(case.metadata.get("expected_route") or "real_user_api"),
                capability_family=case.capability_family,
                severity=case.severity,
                tags=case.tags,
                requirements=case.answer_requirements,
                oracle=oracle,
                result=result,
                metadata={"canonical_case_id": case.case_id, "dataset": case.dataset},
            )
        )
    return rows


def run_conversation(
    manifest: Mapping[str, Any],
    conversation: ConversationCase,
    target: EvalTarget,
    *,
    dataset_id_cache: dict[str, str] | None = None,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    files = dataset_file_paths(manifest, conversation.dataset)
    conversation_id = conversation.conversation_id
    dataset_id_cache = dataset_id_cache if dataset_id_cache is not None else {}
    dataset_id = dataset_id_cache.get(conversation.dataset, "")
    rows = []
    for index, turn in enumerate(conversation.turns, start=1):
        oracle = evaluate_oracle(
            oracle_type=turn.oracle_type,
            oracle_query_or_formula=turn.oracle_query_or_formula,
            file_paths=files,
            table_names=_dataset_table_names(manifest, conversation.dataset),
        )
        result = target.run(
            TargetRequest(
                question=turn.question,
                file_paths=tuple(files) if index == 1 and not dataset_id else (),
                dataset_id=dataset_id,
                conversation_id=conversation_id,
                metadata={"conversation_id": conversation_id, "turn_id": turn.turn_id},
            )
        )
        dataset_id = result.dataset_id or dataset_id
        if dataset_id:
            dataset_id_cache[conversation.dataset] = dataset_id
        rows.append(
            _row_and_raw(
                case_id=f"{conversation.conversation_id}__{turn.turn_id}",
                category="real_user_conversation",
                ae_group=f"conversation::{conversation.dataset}",
                question=turn.question,
                expected_contract=turn.expected_contract,
                expected_route="real_user_followup" if index > 1 else "real_user_api",
                capability_family=conversation.capability_family,
                severity=conversation.severity,
                tags=conversation.tags,
                requirements=turn.answer_requirements,
                oracle=oracle,
                result=result,
                metadata={
                    "dataset": conversation.dataset,
                    "conversation_id": conversation_id,
                    "turn_index": index,
                },
            )
        )
    return rows


def _row_and_raw(
    *,
    case_id: str,
    category: str,
    ae_group: str,
    question: str,
    expected_contract: Any,
    expected_route: str,
    capability_family: str,
    severity: str,
    tags: tuple[str, ...],
    requirements: Mapping[str, Any],
    oracle: Mapping[str, Any],
    result: AgentResult,
    metadata: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    missing_terms = _missing_terms(result.answer_text, requirements)
    number_checks = _number_checks(result.answer_text, requirements)
    failure_reasons: list[str] = []
    if not result.success:
        failure_reasons.extend(result.issues or ("target_failed",))
    if not result.answer_text.strip():
        failure_reasons.append("empty_answer")
    if missing_terms:
        failure_reasons.append("missing_required_terms")
    if not all(item["passed"] for item in number_checks):
        failure_reasons.append("missing_expected_numbers")
    semantic_passed = _semantic_passed(result.semantic_status)
    if result.semantic_status == "not_available":
        failure_reasons.append("semantic_evidence_missing")
    elif not semantic_passed:
        failure_reasons.append(f"semantic_not_passed:{result.semantic_status}")
    if result.contract_satisfied is False:
        failure_reasons.append("contract_not_satisfied")
    if result.oracle_passed is False:
        failure_reasons.append("runtime_oracle_failed")
    execution_failed = (not result.success) or not result.answer_text.strip()
    status = "execution_failed" if execution_failed else "response_collected"
    semantic_gate_status = _semantic_gate_status(result)
    oracle_gate_status = _oracle_gate_status(result)
    runtime_gate_passed = bool(result.success and semantic_passed and result.oracle_passed is True)
    runtime_semantic_evidence = _runtime_semantic_evidence(result)
    row = {
        "case_id": case_id,
        "ae_group": ae_group,
        "category": category,
        "difficulty_bucket": "complex" if severity in {"p0", "critical", "high"} else "ordinary",
        "capability_family": capability_family,
        "answerability": str(requirements.get("answerability") or "answerable"),
        "question": question,
        "expected_route": expected_route,
        "expected_contract": expected_contract,
        "standard_answer": oracle.get("answer") or expected_contract,
        "source_answer": oracle.get("answer") or expected_contract,
        "standard_answer_source": "direct_computation",
        "source_answer_origin": "direct_computation",
        "reference_answer_label": "reference",
        "standard_answer_model": str(oracle.get("oracle_type") or "oracle"),
        "standard_answer_policy": "Direct-computation oracle; offline only and not sent to Agent.",
        "candidate_answer": result.answer_text,
        "comparison_status": status,
        "transport_success": result.success,
        "service_success": result.success,
        "semantic_status": result.semantic_status,
        "semantic_passed": semantic_passed,
        "semantic_gate_status": semantic_gate_status,
        "contract_satisfied": result.contract_satisfied,
        "contract_family": result.contract_family,
        "violations": list(result.violations),
        "violation_codes": _violation_codes(result),
        "contract_report": dict(result.contract_report),
        "runtime_oracle_result": dict(result.oracle_result),
        "oracle_available": result.oracle_available,
        "oracle_passed": result.oracle_passed,
        "oracle_gate_status": oracle_gate_status,
        "oracle_issue_codes": list(result.oracle_issue_codes),
        "runtime_gate_passed": runtime_gate_passed,
        "semantic_evidence_available": result.semantic_evidence_available,
        "semantic_evidence_missing_reason": result.semantic_evidence_missing_reason,
        "unexpected_not_applicable": _contains_unexpected_not_applicable(result.answer_text),
        "failure_reasons": failure_reasons,
        "missing_terms": missing_terms,
        "number_checks": number_checks,
        "gpt_like_checks": [],
        "severity": severity,
        "tags": list(tags),
        "oracle_result": dict(oracle),
        "agent_evidence": {
            "target": result.target,
            "run_id": result.run_id,
            "conversation_id": result.conversation_id,
            "dataset_id": result.dataset_id,
            "status": result.status,
            "issues": list(result.issues),
            "transport_success": result.success,
            "service_success": result.success,
            "semantic_status": result.semantic_status,
            "semantic_passed": semantic_passed,
            "contract_satisfied": result.contract_satisfied,
            "contract_family": result.contract_family,
            "violations": list(result.violations),
            "violation_codes": _violation_codes(result),
            "contract_report": dict(result.contract_report),
            "oracle_result": dict(result.oracle_result),
            "oracle_available": result.oracle_available,
            "oracle_passed": result.oracle_passed,
            "oracle_issue_codes": list(result.oracle_issue_codes),
            "semantic_evidence_available": result.semantic_evidence_available,
            "semantic_evidence_missing_reason": result.semantic_evidence_missing_reason,
        },
        "metadata": dict(metadata),
    }
    raw = {
        "case_id": case_id,
        "request_metadata": dict(metadata),
        "agent_result": result.to_dict(),
        "runtime_semantic_evidence": runtime_semantic_evidence,
        "oracle_result": dict(oracle),
    }
    return row, raw


def _runtime_semantic_evidence(result: AgentResult) -> dict[str, Any]:
    return {
        "transport_success": result.success,
        "service_success": result.success,
        "semantic_status": result.semantic_status,
        "semantic_passed": _semantic_passed(result.semantic_status),
        "contract_satisfied": result.contract_satisfied,
        "contract_family": result.contract_family,
        "violations": list(result.violations),
        "violation_codes": _violation_codes(result),
        "contract_report": dict(result.contract_report),
        "oracle_result": dict(result.oracle_result),
        "oracle_available": result.oracle_available,
        "oracle_passed": result.oracle_passed,
        "oracle_issue_codes": list(result.oracle_issue_codes),
        "semantic_evidence_available": result.semantic_evidence_available,
        "semantic_evidence_missing_reason": result.semantic_evidence_missing_reason,
    }


def _merge_runtime_gate_fields_into_scored_rows(rows: list[dict[str, Any]], scored_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_case = {str(row.get("case_id")): row for row in rows}
    enriched: list[dict[str, Any]] = []
    for scored in scored_rows:
        source = rows_by_case.get(str(scored.get("case_id"))) or {}
        candidate = (scored.get("answers") or {}).get("candidate") or {}
        item = dict(scored)
        item.update(
            {
                "transport_success": source.get("transport_success"),
                "service_success": source.get("service_success"),
                "semantic_status": source.get("semantic_status"),
                "semantic_passed": source.get("semantic_passed"),
                "semantic_gate_status": source.get("semantic_gate_status"),
                "contract_satisfied": source.get("contract_satisfied"),
                "contract_family": source.get("contract_family"),
                "violations": list(source.get("violations") or []),
                "violation_codes": list(source.get("violation_codes") or []),
                "contract_report": dict(source.get("contract_report") or {}),
                "runtime_oracle_result": dict(source.get("runtime_oracle_result") or {}),
                "oracle_available": source.get("oracle_available"),
                "oracle_passed": source.get("oracle_passed"),
                "oracle_gate_status": source.get("oracle_gate_status"),
                "oracle_issue_codes": list(source.get("oracle_issue_codes") or []),
                "runtime_gate_passed": source.get("runtime_gate_passed"),
                "semantic_evidence_available": source.get("semantic_evidence_available"),
                "semantic_evidence_missing_reason": source.get("semantic_evidence_missing_reason"),
                "llm_judge_passed": candidate.get("acceptable") is True,
            }
        )
        enriched.append(item)
    return enriched


def _runtime_gate_summary(rows: list[dict[str, Any]], scored_rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    checked_statuses = {"passed", "corrected_passed", "partial", "failed", "needs_clarification"}
    semantic_checked = sum(1 for row in rows if str(row.get("semantic_status") or "") in checked_statuses)
    semantic_passed = sum(1 for row in rows if row.get("semantic_passed") is True)
    semantic_failed = sum(1 for row in rows if str(row.get("semantic_status") or "") in {"partial", "failed", "needs_clarification"})
    legacy_unverified = sum(1 for row in rows if str(row.get("semantic_status") or "") in {"legacy_unverified", "not_available", ""})
    contract_satisfied = sum(1 for row in rows if row.get("contract_satisfied") is True)
    contract_failed = sum(1 for row in rows if row.get("contract_satisfied") is False)
    oracle_available = sum(1 for row in rows if row.get("oracle_available") is True)
    oracle_passed = sum(1 for row in rows if row.get("oracle_passed") is True)
    oracle_failed = sum(1 for row in rows if row.get("oracle_passed") is False)
    missing_evidence = sum(1 for row in rows if not row.get("semantic_evidence_available"))
    transport_success = sum(1 for row in rows if row.get("transport_success") is True)
    service_success = sum(1 for row in rows if row.get("service_success") is True)
    llm_judge_passed = sum(1 for row in scored_rows if row.get("llm_judge_passed") is True)
    violation_counts: Counter[str] = Counter()
    for row in rows:
        violation_counts.update(str(code) for code in row.get("violation_codes") or [] if str(code))
        violation_counts.update(str(code) for code in row.get("oracle_issue_codes") or [] if str(code))
    return {
        "semantic_checked_turns": semantic_checked,
        "semantic_passed_turns": semantic_passed,
        "semantic_failed_turns": semantic_failed,
        "contract_satisfied_turns": contract_satisfied,
        "contract_failed_turns": contract_failed,
        "oracle_available_turns": oracle_available,
        "oracle_passed_turns": oracle_passed,
        "oracle_failed_turns": oracle_failed,
        "top_violation_codes": dict(violation_counts.most_common(12)),
        "legacy_unverified_turns": legacy_unverified,
        "semantic_evidence_missing_turns": missing_evidence,
        "transport_success_turns": transport_success,
        "service_success_turns": service_success,
        "llm_judge_passed_turns": llm_judge_passed,
        "runtime_gate": {
            "total_turns": total,
            "transport_success_turns": transport_success,
            "service_success_turns": service_success,
            "semantic_passed_turns": semantic_passed,
            "oracle_passed_turns": oracle_passed,
            "llm_judge_passed_turns": llm_judge_passed,
            "final_passed_turns": sum(1 for row in scored_rows if _final_runtime_gate_passed(row)),
        },
    }


def _runtime_gate_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Real-user Runtime Semantic Gate",
        "",
        f"- Cases: {summary.get('case_count', 0)}",
        f"- Transport success: {summary.get('transport_success_turns', 0)}",
        f"- Service success: {summary.get('service_success_turns', 0)}",
        f"- Semantic checked: {summary.get('semantic_checked_turns', 0)}",
        f"- Semantic passed: {summary.get('semantic_passed_turns', 0)}",
        f"- Semantic failed: {summary.get('semantic_failed_turns', 0)}",
        f"- Contract satisfied: {summary.get('contract_satisfied_turns', 0)}",
        f"- Contract failed: {summary.get('contract_failed_turns', 0)}",
        f"- Runtime oracle available: {summary.get('oracle_available_turns', 0)}",
        f"- Runtime oracle passed: {summary.get('oracle_passed_turns', 0)}",
        f"- Runtime oracle failed: {summary.get('oracle_failed_turns', 0)}",
        f"- Legacy/unverified turns: {summary.get('legacy_unverified_turns', 0)}",
        f"- Missing semantic evidence: {summary.get('semantic_evidence_missing_turns', 0)}",
        f"- LLM judge passed: {summary.get('llm_judge_passed_turns', 0)}",
        "",
        "## Top Violation Codes",
        "",
    ]
    top_codes = summary.get("top_violation_codes") or {}
    if top_codes:
        for code, count in top_codes.items():
            lines.append(f"- {code}: {count}")
    else:
        lines.append("- none")
    return "\n".join(lines)


def _final_runtime_gate_passed(row: Mapping[str, Any]) -> bool:
    return bool(
        row.get("transport_success") is True
        and row.get("semantic_passed") is True
        and row.get("oracle_passed") is True
        and row.get("llm_judge_passed") is True
    )


def _semantic_passed(status: Any) -> bool:
    return str(status or "").strip().lower() in {"passed", "corrected_passed"}


def _semantic_gate_status(result: AgentResult) -> str:
    status = str(result.semantic_status or "").strip().lower()
    if status in {"passed", "corrected_passed"}:
        return "passed"
    if status in {"partial", "failed", "needs_clarification"}:
        return "failed"
    if status == "legacy_unverified":
        return "legacy_unverified"
    return "not_available"


def _oracle_gate_status(result: AgentResult) -> str:
    if result.oracle_passed is True:
        return "passed"
    if result.oracle_passed is False:
        return "failed"
    if result.oracle_available is False:
        return "not_available"
    return "not_available"


def _violation_codes(result: AgentResult) -> list[str]:
    codes = []
    for item in result.violations:
        if isinstance(item, Mapping) and item.get("code"):
            codes.append(str(item["code"]))
    return codes


def _candidate_score_from_scored_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    passed = int(summary.get("candidate_acceptable_count") or 0)
    total = int(summary.get("case_count") or 0)
    return {
        "passed": passed,
        "total": total,
        "pass_rate": float(summary.get("candidate_acceptance_rate") or (passed / total if total else 0.0)),
        "gpt_like_passed": passed,
        "gpt_like_pass_rate": float(summary.get("candidate_acceptance_rate") or (passed / total if total else 0.0)),
        "unexpected_not_applicable_count": int(summary.get("unexpected_not_applicable_count") or 0),
    }


def _failure_rows_from_scored_rows(rows: list[dict[str, Any]], scored_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_case = {str(row.get("case_id")): row for row in rows}
    failures: list[dict[str, Any]] = []
    for scored in scored_rows:
        candidate = (scored.get("answers") or {}).get("candidate") or {}
        if candidate.get("acceptable") is True:
            continue
        source = dict(rows_by_case.get(str(scored.get("case_id")), {}))
        source["llm_judge"] = {
            "judge_mode": scored.get("judge_mode"),
            "candidate_total_score": candidate.get("total_score"),
            "candidate_acceptable": candidate.get("acceptable"),
            "candidate_issues": candidate.get("issues") or [],
            "verdict": scored.get("verdict") or {},
        }
        failures.append(source)
    return failures


def _dataset_table_names(manifest: Mapping[str, Any], dataset_name: str) -> list[str]:
    dataset = (manifest.get("datasets") or {}).get(dataset_name) or {}
    table_names = dataset.get("table_names") if isinstance(dataset, Mapping) else None
    return [str(item) for item in table_names] if isinstance(table_names, list) else []


def _missing_terms(text: str, requirements: Mapping[str, Any]) -> list[str]:
    required_terms = requirements.get("required_terms") or []
    return [str(term) for term in required_terms if str(term) and str(term) not in text]


def _number_checks(text: str, requirements: Mapping[str, Any]) -> list[dict[str, Any]]:
    checks = []
    for expected in requirements.get("expected_numbers", []) or []:
        expected_text = str(expected)
        checks.append({"expected": expected, "passed": expected_text in text})
    return checks


def _contains_unexpected_not_applicable(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return lowered in {"na", "n/a", "not applicable"} or "not applicable" in lowered
