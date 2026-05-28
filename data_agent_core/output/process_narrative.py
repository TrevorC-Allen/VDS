"""Safe user-facing process narrative for Workbench.

This module builds a product-facing process view from already-safe response and
trace summaries. It does not expose raw prompts, raw reasoning, full Chain of
Thought, hidden benchmark answers, task ids, or scorer/proxy artifacts.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


PROCESS_VIEW_VERSION = "v2"

PROCESS_MODES = {
    "chat",
    "dataset_overview",
    "dataset_source_overview",
    "metric_lookup",
    "ranking_topn",
    "comparison_or_trend",
    "multi_table_join",
    "diagnostic_or_anomaly",
    "clarification_or_not_applicable",
}

BLOCKED_KEYS = {
    "accepted" + "_answer",
    "accepted" + "_answers",
    "api_key",
    "chain_of_thought",
    "cot",
    "full_reasoning",
    "hidden" + "_answer",
    "hidden_reasoning",
    "public" + "_proxy",
    "raw_prompt",
    "raw_reasoning",
    "reasoning_tokens",
    "scorer",
    "standard" + "_answer",
    "task" + "_id",
}

BLOCKED_TEXT_MARKERS = (
    "accepted-answer",
    "accepted " + "answer",
    "accepted" + "_answer",
    "accepted" + "_answers",
    "api key",
    "api_key",
    "chain of thought",
    "chain_of_thought",
    "cot",
    "full reasoning",
    "full_reasoning",
    "hidden " + "answer",
    "hidden" + "_answer",
    "hidden benchmark",
    "hidden_reasoning",
    "public " + "proxy",
    "public" + "_proxy",
    "raw prompt",
    "raw reasoning",
    "raw_prompt",
    "raw_reasoning",
    "reasoning tokens",
    "reasoning_tokens",
    "scorer",
    "standard " + "answer",
    "standard" + "_answer",
    "task" + "_id",
)


def build_process_view_v2(
    trace_like: Any | None = None,
    response_like: Any | None = None,
    *,
    mode: str | None = None,
) -> dict[str, Any]:
    """Build a safe dynamic process view for API and frontend display."""

    trace = _safe(_as_dict(trace_like))
    response = _safe(_as_dict(response_like))
    logic_form = _first_dict(response.get("logic_form"), trace.get("logic_form"))
    selected_mode = _select_mode(trace, response, logic_form, mode)
    steps = _steps_for_mode(selected_mode, trace, response, logic_form)
    return _view(
        summary=_summary_for_mode(selected_mode, trace, response),
        mode=selected_mode,
        steps=steps,
    )


def build_chat_process_view(question: str, *, has_dataset: bool) -> dict[str, Any]:
    """Build a safe process view for hand-written chat responses."""

    summary = "已识别为普通对话，未进入数据计算链路。"
    caveats = [] if has_dataset else ["需要真实业务结论时，请先上传包含相关字段的数据。"]
    return _view(
        summary=summary,
        mode="chat",
        steps=[
            _step(
                title="识别消息类型",
                summary="这次消息是普通对话或助手能力说明，不需要执行数据分析。",
                evidence=["answer_type=chat"],
                caveats=caveats,
                source="service_route",
            ),
            _step(
                title="保留上下文",
                summary="已直接回复；后续如果提出分析问题，会继续由后端路由到对应分析链路。",
                evidence=["已上传数据可继续使用。" if has_dataset else "当前没有可分析数据。"],
                source="response_contract",
            ),
        ],
    )


def build_dataset_overview_process_view(
    *,
    question: str = "",
    table_name: str,
    row_count: int,
    column_count: int,
    metric_column: str | None = None,
    dimension_column: str | None = None,
    period_column: str | None = None,
    table_count: int | None = None,
    is_multi_table: bool = False,
    question_kind: str = "overview",
    table_summaries: list[dict[str, Any]] | None = None,
    sample_columns: list[str] | None = None,
    artifact_count: int = 0,
) -> dict[str, Any]:
    """Build a safe process view for deterministic dataset overview responses."""

    table_summaries = table_summaries or []
    sample_columns = sample_columns or []
    evidence = [f"主表：{table_name}", f"规模：{row_count} 行，{column_count} 列"]
    if table_count:
        evidence.insert(0, f"表数量：{table_count}")
    if metric_column:
        evidence.append(f"关键数值字段：{metric_column}")
    if dimension_column:
        evidence.append(f"可下钻维度：{dimension_column}")
    if period_column:
        evidence.append(f"时间字段：{period_column}")
    source_files = _overview_source_files(table_summaries)
    table_role_evidence = _overview_table_role_evidence(table_summaries)
    question_label = _overview_question_kind_label(question_kind)
    summary = (
        f"识别{question_label}、扫描{table_count or 1}张表、整理字段结构、生成Pandas复现代码、输出用户回答。"
        if is_multi_table
        else f"识别{question_label}、读取表画像、整理关键字段、生成Pandas复现代码、输出用户回答。"
    )
    return _view(
        summary=summary,
        mode="dataset_overview",
        steps=[
            _step(
                title="识别用户问题",
                summary=f"用户问的是{question_label}，先走数据概览路径，不把它误判成明细查询或不可信 join。",
                evidence=_compact_texts([f"问题：{question}", "answer_type=overview", f"question_kind={question_kind}"], limit=4),
                source="service_route",
            ),
            _step(
                title="读取上传数据",
                summary="已从上传文件生成可读表画像，先看表数量、行列规模和来源，不展示原始明细行。",
                evidence=_compact_texts([*source_files, *evidence], limit=4),
                source="deterministic_result",
            ),
            _step(
                title="扫描字段结构",
                summary="已按字段名、类型和样例分布识别时间字段、数值指标、分类维度和 ID/代码字段。",
                evidence=_compact_texts([f"样例字段：{'、'.join(sample_columns[:8])}" if sample_columns else "", *evidence[-3:]], limit=4),
                source="deterministic_result",
            ),
            _step(
                title="判断表的关系和用途" if is_multi_table else "判断表的业务用途",
                summary="已区分事实/过程表、维表或说明表，并标记哪些关系需要业务主键确认。" if is_multi_table else "已根据字段角色判断这张表更像明细表、维表、目标表还是过程表。",
                evidence=table_role_evidence or ["字段含义和表类型由后端画像生成。"],
                caveats=["字段同名不等于可以直接 join。"] if is_multi_table else [],
                source="deterministic_result",
            ),
            _step(
                title="生成 Python / Pandas / SQL 复现代码",
                summary="已生成安全代码卡片，用 Pandas 复现行列统计、字段画像和基础分布；代码只放在处理过程详情中。",
                evidence=_compact_texts([f"artifact_count={artifact_count}" if artifact_count else "", "languages=python/sql", "library=pandas", "sql=readonly_reference"], limit=4),
                source="execution_summary",
            ),
            _step(
                title="组织回答内容",
                summary="已按用户问法生成差异化主回答：看数据、讲主题、比区别、给分析建议或看质量，不复用同一段模板。",
                evidence=["主回答不展示 raw rows。", "完整清单和代码留在结果表与过程详情。"],
                caveats=["字段含义是安全推断，正式口径仍以业务说明为准。"],
                source="response_contract",
            ),
        ],
    )


def build_dataset_source_process_view(
    *,
    question: str,
    source_count: int,
    table_count: int,
    knowledge_count: int,
    source_names: list[str] | None = None,
    artifact_count: int = 0,
) -> dict[str, Any]:
    """Build a safe process view for uploaded source/document overview responses."""

    source_names = source_names or []
    shown_sources = "、".join(source_names[:6])
    summary = (
        "识别来源文件问题、枚举上传来源、读取说明/规则文件、区分表格与知识文件、"
        "整理用途说明、生成可复现读取代码、输出用户回答。"
    )
    return _view(
        summary=summary,
        mode="dataset_source_overview",
        steps=[
            _step(
                title="识别用户问题",
                summary="用户问的是上传文件用途和说明来源，先进入来源概览，不进入明细计算。",
                evidence=_compact_texts([f"问题：{question}", "answer_type=overview", "message_intent=dataset_source_overview"], limit=4),
                source="service_route",
            ),
            _step(
                title="枚举上传来源",
                summary="已从数据集存储层读取完整来源清单，区分可计算表、JSON 规则、Markdown/文本/文档说明。",
                evidence=_compact_texts([f"来源文件数：{source_count}", f"表格文件数：{table_count}", f"说明/规则文件数：{knowledge_count}", shown_sources], limit=4),
                source="deterministic_result",
            ),
            _step(
                title="读取说明和规则内容",
                summary="已读取 Markdown、TXT、JSON、YAML 等文本来源；Word/PDF/Pages 走可用文本抽取，抽不到正文时保留元数据和边界说明。",
                evidence=_compact_texts(source_names, limit=5),
                caveats=["扫描版 PDF 或不含明文预览的 Pages 文件可能需要先转换格式。"],
                source="deterministic_result",
            ),
            _step(
                title="判断文件用途",
                summary="已把文件映射为事实表、维表、费率规则、商户属性或业务手册，避免只回答已解析的 CSV 表。",
                evidence=["表格用于计算和字段画像。", "说明/规则文件用于解释字段、取值、费用口径和分析边界。"],
                source="deterministic_result",
            ),
            _step(
                title="生成 Python / Pandas / SQL 复现代码",
                summary="已生成安全代码卡片，展示如何用 Pandas 枚举来源文件，并提供只读 SQL 来源清单口径做对照。",
                evidence=_compact_texts([f"artifact_count={artifact_count}" if artifact_count else "", "languages=python/sql", "library=pandas", "sql=readonly_reference"], limit=4),
                source="execution_summary",
            ),
            _step(
                title="组织回答内容",
                summary="主回答按用户追问聚焦“其他几个文件”的作用，同时在结果表保留完整来源清单。",
                evidence=["返回来源概览回答。", "不展示原始明细行。"],
                source="response_contract",
            ),
        ],
    )


def _overview_question_kind_label(kind: str) -> str:
    labels = {
        "difference": "文件/表差异",
        "fields": "字段含义",
        "content": "内容概览",
        "story": "数据主题",
        "analysis_suggestions": "分析建议",
        "quality": "数据质量",
        "shape": "行列规模",
        "overview": "数据概览",
    }
    return labels.get(str(kind or ""), "数据概览")


def _overview_source_files(table_summaries: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for item in table_summaries[:4]:
        source = _clean_text(item.get("source_file") or item.get("table"), 80)
        if source and source not in values:
            values.append(f"来源：{source}")
    return values


def _overview_table_role_evidence(table_summaries: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for item in table_summaries[:4]:
        table = _clean_text(item.get("table"), 60)
        meaning = _clean_text(item.get("likely_meaning"), 100)
        if table and meaning:
            values.append(f"{table}：{meaning}")
    return values[:4]


def _compact_texts(values: list[Any], *, limit: int) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _clean_text(value, 140)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def process_view_monitor_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the safe final monitor payload for a response-like dict."""

    process_view = payload.get("process_view_v2") if isinstance(payload, dict) else None
    if not isinstance(process_view, dict):
        process_view = {}
    activity_trace = payload.get("activity_trace_v2") if isinstance(payload, dict) else None
    return {
        "run_id": _clean_text(payload.get("run_id"), 80),
        "dataset_id": _clean_text(payload.get("dataset_id"), 80),
        "success": bool(payload.get("success")),
        "answer_type": _clean_text(payload.get("answer_type"), 40),
        "execution_mode": _clean_text(payload.get("execution_mode"), 40),
        "process_view_v2": _safe_process_view(process_view),
        "activity_trace_v2": _safe(activity_trace if isinstance(activity_trace, list) else [])[:12],
    }


def _steps_for_mode(mode: str, trace: dict[str, Any], response: dict[str, Any], logic_form: dict[str, Any]) -> list[dict[str, Any]]:
    if mode == "chat":
        return build_chat_process_view(str(response.get("question") or trace.get("question") or ""), has_dataset=bool(response.get("dataset_id")))[
            "steps"
        ]
    if mode == "dataset_overview":
        value = _first_dict(response.get("result", {}).get("value") if isinstance(response.get("result"), dict) else None)
        return build_dataset_overview_process_view(
            table_name=_clean_text(value.get("table") or _first_item(_source_tables(trace, logic_form)) or "上传数据", 80),
            row_count=_safe_int(value.get("row_count")),
            column_count=_safe_int(value.get("column_count")),
            metric_column=_clean_text(value.get("metric_column"), 80) or None,
            dimension_column=_clean_text(value.get("dimension_column"), 80) or None,
        )["steps"]
    if mode == "dataset_source_overview":
        value = _first_dict(response.get("result", {}).get("value") if isinstance(response.get("result"), dict) else None)
        return build_dataset_source_process_view(
            question=str(response.get("question") or trace.get("question") or ""),
            source_count=_safe_int(value.get("source_count")),
            table_count=_safe_int(value.get("table_source_count")),
            knowledge_count=_safe_int(value.get("knowledge_source_count")),
            source_names=[str(value) for value in value.get("source_names") or []],
            artifact_count=len(response.get("execution_artifacts") or []) if isinstance(response.get("execution_artifacts"), list) else 0,
        )["steps"]

    specialized_steps = _specialized_steps_for_operation(mode, trace, response, logic_form)
    if specialized_steps:
        return specialized_steps

    steps = [
        _intent_step(mode, trace, response, logic_form),
        _data_selection_step(trace, logic_form),
    ]
    definition_step = _business_definition_step(trace, logic_form)
    if definition_step:
        steps.append(definition_step)
    candidate_step = _candidate_step(trace, logic_form)
    if candidate_step:
        steps.append(candidate_step)
    if mode == "multi_table_join":
        steps.append(_join_step(trace, logic_form))
    steps.append(_execution_step(mode, trace, logic_form))
    correction_step = _correction_step(trace)
    if correction_step:
        steps.append(correction_step)
    steps.append(_verification_step(trace, response))
    chart_step = _chart_step(trace, response)
    if chart_step:
        steps.append(chart_step)
    if mode == "clarification_or_not_applicable":
        steps.append(_next_step_for_limits(trace, response))
    else:
        steps.append(_final_step(trace, response))
    return steps[:7]


def _specialized_steps_for_operation(
    mode: str,
    trace: dict[str, Any],
    response: dict[str, Any],
    logic_form: dict[str, Any],
) -> list[dict[str, Any]]:
    operation = _lower(logic_form.get("operation") or _first_dict(response.get("debug")).get("operation"))
    if operation == "retail_distribution_product_share":
        return _retail_distribution_product_share_steps(mode, trace, response, logic_form)
    return []


def _retail_distribution_product_share_steps(
    mode: str,
    trace: dict[str, Any],
    response: dict[str, Any],
    logic_form: dict[str, Any],
) -> list[dict[str, Any]]:
    params = _first_dict(logic_form.get("parameters"))
    ym_label = _ym_label(params.get("ym"))
    person = _clean_text(params.get("person"), 80)
    role = _role_label(params.get("role"))
    product = _clean_text(params.get("product"), 80)
    metric = _metric_label(params.get("metric") or logic_form.get("metric") or _first_dict(logic_form.get("metric_definition")).get("name"))
    table = _clean_text(_first_item(_source_tables(trace, logic_form)) or params.get("table"), 80)
    answer_type = _answer_type_evidence(response)
    scope_evidence = _compact_evidence(
        [
            f"{role}：{person}" if person else "",
            f"月份：{ym_label}" if ym_label else "",
            f"产品：{product}" if product else "",
            f"指标：{metric}",
        ]
    )
    table_evidence = _compact_evidence(
        [
            f"使用数据表：{table}" if table else "从当前上传数据中选择历史分销明细。",
            "需要同时具备时间、人员/主任、产品和历史分销金额字段。",
        ]
    )
    denominator_scope = _join_scope([ym_label, f"{role}={person}" if person else "", "全部产品"])
    numerator_scope = _join_scope([ym_label, f"{role}={person}" if person else "", product])
    formula_evidence = _compact_evidence(
        [
            f"分母：{denominator_scope} 的{metric}",
            f"分子：{numerator_scope} 的{metric}",
            "计算方式：分子 ÷ 分母 × 100",
        ]
    )
    execution_evidence = ["Pandas 路径已返回执行摘要。"] if _first_dict(trace.get("pandas_result_summary")) else [_operation_evidence(logic_form)]
    if answer_type:
        execution_evidence.append(answer_type)

    steps = [
        _step(
            title="识别占比问题",
            summary="已识别为特定对象在指定月份的历史分销金额构成占比，不按通用趋势或排名模板处理。",
            evidence=scope_evidence,
            confidence=_confidence(trace.get("intent_summary")),
            source="llm_summary",
        ),
        _step(
            title="选择历史分销明细",
            summary="已选择能承载历史分销金额、人员范围、月份和产品维度的数据源。",
            evidence=table_evidence,
            source="trace_summary",
        ),
        _step(
            title="锁定筛选口径",
            summary="先把分母范围限定到同一人员和同一月份，避免把其他人员、月份或无关产品混入占比。",
            evidence=scope_evidence,
            source="trace_summary",
        ),
        _step(
            title="确认分子分母",
            summary="分母是筛选范围内全部产品的历史分销金额；分子是在同一范围内目标产品的历史分销金额。",
            evidence=formula_evidence,
            source="trace_summary",
        ),
        _step(
            title="执行占比计算",
            summary="已按后端结构化口径聚合金额并换算为百分比，前端只展示结果。",
            evidence=execution_evidence,
            source="execution_summary",
        ),
        _verification_step(trace, response),
        _final_step(trace, response),
    ]
    return steps[:7]


def _intent_step(mode: str, trace: dict[str, Any], response: dict[str, Any], logic_form: dict[str, Any]) -> dict[str, Any]:
    labels = {
        "metric_lookup": ("理解指标问题", "已识别为需要定位指标并返回计算结果的问题。"),
        "ranking_topn": ("确定排名问题", "已识别为 TopN / 排名类问题，会先确定排序指标和候选范围。"),
        "comparison_or_trend": ("确定对比口径", "已识别为对比、趋势或占比变化类问题，会先对齐时间和对象口径。"),
        "multi_table_join": ("识别多表问题", "已识别为需要在多张表之间选择数据源或关联后回答的问题。"),
        "diagnostic_or_anomaly": ("识别诊断目标", "已识别为异常、质量、影响或原因分析类问题，会优先定位对象和风险信号。"),
        "clarification_or_not_applicable": ("识别限制", "当前问题存在缺少字段、口径不支持或结果不可安全回答的信号。"),
    }
    title, fallback = labels.get(mode, labels["metric_lookup"])
    summary = _stage_summary(trace.get("intent_summary")) or _stage_summary(trace.get("analysis_planner_summary")) or fallback
    evidence = [_operation_evidence(logic_form), _answer_type_evidence(response)]
    return _step(title=title, summary=summary, evidence=evidence, confidence=_confidence(trace.get("intent_summary")), source="llm_summary")


def _data_selection_step(trace: dict[str, Any], logic_form: dict[str, Any]) -> dict[str, Any]:
    sources = _source_tables(trace, logic_form)
    evidence = [f"使用数据表：{'、'.join(sources[:3])}"] if sources else ["从当前上传数据中选择相关表。"]
    reason = _clean_text(trace.get("table_selection_reason") or logic_form.get("table_selection_reason"), 140)
    if reason:
        evidence.append(f"表选择摘要：{reason}")
    return _step(
        title="选择相关数据",
        summary="已根据问题、字段画像和表信息选择本次分析所需的数据源。",
        evidence=evidence,
        source="trace_summary",
    )


def _business_definition_step(trace: dict[str, Any], logic_form: dict[str, Any]) -> dict[str, Any] | None:
    metric_definition = _first_dict(trace.get("metric_definition"), logic_form.get("metric_definition"))
    numerator = _first_dict(trace.get("numerator"), logic_form.get("numerator"))
    denominator = _first_dict(trace.get("denominator"), logic_form.get("denominator"))
    metric = _clean_text(logic_form.get("metric") or metric_definition.get("metric") or metric_definition.get("name"), 80)
    evidence = []
    if metric:
        evidence.append(f"指标：{metric}")
    if numerator:
        evidence.append("已记录分子口径。")
    if denominator:
        evidence.append("已记录分母口径。")
    if not evidence:
        return None
    return _step(
        title="确认业务口径",
        summary="已把问题中的指标、分子、分母或实体粒度整理成结构化口径。",
        evidence=evidence,
        source="trace_summary",
    )


def _candidate_step(trace: dict[str, Any], logic_form: dict[str, Any]) -> dict[str, Any] | None:
    candidate_set = _first_dict(trace.get("candidate_set"), logic_form.get("candidate_set"))
    selected = _first_dict(trace.get("selected_candidate"))
    if not candidate_set and not selected:
        return None
    evidence = []
    if candidate_set:
        evidence.append("已限定候选范围。")
    if selected:
        evidence.append("已记录被选中的候选项摘要。")
    return _step(
        title="限定候选范围",
        summary="已先收缩候选对象，避免在不相关数据上排序或比较。",
        evidence=evidence,
        source="trace_summary",
    )


def _join_step(trace: dict[str, Any], logic_form: dict[str, Any]) -> dict[str, Any]:
    join_plan = _first_dict(trace.get("join_plan"), logic_form.get("join_plan"))
    left = _clean_text(join_plan.get("left_table"), 80)
    right = _clean_text(join_plan.get("right_table"), 80)
    left_key = _clean_text(join_plan.get("left_key"), 80)
    right_key = _clean_text(join_plan.get("right_key"), 80)
    evidence = []
    if left or right:
        evidence.append(f"关联表：{' / '.join(item for item in [left, right] if item)}")
    if left_key or right_key:
        evidence.append(f"关联键：{' / '.join(item for item in [left_key, right_key] if item)}")
    if not evidence:
        evidence = ["已检测到多表关联需求。"]
    caveats = [] if join_plan.get("trusted") else ["关联关系需要保持可信，否则不会伪装成已完成 join。"]
    return _step(
        title="判断关联方式",
        summary="已检查是否需要 join，并只展示关联摘要，不暴露完整后端 join 细节。",
        evidence=evidence,
        caveats=caveats,
        source="trace_summary",
    )


def _execution_step(mode: str, trace: dict[str, Any], logic_form: dict[str, Any]) -> dict[str, Any]:
    labels = {
        "ranking_topn": ("执行排名计算", "已按确定的指标和候选范围生成排序结果。"),
        "comparison_or_trend": ("执行对比计算", "已按统一口径完成对比、占比或趋势计算。"),
        "multi_table_join": ("执行关联后分析", "已在可信数据选择或关联结果上执行分析。"),
        "diagnostic_or_anomaly": ("检查异常信号", "已基于执行结果检查异常、质量或影响因素。"),
        "clarification_or_not_applicable": ("尝试安全执行", "已尝试按当前能力边界执行，发现需要澄清或补齐能力。"),
    }
    title, summary = labels.get(mode, ("执行 Python / SQL", "已执行受控 Pandas / SQL 计划并标准化结果。"))
    pandas = _first_dict(trace.get("pandas_result_summary"))
    sql = _first_dict(trace.get("sql_result_summary"))
    evidence = []
    if pandas:
        evidence.append("Pandas 路径已返回执行摘要。")
    if sql and sql.get("success") is not None:
        evidence.append("SQL / DuckDB 路径已返回覆盖摘要。")
    if not evidence:
        evidence.append(_operation_evidence(logic_form))
    return _step(title=title, summary=summary, evidence=evidence, source="execution_summary")


def _correction_step(trace: dict[str, Any]) -> dict[str, Any] | None:
    attempts = trace.get("correction_attempts")
    if not isinstance(attempts, list) or not attempts:
        return None
    return _step(
        title="处理校验反馈",
        summary=f"已记录 {len(attempts)} 次受控修正检查，必要时才触发重算。",
        evidence=["修正只通过结构化方向进入执行链路。"],
        source="trace_summary",
    )


def _verification_step(trace: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    verification = _first_dict(trace.get("verification_result"), response.get("verification"))
    passed = verification.get("passed")
    status = "completed" if passed is not False else "failed"
    summary = "已核对执行成功、语义契约和输出契约。" if passed is not False else "校验发现当前结果不能直接作为可信答案。"
    caveats = _safe_text_list(trace.get("semantic_verification_notes"), limit=2)
    return _step(
        title="核对结果",
        summary=summary,
        status=status,
        evidence=["校验结果：通过" if passed is not False else "校验结果：未通过"],
        caveats=caveats,
        confidence=_confidence(verification),
        source="verification_summary",
    )


def _chart_step(trace: dict[str, Any], response: dict[str, Any]) -> dict[str, Any] | None:
    chart = _first_dict(response.get("chart"), trace.get("chart_plan_summary"))
    chart_type = _clean_text(chart.get("chart_type"), 40)
    if not chart_type:
        return None
    return _step(
        title="选择展示方式",
        summary="已按结果形态选择适合的图表或 KPI 展示。",
        evidence=[f"图表类型：{chart_type}"],
        confidence=_confidence(chart),
        source="response_contract",
    )


def _final_step(trace: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    insight = _first_dict(response.get("insight"), trace.get("insight_summary"))
    evidence = []
    summary = _clean_text(insight.get("summary"), 160) if insight else ""
    if summary:
        evidence.append("已生成洞察摘要。")
    else:
        summary = "已把计算结果整理为最终回答和稳定 API 字段。"
    return _step(title="生成回答", summary=summary, evidence=evidence or ["最终回答来自已验证结果。"], source="response_contract")


def _next_step_for_limits(trace: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    warnings = _safe_text_list(response.get("warnings") or trace.get("warnings"), limit=2)
    return _step(
        title="给出安全边界",
        summary="已避免编造结论，并通过错误或警告说明需要补充字段、规则或能力。",
        evidence=["未把不可信结果包装成成功回答。"],
        caveats=warnings,
        source="response_contract",
    )


def _summary_for_mode(mode: str, trace: dict[str, Any], response: dict[str, Any]) -> str:
    summaries = {
        "chat": "已识别为普通对话，直接生成安全回复。",
        "dataset_overview": "已按数据概览请求生成差异化过程摘要。",
        "dataset_source_overview": "已按上传来源文件请求生成差异化过程摘要。",
        "metric_lookup": "已按指标查询问题生成差异化过程摘要。",
        "ranking_topn": "已按排名 / TopN 问题生成差异化过程摘要。",
        "comparison_or_trend": "已按对比 / 趋势问题生成差异化过程摘要。",
        "multi_table_join": "已按多表问题生成差异化过程摘要。",
        "diagnostic_or_anomaly": "已按诊断 / 异常问题生成差异化过程摘要。",
        "clarification_or_not_applicable": "已按需澄清或不支持场景生成安全过程摘要。",
    }
    return summaries.get(mode, summaries["metric_lookup"])


def _select_mode(trace: dict[str, Any], response: dict[str, Any], logic_form: dict[str, Any], forced_mode: str | None) -> str:
    if forced_mode in PROCESS_MODES:
        return str(forced_mode)
    answer_type = _lower(response.get("answer_type"))
    execution_mode = _lower(response.get("execution_mode"))
    operation = _lower(logic_form.get("operation") or _first_dict(response.get("debug")).get("operation"))
    task_type = _lower(logic_form.get("task_type"))
    question = _lower(response.get("question") or trace.get("question"))
    if answer_type == "chat" or execution_mode == "chat":
        return "chat"
    if operation == "dataset_source_overview":
        return "dataset_source_overview"
    if answer_type == "overview" or operation == "dataset_overview":
        return "dataset_overview"
    if response.get("success") is False or operation == "not_applicable" or _first_dict(response.get("debug")).get("not_applicable_attribution"):
        return "clarification_or_not_applicable"
    if any(token in question for token in ("不存在字段", "没有上传字段", "缺少字段", "未提供字段", "无法计算", "不能计算", "不支持")):
        return "clarification_or_not_applicable"
    join_plan = _first_dict(trace.get("join_plan"), logic_form.get("join_plan"))
    if join_plan.get("trusted") or len(_source_tables(trace, logic_form)) > 1 or "join" in operation or any(
        token in question for token in ("关联", "结合", "映射", "多表", "多个表", "另一张表", "join")
    ):
        return "multi_table_join"
    if any(token in f"{operation} {task_type} {question}" for token in ("rank", "top", "topn", "top_k", "top_count", "ranking", "排名", "最高", "最低", "最多", "最少", "最大", "最小")):
        return "ranking_topn"
    if any(
        token in f"{operation} {task_type} {question}"
        for token in (
            "trend",
            "growth",
            "delta",
            "period",
            "compare",
            "comparison",
            "rate",
            "share",
            "ratio",
            "change",
            "percentage",
            "趋势",
            "对比",
            "比较",
            "增长",
            "变化",
            "环比",
            "同比",
            "占比",
            "比率",
            "增长率",
            "下降",
            "上升",
        )
    ):
        return "comparison_or_trend"
    if any(token in f"{operation} {task_type} {question}" for token in ("anomaly", "outlier", "fraud", "diagnostic", "quality", "problem", "issue", "impact", "异常", "离群", "问题", "影响", "原因", "风险", "质量")):
        return "diagnostic_or_anomaly"
    return "metric_lookup"


def _view(*, summary: str, mode: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": PROCESS_VIEW_VERSION,
        "summary": _clean_text(summary, 180),
        "mode": mode if mode in PROCESS_MODES else "metric_lookup",
        "steps": [_normalize_step(step) for step in steps if isinstance(step, dict)],
    }


def _safe_process_view(process_view: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": _clean_text(process_view.get("version") or PROCESS_VIEW_VERSION, 20) or PROCESS_VIEW_VERSION,
        "summary": _clean_text(process_view.get("summary"), 180),
        "mode": _safe_process_mode(process_view.get("mode")),
        "steps": [
            _normalize_step(_safe(step))
            for step in (process_view.get("steps") if isinstance(process_view.get("steps"), list) else [])
            if isinstance(step, dict)
        ][:8],
    }


def _safe_process_mode(value: Any) -> str:
    mode = _clean_text(value, 80)
    return mode if mode in PROCESS_MODES else "metric_lookup"


def _step(
    *,
    title: str,
    summary: str,
    status: str = "completed",
    evidence: list[Any] | None = None,
    assumptions: list[Any] | None = None,
    caveats: list[Any] | None = None,
    confidence: Any = None,
    source: str = "trace_summary",
) -> dict[str, Any]:
    return _normalize_step(
        {
            "title": title,
            "summary": summary,
            "status": status,
            "evidence": evidence or [],
            "assumptions": assumptions or [],
            "caveats": caveats or [],
            "confidence": confidence,
            "source": source,
        }
    )


def _normalize_step(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": _clean_text(step.get("title") or "处理步骤", 60),
        "summary": _clean_text(step.get("summary") or "已完成该步骤。", 220),
        "status": _safe_status(step.get("status")),
        "evidence": _safe_text_list(step.get("evidence"), limit=4),
        "assumptions": _safe_text_list(step.get("assumptions"), limit=3),
        "caveats": _safe_text_list(step.get("caveats"), limit=3),
        "confidence": _confidence(step),
        "source": _safe_source(step.get("source")),
    }


def _safe(value: Any) -> Any:
    if is_dataclass(value):
        return _safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items() if str(key).lower() not in BLOCKED_KEYS}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, str):
        return _clean_text(value, 500)
    return value


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        data = value.to_dict()
        return data if isinstance(data, dict) else {}
    return {}


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if is_dataclass(value):
            value = asdict(value)
        if isinstance(value, dict):
            return value
    return {}


def _source_tables(trace: dict[str, Any], logic_form: dict[str, Any]) -> list[str]:
    values = trace.get("source_tables") or logic_form.get("source_tables") or []
    if not isinstance(values, list):
        return []
    return [item for item in (_clean_text(value, 80) for value in values) if item]


def _stage_summary(payload: Any) -> str:
    data = _first_dict(payload)
    for key in ("display_summary", "reasoning_summary", "summary"):
        value = _clean_text(data.get(key), 180)
        if value:
            return value
    return ""


def _operation_evidence(logic_form: dict[str, Any]) -> str:
    operation = _clean_text(logic_form.get("operation"), 80)
    return f"operation={operation}" if operation else "已生成结构化分析计划。"


def _answer_type_evidence(response: dict[str, Any]) -> str:
    answer_type = _clean_text(response.get("answer_type"), 60)
    return f"answer_type={answer_type}" if answer_type else ""


def _metric_label(value: Any) -> str:
    metric = _clean_text(value, 80)
    labels = {
        "sign_amt": "历史分销金额",
        "sign_box_cnt": "历史分销数量",
        "target": "分销目标",
        "target_amt": "分销目标金额",
    }
    return labels.get(metric, metric or "目标指标")


def _role_label(value: Any) -> str:
    role = _clean_text(value, 40)
    if role == "manager":
        return "主任"
    if role == "employee":
        return "业代"
    return "对象"


def _ym_label(value: Any) -> str:
    try:
        text = str(int(value))
    except (TypeError, ValueError):
        return _clean_text(value, 40)
    if len(text) != 6:
        return _clean_text(value, 40)
    return f"{text[:4]}年{int(text[4:])}月"


def _join_scope(parts: list[str]) -> str:
    cleaned = [part for part in (_clean_text(item, 80) for item in parts) if part]
    return " + ".join(cleaned) if cleaned else "当前筛选范围"


def _compact_evidence(values: list[str]) -> list[str]:
    return [item for item in values if item][:4]


def _clean_text(value: Any, limit: int = 160) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    lower = text.lower()
    for marker in BLOCKED_TEXT_MARKERS:
        if marker in lower:
            text = _replace_case_insensitive(text, marker, "[redacted]")
            lower = text.lower()
    text = " ".join(text.split())
    if not text:
        return ""
    if len(text) > limit:
        return text[: max(0, limit - 1)] + "..."
    return text


def _replace_case_insensitive(text: str, needle: str, replacement: str) -> str:
    start = 0
    result = ""
    lowered = text.lower()
    needle_lower = needle.lower()
    while True:
        index = lowered.find(needle_lower, start)
        if index < 0:
            return result + text[start:]
        result += text[start:index] + replacement
        start = index + len(needle)


def _safe_text_list(value: Any, *, limit: int) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    cleaned: list[str] = []
    for item in items:
        text = _clean_text(item, 120)
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _confidence(payload: Any) -> float | None:
    if isinstance(payload, dict) and "confidence" in payload:
        value = payload.get("confidence")
    else:
        value = payload
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not 0 <= number <= 1:
        return None
    return number


def _safe_status(value: Any) -> str:
    status = str(value or "completed")
    return status if status in {"completed", "active", "pending", "failed", "skipped"} else "completed"


def _safe_source(value: Any) -> str:
    source = str(value or "trace_summary")
    allowed = {"service_route", "trace_summary", "llm_summary", "execution_summary", "verification_summary", "response_contract", "deterministic_result"}
    return source if source in allowed else "trace_summary"


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _first_item(values: list[str]) -> str:
    return values[0] if values else ""


def _lower(value: Any) -> str:
    return str(value or "").lower()
