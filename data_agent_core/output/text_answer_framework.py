"""GPT-like Chinese text framework for VDS data answers.

The composer only reorganizes verified response facts. It must not inspect raw
dataframes, re-run calculations, or invent new numeric values.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import math
import re
from typing import Any


def _marker(*parts: str, sep: str = "_") -> str:
    return sep.join(parts)


FORBIDDEN_MARKERS = (
    "chain_of_thought",
    "chain of thought",
    "raw_prompt",
    "raw prompt",
    "reasoning_trace",
    "trace.json",
    "trace json",
    _marker("standard", "answer"),
    _marker("standard", "answer", sep=" "),
    _marker("hidden", "answer"),
    _marker("task", "id"),
    "scorer",
    "api_key",
    "benchmark",
    _marker("public", "proxy", sep=" "),
    "后端审计",
    "标准答案",
    "评分器",
)

FRAMEWORK_HEADINGS = (
    "数据摘要（关键指标）",
    "分析洞察（发现了什么）",
    "业务建议（可以采取什么行动）",
    "口径与边界",
    "下一步可继续分析",
)


def apply_text_answer_framework(response: dict[str, Any], *, question: str) -> dict[str, Any]:
    """Apply the shared GPT-like Chinese answer frame to a response dict."""

    if not isinstance(response, dict) or _should_skip_response(response):
        return response

    answer = _sanitize_text(response.get("answer"))
    if _looks_frameworked(answer):
        response["answer"] = answer
        _mark_debug(response, applied=False, reason="already_frameworked")
        return response

    kind = _classify_kind(question, response)
    context = _FrameContext(question=question, response=response, original_answer=answer, kind=kind)
    direct_answer = _render_direct_answer(context)
    if direct_answer:
        response["answer"] = direct_answer
        insight = response.get("insight")
        if isinstance(insight, dict) and not str(insight.get("summary") or "").strip():
            insight["summary"] = _first_sentence(direct_answer, limit=180)
        _mark_debug(response, applied=True, reason=f"direct_kind={kind}")
        _attach_process_note(response, direct=True)
        return response

    sections = _compose_structured_sections(context)
    framed = _render_structured_sections(sections)
    if not framed:
        _mark_debug(response, applied=False, reason="empty_composition")
        return response

    response["answer"] = framed
    response["structured_answer_sections"] = sections
    insight = response.get("insight")
    if isinstance(insight, dict):
        if not str(insight.get("summary") or "").strip():
            insight["summary"] = _first_sentence(_strip_heading_prefix(_core_conclusion(context)), limit=180)
        next_questions = _next_questions(context)
        scalar_value_context = _is_scalar_value_context(
            answer_type=str(response.get("answer_type") or ""),
            operation=str(context.logic_form.get("operation") or ""),
        )
        if next_questions and (scalar_value_context or not insight.get("next_questions")):
            insight["next_questions"] = next_questions[:3]
        insight["confidence"] = max(float(insight.get("confidence") or 0.0), 0.82)
    _mark_debug(response, applied=True, reason=f"kind={kind}")
    _attach_process_note(response)
    return response


class _FrameContext:
    def __init__(self, *, question: str, response: dict[str, Any], original_answer: str, kind: str) -> None:
        self.question = str(question or response.get("question") or "")
        self.response = response
        self.original_answer = original_answer
        self.kind = kind
        self.logic_form = _as_dict(response.get("logic_form"))
        self.result = _as_dict(response.get("result"))
        self.overview_report = _as_dict(response.get("overview_report"))
        self.quality_report = _as_dict(response.get("quality_report"))
        self.source_references = response.get("source_references") if isinstance(response.get("source_references"), list) else []
        self.rows = _result_rows(self.result)
        self.columns = _result_columns(self.result, self.rows)


def _should_skip_response(response: dict[str, Any]) -> bool:
    answer_type = str(response.get("answer_type") or "")
    overview_report = _as_dict(response.get("overview_report"))
    logic = _as_dict(response.get("logic_form"))
    debug = _as_dict(response.get("debug"))
    operation = str(logic.get("operation") or "")
    route = str(debug.get("operation") or debug.get("message_intent") or "")
    output_format = _as_dict(logic.get("output_format"))
    guidelines = str(output_format.get("guidelines") or "")
    answer = str(response.get("answer") or "").strip()
    if answer in {"没有匹配记录", "No matching records", "NO_MATCHING_RECORDS"} and answer_type not in {"list", "table"}:
        return True
    if _guidelines_request_raw_answer(guidelines):
        return True
    if answer_type == "chat":
        if operation not in {"cleaning_boundary", "not_applicable"} and "cleaning" not in route:
            return True
    return False


def _guidelines_request_raw_answer(guidelines: str) -> bool:
    lowered = guidelines.lower()
    return any(
        token in lowered
        for token in (
            "just a number",
            "return only a number",
            "only the number",
            "return only",
            "answer only",
            "answer must be just",
            "must be just",
            "just the country code",
        )
    ) or any(token in guidelines for token in ("只返回数字", "只返回整数", "只需数字", "只返回百分比", "只返回姓名", "只返回SKU名称", "只返回"))


def _classify_kind(question: str, response: dict[str, Any]) -> str:
    answer_type = str(response.get("answer_type") or "")
    logic = _as_dict(response.get("logic_form"))
    operation = str(logic.get("operation") or "")
    debug = _as_dict(response.get("debug"))
    text = (str(question or "") + " " + operation + " " + str(debug.get("operation") or "")).lower().replace(" ", "")
    answer = str(response.get("answer") or "")
    verification = _as_dict(response.get("verification"))
    debug = _as_dict(response.get("debug"))
    semantic_status = str(
        verification.get("semantic_status")
        or debug.get("semantic_status")
        or debug.get("semantic_verification_status")
        or ""
    ).lower()
    if (
        response.get("success") is False
        or answer.strip() == "Not Applicable"
        or operation == "not_applicable"
        or answer_type == "clarification"
        or semantic_status in {"failed", "needs_clarification", "need_clarification"}
    ):
        return "clarification"
    if answer_type == "cleaning_simulation" or operation in {"data_quality_report", "outlier_count", "null_check"} or "cleaning" in operation or "清洗" in text or "质量" in text or "异常" in text:
        if any(token in text for token in ("缺失", "重复", "异常", "质量", "clean")):
            return "quality"
        return "cleaning"
    if answer_type == "overview" or "overview" in operation or any(token in text for token in ("主要讲什么", "概览", "看一下这个数据", "字段含义", "有哪些字段")):
        return "overview"
    if operation in {"retail_route_scope_metric_summary", "retail_route_scope_difference_reason"}:
        return "analysis"
    if _is_scalar_value_context(answer_type=answer_type, operation=operation):
        return "analysis"
    if any(token in text for token in ("完成率", "目标", "实际", "达标", "target", "actual", "achievement")):
        return "target_actual"
    if any(token in text for token in ("差距", "相差", "差多少", "gap", "delta", "difference")):
        return "gap"
    if any(token in text for token in ("趋势", "环比", "同比", "增长", "下降", "波动", "trend", "mom", "yoy", "growth")):
        return "trend"
    if any(token in text for token in ("排名", "top", "最高", "最低", "最大", "最小", "第一", "last", "ranking")) or operation in {"ranking", "top_count", "topn"}:
        return "ranking"
    return "analysis"


def _requires_contract_overview(question: str) -> bool:
    compact = str(question or "").lower().replace(" ", "")
    signals = (
        "概览",
        "overview",
        "数据结构",
        "表结构",
        "能支持哪些分析",
        "支持哪些分析",
        "能分析什么",
        "可分析方向",
        "分析方向",
        "上传文件能分析什么",
    )
    return any(signal in compact for signal in signals)


def _requires_contract_quality(question: str) -> bool:
    compact = str(question or "").lower().replace(" ", "")
    has_quality = any(token in compact for token in ("数据质量", "质量检查", "quality", "做分析前", "清洗"))
    has_missing = any(token in compact for token in ("缺失", "missing", "null"))
    has_duplicate = any(token in compact for token in ("重复", "duplicate"))
    has_outlier = any(token in compact for token in ("异常值", "离群", "outlier"))
    return has_quality and has_missing and has_duplicate and has_outlier


def _render_direct_answer(context: _FrameContext) -> str:
    if _should_preserve_existing_answer(context):
        return ""
    if context.kind == "overview" and _requires_contract_overview(context.question):
        return render_overview_answer(context)
    if context.kind == "gap":
        return render_gap_answer(context)
    if context.kind == "trend":
        return render_trend_answer(context)
    if context.kind == "quality" and (_requires_contract_quality(context.question) or _quality_field_rows(context)):
        return render_quality_answer(context)
    if context.kind == "ranking":
        if len(context.rows) == 1:
            return render_single_best_answer(context)
        return render_topn_answer(context)
    return ""


def render_topn_answer(context: _FrameContext) -> str:
    """Render a TopN answer with the result in the first sentence."""

    if not context.rows:
        return ""
    insufficient = _topn_insufficient_contract_answer(context)
    if insufficient:
        return insufficient
    if _result_shape_issue(context):
        return ""
    metric = _preferred_metric_column(context.columns, context.rows)
    label = _preferred_label_column(context.columns, metric)
    if not metric or not label:
        return ""
    direction = _ranking_direction(context)
    requested_n = _requested_topn_count(context.question) or len(context.rows)
    items = [
        f"{str(row.get(label)).strip()}（{_format_cell_value(row.get(metric), metric)}）"
        for row in context.rows[:requested_n]
        if row.get(label) not in {None, ""} and row.get(metric) not in {None, ""}
    ]
    if not items:
        return ""
    dimension_label = _display_dimension_label(label)
    answer = f"{metric}{direction}的 {len(items)} 个{dimension_label}是：" + "、".join(items) + "。"
    scope = _short_scope_suffix(context)
    return _sanitize_text(answer + scope)


def _topn_insufficient_contract_answer(context: _FrameContext) -> str:
    semantic_status = str(context.response.get("semantic_status") or _as_dict(context.response.get("debug")).get("semantic_status") or "")
    if semantic_status not in {"passed_with_insufficient_data", "partial"}:
        return ""
    task_contract = _as_dict(context.response.get("task_contract")) or _as_dict(_as_dict(context.response.get("debug")).get("task_contract"))
    if str(task_contract.get("task_family") or "") != "topn":
        return ""
    required_n = _to_int(task_contract.get("required_n"))
    dimension = str(task_contract.get("dimension") or "对象")
    if not required_n:
        return ""
    distinct_count = len({row.get(dimension) for row in context.rows if row.get(dimension) not in {None, ""}}) if dimension else len(context.rows)
    if distinct_count >= required_n:
        return ""
    return f"数据集中只有 {distinct_count} 个不同{dimension}，因此无法返回 Top {required_n}，只能展示 Top {distinct_count}。"


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def render_single_best_answer(context: _FrameContext) -> str:
    """Render a one-row best/worst ranking without the section framework."""

    if len(context.rows) != 1:
        return ""
    row = context.rows[0]
    metric = _preferred_metric_column(context.columns, context.rows)
    label = _preferred_label_column(context.columns, metric)
    if not metric or not label or row.get(label) in {None, ""}:
        return ""
    direction = _ranking_direction(context)
    dimension_label = _display_dimension_label(label)
    join_prefix = _join_answer_prefix(context)
    answer = f"{join_prefix}{metric}{direction}的{dimension_label}是{row.get(label)}，{metric}为 {_format_cell_value(row.get(metric), metric)}。"
    scope = _short_scope_suffix(context, include_join=True)
    return _sanitize_text(answer + scope)


def render_gap_answer(context: _FrameContext) -> str:
    """Render adjacent and first-place gaps directly."""

    if len(context.rows) < 2:
        return ""
    metric = _preferred_metric_column(context.columns, context.rows)
    label = _preferred_label_column(context.columns, metric)
    if not metric or not label:
        return ""
    ranked = [
        (str(row.get(label)).strip(), _to_float(row.get(metric)))
        for row in context.rows
        if row.get(label) not in {None, ""} and _to_float(row.get(metric)) is not None
    ]
    if len(ranked) < 2:
        return ""
    top_n = _requested_topn_count(context.question) or min(len(ranked), 3)
    ranked = ranked[:top_n]
    adjacent = []
    for (left_name, left_value), (right_name, right_value) in zip(ranked, ranked[1:]):
        if left_value is None or right_value is None:
            continue
        diff = left_value - right_value
        relation = "高" if diff >= 0 else "低"
        adjacent.append(f"{left_name}比{right_name}{relation} {_format_plain_value(abs(diff))}")
    first_name, first_value = ranked[0]
    last_name, last_value = ranked[-1]
    tail = ""
    if len(ranked) >= 3 and first_value is not None and last_value is not None:
        diff = first_value - last_value
        relation = "低" if diff >= 0 else "高"
        tail = f"；{last_name}比第一名{first_name}{relation} {_format_plain_value(abs(diff))}"
    dimension_label = _display_dimension_label(label)
    if not adjacent:
        return ""
    return f"Top {len(ranked)} {dimension_label}中，" + "，".join(adjacent) + tail + "。以上为相邻排名与第一名的差距。"


def render_trend_answer(context: _FrameContext) -> str:
    """Render a trend using ordered period-to-value movements."""

    metric = _preferred_metric_column(context.columns, context.rows)
    period = _preferred_period_column(context.columns)
    if not metric or not period:
        return ""
    value_columns = [column for column in context.columns if column != period and _numeric_ratio(context.rows, column) >= 0.5 and not _looks_identifier(column)]
    if len(value_columns) > 1:
        return ""
    pairs = [
        (str(row.get(period)).strip(), _to_float(row.get(metric)), row.get(metric))
        for row in context.rows
        if row.get(period) not in {None, ""} and _to_float(row.get(metric)) is not None
    ]
    if not pairs:
        return ""
    pairs = sorted(pairs, key=lambda item: item[0])
    trend = describe_trend([(label, value) for label, value, _ in pairs])
    sequence = _trend_sequence_text(pairs, metric)
    return f"按{period}看，{metric}{trend}：{sequence}。"


def render_overview_answer(context: _FrameContext) -> str:
    """Render an overview answer with a compact field list."""

    report = context.overview_report
    if isinstance(report.get("tables_summary"), list) and report.get("tables_summary"):
        return _render_multi_table_contract_overview(report)
    rows = _overview_field_rows(context)
    if not rows:
        return ""
    table = str(report.get("table") or "这张表")
    row_count = report.get("row_count")
    column_count = report.get("column_count") or len(rows)
    first = f"{table} 是一张包含 {_format_plain_value(row_count)} 行、{_format_plain_value(column_count)} 个字段的数据表；字段清单见下表。"
    directions = _overview_analysis_directions(report)
    quality = "数据质量摘要：缺失 / 重复 / 异常当前统计未发现非 0 问题；正式分析前仍可运行字段级质量检查。"
    if int(report.get("quality_issue_count") or 0):
        quality = f"数据质量摘要：当前识别到 {int(report.get('quality_issue_count') or 0)} 类质量信号。"
    return (
        first
        + "\n\n"
        + _markdown_table(["字段", "类型", "角色", "可用于什么分析"], rows)
        + "\n\n可分析方向：\n"
        + "\n".join(f"- {item}" for item in directions)
        + "\n\n"
        + quality
    )


def render_quality_answer(context: _FrameContext) -> str:
    """Render data quality as a direct answer plus a field-level table."""

    compact_rows = _quality_compact_field_rows(context)
    if compact_rows:
        issue_count = sum(
            int(row.get("缺失数") or 0) + int(row.get("重复数") or 0) + int(row.get("异常数") or 0)
            for row in compact_rows
        )
        first = (
            "本次质量检查未发现缺失、重复或异常值。"
            if issue_count == 0
            else f"本次质量检查发现 {issue_count} 个缺失、重复或异常值信号；具体字段级结果如下。"
        )
        return first + "\n\n" + _markdown_table(["字段", "类型", "缺失数", "重复数", "异常数"], compact_rows[:50])

    rows = _quality_field_rows(context)
    issue_count = sum(
        int(row.get("缺失数") or 0) + int(row.get("类型异常数") or 0) + int(row.get("异常值数") or 0)
        for row in rows
    )
    duplicate_text = _quality_duplicate_rule_text(context)
    first = (
        "本次质量检查未发现缺失、重复或异常值。按当前规则检查，各字段缺失、重复、异常统计均为 0；具体字段级结果如下。"
        if issue_count == 0 and "full_row_duplicate_count=0" in duplicate_text
        else f"本次质量检查发现 {issue_count} 个字段级质量信号；具体字段级结果如下。"
    )
    if not rows:
        rows = [{"字段": "当前结果字段", "类型": "unknown", "缺失数": 0, "缺失率": "0.00%", "类型异常数": 0, "异常值数": 0, "检测规则": "missing placeholder scan; non-null type parse failure; numeric IQR rule", "备注": "字段级结果不可用"}]
    table = _markdown_table(["字段", "缺失数", "缺失率", "类型异常数", "异常值数", "检测规则", "备注"], rows[:50])
    rules = "\n".join(
        [
            f"重复规则：{duplicate_text}",
            "异常规则：numeric IQR rule；未实现 z-score 时不声明 z-score 结果；类型异常按 non-null type parse failure 统计。",
        ]
    )
    return first + "\n\n" + table + "\n\n" + rules


def describe_trend(values_by_time: Any) -> str:
    """Classify a time series by adjacent movements instead of first/last only."""

    pairs: list[tuple[str, float]] = []
    if isinstance(values_by_time, dict):
        pairs = [(str(key), value) for key, value in values_by_time.items() if _to_float(value) is not None]
    elif isinstance(values_by_time, list):
        for item in values_by_time:
            if isinstance(item, dict):
                label = str(item.get("time") or item.get("period") or item.get("label") or "")
                value = _to_float(item.get("value"))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                label = str(item[0])
                value = _to_float(item[1])
            else:
                label = str(len(pairs) + 1)
                value = _to_float(item)
            if value is not None:
                pairs.append((label, value))
    if len(pairs) <= 1:
        return "只有一个周期，无法判断趋势"
    values = [value for _, value in pairs]
    movements = []
    for previous, current in zip(values, values[1:]):
        if math.isclose(previous, current, rel_tol=1e-9, abs_tol=1e-9):
            movements.append(0)
        else:
            movements.append(1 if current > previous else -1)
    non_zero = [item for item in movements if item != 0]
    if not non_zero:
        return "基本持平"
    if all(item > 0 for item in non_zero):
        return "单调上升"
    if all(item < 0 for item in non_zero):
        return "单调下降"
    signs = [item for index, item in enumerate(non_zero) if index == 0 or item != non_zero[index - 1]]
    if signs == [1, -1]:
        suffix = ""
        if values[-1] > values[0] and max(values) != values[-1]:
            suffix = f"，末期仍高于首期，但低于{pairs[values.index(max(values))][0]}峰值"
        return "先升后降" + suffix
    if signs == [-1, 1]:
        suffix = ""
        if values[-1] < values[0] and min(values) != values[-1]:
            suffix = f"，末期仍低于首期，但高于{pairs[values.index(min(values))][0]}低点"
        return "先降后升" + suffix
    return "波动"


def _should_preserve_existing_answer(context: _FrameContext) -> bool:
    debug = _as_dict(context.response.get("debug"))
    shaping = _as_dict(debug.get("user_experience_shaping"))
    if shaping.get("reason") == "vds_current_metric_top_answer_summary":
        return True
    if context.kind == "ranking" and re.search(r"(^|[；;\n])\s*\d+[.、]", context.original_answer):
        return True
    return False


def _compose_structured_sections(context: _FrameContext) -> dict[str, list[str]]:
    core = _core_conclusion(context)
    evidence = _evidence_paragraph(context)
    summary = _dedupe_points([core, evidence], limit=3)
    analysis = _dedupe_points(_brief_conclusions(context), limit=4)
    suggestions = _business_suggestion_lines(context)
    boundaries = _boundary_lines(context)
    next_questions = _next_questions(context)

    if not suggestions:
        suggestions = ["当前结果只适合先确认口径和数据完整性，暂不生成经营动作建议"]

    return {
        "数据摘要（关键指标）": summary or ["已基于当前可验证的数据完成分析，具体结果和边界见下方"],
        "分析洞察（发现了什么）": analysis or ["当前结果不足以形成更多洞察，需要结合结果表和口径边界继续复核"],
        "业务建议（可以采取什么行动）": suggestions[:3],
        "口径与边界": boundaries[:5],
        "下一步可继续分析": _dedupe_points(next_questions, limit=3) or ["补充字段、时间范围或过滤条件后重新分析"],
    }


def _render_structured_sections(sections: dict[str, list[str]]) -> str:
    parts: list[str] = []
    for heading in FRAMEWORK_HEADINGS:
        lines = [str(item).strip() for item in sections.get(heading, []) if str(item or "").strip()]
        if not lines:
            continue
        if parts:
            parts.append("")
        parts.append(heading)
        for index, line in enumerate(lines[:5], start=1):
            text = _strip_sentence_punctuation(line)
            if heading == "下一步可继续分析":
                suffix = "？" if not text.endswith(("?", "？", "。")) else ""
                parts.append(f"{index}. {text}{suffix}")
            else:
                parts.append(f"- {text}。")
    return _sanitize_text("\n".join(parts))


def _is_scalar_value_context(*, answer_type: str, operation: str) -> bool:
    return answer_type in {"number", "percentage"} and operation not in {"ranking", "top_count", "topn", "filtered_metric_ranking"}


def _core_conclusion(context: _FrameContext) -> str:
    if context.kind == "gap":
        direct = render_gap_answer(context)
        if direct:
            return _first_sentence(direct, limit=260)
    if context.kind == "overview":
        return _overview_core(context)
    if context.kind in {"cleaning", "quality"}:
        return _cleaning_core(context)
    if context.kind == "clarification":
        specific = _specific_clarification_core(context)
        if specific:
            return specific
        return f"这个问题暂时不能可靠回答，当前还缺少{_missing_information(context)}"
    if context.kind == "target_actual":
        best = _best_metric_row(context, prefer_rate=True, highest=True)
        if best:
            return f"{best['label']} 表现最好，{best['metric']}为 {best['value']}"
        return _fallback_core(context)
    if context.kind == "trend":
        trend = _trend_summary(context)
        if trend:
            return trend
    if context.kind == "ranking":
        original = _useful_original_ranking_core(context)
        if original:
            return original
        top = _top_result_text(context)
        if top:
            return top
    return _fallback_core(context)


def _ranking_direction(context: _FrameContext) -> str:
    text = context.question.lower() + " " + str(context.logic_form.get("operation") or "")
    params = _as_dict(context.logic_form.get("parameters"))
    sort_order = str(params.get("sort_order") or params.get("order") or "").lower()
    if sort_order == "asc" or any(token in text for token in ("最低", "最少", "bottom", "lowest", "min")):
        return "最低"
    return "最高"


def _display_dimension_label(column: str | None) -> str:
    text = str(column or "对象").strip()
    lowered = text.lower()
    if any(token in text for token in ("城市", "city")) or "city" in lowered:
        return "城市"
    if any(token in text for token in ("客户", "customer")) or "customer" in lowered:
        return "客户"
    if any(token in text for token in ("产品", "商品", "sku", "product")) or "product" in lowered:
        return "产品"
    if any(token in text for token in ("月份", "日期", "时间", "month", "date", "period")) or any(token in lowered for token in ("month", "date", "period")):
        return "周期"
    if any(token in text for token in ("区域", "region")) or "region" in lowered:
        return "区域"
    return text


def _join_answer_prefix(context: _FrameContext) -> str:
    params = _as_dict(context.logic_form.get("parameters"))
    join_plan = _as_dict(params.get("join_plan") or context.logic_form.get("join_plan"))
    tables: list[str] = []
    left = str(join_plan.get("left_table") or "").strip()
    right = str(join_plan.get("right_table") or "").strip()
    if left and right:
        tables = [left, right]
    elif isinstance(context.logic_form.get("source_tables"), list):
        tables = [str(item) for item in context.logic_form.get("source_tables") or [] if str(item)]
    if len(tables) >= 2:
        return "关联 " + " 和 ".join(tables[:2]) + " 后，"
    return ""


def _short_scope_suffix(context: _FrameContext, *, include_join: bool = True) -> str:
    notes: list[str] = []
    params = _as_dict(context.logic_form.get("parameters"))
    if include_join:
        join_plan = _as_dict(params.get("join_plan") or context.logic_form.get("join_plan"))
        link = _join_link_text(join_plan)
        if link and join_plan.get("trusted"):
            notes.append(f"关联口径：{link}。")
    derived = _derived_metric_scope(context)
    if derived:
        notes.append(f"口径：{derived}。")
    return (" " + " ".join(notes)) if notes else ""


def _trend_sequence_text(pairs: list[tuple[str, float | None, Any]], metric: str) -> str:
    parts: list[str] = []
    previous: float | None = None
    for index, (label, value, raw_value) in enumerate(pairs):
        formatted = _format_cell_value(raw_value, metric)
        if index == 0 or previous is None or value is None:
            parts.append(f"{label} 为 {formatted}")
        elif value > previous:
            parts.append(f"{label} 升至 {formatted}")
        elif value < previous:
            parts.append(f"{label} 回落到 {formatted}")
        else:
            parts.append(f"{label} 持平在 {formatted}")
        previous = value
    return "，".join(parts)


def _overview_field_rows(context: _FrameContext) -> list[dict[str, Any]]:
    report = context.overview_report
    field_meanings = report.get("field_meanings")
    rows: list[dict[str, Any]] = []
    if isinstance(field_meanings, list):
        for item in field_meanings:
            if not isinstance(item, dict):
                continue
            field = str(item.get("field") or item.get("name") or item.get("字段") or "").strip()
            if not field:
                continue
            rows.append(
                {
                    "字段": field,
                    "类型": str(item.get("type") or item.get("dtype") or item.get("数据类型") or "unknown"),
                    "角色": str(item.get("role") or item.get("meaning") or item.get("含义") or "待确认"),
                    "可用于什么分析": str(item.get("analysis_use") or item.get("meaning") or "需结合业务说明确认"),
                }
            )
    if not rows:
        for column in context.columns:
            rows.append({"字段": column, "类型": "numeric" if _numeric_ratio(context.rows, column) >= 0.5 else "text", "角色": "待确认", "可用于什么分析": "需结合业务说明确认"})
    return rows


def _render_multi_table_contract_overview(report: dict[str, Any]) -> str:
    tables = [item for item in report.get("tables_summary") or [] if isinstance(item, dict)]
    lines = [
        f"这批上传文件包含 {int(report.get('table_count') or len(tables))} 张表，共 {_format_plain_value(report.get('total_row_count') or 0)} 行、{_format_plain_value(report.get('total_column_count') or 0)} 个字段；需要先按表理解字段，再确认关联键后做跨表分析。",
        "关键字段已按表列出如下。",
        "",
        "每张表字段清单：",
    ]
    for table in tables:
        lines.extend(
            [
                "",
                f"{table.get('table')}（{_format_plain_value(table.get('row_count') or 0)} 行、{_format_plain_value(table.get('column_count') or 0)} 列）",
                "字段 | 类型 | 角色 | 可用于什么分析",
                "--- | --- | --- | ---",
            ]
        )
        for field in table.get("field_meanings") or []:
            item = _as_dict(field)
            if not item:
                continue
            lines.append(
                " | ".join(
                    [
                        str(item.get("field") or ""),
                        str(item.get("type") or "unknown"),
                        str(item.get("role") or "待确认"),
                        str(item.get("analysis_use") or item.get("meaning") or "需结合业务说明确认"),
                    ]
                )
            )
    join_keys = report.get("candidate_join_keys") if isinstance(report.get("candidate_join_keys"), list) else []
    join_text = "；".join(str(_as_dict(item).get("text") or "") for item in join_keys if _as_dict(item).get("text")) or "未识别到稳定的同名 ID / 编码 / 日期类候选关联键"
    lines.extend(["", "候选关联键：", f"- {join_text}", "", "可分析方向："])
    lines.extend(f"- {item}" for item in _multi_table_overview_directions(tables))
    total_quality = sum(int(_to_float(table.get("quality_issue_count") or 0) or 0) for table in tables)
    quality_text = "各表缺失 / 重复 / 异常当前统计未发现非 0 问题；仍需逐表查看字段级结果。" if total_quality == 0 else f"当前共识别 {total_quality} 类质量信号，需逐表确认。"
    lines.extend(
        [
            "",
            "join 风险和数据质量摘要：",
            "- join 风险：候选键必须再检查唯一性、缺失率、一对多关系和业务主键定义；不能仅凭同名字段直接 join。",
            f"- 数据质量：{quality_text}",
        ]
    )
    return "\n".join(lines)


def _overview_analysis_directions(report: dict[str, Any]) -> list[str]:
    metrics = [str(item) for item in report.get("metric_candidates") or [] if str(item)]
    dimensions = [str(item) for item in report.get("dimension_candidates") or [] if str(item)]
    times = [str(item) for item in report.get("time_columns") or [] if str(item)]
    metric_text = "/".join(metrics[:3]) or str(report.get("metric_column") or "核心指标")
    directions: list[str] = []
    for dimension in dimensions[:3]:
        directions.append(f"按 {dimension} 分组汇总 {metric_text}")
    for time_column in times[:2]:
        directions.append(f"按 {time_column} 看 {metric_text} 趋势")
    if not directions:
        directions.append("先确认一个指标字段和一个维度字段，再做分组汇总或趋势分析")
    return directions


def _multi_table_overview_directions(tables: list[dict[str, Any]]) -> list[str]:
    metrics: list[str] = []
    dimensions: list[str] = []
    times: list[str] = []
    for table in tables:
        for source, target in (
            (table.get("metric_candidates") or [], metrics),
            (table.get("dimension_candidates") or [], dimensions),
            (table.get("time_columns") or [], times),
        ):
            for item in source:
                text = str(item)
                if text and text not in target:
                    target.append(text)
    metric_text = "/".join(metrics[:3]) or "核心指标"
    directions: list[str] = []
    if times:
        directions.append(f"按 {times[0]} 看 {metric_text} 趋势")
    for dimension in dimensions[:2]:
        directions.append(f"按 {dimension} 分组汇总 {metric_text}")
    if len(tables) >= 2:
        directions.append(f"关联 {tables[0].get('table')} 与 {tables[1].get('table')} 后，结合 {', '.join(dimensions[:2]) or '维度字段'} 分析 {metric_text}")
    return directions or ["先选事实表、指标字段和关联键，再做跨表汇总分析"]


def _quality_field_rows(context: _FrameContext) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    report = context.quality_report
    field_level = report.get("field_level_table") if isinstance(report.get("field_level_table"), list) else []
    if field_level:
        for item in field_level:
            row = _as_dict(item)
            field = str(row.get("字段") or row.get("field") or row.get("column") or row.get("column_name") or "").strip()
            if not field:
                continue
            rows.append(
                {
                    "字段": field,
                    "类型": str(row.get("类型") or row.get("type") or row.get("dtype") or "unknown"),
                    "缺失数": int(_to_float(row.get("缺失数") or row.get("missing_count") or 0) or 0),
                    "缺失率": str(row.get("缺失率") or row.get("missing_rate") or "0.00%"),
                    "类型异常数": int(_to_float(row.get("类型异常数") or row.get("type_parse_failure_count") or 0) or 0),
                    "异常值数": int(_to_float(row.get("异常值数") or row.get("outlier_count") or row.get("anomaly_count") or 0) or 0),
                    "检测规则": str(row.get("检测规则") or "missing placeholder scan; non-null type parse failure; numeric IQR rule"),
                    "备注": str(row.get("备注") or ""),
                }
            )
        return rows
    for row in context.rows:
        field = str(row.get("字段") or row.get("field") or row.get("column") or row.get("column_name") or "").strip()
        if not field:
            continue
        rows.append(
                {
                    "字段": field,
                    "类型": str(row.get("类型") or row.get("type") or row.get("dtype") or "unknown"),
                    "缺失数": int(_to_float(row.get("缺失数") or row.get("missing_count") or row.get("null_count") or 0) or 0),
                    "缺失率": str(row.get("缺失率") or row.get("missing_rate") or "0.00%"),
                    "类型异常数": int(_to_float(row.get("类型异常数") or row.get("type_parse_failure_count") or 0) or 0),
                    "异常值数": int(_to_float(row.get("异常值数") or row.get("异常数") or row.get("outlier_count") or row.get("anomaly_count") or 0) or 0),
                    "检测规则": str(row.get("检测规则") or "missing placeholder scan; non-null type parse failure; numeric IQR rule"),
                    "备注": str(row.get("备注") or ""),
                }
        )
    if rows:
        return rows
    issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    by_field: dict[str, dict[str, Any]] = {}
    for issue in issues:
        issue_dict = _as_dict(issue)
        field = str(issue_dict.get("column_name") or issue_dict.get("field") or "全表").strip()
        current = by_field.setdefault(field, {"字段": field, "类型": "unknown", "缺失数": 0, "缺失率": "0.00%", "类型异常数": 0, "异常值数": 0, "检测规则": "missing placeholder scan; non-null type parse failure; numeric IQR rule", "备注": ""})
        issue_type = str(issue_dict.get("issue_type") or "").lower()
        count = int(_to_float(issue_dict.get("affected_rows") or 1) or 1)
        if any(token in issue_type for token in ("missing", "null", "缺失")):
            current["缺失数"] += count
        elif any(token in issue_type for token in ("mixed", "invalid_dates", "parse", "type")):
            current["类型异常数"] += count
        else:
            current["异常值数"] += count
    return list(by_field.values())


def _quality_compact_field_rows(context: _FrameContext) -> list[dict[str, Any]]:
    columns = set(context.columns)
    if not {"字段", "类型", "缺失数", "重复数", "异常数"}.issubset(columns):
        return []
    rows: list[dict[str, Any]] = []
    for row in context.rows:
        field = str(row.get("字段") or row.get("field") or row.get("column") or "").strip()
        if not field:
            continue
        rows.append(
            {
                "字段": field,
                "类型": str(row.get("类型") or row.get("type") or row.get("dtype") or "unknown"),
                "缺失数": int(_to_float(row.get("缺失数") or row.get("missing_count") or 0) or 0),
                "重复数": int(_to_float(row.get("重复数") or row.get("duplicate_count") or 0) or 0),
                "异常数": int(_to_float(row.get("异常数") or row.get("异常值数") or row.get("outlier_count") or row.get("anomaly_count") or 0) or 0),
            }
        )
    return rows


def _quality_duplicate_rule_text(context: _FrameContext) -> str:
    report = context.quality_report
    rules = report.get("duplicate_rules") if isinstance(report.get("duplicate_rules"), list) else []
    if not rules:
        return "full_row_duplicate_count=0；key_duplicate_count=无候选键"
    parts: list[str] = []
    for rule in rules:
        item = _as_dict(rule)
        table = str(item.get("table") or "当前表")
        full_count = int(_to_float(item.get("full_row_duplicate_count") or 0) or 0)
        key_counts = item.get("key_duplicate_count") if isinstance(item.get("key_duplicate_count"), dict) else {}
        key_text = ", ".join(f"{key}={value}" for key, value in key_counts.items()) if key_counts else "无候选键"
        parts.append(f"{table}: full_row_duplicate_count={full_count}; key_duplicate_count={key_text}")
    return "；".join(parts)


def _markdown_table(columns: list[str], rows: list[dict[str, Any]]) -> str:
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, separator]
    for row in rows:
        lines.append("| " + " | ".join(_markdown_cell(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def _markdown_cell(value: Any) -> str:
    text = _sanitize_text("" if value is None else value).replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip().replace("|", "\\|")


def _overview_core(context: _FrameContext) -> str:
    report = context.overview_report
    if report.get("report_type") == "source_overview_report":
        table_count = report.get("table_source_count")
        knowledge_count = report.get("knowledge_source_count")
        return f"这次上传包含 {table_count or 0} 个可计算表和 {knowledge_count or 0} 个说明/规则来源，适合先区分事实数据、字段口径和业务背景"
    tables = report.get("tables_summary")
    if isinstance(tables, list) and tables:
        themes = _short_join([_short_meaning(item.get("likely_meaning")) for item in tables[:4] if isinstance(item, dict)], limit=3)
        roles = _overview_table_role_summary(tables)
        role_suffix = f"，表角色包括 {roles}" if roles else ""
        return f"已读取这组数据：它由 {report.get('table_count') or len(tables)} 张表组成，主要覆盖{themes or '业务事实、维表和过程记录'}{role_suffix}"
    meaning = str(report.get("likely_meaning") or "").strip()
    table = str(report.get("table") or "这张表")
    metric = str(report.get("metric_column") or "").strip()
    dimension = str(report.get("dimension_column") or "").strip()
    period = str(report.get("period_column") or "").strip()
    if meaning:
        suffix = _short_join([f"指标可看 {metric}" if metric else "", f"维度可按 {dimension}" if dimension else "", f"时间可按 {period}" if period else ""], limit=3)
        return f"这份数据主要是一张表，{table}记录{_short_meaning(meaning)}" + (f"，{suffix}" if suffix else "")
    return _fallback_core(context)


def _overview_table_role_summary(tables: list[Any]) -> str:
    counts: dict[str, int] = {}
    for item in tables:
        if not isinstance(item, dict):
            continue
        table_type = str(item.get("table_type") or "").strip()
        if not table_type:
            continue
        counts[table_type] = counts.get(table_type, 0) + 1
    if not counts:
        return ""
    return "、".join(f"{name} {count} 张" for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5])


def _cleaning_core(context: _FrameContext) -> str:
    outlier_text = _outlier_count_text(context)
    if outlier_text:
        return outlier_text
    original = _original_points(context, limit=1)
    if original:
        return original[0]
    value = _as_dict(context.result.get("value"))
    impacted = value.get("estimated_impacted_rows")
    rate = value.get("estimated_impacted_rate")
    direct = value.get("direct_action_rows")
    if impacted is not None:
        return (
            f"当前只适合先做清洗模拟，估算有 {_format_plain_value(impacted)} 行受质量规则影响"
            f"{f'（{rate}）' if rate not in {None, ''} else ''}，其中 {_format_plain_value(direct or 0)} 行需要优先确认；不会直接修改原始数据"
        )
    return "当前清洗结论只作为模拟建议，不会直接修改原始数据，需要你确认规则后再执行"


def _fallback_core(context: _FrameContext) -> str:
    multi_metric_text = _multi_metric_result_text(context)
    if multi_metric_text:
        return multi_metric_text
    first = _first_sentence(context.original_answer, limit=220)
    if first and first.lower() != "not applicable":
        return first
    answer_type = str(context.response.get("answer_type") or "")
    if answer_type in {"number", "percentage"}:
        value = context.result.get("value")
        if value not in (None, "", []):
            return f"已基于已验证结果得到 {_format_cell_value(value, 'answer')}"
    row_text = _top_result_text(context)
    if row_text:
        return row_text
    value = context.result.get("value")
    if value not in (None, "", []):
        return f"已基于已验证结果得到 {str(value)[:120]}"
    return "已基于当前可验证的数据完成分析，具体结果和边界见下方"


def _evidence_paragraph(context: _FrameContext) -> str:
    if context.kind == "overview":
        return _overview_evidence(context)
    if context.kind in {"cleaning", "quality"}:
        return _cleaning_evidence(context)
    if context.kind == "clarification":
        return f"要继续分析，最少需要补充{_missing_information(context)}；否则我只能说明缺口，不能编造字段、时间范围或映射关系"
    if context.kind == "target_actual":
        best = _best_metric_row(context, prefer_rate=True, highest=True)
        worst = _best_metric_row(context, prefer_rate=True, highest=False)
        if best and worst:
            return f"例如 {best['label']} 最高，{best['metric']}为 {best['value']}；相对低位是 {worst['label']}，{worst['metric']}为 {worst['value']}"
    if context.kind == "trend":
        extrema = _extrema_text(context)
        if extrema:
            return extrema
    if context.kind == "ranking":
        top_rows = _top_rows_text(context)
        if top_rows:
            return f"关键排序结果是：{top_rows}"
    if context.rows:
        return f"关键结果来自已验证结果表：{_describe_row(context.rows[0], context.columns)}"
    return ""


def _overview_evidence(context: _FrameContext) -> str:
    report = context.overview_report
    if report.get("report_type") == "source_overview_report":
        sources = report.get("sources") if isinstance(report.get("sources"), list) else []
        examples = _short_join(
            [
                f"{item.get('file_name')}（{item.get('source_category') or item.get('source_type') or '来源文件'}：{item.get('purpose_label') or item.get('purpose') or item.get('source_role') or '补充说明'}）"
                for item in sources[:5]
                if isinstance(item, dict)
            ],
            limit=5,
            separator="；",
        )
        original = _original_points(context, limit=1)
        suffix = f"；{original[0]}" if original else ""
        return f"从来源结构看，可计算表和说明/规则文件需要分开使用：{examples or '已识别上传来源'}{suffix}"
    tables = report.get("tables_summary")
    if isinstance(tables, list) and tables:
        examples = _short_join(
            [
                f"{item.get('table')}（{item.get('table_type') or '结构化数据表'}，{_format_plain_value(item.get('row_count'))} 行、{_format_plain_value(item.get('column_count'))} 列，关键字段：{_short_join(item.get('key_fields') or [], limit=4)}）"
                for item in tables[:3]
                if isinstance(item, dict)
            ],
            limit=3,
            separator="；",
        )
        original = _original_points(context, limit=1)
        suffix = f"；{original[0]}" if original else ""
        return f"从结构上看，核心对象分散在多张表里，主要表包括 {examples or '已识别表'}；多表关系还需要主键、时间粒度或说明文件确认{suffix}"
    fields = []
    if _asks_field_roles(context.question):
        fields.append(
            "字段角色："
            f"指标={_format_role_values(report.get('metric_candidates') or ([report.get('metric_column')] if report.get('metric_column') else []))}；"
            f"维度={_format_role_values(report.get('dimension_candidates') or ([report.get('dimension_column')] if report.get('dimension_column') else []))}；"
            f"时间={_format_role_values(report.get('time_columns') or ([report.get('period_column')] if report.get('period_column') else []))}；"
            f"ID={_format_role_values(report.get('id_candidates') or [])}"
        )
    if report.get("period_column"):
        fields.append(f"时间字段是 {report.get('period_column')}")
    if report.get("metric_column"):
        fields.append(f"核心指标字段是 {report.get('metric_column')}")
    metric_rows = _metric_summary_rows(report)
    if metric_rows:
        fields.append("关键数值包括 " + _short_join(metric_rows, limit=3, separator="；"))
    if report.get("dimension_column"):
        fields.append(f"维度字段是 {report.get('dimension_column')}")
    field_meanings = report.get("field_meanings") if isinstance(report.get("field_meanings"), list) else []
    if field_meanings:
        fields.append("还包含 " + _short_join([str(item.get("field")) for item in field_meanings[:5] if isinstance(item, dict)], limit=5))
    size = ""
    if report.get("row_count") is not None and report.get("column_count") is not None:
        size = f"表规模是 {_format_plain_value(report.get('row_count'))} 行、{_format_plain_value(report.get('column_count'))} 列；"
    original = _original_points(context, limit=1)
    suffix = f"；{original[0]}" if original else ""
    return "从结构上看，" + size + (_short_join(fields, limit=4, separator="；") or "这不是只看行列数的问题，还需要结合字段角色判断可分析方向") + suffix


def _asks_field_roles(question: str) -> bool:
    compact = str(question or "").lower().replace(" ", "")
    return "字段" in compact and all(token in compact for token in ("指标", "维度", "时间")) and ("id" in compact or "ID" in question)


def _format_role_values(values: Any) -> str:
    if isinstance(values, list):
        cleaned = [str(item) for item in values if str(item)]
    else:
        cleaned = [str(values)] if str(values or "") else []
    return "、".join(cleaned[:6]) if cleaned else "待确认"


def _cleaning_evidence(context: _FrameContext) -> str:
    outlier_text = _outlier_count_text(context)
    if outlier_text:
        return f"异常检查基于已验证结果：{outlier_text}"
    rows = context.rows[:4]
    if rows:
        items = []
        for row in rows:
            table = _first_existing(row, ("表名", "table", "Table")) or "数据表"
            rule = _first_existing(row, ("规则", "rule", "问题")) or "质量规则"
            affected = _first_existing(row, ("影响行数", "affected_rows", "影响比例")) or ""
            suggestion = _cleaning_suggestion_text(_first_existing(row, ("建议", "suggestion", "说明")) or "")
            suffix = f"，{suggestion}" if suggestion not in {None, ""} else ""
            items.append(f"{table} 的 {rule}{f' 影响 {affected}' if affected not in {None, ''} else ''}{suffix}")
        extra = _keyword_any_point(context, ("0 值", "InvoiceDate 范围", "无法解析"))
        if extra:
            items.append(extra)
        return "主要质量信号包括：" + "；".join(items)
    return "我会按缺失、重复、异常值和字段类型问题分层说明，并保持原始数据只读"


def _brief_conclusions(context: _FrameContext) -> list[str]:
    if context.kind == "overview":
        return _overview_conclusions(context)
    if context.kind in {"cleaning", "quality"}:
        return _cleaning_conclusions(context)
    if context.kind == "clarification":
        missing = _missing_information(context)
        return [
            f"当前缺少{missing}，所以不能直接给出数据结论",
            "如果强行回答，容易把不存在字段、未确认时间或未上传映射关系当成事实",
            "补充最小信息后，我可以重新按同一口径计算并给出可复核结果",
        ]
    if context.kind == "target_actual":
        best = _best_metric_row(context, prefer_rate=True, highest=True)
        worst = _best_metric_row(context, prefer_rate=True, highest=False)
        rows = [f"最高完成表现：{best['label']}，{best['metric']} {best['value']}" if best else "已按目标与实际的已验证结果整理完成表现"]
        rows.append(f"最低完成表现：{worst['label']}，{worst['metric']} {worst['value']}" if worst else "低表现项需要结合目标、实际和周期完整性复核")
        rows.append("未达标项需要优先看目标来源、实际来源和周期是否完整")
        return rows
    if context.kind == "trend":
        extrema = _multi_series_trend_points(context) or _trend_points(context)
        return extrema or _sentence_fallbacks(context)
    if context.kind == "ranking":
        rows = _ranking_conclusions(context)
        if rows:
            return rows
    return _sentence_fallbacks(context)


def _overview_conclusions(context: _FrameContext) -> list[str]:
    report = context.overview_report
    if report.get("report_type") == "source_overview_report":
        conclusions = [
            f"可计算表有 {report.get('table_source_count') or 0} 个，适合交给数据分析链路做金额、排名、趋势或 join",
            f"说明/规则来源有 {report.get('knowledge_source_count') or 0} 个，适合解释字段含义、业务规则和分析口径",
            "后续问题应先判断是问文件用途、字段口径，还是问具体计算结果",
        ]
        return _merge_points(_original_points(context, limit=2), conclusions, limit=3)
    tables = report.get("tables_summary")
    if isinstance(tables, list) and tables:
        largest = tables[0] if isinstance(tables[0], dict) else {}
        quality_count = sum(int(item.get("quality_issue_count") or 0) for item in tables if isinstance(item, dict))
        keyword_point = _keyword_point(context, "建议分析方向")
        roles = _overview_table_role_summary(tables)
        conclusions = [
            f"这组数据不是单表，最大表是 {largest.get('table') or '主表'}，有 {_format_plain_value(largest.get('row_count'))} 行",
            f"表角色需要先分清：{roles or '事实表、维表、规则/说明文件'}，再决定是否 join",
            f"已识别的质量问题数量为 {quality_count} 个，正式分析前建议先确认缺失、重复和异常影响",
        ]
        return _merge_points(_original_points(context, limit=2) + ([keyword_point] if keyword_point else []), conclusions, limit=3)
    conclusions = [
        f"这份数据主要记录{_short_meaning(report.get('likely_meaning') or '结构化业务过程')}",
        f"最适合优先看的字段角色是：指标={report.get('metric_column') or '待确认'}，维度={report.get('dimension_column') or '待确认'}，时间={report.get('period_column') or '待确认'}",
        "不只看多少行多少列，下一步应围绕指标、维度、时间和质量边界继续问",
    ]
    return _merge_points(_original_points(context, limit=2), conclusions, limit=3)


def _cleaning_conclusions(context: _FrameContext) -> list[str]:
    outlier_text = _outlier_count_text(context)
    if outlier_text:
        return [
            outlier_text,
            "异常判断只覆盖当前筛选后的数值分布，样本量过少时不能代表整体风险",
            "如果要判断业务是否异常，还需要和相邻月份、同类城市或历史基线对比",
        ]
    value = _as_dict(context.result.get("value"))
    direct = value.get("direct_action_rows")
    impacted = value.get("estimated_impacted_rows")
    rows = context.rows
    rules = _short_join([str(_first_existing(row, ("规则", "rule")) or "") for row in rows[:4]], limit=4)
    fallback = [
        f"缺失、重复、异常或类型问题会先作为质量信号标记，估算影响 {_format_plain_value(impacted or 0)} 行，不能简单说数据完全正常",
        f"建议清洗规则包括 {rules or '缺失/重复/异常/类型检查'}，需要优先人工确认的直接清洗影响约 {_format_plain_value(direct or 0)} 行",
        "我不会直接修改原始数据，不能覆盖原始文件；删除、填充、覆盖或导出清洗后数据都需要用户确认，必须等用户明确确认",
    ]
    return _merge_points(_original_points(context, limit=2), fallback, limit=3)


def _outlier_count_text(context: _FrameContext) -> str:
    if str(context.logic_form.get("operation") or "") != "outlier_count":
        return ""
    value = context.result.get("value")
    if value in (None, "") and context.rows:
        value = context.rows[0].get("answer")
    if value in (None, ""):
        return ""
    return f"当前筛选口径下异常值数量为 {_format_plain_value(value)}"


def _cleaning_suggestion_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"主要缺失字段[:：]\s*([^。；;]+)", text)
    if match:
        fields = []
        for field_match in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fffA-Za-z0-9_]+)\s+\d+\s*行", match.group(1)):
            field = field_match.group(1).strip()
            if field:
                fields.append(f"{field} 缺失")
        if fields:
            text = f"{text}（{_short_join(fields, limit=4)}）"
    return text


def _ranking_conclusions(context: _FrameContext) -> list[str]:
    rows = context.rows[:3]
    if not rows:
        return []
    metric = _preferred_metric_column(context.columns, rows)
    label = _preferred_label_column(context.columns, metric)
    conclusions = []
    for index, row in enumerate(rows, start=1):
        name = str(row.get(label) if label else _first_non_empty_value(row))
        value = _format_cell_value(row.get(metric), metric) if metric else _describe_row(row, context.columns)
        extras = _supplemental_row_metrics(row, context.columns, label=label, metric=metric)
        conclusions.append(f"第 {index} 位是 {name}，{metric or '结果'}为 {value}{extras}")
    if len(conclusions) < 3 and _is_simple_top1_ranking(context):
        conclusions.append("当前问题只要求最高或最低项，结果表已收敛到首位")
        conclusions.append("如需复核完整排序，可以扩大 TopN 范围或查看完整结果表")
        return conclusions[:3]
    if len(conclusions) < 3:
        requested_n = _requested_topn_count(context.question)
        if requested_n >= 2:
            conclusions.append(f"当前结果表只返回 {len(rows)} 条排序结果，未展示的候选项不能从当前结果推断完整排名")
        else:
            conclusions.append("该结论来自已验证排序结果，未把未返回明细行展开成额外结论")
    if len(conclusions) < 3:
        conclusions.append("排序口径应以结果表的聚合字段和排序字段为准，避免把明细行顺序当排名")
    if len(conclusions) < 3:
        conclusions.append("如需复核完整排名，需要查看未截断结果表或扩大 TopN 范围")
    return conclusions[:3]


def _is_simple_top1_ranking(context: _FrameContext) -> bool:
    if len(context.rows) != 1:
        return False
    logic = context.logic_form
    params = _as_dict(logic.get("parameters"))
    if str(logic.get("operation") or "") not in {"ranking", "filtered_metric_ranking"}:
        return False
    if context.response.get("warnings") or context.response.get("errors"):
        return False
    join_plan = _as_dict(params.get("join_plan") or logic.get("join_plan"))
    if join_plan and not join_plan.get("trusted"):
        return False
    return True


def _simple_top1_ranking_answer(context: _FrameContext) -> str:
    row = context.rows[0]
    metric = _preferred_metric_column(context.columns, context.rows)
    label = _preferred_label_column(context.columns, metric)
    name = str(row.get(label) if label else _first_non_empty_value(row)).strip()
    direction = "最低" if any(token in context.question.lower() for token in ("最低", "最少", "lowest", "bottom", "min")) else "最高"
    params = _as_dict(context.logic_form.get("parameters"))
    table = str(params.get("table") or "").strip()
    if params.get("same_schema_union") and table == "__same_schema_union__":
        table = ""
    prefix = f"{table} 中" if table else ""
    scope = _simple_top1_scope_notes(context, params)
    if metric:
        answer = f"{prefix}{metric}{direction}的是{name}，{metric} {_format_cell_value(row.get(metric), metric)}。"
    else:
        answer = f"{prefix}{direction}项是{_describe_row(row, context.columns)}。"
    if scope:
        answer = answer + " " + " ".join(scope)
    return _sanitize_text(answer)


def _simple_top1_scope_notes(context: _FrameContext, params: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    derived_metric = _as_dict(params.get("derived_metric"))
    if derived_metric:
        name = str(derived_metric.get("name") or "派生指标").strip()
        formula = str(derived_metric.get("formula") or "").strip()
        numerator = str(derived_metric.get("numerator") or "").strip()
        denominator = str(derived_metric.get("denominator") or "").strip()
        if formula:
            notes.append(f"口径：{name} = {formula}。")
        elif numerator and denominator:
            notes.append(f"口径：{name} = sum({numerator}) / sum({denominator})。")

    join_plan = _as_dict(params.get("join_plan") or context.logic_form.get("join_plan"))
    if join_plan.get("trusted"):
        steps = join_plan.get("steps") if isinstance(join_plan.get("steps"), list) else []
        if steps:
            links: list[str] = []
            for step in steps[:3]:
                step_dict = _as_dict(step)
                left = str(step_dict.get("left_table") or "").strip()
                right = str(step_dict.get("right_table") or "").strip()
                left_key = str(step_dict.get("left_key") or "").strip()
                right_key = str(step_dict.get("right_key") or "").strip()
                if left and right and left_key and right_key:
                    links.append(f"{left}.{left_key} -> {right}.{right_key}")
            if links:
                notes.append("关联：" + "；".join(links) + "。")
        else:
            left = str(join_plan.get("left_table") or "").strip()
            right = str(join_plan.get("right_table") or "").strip()
            left_key = str(join_plan.get("left_key") or "").strip()
            right_key = str(join_plan.get("right_key") or "").strip()
            if left and right and left_key and right_key:
                notes.append(f"关联：{left}.{left_key} -> {right}.{right_key}。")

    source_tables = context.logic_form.get("source_tables") or params.get("source_tables") or []
    if not join_plan and params.get("same_schema_union") and isinstance(source_tables, list) and len(source_tables) > 1:
        notes.append("范围：已合并同结构表 " + _short_join([str(item) for item in source_tables], limit=4) + "。")
    return notes


def _specific_clarification_core(context: _FrameContext) -> str:
    original = context.original_answer.strip()
    if not original or original.lower() == "not applicable":
        return ""
    if any(token in original for token in ("关联键", "关联", "join", "->")) and "." in original:
        return original
    if any(token in original for token in ("没有可用于", "不能把其他字段替代", "点名要按")):
        return original
    return ""


def _useful_original_ranking_core(context: _FrameContext) -> str:
    original = _first_sentence(context.original_answer, limit=260)
    if not original or original.lower() == "not applicable":
        return ""
    lowered = original.lower()
    if any(token in lowered for token in ("trace", "debug", "not applicable")):
        return ""
    if any(token in original for token in ("最高", "最低", "Top", "top", "第 1", "1.", "第一")):
        return original
    return ""


def _sentence_fallbacks(context: _FrameContext) -> list[str]:
    sentences = _sentences(context.original_answer)
    result = [sentence for sentence in sentences if sentence.lower() != "not applicable"][:3]
    if context.rows and len(result) < 3:
        result.append(f"结果表首行显示：{_describe_row(context.rows[0], context.columns)}")
    while len(result) < 3:
        result.append("该结论只基于已验证结果和当前筛选口径，未展开原始明细行")
    return result[:3]


def _original_points(context: _FrameContext, *, limit: int) -> list[str]:
    points: list[str] = []
    candidates: list[str] = []
    for line in _sanitize_text(context.original_answer).splitlines():
        clean_line = line.strip(" -•\t")
        if not clean_line:
            continue
        candidates.extend(part for part in re.split(r"(?<=[。！？!?])", clean_line) if part.strip())
    if not candidates:
        candidates = _sentences(context.original_answer)
    for sentence in candidates:
        sentence = _strip_sentence_punctuation(sentence.strip(" -•\t"))
        if sentence.lower() == "not applicable":
            continue
        points.append(sentence)
        if len(points) >= limit:
            break
    return points


def _keyword_point(context: _FrameContext, keyword: str) -> str:
    for line in _sanitize_text(context.original_answer).splitlines():
        text = _strip_sentence_punctuation(line.strip(" -•\t"))
        if keyword in text:
            return text
    return ""


def _keyword_any_point(context: _FrameContext, keywords: tuple[str, ...]) -> str:
    for keyword in keywords:
        point = _keyword_point(context, keyword)
        if point:
            return point
    return ""


def _metric_summary_rows(report: dict[str, Any]) -> list[str]:
    summary = report.get("metric_summary")
    if not isinstance(summary, dict):
        return []
    rows = summary.get("rows")
    if not isinstance(rows, list):
        return []
    result: list[str] = []
    for row in rows[:3]:
        if not isinstance(row, dict):
            continue
        label = str(row.get("指标") or row.get("metric") or "").strip()
        value = str(row.get("数值") or row.get("value") or "").strip()
        if label and value:
            result.append(f"{label}={value}")
    return result


def _merge_points(primary: list[str], fallback: list[str], *, limit: int) -> list[str]:
    result: list[str] = []
    for item in [*primary, *fallback]:
        text = _strip_sentence_punctuation(str(item or "").strip())
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _dedupe_points(values: list[Any], *, limit: int) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _strip_sentence_punctuation(str(value or "").strip())
        if text and not _has_forbidden_marker(text) and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _business_suggestion_lines(context: _FrameContext) -> list[str]:
    shape_issue = _result_shape_issue(context)
    if shape_issue:
        return [
            "先按 SKU 编码去重，或按 SKU 聚合金额、数量后再做品类汇总",
            "确认 TopN 的排序指标、时间范围和品类字段，避免把明细重复当成 SKU 排名",
            "等结果满足口径后，再分析头部品类贡献和长尾品类机会",
        ]
    if context.kind == "clarification":
        return [
            f"先补充{_missing_information(context)}，再重新计算",
            "不要用猜测字段或外部映射替代当前上传数据里不存在的口径",
            "补齐口径后优先输出可复核结果表，再做业务解读",
        ]
    if context.kind in {"cleaning", "quality"}:
        return [
            "先确认影响行数最高的质量规则，再决定删除、填充、标记或暂不处理",
            "正式清洗前导出副本并保留原始数据，避免覆盖不可恢复",
            "清洗后重新跑关键指标，比较清洗前后结果差异",
        ]
    if _asks_reasonableness_comparison(context):
        return [
            "先定义合理性的业务基准、阈值或同类对照口径，再判断当前指标关系是否异常",
            "补充历史趋势、同城市同月基准或同类城市对比，避免只凭两个指标值下经营结论",
            "确认工单、销售等指标是否属于同一时间、同一对象和同一统计粒度",
        ]
    insight = _as_dict(context.response.get("insight"))
    existing = []
    for key in ("business_suggestions", "suggestions"):
        for item in insight.get(key) or []:
            text = _strip_sentence_punctuation(str(item or "").strip())
            if text and not _has_forbidden_marker(text):
                existing.append(text)
    if existing:
        return _dedupe_points(existing, limit=3)
    if not context.rows and context.kind != "overview":
        return [
            "先扩大或修正筛选条件，确认是否确实没有符合条件的数据",
            "补充可计算字段和时间范围后再生成经营建议",
        ]
    if context.kind == "overview":
        return [
            "优先确认事实表、维表、时间字段和核心指标字段",
            "先做一版 TopN、趋势和质量检查，建立可复核的数据地图",
            "多表分析前先确认关联键和时间粒度，避免误 join",
        ]
    if context.kind == "target_actual":
        return [
            "优先复盘完成率最低项的目标来源、实际来源和周期完整性",
            "把未达标项继续拆到产品、区域或负责人，定位差距来源",
            "对完成率异常高或异常低的对象做质量和口径复核",
        ]
    if context.kind == "trend":
        return [
            "优先复核峰值、低点和最大变化周期对应的业务事件或数据完整性",
            "把主要变化按区域、产品或渠道拆分，判断是整体变化还是结构变化",
            "检查最近一个周期是否完整，避免把未完结周期当成下降",
        ]
    if context.kind == "ranking":
        return [
            "优先复核 Top 项的时间、区域或渠道拆分，确认贡献来源",
            "比较第一名和第二名的差距，判断是否存在头部集中",
            "同时查看低排名项，排除缺失值或异常值导致的排名偏差",
        ]
    return [
        "围绕当前已验证结果继续下钻关键维度",
        "复核异常值、缺失值和筛选口径是否影响结论",
        "将结果表和图表一起保存，便于后续复查",
    ]


def _boundary_lines(context: _FrameContext) -> list[str]:
    lines: list[str] = []
    shape_issue = _result_shape_issue(context)
    if shape_issue:
        lines.append(shape_issue)
    if not context.rows and context.kind not in {"overview", "clarification", "cleaning", "quality"}:
        lines.append("当前结果没有返回可分析明细或聚合行，不能据此生成经营判断")
    for label, value in _scope_lines(context):
        if value:
            lines.append(f"{label}：{value}")
    return _dedupe_points(lines, limit=5)


def _scope_lines(context: _FrameContext) -> list[tuple[str, str]]:
    lines = [
        ("数据范围", _data_scope(context)),
        ("指标口径", _metric_scope(context)),
    ]
    join_scope = _join_scope(context)
    if join_scope:
        lines.append(("关联口径", join_scope))
    lines.append(("注意事项", _caveat_scope(context)))
    return lines


def _result_shape_issue(context: _FrameContext) -> str:
    if not context.rows:
        return ""
    question = context.question.lower().replace(" ", "")
    asks_sku = "sku" in question or "商品" in question or "产品" in question
    asks_category_group = "按品类" in question or "品类分组" in question or "category" in question
    requested_n = _requested_topn_count(context.question)
    if not asks_sku and not asks_category_group and requested_n < 2:
        return ""
    sku_col = _first_matching_column(context.columns, ("sku", "商品编码", "商品编号", "产品编码", "产品编号"))
    label_col = sku_col or _preferred_label_column(context.columns, _preferred_metric_column(context.columns, context.rows))
    if not label_col:
        return ""
    values = [str(row.get(label_col) or "").strip() for row in context.rows if str(row.get(label_col) or "").strip()]
    distinct_values = sorted(set(values))
    if len(context.rows) <= 1 or len(distinct_values) != 1:
        return ""
    expected = requested_n if requested_n >= 2 else len(context.rows)
    sample = distinct_values[0]
    entity = "SKU" if asks_sku or (sku_col and "sku" in sku_col.lower()) else label_col
    group_suffix = "，也不能直接作为按品类分组汇总结果" if asks_category_group else ""
    return (
        f"当前结果没有返回 {expected} 个不同{entity}；{label_col} 只有 1 个不同值（{sample}），"
        f"更像明细重复或未按 {entity} 去重/聚合{group_suffix}"
    )


def _requested_topn_count(question: str) -> int:
    text = _normalize_digits(str(question or "").lower())
    for pattern in (
        r"(?:top|前|最高的|最低的)\s*(\d{1,3})",
        r"这\s*(\d{1,3})\s*个",
        r"(\d{1,3})\s*(?:个|名|条)\s*(?:sku|商品|产品|品类)",
    ):
        match = re.search(pattern, text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return 0
    return 0


def _normalize_digits(value: str) -> str:
    table = str.maketrans("０１２３４５６７８９", "0123456789")
    return value.translate(table)


def _first_matching_column(columns: list[str], tokens: tuple[str, ...]) -> str | None:
    for token in tokens:
        for column in columns:
            if token.lower() in column.lower():
                return column
    return None


def _join_scope(context: _FrameContext) -> str:
    params = _as_dict(context.logic_form.get("parameters"))
    join_plan = _as_dict(params.get("join_plan") or context.logic_form.get("join_plan"))
    if not join_plan:
        return ""
    if join_plan.get("trusted") is False:
        return "当前关联计划未通过可信校验，不能把跨表结果当成已验证业务口径"
    steps = join_plan.get("steps") if isinstance(join_plan.get("steps"), list) else []
    links: list[str] = []
    for step in steps[:3]:
        step_dict = _as_dict(step)
        link = _join_link_text(step_dict)
        if link:
            links.append(link)
    if not links:
        link = _join_link_text(join_plan)
        if link:
            links.append(link)
    return "；".join(links)


def _join_link_text(join_plan: dict[str, Any]) -> str:
    left = str(join_plan.get("left_table") or "").strip()
    right = str(join_plan.get("right_table") or "").strip()
    left_key = str(join_plan.get("left_key") or "").strip()
    right_key = str(join_plan.get("right_key") or "").strip()
    if left and right and left_key and right_key:
        return f"{left}.{left_key} -> {right}.{right_key}"
    return ""


def _data_scope(context: _FrameContext) -> str:
    refs = _source_reference_text(context.source_references)
    if refs:
        return refs
    report = context.overview_report
    if report.get("report_type") == "source_overview_report":
        return f"{report.get('source_count') or 0} 个上传来源，其中 {report.get('table_source_count') or 0} 个表格来源、{report.get('knowledge_source_count') or 0} 个说明/规则来源"
    if report.get("tables_summary"):
        return f"{report.get('table_count') or len(report.get('tables_summary') or [])} 张表，总计 {_format_plain_value(report.get('total_row_count'))} 行"
    if report:
        table = report.get("table") or "当前表"
        source = report.get("source_file") or table
        row_count = report.get("row_count")
        column_count = report.get("column_count")
        return f"{source} / {table}，{_format_plain_value(row_count)} 行、{_format_plain_value(column_count)} 列"
    tables = context.logic_form.get("source_tables")
    if isinstance(tables, list) and tables:
        return "、".join(str(item) for item in tables[:6])
    return "当前上传数据和本次已验证结果"


def _metric_scope(context: _FrameContext) -> str:
    if context.kind == "target_actual":
        target_cols = [col for col in context.columns if any(token in col.lower() for token in ("目标", "target", "goal"))]
        actual_cols = [col for col in context.columns if any(token in col.lower() for token in ("实际", "actual", "完成", "amount"))]
        rate_cols = [col for col in context.columns if any(token in col.lower() for token in ("完成率", "达成率", "achievement", "rate"))]
        return (
            f"目标来源={_short_join(target_cols, limit=3) or '已验证目标字段'}；"
            f"实际来源={_short_join(actual_cols, limit=3) or '已验证实际字段'}；"
            f"完成率={_short_join(rate_cols, limit=2) or '实际/目标'}"
        )
    if context.kind == "ranking":
        params = _as_dict(context.logic_form.get("parameters"))
        metric = _preferred_metric_column(context.columns, context.rows)
        group = _preferred_label_column(context.columns, metric)
        base = (
            f"按 {group or context.logic_form.get('group_by') or params.get('dimension') or params.get('group_by') or '分组字段'} 聚合后，"
            f"用 {metric or context.logic_form.get('metric') or params.get('metric') or '结果字段'} 排序"
        )
        derived = _derived_metric_scope(context)
        return f"{base}；{derived}" if derived else base
    if context.kind == "trend":
        metric = _preferred_metric_column(context.columns, context.rows)
        period = _preferred_period_column(context.columns)
        return f"按 {period or '结果表周期字段'} 的顺序观察 {metric or context.logic_form.get('metric') or '指标'}，周期是否完整需结合原始数据确认"
    if context.kind in {"cleaning", "quality"}:
        return "按缺失、重复、异常值和字段类型等质量规则做模拟统计，不执行删除、填充或覆盖"
    if context.kind == "overview":
        report = context.overview_report
        if report.get("report_type") == "source_overview_report":
            return "按上传 manifest、文件类型、读取状态和内容摘要解释来源用途；不把说明文件当成可计算事实表"
        tables = report.get("tables_summary")
        if isinstance(tables, list) and tables:
            roles = _overview_table_role_summary(tables)
            return f"表角色={roles or '待确认'}；字段角色来自表名、字段名、类型和样例的安全推断"
        metric = report.get("metric_column")
        dimension = report.get("dimension_column")
        period = report.get("period_column")
        return f"字段角色来自表名、字段名、类型和样例的安全推断；指标={metric or '待确认'}，维度={dimension or '待确认'}，时间={period or '待确认'}"
    if context.kind == "clarification":
        return "尚未形成可计算口径；需要先补齐字段、时间、指标定义、维表或过滤条件"
    operation = str(context.logic_form.get("operation") or "已验证分析")
    params = _as_dict(context.logic_form.get("parameters"))
    metrics = [str(item) for item in params.get("metrics") or [] if str(item)]
    metric = context.logic_form.get("metric") or _preferred_metric_column(context.columns, context.rows)
    group = context.logic_form.get("group_by") or _preferred_label_column(context.columns, str(metric or ""))
    pieces = [f"operation={operation}"]
    if len(metrics) > 1:
        pieces.append("指标=" + "、".join(metrics))
    elif metric:
        pieces.append(f"指标={metric}")
    if group:
        pieces.append(f"分组={group}")
    derived = _derived_metric_scope(context)
    if derived:
        pieces.append(derived)
    return "；".join(pieces)


def _derived_metric_scope(context: _FrameContext) -> str:
    params = _as_dict(context.logic_form.get("parameters"))
    derived_metric = _as_dict(params.get("derived_metric"))
    if not derived_metric:
        return ""
    name = str(derived_metric.get("name") or "派生指标").strip()
    formula = str(derived_metric.get("formula") or "").strip()
    numerator = str(derived_metric.get("numerator") or "").strip()
    denominator = str(derived_metric.get("denominator") or "").strip()
    if formula:
        return f"{name}={formula}"
    if numerator and denominator:
        return f"{name}=sum({numerator})/sum({denominator})"
    return ""


def _multi_metric_result_text(context: _FrameContext) -> str:
    params = _as_dict(context.logic_form.get("parameters"))
    metrics = [str(item) for item in params.get("metrics") or [] if str(item)]
    if len(metrics) <= 1 or not context.rows:
        return ""
    row = context.rows[0]
    values = [
        f"{metric} 为 {_format_cell_value(row.get(metric), metric)}"
        for metric in metrics
        if metric in row and row.get(metric) not in {None, ""}
    ]
    if not values:
        return ""
    dimension = str(params.get("dimension") or "").strip()
    if dimension and dimension in row:
        return f"{row.get(dimension)} 的" + "，".join(values)
    return "本次多指标汇总结果：" + "，".join(values)


def _caveat_scope(context: _FrameContext) -> str:
    if context.kind in {"cleaning", "quality"}:
        return "不会直接修改原始数据，不能覆盖原始文件，需要用户确认，必须等用户明确确认清洗规则、影响范围和导出方式"
    if context.kind == "clarification":
        return "在缺口补齐前，不能把猜测字段、猜测口径或外部映射当成事实"
    if context.kind == "overview":
        return "没有展示原始明细行；字段含义和可分析方向来自概览报告与已验证表画像"
    if _asks_reasonableness_comparison(context):
        return "是否合理需要历史基准、业务阈值或同类对比；当前只展示已验证指标对照，不能仅凭本次结果直接判断合理性"
    verification = _as_dict(context.response.get("verification"))
    notes = verification.get("notes") if isinstance(verification.get("notes"), list) else []
    for note in notes:
        text = _verification_note_scope(note)
        if text:
            return text
    boundaries = context.overview_report.get("missing_boundaries")
    if isinstance(boundaries, list) and boundaries:
        return _sanitize_inline(boundaries[0])
    quality = context.quality_report
    if quality.get("issue_count"):
        return f"质量报告识别到 {quality.get('issue_count')} 个问题，可能影响后续精算"
    return "主回答只引用已验证结果、概览报告和来源引用中的事实，未展开原始明细行"


def _asks_reasonableness_comparison(context: _FrameContext) -> bool:
    params = _as_dict(context.logic_form.get("parameters"))
    if params.get("requires_reasonableness_baseline") is True:
        return True
    question = context.question.replace(" ", "")
    if not any(token in question for token in ("是否合理", "合不合理", "合理", "相比", "对比", "比较")):
        return False
    metrics = [str(item) for item in params.get("metrics") or [] if str(item)]
    if len(metrics) > 1:
        return True
    metric_signals = (
        ("销售额", "销售金额", "销售总额", "收入", "sales", "revenue"),
        ("工单数量", "工单量", "工单数", "工单", "tickets", "ticket"),
        ("利润率", "毛利率", "profitmargin", "margin"),
        ("利润", "毛利", "profit"),
        ("订单金额", "订单总额", "订单总金额", "订单", "amount"),
    )
    lowered = question.lower()
    matched = sum(1 for signals in metric_signals if any(token in question or token in lowered for token in signals))
    return matched >= 2


def _verification_note_scope(value: Any) -> str:
    text = _sanitize_inline(value)
    if not text:
        return ""
    lowered = text.lower()
    if "verifier checked execution success" in lowered or (
        "execution success" in lowered and "semantic metric" in lowered
    ):
        return "执行、后端一致性和语义口径已校验；解读范围以本次数据和当前指标口径为准"
    if _has_cjk(text):
        return text
    if any(token in lowered for token in ("verified", "execution success", "backend consistency", "semantic metric")):
        return "执行结果已通过基础校验；解读范围以本次数据和当前指标口径为准"
    return ""


def _next_questions(context: _FrameContext) -> list[str]:
    insight = _as_dict(context.response.get("insight"))
    existing = [str(item).strip() for item in insight.get("next_questions") or [] if _safe_question(item)]
    if _is_scalar_value_context(
        answer_type=str(context.response.get("answer_type") or ""),
        operation=str(context.logic_form.get("operation") or ""),
    ):
        existing = []
        generated = [
            "按关键维度拆解这个数值",
            "对比相邻时间段或相关对象的同一指标",
            "检查异常值、缺失值或规则口径是否影响该数值",
        ]
    elif context.kind == "overview":
        generated = [
            "按核心指标做一次 TopN 排名",
            "看时间趋势和最大波动月份",
            "检查缺失、重复和异常值对分析的影响",
        ]
    elif context.kind == "target_actual":
        generated = [
            "把完成率最低的对象拆到产品、区域或负责人",
            "对未达标项看目标差距和实际缺口",
            "按月份看完成率趋势和拐点",
        ]
    elif context.kind == "trend":
        generated = [
            "找出峰值、低点和最大环比变化的原因",
            "按区域或产品拆分同一趋势",
            "检查最近一个周期是否为完整周期",
        ]
    elif context.kind == "ranking":
        generated = [
            "把 Top 项继续按时间或区域拆分",
            "比较第一名和第二名的差距",
            "查看低排名项是否有异常或缺失影响",
        ]
    elif context.kind in {"cleaning", "quality"}:
        generated = [
            "按缺失率或异常值数排序查看高风险字段",
            "确认哪些字段需要删除、填充或只标记",
            "生成一份不覆盖原始数据的清洗后副本",
        ]
    elif context.kind == "clarification":
        generated = [
            "告诉我应该使用哪个字段作为指标",
            "补充时间范围和过滤条件后重新计算",
            "上传或指定维表映射后再做关联分析",
        ]
    else:
        generated = [
            "把这个结论按关键维度下钻",
            "检查是否存在异常值或质量问题影响结果",
            "生成可复核的结果表和图表",
        ]
    result: list[str] = []
    for item in [*existing, *generated]:
        text = _strip_sentence_punctuation(str(item).strip())
        if text and text not in result:
            result.append(text)
        if len(result) >= 3:
            break
    return result


def _missing_information(context: _FrameContext) -> str:
    warnings = "；".join(str(item) for item in context.response.get("warnings") or [])
    errors = "；".join(str(item.get("error_message") if isinstance(item, dict) else item) for item in context.response.get("errors") or [])
    text = warnings + "；" + errors + "；" + context.original_answer + "；" + context.question
    missing = []
    if any(token in text for token in ("字段", "field", "column", "不存在")):
        missing.append("可计算字段")
    if any(token in text for token in ("时间", "月份", "日期", "周期", "period")):
        missing.append("时间范围或周期粒度")
    if any(token in text for token in ("口径", "指标", "分母", "分子", "metric")):
        missing.append("指标口径")
    if any(token in text for token in ("维表", "映射", "join", "关联", "真实名称")):
        missing.append("维表或映射关系")
    if any(token in text for token in ("筛选", "过滤", "条件", "where")):
        missing.append("过滤条件")
    return "、".join(missing[:5]) or "字段、时间、口径、维表或过滤条件中的至少一项"


def _top_result_text(context: _FrameContext) -> str:
    if not context.rows:
        return ""
    row = context.rows[0]
    metric = _preferred_metric_column(context.columns, context.rows)
    label = _preferred_label_column(context.columns, metric)
    name = str(row.get(label) if label else _first_non_empty_value(row)).strip()
    if metric:
        extras = _supplemental_row_metrics(row, context.columns, label=label, metric=metric)
        return f"排名结果里首位是 {name}，{metric}为 {_format_cell_value(row.get(metric), metric)}{extras}"
    return f"结果首项是 {_describe_row(row, context.columns)}"


def _top_rows_text(context: _FrameContext) -> str:
    items = []
    metric = _preferred_metric_column(context.columns, context.rows)
    label = _preferred_label_column(context.columns, metric)
    for index, row in enumerate(context.rows[:3], start=1):
        name = str(row.get(label) if label else _first_non_empty_value(row)).strip()
        if metric:
            extras = _supplemental_row_metrics(row, context.columns, label=label, metric=metric, prefix="；")
            items.append(f"第 {index} 位 {name}（{metric}={_format_cell_value(row.get(metric), metric)}{extras}）")
        else:
            items.append(f"第 {index} 位 {_describe_row(row, context.columns)}")
    return "；".join(items)


def _supplemental_row_metrics(
    row: dict[str, Any],
    columns: list[str],
    *,
    label: str | None,
    metric: str | None,
    prefix: str = "，",
) -> str:
    excluded = {str(value) for value in (label, metric) if value}
    extras: list[str] = []
    for column in columns:
        name = str(column or "")
        if not name or name in excluded:
            continue
        value = row.get(name)
        if value in (None, "", []):
            continue
        extras.append(f"{name}为 {_format_cell_value(value, name)}")
        if len(extras) >= 3:
            break
    return f"{prefix}{'，'.join(extras)}" if extras else ""


def _best_metric_row(context: _FrameContext, *, prefer_rate: bool, highest: bool) -> dict[str, str] | None:
    if not context.rows:
        return None
    metric = _preferred_rate_column(context.columns) if prefer_rate else None
    metric = metric or _preferred_metric_column(context.columns, context.rows)
    if not metric:
        return None
    candidates = []
    for row in context.rows:
        value = _to_float(row.get(metric))
        if value is None:
            continue
        candidates.append((value, row))
    if not candidates:
        return None
    _, row = max(candidates, key=lambda item: item[0]) if highest else min(candidates, key=lambda item: item[0])
    label_col = _preferred_period_column(context.columns) or _preferred_label_column(context.columns, metric)
    label = str(row.get(label_col) if label_col else _first_non_empty_value(row)).strip()
    return {"label": label or "该项", "metric": metric, "value": _format_cell_value(row.get(metric), metric)}


def _trend_summary(context: _FrameContext) -> str:
    multi_series = _multi_series_trend_points(context)
    if multi_series:
        return "；".join(multi_series[:3])
    metric = _preferred_metric_column(context.columns, context.rows)
    period = _preferred_period_column(context.columns)
    if not metric or len(context.rows) < 2:
        return _fallback_core(context)
    time_points: list[tuple[str, float, Any]] = []
    for row in context.rows:
        value = _to_float(row.get(metric))
        if value is None:
            continue
        label = str(row.get(period) if period else "")
        time_points.append((label, value, row.get(metric)))
    if len(time_points) < 2:
        return _fallback_core(context)
    sequence = [(label or str(index), value) for index, (label, value, _raw) in enumerate(time_points)]
    trend = describe_trend(sequence)
    if trend == "单调上升":
        direction = "整体上升"
    elif trend == "单调下降":
        direction = "整体下降"
    elif trend == "基本持平":
        direction = "整体持平"
    else:
        direction = trend
    start_label = str(time_points[0][0] or "首期")
    end_label = str(time_points[-1][0] or "末期")
    start_value = time_points[0][2]
    end_value = time_points[-1][2]
    return f"{metric}{direction}趋势，从 {start_label} 的 {_format_cell_value(start_value, metric)} 到 {end_label} 的 {_format_cell_value(end_value, metric)}"


def _extrema_text(context: _FrameContext) -> str:
    points = _multi_series_trend_points(context) or _trend_points(context)
    return "；".join(points[:3]) if points else ""


def _multi_series_trend_points(context: _FrameContext) -> list[str]:
    period = _preferred_period_column(context.columns)
    series_columns = _multi_series_value_columns(context.columns, context.rows, period)
    if not period or len(series_columns) < 2 or len(context.rows) < 2:
        return []
    series_profiles = []
    for column in series_columns:
        values = [_to_float(row.get(column)) for row in context.rows]
        numeric_values = [value for value in values if value is not None]
        if len(numeric_values) < 2:
            continue
        indexed = [(index, value) for index, value in enumerate(values) if value is not None]
        total = sum(numeric_values)
        peak_index, peak_value = max(indexed, key=lambda item: item[1])
        leader_count = 0
        for row in context.rows:
            row_values = [_to_float(row.get(name)) for name in series_columns]
            valid_values = [value for value in row_values if value is not None]
            current = _to_float(row.get(column))
            if current is not None and valid_values and math.isclose(current, max(valid_values), rel_tol=1e-9, abs_tol=1e-9):
                leader_count += 1
        last_change = None
        previous_value = values[-2]
        current_value = values[-1]
        if previous_value is not None and current_value is not None:
            last_change = current_value - previous_value
        series_profiles.append(
            {
                "column": column,
                "total": total,
                "leader_count": leader_count,
                "peak_index": peak_index,
                "peak_value": peak_value,
                "last_change": last_change,
            }
        )
    if len(series_profiles) < 2:
        return []
    leader = max(series_profiles, key=lambda item: item["total"])
    leader_periods = int(leader["leader_count"])
    if leader_periods == len(context.rows):
        leader_text = f"{leader['column']} 持续领先"
    elif leader_periods >= max(2, len(context.rows) - 1):
        leader_text = f"{leader['column']} 在大多数周期领先"
    else:
        leader_text = f"{leader['column']} 整体规模最高"
    points = [leader_text]
    growth_candidates = [item for item in series_profiles if item.get("last_change") not in {None, 0}]
    if growth_candidates:
        growth = max(growth_candidates, key=lambda item: float(item.get("last_change") or float("-inf")))
        if float(growth.get("last_change") or 0.0) > 0:
            points.append(f"{growth['column']} 在 {context.rows[-1].get(period)} 明显跃升")
    peak_candidates = [item for item in series_profiles if item["column"] != leader["column"]]
    if peak_candidates:
        peak = max(peak_candidates, key=lambda item: item["peak_value"])
        peak_period = context.rows[int(peak["peak_index"])].get(period)
        points.append(f"{peak['column']} 在 {peak_period} 达到阶段峰值")
    return points[:3]


def _trend_points(context: _FrameContext) -> list[str]:
    metric = _preferred_metric_column(context.columns, context.rows)
    period = _preferred_period_column(context.columns)
    if not metric or not context.rows:
        return []
    candidates = [(float_value, row) for row in context.rows if (float_value := _to_float(row.get(metric))) is not None]
    if not candidates:
        return []
    high_value, high_row = max(candidates, key=lambda item: item[0])
    low_value, low_row = min(candidates, key=lambda item: item[0])
    lines = [
        f"峰值出现在 {high_row.get(period) if period else '结果表'}，{metric}为 {_format_cell_value(high_value, metric)}",
        f"低点出现在 {low_row.get(period) if period else '结果表'}，{metric}为 {_format_cell_value(low_value, metric)}",
    ]
    if len(candidates) >= 2:
        deltas = []
        for index in range(1, len(context.rows)):
            previous = _to_float(context.rows[index - 1].get(metric))
            current = _to_float(context.rows[index].get(metric))
            if previous is None or current is None:
                continue
            deltas.append((abs(current - previous), context.rows[index - 1], context.rows[index], current - previous))
        if deltas:
            _, prev_row, row, delta = max(deltas, key=lambda item: item[0])
            lines.append(
                f"最大变化发生在 {prev_row.get(period) if period else '上一期'} 到 {row.get(period) if period else '下一期'}，变化 {_format_cell_value(delta, metric)}"
            )
    return lines[:3]


def _source_reference_text(references: list[Any]) -> str:
    items = []
    for ref in references[:3]:
        if not isinstance(ref, dict):
            continue
        file_name = str(ref.get("file_name") or "").strip()
        tables = ref.get("tables") if isinstance(ref.get("tables"), list) else []
        table_text = _short_join(
            [
                f"{table.get('table_name') or table.get('sheet') or '表'}"
                + (
                    f"({_format_plain_value(table.get('row_count'))} 行"
                    + (f"、{_format_plain_value(table.get('column_count'))} 列" if table.get("column_count") is not None else "")
                    + ")"
                    if table.get("row_count") is not None
                    else ""
                )
                for table in tables[:3]
                if isinstance(table, dict)
            ],
            limit=3,
        )
        if file_name:
            items.append(f"{file_name}{f'：{table_text}' if table_text else ''}")
    return "；".join(items)


def _result_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = result.get("rows")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    value = result.get("value")
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _result_columns(result: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    columns = result.get("columns")
    if isinstance(columns, list):
        return [str(column) for column in columns]
    if rows:
        return [str(column) for column in rows[0].keys()]
    return []


def _preferred_metric_column(columns: list[str], rows: list[dict[str, Any]]) -> str | None:
    candidates = [column for column in columns if _numeric_ratio(rows, column) >= 0.5 and not _looks_identifier(column)]
    if not candidates:
        return None
    preferred = ("完成率", "达成率", "销售额", "金额", "收入", "目标", "实际", "数量", "占比", "比例", "rate", "amount", "revenue", "sales", "count")
    for token in preferred:
        for column in candidates:
            if token.lower() in column.lower():
                return column
    return candidates[-1] if len(candidates) > 1 else candidates[0]


def _preferred_rate_column(columns: list[str]) -> str | None:
    for column in columns:
        lowered = column.lower()
        if any(token in lowered for token in ("完成率", "达成率", "占比", "比例", "rate", "share", "pct", "%")):
            return column
    return None


def _preferred_label_column(columns: list[str], metric: str | None) -> str | None:
    preferred = ("月份", "日期", "周", "城市", "区域", "客户", "产品", "负责人", "姓名", "名称", "类型", "category", "city", "region", "name", "month", "date")
    non_metric = [column for column in columns if column != metric]
    for token in preferred:
        for column in non_metric:
            if token.lower() in column.lower():
                return column
    for column in non_metric:
        if not _looks_identifier(column):
            return column
    return non_metric[0] if non_metric else None


def _preferred_period_column(columns: list[str]) -> str | None:
    for token in ("月份", "日期", "周", "季度", "年度", "年月", "month", "date", "week", "period", "year"):
        for column in columns:
            if token.lower() in column.lower():
                return column
    return None


def _multi_series_value_columns(columns: list[str], rows: list[dict[str, Any]], period_column: str | None) -> list[str]:
    excluded = {period_column, _preferred_rate_column(columns)}
    return [column for column in columns if column not in excluded and _numeric_ratio(rows, column) >= 0.5 and not _looks_identifier(column)]


def _numeric_ratio(rows: list[dict[str, Any]], column: str) -> float:
    values = [row.get(column) for row in rows if row.get(column) not in {None, ""}]
    if not values:
        return 0.0
    return sum(1 for value in values if _to_float(value) is not None) / len(values)


def _looks_identifier(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in ("id", "code", "编号", "编码", "序号", "单号", "订单号"))


def _to_float(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "").rstrip("%"))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _format_cell_value(value: Any, column: str | None = None) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    number = _to_float(value)
    if number is None:
        return str(value)
    column_text = str(column or "").lower()
    if any(token in column_text for token in ("率", "占比", "比例", "rate", "share", "pct", "%")):
        if abs(number) <= 1:
            number *= 100
        return f"{number:,.2f}%"
    if math.isclose(number, round(number)):
        return f"{int(round(number)):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _format_plain_value(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return str(value or 0)
    if math.isclose(number, round(number)):
        return f"{int(round(number)):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _describe_row(row: dict[str, Any], columns: list[str]) -> str:
    parts = []
    for column in columns[:5] or list(row.keys())[:5]:
        value = row.get(column)
        if value not in {None, ""}:
            parts.append(f"{column}={_format_cell_value(value, column)}")
    return "，".join(parts)


def _first_existing(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in row and row.get(key) not in {None, ""}:
            return row.get(key)
    return None


def _first_non_empty_value(row: dict[str, Any]) -> Any:
    for value in row.values():
        if value not in {None, ""}:
            return value
    return ""


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    return {}


def _sentences(text: str) -> list[str]:
    raw = _sanitize_text(text)
    parts = re.split(r"(?<=[。！？!?])\s+|[\n\r]+", raw)
    result = []
    for part in parts:
        clean = _strip_sentence_punctuation(part.strip(" -•\t"))
        if clean and not _has_forbidden_marker(clean):
            result.append(clean)
    return result


def _first_sentence(text: str, *, limit: int) -> str:
    sentences = _sentences(text)
    value = sentences[0] if sentences else _sanitize_text(text)
    if len(value) <= limit:
        return _strip_sentence_punctuation(value)
    return _strip_sentence_punctuation(value[:limit].rstrip()) + "..."


def _short_meaning(value: Any) -> str:
    text = _strip_sentence_punctuation(str(value or "").strip())
    if not text:
        return ""
    return text.split("，")[0].split("；")[0]


def _short_join(values: Any, *, limit: int, separator: str = "、") -> str:
    if not isinstance(values, (list, tuple, set)):
        return ""
    result: list[str] = []
    for value in values:
        text = _strip_sentence_punctuation(str(value or "").strip())
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return separator.join(result)


def _safe_question(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and not _has_forbidden_marker(text)


def _looks_frameworked(text: str) -> bool:
    return all(heading in str(text or "") for heading in FRAMEWORK_HEADINGS)


def _sanitize_text(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    safe_lines = []
    for line in text.splitlines():
        if _has_forbidden_marker(line):
            continue
        safe_lines.append(line.rstrip())
    safe = "\n".join(safe_lines).strip()
    for marker in FORBIDDEN_MARKERS:
        safe = re.sub(re.escape(marker), "[redacted]", safe, flags=re.IGNORECASE)
    return safe


def _sanitize_inline(value: Any) -> str:
    text = _sanitize_text(value).replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _has_forbidden_marker(text: Any) -> bool:
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in FORBIDDEN_MARKERS)


def _has_cjk(text: Any) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(text or "")))


def _strip_sentence_punctuation(text: str) -> str:
    return str(text or "").strip().rstrip("。；;,.，")


def _strip_heading_prefix(text: str) -> str:
    value = str(text or "").replace("已帮你看了这个数据，核心结论是：", "", 1).strip()
    for heading in FRAMEWORK_HEADINGS:
        value = value.replace(heading, "", 1).strip(" ：:\n")
    return value


def _mark_debug(response: dict[str, Any], *, applied: bool, reason: str) -> None:
    debug = response.setdefault("debug", {})
    if isinstance(debug, dict):
        debug["text_answer_framework"] = {
            "applied": applied,
            "reason": reason,
            "version": "bigcat_evidence_report_v2",
        }


def _attach_process_note(response: dict[str, Any], *, direct: bool = False) -> None:
    process = response.get("process_view_v2")
    if not isinstance(process, dict):
        return
    steps = process.setdefault("steps", [])
    if not isinstance(steps, list):
        return
    if any(isinstance(step, dict) and step.get("title") == "整理结构化回答" for step in steps):
        return
    steps.append(
        {
            "title": "整理结构化回答",
            "summary": "已把已验证结果整理为直答或结构化回答；没有重新计算数字。" if direct else "已把已验证结果整理为数据摘要、分析洞察、业务建议、口径边界和下一步；没有重新计算数字。",
            "status": "completed",
            "evidence": ["text_framework=direct_answer_v1" if direct else "text_framework=bigcat_evidence_report_v2"],
            "assumptions": [],
            "caveats": ["只使用 response 中已有的验证结果、概览报告、质量报告和来源引用。"],
            "confidence": 0.86,
            "source": "response_contract",
        }
    )
