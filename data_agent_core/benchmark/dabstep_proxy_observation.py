"""Post-response DABstep proxy observation from local task score files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from data_agent_core.benchmark.evaluator import question_scorer
from data_agent_core.benchmark.provenance import command_line, sha256_file, stamp_report_provenance


def build_dabstep_proxy_observation(
    *,
    dataset_root: str | Path,
    report_path: str | Path | None = None,
    predictions_path: str | Path | None = None,
    output_path: str | Path | None = None,
    old_proxy_path: str | Path | None = None,
    external_easy_target: float | None = None,
    external_hard_target: float | None = None,
) -> dict[str, Any]:
    """Score produced answers against local post-response answer pools."""

    dataset_root = Path(dataset_root)
    tasks_path = dataset_root / "data" / "tasks" / "all.jsonl"
    task_scores_dir = dataset_root / "data" / "task_scores"
    tasks = _load_jsonl(tasks_path)
    report = _load_json(report_path) if report_path else {}
    report_rows = _rows_by_task_id(report.get("details") or [])
    prediction_rows = _rows_by_task_id(_load_jsonl(predictions_path) if predictions_path else [])
    observed_rows = _merge_observed_rows(report_rows, prediction_rows)
    answer_pools, answer_counts, score_levels, task_score_stats = _load_score_pools(task_scores_dir)

    rows: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task.get("task_id"))
        observed = observed_rows.get(task_id, {})
        agent_answer = str(observed.get("agent_answer") or observed.get("predicted") or "")
        pool = answer_pools.get(task_id, set())
        raw_match = bool(pool) and any(question_scorer(expected, agent_answer) for expected in pool)
        canonical_agent_answer = canonical_proxy_answer(agent_answer)
        normalized_match = raw_match or (
            bool(pool)
            and any(_proxy_answers_match(expected, canonical_agent_answer) for expected in pool)
        )
        level = str(task.get("level") or score_levels.get(task_id) or observed.get("level") or "unknown").lower()
        proxy_correct = bool(pool) and normalized_match
        row = {
            "task_id": task_id,
            "level": level,
            "question": task.get("question"),
            "operation": observed.get("operation"),
            "capability_family": observed.get("capability_family"),
            "agent_answer": agent_answer,
            "canonical_agent_answer": canonical_agent_answer,
            "proxy_correct": proxy_correct,
            "proxy_raw_match": raw_match,
            "proxy_normalized_match": normalized_match,
            "proxy_pool_size": task_score_stats["true_row_count_by_task"].get(task_id, 0),
            "proxy_distinct_answer_count": len(pool),
            "proxy_top_answers": [answer for answer, _count in answer_counts.get(task_id, Counter()).most_common(5)],
            "success": observed.get("success"),
            "error_type": observed.get("error_type"),
            "not_applicable_category": observed.get("not_applicable_category"),
            "coverage_gap": observed.get("coverage_gap"),
            "semantic_mismatch": observed.get("semantic_mismatch"),
            "executor_mismatch": observed.get("executor_mismatch"),
            "format_mismatch": observed.get("format_mismatch"),
            "list_answer_normalized": _looks_like_list(agent_answer) and canonical_agent_answer != agent_answer.strip(),
            "normalization_recovered_match": (not raw_match) and normalized_match,
        }
        rows.append(row)

    report_payload = _summarize_observation(
        rows=rows,
        dataset_root=dataset_root,
        report_path=Path(report_path) if report_path else None,
        predictions_path=Path(predictions_path) if predictions_path else _report_predictions_path(report),
        old_proxy_path=Path(old_proxy_path) if old_proxy_path else None,
        source_report=report,
        task_score_stats=task_score_stats,
        external_easy_target=external_easy_target,
        external_hard_target=external_hard_target,
    )
    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        stamp_report_provenance(report_payload)
        output.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2))
    return report_payload


def canonical_proxy_answer(answer: Any) -> str:
    """Normalize list-like answer text for observation-time comparison."""

    text = "" if answer is None else str(answer).strip()
    if not _looks_like_list(text):
        return text
    stripped = re.sub(r"^\[|\]$", "", text).strip()
    items = [item.strip().strip("'\"") for item in re.split(r"[,;]", stripped) if item.strip()]
    if not items:
        return text
    if all(re.fullmatch(r"-?\d+(?:\.0+)?", item) for item in items):
        items = [str(int(float(item))) for item in items]
        items.sort(key=lambda item: int(item))
    else:
        items.sort(key=lambda item: item.lower())
    return ", ".join(items)


def _proxy_answers_match(expected: str, predicted: str) -> bool:
    if question_scorer(expected, predicted):
        return True
    return canonical_proxy_answer(expected).lower() == canonical_proxy_answer(predicted).lower()


def _looks_like_list(answer: str) -> bool:
    text = answer.strip()
    return "," in text or ";" in text or (text.startswith("[") and text.endswith("]"))


def _load_jsonl(path: str | Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    rows: list[dict[str, Any]] = []
    with Path(path).open() as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _load_json(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return json.loads(Path(path).read_text())


def _rows_by_task_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_id = row.get("task_id")
        if task_id is not None:
            out[str(task_id)] = dict(row)
    return out


def _merge_observed_rows(
    report_rows: dict[str, dict[str, Any]],
    prediction_rows: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged = {task_id: dict(row) for task_id, row in report_rows.items()}
    for task_id, row in prediction_rows.items():
        merged.setdefault(task_id, {}).update(row)
    return merged


def _load_score_pools(
    task_scores_dir: Path,
) -> tuple[dict[str, set[str]], dict[str, Counter[str]], dict[str, str], dict[str, Any]]:
    answer_pools: dict[str, set[str]] = defaultdict(set)
    answer_counts: dict[str, Counter[str]] = defaultdict(Counter)
    score_levels: dict[str, str] = {}
    true_row_count_by_task: Counter[str] = Counter()
    file_count = 0
    row_count = 0
    true_row_count = 0
    for path in sorted(task_scores_dir.glob("*.jsonl")):
        file_count += 1
        with path.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                row_count += 1
                row = json.loads(line)
                task_id = str(row.get("task_id"))
                if row.get("level"):
                    score_levels.setdefault(task_id, str(row["level"]).lower())
                if row.get("score") is not True:
                    continue
                answer = str(row.get("agent_answer") or "").strip()
                if not answer:
                    continue
                true_row_count += 1
                true_row_count_by_task[task_id] += 1
                answer_pools[task_id].add(answer)
                answer_counts[task_id][answer] += 1
    stats = {
        "task_scores_dir": str(task_scores_dir),
        "task_scores_file_count": file_count,
        "task_scores_manifest_sha256": _manifest_sha256(task_scores_dir),
        "task_score_row_count": row_count,
        "task_score_true_row_count": true_row_count,
        "true_row_count_by_task": dict(true_row_count_by_task),
    }
    return dict(answer_pools), dict(answer_counts), score_levels, stats


def _summarize_observation(
    *,
    rows: list[dict[str, Any]],
    dataset_root: Path,
    report_path: Path | None,
    predictions_path: Path | None,
    old_proxy_path: Path | None,
    source_report: dict[str, Any],
    task_score_stats: dict[str, Any],
    external_easy_target: float | None,
    external_hard_target: float | None,
) -> dict[str, Any]:
    scored_rows = [row for row in rows if row["proxy_pool_size"] > 0]
    correct_rows = [row for row in scored_rows if row["proxy_correct"]]
    failure_rows = [row for row in scored_rows if not row["proxy_correct"]]
    payload: dict[str, Any] = {
        "predictions_path": None if predictions_path is None else str(predictions_path),
        "report_path": None if report_path is None else str(report_path),
        "proxy_source": "local task_scores true-score answer pools; not official hidden score",
        "proxy_policy": "post-response observation only; not used in planner/executor/verifier/correction",
        "public_proxy_policy": "not_used_in_core_chain",
        "score_context": {
            "latest_proxy": "generated_from_current_report_or_predictions",
            "old_proxy_path": None if old_proxy_path is None else str(old_proxy_path),
            "external_easy_target": external_easy_target,
            "external_hard_target": external_hard_target,
            "external_score_policy": "user-provided target line only unless separately verified",
        },
        "total_tasks": len(rows),
        "proxy_scored": len(scored_rows),
        "proxy_correct": len(correct_rows),
        "proxy_accuracy": None if not scored_rows else len(correct_rows) / len(scored_rows),
        "proxy_by_level": _summarize_by_level(rows),
        "no_public_accepted_pool": [row["task_id"] for row in rows if row["proxy_pool_size"] == 0],
        "success_count": sum(1 for row in rows if row.get("success") is True),
        "unexpected_not_applicable": source_report.get("unexpected_not_applicable"),
        "true_unsupported": source_report.get("true_unsupported"),
        "format_observation": {
            "list_answer_normalized_count": sum(1 for row in rows if row["list_answer_normalized"]),
            "normalization_recovered_match_count": sum(1 for row in rows if row["normalization_recovered_match"]),
            "failed_after_normalization_count": len(failure_rows),
        },
        "format_risk_count": _risk_count(source_report, "format_risk"),
        "submission_risk_count": _risk_count(source_report, "submission_risk"),
        "trace_redaction_risk_count": _risk_count(source_report, "trace_redaction_risk"),
        "sql_coverage": (source_report.get("metrics") or {}).get("sql_coverage") or source_report.get("sql_coverage"),
        "pandas_sql_consistency": (source_report.get("metrics") or {}).get("pandas_sql_consistency") or source_report.get("pandas_sql_consistency"),
        "failure_count": len(failure_rows),
        "failure_task_ids": [row["task_id"] for row in failure_rows],
        "failure_by_operation": _count_key(failure_rows, "operation"),
        "failure_by_capability_family": _count_key(failure_rows, "capability_family"),
        "risk_taxonomy": source_report.get("risk_taxonomy") or (source_report.get("metrics") or {}).get("risk_taxonomy"),
        "provenance": _observation_provenance(
            dataset_root=dataset_root,
            report_path=report_path,
            predictions_path=predictions_path,
            old_proxy_path=old_proxy_path,
            task_score_stats=task_score_stats,
        ),
        "rows": rows,
    }
    return payload


def _summarize_by_level(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("level") or "unknown")].append(row)
    return {level: _summarize_rows(level_rows) for level, level_rows in sorted(grouped.items())}


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [row for row in rows if row["proxy_pool_size"] > 0]
    correct = [row for row in scored if row["proxy_correct"]]
    return {
        "total": len(rows),
        "proxy_scored": len(scored),
        "proxy_correct": len(correct),
        "proxy_accuracy": None if not scored else len(correct) / len(scored),
    }


def _count_key(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(row.get(key) or "unknown") for row in rows)
    return dict(sorted(counts.items()))


def _risk_count(report: dict[str, Any], key: str) -> int | None:
    risk_taxonomy = report.get("risk_taxonomy") or (report.get("metrics") or {}).get("risk_taxonomy") or {}
    bucket = risk_taxonomy.get(key)
    if isinstance(bucket, dict):
        return bucket.get("count")
    return None


def _report_predictions_path(report: dict[str, Any]) -> Path | None:
    path = report.get("predictions_path")
    return Path(path) if path else None


def _observation_provenance(
    *,
    dataset_root: Path,
    report_path: Path | None,
    predictions_path: Path | None,
    old_proxy_path: Path | None,
    task_score_stats: dict[str, Any],
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "benchmark": "dabstep_proxy_observation",
        "command": command_line(),
        "cwd": str(Path.cwd()),
        "dataset_root": str(dataset_root),
        "source_report": _file_record(report_path),
        "source_predictions": _file_record(predictions_path),
        "old_proxy": _file_record(old_proxy_path),
        "task_scores": {
            key: value
            for key, value in task_score_stats.items()
            if key != "true_row_count_by_task"
        },
        "public_proxy_policy": "not_used_in_core_chain",
        "official_hidden_policy": "not_available_locally",
    }


def _file_record(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return {
        "path": str(path),
        "sha256": sha256_file(path) if path.exists() and path.is_file() else None,
    }


def _manifest_sha256(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.jsonl")):
        stat = path.stat()
        digest.update(f"{path.name}\t{stat.st_size}\t{stat.st_mtime_ns}\n".encode("utf-8"))
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build DABstep post-response proxy observation.")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--report")
    parser.add_argument("--predictions")
    parser.add_argument("--output", required=True)
    parser.add_argument("--old-proxy")
    parser.add_argument("--external-easy-target", type=float)
    parser.add_argument("--external-hard-target", type=float)
    args = parser.parse_args()

    payload = build_dabstep_proxy_observation(
        dataset_root=args.dataset_root,
        report_path=args.report,
        predictions_path=args.predictions,
        output_path=args.output,
        old_proxy_path=args.old_proxy,
        external_easy_target=args.external_easy_target,
        external_hard_target=args.external_hard_target,
    )
    printable = {key: value for key, value in payload.items() if key != "rows"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
