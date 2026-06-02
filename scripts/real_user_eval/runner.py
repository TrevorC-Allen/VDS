"""Runner for real-user manifest cases and conversation flows."""

from __future__ import annotations

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
    scored_summary = summarize(scored_rows)
    summary = {
        "name": "real_user_case_eval",
        "dataset_name": manifest.get("name") or "real_user_case_manifest",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "case_count": len(rows),
        "passed": int(scored_summary.get("candidate_acceptable_count") or 0),
        "failed": max(0, len(rows) - int(scored_summary.get("candidate_acceptable_count") or 0)),
        "target": getattr(target, "target_name", target.__class__.__name__),
        "acceptance_source": f"comparison_scored:{actual_judge}",
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
        "rows": scored_rows,
    }
    write_jsonl(output_dir / "failure_index.jsonl", _failure_rows_from_scored_rows(rows, scored_rows))
    (output_dir / "comparison.md").write_text(comparison_markdown(summary), encoding="utf-8")
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
    expected_contract: str,
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
    execution_failed = (not result.success) or not result.answer_text.strip()
    status = "execution_failed" if execution_failed else "response_collected"
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
        },
        "metadata": dict(metadata),
    }
    raw = {
        "case_id": case_id,
        "request_metadata": dict(metadata),
        "agent_result": result.to_dict(),
        "oracle_result": dict(oracle),
    }
    return row, raw


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
