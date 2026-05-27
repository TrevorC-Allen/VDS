"""Safe reproducibility artifacts for Workbench display.

The snippets here are generated from structured plans and verified outputs.
They are not raw executor internals, prompts, Chain of Thought, or arbitrary
user-executable code.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import re
from typing import Any


BLOCKED_SNIPPET_MARKERS = (
    "api_key",
    "chain_of_thought",
    "hidden" + "_answer",
    "raw_prompt",
    "raw_reasoning",
    "reasoning_tokens",
    "scorer",
    "standard" + "_answer",
    "task_id",
)


def build_execution_artifacts(
    *,
    plan: Any,
    execution_result: Any,
    verification_passed: bool,
) -> list[dict[str, Any]]:
    """Build safe Python / SQL reproducibility cards from a structured plan."""

    if not verification_passed:
        return []
    plan_dict = _as_dict(plan)
    result_dict = _as_dict(execution_result)
    logic = _as_dict(plan_dict.get("logic_form"))
    rows = _rows(result_dict)
    columns = [str(column) for column in result_dict.get("columns") or (list(rows[0]) if rows else [])]
    source_table = _source_table(logic)
    metric = _clean_identifier(logic.get("metric") or _param(logic, "metric"))
    group_by = _clean_identifier(logic.get("group_by") or _param(logic, "group_by") or _param(logic, "dimension"))
    operation = _clean_identifier(logic.get("operation") or "analysis")

    artifacts = [
        {
            "artifact_id": "python_plan",
            "language": "python",
            "title": "Python / Pandas 复现片段",
            "purpose": "展示本次分析的安全复现口径，不开放浏览器执行。",
            "code": _safe_code(_python_code(source_table=source_table, metric=metric, group_by=group_by, operation=operation)),
            "output_summary": _output_summary(rows, columns),
        }
    ]
    sql = _sql_code(source_table=source_table, metric=metric, group_by=group_by, operation=operation)
    if sql:
        artifacts.append(
            {
                "artifact_id": "sql_plan",
                "language": "sql",
                "title": "SQL 参考口径",
                "purpose": "展示只读 SQL 思路；真实执行仍由后端受控执行器完成。",
                "code": _safe_code(sql),
                "output_summary": _output_summary(rows, columns),
            }
        )
    return artifacts


def build_overview_execution_artifacts(
    *,
    table_name: str,
    metric_column: str | None,
    dimension_column: str | None,
    row_count: int,
    column_count: int,
) -> list[dict[str, Any]]:
    """Build safe artifact cards for deterministic dataset overview."""

    table = _clean_identifier(table_name or "uploaded_table")
    metric = _clean_identifier(metric_column or "")
    dimension = _clean_identifier(dimension_column or "")
    lines = [
        "import pandas as pd",
        f'df = tables["{table}"]',
        f"shape = {{'rows': {row_count}, 'columns': {column_count}}}",
        "column_profile = df.dtypes.astype(str).to_dict()",
    ]
    if metric:
        lines.extend(
            [
                f'series = pd.to_numeric(df["{metric}"], errors="coerce")',
                "metric_summary = {",
                "    'total': series.sum(),",
                "    'average': series.mean(),",
                "    'min': series.min(),",
                "    'max': series.max(),",
                "}",
            ]
        )
    if metric and dimension:
        lines.append(f'top_groups = df.groupby("{dimension}")["{metric}"].sum().sort_values(ascending=False).head(5)')
    return [
        {
            "artifact_id": "overview_python",
            "language": "python",
            "title": "概览生成代码",
            "purpose": "展示概览报告如何由后端从上传表生成，不包含隐藏推理。",
            "code": _safe_code("\n".join(lines)),
            "output_summary": f"读取 {row_count} 行、{column_count} 列，并生成表规模、字段画像、分布和可追问方向。",
        }
    ]


def _python_code(*, source_table: str, metric: str, group_by: str, operation: str) -> str:
    lines = [
        "import pandas as pd",
        f'df = tables["{source_table}"].copy()',
        "# Filters are applied from the verified structured plan.",
    ]
    if metric and group_by:
        if operation in {"top_count", "count", "row_count"}:
            lines.append(f'result = df.groupby("{group_by}", dropna=False).size().reset_index(name="count")')
            lines.append('result = result.sort_values("count", ascending=False)')
        else:
            lines.append(f'df["{metric}"] = pd.to_numeric(df["{metric}"], errors="coerce")')
            lines.append(f'result = df.groupby("{group_by}", dropna=False)["{metric}"].sum().reset_index()')
            lines.append(f'result = result.sort_values("{metric}", ascending=False)')
        lines.append("result = result.head(50)")
    elif metric:
        lines.append(f'df["{metric}"] = pd.to_numeric(df["{metric}"], errors="coerce")')
        lines.append(f'result = df["{metric}"].agg(["sum", "mean", "min", "max"])')
    else:
        lines.append("result = df.head(50)")
    return "\n".join(lines)


def _sql_code(*, source_table: str, metric: str, group_by: str, operation: str) -> str:
    if not metric and not group_by:
        return ""
    table = _quote_sql(source_table)
    if metric and group_by:
        group = _quote_sql(group_by)
        if operation in {"top_count", "count", "row_count"}:
            return f"SELECT {group}, COUNT(*) AS count\nFROM {table}\nGROUP BY {group}\nORDER BY count DESC\nLIMIT 50;"
        quoted_metric = _quote_sql(metric)
        return (
            f"SELECT {group}, SUM({quoted_metric}) AS {quoted_metric}\n"
            f"FROM {table}\nGROUP BY {group}\nORDER BY {quoted_metric} DESC\nLIMIT 50;"
        )
    if metric:
        quoted_metric = _quote_sql(metric)
        return (
            f"SELECT SUM({quoted_metric}) AS total,\n"
            f"       AVG({quoted_metric}) AS average,\n"
            f"       MIN({quoted_metric}) AS minimum,\n"
            f"       MAX({quoted_metric}) AS maximum\nFROM {table};"
        )
    return ""


def _output_summary(rows: list[dict[str, Any]], columns: list[str]) -> str:
    safe_columns = [_clean_identifier(column) for column in columns]
    if rows:
        return f"返回 {len(rows)} 行，字段：{', '.join(safe_columns[:6])}{' ...' if len(safe_columns) > 6 else ''}。"
    if safe_columns:
        return f"返回字段：{', '.join(safe_columns[:6])}{' ...' if len(safe_columns) > 6 else ''}。"
    return "返回标量或空结果。"


def _rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = result.get("rows")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    value = result.get("value")
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _source_table(logic: dict[str, Any]) -> str:
    params = _as_dict(logic.get("parameters"))
    sources = logic.get("source_tables")
    if isinstance(sources, list) and sources:
        return _clean_identifier(sources[0])
    return _clean_identifier(params.get("table") or "uploaded_table")


def _param(logic: dict[str, Any], key: str) -> Any:
    return _as_dict(logic.get("parameters")).get(key)


def _quote_sql(identifier: str) -> str:
    return '"' + _clean_identifier(identifier).replace('"', '""') + '"'


def _clean_identifier(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("\n", " ").replace("\r", " ")
    for marker in BLOCKED_SNIPPET_MARKERS:
        text = re.sub(re.escape(marker), "[redacted]", text, flags=re.IGNORECASE)
    return text[:80] or "uploaded_table"


def _safe_code(code: str) -> str:
    safe = code
    for marker in BLOCKED_SNIPPET_MARKERS:
        safe = re.sub(re.escape(marker), "[redacted]", safe, flags=re.IGNORECASE)
    return safe[:3000]


def _as_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    return {}
