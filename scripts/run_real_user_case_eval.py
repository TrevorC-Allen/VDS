#!/usr/bin/env python3
"""Run real-user VDS cases from a manifest through service or HTTP targets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.real_user_eval.http_target import HttpEvalTarget
from scripts.real_user_eval.manifest import load_manifest, validate_v1_coverage
from scripts.real_user_eval.runner import DEFAULT_SCORE_JUDGE, run_manifest
from scripts.real_user_eval.service_target import ServiceEvalTarget


DEFAULT_MANIFEST = REPO_ROOT / "configs" / "eval_gate" / "real_user_case_manifest_v1.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run real-user VDS manifest cases.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Path to real_user_case_manifest JSON.")
    parser.add_argument("--target", choices=("service", "http"), default="service")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Base URL for --target http.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-variants-per-case", type=int)
    parser.add_argument("--skip-conversations", action="store_true")
    parser.add_argument("--enforce-v1-coverage", action="store_true")
    parser.add_argument("--score-judge", choices=("heuristic", "llm", "auto"), default=DEFAULT_SCORE_JUDGE)
    parser.add_argument("--min-acceptable", type=float, default=75.0)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    coverage = validate_v1_coverage(manifest) if args.enforce_v1_coverage else None
    target: Any
    if args.target == "http":
        target = HttpEvalTarget(args.base_url)
    else:
        target = ServiceEvalTarget()
    summary = run_manifest(
        manifest,
        target,
        output_dir=Path(args.output_dir),
        max_variants_per_case=args.max_variants_per_case,
        include_conversations=not args.skip_conversations,
        score_judge=args.score_judge,
        min_acceptable=args.min_acceptable,
    )
    if args.print_summary:
        print(
            json.dumps(
                {
                    "output_dir": str(Path(args.output_dir)),
                    "cases": summary["case_count"],
                    "passed": summary["passed"],
                    "failed": summary["failed"],
                    "acceptance_source": summary.get("acceptance_source"),
                    "coverage": coverage,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
