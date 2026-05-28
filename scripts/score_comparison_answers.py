#!/usr/bin/env python3
"""Score the two answers inside a VDS comparison artifact.

The scorer is intentionally conservative. It compares the two answers for
semantic similarity, but does not require exact wording when both answers are
useful, factual, and aligned with the requested route. If the VDS/candidate
answer appears better than the reference answer, the script flags that case for
human review instead of treating it as an automatic win.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

WEIGHTS = {
    "semantic_similarity": 0.15,
    "factuality": 0.20,
    "instruction_following": 0.18,
    "truthfulness": 0.12,
    "completeness": 0.18,
    "text_framework_alignment": 0.17,
}

REFERENCE_SOURCE_LABELS = {
    "deepseek_reference": "deepseek",
    "browser_gpt_reference": "gpt",
    "deterministic_fallback": "deterministic_smoke",
}

TEXT_FRAMEWORK_PASS_MIN = 7.0
COMPLETENESS_PASS_MIN = 6.5
ORDINARY_ACCEPTANCE_THRESHOLD = 1.0
COMPLEX_ACCEPTANCE_THRESHOLD = 0.9
ANSWERABLE_CASE_NOT_APPLICABLE_LIMIT = 0

HAN_RE = re.compile(r"[\u4e00-\u9fff]+")
TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-zA-Z][a-zA-Z0-9_%-]*|[-+]?\d[\d,]*(?:\.\d+)?%?")
NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?%?")
PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)

STOP_TOKENS = {
    "的",
    "了",
    "和",
    "或",
    "及",
    "与",
    "在",
    "是",
    "为",
    "把",
    "先",
    "后",
    "可以",
    "需要",
    "这个",
    "这些",
    "一个",
    "当前",
    "数据",
    "字段",
    "分析",
    "the",
    "and",
    "or",
    "to",
    "of",
    "in",
    "for",
    "a",
    "an",
}

NO_FILE_BOUNDARY_TERMS = (
    "没有上传",
    "没有数据",
    "当前没有",
    "上传文件后",
    "上传数据后",
    "先上传",
    "不能给出具体数据结论",
    "不会编造",
)

DATASET_TERMS = (
    "已读取",
    "这个表",
    "这组数据",
    "数据集",
    "行",
    "列",
    "字段",
    "缺失",
    "异常",
    "质量",
    "分布",
    "趋势",
)

SAFETY_MARKERS = (
    "raw prompt",
    "reasoning_trace",
    "trace.json",
    "scorer",
    "standard_answer",
    "标准答案",
    "后端审计",
)


@dataclass(frozen=True)
class AnswerScore:
    total_score: float
    dimensions: dict[str, float]
    issues: list[str]
    notes: list[str]
    acceptable: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "total_score": round(self.total_score, 2),
            "dimensions": {key: round(value, 2) for key, value in self.dimensions.items()},
            "acceptable": self.acceptable,
            "issues": self.issues,
            "notes": self.notes,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Score standard and VDS answers in comparison.json/jsonl/md.")
    parser.add_argument(
        "comparison",
        nargs="?",
        help="Path to comparison.json, comparison.jsonl, comparison.md, or a directory containing one. Defaults to the latest outputs/eval_gate comparison.",
    )
    parser.add_argument("--output-dir", help="Defaults to the comparison file directory.")
    parser.add_argument("--print-summary", action="store_true", help="Print a compact JSON summary.")
    parser.add_argument("--min-acceptable", type=float, default=75.0, help="Total score threshold for an acceptable answer.")
    parser.add_argument(
        "--judge",
        choices=("llm", "heuristic", "auto"),
        default="llm",
        help="Use an LLM judge, deterministic heuristic scorer, or LLM with heuristic fallback. Default: llm.",
    )
    args = parser.parse_args()

    comparison_path = resolve_comparison_path(Path(args.comparison)) if args.comparison else latest_comparison_path()
    output_dir = Path(args.output_dir) if args.output_dir else comparison_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = load_comparison_rows(comparison_path)
    actual_judge, scored_rows = score_rows(rows, judge=args.judge, min_acceptable=args.min_acceptable)
    result = {
        "source": str(comparison_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "judge_mode": actual_judge,
        "weights": WEIGHTS,
        "min_acceptable": args.min_acceptable,
        "summary": summarize(scored_rows),
        "rows": scored_rows,
    }

    write_json(output_dir / "comparison_scored.json", result)
    write_jsonl(output_dir / "comparison_scored.jsonl", scored_rows)
    (output_dir / "comparison_scored.md").write_text(score_markdown(result), encoding="utf-8")

    if args.print_summary:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"output_dir": str(output_dir), "rows": len(scored_rows)}, ensure_ascii=False))


def score_rows(rows: list[dict[str, Any]], *, judge: str, min_acceptable: float) -> tuple[str, list[dict[str, Any]]]:
    if judge == "heuristic":
        return "heuristic", [score_row(row, min_acceptable=min_acceptable) for row in rows]

    try:
        llm_client = load_llm_judge_client()
    except RuntimeError as exc:
        if judge == "auto":
            return "heuristic_fallback_no_llm", [score_row(row, min_acceptable=min_acceptable) for row in rows]
        raise SystemExit(str(exc)) from exc

    return "llm", [score_row_with_llm(row, llm_client, min_acceptable=min_acceptable) for row in rows]


def load_llm_judge_client() -> Any:
    from data_agent_core.llm.client import MissingLLMConfigError, load_llm_client_from_env

    try:
        client = load_llm_client_from_env()
    except MissingLLMConfigError as exc:
        raise RuntimeError(
            "LLM judge requires VDS_LLM_PROVIDER=openai or deepseek plus the matching API key. "
            "Use --judge heuristic only for local smoke scoring."
        ) from exc
    if client.__class__.__name__ == "MockLLMClient":
        raise RuntimeError("VDS_LLM_PROVIDER=mock is not valid for LLM judging. Use openai or deepseek.")
    return client


def resolve_comparison_path(path: Path) -> Path:
    if path.is_dir():
        for name in ("comparison.json", "comparison.jsonl", "comparison.md"):
            candidate = path / name
            if candidate.exists():
                return candidate
        raise SystemExit(f"No comparison.json/jsonl/md found in {path}")
    if not path.exists():
        raise SystemExit(f"Comparison file not found: {path}")
    return path


def latest_comparison_path() -> Path:
    root = Path("outputs") / "eval_gate"
    candidates: list[Path] = []
    for name in ("comparison.json", "comparison.jsonl", "comparison.md"):
        candidates.extend(root.glob(f"**/{name}"))
    candidates = [path for path in candidates if "comparison_scored" not in path.name]
    if not candidates:
        raise SystemExit("No comparison files found under outputs/eval_gate. Pass a comparison path explicitly.")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_comparison_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    elif suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("comparison", data.get("rows", data)) if isinstance(data, dict) else data
    elif suffix in {".md", ".markdown"}:
        rows = parse_comparison_markdown(path.read_text(encoding="utf-8"))
    else:
        raise SystemExit(f"Unsupported comparison file type: {path}")
    if not isinstance(rows, list):
        raise SystemExit(f"Comparison file must contain a list of rows: {path}")
    normalized = [normalize_row(row, index) for index, row in enumerate(rows, start=1)]
    if not normalized:
        raise SystemExit(f"Comparison file has no rows: {path}")
    return normalized


def normalize_row(row: dict[str, Any], index: int) -> dict[str, Any]:
    standard = row.get("source_answer") or row.get("standard_answer") or row.get("reference_answer") or row.get("answer_a") or ""
    candidate = row.get("candidate_answer") or row.get("vds_answer") or row.get("answer_b") or row.get("actual_answer") or ""
    source_origin = row.get("source_answer_origin") or row.get("standard_answer_source")
    reference_label = row.get("reference_answer_label") or row.get("standard_answer_label") or reference_answer_label(source_origin)
    return {
        "case_id": str(row.get("case_id") or f"row_{index:03d}"),
        "ae_group": str(row.get("ae_group") or ""),
        "category": str(row.get("category") or ""),
        "difficulty_bucket": str(row.get("difficulty_bucket") or infer_difficulty_bucket(row)),
        "capability_family": str(row.get("capability_family") or infer_capability_family(row)),
        "answerability": str(row.get("answerability") or "answerable"),
        "standard_answer_source": str(source_origin or "unknown"),
        "reference_answer_label": str(reference_label or "reference"),
        "standard_answer_model": str(row.get("standard_answer_model") or ""),
        "question": str(row.get("question") or ""),
        "expected_route": str(row.get("expected_route") or row.get("route") or ""),
        "standard_answer": str(standard),
        "candidate_answer": str(candidate),
        "comparison_status": str(row.get("comparison_status") or ""),
        "unexpected_not_applicable": bool(row.get("unexpected_not_applicable") or contains_unexpected_not_applicable(str(candidate))),
        "failure_reasons": list(row.get("failure_reasons") or []),
        "missing_terms": list(row.get("missing_terms") or []),
        "number_checks": list(row.get("number_checks") or []),
        "gpt_like_checks": list(row.get("gpt_like_checks") or []),
    }


def reference_answer_label(source: Any) -> str:
    normalized = str(source or "").strip().lower()
    if normalized.startswith("mixed_deepseek_reference"):
        return "deepseek"
    if normalized.startswith("mixed_browser_gpt_reference"):
        return "gpt"
    return REFERENCE_SOURCE_LABELS.get(normalized, normalized or "reference")


def dominant_reference_label(rows: list[dict[str, Any]]) -> str:
    labels = [str(row.get("reference_answer_label") or reference_answer_label(row.get("standard_answer_source")) or "reference") for row in rows]
    unique = {label for label in labels if label}
    if len(unique) == 1:
        return labels[0]
    return "gpt/deepseek"


def reference_heading(label: str) -> str:
    return f"**{label or 'reference'} 回答**"


def infer_difficulty_bucket(row: dict[str, Any]) -> str:
    category = str(row.get("category") or "")
    case_id = str(row.get("case_id") or "")
    if case_id in {"generic_quality_004", "generic_business_002", "generic_business_003", "generic_route_003", "generic_cleaning_001", "generic_cleaning_004"}:
        return "complex"
    if category in {"adaptive_business", "general_to_analysis_routing", "cleaning_strategy"}:
        return "complex"
    return "ordinary"


def infer_capability_family(row: dict[str, Any]) -> str:
    category = str(row.get("category") or "")
    case_id = str(row.get("case_id") or "")
    if "business_003" in case_id:
        return "join"
    if "business_002" in case_id:
        return "trend"
    if "route" in case_id:
        return "broad_question_routing"
    mapping = {
        "general_no_file": "safety_boundary",
        "general_uploaded": "overview",
        "ambiguous_user_questions": "broad_question_routing",
        "basic_data_understanding": "field_mapping",
        "quality_and_anomaly": "quality",
        "analysis_readiness": "field_mapping",
        "adaptive_business": "single_table_aggregation",
        "general_to_analysis_routing": "broad_question_routing",
        "technical_review_guardrails": "safety_boundary",
        "cleaning_strategy": "quality",
    }
    return mapping.get(category, "unknown")


def contains_unexpected_not_applicable(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    return "not applicable" in lowered or bool(re.search(r"(^|[^a-z0-9])n/a([^a-z0-9]|$)", lowered)) or lowered == "na"


def parse_comparison_markdown(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    parts = re.split(r"\n###\s+", "\n" + text)
    current_group = ""
    for part in parts:
        if not part.strip():
            continue
        reference_marker, reference_label = _reference_answer_marker(part)
        has_answer_pair = bool(reference_marker) and "**VDS 实际回复**" in part
        group_match = re.search(r"^##\s+(.+)$", part, re.M)
        if group_match and not has_answer_pair:
            current_group = group_match.group(1).strip()
        if not has_answer_pair:
            continue
        header, body = part.split("\n", 1)
        case_match = re.match(r"(?P<case_id>\S+)\s+-\s+(?P<category>.+)", header.strip())
        question = _first_markdown_value(body, "Question")
        expected_route = _first_markdown_value(body, "Expected route")
        difficulty_bucket = _first_markdown_value(body, "Difficulty bucket")
        capability_family = _first_markdown_value(body, "Capability family")
        answerability = _first_markdown_value(body, "Answerability")
        standard_source = _first_markdown_value(body, "Answer source") or _first_markdown_value(body, "Standard source")
        standard_model = _first_markdown_value(body, "Answer model") or _first_markdown_value(body, "Standard model")
        answer_label = _first_markdown_value(body, "Answer label") or reference_label or reference_answer_label(standard_source)
        status = _first_markdown_value(body, "Comparison status")
        standard = _between(body, reference_marker, "**VDS 实际回复**")
        candidate = _between_any(body, "**VDS 实际回复**", ["**对比细节**", "\n## "])
        rows.append(
            {
                "case_id": case_match.group("case_id") if case_match else f"md_row_{len(rows) + 1:03d}",
                "category": case_match.group("category").strip() if case_match else "",
                "ae_group": current_group,
                "question": question,
                "expected_route": expected_route,
                "difficulty_bucket": difficulty_bucket,
                "capability_family": capability_family,
                "answerability": answerability,
                "standard_answer_source": standard_source,
                "reference_answer_label": answer_label,
                "standard_answer_model": standard_model,
                "comparison_status": status,
                "standard_answer": standard,
                "candidate_answer": candidate,
            }
        )
    return rows


def _reference_answer_marker(text: str) -> tuple[str, str]:
    for label in ("gpt", "deepseek", "deterministic_smoke", "deterministic smoke", "reference"):
        marker = f"**{label} 回答**"
        if marker in text:
            return marker, label.replace(" ", "_")
    old_marker = "**我的标准回复**"
    if old_marker in text:
        return old_marker, "reference"
    return "", ""


def _first_markdown_value(text: str, label: str) -> str:
    match = re.search(rf"^- {re.escape(label)}:\s*(.*)$", text, re.M)
    return match.group(1).strip() if match else ""


def _between(text: str, start: str, end: str) -> str:
    return _between_any(text, start, [end])


def _between_any(text: str, start: str, ends: list[str]) -> str:
    if start not in text:
        return ""
    value = text.split(start, 1)[1]
    end_positions = [value.find(end) for end in ends if value.find(end) >= 0]
    if end_positions:
        value = value[: min(end_positions)]
    return value.strip()


def score_row(row: dict[str, Any], *, min_acceptable: float) -> dict[str, Any]:
    standard = row["standard_answer"]
    candidate = row["candidate_answer"]
    raw_pair_similarity = semantic_similarity(standard, candidate)
    route_pair_floor = min(
        route_coverage_score(standard, row.get("question", ""), row.get("expected_route", "")),
        route_coverage_score(candidate, row.get("question", ""), row.get("expected_route", "")),
    ) * 6.5
    pair_similarity = max(raw_pair_similarity, route_pair_floor)
    expected_numbers = expected_numbers_from_row(row)

    standard_score = score_answer(
        answer=standard,
        other_answer=candidate,
        row=row,
        pair_similarity=pair_similarity,
        expected_numbers=expected_numbers,
        role="standard",
        min_acceptable=min_acceptable,
    )
    candidate_score = score_answer(
        answer=candidate,
        other_answer=standard,
        row=row,
        pair_similarity=pair_similarity,
        expected_numbers=expected_numbers,
        role="candidate",
        min_acceptable=min_acceptable,
    )
    verdict = pair_verdict(standard_score, candidate_score)
    return {
        "case_id": row["case_id"],
        "ae_group": row.get("ae_group", ""),
        "category": row.get("category", ""),
        "difficulty_bucket": row.get("difficulty_bucket", "ordinary"),
        "capability_family": row.get("capability_family", "unknown"),
        "answerability": row.get("answerability", "answerable"),
        "standard_answer_source": row.get("standard_answer_source", "unknown"),
        "reference_answer_label": row.get("reference_answer_label") or reference_answer_label(row.get("standard_answer_source")),
        "standard_answer_model": row.get("standard_answer_model", ""),
        "question": row.get("question", ""),
        "expected_route": row.get("expected_route", ""),
        "comparison_status": row.get("comparison_status", ""),
        "unexpected_not_applicable": contains_unexpected_not_applicable(candidate),
        "failure_reasons": list(row.get("failure_reasons") or []),
        "source_answers": {
            "reference_answer_label": row.get("reference_answer_label") or reference_answer_label(row.get("standard_answer_source")),
            "standard_answer": standard,
            "candidate_answer": candidate,
        },
        "pair_similarity": round(pair_similarity, 2),
        "raw_pair_similarity": round(raw_pair_similarity, 2),
        "answers": {
            "standard": standard_score.to_json(),
            "candidate": candidate_score.to_json(),
        },
        "verdict": verdict,
        "judge_mode": "heuristic",
    }


def score_row_with_llm(row: dict[str, Any], llm_client: Any, *, min_acceptable: float) -> dict[str, Any]:
    response = llm_client.complete_json(llm_judge_messages(row), temperature=0.0)
    pair_similarity = clamp10(float(response.get("pair_similarity", 0.0)))
    expected_route = str(row.get("expected_route", ""))
    standard_score = llm_answer_score(response.get("reference", response.get("standard", {})), min_acceptable=min_acceptable, expected_route=expected_route)
    candidate_score = llm_answer_score(response.get("candidate", {}), min_acceptable=min_acceptable, expected_route=expected_route)
    standard_score = force_not_applicable_failure_if_needed(standard_score, row["standard_answer"])
    candidate_score = force_not_applicable_failure_if_needed(candidate_score, row["candidate_answer"])
    verdict = pair_verdict(standard_score, candidate_score)
    llm_verdict = response.get("verdict", {})
    if isinstance(llm_verdict, dict):
        reason = str(llm_verdict.get("reason") or "").strip()
        if reason:
            verdict["llm_reason"] = reason
    return {
        "case_id": row["case_id"],
        "ae_group": row.get("ae_group", ""),
        "category": row.get("category", ""),
        "difficulty_bucket": row.get("difficulty_bucket", "ordinary"),
        "capability_family": row.get("capability_family", "unknown"),
        "answerability": row.get("answerability", "answerable"),
        "standard_answer_source": row.get("standard_answer_source", "unknown"),
        "reference_answer_label": row.get("reference_answer_label") or reference_answer_label(row.get("standard_answer_source")),
        "standard_answer_model": row.get("standard_answer_model", ""),
        "question": row.get("question", ""),
        "expected_route": row.get("expected_route", ""),
        "comparison_status": row.get("comparison_status", ""),
        "unexpected_not_applicable": contains_unexpected_not_applicable(row["candidate_answer"]),
        "failure_reasons": list(row.get("failure_reasons") or []),
        "source_answers": {
            "reference_answer_label": row.get("reference_answer_label") or reference_answer_label(row.get("standard_answer_source")),
            "standard_answer": row["standard_answer"],
            "candidate_answer": row["candidate_answer"],
        },
        "pair_similarity": round(pair_similarity, 2),
        "answers": {
            "standard": standard_score.to_json(),
            "candidate": candidate_score.to_json(),
        },
        "verdict": verdict,
        "judge_mode": "llm",
    }


def llm_answer_score(payload: Any, *, min_acceptable: float, expected_route: str = "") -> AnswerScore:
    if not isinstance(payload, dict):
        payload = {}
    dimensions = {
        key: score_value(payload.get(key, 0.0))
        for key in WEIGHTS
    }
    total = calibrated_total(dimensions, expected_route=expected_route)
    issues = [str(item) for item in payload.get("issues", []) if str(item).strip()] if isinstance(payload.get("issues"), list) else []
    notes = [str(item) for item in payload.get("notes", []) if str(item).strip()] if isinstance(payload.get("notes"), list) else []
    acceptable = (
        total >= min_acceptable
        and dimensions["factuality"] >= 6.5
        and dimensions["instruction_following"] >= 6.0
        and dimensions["truthfulness"] >= 7.0
        and (
            not requires_text_framework(expected_route)
            or (
                dimensions["text_framework_alignment"] >= TEXT_FRAMEWORK_PASS_MIN
                and dimensions["completeness"] >= COMPLETENESS_PASS_MIN
            )
        )
    )
    return AnswerScore(total_score=total, dimensions=dimensions, issues=issues, notes=notes, acceptable=acceptable)


def force_not_applicable_failure_if_needed(score: AnswerScore, answer: str) -> AnswerScore:
    if not contains_unexpected_not_applicable(answer):
        return score
    dimensions = dict(score.dimensions)
    dimensions["factuality"] = min(dimensions.get("factuality", 0.0), 2.0)
    dimensions["instruction_following"] = min(dimensions.get("instruction_following", 0.0), 2.0)
    dimensions["completeness"] = min(dimensions.get("completeness", 0.0), 1.0)
    dimensions["text_framework_alignment"] = min(dimensions.get("text_framework_alignment", 0.0), 1.0)
    issues = sorted(set(score.issues + ["unexpected_not_applicable"]))
    notes = list(score.notes)
    if "forced_failure_unexpected_not_applicable" not in notes:
        notes.append("forced_failure_unexpected_not_applicable")
    return AnswerScore(total_score=min(score.total_score, 25.0), dimensions=dimensions, issues=issues, notes=notes, acceptable=False)


def score_value(value: Any) -> float:
    try:
        return clamp10(float(value))
    except (TypeError, ValueError):
        return 0.0


def llm_judge_messages(row: dict[str, Any]) -> list[dict[str, str]]:
    source_label = row.get("reference_answer_label") or reference_answer_label(row.get("standard_answer_source"))
    payload = {
        "case_id": row.get("case_id", ""),
        "question": row.get("question", ""),
        "expected_route": row.get("expected_route", ""),
        "category": row.get("category", ""),
        "difficulty_bucket": row.get("difficulty_bucket", "ordinary"),
        "capability_family": row.get("capability_family", "unknown"),
        "answerability": row.get("answerability", "answerable"),
        "source_answer_label": source_label,
        "source_answer_origin": row.get("standard_answer_source", "unknown"),
        "source_answer_model": row.get("standard_answer_model", ""),
        "comparison_status_from_exact_checker": row.get("comparison_status", ""),
        "missing_terms_from_exact_checker": row.get("missing_terms", []),
        "number_checks_from_exact_checker": row.get("number_checks", []),
        "source_answer": truncate_for_llm(row.get("standard_answer", "")),
        "candidate_answer": truncate_for_llm(row.get("candidate_answer", "")),
    }
    system = (
        "你是 VDS 回答质量的严格 LLM judge。你需要分别评价 source_answer 和 candidate_answer，"
        "source_answer_label 会标明它来自 gpt 网页端人工导入或 deepseek API；candidate_answer 是 VDS 实际回复。"
        "不要把 deepseek 冒充 GPT API；但要以网页端 ChatGPT Data Analysis 的质量为标尺。"
        "如果两个回答事实正确、跟随问题、安全边界清楚，表达不同可以接受；"
        "但数据类回答如果只是短句、字段清单、泛泛建议、没有结论/依据/口径/下一步，不能因为没有事实错误就给高分。"
        "如果 candidate_answer 看起来比 source_answer 更好，可以给更高维度分；但不要自行放行，脚本会要求人工复核。"
        "当前 VDS 还没达到 GPT 水平，所以 candidate 优于 reference 的判断要保守。"
        "只返回 JSON，不要返回 Markdown。"
    )
    user = (
        "按以下 6 个维度给 0-10 分：\n"
        "- semantic_similarity: 两个回答在核心语义和结论上的相似度。不同措辞可接受。\n"
        "- factuality: 是否包含可由题目/上下文支持的事实、数字和口径；明显乱报数字要低分。\n"
        "- instruction_following: 是否回答了原问题，并符合 expected_route。\n"
        "- truthfulness: 是否避免编造、过度确定、泄露 raw prompt/trace/scorer/源答案等内部物。\n"
        "- completeness: 对用户复核是否足够完整；缺少关键结论、证据、边界或下一步要低分，不要奖励无关长篇。\n\n"
        "- text_framework_alignment: 对数据类回答，是否有网页端 GPT-like 文字层级：核心结论、简要结论、口径说明、下一步。"
        "没有这些模块时最高 4.5；只有零散字段/数值时最高 5.5；接近 GPT 网页端组织方式才给 8+。\n\n"
        "返回格式必须是：\n"
        "{\n"
        '  "pair_similarity": 0-10,\n'
        '  "reference": {"semantic_similarity": 0-10, "factuality": 0-10, "instruction_following": 0-10, "truthfulness": 0-10, "completeness": 0-10, "text_framework_alignment": 0-10, "issues": [], "notes": []},\n'
        '  "candidate": {"semantic_similarity": 0-10, "factuality": 0-10, "instruction_following": 0-10, "truthfulness": 0-10, "completeness": 0-10, "text_framework_alignment": 0-10, "issues": [], "notes": []},\n'
        '  "verdict": {"reason": "一句中文理由"}\n'
        "}\n\n"
        "待评估内容：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def truncate_for_llm(text: str, limit: int = 8000) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "\n...[truncated]"


def score_answer(
    *,
    answer: str,
    other_answer: str,
    row: dict[str, Any],
    pair_similarity: float,
    expected_numbers: list[dict[str, float]],
    role: str,
    min_acceptable: float,
) -> AnswerScore:
    text = answer.strip()
    question = row.get("question", "")
    expected_route = row.get("expected_route", "")
    dimensions = {
        "semantic_similarity": pair_similarity,
        "factuality": factuality_score(text, other_answer, row, expected_numbers, role=role),
        "instruction_following": instruction_following_score(text, question, expected_route),
        "truthfulness": truthfulness_score(text, question, expected_route),
        "completeness": completeness_score(text, other_answer, question, expected_route),
        "text_framework_alignment": text_framework_alignment_score(text, expected_route),
    }
    if contains_unexpected_not_applicable(text):
        dimensions["factuality"] = min(dimensions["factuality"], 2.0)
        dimensions["instruction_following"] = min(dimensions["instruction_following"], 2.0)
        dimensions["completeness"] = min(dimensions["completeness"], 1.0)
        dimensions["text_framework_alignment"] = min(dimensions["text_framework_alignment"], 1.0)
    issues = answer_issues(text, question, expected_route, dimensions)
    notes = answer_notes(role, text, other_answer, row, dimensions)
    total = calibrated_total(dimensions, expected_route=expected_route)
    acceptable = (
        total >= min_acceptable
        and dimensions["factuality"] >= 6.5
        and dimensions["instruction_following"] >= 6.0
        and dimensions["truthfulness"] >= 7.0
        and (
            not requires_text_framework(expected_route)
            or (
                dimensions["text_framework_alignment"] >= TEXT_FRAMEWORK_PASS_MIN
                and dimensions["completeness"] >= COMPLETENESS_PASS_MIN
            )
        )
    )
    return AnswerScore(total_score=total, dimensions=dimensions, issues=issues, notes=notes, acceptable=acceptable)


def semantic_similarity(left: str, right: str) -> float:
    if not left.strip() or not right.strip():
        return 0.0
    left_tokens = content_tokens(left)
    right_tokens = content_tokens(right)
    token_f1 = f1_score(left_tokens, right_tokens)
    char_jaccard = jaccard(char_ngrams(left), char_ngrams(right))
    number_score = number_similarity(extract_numbers(left), extract_numbers(right))
    concept_f1 = f1_score(semantic_concepts(left), semantic_concepts(right))
    lexical_score = 0.68 * token_f1 + 0.32 * char_jaccard
    blended = 0.46 * lexical_score + 0.42 * concept_f1 + 0.12 * number_score
    if concept_f1 >= 0.65 and number_score >= 0.5:
        blended = max(blended, 0.68)
    elif concept_f1 >= 0.65:
        blended = max(blended, 0.58)
    return clamp10(10.0 * blended)


def factuality_score(
    text: str,
    reference: str,
    row: dict[str, Any],
    expected_numbers: list[dict[str, float]],
    *,
    role: str,
) -> float:
    if not text.strip():
        return 0.0
    if expected_numbers:
        checks = [contains_expected_number(text, item["value"], item["tolerance"]) for item in expected_numbers]
        passed_rate = sum(1 for item in checks if item) / len(checks)
        base = 4.0 + 6.0 * passed_rate
    else:
        reference_numbers = extract_numbers(reference)
        answer_numbers = extract_numbers(text)
        if reference_numbers and not answer_numbers:
            base = 7.0
        elif answer_numbers and reference_numbers:
            base = 7.0 + 3.0 * number_similarity(answer_numbers, reference_numbers)
        else:
            base = 8.2

    if row.get("comparison_status") == "passed":
        base = max(base, 8.0)
    if role == "candidate" and row.get("comparison_status") == "failed" and row.get("missing_terms"):
        base -= min(1.5, 0.35 * len(row.get("missing_terms") or []))
    if looks_like_raw_detail_dump(text):
        base -= 2.0
    if route_is_no_file(row.get("expected_route", "")) and has_concrete_dataset_claim(text) and not has_no_file_boundary(text):
        base -= 3.0
    return clamp10(base)


def instruction_following_score(text: str, question: str, expected_route: str) -> float:
    if not text.strip():
        return 0.0
    score = 7.0
    lowered_question = question.lower()
    if route_is_no_file(expected_route):
        score += 2.0 if has_no_file_boundary(text) or "上传" in text else -2.0
        if has_concrete_dataset_claim(text) and not has_no_file_boundary(text):
            score -= 3.0
        if "多文件" in question and "多文件" not in text and "join" not in text.lower() and "对比" not in text:
            score -= 2.0
    elif expected_route == "cleaning_simulation":
        score += 2.0 if any(term in text for term in ("模拟", "影响", "规则", "用户确认", "不能覆盖原始")) else -2.0
        if any(term in text for term in ("直接删除", "直接覆盖", "已修改原始")):
            score -= 4.0
    elif expected_route == "dataset_overview":
        score += 1.5 if any(term in text for term in DATASET_TERMS) else -1.5
        if "没有上传" in text or "还没有上传" in text:
            score -= 3.0
        if any(term in lowered_question for term in ("raw prompt", "trace", "sql", "标准答案")):
            score += 1.0 if guardrail_denial(text) else -3.0
    else:
        score += 0.5 if len(text) >= 20 else -1.0

    if question and question_keyword_coverage(text, question) < 0.12 and len(text) < 80:
        score -= 1.0
    if len(text) > 3500:
        score -= 1.0
    return clamp10(score)


def truthfulness_score(text: str, question: str, expected_route: str) -> float:
    if not text.strip():
        return 0.0
    score = 8.5
    if contains_internal_marker(text) and not guardrail_context(question, text):
        score -= 2.5
    if looks_like_raw_detail_dump(text):
        score -= 2.0
    if route_is_no_file(expected_route) and has_concrete_dataset_claim(text) and not has_no_file_boundary(text):
        score -= 3.5
    if expected_route in {"dataset_overview", "analysis", "cleaning_simulation"} and ("没有上传" in text or "还没有上传" in text):
        score -= 2.0
    if any(term in text for term in ("肯定", "一定", "绝对")) and not any(term in text for term in ("不确定", "推测", "需要确认")):
        score -= 0.8
    if "直接修改原始" in text or "已覆盖原始" in text:
        score -= 3.0
    if any(term in question for term in ("字段含义", "真实名称", "不确定")):
        score += 1.0 if any(term in text for term in ("不确定", "推测", "不能", "需要")) else -1.0
    return clamp10(score)


def completeness_score(text: str, reference: str, question: str, expected_route: str) -> float:
    if not text.strip():
        return 0.0
    ref_tokens = content_tokens(reference)
    answer_tokens = content_tokens(text)
    coverage = recall_score(ref_tokens, answer_tokens)
    question_cov = question_keyword_coverage(text, question)
    route_cov = route_coverage_score(text, question, expected_route)
    length_score = min(1.0, len(text) / 180.0)
    if len(text) > 3200:
        length_score -= 0.15
    score = 10.0 * (0.15 * coverage + 0.20 * question_cov + 0.45 * route_cov + 0.20 * max(0.0, length_score))
    return clamp10(score)


def text_framework_alignment_score(text: str, expected_route: str) -> float:
    if not text.strip():
        return 0.0
    if not requires_text_framework(expected_route):
        return 8.0 if len(text) >= 20 else 5.0

    score = 0.0
    if any(term in text for term in ("核心结论是", "核心结论", "直接结论", "结论是")):
        score += 2.0
    if "简要结论" in text:
        score += 2.0
    if "口径说明" in text or ("口径" in text and any(term in text for term in ("数据范围", "指标口径", "筛选条件"))):
        score += 2.0
    if any(term in text for term in ("下一步", "继续看", "继续问", "如果你愿意")):
        score += 1.5
    if re.search(r"(?m)^-\s+", text) or re.search(r"(?m)^\d+[.、]\s*", text):
        score += 1.0
    if any(term in text for term in ("数据范围", "指标口径", "注意事项", "筛选条件", "聚合", "排序", "目标", "实际")):
        score += 1.0
    if expected_route == "cleaning_simulation" and any(term in text for term in ("不会直接修改原始数据", "用户确认", "需要确认")):
        score += 0.5
    return clamp10(score)


def requires_text_framework(expected_route: str) -> bool:
    route = str(expected_route or "").lower()
    if route_is_no_file(route) or route.startswith("chat"):
        return False
    return route in {"dataset_overview", "analysis", "cleaning_simulation"} or any(
        token in route for token in ("overview", "analysis", "cleaning", "dataset")
    )


def answer_issues(text: str, question: str, expected_route: str, dimensions: dict[str, float]) -> list[str]:
    issues: list[str] = []
    if not text.strip():
        issues.append("empty_answer")
    if contains_unexpected_not_applicable(text):
        issues.append("unexpected_not_applicable")
    if dimensions["semantic_similarity"] < 4.0:
        issues.append("low_similarity_to_other_answer")
    if dimensions["factuality"] < 6.5:
        issues.append("fact_alignment_risk")
    if dimensions["instruction_following"] < 6.0:
        issues.append("instruction_following_risk")
    if dimensions["truthfulness"] < 7.0:
        issues.append("truthfulness_or_safety_risk")
    if looks_like_raw_detail_dump(text):
        issues.append("raw_detail_dump_risk")
    if contains_internal_marker(text) and not guardrail_context(question, text):
        issues.append("internal_artifact_marker")
    if route_is_no_file(expected_route) and has_concrete_dataset_claim(text) and not has_no_file_boundary(text):
        issues.append("no_file_route_has_dataset_claim")
    if requires_text_framework(expected_route) and dimensions.get("text_framework_alignment", 0.0) < TEXT_FRAMEWORK_PASS_MIN:
        issues.append("text_framework_alignment_risk")
    if requires_text_framework(expected_route) and dimensions.get("completeness", 0.0) < COMPLETENESS_PASS_MIN:
        issues.append("incomplete_gpt_like_answer")
    return sorted(set(issues))


def answer_notes(role: str, text: str, other_answer: str, row: dict[str, Any], dimensions: dict[str, float]) -> list[str]:
    notes: list[str] = []
    if dimensions["semantic_similarity"] < 6.0 and min(dimensions["factuality"], dimensions["instruction_following"], dimensions["truthfulness"]) >= 7.5:
        notes.append("wording_differs_but_core_quality_is_good")
    if role == "candidate" and dimensions["completeness"] > 8.0 and len(text) > len(other_answer) * 1.4:
        notes.append("candidate_adds_more_context_than_reference")
    if row.get("comparison_status") == "failed" and dimensions["instruction_following"] >= 8.0 and dimensions["truthfulness"] >= 8.0:
        notes.append("exact_comparison_failed_but_rubric_score_is_stronger")
    return notes


def pair_verdict(standard: AnswerScore, candidate: AnswerScore) -> dict[str, Any]:
    diff = candidate.total_score - standard.total_score
    if diff > 5:
        label = "candidate_higher_needs_human_review"
    elif diff < -5:
        label = "standard_higher"
    elif standard.total_score < 70 and candidate.total_score < 70:
        label = "both_need_work"
    elif standard.acceptable and candidate.acceptable:
        label = "both_acceptable_similarity_or_quality"
    else:
        label = "close_call"
    return {
        "label": label,
        "score_delta_candidate_minus_standard": round(diff, 2),
        "needs_human_review": label in {"candidate_higher_needs_human_review", "close_call"},
        "reason": verdict_reason(label),
    }


def verdict_reason(label: str) -> str:
    reasons = {
        "both_need_work": "两个回答都低于可接受线，不能靠相似度放行。",
        "both_acceptable_similarity_or_quality": "两个回答都达到基本质量线；表述不同也可接受。",
        "close_call": "两边分差小，但至少一个回答没有稳定过可接受线，需要人工看一眼。",
        "candidate_higher_needs_human_review": "VDS 回复分数更高；按当前阶段保守处理，需要人工确认不是过度乐观。",
        "standard_higher": "gpt/deepseek 源回答明显更稳，VDS 回复需要修正或补充。",
    }
    return reasons[label]


def display_verdict_label(label: str) -> str:
    if label == "standard_higher":
        return "source_higher"
    return label


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_label = dominant_reference_label(rows)
    standard_totals = [row["answers"]["standard"]["total_score"] for row in rows]
    candidate_totals = [row["answers"]["candidate"]["total_score"] for row in rows]
    verdict_counts: dict[str, int] = {}
    for row in rows:
        label = row["verdict"]["label"]
        verdict_counts[label] = verdict_counts.get(label, 0) + 1
    bucket_summary = acceptance_bucket_summary(rows)
    unexpected_not_applicable_count = sum(
        1
        for row in rows
        if row.get("unexpected_not_applicable") and row.get("answerability") != "true_unsupported"
    )
    return {
        "case_count": len(rows),
        "source_answer_label": source_label,
        "source_average_total": round(statistics.mean(standard_totals), 2),
        "standard_average_total": round(statistics.mean(standard_totals), 2),
        "candidate_average_total": round(statistics.mean(candidate_totals), 2),
        "source_acceptable_count": sum(1 for row in rows if row["answers"]["standard"]["acceptable"]),
        "standard_acceptable_count": sum(1 for row in rows if row["answers"]["standard"]["acceptable"]),
        "candidate_acceptable_count": sum(1 for row in rows if row["answers"]["candidate"]["acceptable"]),
        "candidate_acceptance_rate": round(
            sum(1 for row in rows if row["answers"]["candidate"]["acceptable"]) / len(rows),
            4,
        ),
        "unexpected_not_applicable_count": unexpected_not_applicable_count,
        "acceptance_policy": {
            "ordinary_required_pass_rate": ORDINARY_ACCEPTANCE_THRESHOLD,
            "complex_required_pass_rate": COMPLEX_ACCEPTANCE_THRESHOLD,
            "unexpected_not_applicable_required": ANSWERABLE_CASE_NOT_APPLICABLE_LIMIT,
        },
        "acceptance_buckets": bucket_summary,
        "acceptance_passed": (
            unexpected_not_applicable_count == ANSWERABLE_CASE_NOT_APPLICABLE_LIMIT
            and all(item["gate_passed"] for item in bucket_summary.values())
        ),
        "capability_failures": score_capability_failures(rows),
        "average_pair_similarity": round(statistics.mean(row["pair_similarity"] for row in rows), 2),
        "verdict_counts": verdict_counts,
        "needs_human_review_count": sum(1 for row in rows if row["verdict"]["needs_human_review"]),
        "dimension_averages": {
            "source": average_dimensions(rows, "standard"),
            "standard": average_dimensions(rows, "standard"),
            "candidate": average_dimensions(rows, "candidate"),
        },
    }


def acceptance_bucket_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for bucket in ("ordinary", "complex"):
        bucket_rows = [
            row
            for row in rows
            if row.get("difficulty_bucket", "ordinary") == bucket and row.get("answerability") != "true_unsupported"
        ]
        threshold = COMPLEX_ACCEPTANCE_THRESHOLD if bucket == "complex" else ORDINARY_ACCEPTANCE_THRESHOLD
        accepted = sum(1 for row in bucket_rows if row["answers"]["candidate"]["acceptable"])
        unexpected_na = sum(1 for row in bucket_rows if row.get("unexpected_not_applicable"))
        pass_rate = accepted / len(bucket_rows) if bucket_rows else 1.0
        summary[bucket] = {
            "total": len(bucket_rows),
            "candidate_acceptable": accepted,
            "pass_rate": round(pass_rate, 4),
            "required_pass_rate": threshold,
            "unexpected_not_applicable_count": unexpected_na,
            "gate_passed": pass_rate >= threshold and unexpected_na == ANSWERABLE_CASE_NOT_APPLICABLE_LIMIT,
        }
    return summary


def score_capability_failures(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for row in rows:
        candidate = row["answers"]["candidate"]
        if candidate["acceptable"] and not row.get("unexpected_not_applicable"):
            continue
        family = str(row.get("capability_family") or "unknown")
        item = summary.setdefault(
            family,
            {
                "total_failures": 0,
                "unexpected_not_applicable_count": 0,
                "case_ids": [],
                "issues": {},
            },
        )
        item["total_failures"] += 1
        if row.get("unexpected_not_applicable"):
            item["unexpected_not_applicable_count"] += 1
        item["case_ids"].append(row.get("case_id"))
        for issue in candidate.get("issues") or []:
            item["issues"][issue] = item["issues"].get(issue, 0) + 1
        for reason in row.get("failure_reasons") or []:
            item["issues"][reason] = item["issues"].get(reason, 0) + 1
    return summary


def average_dimensions(rows: list[dict[str, Any]], role: str) -> dict[str, float]:
    keys = list(WEIGHTS)
    return {
        key: round(statistics.mean(row["answers"][role]["dimensions"][key] for row in rows), 2)
        for key in keys
    }


def score_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    source_label = summary.get("source_answer_label") or dominant_reference_label(result["rows"])
    candidate_acceptable_count = summary.get("candidate_acceptable_count", 0)
    candidate_acceptance_rate = summary.get(
        "candidate_acceptance_rate",
        candidate_acceptable_count / summary["case_count"] if summary.get("case_count") else 0.0,
    )
    lines = [
        "# Comparison Answer Scores",
        "",
        f"Source: {result['source']}",
        f"Generated at: {result['generated_at']}",
        f"Judge mode: {result.get('judge_mode', 'unknown')}",
        "",
        "## Summary",
        "",
        f"- Cases: {summary['case_count']}",
        f"- {source_label} average total: {summary['standard_average_total']}",
        f"- VDS candidate average total: {summary['candidate_average_total']}",
        f"- VDS candidate acceptable: {candidate_acceptable_count} / {summary['case_count']} ({candidate_acceptance_rate:.2%})",
        f"- Unexpected Not Applicable: {summary.get('unexpected_not_applicable_count', 0)}",
        f"- Acceptance gate passed: {summary.get('acceptance_passed', False)}",
        f"- Average pair similarity: {summary['average_pair_similarity']}",
        f"- Needs human review: {summary['needs_human_review_count']}",
        f"- Verdict counts: {json.dumps(display_verdict_counts(summary['verdict_counts']), ensure_ascii=False)}",
        "",
        "## Acceptance Buckets",
        "",
        "| bucket | candidate acceptable | required | unexpected Not Applicable | gate |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for bucket in ("ordinary", "complex"):
        item = (summary.get("acceptance_buckets") or {}).get(bucket) or {}
        lines.append(
            "| {bucket} | {accepted}/{total} ({rate:.2%}) | {required:.0%} | {na} | {gate} |".format(
                bucket=bucket,
                accepted=item.get("candidate_acceptable", 0),
                total=item.get("total", 0),
                rate=float(item.get("pass_rate", 0.0)),
                required=float(item.get("required_pass_rate", 0.0)),
                na=item.get("unexpected_not_applicable_count", 0),
                gate=item.get("gate_passed", False),
            )
        )
    if summary.get("capability_failures"):
        lines.extend(["", "## Capability Failures", ""])
        for family, item in sorted(summary["capability_failures"].items(), key=lambda pair: pair[1].get("total_failures", 0), reverse=True)[:12]:
            lines.append(
                f"- {family}: failures={item.get('total_failures', 0)}, unexpected Not Applicable={item.get('unexpected_not_applicable_count', 0)}, cases={', '.join(str(case_id) for case_id in item.get('case_ids', [])[:8])}"
            )
    lines.extend(
        [
            "",
            "## Cases",
            "",
            f"| case_id | {source_label} | VDS candidate | similarity | verdict |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in result["rows"]:
        lines.append(
            "| {case_id} | {standard:.2f} | {candidate:.2f} | {similarity:.2f} | {verdict} |".format(
                case_id=row["case_id"],
                standard=row["answers"]["standard"]["total_score"],
                candidate=row["answers"]["candidate"]["total_score"],
                similarity=row["pair_similarity"],
                verdict=display_verdict_label(row["verdict"]["label"]),
            )
        )
    lines.extend(["", "## Review Notes", ""])
    for row in result["rows"]:
        if not row["verdict"]["needs_human_review"] and not row["answers"]["candidate"]["issues"]:
            continue
        row_source_label = row.get("reference_answer_label") or reference_answer_label(row.get("standard_answer_source"))
        lines.extend(
            [
                f"### {row['case_id']}",
                "",
                f"- Question: {row['question']}",
                f"- Expected route: {row['expected_route']}",
                f"- Difficulty bucket: {row.get('difficulty_bucket', 'ordinary')}",
                f"- Capability family: {row.get('capability_family', 'unknown')}",
                f"- Unexpected Not Applicable: {row.get('unexpected_not_applicable', False)}",
                f"- Verdict: {display_verdict_label(row['verdict']['label'])} ({row['verdict']['reason']})",
                f"- {row_source_label} dimensions: {json.dumps(row['answers']['standard']['dimensions'], ensure_ascii=False)}",
                f"- Candidate dimensions: {json.dumps(row['answers']['candidate']['dimensions'], ensure_ascii=False)}",
                f"- Candidate issues: {display_text_items(row['answers']['candidate']['issues'], row_source_label)}",
                f"- Candidate notes: {display_text_items(row['answers']['candidate']['notes'], row_source_label)}",
                "",
                reference_heading(row_source_label),
                "",
                markdown_answer_block(row.get("source_answers", {}).get("standard_answer") or ""),
                "",
                "**VDS 实际回复**",
                "",
                markdown_answer_block(row.get("source_answers", {}).get("candidate_answer") or ""),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def markdown_answer_block(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return "_空回复_"
    return "```text\n" + value.replace("```", "'''") + "\n```"


def display_verdict_counts(counts: dict[str, int]) -> dict[str, int]:
    result: dict[str, int] = {}
    for label, count in counts.items():
        display = display_verdict_label(label)
        result[display] = result.get(display, 0) + count
    return result


def display_text_items(items: list[Any], source_label: str) -> str:
    texts = [display_source_word(str(item), source_label) for item in items if str(item).strip()]
    return ", ".join(texts) or "none"


def display_source_word(text: str, source_label: str) -> str:
    label = source_label or "source"
    return re.sub(r"reference", label, text, flags=re.IGNORECASE)


def expected_numbers_from_row(row: dict[str, Any]) -> list[dict[str, float]]:
    numbers: list[dict[str, float]] = []
    for item in row.get("number_checks") or []:
        if not isinstance(item, dict) or "expected" not in item:
            continue
        try:
            expected = float(item["expected"])
            tolerance = float(item.get("tolerance", max(0.01, abs(expected) * 0.01)))
        except (TypeError, ValueError):
            continue
        numbers.append({"value": expected, "tolerance": tolerance})
    if numbers:
        return numbers
    reference_values = extract_numbers(row.get("standard_answer", ""))
    return [{"value": value, "tolerance": max(0.01, abs(value) * 0.01)} for value in reference_values[:8]]


def contains_expected_number(text: str, expected: float, tolerance: float) -> bool:
    return any(abs(value - expected) <= tolerance for value in extract_numbers(text))


def extract_numbers(text: str) -> list[float]:
    values: list[float] = []
    for match in NUMBER_RE.finditer(text):
        raw = match.group(0).replace(",", "")
        is_percent = raw.endswith("%")
        raw = raw.rstrip("%")
        try:
            value = float(raw)
        except ValueError:
            continue
        values.append(value / 100.0 if is_percent else value)
    return values


def number_similarity(left: list[float], right: list[float]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    matched = 0
    used: set[int] = set()
    for left_value in left[:20]:
        for index, right_value in enumerate(right[:20]):
            if index in used:
                continue
            tolerance = max(0.01, abs(right_value) * 0.01)
            if abs(left_value - right_value) <= tolerance:
                matched += 1
                used.add(index)
                break
    return matched / max(len(left[:20]), len(right[:20]))


def content_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in TOKEN_RE.findall(text.lower()):
        if HAN_RE.fullmatch(raw):
            if len(raw) <= 2:
                tokens.add(raw)
            else:
                tokens.update(raw[index : index + 2] for index in range(len(raw) - 1))
                tokens.update(raw[index : index + 3] for index in range(max(0, len(raw) - 2)))
        else:
            cleaned = raw.strip("_").rstrip("%")
            if cleaned and cleaned not in STOP_TOKENS:
                tokens.add(cleaned)
    return {token for token in tokens if token not in STOP_TOKENS and len(token) > 1}


def char_ngrams(text: str, n: int = 3) -> set[str]:
    normalized = PUNCT_RE.sub("", text.lower())
    if len(normalized) <= n:
        return {normalized} if normalized else set()
    return {normalized[index : index + n] for index in range(len(normalized) - n + 1)}


def f1_score(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    precision = overlap / len(right)
    recall = overlap / len(left)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def recall_score(reference: set[str], answer: set[str]) -> float:
    if not reference:
        return 1.0 if answer else 0.0
    return len(reference & answer) / len(reference)


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def question_keyword_coverage(text: str, question: str) -> float:
    question_tokens = content_tokens(question)
    if not question_tokens:
        return 0.5
    answer_tokens = content_tokens(text)
    return len(question_tokens & answer_tokens) / len(question_tokens)


def route_coverage_score(text: str, question: str, expected_route: str) -> float:
    if not text.strip():
        return 0.0
    if route_is_no_file(expected_route):
        coverage = 0.0
        coverage += 0.45 if has_no_file_boundary(text) or "上传" in text else 0.0
        coverage += 0.30 if any(term in text for term in ("分析", "字段", "指标", "质量", "趋势", "多文件", "join", "对比")) else 0.0
        coverage += 0.25 if any(term in text for term in ("不能", "不会", "不编造", "真实数据", "具体数据结论")) else 0.0
        return min(1.0, coverage)
    if expected_route == "cleaning_simulation":
        coverage = 0.0
        coverage += 0.35 if any(term in text for term in ("清洗", "删除", "填充", "保留", "规则")) else 0.0
        coverage += 0.30 if any(term in text for term in ("影响", "行数", "比例", "模拟")) else 0.0
        coverage += 0.35 if any(term in text for term in ("确认", "不能覆盖", "不会直接修改", "原始数据")) else 0.0
        return min(1.0, coverage)
    if expected_route in {"dataset_overview", "analysis", "chat_with_dataset"}:
        coverage = 0.0
        coverage += 0.30 if any(term in text for term in ("表", "数据集", "行", "列", "记录")) else 0.0
        coverage += 0.25 if any(term in text for term in ("字段", "指标", "维度", "时间", "ID", "角色")) else 0.0
        coverage += 0.25 if any(term in text for term in ("缺失", "异常", "质量", "重复", "极端", "风险")) else 0.0
        coverage += 0.20 if any(term in text for term in ("建议", "下一步", "适合", "可以继续", "不能", "需要")) else 0.0
        if any(term in question.lower() for term in ("raw prompt", "trace", "sql", "标准答案")) and guardrail_denial(text):
            coverage = max(coverage, 0.9)
        return min(1.0, coverage)
    return 0.7 if len(text) >= 20 else 0.35


def semantic_concepts(text: str) -> set[str]:
    lowered = text.lower()
    concepts: set[str] = set()
    concept_terms = {
        "upload_boundary": ("没有上传", "没有数据", "上传文件", "上传数据", "先上传", "当前没有"),
        "no_fabrication": ("不编造", "不能编造", "不能给出具体", "真实数据", "推测", "不确定"),
        "schema_overview": ("表", "行", "列", "记录", "字段", "schema", "结构"),
        "field_roles": ("字段角色", "指标", "维度", "时间字段", "id", "编号", "代码"),
        "data_quality": ("质量", "缺失", "异常", "重复", "极端", "负值", "无法解析"),
        "cleaning": ("清洗", "删除", "填充", "保留", "规则", "不能覆盖", "原始数据"),
        "impact": ("影响", "行数", "比例", "占比", "模拟"),
        "next_analysis": ("建议", "下一步", "可继续", "继续问", "适合", "分析方向"),
        "multi_file": ("多文件", "join", "关联", "字段一致", "对比", "第一个文件"),
        "trend": ("趋势", "环比", "同比", "时间", "波动"),
        "ranking": ("排名", "top", "topn", "最大", "最小", "分布"),
        "guardrail": ("raw prompt", "trace", "sql", "标准答案", "只给用户可读", "不展示"),
        "business_story": ("主要讲", "业务含义", "订单", "交易", "零售", "客户", "商品"),
        "numeric_fact": ("合计", "平均", "中位数", "最大", "最小", "总计"),
    }
    for concept, terms in concept_terms.items():
        if any(term in lowered for term in terms):
            concepts.add(concept)
    numbers = extract_numbers(text)
    if numbers:
        concepts.add("has_numbers")
    if len(numbers) >= 2:
        concepts.add("multiple_numbers")
    return concepts


def weighted_total(dimensions: dict[str, float]) -> float:
    return sum(dimensions[key] * WEIGHTS[key] * 10.0 for key in WEIGHTS)


def calibrated_total(dimensions: dict[str, float], *, expected_route: str) -> float:
    total = weighted_total(dimensions)
    if requires_text_framework(expected_route):
        framework = dimensions.get("text_framework_alignment", 0.0)
        completeness = dimensions.get("completeness", 0.0)
        instruction = dimensions.get("instruction_following", 0.0)
        if framework < 4.5:
            total = min(total, 52.0)
        elif framework < 5.5:
            total = min(total, 60.0)
        elif framework < TEXT_FRAMEWORK_PASS_MIN:
            total = min(total, 70.0)

        if completeness < 5.0:
            total = min(total, 55.0)
        elif completeness < COMPLETENESS_PASS_MIN:
            total = min(total, 68.0)

        if instruction < 6.0:
            total = min(total, 62.0)
    return total


def clamp10(value: float) -> float:
    if math.isnan(value):
        return 0.0
    return max(0.0, min(10.0, value))


def route_is_no_file(route: str) -> bool:
    return route == "chat_without_dataset" or "no_file" in route


def has_no_file_boundary(text: str) -> bool:
    return any(term in text for term in NO_FILE_BOUNDARY_TERMS)


def has_concrete_dataset_claim(text: str) -> bool:
    if len(extract_numbers(text)) >= 3 and any(term in text for term in ("行", "列", "记录", "字段")):
        return True
    return any(term in text for term in ("已读取", "总计", "数据表：", "合计：", "平均 / 中位数"))


def contains_internal_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in SAFETY_MARKERS)


def guardrail_context(question: str, text: str) -> bool:
    lowered_question = question.lower()
    if not any(marker in lowered_question for marker in SAFETY_MARKERS):
        return False
    return guardrail_denial(text)


def guardrail_denial(text: str) -> bool:
    return any(term in text for term in ("不展示", "不会展示", "不能展示", "只给用户可读", "不暴露", "不能把"))


def looks_like_raw_detail_dump(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 80:
        return False
    csv_like_lines = sum(1 for line in stripped.splitlines() if line.count(",") >= 5)
    if csv_like_lines >= 5:
        return True
    parts = [part.strip() for part in re.split(r"[,，]", stripped) if part.strip()]
    if len(parts) >= 24:
        short_parts = sum(1 for part in parts if len(part) <= 24)
        numeric_parts = sum(1 for part in parts if NUMBER_RE.fullmatch(part))
        return short_parts / len(parts) >= 0.7 and numeric_parts >= 4
    return False


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
