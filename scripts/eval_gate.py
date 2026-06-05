"""Shared multi-metric eval gate helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class EvalGateConfig:
    min_transport_pass_rate: float = 0.0
    max_semantic_failed_turns: int = 0
    max_oracle_failed_turns: int = 0
    max_expected_contract_failed_turns: int = 0
    max_legacy_unverified_rate: float = 0.2
    required_families: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvalGateMetrics:
    total_turns: int = 0
    transport_success_turns: int | None = None
    semantic_contract_turns: int = 0
    semantic_passed_turns: int = 0
    semantic_failed_turns: int = 0
    oracle_available_turns: int = 0
    oracle_passed_turns: int = 0
    oracle_failed_turns: int = 0
    contract_satisfied_turns: int = 0
    legacy_unverified_turns: int = 0
    expected_contract_checked_turns: int = 0
    expected_contract_passed_turns: int = 0
    expected_contract_failed_turns: int = 0
    expected_contract_missing_evidence_turns: int = 0
    expected_contract_available_turns: int = 0
    expected_contract_not_instrumented_turns: int = 0
    expected_contract_coverage_risk_turns: int = 0
    expected_contract_coverage_status: str = ""
    covered_families: tuple[str, ...] = ()
    top_violation_codes: tuple[dict[str, Any], ...] = ()
    expected_contract_issue_codes: tuple[dict[str, Any], ...] = ()


def build_eval_gate_result(metrics: EvalGateMetrics, config: EvalGateConfig | None = None) -> dict[str, Any]:
    gate_config = config or EvalGateConfig()
    total_turns = max(0, int(metrics.total_turns or 0))
    transport_success = metrics.transport_success_turns
    if transport_success is None:
        transport_success = total_turns
    semantic_denominator = int(metrics.semantic_contract_turns or 0)
    oracle_denominator = int(metrics.oracle_available_turns or 0)
    family_coverage = _family_coverage(metrics.covered_families, gate_config.required_families)
    transport_pass_rate = _rate(transport_success, total_turns)
    semantic_pass_rate = _rate(metrics.semantic_passed_turns, semantic_denominator)
    oracle_pass_rate = _rate(metrics.oracle_passed_turns, oracle_denominator)
    contract_satisfied_rate = _rate(metrics.contract_satisfied_turns, semantic_denominator)
    legacy_unverified_rate = _rate(metrics.legacy_unverified_turns, total_turns)
    expected_contract_pass_rate = _rate(metrics.expected_contract_passed_turns, metrics.expected_contract_checked_turns)
    expected_contract_available_turns = int(
        metrics.expected_contract_available_turns
        or int(metrics.expected_contract_checked_turns or 0)
        + int(metrics.expected_contract_missing_evidence_turns or 0)
    )
    expected_contract_not_instrumented_turns = int(metrics.expected_contract_not_instrumented_turns or 0)
    expected_contract_coverage_risk_turns = int(
        metrics.expected_contract_coverage_risk_turns
        or expected_contract_not_instrumented_turns
        + int(metrics.expected_contract_missing_evidence_turns or 0)
    )
    expected_contract_coverage_status = str(metrics.expected_contract_coverage_status or "").strip() or _expected_contract_coverage_status(
        total_turns=total_turns,
        checked_turns=int(metrics.expected_contract_checked_turns or 0),
        missing_evidence_turns=int(metrics.expected_contract_missing_evidence_turns or 0),
        not_instrumented_turns=expected_contract_not_instrumented_turns,
    )

    failed_reasons: list[str] = []
    if total_turns <= 0:
        failed_reasons.append("no_turns_available")
    if isinstance(transport_pass_rate, float) and transport_pass_rate < gate_config.min_transport_pass_rate:
        failed_reasons.append(
            f"transport_pass_rate_below_threshold:{transport_pass_rate:.4f}<{gate_config.min_transport_pass_rate:.4f}"
        )
    if int(metrics.semantic_failed_turns or 0) > gate_config.max_semantic_failed_turns:
        failed_reasons.append(
            f"semantic_failed_turns_above_threshold:{int(metrics.semantic_failed_turns)}>{gate_config.max_semantic_failed_turns}"
        )
    if int(metrics.oracle_failed_turns or 0) > gate_config.max_oracle_failed_turns:
        failed_reasons.append(f"oracle_failed_turns_above_threshold:{int(metrics.oracle_failed_turns)}>{gate_config.max_oracle_failed_turns}")
    if int(metrics.expected_contract_failed_turns or 0) > gate_config.max_expected_contract_failed_turns:
        failed_reasons.append(
            f"expected_contract_failed_turns_above_threshold:{int(metrics.expected_contract_failed_turns)}>{gate_config.max_expected_contract_failed_turns}"
        )
    if isinstance(legacy_unverified_rate, float) and legacy_unverified_rate > gate_config.max_legacy_unverified_rate:
        failed_reasons.append(
            f"legacy_unverified_rate_above_threshold:{legacy_unverified_rate:.4f}>{gate_config.max_legacy_unverified_rate:.4f}"
        )
    for family in family_coverage["missing"]:
        failed_reasons.append(f"missing_required_family:{family}")

    return {
        "gate_passed": not failed_reasons,
        "gate_failed_reasons": failed_reasons,
        "transport_pass_rate": transport_pass_rate,
        "semantic_pass_rate": semantic_pass_rate,
        "oracle_pass_rate": oracle_pass_rate,
        "contract_satisfied_rate": contract_satisfied_rate,
        "legacy_unverified_rate": legacy_unverified_rate,
        "expected_contract_pass_rate": expected_contract_pass_rate,
        "expected_contract_checked_turns": int(metrics.expected_contract_checked_turns or 0),
        "expected_contract_passed_turns": int(metrics.expected_contract_passed_turns or 0),
        "expected_contract_failed_turns": int(metrics.expected_contract_failed_turns or 0),
        "expected_contract_missing_evidence_turns": int(metrics.expected_contract_missing_evidence_turns or 0),
        "expected_contract_available_turns": expected_contract_available_turns,
        "expected_contract_not_instrumented_turns": expected_contract_not_instrumented_turns,
        "expected_contract_coverage_risk_turns": expected_contract_coverage_risk_turns,
        "expected_contract_coverage_status": expected_contract_coverage_status,
        "expected_contract_issue_codes": list(metrics.expected_contract_issue_codes),
        "family_coverage": family_coverage,
        "top_violation_codes": list(metrics.top_violation_codes),
        "thresholds": gate_config.to_dict(),
    }


def metrics_from_coverage(
    coverage: Mapping[str, Any],
    *,
    required_families: Sequence[str] = (),
    transport_success_turns: int | None = None,
    top_violation_codes: Any | None = None,
) -> EvalGateMetrics:
    top_codes = top_violation_codes
    if top_codes is None:
        top_codes = coverage.get("top_violation_codes", coverage.get("top_contract_violation_codes", []))
    total_turns = _to_int(coverage.get("turn_count", coverage.get("total_turns")))
    return EvalGateMetrics(
        total_turns=total_turns,
        transport_success_turns=transport_success_turns,
        semantic_contract_turns=_to_int(coverage.get("semantic_contract_turns", coverage.get("semantic_checked_turns"))),
        semantic_passed_turns=_to_int(coverage.get("semantic_passed_turns")),
        semantic_failed_turns=_to_int(coverage.get("semantic_failed_turns")),
        oracle_available_turns=_to_int(coverage.get("oracle_available_turns")),
        oracle_passed_turns=_to_int(coverage.get("oracle_passed_turns", coverage.get("oracle_passed"))),
        oracle_failed_turns=_to_int(coverage.get("oracle_failed_turns", coverage.get("oracle_failed"))),
        contract_satisfied_turns=_to_int(coverage.get("contract_satisfied_turns")),
        legacy_unverified_turns=_legacy_unverified_turns(coverage, total_turns),
        expected_contract_checked_turns=_to_int(coverage.get("expected_contract_checked_turns")),
        expected_contract_passed_turns=_to_int(coverage.get("expected_contract_passed_turns")),
        expected_contract_failed_turns=_to_int(coverage.get("expected_contract_failed_turns")),
        expected_contract_missing_evidence_turns=_to_int(coverage.get("expected_contract_missing_evidence_turns")),
        expected_contract_available_turns=_to_int(coverage.get("expected_contract_available_turns")),
        expected_contract_not_instrumented_turns=_to_int(coverage.get("expected_contract_not_instrumented_turns")),
        expected_contract_coverage_risk_turns=_to_int(coverage.get("expected_contract_coverage_risk_turns")),
        expected_contract_coverage_status=str(coverage.get("expected_contract_coverage_status") or ""),
        covered_families=tuple(
            str(item)
            for item in coverage.get(
                "scenario_families",
                coverage.get("covered_families", coverage.get("capability_families", [])),
            )
            or []
        ),
        top_violation_codes=tuple(_normalize_top_violation_codes(top_codes)),
        expected_contract_issue_codes=tuple(_normalize_top_violation_codes(coverage.get("expected_contract_issue_codes", []))),
    )


def metrics_from_real_user_summary(summary: Mapping[str, Any], *, required_families: Sequence[str] = ()) -> EvalGateMetrics:
    total_turns = _to_int(summary.get("case_count"))
    return EvalGateMetrics(
        total_turns=total_turns,
        transport_success_turns=_to_int(summary.get("transport_success_turns")),
        semantic_contract_turns=_to_int(summary.get("semantic_checked_turns")),
        semantic_passed_turns=_to_int(summary.get("semantic_passed_turns")),
        semantic_failed_turns=_to_int(summary.get("semantic_failed_turns")),
        oracle_available_turns=_to_int(summary.get("oracle_available_turns")),
        oracle_passed_turns=_to_int(summary.get("oracle_passed_turns")),
        oracle_failed_turns=_to_int(summary.get("oracle_failed_turns")),
        contract_satisfied_turns=_to_int(summary.get("contract_satisfied_turns")),
        legacy_unverified_turns=_legacy_unverified_turns(summary, total_turns),
        expected_contract_checked_turns=_to_int(summary.get("expected_contract_checked_turns")),
        expected_contract_passed_turns=_to_int(summary.get("expected_contract_passed_turns")),
        expected_contract_failed_turns=_to_int(summary.get("expected_contract_failed_turns")),
        expected_contract_missing_evidence_turns=_to_int(summary.get("expected_contract_missing_evidence_turns")),
        expected_contract_available_turns=_to_int(summary.get("expected_contract_available_turns")),
        expected_contract_not_instrumented_turns=_to_int(summary.get("expected_contract_not_instrumented_turns")),
        expected_contract_coverage_risk_turns=_to_int(summary.get("expected_contract_coverage_risk_turns")),
        expected_contract_coverage_status=str(summary.get("expected_contract_coverage_status") or ""),
        covered_families=tuple(str(item) for item in _real_user_families(summary)),
        top_violation_codes=tuple(_normalize_top_violation_codes(summary.get("top_violation_codes", []))),
        expected_contract_issue_codes=tuple(_normalize_top_violation_codes(summary.get("expected_contract_issue_codes", []))),
    )


def eval_gate_markdown(gate_result: Mapping[str, Any], *, title: str = "Eval Gate") -> str:
    lines = [
        f"## {title}",
        "",
        f"- Gate passed: {gate_result.get('gate_passed', False)}",
        f"- Failed reasons: {', '.join(gate_result.get('gate_failed_reasons') or []) or 'none'}",
        f"- Transport pass rate: {_display_rate(gate_result.get('transport_pass_rate'))}",
        f"- Semantic pass rate: {_display_rate(gate_result.get('semantic_pass_rate'))}",
        f"- Oracle pass rate: {_display_rate(gate_result.get('oracle_pass_rate'))}",
        f"- Contract satisfied rate: {_display_rate(gate_result.get('contract_satisfied_rate'))}",
        f"- Legacy unverified rate: {_display_rate(gate_result.get('legacy_unverified_rate'))}",
        f"- Expected contract pass rate: {_display_rate(gate_result.get('expected_contract_pass_rate'))}",
        f"- Expected contract checked: {gate_result.get('expected_contract_checked_turns', 0)}",
        f"- Expected contract failed: {gate_result.get('expected_contract_failed_turns', 0)}",
        f"- Expected contract missing evidence: {gate_result.get('expected_contract_missing_evidence_turns', 0)}",
        f"- Expected contract coverage status: {gate_result.get('expected_contract_coverage_status') or 'not_available'}",
        f"- Expected contract available turns: {gate_result.get('expected_contract_available_turns', 0)}",
        f"- Expected contract not instrumented turns: {gate_result.get('expected_contract_not_instrumented_turns', 0)}",
        f"- Expected contract coverage risk turns: {gate_result.get('expected_contract_coverage_risk_turns', 0)}",
    ]
    family_coverage = gate_result.get("family_coverage") if isinstance(gate_result.get("family_coverage"), Mapping) else {}
    lines.append(f"- Family coverage: {', '.join(family_coverage.get('covered') or []) or '-'}")
    if family_coverage.get("missing"):
        lines.append(f"- Missing required families: {', '.join(family_coverage.get('missing') or [])}")
    top_codes = gate_result.get("top_violation_codes") or []
    if top_codes:
        lines.append("- Top violation codes: " + ", ".join(f"{item.get('code')}={item.get('count')}" for item in top_codes if isinstance(item, Mapping)))
    else:
        lines.append("- Top violation codes: none")
    expected_codes = gate_result.get("expected_contract_issue_codes") or []
    if expected_codes:
        lines.append(
            "- Expected contract issue codes: "
            + ", ".join(f"{item.get('code')}={item.get('count')}" for item in expected_codes if isinstance(item, Mapping))
        )
    else:
        lines.append("- Expected contract issue codes: none")
    return "\n".join(lines)


def _rate(numerator: Any, denominator: Any) -> float | str:
    denominator_int = _to_int(denominator)
    if denominator_int <= 0:
        return "not_available"
    return _to_int(numerator) / denominator_int


def _expected_contract_coverage_status(
    *,
    total_turns: int,
    checked_turns: int,
    missing_evidence_turns: int,
    not_instrumented_turns: int,
) -> str:
    if checked_turns > 0 and (missing_evidence_turns > 0 or not_instrumented_turns > 0):
        return "partial"
    if checked_turns > 0:
        return "available"
    if missing_evidence_turns > 0:
        return "missing"
    if not_instrumented_turns > 0 or total_turns > 0:
        return "not_instrumented"
    return "not_available"


def _family_coverage(covered: Sequence[str], required: Sequence[str]) -> dict[str, Any]:
    covered_values = sorted({str(item) for item in covered if str(item)})
    required_values = sorted({str(item) for item in required if str(item)})
    missing = [family for family in required_values if family not in covered_values]
    return {
        "required": required_values,
        "covered": covered_values,
        "missing": missing,
        "required_count": len(required_values),
        "covered_required_count": len(required_values) - len(missing),
        "covered_count": len(covered_values),
        "passed": not missing,
    }


def _real_user_families(summary: Mapping[str, Any]) -> list[str]:
    comparison = summary.get("comparison")
    if not isinstance(comparison, list):
        return []
    families = []
    for row in comparison:
        if isinstance(row, Mapping) and row.get("capability_family"):
            families.append(str(row["capability_family"]))
    return sorted(set(families))


def _normalize_top_violation_codes(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, Mapping):
        payload = [{"code": code, "count": count} for code, count in payload.items()]
    if not isinstance(payload, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, Mapping):
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            normalized.append({"code": code, "count": _to_int(item.get("count")) or 1})
    return normalized


def _legacy_unverified_turns(payload: Mapping[str, Any], total_turns: int) -> int:
    if "legacy_unverified_turns" in payload:
        return _to_int(payload.get("legacy_unverified_turns"))
    evidence_keys = {
        "semantic_contract_turns",
        "semantic_checked_turns",
        "semantic_passed_turns",
        "semantic_failed_turns",
        "contract_satisfied_turns",
    }
    if total_turns > 0 and not any(key in payload for key in evidence_keys):
        return total_turns
    return 0


def _display_rate(value: Any) -> str:
    if isinstance(value, (float, int)):
        return f"{float(value):.2%}"
    return str(value or "not_available")


def _to_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0
