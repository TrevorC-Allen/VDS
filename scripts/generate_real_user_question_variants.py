#!/usr/bin/env python3
"""Generate real-user question variants with an LLM, then freeze them into a manifest."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import random
import sys
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent_core.llm.client import load_llm_client_from_env
from scripts.real_user_eval.manifest import (
    FORBIDDEN_VARIANT_TOKENS,
    load_manifest,
    manifest_cases,
    validate_manifest,
    validate_v1_coverage,
)
from scripts.run_generic_dataset_eval import write_jsonl


DEFAULT_MANIFEST = REPO_ROOT / "configs" / "eval_gate" / "real_user_case_manifest_v1.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "eval_gate" / "real_user_variant_proposals"


@dataclass(frozen=True)
class VariantProposal:
    case_id: str
    dataset: str
    canonical_question: str
    capability_family: str
    seed: int
    requested_count: int
    accepted_variants: tuple[str, ...]
    rejected_variants: tuple[dict[str, str], ...]
    generation_model: str


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate LLM question variants for real-user manifest cases.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--count", type=int, default=10, help="Accepted variants to keep per case.")
    parser.add_argument("--case-id", action="append", help="Limit generation to one or more case ids.")
    parser.add_argument("--dataset", action="append", help="Limit generation to one or more datasets.")
    parser.add_argument("--seed", type=int, default=20260602)
    parser.add_argument("--temperature", type=float, default=0.85)
    parser.add_argument("--apply", action="store_true", help="Replace manifest question_variants with accepted LLM variants.")
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)
    client = load_llm_client_from_env()
    proposals = generate_variant_proposals(
        manifest,
        client=client,
        count=args.count,
        seed=args.seed,
        temperature=args.temperature,
        case_ids=set(args.case_id or []),
        datasets=set(args.dataset or []),
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-variants.jsonl"
    write_jsonl(output_path, [asdict(item) for item in proposals])
    if args.apply:
        apply_variant_proposals(manifest, proposals)
        validate_manifest(manifest)
        validate_v1_coverage(manifest)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "proposal_path": str(output_path),
        "case_count": len(proposals),
        "accepted_total": sum(len(item.accepted_variants) for item in proposals),
        "rejected_total": sum(len(item.rejected_variants) for item in proposals),
        "applied": args.apply,
    }
    if args.print_summary:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(summary, ensure_ascii=False))


def generate_variant_proposals(
    manifest: Mapping[str, Any],
    *,
    client: Any,
    count: int,
    seed: int,
    temperature: float,
    case_ids: set[str] | None = None,
    datasets: set[str] | None = None,
) -> list[VariantProposal]:
    selected_cases = []
    for case in manifest_cases(manifest):
        if case_ids and case.case_id not in case_ids:
            continue
        if datasets and case.dataset not in datasets:
            continue
        selected_cases.append(case)
    proposals = []
    rng = random.Random(seed)
    for case in selected_cases:
        case_seed = rng.randint(1, 2_147_483_647)
        raw = _complete_variant_json(client, _variant_messages(case, count=count, seed=case_seed), temperature=temperature)
        accepted, rejected = sanitize_generated_variants(
            raw.get("variants"),
            canonical_question=case.canonical_question,
            existing_variants=case.question_variants,
            required_count=count,
        )
        proposals.append(
            VariantProposal(
                case_id=case.case_id,
                dataset=case.dataset,
                canonical_question=case.canonical_question,
                capability_family=case.capability_family,
                seed=case_seed,
                requested_count=count,
                accepted_variants=tuple(accepted),
                rejected_variants=tuple(rejected),
                generation_model=_llm_model_name(client),
            )
        )
    return proposals


def _complete_variant_json(client: Any, messages: list[dict[str, str]], *, temperature: float) -> dict[str, Any]:
    try:
        return client.complete_json(messages, temperature=temperature)
    except ValueError as exc:
        retry_messages = [
            *messages,
            {
                "role": "user",
                "content": (
                    '上一次输出格式不合格。必须只返回一个 JSON object，顶层格式严格为 '
                    '{"variants":["问法1","问法2"]}。不要返回 JSON array、markdown、解释文字或代码块。'
                ),
            },
        ]
        try:
            return client.complete_json(retry_messages, temperature=0.2)
        except ValueError as retry_exc:
            raise ValueError(f"LLM variant response was not a JSON object after retry: {retry_exc}") from exc


def sanitize_generated_variants(
    value: Any,
    *,
    canonical_question: str,
    existing_variants: tuple[str, ...] | list[str],
    required_count: int,
) -> tuple[list[str], list[dict[str, str]]]:
    if not isinstance(value, list):
        raise ValueError("LLM response must contain variants as an array.")
    accepted: list[str] = []
    rejected: list[dict[str, str]] = []
    seen = {_normalize_variant(canonical_question)}
    seen.update(_normalize_variant(item) for item in existing_variants)
    for item in value:
        text = _clean_variant_text(item)
        reason = _variant_reject_reason(text, seen)
        if reason:
            rejected.append({"variant": text, "reason": reason})
            continue
        accepted.append(text)
        seen.add(_normalize_variant(text))
        if len(accepted) >= required_count:
            break
    if len(accepted) < required_count:
        raise ValueError(f"Only {len(accepted)} valid variants generated; required {required_count}.")
    return accepted, rejected


def apply_variant_proposals(manifest: dict[str, Any], proposals: list[VariantProposal]) -> None:
    by_case_id = {proposal.case_id: proposal for proposal in proposals}
    for case in manifest.get("cases", []):
        proposal = by_case_id.get(str(case.get("case_id") or ""))
        if proposal:
            case["question_variants"] = list(proposal.accepted_variants)
            case.setdefault("metadata", {})
            case["metadata"]["variant_generation"] = {
                "source": "llm",
                "seed": proposal.seed,
                "model": proposal.generation_model,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
            }


def _variant_messages(case: Any, *, count: int, seed: int) -> list[dict[str, str]]:
    payload = {
        "seed": seed,
        "count": count * 2,
        "dataset": case.dataset,
        "capability_family": case.capability_family,
        "canonical_question": case.canonical_question,
        "expected_contract": case.expected_contract,
        "existing_variants": list(case.question_variants),
    }
    return [
        {
            "role": "system",
            "content": (
                "你是 VDS 真实用户问法变体生成器。只生成用户可能真实输入的问题，不回答问题。"
                "不要生成标准答案、oracle、SQL、字段计算结果、task_id、raw prompt 或内部评测信息。"
                "需要覆盖口语、省略、模糊表达、字段别名、错别字、中英混合和追问式表达。"
                '只返回 JSON object，顶层必须是 {"variants": [...]}，不能返回数组或 markdown。'
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "generate_question_variants",
                    "required_output": {"variants": "array of short user question strings"},
                    "rules": [
                        "每个变体必须仍然表达 canonical_question 的同一业务意图。",
                        "不要包含答案、数字结果、SQL、oracle、expected facts、标准答案或 task_id。",
                        "不要只是替换标点；要有真实表达差异。",
                        "可以中英混合，但不能变成英文 benchmark prompt。",
                    ],
                    "payload": payload,
                },
                ensure_ascii=False,
            ),
        },
    ]


def _clean_variant_text(value: Any) -> str:
    text = str(value or "").strip()
    return " ".join(text.split())


def _variant_reject_reason(text: str, seen: set[str]) -> str:
    if not text:
        return "empty"
    if len(text) > 120:
        return "too_long"
    normalized = _normalize_variant(text)
    if normalized in seen:
        return "duplicate_or_existing"
    lowered = text.lower()
    for token in FORBIDDEN_VARIANT_TOKENS:
        if token in lowered:
            return f"forbidden_token:{token}"
    if "select " in lowered or " from " in lowered or "oracle" in lowered:
        return "internal_or_sql_marker"
    return ""


def _normalize_variant(text: str) -> str:
    return "".join(str(text or "").lower().split())


def _llm_model_name(client: Any) -> str:
    config = getattr(client, "config", None)
    provider = getattr(config, "provider", "")
    model = getattr(config, "model", "")
    if provider or model:
        return f"{provider}:{model}".strip(":")
    return client.__class__.__name__


if __name__ == "__main__":
    main()
