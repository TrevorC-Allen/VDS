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
    expected_contract_runtime_hints,
    manifest_cases,
    manifest_conversations,
)
from scripts.real_user_eval.oracle import evaluate_oracle
from scripts.real_user_eval.targets import AgentResult, EvalTarget, TargetRequest
from scripts.eval_gate import EvalGateConfig, build_eval_gate_result, eval_gate_markdown, metrics_from_real_user_summary
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
    max_semantic_failed_turns: int = 0,
    max_oracle_failed_turns: int = 0,
    max_legacy_unverified_rate: float = 0.2,
    required_families: tuple[str, ...] = (),
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
    gate_result = build_eval_gate_result(
        metrics_from_real_user_summary(summary, required_families=required_families),
        EvalGateConfig(
            max_semantic_failed_turns=max(0, int(max_semantic_failed_turns or 0)),
            max_oracle_failed_turns=max(0, int(max_oracle_failed_turns or 0)),
            max_legacy_unverified_rate=max(0.0, min(1.0, float(max_legacy_unverified_rate))),
            required_families=tuple(required_families),
        ),
    )
    summary["gate_result"] = gate_result
    summary["gate_passed"] = gate_result["gate_passed"]
    summary["gate_failed_reasons"] = gate_result["gate_failed_reasons"]
    write_json(output_dir / "summary.json", summary)
    (output_dir / "summary.md").write_text(_runtime_gate_markdown(summary) + "\n\n" + eval_gate_markdown(gate_result, title="Multi-metric Eval Gate"), encoding="utf-8")
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
        "gate_result": gate_result,
        "rows": scored_rows,
    }
    write_jsonl(output_dir / "failure_index.jsonl", _failure_rows_from_scored_rows(rows, scored_rows))
    (output_dir / "comparison.md").write_text(
        comparison_markdown(summary)
        + "\n\n"
        + _runtime_gate_markdown(summary)
        + "\n\n"
        + eval_gate_markdown(gate_result, title="Multi-metric Eval Gate"),
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
    expected_contract_normalized = expected_contract if isinstance(expected_contract, Mapping) else None
    expected_contract_hints = expected_contract_runtime_hints(expected_contract_normalized) if expected_contract_normalized else {}
    expected_contract_check = _check_expected_contract(
        expected_contract_normalized,
        expected_contract_hints=expected_contract_hints,
        result=result,
    )
    expected_contract_issue_codes = list(expected_contract_check.get("issue_codes") or [])
    expected_contract_missing_evidence = list(expected_contract_check.get("missing_evidence") or [])
    if expected_contract_check.get("checked") and not expected_contract_check.get("passed"):
        failure_reasons.append("expected_contract_not_satisfied")
        runtime_gate_passed = False
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
        "expected_contract_normalized": expected_contract_normalized,
        "expected_contract_runtime_hints": expected_contract_hints,
        "expected_contract_check": expected_contract_check,
        "expected_contract_issue_codes": expected_contract_issue_codes,
        "expected_contract_missing_evidence": expected_contract_missing_evidence,
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
        "expected_contract_normalized": expected_contract_normalized,
        "expected_contract_runtime_hints": expected_contract_hints,
        "expected_contract_check": expected_contract_check,
        "oracle_result": dict(oracle),
    }
    return row, raw


def _check_expected_contract(
    expected_contract: Mapping[str, Any] | None,
    *,
    expected_contract_hints: Mapping[str, Any],
    result: AgentResult,
) -> dict[str, Any]:
    if not isinstance(expected_contract, Mapping):
        return {
            "checked": False,
            "passed": True,
            "issue_codes": [],
            "missing_evidence": [],
            "details": {"reason": "legacy_text_or_missing_expected_contract"},
        }

    family = str(expected_contract.get("contract_family") or expected_contract_hints.get("task_family") or "").strip()
    evidence = _expected_contract_evidence(result)
    issue_codes: list[str] = []
    missing_evidence: list[str] = []
    details: dict[str, Any] = {
        "contract_family": family,
        "runtime_contract_family": result.contract_family,
        "runtime_violation_codes": evidence["violation_codes"],
        "oracle_issue_codes": evidence["oracle_issue_codes"],
    }

    if result.contract_family and family and result.contract_family != family:
        aliases = {"followup_referent": {"topn", "ranking"}, "topn": {"ranking"}}
        if result.contract_family not in aliases.get(family, set()):
            issue_codes.append("EXPECTED_CONTRACT_FAMILY_MISMATCH")

    if family == "topn":
        _check_topn_expected_contract(expected_contract, evidence, issue_codes, missing_evidence, details)
    elif family == "followup_referent":
        _check_context_expected_contract(expected_contract, evidence, issue_codes, missing_evidence, details)
        _check_topn_expected_contract(expected_contract, evidence, issue_codes, missing_evidence, details)
    elif family == "gap":
        _check_gap_expected_contract(expected_contract, evidence, issue_codes, missing_evidence, details)
    elif family == "multi_file_overview":
        _check_multi_file_expected_contract(expected_contract, evidence, issue_codes, missing_evidence, details)
    elif family == "data_quality":
        _check_data_quality_expected_contract(expected_contract, evidence, issue_codes, missing_evidence, details)

    if expected_contract.get("requires_direct_answer_first"):
        if _has_any_code(evidence["violation_codes"], ("direct_answer", "direct-answer", "direct answer", "answer_first")):
            issue_codes.append("EXPECTED_DIRECT_ANSWER_FIRST_VIOLATION")
        elif not _has_direct_answer_evidence(evidence):
            missing_evidence.append("direct_answer_first_evidence")

    issue_codes = _dedupe(issue_codes)
    missing_evidence = _dedupe(missing_evidence)
    return {
        "checked": True,
        "passed": not issue_codes and not missing_evidence,
        "issue_codes": issue_codes,
        "missing_evidence": missing_evidence,
        "details": details,
    }


def _check_topn_expected_contract(
    expected_contract: Mapping[str, Any],
    evidence: Mapping[str, Any],
    issue_codes: list[str],
    missing_evidence: list[str],
    details: dict[str, Any],
) -> None:
    required = _required_row_count(expected_contract)
    row_count = evidence.get("row_count")
    details["row_count_evidence"] = row_count
    if required is not None:
        details["required_row_count"] = required
        if row_count is None:
            missing_evidence.append("row_count_evidence")
        elif int(row_count) < required:
            issue_codes.append("EXPECTED_ROW_COUNT_SHORT")

    required_metrics = [str(item) for item in expected_contract.get("required_metrics") or [] if str(item)]
    if required_metrics:
        missing_metrics = [metric for metric in required_metrics if not _text_contains_metric(evidence["search_text"], metric)]
        details["missing_metrics"] = missing_metrics
        if missing_metrics:
            missing_evidence.append("metric_evidence")

    if expected_contract.get("required_sort") and _has_any_code(evidence["violation_codes"] + evidence["oracle_issue_codes"], ("sort", "排序", "order")):
        issue_codes.append("EXPECTED_SORT_VIOLATION_PRESENT")


def _check_context_expected_contract(
    expected_contract: Mapping[str, Any],
    evidence: Mapping[str, Any],
    issue_codes: list[str],
    missing_evidence: list[str],
    details: dict[str, Any],
) -> None:
    references = expected_contract.get("required_context_reference")
    reference_values = references if isinstance(references, list) else [references]
    required = {str(item) for item in reference_values if str(item) in {"previous_top_objects", "previous_result_set"}}
    if not required:
        return
    details["required_context_reference"] = sorted(required)
    if not evidence.get("context_reference_available"):
        issue_codes.append("EXPECTED_CONTEXT_REFERENCE_MISSING")
        missing_evidence.append("context_reference_evidence")


def _check_gap_expected_contract(
    expected_contract: Mapping[str, Any],
    evidence: Mapping[str, Any],
    issue_codes: list[str],
    missing_evidence: list[str],
    details: dict[str, Any],
) -> None:
    gap_type = str(expected_contract.get("required_gap_type") or "")
    details["required_gap_type"] = gap_type
    if gap_type == "pairwise" and _has_any_code(evidence["violation_codes"], ("gap_pairwise_missing", "GAP_PAIRWISE_MISSING")):
        issue_codes.append("EXPECTED_GAP_PAIRWISE_MISSING")
    if gap_type == "adjacent" and _has_any_code(evidence["violation_codes"], ("gap_adjacent_missing", "GAP_ADJACENT_MISSING")):
        issue_codes.append("EXPECTED_GAP_ADJACENT_MISSING")
    if gap_type and not evidence.get("gap_evidence_available"):
        issue_codes.append("EXPECTED_GAP_EVIDENCE_MISSING")
        missing_evidence.append("gap_evidence")
    _check_context_expected_contract(expected_contract, evidence, issue_codes, missing_evidence, details)


def _check_multi_file_expected_contract(
    expected_contract: Mapping[str, Any],
    evidence: Mapping[str, Any],
    issue_codes: list[str],
    missing_evidence: list[str],
    details: dict[str, Any],
) -> None:
    required_tables = [str(item) for item in expected_contract.get("required_tables_covered") or [] if str(item)]
    if expected_contract.get("required_all_files_covered") or required_tables:
        covered_tables = set(evidence.get("covered_tables") or [])
        details["covered_tables"] = sorted(covered_tables)
        if required_tables:
            missing_tables = [table for table in required_tables if table not in covered_tables and not _text_contains_metric(evidence["search_text"], table)]
            details["missing_tables"] = missing_tables
            if missing_tables:
                issue_codes.append("EXPECTED_TABLE_COVERAGE_MISSING")
                missing_evidence.append("table_coverage_evidence")
        elif not covered_tables:
            issue_codes.append("EXPECTED_TABLE_COVERAGE_MISSING")
            missing_evidence.append("table_coverage_evidence")

    required_join_keys = [str(item) for item in expected_contract.get("required_join_keys") or [] if str(item)]
    if required_join_keys:
        join_keys = set(evidence.get("join_keys") or [])
        missing_keys = [key for key in required_join_keys if key not in join_keys and not _text_contains_metric(evidence["search_text"], key)]
        details["missing_join_keys"] = missing_keys
        if missing_keys:
            issue_codes.append("EXPECTED_JOIN_KEY_EVIDENCE_MISSING")
            missing_evidence.append("join_key_evidence")


def _check_data_quality_expected_contract(
    expected_contract: Mapping[str, Any],
    evidence: Mapping[str, Any],
    issue_codes: list[str],
    missing_evidence: list[str],
    details: dict[str, Any],
) -> None:
    if expected_contract.get("required_field_level_quality") and not evidence.get("field_level_quality_available"):
        issue_codes.append("EXPECTED_FIELD_LEVEL_QUALITY_EVIDENCE_MISSING")
        missing_evidence.append("field_level_quality_evidence")
    if expected_contract.get("required_duplicate_check") and not evidence.get("duplicate_check_available"):
        issue_codes.append("EXPECTED_DUPLICATE_CHECK_EVIDENCE_MISSING")
        missing_evidence.append("duplicate_check_evidence")
    if expected_contract.get("required_outlier_check") and not evidence.get("outlier_check_available"):
        issue_codes.append("EXPECTED_OUTLIER_CHECK_EVIDENCE_MISSING")
        missing_evidence.append("outlier_check_evidence")
    details["quality_evidence"] = {
        "field_level_quality_available": evidence.get("field_level_quality_available"),
        "duplicate_check_available": evidence.get("duplicate_check_available"),
        "outlier_check_available": evidence.get("outlier_check_available"),
    }


def _expected_contract_evidence(result: AgentResult) -> dict[str, Any]:
    raw_response = dict(result.raw_response or {})
    contract_report = dict(result.contract_report or {})
    oracle_result = dict(result.oracle_result or {})
    payloads = [raw_response, contract_report, oracle_result]
    search_text = " ".join(
        [
            result.answer_text,
            _json_text(raw_response),
            _json_text(contract_report),
            _json_text(oracle_result),
            _json_text(list(result.violations)),
        ]
    ).lower()
    covered_tables = _collect_named_values(payloads, ("table", "table_name", "tables", "covered_tables", "scanned_tables", "source_tables"))
    join_keys = _collect_named_values(payloads, ("join_key", "join_keys", "key", "keys"))
    return {
        "search_text": search_text,
        "violation_codes": _violation_codes(result),
        "oracle_issue_codes": list(result.oracle_issue_codes),
        "row_count": _extract_row_count(payloads),
        "context_reference_available": _has_context_reference_evidence(payloads, search_text),
        "gap_evidence_available": _has_gap_evidence(payloads, search_text),
        "covered_tables": sorted(covered_tables),
        "join_keys": sorted(join_keys),
        "field_level_quality_available": _has_field_level_quality_evidence(payloads, search_text),
        "duplicate_check_available": _has_duplicate_evidence(payloads, search_text),
        "outlier_check_available": _has_outlier_evidence(payloads, search_text),
        "direct_answer_available": _has_direct_answer_evidence_from_payloads(payloads, search_text),
    }


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


def _required_row_count(expected_contract: Mapping[str, Any]) -> int | None:
    values = [expected_contract.get("required_row_count"), expected_contract.get("min_row_count")]
    numeric = [int(value) for value in values if isinstance(value, int) and not isinstance(value, bool)]
    if not numeric:
        return None
    return max(numeric)


def _extract_row_count(payloads: list[Mapping[str, Any]]) -> int | None:
    for payload in payloads:
        count = _find_first_int(payload, ("row_count", "row_count_evidence", "result_row_count", "actual_row_count"))
        if count is not None:
            return count
        rows = _find_first_rows(payload)
        if rows is not None:
            return len(rows)
    return None


def _find_first_int(value: Any, keys: tuple[str, ...]) -> int | None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in keys and isinstance(child, int) and not isinstance(child, bool):
                return child
            found = _find_first_int(child, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_first_int(child, keys)
            if found is not None:
                return found
    return None


def _find_first_rows(value: Any) -> list[Any] | None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in {"rows", "data", "records", "actual_result"} and isinstance(child, list):
                return child
            found = _find_first_rows(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_first_rows(child)
            if found is not None:
                return found
    return None


def _collect_named_values(payloads: list[Mapping[str, Any]], keys: tuple[str, ...]) -> set[str]:
    values: set[str] = set()
    for payload in payloads:
        _collect_named_values_from_any(payload, keys, values)
    return values


def _collect_named_values_from_any(value: Any, keys: tuple[str, ...], out: set[str]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in keys:
                _add_named_value(child, out)
            _collect_named_values_from_any(child, keys, out)
    elif isinstance(value, list):
        for child in value:
            _collect_named_values_from_any(child, keys, out)


def _add_named_value(value: Any, out: set[str]) -> None:
    if isinstance(value, str):
        text = value.strip()
        if text:
            out.add(text)
    elif isinstance(value, Mapping):
        for key in ("name", "table", "table_name", "column", "column_name", "key"):
            child = value.get(key)
            if isinstance(child, str) and child.strip():
                out.add(child.strip())
    elif isinstance(value, list):
        for child in value:
            _add_named_value(child, out)


def _has_context_reference_evidence(payloads: list[Mapping[str, Any]], search_text: str) -> bool:
    if any(token in search_text for token in ("previous_top_objects", "previous_result_set", "inherited_top_objects", "context_used")):
        return True
    return any(_find_truthy(payload, ("context_used", "inherited_top_objects", "previous_top_objects", "previous_result_set")) for payload in payloads)


def _has_gap_evidence(payloads: list[Mapping[str, Any]], search_text: str) -> bool:
    if any(token in search_text for token in ("gap_to_leader", "adjacent_gap", "pairwise_gap", "gap_value", "差距", "差多少")):
        return True
    return any(_find_truthy(payload, ("gap_to_leader", "adjacent_gap", "pairwise_gap", "gap_evidence", "gap_value")) for payload in payloads)


def _has_field_level_quality_evidence(payloads: list[Mapping[str, Any]], search_text: str) -> bool:
    if any(token in search_text for token in ("field_level_table", "field_level_quality", "missing_count", "missing_rate", "字段级")):
        return True
    return any(_find_truthy(payload, ("field_level_table", "field_level_quality", "fields")) for payload in payloads)


def _has_duplicate_evidence(payloads: list[Mapping[str, Any]], search_text: str) -> bool:
    if any(token in search_text for token in ("duplicate_rules", "duplicate_checks", "duplicate_count", "重复")):
        return True
    return any(_find_truthy(payload, ("duplicate_rules", "duplicate_checks", "duplicate_count", "full_row_duplicate_count")) for payload in payloads)


def _has_outlier_evidence(payloads: list[Mapping[str, Any]], search_text: str) -> bool:
    if any(token in search_text for token in ("outlier_rules", "outlier_count", "anomaly_rules", "异常", "离群")):
        return True
    return any(_find_truthy(payload, ("outlier_rules", "outlier_count", "anomaly_rules")) for payload in payloads)


def _has_direct_answer_evidence(evidence: Mapping[str, Any]) -> bool:
    return bool(evidence.get("direct_answer_available"))


def _has_direct_answer_evidence_from_payloads(payloads: list[Mapping[str, Any]], search_text: str) -> bool:
    if any(token in search_text for token in ("direct_answer_first", "direct_answer", "answer_first")):
        return True
    return any(_find_truthy(payload, ("direct_answer", "direct_answer_first", "answer_first")) for payload in payloads)


def _find_truthy(value: Any, keys: tuple[str, ...]) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in keys and bool(child):
                return True
            if _find_truthy(child, keys):
                return True
    elif isinstance(value, list):
        return any(_find_truthy(child, keys) for child in value)
    return False


def _has_any_code(codes: list[str], needles: tuple[str, ...]) -> bool:
    lowered_needles = tuple(needle.lower() for needle in needles)
    for code in codes:
        code_text = str(code).lower()
        if any(needle in code_text for needle in lowered_needles):
            return True
    return False


def _text_contains_metric(text: str, metric: str) -> bool:
    return str(metric or "").strip().lower() in text


def _json_text(value: Any) -> str:
    try:
        import json

        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _dedupe(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        text = str(value)
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


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
                "expected_contract_normalized": source.get("expected_contract_normalized"),
                "expected_contract_runtime_hints": dict(source.get("expected_contract_runtime_hints") or {}),
                "expected_contract_check": dict(source.get("expected_contract_check") or {}),
                "expected_contract_issue_codes": list(source.get("expected_contract_issue_codes") or []),
                "expected_contract_missing_evidence": list(source.get("expected_contract_missing_evidence") or []),
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
    expected_contract_checked = sum(1 for row in rows if (row.get("expected_contract_check") or {}).get("checked") is True)
    expected_contract_passed = sum(1 for row in rows if (row.get("expected_contract_check") or {}).get("checked") is True and (row.get("expected_contract_check") or {}).get("passed") is True)
    expected_contract_failed = sum(1 for row in rows if (row.get("expected_contract_check") or {}).get("checked") is True and (row.get("expected_contract_check") or {}).get("passed") is False)
    expected_contract_missing = sum(1 for row in rows if row.get("expected_contract_missing_evidence"))
    violation_counts: Counter[str] = Counter()
    expected_contract_issue_counts: Counter[str] = Counter()
    for row in rows:
        violation_counts.update(str(code) for code in row.get("violation_codes") or [] if str(code))
        violation_counts.update(str(code) for code in row.get("oracle_issue_codes") or [] if str(code))
        expected_contract_issue_counts.update(str(code) for code in row.get("expected_contract_issue_codes") or [] if str(code))
        violation_counts.update(str(code) for code in row.get("expected_contract_issue_codes") or [] if str(code))
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
        "expected_contract_checked_turns": expected_contract_checked,
        "expected_contract_passed_turns": expected_contract_passed,
        "expected_contract_failed_turns": expected_contract_failed,
        "expected_contract_missing_evidence_turns": expected_contract_missing,
        "expected_contract_issue_codes": dict(expected_contract_issue_counts.most_common(12)),
        "runtime_gate": {
            "total_turns": total,
            "transport_success_turns": transport_success,
            "service_success_turns": service_success,
            "semantic_passed_turns": semantic_passed,
            "oracle_passed_turns": oracle_passed,
            "llm_judge_passed_turns": llm_judge_passed,
            "expected_contract_passed_turns": expected_contract_passed,
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
        f"- Expected contract checked: {summary.get('expected_contract_checked_turns', 0)}",
        f"- Expected contract passed: {summary.get('expected_contract_passed_turns', 0)}",
        f"- Expected contract failed: {summary.get('expected_contract_failed_turns', 0)}",
        f"- Expected contract missing evidence: {summary.get('expected_contract_missing_evidence_turns', 0)}",
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
        and not ((row.get("expected_contract_check") or {}).get("checked") is True and (row.get("expected_contract_check") or {}).get("passed") is False)
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
