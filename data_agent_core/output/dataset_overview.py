"""Dataset overview response builder for broad workbench questions."""

from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from typing import Any

import pandas as pd

from data_agent_core.contracts.response_contracts import InsightResult
from data_agent_core.output.execution_artifacts import build_overview_execution_artifacts
from data_agent_core.output.process_narrative import build_dataset_overview_process_view


def build_dataset_overview_response(
    *,
    run_id: str,
    dataset_id: str,
    question: str,
    tables: dict[str, pd.DataFrame],
    profile: Any = None,
    agent_mode: str = "multi_agent",
) -> dict[str, Any]:
    """Build a full-table, user-facing dataset overview response."""

    profile_payload = _profile_payload(profile)
    if _wants_multi_table_overview(question, tables):
        return _build_multi_table_overview_response(
            run_id=run_id,
            dataset_id=dataset_id,
            question=question,
            tables=tables,
            profile_payload=profile_payload,
            agent_mode=agent_mode,
        )

    table_name, df = _primary_table(tables)
    table_profile = _table_profile(profile_payload, table_name)
    source_file = table_profile.get("source_file") or profile_payload.get("file_name") or table_name
    sheet = table_profile.get("sheet")
    row_count = int(len(df))
    columns = [str(column) for column in df.columns]
    metric_column = _preferred_metric_column(df, question)
    dimension_column = _preferred_dimension_column(columns, metric_column)
    period_column = _preferred_period_column(columns)

    metric_summary = _metric_summary(df, metric_column, dimension_column, period_column) if metric_column else None
    field_meanings = _field_meanings(df)
    categorical_distributions = _categorical_distributions(df, metric_column)
    boolean_rates = _boolean_rates(df)
    answerable_questions = _answerable_questions(metric_column, dimension_column, period_column, categorical_distributions, boolean_rates)
    missing_boundaries = _missing_boundaries(columns)
    likely_meaning = _likely_table_meaning(table_name, columns, field_meanings)
    overview_report = {
        "report_type": "overview_report",
        "table": table_name,
        "source_file": source_file,
        "sheet": sheet,
        "row_count": row_count,
        "column_count": len(columns),
        "likely_meaning": likely_meaning,
        "metric_column": metric_column,
        "dimension_column": dimension_column,
        "period_column": period_column,
        "field_meanings": field_meanings,
        "metric_summary": metric_summary or {},
        "categorical_distributions": categorical_distributions,
        "boolean_rates": boolean_rates,
        "answerable_questions": answerable_questions,
        "missing_boundaries": missing_boundaries,
    }
    result_rows = _overview_result_rows(overview_report)
    answer = _overview_shape_answer(overview_report) if _wants_shape_summary(question) else _overview_answer(overview_report)
    insight = _overview_insight(overview_report)
    execution_artifacts = build_overview_execution_artifacts(
        table_name=table_name,
        metric_column=metric_column,
        dimension_column=dimension_column,
        row_count=row_count,
        column_count=len(columns),
    )

    return {
        "response_version": "v1",
        "success": True,
        "run_id": run_id,
        "dataset_id": dataset_id,
        "question": question,
        "answer_type": "overview",
        "execution_mode": "overview",
        "answer": answer,
        "logic_form": {
            "task_type": "dataset_overview",
            "operation": "dataset_overview",
            "parameters": {
                "table": table_name,
                "metric": metric_column,
                "dimension": dimension_column,
                "period": period_column,
            },
            "source_tables": [table_name],
            "output_format": {"answer_type": "overview"},
        },
        "result": {
            "columns": ["指标", "数值"],
            "rows": result_rows,
            "value": {
                "table": table_name,
                "row_count": row_count,
                "column_count": len(columns),
                "metric_column": metric_column,
                "dimension_column": dimension_column,
                "overview_report": overview_report,
            },
        },
        "overview_report": overview_report,
        "verification": {
            "passed": True,
            "confidence": 1.0,
            "notes": ["Dataset overview was computed from the uploaded table, not from a row-count shortcut."],
        },
        "insight": insight.__dict__,
        "chart": None,
        "quality_report": None,
        "execution_artifacts": execution_artifacts,
        "reasoning_trace_view": [
            {
                "step_id": "intent",
                "name": "理解问题",
                "status": "completed",
                "summary": "这是宽泛的数据概览请求，我会先给出表规模、关键数值字段和可下钻方向。",
            },
            {
                "step_id": "select_table",
                "name": "选择数据",
                "status": "completed",
                "summary": f"使用主表“{table_name}”，共 {row_count} 行、{len(columns)} 列。",
            },
            {
                "step_id": "summarize",
                "name": "生成概览",
                "status": "completed",
                "summary": "已整理为结构化概览报告，避免把原始明细行或单个行数当作回答。",
            },
        ],
        "process_view_v2": build_dataset_overview_process_view(
            table_name=table_name,
            row_count=row_count,
            column_count=len(columns),
            metric_column=metric_column,
            dimension_column=dimension_column,
        ),
        "warnings": [],
        "errors": [],
        "debug": {
            "agent_mode": agent_mode,
            "message_intent": "dataset_overview",
            "operation": "dataset_overview",
            "source_tables": [table_name],
            "user_experience_shaping": {
                "applied": True,
                "reason": "generic_dataset_overview_prevents_row_count_or_raw_detail_answer",
                "source_row_count": row_count,
                "source_column_count": len(columns),
                "metric_column": metric_column,
                "dimension_column": dimension_column,
            },
        },
    }


def _primary_table(tables: dict[str, pd.DataFrame]) -> tuple[str, pd.DataFrame]:
    if not tables:
        raise ValueError("No parsed tables are available.")
    return max(tables.items(), key=lambda item: (len(item[1]), len(item[1].columns)))


def _wants_multi_table_overview(question: str, tables: dict[str, pd.DataFrame]) -> bool:
    if len(tables) <= 1:
        return False
    if _wants_shape_summary(question):
        return True
    compact = str(question or "").lower().replace(" ", "")
    multi_signals = (
        "这几个表",
        "这几张表",
        "这些表",
        "几个表",
        "几张表",
        "多张表",
        "所有表",
        "全部表",
        "各个表",
        "几个文件",
        "这些文件",
        "每个文件",
        "各个文件",
        "每张表",
        "各张表",
        "这个数据主要讲什么",
        "数据主要讲什么",
        "这个数据讲什么",
        "这个数据集",
        "这份数据",
        "表单含义",
        "有什么字段",
        "有哪些字段",
    )
    single_signals = ("这个表", "这张表", "当前表", "这个文件")
    return any(signal in compact for signal in multi_signals) and not any(signal in compact for signal in single_signals)


def _wants_shape_summary(question: str) -> bool:
    compact = str(question or "").lower().replace(" ", "")
    shape_signals = (
        "多少行、多少列",
        "多少行，多少列",
        "多少行多少列",
        "行数、列数",
        "行数，列数",
        "行数列数",
        "行列规模",
        "表规模",
        "文件规模",
    )
    return any(signal in compact for signal in shape_signals)


def _build_multi_table_overview_response(
    *,
    run_id: str,
    dataset_id: str,
    question: str,
    tables: dict[str, pd.DataFrame],
    profile_payload: dict[str, Any],
    agent_mode: str,
) -> dict[str, Any]:
    table_summaries = []
    total_rows = 0
    total_columns = 0
    for table_name, df in tables.items():
        table_profile = _table_profile(profile_payload, table_name)
        source_file = table_profile.get("source_file") or profile_payload.get("file_name") or table_name
        summary = _table_overview_summary(
            table_name=table_name,
            df=df,
            source_file=source_file,
            sheet=table_profile.get("sheet"),
            question=question,
        )
        table_summaries.append(summary)
        total_rows += summary["row_count"]
        total_columns += summary["column_count"]

    table_summaries.sort(key=lambda item: (-int(item["row_count"]), -int(item["column_count"]), str(item["table"])))
    overview_report = {
        "report_type": "overview_report",
        "overview_scope": "multi_table",
        "table_count": len(table_summaries),
        "total_row_count": total_rows,
        "total_column_count": total_columns,
        "tables_summary": table_summaries,
        "missing_boundaries": [
            "多表关系需要结合业务主键、时间粒度和说明文件确认，不能仅凭字段同名自动 join。",
            "字段含义来自字段名、类型和样例的安全推断，正式口径仍应以业务说明为准。",
        ],
    }
    result_rows = _multi_table_result_rows(overview_report)
    answer = _multi_table_shape_answer(overview_report) if _wants_shape_summary(question) else _multi_table_answer(overview_report)
    insight = _multi_table_insight(overview_report)
    execution_artifacts = _multi_table_execution_artifacts(overview_report)

    return {
        "response_version": "v1",
        "success": True,
        "run_id": run_id,
        "dataset_id": dataset_id,
        "question": question,
        "answer_type": "overview",
        "execution_mode": "overview",
        "answer": answer,
        "logic_form": {
            "task_type": "dataset_overview",
            "operation": "multi_table_dataset_overview",
            "parameters": {
                "table_count": len(table_summaries),
                "tables": [item["table"] for item in table_summaries],
            },
            "source_tables": [item["table"] for item in table_summaries],
            "output_format": {"answer_type": "overview"},
        },
        "result": {
            "columns": ["表名", "来源", "行数", "列数", "可能含义", "关键字段"],
            "rows": result_rows,
            "value": {
                "table_count": len(table_summaries),
                "total_row_count": total_rows,
                "total_column_count": total_columns,
                "overview_report": overview_report,
            },
        },
        "overview_report": overview_report,
        "verification": {
            "passed": True,
            "confidence": 1.0,
            "notes": ["Multi-table overview was computed from uploaded table profiles, not from raw detail rows."],
        },
        "insight": insight.__dict__,
        "chart": None,
        "quality_report": None,
        "execution_artifacts": execution_artifacts,
        "reasoning_trace_view": [
            {
                "step_id": "intent",
                "name": "理解问题",
                "status": "completed",
                "summary": "这是多表字段和含义概览请求，我会汇总每张表的用途与关键字段。",
            },
            {
                "step_id": "scan_tables",
                "name": "扫描多表",
                "status": "completed",
                "summary": f"识别到 {len(table_summaries)} 张可读表，共 {total_rows} 行、{total_columns} 个字段。",
            },
            {
                "step_id": "summarize",
                "name": "生成概览",
                "status": "completed",
                "summary": "已整理为多表概览清单，避免展示原始明细行。",
            },
        ],
        "process_view_v2": build_dataset_overview_process_view(
            table_name="多表数据集",
            row_count=total_rows,
            column_count=total_columns,
            table_count=len(table_summaries),
            is_multi_table=True,
        ),
        "warnings": [],
        "errors": [],
        "debug": {
            "agent_mode": agent_mode,
            "message_intent": "dataset_overview",
            "operation": "multi_table_dataset_overview",
            "source_tables": [item["table"] for item in table_summaries],
            "user_experience_shaping": {
                "applied": True,
                "reason": "multi_table_overview_prevents_raw_detail_answer",
                "source_table_count": len(table_summaries),
                "source_row_count": total_rows,
                "source_column_count": total_columns,
            },
        },
    }


def _profile_payload(profile: Any) -> dict[str, Any]:
    if profile is None:
        return {}
    if is_dataclass(profile):
        return asdict(profile)
    if isinstance(profile, dict):
        return profile
    return {}


def _table_profile(profile: dict[str, Any], table_name: str) -> dict[str, Any]:
    for table in profile.get("tables") or []:
        if not isinstance(table, dict):
            continue
        if str(table.get("table_name") or "") == table_name:
            return table
    return {}


def _table_overview_summary(
    *,
    table_name: str,
    df: pd.DataFrame,
    source_file: str,
    sheet: str | None,
    question: str,
) -> dict[str, Any]:
    columns = [str(column) for column in df.columns]
    metric_column = _preferred_metric_column(df, question)
    dimension_column = _preferred_dimension_column(columns, metric_column)
    period_column = _preferred_period_column(columns)
    field_meanings = _field_meanings(df)
    key_fields = _key_fields(columns, metric_column, dimension_column, period_column)
    return {
        "table": table_name,
        "source_file": source_file,
        "sheet": sheet,
        "row_count": int(len(df)),
        "column_count": len(columns),
        "table_type": _table_type_label({"field_meanings": field_meanings}),
        "likely_meaning": _likely_table_meaning(table_name, columns, field_meanings),
        "metric_column": metric_column,
        "dimension_column": dimension_column,
        "period_column": period_column,
        "key_fields": key_fields,
        "field_meanings": field_meanings[:12],
    }


def _key_fields(
    columns: list[str],
    metric_column: str | None,
    dimension_column: str | None,
    period_column: str | None,
) -> list[str]:
    preferred = [period_column, dimension_column, metric_column]
    preferred.extend(
        column
        for column in columns
        if column not in preferred
        and (
            any(token in column.lower() for token in ("id", "code", "name", "date", "month", "amount", "sales", "revenue"))
            or any(token in column for token in ("编号", "编码", "名称", "日期", "月份", "金额", "销售", "收入", "客户", "产品", "区域"))
        )
    )
    result: list[str] = []
    for column in preferred:
        if column and column in columns and column not in result:
            result.append(column)
        if len(result) >= 8:
            break
    return result or columns[:8]


def _likely_table_meaning(table_name: str, columns: list[str], field_meanings: list[dict[str, str]]) -> str:
    haystack = " ".join([table_name, *columns]).lower()
    if any(token in haystack for token in ("taxi", "trip", "fare", "pickup", "dropoff", "行程", "车费")):
        return "出租车或出行行程明细，适合看行程量、金额、里程、时间和区域差异。"
    if any(token in haystack for token in ("order", "ord", "订单", "交易", "invoice")):
        return "订单或交易明细，适合看金额、数量、客户/商品和时间趋势。"
    if any(token in haystack for token in ("customer", "cust", "客户", "终端")):
        return "客户或终端维表，适合补充客户属性、区域、渠道或层级。"
    if any(token in haystack for token in ("sku", "product", "item", "商品", "产品")):
        return "商品或 SKU 相关表，适合解释产品、品类和规格。"
    if any(token in haystack for token in ("target", "goal", "目标")):
        return "目标或计划表，适合与实际完成情况做对比。"
    if any(token in haystack for token in ("visit", "route", "拜访", "路线")):
        return "拜访或路线过程表，适合分析覆盖、频次和执行。"
    if any(token in haystack for token in ("actv", "activity", "dsp", "活动", "陈列")):
        return "活动执行或陈列明细，适合分析执行状态、费用和活动效果。"
    if any("金额或收入" in item.get("meaning", "") for item in field_meanings):
        return "业务明细表，包含可汇总的金额或收入指标。"
    return "结构化数据表，适合先确认主键、时间字段、维度字段和可汇总指标。"


def _multi_table_shape_answer(report: dict[str, Any]) -> str:
    tables = report.get("tables_summary") or []
    shown = tables[:8]
    lines = [
        f"这组数据共有 {report['table_count']} 张表/文件，总计 {report['total_row_count']:,} 行、{report['total_column_count']} 个字段。",
        "每张表的行列规模如下：",
    ]
    for item in shown:
        source = _join_non_empty([item.get("source_file"), item.get("sheet")], " / ")
        label = str(item.get("table") or source or "未命名表")
        suffix = f"（来源：{source}）" if source and source != label else ""
        lines.append(f"- {label}：{int(item.get('row_count') or 0):,} 行、{int(item.get('column_count') or 0)} 列{suffix}")
    if len(tables) > len(shown):
        lines.append(f"还有 {len(tables) - len(shown)} 张表没有在主回答里展开，完整清单在结果表里。")
    lines.append("我没有展示原始明细行；如果下一步要看字段含义、缺失或文件差异，可以直接继续问。")
    return "\n".join(lines)


def _multi_table_answer(report: dict[str, Any]) -> str:
    tables = report.get("tables_summary") or []
    top_tables = tables[:5]
    themes = _short_join([str(item.get("likely_meaning") or "").split("，")[0] for item in top_tables], limit=4)
    table_examples = _short_join([f"{item['table']}（{item['row_count']:,} 行）" for item in top_tables], limit=5)
    relationship = _multi_table_relationship_text(tables)
    suggestions = _multi_table_suggestion_text(tables)
    lines = [
        f"已读取这组数据：它不是一张单表，而是 {report['table_count']} 张表组成的数据集，共 {report['total_row_count']:,} 行、{report['total_column_count']} 个字段。",
        f"初步看，数据主题大致覆盖 {themes or '业务事实表、维表和过程表'}；这是基于字段名、表名和类型的推测，正式口径还要看业务说明。",
        f"主要区别在表的粒度和用途：例如 {table_examples or '各表'}。{relationship}",
        f"建议分析方向：{suggestions}",
        "质量问题也需要单独看，尤其是缺失、重复和异常值；完整表清单和关键字段我放在结果表里，不在主回答里展开明细。",
    ]
    return "\n".join(lines)


def _multi_table_relationship_text(tables: list[dict[str, Any]]) -> str:
    if len(tables) >= 2:
        column_counts = {int(item.get("column_count") or 0) for item in tables}
        key_sets = {tuple(item.get("key_fields") or []) for item in tables}
        if len(column_counts) == 1 and len(key_sets) <= 2:
            return "这些表结构很接近，更像同一口径数据按时间、来源或批次拆开的文件，优先做对比而不是直接 join。"
    haystack = _tables_haystack(tables)
    if any(token in haystack for token in ("target", "visit", "route", "actv", "dsp", "目标", "拜访", "活动", "陈列")):
        return "这些表更像事实明细、目标计划、客户/SKU 维表和执行过程表的组合。"
    if any(token in haystack for token in ("order", "payment", "customer", "product", "seller", "订单", "支付", "客户", "商品")):
        return "这些表更像订单、支付、客户、商品或卖家等主题表，需要先确定订单或客户主键再关联。"
    return "需要先确认哪张是事实表、哪些是维表或补充说明，再决定对比或 join。"


def _multi_table_suggestion_text(tables: list[dict[str, Any]]) -> str:
    haystack = _tables_haystack(tables)
    if any(token in haystack for token in ("taxi", "trip", "fare", "pickup", "dropoff", "行程", "车费")):
        return "先看行程量、fare/total amount、trip distance 和 pickup 时间趋势；如果是两期文件，再做同口径同比或差异对比。"
    if any(token in haystack for token in ("target", "visit", "route", "actv", "dsp", "目标", "拜访", "活动", "陈列")):
        return "先选目标完成、订单金额、活动执行或拜访覆盖中的一个主问题；跨表 join 前确认主键、月份/日期粒度和一对多关系。"
    if any(token in haystack for token in ("order", "payment", "customer", "product", "seller", "订单", "支付", "客户", "商品")):
        return "先看订单量、支付金额、客户区域、商品品类和卖家表现；跨表分析前确认 order/customer/product/seller 的关联键。"
    return "先选一张事实表和一个核心指标，再决定是做分组对比、时间趋势、质量检查还是多表关联。"


def _tables_haystack(tables: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in tables:
        parts.append(str(item.get("table") or ""))
        parts.append(str(item.get("likely_meaning") or ""))
        parts.extend(str(field) for field in (item.get("key_fields") or []))
    return " ".join(parts).lower()


def _short_join(values: list[str], *, limit: int = 4) -> str:
    cleaned: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return "、".join(cleaned)


def _multi_table_result_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in (report.get("tables_summary") or [])[:30]:
        rows.append(
            {
                "表名": item.get("table"),
                "来源": _join_non_empty([item.get("source_file"), item.get("sheet")], " / "),
                "行数": item.get("row_count"),
                "列数": item.get("column_count"),
                "可能含义": item.get("likely_meaning"),
                "关键字段": "、".join(item.get("key_fields") or []),
            }
        )
    return rows


def _multi_table_insight(report: dict[str, Any]) -> InsightResult:
    tables = report.get("tables_summary") or []
    table_names = "、".join(str(item.get("table")) for item in tables[:5])
    suggestions = [
        f"观察：这组数据覆盖 {len(tables)} 张表；依据：上传表画像；建议：先从 {table_names or '主业务表'} 中选定事实表，再决定是否关联维表。",
        "观察：表之间可能存在订单、客户、产品、目标或活动执行链路；依据：表名和关键字段推断；建议：做 join 前先确认主键、月份/日期粒度和一对多关系。",
        "观察：当前问题是概览/字段理解，不适合展示明细行；依据：用户问法和多表规模；建议：后续用具体指标问题触发聚合、排序或趋势分析。",
    ]
    return InsightResult(
        summary=f"已生成多表 overview：{report['table_count']} 张表，重点是表含义、关键字段和后续分析入口。",
        business_suggestions=suggestions,
        suggestions=suggestions,
        caveats=list(report.get("missing_boundaries") or []),
        evidence_rows=_multi_table_result_rows(report)[:5],
        confidence=0.84,
    )


def _multi_table_execution_artifacts(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _multi_table_result_rows(report)
    code = "\n".join(
        [
            "overview = []",
            "for table_name, df in tables.items():",
            "    overview.append({",
            "        'table': table_name,",
            "        'rows': len(df),",
            "        'columns': len(df.columns),",
            "        'key_fields': list(df.columns)[:8],",
            "    })",
            "overview = sorted(overview, key=lambda item: (-item['rows'], -item['columns']))",
        ]
    )
    return [
        {
            "artifact_id": "multi_table_overview_python",
            "language": "python",
            "title": "多表概览代码",
            "purpose": "展示如何从上传表生成多表概览清单，不展示原始明细。",
            "code": code,
            "output_summary": f"返回 {len(rows)} 张表的表名、行列规模、可能含义和关键字段。",
        }
    ]


def _overview_answer(report: dict[str, Any]) -> str:
    metric = report.get("metric_column")
    metric_summary = report.get("metric_summary") or {}
    dimension = report.get("dimension_column")
    period = report.get("period_column")
    field_names = [str(item.get("field")) for item in (report.get("field_meanings") or [])[:8]]
    key_fields = _short_join([item for item in [period, dimension, metric, *field_names] if item], limit=8)
    suggestions = report.get("answerable_questions") or []
    trend_text = f"时间字段是 {period}，可以继续做趋势、环比或同比；同比是否成立还要看是否覆盖可比年份。" if period else "暂未识别稳定时间字段，趋势、环比或同比需要先补充或指定日期字段。"
    metric_total = metric_summary.get("total")
    if metric and metric_total:
        metric_text = f"可作为核心指标优先尝试的是 {metric}（{metric}合计：{metric_total}）"
    elif metric:
        metric_text = f"可作为核心指标优先尝试的是 {metric}"
    else:
        metric_text = "暂未识别特别稳定的核心数值指标"
    dimension_text = f"可作为分组维度的是 {dimension}" if dimension else "分组维度需要结合业务字段再确认"
    distributions = report.get("categorical_distributions") or []
    lines = [
        f"已读取这个数据（{report.get('table') or '当前表'}）：{report['row_count']:,} 行、{report['column_count']} 列。",
        f"这个表更像是{_table_type_label(report)}，主要讲的是{report.get('likely_meaning') or '一组结构化业务记录'}",
        f"字段含义是根据字段名、类型和基础分布做的推测；关键字段包括 {key_fields or '待结合业务说明确认'}。",
        f"分析上，{metric_text}，{dimension_text}。{trend_text}",
    ]
    if distributions:
        lines.append(f"从基础分布看，{distributions[0]['field']} 是一个值得优先下钻的维度。")
    if suggestions:
        suggestion_text = "；".join(_trim_sentence_punctuation(str(item)) for item in suggestions[:3] if str(item).strip())
        lines.append(f"建议分析方向：{suggestion_text}。")
    lines.append("质量问题不能只回答“正常/不正常”：还需要看缺失、重复、负值、极端值和业务口径；完整字段画像和分布明细在结果表里。")
    return "\n".join(lines)


def _trim_sentence_punctuation(value: str) -> str:
    return str(value or "").strip().rstrip("。；;.")


def _overview_shape_answer(report: dict[str, Any]) -> str:
    source = _join_non_empty([report.get("source_file"), report.get("sheet")], " / ")
    label = str(report.get("table") or source or "当前表")
    lines = [
        f"{label} 是 {report['row_count']:,} 行、{report['column_count']} 列。",
    ]
    if source and source != label:
        lines.append(f"来源文件是 {source}。")
    metric = report.get("metric_column")
    dimension = report.get("dimension_column")
    period = report.get("period_column")
    quick_bits = [value for value in (period, dimension, metric) if value]
    if quick_bits:
        lines.append("可优先关注的字段包括 " + "、".join(str(item) for item in quick_bits[:4]) + "。")
    lines.append("我没有展开原始明细行；字段含义、缺失和分布明细放在结果表里，主回答只保留行列结论。")
    lines.append("下一步可以继续问字段含义、缺失情况或适合做哪些分析。")
    return "\n".join(lines)


def _overview_result_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        {"指标": "数据表", "数值": _join_non_empty([report.get("table"), report.get("source_file"), report.get("sheet")], " / ")},
        {"指标": "行列规模", "数值": f"{report['row_count']:,} 行，{report['column_count']} 列"},
    ]
    metric_summary = report.get("metric_summary") or {}
    for key, label in (
        ("total", "合计"),
        ("average", "平均"),
        ("median", "中位数"),
        ("min", "最小"),
        ("max", "最大"),
        ("top_group", "最高分组"),
    ):
        value = metric_summary.get(key)
        if value:
            rows.append({"指标": f"{report.get('metric_column')} {label}", "数值": value})
    for field in (report.get("field_meanings") or [])[:12]:
        rows.append({"指标": f"字段：{field['field']}", "数值": field["meaning"]})
    for dist in (report.get("categorical_distributions") or [])[:3]:
        text = _distribution_summary_text(dist)
        rows.append({"指标": f"分布：{dist['field']}", "数值": text})
    for rate in (report.get("boolean_rates") or [])[:4]:
        rows.append({"指标": f"状态：{rate['field']}", "数值": f"true {rate['true_count']:,} 条，占 {rate['true_rate']}"})
    for question in (report.get("answerable_questions") or [])[:5]:
        rows.append({"指标": "可继续提问", "数值": question})
    return rows


def _overview_insight(report: dict[str, Any]) -> InsightResult:
    metric = report.get("metric_column") or "关键指标"
    summary = f"这份数据已整理为 overview report：{report['row_count']:,} 行、{report['column_count']} 列。"
    suggestions = []
    distributions = report.get("categorical_distributions") or []
    if distributions and distributions[0].get("top_values"):
        top = distributions[0]["top_values"][0]
        suggestions.append(
            f"观察：{distributions[0]['field']} 中 {top['value']} 记录最多（{top['count']:,} 条）；依据：字段分布统计；建议：优先按该维度下钻金额、风险或转化。"
        )
    metric_summary = report.get("metric_summary") or {}
    if metric_summary.get("max_description"):
        suggestions.append(
            f"观察：{metric} 的最高记录为 {metric_summary['max_description']}；依据：数值字段最大值；建议：复核是否为真实业务高点或需要拆分来源。"
        )
    for rate in (report.get("boolean_rates") or [])[:2]:
        suggestions.append(
            f"观察：{rate['field']} 的 true 占比为 {rate['true_rate']}；依据：布尔字段计数；建议：结合商户、渠道或国家维度查看驱动因素。"
        )
    if not suggestions:
        suggestions.append(
            "观察：当前概览未发现单一突出风险信号；依据：字段画像和基础分布；建议：指定时间、维度和指标后继续做趋势或对比。"
        )
    return InsightResult(
        summary=summary,
        business_suggestions=suggestions,
        suggestions=suggestions,
        caveats=list(report.get("missing_boundaries") or []),
        evidence_rows=(report.get("categorical_distributions") or [])[:3],
        confidence=0.86,
    )


def _field_meanings(df: pd.DataFrame) -> list[dict[str, str]]:
    meanings = []
    for column in [str(item) for item in df.columns]:
        meanings.append({"field": column, "meaning": _field_meaning(column, df[column])})
    return meanings


def _field_meaning(column: str, series: pd.Series) -> str:
    lowered = column.lower()
    if any(token in lowered for token in ("date", "datetime", "time", "month", "week", "year", "日期", "时间", "月份", "年份", "周")):
        return "时间字段，可用于筛选或趋势分析；单独年份/小时不应作为金额指标。"
    if any(token in lowered for token in ("psp_reference", "reference", "invoice", "stockcode", "code", "id", "流水", "交易编号", "订单号", "编号", "编码")):
        return "编号或代码字段，通常用于追踪、关联或识别明细，不适合作为指标求和。"
    if "merchant" in lowered or "商户" in column:
        return "商户或业务主体名称，可用于分组比较。"
    if "scheme" in lowered or "卡组织" in column:
        return "卡组织或支付网络，可用于支付渠道分布分析。"
    if any(token in lowered for token in ("amount", "sales", "revenue", "gmv", "arr", "price", "unitprice")) or any(token in column for token in ("金额", "销售额", "收入", "毛利", "利润", "价格", "单价")):
        return "金额或收入类数值指标，适合汇总、平均、排名和趋势分析。"
    if any(token in lowered for token in ("quantity", "qty")) or any(token in column for token in ("数量", "件数", "次数")):
        return "数量类数值指标，适合汇总、排名、异常检查和趋势分析。"
    if any(token in lowered for token in ("country", "国家", "城市", "区域", "region", "city")):
        return "地理或区域维度，可用于分布和对比。"
    if series.dropna().isin([True, False, "true", "false", "True", "False", 0, 1]).mean() >= 0.8:
        return "布尔状态字段，可统计 true/false 占比和风险状态。"
    if _numeric_ratio(series) >= 0.75:
        return "数值字段；需要结合业务名判断是指标、编号还是时间桶。"
    return "分类或文本字段，可用于分组、筛选或明细识别。"


def _categorical_distributions(df: pd.DataFrame, metric_column: str | None) -> list[dict[str, Any]]:
    distributions: list[dict[str, Any]] = []
    for column in [str(item) for item in df.columns]:
        if column == metric_column or _looks_like_identifier_or_score(column) or _numeric_ratio(df[column]) >= 0.75:
            continue
        series = df[column].dropna().astype(str)
        unique = series.nunique()
        if series.empty or unique <= 1 or unique > min(50, max(12, len(series) // 2)):
            continue
        counts = series.value_counts().head(8)
        distributions.append(
            {
                "field": column,
                "unique_count": int(unique),
                "top_values": [{"value": str(index), "count": int(value)} for index, value in counts.items()],
            }
        )
    preferred = ("merchant", "商户", "scheme", "卡组织", "country", "国家", "city", "城市", "region", "区域", "channel", "渠道", "product", "产品")
    distributions.sort(key=lambda item: (0 if any(token in item["field"].lower() for token in preferred) else 1, -item["unique_count"]))
    return distributions[:5]


def _boolean_rates(df: pd.DataFrame) -> list[dict[str, Any]]:
    rates: list[dict[str, Any]] = []
    for column in [str(item) for item in df.columns]:
        series = df[column].dropna()
        if series.empty:
            continue
        normalized = series.map(lambda value: str(value).strip().lower())
        if not normalized.isin(["true", "false", "1", "0", "yes", "no"]).mean() >= 0.9:
            continue
        true_count = int(normalized.isin(["true", "1", "yes"]).sum())
        total = int(len(normalized))
        rates.append({"field": column, "true_count": true_count, "total": total, "true_rate": _format_percent(true_count / total * 100 if total else 0)})
    return rates


def _answerable_questions(
    metric_column: str | None,
    dimension_column: str | None,
    period_column: str | None,
    distributions: list[dict[str, Any]],
    rates: list[dict[str, Any]],
) -> list[str]:
    metric = metric_column or "关键指标"
    dimension = dimension_column or ((distributions[0] or {}).get("field") if distributions else "主要维度")
    questions = [
        f"按 {dimension} 看 {metric} 的 Top 排名。",
        f"按 {dimension} 拆分 {metric} 的构成和集中度。",
    ]
    if period_column:
        questions.append(f"按 {period_column} 看 {metric} 的趋势和波动。")
    if rates:
        questions.append(f"分析 {rates[0]['field']} 的占比以及由哪些维度驱动。")
    questions.append("检查缺失值、重复值、离群值和可疑记录。")
    return questions


def _missing_boundaries(columns: list[str]) -> list[str]:
    lowered = {column.lower() for column in columns}
    boundaries = []
    payment_like = any(
        token in column
        for column in lowered
        for token in ("merchant", "card", "psp", "acquirer", "issuing", "eur_amount", "mcc")
    )
    if payment_like and not any("mcc" in column for column in lowered):
        boundaries.append("如果要计算 MCC 或费率变化，需要额外规则表、原 MCC 和目标 MCC 费率口径。")
    if not any(token in column for column in lowered for token in ("date", "month", "日期", "月份")):
        boundaries.append("当前未识别稳定日期字段，时间趋势可能需要补充日期或月份。")
    return boundaries


def _table_type_label(report: dict[str, Any]) -> str:
    fields = " ".join(item["field"].lower() for item in report.get("field_meanings") or [])
    if any(token in fields for token in ("taxi", "trip", "fare", "pickup", "dropoff")):
        return "出租车 / 出行行程明细表"
    if "invoice" in fields and any(token in fields for token in ("stock", "quantity", "unitprice", "customer")):
        return "订单 / 零售交易明细表"
    if "merchant" in fields and ("amount" in fields or "eur_amount" in fields):
        return "支付交易明细表"
    if any(token in fields for token in ("sales", "销售额", "revenue", "收入")):
        return "业务销售 / 收入明细表"
    if any(token in fields for token in ("inventory", "库存")):
        return "库存明细表"
    return "结构化数据表"


def _preferred_metric_column(df: pd.DataFrame, question: str) -> str | None:
    columns = [str(column) for column in df.columns]
    numeric_columns = [column for column in columns if _numeric_ratio(df[column]) >= 0.75]
    if not numeric_columns:
        return None
    lowered_question = question.lower()
    preferred_tokens = (
        "订阅收入",
        "销售额",
        "收入",
        "订单金额",
        "成交金额",
        "金额",
        "毛利",
        "利润",
        "arr",
        "gmv",
        "sales",
        "revenue",
        "amount",
    )
    for token in preferred_tokens:
        for column in numeric_columns:
            if token in column.lower() or column.lower() in lowered_question:
                return column
    non_identifier = [column for column in numeric_columns if not _looks_like_identifier_or_score(column)]
    return non_identifier[0] if non_identifier else numeric_columns[0]


def _preferred_dimension_column(columns: list[str], metric_column: str | None) -> str | None:
    preferred_tokens = ("区域", "城市", "获客渠道", "渠道", "产品线", "套餐名称", "客户类型", "行业", "category", "city", "region", "channel", "product")
    for token in preferred_tokens:
        for column in columns:
            if column == metric_column:
                continue
            if token in column.lower():
                return column
    return None


def _preferred_period_column(columns: list[str]) -> str | None:
    for token in ("月份", "周标签", "日期", "month", "week", "date"):
        for column in columns:
            if token in column.lower():
                return column
    return None


def _metric_summary(df: pd.DataFrame, metric_column: str, dimension_column: str | None, period_column: str | None) -> dict[str, Any]:
    values = pd.to_numeric(df[metric_column], errors="coerce").dropna()
    total = float(values.sum()) if not values.empty else 0.0
    average = float(values.mean()) if not values.empty else 0.0
    max_index = values.idxmax() if not values.empty else None
    min_index = values.idxmin() if not values.empty else None
    max_row = df.loc[max_index].to_dict() if max_index is not None else {}
    min_row = df.loc[min_index].to_dict() if min_index is not None else {}
    rows = [
        {"指标": f"{metric_column}合计", "数值": _format_number(total)},
        {"指标": f"{metric_column}平均", "数值": _format_number(average)},
        {"指标": f"{metric_column}中位数", "数值": _format_number(float(values.median()) if not values.empty else 0.0)},
        {"指标": f"{metric_column}最高", "数值": _describe_row_metric(max_row, metric_column, dimension_column, period_column)},
        {"指标": f"{metric_column}最低", "数值": _describe_row_metric(min_row, metric_column, dimension_column, period_column)},
    ]
    return {
        "rows": rows,
        "total": _format_number(total),
        "average": _format_number(average),
        "median": _format_number(float(values.median()) if not values.empty else 0.0),
        "min": _format_number(float(values.min()) if not values.empty else 0.0),
        "max": _format_number(float(values.max()) if not values.empty else 0.0),
        "max_description": _describe_row_metric(max_row, metric_column, dimension_column, period_column),
        "min_description": _describe_row_metric(min_row, metric_column, dimension_column, period_column),
        "top_group": _top_group(df, dimension_column, metric_column) if dimension_column else None,
    }


def _numeric_ratio(series: pd.Series) -> float:
    non_null = series.dropna()
    if non_null.empty:
        return 0.0
    numeric = pd.to_numeric(non_null, errors="coerce").notna().sum()
    return float(numeric) / float(len(non_null))


def _looks_like_identifier_or_score(column: str) -> bool:
    lowered = column.lower()
    return any(
        token in lowered
        for token in (
            "id",
            "code",
            "invoice",
            "reference",
            "ref",
            "number",
            "stock",
            "customer",
            "序号",
            "编号",
            "编码",
            "评分",
            "score",
            "rate",
            "率",
            "天数",
            "账号数",
            "席位",
        )
    )


def _distribution_summary_text(dist: dict[str, Any]) -> str:
    values = [str(item.get("value") or "") for item in dist.get("top_values", [])[:5]]
    field = str(dist.get("field") or "")
    unique_count = int(dist.get("unique_count") or 0)
    if any(token in field.lower() for token in ("description", "desc", "name", "备注", "描述", "名称")) or any(len(value) > 24 for value in values):
        return f"共 {unique_count} 个常见取值，适合作为分组、筛选或明细识别字段；概览不展开原始取值。"
    return "，".join(f"{item['value']} {item['count']:,}" for item in dist.get("top_values", [])[:5])


def _describe_row_metric(row: dict[str, Any], metric_column: str, dimension_column: str | None, period_column: str | None) -> str:
    parts = []
    if dimension_column and row.get(dimension_column) not in {None, ""}:
        parts.append(str(row.get(dimension_column)))
    if period_column and row.get(period_column) not in {None, ""}:
        parts.append(str(row.get(period_column)))
    value = _as_float(row.get(metric_column)) or 0.0
    prefix = " / ".join(parts)
    return f"{prefix}：{_format_number(value)}" if prefix else _format_number(value)


def _top_group(df: pd.DataFrame, dimension_column: str | None, metric_column: str) -> str | None:
    if not dimension_column or dimension_column not in df.columns:
        return None
    data = df[[dimension_column, metric_column]].copy()
    data[metric_column] = pd.to_numeric(data[metric_column], errors="coerce")
    grouped = data.dropna(subset=[dimension_column, metric_column]).groupby(dimension_column, dropna=True)[metric_column].sum()
    if grouped.empty:
        return None
    key = grouped.idxmax()
    return f"{key}：{_format_number(float(grouped.loc[key]))}"


def _format_number(value: float) -> str:
    if not math.isfinite(value):
        return "-"
    if math.isclose(value, round(value)):
        return f"{int(round(value)):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _format_percent(value: float) -> str:
    if not math.isfinite(value):
        return "-"
    return f"{value:.2f}%"


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _join_non_empty(values: list[Any], sep: str) -> str:
    return sep.join(str(value) for value in values if value not in {None, ""})
