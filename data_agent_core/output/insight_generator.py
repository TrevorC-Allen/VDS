"""Deterministic insight generator for trusted execution results."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import math
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
    suggestions = _suggestions(anomaly_findings, volatility_findings, quality_report, rows)
    summary = _summary(question, key_numbers, rows)
    return InsightResult(
        summary=summary,
        key_numbers=key_numbers,
        anomaly_findings=anomaly_findings,
        volatility_findings=volatility_findings,
        suggestions=suggestions,
        business_suggestions=suggestions,
        caveats=caveats,
        next_questions=_next_questions(question, plan, rows),
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
    multi_series = _multi_series_trend_summary(rows)
    if multi_series:
        return multi_series
    if rows:
        return f"结果已通过校验，当前最值得看的是这 {len(rows)} 条结果背后的异常、波动或维度差异。"
    if key_numbers.get("answer_value") is not None:
        return f"本次结果已通过校验，核心数值为 {key_numbers['answer_value']}。"
    return f"本次结果已通过校验，可用于回答：{question}"


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
                    "message": f"观察：{column} 存在 {len(outliers)} 个统计离群点；依据：IQR 边界 {lower:.2f} ~ {upper:.2f}；建议：优先复核这些明细是否为真实业务高点或录入口径问题。",
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
                    "message": f"观察：{column} 存在 {len(changes)} 次超过 30% 的阶段波动；依据：相邻周期变化率；建议：继续按客户、城市、产品或渠道拆分驱动因素。",
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
    rows: list[dict[str, Any]],
) -> list[str]:
    if anomaly_findings:
        first = anomaly_findings[0]
        metric = str(first.get("metric") or "核心指标")
        count = int(first.get("count") or 0)
        return [
            f"观察：{metric} 出现 {count} 个明显离群点；依据：已验证结果的 IQR 边界；建议：下一步先复核这些异常高/低点是否为真实业务事件，再按客户、城市、产品或渠道拆分来源。"
        ]
    if volatility_findings:
        first = volatility_findings[0]
        metric = str(first.get("metric") or "核心指标")
        count = int(first.get("count") or 0)
        return [
            f"观察：{metric} 有 {count} 次较大阶段波动；依据：相邻周期变化率；建议：下一步按同一周期口径拆到区域、客户或产品，先找出波动最大的贡献项。"
        ]
    if isinstance(quality_report, dict) and int(quality_report.get("issue_count") or 0) > 0:
        issue_count = int(quality_report.get("issue_count") or 0)
        return [
            f"观察：数据质量扫描发现 {issue_count} 个潜在问题；依据：缺失、重复和异常值扫描；建议：下一步先做清洗前后核心指标对比，再决定是否删除、填充或保留。"
        ]
    if rows:
        return [
            "观察：当前结果没有触发明显异常信号；依据：已验证结果未出现显著离群、阶段波动或质量告警；建议：下一步选一个最关键维度做趋势或 Top/Bottom 对比。"
        ]
    return ["建议：先补充具体指标、时间范围和分组维度，再继续做可验证分析。"]


def _next_questions(question: str, plan: AnalysisPlan | dict[str, Any] | None, rows: list[dict[str, Any]]) -> list[str]:
    logic = _logic_form_dict(plan)
    parameters = logic.get("parameters") if isinstance(logic.get("parameters"), dict) else {}
    time_window = logic.get("time_window") if isinstance(logic.get("time_window"), dict) else {}
    columns = [str(column) for column in (rows[0].keys() if rows else [])]
    metric = _first_text(logic.get("metric"), parameters.get("metric"), _first_numeric_column(rows, columns), "核心指标")
    dimension = _first_text(
        logic.get("group_by"),
        parameters.get("dimension"),
        parameters.get("group_by"),
        _first_dimension_column(rows, columns),
        "关键维度",
    )
    time_column = _first_text(_time_column(columns), parameters.get("time_column"), time_window.get("column"), "时间")
    has_time_column = time_column != "时间"
    operation = str(logic.get("operation") or logic.get("task_type") or "").lower()
    question_text = str(question or "").lower().replace(" ", "")

    candidates: list[str] = []
    if _looks_like_trend(operation, question_text):
        candidates.extend(
            [
                f"把{metric}的峰值、低点和最大波动期标出来？",
                f"按{dimension}拆分同一趋势，看看是谁拉动变化？",
                f"检查最近一期{time_column}是否完整、是否影响趋势判断？",
            ]
        )
    elif _looks_like_ranking(operation, question_text):
        candidates.extend(
            [
                f"比较 Top 结果之间的{metric}差距有多大？",
                f"把排名靠前的{dimension}按{time_column}继续下钻？" if has_time_column else f"把排名靠前的{dimension}按其他维度继续下钻？",
                f"看低排名对象是否受缺失值、异常值或样本量影响？",
            ]
        )
    elif _looks_like_share_or_rate(operation, question_text):
        candidates.extend(
            [
                f"按{dimension}拆分这个占比，找出贡献最大的分组？",
                f"看这个比例在{time_column}上是否稳定？",
                "检查分子、分母口径是否有过滤条件或缺失值影响？",
            ]
        )
    elif _looks_like_quality(question_text):
        candidates.extend(
            [
                f"列出影响{metric}的异常值、缺失值和重复记录？",
                f"模拟清洗前后{metric}会差多少？",
                f"按{dimension}看哪些分组受数据质量问题影响最大？",
            ]
        )
    elif rows:
        candidates.extend(
            [
                f"按{dimension}继续拆解{metric}的构成和集中度？",
                f"按{time_column}看{metric}的趋势和波动？",
                f"检查{metric}是否存在异常值或质量问题影响结论？",
            ]
        )
    else:
        candidates.extend(
            [
                f"补充{metric}、{dimension}或{time_column}后重新计算？",
                "需要先确认用哪张表和哪些字段作为口径？",
            ]
        )
    return _dedupe_questions(candidates)[:3]


def _logic_form_dict(plan: AnalysisPlan | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(plan, AnalysisPlan):
        return _as_dict(plan.logic_form)
    if isinstance(plan, dict):
        logic = plan.get("logic_form")
        if isinstance(logic, dict):
            return logic
        return plan
    return {}


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _first_numeric_column(rows: list[dict[str, Any]], columns: list[str]) -> str:
    for column in _numeric_columns(rows, columns):
        return column
    return ""


def _first_dimension_column(rows: list[dict[str, Any]], columns: list[str]) -> str:
    numeric = set(_numeric_columns(rows, columns))
    for column in columns:
        if column not in numeric and column != _time_column(columns):
            return column
    return ""


def _looks_like_trend(operation: str, question_text: str) -> bool:
    return "trend" in operation or any(token in question_text for token in ("趋势", "波动", "环比", "同比", "增长", "下降", "trend", "mom", "yoy"))


def _looks_like_ranking(operation: str, question_text: str) -> bool:
    return any(token in operation for token in ("rank", "top")) or any(
        token in question_text for token in ("排名", "top", "最高", "最低", "最大", "最小", "第一", "前")
    )


def _looks_like_share_or_rate(operation: str, question_text: str) -> bool:
    return any(token in operation for token in ("percent", "percentage", "rate", "ratio", "share")) or any(
        token in question_text for token in ("占比", "比例", "率", "percent", "rate", "ratio", "share")
    )


def _looks_like_quality(question_text: str) -> bool:
    return any(token in question_text for token in ("缺失", "重复", "异常", "离群", "质量", "清洗", "填充", "删除"))


def _dedupe_questions(candidates: list[str]) -> list[str]:
    result: list[str] = []
    for item in candidates:
        text = str(item or "").strip().rstrip("。；;")
        if not text:
            continue
        if not text.endswith(("?", "？")):
            text += "？"
        if text not in result:
            result.append(text)
    return result


def _multi_series_trend_summary(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    columns = [str(column) for column in rows[0].keys()]
    time_column = _time_column(columns)
    if not time_column:
        return ""
    series_columns = [column for column in columns if column != time_column and len(_numeric_values(rows, column)) >= 2 and not _looks_like_identifier(column)]
    if len(series_columns) < 2:
        return ""
    profiles = []
    for column in series_columns:
        values = [_to_float(row.get(column)) for row in rows]
        numeric_values = [value for value in values if value is not None]
        if len(numeric_values) < 2:
            continue
        peak_index, peak_value = max(((index, value) for index, value in enumerate(values) if value is not None), key=lambda item: item[1])
        leader_count = 0
        for row in rows:
            valid_values = [_to_float(row.get(name)) for name in series_columns]
            current = _to_float(row.get(column))
            if current is not None and any(value is not None for value in valid_values):
                best = max(value for value in valid_values if value is not None)
                if math.isclose(current, best, rel_tol=1e-9, abs_tol=1e-9):
                    leader_count += 1
        last_change = None
        if values[-2] is not None and values[-1] is not None:
            last_change = values[-1] - values[-2]
        profiles.append(
            {
                "column": column,
                "total": sum(numeric_values),
                "leader_count": leader_count,
                "peak_index": peak_index,
                "peak_value": peak_value,
                "last_change": last_change,
            }
        )
    if len(profiles) < 2:
        return ""
    leader = max(profiles, key=lambda item: item["total"])
    leader_text = f"{leader['column']} 持续领先" if leader["leader_count"] == len(rows) else f"{leader['column']} 整体领先"
    parts = [leader_text]
    growth_candidates = [item for item in profiles if item.get("last_change") not in {None, 0}]
    if growth_candidates:
        growth = max(growth_candidates, key=lambda item: float(item.get("last_change") or float("-inf")))
        if float(growth.get("last_change") or 0.0) > 0:
            parts.append(f"{growth['column']} 在 {rows[-1].get(time_column)} 跃升明显")
    peak_candidates = [item for item in profiles if item["column"] != leader["column"]]
    if peak_candidates:
        peak = max(peak_candidates, key=lambda item: item["peak_value"])
        parts.append(f"{peak['column']} 在 {rows[int(peak['peak_index'])].get(time_column)} 达到阶段峰值")
    return "；".join(parts[:3]) + "。"


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


def _looks_like_identifier(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in ("id", "code", "编号", "编码", "序号", "订单号"))


def _as_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    return {}
