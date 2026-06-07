"""Structured conversation context and follow-up action helpers."""

from __future__ import annotations

import re
from typing import Any, Mapping

from data_agent_core.contracts.analysis_contracts import AnalysisPlan
from data_agent_core.core.capability_registry import capability_for_operation
from data_agent_core.result_artifacts import build_result_artifacts, merge_result_artifacts, resolve_followup_referent


_CONTEXT_PASS_STATUSES = {"passed", "corrected_passed", "passed_with_insufficient_data"}
_NON_FOCUS_OPERATIONS = {"detail_lookup", "filtering"}


def build_analysis_context(
    response: Mapping[str, Any] | None,
    *,
    previous_context: Mapping[str, Any] | None = None,
    original_question: str = "",
) -> dict[str, Any]:
    """Build the persisted analysis state object for a conversation turn."""

    payload = dict(response or {})
    active_payload = _active_payload_for_context(payload)
    logic = _logic_form_dict(active_payload)
    previous = dict(previous_context or {})
    if not logic:
        state_name = "awaiting_clarification" if active_payload.get("answer_type") == "clarification" else "chat_only"
        return {
            "state_version": "v1",
            "state_name": state_name,
            "dataset_id": str(active_payload.get("dataset_id") or previous.get("dataset_id") or ""),
            "run_id": str(active_payload.get("run_id") or ""),
            "question": str(original_question or active_payload.get("question") or ""),
            "previous_run_id": str(previous.get("run_id") or ""),
            "active": state_name == "awaiting_clarification",
            "history_depth": int(previous.get("history_depth") or 0),
            "available_followup_actions": list(previous.get("available_followup_actions") or []),
            "last_result_artifact_id": str(previous.get("last_result_artifact_id") or ""),
            "active_result_artifacts": list(previous.get("active_result_artifacts") or []),
            "last_ranking_artifact_id": str(previous.get("last_ranking_artifact_id") or ""),
            "referent_resolution_trace": list(previous.get("referent_resolution_trace") or []),
        }

    operation = str(logic.get("operation") or logic.get("task_type") or "")
    params = logic.get("parameters") if isinstance(logic.get("parameters"), dict) else {}
    if not _payload_can_update_primary_focus(active_payload, operation):
        return _preserve_previous_analysis_context(
            previous,
            active_payload=active_payload,
            operation=operation,
            original_question=original_question,
        )
    time_window = logic.get("time_window") if isinstance(logic.get("time_window"), dict) else {}
    result = active_payload.get("result") if isinstance(active_payload.get("result"), dict) else {}
    rows = [row for row in result.get("rows") or [] if isinstance(row, dict)]
    columns = [str(column) for column in result.get("columns") or (rows[0].keys() if rows else [])]
    focus_sets = _merge_focus_sets(
        previous.get("focus_sets") if isinstance(previous.get("focus_sets"), list) else [],
        _focus_sets_from_logic_result(logic, params, operation, rows),
    )
    current_artifacts = build_result_artifacts(
        logic=logic,
        params=params,
        operation=operation,
        rows=rows,
        run_id=str(active_payload.get("run_id") or ""),
        question=str(original_question or active_payload.get("question") or ""),
    )
    active_artifacts = merge_result_artifacts(previous.get("active_result_artifacts"), current_artifacts)
    last_artifact_id = str(current_artifacts[0].get("artifact_id") or "") if current_artifacts else str(previous.get("last_result_artifact_id") or "")
    last_ranking_artifact_id = next(
        (
            str(artifact.get("artifact_id") or "")
            for artifact in active_artifacts
            if str(artifact.get("artifact_type") or "") in {"ranking", "topn"}
        ),
        str(previous.get("last_ranking_artifact_id") or ""),
    )
    context = {
        "state_version": "v1",
        "state_name": "analysis_ready" if active_payload.get("success") is not False else "analysis_failed",
        "active": active_payload.get("success") is not False,
        "dataset_id": str(active_payload.get("dataset_id") or previous.get("dataset_id") or ""),
        "run_id": str(active_payload.get("run_id") or ""),
        "question": str(original_question or active_payload.get("question") or ""),
        "operation": operation,
        "capability": capability_for_operation(operation).to_dict(),
        "logic_form": logic,
        "scope": {
            "source_tables": _source_tables(logic, params),
            "metric": _first_text(logic.get("metric"), params.get("metric")),
            "dimension": _first_text(logic.get("group_by"), params.get("dimension"), params.get("group_by")),
            "time_window": time_window or _retail_time_window(params),
            "filters": logic.get("filters") if isinstance(logic.get("filters"), dict) else {},
            "parameters": _compact_parameters(params),
        },
        "last_result": {
            "columns": columns,
            "row_count": len(rows),
            "first_row": rows[0] if rows else {},
        },
        "focus_sets": focus_sets,
        "last_result_artifact_id": last_artifact_id,
        "active_result_artifacts": active_artifacts,
        "last_ranking_artifact_id": last_ranking_artifact_id,
        "referent_resolution_trace": list(previous.get("referent_resolution_trace") or [])[-10:],
        "history_depth": int(previous.get("history_depth") or 0) + 1,
    }
    context["available_followup_actions"] = build_next_actions(
        question=str(active_payload.get("question") or original_question or ""),
        plan=logic,
        rows=rows,
    )
    completed = payload.get("agent_actions") if isinstance(payload.get("agent_actions"), list) else []
    if completed:
        context["last_completed_actions"] = completed
    return context


def _payload_can_update_primary_focus(payload: Mapping[str, Any], operation: str) -> bool:
    if payload.get("success") is False:
        return False
    semantic_status = _payload_semantic_status(payload)
    if semantic_status and semantic_status not in _CONTEXT_PASS_STATUSES:
        return False
    answer_type = str(payload.get("answer_type") or "").strip().lower()
    if answer_type == "clarification":
        return False
    if operation in _NON_FOCUS_OPERATIONS:
        return False
    logic = _logic_form_dict(payload)
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    if (
        operation in {"aggregation", "trend", "time_series"}
        and str(params.get("dimension") or "") == "month"
        and (
            str(params.get("capability_family") or "") == "drilldown_followup"
            or bool(params.get("series_dimension"))
        )
    ):
        return False
    return True


def _payload_semantic_status(payload: Mapping[str, Any]) -> str:
    verification = payload.get("verification") if isinstance(payload.get("verification"), Mapping) else {}
    debug = payload.get("debug") if isinstance(payload.get("debug"), Mapping) else {}
    return str(payload.get("semantic_status") or verification.get("semantic_status") or debug.get("semantic_status") or "").strip()


def _preserve_previous_analysis_context(
    previous: Mapping[str, Any],
    *,
    active_payload: Mapping[str, Any],
    operation: str,
    original_question: str,
) -> dict[str, Any]:
    preserved = dict(previous or {})
    if not preserved:
        return {
            "state_version": "v1",
            "state_name": "analysis_failed" if active_payload.get("success") is False else "chat_only",
            "dataset_id": str(active_payload.get("dataset_id") or ""),
            "run_id": str(active_payload.get("run_id") or ""),
            "question": str(original_question or active_payload.get("question") or ""),
            "previous_run_id": "",
            "active": False,
            "history_depth": 0,
            "available_followup_actions": [],
            "last_result_artifact_id": "",
            "active_result_artifacts": [],
            "last_ranking_artifact_id": "",
            "referent_resolution_trace": [],
        }
    preserved["last_non_focus_run_id"] = str(active_payload.get("run_id") or "")
    preserved["last_non_focus_question"] = str(original_question or active_payload.get("question") or "")
    preserved["last_non_focus_operation"] = operation
    preserved["last_non_focus_semantic_status"] = _payload_semantic_status(active_payload)
    preserved["history_depth"] = int(preserved.get("history_depth") or 0) + 1
    return preserved


def build_next_actions(
    *,
    question: str,
    plan: AnalysisPlan | Mapping[str, Any] | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return executable follow-up actions derived from operation capability metadata."""

    logic = _logic_form_dict(plan)
    parameters = logic.get("parameters") if isinstance(logic.get("parameters"), dict) else {}
    operation = str(logic.get("operation") or logic.get("task_type") or "")
    question_text = str(question or "")
    rows = rows or []
    columns = [str(column) for column in (rows[0].keys() if rows else [])]
    metric = _first_text(logic.get("metric"), parameters.get("metric"), _first_numeric_column(rows, columns), "核心指标")
    dimension = _first_text(logic.get("group_by"), parameters.get("dimension"), parameters.get("group_by"), _first_dimension_column(rows, columns))

    def finish(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sanitize_next_actions(question=question_text, operation=operation, actions=actions)

    if operation == "retail_category_distribution_monthly_trend" or (
        "分品类" in question_text and "历史分销金额" in question_text and "趋势" in question_text
    ):
        window = _retail_month_window_text(parameters.get("start_ym"), parameters.get("end_ym")) or _retail_month_window_from_question(question_text)
        return finish([
            _action(
                action_id="review_extremes",
                label="复核峰值、低点和最大波动期",
                operation="retail_category_distribution_monthly_trend",
                question=f"{window}分品类历史分销金额趋势，标出峰值、低点和最大波动期？" if window else "分品类历史分销金额趋势，标出峰值、低点和最大波动期？",
                inherited_parameters=_inherit_retail_window(parameters),
                parameters={"dimension": "ctg_name", "metric": "sign_amt"},
                dimension="ctg_name",
            ),
            _action(
                action_id="drilldown_customer_source",
                label="按客户拆分来源 Top 排名",
                operation="retail_distribution_topn_chart",
                question=f"请生成{window}历史分销金额按客户拆分来源Top排名。" if window else "请生成历史分销金额按客户拆分来源Top排名。",
                inherited_parameters=_inherit_retail_window(parameters),
                parameters={"dimension": "cust_name", "metric": "sign_amt"},
                dimension="cust_name",
            ),
            _action(
                action_id="drilldown_product_source",
                label="按产品拆分来源 Top 排名",
                operation="retail_distribution_topn_chart",
                question=f"请生成{window}历史分销金额按产品拆分来源Top排名。" if window else "请生成历史分销金额按产品拆分来源Top排名。",
                inherited_parameters=_inherit_retail_window(parameters),
                parameters={"dimension": "sku_name", "metric": "sign_amt"},
                dimension="sku_name",
            ),
        ])

    if operation == "retail_distribution_topn_chart":
        window = _retail_month_window_text(parameters.get("start_ym"), parameters.get("end_ym"))
        return finish([
            _action(
                action_id="switch_to_customer_source",
                label="按客户拆分来源",
                operation="retail_distribution_topn_chart",
                question=f"请生成{window}历史分销金额按客户拆分来源Top排名。" if window else "请生成历史分销金额按客户拆分来源Top排名。",
                inherited_parameters=_inherit_retail_window(parameters),
                parameters={"dimension": "cust_name", "metric": "sign_amt"},
                dimension="cust_name",
            ),
            _action(
                action_id="switch_to_product_source",
                label="按产品拆分来源",
                operation="retail_distribution_topn_chart",
                question=f"请生成{window}历史分销金额按产品拆分来源Top排名。" if window else "请生成历史分销金额按产品拆分来源Top排名。",
                inherited_parameters=_inherit_retail_window(parameters),
                parameters={"dimension": "sku_name", "metric": "sign_amt"},
                dimension="sku_name",
            ),
        ])

    if _looks_like_trend(operation, question_text):
        return finish([
            _action(
                action_id="switch_to_time_trend",
                label="按时间查看趋势",
                operation="aggregation",
                question=f"按{_dimension_question_label(dimension)}继续展示{_metric_question_label(metric)}趋势。",
                inherited_parameters=_generic_inherited_parameters(logic, parameters),
                parameters={"metric": metric, "dimension": dimension},
                dimension=dimension,
            ),
            _action(
                action_id="grouped_metric_distribution",
                label=f"按{_dimension_question_label(dimension)}汇总{_metric_question_label(metric)}",
                operation="aggregation",
                question=f"按{_dimension_question_label(dimension)}汇总{_metric_question_label(metric)}。",
                inherited_parameters=_generic_inherited_parameters(logic, parameters),
                parameters={"metric": metric, "dimension": dimension},
                dimension=dimension,
            ),
            _action(
                action_id="check_metric_anomaly",
                label="检查指标异常",
                operation="outlier_count",
                question=f"{_metric_question_label(metric)}是否异常？",
                inherited_parameters=_generic_inherited_parameters(logic, parameters),
                parameters={"metric": metric},
                dimension=dimension,
            ),
        ])
    if _looks_like_ranking(operation, question_text):
        return finish([
            _action(
                action_id="grouped_metric_distribution",
                label=f"按{_dimension_question_label(dimension)}汇总{_metric_question_label(metric)}",
                operation="aggregation",
                question=f"按{_dimension_question_label(dimension)}汇总{_metric_question_label(metric)}。",
                inherited_parameters=_generic_inherited_parameters(logic, parameters),
                parameters={"metric": metric, "dimension": dimension},
                dimension=dimension,
            ),
            _action(
                action_id="check_metric_anomaly",
                label="检查指标异常",
                operation="outlier_count",
                question=f"{_metric_question_label(metric)}是否异常？",
                inherited_parameters=_generic_inherited_parameters(logic, parameters),
                parameters={"metric": metric},
                dimension=dimension,
            ),
        ])
    return []


def sanitize_next_actions(
    *,
    question: str,
    operation: str,
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop repetitive or vague follow-up actions after the current answer is done."""

    current = _compact_question(question)
    current_operation = str(operation or "")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for action in actions:
        if not isinstance(action, dict):
            continue
        candidate = dict(action)
        action_question = str(candidate.get("question") or "").strip()
        compact_action = _compact_question(action_question)
        action_operation = str(candidate.get("operation") or "")
        if compact_action and compact_action == current:
            continue
        if _repeats_completed_work(current=current, current_operation=current_operation, action_question=compact_action, action_operation=action_operation):
            continue
        if _specificity_score(candidate, action_question) < 2:
            continue
        key = (action_operation, compact_action)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _compact_question(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").lower())


def _repeats_completed_work(*, current: str, current_operation: str, action_question: str, action_operation: str) -> bool:
    if not current and not current_operation:
        return False
    current_text = current + current_operation.lower()
    action_text = action_question + action_operation.lower()
    current_is_topn = any(token in current_text for token in ("top", "前", "排名", "最高", "最低", "topn", "ranking"))
    action_is_topn = any(token in action_text for token in ("top", "前", "排名", "最高", "最低", "topn", "ranking"))
    if current_is_topn and action_is_topn and action_operation == current_operation and (
        action_question in current or current in action_question
    ):
        return True
    if any(token in current_text for token in ("差距", "相差", "gap", "delta", "difference")) and any(token in action_text for token in ("差距", "相差", "gap", "delta", "difference")):
        return True
    if any(token in current_text for token in ("峰值", "低点", "最大波动")) and any(token in action_text for token in ("峰值", "低点", "最大波动")):
        return True
    return False


def _specificity_score(action: dict[str, Any], question: str) -> int:
    params = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
    inherited = action.get("inherited_parameters") if isinstance(action.get("inherited_parameters"), dict) else {}
    text = str(question or "")
    score = 0
    if action.get("metric") or params.get("metric") or any(token in text for token in ("销售额", "金额", "收入", "利润", "数量", "sign_amt", "sales", "revenue", "amount", "metric")):
        score += 1
    if action.get("dimension") or params.get("dimension") or params.get("group_by") or any(token in text for token in ("城市", "客户", "产品", "品类", "渠道", "区域", "city", "customer", "product", "category", "dimension")):
        score += 1
    if inherited.get("start_ym") or inherited.get("end_ym") or inherited.get("time_window") or any(token in text for token in ("202", "月份", "月", "季度", "年度", "时间", "month", "date", "period")):
        score += 1
    filters = action.get("filters") or params.get("filters") or inherited.get("filters") or inherited.get("value_filters")
    if filters or any(token in text for token in ("筛选", "过滤", "条件", "为", "只看", "filter", "where")):
        score += 1
    return score


def plan_followup_actions(question: str, context: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Plan executable follow-up actions from the current analysis context."""

    if not isinstance(context, Mapping) or context.get("state_name") not in {"analysis_ready", "analysis_failed"}:
        return []
    compact = re.sub(r"\s+", "", str(question or ""))
    if not compact:
        return []
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    operation = str(context.get("operation") or logic.get("operation") or logic.get("task_type") or "")
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    available = list(context.get("available_followup_actions") or [])
    actions: list[dict[str, Any]] = []
    referent_resolution = resolve_followup_referent(question, context)
    if (
        str(referent_resolution.get("missing_reason", "")).upper() == "REFERENT_ARTIFACT_MISSING"
        and not bool(referent_resolution.get("resolved"))
        and not _has_contextual_referent_fallback(context)
        and not (_is_retail_context(operation) and (_asks_extreme_review(compact) or _asks_source_drilldown(compact)))
    ):
        return []

    if operation in {"quality_summary", "data_quality_report", "cleaning_policy", "anomaly_rules"} and _asks_quality_followup(compact):
        return []

    if _is_self_contained_ranking_request(compact, context) and not (
        _asks_ranked_entity_share_followup(compact) or _asks_ranked_set_metric_display_followup(compact)
        or _asks_extreme_time_scoped_dimension_drilldown(compact)
        or _asks_focus_entity_rank_position_followup(compact, context)
        or (_asks_gap_comparison(compact) and bool(referent_resolution.get("resolved")))
    ):
        return []

    if not actions and _asks_extreme_time_scoped_dimension_drilldown(compact):
        action = _generic_extreme_time_scoped_dimension_drilldown_action(context, compact)
        if action:
            actions.append(action)

    if not actions and _asks_grouped_distribution_followup(compact) and not _asks_share_followup(compact):
        action = _generic_grouped_distribution_action(context, compact)
        if action:
            actions.append(action)
    if not actions and bool(referent_resolution.get("resolved")) and _asks_referent_child_dimension_breakdown(compact) and not _asks_share_followup(compact):
        available_columns = [str(column) for column in params.get("available_columns") or []]
        child_dimension = _explicit_child_drilldown_dimension(compact, available_columns)
        referent_dimension = str(referent_resolution.get("referent_dimension") or "")
        if child_dimension and child_dimension != referent_dimension:
            action = _generic_grouped_child_ranking_action(context, compact)
            if action:
                actions.append(action)
    if not actions and _asks_ranked_entity_share_followup(compact):
        action = _generic_ranked_entity_share_action(context, compact)
        if action:
            actions.append(action)
    if not actions and _asks_topn_entity_count_ranking_display(compact):
        return []
    if (
        not actions
        and _asks_ranked_set_metric_display_followup(compact)
        and not _asks_time_trend_followup(compact)
        and not _asks_profit_rate_followup(compact)
        and not _asks_source_drilldown(compact)
    ):
        action = _generic_focus_set_metric_aggregation_action(context, compact)
        if action:
            actions.append(action)

    if not actions and _asks_quality_followup(compact):
        action = _generic_quality_anomaly_action(context, compact) if _asks_metric_anomaly_followup(compact) else {}
        if action:
            actions.append(action)
            return actions
        return []

    if not actions and _asks_grouped_child_ranking_followup(compact) and not _has_context_filters(context):
        action = _generic_grouped_child_ranking_action(context, compact)
        if action:
            actions.append(action)

    if not actions and operation == "retail_distribution_topn_chart" and _asks_dimension_switch(compact):
        dimension = _followup_dimension(compact)
        action = _find_retail_drilldown_action(available, dimension) or _retail_source_action(params, dimension)
        if action:
            actions.append(action)
    if not actions and _asks_profit_rate_followup(compact) and _asks_profit_rate_compound_breakdown_then_ranking(compact):
        breakdown_action = _generic_profit_margin_breakdown_action(context, compact)
        ranking_action = _generic_profit_margin_action(context, compact)
        if breakdown_action and ranking_action:
            actions.extend([breakdown_action, ranking_action])
    if not actions and _asks_profit_rate_followup(compact) and _asks_profit_rate_ranking_request(compact) and not _asks_time_trend_followup(compact):
        action = _generic_profit_margin_action(context, compact)
        if action:
            actions.append(action)
    if not actions and _asks_profit_rate_followup(compact) and _asks_metric_breakdown_followup(compact):
        action = _generic_profit_margin_breakdown_action(context, compact)
        if action:
            actions.append(action)
    if not actions and _asks_profit_rate_followup(compact) and (
        _asks_time_trend_followup(compact) or (_asks_growth_rate_followup(compact) and not _references_growth_entity_set(compact))
    ) and (
        not _asks_top_or_gap_followup(compact)
        or (
            _references_contextual_focus_entity(compact, context)
            and (not _asks_explicit_ranking_followup(compact) or _asks_explicit_trend_language(compact))
        )
    ):
        action = _generic_profit_margin_time_trend_action(context, compact)
        if action:
            actions.append(action)
    if not actions and _asks_profit_rate_followup(compact) and _asks_scalar_metric_followup(compact):
        action = _generic_profit_margin_scalar_action(context, compact)
        if action:
            actions.append(action)
    if not actions and _asks_profit_rate_followup(compact):
        action = _generic_profit_margin_action(context, compact)
        if action:
            actions.append(action)
    if not actions and _asks_extreme_review(compact):
        action = _find_action(available, "review_extremes") or _retail_review_extremes_action(params)
        if action:
            actions.append(action)
    if _asks_source_drilldown(compact) and not _asks_time_trend_followup(compact) and (not actions or _asks_extreme_review(compact)):
        dimension = _followup_dimension(compact)
        action = (
            (_find_retail_drilldown_action(available, dimension) or _retail_source_action(params, dimension))
            if _is_retail_context(operation)
            else _generic_dimension_switch_action(context, compact)
        )
        if action:
            if bool(referent_resolution.get("resolved")):
                action["capability_family"] = "drilldown_followup"
            actions.append(action)
    if not actions and _asks_rank_retention_followup(compact):
        action = _generic_rank_retention_action(context, compact)
        if action:
            actions.append(action)
    if not actions and _asks_focus_entity_rank_position_followup(compact, context):
        action = _generic_focus_entity_rank_position_action(context, compact)
        if action:
            actions.append(action)
    if not actions and _asks_growth_ranking_followup(compact):
        action = _generic_growth_ranking_action(context, compact)
        if action:
            actions.append(action)
    if not actions and _asks_same_metric_adjacent_comparison_followup(compact):
        action = _generic_same_metric_adjacent_comparison_action(context, compact)
        if action:
            actions.append(action)
    if not actions and _asks_grouped_time_comparison_followup(compact):
        action = _generic_grouped_time_comparison_action(context, compact)
        if action:
            actions.append(action)
    if not actions and _asks_same_analysis_for_new_time(compact):
        action = _generic_same_analysis_new_time_action(context, compact)
        if action:
            actions.append(action)
    if not actions and (_asks_time_trend_followup(compact) or _asks_growth_rate_followup(compact)):
        action = _generic_time_trend_action(context, compact)
        if action:
            actions.append(action)
    if not actions and bool(referent_resolution.get("resolved")) and _asks_scalar_metric_followup(compact):
        action = _generic_focus_set_metric_aggregation_action(context, compact)
        if action:
            actions.append(action)
    if not actions and _asks_focus_set_metric_scalar(compact, context):
        action = _generic_focus_set_metric_aggregation_action(context, compact)
        if action:
            actions.append(action)
    if not actions and _asks_top_or_gap_followup(compact):
        available_columns = [str(column) for column in params.get("available_columns") or []]
        if _explicit_dimension_column(compact, available_columns) or _explicit_dimension_concept(compact):
            action = _generic_dimension_switch_action(context, compact)
            if action:
                actions.append(action)
    if not actions and _asks_top_or_gap_followup(compact) and not _asks_share_followup(compact):
        if _is_self_contained_ranking_request(compact, context) and not (_asks_gap_comparison(compact) and bool(referent_resolution.get("resolved"))):
            return []
        available_columns = [str(column) for column in params.get("available_columns") or []]
        explicit_metric = _explicit_answer_metric_column(compact, available_columns) or _explicit_metric_concept(compact)
        action = _generic_ranking_action(context, compact) if explicit_metric else (_find_action(available, "drilldown_top_results") or _generic_ranking_action(context, compact))
        if action:
            actions.append(action)

    unique: list[dict[str, Any]] = []
    seen = set()
    for action in actions:
        action = _attach_referent_resolution(action, referent_resolution, compact)
        key = (action.get("operation"), action.get("question"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(dict(action))
    return unique


def _attach_referent_resolution(action: dict[str, Any], resolution: Mapping[str, Any], compact: str) -> dict[str, Any]:
    if not resolution.get("resolved"):
        return action
    if str(action.get("action_id") or "") == "rank_retention_new_time":
        return action
    dimension = str(resolution.get("referent_dimension") or "")
    values = list(resolution.get("referent_values") or [])
    if not dimension or not values:
        return action
    enriched = dict(action)
    parameters = dict(enriched.get("parameters") or {})
    inherited = dict(enriched.get("inherited_parameters") or {})
    ranking_context = dict(resolution.get("ranking_context") or {})
    gap_comparison = _asks_gap_comparison(compact)
    auto_expand = _should_auto_expand_gap_followup(compact=compact, values=values, ranking_context=ranking_context)
    if ranking_context:
        inherited.update({key: value for key, value in ranking_context.items() if key in {"table", "join_plan", "table_selection_reason", "source_tables"} and value not in (None, "", [], {})})
        inherited["filters"] = dict(ranking_context.get("filters") or inherited.get("filters") or {})
        for key in ("metric", "dimension", "aggregation", "sort_order"):
            value = ranking_context.get(key)
            if value not in (None, "", [], {}):
                parameters.setdefault(key, value)
        if isinstance(ranking_context.get("derived_metric"), Mapping) and ranking_context.get("derived_metric"):
            parameters.setdefault("derived_metric", dict(ranking_context.get("derived_metric") or {}))
        derived_metadata = _derived_metric_metadata(ranking_context) or _derived_metric_metadata(parameters)
        parameters.update(derived_metadata)
        if _compact_mentions_derived_metric(compact, derived_metadata):
            parameters["metric"] = derived_metadata["derived_metric_name"]
    filters = dict(inherited.get("filters") or {})
    if _share_total_scope_requested(compact):
        filters = {}
    same_dimension_grouping = (
        not gap_comparison
        and str(parameters.get("dimension") or "") == dimension
        and str(enriched.get("operation") or "") in {
            "aggregation",
            "ranking",
            "filtered_metric_ranking",
            "top_k_share",
        }
    )
    if auto_expand:
        filters.pop(dimension, None)
    elif same_dimension_grouping and not _asks_share_followup(compact):
        filters[dimension] = values[0] if len(values) == 1 else values
        parameters.pop("candidate_filter", None)
    elif same_dimension_grouping:
        filters.pop(dimension, None)
        requested_limit = _focus_set_requested_limit(compact) or _positive_int(ranking_context.get("limit"))
        candidate_filter = {
            "dimension": dimension,
            "metric": ranking_context.get("metric") or parameters.get("metric"),
            "aggregation": ranking_context.get("aggregation") or parameters.get("aggregation") or "sum",
            "limit": requested_limit or len(values),
            "sort_order": ranking_context.get("sort_order") or "desc",
        }
        if isinstance(ranking_context.get("derived_metric"), Mapping) and ranking_context.get("derived_metric"):
            candidate_filter["derived_metric"] = dict(ranking_context.get("derived_metric") or {})
        carry_ranking_filters = not (
            requested_limit is not None
            and requested_limit > 1
            and len(values) == 1
            and _looks_like_time_scope_reference(compact)
        )
        if carry_ranking_filters and isinstance(ranking_context.get("filters"), Mapping) and ranking_context.get("filters"):
            candidate_filter["filters"] = dict(ranking_context.get("filters") or {})
        if requested_limit is None:
            parameters.setdefault("candidate_filter", candidate_filter)
        else:
            parameters["candidate_filter"] = candidate_filter
    else:
        filters[dimension] = values[0] if len(values) == 1 else values
    inherited["filters"] = filters
    minimum_required_objects = 2 if (auto_expand or gap_comparison) else None
    preferred_top_n = 3 if auto_expand else None
    parameters.update(
        {
            "requires_previous_artifact": True,
            "referent_artifact_id": str(resolution.get("artifact_id") or ""),
            "referent_dimension": dimension,
            "referent_values": values,
            "referent_policy": "auto_expand_previous_metric_dimension_context" if auto_expand else "must_filter_to_previous_result_objects",
            "referent_source": str(resolution.get("referent_source") or "result_artifact"),
            **(
                {
                    "requires_gap_comparison": True,
                    "minimum_required_objects": minimum_required_objects,
                    "preferred_top_n": preferred_top_n,
                    "auto_expand_topn_if_needed": True,
                    "expansion_source": "previous_metric_dimension_context",
                    "limit": preferred_top_n,
                    "top_n": preferred_top_n,
                }
                if auto_expand
                else {}
            ),
            **({"requires_gap_comparison": True, "minimum_required_objects": minimum_required_objects} if gap_comparison else {}),
        }
    )
    if resolution.get("metric") and not parameters.get("metric"):
        parameters["metric"] = str(resolution.get("metric") or "")
    child_dimension = str(parameters.get("dimension") or enriched.get("dimension") or "")
    derived_metadata_for_drilldown = _derived_metric_metadata(ranking_context) or _derived_metric_metadata(parameters)
    drilldown_followup = bool(
        child_dimension
        and child_dimension != dimension
        and (
            str(enriched.get("capability_family") or "") == "drilldown_followup"
            or _compact_mentions_derived_metric(compact, derived_metadata_for_drilldown)
        )
    )
    if drilldown_followup:
        enriched["capability_family"] = "drilldown_followup"
        parameters["capability_family"] = "drilldown_followup"
        parameters["merged_filters"] = dict(filters)
    label = _dimension_question_label(dimension)
    value_text = _filter_value_text(values)
    question = str(enriched.get("question") or "")
    if auto_expand and _asks_gap_comparison(compact):
        metric_label = _metric_question_label(str(parameters.get("metric") or ranking_context.get("metric") or "核心指标"))
        question = f"按{label or dimension}看{metric_label}排名前3，并比较Top{label or dimension}之间的差距。"
    elif not same_dimension_grouping and label and value_text and f"筛选{value_text}{label}的数据" not in question:
        prefix = f"筛选{value_text}{label}的数据，"
        if "Top对象" in compact or "top对象" in compact or "TOP对象" in compact or "这些" in compact:
            prefix = f"这些Top对象来自上一轮结果，仅包含{value_text}{label}；{prefix}"
        question = prefix + question
    enriched["question"] = question
    derived_metadata = _derived_metric_metadata(ranking_context) or _derived_metric_metadata(parameters)
    parameters.update(derived_metadata)
    if _compact_mentions_derived_metric(compact, derived_metadata):
        parameters["metric"] = derived_metadata["derived_metric_name"]
    enriched["parameters"] = parameters
    enriched["inherited_parameters"] = inherited
    enriched["referent_contract"] = {
        "requires_previous_artifact": True,
        "referent_artifact_id": str(resolution.get("artifact_id") or ""),
        "referent_values": values,
        "referent_dimension": dimension,
        "referent_policy": "auto_expand_previous_metric_dimension_context" if auto_expand else "must_filter_to_previous_result_objects",
        "referent_source": str(resolution.get("referent_source") or "result_artifact"),
        "inherited_parameters": inherited,
        "action_parameters": parameters,
        **(
            {
                "capability_family": "drilldown_followup",
                "merged_filters": dict(filters),
            }
            if drilldown_followup
            else {}
        ),
        **(
            {
                "requires_gap_comparison": True,
                "minimum_required_objects": minimum_required_objects,
                "preferred_top_n": preferred_top_n,
                "auto_expand_topn_if_needed": True,
                "expansion_source": "previous_metric_dimension_context",
                "ranking_context": ranking_context,
            }
            if auto_expand
            else {}
        ),
        **({"requires_gap_comparison": True, "minimum_required_objects": minimum_required_objects} if gap_comparison else {}),
    }
    enriched["referent_resolution_trace"] = dict(resolution)
    return enriched


def _should_auto_expand_gap_followup(*, compact: str, values: list[Any], ranking_context: Mapping[str, Any]) -> bool:
    if len(values) >= 2:
        return False
    if not _asks_gap_comparison(compact):
        return False
    return bool(ranking_context.get("metric") and ranking_context.get("dimension"))


def _asks_gap_comparison(compact: str) -> bool:
    lowered = str(compact or "").lower()
    return any(token in compact for token in ("差距", "差值", "差多少", "少多少", "多多少", "相差", "差额", "比较Top", "比较top", "前N名", "第一名和第二名")) or any(
        token in lowered for token in ("gap", "difference", "compare top")
    )


def action_questions(actions: list[Mapping[str, Any]]) -> list[str]:
    """Extract user-facing questions from structured actions."""

    questions = []
    for action in actions:
        question = str(action.get("question") or "").strip()
        if question:
            questions.append(question)
    return questions


def _active_payload_for_context(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    sub_results = result.get("sub_results") if isinstance(result.get("sub_results"), list) else []
    for sub in reversed(sub_results):
        if isinstance(sub, dict) and sub.get("success") is not False and isinstance(sub.get("logic_form"), dict):
            return sub
    return payload


def _logic_form_dict(plan: AnalysisPlan | Mapping[str, Any] | None) -> dict[str, Any]:
    if isinstance(plan, AnalysisPlan):
        return _as_dict(plan.logic_form)
    if isinstance(plan, Mapping):
        logic = plan.get("logic_form")
        if isinstance(logic, Mapping):
            return dict(logic)
        return dict(plan)
    return {}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _has_contextual_referent_fallback(context: Mapping[str, Any] | None) -> bool:
    if not isinstance(context, Mapping):
        return False
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    if isinstance(scope.get("filters"), Mapping) and scope.get("filters"):
        return True
    last_result = context.get("last_result") if isinstance(context.get("last_result"), Mapping) else {}
    if isinstance(last_result.get("first_row"), Mapping) and last_result.get("first_row"):
        return True
    if any(isinstance(item, Mapping) for item in context.get("focus_sets") or []):
        return True
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    return isinstance(logic.get("filters"), Mapping) and bool(logic.get("filters"))


def _has_context_filters(context: Mapping[str, Any] | None) -> bool:
    if not isinstance(context, Mapping):
        return False
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    return any(
        isinstance(filters, Mapping) and bool(filters)
        for filters in (scope.get("filters"), logic.get("filters"))
    )


def _action(
    *,
    action_id: str,
    label: str,
    operation: str,
    question: str,
    inherited_parameters: dict[str, Any],
    parameters: dict[str, Any],
    dimension: str = "",
) -> dict[str, Any]:
    capability = capability_for_operation(operation)
    parameters = dict(parameters)
    parameters.update(_derived_metric_metadata(parameters))
    return {
        "action_id": action_id,
        "label": label,
        "operation": operation,
        "question": question,
        "inherited_parameters": {key: value for key, value in inherited_parameters.items() if value not in (None, "", [], {})},
        "parameters": {key: value for key, value in parameters.items() if value not in (None, "", [], {})},
        "dimension": dimension,
        "status": "executable" if capability.supports_pandas else "unsupported",
        "capability_family": capability.capability_family,
        "support_boundary": capability.support_boundary,
    }


def _derived_metric_metadata(payload: Mapping[str, Any]) -> dict[str, str]:
    derived = payload.get("derived_metric") if isinstance(payload.get("derived_metric"), Mapping) else {}
    name = str(payload.get("derived_metric_name") or derived.get("name") or "").strip()
    numerator = str(payload.get("numerator_column") or derived.get("numerator") or "").strip()
    denominator = str(payload.get("denominator_column") or derived.get("denominator") or "").strip()
    formula = str(payload.get("metric_formula") or derived.get("formula") or "").strip()
    if not formula and numerator and denominator:
        formula = f"sum({numerator})/sum({denominator})"
    return {
        key: value
        for key, value in {
            "derived_metric_name": name,
            "metric_formula": formula,
            "numerator_column": numerator,
            "denominator_column": denominator,
        }.items()
        if value
    }


def _compact_mentions_derived_metric(compact: str, metadata: Mapping[str, Any]) -> bool:
    if not metadata.get("derived_metric_name"):
        return False
    text = str(compact or "").lower()
    name = str(metadata.get("derived_metric_name") or "").lower()
    if name and name in text:
        return True
    if name in {"sales", "amount", "revenue"} and any(
        token in str(compact or "")
        for token in ("销售额", "销售金额", "订单金额", "订单总额", "总销售额", "收入", "营收")
    ):
        return True
    return any(
        token in text
        for token in (
            "利润率",
            "profitmargin",
            "profit_margin",
            "转化率",
            "conversionrate",
            "conversion_rate",
            "留存率",
            "retentionrate",
            "retention_rate",
            "客单价",
            "averageordervalue",
            "average_order_value",
        )
    )


def _explicit_sales_derived_metric(compact: str, available_columns: list[str]) -> dict[str, str]:
    available = [str(column) for column in available_columns if str(column or "").strip()]
    if not available:
        return {}
    compact_text = str(compact or "")
    lowered = compact_text.lower().replace(" ", "")
    sales_signal = any(
        token in compact_text
        for token in ("销售额", "销售金额", "订单金额", "订单总额", "总销售额", "收入", "营收")
    ) or any(token in lowered for token in ("sales", "revenue", "amount"))
    formula_signal = bool(re.search(r"quantity\s*\*\s*unit\s*price", compact_text, re.I)) or any(
        token in lowered for token in ("quantity*unitprice", "quantity×unitprice", "quantityxunitprice")
    )
    if not (sales_signal or formula_signal):
        return {}
    numerator = _pick_column_by_aliases(available, ("quantity", "qty", "数量"))
    denominator = _pick_column_by_aliases(available, ("unitprice", "unit_price", "unit price", "price", "单价", "价格"))
    if not numerator or not denominator:
        return {}
    name = _pick_column_by_aliases(available, ("sales", "amount", "revenue", "销售额", "销售金额", "订单金额", "收入")) or "Sales"
    return {
        "name": name,
        "numerator": numerator,
        "denominator": denominator,
        "formula": f"{numerator} * {denominator}",
        "operator": "multiply",
    }


def _share_total_scope_requested(compact: str) -> bool:
    lowered = str(compact or "").lower()
    return _asks_share_followup(compact) and (
        any(token in str(compact or "") for token in ("占总", "总销售额", "总金额", "整体", "总体", "全量", "全部", "所有"))
        or any(token in lowered for token in ("total", "overall", "all"))
    )


def _find_action(actions: list[Any], action_id: str) -> dict[str, Any]:
    for action in actions:
        if isinstance(action, Mapping) and str(action.get("action_id") or "") == action_id:
            return dict(action)
    return {}


def _find_retail_drilldown_action(actions: list[Any], dimension: str) -> dict[str, Any]:
    for action in actions:
        if not isinstance(action, Mapping):
            continue
        if action.get("operation") != "retail_distribution_topn_chart":
            continue
        if dimension and action.get("dimension") == dimension:
            return dict(action)
        if not dimension and action.get("dimension") in {"cust_name", "sku_name"}:
            return dict(action)
    return {}


def _retail_review_extremes_action(params: Mapping[str, Any]) -> dict[str, Any]:
    window = _retail_month_window_text(params.get("start_ym"), params.get("end_ym"))
    return _action(
        action_id="review_extremes",
        label="复核峰值、低点和最大波动期",
        operation="retail_category_distribution_monthly_trend",
        question=f"{window}分品类历史分销金额趋势，标出峰值、低点和最大波动期？" if window else "分品类历史分销金额趋势，标出峰值、低点和最大波动期？",
        inherited_parameters=_inherit_retail_window(params),
        parameters={"dimension": "ctg_name", "metric": "sign_amt"},
        dimension="ctg_name",
    )


def _retail_source_action(params: Mapping[str, Any], dimension: str) -> dict[str, Any]:
    dimension = dimension or "cust_name"
    label = "按产品拆分来源 Top 排名" if dimension == "sku_name" else "按客户拆分来源 Top 排名"
    text = "产品" if dimension == "sku_name" else "客户"
    window = _retail_month_window_text(params.get("start_ym"), params.get("end_ym"))
    return _action(
        action_id="drilldown_product_source" if dimension == "sku_name" else "drilldown_customer_source",
        label=label,
        operation="retail_distribution_topn_chart",
        question=f"请生成{window}历史分销金额按{text}拆分来源Top排名。" if window else f"请生成历史分销金额按{text}拆分来源Top排名。",
        inherited_parameters=_inherit_retail_window(params),
        parameters={"dimension": dimension, "metric": "sign_amt"},
        dimension=dimension,
    )


def _generic_ranking_action(context: Mapping[str, Any], compact: str = "") -> dict[str, Any]:
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    available = [str(column) for column in params.get("available_columns") or []]
    operation = str(context.get("operation") or logic.get("operation") or "ranking")
    metric = _first_text(_explicit_answer_metric_column(compact, available), _explicit_metric_concept(compact), scope.get("metric"), params.get("metric"), logic.get("metric"), "核心指标")
    dimension = _first_text(_explicit_rank_target_dimension_column(compact, available), _explicit_dimension_column(compact, available), _explicit_dimension_concept(compact), scope.get("dimension"), params.get("dimension"), logic.get("group_by"), "对象")
    label = _dimension_question_label(dimension)
    question = f"按{dimension}看{_metric_question_label(metric)}排名前3。"
    if _asks_gap_comparison(compact):
        question = f"按{dimension}看{_metric_question_label(metric)}排名前3，并比较Top{label or dimension}之间的差距。"
    return _action(
        action_id="drilldown_top_results",
        label="继续比较 Top 结果",
        operation=operation,
        question=question,
        inherited_parameters=_generic_inherited_parameters_for_question(logic, params, compact),
        parameters={"metric": metric, "dimension": dimension},
        dimension=dimension,
    )


def _generic_profit_margin_action(context: Mapping[str, Any], compact: str = "") -> dict[str, Any]:
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    available = [str(column) for column in params.get("available_columns") or []]
    numerator = _pick_column_by_aliases(available, ("profit", "gross_profit", "毛利", "利润"))
    denominator = _profit_margin_denominator_column(available)
    derived_metric = (
        {
            "name": "利润率",
            "numerator": numerator,
            "denominator": denominator,
            "formula": f"sum({numerator})/sum({denominator})",
        }
        if numerator and denominator
        else {}
    )
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    dimension = _first_text(
        _explicit_grouped_dimension_column(compact, available),
        _explicit_dimension_column(compact, available),
        _explicit_dimension_concept(compact),
        _explicit_rank_target_dimension_column(compact, available),
        scope.get("dimension"),
        params.get("dimension"),
        logic.get("group_by"),
        "对象",
    )
    label = _dimension_question_label(dimension)
    filter_prefix = _combined_filter_question_prefix(context, compact)
    time_prefix = _combined_time_question_prefix(context, compact)
    time_prefix = _dedupe_time_prefix(time_prefix, filter_prefix)
    scope_prefix = _combined_scope_question_prefix(time_prefix, filter_prefix)
    rank_position_followup = _asks_rank_position_followup(compact)
    time_dimension = bool(re.search(r"month|date|day|time|月份|日期|时间", str(dimension), re.I))
    if rank_position_followup or time_dimension:
        question = f"{scope_prefix}按{label}看利润率排名前3。"
    else:
        question = f"{time_prefix}{filter_prefix}哪个{label}利润率最高？"
    return _action(
        action_id="switch_to_profit_margin",
        label="切换到利润率排名",
        operation="ranking",
        question=question,
        inherited_parameters=(
            _generic_inherited_parameters_for_question(logic, params, compact)
            if rank_position_followup
            else _generic_inherited_parameters(logic, params)
        ),
        parameters={
            "metric": "利润率",
            "dimension": dimension,
            **({"derived_metric": derived_metric} if derived_metric else {}),
        },
        dimension=dimension,
    )


def _generic_profit_margin_scalar_action(context: Mapping[str, Any], compact: str = "") -> dict[str, Any]:
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    available = [str(column) for column in params.get("available_columns") or []]
    numerator = _pick_column_by_aliases(available, ("profit", "gross_profit", "毛利", "利润"))
    denominator = _profit_margin_denominator_column(available)
    if not numerator or not denominator:
        return {}
    filter_prefix = _combined_filter_question_prefix(context, compact)
    time_prefix = _combined_time_question_prefix(context, compact)
    time_prefix = _dedupe_time_prefix(time_prefix, filter_prefix)
    scope_prefix = _combined_scope_question_prefix(time_prefix, filter_prefix)
    return _action(
        action_id="switch_to_profit_margin_scalar",
        label="计算利润率",
        operation="aggregation",
        question=f"{time_prefix}{filter_prefix}利润率是多少？",
        inherited_parameters=_generic_inherited_parameters(logic, params),
        parameters={
            "metric": "利润率",
            "derived_metric": {
                "name": "利润率",
                "numerator": numerator,
                "denominator": denominator,
                "formula": f"sum({numerator})/sum({denominator})",
            },
        },
        dimension="",
    )


def _generic_profit_margin_time_trend_action(context: Mapping[str, Any], compact: str = "") -> dict[str, Any]:
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    available = [str(column) for column in params.get("available_columns") or []]
    numerator = _pick_column_by_aliases(available, ("profit", "gross_profit", "毛利", "利润"))
    denominator = _profit_margin_denominator_column(available)
    time_column = _first_time_column(available)
    if not numerator or not denominator or not time_column:
        return {}
    filter_prefix = _combined_filter_question_prefix(context, compact)
    time_prefix = _combined_time_question_prefix(context, compact)
    time_prefix = _dedupe_time_prefix(time_prefix, filter_prefix)
    scope_prefix = _combined_scope_question_prefix(time_prefix, filter_prefix)
    return _action(
        action_id="switch_profit_margin_time_trend",
        label="按时间查看利润率趋势",
        operation="aggregation",
        question=f"{time_prefix}{filter_prefix}按{_time_question_label(time_column)}展示利润率趋势，生成折线图。",
        inherited_parameters=_generic_inherited_parameters(logic, params),
        parameters={
            "metric": "利润率",
            "dimension": time_column,
            "derived_metric": {
                "name": "利润率",
                "numerator": numerator,
                "denominator": denominator,
                "formula": f"sum({numerator})/sum({denominator})",
            },
        },
        dimension=time_column,
    )


def _generic_profit_margin_breakdown_action(context: Mapping[str, Any], compact: str = "") -> dict[str, Any]:
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    available = [str(column) for column in params.get("available_columns") or []]
    numerator = _pick_column_by_aliases(available, ("profit", "gross_profit", "毛利", "利润"))
    denominator = _profit_margin_denominator_column(available)
    if not numerator or not denominator:
        return {}
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    dimension = _explicit_grouped_dimension_column(compact, available) or _explicit_dimension_column(compact, available) or _first_text(
        scope.get("dimension"), params.get("dimension"), logic.get("group_by")
    )
    if not dimension or re.search(r"date|day|month|year|week|time|日期|时间|月份|年份|周", dimension, re.I):
        return {}
    label = _dimension_question_label(dimension)
    candidate_prefix = _explicit_candidate_topn_question_prefix(compact, available)
    filter_prefix = candidate_prefix or _combined_filter_question_prefix(context, compact)
    time_prefix = "" if candidate_prefix else _combined_time_question_prefix(context, compact)
    time_prefix = _dedupe_time_prefix(time_prefix, filter_prefix)
    scope_prefix = _combined_scope_question_prefix(time_prefix, filter_prefix)
    return _action(
        action_id="switch_profit_margin_breakdown",
        label=f"按{label}汇总利润率",
        operation="aggregation",
        question=f"{scope_prefix}按{label}汇总利润率。",
        inherited_parameters=_generic_inherited_parameters(logic, params),
        parameters={
            "metric": "利润率",
            "dimension": dimension,
            "derived_metric": {
                "name": "利润率",
                "numerator": numerator,
                "denominator": denominator,
                "formula": f"sum({numerator})/sum({denominator})",
            },
        },
        dimension=dimension,
    )


def _generic_dimension_switch_action(context: Mapping[str, Any], compact: str) -> dict[str, Any]:
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    available = [str(column) for column in params.get("available_columns") or []]
    current_dimension = _first_text(scope.get("dimension"), params.get("dimension"), logic.get("group_by"))
    dimension = _generic_followup_dimension(compact, available, current_dimension=current_dimension)
    if not dimension:
        return {}
    purchase_quantity_metric = _purchase_quantity_metric(compact, available)
    metric = _first_text(purchase_quantity_metric, _explicit_answer_metric_column(compact, available), scope.get("metric"), params.get("metric"), logic.get("metric"), "核心指标")
    filter_prefix = _combined_filter_question_prefix(context, compact)
    time_prefix = _combined_time_question_prefix(context, compact)
    time_prefix = _dedupe_time_prefix(time_prefix, filter_prefix)
    scope_prefix = _combined_scope_question_prefix(time_prefix, filter_prefix)
    ordinal_phrase = _rank_position_question_phrase(compact)
    question = (
        f"{scope_prefix}{_metric_question_label(metric)}{ordinal_phrase}的{_dimension_question_label(dimension)}是什么？"
        if ordinal_phrase
        else f"{scope_prefix}按{_dimension_question_label(dimension)}看{_metric_question_label(metric)}排名前3。"
    )
    action_parameters = {"metric": metric, "dimension": dimension}
    if purchase_quantity_metric:
        action_parameters["aggregation"] = "sum"
    if not purchase_quantity_metric and isinstance(params.get("derived_metric"), Mapping) and params.get("derived_metric"):
        action_parameters["derived_metric"] = dict(params.get("derived_metric") or {})
    inherited_parameters = _generic_inherited_parameters_for_question(logic, params, compact)
    if purchase_quantity_metric:
        inherited_parameters.pop("derived_metric", None)
    return _action(
        action_id="switch_generic_dimension",
        label=f"按{_dimension_question_label(dimension)}切换维度",
        operation="ranking",
        question=question,
        inherited_parameters=inherited_parameters,
        parameters=action_parameters,
        dimension=dimension,
    )


def _generic_extreme_time_scoped_dimension_drilldown_action(context: Mapping[str, Any], compact: str) -> dict[str, Any]:
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    available = [str(column) for column in params.get("available_columns") or []]
    time_column = _first_time_column(available)
    dimension = _first_text(
        _explicit_rank_target_dimension_column(compact, available),
        _explicit_grouped_dimension_column(compact, available),
        _explicit_dimension_column(compact, available),
        _explicit_dimension_concept(compact),
    )
    metric = _first_text(_explicit_metric_column(compact, available), scope.get("metric"), params.get("metric"), logic.get("metric"), "核心指标")
    if not time_column or not dimension or not metric:
        return {}
    limit = _extract_limit_from_compact(compact, default=3)
    sort_label = "最低" if any(token in compact for token in ("最低", "最小", "最少")) else "最高"
    filter_prefix = _combined_filter_question_prefix(context, compact)
    label = _dimension_question_label(dimension)
    time_label = _time_question_label(time_column)
    metric_label = _metric_question_label(metric)
    return _action(
        action_id="extreme_time_scoped_dimension_drilldown",
        label=f"{sort_label}{time_label}内按{label}排名",
        operation="ranking",
        question=f"{filter_prefix}哪个{time_label}的{metric_label}{sort_label}？请列出该{time_label}{metric_label}排名前{limit}的{label}。",
        inherited_parameters=_generic_inherited_parameters(logic, params),
        parameters={"metric": metric, "dimension": dimension, "time_column": time_column, "limit": limit},
        dimension=dimension,
    )


def _generic_quality_anomaly_action(context: Mapping[str, Any], compact: str) -> dict[str, Any]:
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    available = [str(column) for column in params.get("available_columns") or []]
    metric = _first_text(_explicit_metric_column(compact, available), scope.get("metric"), params.get("metric"), logic.get("metric"))
    if not metric:
        return {}
    filter_prefix = _combined_filter_question_prefix(context, compact)
    time_prefix = _combined_time_question_prefix(context, compact)
    time_prefix = _dedupe_time_prefix(time_prefix, filter_prefix)
    scope_prefix = _combined_scope_question_prefix(time_prefix, filter_prefix)
    negative_value_check = _asks_negative_value_quality(compact)
    question = (
        f"{scope_prefix}{_metric_question_label(metric)}是否存在负值？请按异常规则给出数量和样例说明。"
        if negative_value_check
        else f"{scope_prefix}{_metric_question_label(metric)}是否异常？"
    )
    return _action(
        action_id="check_metric_anomaly",
        label="检查指标异常",
        operation="anomaly_rules" if negative_value_check else "outlier_count",
        question=question,
        inherited_parameters=_generic_inherited_parameters(logic, params),
        parameters={"metric": metric, **({"quality_check": "negative_value"} if negative_value_check else {})},
        dimension=_first_text(scope.get("dimension"), params.get("dimension"), logic.get("group_by")),
    )


def _generic_growth_ranking_action(context: Mapping[str, Any], compact: str) -> dict[str, Any]:
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    available = [str(column) for column in params.get("available_columns") or []]
    dimension = _first_text(
        _explicit_rank_target_dimension_column(compact, available),
        _explicit_grouped_dimension_column(compact, available),
        _explicit_dimension_column(compact, available),
        scope.get("dimension"),
        params.get("dimension"),
        logic.get("group_by"),
    )
    metric = _first_text(_explicit_metric_column(compact, available), scope.get("metric"), params.get("metric"), logic.get("metric"), "核心指标")
    time_column = _first_time_column(available)
    if not dimension or not metric or not time_column:
        return {}
    filter_prefix = _combined_filter_question_prefix(context, compact)
    time_prefix = _combined_time_question_prefix(context, compact)
    time_prefix = _dedupe_time_prefix(time_prefix, filter_prefix)
    label = _dimension_question_label(dimension)
    change_delta = _asks_change_delta_ranking(compact)
    ranking_phrase = "变化最大" if change_delta else "增长最快"
    return _action(
        action_id="growth_ranking",
        label=f"按{label}计算{ranking_phrase}",
        operation="growth_ranking",
        question=f"{time_prefix}{filter_prefix}哪个{label}的{_metric_question_label(metric)}{ranking_phrase}？",
        inherited_parameters=_generic_inherited_parameters_for_question(logic, params, compact),
        parameters={"metric": metric, "dimension": dimension, "time_column": time_column, "growth_mode": "abs_delta" if change_delta else "rate"},
        dimension=dimension,
    )


def _generic_rank_retention_action(context: Mapping[str, Any], compact: str) -> dict[str, Any]:
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    available = [str(column) for column in params.get("available_columns") or []]
    dimension = _first_text(scope.get("dimension"), params.get("dimension"), logic.get("group_by"), _explicit_rank_target_dimension_column(compact, available))
    metric = _first_text(_explicit_metric_column(compact, available), scope.get("metric"), params.get("metric"), logic.get("metric"), "核心指标")
    if not dimension or not metric:
        return {}
    time_prefix = _explicit_time_question_prefix(compact) or _combined_time_question_prefix(context, compact)
    if not time_prefix:
        return {}
    label = _dimension_question_label(dimension)
    return _action(
        action_id="rank_retention_new_time",
        label="复核新时间排名",
        operation="ranking",
        question=f"{time_prefix}按{label}看{_metric_question_label(metric)}排名前3。",
        inherited_parameters=_generic_inherited_parameters_for_question(logic, params, compact),
        parameters={"metric": metric, "dimension": dimension},
        dimension=dimension,
    )


def _generic_focus_entity_rank_position_action(context: Mapping[str, Any], compact: str) -> dict[str, Any]:
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    available = [str(column) for column in params.get("available_columns") or []]
    dimension, value = _rank_position_focus_target(context, compact)
    if not dimension or value in (None, "", [], {}):
        return {}
    explicit_dimension = _first_text(
        _explicit_rank_target_dimension_column(compact, available),
        _explicit_dimension_column(compact, available),
        _explicit_dimension_concept(compact),
    )
    if explicit_dimension and explicit_dimension != dimension:
        return {}
    metric = _first_text(
        _explicit_answer_metric_column(compact, available),
        _explicit_metric_concept(compact),
        scope.get("metric"),
        params.get("metric"),
        logic.get("metric"),
        "核心指标",
    )
    label = _dimension_question_label(dimension)
    value_text = _filter_value_text(value)
    if not label or not value_text:
        return {}
    time_prefix = _explicit_time_question_prefix(compact) or _combined_time_question_prefix(context, compact)
    filter_prefix = _contextual_filter_question_prefix_excluding_dimension(context, dimension)
    scope_prefix = _combined_scope_question_prefix(time_prefix, filter_prefix)
    inherited = _generic_inherited_parameters_for_question(logic, params, compact)
    _remove_inherited_filter(inherited, dimension)
    return _action(
        action_id="focus_entity_rank_position",
        label=f"查询当前{label}在全部{label}中的名次",
        operation="ranking",
        question=f"{scope_prefix}{value_text}{label}的{_metric_question_label(metric)}在全部{label}中排第几？",
        inherited_parameters=inherited,
        parameters={"metric": metric, "dimension": dimension, "rank_target": {"dimension": dimension, "value": value}},
        dimension=dimension,
    )


def _generic_time_trend_action(context: Mapping[str, Any], compact: str = "") -> dict[str, Any]:
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    available = [str(column) for column in params.get("available_columns") or []]
    time_column = _first_time_column(available)
    if not time_column:
        return {}
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    explicit_metrics = _explicit_metric_columns(compact, available)
    metric = _first_text(*(explicit_metrics or []), _explicit_metric_column(compact, available), scope.get("metric"), params.get("metric"), logic.get("metric"), "核心指标")
    metric_label = "和".join(_metric_question_label(item) for item in explicit_metrics) if len(explicit_metrics) > 1 else _metric_question_label(metric)
    filter_prefix = _combined_filter_question_prefix(context, compact)
    time_prefix = _combined_time_question_prefix(context, compact)
    time_prefix = _dedupe_time_prefix(time_prefix, filter_prefix)
    scope_prefix = _combined_scope_question_prefix(time_prefix, filter_prefix)
    explicit_time_drilldown = _explicit_time_drilldown(compact)
    month_bucket = _has_multiple_month_reference(compact) or explicit_time_drilldown or any(
        token in compact
        for token in ("每月", "每个月", "各月", "各月份", "按月", "按月份", "月份", "月度", "月粒度", "月粒", "哪些月份", "哪个月份")
    )
    series_dimension = ""
    focus_set_for_time: Mapping[str, Any] | None = None
    if month_bucket:
        explicit_dimension = _explicit_grouped_dimension_column(compact, available) or _explicit_dimension_column(compact, available) or _explicit_dimension_concept(compact)
        if explicit_dimension and explicit_dimension != "month":
            series_dimension = explicit_dimension
        focus_set_for_time = next(
            (
                focus_set
                for focus_set in _context_focus_sets(context)
                if str(focus_set.get("dimension") or "")
                and _question_references_focus_set(compact, str(focus_set.get("dimension") or ""))
            ),
            None,
        )
        if not series_dimension and focus_set_for_time:
            series_dimension = str(focus_set_for_time.get("dimension") or "")
    action_parameters = {
        "metric": metric,
        **({"metrics": explicit_metrics} if len(explicit_metrics) > 1 else {}),
        "dimension": "month" if month_bucket else time_column,
        **(
            {
                "time_column": time_column,
                "time_dimension": "month",
                "source_time_field": time_column,
                "time_bucket": "month",
                "capability_family": "time_series",
                **({"series_dimension": series_dimension} if series_dimension else {}),
            }
            if month_bucket
            else {}
        ),
    }
    time_label = _time_question_label(str(action_parameters.get("dimension") or time_column))
    series_label = _dimension_question_label(series_dimension) if series_dimension else ""
    trend_question = (
        f"{scope_prefix}按{series_label}和{time_label}展示{metric_label}趋势，生成折线图。"
        if series_label and month_bucket
        else f"{scope_prefix}按{time_label}展示{metric_label}趋势，生成折线图。"
    )
    if isinstance(params.get("derived_metric"), Mapping) and params.get("derived_metric"):
        action_parameters["derived_metric"] = dict(params.get("derived_metric") or {})
    inherited_parameters = _generic_inherited_parameters(logic, params)
    action = _action(
        action_id="switch_to_time_trend",
        label="按时间查看趋势",
        operation="aggregation",
        question=trend_question,
        inherited_parameters=inherited_parameters,
        parameters=action_parameters,
        dimension=str(action_parameters.get("dimension") or time_column),
    )
    if month_bucket and focus_set_for_time and series_dimension:
        values = [value for value in focus_set_for_time.get("values") or [] if value not in (None, "")]
        if values:
            referent_artifact_id = _focus_set_artifact_id(context, focus_set_for_time)
            action_parameters = dict(action.get("parameters") or {})
            action_parameters.update(
                {
                    "requires_previous_artifact": True,
                    "referent_artifact_id": referent_artifact_id,
                    "referent_dimension": series_dimension,
                    "referent_values": values,
                    "referent_policy": "must_filter_to_previous_result_objects",
                    "referent_source": str(focus_set_for_time.get("source") or "focus_set"),
                }
            )
            action["parameters"] = action_parameters
            action["referent_contract"] = {
                "requires_previous_artifact": True,
                "referent_artifact_id": referent_artifact_id,
                "referent_values": values,
                "referent_dimension": series_dimension,
                "referent_policy": "must_filter_to_previous_result_objects",
                "referent_source": str(focus_set_for_time.get("source") or "focus_set"),
                "inherited_parameters": inherited_parameters,
                "action_parameters": action_parameters,
                "capability_family": "drilldown_followup",
                "merged_filters": {series_dimension: values},
            }
    return action


def _generic_same_metric_adjacent_comparison_action(context: Mapping[str, Any], compact: str = "") -> dict[str, Any]:
    action = _generic_time_trend_action(context, compact)
    if not action:
        return {}
    enriched = dict(action)
    parameters = dict(enriched.get("parameters") or {})
    time_column = str(parameters.get("dimension") or "")
    metric = str(parameters.get("metric") or "")
    if time_column:
        parameters["time_column"] = time_column
        parameters["time_dimension"] = time_column
    parameters["requires_gap_comparison"] = True
    enriched["parameters"] = parameters
    enriched["action_id"] = "same_metric_adjacent_comparison"
    enriched["label"] = "对比同一指标"
    if time_column and metric:
        filter_prefix = _combined_filter_question_prefix(context, compact)
        enriched["question"] = f"{filter_prefix}按{_time_question_label(time_column)}对比相邻时间段的{_metric_question_label(metric)}差距。"
    return enriched


def _generic_grouped_time_comparison_action(context: Mapping[str, Any], compact: str = "") -> dict[str, Any]:
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    available = [str(column) for column in params.get("available_columns") or []]
    time_column = _first_time_column(available)
    dimension = _first_text(
        _explicit_grouped_dimension_column(compact, available),
        _explicit_dimension_column(compact, available),
        _explicit_dimension_concept(compact),
        scope.get("dimension"),
        params.get("dimension"),
        logic.get("group_by"),
    )
    metric = _first_text(_explicit_metric_column(compact, available), scope.get("metric"), params.get("metric"), logic.get("metric"), "核心指标")
    if not metric or not dimension or dimension == time_column:
        return {}
    time_prefix = _explicit_time_question_prefix(compact) or _combined_time_question_prefix(context, compact)
    if not time_prefix:
        return {}
    label = _dimension_question_label(dimension)
    return _action(
        action_id="grouped_time_comparison",
        label=f"按{label}比较时间变化",
        operation="aggregation",
        question=f"{time_prefix}按{label}汇总{_metric_question_label(metric)}，用于比较变化。",
        inherited_parameters=_generic_inherited_parameters_for_question(logic, params, compact),
        parameters={"metric": metric, "dimension": dimension},
        dimension=dimension,
    )


def _generic_same_analysis_new_time_action(context: Mapping[str, Any], compact: str = "") -> dict[str, Any]:
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    metric = _first_text(scope.get("metric"), params.get("metric"), logic.get("metric"), "核心指标")
    dimension = _first_text(scope.get("dimension"), params.get("dimension"), logic.get("group_by"))
    if not metric:
        return {}
    time_prefix = _explicit_time_question_prefix(compact)
    if not time_prefix:
        return {}
    label = _dimension_question_label(dimension) if dimension else ""
    question = f"{time_prefix}按{label}汇总{_metric_question_label(metric)}。" if label else f"{time_prefix}{_metric_question_label(metric)}是多少？"
    return _action(
        action_id="same_analysis_new_time",
        label="切换时间继续分析",
        operation="aggregation",
        question=question,
        inherited_parameters=_generic_inherited_parameters(logic, params),
        parameters={"metric": metric, **({"dimension": dimension} if dimension else {})},
        dimension=dimension,
    )


def _generic_focus_set_metric_aggregation_action(context: Mapping[str, Any], compact: str = "") -> dict[str, Any]:
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    available = [str(column) for column in params.get("available_columns") or []]
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    explicit_derived_metric = _explicit_sales_derived_metric(compact, available)
    explicit_metrics = _explicit_metric_columns(compact, available)
    explicit_metric = _first_text(
        explicit_derived_metric.get("name") if explicit_derived_metric else "",
        *(explicit_metrics or []),
        _explicit_metric_column(compact, available),
        _explicit_metric_concept(compact),
    )
    metric = _first_text(explicit_metric, scope.get("metric"), params.get("metric"), logic.get("metric"), "核心指标")
    metric_label = "和".join(_metric_question_label(item) for item in explicit_metrics) if len(explicit_metrics) > 1 else _metric_question_label(metric)
    metric_params = {"metric": metric, **({"metrics": explicit_metrics} if len(explicit_metrics) > 1 else {})}
    if explicit_derived_metric:
        metric_params.update(
            {
                "metric": str(explicit_derived_metric.get("name") or metric),
                "derived_metric": explicit_derived_metric,
                "aggregation": "sum",
            }
        )
        metric_params.update(_derived_metric_metadata(metric_params))
    time_column = _first_time_column(available)
    filter_prefix = _combined_filter_question_prefix(context, compact)
    time_prefix = _combined_time_question_prefix(context, compact)
    time_prefix = _dedupe_time_prefix(time_prefix, filter_prefix)
    scope_prefix = _combined_scope_question_prefix(time_prefix, filter_prefix)
    focus_dimension_for_time = next(
        (
            str(focus_set.get("dimension") or "")
            for focus_set in _context_focus_sets(context)
            if str(focus_set.get("dimension") or "") and _question_references_focus_set(compact, str(focus_set.get("dimension") or ""))
        ),
        "",
    )
    if time_column and (_has_multiple_month_reference(compact) or any(token in compact for token in ("每月", "每个月", "各月", "各月份", "按月", "按月份"))):
        series_label = _dimension_question_label(focus_dimension_for_time) if focus_dimension_for_time else ""
        return _action(
            action_id="aggregate_focus_set_metric",
            label="按时间汇总当前对象集合指标",
            operation="aggregation",
            question=(
                f"{scope_prefix}按{series_label}和月份展示{metric_label}。"
                if series_label
                else f"{scope_prefix}按月份展示{metric_label}。"
            ),
            inherited_parameters=_generic_inherited_parameters(logic, params),
            parameters={
                **metric_params,
                "dimension": "month",
                "time_column": time_column,
                "time_dimension": "month",
                "source_time_field": time_column,
                "time_bucket": "month",
                "capability_family": "time_series",
                **({"series_dimension": focus_dimension_for_time} if focus_dimension_for_time else {}),
            },
            dimension="month",
        )
    focus_dimension = next(
        (
            str(focus_set.get("dimension") or "")
            for focus_set in _context_focus_sets(context)
            if str(focus_set.get("dimension") or "") and _question_references_focus_set(compact, str(focus_set.get("dimension") or ""))
        ),
        "",
    )
    if focus_dimension and _asks_share_followup(compact):
        limit = _ranked_entity_share_limit(compact=compact, context=context, dimension=focus_dimension)
        share_metric = str(metric_params.get("metric") or metric)
        total_column = f"total_{share_metric}" if share_metric and share_metric != "核心指标" else "total_metric_value"
        share_column = f"{share_metric}_share" if share_metric and share_metric != "核心指标" else "share"
        return _action(
            action_id="ranked_entity_share",
            label="计算当前对象集合贡献占比",
            operation="top_k_share",
            question=f"{scope_prefix}按{_dimension_question_label(focus_dimension)}看{_metric_question_label(share_metric)}分别占总{_metric_question_label(share_metric)}的比例。",
            inherited_parameters=_generic_inherited_parameters_for_question(logic, params, compact),
            parameters={
                **metric_params,
                "dimension": focus_dimension,
                "ranking_metric": share_metric,
                "share_metric": share_metric,
                "share_column": share_column,
                "total_metric_column": total_column,
                "share_of_total": True,
                "share_denominator_scope": "all_rows" if _share_total_scope_requested(compact) else "current_context",
                "limit": limit,
            },
            dimension=focus_dimension,
        )
    if focus_dimension and any(token in compact for token in ("分别", "各自", "每个", "各个", "分组", "按", "返回前", "前5", "前五", "top")):
        return _action(
            action_id="aggregate_focus_set_metric",
            label="按当前对象集合汇总指标",
            operation="aggregation",
            question=f"{scope_prefix}按{_dimension_question_label(focus_dimension)}展示{metric_label}。",
            inherited_parameters=_generic_inherited_parameters(logic, params),
            parameters={**metric_params, "dimension": focus_dimension},
            dimension=focus_dimension,
        )
    return _action(
        action_id="aggregate_focus_set_metric",
        label="汇总当前对象集合指标",
        operation="aggregation",
        question=f"{scope_prefix}{metric_label}是多少？",
        inherited_parameters=_generic_inherited_parameters(logic, params),
        parameters=metric_params,
        dimension="",
    )


def _generic_grouped_distribution_action(context: Mapping[str, Any], compact: str = "") -> dict[str, Any]:
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    available = [str(column) for column in params.get("available_columns") or []]
    dimension = _explicit_grouped_dimension_column(compact, available) or _explicit_dimension_column(compact, available) or _explicit_dimension_concept(compact)
    explicit_metrics = _explicit_metric_columns(compact, available)
    metric = _first_text(*(explicit_metrics or []), _explicit_metric_column(compact, available), _explicit_metric_concept(compact), scope.get("metric"), params.get("metric"), logic.get("metric"), "核心指标")
    if not dimension or not metric:
        return {}
    metric_label = "和".join(_metric_question_label(item) for item in explicit_metrics) if len(explicit_metrics) > 1 else _metric_question_label(metric)
    filter_prefix = _combined_filter_question_prefix(context, compact)
    time_prefix = _combined_time_question_prefix(context, compact)
    time_prefix = _dedupe_time_prefix(time_prefix, filter_prefix)
    scope_prefix = _combined_scope_question_prefix(time_prefix, filter_prefix)
    reasonableness = _asks_reasonableness_boundary(compact)
    question = f"{scope_prefix}按{_dimension_question_label(dimension)}汇总{metric_label}。"
    if reasonableness:
        question = f"{scope_prefix}按{_dimension_question_label(dimension)}汇总{metric_label}，并说明是否合理需要哪些基准。"
    return _action(
        action_id="grouped_metric_distribution",
        label=f"按{_dimension_question_label(dimension)}汇总{metric_label}",
        operation="aggregation",
        question=question,
        inherited_parameters=_generic_inherited_parameters(logic, params),
        parameters={
            "metric": metric,
            **({"metrics": explicit_metrics} if len(explicit_metrics) > 1 else {}),
            "dimension": dimension,
            **({"requires_reasonableness_baseline": True} if reasonableness else {}),
            **({"share_of_total": True} if _asks_share_followup(compact) else {}),
        },
        dimension=dimension,
    )


def _generic_grouped_child_ranking_action(context: Mapping[str, Any], compact: str = "") -> dict[str, Any]:
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    available = [str(column) for column in params.get("available_columns") or []]
    child_dimension = _explicit_child_drilldown_dimension(compact, available)
    purchase_quantity_metric = _purchase_quantity_metric(compact, available)
    metric = _first_text(purchase_quantity_metric, _explicit_metric_column(compact, available), scope.get("metric"), params.get("metric"), logic.get("metric"), "核心指标")
    aggregation = "sum" if purchase_quantity_metric else str(params.get("aggregation") or "sum")
    inherited_parameters = _generic_inherited_parameters_for_question(logic, params, compact)
    if purchase_quantity_metric:
        inherited_parameters.pop("derived_metric", None)
    action = _action(
        action_id="grouped_child_ranking",
        label="在父级集合内查找子项 Top",
        operation="filtered_metric_ranking",
        question=f"{compact}？" if compact and not compact.endswith(("?", "？")) else compact,
        inherited_parameters=inherited_parameters,
        parameters={"metric": metric, "dimension": child_dimension, "aggregation": aggregation, "sort_order": "desc", "limit": _extract_limit_from_compact(compact, default=5)},
        dimension=child_dimension,
    )
    action["capability_family"] = "drilldown_followup"
    return action


def _explicit_child_drilldown_dimension(compact: str, available_columns: list[str]) -> str:
    available = [str(column) for column in available_columns if str(column or "").strip()]
    if any(token in compact for token in ("主要国家", "哪些国家", "哪个国家", "按国家", "国家")):
        column = _pick_column_by_aliases(available, ("country", "nation", "region", "area", "province", "city", "国家", "地区", "区域", "城市"))
        if column:
            return column
        return "country"
    explicit = _explicit_rank_target_dimension_column(compact, available) or _explicit_grouped_dimension_column(compact, available) or _explicit_dimension_column(compact, available)
    if explicit:
        return explicit
    if _explicit_stockcode_reference(compact):
        return _pick_column_by_aliases(available, ("stockcode", "stock_code", "sku", "sku_name")) or "stockcode"
    if any(token in compact for token in ("产品", "商品", "货品", "item", "product", "goods")):
        return _product_label_column(available) or "product"
    return _explicit_dimension_concept(compact)


def _purchase_quantity_metric(compact: str, available_columns: list[str]) -> str:
    if not any(token in compact for token in ("买最多", "买得最多", "购买最多", "卖最多", "销量", "销售数量", "购买数量", "数量最多", "卖得最多")):
        return ""
    return _pick_column_by_aliases([str(column) for column in available_columns], ("quantity", "qty", "数量", "件数", "volume"))


def _generic_ranked_entity_share_action(context: Mapping[str, Any], compact: str = "") -> dict[str, Any]:
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    available = [str(column) for column in params.get("available_columns") or []]
    explicit_derived_metric = _explicit_sales_derived_metric(compact, available)
    focus_dimension = next(
        (
            str(focus_set.get("dimension") or "")
            for focus_set in _context_focus_sets(context)
            if str(focus_set.get("dimension") or "")
            and (
                _question_has_specific_focus_reference(compact, str(focus_set.get("dimension") or ""))
                or _question_references_focus_set(compact, str(focus_set.get("dimension") or ""))
            )
        ),
        "",
    )
    dimension = _first_text(
        focus_dimension,
        _explicit_rank_target_dimension_column(compact, available),
        _explicit_dimension_column(compact, available),
        _explicit_dimension_concept(compact),
        scope.get("dimension"),
        params.get("dimension"),
        logic.get("group_by"),
    )
    inherited_metric = _first_text(scope.get("metric"), params.get("metric"), logic.get("metric"))
    explicit_metric = _explicit_metric_column(compact, available) or _explicit_metric_concept(compact)
    prefer_inherited_metric = bool(
        focus_dimension
        and inherited_metric
        and _compact_mentions_derived_metric(compact, {"derived_metric_name": inherited_metric})
    )
    metric = _first_text(
        explicit_derived_metric.get("name") if explicit_derived_metric else "",
        inherited_metric if prefer_inherited_metric else "",
        explicit_metric,
        inherited_metric,
        "核心指标",
    )
    if not dimension or not metric:
        return {}
    limit = _ranked_entity_share_limit(compact=compact, context=context, dimension=dimension)
    label = _dimension_question_label(dimension)
    metric_label = _metric_question_label(metric)
    share_column = f"{metric}_share" if metric and metric != "核心指标" else "share"
    total_column = f"total_{metric}" if metric and metric != "核心指标" else "total_metric_value"
    action_parameters = {
        "metric": metric,
        "ranking_metric": metric,
        "share_metric": metric,
        "share_column": share_column,
        "total_metric_column": total_column,
        "share_of_total": True,
        "share_denominator_scope": "all_rows" if _share_total_scope_requested(compact) else "current_context",
        "dimension": dimension,
        "limit": limit,
    }
    if explicit_derived_metric:
        action_parameters["derived_metric"] = explicit_derived_metric
        action_parameters["aggregation"] = "sum"
    elif isinstance(params.get("derived_metric"), Mapping) and params.get("derived_metric"):
        action_parameters["derived_metric"] = dict(params.get("derived_metric") or {})
    action_parameters.update(_derived_metric_metadata(action_parameters))
    action = _action(
        action_id="ranked_entity_share",
        label="计算已排名对象贡献占比",
        operation="top_k_share",
        question=f"按{label}看{metric_label}前{limit}名分别占总{metric_label}的比例。",
        inherited_parameters=_generic_inherited_parameters_for_question(logic, params, compact),
        parameters=action_parameters,
        dimension=dimension,
    )
    action["capability_family"] = "share_followup"
    return action


def _ranked_entity_share_limit(*, compact: str, context: Mapping[str, Any], dimension: str) -> int:
    explicit_limit = _extract_limit_from_compact(compact, default=0)
    if explicit_limit:
        return explicit_limit
    references_set = any(token in compact for token in ("这些", "它们", "上述", "分别", "各自", "每个", "各个", "Top对象", "top对象"))
    if references_set:
        for focus_set in _context_focus_sets(context):
            if str(focus_set.get("dimension") or "") != dimension:
                continue
            values = focus_set.get("values")
            if isinstance(values, list) and values:
                return len(values)
            limit = _positive_int(focus_set.get("limit"))
            if limit:
                return limit
    return 1


def _asks_extreme_review(compact: str) -> bool:
    return any(token in compact for token in ("复核", "高点", "低点", "峰值", "异常高", "异常低", "波动"))


def _asks_source_drilldown(compact: str) -> bool:
    return any(
        token in compact
        for token in (
            "拆分",
            "来源",
            "拉动",
            "驱动",
            "构成",
            "组成",
            "下钻",
            "按客户",
            "按产品",
            "按品类",
            "客户贡献",
            "产品贡献",
            "品类贡献",
            "哪个客户",
            "哪些客户",
            "客户是哪些",
            "客户有哪些",
            "哪个产品",
            "哪种产品",
            "哪些产品",
            "产品是哪些",
            "产品有哪些",
            "哪个品类",
            "哪些品类",
            "品类是哪些",
            "品类有哪些",
            "细分市场",
            "客户细分",
            "客户群体",
            "客户分区",
            "客户段",
            "哪个客群",
            "哪些客群",
            "客群排名",
            "客户是谁",
            "客户是哪个",
            "利润最高的客户",
            "利润最多的客户",
            "个客户",
            "名客户",
            "产品是谁",
            "产品是什么",
            "产品是哪",
            "的产品是什么",
            "的产品是哪",
            "个产品",
            "名产品",
        )
    )


def _asks_dimension_switch(compact: str) -> bool:
    return any(token in compact for token in ("按客户", "按产品", "按品类", "也看", "换成"))


def _asks_top_or_gap_followup(compact: str) -> bool:
    return _asks_rank_position_followup(compact) or any(
        token in compact
        for token in (
            "top",
            "Top",
            "排名",
            "排行",
            "前",
            "最高",
            "最低",
            "最多",
            "最少",
            "最大",
            "最小",
            "最集中",
            "集中",
            "差距",
            "差值",
            "差多少",
            "少多少",
            "多多少",
            "比较",
            "继续看",
        )
    )


def _asks_explicit_ranking_followup(compact: str) -> bool:
    return _asks_rank_position_followup(compact) or any(token in compact for token in ("top", "Top", "排名", "排行", "最高", "最低", "前"))


def _asks_explicit_trend_language(compact: str) -> bool:
    return any(token in compact for token in ("趋势", "变化趋势", "如何变化", "怎么变化", "怎样变化", "走势", "变化"))


def _asks_quality_followup(compact: str) -> bool:
    if _asks_negative_value_quality(compact):
        return True
    if any(token in compact for token in ("数据质量", "质量问题", "质量如何", "质量怎么样", "缺失", "重复", "异常值", "有没有异常", "有异常吗", "是否异常", "是否有异常", "是否存在异常", "异常波动", "是否存在数据质量")):
        return True
    if any(token in compact for token in ("异常高", "异常低", "异常偏高", "异常偏低")) and not any(token in compact for token in ("复核", "高点", "低点", "峰值")):
        return True
    return False


def _asks_metric_anomaly_followup(compact: str) -> bool:
    anomaly_signal = "异常" in compact or _asks_negative_value_quality(compact)
    return anomaly_signal and any(
        token in compact
        for token in (
            "销售额",
            "销售金额",
            "订单金额",
            "订单总额",
            "订单总金额",
            "工单量",
            "工单数",
            "利润",
            "利润率",
            "毛利率",
            "收入",
            "金额",
            "指标",
        )
    )


def _asks_negative_value_quality(compact: str) -> bool:
    return any(token in compact for token in ("负值", "负数", "为负", "出现负", "小于0", "小于零", "低于0", "低于零", "<0"))


def _asks_grouped_distribution_followup(compact: str) -> bool:
    if _asks_top_or_gap_followup(compact):
        return False
    distribution_signal = any(token in compact for token in ("分布", "占比", "比例", "份额", "构成", "组成", "是否合理", "合不合理"))
    business_quality_signal = any(token in compact for token in ("质量如何", "质量怎么样")) and not any(
        token in compact for token in ("数据质量", "质量问题", "异常", "缺失", "重复", "清洗")
    )
    if not distribution_signal and not business_quality_signal:
        return False
    if not _explicit_dimension_concept(compact):
        return False
    return bool(_explicit_metric_concept(compact) or any(token in compact for token in ("销售", "收入", "金额", "利润", "订单", "客户", "工单", "指标", "数据")))


def _asks_grouped_child_ranking_followup(compact: str) -> bool:
    grouped_parent = any(token in compact for token in ("每个", "各个", "各自", "各"))
    child_question = any(token in compact for token in ("哪个", "哪些", "哪类", "哪种", "哪几个"))
    ranking_signal = any(token in compact for token in ("最高", "最低", "最多", "最少", "最大", "最小", "排名", "排行", "Top", "top"))
    parent_set_signal = any(token in compact for token in ("前", "排名", "排行", "Top", "top", "这些", "这几个", "上述"))
    child_dimension_signal = any(token in compact for token in ("产品", "商品", "sku", "SKU"))
    parent_scope_signal = parent_set_signal or any(token in compact for token in ("它下面", "其下", "里面", "里"))
    return ranking_signal and parent_scope_signal and child_dimension_signal and grouped_parent and child_question


def _asks_referent_child_dimension_breakdown(compact: str) -> bool:
    references_previous_set = any(token in compact for token in ("这些", "这几个", "上述", "它们", "Top", "top", "TOP", "前几个"))
    references_previous_set = references_previous_set or bool(
        re.search(r"(?:这|这些|上述)?前(?:\d+|[一二两三四五六七八九十]+)", compact)
    )
    references_previous_set = references_previous_set or bool(re.search(r"这(?:\d+|[一二两三四五六七八九十]+)个", compact))
    if not references_previous_set:
        return False
    child_question = any(token in compact for token in ("哪个", "哪些", "哪几个", "主要", "分别", "各自", "每个", "各个", "列出", "拆分", "分布"))
    child_dimension = bool(_explicit_dimension_concept(compact))
    return child_question and child_dimension


def _asks_reasonableness_boundary(compact: str) -> bool:
    return any(token in compact for token in ("是否合理", "合不合理", "合理", "相比", "对比", "比较"))


def _asks_profit_rate_followup(compact: str) -> bool:
    return "利润率" in compact or ("profit" in compact.lower() and any(token in compact.lower() for token in ("rate", "margin")))


def _asks_profit_rate_ranking_request(compact: str) -> bool:
    return any(
        token in compact
        for token in (
            "利润率最高",
            "毛利率最高",
            "利润率最低",
            "毛利率最低",
            "利润率排名",
            "毛利率排名",
            "按利润率",
            "按毛利率",
            "找出利润率最高",
            "找出毛利率最高",
        )
    )


def _asks_profit_rate_compound_breakdown_then_ranking(compact: str) -> bool:
    if not _asks_profit_rate_ranking_request(compact):
        return False
    if not any(token in compact for token in ("各月", "每月", "每个月", "按月", "按月份", "各月份")):
        return False
    if not any(token in compact for token in ("并", "再", "然后", "同时", "接着", "顺便", "找出")):
        return False
    entity_group_tokens = (
        "各城市",
        "每个城市",
        "各地区",
        "每个地区",
        "各区域",
        "每个区域",
        "各服务线",
        "每个服务线",
        "各业务线",
        "每个业务线",
        "各客户",
        "每个客户",
        "各产品",
        "每个产品",
    )
    return any(token in compact for token in entity_group_tokens)


def _asks_scalar_metric_followup(compact: str) -> bool:
    if _asks_rank_position_followup(compact) or _asks_top_or_gap_followup(compact) or _asks_time_trend_followup(compact):
        return False
    return any(token in compact for token in ("是多少", "多少", "几", "数值", "具体值", "当前值", "算一下"))


def _asks_focus_set_metric_scalar(compact: str, context: Mapping[str, Any]) -> bool:
    if _asks_time_trend_followup(compact) or _asks_growth_ranking_followup(compact):
        return False
    if not any(token in compact for token in ("是多少", "多少", "总", "合计", "汇总")):
        return False
    for focus_set in _context_focus_sets(context):
        dimension = str(focus_set.get("dimension") or "")
        if dimension and _question_references_focus_set(compact, dimension):
            return True
    return False


def _asks_time_trend_followup(compact: str) -> bool:
    if _asks_grouped_time_comparison_followup(compact):
        return False
    if "排名" in compact and any(token in compact for token in ("有变化", "变化吗", "是否变化", "有没有变化", "相比有变化")):
        return False
    if any(token in compact for token in ("排名变化", "排名的变化", "排名是否变化", "名次变化", "位次变化")) and any(
        token in compact for token in ("这些", "这几个", "上述", "前3", "前三")
    ):
        return False
    if (
        "排名" in compact
        and any(token in compact for token in ("变化", "相比", "相较", "对比"))
        and any(token in compact for token in ("城市", "产品", "客户", "客群", "客户群体", "服务线"))
        and not _asks_explicit_trend_language(compact)
    ):
        return False
    if "排名" in compact and any(token in compact for token in ("各月", "每月", "每个月", "按月", "按月份", "各月份")) and not _asks_explicit_trend_language(compact):
        return False
    if any(token in compact for token in ("趋势", "按月份", "按月", "按时间", "时间变化", "月度变化", "如何变化", "怎么变化", "怎样变化", "每月", "每个月", "各月", "各月份")):
        return True
    if _explicit_time_drilldown(compact):
        return True
    if any(token in compact for token in ("哪些月份", "哪个月份", "哪几个月", "哪些月")) and any(token in compact for token in ("最高", "最多", "最活跃", "活跃")):
        return True
    if "逐月" in compact and any(token in compact for token in ("增长", "下降", "上升", "变化")):
        return True
    if any(token in compact for token in ("增长还是下降", "上升还是下降", "升还是降")):
        return True
    if _has_multiple_month_reference(compact) and any(token in compact for token in ("分别", "变化", "走势", "趋势")):
        return True
    return "变化" in compact and any(token in compact for token in ("月", "季度", "时间", "期间", "这几个月", "这三个月", "这两个月"))


def _explicit_time_drilldown(compact: str) -> bool:
    lowered = str(compact or "").lower()
    has_time_target = any(token in lowered for token in ("invoicedate", "date", "time")) or any(token in compact for token in ("日期", "时间"))
    if not has_time_target:
        return False
    return any(token in compact for token in ("下钻", "拆分", "继续", "按"))


def _asks_grouped_time_comparison_followup(compact: str) -> bool:
    if not _has_multiple_month_reference(compact):
        return False
    grouped_entity = any(
        token in compact
        for token in (
            "各城市",
            "每个城市",
            "按城市",
            "各地区",
            "每个地区",
            "按地区",
            "各客户",
            "每个客户",
            "按客户",
            "各产品",
            "每个产品",
            "按产品",
            "各服务线",
            "每个服务线",
            "按服务线",
            "各业务线",
            "每个业务线",
            "按业务线",
            "各客户细分",
            "每个客户细分",
            "按客户细分",
            "各客群",
            "每个客群",
            "按客群",
        )
    )
    if not grouped_entity:
        return False
    return any(token in compact for token in ("相比", "相较", "对比", "比较", "变化", "差异", "增减"))


def _asks_same_metric_adjacent_comparison_followup(compact: str) -> bool:
    if not any(token in compact for token in ("同一指标", "这个指标", "该指标", "同个指标")):
        return False
    return any(token in compact for token in ("相邻时间段", "相邻期间", "相关对象", "对比", "比较", "相比", "相较"))


def _has_multiple_month_reference(compact: str) -> bool:
    if re.search(r"20\d{2}[-/]\d{1,2}(?:到|至|~|—|和|与)20\d{2}[-/]\d{1,2}", compact):
        return True
    if re.search(r"\d{1,2}月(?:到|至|-|~|—|和|与)\d{1,2}月", compact):
        return True
    return len(re.findall(r"\d{1,2}月", compact)) >= 2


def _asks_metric_breakdown_followup(compact: str) -> bool:
    if _asks_top_or_gap_followup(compact) and not any(token in compact for token in ("分别", "各自", "每个", "各个")):
        return False
    grouped_display = any(
        token in compact
        for token in (
            "各城市",
            "每个城市",
            "各地区",
            "每个地区",
            "各区域",
            "每个区域",
            "各服务线",
            "每个服务线",
            "各业务线",
            "每个业务线",
            "各客户",
            "每个客户",
            "各产品",
            "每个产品",
        )
    ) and any(token in compact for token in ("如何", "怎样", "怎么样", "情况", "表现", "汇总", "展示", "显示"))
    if grouped_display:
        return bool(_explicit_dimension_concept(compact))
    if not any(token in compact for token in ("分别", "各自", "每个", "各个")):
        return False
    return bool(_explicit_dimension_concept(compact))


def _asks_growth_rate_followup(compact: str) -> bool:
    if _asks_growth_ranking_followup(compact):
        return False
    if "排名" in compact and any(token in compact for token in ("城市", "产品", "客户", "客群", "客户群体", "服务线")):
        return False
    return any(token in compact for token in ("增长率", "增长最快", "增长最多", "增速", "变化最快", "相比", "相较"))


def _references_growth_entity_set(compact: str) -> bool:
    return any(
        token in compact
        for token in (
            "增长最快城市",
            "增长最快的城市",
            "增长最多城市",
            "增长最多的城市",
            "增速最快城市",
            "增速最快的城市",
            "增长最快客户",
            "增长最快的客户",
            "增长最快产品",
            "增长最快的产品",
        )
    )


def _asks_growth_ranking_followup(compact: str) -> bool:
    return any(token in compact for token in ("增长最快", "增长最多", "增速最快", "增幅最大", "提升最快", "提升最多", "下降最快", "下降最多", "增长趋势最明显", "增长最明显", "变化最明显", "变化最大", "变化最多", "变动最大", "变动最多", "波动最大", "波动最多")) and any(
        token in compact
        for token in (
            "哪个城市",
            "哪些城市",
            "城市是哪个",
            "城市是哪",
            "城市有哪些",
            "城市是哪些",
            "这些城市",
            "几个城市",
            "个城市",
            "城市中",
            "城市里",
            "哪个产品",
            "哪些产品",
            "产品是哪个",
            "产品是哪",
            "产品有哪些",
            "产品是哪些",
            "这些产品",
            "几款产品",
            "个产品",
            "产品中",
            "产品里",
            "哪个客户",
            "哪些客户",
            "客户是哪个",
            "客户是哪",
            "客户是谁",
            "客户有哪些",
            "客户是哪些",
            "这些客户",
            "几个客户",
            "个客户",
            "客户中",
            "客户里",
            "哪个服务线",
            "哪些服务线",
            "服务线是哪个",
            "服务线是哪",
            "服务线有哪些",
            "服务线是哪些",
            "这些服务线",
            "几个服务线",
            "个服务线",
            "服务线中",
            "服务线里",
            "业务线中",
            "业务线里",
            "业务线是哪个",
            "业务线是哪",
            "业务线有哪些",
            "业务线是哪些",
        )
    )


def _asks_change_delta_ranking(compact: str) -> bool:
    return any(token in compact for token in ("变化最大", "变化最多", "变动最大", "变动最多", "波动最大", "波动最多"))


def _asks_rank_retention_followup(compact: str) -> bool:
    rank_retention = any(token in compact for token in ("保持第一", "还是第一", "仍然第一", "依然第一", "还排第一", "还排名第一", "是否第一"))
    time_shift = bool(re.search(r"(?:20\d{2}年)?\d{1,2}月份?", compact)) or any(token in compact for token in ("下个月", "上个月", "下一月", "上一月"))
    return rank_retention and time_shift


def _asks_same_analysis_for_new_time(compact: str) -> bool:
    cleaned = str(compact or "").strip("？?。.!！")
    return bool(re.fullmatch(r"(?:那|那么|再看|换成|改看)?(?:20\d{2}年)?\d{1,2}月(?:呢|如何|怎么样)?", cleaned))


def _asks_share_followup(compact: str) -> bool:
    return any(
        token in compact
        for token in (
            "占比",
            "占总",
            "占整体",
            "占全",
            "占多少",
            "贡献率",
            "贡献占比",
            "贡献比例",
            "比例",
            "份额",
            "share",
            "percentage",
            "proportion",
        )
    )


def _asks_extreme_time_scoped_dimension_drilldown(compact: str) -> bool:
    has_extreme_time = (
        any(token in compact for token in ("哪个月份", "哪个月", "哪月份", "哪月", "几月份", "几月"))
        and any(token in compact for token in ("最高", "最大", "最多", "最低", "最小", "最少"))
    )
    if not has_extreme_time:
        return False
    return any(
        re.search(pattern, compact)
        for pattern in (
            r"前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位|条)?(?:大)?的?(?:客户|城市|产品|商品|服务线|业务线|品类|门店|区域|地区)",
            r"(?:哪个|哪些|哪几个)(?:客户|城市|产品|商品|服务线|业务线|品类|门店|区域|地区)",
        )
    )


def _asks_ranked_entity_share_followup(compact: str) -> bool:
    if not _asks_share_followup(compact):
        return False
    top_set_signal = any(
        token in compact
        for token in (
            "这些Top",
            "这些top",
            "这些TOP",
            "Top对象",
            "top对象",
            "前几名",
            "前几",
            "前几位",
            "排名前",
            "前3",
            "前三",
            "Top3",
            "top3",
            "它们",
            "这些",
            "上述",
        )
    )
    single_rank_signal = any(token in compact for token in ("排名第一", "排名第1", "第一名", "第1名", "Top1", "top1", "首位", "最高的", "最多的"))
    if not (top_set_signal or single_rank_signal):
        return False
    return bool(
        _explicit_dimension_concept(compact)
        or any(token in compact for token in ("对象", "客户", "城市", "产品", "服务线", "业务线", "客群", "细分"))
        or top_set_signal
    )


def _asks_ranked_set_metric_display_followup(compact: str) -> bool:
    if not any(token in compact for token in ("分别", "各自", "每个", "各个", "是多少", "多少")):
        return False
    if not any(token in compact for token in ("排名前", "排名前三", "排名前3", "前3", "前三", "前五", "前5", "Top", "top", "这些")):
        return False
    return bool(_explicit_dimension_concept(compact) or any(token in compact for token in ("城市", "客户", "产品", "服务线", "业务线", "客群", "细分")))


def _asks_topn_entity_count_ranking_display(compact: str) -> bool:
    if not any(token in compact for token in ("排名前", "前3", "前三", "前5", "前五", "Top", "top")):
        return False
    if not any(token in compact for token in ("客户数量", "客户数", "客户总数", "总客户数", "客户个数", "订单数量", "订单数", "订单量", "购买次数", "下单次数")):
        return False
    return any(token in compact for token in ("城市", "客户", "产品", "商品", "服务线", "业务线", "地区", "区域", "国家"))


def _extract_limit_from_compact(compact: str, *, default: int = 3) -> int:
    match = re.search(r"(?:前|top|Top)\s*(\d+|[一二两三四五六七八九十]+)", compact)
    if match:
        raw = match.group(1)
        return int(raw) if str(raw).isdigit() else (_small_chinese_number(str(raw)) or default)
    rank = re.search(r"排名第?(\d+|[一二两三四五六七八九十]+)", compact)
    if rank:
        raw = rank.group(1)
        return int(raw) if str(raw).isdigit() else (_small_chinese_number(str(raw)) or default)
    if any(token in compact for token in ("排名第一", "第一名", "第1名", "Top1", "top1", "首位")):
        return 1
    return default


def _rank_position_question_phrase(compact: str) -> str:
    match = re.search(r"排名(?:第)?(\d+|[一二两三四五六七八九十]+)", compact)
    if match:
        return f"排名第{match.group(1)}"
    for token in ("第一", "第二", "第三", "第四", "第五", "第六", "第七", "第八", "第九", "第十"):
        if token in compact:
            return f"排名{token}"
    return ""


def _asks_rank_position_followup(compact: str) -> bool:
    return bool(re.search(r"(?:排|排名|排行|名次|位次)(?:在)?第?几", compact)) or any(
        token in compact for token in ("第几名", "排第几", "排名第几", "排行第几")
    )


def _asks_focus_entity_rank_position_followup(compact: str, context: Mapping[str, Any]) -> bool:
    if not _asks_rank_position_followup(compact):
        return False
    dimension, value = _rank_position_focus_target(context, compact)
    return bool(dimension and value not in (None, "", [], {}))


def _is_self_contained_ranking_request(compact: str, context: Mapping[str, Any]) -> bool:
    if not _asks_top_or_gap_followup(compact):
        return False
    if _asks_time_trend_followup(compact):
        return False
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    current_dimension = _first_text(scope.get("dimension"), params.get("dimension"), logic.get("group_by"))
    current_label = _dimension_question_label(current_dimension)
    available = [str(column) for column in params.get("available_columns") or []]
    explicit_dimension = _explicit_dimension_column(compact, available) or _explicit_dimension_concept(compact)
    explicit_metric = _explicit_metric_column(compact, available) or _explicit_metric_concept(compact)
    has_contextual_scope_reference = _question_has_specific_focus_reference(compact, current_dimension)
    filters = scope.get("filters") if isinstance(scope.get("filters"), Mapping) else {}
    for column, value in filters.items():
        if value in (None, "", [], {}) or not _looks_like_entity_filter_column(str(column)):
            continue
        if _question_has_specific_focus_reference(compact, str(column)) or _question_references_focus_set(compact, str(column)):
            has_contextual_scope_reference = True
            break
    if not has_contextual_scope_reference:
        for focus_set in _context_focus_sets(context):
            dimension = str(focus_set.get("dimension") or "")
            if dimension and (
                _question_has_specific_focus_reference(compact, dimension)
                or _question_references_focus_set(compact, dimension)
            ):
                has_contextual_scope_reference = True
                break
    if explicit_dimension and explicit_metric and (
        not current_dimension
        or explicit_dimension != current_dimension
        and not has_contextual_scope_reference
    ):
        return True
    if current_label and any(token in compact for token in (f"这些{current_label}", f"这几个{current_label}", f"上述{current_label}")):
        return False
    if _question_references_focus_entity(compact, current_dimension):
        return False
    for column, value in filters.items():
        if (
            value not in (None, "", [], {})
            and _looks_like_entity_filter_column(str(column))
            and (_question_references_focus_entity(compact, str(column)) or _question_references_focus_set(compact, str(column)))
        ):
            return False
    demonstrative_focus_reference = any(token in compact for token in ("这些", "这几个", "上述", "这3", "这三", "这五", "这前")) or bool(
        re.search(r"前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?", compact)
    )
    for focus_set in _context_focus_sets(context):
        dimension = str(focus_set.get("dimension") or "")
        if dimension and _question_references_rank_target_focus_entity(compact, dimension):
            return False
        if dimension and demonstrative_focus_reference and _question_references_focus_set(compact, dimension):
            return False
    if explicit_dimension and explicit_metric:
        return True
    return bool(explicit_dimension and current_dimension and explicit_dimension != current_dimension)


def _is_retail_context(operation: str) -> bool:
    return str(operation or "").startswith("retail_")


def _followup_dimension(compact: str) -> str:
    if "产品" in compact or "sku" in compact.lower() or "SKU" in compact:
        return "sku_name"
    if "品类" in compact:
        return "ctg_name"
    if "客户" in compact:
        return "cust_name"
    return ""


def _generic_followup_dimension(compact: str, available_columns: list[str], *, current_dimension: str = "") -> str:
    available = [str(column) for column in available_columns if str(column or "").strip()]
    rank_target = _explicit_rank_target_dimension_column(compact, available)
    if rank_target:
        return rank_target
    grouped_dimension = _explicit_grouped_dimension_column(compact, available)
    if grouped_dimension:
        return grouped_dimension
    if any(token in compact for token in ("哪个月", "哪月", "几月", "哪个月份", "哪些月份", "月份最高", "月份最低", "月份最多", "月份最少", "月份是", "月度排名", "各月", "每月", "每个月")):
        if str(current_dimension or "") == "month":
            return "month"
        column = _pick_column_by_aliases(available, ("month", "月份", "月度", "date", "time", "日期", "时间"))
        if column:
            return column
        return "month"
    alias_groups = [
        (("客户细分", "客户群", "客户群体", "客户分区", "客户分段", "客户段", "客群", "segment", "细分", "分段"), ("segment", "customer_segment", "客户细分", "客户群", "客户群体", "客户分区", "客户分段", "客户段", "客群", "细分", "分段"), "segment"),
        (("StockCode", "stockcode"), ("stockcode", "stock_code", "sku", "sku_name"), "stockcode"),
        (("产品", "商品", "货品", "item", "product", "goods"), ("description", "desc", "product_name", "product_label", "item_name", "goods_name", "product", "item", "goods", "产品", "商品", "品名", "描述", "stockcode", "stock_code", "sku", "sku_name"), "product"),
        (("客户", "顾客"), ("customer", "cust", "client", "buyer", "客户", "顾客"), "customer"),
        (("国家", "城市", "地区", "区域", "地域", "country", "region"), ("country", "nation", "region", "area", "province", "city", "国家", "地区", "区域", "城市"), "country"),
        (("门店", "店铺", "门店"), ("store", "shop", "门店", "店铺"), "store"),
        (("品类", "类别", "类目"), ("category", "ctg", "type", "品类", "类别", "类目"), "category"),
        (("团队", "小组", "部门"), ("team", "group", "department", "团队", "小组", "部门"), "team"),
        (("服务线", "业务线", "渠道"), ("service_line", "line", "channel", "渠道", "服务线", "业务线"), "service_line"),
    ]
    for triggers, aliases, fallback_concept in alias_groups:
        if _contains_any_token(compact, triggers):
            column = _pick_column_by_aliases(available, aliases)
            if column:
                return column
            return fallback_concept
    return _first_alternate_dimension_column(available, current_dimension=current_dimension)


def _contextual_filter_question_prefix(context: Mapping[str, Any], compact: str) -> str:
    for focus_set in _context_focus_sets(context):
        dimension = str(focus_set.get("dimension") or "")
        if dimension and _question_references_focus_set(compact, dimension):
            if _looks_like_new_explicit_topn_request(compact, dimension):
                continue
            prefix = _focus_set_question_prefix(focus_set, compact=compact)
            if prefix:
                return prefix
    matched: list[tuple[str, Any, str]] = []
    scoped_filters: list[tuple[str, Any, str]] = []
    for column, value, source in _contextual_focus_filters(context):
        if _looks_like_new_explicit_topn_request(compact, str(column)):
            continue
        if source == "filter":
            scoped_filters.append((column, value, source))
        if not _question_references_focus_entity(compact, column) and not (source == "filter" and _question_references_focus_set(compact, column)):
            continue
        matched.append((column, value, source))
    if matched:
        parts: list[str] = []
        seen = set()
        include_scoped_filters = bool(scoped_filters) or _asks_explicit_trend_language(compact)
        for column, value, source in [*(scoped_filters if include_scoped_filters else []), *matched]:
            label = _dimension_question_label(column)
            value_text = _filter_value_text(value)
            key = (str(column), value_text)
            if not label or not value_text or key in seen:
                continue
            seen.add(key)
            parts.append(f"{value_text}{label}")
        if parts:
            return f"筛选{'、'.join(parts)}的数据，"
    for column, value, source in _contextual_focus_filters(context):
        if not _question_references_focus_entity(compact, column) and not (source == "filter" and _question_references_focus_set(compact, column)):
            continue
        label = _dimension_question_label(column)
        value_text = _filter_value_text(value)
        if value_text:
            return f"筛选{value_text}{label}的数据，"
    return ""


def _contextual_filter_question_prefix_excluding_dimension(context: Mapping[str, Any], excluded_dimension: str) -> str:
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    filters = scope.get("filters") if isinstance(scope.get("filters"), Mapping) else {}
    parts: list[str] = []
    seen = set()
    for column, value in filters.items():
        column_text = str(column)
        if column_text == excluded_dimension:
            continue
        if re.search(r"date|day|month|year|week|time|日期|时间|月份|年份|周", column_text, re.I):
            continue
        if not _looks_like_entity_filter_column(column_text) or value in (None, "", [], {}):
            continue
        label = _dimension_question_label(column_text)
        value_text = _filter_value_text(value)
        key = (column_text, value_text)
        if not label or not value_text or key in seen:
            continue
        seen.add(key)
        parts.append(f"{value_text}{label}")
    return f"筛选{'、'.join(parts)}的数据，" if parts else ""


def _explicit_candidate_topn_question_prefix(compact: str, available_columns: list[str]) -> str:
    if not any(token in compact for token in ("前", "排名", "排行", "Top", "top")):
        return ""
    dimension = _explicit_rank_target_dimension_column(compact, available_columns) or _explicit_dimension_column(compact, available_columns) or _explicit_dimension_concept(compact)
    label = _dimension_question_label(dimension)
    if not label:
        return ""
    topn = re.search(rf"(?:排名|排行)?前(\d+|[一二两三四五六七八九十]+)(?:个|名|位)?(?:大)?的?{label}", compact)
    if not topn:
        return ""
    prefix_text = compact[: topn.start()]
    metric = _explicit_metric_column(prefix_text, available_columns) or _explicit_metric_concept(prefix_text)
    if not metric:
        return ""
    raw_limit = topn.group(1)
    limit = int(raw_limit) if str(raw_limit).isdigit() else (_small_chinese_number(str(raw_limit)) or 0)
    if limit <= 0:
        return ""
    return f"{_explicit_time_question_prefix(compact)}{_metric_question_label(metric)}排名前{limit}的{label}中，"


def _combined_filter_question_prefix(context: Mapping[str, Any], compact: str) -> str:
    return _explicit_entity_filter_question_prefix(context, compact) or _contextual_filter_question_prefix(context, compact)


def _looks_like_new_explicit_topn_request(compact: str, dimension: str) -> bool:
    time_start = _explicit_time_match_start(compact)
    if time_start is None:
        return False
    label = _dimension_question_label(dimension)
    if not label:
        return False
    if any(token in compact for token in ("这些", "这几个", "上述", "刚才", "上一轮", "这前", "这3", "这三", "那")):
        return False
    topn = re.search(rf"(?:排名|排行)?前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?(?:大)?的?{label}", compact)
    if topn and re.match(r"(?:中|里|内|之中|里面|范围内)", compact[topn.end() :]):
        return False
    return bool(topn and time_start <= topn.start())


def _explicit_time_match_start(compact: str) -> int | None:
    patterns = (
        r"20\d{2}年\d{1,2}月(?:到|至|-|~|—)(?:20\d{2}年)?\d{1,2}月",
        r"\d{1,2}月(?:到|至|-|~|—)\d{1,2}月",
        r"20\d{2}年\d{1,2}月",
        r"\d{1,2}月份?",
    )
    starts = [match.start() for pattern in patterns for match in [re.search(pattern, compact)] if match]
    return min(starts) if starts else None


def _dedupe_time_prefix(time_prefix: str, filter_prefix: str) -> str:
    if not time_prefix or not filter_prefix:
        return time_prefix
    normalized_time = time_prefix.strip(" ，,")
    return "" if normalized_time and normalized_time in filter_prefix else time_prefix


def _combined_scope_question_prefix(time_prefix: str, filter_prefix: str) -> str:
    if filter_prefix and time_prefix and "排名前" in filter_prefix:
        return f"{filter_prefix}{time_prefix}"
    return f"{time_prefix}{filter_prefix}"


def _explicit_entity_filter_question_prefix(context: Mapping[str, Any], compact: str) -> str:
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    dimension = _first_text(scope.get("dimension"), params.get("dimension"), logic.get("group_by"))
    if not dimension or not _looks_like_entity_filter_column(dimension):
        return ""
    metric_terms = (
        "销售额",
        "销售金额",
        "订单总额",
        "订单金额",
        "订单额",
        "总金额",
        "总额",
        "金额",
        "收入",
        "营收",
        "利润率",
        "利润",
        "指标",
        "数据",
    )
    match = re.search(rf"([\u4e00-\u9fffA-Za-z0-9_-]{{2,20}})的(?:{'|'.join(metric_terms)})", compact)
    if not match:
        return ""
    value = match.group(1).strip()
    if not value or _looks_like_generic_reference(value) or _looks_like_time_scope_reference(value):
        return ""
    return f"筛选{value}{_dimension_question_label(dimension)}的数据，"


def _contextual_focus_filters(context: Mapping[str, Any]) -> list[tuple[str, Any, str]]:
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    operation = str(context.get("operation") or "")
    candidates: list[tuple[str, Any, str]] = []
    filters = scope.get("filters") if isinstance(scope.get("filters"), Mapping) else {}
    for column, value in filters.items():
        if _looks_like_entity_filter_column(str(column)) and value not in (None, "", [], {}):
            candidates.append((str(column), value, "filter"))
    dimension = str(scope.get("dimension") or "").strip()
    last_result = context.get("last_result") if isinstance(context.get("last_result"), Mapping) else {}
    first_row = last_result.get("first_row") if isinstance(last_result.get("first_row"), Mapping) else {}
    value = first_row.get(dimension) if dimension else None
    if dimension and value not in (None, "", [], {}) and _looks_like_entity_filter_column(dimension) and _looks_like_ranking(operation, ""):
        candidates.append((dimension, value, "result"))
    return candidates


def _filter_value_text(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return "、".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, Mapping):
        return ""
    return str(value).strip()


def _context_focus_sets(context: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    focus_sets = context.get("focus_sets")
    if not isinstance(focus_sets, list):
        return []
    return [item for item in focus_sets if isinstance(item, Mapping)]


def _focus_set_artifact_id(context: Mapping[str, Any], focus_set: Mapping[str, Any]) -> str:
    dimension = str(focus_set.get("dimension") or "")
    metric = str(focus_set.get("metric") or "")
    values = [str(value) for value in focus_set.get("values") or [] if value not in (None, "")]
    artifacts = context.get("active_result_artifacts") if isinstance(context.get("active_result_artifacts"), list) else []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            continue
        if str(artifact.get("dimension") or "") != dimension:
            continue
        if metric and str(artifact.get("metric") or "") != metric:
            continue
        artifact_values = [str(value) for value in artifact.get("values") or [] if value not in (None, "")]
        if values and artifact_values and values != artifact_values:
            continue
        artifact_id = str(artifact.get("artifact_id") or "")
        if artifact_id:
            return artifact_id
    return str(context.get("last_ranking_artifact_id") or context.get("last_result_artifact_id") or "")


def _focus_set_question_prefix(focus_set: Mapping[str, Any], *, compact: str = "") -> str:
    dimension = str(focus_set.get("dimension") or "")
    if not dimension:
        return ""
    label = _dimension_question_label(dimension)
    metric = str(focus_set.get("metric") or "").strip()
    limit = _focus_set_requested_limit(compact) or int(focus_set.get("limit") or 0)
    filters = focus_set.get("filters") if isinstance(focus_set.get("filters"), Mapping) else {}
    time_prefix = ""
    for column, value in filters.items():
        time_prefix = _time_filter_value_prefix(str(column), value)
        if time_prefix:
            break
    if metric and limit > 0:
        time_scope = time_prefix.strip("，, ")
        scope_prefix = time_scope if not time_scope or time_scope.startswith("在") else f"在{time_scope}"
        return f"{scope_prefix or '在'}{_metric_question_label(metric)}排名前{limit}的{label}中，"
    values = focus_set.get("values")
    if isinstance(values, list) and values:
        value_text = _filter_value_text(values[:10])
        if value_text:
            return f"筛选{value_text}{label}的数据，"
    return ""


def _focus_set_requested_limit(compact: str) -> int | None:
    patterns = (
        r"排名前(\d+|[一二两三四五六七八九十]+)",
        r"前(\d+|[一二两三四五六七八九十]+)(?:个|名|位)?",
        r"这(\d+|[一二两三四五六七八九十]+)(?:个|名|位)",
        r"top(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, compact, re.I)
        if not match:
            continue
        raw = match.group(1)
        if str(raw).isdigit():
            return int(raw)
        value = _small_chinese_number(str(raw))
        if value:
            return value
    return None


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _question_references_focus_entity(compact: str, column: str) -> bool:
    if not str(column or "").strip():
        return False
    label = _dimension_question_label(column)
    if _question_references_all_scope(compact, column):
        return False
    explicit_label = _explicit_focus_label(compact)
    if explicit_label and explicit_label != label:
        return False
    if any(
        token in compact
        for token in (
            f"这些{label}",
            f"这些Top{label}",
            f"这些top{label}",
            f"这些TOP{label}",
            f"这几个{label}",
            f"上述{label}",
            f"这3个{label}",
            f"这三个{label}",
            f"这五个{label}",
            f"这前3个{label}",
            f"这前三个{label}",
            f"这前3名{label}",
            f"这前三名{label}",
            f"前3个{label}",
            f"前三个{label}",
            f"前3名{label}",
            f"这些前三{label}",
            f"这些前3{label}",
            f"排名前三的{label}",
            f"排名前3的{label}",
            f"前三的{label}",
            f"前3的{label}",
            f"前三{label}",
        )
    ):
        return False
    generic_refs = ("这个", "那个", "它", "其", "该", "上述", "刚才", "上一轮", "最高的", "最低的", "排名第一", "Top1", "top1")
    if any(token in compact for token in generic_refs):
        return True
    return any(token in compact for token in (f"这个{label}", f"这款{label}", f"那款{label}", f"该{label}", f"{label}中", f"{label}里"))


def _question_has_specific_focus_reference(compact: str, column: str) -> bool:
    label = _dimension_question_label(column)
    if not label or _question_references_all_scope(compact, column):
        return False
    for alias in _focus_label_aliases(label):
        if any(
            token in compact
            for token in (
                f"这些{alias}",
                f"这些Top{alias}",
                f"这些top{alias}",
                f"这些TOP{alias}",
                f"这几个{alias}",
                f"上述{alias}",
                f"这个{alias}",
                f"那个{alias}",
                f"该{alias}",
                f"这款{alias}",
                f"那款{alias}",
                f"{alias}中",
                f"{alias}里",
                f"最高的{alias}",
                f"最低的{alias}",
                f"最多的{alias}",
                f"最少的{alias}",
                f"排名第一的{alias}",
                f"排名第1的{alias}",
            )
        ):
            return True
        if re.search(
            rf"(?:这|这些|上述)?(?:排名|排行)?前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?(?:大)?的?{alias}",
            compact,
        ):
            return True
        if re.search(rf"这(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?{alias}", compact):
            return True
    return False


def _question_references_rank_target_focus_entity(compact: str, column: str) -> bool:
    if not str(column or "").strip():
        return False
    label = _dimension_question_label(column)
    if not label:
        return False
    explicit_label = _explicit_focus_label(compact)
    if explicit_label and explicit_label != label:
        return False
    specific_refs = (
        f"这个{label}",
        f"那个{label}",
        f"该{label}",
        f"这款{label}",
        f"那款{label}",
        f"最高的{label}",
        f"最低的{label}",
        f"排名第一的{label}",
        f"排名第1的{label}",
    )
    if any(token in compact for token in specific_refs):
        return True
    return any(token in compact for token in ("这个", "那个", "它", "其", "该", "刚才", "上一轮", "最高的", "最低的", "排名第一", "Top1", "top1"))


def _rank_position_focus_target(context: Mapping[str, Any], compact: str) -> tuple[str, Any]:
    for column, value, _source in _contextual_focus_filters(context):
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (list, tuple, set)):
            continue
        if _question_references_rank_target_focus_entity(compact, column):
            return column, value
    for focus_set in _context_focus_sets(context):
        dimension = str(focus_set.get("dimension") or "")
        if not dimension or not _question_references_rank_target_focus_entity(compact, dimension):
            continue
        values = focus_set.get("values")
        if isinstance(values, list) and values and values[0] not in (None, "", [], {}):
            return dimension, values[0]
    return "", None


def _question_references_focus_set(compact: str, column: str) -> bool:
    if not str(column or "").strip():
        return False
    label = _dimension_question_label(column)
    if _question_references_all_scope(compact, column):
        return False
    explicit_label = _explicit_focus_label(compact)
    if explicit_label and explicit_label != label:
        return False
    for alias in _focus_label_aliases(label):
        if re.search(
            rf"(?:这|这些)?(?:排名|排行)?前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?(?:大)?的?{alias}",
            compact,
        ):
            return True
        if re.search(rf"这(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?{alias}", compact):
            return True
        if any(
            token in compact
            for token in (
                f"排名靠前的{alias}",
                f"排名靠前{alias}",
                f"靠前的{alias}",
                f"靠前{alias}",
                f"这些Top{alias}",
                f"这些top{alias}",
                f"这些TOP{alias}",
                f"这些{alias}",
                f"这几个{alias}",
                f"上述{alias}",
            )
        ):
            return True
    return any(
        token in compact
        for token in (
            f"这些{label}",
            f"这几个{label}",
            f"上述{label}",
            f"这3个{label}",
            f"这三个{label}",
            f"这前3个{label}",
            f"这前三个{label}",
            f"前3个{label}",
            f"前三个{label}",
            f"前3名{label}",
            f"这些前三{label}",
            f"这些前3{label}",
            f"这前三名{label}",
            f"这前3名{label}",
            f"排名前三的{label}",
            f"排名前3的{label}",
            f"前三的{label}",
            f"前3的{label}",
            f"前三{label}",
            f"前三名{label}",
        )
    )


def _focus_label_aliases(label: str) -> list[str]:
    aliases = [str(label or "")]
    if label == "产品":
        aliases.extend(["商品", "货品", "item", "product", "sku", "SKU", "StockCode", "stockcode"])
    elif label == "客户":
        aliases.extend(["顾客", "CustomerID", "customer", "customerid"])
    elif label == "国家":
        aliases.extend(["Country", "country"])
    elif label == "月份":
        aliases.extend(["月度", "高月份", "month", "Month"])
    seen: set[str] = set()
    deduped: list[str] = []
    for alias in aliases:
        if not alias or alias in seen:
            continue
        seen.add(alias)
        deduped.append(alias)
    return deduped


def _explicit_focus_label(compact: str) -> str:
    for label in ("城市", "产品", "客户", "客群", "服务线", "业务线", "门店", "品类"):
        if re.search(rf"(?:最高|最低|最多|最少|排名第一|排名第1|top1|Top1)的(?:那个|该|这个)?{label}", compact):
            return label
        if any(token in compact for token in (f"这个{label}", f"那个{label}", f"这款{label}", f"那款{label}", f"该{label}")):
            return label
        if any(token in compact for token in (f"{label}中", f"{label}里")) and not _question_references_all_scope(compact, label):
            return label
    return ""


def _question_references_all_scope(compact: str, column_or_label: str) -> bool:
    label = _dimension_question_label(column_or_label)
    if not label:
        return False
    return any(token in compact for token in (f"全部{label}", f"所有{label}", f"全体{label}"))


def _looks_like_generic_reference(value: str) -> bool:
    return value in {"这个", "那个", "这些", "上述", "刚才", "上一轮", "该", "其"} or any(
        token in value
        for token in (
            "排名",
            "最高",
            "最低",
            "最多",
            "增长",
            "贡献",
            "这些",
            "哪个",
            "哪些",
            "客户",
            "产品",
            "城市",
            "地区",
            "区域",
            "月份",
            "金额",
            "利润",
            "销售",
            "收入",
            "订单",
        )
    ) or bool(re.search(r"\d{1,2}月", value))


def _looks_like_time_scope_reference(value: str) -> bool:
    compact = re.sub(r"\s+", "", str(value or ""))
    if not compact:
        return False
    if any(token in compact for token in ("每月", "每个月", "各月", "各月份", "按月", "按月份", "逐月", "本月", "上月", "下月", "这个月", "那个月", "这几个月", "这三个月", "前三个月", "第一季度", "第二季度", "第三季度", "第四季度")):
        return True
    return bool(re.search(r"(?:20\d{2}[-/年])?\d{1,2}月|20\d{2}[-/]\d{1,2}", compact))


def _looks_like_entity_filter_column(column: str) -> bool:
    if re.search(r"date|day|month|year|week|time|日期|时间|月份|年份|周", column, re.I):
        return False
    if re.search(r"amount|sales|profit|revenue|price|count|cnt|rate|ratio|金额|销售|利润|收入|数量|率|比例", column, re.I):
        return False
    return bool(str(column or "").strip())


def _focus_sets_from_logic_result(
    logic: Mapping[str, Any],
    params: Mapping[str, Any],
    operation: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    focus_sets: list[dict[str, Any]] = []
    candidate_filter = params.get("candidate_filter")
    if isinstance(candidate_filter, Mapping) and candidate_filter:
        candidate_filters = candidate_filter.get("filters") if isinstance(candidate_filter.get("filters"), Mapping) else logic.get("filters")
        focus_sets.append(
            {
                "source": "candidate_filter",
                "dimension": str(candidate_filter.get("dimension") or ""),
                "metric": str(candidate_filter.get("metric") or ""),
                "aggregation": str(candidate_filter.get("aggregation") or "sum"),
                "limit": int(candidate_filter.get("limit") or 0),
                "sort_order": str(candidate_filter.get("sort_order") or "desc"),
                "filters": dict(candidate_filters or {}),
            }
        )
    dimension = _first_text(logic.get("group_by"), params.get("dimension"), params.get("group_by"))
    if dimension and _looks_like_ranking(operation, str(logic.get("question") or "")):
        values = [row.get(dimension) for row in rows if isinstance(row, Mapping) and row.get(dimension) not in (None, "")]
        if values:
            focus_sets.append(
                {
                    "source": "ranking_result",
                    "dimension": dimension,
                    "metric": _first_text(logic.get("metric"), params.get("metric")),
                    "aggregation": str(params.get("aggregation") or "sum"),
                    "limit": int(params.get("limit") or len(values)),
                    "sort_order": str(params.get("sort_order") or "desc"),
                    "filters": dict(logic.get("filters") or {}),
                    "values": values[:10],
                }
            )
    return [item for item in focus_sets if item.get("dimension")]


def _merge_focus_sets(previous: Any, current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for item in [*current, *(previous if isinstance(previous, list) else [])]:
        if not isinstance(item, Mapping):
            continue
        normalized = dict(item)
        key = (
            str(normalized.get("dimension") or ""),
            str(normalized.get("metric") or ""),
            str(normalized.get("limit") or ""),
            repr(normalized.get("filters") or {}),
        )
        if not key[0] or any(existing.get("_focus_key") == key for existing in merged):
            continue
        normalized["_focus_key"] = key
        merged.append(normalized)
    for item in merged:
        item.pop("_focus_key", None)
    return merged[:5]


def _pick_column_by_aliases(columns: list[str], aliases: tuple[str, ...]) -> str:
    lowered = [(column, column.lower()) for column in columns]
    for alias in aliases:
        alias_lower = alias.lower()
        for column, lowered_column in lowered:
            if alias_lower == lowered_column or alias_lower in lowered_column:
                return column
    return ""


def _explicit_stockcode_reference(compact: str) -> bool:
    lowered = str(compact or "").lower()
    return "stockcode" in lowered or "stock_code" in lowered


def _product_label_column(columns: list[str]) -> str:
    return _pick_column_by_aliases(
        [str(column) for column in columns],
        (
            "description",
            "desc",
            "product_name",
            "product_label",
            "item_name",
            "goods_name",
            "product",
            "item",
            "goods",
            "产品",
            "商品",
            "品名",
            "描述",
            "stockcode",
            "stock_code",
            "sku",
            "sku_name",
        ),
    )


def _explicit_dimension_column(compact: str, available_columns: list[str]) -> str:
    available = [str(column) for column in available_columns if str(column or "").strip()]
    if _explicit_stockcode_reference(compact):
        column = _pick_column_by_aliases(available, ("stockcode", "stock_code", "sku", "sku_name"))
        if column:
            return column
    if any(token in compact for token in ("产品", "商品", "货品", "item", "product", "goods")):
        column = _product_label_column(available)
        if column:
            return column
    if any(token in compact for token in ("哪个月", "哪月", "几月", "哪个月份", "各月", "每月", "每个月", "按月", "月度")):
        column = _pick_column_by_aliases(available, ("month", "月份", "月度"))
        if column:
            return column
    alias_groups = [
        (("客户细分", "客户群", "客户群体", "客户分区", "客户分段", "客户段", "客群", "segment", "细分", "分段"), ("segment", "customer_segment", "客户细分", "客户群", "客户群体", "客户分区", "客户分段", "客户段", "客群", "细分", "分段")),
        (("产品", "商品", "sku", "SKU", "StockCode", "stockcode"), ("product", "sku", "stockcode", "stock_code", "item", "goods", "产品", "商品")),
        (("客户", "顾客"), ("customer", "cust", "client", "buyer", "客户", "顾客")),
        (("国家", "城市", "地区", "区域", "地域", "country", "region"), ("country", "nation", "region", "area", "province", "city", "国家", "地区", "区域", "城市")),
        (("门店", "店铺", "门店"), ("store", "shop", "门店", "店铺")),
        (("容量", "规格", "包装规格"), ("capacity", "volume", "size", "规格", "容量")),
        (("品类", "类别", "类目"), ("category", "ctg", "type", "品类", "类别")),
        (("月份", "月度", "按月", "各月", "每月", "每个月"), ("month", "月份", "月度")),
        (("团队", "小组", "部门"), ("team", "group", "department", "团队", "小组", "部门")),
        (("服务线", "业务线", "渠道"), ("service_line", "line", "channel", "渠道", "服务线", "业务线")),
    ]
    for triggers, aliases in alias_groups:
        if _contains_any_token(compact, triggers):
            column = _pick_column_by_aliases(available, aliases)
            if column:
                return column
    return ""


def _explicit_grouped_dimension_column(compact: str, available_columns: list[str]) -> str:
    available = [str(column) for column in available_columns if str(column or "").strip()]
    if _explicit_stockcode_reference(compact):
        column = _pick_column_by_aliases(available, ("stockcode", "stock_code", "sku", "sku_name"))
        if column:
            return column
    alias_groups = [
        (
            ("各服务线", "每个服务线", "各条服务线", "每条服务线", "按服务线", "服务线分布", "各业务线", "每个业务线", "各条业务线", "每条业务线", "按业务线", "业务线分布"),
            ("service_line", "line", "channel", "渠道", "服务线", "业务线"),
        ),
        (("各国家", "每个国家", "按国家", "主要国家", "哪些国家", "哪个国家", "各城市", "每个城市", "按城市", "各地区", "每个地区", "按地区", "各区域", "每个区域", "按区域"), ("country", "nation", "region", "area", "province", "city", "国家", "地区", "区域", "城市")),
        (
            ("各客户细分", "每个客户细分", "按客户细分", "各客户群", "每个客户群", "按客户群", "各客户群体", "每个客户群体", "按客户群体", "各客户分区", "每个客户分区", "按客户分区", "各客户分段", "每个客户分段", "按客户分段", "各客户段", "每个客户段", "按客户段"),
            ("segment", "customer_segment", "客户细分", "客户群", "客户群体", "客户分区", "客户分段", "客户段", "客群", "细分", "分段"),
        ),
        (("各客户", "每个客户", "按客户", "各顾客", "每个顾客", "按顾客"), ("customer", "cust", "client", "buyer", "客户", "顾客")),
        (("各产品", "每个产品", "按产品", "各商品", "每个商品", "按商品"), ("description", "desc", "product_name", "product_label", "item_name", "goods_name", "product", "item", "goods", "产品", "商品", "品名", "描述", "stockcode", "stock_code", "sku", "sku_name")),
        (("各容量", "每个容量", "按容量", "各规格", "每个规格", "按规格"), ("capacity", "volume", "size", "规格", "容量")),
        (("各品类", "每个品类", "按品类", "各类别", "每个类别", "按类别"), ("category", "ctg", "type", "品类", "类别")),
        (("各月", "每月", "每个月", "按月", "按月份"), ("month", "月份", "月度")),
    ]
    for triggers, aliases in alias_groups:
        if _contains_any_token(compact, triggers):
            column = _pick_column_by_aliases(available, aliases)
            if column:
                return column
            return aliases[0]
    return ""


def _contains_any_token(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(token in text or str(token).lower() in lowered for token in tokens)


def _explicit_rank_target_dimension_column(compact: str, available_columns: list[str]) -> str:
    available = [str(column) for column in available_columns if str(column or "").strip()]
    label_aliases = [
        ("service_line", ("服务线", "业务线"), ("service_line", "line", "business_line", "channel", "服务线", "业务线")),
        ("country", ("国家", "城市", "地区", "区域"), ("country", "nation", "region", "area", "province", "city", "国家", "地区", "区域", "城市")),
        ("segment", ("客户细分", "客户群", "客户群体", "客户分区", "客户分段", "客户段", "客群", "细分市场"), ("segment", "customer_segment", "客户细分", "客户群", "客户群体", "客户分区", "客户分段", "客户段", "客群", "细分", "分段")),
        ("customer", ("客户", "顾客"), ("customer", "cust", "client", "buyer", "客户", "顾客")),
        ("product", ("产品", "商品", "sku", "SKU"), ("description", "desc", "product_name", "product_label", "item_name", "goods_name", "product", "item", "goods", "产品", "商品", "品名", "描述", "stockcode", "stock_code", "sku", "sku_name")),
        ("category", ("品类", "类别", "类目"), ("category", "ctg", "type", "品类", "类别")),
        ("store", ("门店", "店铺"), ("store", "shop", "门店", "店铺")),
        ("capacity", ("容量", "规格", "包装规格"), ("capacity", "volume", "size", "规格", "容量")),
    ]
    rank_signals = ("最高", "最低", "最多", "最少", "最大", "最小", "最集中", "集中", "排名", "排行", "Top", "top", "前")
    candidates: list[tuple[int, str, tuple[str, ...]]] = []
    for fallback, labels, aliases in label_aliases:
        for label in labels:
            direct_question_patterns = (
                rf"(?:哪个|哪些|哪条|哪几个|哪类|哪种|哪款){label}",
                rf"(?:排名|排行)?第(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?的?{label}",
            )
            for pattern in direct_question_patterns:
                match = re.search(pattern, compact)
                if match:
                    candidates.append((match.start(), fallback, aliases))
    for fallback, labels, aliases in label_aliases:
        for label in labels:
            target_patterns = (
                rf"(?:最高|最低|最多|最少|最大|最小)的(?:那个|该|这个)?{label}",
                rf"(?:排名|排行)?前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?(?:大)?的?{label}",
            )
            if not any(signal in compact for signal in rank_signals):
                continue
            for pattern in target_patterns:
                match = re.search(pattern, compact)
                if match:
                    candidates.append((match.start(), fallback, aliases))
    if candidates:
        _position, fallback, aliases = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
        column = _pick_column_by_aliases(available, aliases)
        return column or fallback
    return ""


def _explicit_metric_column(compact: str, available_columns: list[str]) -> str:
    columns = _explicit_metric_columns(compact, available_columns)
    if columns:
        return columns[0]
    return ""


def _explicit_answer_metric_column(compact: str, available_columns: list[str]) -> str:
    columns = _explicit_metric_columns(compact, available_columns)
    if not columns:
        return ""
    if len(columns) > 1 and re.search(r"前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?(?:大)?的?(?:城市|客户|产品|商品|服务线|业务线|品类|门店|区域|地区)(?:中|里|内)", compact):
        return columns[-1]
    return columns[0]


def _explicit_metric_columns(compact: str, available_columns: list[str]) -> list[str]:
    available = [str(column) for column in available_columns if str(column or "").strip()]
    profit_rate_condition_for_amount = _profit_rate_candidate_condition_for_amount_display(compact)
    alias_groups = [
        (("订单总金额", "订单总额", "订单金额", "订单额", "总金额", "总额", "销售额", "收入", "营收", "amount", "sales", "revenue"), ("amount", "sales", "revenue", "金额", "销售额", "收入")),
        (("总利润", "利润总额", "利润", "profit"), ("profit", "利润")),
        (("工单量", "工单数", "工单", "tickets", "ticket"), ("tickets", "ticket", "工单量", "工单数")),
        (("订单数", "数量", "件数", "count", "cnt"), ("count", "cnt", "quantity", "num", "数量")),
    ]
    columns: list[str] = []
    for triggers, aliases in alias_groups:
        if profit_rate_condition_for_amount and any(alias in aliases for alias in ("profit", "利润")):
            continue
        if any(trigger in compact for trigger in triggers):
            column = _pick_column_by_aliases(available, aliases)
            if column and column not in columns:
                columns.append(column)
    return columns


def _profit_rate_candidate_condition_for_amount_display(compact: str) -> bool:
    match = re.search(r"(?:利润率|毛利率)[^，,。？?；;]{0,20}(?:排名)?前(?:\d+|[一二两三四五六七八九十]+)", compact)
    if not match:
        return False
    suffix = compact[match.end() :]
    return any(token in suffix for token in ("月收入", "收入", "订单总额", "订单总金额", "订单金额", "订单额", "总金额", "金额", "销售额", "销售金额"))


def _explicit_dimension_concept(compact: str) -> str:
    if any(token in compact for token in ("哪个月", "哪月", "几月", "哪个月份", "各月", "每月", "每个月", "按月", "月度")):
        return "month"
    alias_groups = [
        (("客户细分", "客户群", "客户群体", "客户分区", "客户分段", "客户段", "客群", "segment", "细分"), "segment"),
        (("国家", "城市", "地区", "区域", "地域", "country", "region"), "country"),
        (("客户", "顾客"), "customer"),
        (("产品", "商品", "sku", "SKU", "StockCode", "stockcode"), "product"),
        (("容量", "规格", "包装规格"), "capacity"),
        (("品类", "类别", "类目"), "category"),
        (("月份", "月度", "按月", "各月", "每月", "每个月"), "month"),
        (("团队", "小组", "部门"), "team"),
        (("服务线", "业务线", "渠道"), "service_line"),
    ]
    for triggers, concept in alias_groups:
        if any(trigger in compact for trigger in triggers):
            return concept
    return ""


def _explicit_metric_concept(compact: str) -> str:
    alias_groups = [
        (("订单总金额", "订单总额", "订单金额", "订单额", "总金额", "总额", "销售额", "收入", "营收", "消费总额", "消费金额", "消费总数", "消费合计", "消费多少", "amount", "sales", "revenue", "spend", "totalspend", "consumption"), "amount"),
        (("总利润", "利润", "profit"), "profit"),
        (("工单量", "工单数", "工单", "tickets", "ticket"), "tickets"),
        (("订单数", "数量", "件数", "count", "cnt"), "count"),
    ]
    for triggers, concept in alias_groups:
        if any(trigger in compact for trigger in triggers):
            return concept
    return ""


def _references_contextual_focus_entity(compact: str, context: Mapping[str, Any]) -> bool:
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    current_dimension = _first_text(scope.get("dimension"), params.get("dimension"), logic.get("group_by"))
    if current_dimension and _question_references_focus_entity(compact, current_dimension):
        return True
    for column, _value, _source in _contextual_focus_filters(context):
        if _question_references_focus_entity(compact, column) or _question_references_focus_set(compact, column):
            return True
    for focus_set in _context_focus_sets(context):
        dimension = str(focus_set.get("dimension") or "")
        if dimension and (_question_references_focus_entity(compact, dimension) or _question_references_focus_set(compact, dimension)):
            return True
    return False


def _first_alternate_dimension_column(columns: list[str], *, current_dimension: str = "") -> str:
    current = str(current_dimension or "").lower()
    for column in columns:
        lowered = column.lower()
        if current and lowered == current:
            continue
        if re.search(r"date|day|month|year|week|time|日期|时间|月份|年份|周", column, re.I):
            continue
        if re.search(r"amount|sales|profit|revenue|price|count|cnt|rate|ratio|金额|销售|利润|收入|数量|率|比例", column, re.I):
            continue
        if lowered in {"id"} or lowered.endswith("_id"):
            continue
        return column
    return ""


def _inherit_retail_window(params: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "start_ym": params.get("start_ym"),
        "end_ym": params.get("end_ym"),
        "top_n": params.get("top_n") or params.get("limit"),
        "metric": params.get("metric") or "sign_amt",
    }


def _generic_inherited_parameters(logic: Mapping[str, Any], params: Mapping[str, Any]) -> dict[str, Any]:
    inherited = {
        "metric": _first_text(logic.get("metric"), params.get("metric")),
        "dimension": _first_text(logic.get("group_by"), params.get("dimension"), params.get("group_by")),
        "filters": logic.get("filters"),
        "time_window": logic.get("time_window"),
    }
    if isinstance(params.get("derived_metric"), Mapping) and params.get("derived_metric"):
        inherited["derived_metric"] = dict(params.get("derived_metric") or {})
    source_tables = _source_tables(logic, params)
    if source_tables:
        inherited["source_tables"] = source_tables
    for key in ("table", "join_plan", "table_selection_reason", "available_columns"):
        value = logic.get(key) if key in logic else params.get(key)
        if value not in (None, "", [], {}):
            inherited[key] = value
    return inherited


def _generic_inherited_parameters_for_question(logic: Mapping[str, Any], params: Mapping[str, Any], compact: str) -> dict[str, Any]:
    inherited = _generic_inherited_parameters(logic, params)
    filters = inherited.get("filters")
    if isinstance(filters, Mapping):
        filtered = dict(filters)
        for column in list(filtered):
            if _explicit_time_match_start(compact) is not None and re.search(r"date|day|month|year|week|time|日期|时间|月份|年份|周", str(column), re.I):
                filtered.pop(column, None)
                continue
            if _looks_like_new_explicit_topn_request(compact, str(column)) or _question_references_all_scope(compact, str(column)):
                filtered.pop(column, None)
        if filtered:
            inherited["filters"] = filtered
        else:
            inherited.pop("filters", None)
    return inherited


def _remove_inherited_filter(inherited: dict[str, Any], column: str) -> None:
    filters = inherited.get("filters")
    if not isinstance(filters, Mapping):
        return
    filtered = dict(filters)
    filtered.pop(str(column), None)
    if filtered:
        inherited["filters"] = filtered
    else:
        inherited.pop("filters", None)


def _compact_parameters(params: Mapping[str, Any]) -> dict[str, Any]:
    keep = ("table", "metric", "dimension", "group_by", "aggregation", "start_ym", "end_ym", "ym", "top_n", "limit")
    return {key: params.get(key) for key in keep if params.get(key) not in (None, "", [], {})}


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
    return list(dict.fromkeys(values))


def _retail_time_window(params: Mapping[str, Any]) -> dict[str, Any]:
    return {key: params.get(key) for key in ("start_ym", "end_ym", "ym") if params.get(key)}


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _first_numeric_column(rows: list[dict[str, Any]], columns: list[str]) -> str:
    for column in columns:
        if any(_to_float(row.get(column)) is not None for row in rows):
            return column
    return ""


def _first_dimension_column(rows: list[dict[str, Any]], columns: list[str]) -> str:
    numeric = {_first_numeric_column(rows, columns)}
    for column in columns:
        if column not in numeric and not re.search(r"date|day|month|year|week|time|日期|时间|月份|年份|周", column, re.I):
            return column
    return ""


def _first_time_column(columns: list[str]) -> str:
    for column in columns:
        if re.search(r"date|day|month|year|week|time|日期|时间|月份|年份|周", column, re.I):
            return column
    return ""


def _profit_margin_denominator_column(columns: list[str]) -> str:
    return _pick_column_by_aliases(columns, ("sales", "amount", "revenue", "销售额", "销售金额", "订单金额", "订单额", "收入", "营收"))


def _explicit_time_question_prefix(compact: str) -> str:
    year_month_without_first_unit = re.search(r"(20\d{2}年\d{1,2}(?:到|至|-|~|—)(?:20\d{2}年)?\d{1,2}月)", compact)
    if year_month_without_first_unit:
        return f"{year_month_without_first_unit.group(1)}，"
    year_month = re.search(r"(20\d{2}年\d{1,2}月(?:到|至|-|~|—)(?:20\d{2}年)?\d{1,2}月)", compact)
    if year_month:
        return f"{year_month.group(1)}，"
    month_range_without_first_unit = re.search(r"(\d{1,2}(?:到|至|-|~|—)\d{1,2}月)", compact)
    if month_range_without_first_unit:
        return f"{month_range_without_first_unit.group(1)}，"
    month_range = re.search(r"(\d{1,2}月(?:到|至|-|~|—)\d{1,2}月)", compact)
    if month_range:
        return f"{month_range.group(1)}，"
    ranking_month = re.search(r"(20\d{2}年\d{1,2}月)", compact)
    if ranking_month and "排名" in compact and any(token in compact for token in ("相比", "相较", "对比", "与")):
        return f"在{ranking_month.group(1)}，"
    year_month_compare = re.search(
        r"(20\d{2})年(\d{1,2})月[^，。；;]*?(?:相比|相较|比|对比|较|和|与)[^，。；;]*?(\d{1,2})月",
        compact,
    )
    if year_month_compare:
        year = int(year_month_compare.group(1))
        first_month = int(year_month_compare.group(2))
        second_month = int(year_month_compare.group(3))
        start_month, end_month = sorted((first_month, second_month))
        return f"{year}年{start_month}月到{end_month}月，"
    month_compare = re.search(r"(\d{1,2})月[^，。；;]*?(?:相比|相较|比|对比|较|和|与)[^，。；;]*?(\d{1,2})月", compact)
    if month_compare:
        first_month = int(month_compare.group(1))
        second_month = int(month_compare.group(2))
        start_month, end_month = sorted((first_month, second_month))
        return f"{start_month}月到{end_month}月，"
    first_months = re.search(r"(?:(20\d{2})年)?前(\d+|[一二两三四五六七八九十]+)个月", compact)
    if first_months:
        prefix = compact[max(0, first_months.start() - 8) : first_months.start()]
        if any(token in prefix for token in ("列出", "展示", "显示", "返回", "排名")):
            return ""
        end_month = int(first_months.group(2)) if first_months.group(2).isdigit() else (_small_chinese_number(first_months.group(2)) or 0)
        if 1 <= end_month <= 12:
            year = first_months.group(1)
            return f"{year}年1月到{end_month}月，" if year else f"1月到{end_month}月，"
    quarter = re.search(r"((?:20\d{2}年)?(?:第?[一二三四1-4]季度|最后一季度))", compact)
    if quarter:
        return f"在{quarter.group(1)}，"
    listed_months = [int(item) for item in re.findall(r"(?<!\d)(\d{1,2})月", compact)]
    unique_listed_months = sorted({month for month in listed_months if 1 <= month <= 12})
    if len(unique_listed_months) >= 2:
        return f"{unique_listed_months[0]}月到{unique_listed_months[-1]}月，"
    single_month = re.search(r"(20\d{2}年\d{1,2}月)", compact)
    if single_month:
        return f"在{single_month.group(1)}，"
    month_only = re.search(r"(\d{1,2}月份?)", compact)
    if month_only:
        return f"在{month_only.group(1).removesuffix('份')}，"
    return ""


def _small_chinese_number(text: str) -> int | None:
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    text = str(text or "")
    if text in digits:
        return digits[text]
    if text == "十":
        return 10
    if text.startswith("十") and len(text) == 2 and text[1] in digits:
        return 10 + digits[text[1]]
    if text.endswith("十") and len(text) == 2 and text[0] in digits:
        return digits[text[0]] * 10
    if "十" in text and len(text) == 3 and text[0] in digits and text[2] in digits:
        return digits[text[0]] * 10 + digits[text[2]]
    return None


def _combined_time_question_prefix(context: Mapping[str, Any], compact: str) -> str:
    explicit = _explicit_time_question_prefix(compact)
    if explicit:
        return explicit
    if _previous_scope_is_time_series(context) and not _question_references_contextual_time(compact):
        return ""
    return _contextual_time_question_prefix(context)


def _contextual_time_question_prefix(context: Mapping[str, Any]) -> str:
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    filters = scope.get("filters") if isinstance(scope.get("filters"), Mapping) else logic.get("filters")
    if isinstance(filters, Mapping):
        for column, value in filters.items():
            prefix = _time_filter_value_prefix(str(column), value)
            if prefix:
                return prefix
    time_window = scope.get("time_window") if isinstance(scope.get("time_window"), Mapping) else logic.get("time_window")
    values = time_window.get("values") if isinstance(time_window, Mapping) and isinstance(time_window.get("values"), Mapping) else {}
    for column, value in values.items():
        prefix = _time_filter_value_prefix(str(column), value)
        if prefix:
            return prefix
    return ""


def _previous_scope_is_time_series(context: Mapping[str, Any]) -> bool:
    scope = context.get("scope") if isinstance(context.get("scope"), Mapping) else {}
    logic = context.get("logic_form") if isinstance(context.get("logic_form"), Mapping) else {}
    params = logic.get("parameters") if isinstance(logic.get("parameters"), Mapping) else {}
    dimension = _first_text(scope.get("dimension"), params.get("dimension"), logic.get("group_by"))
    return bool(dimension and re.search(r"date|day|month|year|week|time|日期|时间|月份|年份|周", str(dimension), re.I))


def _question_references_contextual_time(compact: str) -> bool:
    return any(
        token in compact
        for token in (
            "这三个月",
            "这两个月",
            "这几个月",
            "这些月份",
            "上述月份",
            "上述时间",
            "这个时间",
            "这段时间",
            "这个期间",
            "该期间",
            "期间",
            "同一时间",
            "同一期间",
            "刚才的时间",
        )
    )


def _time_filter_value_prefix(column: str, value: Any) -> str:
    if not re.search(r"date|day|month|year|week|time|日期|时间|月份|年份|周", column, re.I):
        return ""
    if isinstance(value, Mapping):
        year = value.get("year")
        month = value.get("month")
        month_range = value.get("month_range")
        if isinstance(month_range, (list, tuple)) and len(month_range) >= 2:
            start, end = int(month_range[0]), int(month_range[1])
            return f"{year}年{start}月到{end}月，" if year else f"{start}月到{end}月，"
        if month:
            return f"在{year}年{int(month)}月，" if year else f"在{int(month)}月，"
    text = str(value or "").strip()
    match = re.match(r"(20\d{2})-(\d{1,2})$", text)
    if match:
        return f"在{match.group(1)}年{int(match.group(2))}月，"
    return ""


def _dimension_question_label(dimension: str) -> str:
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(dimension or "").strip().lower())
    if any(token in normalized for token in ("description", "desc", "product", "sku", "stockcode", "stock", "item", "goods", "产品", "商品", "品名", "描述")):
        return "产品"
    if any(token in normalized for token in ("country", "nation", "国家")):
        return "国家"
    if any(token in normalized for token in ("customer", "cust", "client", "buyer", "客户", "顾客")):
        return "客户"
    mapping = {
        "city": "城市",
        "country": "国家",
        "product": "产品",
        "store": "门店",
        "customer": "客户",
        "customer_id": "客户",
        "cust_name": "客户",
        "cust_code": "客户",
        "segment": "客群",
        "service_line": "服务线",
        "business_line": "业务线",
        "month": "月份",
        "date": "日期",
        "time": "时间",
    }
    return mapping.get(str(dimension or "").strip().lower(), str(dimension or "对象"))


def _metric_question_label(metric: str) -> str:
    mapping = {
        "amount": "订单金额",
        "sales": "销售额",
        "revenue": "收入",
        "profit": "利润",
        "tickets": "工单量",
        "count": "数量",
        "__row_count__": "数量",
        "row_count": "数量",
    }
    return mapping.get(str(metric or "").strip().lower(), str(metric or "核心指标"))


def _time_question_label(column: str) -> str:
    mapping = {"month": "月份", "date": "日期", "day": "日期", "time": "时间"}
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(column or "").strip().lower())
    return mapping.get(normalized, str(column or "时间"))


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _looks_like_trend(operation: str, question_text: str) -> bool:
    return "trend" in operation or any(token in question_text for token in ("趋势", "波动", "环比", "同比", "增长", "下降"))


def _looks_like_ranking(operation: str, question_text: str) -> bool:
    return any(token in operation for token in ("rank", "top")) or any(token in question_text for token in ("排名", "top", "最高", "最低", "最大", "最小", "第一", "前"))


def _retail_month_window_from_question(question: str) -> str:
    match = re.search(r"(\d{4})年\s*(\d{1,2})月?\s*至\s*(?:(\d{4})年)?\s*(\d{1,2})月", str(question or ""))
    if not match:
        return ""
    start_year = int(match.group(1))
    start_month = int(match.group(2))
    end_year = int(match.group(3) or start_year)
    end_month = int(match.group(4))
    if not (1 <= start_month <= 12 and 1 <= end_month <= 12):
        return ""
    return f"{start_year}年{start_month}月至{end_year}年{end_month}月"


def _retail_month_window_text(start_ym: Any, end_ym: Any) -> str:
    start_text = _ym_text(start_ym)
    end_text = _ym_text(end_ym)
    if start_text and end_text and start_text != end_text:
        return f"{start_text}至{end_text}"
    return start_text or end_text


def _ym_text(value: Any) -> str:
    try:
        ym_value = int(value)
    except (TypeError, ValueError):
        return ""
    year, month = divmod(ym_value, 100)
    if year <= 0 or month <= 0 or month > 12:
        return ""
    return f"{year}年{month}月"
