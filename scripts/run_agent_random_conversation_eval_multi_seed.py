#!/usr/bin/env python3
"""Run random conversation eval across multiple seeds and aggregate summaries."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

SUMMARY_FIELDS = [
    "seed",
    "output_dir",
    "pass_rate",
    "total_turns",
    "contract_checked_turns",
    "contract_satisfied_turns",
    "semantic_passed_turns",
    "semantic_failed_turns",
    "oracle_result_turns",
    "oracle_passed",
    "oracle_failed",
    "oracle_expected_missing",
    "oracle_actual_missing",
    "llm_judge_failed_turns",
    "top_violation_codes",
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
            "total_turns": 0,
            "contract_checked_turns": 0,
            "contract_satisfied_turns": 0,
            "semantic_passed_turns": 0,
            "semantic_failed_turns": 0,
            "oracle_result_turns": 0,
            "oracle_passed": 0,
            "oracle_failed": 0,
            "oracle_expected_missing": 0,
            "oracle_actual_missing": 0,
            "llm_judge_failed_turns": 0,
            "top_violation_codes": [],
        }

    summary = json.loads(path.read_text(encoding="utf-8"))
    coverage = summary.get("coverage", {})

    return {
        "seed": seed,
        "output_dir": output_dir_value or str(path.parent),
        "pass_rate": _to_float(summary.get("pass_rate")),
        "total_turns": _to_int(coverage.get("turn_count")),
        "contract_checked_turns": _to_int(coverage.get("contract_checked_turns")),
        "contract_satisfied_turns": _to_int(coverage.get("contract_satisfied_turns")),
        "semantic_passed_turns": _to_int(coverage.get("semantic_passed_turns")),
        "semantic_failed_turns": _to_int(coverage.get("semantic_failed_turns")),
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
            coverage.get("top_contract_violation_codes", summary.get("top_contract_violation_codes", []))
        ),
    }


def _parse_seeds(seed_csv: str) -> list[int]:
    seeds = [item.strip() for item in seed_csv.split(",") if item.strip()]
    return [int(seed) for seed in seeds]


def _parse_markdown_cell(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(f"{item.get('code')}={item.get('count')}" for item in value)
    if isinstance(value, float):
        return f"{value:.4f}"
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
        normalized_rows.append(normalized)

    with path.open("w", encoding="utf-8", newline="") as handler:
        writer = csv.DictWriter(handler, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(normalized_rows)


def _write_json(rows: list[dict[str, Any]], path: Path, output_root: Path) -> None:
    payload = {
        "output_root": str(output_root),
        "rows": rows,
        "count": len(rows),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_multi_seed_eval(seeds: list[int], *, output_root: Path) -> list[dict[str, Any]]:
    output_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for seed in seeds:
        command = ["python3", str(REPO_ROOT / "scripts/run_agent_random_conversation_eval.py"), "--seed", str(seed)]
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

        row = _collect_seed_summary(seed=seed, output_dir=output_dir, summary_path=summary_path)
        rows.append(row)

        if run.returncode != 0:
            print(f"[warn] seed={seed} run failed with exit code {run.returncode}", file=sys.stderr)
    return rows


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
    args = parser.parse_args()
    try:
        seeds = build_seeds(args)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = REPO_ROOT / output_root
    rows = run_multi_seed_eval(seeds, output_root=output_root)

    csv_path = output_root / "multi_seed_summary.csv"
    json_path = output_root / "multi_seed_summary.json"
    _write_csv(rows, csv_path)
    _write_json(rows, json_path, output_root)

    print(f"multi_seed_summary.csv: {csv_path}")
    print(f"multi_seed_summary.json: {json_path}")
    _print_markdown_table(rows)


if __name__ == "__main__":
    main()
