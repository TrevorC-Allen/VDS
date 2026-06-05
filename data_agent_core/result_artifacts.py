"""Result artifacts used to bind follow-up pronouns to prior answers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


_TOP_OBJECT_CACHE: dict[tuple[str, str, tuple[str, ...]], list[dict[str, Any]]] = {}


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
    derived_metadata = _derived_metric_metadata(params)
    limit = _positive_int(params.get("limit") or params.get("top_n") or params.get("k")) or len(values)
    top_objects = _build_top_objects(rows=rows[:limit], dimension=str(dimension), metric=str(metric or ""), start=1)
    artifact_id = _artifact_id(
        run_id=run_id,
        operation=operation,
        dimension=str(dimension),
        metric=str(metric or ""),
        values=values,
    )
    artifact = {
            "artifact_id": artifact_id,
            "artifact_type": "ranking",
            "source": "result_rows",
            "run_id": run_id,
            "question": question,
            "operation": operation,
            "dimension": str(dimension),
            "metric": str(metric or ""),
            "derived_metric": dict(params.get("derived_metric") or {}) if isinstance(params.get("derived_metric"), Mapping) else {},
            "aggregation": str(params.get("aggregation") or "sum"),
            "limit": limit,
            "sort_order": str(params.get("sort_order") or "desc"),
            "filters": dict(logic.get("filters") or {}),
            "source_tables": _source_tables(logic, params),
            "join_plan": dict(logic.get("join_plan") or params.get("join_plan") or {}),
            "join_keys": _join_keys(logic, params),
            "table": str(params.get("table") or ""),
            "table_selection_reason": str(logic.get("table_selection_reason") or params.get("table_selection_reason") or ""),
            "values": values[:limit],
            "top_objects": top_objects,
            "rank_map": {str(value): index for index, value in enumerate(values[:limit], start=1)},
            "rows": rows[:limit],
            **derived_metadata,
        }
    _remember_top_objects(dimension=str(dimension), metric=str(metric or ""), values=values[:limit], top_objects=top_objects)
    return [artifact]


def lookup_cached_top_objects(*, dimension: str, metric: str, values: list[Any]) -> list[dict[str, Any]]:
    """Return prior TopN object metric values remembered in this process."""

    key = _top_object_cache_key(dimension=dimension, metric=metric, values=values)
    return [dict(item) for item in _TOP_OBJECT_CACHE.get(key, [])]


def _remember_top_objects(*, dimension: str, metric: str, values: list[Any], top_objects: list[dict[str, Any]]) -> None:
    if not dimension or not values or not top_objects:
        return
    key = _top_object_cache_key(dimension=dimension, metric=metric, values=values)
    _TOP_OBJECT_CACHE[key] = [dict(item) for item in top_objects]


def _top_object_cache_key(*, dimension: str, metric: str, values: list[Any]) -> tuple[str, str, tuple[str, ...]]:
    return (_normalize(dimension), _normalize(metric), tuple(str(value) for value in values if value not in (None, "")))


def build_task_artifacts(*, task_contract: Mapping[str, Any], rows: list[dict[str, Any]], answer: str = "") -> dict[str, Any]:
    """Build task artifacts for TopN, Gap, and Trend contracts."""

    family = str(task_contract.get("task_family") or "")
    derived_metadata = _derived_metric_metadata(task_contract)
    if family in {"topn", "ranking", "drilldown_followup"}:
        dimension = str(task_contract.get("dimension") or "")
        metric = str(task_contract.get("metric") or "")
        top_objects = _build_top_objects(rows=rows, dimension=dimension, metric=metric, start=1)
        distinct_count = len({row.get(dimension) for row in rows if dimension and row.get(dimension) not in {None, ""}})
        source_tables = [str(item) for item in task_contract.get("source_tables") or [] if str(item)]
        join_plan = dict(task_contract.get("join_plan") or {})
        join_keys = [dict(item) for item in task_contract.get("join_keys") or [] if isinstance(item, Mapping)]
        verification_rules = dict(task_contract.get("verification_rules") or {})
        merged_filters = dict(task_contract.get("merged_filters") or verification_rules.get("merged_filters") or {})
        artifact = {
            "task_family": family,
            "top_objects": top_objects,
            "distinct_count": distinct_count if dimension else len(rows),
            "metric": metric,
            "metric_column": metric,
            "primary_metric_column": metric,
            "sort_metric": metric,
            "sort_order": str(task_contract.get("sort_order") or "desc"),
            "row_count": len(rows),
            "requested_n": _positive_int(task_contract.get("required_n")),
            "dimension": dimension,
            "dimension_column": dimension,
            "result_rows": rows,
            "filters": merged_filters,
            "merged_filters": merged_filters,
            **derived_metadata,
        }
        if family == "drilldown_followup":
            artifact["referent_dimension"] = str(task_contract.get("referent_dimension") or "")
            artifact["referent_values"] = list(task_contract.get("referent_values") or [])
        if source_tables:
            artifact["source_tables"] = source_tables
        if join_plan:
            artifact["join_plan"] = join_plan
        if join_keys:
            artifact["join_keys"] = join_keys
        required_n = _positive_int(task_contract.get("required_n"))
        if required_n and artifact["distinct_count"] < required_n:
            artifact["insufficient_data"] = {
                "required_n": required_n,
                "distinct_count": artifact["distinct_count"],
                "reason": "topn_distinct_count_below_requested_n",
            }
        return artifact
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
    scope_artifact = _scalar_filter_artifact_from_context(compact, context)
    if scope_artifact:
        return ReferentResolution(
            True,
            artifact_id=str(scope_artifact.get("artifact_id") or ""),
            referent_dimension=str(scope_artifact.get("dimension") or ""),
            referent_values=_referent_values_from_artifact(scope_artifact),
            metric=str(scope_artifact.get("metric") or ""),
            referent_source=str(scope_artifact.get("source") or "current_scope_filter"),
            ranking_context=_ranking_context_from_artifact(scope_artifact),
        ).to_dict()
    artifacts = _active_artifacts(context)
    artifact = _select_artifact(compact, artifacts)
    if not artifact:
        return ReferentResolution(False, missing_reason="REFERENT_ARTIFACT_MISSING").to_dict()
    dimension = str(artifact.get("dimension") or "")
    if _asks_specific_dimension(compact, "city") and not _dimension_matches_concept(dimension, "city"):
        return ReferentResolution(False, missing_reason="REFERENT_ARTIFACT_MISSING").to_dict()
    values = _referent_values_from_artifact(artifact)
    rank_index = _rank_index(compact)
    if rank_index is not None and not _rank_index_applies_to_artifact(compact, dimension):
        rank_index = None
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


def _scalar_filter_artifact_from_context(compact: str, context: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(context, Mapping) or not _singular_referent_question(compact):
        return None
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    filters = scope.get("filters") if isinstance(scope.get("filters"), Mapping) else {}
    if not filters:
        return None
    target_concept = _referent_dimension_concept(compact)
    for column, value in filters.items():
        if value in (None, "", [], {}) or isinstance(value, (list, tuple, set, dict)):
            continue
        dimension = str(column)
        concept = _dimension_concept_from_column(dimension)
        if target_concept and concept and concept != target_concept:
            continue
        if target_concept and not concept:
            continue
        return {
            "artifact_id": f"scope_filter_{_normalize(dimension)}",
            "artifact_type": "referent_filter",
            "source": "current_scope_filter",
            "dimension": dimension,
            "metric": str(scope.get("metric") or ""),
            "aggregation": "sum",
            "filters": dict(filters),
            "values": [value],
            "top_objects": [{"rank": 1, "value": value, "metric_value": None}],
        }
    return None


def _singular_referent_question(compact: str) -> bool:
    singular_tokens = (
        "该城市",
        "这个城市",
        "那个城市",
        "刚才那个城市",
        "该客户",
        "这个客户",
        "那个客户",
        "该产品",
        "这个产品",
        "那个产品",
        "该服务线",
        "这个服务线",
        "那个服务线",
    )
    if any(token in compact for token in singular_tokens):
        return True
    if any(token in compact for token in ("这些", "这几个", "上述", "上面几个", "前几个", "前3", "前三", "top")):
        return False
    return False


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
        "join_keys": [dict(item) for item in artifact.get("join_keys") or [] if isinstance(item, Mapping)],
        "aggregation": artifact.get("aggregation") or "sum",
        "limit": _positive_int(artifact.get("limit")),
        "derived_metric": dict(artifact.get("derived_metric") or {}),
        "derived_metric_name": artifact.get("derived_metric_name"),
        "metric_formula": artifact.get("metric_formula"),
        "numerator_column": artifact.get("numerator_column"),
        "denominator_column": artifact.get("denominator_column"),
        "sort_order": artifact.get("sort_order") or "desc",
        "table": artifact.get("table"),
        "table_selection_reason": artifact.get("table_selection_reason"),
    }
    return {key: value for key, value in keep.items() if value not in (None, "", [], {})}


def _derived_metric_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    derived = payload.get("derived_metric") if isinstance(payload.get("derived_metric"), Mapping) else {}
    name = _first_text(payload.get("derived_metric_name"), derived.get("name"))
    numerator = _first_text(payload.get("numerator_column"), derived.get("numerator"))
    denominator = _first_text(payload.get("denominator_column"), derived.get("denominator"))
    formula = _first_text(payload.get("metric_formula"), derived.get("formula"))
    if not formula and numerator and denominator:
        formula = f"sum({numerator})/sum({denominator})"
    if not (name or numerator or denominator or formula):
        return {}
    normalized = {
        "derived_metric_name": name,
        "metric_formula": formula,
        "numerator_column": numerator,
        "denominator_column": denominator,
        "derived_metric": {
            key: value
            for key, value in {
                "name": name,
                "numerator": numerator,
                "denominator": denominator,
                "formula": formula,
            }.items()
            if value not in (None, "")
        },
    }
    return {key: value for key, value in normalized.items() if value not in (None, "", {})}


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


def _join_keys(logic: Mapping[str, Any], params: Mapping[str, Any]) -> list[dict[str, str]]:
    raw = logic.get("join_keys") or params.get("join_keys")
    normalized = _normalize_join_keys(raw)
    if normalized:
        return normalized
    join_plan = logic.get("join_plan") or params.get("join_plan") or {}
    if not isinstance(join_plan, Mapping):
        return []
    left_table = _first_text(join_plan.get("left_table"), join_plan.get("from_table"))
    right_table = _first_text(join_plan.get("right_table"), join_plan.get("to_table"))
    left_column = _first_text(join_plan.get("left_column"), join_plan.get("left_key"), join_plan.get("from_key"))
    right_column = _first_text(join_plan.get("right_column"), join_plan.get("right_key"), join_plan.get("to_key"))
    if not left_column or not right_column:
        return []
    return [
        {
            "left_table": left_table,
            "left_column": left_column,
            "right_table": right_table,
            "right_column": right_column,
        }
    ]


def _normalize_join_keys(raw: Any) -> list[dict[str, str]]:
    if isinstance(raw, Mapping):
        items = [raw]
    elif isinstance(raw, list):
        items = [item for item in raw if isinstance(item, Mapping)]
    else:
        return []
    normalized: list[dict[str, str]] = []
    for item in items:
        left_column = _first_text(item.get("left_column"), item.get("left_key"), item.get("from_key"))
        right_column = _first_text(item.get("right_column"), item.get("right_key"), item.get("to_key"))
        if not left_column or not right_column:
            continue
        normalized.append(
            {
                "left_table": _first_text(item.get("left_table"), item.get("from_table")),
                "left_column": left_column,
                "right_table": _first_text(item.get("right_table"), item.get("to_table")),
                "right_column": right_column,
            }
        )
    return normalized


def _looks_like_referent_question(compact: str) -> bool:
    if any(
        token in compact
        for token in (
            "这些Top对象",
            "这些top对象",
            "这些TOP对象",
            "Top对象",
            "top对象",
            "TOP对象",
            "Top结果",
            "top结果",
            "TOP结果",
            "Top项",
            "top项",
            "TOP项",
            "Top集合",
            "top集合",
            "TOP集合",
            "Top城市",
            "top城市",
            "这些城市",
            "上述城市",
            "这些",
            "上述",
            "它们",
            "前几个",
            "相邻时间段",
            "相关对象",
            "同一指标",
        )
    ):
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


def _rank_index_applies_to_artifact(compact: str, dimension: str) -> bool:
    concept = _dimension_concept_from_column(dimension)
    if not concept:
        return True
    labels = {
        "city": ("城市", "地区", "区域"),
        "product": ("产品", "商品", "sku", "SKU"),
        "customer": ("客户", "顾客"),
    }.get(concept, ())
    rank_patterns = (
        "排名第一",
        "排名第1",
        "第一名",
        "第1名",
        "Top1",
        "top1",
        "首位",
        "最高的",
        "最多的",
    )
    if any(f"{pattern}的{label}" in compact or f"{pattern}{label}" in compact for pattern in rank_patterns for label in labels):
        return True
    if any(f"{label}排名第一" in compact or f"{label}排名第1" in compact for label in labels):
        return True
    child_question = re.search(r"(?:哪个|哪些|哪几个|哪类|哪种)(城市|地区|区域|产品|商品|客户|顾客)", compact)
    if child_question:
        asked_concept = _referent_dimension_concept(child_question.group(1))
        if asked_concept and asked_concept != concept:
            return False
    return not re.search(r"(?:哪个|哪些|哪几个|哪类|哪种).{0,12}(?:排名第一|排名第1|第一名|第1名|Top1|top1|最高|最多)", compact)


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


def _dimension_concept_from_column(dimension: str) -> str:
    normalized = _normalize(dimension)
    if any(alias in normalized for alias in ("city", "城市", "region", "area", "地区", "区域")):
        return "city"
    if any(alias in normalized for alias in ("product", "sku", "item", "goods", "产品", "商品")):
        return "product"
    if any(alias in normalized for alias in ("customer", "cust", "client", "buyer", "客户", "顾客")):
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
        metric_value = row.get(metric) if metric else None
        if metric_value is None:
            metric_value = _first_non_dimension_value(row=row, dimension=dimension)
        normalized["metric_value"] = metric_value
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
        **_derived_metric_metadata(task_contract),
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
