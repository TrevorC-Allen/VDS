"""Dataset overview response builder for broad workbench questions."""

from __future__ import annotations

import math
import warnings
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
    quality_report = _quality_report_payload(profile_payload)
    quality_issues = _quality_issues_for_table(quality_report, table_name)
    likely_meaning = _likely_table_meaning(table_name, columns, field_meanings)
    overview_report = {
        "report_type": "overview_report",
        "question": question,
        "table": table_name,
        "source_file": source_file,
        "sheet": sheet,
        "row_count": row_count,
        "column_count": len(columns),
        "likely_meaning": likely_meaning,
        "metric_column": metric_column,
        "dimension_column": dimension_column,
        "period_column": period_column,
        "period_range": _period_range(df, period_column) if period_column else {},
        "field_meanings": field_meanings,
        "metric_summary": metric_summary or {},
        "categorical_distributions": categorical_distributions,
        "boolean_rates": boolean_rates,
        "answerable_questions": answerable_questions,
        "missing_boundaries": missing_boundaries,
        "quality_issues": quality_issues,
        "quality_issue_count": len(quality_issues),
    }
    result_rows = _overview_result_rows(overview_report)
    question_kind = _overview_question_kind(question)
    answer = _overview_shape_answer(overview_report) if _wants_shape_summary(question) else _overview_answer(overview_report, question)
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
        "quality_report": quality_report,
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
            question=question,
            table_name=table_name,
            row_count=row_count,
            column_count=len(columns),
            metric_column=metric_column,
            dimension_column=dimension_column,
            period_column=period_column,
            question_kind=question_kind,
            sample_columns=columns[:8],
            artifact_count=len(execution_artifacts),
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
        "看一下这个数据",
        "看下这个数据",
        "看看这个数据",
        "看一下这份数据",
        "看下这份数据",
        "看看这份数据",
        "表单含义",
        "有什么字段",
        "有哪些字段",
        "字段是否一致",
        "新增",
        "类型变化",
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
    quality_report = _quality_report_payload(profile_payload)
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
        quality_issues = _quality_issues_for_table(quality_report, table_name)
        summary["quality_issue_count"] = len(quality_issues)
        summary["quality_issues"] = quality_issues[:8]
        table_summaries.append(summary)
        total_rows += summary["row_count"]
        total_columns += summary["column_count"]

    table_summaries.sort(key=lambda item: (-int(item["row_count"]), -int(item["column_count"]), str(item["table"])))
    overview_report = {
        "report_type": "overview_report",
        "question": question,
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
    question_kind = _overview_question_kind(question)
    answer = _multi_table_shape_answer(overview_report) if _wants_shape_summary(question) else _multi_table_answer(overview_report, question)
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
            "columns": ["表名", "行数", "类型", "主要作用", "关键字段"],
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
        "quality_report": quality_report,
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
            question=question,
            table_name="多表数据集",
            row_count=total_rows,
            column_count=total_columns,
            table_count=len(table_summaries),
            is_multi_table=True,
            question_kind=question_kind,
            table_summaries=table_summaries,
            sample_columns=_multi_table_sample_columns(table_summaries),
            artifact_count=len(execution_artifacts),
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


def _quality_report_payload(profile: dict[str, Any]) -> dict[str, Any] | None:
    report = profile.get("quality_report") if isinstance(profile, dict) else None
    return report if isinstance(report, dict) else None


def _quality_issues_for_table(report: dict[str, Any] | None, table_name: str) -> list[dict[str, Any]]:
    if not isinstance(report, dict):
        return []
    issues: list[dict[str, Any]] = []
    for issue in report.get("issues") or []:
        payload = issue if isinstance(issue, dict) else asdict(issue)
        if str(payload.get("table_name") or "") == table_name:
            issues.append(payload)
    issues.sort(key=lambda item: (_severity_rank(str(item.get("severity") or "")), -int(item.get("affected_rows") or 0)))
    return issues


def _severity_rank(value: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(value.lower(), 3)


def _quality_issue_messages(issues: list[dict[str, Any]], *, limit: int = 8) -> list[str]:
    messages: list[str] = []
    for issue in issues[:limit]:
        message = str(issue.get("message") or "").strip()
        if not message:
            issue_type = str(issue.get("issue_type") or "质量问题")
            column = str(issue.get("column_name") or "").strip()
            affected = issue.get("affected_rows")
            message = f"{column or issue_type}：影响 {affected} 行" if affected is not None else issue_type
        messages.append(_trim_sentence_punctuation(message))
    return messages


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
        "table_type": _table_type_label(
            {
                "table": table_name,
                "source_file": source_file,
                "field_meanings": field_meanings,
                "columns": columns,
            }
        ),
        "likely_meaning": _likely_table_meaning(table_name, columns, field_meanings),
        "metric_column": metric_column,
        "dimension_column": dimension_column,
        "period_column": period_column,
        "period_range": _period_range(df, period_column) if period_column else {},
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


def _multi_table_sample_columns(table_summaries: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    for item in table_summaries:
        for field in item.get("field_meanings") or []:
            name = str(field.get("field") or "").strip() if isinstance(field, dict) else ""
            if name and name not in columns:
                columns.append(name)
            if len(columns) >= 10:
                return columns
    return columns


def _overview_question_kind(question: str) -> str:
    compact = str(question or "").lower().replace(" ", "")
    if any(token in compact for token in ("最主要的分组", "主要分组", "主要类别", "分组或类别")):
        return "top_category"
    if any(token in compact for token in ("趋势", "环比", "同比")) and any(token in compact for token in ("能不能", "能否", "可以", "准备")):
        return "time_readiness"
    if any(token in compact for token in ("join", "关联", "对比字段")) and any(token in compact for token in ("多文件", "多表", "多个表", "多个文件")):
        return "join_readiness"
    if "核心指标" in compact and "维度" in compact and any(token in compact for token in ("选", "选择", "做分析")):
        return "metric_dimension"
    if "字段" in compact and any(token in compact for token in ("指标", "维度", "时间", "id", "ID")):
        return "field_roles"
    if any(token in compact for token in ("区别", "差异", "不同", "字段是否一致", "新增", "类型变化")):
        return "difference"
    if any(token in compact for token in ("有什么字段", "有哪些字段", "字段是什么", "字段含义", "字段意思")):
        return "fields"
    if any(token in compact for token in ("有什么内容", "有哪些内容", "包含什么", "里面有什么")):
        return "content"
    if any(token in compact for token in ("主要讲什么", "讲的什么", "讲什么", "什么意思", "含义", "是做什么", "主要内容")):
        return "story"
    if any(token in compact for token in ("适合做哪些分析", "可以做哪些分析", "下一步", "建议分析", "分析方向")):
        return "analysis_suggestions"
    if any(token in compact for token in ("正常吗", "能不能用", "哪里有问题", "有什么问题", "质量", "异常", "缺失")):
        return "quality"
    if _wants_shape_summary(question):
        return "shape"
    return "overview"


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


def _multi_table_answer(report: dict[str, Any], question: str) -> str:
    kind = _overview_question_kind(question)
    if kind == "difference":
        return _multi_table_difference_answer(report)
    if kind == "story":
        return _multi_table_story_answer(report)
    if kind == "content":
        return _multi_table_content_answer(report)
    if kind == "fields":
        return _multi_table_fields_answer(report)
    if kind == "field_roles":
        return _multi_table_field_roles_answer(report)
    if kind == "analysis_suggestions":
        return _multi_table_analysis_suggestions_answer(report)
    if kind == "quality":
        return _multi_table_quality_answer(report)
    if kind == "top_category":
        return _multi_table_top_category_answer(report)
    if kind == "time_readiness":
        return _multi_table_time_readiness_answer(report)
    if kind == "join_readiness":
        return _multi_table_join_readiness_answer(report)
    if kind == "metric_dimension":
        return _multi_table_metric_dimension_answer(report)
    return _multi_table_general_answer(report)


def _multi_table_general_answer(report: dict[str, Any]) -> str:
    tables = report.get("tables_summary") or []
    top_tables = tables[:5]
    themes = _short_join([str(item.get("likely_meaning") or "").split("，")[0] for item in top_tables], limit=4)
    table_examples = _short_join([f"{item['table']}（{item['row_count']:,} 行）" for item in top_tables], limit=5)
    relationship = _multi_table_relationship_text(tables)
    suggestions = _multi_table_suggestion_text(tables)
    role_summary = _table_role_summary(tables)
    lines = [
        f"已读取这组数据：它不是一张单表，而是 {report['table_count']} 张表组成的数据集，共 {report['total_row_count']:,} 行、{report['total_column_count']} 个字段。",
        f"初步看，数据主题大致覆盖 {themes or '业务事实表、维表和过程表'}；这是基于字段名、表名和类型的推测，正式口径还要看业务说明。",
        f"按角色看，{role_summary}。",
        f"主要区别在表的粒度和用途：例如 {table_examples or '各表'}。{relationship}",
        f"建议分析方向：{suggestions}",
        "质量问题也需要单独看，尤其是缺失、重复和异常值；完整表清单和关键字段我放在结果表里，不在主回答里展开明细。",
    ]
    return "\n".join(lines)


def _multi_table_story_answer(report: dict[str, Any]) -> str:
    tables = report.get("tables_summary") or []
    fact_tables = _tables_matching(tables, ("明细", "订单", "交易", "活动", "拜访", "行程", "目标", "计划"))
    dim_tables = _dimension_like_tables(tables)
    shown = tables[:5]
    table_roles = "；".join(
        f"{item['table']}：{_trim_sentence_punctuation(str(item.get('likely_meaning') or '结构化数据表'))}"
        for item in shown
    )
    lines = [
        f"这组数据主要是在描述一个业务过程，而不是单张孤立表：共有 {report['table_count']} 张表、{report['total_row_count']:,} 行。",
        f"从表名和字段看，核心内容大致是：{_multi_table_theme_sentence(tables)}",
    ]
    if fact_tables:
        lines.append("事实/过程类表更像承载真实发生的记录，例如 " + "、".join(item["table"] for item in fact_tables[:4]) + "。")
    if dim_tables:
        lines.append("维度/说明类表更像补充客户、产品、组织或字段解释，例如 " + "、".join(item["table"] for item in dim_tables[:4]) + "。")
    lines.append(f"几张主要表的含义是：{table_roles}。")
    lines.append("建议分析方向：先做“表结构和业务口径确认”，再进入目标完成、订单/交易、活动执行或客户/产品维度分析。")
    return "\n".join(lines)


def _multi_table_content_answer(report: dict[str, Any]) -> str:
    tables = report.get("tables_summary") or []
    shown = tables[:6]
    lines = [
        f"这些表单/文件里主要有 {report['table_count']} 类内容，我按“每个文件装了什么”来讲，不走计算型查询。",
    ]
    for item in shown:
        key_fields = "、".join(item.get("key_fields") or []) or "待确认"
        lines.append(
            f"- {item['table']}：{int(item.get('row_count') or 0):,} 行、{int(item.get('column_count') or 0)} 列；"
            f"内容大致是{_trim_sentence_punctuation(str(item.get('likely_meaning') or '结构化业务记录'))}；关键字段包括 {key_fields}。"
        )
    if len(tables) > len(shown):
        lines.append(f"还有 {len(tables) - len(shown)} 张表在结果表里，主回答先保留前 {len(shown)} 张。")
    lines.append("如果这组上传里还有说明/规则文件，我会在来源文件概览里把 manual、json、txt、docx 等文件也列出来解释用途。")
    lines.append("下一步可以直接问“这些文件怎么关联”或“哪个表适合作为主事实表”，再进入具体分析。")
    return "\n".join(lines)


def _multi_table_difference_answer(report: dict[str, Any]) -> str:
    tables = report.get("tables_summary") or []
    shown = tables[:8]
    lines = [
        f"这些文件/表的区别主要在三件事：粒度、用途和关键字段。当前一共 {report['table_count']} 张表，不应该默认把它们当成同一张表拼起来。",
    ]
    for item in shown:
        key_fields = "、".join(item.get("key_fields") or []) or "待确认"
        lines.append(
            f"- {item['table']}：{int(item.get('row_count') or 0):,} 行、{int(item.get('column_count') or 0)} 列；"
            f"{_trim_sentence_punctuation(str(item.get('likely_meaning') or '结构化数据表'))}；关键字段：{key_fields}"
        )
    if len(tables) > len(shown):
        lines.append(f"还有 {len(tables) - len(shown)} 张表在结果表里，主回答先保留前 {len(shown)} 张，避免刷屏。")
    lines.append(_multi_table_relationship_text(tables))
    lines.append("下一步如果要关联分析，需要先确认主键、月份/日期粒度和一对多关系；如果只是文件差异，先比较行列、字段集合、缺失率和字段类型。")
    return "\n".join(lines)


def _multi_table_fields_answer(report: dict[str, Any]) -> str:
    tables = report.get("tables_summary") or []
    shown = tables[:6]
    lines = [
        f"这组数据有 {report['table_count']} 张表，我先按表列出关键字段，不展开原始行。",
    ]
    for item in shown:
        key_fields = "、".join(item.get("key_fields") or []) or "待确认"
        meanings = item.get("field_meanings") or []
        meaning_text = "；".join(f"{field.get('field')}：{field.get('meaning')}" for field in meanings[:3] if isinstance(field, dict))
        lines.append(f"- {item['table']}：关键字段 {key_fields}。{meaning_text}")
    if len(tables) > len(shown):
        lines.append(f"还有 {len(tables) - len(shown)} 张表的字段清单在结果表里。")
    lines.append("字段含义是根据字段名、类型和样例分布做的推测；正式业务口径要以表说明或知识库为准。")
    lines.append("不确定字段会标记为“需业务确认/需用户确认”，不会当成已经确认的事实。")
    lines.append("下一步可以继续问“哪些字段适合做指标、维度、时间和 ID”，或让我按缺失率、类型变化和样例分布做字段体检。")
    return "\n".join(lines)


def _multi_table_field_roles_answer(report: dict[str, Any]) -> str:
    tables = report.get("tables_summary") or []
    lines = [
        f"我按指标、维度、时间和 ID 四类整理字段角色；当前有 {report['table_count']} 张表，字段角色属于推测，需业务确认。",
    ]
    for item in tables[:8]:
        field_names = [str(field.get("field")) for field in item.get("field_meanings") or [] if isinstance(field, dict)]
        roles = _field_role_columns(
            field_names,
            metric_column=item.get("metric_column"),
            dimension_column=item.get("dimension_column"),
            period_column=item.get("period_column"),
        )
        lines.append(
            f"- {item['table']}：指标={_format_role_list(roles['metrics'])}；维度={_format_role_list(roles['dimensions'])}；"
            f"时间={_format_role_list(roles['time'])}；ID={_format_role_list(roles['ids'])}。"
        )
    if len(tables) > 8:
        lines.append(f"还有 {len(tables) - 8} 张表的字段角色在结果表里。")
    lines.append("下一步建议先确认主事实表和核心指标，再决定是否按 ID / 编码 / 日期字段做 join 或趋势分析。")
    return "\n".join(lines)


def _multi_table_analysis_suggestions_answer(report: dict[str, Any]) -> str:
    tables = report.get("tables_summary") or []
    suggestions = _multi_table_suggestion_text(tables)
    lines = [
        f"这组数据可以分析，但建议先按“事实表 -> 维表 -> 指标”来推进。当前有 {report['table_count']} 张表、{report['total_column_count']} 个字段。",
        f"第一步：先选主事实表。{_multi_table_relationship_text(tables)}",
        f"第二步：选一个核心指标和时间粒度。{suggestions}",
        "第三步：再决定是否做 join。字段同名不等于可关联，必须确认业务主键和一对多关系。",
        "我建议你下一条直接问一个具体目标，例如“按月份看订单金额趋势”或“活动执行和目标完成有什么差距”。",
    ]
    return "\n".join(lines)


def _multi_table_quality_answer(report: dict[str, Any]) -> str:
    tables = report.get("tables_summary") or []
    biggest = tables[:3]
    issue_tables = [item for item in tables if int(item.get("quality_issue_count") or 0) > 0]
    lines = [
        f"只看表结构，这组数据“可以继续分析”，但还不能直接判定完全正常。它包含 {report['table_count']} 张表、{report['total_row_count']:,} 行。",
        "我会优先检查四类质量问题：字段缺失、重复记录、异常数值、跨表主键是否能对齐。",
    ]
    if issue_tables:
        lines.append(
            "当前质量扫描已发现问题最多的表："
            + "、".join(f"{item['table']}（{int(item.get('quality_issue_count') or 0)} 类）" for item in issue_tables[:5])
            + "。"
        )
        first_issue = _quality_issue_messages(issue_tables[0].get("quality_issues") or [], limit=3)
        if first_issue:
            lines.append(f"例如 {issue_tables[0]['table']} 的主要问题包括：" + "；".join(first_issue) + "。")
    if biggest:
        lines.append("优先检查的大表是：" + "、".join(f"{item['table']}（{item['row_count']:,} 行）" for item in biggest) + "。")
    lines.append("如果要正式判断“哪里有问题”，下一步应按表展开缺失率、重复率、数值极端值、时间范围和字段类型变化。")
    lines.append("我不会把概览阶段包装成“数据完全正常”；当前结论是：结构可读，但质量风险需要逐表确认。")
    return "\n".join(lines)


def _multi_table_top_category_answer(report: dict[str, Any]) -> str:
    tables = report.get("tables_summary") or []
    lines = [f"这是多表数据，不能先假设一个全局“最主要类别”；需要先选主事实表。当前有 {report['table_count']} 张表。"]
    for item in tables[:5]:
        roles = _field_role_columns(
            [str(field.get("field")) for field in item.get("field_meanings") or [] if isinstance(field, dict)],
            metric_column=item.get("metric_column"),
            dimension_column=item.get("dimension_column"),
            period_column=item.get("period_column"),
        )
        lines.append(f"- {item['table']}：可优先尝试的分组字段={_format_role_list(roles['dimensions'])}。")
    lines.append("下一步应先指定事实表和指标，再判断哪个分组/类别真正重要。")
    return "\n".join(lines)


def _multi_table_time_readiness_answer(report: dict[str, Any]) -> str:
    tables = report.get("tables_summary") or []
    ready = [item for item in tables if item.get("period_column") and item.get("metric_column")]
    if ready:
        lines = ["这些表里有部分表具备趋势/环比/同比准备条件："]
        lines.extend(f"- {item['table']}：时间={item.get('period_column')}，指标={item.get('metric_column')}。" for item in ready[:6])
    else:
        lines = ["当前没有稳定识别到同时具备时间字段和指标字段的表；趋势、环比或同比需要先指定时间字段和指标。"]
    lines.append("同比还需要覆盖可比年份或周期；字段同名不等于可以直接跨表拼接。")
    return "\n".join(lines)


def _multi_table_join_readiness_answer(report: dict[str, Any]) -> str:
    tables = report.get("tables_summary") or []
    shared: set[str] | None = None
    for item in tables:
        names = {str(field.get("field")) for field in item.get("field_meanings") or [] if isinstance(field, dict)}
        shared = names if shared is None else shared & names
    candidates = [field for field in sorted(shared or set()) if _looks_like_id_field(field) or _looks_like_time_field(field)]
    if candidates:
        text = "多表存在潜在 join / 对比字段：" + "、".join(candidates[:10]) + "。"
    else:
        text = "当前未识别到稳定的同名 ID / 编码 / 日期类 join key。"
    return text + "必须再检查唯一性、一对多关系、缺失率和业务主键定义，不能仅凭同名字段直接 join。"


def _multi_table_metric_dimension_answer(report: dict[str, Any]) -> str:
    tables = report.get("tables_summary") or []
    for item in tables:
        if item.get("metric_column") and item.get("dimension_column"):
            return f"可以先用 {item['table']} 做正式分析：核心指标={item['metric_column']}，维度={item['dimension_column']}。这一步应从概览切到 analysis，并保留字段依据。"
    return "还不能稳定选择核心指标和维度；请先指定主事实表，或让我按字段角色列出每张表的候选指标、维度、时间和 ID。"


def _tables_matching(tables: list[dict[str, Any]], tokens: tuple[str, ...]) -> list[dict[str, Any]]:
    result = []
    for item in tables:
        haystack = f"{item.get('table', '')} {item.get('table_type', '')} {item.get('likely_meaning', '')}".lower()
        if any(token.lower() in haystack for token in tokens):
            result.append(item)
    return result


def _dimension_like_tables(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    fact_markers = ("订单或交易明细", "活动执行", "陈列明细", "拜访或路线过程", "目标或计划", "出租车或出行")
    dim_markers = ("维表", "客户或终端", "sku", "商品", "产品", "说明")
    for item in tables:
        meaning = str(item.get("likely_meaning") or "")
        table_type = str(item.get("table_type") or "")
        table_name = str(item.get("table") or "").lower()
        if any(marker in meaning for marker in fact_markers):
            continue
        haystack = f"{table_name} {table_type} {meaning}".lower()
        if any(marker.lower() in haystack for marker in dim_markers):
            result.append(item)
    return result


def _multi_table_theme_sentence(tables: list[dict[str, Any]]) -> str:
    haystack = _tables_haystack(tables)
    if any(token in haystack for token in ("target", "visit", "route", "actv", "dsp", "目标", "拜访", "活动", "陈列")):
        return "围绕销售/分销目标、订单或交易、终端客户、产品/SKU、拜访路线和活动执行形成的一组运营数据。"
    if any(token in haystack for token in ("order", "payment", "customer", "product", "seller", "订单", "支付", "客户", "商品")):
        return "围绕订单、支付、客户、商品和卖家形成的交易数据。"
    if any(token in haystack for token in ("taxi", "trip", "fare", "pickup", "dropoff", "行程", "车费")):
        return "围绕出行订单、上下车时间地点、里程和费用形成的行程数据。"
    return "围绕若干业务实体、记录明细和辅助说明表形成的结构化数据集。"


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
                "行数": item.get("row_count"),
                "类型": item.get("table_type"),
                "主要作用": item.get("likely_meaning"),
                "关键字段": "、".join(item.get("key_fields") or []),
            }
        )
    return rows


def _table_role_summary(tables: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for item in tables:
        table_type = str(item.get("table_type") or "结构化数据表")
        counts[table_type] = counts.get(table_type, 0) + 1
    if not counts:
        return "暂未识别稳定表角色"
    return "、".join(f"{name} {count} 张" for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5])


def _multi_table_insight(report: dict[str, Any]) -> InsightResult:
    tables = report.get("tables_summary") or []
    table_names = "、".join(str(item.get("table")) for item in tables[:3])
    question_kind = _overview_question_kind(str(report.get("question") or ""))
    topic = "差异" if question_kind == "difference" else "分析入口"
    suggestions = [
        f"观察：这组数据的关键不是把 {len(tables)} 张表直接拼宽，而是先选事实表再关联维表；依据：{table_names or '前几张表'} 的行列规模和关键字段差异；建议：下一步先确认主事实表、日期粒度和客户/商品/员工等关联键，再做趋势、目标达成或过程漏斗分析。"
    ]
    return InsightResult(
        summary=f"这是一组多表数据，当前最有价值的是先理清表的{topic}和关联边界，而不是直接展示明细行。",
        business_suggestions=suggestions,
        suggestions=suggestions,
        caveats=list(report.get("missing_boundaries") or []),
        next_questions=[
            "哪张表最适合作为主事实表？",
            "这些表可以按哪些字段安全关联？",
        ],
        evidence_rows=_multi_table_result_rows(report)[:5],
        confidence=0.84,
    )


def _multi_table_execution_artifacts(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _multi_table_result_rows(report)
    code = "\n".join(
        [
            "import pandas as pd",
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
    sql = "\n".join(
        [
            "-- table_manifest is built by the backend from parsed upload tables.",
            "SELECT",
            "  table_name,",
            "  source_file,",
            "  row_count,",
            "  column_count,",
            "  likely_meaning",
            "FROM table_manifest",
            "ORDER BY row_count DESC, column_count DESC;",
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
        },
        {
            "artifact_id": "multi_table_overview_sql",
            "language": "sql",
            "title": "多表 SQL 清单口径",
            "purpose": "展示同一组上传表在只读 SQL 视角下如何枚举，便于和 Pandas 概览对照。",
            "code": sql,
            "output_summary": f"返回 {len(rows)} 张表的表名、来源文件、行列规模和可能含义。",
        },
    ]


def _overview_answer(report: dict[str, Any], question: str) -> str:
    kind = _overview_question_kind(question)
    if kind == "difference":
        return _single_table_difference_answer(report)
    if kind == "story":
        return _single_table_story_answer(report)
    if kind == "content":
        return _single_table_content_answer(report)
    if kind == "fields":
        return _single_table_fields_answer(report)
    if kind == "field_roles":
        return _single_table_field_roles_answer(report)
    if kind == "analysis_suggestions":
        return _single_table_analysis_suggestions_answer(report)
    if kind == "quality":
        return _single_table_quality_answer(report)
    if kind == "top_category":
        return _single_table_top_category_answer(report)
    if kind == "time_readiness":
        return _single_table_time_readiness_answer(report)
    if kind == "join_readiness":
        return _single_table_join_readiness_answer(report)
    if kind == "metric_dimension":
        return _single_table_metric_dimension_answer(report)
    return _single_table_general_answer(report)


def _single_table_general_answer(report: dict[str, Any]) -> str:
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
    table_role = _table_type_label(report)
    business_type = _table_business_type_label(report)
    table_type_text = f"{table_role}（{business_type}）" if business_type else table_role
    lines = [
        f"已读取这个数据（{report.get('table') or '当前表'}）：{report['row_count']:,} 行、{report['column_count']} 列。",
        f"这个表更像是{table_type_text}，主要讲的是{report.get('likely_meaning') or '一组结构化业务记录'}",
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


def _single_table_story_answer(report: dict[str, Any]) -> str:
    metric = report.get("metric_column")
    dimension = report.get("dimension_column")
    period = report.get("period_column")
    field_names = [str(item.get("field")) for item in (report.get("field_meanings") or [])[:8]]
    lines = [
        f"这个数据主要讲的是：{report.get('likely_meaning') or '一组结构化业务记录'}",
        f"它目前是一张表（{report.get('table') or '当前表'}），规模是 {report['row_count']:,} 行、{report['column_count']} 列。",
        "从字段看，核心信息包括 " + (_short_join([item for item in [period, dimension, metric, *field_names] if item], limit=8) or "待结合业务说明确认的字段") + "。",
    ]
    if metric:
        lines.append(f"如果要进一步分析，{metric} 可以作为优先指标；" + (f"{dimension} 可以作为分组维度。" if dimension else "分组维度需要你指定或结合字段说明确认。"))
    else:
        lines.append("如果要进一步分析，需要先确认哪个数值字段才是业务指标，避免把编号或代码当成金额求和。")
    lines.append("建议分析方向：先确认指标字段和维度字段，再继续做汇总、排名、趋势或质量检查。")
    lines.append("这不是原始明细展示；完整字段画像、基础分布和可追问方向在结果表里。")
    return "\n".join(lines)


def _single_table_content_answer(report: dict[str, Any]) -> str:
    metric = report.get("metric_column")
    dimension = report.get("dimension_column")
    period = report.get("period_column")
    field_names = [str(item.get("field")) for item in (report.get("field_meanings") or [])[:8]]
    lines = [
        f"这张表单里有 {report['row_count']:,} 行、{report['column_count']} 列，内容大致是{report.get('likely_meaning') or '结构化业务记录'}。",
        "主要字段包括 " + (_short_join([item for item in [period, dimension, metric, *field_names] if item], limit=8) or "待结合业务说明确认的字段") + "。",
    ]
    if metric or dimension or period:
        lines.append(
            "从字段角色看，"
            + (f"时间字段可能是 {period}；" if period else "")
            + (f"分组维度可能是 {dimension}；" if dimension else "")
            + (f"可汇总指标可能是 {metric}。" if metric else "")
        )
    lines.append("这类问题先做内容概览；真正的金额、排名、趋势问题再进入计算链路。")
    return "\n".join(lines)


def _single_table_fields_answer(report: dict[str, Any]) -> str:
    fields = report.get("field_meanings") or []
    shown = fields[:12]
    lines = [
        f"这张表有 {report['column_count']} 个字段；我先列关键字段含义，不展示原始明细。",
    ]
    for field in shown:
        lines.append(f"- {field.get('field')}：{field.get('meaning')}")
    if len(fields) > len(shown):
        lines.append(f"还有 {len(fields) - len(shown)} 个字段在结果表里。")
    lines.append("这些含义是根据字段名、类型和样例分布做的推测；如果有字段说明文件，应以说明文件为准。")
    lines.append("不确定字段会标记为“需业务确认/需用户确认”，不会当成已经确认的事实。")
    lines.append("下一步可以继续问“哪些字段适合做指标、维度、时间和 ID”，或让我按缺失率、类型变化和样例分布做字段体检。")
    return "\n".join(lines)


def _single_table_field_roles_answer(report: dict[str, Any]) -> str:
    fields = [str(field.get("field")) for field in report.get("field_meanings") or [] if isinstance(field, dict)]
    roles = _field_role_columns(
        fields,
        metric_column=report.get("metric_column"),
        dimension_column=report.get("dimension_column"),
        period_column=report.get("period_column"),
    )
    lines = [
        f"这张表可以先按字段角色来用：指标={_format_role_list(roles['metrics'])}；维度={_format_role_list(roles['dimensions'])}；时间={_format_role_list(roles['time'])}；ID={_format_role_list(roles['ids'])}。",
        "这些角色是根据字段名、类型和样例分布做的推测；正式建模或汇总前仍需业务确认。",
        "下一步可以选一个指标和一个维度进入正式 analysis，例如按主要维度汇总核心指标，或按时间字段做趋势/环比/同比准备。",
    ]
    return "\n".join(lines)


def _single_table_top_category_answer(report: dict[str, Any]) -> str:
    distributions = report.get("categorical_distributions") or []
    if not distributions:
        return "暂未识别到适合直接做主要分组的低基数字段；如果要判断业务好坏，需要先指定核心指标和分组口径。"
    dist = distributions[0]
    top_values = "、".join(f"{item['value']} {int(item['count']):,}" for item in (dist.get("top_values") or [])[:5])
    return (
        f"可先按 {dist['field']} 看主要分组，Top 值为 {top_values}。"
        "这只是通用分布分析；如果要判断业务好坏，还需要用户指定核心指标和口径。"
    )


def _single_table_time_readiness_answer(report: dict[str, Any]) -> str:
    period = report.get("period_column")
    metric = report.get("metric_column")
    period_range = report.get("period_range") or {}
    if period and metric:
        range_text = f"，时间范围 {period_range.get('min')} 到 {period_range.get('max')}" if period_range else ""
        return f"可以做趋势/环比/同比准备：时间字段={period}，指标字段={metric}{range_text}。同比是否成立还要看是否覆盖可比年份或完整周期。"
    if period:
        return f"有时间字段 {period}，但未稳定识别核心数值指标；趋势、环比或同比需要先指定指标。"
    if metric:
        return f"有指标字段 {metric}，但未识别稳定时间字段；不能直接做趋势、环比或同比。"
    return "暂未识别稳定时间字段和核心指标；不能直接做趋势、环比或同比。"


def _single_table_join_readiness_answer(report: dict[str, Any]) -> str:
    fields = [str(field.get("field")) for field in report.get("field_meanings") or [] if isinstance(field, dict)]
    candidates = [field for field in fields if _looks_like_id_field(field) or _looks_like_time_field(field)]
    return (
        "当前只有一张主表，不需要做多文件 join。"
        + (f"若后续上传多个表，可优先检查这些候选关联/对比字段：{_format_role_list(candidates)}。" if candidates else "若后续上传多个表，需要用户提供共享 ID、编码、名称或日期字段。")
        + "仍要确认 join 粒度、唯一性和一对多关系。"
    )


def _single_table_metric_dimension_answer(report: dict[str, Any]) -> str:
    metric = report.get("metric_column")
    dimension = report.get("dimension_column")
    distributions = report.get("categorical_distributions") or []
    if not dimension and distributions:
        dimension = distributions[0].get("field")
    if metric and dimension:
        return f"可以先选核心指标 {metric}，维度 {dimension} 做分组分析。这一步应从 general 概览切到正式 analysis，但仍要保留字段依据。"
    if metric:
        return f"可以先选核心指标 {metric}，但维度需要用户指定或结合字段说明确认。"
    return "还不能稳定选择核心指标；应先确认哪个数值字段是业务指标，避免把编号或代码当成金额求和。"


def _single_table_difference_answer(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "当前上传内容在可用数据里主要是一张表，所以不能做“多个文件/多张表之间的区别”比较。",
            f"这张表是 {report.get('table') or '当前表'}：{report['row_count']:,} 行、{report['column_count']} 列，{report.get('likely_meaning') or '属于结构化数据表'}",
            "如果你后续上传多个文件，我可以比较每个文件的行列规模、字段集合、字段类型、缺失情况和可能用途差异。",
        ]
    )


def _single_table_analysis_suggestions_answer(report: dict[str, Any]) -> str:
    suggestions = report.get("answerable_questions") or []
    metric = report.get("metric_column")
    dimension = report.get("dimension_column")
    period = report.get("period_column")
    lines = [
        f"这张表可以继续分析。当前规模是 {report['row_count']:,} 行、{report['column_count']} 列。",
        f"优先口径：指标可以先看 {metric or '待确认的数值字段'}；维度可以先看 {dimension or '分类字段'}；时间字段是 {period or '暂未稳定识别'}。",
    ]
    if suggestions:
        lines.append("可直接追问：" + "；".join(_trim_sentence_punctuation(str(item)) for item in suggestions[:4]) + "。")
    else:
        lines.append("可直接追问：字段缺失情况、按维度分组统计、Top 排名、趋势或异常值。")
    lines.append("如果要我给业务结论，请指定一个指标和一个维度；否则我只会停留在概览层。")
    return "\n".join(lines)


def _single_table_quality_answer(report: dict[str, Any]) -> str:
    rows = report.get("row_count") or 0
    columns = report.get("column_count") or 0
    caveats = report.get("missing_boundaries") or []
    issues = report.get("quality_issues") or []
    question_hint = str(report.get("question") or "")
    issue_messages = _quality_issue_messages(issues, limit=8)
    if issues:
        prefix = "这张表可以用于探索性分析，但不能简单说“完全正常”。" if any(token in question_hint for token in ("能不能用", "正常")) else "当前通用质量扫描已经发现一些需要确认的问题。"
        lines = [
            f"{prefix}表规模是 {rows:,} 行、{columns} 列，质量扫描发现 {len(issues)} 类潜在问题。",
            "主要问题：" + "；".join(issue_messages) + "。",
            "这些问题不代表数据不可用，但正式分析前需要确认缺失、重复、负值、极端值或日期解析问题的业务含义。",
            "下一步可以让我按影响行数排序生成清洗模拟，或先选定一个核心指标看这些问题会不会改变结论。",
        ]
        return "\n".join(lines)
    lines = [
        f"这张表结构可读：{rows:,} 行、{columns} 列；但“是否正常”不能只靠概览判断。",
        "我建议正式质量检查至少看：缺失率、重复行、负值/极端值、时间范围、字段类型是否稳定，以及编号字段是否异常重复。",
    ]
    if caveats:
        lines.append("当前边界：" + "；".join(str(item) for item in caveats[:3]) + "。")
    lines.append("所以现阶段结论是：可以继续分析，但需要跑质量扫描后才能说哪些地方有问题。")
    return "\n".join(lines)


def _field_role_columns(
    fields: list[str],
    *,
    metric_column: Any = None,
    dimension_column: Any = None,
    period_column: Any = None,
) -> dict[str, list[str]]:
    roles = {"metrics": [], "dimensions": [], "time": [], "ids": []}

    def add(role: str, value: Any) -> None:
        text = str(value or "").strip()
        if text and text in fields and text not in roles[role]:
            roles[role].append(text)

    add("metrics", metric_column)
    add("dimensions", dimension_column)
    add("time", period_column)
    for field in fields:
        if _looks_like_time_field(field):
            add("time", field)
        elif _looks_like_id_field(field):
            add("ids", field)
        elif _looks_like_metric_field(field):
            add("metrics", field)
        elif field not in roles["metrics"] and field not in roles["time"] and field not in roles["ids"]:
            add("dimensions", field)
    return {key: values[:8] for key, values in roles.items()}


def _looks_like_time_field(field: str) -> bool:
    lowered = field.lower()
    return any(token in lowered for token in ("date", "time", "month", "year", "day")) or any(token in field for token in ("日期", "时间", "月份", "年度", "年份"))


def _looks_like_id_field(field: str) -> bool:
    lowered = field.lower()
    return any(token in lowered for token in ("id", "code", "no", "number", "reference", "invoice", "stockcode")) or any(token in field for token in ("编号", "编码", "单号", "订单号", "客户号"))


def _looks_like_metric_field(field: str) -> bool:
    lowered = field.lower()
    return (
        any(token in lowered for token in ("amount", "price", "quantity", "qty", "sales", "revenue", "_count", "count_", "rate", "fee", "cost"))
        or lowered == "count"
        or any(token in field for token in ("金额", "价格", "单价", "数量", "销量", "销售", "收入", "占比", "费率", "成本"))
    )


def _format_role_list(values: list[str]) -> str:
    return "、".join(values[:6]) if values else "待确认"


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
    dimension = report.get("dimension_column") or "主要维度"
    summary = f"这份数据有 {report['row_count']:,} 行、{report['column_count']} 列，适合先围绕 {metric} 和 {dimension} 建立分析口径。"
    suggestion = ""
    distributions = report.get("categorical_distributions") or []
    if distributions and distributions[0].get("top_values"):
        top = distributions[0]["top_values"][0]
        suggestion = f"观察：{distributions[0]['field']} 中 {top['value']} 记录最多（{top['count']:,} 条）；依据：字段分布统计；建议：下一步先按这个维度拆 {metric}，确认集中度是否来自真实业务结构。"
    metric_summary = report.get("metric_summary") or {}
    if not suggestion and metric_summary.get("max_description"):
        suggestion = f"观察：{metric} 的最高记录为 {metric_summary['max_description']}；依据：数值字段最大值；建议：下一步复核这个高点是否为真实业务峰值，再按来源维度拆解。"
    if not suggestion:
        for rate in (report.get("boolean_rates") or [])[:1]:
            suggestion = f"观察：{rate['field']} 的 true 占比为 {rate['true_rate']}；依据：布尔字段计数；建议：下一步结合 {dimension} 查看这个状态的驱动因素。"
            break
    if not suggestion:
        suggestion = (
            "观察：当前概览未发现单一突出风险信号；依据：字段画像和基础分布；建议：指定时间、维度和指标后继续做趋势或对比。"
        )
    return InsightResult(
        summary=summary,
        business_suggestions=[suggestion],
        suggestions=[suggestion],
        caveats=list(report.get("missing_boundaries") or []),
        next_questions=list(report.get("answerable_questions") or [])[:2],
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
    source_file = str(report.get("source_file") or "")
    table_name = str(report.get("table") or "")
    columns = " ".join(str(column).lower() for column in report.get("columns") or [])
    file_haystack = f"{source_file} {table_name} {columns}".lower()
    if any(token in file_haystack for token in ("知识库", "说明", "表结构", "数据结构", "metadata", "glossary", "dictionary", "readme", "manual", "口径", "规则")):
        return "说明或元数据表"
    fields = " ".join(item["field"].lower() for item in report.get("field_meanings") or [])
    combined = f"{file_haystack} {fields}"
    if any(token in combined for token in ("target", "goal", "目标", "plan", "计划")):
        return "可计算事实表"
    if any(token in combined for token in ("order", "ord", "订单", "交易", "明细", "fact")):
        return "可计算事实表"
    if any(token in fields for token in ("taxi", "trip", "fare", "pickup", "dropoff")):
        return "可计算事实表"
    if "invoice" in fields and any(token in fields for token in ("stock", "quantity", "unitprice", "customer")):
        return "可计算事实表"
    if "merchant" in fields and ("amount" in fields or "eur_amount" in fields):
        return "可计算事实表"
    if any(token in fields for token in ("sales", "销售额", "revenue", "收入")):
        return "可计算事实表"
    if any(token in fields for token in ("inventory", "库存")):
        return "可计算事实表"
    if any(token in combined for token in ("customer", "cust", "客户", "终端", "维表", "dimension", "dim_")):
        return "维表"
    return "结构化数据表"


def _table_business_type_label(report: dict[str, Any]) -> str:
    meaning = str(report.get("likely_meaning") or "")
    haystack = " ".join(
        [
            str(report.get("source_file") or ""),
            str(report.get("table") or ""),
            " ".join(str(column) for column in report.get("columns") or []),
            meaning,
        ]
    ).lower()
    if "出租车" in meaning or any(token in haystack for token in ("taxi", "trip", "fare", "pickup", "dropoff")):
        return "出租车 / 出行行程明细表"
    if "订单或交易明细" in meaning or any(token in haystack for token in ("invoice", "order", "订单", "交易")):
        return "订单 / 零售交易明细表"
    if "客户或终端维表" in meaning or any(token in haystack for token in ("customer", "cust", "客户", "终端")):
        return "客户 / 终端维表"
    if "商品或 SKU" in meaning or any(token in haystack for token in ("sku", "product", "item", "商品", "产品")):
        return "商品 / SKU 维表"
    if "目标或计划表" in meaning or any(token in haystack for token in ("target", "goal", "目标", "计划")):
        return "目标 / 计划表"
    return ""


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
    preferred_tokens = ("区域", "城市", "国家", "获客渠道", "渠道", "产品线", "套餐名称", "客户类型", "行业", "category", "city", "country", "region", "channel", "product")
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


def _period_range(df: pd.DataFrame, period_column: str | None) -> dict[str, str]:
    if not period_column or period_column not in df.columns:
        return {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        parsed = pd.to_datetime(df[period_column], errors="coerce").dropna()
    if parsed.empty:
        return {}
    return {"min": str(parsed.min()), "max": str(parsed.max())}


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
