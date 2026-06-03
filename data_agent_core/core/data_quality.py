"""Dataset quality scanning for uploaded tables.

The scanner is deterministic and trace-safe. It reports likely data problems
and cleaning suggestions, but it never mutates user data.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from data_agent_core.contracts.response_contracts import DataQualityIssue, DataQualityReport


def build_data_quality_report(
    tables: dict[str, pd.DataFrame],
    *,
    generated_from: str = "dataframe_scan",
) -> DataQualityReport:
    """Scan tables and return a stable quality report."""

    issues: list[DataQualityIssue] = []
    field_level_table: list[dict[str, Any]] = []
    duplicate_rules: list[dict[str, Any]] = []
    outlier_rules: list[dict[str, Any]] = []
    type_parse_failure_rules: list[dict[str, Any]] = []
    for table_name, df in tables.items():
        issues.extend(_table_issues(table_name, df))
        duplicate_rules.append(_duplicate_rule(table_name, df))
        for column_name in df.columns:
            column = str(column_name)
            column_quality = _column_quality_row(table_name, column, df[column])
            field_level_table.append(column_quality)
            outlier_rules.append(
                {
                    "table": table_name,
                    "field": column,
                    "rule": "numeric IQR rule",
                    "affected_rows": column_quality["异常值数"],
                    "affected_rate": column_quality["异常值率"],
                }
            )
            type_parse_failure_rules.append(
                {
                    "table": table_name,
                    "field": column,
                    "rule": column_quality["类型检测规则"],
                    "affected_rows": column_quality["类型异常数"],
                    "affected_rate": column_quality["类型异常率"],
                }
            )
            issues.extend(_column_issues(table_name, column, df[column]))

    issues = _dedupe_issues(issues)
    score = _quality_score(issues)
    summary = _summary(issues, len(tables))
    return DataQualityReport(
        status="scanned",
        quality_score=score,
        scanned_tables=list(tables.keys()),
        issue_count=len(issues),
        summary=summary,
        issues=issues,
        field_level_table=field_level_table,
        duplicate_rules=duplicate_rules,
        outlier_rules=outlier_rules,
        type_parse_failure_rules=type_parse_failure_rules,
        generated_from=generated_from,
    )


def report_to_dict(report: DataQualityReport | dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a JSON-ready report dict."""

    if report is None:
        return None
    if isinstance(report, dict):
        return report
    return asdict(report)


def _table_issues(table_name: str, df: pd.DataFrame) -> list[DataQualityIssue]:
    issues: list[DataQualityIssue] = []
    if df.empty:
        issues.append(
            DataQualityIssue(
                severity="high",
                issue_type="empty_table",
                table_name=table_name,
                message=f"表 {table_name} 没有可分析的数据行。",
                affected_rows=0,
                suggested_cleaning_actions=["确认文件是否选错 sheet 或表头行。"],
            )
        )
        return issues

    duplicate_count = int(df.duplicated().sum())
    if duplicate_count:
        issues.append(
            DataQualityIssue(
                severity="medium" if duplicate_count / len(df) < 0.2 else "high",
                issue_type="duplicate_rows",
                table_name=table_name,
                message=f"表 {table_name} 存在 {duplicate_count} 行重复记录。",
                affected_rows=duplicate_count,
                sample_values=_sample_rows(df[df.duplicated(keep=False)]),
                suggested_cleaning_actions=["确认重复记录是否代表真实多次发生；如不是，按业务主键去重。"],
                evidence={"duplicate_rate": duplicate_count / len(df)},
            )
        )

    unnamed = [str(column) for column in df.columns if str(column).startswith("Unnamed")]
    if unnamed:
        issues.append(
            DataQualityIssue(
                severity="medium",
                issue_type="uncertain_header",
                table_name=table_name,
                message=f"表 {table_name} 存在疑似未识别表头字段：{', '.join(unnamed)}。",
                sample_values=unnamed[:5],
                suggested_cleaning_actions=["检查 Excel/CSV 表头行，必要时重新选择正确表头。"],
            )
        )
    return issues


def _duplicate_rule(table_name: str, df: pd.DataFrame) -> dict[str, Any]:
    row_count = len(df)
    full_row_duplicate_count = int(df.duplicated().sum()) if row_count else 0
    key_duplicate_counts: dict[str, int] = {}
    for column_name in df.columns:
        column = str(column_name)
        if not _looks_identifier(column):
            continue
        series = df[column_name]
        non_null = series[~_missing_mask(series)]
        key_duplicate_counts[column] = int(non_null.duplicated(keep=False).sum())
    return {
        "table": table_name,
        "rule": "full_row_duplicate_count",
        "full_row_duplicate_count": full_row_duplicate_count,
        "full_row_duplicate_rate": _safe_rate(full_row_duplicate_count, row_count),
        "key_duplicate_count": key_duplicate_counts,
        "row_count": row_count,
    }


def _column_quality_row(table_name: str, column_name: str, series: pd.Series) -> dict[str, Any]:
    row_count = len(series)
    missing_mask = _missing_mask(series)
    missing_count = int(missing_mask.sum())
    non_null = series[~missing_mask]
    type_failure_count, type_rule = _type_parse_failure_count(column_name, non_null)
    outlier_count = _numeric_iqr_outlier_count(column_name, non_null)
    return {
        "表": table_name,
        "字段": column_name,
        "类型": _column_type_label(series),
        "缺失数": missing_count,
        "缺失率": _format_rate(_safe_rate(missing_count, row_count)),
        "类型异常数": type_failure_count,
        "类型异常率": _format_rate(_safe_rate(type_failure_count, row_count)),
        "异常值数": outlier_count,
        "异常值率": _format_rate(_safe_rate(outlier_count, row_count)),
        "检测规则": "missing placeholder scan; non-null type parse failure; numeric IQR rule",
        "类型检测规则": type_rule,
        "备注": "按当前规则未发现字段级问题" if missing_count + type_failure_count + outlier_count == 0 else "存在字段级质量信号，需结合业务口径确认",
        "row_count": row_count,
        "affected_rows": missing_count + type_failure_count + outlier_count,
        "affected_rate": _format_rate(_safe_rate(missing_count + type_failure_count + outlier_count, row_count)),
    }


def _column_type_label(series: pd.Series) -> str:
    non_null = series.dropna()
    if non_null.empty:
        return "unknown"
    if pd.api.types.is_bool_dtype(non_null):
        return "boolean"
    if pd.api.types.is_numeric_dtype(non_null):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(non_null):
        return "datetime"
    numeric = pd.to_numeric(non_null, errors="coerce")
    if float(numeric.notna().mean()) >= 0.95:
        return "numeric"
    parsed_dates = pd.to_datetime(non_null, errors="coerce")
    if float(parsed_dates.notna().mean()) >= 0.95 and _looks_date_name(str(series.name or "")):
        return "datetime"
    return "text"


def _type_parse_failure_count(column_name: str, non_null: pd.Series) -> tuple[int, str]:
    if non_null.empty:
        return 0, "non-null type parse failure"
    boolean_like = pd.api.types.is_bool_dtype(non_null)
    if _looks_date_name(column_name):
        parsed = pd.to_datetime(non_null, errors="coerce")
        return int(parsed.isna().sum()), "non-null date parse failure"
    numeric = pd.to_numeric(non_null, errors="coerce")
    numeric_rate = float(numeric.notna().mean())
    if not boolean_like and (_looks_metric_name(column_name) or numeric_rate >= 0.95):
        return int(numeric.isna().sum()), "non-null numeric parse failure"
    return 0, "non-null type parse failure"


def _numeric_iqr_outlier_count(column_name: str, non_null: pd.Series) -> int:
    if non_null.empty:
        return 0
    boolean_like = pd.api.types.is_bool_dtype(non_null)
    numeric = pd.to_numeric(non_null, errors="coerce")
    if boolean_like or numeric.notna().sum() < 8 or float(numeric.notna().mean()) < 0.95:
        return 0
    valid = numeric.dropna()
    q1 = float(valid.quantile(0.25))
    q3 = float(valid.quantile(0.75))
    iqr = q3 - q1
    if iqr == 0:
        return 0
    lower = q1 - 3 * iqr
    upper = q3 + 3 * iqr
    return int(((numeric < lower) | (numeric > upper)).sum())


def _column_issues(table_name: str, column_name: str, series: pd.Series) -> list[DataQualityIssue]:
    issues: list[DataQualityIssue] = []
    row_count = len(series)
    if row_count == 0:
        return issues

    missing_mask = _missing_mask(series)
    missing_count = int(missing_mask.sum())
    missing_rate = missing_count / row_count
    if missing_rate > 0:
        severity = "low" if missing_rate < 0.05 else "medium" if missing_rate < 0.3 else "high"
        issues.append(
            DataQualityIssue(
                severity=severity,
                issue_type="missing_values",
                table_name=table_name,
                column_name=column_name,
                message=f"{table_name}.{column_name} 缺失率为 {missing_rate:.2%}。",
                affected_rows=missing_count,
                sample_values=_sample_values(series[missing_mask]),
                suggested_cleaning_actions=["确认缺失是否有业务含义；必要时补全、删除或单独标记缺失。"],
                evidence={"missing_rate": missing_rate, "missing_count": missing_count},
            )
        )

    non_null = series[~missing_mask]
    unique_count = int(non_null.nunique(dropna=True))
    if len(non_null) > 0 and unique_count <= 1 and row_count >= 2:
        issues.append(
            DataQualityIssue(
                severity="low",
                issue_type="constant_column",
                table_name=table_name,
                column_name=column_name,
                message=f"{table_name}.{column_name} 几乎没有变化，分析区分度较低。",
                sample_values=_sample_values(non_null),
                suggested_cleaning_actions=["确认该字段是否为常量配置字段；如无分析价值，可从建模特征中排除。"],
                evidence={"unique_count": unique_count},
            )
        )

    boolean_like = pd.api.types.is_bool_dtype(non_null)
    numeric = pd.to_numeric(non_null, errors="coerce")
    numeric_rate = 0.0 if len(non_null) == 0 else float(numeric.notna().mean())
    if not boolean_like and 0.0 < numeric_rate < 0.95 and _looks_metric_name(column_name):
        issues.append(
            DataQualityIssue(
                severity="medium",
                issue_type="mixed_numeric_type",
                table_name=table_name,
                column_name=column_name,
                message=f"{table_name}.{column_name} 疑似数值字段，但部分值无法转成数字。",
                affected_rows=int(numeric.isna().sum()),
                sample_values=_sample_values(non_null[numeric.isna()]),
                suggested_cleaning_actions=["统一数字格式，去除单位、逗号、异常文本或占位符。"],
                evidence={"numeric_parse_rate": numeric_rate},
            )
        )

    if not boolean_like and numeric_rate >= 0.95 and numeric.notna().sum() >= 8:
        issues.extend(_numeric_outlier_issues(table_name, column_name, numeric))
        negative_count = int((numeric < 0).sum())
        if negative_count and _looks_non_negative_metric(column_name):
            issues.append(
                DataQualityIssue(
                    severity="medium",
                    issue_type="suspicious_negative_values",
                    table_name=table_name,
                    column_name=column_name,
                    message=f"{table_name}.{column_name} 存在 {negative_count} 个可疑负值。",
                    affected_rows=negative_count,
                    sample_values=_sample_values(non_null[numeric < 0]),
                    suggested_cleaning_actions=["确认负值是否代表退款、冲销或录入错误。"],
                    evidence={"negative_count": negative_count},
                )
            )

    if _looks_date_name(column_name):
        parsed = pd.to_datetime(non_null, errors="coerce")
        bad_rate = 0.0 if len(non_null) == 0 else float(parsed.isna().mean())
        if bad_rate > 0:
            issues.append(
                DataQualityIssue(
                    severity="medium" if bad_rate < 0.2 else "high",
                    issue_type="invalid_dates",
                    table_name=table_name,
                    column_name=column_name,
                    message=f"{table_name}.{column_name} 存在 {bad_rate:.2%} 无法解析的日期值。",
                    affected_rows=int(parsed.isna().sum()),
                    sample_values=_sample_values(non_null[parsed.isna()]),
                    suggested_cleaning_actions=["统一日期格式，确认是否存在文本占位符或非法日期。"],
                    evidence={"invalid_date_rate": bad_rate},
                )
            )

    if _looks_identifier(column_name) and row_count >= 10:
        duplicate_key_count = int(non_null.duplicated(keep=False).sum())
        if duplicate_key_count:
            issues.append(
                DataQualityIssue(
                    severity="medium",
                    issue_type="duplicate_key_candidate",
                    table_name=table_name,
                    column_name=column_name,
                    message=f"{table_name}.{column_name} 像主键或 join key，但存在重复值。",
                    affected_rows=duplicate_key_count,
                    sample_values=_sample_values(non_null[non_null.duplicated(keep=False)]),
                    suggested_cleaning_actions=["确认该字段是一对一主键、外键，还是允许一对多关系。"],
                    evidence={"duplicate_key_count": duplicate_key_count},
                )
            )

    if row_count >= 20 and unique_count / row_count > 0.9 and not _looks_identifier(column_name) and not _looks_metric_name(column_name):
        issues.append(
            DataQualityIssue(
                severity="low",
                issue_type="high_cardinality_category",
                table_name=table_name,
                column_name=column_name,
                message=f"{table_name}.{column_name} 唯一值占比很高，作为分组维度可能过细。",
                sample_values=_sample_values(non_null),
                suggested_cleaning_actions=["确认是否需要映射到更高层级分类，或作为明细字段处理。"],
                evidence={"unique_rate": unique_count / row_count},
            )
        )
    return issues


def _numeric_outlier_issues(table_name: str, column_name: str, numeric: pd.Series) -> list[DataQualityIssue]:
    valid = numeric.dropna()
    q1 = float(valid.quantile(0.25))
    q3 = float(valid.quantile(0.75))
    iqr = q3 - q1
    if iqr == 0:
        return []
    lower = q1 - 3 * iqr
    upper = q3 + 3 * iqr
    mask = (numeric < lower) | (numeric > upper)
    count = int(mask.sum())
    if not count:
        return []
    return [
        DataQualityIssue(
            severity="medium" if count / len(valid) < 0.1 else "high",
            issue_type="numeric_outliers",
            table_name=table_name,
            column_name=column_name,
            message=f"{table_name}.{column_name} 存在 {count} 个 IQR 离群值。",
            affected_rows=count,
            sample_values=_sample_values(numeric[mask]),
            suggested_cleaning_actions=["结合业务确认离群值是真实极端值还是录入/单位错误。"],
            evidence={"lower_bound": lower, "upper_bound": upper, "outlier_count": count},
        )
    ]


def _missing_mask(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=bool)
    text = series.astype("string")
    placeholders = text.str.strip().str.lower().isin({"", "nan", "none", "null", "na", "n/a", "-", "--"})
    return series.isna() | placeholders.fillna(False)


def _looks_metric_name(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("amount", "sales", "revenue", "rate", "price", "count", "qty", "quantity", "金额", "销售", "收入", "数量", "价格", "率"))


def _looks_non_negative_metric(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("amount", "sales", "revenue", "price", "count", "qty", "quantity", "库存", "金额", "销售", "收入", "数量", "价格"))


def _looks_date_name(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("date", "day", "month", "year", "日期", "时间", "月份", "年份"))


def _looks_identifier(name: str) -> bool:
    lowered = name.lower()
    return lowered == "id" or lowered.endswith("id") or lowered.endswith("_id") or "编号" in lowered or "id" in lowered


def _sample_values(series: pd.Series) -> list[Any]:
    return [_json_scalar(value) for value in series.dropna().head(5).tolist()]


def _sample_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [{str(key): _json_scalar(value) for key, value in row.items()} for row in df.head(3).to_dict(orient="records")]


def _json_scalar(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _dedupe_issues(issues: list[DataQualityIssue]) -> list[DataQualityIssue]:
    seen: set[tuple[str, str | None, str | None]] = set()
    deduped: list[DataQualityIssue] = []
    for issue in issues:
        key = (issue.issue_type, issue.table_name, issue.column_name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def _quality_score(issues: list[DataQualityIssue]) -> float:
    penalty = 0
    for issue in issues:
        penalty += {"low": 3, "medium": 8, "high": 15}.get(issue.severity, 5)
    return max(0.0, float(100 - penalty))


def _summary(issues: list[DataQualityIssue], table_count: int) -> str:
    if not issues:
        return f"已扫描 {table_count} 张表，未发现明显数据质量问题。"
    high = sum(1 for issue in issues if issue.severity == "high")
    medium = sum(1 for issue in issues if issue.severity == "medium")
    low = sum(1 for issue in issues if issue.severity == "low")
    return f"已扫描 {table_count} 张表，发现 {len(issues)} 个潜在问题：high={high}, medium={medium}, low={low}。"


def _safe_rate(count: int, total: int) -> float:
    return 0.0 if total <= 0 else float(count) / float(total)


def _format_rate(rate: float) -> str:
    return f"{rate:.2%}"
