#!/usr/bin/env python3
"""Run random conversation eval across multiple seeds and aggregate summaries."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.eval_gate import EvalGateConfig, EvalGateMetrics, build_eval_gate_result, eval_gate_markdown, metrics_from_coverage

SUMMARY_FIELDS = [
    "seed",
    "output_dir",
    "pass_rate",
    "gate_passed",
    "gate_failed_reasons",
    "transport_pass_rate",
    "semantic_pass_rate",
    "oracle_pass_rate",
    "contract_satisfied_rate",
    "legacy_unverified_rate",
    "total_turns",
    "transport_success_turns",
    "semantic_contract_turns",
    "contract_checked_turns",
    "contract_satisfied_turns",
    "semantic_passed_turns",
    "semantic_failed_turns",
    "legacy_unverified_turns",
    "oracle_available_turns",
    "oracle_result_turns",
    "oracle_passed",
    "oracle_failed",
    "oracle_expected_missing",
    "oracle_actual_missing",
    "llm_judge_failed_turns",
    "top_violation_codes",
    "family_coverage",
    "scenario_families",
    "family_summary",
    "top_violation_codes_by_family",
]


def _to_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_top_violation_codes(payload: Any) -> list[dict[str, Any]]:
    raw_codes = []
    if isinstance(payload, dict):
        raw_codes = payload.get("top_contract_violation_codes", []) or []
    elif isinstance(payload, list):
        raw_codes = payload

    normalized: list[dict[str, Any]] = []
    for item in raw_codes:
        if isinstance(item, dict):
            code = item.get("code")
            if not isinstance(code, str):
                continue
            code = code.strip()
            if not code:
                continue
            count = item.get("count", 1)
            try:
                normalized_count = int(count)
            except (TypeError, ValueError):
                normalized_count = 1
            normalized.append({"code": code, "count": normalized_count})
            continue
        if not isinstance(item, str):
            continue
        code = item.strip()
        if not code:
            continue
        normalized.append({"code": code, "count": 1})
    return normalized


def _extract_summary_payload_from_stdout(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        candidate = line.strip()
        if not candidate:
            continue
        if not (candidate.startswith("{") and candidate.endswith("}")):
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    # fallback: try the last JSON-like segment from full stdout
    start = stdout.rfind("{")
    end = stdout.rfind("}")
    if start != -1 and end > start + 1:
        try:
            payload = json.loads(stdout[start : end + 1])
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            return None
    return None


def _collect_seed_summary(
    *,
    seed: int,
    output_dir: Path | None = None,
    summary_path: Path | None = None,
    gate_config: EvalGateConfig | None = None,
) -> dict[str, Any]:
    path = Path(summary_path) if summary_path else None
    output_dir_value = str(output_dir) if output_dir else ""
    if path is None and output_dir:
        path = Path(output_dir) / "summary.json"

    if path is None or not path.exists():
        return {
            "seed": seed,
            "output_dir": output_dir_value,
            "pass_rate": 0.0,
            "gate_passed": False,
            "gate_failed_reasons": ["summary_missing"],
            "transport_pass_rate": "not_available",
            "semantic_pass_rate": "not_available",
            "oracle_pass_rate": "not_available",
            "contract_satisfied_rate": "not_available",
            "legacy_unverified_rate": "not_available",
            "total_turns": 0,
            "transport_success_turns": 0,
            "semantic_contract_turns": 0,
            "contract_checked_turns": 0,
            "contract_satisfied_turns": 0,
            "semantic_passed_turns": 0,
            "semantic_failed_turns": 0,
            "legacy_unverified_turns": 0,
            "oracle_available_turns": 0,
            "oracle_result_turns": 0,
            "oracle_passed": 0,
            "oracle_failed": 0,
            "oracle_expected_missing": 0,
            "oracle_actual_missing": 0,
            "llm_judge_failed_turns": 0,
            "top_violation_codes": [],
            "family_coverage": {"required": [], "covered": [], "missing": [], "passed": True},
            "scenario_families": [],
            "family_summary": {"status": "not_available", "families": []},
            "top_violation_codes_by_family": {},
        }

    summary = json.loads(path.read_text(encoding="utf-8"))
    coverage = summary.get("coverage", {})
    gate_result = summary.get("gate_result") if isinstance(summary.get("gate_result"), dict) else build_eval_gate_result(
        metrics_from_coverage(coverage),
        gate_config or EvalGateConfig(),
    )

    return {
        "seed": seed,
        "output_dir": output_dir_value or str(path.parent),
        "pass_rate": _to_float(summary.get("pass_rate")),
        "gate_passed": bool(gate_result.get("gate_passed")),
        "gate_failed_reasons": list(gate_result.get("gate_failed_reasons") or []),
        "transport_pass_rate": gate_result.get("transport_pass_rate", "not_available"),
        "semantic_pass_rate": gate_result.get("semantic_pass_rate", "not_available"),
        "oracle_pass_rate": gate_result.get("oracle_pass_rate", "not_available"),
        "contract_satisfied_rate": gate_result.get("contract_satisfied_rate", "not_available"),
        "legacy_unverified_rate": gate_result.get("legacy_unverified_rate", "not_available"),
        "total_turns": _to_int(coverage.get("turn_count")),
        "transport_success_turns": _to_int(coverage.get("transport_success_turns", coverage.get("turn_count"))),
        "semantic_contract_turns": _to_int(coverage.get("semantic_contract_turns")),
        "contract_checked_turns": _to_int(coverage.get("contract_checked_turns")),
        "contract_satisfied_turns": _to_int(coverage.get("contract_satisfied_turns")),
        "semantic_passed_turns": _to_int(coverage.get("semantic_passed_turns")),
        "semantic_failed_turns": _to_int(coverage.get("semantic_failed_turns")),
        "legacy_unverified_turns": _to_int(coverage.get("legacy_unverified_turns")),
        "oracle_available_turns": _to_int(coverage.get("oracle_available_turns")),
        "oracle_result_turns": _to_int(coverage.get("oracle_result_turns")),
        "oracle_passed": _to_int(
            coverage.get("oracle_passed", coverage.get("oracle_passed_turns"))
        ),
        "oracle_failed": _to_int(
            coverage.get("oracle_failed", coverage.get("oracle_failed_turns"))
        ),
        "oracle_expected_missing": _to_int(
            coverage.get("oracle_expected_missing", coverage.get("oracle_expected_result_missing_turns"))
        ),
        "oracle_actual_missing": _to_int(
            coverage.get("oracle_actual_missing", coverage.get("oracle_actual_result_missing_turns"))
        ),
        "llm_judge_failed_turns": _to_int(
            summary.get("llm_judge_failed_turns", coverage.get("llm_judge_failed_turns"))
        ),
        "top_violation_codes": _normalize_top_violation_codes(
            coverage.get("top_violation_codes", coverage.get("top_contract_violation_codes", summary.get("top_contract_violation_codes", [])))
        ),
        "family_coverage": gate_result.get("family_coverage") or {},
        "scenario_families": list(summary.get("scenario_families") or coverage.get("scenario_families") or []),
        "family_summary": summary.get("family_summary") or coverage.get("family_summary") or {"status": "not_available", "families": []},
        "top_violation_codes_by_family": summary.get("top_violation_codes_by_family") or coverage.get("top_violation_codes_by_family") or {},
    }


def _parse_seeds(seed_csv: str) -> list[int]:
    seeds = [item.strip() for item in seed_csv.split(",") if item.strip()]
    return [int(seed) for seed in seeds]


def _parse_markdown_cell(value: Any) -> str:
    if isinstance(value, list):
        if all(isinstance(item, dict) and "code" in item for item in value):
            return ", ".join(f"{item.get('code')}={item.get('count')}" for item in value)
        return ", ".join(str(item) for item in value)
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _print_markdown_table(rows: list[dict[str, Any]]) -> None:
    header = "| " + " | ".join(SUMMARY_FIELDS) + " |"
    divider = "|" + "|".join(" --- " for _ in SUMMARY_FIELDS) + "|"
    print(header)
    print(divider)
    for row in rows:
        values = [_parse_markdown_cell(row.get(key, "")) for key in SUMMARY_FIELDS]
        print("| " + " | ".join(values) + " |")


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized_rows = []
    for row in rows:
        normalized = dict(row)
        normalized["top_violation_codes"] = json.dumps(row.get("top_violation_codes", []), ensure_ascii=False)
        normalized["gate_failed_reasons"] = json.dumps(row.get("gate_failed_reasons", []), ensure_ascii=False)
        normalized["family_coverage"] = json.dumps(row.get("family_coverage", {}), ensure_ascii=False)
        normalized["scenario_families"] = json.dumps(row.get("scenario_families", []), ensure_ascii=False)
        normalized["family_summary"] = json.dumps(row.get("family_summary", {}), ensure_ascii=False)
        normalized["top_violation_codes_by_family"] = json.dumps(row.get("top_violation_codes_by_family", {}), ensure_ascii=False)
        normalized_rows.append(normalized)

    with path.open("w", encoding="utf-8", newline="") as handler:
        writer = csv.DictWriter(handler, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(normalized_rows)


def _write_json(rows: list[dict[str, Any]], path: Path, output_root: Path, *, gate_result: dict[str, Any]) -> None:
    family_metrics = aggregate_multi_seed_family_metrics(rows, gate_result=gate_result)
    payload = {
        "output_root": str(output_root),
        "rows": rows,
        "count": len(rows),
        "gate_result": gate_result,
        "gate_passed": gate_result.get("gate_passed", False),
        "gate_failed_reasons": gate_result.get("gate_failed_reasons", []),
        **family_metrics,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_multi_seed_eval(
    seeds: list[int],
    *,
    output_root: Path,
    gate_config: EvalGateConfig | None = None,
    scenario_families: list[str] | None = None,
) -> list[dict[str, Any]]:
    output_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for seed in seeds:
        config = gate_config or EvalGateConfig()
        command = [
            "python3",
            str(REPO_ROOT / "scripts/run_agent_random_conversation_eval.py"),
            "--seed",
            str(seed),
            "--max-semantic-failed-turns",
            str(config.max_semantic_failed_turns),
            "--max-oracle-failed-turns",
            str(config.max_oracle_failed_turns),
            "--max-legacy-unverified-rate",
            str(config.max_legacy_unverified_rate),
        ]
        for family in scenario_families or []:
            command.extend(["--scenario-family", str(family)])
        for family in config.required_families:
            command.extend(["--required-family", str(family)])
        run = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        payload = _extract_summary_payload_from_stdout(run.stdout) or {}
        output_dir = Path(payload.get("output_dir", "")).resolve() if payload.get("output_dir") else None
        summary_path = None
        if isinstance(payload.get("artifacts"), dict):
            summary_path_raw = payload["artifacts"].get("summary_json")
            if summary_path_raw:
                summary_path = Path(summary_path_raw)
        elif output_dir:
            candidate = output_dir / "summary.json"
            if candidate.exists():
                summary_path = candidate

        row = _collect_seed_summary(seed=seed, output_dir=output_dir, summary_path=summary_path, gate_config=gate_config)
        rows.append(row)

        if run.returncode != 0:
            row["gate_passed"] = False
            row["gate_failed_reasons"] = list(row.get("gate_failed_reasons") or []) + [f"seed_run_failed:{run.returncode}"]
            print(f"[warn] seed={seed} run failed with exit code {run.returncode}", file=sys.stderr)
    return rows


def aggregate_multi_seed_family_metrics(rows: list[dict[str, Any]], *, gate_result: dict[str, Any] | None = None) -> dict[str, Any]:
    families_run: set[str] = set()
    family_values: dict[str, dict[str, int]] = {}
    family_violation_counts: dict[str, Counter[str]] = {}
    for row in rows:
        families_run.update(str(item) for item in row.get("scenario_families") or [] if str(item))
        family_summary = row.get("family_summary") if isinstance(row.get("family_summary"), dict) else {}
        for item in family_summary.get("families") or []:
            if not isinstance(item, dict):
                continue
            family = str(item.get("family") or "").strip()
            if not family:
                continue
            families_run.add(family)
            values = family_values.setdefault(
                family,
                {
                    "conversation_count": 0,
                    "passed_conversation_count": 0,
                    "semantic_contract_turns": 0,
                    "semantic_passed_turns": 0,
                    "oracle_available_turns": 0,
                    "oracle_passed_turns": 0,
                    "expected_contract_checked_turns": 0,
                    "expected_contract_passed_turns": 0,
                },
            )
            values["conversation_count"] += _to_int(item.get("conversation_count"))
            values["passed_conversation_count"] += _to_int(item.get("passed_conversation_count"))
            values["semantic_contract_turns"] += _to_int(item.get("semantic_contract_turns"))
            values["semantic_passed_turns"] += _to_int(item.get("semantic_passed_turns"))
            values["oracle_available_turns"] += _to_int(item.get("oracle_available_turns"))
            values["oracle_passed_turns"] += _to_int(item.get("oracle_passed_turns"))
            values["expected_contract_checked_turns"] += _to_int(item.get("expected_contract_checked_turns"))
            values["expected_contract_passed_turns"] += _to_int(item.get("expected_contract_passed_turns"))
            counts = family_violation_counts.setdefault(family, Counter())
            for violation in item.get("top_violation_codes") or []:
                if isinstance(violation, dict) and violation.get("code"):
                    counts[str(violation["code"])] += _to_int(violation.get("count")) or 1
        top_by_family = row.get("top_violation_codes_by_family") if isinstance(row.get("top_violation_codes_by_family"), dict) else {}
        for family, violations in top_by_family.items():
            families_run.add(str(family))
            counts = family_violation_counts.setdefault(str(family), Counter())
            for violation in violations or []:
                if isinstance(violation, dict) and violation.get("code"):
                    counts[str(violation["code"])] += _to_int(violation.get("count")) or 1
    per_family_pass_rate = {
        family: _rate(values.get("passed_conversation_count"), values.get("conversation_count"))
        for family, values in sorted(family_values.items())
    }
    per_family_semantic_pass_rate = {
        family: _rate(values.get("semantic_passed_turns"), values.get("semantic_contract_turns"))
        for family, values in sorted(family_values.items())
    }
    per_family_oracle_pass_rate = {
        family: _rate(values.get("oracle_passed_turns"), values.get("oracle_available_turns"))
        for family, values in sorted(family_values.items())
    }
    per_family_expected_contract_pass_rate = {
        family: _rate(values.get("expected_contract_passed_turns"), values.get("expected_contract_checked_turns"))
        for family, values in sorted(family_values.items())
    }
    return {
        "families_run": sorted(families_run),
        "family_coverage": (gate_result or {}).get("family_coverage", {}),
        "per_family_pass_rate": per_family_pass_rate,
        "per_family_semantic_pass_rate": per_family_semantic_pass_rate,
        "per_family_oracle_pass_rate": per_family_oracle_pass_rate,
        "per_family_expected_contract_pass_rate": per_family_expected_contract_pass_rate,
        "top_violation_codes_by_family": {
            family: [{"code": code, "count": count} for code, count in counts.most_common(10)]
            for family, counts in sorted(family_violation_counts.items())
        },
    }


def _rate(numerator: Any, denominator: Any) -> float | str:
    denominator_int = _to_int(denominator)
    if denominator_int <= 0:
        return "not_available"
    return _to_int(numerator) / denominator_int


def aggregate_multi_seed_gate(rows: list[dict[str, Any]], *, gate_config: EvalGateConfig | None = None) -> dict[str, Any]:
    violation_counts: Counter[str] = Counter()
    covered_families: set[str] = set()
    for row in rows:
        for item in row.get("top_violation_codes") or []:
            if isinstance(item, dict) and item.get("code"):
                violation_counts[str(item["code"])] += _to_int(item.get("count")) or 1
        family_coverage = row.get("family_coverage") if isinstance(row.get("family_coverage"), dict) else {}
        covered_families.update(str(item) for item in family_coverage.get("covered", []) if str(item))
        covered_families.update(str(item) for item in row.get("scenario_families", []) if str(item))
    gate_result = build_eval_gate_result(
        EvalGateMetrics(
            total_turns=sum(_to_int(row.get("total_turns")) for row in rows),
            transport_success_turns=sum(_to_int(row.get("transport_success_turns")) for row in rows),
            semantic_contract_turns=sum(_to_int(row.get("semantic_contract_turns")) for row in rows),
            semantic_passed_turns=sum(_to_int(row.get("semantic_passed_turns")) for row in rows),
            semantic_failed_turns=sum(_to_int(row.get("semantic_failed_turns")) for row in rows),
            oracle_available_turns=sum(_to_int(row.get("oracle_available_turns")) for row in rows),
            oracle_passed_turns=sum(_to_int(row.get("oracle_passed")) for row in rows),
            oracle_failed_turns=sum(_to_int(row.get("oracle_failed")) for row in rows),
            contract_satisfied_turns=sum(_to_int(row.get("contract_satisfied_turns")) for row in rows),
            legacy_unverified_turns=sum(_to_int(row.get("legacy_unverified_turns")) for row in rows),
            covered_families=tuple(sorted(covered_families)),
            top_violation_codes=tuple({"code": code, "count": count} for code, count in violation_counts.most_common(12)),
        ),
        gate_config or EvalGateConfig(),
    )
    failed_reasons = list(gate_result["gate_failed_reasons"])
    for row in rows:
        if row.get("gate_passed") is False:
            failed_reasons.append(f"seed_gate_failed:{row.get('seed')}")
    gate_result["gate_failed_reasons"] = sorted(set(failed_reasons))
    gate_result["gate_passed"] = not gate_result["gate_failed_reasons"]
    return gate_result


def _write_markdown_report(rows: list[dict[str, Any]], path: Path, *, gate_result: dict[str, Any]) -> None:
    family_metrics = aggregate_multi_seed_family_metrics(rows, gate_result=gate_result)
    lines = [
        "# Multi-seed Agent Random Eval",
        "",
        eval_gate_markdown(gate_result, title="Multi-seed Multi-metric Eval Gate"),
        "",
        "## Scenario Families",
        "",
        f"- families_run: {', '.join(family_metrics.get('families_run') or []) or '-'}",
        f"- family_coverage: {json.dumps(family_metrics.get('family_coverage') or {}, ensure_ascii=False)}",
        "",
        "| family | pass_rate | semantic_pass_rate | oracle_pass_rate | expected_contract_pass_rate | top_violation_codes |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for family in family_metrics.get("families_run") or []:
        top_codes = family_metrics.get("top_violation_codes_by_family", {}).get(family, [])
        lines.append(
            "| "
            + " | ".join(
                [
                    str(family),
                    _parse_markdown_cell(family_metrics.get("per_family_pass_rate", {}).get(family, "not_available")),
                    _parse_markdown_cell(family_metrics.get("per_family_semantic_pass_rate", {}).get(family, "not_available")),
                    _parse_markdown_cell(family_metrics.get("per_family_oracle_pass_rate", {}).get(family, "not_available")),
                    _parse_markdown_cell(family_metrics.get("per_family_expected_contract_pass_rate", {}).get(family, "not_available")),
                    _parse_markdown_cell(top_codes),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
        "## Seeds",
        "",
        ]
    )
    for row in rows:
        lines.append(
            f"- seed={row.get('seed')} pass_rate={_parse_markdown_cell(row.get('pass_rate'))} "
            f"gate_passed={row.get('gate_passed')} reasons={_parse_markdown_cell(row.get('gate_failed_reasons') or [])}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build_seeds(args: argparse.Namespace) -> list[int]:
    if args.seeds:
        return _parse_seeds(args.seeds)
    if args.num_seeds <= 0:
        raise ValueError("--num-seeds must be greater than 0 when --seeds is not provided.")
    return [args.base_seed + index for index in range(args.num_seeds)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run multi-seed random-agent eval and collect summaries.")
    parser.add_argument("--seeds", default="", help="Comma separated list of seeds, e.g. 20260603,20260604")
    parser.add_argument("--num-seeds", type=int, default=1)
    parser.add_argument("--base-seed", type=int, default=20260603)
    parser.add_argument("--output-root", default="outputs/agent_random_eval_multi_seed")
    parser.add_argument("--max-semantic-failed-turns", type=int, default=0)
    parser.add_argument("--max-oracle-failed-turns", type=int, default=0)
    parser.add_argument("--max-legacy-unverified-rate", type=float, default=0.2)
    parser.add_argument("--scenario-family", action="append", default=[], help="Scenario family to pass to each seed run. Repeat or use all.")
    parser.add_argument("--required-family", action="append", default=[], help="Required scenario family coverage for aggregate gate.")
    args = parser.parse_args()
    try:
        seeds = build_seeds(args)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = REPO_ROOT / output_root
    gate_config = EvalGateConfig(
        max_semantic_failed_turns=max(0, int(args.max_semantic_failed_turns or 0)),
        max_oracle_failed_turns=max(0, int(args.max_oracle_failed_turns or 0)),
        max_legacy_unverified_rate=max(0.0, min(1.0, float(args.max_legacy_unverified_rate))),
        required_families=tuple(args.required_family or ()),
    )
    rows = run_multi_seed_eval(seeds, output_root=output_root, gate_config=gate_config, scenario_families=list(args.scenario_family or []))
    gate_result = aggregate_multi_seed_gate(rows, gate_config=gate_config)

    csv_path = output_root / "multi_seed_summary.csv"
    json_path = output_root / "multi_seed_summary.json"
    report_path = output_root / "multi_seed_report.md"
    _write_csv(rows, csv_path)
    _write_json(rows, json_path, output_root, gate_result=gate_result)
    _write_markdown_report(rows, report_path, gate_result=gate_result)

    print(f"multi_seed_summary.csv: {csv_path}")
    print(f"multi_seed_summary.json: {json_path}")
    print(f"multi_seed_report.md: {report_path}")
    print(f"gate_passed: {gate_result.get('gate_passed', False)}")
    if gate_result.get("gate_failed_reasons"):
        print("gate_failed_reasons: " + ", ".join(str(item) for item in gate_result.get("gate_failed_reasons") or []))
    _print_markdown_table(rows)
    if not gate_result.get("gate_passed", False):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
