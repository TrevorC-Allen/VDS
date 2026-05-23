"""Deterministic insight generator for trusted execution results."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from data_agent_core.contracts.analysis_contracts import AnalysisPlan
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.response_contracts import InsightResult


def generate_insight(
    *,
    question: str,
    plan: AnalysisPlan | dict[str, Any] | None = None,
    execution_result: ExecutionResult | dict[str, Any],
    verification_passed: bool,
    quality_report: dict[str, Any] | None = None,
) -> InsightResult:
    """Generate cautious, evidence-backed insight from verified results."""

    if not verification_passed:
        return InsightResult(
            caveats=["校验未通过，因此不生成业务洞察或建议。"],
            confidence=0.0,
        )

    result = _as_dict(execution_result)
    rows, columns = _rows_and_columns(result)
    key_numbers = _key_numbers(result, rows)
    anomaly_findings = _anomaly_findings(rows, columns)
    volatility_findings = _volatility_findings(rows, columns)
    caveats = _quality_caveats(quality_report)
    suggestions = _suggestions(anomaly_findings, volatility_findings, quality_report)
    summary = _summary(question, key_numbers, rows)
    return InsightResult(
        summary=summary,
        key_numbers=key_numbers,
        anomaly_findings=anomaly_findings,
        volatility_findings=volatility_findings,
        suggestions=suggestions,
        business_suggestions=suggestions,
        caveats=caveats,
        next_questions=_next_questions(plan, rows),
        evidence_rows=rows[:5],
        confidence=0.82 if rows else 0.72,
    )


def _rows_and_columns(result: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    rows = list(result.get("rows") or [])
    columns = list(result.get("columns") or [])
    value = result.get("value")
    if not rows and isinstance(value, list) and all(isinstance(row, dict) for row in value):
        rows = list(value)
    if not rows and isinstance(value, dict):
        rows = [value]
    if not columns and rows:
        columns = [str(column) for column in rows[0]]
    return rows, columns


def _key_numbers(result: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    key_numbers: dict[str, Any] = {"row_count": len(rows)}
    value = result.get("value")
    if isinstance(value, (int, float, str)):
        key_numbers["answer_value"] = value
    if rows:
        numeric_columns = _numeric_columns(rows)
        for column in numeric_columns[:3]:
            values = _numeric_values(rows, column)
            if values:
                key_numbers[column] = {
                    "min": min(values),
                    "max": max(values),
                    "sum": sum(values),
                    "avg": sum(values) / len(values),
                }
    return key_numbers


def _summary(question: str, key_numbers: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    if rows:
        return f"Verified result: 本次结果已通过校验，返回 {len(rows)} 行可展示数据；可结合图表查看主要排序、趋势或构成。"
    if key_numbers.get("answer_value") is not None:
        return f"Verified result: 本次结果已通过校验，核心数值为 {key_numbers['answer_value']}。"
    return f"Verified result: 本次结果已通过校验，可用于回答：{question}"


def _anomaly_findings(rows: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for column in _numeric_columns(rows, columns):
        values = _numeric_values(rows, column)
        if len(values) < 5:
            continue
        q1 = _quantile(values, 0.25)
        q3 = _quantile(values, 0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        outliers = [
            row
            for row in rows
            if _to_float(row.get(column)) is not None
            and (_to_float(row.get(column)) < lower or _to_float(row.get(column)) > upper)
        ]
        if outliers:
            findings.append(
                {
                    "type": "numeric_outlier",
                    "metric": column,
                    "count": len(outliers),
                    "bounds": {"lower": lower, "upper": upper},
                    "message": f"{column} 存在 {len(outliers)} 个统计离群点，建议优先复核。",
                    "evidence_rows": outliers[:3],
                }
            )
    return findings


def _volatility_findings(rows: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    time_column = _time_column(columns)
    if not time_column:
        return []
    numeric_columns = [column for column in _numeric_columns(rows, columns) if column != time_column]
    findings: list[dict[str, Any]] = []
    for column in numeric_columns[:2]:
        ordered = sorted(rows, key=lambda row: str(row.get(time_column) or ""))
        changes: list[dict[str, Any]] = []
        previous = None
        for row in ordered:
            current = _to_float(row.get(column))
            if current is None:
                continue
            if previous not in {None, 0}:
                pct = (current - previous) / abs(previous) * 100
                if abs(pct) >= 30:
                    changes.append({"period": row.get(time_column), "metric": column, "change_pct": pct, "value": current})
            previous = current
        if changes:
            findings.append(
                {
                    "type": "period_volatility",
                    "metric": column,
                    "count": len(changes),
                    "message": f"{column} 存在 {len(changes)} 次超过 30% 的阶段波动。",
                    "evidence_rows": changes[:3],
                }
            )
    return findings


def _quality_caveats(quality_report: dict[str, Any] | None) -> list[str]:
    if not isinstance(quality_report, dict):
        return []
    issue_count = int(quality_report.get("issue_count") or 0)
    if issue_count <= 0:
        return []
    return [f"数据质量扫描发现 {issue_count} 个潜在问题，分析结论需要结合缺失、重复或异常值一起判断。"]


def _suggestions(
    anomaly_findings: list[dict[str, Any]],
    volatility_findings: list[dict[str, Any]],
    quality_report: dict[str, Any] | None,
) -> list[str]:
    suggestions: list[str] = []
    if anomaly_findings:
        suggestions.append("优先复核离群点对应的原始记录，确认是真实业务极端值还是录入/口径问题。")
    if volatility_findings:
        suggestions.append("对波动较大的周期补充拆分维度，查看是否由单个客户、城市、产品或渠道驱动。")
    if isinstance(quality_report, dict) and int(quality_report.get("issue_count") or 0) > 0:
        suggestions.append("在做正式决策前先处理高严重度数据质量问题，保留清洗前后结果对比。")
    if not suggestions:
        suggestions.append("当前结果未显示明显异常，可继续按时间、区域或产品维度做下钻分析。")
    return suggestions


def _next_questions(plan: AnalysisPlan | dict[str, Any] | None, rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["是否需要按维度展开明细？"]
    return ["异常值来自哪些明细记录？", "这个结果按时间趋势是否稳定？", "是否需要对 Top 结果继续下钻？"]


def _numeric_columns(rows: list[dict[str, Any]], columns: list[str] | None = None) -> list[str]:
    if not rows:
        return []
    candidates = columns or list(rows[0])
    return [column for column in candidates if len(_numeric_values(rows, column)) >= max(1, min(3, len(rows)))]


def _numeric_values(rows: list[dict[str, Any]], column: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = _to_float(row.get(column))
        if value is not None:
            values.append(value)
    return values


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _time_column(columns: list[str]) -> str | None:
    for column in columns:
        lowered = column.lower()
        if any(token in lowered for token in ("date", "day", "month", "year", "week", "time", "日期", "时间", "月份", "年份", "周")):
            return column
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    return {}
