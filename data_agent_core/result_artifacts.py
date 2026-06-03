"""Result artifacts used to bind follow-up pronouns to prior answers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass
class ReferentResolution:
    """Structured referent resolution for a follow-up question."""

    resolved: bool
    artifact_id: str = ""
    referent_dimension: str = ""
    referent_values: list[Any] = field(default_factory=list)
    metric: str = ""
    referent_source: str = ""
    missing_reason: str = ""
    ranking_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_result_artifacts(
    *,
    logic: Mapping[str, Any],
    params: Mapping[str, Any],
    operation: str,
    rows: list[dict[str, Any]],
    run_id: str = "",
    question: str = "",
) -> list[dict[str, Any]]:
    """Build durable result artifacts from tabular outputs."""

    dimension = _first_text(logic.get("group_by"), params.get("dimension"), params.get("group_by"))
    if not dimension or not _looks_like_ranking(operation, question):
        return []
    values = [row.get(dimension) for row in rows if isinstance(row, Mapping) and row.get(dimension) not in (None, "")]
    if not values:
        return []
    metric = _first_text(logic.get("metric"), params.get("metric"))
    limit = _positive_int(params.get("limit") or params.get("top_n") or params.get("k")) or len(values)
    top_objects = _build_top_objects(rows=rows[:limit], dimension=str(dimension), metric=str(metric or ""), start=1)
    artifact_id = _artifact_id(
        run_id=run_id,
        operation=operation,
        dimension=str(dimension),
        metric=str(metric or ""),
        values=values,
    )
    return [
        {
            "artifact_id": artifact_id,
            "artifact_type": "ranking",
            "source": "result_rows",
            "run_id": run_id,
            "question": question,
            "operation": operation,
            "dimension": str(dimension),
            "metric": str(metric or ""),
            "aggregation": str(params.get("aggregation") or "sum"),
            "limit": limit,
            "sort_order": str(params.get("sort_order") or "desc"),
            "filters": dict(logic.get("filters") or {}),
            "source_tables": _source_tables(logic, params),
            "join_plan": dict(logic.get("join_plan") or params.get("join_plan") or {}),
            "table": str(params.get("table") or ""),
            "table_selection_reason": str(logic.get("table_selection_reason") or params.get("table_selection_reason") or ""),
            "values": values[:limit],
            "top_objects": top_objects,
            "rank_map": {str(value): index for index, value in enumerate(values[:limit], start=1)},
            "rows": rows[:limit],
        }
    ]


def build_task_artifacts(*, task_contract: Mapping[str, Any], rows: list[dict[str, Any]], answer: str = "") -> dict[str, Any]:
    """Build task artifacts for TopN, Gap, and Trend contracts."""

    family = str(task_contract.get("task_family") or "")
    if family in {"topn", "ranking"}:
        dimension = str(task_contract.get("dimension") or "")
        metric = str(task_contract.get("metric") or "")
        top_objects = _build_top_objects(rows=rows, dimension=dimension, metric=metric, start=1)
        distinct_count = len({row.get(dimension) for row in rows if dimension and row.get(dimension) not in {None, ""}})
        return {
            "top_objects": top_objects,
            "distinct_count": distinct_count if dimension else len(rows),
        }
    if family == "gap":
        return _gap_task_artifacts(task_contract, rows, answer)
    if family == "trend":
        return _trend_task_artifacts(task_contract, rows, answer)
    return {}


def merge_result_artifacts(previous: Any, current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge newest artifacts first while preserving prior context."""

    merged: list[dict[str, Any]] = []
    for item in [*current, *(previous if isinstance(previous, list) else [])]:
        if not isinstance(item, Mapping):
            continue
        normalized = dict(item)
        artifact_id = str(normalized.get("artifact_id") or "")
        if not artifact_id or any(existing.get("artifact_id") == artifact_id for existing in merged):
            continue
        merged.append(normalized)
    return merged[:10]


def resolve_followup_referent(user_question: str, context: Mapping[str, Any] | None) -> dict[str, Any]:
    """Resolve Chinese demonstratives and rank ordinals to prior result artifacts."""

    compact = re.sub(r"\s+", "", str(user_question or ""))
    if not _looks_like_referent_question(compact):
        return ReferentResolution(False, missing_reason="not_referent").to_dict()
    artifacts = _active_artifacts(context)
    artifact = _select_artifact(compact, artifacts)
    if not artifact:
        return ReferentResolution(False, missing_reason="REFERENT_ARTIFACT_MISSING").to_dict()
    dimension = str(artifact.get("dimension") or "")
    if _asks_specific_dimension(compact, "city") and not _dimension_matches_concept(dimension, "city"):
        return ReferentResolution(False, missing_reason="REFERENT_ARTIFACT_MISSING").to_dict()
    values = _referent_values_from_artifact(artifact)
    rank_index = _rank_index(compact)
    source = str(artifact.get("source") or "")
    source = "result_artifact:ranking:top_objects" if artifact.get("top_objects") else f"{source}:ranking" if source else "result_artifact:ranking"
    if rank_index is not None:
        if rank_index < 1 or rank_index > len(values):
            return ReferentResolution(False, artifact_id=str(artifact.get("artifact_id") or ""), referent_dimension=dimension, missing_reason="REFERENT_VALUES_MISSING").to_dict()
        values = [values[rank_index - 1]]
        source = f"{source}:rank_{rank_index}"
    if not values:
        return ReferentResolution(False, artifact_id=str(artifact.get("artifact_id") or ""), referent_dimension=dimension, missing_reason="REFERENT_VALUES_MISSING").to_dict()
    return ReferentResolution(
        True,
        artifact_id=str(artifact.get("artifact_id") or ""),
        referent_dimension=dimension,
        referent_values=values,
        metric=str(artifact.get("metric") or ""),
        referent_source=source,
        ranking_context=_ranking_context_from_artifact(artifact),
    ).to_dict()


def _active_artifacts(context: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not isinstance(context, Mapping):
        return []
    artifacts = [item for item in context.get("active_result_artifacts") or [] if isinstance(item, Mapping)]
    focus_artifacts = [_artifact_from_focus_set(item) for item in context.get("focus_sets") or [] if isinstance(item, Mapping)]
    combined = [*artifacts, *[item for item in focus_artifacts if item]]
    last_ranking_artifact_id = str(context.get("last_ranking_artifact_id") or "")
    if last_ranking_artifact_id:
        combined.sort(key=lambda item: 0 if str(item.get("artifact_id") or "") == last_ranking_artifact_id else 1)
    return combined


def _select_artifact(compact: str, artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    ranking = [item for item in artifacts if str(item.get("artifact_type") or "") in {"ranking", "topn"}]
    if not ranking:
        return None
    target_concept = _referent_dimension_concept(compact)
    if target_concept:
        for artifact in ranking:
            if _dimension_matches_concept(str(artifact.get("dimension") or ""), target_concept):
                return artifact
        return None
    return ranking[0]


def _referent_values_from_artifact(artifact: Mapping[str, Any]) -> list[Any]:
    values = []
    for item in artifact.get("top_objects") or []:
        if not isinstance(item, Mapping):
            continue
        value = item.get("value")
        if value not in (None, ""):
            values.append(value)
    if values:
        return values
    return [value for value in artifact.get("values") or [] if value not in (None, "")]


def _artifact_from_focus_set(focus_set: Mapping[str, Any]) -> dict[str, Any] | None:
    values = [value for value in focus_set.get("values") or [] if value not in (None, "")]
    if not values:
        return None
    dimension = str(focus_set.get("dimension") or "")
    if not dimension:
        return None
    return {
        "artifact_id": str(focus_set.get("artifact_id") or f"focus_set_{_normalize(dimension)}"),
        "artifact_type": "ranking",
        "source": str(focus_set.get("source") or "focus_set"),
        "dimension": dimension,
        "metric": str(focus_set.get("metric") or ""),
        "values": values,
        "top_objects": [
            {"rank": index, "value": value, "metric_value": None}
            for index, value in enumerate(values, start=1)
        ],
    }


def _ranking_context_from_artifact(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Carry enough prior ranking metadata to rerun TopN for follow-up gaps."""

    keep = {
        "metric": artifact.get("metric"),
        "metric_column": artifact.get("metric") or artifact.get("metric_column"),
        "dimension": artifact.get("dimension"),
        "dimension_column": artifact.get("dimension") or artifact.get("dimension_column"),
        "filters": dict(artifact.get("filters") or {}),
        "source_tables": [str(item) for item in artifact.get("source_tables") or [] if str(item)],
        "join_plan": dict(artifact.get("join_plan") or {}),
        "aggregation": artifact.get("aggregation") or "sum",
        "sort_order": artifact.get("sort_order") or "desc",
        "table": artifact.get("table"),
        "table_selection_reason": artifact.get("table_selection_reason"),
    }
    return {key: value for key, value in keep.items() if value not in (None, "", [], {})}


def _source_tables(logic: Mapping[str, Any], params: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for item in logic.get("source_tables") or []:
        if item:
            values.append(str(item))
    for key in ("source_tables", "tables", "table"):
        raw = params.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if item)
        elif raw:
            values.append(str(raw))
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped


def _looks_like_referent_question(compact: str) -> bool:
    if any(token in compact for token in ("这些Top对象", "这些top对象", "这些TOP对象", "Top城市", "top城市", "这些城市", "上述城市", "这些", "上述", "它们", "前几个")):
        return True
    return _rank_index(compact) is not None


def _rank_index(compact: str) -> int | None:
    patterns = (
        (r"(?:第一名|第1名|排名第一|排名第1|第一|第1)", 1),
        (r"(?:第二名|第2名|排名第二|排名第2|第二|第2)", 2),
        (r"(?:第三名|第3名|排名第三|排名第3|第三|第3)", 3),
    )
    for pattern, index in patterns:
        if re.search(pattern, compact):
            return index
    return None


def _asks_specific_dimension(compact: str, concept: str) -> bool:
    return _referent_dimension_concept(compact) == concept


def _referent_dimension_concept(compact: str) -> str:
    if any(token in compact for token in ("城市", "地区", "区域")):
        return "city"
    if any(token in compact for token in ("产品", "商品", "sku", "SKU")):
        return "product"
    if any(token in compact for token in ("客户", "顾客")):
        return "customer"
    return ""


def _dimension_matches_concept(dimension: str, concept: str) -> bool:
    aliases = {
        "city": ("city", "城市", "市", "region", "area", "地区", "区域"),
        "product": ("product", "sku", "item", "goods", "产品", "商品"),
        "customer": ("customer", "cust", "client", "buyer", "客户", "顾客"),
    }.get(concept, ())
    normalized = _normalize(dimension)
    return any(_normalize(alias) and _normalize(alias) in normalized for alias in aliases)


def _artifact_id(*, run_id: str, operation: str, dimension: str, metric: str, values: list[Any]) -> str:
    seed = repr((run_id, operation, dimension, metric, [str(value) for value in values[:20]]))
    return "artifact_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def _looks_like_ranking(operation: str, question: str) -> bool:
    text = f"{operation} {question}".lower()
    return any(token in text for token in ("ranking", "top", "rank", "排名", "排行", "前", "最高", "最低", "最多", "最少"))


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _first_non_dimension_value(*, row: Mapping[str, Any], dimension: str) -> Any:
    for key, value in row.items():
        if key == dimension:
            continue
        return value
    return None


def _normalize(value: str) -> str:
    return "".join(char for char in str(value or "").lower() if char.isalnum() or "\u4e00" <= char <= "\u9fff")


def _gap_task_artifacts(task_contract: Mapping[str, Any], rows: list[dict[str, Any]], answer: str) -> dict[str, Any]:
    metric = str(task_contract.get("metric") or "")
    if not metric and rows:
        dimension = str(task_contract.get("dimension") or "")
        metric = next((key for key in rows[0] if key != dimension and _as_float(rows[0].get(key)) is not None), "")
    dimension = str(task_contract.get("dimension") or "")
    top_objects = _build_top_objects(rows=rows, dimension=dimension, metric=metric, start=1)
    adjacent_gaps: list[Any] = []
    gap_to_leader: list[Any] = []
    if top_objects:
        adjacent_gaps, gap_to_leader = _derive_gap_series(top_objects=top_objects)
    gap_rows: list[dict[str, Any]] = []
    if len(rows) >= 2 and metric:
        leader_value = _as_float(rows[0].get(metric))
        previous_value = leader_value
        for index, row in enumerate(rows):
            value = _as_float(row.get(metric))
            gap_row = dict(row)
            if leader_value is not None and value is not None:
                gap_row["gap_to_leader"] = leader_value - value
            if index > 0 and previous_value is not None and value is not None:
                gap_row["gap_from_previous"] = previous_value - value
                gap_row["adjacent_gap"] = previous_value - value
            gap_rows.append(gap_row)
            previous_value = value
    return {
        "top_objects": top_objects,
        "adjacent_gaps": adjacent_gaps,
        "gap_to_leader": gap_to_leader,
        "gap_rows": gap_rows,
        "direct_gap_summary": (str(answer or "").splitlines() or [""])[0].strip(),
    }


def _build_top_objects(*, rows: list[dict[str, Any]], dimension: str, metric: str, start: int) -> list[dict[str, Any]]:
    top_objects: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=start):
        if not isinstance(row, Mapping):
            continue
        value = row.get(dimension)
        if value in {None, ""}:
            continue
        normalized = dict(row)
        normalized["rank"] = index
        normalized["value"] = value
        normalized["metric_value"] = row.get(metric) if metric else _first_non_dimension_value(row=row, dimension=dimension)
        top_objects.append(normalized)
    return top_objects


def _derive_gap_series(*, top_objects: list[dict[str, Any]]) -> tuple[list[Any], list[Any]]:
    adjacent_gaps: list[Any] = []
    gap_to_leader: list[Any] = []
    if not top_objects:
        return adjacent_gaps, gap_to_leader
    leader_value = _as_float(top_objects[0].get("metric_value"))
    previous_value = leader_value
    for index, row in enumerate(top_objects):
        value = _as_float(row.get("metric_value"))
        if leader_value is not None and value is not None:
            gap_to_leader.append(_round_gap_value(leader_value - value))
        else:
            gap_to_leader.append(None)
        if index > 0:
            if previous_value is not None and value is not None:
                adjacent_gaps.append(_round_gap_value(previous_value - value))
            else:
                adjacent_gaps.append(None)
        previous_value = value
    return adjacent_gaps, gap_to_leader


def _round_gap_value(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 4)


def _trend_task_artifacts(task_contract: Mapping[str, Any], rows: list[dict[str, Any]], answer: str) -> dict[str, Any]:
    metric = str(task_contract.get("metric") or "")
    values = [_as_float(row.get(metric)) for row in rows] if metric else []
    numeric_values = [value for value in values if value is not None]
    return {
        "time_series": [dict(row) for row in rows],
        "trend_description": _trend_description(numeric_values),
        "direct_trend_summary": str(answer or "").splitlines()[0].strip(),
    }


def _trend_description(values: list[float]) -> str:
    if len(values) <= 1:
        return "无法判断趋势"
    deltas = [values[index + 1] - values[index] for index in range(len(values) - 1)]
    positives = [delta for delta in deltas if delta > 0]
    negatives = [delta for delta in deltas if delta < 0]
    if positives and not negatives:
        return "整体上升"
    if negatives and not positives:
        return "整体下降"
    if len(deltas) >= 2 and deltas[0] > 0 and any(delta < 0 for delta in deltas[1:]):
        return "先升后降"
    if len(deltas) >= 2 and deltas[0] < 0 and any(delta > 0 for delta in deltas[1:]):
        return "先降后升"
    return "波动"


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
