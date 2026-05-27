"""Safe cleaning-policy and cleaning-simulation responses.

This module produces user-facing cleaning guidance from table statistics only.
It never mutates uploaded data and never returns raw detail rows as the answer.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from data_agent_core.contracts.response_contracts import InsightResult


def build_cleaning_guidance_response(
    *,
    run_id: str,
    dataset_id: str,
    question: str,
    tables: dict[str, pd.DataFrame],
    agent_mode: str = "multi_agent",
) -> dict[str, Any]:
    """Build a safe response for cleaning strategy questions."""

    profiles = [_table_cleaning_profile(table_name, df) for table_name, df in tables.items()]
    total_rows = sum(int(profile["row_count"]) for profile in profiles)
    impacted_rows = sum(int(profile["impacted_rows"]) for profile in profiles)
    direct_action_rows = sum(int(profile["direct_action_rows"]) for profile in profiles)
    impacted_rate = _safe_rate(impacted_rows, total_rows)
    direct_action_rate = _safe_rate(direct_action_rows, total_rows)
    boundary = _is_mutation_boundary_question(question)
    missing_strategy = _is_missing_strategy_question(question)
    question_kind = _cleaning_question_kind(question)
    if boundary:
        answer = _boundary_answer()
        answer_type = "chat"
        execution_mode = "chat"
    elif question_kind == "numeric_quality":
        answer = _numeric_quality_answer(profiles)
        answer_type = "cleaning_simulation"
        execution_mode = "cleaning_simulation"
    elif question_kind == "temporal_quality":
        answer = _temporal_quality_answer(profiles)
        answer_type = "cleaning_simulation"
        execution_mode = "cleaning_simulation"
    elif question_kind == "quality_summary":
        answer = _quality_summary_answer(profiles)
        answer_type = "cleaning_simulation"
        execution_mode = "cleaning_simulation"
    elif question_kind == "cleaning_impact":
        answer = _cleaning_impact_answer(profiles, direct_action_rows, direct_action_rate)
        answer_type = "cleaning_simulation"
        execution_mode = "cleaning_simulation"
    elif question_kind == "missing_fields":
        answer = _missing_fields_answer(profiles)
        answer_type = "cleaning_simulation"
        execution_mode = "cleaning_simulation"
    elif missing_strategy:
        answer = _missing_strategy_answer(profiles)
        answer_type = "cleaning_simulation"
        execution_mode = "cleaning_simulation"
    else:
        answer = _cleaning_policy_answer(profiles, direct_action_rows, direct_action_rate)
        answer_type = "cleaning_simulation"
        execution_mode = "cleaning_simulation"
    result_rows = _cleaning_result_rows(profiles)
    insight = _cleaning_insight(profiles, impacted_rows, impacted_rate, boundary=boundary)
    return {
        "response_version": "v1",
        "success": True,
        "run_id": run_id,
        "dataset_id": dataset_id,
        "question": question,
        "answer_type": answer_type,
        "execution_mode": execution_mode,
        "answer": answer,
        "logic_form": {
            "task_type": "cleaning_guidance",
            "operation": "cleaning_policy" if not boundary else "cleaning_boundary",
            "parameters": {"table_count": len(profiles), "simulation_only": True},
            "source_tables": [profile["table"] for profile in profiles],
            "output_format": {"answer_type": answer_type},
        },
        "result": {
            "columns": ["表名", "规则", "影响行数", "影响比例", "建议"],
            "rows": result_rows,
            "value": {
                "table_count": len(profiles),
                "total_rows": total_rows,
                "estimated_impacted_rows": impacted_rows,
                "estimated_impacted_rate": impacted_rate,
                "direct_action_rows": direct_action_rows,
                "direct_action_rate": direct_action_rate,
            },
        },
        "verification": {
            "passed": True,
            "confidence": 1.0,
            "notes": ["Cleaning guidance is simulation-only and does not modify uploaded files."],
        },
        "insight": insight.__dict__ if not boundary else None,
        "chart": None,
        "quality_report": None,
        "execution_artifacts": [
            {
                "artifact_id": "cleaning_profile_python",
                "language": "python",
                "title": "清洗模拟代码",
                "purpose": "展示如何统计清洗影响；不会覆盖原始文件。",
                "code": _cleaning_artifact_code(),
                "output_summary": f"估算需优先确认的直接清洗影响 {direct_action_rows:,} 行，占 {direct_action_rate}。",
            }
        ]
        if not boundary
        else [],
        "reasoning_trace_view": [
            {
                "step_id": "intent",
                "name": "识别清洗问题",
                "status": "completed",
                "summary": "这是清洗策略或清洗边界问题，只做模拟和建议，不返回原始明细。",
            },
            {
                "step_id": "profile",
                "name": "扫描质量信号",
                "status": "completed",
                "summary": f"已扫描 {len(profiles)} 张表的重复、缺失、负值和极端值信号。",
            },
            {
                "step_id": "boundary",
                "name": "确认安全边界",
                "status": "completed",
                "summary": "所有删除、填充、覆盖或导出清洗后数据都必须先得到用户确认。",
            },
        ],
        "process_view_v2": {
            "version": "v2",
            "summary": "已生成清洗模拟和安全边界说明。",
            "mode": "diagnostic_or_anomaly",
            "steps": [
                {
                    "title": "识别清洗意图",
                    "summary": "问题涉及清洗策略、影响行数/比例或是否修改原始数据。",
                    "status": "completed",
                    "evidence": ["operation=cleaning_policy", "simulation_only=true"],
                    "assumptions": [],
                    "caveats": [],
                    "confidence": 0.9,
                    "source": "service_route",
                },
                {
                    "title": "统计质量信号",
                    "summary": "已基于上传表统计重复、缺失、负值和极端值，不展开原始明细行。",
                    "status": "completed",
                    "evidence": [f"表数量：{len(profiles)}", f"需优先确认：{direct_action_rows:,} 行（{direct_action_rate}）"],
                    "assumptions": ["影响行数按规则并集粗略估算。"],
                    "caveats": ["是否删除、填充或 winsorize 需要业务确认。"],
                    "confidence": 0.86,
                    "source": "deterministic_result",
                },
                {
                    "title": "输出安全建议",
                    "summary": "已给出清洗建议、影响范围和用户确认边界；不会修改原始文件。",
                    "status": "completed",
                    "evidence": ["原始文件保持只读。"],
                    "assumptions": [],
                    "caveats": ["正式清洗前需要确认规则和导出路径。"],
                    "confidence": 0.9,
                    "source": "response_contract",
                },
            ],
        },
        "warnings": [],
        "errors": [],
        "debug": {
            "agent_mode": agent_mode,
            "message_intent": "cleaning_guidance",
            "operation": "cleaning_policy" if not boundary else "cleaning_boundary",
            "source_tables": [profile["table"] for profile in profiles],
            "user_experience_shaping": {
                "applied": True,
                "reason": "cleaning_guidance_prevents_raw_detail_answer",
                "source_row_count": total_rows,
                "estimated_impacted_rows": impacted_rows,
                "direct_action_rows": direct_action_rows,
            },
        },
    }


def _table_cleaning_profile(table_name: str, df: pd.DataFrame) -> dict[str, Any]:
    row_count = int(len(df))
    duplicate_count = int(df.duplicated().sum()) if row_count else 0
    impacted_mask = pd.Series(False, index=df.index)
    direct_action_rows = duplicate_count
    rules: list[dict[str, Any]] = []
    missing_columns = _missing_columns(df)
    numeric_quality: list[dict[str, Any]] = []
    temporal_quality = _temporal_quality(df)
    if duplicate_count:
        impacted_mask = impacted_mask | df.duplicated(keep=False)
        rules.append(_rule("重复行", duplicate_count, row_count, "需确认是否业务重复；默认先标记，不覆盖原始文件。"))
    missing_mask = df.isna().any(axis=1) if row_count else pd.Series(False, index=df.index)
    missing_count = int(missing_mask.sum()) if row_count else 0
    if missing_count:
        impacted_mask = impacted_mask | missing_mask
        top_missing = _top_missing_columns(df)
        rules.append(_rule("缺失值", missing_count, row_count, f"先保留并标记；问题强依赖字段时再讨论删除或填充。{top_missing}"))
    for column in [str(column) for column in df.columns]:
        if _looks_like_identifier_column(column):
            continue
        numeric = pd.to_numeric(df[column], errors="coerce")
        valid = numeric.dropna()
        if len(valid) < max(3, min(20, row_count // 20 if row_count else 3)):
            continue
        negative_mask = numeric < 0
        negative_count = int(negative_mask.sum())
        zero_count = int((numeric == 0).sum())
        high_mask = _high_outlier_mask(numeric)
        high_count = int(high_mask.sum())
        numeric_quality.append(
            {
                "column": column,
                "negative_count": negative_count,
                "zero_count": zero_count,
                "high_outlier_count": high_count,
            }
        )
        if negative_count and _looks_like_measure(column):
            impacted_mask = impacted_mask | negative_mask.fillna(False)
            direct_action_rows += negative_count
            rules.append(_rule(f"{column} 负值", negative_count, row_count, "需确认是否退款、冲销或录入口径。"))
        if high_count and _looks_like_measure(column):
            impacted_mask = impacted_mask | high_mask.fillna(False)
            rules.append(_rule(f"{column} 极端高值", high_count, row_count, "建议 winsorize、单独审查或按业务规则保留。"))
    for item in temporal_quality:
        direct_action_rows += int(item.get("invalid_count") or 0)
    impacted_rows = int(impacted_mask.sum()) if row_count else 0
    return {
        "table": table_name,
        "row_count": row_count,
        "impacted_rows": impacted_rows,
        "direct_action_rows": direct_action_rows,
        "impacted_rate": _safe_rate(impacted_rows, row_count),
        "rules": rules[:10],
        "duplicate_count": duplicate_count,
        "missing_columns": missing_columns,
        "numeric_quality": numeric_quality,
        "temporal_quality": temporal_quality,
    }


def _rule(name: str, count: int, total: int, suggestion: str) -> dict[str, Any]:
    return {
        "rule": name,
        "affected_rows": int(count),
        "affected_rate": _safe_rate(count, total),
        "suggestion": suggestion,
    }


def _cleaning_policy_answer(profiles: list[dict[str, Any]], impacted_rows: int, impacted_rate: str) -> str:
    top_rules = _top_cleaning_rules(profiles, limit=5)
    if top_rules:
        rule_text = "；".join(
            f"{item['table']} 的 {item['rule']} 约 {item['affected_rows']:,} 行（{item['affected_rate']}）"
            for item in top_rules
        )
    else:
        rule_text = "暂未发现需要立即处理的重复、缺失、负值或极端值信号"
    parts = [
        f"建议清洗规则先按影响范围排优先级：{rule_text}。",
        f"其中重复、可疑负值或无法解析日期这类需优先确认的直接清洗信号，粗略影响 {impacted_rows:,} 行（{impacted_rate}）。这只是规则命中数求和，不代表应该直接删除这些行。",
        "建议先确认每条规则的业务含义，再做清洗前后指标对比；不能覆盖原始文件，删除、填充或 winsorize 都需要用户确认。",
        "完整规则、影响行数和影响比例我放在结果表里，主回答不展开所有表的明细。",
    ]
    return "\n".join(parts)


def _top_cleaning_rules(profiles: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for profile in profiles:
        for rule in profile.get("rules") or []:
            flattened.append({"table": profile["table"], **rule})
    flattened.sort(key=lambda item: int(item.get("affected_rows") or 0), reverse=True)
    return flattened[:limit]


def _cleaning_question_kind(question: str) -> str:
    compact = str(question or "").replace(" ", "")
    if any(token in compact for token in ("日期字段", "日期", "时间字段", "时间范围", "无法解析", "范围异常")):
        return "temporal_quality"
    if any(token in compact for token in ("数值字段", "负值", "0值", "零值", "极端值", "离群值")):
        return "numeric_quality"
    if any(token in compact for token in ("如果先处理", "删除明显异常", "核心指标会受什么影响", "结论会不会变")):
        return "cleaning_impact"
    if "缺失" in compact and any(token in compact for token in ("哪些字段", "字段有缺失", "缺失最多")):
        return "missing_fields"
    if any(token in compact for token in ("哪里有问题", "正常吗", "能不能用", "数据质量", "明显的数据质量问题")):
        return "quality_summary"
    return "cleaning_policy"


def _quality_summary_answer(profiles: list[dict[str, Any]]) -> str:
    ranked = sorted(profiles, key=lambda profile: len(_profile_quality_messages(profile, limit=20)), reverse=True)
    issue_parts: list[str] = []
    for profile in ranked[:5]:
        messages = _profile_quality_messages(profile, limit=6)
        if messages:
            issue_parts.append(f"{profile['table']}：" + "；".join(messages[:4]))
        else:
            issue_parts.append(f"{profile['table']} 未发现明显通用质量问题")
    remaining = max(0, len(ranked) - 5)
    tail = f" 其余 {remaining} 张表的完整规则在结果表里。" if remaining else ""
    return (
        "数据质量问题不能简单说数据完全正常，也不能简单说不能用；当前通用扫描结果是："
        + " ".join(issue_parts)
        + f"。{tail}这些问题不代表数据不可用，但正式分析前需要确认缺失、重复、负值、极端值和日期解析问题的业务含义。"
    )


def _numeric_quality_answer(profiles: list[dict[str, Any]]) -> str:
    flags: list[dict[str, Any]] = []
    for profile in profiles:
        for item in profile.get("numeric_quality") or []:
            if int(item.get("negative_count") or 0) or int(item.get("zero_count") or 0) or int(item.get("high_outlier_count") or 0):
                flags.append({"table": profile["table"], **item})
    flags.sort(key=lambda item: int(item.get("negative_count") or 0) + int(item.get("zero_count") or 0) + int(item.get("high_outlier_count") or 0), reverse=True)
    if not flags:
        return "未发现明显数值异常。负值、0 值或极端值是否异常仍需要结合业务口径确认。"
    parts = [
        f"{item['table']}.{item['column']}：负值 {int(item.get('negative_count') or 0):,}，0 值 {int(item.get('zero_count') or 0):,}，高端异常 {int(item.get('high_outlier_count') or 0):,}"
        for item in flags[:10]
    ]
    tail = f" 还有 {len(flags) - 10} 个数值字段的统计放在结果表里。" if len(flags) > 10 else ""
    return "数值字段异常概览：" + "；".join(parts) + f"。{tail}这些只是统计信号，负值和极端值是否要清洗需要用户确认业务口径。"


def _temporal_quality_answer(profiles: list[dict[str, Any]]) -> str:
    items_with_table: list[dict[str, Any]] = []
    for profile in profiles:
        for item in profile.get("temporal_quality") or []:
            items_with_table.append({"table": profile["table"], **item})
    if not items_with_table:
        return "未识别到明显日期字段。日期范围是否异常需要结合业务周期确认。"
    items_with_table.sort(key=lambda item: int(item.get("invalid_count") or 0), reverse=True)
    parts = [
        f"{item['table']}.{item['column']} 范围 {item.get('min') or '未知'} 到 {item.get('max') or '未知'}，无法解析 {int(item.get('invalid_count') or 0):,}"
        for item in items_with_table[:10]
    ]
    tail = f" 还有 {len(items_with_table) - 10} 个日期字段在结果表里。" if len(items_with_table) > 10 else ""
    return "日期字段范围概览：" + "；".join(parts) + f"。{tail}日期范围是否异常需要结合业务周期确认。"


def _cleaning_impact_answer(profiles: list[dict[str, Any]], direct_action_rows: int, direct_action_rate: str) -> str:
    parts = [
        f"{profile['table']} 粗略影响行数合计 {int(profile.get('direct_action_rows') or 0):,}，约 {_safe_rate(int(profile.get('direct_action_rows') or 0), int(profile.get('row_count') or 0))}"
        for profile in profiles
    ]
    return (
        "这类追问应走 cleaning_simulation，只模拟清洗前后可能变化，不直接改原始数据。"
        + " ".join(parts)
        + f" 总计约 {direct_action_rows:,} 行（{direct_action_rate}）。这只是规则命中数求和，不能当作去重后的精确删除行数。"
        + "任何删除、填充或覆盖都需要用户确认，不能覆盖原始文件。"
    )


def _missing_strategy_answer(profiles: list[dict[str, Any]]) -> str:
    missing_rows = sum(
        int(rule["affected_rows"])
        for profile in profiles
        for rule in profile.get("rules", [])
        if str(rule.get("rule")) == "缺失值"
    )
    return (
        f"缺失策略建议先按模拟处理，不直接修改原始数据。当前检测到约 {missing_rows:,} 行存在至少一个缺失字段。"
        "删除：只适合问题强依赖该字段且缺失比例可接受时使用，并要报告影响行数和比例；"
        "填充：必须说明填充值、业务含义和可能引入的偏差；"
        "保留：适合不依赖该字段的分析，可加缺失标记继续计算。"
        "所有策略执行前都需要用户确认，不能静默填充、删除，不能覆盖原始文件。"
    )


def _missing_fields_answer(profiles: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for profile in profiles:
        missing = profile.get("missing_columns") or []
        if missing:
            parts.append(
                f"{profile['table']} 缺失最多字段："
                + "、".join(f"{item['column']} {int(item['missing_count']):,}（{item['missing_rate']}）" for item in missing[:8])
            )
        else:
            parts.append(f"{profile['table']} 未发现空值或常见缺失占位符")
    return "；".join(parts) + "。下一步可以按问题依赖程度决定保留、填充或删除，但不能静默改动原始数据。"


def _boundary_answer() -> str:
    return (
        "不会直接修改原始数据。VDS 只能先给清洗模拟、建议规则、影响行数和影响比例；"
        "真正删除、填充、覆盖或导出清洗后数据，必须等用户明确确认。"
    )


def _cleaning_result_rows(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for profile in profiles:
        rules = profile.get("rules") or []
        if not rules:
            rows.append(
                {
                    "表名": profile["table"],
                    "规则": "无需立即清洗",
                    "影响行数": 0,
                    "影响比例": "0.00%",
                    "建议": "保留原始数据，按具体问题继续分析。",
                }
            )
            continue
        for rule in rules:
            rows.append(
                {
                    "表名": profile["table"],
                    "规则": rule["rule"],
                    "影响行数": rule["affected_rows"],
                    "影响比例": rule["affected_rate"],
                    "建议": rule["suggestion"],
                }
            )
    return rows[:40]


def _cleaning_insight(
    profiles: list[dict[str, Any]],
    impacted_rows: int,
    impacted_rate: str,
    *,
    boundary: bool,
) -> InsightResult:
    if boundary:
        return InsightResult(confidence=1.0)
    rule_count = sum(len(profile.get("rules") or []) for profile in profiles)
    suggestions = [
        f"观察：检测到 {rule_count} 类清洗信号，粗略影响 {impacted_rows:,} 行（{impacted_rate}）；依据：重复、缺失、负值和 IQR 极端值扫描；建议：下一步先做清洗前后核心指标对比，再决定删除、填充或保留。"
    ]
    return InsightResult(
        summary="清洗策略还不应该直接执行，当前重点是先确认影响范围和口径变化。",
        suggestions=suggestions,
        business_suggestions=suggestions,
        caveats=["当前只做模拟，不修改原始文件；影响行数是规则并集估算。"],
        next_questions=["清洗前后核心指标会差多少？", "哪些字段适合填充而不是删除？"],
        evidence_rows=_cleaning_result_rows(profiles)[:5],
        confidence=0.84,
    )


def _profile_quality_messages(profile: dict[str, Any], *, limit: int) -> list[str]:
    messages: list[str] = []
    duplicate_count = int(profile.get("duplicate_count") or 0)
    if duplicate_count:
        messages.append(f"存在 {duplicate_count:,} 行完全重复记录")
    for item in profile.get("missing_columns") or []:
        messages.append(f"{item['column']} 缺失 {int(item['missing_count']):,} 行（{item['missing_rate']}）")
    for item in profile.get("numeric_quality") or []:
        negative_count = int(item.get("negative_count") or 0)
        high_count = int(item.get("high_outlier_count") or 0)
        if negative_count:
            messages.append(f"{item['column']} 存在 {negative_count:,} 个负值")
        if high_count:
            messages.append(f"{item['column']} 存在 {high_count:,} 个 IQR 高端异常值")
    for item in profile.get("temporal_quality") or []:
        invalid_count = int(item.get("invalid_count") or 0)
        if invalid_count:
            messages.append(f"{item['column']} 有 {invalid_count:,} 个无法解析的日期/时间值")
    return messages[:limit]


def _missing_columns(df: pd.DataFrame) -> list[dict[str, Any]]:
    total = int(len(df))
    if total <= 0:
        return []
    counts = df.isna().sum().sort_values(ascending=False)
    rows: list[dict[str, Any]] = []
    for column, count in counts.items():
        count = int(count)
        if count <= 0:
            continue
        rows.append({"column": str(column), "missing_count": count, "missing_rate": _safe_rate(count, total)})
    return rows[:10]


def _temporal_quality(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for column in [str(column) for column in df.columns]:
        if not _looks_like_date_column(column, df[column]):
            continue
        non_null = df[column].dropna()
        parsed = pd.to_datetime(non_null, errors="coerce")
        valid = parsed.dropna()
        rows.append(
            {
                "column": column,
                "invalid_count": int(parsed.isna().sum()),
                "min": str(valid.min()) if not valid.empty else None,
                "max": str(valid.max()) if not valid.empty else None,
            }
        )
    return rows[:10]


def _top_missing_columns(df: pd.DataFrame) -> str:
    counts = df.isna().sum().sort_values(ascending=False)
    pairs = [(str(column), int(count)) for column, count in counts.items() if int(count) > 0][:3]
    if not pairs:
        return ""
    return "主要缺失字段：" + "、".join(f"{column} {count:,} 行" for column, count in pairs) + "。"


def _high_outlier_mask(series: pd.Series) -> pd.Series:
    valid = series.dropna()
    if len(valid) < 5:
        return pd.Series(False, index=series.index)
    q1 = valid.quantile(0.25)
    q3 = valid.quantile(0.75)
    iqr = q3 - q1
    if not math.isfinite(float(iqr)) or iqr <= 0:
        return pd.Series(False, index=series.index)
    return series > q3 + 3 * iqr


def _looks_like_measure(column: str) -> bool:
    lowered = column.lower()
    blocked = ("id", "code", "编号", "编码", "year", "month", "date")
    if any(token in lowered or token in column for token in blocked):
        return False
    preferred = ("amount", "price", "quantity", "qty", "sales", "revenue", "金额", "价格", "数量", "销售", "收入", "利润")
    return any(token in lowered or token in column for token in preferred) or True


def _looks_like_identifier_column(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in ("id", "code", "invoice", "reference", "stockcode", "number")) or any(token in column for token in ("编号", "编码", "单号", "订单号", "客户号"))


def _looks_like_date_column(column: str, series: pd.Series) -> bool:
    lowered = column.lower()
    if any(token in lowered for token in ("date", "time", "month", "year", "day")) or any(token in column for token in ("日期", "时间", "月份", "年度", "年份")):
        return True
    return pd.api.types.is_datetime64_any_dtype(series)


def _safe_rate(count: int, total: int) -> str:
    if total <= 0:
        return "0.00%"
    return f"{count / total * 100:.2f}%"


def _is_mutation_boundary_question(question: str) -> bool:
    compact = str(question or "").replace(" ", "")
    return any(token in compact for token in ("直接修改原始数据", "修改原始数据", "覆盖原始", "覆盖源文件", "你会直接修改"))


def _is_missing_strategy_question(question: str) -> bool:
    compact = str(question or "").replace(" ", "")
    return "缺失" in compact and any(token in compact for token in ("删除", "填充", "保留", "策略", "风险"))


def _cleaning_artifact_code() -> str:
    return "\n".join(
        [
            "profile = []",
            "for table_name, df in tables.items():",
            "    duplicate_rows = int(df.duplicated().sum())",
            "    missing_rows = int(df.isna().any(axis=1).sum())",
            "    # Numeric rules are simulated only; source df is not mutated.",
            "    profile.append({'table': table_name, 'duplicates': duplicate_rows, 'missing_rows': missing_rows})",
        ]
    )
