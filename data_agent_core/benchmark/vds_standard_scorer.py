"""Post-response scorer for local VDS standard-answer workbooks.

The scorer is intentionally benchmark-side only: expected answers are compared
after an agent response exists and are never used by Planner, Executor, Verifier,
Correction, prompts, or traces.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from data_agent_core.benchmark.evaluator import question_scorer


@dataclass(frozen=True)
class VdsScoreResult:
    correct: bool
    scorer: str


def score_vds_standard_answer(
    expected: str,
    predicted: str,
    *,
    raw_value: Any = None,
    operation: str = "",
) -> VdsScoreResult:
    """Score a VDS answer with semantic checks for Chinese BI outputs."""

    if question_scorer(expected, predicted):
        return VdsScoreResult(True, "question_scorer")
    if _no_record_equivalent(expected, predicted, raw_value):
        return VdsScoreResult(True, "no_record_equivalent")
    if operation == "vds_period_growth_count_share" and _count_share_equal(expected, raw_value):
        return VdsScoreResult(True, "count_share_structured")
    if operation == "vds_peer_anomaly" and _ordered_rows_with_tie_groups(expected, predicted):
        return VdsScoreResult(True, "peer_anomaly_tie_tolerant")
    if operation == "vds_peer_anomaly" and _ordered_entity_subset(expected, predicted):
        return VdsScoreResult(True, "peer_anomaly_entity_subset")
    if _ordered_entity_subset(expected, predicted):
        return VdsScoreResult(True, "ordered_entity_subset")
    if operation == "vds_status_impact_top" and _status_impact_positive_prefix(expected, predicted, raw_value):
        return VdsScoreResult(True, "status_impact_positive_prefix_tie")
    return VdsScoreResult(False, "unmatched")


def _no_record_equivalent(expected: str, predicted: str, raw_value: Any) -> bool:
    expected_text = _compact(expected)
    predicted_text = _compact(predicted)
    expected_zero = any(token in expected_text for token in ("未发现满足条件的记录", "无满足条件", "0个"))
    predicted_zero = any(token in predicted_text for token in ("未发现满足条件的记录", "无满足条件", "0个"))
    if not expected_zero or not predicted_zero:
        return False
    table = raw_value.get("candidate_table") if isinstance(raw_value, dict) else None
    return table == [] or table is None


def _count_share_equal(expected: str, raw_value: Any) -> bool:
    if not isinstance(raw_value, dict) or not {"count", "share", "total"} <= set(raw_value):
        return False
    values = _numbers(expected)
    if len(values) >= 3:
        total, count, share = values[0], values[1], values[2]
        return (
            int(total) == int(raw_value["total"])
            and int(count) == int(raw_value["count"])
            and abs(float(raw_value["share"]) - float(share)) < 0.02
        )
    if len(values) < 2:
        return False
    count, share = values[0], values[1]
    return int(count) == int(raw_value["count"]) and abs(float(raw_value["share"]) - float(share)) < 0.02


def _ordered_entity_subset(expected: str, predicted: str) -> bool:
    expected_entities = [row.entity for row in _parse_rows(expected)]
    predicted_entities = [row.entity for row in _parse_rows(predicted)]
    if not expected_entities or not predicted_entities:
        return False
    position = 0
    for entity in predicted_entities:
        if position < len(expected_entities) and _entities_match(expected_entities[position], entity):
            position += 1
    return position == len(expected_entities)


def _ordered_rows_with_tie_groups(expected: str, predicted: str) -> bool:
    expected_rows = _parse_rows(expected)
    predicted_rows = _parse_rows(predicted)
    if not expected_rows or len(predicted_rows) < len(expected_rows):
        return False
    expected_index = 0
    predicted_index = 0
    while expected_index < len(expected_rows):
        key = expected_rows[expected_index].score_key
        expected_group = []
        while expected_index < len(expected_rows) and expected_rows[expected_index].score_key == key:
            expected_group.append(expected_rows[expected_index])
            expected_index += 1
        predicted_group = predicted_rows[predicted_index : predicted_index + len(expected_group)]
        if len(predicted_group) != len(expected_group):
            return False
        if any(row.score_key != key for row in predicted_group):
            return False
        expected_entities = {row.entity for row in expected_group}
        predicted_entities = {row.entity for row in predicted_group}
        if expected_entities != predicted_entities and {_entity_key(row.entity) for row in expected_group} != {
            _entity_key(row.entity) for row in predicted_group
        }:
            return False
        predicted_index += len(expected_group)
    return True


def _status_impact_positive_prefix(expected: str, predicted: str, raw_value: Any) -> bool:
    table = raw_value.get("candidate_table") if isinstance(raw_value, dict) else None
    if not isinstance(table, list) or not table:
        return False
    positive_names = [
        str(row.get("客户名称") or row.get("entity") or "")
        for row in table
        if abs(float(row.get("delta") or 0.0)) > 1e-9
    ]
    expected_entities = [row.entity for row in _parse_rows(expected)]
    predicted_entities = [row.entity for row in _parse_rows(predicted)]
    return expected_entities[: len(positive_names)] == positive_names == predicted_entities[: len(positive_names)]


@dataclass(frozen=True)
class _ParsedRow:
    entity: str
    score_key: tuple[float, ...]


def _parse_rows(text: str) -> list[_ParsedRow]:
    rows: list[_ParsedRow] = []
    for segment in re.split(r"[；;。]", str(text)):
        segment = segment.strip()
        if not segment or "：" not in segment:
            continue
        entity, rest = segment.split("：", 1)
        entity = re.sub(r"^\s*\d+\.\s*", "", entity).strip()
        if not entity:
            continue
        values = tuple(round(value, 2) for value in _numbers(rest))
        rows.append(_ParsedRow(entity=entity, score_key=values))
    return rows


def _entities_match(expected: str, predicted: str) -> bool:
    return expected == predicted or _entity_key(expected) == _entity_key(predicted)


def _entity_key(entity: str) -> str:
    return str(entity).split("/")[-1].strip()


def _numbers(text: str) -> list[float]:
    values: list[float] = []
    for match in re.findall(r"-?\d+(?:,\d{3})*(?:\.\d+)?", str(text)):
        try:
            values.append(float(match.replace(",", "")))
        except ValueError:
            continue
    return values


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").replace(",", ""))
