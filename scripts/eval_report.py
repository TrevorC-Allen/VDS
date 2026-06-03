#!/usr/bin/env python3
"""Generate a unified PR-facing eval report for random/multi-seed/real-user runs."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    # allow running as a standalone script from repository root
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from scripts.eval_gate import EvalGateConfig, EvalGateMetrics, build_eval_gate_result, metrics_from_coverage, metrics_from_real_user_summary


NOT_AVAILABLE = "not_available"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a unified PR eval summary and markdown report.")
    parser.add_argument("--output-dir", required=True, help="Directory containing summary artifacts from a single eval run.")
    parser.add_argument("--print-summary", action="store_true")
    parser.add_argument("--min-transport-pass-rate", type=float, default=0.0)
    parser.add_argument("--max-semantic-failed-turns", type=int, default=0)
    parser.add_argument("--max-oracle-failed-turns", type=int, default=0)
    parser.add_argument("--max-expected-contract-failed-turns", type=int, default=0)
    parser.add_argument("--max-legacy-unverified-rate", type=float, default=0.2)
    parser.add_argument("--required-family", action="append", default=[], help="Required capability family for family coverage checks.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = Path.cwd() / output_dir

    gate_config = EvalGateConfig(
        min_transport_pass_rate=args.min_transport_pass_rate,
        max_semantic_failed_turns=max(0, int(args.max_semantic_failed_turns or 0)),
        max_oracle_failed_turns=max(0, int(args.max_oracle_failed_turns or 0)),
        max_expected_contract_failed_turns=max(0, int(args.max_expected_contract_failed_turns or 0)),
        max_legacy_unverified_rate=max(0.0, min(1.0, float(args.max_legacy_unverified_rate))),
        required_families=tuple(args.required_family or ()),
    )

    report = build_pr_eval_summary(output_dir, gate_config=gate_config)
    paths = write_pr_eval_summary(output_dir, report)
    if args.print_summary:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"output_dir": str(output_dir), **paths}, ensure_ascii=False))


def build_pr_eval_summary(output_dir: Path, gate_config: EvalGateConfig | None = None) -> dict[str, Any]:
    """Build PR summary payload from one eval output directory."""

    output_dir = Path(output_dir)
    summary_path = output_dir / "summary.json"
    multi_seed_summary_path = output_dir / "multi_seed_summary.json"

    source_artifacts = _collect_source_artifacts(output_dir)
    if multi_seed_summary_path.exists():
        payload = _load_json(multi_seed_summary_path)
        return _build_multi_seed_report(payload, output_dir=output_dir, source_artifacts=source_artifacts, gate_config=gate_config)

    if not summary_path.exists():
        raise SystemExit(f"No summary artifact found in {output_dir}")

    payload = _load_json(summary_path)
    if "case_count" in payload and "comparison" in payload:
        return _build_real_user_report(payload, output_dir=output_dir, source_artifacts=source_artifacts, gate_config=gate_config)

    if "coverage" in payload or "scenario_count" in payload:
        return _build_random_report(payload, output_dir=output_dir, source_artifacts=source_artifacts, gate_config=gate_config)

    # Fallback for older/other eval artifacts.
    return _build_generic_report(payload, output_dir=output_dir, source_artifacts=source_artifacts, gate_config=gate_config)


def write_pr_eval_summary(output_dir: Path, summary: dict[str, Any]) -> dict[str, str]:
    output_dir = Path(output_dir)
    json_path = output_dir / "pr_eval_summary.json"
    md_path = output_dir / "pr_eval_summary.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_pr_eval_markdown(summary), encoding="utf-8")
    return {
        "pr_eval_summary_json": str(json_path),
        "pr_eval_summary_md": str(md_path),
    }


def _build_multi_seed_report(payload: MappingLike, *, output_dir: Path, source_artifacts: MappingLike, gate_config: EvalGateConfig | None = None) -> dict[str, Any]:
    rows = list(_as_list(payload.get("rows")))
    if not rows:
        summary = {
            "count": 0,
            "rows": [],
            "pass_rate": 0.0,
            "gate_result": build_eval_gate_result(EvalGateMetrics()),
        }

    gate_result = payload.get("gate_result")
    if isinstance(gate_result, dict):
        gate = gate_result
    else:
        gate = _build_gate_result_from_multi_seed_rows(rows, gate_config=gate_config)

    total_turns = _sum_numeric(rows, "total_turns")
    failed_cases: list[dict[str, Any]] = []
    violation_counter: dict[str, int] = {}
    violation_examples: dict[str, dict[str, list[str]]] = {}
    evidence = {
        "semantic_evidence_available_turns": 0,
        "semantic_evidence_missing_turns": 0,
        "oracle_evidence_available_turns": 0,
        "oracle_evidence_missing_turns": 0,
        "legacy_unverified_turns": 0,
        "missing_evidence_reasons": {},
    }

    for row in rows:
        passed = bool(row.get("gate_passed"))
        if not passed:
            failed_cases.append(
                {
                    "case_id": row.get("seed"),
                    "scenario_family": "multi_seed",
                    "turn_id": row.get("seed"),
                    "user_message": f"seed={row.get('seed')}",
                    "semantic_status": "not_available",
                    "oracle_status": "not_available",
                    "violation_codes": _to_list(row.get("top_violation_codes")),
                    "expected_result": NOT_AVAILABLE,
                    "actual_result": NOT_AVAILABLE,
                    "artifact_path": str(output_dir / "multi_seed_summary.json"),
                }
            )
        for violation in _to_list(row.get("top_violation_codes")):
            if not isinstance(violation, dict):
                continue
            code = str(violation.get("code") or "").strip()
            if not code:
                continue
            count = _to_int(violation.get("count"))
            violation_counter[code] = violation_counter.get(code, 0) + count
            # Seed rows do not carry turn-level case references.
            examples = violation_examples.setdefault(code, {"example_case_ids": [], "example_turn_ids": []})
            examples["example_case_ids"].append(_safe_id(row.get("seed")))

    pass_rate = _to_float(payload.get("pass_rate") or payload.get("average_pass_rate"))
    if pass_rate is None:
        pass_rate = 0.0
    total_cases = _to_int(payload.get("count") or payload.get("seed_count") or len(rows))
    eval_summary = {
        "total_cases": total_cases,
        "total_conversations": total_cases,
        "total_turns": total_turns,
        "pass_rate": pass_rate,
        "semantic_checked_turns": _sum_numeric(rows, "semantic_contract_turns"),
        "semantic_passed_turns": _sum_numeric(rows, "semantic_passed_turns"),
        "semantic_failed_turns": _sum_numeric(rows, "semantic_failed_turns"),
        "contract_checked_turns": _sum_numeric(rows, "contract_checked_turns"),
        "contract_satisfied_turns": _sum_numeric(rows, "contract_satisfied_turns"),
        "oracle_available_turns": _sum_numeric(rows, "oracle_available_turns"),
        "oracle_passed_turns": _sum_numeric(rows, "oracle_passed"),
        "oracle_failed_turns": _sum_numeric(rows, "oracle_failed"),
        "llm_judge_passed_turns": _sum_numeric(rows, "llm_judge_passed"),
        "llm_judge_failed_turns": _sum_numeric(rows, "llm_judge_failed"),
    }
    top_violations = _sorted_violation_records(violation_counter, violation_examples)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "output_dir": str(output_dir),
        "eval_type": "multi_seed_random_agent",
        "gate_result": gate,
        "eval_summary": eval_summary,
        "family_summary": _multi_seed_family_summary(payload),
        "top_violation_codes": top_violations,
        "failed_cases": _dedupe_rows(failed_cases),
        "evidence_coverage": evidence,
        "source_artifacts": source_artifacts,
    }


def _build_random_report(payload: MappingLike, *, output_dir: Path, source_artifacts: MappingLike, gate_config: EvalGateConfig | None = None) -> dict[str, Any]:
    coverage = _as_dict(payload.get("coverage"))
    turn_rows = list(_iter_random_turn_rows(payload.get("results")))
    if not turn_rows:
        # fallback from coverage only.
        turn_rows = list(_iter_coverages_to_fake_turn_rows(coverage))

    gate_result = payload.get("gate_result")
    if isinstance(gate_result, dict) and not (gate_config and gate_config.required_families):
        gate = gate_result
    else:
        gate = build_eval_gate_result(
            metrics_from_coverage(coverage, required_families=(tuple(gate_config.required_families) if gate_config else ())),
            gate_config,
        )

    family_summary = _aggregate_family_summary(turn_rows)
    top_violation_codes = _collect_top_violation_codes(turn_rows)
    failed_cases = _collect_failed_random_cases(turn_rows, artifact=str(output_dir / "summary.json"))
    eval_summary = {
        "total_cases": _to_int(coverage.get("conversation_count") or payload.get("conversation_count") or payload.get("scenario_count")),
        "total_conversations": _to_int(coverage.get("conversation_count") or payload.get("conversation_count")),
        "total_turns": _to_int(coverage.get("turn_count") or len(turn_rows)),
        "pass_rate": _to_float(payload.get("pass_rate")),
        "semantic_checked_turns": _to_int(coverage.get("semantic_contract_turns", coverage.get("semantic_checked_turns"))),
        "semantic_passed_turns": _to_int(coverage.get("semantic_passed_turns")),
        "semantic_failed_turns": _to_int(coverage.get("semantic_failed_turns")),
        "contract_checked_turns": _to_int(coverage.get("contract_checked_turns")),
        "contract_satisfied_turns": _to_int(coverage.get("contract_satisfied_turns")),
        "oracle_available_turns": _to_int(coverage.get("oracle_available_turns")),
        "oracle_passed_turns": _to_int(coverage.get("oracle_passed_turns") or coverage.get("oracle_passed")),
        "oracle_failed_turns": _to_int(coverage.get("oracle_failed_turns") or coverage.get("oracle_failed")),
        "llm_judge_passed_turns": _to_int(coverage.get("turn_count", 0)) - _to_int(coverage.get("llm_judge_failed_turns")),
        "llm_judge_failed_turns": _to_int(coverage.get("llm_judge_failed_turns")),
        "expected_contract_checked_turns": _to_int(coverage.get("expected_contract_checked_turns")),
        "expected_contract_passed_turns": _to_int(coverage.get("expected_contract_passed_turns")),
        "expected_contract_failed_turns": _to_int(coverage.get("expected_contract_failed_turns")),
        "expected_contract_missing_evidence_turns": _to_int(coverage.get("expected_contract_missing_evidence_turns")),
        "expected_contract_issue_codes": _collect_top_violation_codes(coverage.get("expected_contract_issue_codes")),
    }
    evidence_coverage = _compute_evidence_coverage_for_turn_rows(turn_rows)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "output_dir": str(output_dir),
        "eval_type": "random_agent",
        "gate_result": gate,
        "eval_summary": eval_summary,
        "family_summary": family_summary,
        "top_violation_codes": top_violation_codes,
        "failed_cases": failed_cases,
        "evidence_coverage": evidence_coverage,
        "source_artifacts": source_artifacts,
    }


def _build_real_user_report(
    payload: MappingLike,
    *,
    output_dir: Path,
    source_artifacts: MappingLike,
    gate_config: EvalGateConfig | None = None,
) -> dict[str, Any]:
    comparison_rows = _as_list(payload.get("comparison"))
    scored_rows = _load_rows_from_jsonl(output_dir / "comparison_scored.jsonl")
    if not scored_rows:
        scored_rows = _as_list(_load_json(output_dir / "comparison_scored.json").get("rows", []), default=[])

    if not comparison_rows:
        comparison_rows = [row.get("candidate", {}) for row in scored_rows]

    gate_result = payload.get("gate_result")
    if isinstance(gate_result, dict):
        gate = gate_result
    else:
        gate = build_eval_gate_result(metrics_from_real_user_summary(payload, required_families=(tuple(gate_config.required_families) if gate_config else ())), gate_config)

    family_summary = _aggregate_family_summary(comparison_rows)
    top_violation_codes = _collect_top_violation_codes(comparison_rows)
    failed_cases = _collect_failed_real_user_cases(
        comparison_rows,
        scored_rows=scored_rows,
        failure_index_path=output_dir / "failure_index.jsonl",
        artifact=str(output_dir / "comparison_scored.jsonl"),
    )
    eval_summary = _build_real_user_eval_summary(payload, comparison_rows)
    evidence_coverage = _compute_evidence_coverage_for_turn_rows(comparison_rows)
    eval_summary["llm_judge_passed_turns"] = sum(1 for row in scored_rows if row.get("llm_judge_passed") is True)
    eval_summary["llm_judge_failed_turns"] = sum(1 for row in scored_rows if row.get("llm_judge_passed") is False)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "output_dir": str(output_dir),
        "eval_type": "real_user",
        "gate_result": gate,
        "eval_summary": eval_summary,
        "family_summary": family_summary,
        "top_violation_codes": top_violation_codes,
        "failed_cases": failed_cases,
        "evidence_coverage": evidence_coverage,
        "source_artifacts": source_artifacts,
    }


def _build_generic_report(payload: MappingLike, *, output_dir: Path, source_artifacts: MappingLike, gate_config: EvalGateConfig | None = None) -> dict[str, Any]:
    gate = payload.get("gate_result")
    if not isinstance(gate, dict):
        candidates = _as_dict(payload.get("candidate_score"))
        summary = _as_dict(candidates.get("summary"))
        turn_count = _to_int(payload.get("total_turns") or payload.get("case_count") or payload.get("elapsed_rows") or 0)
        passed = _to_int(candidates.get("passed") or summary.get("passed") or payload.get("passed") or 0)
        gate = build_eval_gate_result(
            EvalGateMetrics(
                total_turns=turn_count,
                semantic_contract_turns=_to_int(payload.get("semantic_checked_turns") or payload.get("semantic_contract_turns")),
                semantic_passed_turns=_to_int(payload.get("semantic_passed_turns")),
                semantic_failed_turns=_to_int(payload.get("semantic_failed_turns")),
                oracle_available_turns=_to_int(payload.get("oracle_available_turns")),
                oracle_passed_turns=_to_int(payload.get("oracle_passed_turns")),
                oracle_failed_turns=_to_int(payload.get("oracle_failed_turns")),
                contract_satisfied_turns=_to_int(payload.get("contract_satisfied_turns")),
            ),
            gate_config,
        )

    eval_summary = {
        "total_cases": _to_int(payload.get("case_count") or payload.get("total")),
        "total_conversations": _to_int(payload.get("case_count") or payload.get("total")),
        "total_turns": _to_int(payload.get("case_count") or payload.get("total")),
        "pass_rate": _to_float(_candidate_pass_rate(payload)),
        "semantic_checked_turns": _to_int(payload.get("semantic_checked_turns") or payload.get("semantic_contract_turns")),
        "semantic_passed_turns": _to_int(payload.get("semantic_passed_turns")),
        "semantic_failed_turns": _to_int(payload.get("semantic_failed_turns")),
        "contract_checked_turns": _to_int(payload.get("contract_checked_turns")),
        "contract_satisfied_turns": _to_int(payload.get("contract_satisfied_turns")),
        "oracle_available_turns": _to_int(payload.get("oracle_available_turns")),
        "oracle_passed_turns": _to_int(payload.get("oracle_passed_turns")),
        "oracle_failed_turns": _to_int(payload.get("oracle_failed_turns")),
        "llm_judge_passed_turns": _to_int(payload.get("llm_judge_passed_turns")),
        "llm_judge_failed_turns": _to_int(payload.get("llm_judge_failed_turns")),
        "expected_contract_checked_turns": _to_int(payload.get("expected_contract_checked_turns")),
        "expected_contract_passed_turns": _to_int(payload.get("expected_contract_passed_turns")),
        "expected_contract_failed_turns": _to_int(payload.get("expected_contract_failed_turns")),
        "expected_contract_missing_evidence_turns": _to_int(payload.get("expected_contract_missing_evidence_turns")),
        "expected_contract_issue_codes": _collect_top_violation_codes(payload.get("expected_contract_issue_codes")),
    }

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "output_dir": str(output_dir),
        "eval_type": "generic_or_other",
        "gate_result": gate,
        "eval_summary": eval_summary,
        "family_summary": _family_summary_not_available(),
        "top_violation_codes": _collect_top_violation_codes(_as_list(payload.get("top_violation_codes"))),
        "failed_cases": _generic_failed_cases(payload, str(output_dir / "summary.json")),
        "evidence_coverage": _compute_evidence_coverage_for_turn_rows(_generic_turn_rows(payload)),
        "source_artifacts": source_artifacts,
    }


def _collect_source_artifacts(output_dir: Path) -> dict[str, Any]:
    candidates = [
        "summary.json",
        "multi_seed_summary.json",
        "comparison.json",
        "comparison.jsonl",
        "comparison_scored.json",
        "comparison_scored.jsonl",
        "failure_index.jsonl",
        "agent_results.jsonl",
        "run_log.json",
    ]
    artifacts: dict[str, Any] = {}
    for name in candidates:
        path = output_dir / name
        artifacts[name] = {
            "path": str(path),
            "exists": path.exists(),
        }
    return artifacts


def _build_gate_result_from_multi_seed_rows(rows: list[dict[str, Any]], gate_config: EvalGateConfig | None = None) -> dict[str, Any]:
    covered_families: set[str] = set()
    top_violation: Counter[str] = Counter()
    for row in rows:
        family_coverage = row.get("family_coverage")
        if isinstance(family_coverage, dict):
            covered_families.update(str(item) for item in family_coverage.get("covered", []) if str(item))
        for code_entry in _to_list(row.get("top_violation_codes")):
            if not isinstance(code_entry, dict):
                continue
            code = str(code_entry.get("code") or "").strip()
            if not code:
                continue
            top_violation[code] += _to_int(code_entry.get("count"))

    metrics = EvalGateMetrics(
        total_turns=_sum_numeric(rows, "total_turns"),
        transport_success_turns=_sum_numeric(rows, "transport_success_turns"),
        semantic_contract_turns=_sum_numeric(rows, "semantic_contract_turns"),
        semantic_passed_turns=_sum_numeric(rows, "semantic_passed_turns"),
        semantic_failed_turns=_sum_numeric(rows, "semantic_failed_turns"),
        oracle_available_turns=_sum_numeric(rows, "oracle_available_turns"),
        oracle_passed_turns=_sum_numeric(rows, "oracle_passed"),
        oracle_failed_turns=_sum_numeric(rows, "oracle_failed"),
        contract_satisfied_turns=_sum_numeric(rows, "contract_satisfied_turns"),
        legacy_unverified_turns=_sum_numeric(rows, "legacy_unverified_turns"),
        covered_families=tuple(sorted(covered_families)),
        top_violation_codes=tuple({"code": code, "count": count} for code, count in top_violation.items()),
    )
    return build_eval_gate_result(metrics, gate_config)


def _iter_random_turn_rows(results: Any) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for result in _as_list(results, default=[]):
        scenario_id = str(result.get("scenario_id") or result.get("scenario") or "")
        scenario_family = str(result.get("scenario_family") or "")
        for turn in _as_list(result.get("turns"), default=[]):
            if not isinstance(turn, dict):
                continue
            row = dict(turn)
            if scenario_family and "scenario_family" not in row:
                row["scenario_family"] = scenario_family
            if "case_id" not in row:
                row["case_id"] = scenario_id
            if "turn_id" not in row:
                row["turn_id"] = _safe_id(row.get("index") or row.get("turn"))
            turns.append(row)
    return turns


def _iter_coverages_to_fake_turn_rows(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    total_turns = _to_int(coverage.get("turn_count", 0))
    if total_turns <= 0:
        return []
    return [
        {
            "case_id": "legacy-coverage",
            "turn_id": f"t{index}",
            "semantic_status": "passed" if _to_int(coverage.get("semantic_passed_turns", 0)) > 0 else "legacy_unverified",
            "contract_satisfied": True,
            "oracle_passed": bool(_to_int(coverage.get("oracle_passed_turns", 0)) > 0),
            "oracle_available": coverage.get("oracle_available_turns") is not None,
            "capability_family": "random",
        }
        for index in range(1, total_turns + 1)
    ]


def _build_real_user_eval_summary(payload: MappingLike, comparison_rows: list[dict[str, Any]]) -> dict[str, Any]:
    transport_success = sum(1 for row in comparison_rows if row.get("transport_success") is True)
    service_success = sum(1 for row in comparison_rows if row.get("service_success") is True)
    semantic_checked = sum(
        1
        for row in comparison_rows
        if str(_safe_text(row.get("semantic_status"))).lower() in {"passed", "corrected_passed", "failed", "needs_clarification", "legacy_unverified", "not_available"}
    )
    semantic_passed = sum(1 for row in comparison_rows if _is_semantic_passed(row))
    semantic_failed = sum(1 for row in comparison_rows if _is_semantic_failed(row))
    contract_checked = sum(1 for row in comparison_rows if row.get("contract_satisfied") in {True, False})
    contract_satisfied = sum(1 for row in comparison_rows if row.get("contract_satisfied") is True)
    oracle_available = sum(1 for row in comparison_rows if row.get("oracle_available") is not None)
    oracle_passed = sum(1 for row in comparison_rows if row.get("oracle_passed") is True)
    oracle_failed = sum(1 for row in comparison_rows if row.get("oracle_passed") is False)
    expected_checked = sum(1 for row in comparison_rows if _as_dict(row.get("expected_contract_check")).get("checked") is True)
    expected_passed = sum(
        1
        for row in comparison_rows
        if _as_dict(row.get("expected_contract_check")).get("checked") is True
        and _as_dict(row.get("expected_contract_check")).get("passed") is True
    )
    expected_failed = sum(
        1
        for row in comparison_rows
        if _as_dict(row.get("expected_contract_check")).get("checked") is True
        and _as_dict(row.get("expected_contract_check")).get("passed") is False
    )
    expected_missing = sum(1 for row in comparison_rows if _to_list(row.get("expected_contract_missing_evidence")))
    expected_issue_counter: Counter[str] = Counter()
    for row in comparison_rows:
        expected_issue_counter.update(_to_str_list(row.get("expected_contract_issue_codes")))
    total = len(comparison_rows)
    passed_cases = _to_int(payload.get("passed"))
    if passed_cases <= 0 and total:
        # compatibility with legacy outputs that use candidate stats in nested structures.
        candidate_score = _as_dict(payload.get("candidate_score"))
        if candidate_score:
            passed_cases = _to_int(candidate_score.get("passed") or candidate_score.get("candidate_acceptable_count"))
    pass_rate = _to_float(payload.get("pass_rate"))
    if pass_rate is None:
        pass_rate = float(passed_cases / total) if total else 0.0

    conversations = {str(row.get("case_id") or "").split("__")[0] for row in comparison_rows}
    return {
        "total_cases": _to_int(payload.get("case_count") or total),
        "total_conversations": len([item for item in conversations if item]),
        "total_turns": total,
        "pass_rate": pass_rate,
        "semantic_checked_turns": semantic_checked,
        "semantic_passed_turns": semantic_passed,
        "semantic_failed_turns": semantic_failed,
        "contract_checked_turns": contract_checked,
        "contract_satisfied_turns": contract_satisfied,
        "oracle_available_turns": oracle_available,
        "oracle_passed_turns": oracle_passed,
        "oracle_failed_turns": oracle_failed,
        "transport_success_turns": transport_success,
        "service_success_turns": service_success,
        "expected_contract_checked_turns": _to_int(payload.get("expected_contract_checked_turns") or expected_checked),
        "expected_contract_passed_turns": _to_int(payload.get("expected_contract_passed_turns") or expected_passed),
        "expected_contract_failed_turns": _to_int(payload.get("expected_contract_failed_turns") or expected_failed),
        "expected_contract_missing_evidence_turns": _to_int(payload.get("expected_contract_missing_evidence_turns") or expected_missing),
        "expected_contract_issue_codes": _collect_top_violation_codes(payload.get("expected_contract_issue_codes") or dict(expected_issue_counter)),
    }


def _collect_failed_real_user_cases(
    rows: list[dict[str, Any]],
    *,
    scored_rows: list[dict[str, Any]],
    failure_index_path: Path,
    artifact: str,
) -> list[dict[str, Any]]:
    if failure_index_path.exists():
        candidates = _load_rows_from_jsonl(failure_index_path)
        return [_normalize_failed_case(row, row.get("case_id"), str(failure_index_path)) for row in candidates]

    scored_by_case = {str(row.get("case_id") or ""): row for row in scored_rows if isinstance(row, dict)}
    failures: list[dict[str, Any]] = []
    for row in rows:
        case_id = str(row.get("case_id") or "")
        scored = scored_by_case.get(case_id)
        if scored is not None and scored.get("llm_judge_passed") is False:
            failures.append(_normalize_failed_case(scored, case_id, str(output_case_artifact(artifact, case_id))))
            continue
        if _is_real_user_failed(row):
            failures.append(_normalize_failed_case(row, case_id, artifact))
    return failures


def _normalize_failed_case(row: MappingLike, case_id: Any, artifact_path: str) -> dict[str, Any]:
    semantic_status = _safe_text(row.get("semantic_status") or row.get("semantic_gate_status") or "not_available")
    oracle_status = "not_available"
    if row.get("oracle_passed") is True:
        oracle_status = "passed"
    elif row.get("oracle_passed") is False:
        oracle_status = "failed"
    elif row.get("oracle_available") is False:
        oracle_status = "not_available"

    return {
        "case_id": str(case_id or row.get("case_id") or ""),
        "scenario_family": _safe_text(row.get("scenario_family") or row.get("capability_family") or row.get("category") or "") or "not_available",
        "turn_id": _safe_id(row.get("turn_id") or row.get("index") or row.get("metadata", {}).get("turn_index") or ""),
        "user_message": _safe_text(row.get("question") or row.get("question_text") or "not_available"),
        "semantic_status": semantic_status,
        "oracle_status": oracle_status,
        "violation_codes": _to_list(row.get("violation_codes") or row.get("violations") or []) + _to_list(row.get("expected_contract_issue_codes")),
        "expected_result": _short_repr(row.get("expected_result") or row.get("standard_answer") or row.get("expected")),
        "actual_result": _short_repr(row.get("actual_result") or row.get("candidate_answer") or row.get("answer") or row.get("answer_text") or ""),
        "artifact_path": artifact_path,
    }


def _collect_failed_random_cases(rows: list[dict[str, Any]], artifact: str) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for row in rows:
        if not _is_random_turn_failed(row):
            continue
        failures.append(
            _normalize_failed_case(row, case_id=row.get("case_id") or row.get("scenario_id") or row.get("conversation_id") or "", artifact_path=artifact)
        )
    return failures


def _generic_turn_rows(payload: MappingLike) -> list[dict[str, Any]]:
    rows = []
    for row in _as_list(payload.get("rows")):
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _generic_failed_cases(payload: MappingLike, artifact: str) -> list[dict[str, Any]]:
    failures = []
    for row in _generic_turn_rows(payload):
        candidate_accepted = None
        candidate = _as_dict(row.get("candidate"))
        if candidate:
            candidate_accepted = candidate.get("accepted")
        if candidate_accepted is False:
            failures.append(_normalize_failed_case(row, row.get("case_id"), artifact))
            continue
        if row.get("success") is False:
            failures.append(_normalize_failed_case(row, row.get("case_id"), artifact))
    return failures


def _aggregate_family_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return _family_summary_not_available()

    families: dict[str, dict[str, int]] = {}
    family_violations: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        family = _safe_text(row.get("scenario_family") or row.get("capability_family"))
        if not family:
            continue
        entry = families.setdefault(
            family,
            {
                "total_turns": 0,
                "semantic_checked_turns": 0,
                "semantic_passed_turns": 0,
                "oracle_available_turns": 0,
                "oracle_passed_turns": 0,
                "contract_checked_turns": 0,
                "contract_satisfied_turns": 0,
                "expected_contract_checked_turns": 0,
                "expected_contract_passed_turns": 0,
                "expected_contract_failed_turns": 0,
            },
        )
        entry["total_turns"] += 1
        semantic_status = _safe_text(row.get("semantic_status") or row.get("semantic_gate_status"))
        if semantic_status:
            entry["semantic_checked_turns"] += 1
            if semantic_status in {"passed", "corrected_passed"}:
                entry["semantic_passed_turns"] += 1
        if row.get("contract_satisfied") is True:
            entry["contract_satisfied_turns"] += 1
        if row.get("contract_satisfied") in {True, False}:
            entry["contract_checked_turns"] += 1
        if row.get("oracle_available") is not None or row.get("oracle_passed") is not None:
            entry["oracle_available_turns"] += 1
            if row.get("oracle_passed") is True:
                entry["oracle_passed_turns"] += 1
        expected_check = _as_dict(row.get("expected_contract_check"))
        if expected_check.get("checked") is True:
            entry["expected_contract_checked_turns"] += 1
            if expected_check.get("passed") is True:
                entry["expected_contract_passed_turns"] += 1
            else:
                entry["expected_contract_failed_turns"] += 1
        for violation in _to_list(row.get("violation_codes") or row.get("contract_violation_codes") or row.get("oracle_issue_codes") or []):
            if isinstance(violation, str):
                family_violations[family][violation] += 1
        for violation in _to_list(row.get("expected_contract_issue_codes")):
            if isinstance(violation, str):
                family_violations[family][violation] += 1

    if not families:
        return _family_summary_not_available()

    family_list: list[dict[str, Any]] = []
    for family, values in sorted(families.items()):
        semantic_rate = _rate(values["semantic_passed_turns"], values["semantic_checked_turns"])
        oracle_rate = _rate(values["oracle_passed_turns"], values["oracle_available_turns"])
        contract_rate = _rate(values["contract_satisfied_turns"], values["contract_checked_turns"])
        expected_contract_rate = _rate(values["expected_contract_passed_turns"], values["expected_contract_checked_turns"])
        top_codes = _sorted_violation_records(dict(family_violations[family]))
        family_list.append(
            {
                "family": family,
                "total_turns": values["total_turns"],
                "semantic_pass_rate": semantic_rate,
                "oracle_pass_rate": oracle_rate,
                "contract_satisfied_rate": contract_rate,
                "expected_contract_pass_rate": expected_contract_rate,
                "expected_contract_failed_turns": values["expected_contract_failed_turns"],
                "top_violation_codes": top_codes,
            }
        )
    return {"status": "available", "families": family_list}


def _collect_top_violation_codes_from_payload(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [
            {
                "code": str(code),
                "count": _to_int(count),
                "example_case_ids": [],
                "example_turn_ids": [],
            }
            for code, count in value.items()
        ]
    if isinstance(value, list):
        return [
            item if isinstance(item, dict) else {"code": str(item), "count": 1, "example_case_ids": [], "example_turn_ids": []}
            for item in value
            if item not in (None, "")
        ]
    return []


def _collect_top_violation_codes(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, dict):
        return _collect_top_violation_codes_from_payload(payload)
    if isinstance(payload, list):
        if _is_violation_code_list(payload):
            return _collect_top_violation_codes_from_payload(payload)
        return _collect_top_violation_codes_from_rows(payload)
    return []


def _is_violation_code_list(payload: list[Any]) -> bool:
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        if "code" in item or "count" in item:
            return True
    return False


def _collect_top_violation_codes_from_rows(rows: list[Any]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    examples: dict[str, dict[str, list[str]]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        case_id = _safe_text(row.get("case_id") or "")
        turn_id = _safe_text(row.get("turn_id") or row.get("index") or row.get("conversation_turn"))
        for code in _to_list(row.get("violation_codes") or row.get("contract_violation_codes") or row.get("oracle_issue_codes")) + _to_list(
            row.get("expected_contract_issue_codes")
        ):
            code_text = _safe_text(code)
            if not code_text:
                continue
            counts[code_text] += 1
            example = examples.setdefault(code_text, {"example_case_ids": [], "example_turn_ids": []})
            if case_id:
                example["example_case_ids"].append(case_id)
            if turn_id:
                example["example_turn_ids"].append(turn_id)
    return _sorted_violation_records(dict(counts), examples)


def _compute_evidence_coverage_for_turn_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    semantic_missing = 0
    oracle_missing = 0
    semantic_available = 0
    oracle_available = 0
    legacy = 0
    expected_contract_checked = 0
    expected_contract_missing = 0
    missing_reasons: Counter[str] = Counter()

    for row in rows:
        status = _safe_text(row.get("semantic_status") or row.get("semantic_gate_status"))
        if status in {"", NOT_AVAILABLE, "legacy_unverified", "not_available"}:
            semantic_missing += 1
            if reason := _safe_text(row.get("semantic_evidence_missing_reason")):
                missing_reasons[reason] += 1
        else:
            semantic_available += 1
        if status in {"legacy_unverified", "not_available", ""}:
            legacy += 1

        if row.get("oracle_available") is None and row.get("oracle_passed") is None and not _to_list(row.get("oracle_issue_codes") or row.get("issues")):
            oracle_missing += 1
        else:
            oracle_available += 1
        expected_check = _as_dict(row.get("expected_contract_check"))
        if expected_check.get("checked") is True:
            expected_contract_checked += 1
        if _to_list(row.get("expected_contract_missing_evidence")):
            expected_contract_missing += 1
            for reason in _to_str_list(row.get("expected_contract_missing_evidence")):
                missing_reasons[f"expected_contract:{reason}"] += 1

    return {
        "semantic_evidence_available_turns": semantic_available,
        "semantic_evidence_missing_turns": semantic_missing,
        "oracle_evidence_available_turns": oracle_available,
        "oracle_evidence_missing_turns": oracle_missing,
        "legacy_unverified_turns": legacy,
        "expected_contract_checked_turns": expected_contract_checked,
        "expected_contract_missing_evidence_turns": expected_contract_missing,
        "missing_evidence_reason": sorted(missing_reasons.items()),
    }


def _multi_seed_family_summary(payload: MappingLike) -> dict[str, Any]:
    families = _to_str_list(payload.get("families_run"))
    if not families:
        return _family_summary_not_available()
    pass_rates = _as_dict(payload.get("per_family_pass_rate"))
    semantic_rates = _as_dict(payload.get("per_family_semantic_pass_rate"))
    oracle_rates = _as_dict(payload.get("per_family_oracle_pass_rate"))
    expected_rates = _as_dict(payload.get("per_family_expected_contract_pass_rate"))
    violations_by_family = _as_dict(payload.get("top_violation_codes_by_family"))
    rows = []
    for family in sorted(set(families)):
        rows.append(
            {
                "family": family,
                "total_turns": 0,
                "semantic_pass_rate": semantic_rates.get(family, NOT_AVAILABLE),
                "oracle_pass_rate": oracle_rates.get(family, NOT_AVAILABLE),
                "contract_satisfied_rate": NOT_AVAILABLE,
                "expected_contract_pass_rate": expected_rates.get(family, NOT_AVAILABLE),
                "expected_contract_failed_turns": 0,
                "pass_rate": pass_rates.get(family, NOT_AVAILABLE),
                "top_violation_codes": _collect_top_violation_codes(violations_by_family.get(family, [])),
            }
        )
    return {"status": "available", "families": rows}


def _family_summary_not_available() -> dict[str, Any]:
    return {"status": "not_available", "families": []}


def _sorted_violation_records(counts: MappingLike, examples: MappingLike | None = None) -> list[dict[str, Any]]:
    entries: list[tuple[str, int]] = []
    for code, count in counts.items():
        if not str(code):
            continue
        entries.append((str(code), _to_int(count)))
    entries.sort(key=lambda item: (-item[1], item[0]))
    records: list[dict[str, Any]] = []
    for code, count in entries:
        record = {
            "code": code,
            "count": count,
            "example_case_ids": [],
            "example_turn_ids": [],
        }
        if isinstance(examples, dict) and code in examples:
            data = _as_dict(examples.get(code))
            record["example_case_ids"] = _dedupe(_as_str_list(data.get("example_case_ids", [])))[:3]
            record["example_turn_ids"] = _dedupe(_as_str_list(data.get("example_turn_ids", [])))[:3]
        records.append(record)
    return records


def _render_pr_eval_markdown(payload: MappingLike) -> str:
    gate = _as_dict(payload.get("gate_result"))
    eval_summary = _as_dict(payload.get("eval_summary"))
    family_summary = _as_dict(payload.get("family_summary"))
    top_violations = _as_list(payload.get("top_violation_codes", []))
    failed_cases = _as_list(payload.get("failed_cases", []))
    evidence = _as_dict(payload.get("evidence_coverage", {}))

    lines = [
        "# Gate Result",
        "",
        f"- gate_passed: {gate.get('gate_passed', False)}",
        f"- gate_failed_reasons: {_join_with_default(gate.get('gate_failed_reasons'), 'none')}",
        f"- transport_pass_rate: {_format_rate(gate.get('transport_pass_rate'))}",
        f"- semantic_pass_rate: {_format_rate(gate.get('semantic_pass_rate'))}",
        f"- oracle_pass_rate: {_format_rate(gate.get('oracle_pass_rate'))}",
        f"- contract_satisfied_rate: {_format_rate(gate.get('contract_satisfied_rate'))}",
        f"- legacy_unverified_rate: {_format_rate(gate.get('legacy_unverified_rate'))}",
        f"- expected_contract_pass_rate: {_format_rate(gate.get('expected_contract_pass_rate'))}",
        f"- expected_contract_failed_turns: {gate.get('expected_contract_failed_turns', 0)}",
        f"- expected_contract_missing_evidence_turns: {gate.get('expected_contract_missing_evidence_turns', 0)}",
        f"- family_coverage: {_join_with_default(_as_dict(gate.get('family_coverage')).get('covered'), '-')}",
        f"- missing_family_coverage: {_join_with_default(_as_dict(gate.get('family_coverage')).get('missing'), 'none')}",
        "",
        "# Eval Summary",
        "",
        f"- total_cases: {eval_summary.get('total_cases', 0)}",
        f"- total_conversations: {eval_summary.get('total_conversations', 0)}",
        f"- total_turns: {eval_summary.get('total_turns', 0)}",
        f"- pass_rate: {_format_rate(eval_summary.get('pass_rate'))}",
        f"- semantic_checked_turns: {eval_summary.get('semantic_checked_turns', 0)}",
        f"- semantic_passed_turns: {eval_summary.get('semantic_passed_turns', 0)}",
        f"- semantic_failed_turns: {eval_summary.get('semantic_failed_turns', 0)}",
        f"- contract_checked_turns: {eval_summary.get('contract_checked_turns', 0)}",
        f"- contract_satisfied_turns: {eval_summary.get('contract_satisfied_turns', 0)}",
        f"- oracle_available_turns: {eval_summary.get('oracle_available_turns', 0)}",
        f"- oracle_passed_turns: {eval_summary.get('oracle_passed_turns', 0)}",
        f"- oracle_failed_turns: {eval_summary.get('oracle_failed_turns', 0)}",
        f"- llm_judge_passed_turns: {eval_summary.get('llm_judge_passed_turns', 0)}",
        f"- llm_judge_failed_turns: {eval_summary.get('llm_judge_failed_turns', 0)}",
        f"- expected_contract_checked_turns: {eval_summary.get('expected_contract_checked_turns', 0)}",
        f"- expected_contract_passed_turns: {eval_summary.get('expected_contract_passed_turns', 0)}",
        f"- expected_contract_failed_turns: {eval_summary.get('expected_contract_failed_turns', 0)}",
        f"- expected_contract_missing_evidence_turns: {eval_summary.get('expected_contract_missing_evidence_turns', 0)}",
        "",
        "# Scenario Family Summary",
    ]

    if family_summary.get("status") == "not_available":
        lines.append("not_available")
    else:
        lines.append("")
        lines.append("| family | total_turns | semantic_pass_rate | oracle_pass_rate | contract_satisfied_rate | expected_contract_pass_rate | expected_contract_failed_turns | top_violation_codes |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
        for item in family_summary.get("families", []):
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(item.get("family", "")),
                        str(item.get("total_turns", 0)),
                        _format_rate(item.get("semantic_pass_rate")),
                        _format_rate(item.get("oracle_pass_rate")),
                        _format_rate(item.get("contract_satisfied_rate")),
                        _format_rate(item.get("expected_contract_pass_rate")),
                        str(item.get("expected_contract_failed_turns", 0)),
                        ", ".join([str(v.get("code")) for v in item.get("top_violation_codes", []) if isinstance(v, dict)]),
                    ]
                )
                + " |"
            )

    lines.extend(
        [
            "",
            "# Top Violation Codes",
            "",
        ]
    )
    if top_violations:
        lines.append("| violation_code | count | example_case_ids | example_turn_ids |")
        lines.append("| --- | ---: | --- | --- |")
        for item in top_violations:
            if not isinstance(item, dict):
                continue
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(item.get("code", "")),
                        str(_to_int(item.get("count", 0))),
                        ",".join(_to_str_list(item.get("example_case_ids", []))),
                        ",".join(_to_str_list(item.get("example_turn_ids", []))),
                    ]
                )
                + " |"
            )
    else:
        lines.append("none")

    lines.extend(["", "# Failed Cases", ""])
    if failed_cases:
        lines.append("| case_id | scenario_family | turn_id | user_message | semantic_status | oracle_status | violation_codes | expected_result | actual_result | artifact_path |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for case in failed_cases:
            if not isinstance(case, dict):
                continue
            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape_md(case.get("case_id")),
                        _escape_md(case.get("scenario_family")),
                        _escape_md(case.get("turn_id")),
                        _escape_md(case.get("user_message")),
                        _escape_md(case.get("semantic_status")),
                        _escape_md(case.get("oracle_status")),
                        _escape_md(_join_with_default(_to_str_list(case.get("violation_codes")), "-")),
                        _escape_md(_safe_text(case.get("expected_result"))),
                        _escape_md(_safe_text(case.get("actual_result"))),
                        _escape_md(case.get("artifact_path")),
                    ]
                )
                + " |"
            )
    else:
        lines.append("none")

    lines.extend(
        [
            "",
            "# Evidence Coverage",
            "",
            f"- semantic evidence available: {evidence.get('semantic_evidence_available_turns', 0)}",
            f"- semantic evidence missing: {evidence.get('semantic_evidence_missing_turns', 0)}",
            f"- oracle evidence available: {evidence.get('oracle_evidence_available_turns', 0)}",
            f"- oracle evidence missing: {evidence.get('oracle_evidence_missing_turns', 0)}",
            f"- legacy_unverified_turns: {evidence.get('legacy_unverified_turns', 0)}",
            f"- expected contract checked: {evidence.get('expected_contract_checked_turns', 0)}",
            f"- expected contract missing evidence: {evidence.get('expected_contract_missing_evidence_turns', 0)}",
            f"- missing evidence reason: {evidence.get('missing_evidence_reason', [])}",
        ]
    )
    return "\n".join(lines)


def _is_random_turn_failed(row: MappingLike) -> bool:
    if row.get("success") is False:
        return True
    if row.get("llm_judge_failed") is True:
        return True
    status = _safe_text(row.get("semantic_status") or row.get("semantic_gate_status") or "")
    return status not in {"passed", "corrected_passed"}


def _is_real_user_failed(row: MappingLike) -> bool:
    if row.get("transport_success") is False or row.get("service_success") is False:
        return True
    if row.get("llm_judge_passed") is False:
        return True
    if _is_semantic_failed(row):
        return True
    if row.get("contract_satisfied") is False:
        return True
    if row.get("oracle_passed") is False:
        return True
    expected_check = _as_dict(row.get("expected_contract_check"))
    if expected_check.get("checked") is True and expected_check.get("passed") is False:
        return True
    comparison_status = _safe_text(row.get("comparison_status") or row.get("status"))
    if comparison_status and comparison_status not in {"response_collected", ""}:
        return True
    return False


def _is_semantic_passed(row: MappingLike) -> bool:
    return _safe_text(row.get("semantic_status") or row.get("semantic_gate_status")) in {"passed", "corrected_passed"}


def _is_semantic_failed(row: MappingLike) -> bool:
    status = _safe_text(row.get("semantic_status") or row.get("semantic_gate_status"))
    return status in {"failed", "needs_clarification", "legacy_unverified", "not_available", ""}


def _sum_numeric(rows: list[dict[str, Any]], key: str) -> int:
    return sum(_to_int(row.get(key)) for row in rows)


def _to_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _as_list(value: Any, default: list[Any] | None = None) -> list[Any]:
    if value is None:
        return default or []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return default or []


def _as_dict(value: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return default or {}


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _to_str_list(value: Any) -> list[str]:
    out: list[str] = []
    for item in _to_list(value):
        text = _safe_text(item).strip()
        if text:
            out.append(text)
    return out


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def _to_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _rate(numerator: Any, denominator: Any) -> str:
    n = _to_int(numerator)
    d = _to_int(denominator)
    if d <= 0:
        return NOT_AVAILABLE
    return round(n / d, 6)


def _format_rate(value: Any) -> str:
    if isinstance(value, (float, int)):
        return f"{float(value):.2%}" if isinstance(value, float) else str(value)
    if value == NOT_AVAILABLE:
        return NOT_AVAILABLE
    return _safe_text(value)


def _short_repr(value: Any, limit: int = 200) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    text = _safe_text(value).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _safe_id(value: Any) -> str:
    text = _safe_text(value).strip()
    return text or NOT_AVAILABLE


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        marker = f"{_safe_text(row.get('case_id'))}:{_safe_text(row.get('turn_id'))}:{_safe_text(row.get('semantic_status'))}"
        if marker in seen:
            continue
        seen.add(marker)
        out.append(row)
    return out


def _join_with_default(values: Any, default: str = "") -> str:
    if not values:
        return default
    if isinstance(values, (list, tuple)):
        return ", ".join(str(value) for value in values)
    return str(values)


def _escape_md(value: Any) -> str:
    text = _safe_text(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data
    return {}


def _load_rows_from_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handler:
        for line in handler:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _candidate_pass_rate(payload: MappingLike) -> float:
    candidate_score = _as_dict(payload.get("candidate_score"))
    if not candidate_score:
        return 0.0

    if _to_float(candidate_score.get("pass_rate")) is not None:
        return _to_float(candidate_score.get("pass_rate")) or 0.0

    summary = _as_dict(candidate_score.get("summary"))
    if _to_float(summary.get("candidate_acceptance_rate")) is not None:
        return _to_float(summary.get("candidate_acceptance_rate")) or 0.0
    if _to_float(summary.get("pass_rate")) is not None:
        return _to_float(summary.get("pass_rate")) or 0.0

    passed = _to_int(candidate_score.get("passed") or candidate_score.get("candidate_acceptable_count"))
    total = _to_int(candidate_score.get("total") or candidate_score.get("total_turns") or candidate_score.get("case_count"))
    return float(passed / total) if total else 0.0


def output_case_artifact(artifact: str, case_id: str) -> str:
    return f"{artifact}#{case_id}" if case_id else artifact


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in {"true", "1", "yes", "y"}:
            return True
        if low in {"false", "0", "no", "n"}:
            return False
    if value is None:
        return None
    return None


MappingLike = Mapping[str, Any]


if __name__ == "__main__":
    main()
