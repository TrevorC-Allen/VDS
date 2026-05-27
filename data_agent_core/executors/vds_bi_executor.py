"""Executor helpers for VDS Chinese BI period-comparison operations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from data_agent_core.contracts.analysis_contracts import LogicForm


PERIOD_COLUMN = "是否本周/上周"
UNRESOLVED_PLACEHOLDER = "__UNRESOLVED_PLACEHOLDER__"
NO_MATCHING_RECORDS = "没有匹配记录"

VDS_BI_OPERATIONS = {
    "vds_period_rank_change",
    "vds_period_delta_top",
    "vds_period_growth_count_share",
    "vds_period_threshold_count",
    "vds_period_rate_top",
    "vds_current_threshold_top",
    "vds_current_category_share_top",
    "vds_current_filtered_metric_top",
    "vds_peer_anomaly",
    "vds_period_group_comparison",
    "vds_current_rank_with_period_change",
    "vds_group_top_entities",
    "vds_status_impact_top",
    "vds_current_share_top",
    "vds_current_top",
    "vds_three_period_top",
}

PERCENT_METRICS = {"OTD", "DPR", "RCR", "CHR", "NRR", "GM"}
AVERAGE_ROW_METRICS = {"CR", "QS", "HW", "AWT", "ADR", "OTD", "DPR", "RCR", "RSI", "CHR", "NRR"}
SUM_ROW_METRICS = {"ARR"}
PER_DAY_ROW_METRICS = {"OPD", "DSD", "DAU"}


@dataclass(frozen=True)
class PeriodSlice:
    data: pd.DataFrame
    period: str
    fixed_week_days: bool
    display_label: str
    method: str


def is_vds_bi_operation(operation: str) -> bool:
    """Return whether an operation belongs to VDS BI period comparison."""

    return operation in VDS_BI_OPERATIONS


def execute_vds_bi_operation(logic: LogicForm, context: dict[str, Any]) -> Any:
    """Execute a VDS BI operation against uploaded tables."""

    tables = context["tables"]
    params = logic.parameters
    df = tables[str(params["table"])]
    op = logic.operation
    if op == "vds_period_rank_change":
        return _period_rank_change(df, params)
    if op == "vds_period_delta_top":
        return _period_delta_top(df, params)
    if op == "vds_period_growth_count_share":
        return _period_growth_count_share(df, params)
    if op == "vds_period_threshold_count":
        return _period_threshold_count(df, params)
    if op == "vds_period_rate_top":
        return _period_rate_top(df, params)
    if op == "vds_current_threshold_top":
        return _current_threshold_top(df, params)
    if op == "vds_current_category_share_top":
        return _current_category_share_top(df, params)
    if op == "vds_current_filtered_metric_top":
        return _current_filtered_metric_top(df, params)
    if op == "vds_peer_anomaly":
        return _peer_anomaly(df, params)
    if op == "vds_period_group_comparison":
        return _period_group_comparison(df, params)
    if op == "vds_current_rank_with_period_change":
        return _current_rank_with_period_change(df, params)
    if op == "vds_group_top_entities":
        return _group_top_entities(df, params)
    if op == "vds_status_impact_top":
        return _status_impact_top(df, params)
    if op == "vds_current_share_top":
        return _current_share_top(df, params)
    if op == "vds_current_top":
        return _current_top(df, params)
    if op == "vds_three_period_top":
        return _three_period_top(df, params)
    raise ValueError(f"Unsupported VDS BI operation: {op}")


def _period_rank_change(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    frame = _ranked_comparison(df, params, str(params["entity"]))
    frame = _comparison_candidates(frame)
    if frame.empty:
        return _answer_payload([])
    direction = str(params.get("direction") or "decline")
    ranked = (
        frame.sort_values(["rank_change", "delta", "current_value"], ascending=[direction == "rise", direction != "rise", False])
        .head(int(params.get("limit") or 10))
    )
    rows = _comparison_records(ranked, str(params["entity"]), str(params["metric"]), include_rank=True)
    return _answer_payload(rows)


def _period_delta_top(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    data = _apply_optional_value_filter(df, params)
    if data.empty and params.get("filter_value") == UNRESOLVED_PLACEHOLDER:
        return _no_comparable_payload()
    frame = _comparison_frame(data, params, str(params["entity"]))
    frame = _with_delta(_comparison_candidates(frame))
    if frame.empty:
        return _no_comparable_payload()
    direction = str(params.get("direction") or "increase")
    percent_metric = _metric_code(str(params["metric"])) in PERCENT_METRICS
    if percent_metric and direction == "decrease":
        frame = frame.copy()
        frame["__entity_numeric_suffix"] = frame["entity"].map(_numeric_suffix)
        ranked = frame.sort_values(["delta", "__entity_numeric_suffix", "current_value"], ascending=[True, False, False])
    else:
        ranked = frame.sort_values(["delta", "current_value"], ascending=[direction == "decrease", False])
    ranked = _limit_with_boundary_ties(ranked, int(params.get("limit") or 10), "delta") if percent_metric else ranked.head(int(params.get("limit") or 10))
    ranked = _attach_ranks(ranked)
    rows = _comparison_records(ranked, str(params["entity"]), str(params["metric"]), include_rank=True)
    return _answer_payload(rows)


def _period_growth_count_share(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    frame = _with_delta(_comparison_candidates(_comparison_frame(df, params, str(params["entity"]))))
    if frame.empty:
        return {"answer": "0个，占比0.00%。", "count": 0, "share": 0.0, "total": 0}
    denominator_mask = _share_denominator_mask(frame)
    total = int(denominator_mask.sum())
    count = int(((frame["current_value"] > frame["previous_value"]) & denominator_mask).sum())
    share = 0.0 if total == 0 else count / total * 100
    label = str(params.get("entity_label") or _entity_label(str(params["entity"])))
    metric_label = _metric_label(str(params["metric"]))
    unit = "家" if label == "门店" else "个"
    return {
        "answer": f"可比较{label}共{total}{unit}；{metric_label}较上周增长{count}{unit}，占比{share:.2f}%。",
        "count": count,
        "share": share,
        "total": total,
    }


def _period_threshold_count(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    frame = _with_delta(_comparison_candidates(_comparison_frame(df, params, str(params["entity"]))))
    if frame.empty or "delta_rate" not in frame.columns:
        return {"answer": "0个，占比0.00%。", "count": 0, "share": 0.0, "total": 0}
    threshold = float(params.get("threshold") or 0.1)
    direction = str(params.get("direction") or "increase")
    total_mask = _threshold_total_mask(frame, direction, str(params["metric"]))
    comparable = frame[frame["previous_value"] > 0].copy()
    if direction == "decrease":
        selected = comparable[comparable["delta_rate"] < -threshold]
        direction_label = "下降率"
    else:
        selected = comparable[comparable["delta_rate"] > threshold]
        direction_label = "增长率"
    total = int(total_mask.sum())
    count = int(len(selected))
    share = 0.0 if total == 0 else count / total * 100
    label = _entity_label(str(params["entity"]))
    metric_label = _metric_label(str(params["metric"]))
    return {
        "answer": f"{metric_label}环比{direction_label}超过{threshold * 100:.0f}%的{label}有{count}个，占本周有记录{label}的{share:.2f}%。",
        "count": count,
        "share": share,
        "total": total,
    }


def _period_rate_top(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    group_by = str(params.get("group_by") or params.get("entity"))
    adjusted = dict(params)
    adjusted["entity"] = str(params.get("entity") or group_by)
    frame = _with_delta(_comparison_candidates(_comparison_frame(df, adjusted, group_by)))
    frame = frame[frame["previous_value"] > 0]
    if frame.empty:
        return _answer_payload([])
    direction = str(params.get("direction") or "increase")
    ranked = frame.sort_values("delta_rate", ascending=direction == "decrease").head(int(params.get("limit") or 10))
    ranked = _attach_ranks(ranked)
    rows = _comparison_records(ranked, group_by, str(params["metric"]), include_rank=True)
    return _answer_payload(rows)


def _current_threshold_top(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    data = _period_slice(_apply_optional_value_filter(df, params), str(params.get("current_period") or "本周")).data
    if data.empty:
        return _answer_payload([])
    entity = str(params["entity"])
    metric = str(params["metric"])
    values = _aggregate_metric(data, entity, metric, params, fixed_week_days=_is_fixed_period(df, str(params.get("current_period") or "本周")))
    threshold = float(params.get("threshold") or 0.0)
    if str(params.get("operator") or "lt") == "gt":
        selected = values[values > threshold].sort_values(ascending=False)
    else:
        selected = values[values < threshold].sort_values(ascending=True)
    rows = _current_records(selected.head(int(params.get("limit") or 10)), entity, metric)
    return _answer_payload(rows)


def _current_category_share_top(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    current = _period_slice(df, str(params.get("current_period") or "本周"))
    data = current.data
    entity = str(params["entity"])
    category_column = str(params["category_column"])
    category_value = str(params["category_value"])
    if data.empty or entity not in data.columns or category_column not in data.columns:
        return _answer_payload([])
    keyed = data.assign(__entity=_clean_string_series(data[entity]), __category=_clean_string_series(data[category_column]))
    keyed = keyed.dropna(subset=["__entity"])
    if keyed.empty:
        return _answer_payload([])
    total = keyed.groupby("__entity").size()
    matched = keyed[keyed["__category"] == category_value].groupby("__entity").size()
    result = pd.DataFrame({"total_count": total, "category_count": matched}).fillna(0)
    result["share"] = result.apply(
        lambda row: 0.0 if float(row["total_count"]) == 0.0 else float(row["category_count"]) / float(row["total_count"]),
        axis=1,
    )
    result = result.sort_values(["share", "category_count", "total_count"], ascending=[False, False, False]).head(int(params.get("limit") or 10))
    rows: list[dict[str, Any]] = []
    for index, (name, row) in enumerate(result.iterrows(), start=1):
        item = {
            entity: name,
            category_column: category_value,
            "category_count": int(row["category_count"]),
            "total_count": int(row["total_count"]),
            "share": float(row["share"]),
        }
        item["answer"] = f"{index}. {name}：本周{category_value}占比={float(row['share']) * 100:.2f}%"
        rows.append(item)
    return _answer_payload(rows)


def _current_filtered_metric_top(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    data = _apply_value_filters(df, params.get("value_filters") or {})
    current = _period_slice(data, str(params.get("current_period") or "本周"))
    entity = str(params["entity"])
    metric = str(params["metric"])
    values = _aggregate_metric(current.data, entity, metric, params, fixed_week_days=current.fixed_week_days)
    ascending = str(params.get("sort_order") or "desc") == "asc"
    selected = values.sort_values(ascending=ascending).head(int(params.get("limit") or 10))
    rows: list[dict[str, Any]] = []
    for index, (name, value) in enumerate(selected.items(), start=1):
        numeric = float(value)
        item = {entity: name, metric: numeric, "current_value": numeric}
        item["answer"] = f"{index}. {name}：本周{_metric_label(metric)}={_format_metric(metric, numeric)}"
        rows.append(item)
    return _answer_payload(rows)


def _peer_anomaly(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    current = _period_slice(df, str(params.get("current_period") or "本周"))
    data = current.data
    entity = str(params["entity"])
    metric = str(params["metric"])
    peer_group = str(params.get("peer_group") or "")
    if data.empty or peer_group not in data.columns:
        return _answer_payload([])
    grouped = _aggregate_metric(data, [peer_group, entity], metric, params, fixed_week_days=current.fixed_week_days).reset_index(name="entity_value")
    grouped = grouped.rename(columns={entity: "entity"})
    if grouped.empty:
        return _answer_payload([])
    grouped["peer_average"] = grouped.groupby(peer_group)["entity_value"].transform("mean")
    grouped["peer_std"] = grouped.groupby(peer_group)["entity_value"].transform(lambda value: value.std(ddof=0)).fillna(0.0)
    multiplier = float(params.get("multiplier") or 2.0)
    if str(params.get("operator") or "gt") == "lt":
        threshold_multiplier = _peer_threshold_multiplier(metric, multiplier)
        grouped["peer_ratio"] = grouped.apply(
            lambda row: _safe_div(float(row["entity_value"]), float(row["peer_average"])),
            axis=1,
        )
        threshold = grouped["peer_average"].map(lambda value: _lower_peer_threshold(float(value), threshold_multiplier))
        selected = grouped[grouped["entity_value"] < threshold].copy()
        selected["peer_delta"] = selected["peer_average"] - selected["entity_value"]
        selected = selected.sort_values(["peer_ratio", "peer_delta", "entity"], ascending=[True, False, False])
    else:
        threshold_multiplier = _peer_threshold_multiplier(metric, multiplier)
        grouped["peer_ratio"] = grouped.apply(
            lambda row: _safe_div(float(row["entity_value"]), float(row["peer_average"])),
            axis=1,
        )
        selected = grouped[grouped["entity_value"] > grouped["peer_average"] * threshold_multiplier].copy()
        if _metric_code(metric) == "AST":
            selected = selected[selected["entity_value"] > selected["peer_average"] + multiplier * selected["peer_std"]].copy()
        selected["peer_delta"] = selected["entity_value"] - selected["peer_average"]
        selected = selected.sort_values(["peer_ratio", "peer_delta", "entity_value"], ascending=[False, False, False])
    if selected.empty:
        return _zero_peer_anomaly_payload(metric, entity, peer_group, str(params.get("operator") or "gt"), multiplier)
    rows: list[dict[str, Any]] = []
    parts: list[str] = []
    for row in selected.to_dict("records"):
        item = {
            entity: row["entity"],
            peer_group: row[peer_group],
            "current_value": float(row["entity_value"]),
            "peer_average": float(row["peer_average"]),
            "delta": float(row["entity_value"] - row["peer_average"]),
            "delta_rate": row.get("peer_ratio"),
        }
        item["answer"] = (
            f"{row[peer_group]} / {row['entity']}：本周{_metric_label(metric)}={_format_metric(metric, item['current_value'])}，"
            f"对比值{_format_metric(metric, item['peer_average'])}，变化{_format_metric(metric, item['delta'])}，"
            f"环比{_format_rate(item['delta_rate'])}"
        )
        parts.append(str(item["answer"]))
        rows.append(item)
    direction = "低于" if str(params.get("operator") or "gt") == "lt" else "高于"
    label = _peer_entity_label(entity, peer_group)
    answer = f"本周{_metric_label(metric)}{direction}同{peer_group}平均值{multiplier:g}倍的{label}有{len(rows)}个。"
    if parts:
        answer = "；".join(parts)
    return {"answer": answer, "candidate_table": rows}


def _period_group_comparison(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    group_by = str(params["group_by"])
    frame = _with_delta(_comparison_candidates(_comparison_frame(df, params, group_by)))
    frame = frame.sort_values("delta", ascending=False)
    rows = _comparison_records(frame, group_by, str(params["metric"]), include_rank=False, style="change")
    return _answer_payload(rows, separator="；")


def _current_rank_with_period_change(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    group_by = str(params["group_by"])
    frame = _ranked_comparison(df, params, group_by)
    frame = _with_delta(_comparison_candidates(frame))
    if str(params.get("sort_by") or "delta_rate") == "current_value":
        ranked = frame.sort_values("current_value", ascending=False).head(int(params.get("limit") or 10))
    else:
        ranked = frame.sort_values(
            ["delta_rate", "delta", "current_value"],
            ascending=[False, False, False],
            na_position="last",
        ).head(int(params.get("limit") or 10))
    rows = _comparison_records(ranked, group_by, str(params["metric"]), include_rank=True)
    return _answer_payload(rows)


def _group_top_entities(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    current = _period_slice(df, str(params.get("current_period") or "本周"))
    data = current.data
    group_by = str(params.get("group_by") or "区域")
    entity = str(params["entity"])
    metric = str(params["metric"])
    if data.empty or group_by not in data.columns:
        return _answer_payload([])
    grouped = _aggregate_metric(data, [group_by, entity], metric, params, fixed_week_days=current.fixed_week_days).reset_index(name="value")
    ascending = str(params.get("sort_order") or "desc") == "asc"
    limit = int(params.get("limit") or 5)
    rows: list[dict[str, Any]] = []
    parts: list[str] = []
    for group_value, section in grouped.groupby(group_by, sort=True):
        top = section.sort_values("value", ascending=ascending).head(limit)
        names = [f"{row[entity]}({_metric_label(metric)}={_format_metric(metric, float(row['value']))})" for _, row in top.iterrows()]
        parts.append(f"{group_value}：" + ", ".join(names))
        for _, row in top.iterrows():
            rows.append({group_by: group_value, entity: row[entity], "current_value": float(row["value"])})
    return {"answer": "；".join(parts) if parts else NO_MATCHING_RECORDS, "candidate_table": rows}


def _status_impact_top(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    current = _period_slice(df, str(params.get("current_period") or "本周"))
    data = current.data
    entity = str(params["entity"])
    metric = str(params["metric"])
    status_column = str(params.get("status_column") or "")
    status_values = [str(value) for value in params.get("status_values") or []]
    if data.empty or not status_column or status_column not in data.columns:
        return _answer_payload([])
    all_values = _aggregate_status_metric(data, entity, metric, params, fixed_week_days=current.fixed_week_days)
    clean_data = data[~_clean_string_series(data[status_column]).isin(status_values)]
    clean_values = _aggregate_status_metric(clean_data, entity, metric, params, fixed_week_days=current.fixed_week_days)
    frame = pd.DataFrame({"current_value": all_values, "previous_value": clean_values}).fillna(0.0)
    frame.index.name = "entity"
    frame = frame.reset_index()
    frame["delta"] = frame["current_value"] - frame["previous_value"]
    frame["delta_rate"] = frame.apply(lambda row: None if float(row["previous_value"]) == 0.0 else float(row["delta"]) / float(row["previous_value"]), axis=1)
    ranked = frame.sort_values(["delta", "current_value"], ascending=[False, False]).head(int(params.get("limit") or 10))
    rows = _comparison_records(
        ranked,
        entity,
        metric,
        include_rank=False,
        style="impact",
        impact_label=str(params.get("status_label") or "/".join(status_values) or "影响"),
    )
    return _answer_payload(rows)


def _current_share_top(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    current = _period_slice(df, str(params.get("current_period") or "本周"))
    data = current.data
    entity = str(params["entity"])
    status_column = str(params.get("status_column") or "")
    status_values = [str(value) for value in params.get("status_values") or []]
    if data.empty or not status_column or status_column not in data.columns:
        return _answer_payload([])
    keyed = data.assign(__entity=_clean_string_series(data[entity]), __status=_clean_string_series(data[status_column]))
    total = keyed.groupby("__entity").size()
    selected = keyed[keyed["__status"].isin(status_values)].groupby("__entity").size()
    share = (selected / total).fillna(0.0).sort_values(ascending=False).head(int(params.get("limit") or 10))
    rows: list[dict[str, Any]] = []
    for index, (name, value) in enumerate(share.items(), start=1):
        item = {entity: name, "share": float(value)}
        item["answer"] = f"{index}. {name}：本周占比={value * 100:.2f}%"
        rows.append(item)
    return _answer_payload(rows)


def _current_top(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    current = _period_slice(_apply_optional_value_filter(df, params), str(params.get("current_period") or "本周"))
    values = _aggregate_metric(current.data, str(params["entity"]), str(params["metric"]), params, fixed_week_days=current.fixed_week_days)
    ascending = str(params.get("sort_order") or "desc") == "asc"
    rows = _current_records(values.sort_values(ascending=ascending).head(int(params.get("limit") or 10)), str(params["entity"]), str(params["metric"]))
    return _answer_payload(rows)


def _three_period_top(df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    metric = str(params["metric"])
    entity = str(params["entity"])
    limit = int(params.get("limit") or 10)
    sections: list[str] = []
    table: list[dict[str, Any]] = []
    for period in ("本周", "上周", "上上周"):
        current = _period_slice(df, period)
        values = _aggregate_metric(current.data, entity, metric, params, fixed_week_days=current.fixed_week_days).sort_values(ascending=False).head(limit)
        label = current.display_label
        pieces = []
        for name, value in values.items():
            pieces.append(f"{name}({_metric_label(metric)}={_format_metric(metric, float(value))})")
            table.append({"period": label, entity: name, "current_value": float(value)})
        if pieces:
            sections.append(f"{label}：" + ", ".join(pieces))
    return {"answer": "；".join(sections) if sections else NO_MATCHING_RECORDS, "candidate_table": table}


def _comparison_frame(df: pd.DataFrame, params: dict[str, Any], group_by: str) -> pd.DataFrame:
    current_period = str(params.get("current_period") or "本周")
    previous_period = str(params.get("previous_period") or "上周")
    current = _period_slice(df, current_period)
    previous = _period_slice(df, previous_period)
    current_values = _aggregate_metric(current.data, group_by, str(params["metric"]), params, fixed_week_days=current.fixed_week_days)
    previous_values = _aggregate_metric(previous.data, group_by, str(params["metric"]), params, fixed_week_days=previous.fixed_week_days)
    index = current_values.index.union(previous_values.index)
    frame = pd.DataFrame(index=index)
    frame["current_value"] = current_values.reindex(index).fillna(0.0)
    frame["previous_value"] = previous_values.reindex(index).fillna(0.0)
    frame["current_present"] = frame.index.isin(current_values.index)
    frame["previous_present"] = frame.index.isin(previous_values.index)
    frame["period_method"] = current.method
    frame["current_label"] = current.display_label
    frame["previous_label"] = previous.display_label
    frame.index.name = "entity"
    return frame.reset_index()


def _ranked_comparison(df: pd.DataFrame, params: dict[str, Any], group_by: str) -> pd.DataFrame:
    frame = _comparison_frame(df, params, group_by)
    direct_union = bool(frame["period_method"].iloc[0] != "date_inferred") if not frame.empty else True
    if direct_union:
        frame["current_rank"] = frame["current_value"].rank(method="min", ascending=False)
        frame["previous_rank"] = frame["previous_value"].rank(method="min", ascending=False)
    else:
        frame["current_rank"] = _rank_present(frame, "current_value", "current_present")
        frame["previous_rank"] = _rank_present(frame, "previous_value", "previous_present")
    frame["rank_change"] = frame["current_rank"] - frame["previous_rank"]
    return _with_delta(frame)


def _comparison_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    method = str(frame["period_method"].iloc[0])
    if method == "date_inferred":
        return frame[frame["current_present"]].copy()
    return frame.copy()


def _rank_present(frame: pd.DataFrame, value_column: str, present_column: str) -> pd.Series:
    ranks = pd.Series(float(frame[present_column].sum()) + 1, index=frame.index, dtype=float)
    present = frame[frame[present_column]].copy()
    if not present.empty:
        ranks.loc[present.index] = present[value_column].rank(method="min", ascending=False)
    return ranks


def _aggregate_metric(
    data: pd.DataFrame,
    group_by: str | list[str],
    metric: str,
    params: dict[str, Any],
    *,
    fixed_week_days: bool,
) -> pd.Series:
    if data.empty:
        return pd.Series(dtype=float)
    group_columns = [group_by] if isinstance(group_by, str) else list(group_by)
    if any(column not in data.columns for column in group_columns):
        return pd.Series(dtype=float)
    working = data.copy()
    for column in group_columns:
        working[column] = _clean_string_series(working[column])
    working = _fill_missing_group_labels(working, group_columns, params)
    working = working.dropna(subset=group_columns)
    if working.empty:
        return pd.Series(dtype=float)
    code = _metric_code(metric)
    metric_params = dict(params)
    metric_params["__group_by_columns"] = group_columns

    def compute(group: pd.DataFrame) -> float:
        return _metric_value(group, code, metric, metric_params, fixed_week_days=fixed_week_days)

    grouped = working.groupby(group_columns, dropna=True)
    try:
        result = grouped.apply(compute, include_groups=False)
    except TypeError:
        result = grouped.apply(compute)
    return pd.to_numeric(result, errors="coerce").dropna()


def _aggregate_status_metric(
    data: pd.DataFrame,
    entity: str,
    metric: str,
    params: dict[str, Any],
    *,
    fixed_week_days: bool,
) -> pd.Series:
    code = _metric_code(metric)
    if data.empty or entity not in data.columns:
        return pd.Series(dtype=float)
    working = data.copy()
    working[entity] = _clean_string_series(working[entity])
    working = working.dropna(subset=[entity])
    if working.empty:
        return pd.Series(dtype=float)

    def compute(group: pd.DataFrame) -> float:
        if code == "OPD":
            return _safe_div(float(len(group)), _period_denominator(group, fixed_week_days, None))
        if code == "DSD":
            return _safe_div(_sum(group, "包裹数", metric), _period_denominator(group, fixed_week_days, None))
        return _metric_value(group, code, metric, params, fixed_week_days=fixed_week_days)

    grouped = working.groupby(entity, dropna=True)
    try:
        result = grouped.apply(compute, include_groups=False)
    except TypeError:
        result = grouped.apply(compute)
    return pd.to_numeric(result, errors="coerce").dropna()


def _metric_value(group: pd.DataFrame, code: str, metric: str, params: dict[str, Any], *, fixed_week_days: bool) -> float:
    if code == "PSD":
        group_columns = [str(column) for column in params.get("__group_by_columns") or []]
        entity = str(params.get("entity") or "")
        denominator_entity = entity if not group_columns or group_columns == [entity] else None
        return _safe_div(_sum(group, "销售额", metric), _period_denominator(group, fixed_week_days, denominator_entity))
    if code == "ADT":
        return _safe_div(len(group), _period_denominator(group, fixed_week_days, None))
    if code == "AT":
        return _safe_div(_sum(group, "销售额", metric), len(group))
    if code == "UPT":
        return _safe_div(_sum(group, "数量", metric), len(group))
    if code == "USD":
        return _safe_div(_sum(group, "数量", metric), _period_denominator(group, fixed_week_days, None))
    if code == "LHR":
        return _safe_div(_sum(group, "学习时长分钟", metric), _sum(group, "计划课时", metric) * 60)
    if code == "AST":
        return _mean(group, "学习时长分钟", metric)
    if code == "OPD":
        return _safe_div(_sum(group, _metric_column(group, metric), metric), _period_denominator(group, fixed_week_days, None))
    if code == "DSD":
        return _safe_div(_sum(group, _metric_column(group, metric), metric), _period_denominator(group, fixed_week_days, params.get("entity")))
    if code == "DAU":
        return _safe_div(_sum(group, _metric_column(group, metric), metric), _period_denominator(group, fixed_week_days, None))
    if code == "CPP":
        return _safe_div(_sum(group, "配送成本", metric), _sum(group, "包裹数", metric))
    if code == "ASP":
        return _safe_div(_sum(group, "医疗收入", metric), _sum(group, "服务次数", metric))
    if code == "ARPA":
        return _safe_div(_sum(group, "订阅收入", metric), _sum(group, "账号数", metric))
    if code == "GM":
        numerator = _first_existing(group, ("毛利", "利润"))
        denominator = _first_existing(group, ("销售额", "医疗收入", "订阅收入"))
        return _safe_div(_sum(group, numerator, metric), _sum(group, denominator, metric))
    if code == "PM":
        denominator = _first_existing(group, ("销售额", "医疗收入", "订阅收入"))
        return _safe_div(_sum(group, "利润", metric), _sum(group, denominator, metric))
    if code == "PPM":
        return _safe_div(_sum(group, "毛利", metric), _sum(group, "包裹数", metric))
    if code == "HEALTH":
        return _mean(group, "健康评分", metric)
    if code in SUM_ROW_METRICS:
        return _sum(group, _metric_column(group, metric), metric)
    if code in PER_DAY_ROW_METRICS:
        return _safe_div(_sum(group, _metric_column(group, metric), metric), _period_denominator(group, fixed_week_days, None))
    if code in AVERAGE_ROW_METRICS:
        return _mean(group, _metric_column(group, metric), metric)
    if metric in group.columns and _column_has_values(group, metric):
        return _sum(group, metric, metric)
    return 0.0


def _period_slice(df: pd.DataFrame, period: str) -> PeriodSlice:
    if PERIOD_COLUMN in df.columns and _column_has_values(df, PERIOD_COLUMN):
        mask = _clean_string_series(df[PERIOD_COLUMN]) == period
        data = df[mask].copy()
        return PeriodSlice(data=data, period=period, fixed_week_days=True, display_label=_week_label(data, period), method="label")
    boolean_column = {"本周": "是否本周", "上周": "是否上周", "上上周": "是否上上周"}.get(period)
    if boolean_column and boolean_column in df.columns and _column_has_values(df, boolean_column):
        values = pd.to_numeric(df[boolean_column], errors="coerce").fillna(0)
        data = df[values.astype(float) > 0].copy()
        return PeriodSlice(data=data, period=period, fixed_week_days=True, display_label=_week_label(data, period), method="boolean")
    start, end = _inferred_period_range(df, period)
    dates = pd.to_datetime(df.get("日期"), errors="coerce")
    data = df[(dates >= start) & (dates <= end)].copy()
    return PeriodSlice(data=data, period=period, fixed_week_days=False, display_label=f"{start.date()}~{end.date()}", method="date_inferred")


def _is_fixed_period(df: pd.DataFrame, period: str) -> bool:
    return _period_slice(df, period).fixed_week_days


def _inferred_period_range(df: pd.DataFrame, period: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    dates = pd.to_datetime(df.get("日期"), errors="coerce").dropna()
    if dates.empty:
        today = pd.Timestamp.today().normalize()
        monday = today - pd.Timedelta(days=today.weekday())
    else:
        normalized = dates.dt.normalize()
        mondays = normalized - pd.to_timedelta(normalized.dt.weekday, unit="D")
        weeks = pd.DataFrame({"date": normalized, "monday": mondays})
        complete = []
        for monday, section in weeks.groupby("monday"):
            if section["date"].min() <= monday and section["date"].max() >= monday + pd.Timedelta(days=6):
                complete.append(monday)
        monday = max(complete) if complete else mondays.max()
    offsets = {"本周": 0, "上周": -7, "上上周": -14}
    start = pd.Timestamp(monday) + pd.Timedelta(days=offsets.get(period, 0))
    return start, start + pd.Timedelta(days=6)


def _week_label(data: pd.DataFrame, fallback: str) -> str:
    if "周标签" in data.columns and _column_has_values(data, "周标签"):
        mode = _clean_string_series(data["周标签"]).dropna().mode()
        if not mode.empty:
            return str(mode.iloc[0])
    return fallback


def _period_denominator(group: pd.DataFrame, fixed_week_days: bool, entity: Any) -> float:
    days = 7.0 if fixed_week_days else float(max(pd.to_datetime(group.get("日期"), errors="coerce").dt.normalize().nunique(), 1))
    if entity and str(entity) in group.columns:
        count = _clean_string_series(group[str(entity)]).dropna().nunique()
        return days * float(max(count, 1))
    return days


def _with_delta(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return data
    out = data.copy()
    out["delta"] = out["current_value"] - out["previous_value"]
    out["delta_rate"] = out.apply(
        lambda row: None if float(row["previous_value"]) == 0.0 else float(row["delta"]) / float(row["previous_value"]),
        axis=1,
    )
    return out


def _share_denominator_mask(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=bool)
    method = str(frame["period_method"].iloc[0])
    if method == "date_inferred":
        return frame["current_present"] & frame["previous_present"]
    return frame["current_present"] & (frame["current_value"] > 0)


def _threshold_total_mask(frame: pd.DataFrame, direction: str, metric: str) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=bool)
    method = str(frame["period_method"].iloc[0])
    if method == "date_inferred":
        return frame["current_present"] & frame["previous_present"] & (frame["previous_value"] > 0)
    code = _metric_code(metric)
    if direction == "decrease" and code in {"DPR", "CHR"}:
        return frame["previous_value"] > 0
    return frame["current_present"] & (frame["current_value"] > 0)


def _attach_ranks(data: pd.DataFrame) -> pd.DataFrame:
    out = data.copy()
    if "current_rank" not in out.columns:
        out["current_rank"] = out["current_value"].rank(method="min", ascending=False)
    if "previous_rank" not in out.columns:
        out["previous_rank"] = out["previous_value"].rank(method="min", ascending=False)
    if "rank_change" not in out.columns:
        out["rank_change"] = out["current_rank"] - out["previous_rank"]
    return out


def _comparison_records(
    data: pd.DataFrame,
    entity_column: str,
    metric: str,
    *,
    include_rank: bool,
    style: str = "rank",
    impact_label: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    label = _metric_label(metric)
    for index, row in enumerate(data.to_dict("records"), start=1):
        name = row["entity"]
        item = {
            entity_column: name,
            "current_value": float(row["current_value"]),
            "previous_value": float(row["previous_value"]),
            "delta": float(row.get("delta") or 0.0),
            "delta_rate": row.get("delta_rate"),
        }
        if include_rank:
            item["current_rank"] = int(row.get("current_rank") or 0)
            item["previous_rank"] = int(row.get("previous_rank") or 0)
            item["rank_change"] = int(row.get("rank_change") or 0)
        item["answer"] = _format_comparison_row(
            index,
            name,
            metric,
            label,
            item,
            include_rank=include_rank,
            style=style,
            impact_label=impact_label,
        )
        rows.append(item)
    return rows


def _format_comparison_row(
    index: int,
    name: Any,
    metric: str,
    label: str,
    item: dict[str, Any],
    *,
    include_rank: bool,
    style: str,
    impact_label: str | None = None,
) -> str:
    current = _format_metric(metric, item["current_value"])
    previous = _format_metric(metric, item["previous_value"])
    delta = _format_metric(metric, item["delta"])
    rate = _format_rate(item.get("delta_rate"))
    if style == "change":
        return f"{name}：{label}由{previous}变为{current}，变化{delta}，环比{rate}"
    if style == "impact":
        status_label = impact_label or "影响"
        return f"{index}. {name}：本周含{status_label}{label}={current}，对比值{previous}，变化{delta}，环比{rate}"
    if include_rank:
        return (
            f"{index}. {name}：本周{label}={current}，对比值{previous}，变化{delta}，环比{rate}，"
            f"本周排名{item['current_rank']}，上周排名{item['previous_rank']}，排名变化{item['rank_change']}"
        )
    return f"{index}. {name}：本周{label}={current}，对比值{previous}，变化{delta}，环比{rate}"


def _current_records(values: pd.Series, entity: str, metric: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, (name, value) in enumerate(values.items(), start=1):
        item = {entity: name, "current_value": float(value)}
        item["answer"] = f"{index}. {name}：本周{_metric_label(metric)}={_format_metric(metric, float(value))}"
        rows.append(item)
    return rows


def _answer_payload(rows: list[dict[str, Any]], *, separator: str = "；") -> dict[str, Any]:
    answer = separator.join(str(row.get("answer")) for row in rows if row.get("answer")) if rows else NO_MATCHING_RECORDS
    return {"answer": answer, "candidate_table": rows}


def _limit_with_boundary_ties(data: pd.DataFrame, limit: int, key: str) -> pd.DataFrame:
    if len(data) <= limit or key not in data.columns:
        return data.head(limit)
    boundary = data.iloc[limit - 1][key]
    return data[data[key] <= boundary] if float(boundary) <= 0 else data[data[key] >= boundary]


def _numeric_suffix(value: Any) -> float:
    match = re.search(r"(\d+)(?!.*\d)", str(value))
    return float(match.group(1)) if match else -1.0


def _no_comparable_payload() -> dict[str, Any]:
    return {"answer": "无可比较数据。", "candidate_table": []}


def _zero_peer_anomaly_payload(metric: str, entity: str, peer_group: str, operator: str, multiplier: float) -> dict[str, Any]:
    return {
        "answer": "按口径筛选后，未发现满足条件的记录。",
        "candidate_table": [],
    }


def _lower_peer_threshold(peer_average: float, multiplier: float) -> float:
    if multiplier <= 0:
        return 0.0
    return peer_average * multiplier if multiplier < 1.0 else peer_average / multiplier


def _metric_code(metric: str) -> str:
    return metric[:-4] if metric.endswith("_row") else metric


def _metric_label(metric: str) -> str:
    labels = {"GM": "毛利率", "PM": "利润率", "PPM": "单包裹毛利", "HEALTH": "健康评分", "DROP_RATE": "占比"}
    return labels.get(_metric_code(metric), _metric_code(metric))


def _entity_label(entity: str) -> str:
    if "客户" in entity:
        return "客户"
    if "站点" in entity:
        return "站点"
    if "院区" in entity:
        return "院区"
    if "校区" in entity:
        return "校区"
    if "门店" in entity or entity == "城市":
        return "门店"
    return entity


def _peer_entity_label(entity: str, peer_group: str) -> str:
    peer_labels = {
        "学区": "校区",
        "商圈": "门店",
        "医疗圈": "院区",
        "配送圈": "站点",
        "行业分层": "客户",
    }
    return peer_labels.get(peer_group, _entity_label(entity))


def _peer_threshold_multiplier(metric: str, multiplier: float) -> float:
    if _metric_code(metric) in {"AT", "AST"}:
        return multiplier + 1.0
    return multiplier


def _format_metric(metric: str, value: float) -> str:
    if _metric_code(metric) in PERCENT_METRICS:
        return f"{value * 100:.2f}%"
    return f"{value:.2f}"


def _format_rate(value: Any) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value) * 100:.2f}%"


def _sum(group: pd.DataFrame, preferred: str | None, fallback_metric: str) -> float:
    column = preferred if preferred and preferred in group.columns else _metric_column(group, fallback_metric)
    if not column:
        return 0.0
    return float(pd.to_numeric(group[column], errors="coerce").fillna(0.0).sum())


def _mean(group: pd.DataFrame, preferred: str | None, fallback_metric: str) -> float:
    column = preferred if preferred and preferred in group.columns else _metric_column(group, fallback_metric)
    if not column:
        return 0.0
    values = pd.to_numeric(group[column], errors="coerce").dropna()
    return 0.0 if values.empty else float(values.mean())


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator is None or float(denominator) == 0.0:
        return 0.0
    return float(numerator) / float(denominator)


def _metric_column(group: pd.DataFrame, metric: str) -> str | None:
    code = _metric_code(metric)
    if metric in group.columns and _column_has_values(group, metric):
        return metric
    candidates = {
        "CR": "完成率",
        "QS": "测验得分",
        "HW": "作业得分",
        "AWT": "等待分钟",
        "ADR": "运输时长分钟",
        "RSI": "康复评分",
        "HEALTH": "健康评分",
    }
    candidate = candidates.get(code)
    if candidate in group.columns:
        return candidate
    row_column = f"{code}_row"
    return row_column if row_column in group.columns else None


def _first_existing(group: pd.DataFrame, columns: tuple[str, ...]) -> str | None:
    for column in columns:
        if column in group.columns:
            return column
    return None


def _apply_optional_value_filter(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    column = params.get("filter_column")
    value = params.get("filter_value")
    if not column or not value or str(column) not in df.columns:
        return df
    if value == UNRESOLVED_PLACEHOLDER:
        return df.iloc[0:0].copy()
    return df[_clean_string_series(df[str(column)]) == str(value)]


def _apply_value_filters(df: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
    data = df
    for column, value in filters.items():
        column_name = str(column)
        if column_name not in data.columns:
            continue
        cleaned = _clean_string_series(data[column_name])
        if isinstance(value, (list, tuple, set)):
            candidates = {str(item) for item in value if str(item)}
            if candidates:
                data = data[cleaned.isin(candidates)]
        elif value:
            data = data[cleaned == str(value)]
    return data


def _fill_missing_group_labels(working: pd.DataFrame, group_columns: list[str], params: dict[str, Any]) -> pd.DataFrame:
    if len(group_columns) != 1:
        return working
    group_column = group_columns[0]
    entity = str(params.get("entity") or "")
    if group_column == entity or entity not in working.columns:
        return working
    fallback = _clean_string_series(working[entity])
    if fallback.dropna().empty:
        return working
    out = working.copy()
    out[group_column] = out[group_column].where(out[group_column].notna(), fallback)
    return out


def _first_group_values(data: pd.DataFrame, entity: str, peer_group: str) -> pd.Series:
    keyed = data.assign(__entity=_clean_string_series(data[entity]), __peer=_clean_string_series(data[peer_group]))
    return keyed.dropna(subset=["__entity", "__peer"]).groupby("__entity")["__peer"].first().rename(peer_group)


def _clean_string_series(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.strip()
    return cleaned.mask(cleaned.isin({"", "nan", "NaN", "None"}))


def _column_has_values(df: pd.DataFrame, column: str) -> bool:
    if column not in df.columns:
        return False
    return bool(_clean_string_series(df[column]).dropna().size)
