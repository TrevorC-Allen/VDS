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
    impacted_rate = _safe_rate(impacted_rows, total_rows)
    boundary = _is_mutation_boundary_question(question)
    missing_strategy = _is_missing_strategy_question(question)
    if boundary:
        answer = _boundary_answer()
        answer_type = "chat"
        execution_mode = "chat"
    elif missing_strategy:
        answer = _missing_strategy_answer(profiles)
        answer_type = "cleaning_simulation"
        execution_mode = "cleaning_simulation"
    else:
        answer = _cleaning_policy_answer(profiles, impacted_rows, impacted_rate)
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
                "output_summary": f"估算影响 {impacted_rows:,} 行，占 {impacted_rate}。",
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
                    "evidence": [f"表数量：{len(profiles)}", f"估算影响：{impacted_rows:,} 行（{impacted_rate}）"],
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
            },
        },
    }


def _table_cleaning_profile(table_name: str, df: pd.DataFrame) -> dict[str, Any]:
    row_count = int(len(df))
    duplicate_count = int(df.duplicated().sum()) if row_count else 0
    impacted_mask = pd.Series(False, index=df.index)
    rules: list[dict[str, Any]] = []
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
        numeric = pd.to_numeric(df[column], errors="coerce")
        valid = numeric.dropna()
        if len(valid) < max(3, min(20, row_count // 20 if row_count else 3)):
            continue
        negative_mask = numeric < 0
        negative_count = int(negative_mask.sum())
        if negative_count and _looks_like_measure(column):
            impacted_mask = impacted_mask | negative_mask.fillna(False)
            rules.append(_rule(f"{column} 负值", negative_count, row_count, "需确认是否退款、冲销或录入口径。"))
        high_mask = _high_outlier_mask(numeric)
        high_count = int(high_mask.sum())
        if high_count and _looks_like_measure(column):
            impacted_mask = impacted_mask | high_mask.fillna(False)
            rules.append(_rule(f"{column} 极端高值", high_count, row_count, "建议 winsorize、单独审查或按业务规则保留。"))
    impacted_rows = int(impacted_mask.sum()) if row_count else 0
    return {
        "table": table_name,
        "row_count": row_count,
        "impacted_rows": impacted_rows,
        "impacted_rate": _safe_rate(impacted_rows, row_count),
        "rules": rules[:10],
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
        f"粗略估算，至少一条规则会影响 {impacted_rows:,} 行（{impacted_rate}）。这只是模拟口径，不代表应该直接删除这些行。",
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
        "不能静默填充、删除或覆盖原始文件。"
    )


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
        f"观察：检测到 {rule_count} 类清洗信号；依据：重复、缺失、负值和 IQR 极端值扫描；建议：先按模拟报告确认规则。",
        f"观察：粗略影响 {impacted_rows:,} 行（{impacted_rate}）；依据：各表规则命中行并集估算；建议：正式清洗前确认删除、填充或保留策略。",
        "观察：清洗动作可能改变核心指标；依据：清洗会改变参与汇总的行集合；建议：输出清洗前后对比后再用于决策。",
    ]
    return InsightResult(
        summary="已生成清洗策略模拟，重点是影响范围和用户确认边界。",
        suggestions=suggestions,
        business_suggestions=suggestions,
        caveats=["当前只做模拟，不修改原始文件；影响行数是规则并集估算。"],
        evidence_rows=_cleaning_result_rows(profiles)[:5],
        confidence=0.84,
    )


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
    return series > q3 + 1.5 * iqr


def _looks_like_measure(column: str) -> bool:
    lowered = column.lower()
    blocked = ("id", "code", "编号", "编码", "year", "month", "date")
    if any(token in lowered or token in column for token in blocked):
        return False
    preferred = ("amount", "price", "quantity", "qty", "sales", "revenue", "金额", "价格", "数量", "销售", "收入", "利润")
    return any(token in lowered or token in column for token in preferred) or True


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
