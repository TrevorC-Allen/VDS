"""Intent parser for natural language data questions.

This parser uses general field, period, and fee-rule patterns. It must not use
benchmark task IDs, standard answers, or single-question templates.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from data_agent_core.contracts.analysis_contracts import LogicForm
from data_agent_core.core.chinese_retail_intent import parse_chinese_retail_question
from data_agent_core.core.date_utils import MONTH_NAME_TO_NUMBER
from data_agent_core.core.logic_form import make_logic_form
from data_agent_core.core.vds_bi_intent import parse_vds_bi_question


CARD_SCHEMES = ("TransactPlus", "GlobalCard", "NexPay", "SwiftCharge")
FIELD_ALIASES = {
    "authorization characteristics indicator": "aci",
    "authorization characteristic indicator": "aci",
    "aci": "aci",
    "card scheme": "card_scheme",
    "device type": "device_type",
    "device": "device_type",
    "shopper interaction": "shopper_interaction",
    "payment interaction": "shopper_interaction",
    "issuing country": "issuing_country",
    "issuing_country": "issuing_country",
    "ip country": "ip_country",
    "ip_country": "ip_country",
    "ip address": "ip_address",
    "ip addresses": "ip_address",
    "ip": "ip_address",
    "merchant": "merchant",
    "shopper": "email_address",
    "customer": "email_address",
    "email": "email_address",
    "card number": "card_number",
    "card bin": "card_bin",
    "transaction": "psp_reference",
    "credit": "is_credit",
    "amount": "eur_amount",
    "transaction amount": "eur_amount",
    "transaction value": "eur_amount",
    "fraudulent disputes": "has_fraudulent_dispute",
    "fraudulent dispute": "has_fraudulent_dispute",
    "email address": "email_address",
}


def _extract_options(question: str) -> dict[str, str]:
    return {
        letter.upper(): value.upper()
        for letter, value in re.findall(r"\b([A-D])\.\s*([A-Z]{2})\b", question)
    }


def _extract_labeled_options(question: str) -> dict[str, str]:
    matches = re.findall(r"\b([A-D])\.\s*([^,]+?)(?=,\s*[A-D]\.|$)", question)
    return {letter.upper(): value.strip() for letter, value in matches}


def _extract_year(question: str, default: int = 2023) -> int:
    match = re.search(r"\b(20\d{2})\b", question)
    return int(match.group(1)) if match else default


def _extract_month(question: str) -> int | None:
    lowered = question.lower()
    for name, number in MONTH_NAME_TO_NUMBER.items():
        if name in lowered:
            return number
    return None


def _extract_month_range(question: str) -> tuple[int, int] | None:
    lowered = question.lower()
    match = re.search(r"(?:between|from)\s+([a-z]+)\s+(?:and|to|through)\s+([a-z]+)", lowered)
    if not match:
        match = re.search(r"\b([a-z]+)\s+(?:to|through|-)\s+([a-z]+)\b", lowered)
    if not match:
        return None
    start = MONTH_NAME_TO_NUMBER.get(match.group(1))
    end = MONTH_NAME_TO_NUMBER.get(match.group(2))
    if start is None or end is None:
        return None
    return start, end


def _extract_quarter_month_range(question: str) -> tuple[int, int] | None:
    lowered = question.lower()
    chinese_quarters = {
        "第一季度": 1,
        "一季度": 1,
        "第1季度": 1,
        "第二季度": 2,
        "二季度": 2,
        "第2季度": 2,
        "第三季度": 3,
        "三季度": 3,
        "第3季度": 3,
        "第四季度": 4,
        "四季度": 4,
        "第4季度": 4,
        "最后一季度": 4,
    }
    for token, quarter in chinese_quarters.items():
        if token in question:
            return (quarter - 1) * 3 + 1, quarter * 3
    aliases = {
        "first quarter": 1,
        "second quarter": 2,
        "third quarter": 3,
        "fourth quarter": 4,
        "final quarter": 4,
        "last quarter": 4,
        "previous quarter": 4,
    }
    for token, quarter in aliases.items():
        if token in lowered:
            return (quarter - 1) * 3 + 1, quarter * 3
    quarter_match = re.search(r"\bq([1-4])\b|quarter\s*([1-4])\b|([1-4])(?:st|nd|rd|th)?\s+quarter", lowered)
    if quarter_match:
        quarter = int(next(group for group in quarter_match.groups() if group))
        return (quarter - 1) * 3 + 1, quarter * 3
    return _extract_month_range(question)


def _extract_day_of_year(question: str) -> int | None:
    match = re.search(r"for the\s+(\d+)(?:st|nd|rd|th)?\s+of the year", question, re.I)
    return int(match.group(1)) if match else None


def _extract_merchant(question: str, context: dict[str, Any]) -> str | None:
    merchants = context.get("merchant_data") or []
    names = [row["merchant"] for row in merchants if isinstance(row, dict) and "merchant" in row]
    for name in sorted(names, key=len, reverse=True):
        if name in question:
            return name
    return None


def _extract_card_scheme(question: str) -> str | None:
    for scheme in CARD_SCHEMES:
        if re.search(rf"\b{re.escape(scheme)}\b", question):
            return scheme
    return None


def _extract_account_type(question: str) -> str | None:
    match = re.search(r"account[_ ]type\s*=\s*([A-Z])", question, re.I)
    if match:
        return match.group(1).upper()
    match = re.search(r"account type\s+([A-Z])\b", question, re.I)
    return match.group(1).upper() if match else None


def _extract_aci(question: str) -> str | None:
    match = re.search(r"\baci\s*=\s*([A-G])\b", question, re.I)
    return match.group(1).upper() if match else None


def _extract_credit_filter(question: str) -> bool | None:
    lowered = question.lower()
    if "credit" in lowered:
        return True
    if "debit" in lowered:
        return False
    return None


def _extract_transaction_value(question: str) -> float | None:
    match = re.search(r"transaction value of\s+(\d+(?:\.\d+)?)\s*(?:EUR|euros?)", question, re.I)
    if not match:
        match = re.search(r"transaction of\s+(\d+(?:\.\d+)?)\s*(?:EUR|euros?)", question, re.I)
    if not match:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:EUR|euros?)", question, re.I)
    return float(match.group(1)) if match else None


def _extract_zscore_threshold(question: str) -> float | None:
    match = re.search(r"z[- ]?score\s*>\s*(\d+(?:\.\d+)?)", question, re.I)
    return float(match.group(1)) if match else None


def _extract_group_by(question: str, default: str = "shopper_interaction") -> str:
    lowered = question.lower()
    aliases = {
        "aci": "aci",
        "authorization characteristics indicator": "aci",
        "shopper interaction": "shopper_interaction",
        "payment interaction": "shopper_interaction",
        "card scheme": "card_scheme",
        "issuing country": "issuing_country",
        "issuing_country": "issuing_country",
        "ip country": "ip_country",
        "ip_country": "ip_country",
        "device type": "device_type",
        "card_scheme": "card_scheme",
        "shopper_interaction": "shopper_interaction",
        "merchant": "merchant",
        "hour of day": "hour_of_day",
        "hour": "hour_of_day",
    }
    match = re.search(r"grouped by\s+([a-z_ ]+?)(?:\s+for|\s+between|\?|$)", lowered)
    candidate = match.group(1).strip() if match else ""
    for text, column in aliases.items():
        if candidate == text or f"grouped by {text}" in lowered:
            return column
    return default


def _extract_fraud_likelihood_dimension(question: str) -> str:
    lowered = question.lower()
    aliases = {
        "authorization characteristics indicator": "aci",
        "authorization characteristic indicator": "aci",
        "aci": "aci",
        "shopper interaction": "shopper_interaction",
        "payment interaction": "shopper_interaction",
        "card scheme": "card_scheme",
        "issuing country": "issuing_country",
        "ip country": "ip_country",
        "device type": "device_type",
        "device": "device_type",
        "merchant": "merchant",
        "credit": "is_credit",
        "debit": "is_credit",
    }
    for text, column in aliases.items():
        if text in lowered:
            return column
    return _extract_group_by(question, default="shopper_interaction")


def _extract_field_name(question: str, context: dict[str, Any] | None = None) -> str | None:
    """Resolve a natural-language field reference to a known column name."""

    lowered = question.lower()
    for alias, column in FIELD_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return column
    for pattern in (r"field\s+([a-zA-Z_ ]+?)(?:\?|$|,|\s+in\s+)", r"column\s+([a-zA-Z_ ]+?)(?:\?|$|,|\s+in\s+)"):
        match = re.search(pattern, question, re.I)
        if match:
            candidate = match.group(1).strip().replace(" ", "_").lower()
            if candidate:
                return candidate
    payments = None if context is None else context.get("payments")
    if payments is not None:
        for column in payments.columns:
            if str(column).lower() in lowered:
                return str(column)
    return None


def _extract_mcc_description(question: str) -> str | None:
    match = re.search(r"MCC description:\s*(.+?)(?:,|\?|$)", question, re.I)
    return match.group(1).strip() if match else None


def _extract_new_rate(question: str) -> int | None:
    match = re.search(r"changed to\s+(\d+)", question, re.I)
    return int(match.group(1)) if match else None


def _extract_new_mcc(question: str) -> int | None:
    match = re.search(r"MCC code to\s+(\d+)", question, re.I)
    return int(match.group(1)) if match else None


def _comparison_spec_for_fraud_rate(question: str) -> dict[str, Any] | None:
    lowered = question.lower()
    if "ecommerce" in lowered and ("in-store" in lowered or "in store" in lowered):
        return {"dimension": "shopper_interaction", "left_value": "Ecommerce", "right_value": "POS"}
    if "credit" in lowered and "debit" in lowered:
        return {"dimension": "is_credit", "left_value": True, "right_value": False}
    return None


def parse_question(question: str, guidelines: str = "", context: dict[str, Any] | None = None) -> LogicForm:
    """Parse a natural language question into a framework-neutral LogicForm."""

    context = context or {}
    lowered = question.lower()
    output_format = {"guidelines": guidelines}

    if _is_worst_fraud_segment_question(lowered):
        return make_logic_form(
            task_type="ranking",
            operation="worst_fraud_segment",
            metric="fraud_volume_rate",
            metric_definition={
                "name": "fraud_volume_rate",
                "description": "Fraud rate is fraudulent volume divided by total volume.",
                "aggregation": "ratio",
                "source": "manual.md section 7 and payments.csv",
            },
            parameters={
                "table": "payments",
                "dimensions": _extract_segment_dimensions(question),
                "metric": "fraud_volume_rate",
            },
            output_format=output_format | {"answer_type": "text"},
        )

    if _is_correlation_threshold_question(lowered):
        return make_logic_form(
            task_type="correlation",
            operation="correlation_threshold",
            metric="eur_amount",
            parameters={
                "table": "payments",
                "metric": "eur_amount",
                "target": "has_fraudulent_dispute",
                "threshold": _extract_threshold(question, default=0.5),
                "method": "pearson",
                "absolute": True,
            },
            output_format=output_format | {"answer_type": "yes_no"},
        )

    if _is_outlier_fraud_rate_comparison_question(lowered):
        return make_logic_form(
            task_type="comparison",
            operation="outlier_rate_comparison",
            metric="fraud_transaction_rate",
            filters={"year": _extract_year(question) if re.search(r"\b20\d{2}\b", question) else None},
            parameters={
                "table": "payments",
                "metric": _extract_outlier_metric(question, context),
                "target": "has_fraudulent_dispute",
                "method": "zscore" if "z-score" in lowered or "z score" in lowered else "iqr",
                "z_threshold": _extract_zscore_threshold(question) or 3.0,
                "operator": "higher_than" if "higher" in lowered or "greater" in lowered else "lower_than",
            },
            output_format=output_format | {"answer_type": "yes_no"},
        )

    if _is_outlier_target_percentage_question(lowered):
        return make_logic_form(
            task_type="aggregation",
            operation="outlier_target_percentage",
            metric="fraud_transaction_rate",
            filters={"year": _extract_year(question) if re.search(r"\b20\d{2}\b", question) else None},
            parameters={
                "table": "payments",
                "metric": _extract_outlier_metric(question, context),
                "target": "has_fraudulent_dispute",
                "method": "zscore" if "z-score" in lowered or "z score" in lowered else "iqr",
                "z_threshold": _extract_zscore_threshold(question) or 3.0,
            },
            output_format=output_format | {"answer_type": "percentage", "decimals": _decimal_places(guidelines, 3)},
        )

    if _is_high_value_percentage_question(lowered):
        return make_logic_form(
            task_type="aggregation",
            operation="quantile_percentage",
            metric="eur_amount",
            filters={"year": _extract_year(question) if re.search(r"\b20\d{2}\b", question) else None},
            parameters={
                "table": "payments",
                "metric": _extract_outlier_metric(question, context),
                "quantile": _extract_percentile(question, default=0.9),
                "operator": "above" if "above" in lowered or "greater" in lowered or "超过" in question else "below",
            },
            output_format=output_format | {"answer_type": "percentage", "decimals": _decimal_places(guidelines, 3)},
        )

    if _is_missing_value_top_count_question(lowered):
        missing_field = _extract_missing_field(question, context) or "email_address"
        return make_logic_form(
            task_type="ranking",
            operation="top_count",
            metric="transaction_count",
            group_by=_extract_group_by(question, default="card_scheme"),
            filters={missing_field: "__NULL__"},
            parameters={"table": "payments", "group_by": _extract_group_by(question, default="card_scheme")},
            output_format=output_format | {"answer_type": "text"},
        )

    if _is_missing_columns_choice_question(lowered):
        return make_logic_form(
            task_type="data_quality",
            operation="missing_columns_choice",
            parameters={
                "table": "payments",
                "fields": _extract_columns_mentioned(question, context),
                "options": _extract_labeled_options(question),
            },
            output_format=output_format | {"answer_type": "text"},
        )

    if _is_fee_factor_direction_question(lowered):
        return make_logic_form(
            task_type="fee_rule",
            operation="fee_factor_direction",
            parameters={"objective": _fee_factor_direction_objective(lowered)},
            output_format=output_format | {"answer_type": "list"},
        )

    if _is_fee_volume_threshold_question(lowered):
        return make_logic_form(
            task_type="fee_rule",
            operation="fee_volume_threshold",
            parameters={"objective": "highest_volume_without_cheaper_fee"},
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_top_outlier_group_question(lowered):
        return make_logic_form(
            task_type="ranking",
            operation="top_outlier_group",
            parameters={
                "table": "payments",
                "group_by": _extract_group_by(question, default="hour_of_day"),
                "metric": _extract_field_name(question, context) or "eur_amount",
                "method": "zscore" if "z-score" in lowered or "z score" in lowered else "iqr",
                "z_threshold": _extract_zscore_threshold(question) or 3.0,
            },
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_top_group_count_question(lowered):
        return make_logic_form(
            task_type="ranking",
            operation="top_count",
            parameters={"group_by": _extract_group_by(question, default="hour_of_day")},
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_most_common_value_question(lowered):
        group_by = _extract_field_name(question, context) or _extract_group_by(question, default="shopper_interaction")
        return make_logic_form(
            task_type="ranking",
            operation="top_count",
            metric="transaction_count",
            group_by=group_by,
            parameters={"table": "payments", "group_by": group_by},
            output_format=output_format | {"answer_type": "text"},
        )

    if _is_boolean_ratio_question(lowered):
        return make_logic_form(
            task_type="aggregation",
            operation="boolean_count_ratio",
            parameters={"table": "payments", "field": "is_credit", "left_value": True, "right_value": False},
            output_format=output_format | {"answer_type": "number", "decimals": _decimal_places(guidelines, 3)},
        )

    if _is_device_transaction_count_question(lowered):
        return make_logic_form(
            task_type="aggregation",
            operation="row_count",
            filters={"device_type": _extract_device_type(question)},
            parameters={"table": "payments"},
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_schema_field_lookup_question(lowered):
        return make_logic_form(
            task_type="schema_query",
            operation="schema_field_lookup",
            parameters={
                "table": "payments",
                "concept": _extract_schema_concept(question),
                "field": _schema_field_for_concept(question, context),
            },
            output_format=output_format | {"answer_type": "text"},
        )

    if _is_present_percentage_question(lowered):
        return make_logic_form(
            task_type="data_quality",
            operation="null_check",
            parameters={"table": "payments", "field": _present_field_for_question(lowered), "mode": "present_rate"},
            output_format=output_format | {"answer_type": "percentage", "decimals": _decimal_places(guidelines, 2)},
        )

    if _is_average_transaction_amount_question(lowered):
        return make_logic_form(
            task_type="aggregation",
            operation="aggregation",
            metric="eur_amount",
            parameters={"table": "payments", "metric": "eur_amount", "aggregation": "mean"},
            output_format=output_format | {"answer_type": "number", "decimals": _decimal_places(guidelines, 2)},
        )

    if _is_day_of_year_top_count_question(lowered):
        return make_logic_form(
            task_type="ranking",
            operation="top_count",
            metric="transaction_count",
            group_by="day_of_year",
            parameters={"table": "payments", "group_by": "day_of_year"},
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_most_missing_column_question(lowered):
        return make_logic_form(
            task_type="data_quality",
            operation="null_check",
            parameters={"table": "payments", "mode": "max_field"},
            output_format=output_format | {"answer_type": "text"},
        )

    if _is_repeat_entity_count_question(lowered):
        return make_logic_form(
            task_type="aggregation",
            operation="repeat_entity_count",
            parameters={"table": "payments", "field": _repeat_entity_field_for_question(lowered), "min_count": 2},
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_row_count_question(lowered):
        return make_logic_form(
            task_type="aggregation",
            operation="row_count",
            filters={"card_scheme": _extract_card_scheme(question)},
            parameters={"table": "payments"},
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_metric_per_distinct_entity_question(lowered):
        metric, aggregation = _metric_per_distinct_entity_metric(question, context)
        return make_logic_form(
            task_type="aggregation",
            operation="metric_per_distinct_entity",
            metric=metric,
            parameters={
                "table": "payments",
                "metric": metric,
                "entity_field": _extract_missing_field(question, context) or "email_address",
                "aggregation": aggregation,
            },
            output_format=output_format | {"answer_type": "number", "decimals": _decimal_places(guidelines, 2)},
        )

    if _is_distinct_count_question(lowered):
        return make_logic_form(
            task_type="schema_query",
            operation="distinct_count",
            parameters={"table": "payments", "field": _extract_field_name(question, context)},
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_repeat_entity_percentage_question(lowered):
        return make_logic_form(
            task_type="aggregation",
            operation="repeat_entity_percentage",
            parameters={"table": "payments", "field": _extract_field_name(question, context) or "email_address"},
            output_format=output_format | {"answer_type": "percentage", "decimals": _decimal_places(guidelines, 2)},
        )

    if _is_outlier_count_question(lowered):
        return make_logic_form(
            task_type="data_quality",
            operation="outlier_count",
            parameters={
                "table": "payments",
                "metric": _extract_outlier_metric(question, context),
                "method": "zscore" if "z-score" in lowered or "z score" in lowered else "iqr",
            },
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_null_check_question(lowered):
        mode = _null_check_mode(lowered)
        return make_logic_form(
            task_type="data_quality",
            operation="null_check",
            filters={"year": _extract_year(question) if re.search(r"\b20\d{2}\b", question) else None},
            parameters={
                "table": "payments",
                "field": _extract_field_name(question, context),
                "mode": mode,
            },
            output_format=output_format | {"answer_type": "yes_no" if mode == "exists" else "percentage" if mode == "rate" else "number"},
        )

    if _is_top_k_share_question(lowered):
        return make_logic_form(
            task_type="aggregation",
            operation="top_k_share",
            metric="eur_amount",
            group_by=_extract_group_by(question, default="merchant"),
            parameters={
                "table": "payments",
                "metric": "eur_amount",
                "dimension": _extract_group_by(question, default="merchant"),
                "aggregation": "sum",
                "limit": _extract_limit(question, default=3),
            },
            output_format=output_format | {"answer_type": "percentage", "decimals": _decimal_places(guidelines, 2)},
        )

    if _is_unique_values_question(lowered):
        return make_logic_form(
            task_type="schema_query",
            operation="field_values",
            parameters={"table": "payments", "field": _extract_field_name(question, context)},
            output_format=output_format | {"answer_type": "list"},
        )

    if "duplicate" in lowered and ("transaction" in lowered or "row" in lowered or "record" in lowered):
        return make_logic_form(
            task_type="data_quality",
            operation="duplicate_check",
            parameters={"table": "payments", "subset": "all"},
            output_format=output_format | {"answer_type": "yes_no"},
        )

    if re.search(r"\b(fine|fines|penalty|penalties|danger)\b", lowered):
        return make_logic_form(
            task_type="unsupported",
            operation="not_applicable",
            parameters={"reason": "Uploaded rules do not define fines or danger thresholds."},
            output_format=output_format | {"answer_type": "text"},
        )

    if "excessive fraud threshold" in lowered or ("fraud threshold" in lowered and "merchant" in lowered):
        return make_logic_form(
            task_type="unsupported",
            operation="not_applicable",
            parameters={"reason": "Uploaded rules do not define excessive fraud thresholds."},
            output_format=output_format | {"answer_type": "text", "not_applicable_type": "true_unsupported"},
        )

    if "fraud rate" in lowered and ("higher than" in lowered or "lower than" in lowered):
        spec = _comparison_spec_for_fraud_rate(question)
        if spec:
            return make_logic_form(
                task_type="comparison",
                operation="fraud_rate_comparison",
                filters={"year": _extract_year(question)},
                parameters={
                    "dimension": spec["dimension"],
                    "left_value": spec["left_value"],
                    "right_value": spec["right_value"],
                    "operator": "higher_than" if "higher than" in lowered else "lower_than",
                },
                output_format=output_format | {"answer_type": "yes_no"},
            )

    if (
        ("fraudulent dispute" in lowered or "fraud dispute" in lowered or "fraud likelihood" in lowered or "more likely" in lowered)
        and "credit" in lowered
        and "debit" in lowered
    ):
        return make_logic_form(
            task_type="comparison",
            operation="fraud_rate_comparison",
            metric="fraud_transaction_rate",
            metric_definition={
                "name": "fraud_transaction_rate",
                "description": "Fraudulent transaction count divided by total transaction count.",
                "aggregation": "ratio",
                "source": "payments.csv",
            },
            numerator={"column": "has_fraudulent_dispute", "filter": {"has_fraudulent_dispute": True}, "aggregation": "count"},
            denominator={"aggregation": "count"},
            filters={"year": _extract_year(question)},
            parameters={
                "dimension": "is_credit",
                "left_value": True,
                "right_value": False,
                "operator": "higher_than" if "more likely" in lowered or "higher" in lowered else "lower_than",
            },
            output_format=output_format | {"answer_type": "yes_no"},
        )

    if _is_fraud_likelihood_ranking_question(lowered):
        group_by = _extract_fraud_likelihood_dimension(question)
        filters = {
            "year": _extract_year(question) if re.search(r"\b20\d{2}\b", question) else None,
            "merchant": _extract_merchant(question, context),
            "card_scheme": None if group_by == "card_scheme" else _extract_card_scheme(question),
            "is_credit": None if group_by == "is_credit" else _extract_credit_filter(question),
            "shopper_interaction": None if group_by == "shopper_interaction" else _extract_shopper_interaction_filter(question),
            "month_range": _extract_quarter_month_range(question),
        }
        filters = {key: value for key, value in filters.items() if value is not None}
        objective = "minimum" if any(token in lowered for token in ("least likely", "less likely", "lowest likelihood")) else "maximum"
        return make_logic_form(
            task_type="ranking",
            operation="rank_by_metric",
            metric="fraud_transaction_rate",
            metric_definition={
                "name": "fraud_transaction_rate",
                "description": "Fraud likelihood is defined as fraudulent transaction count divided by total transaction count.",
                "aggregation": "ratio",
                "source": "payments.csv",
            },
            numerator={"column": "has_fraudulent_dispute", "filter": {"has_fraudulent_dispute": True}, "aggregation": "count"},
            denominator={"aggregation": "count"},
            group_by=group_by,
            objective=objective,
            filters=filters,
            options=_extract_options(question),
            parameters={
                "table": "payments",
                "group_by": group_by,
                "metric": "fraud_transaction_rate",
                "objective": objective,
                "options": _extract_options(question),
            },
            output_format=output_format | {"answer_type": "text"},
        )

    if _is_fraudulent_transaction_percentage_question(lowered):
        return make_logic_form(
            task_type="aggregation",
            operation="boolean_percentage",
            filters={"year": _extract_year(question) if re.search(r"\b20\d{2}\b", question) else None},
            parameters={"table": "payments", "field": "has_fraudulent_dispute", "value": True},
            output_format=output_format | {"answer_type": "number", "decimals": _decimal_places(guidelines, 3)},
        )

    if "fraud rate" in lowered or _is_fraud_percentage_question(lowered):
        filters: dict[str, Any] = {"year": _extract_year(question)}
        if "in-person" in lowered or "in person" in lowered or "in-store" in lowered or "in store" in lowered:
            filters["shopper_interaction"] = "POS"
        elif "ecommerce" in lowered or "e-commerce" in lowered:
            filters["shopper_interaction"] = "Ecommerce"
        return make_logic_form(
            task_type="aggregation",
            operation="fraud_rate_filtered",
            metric="fraud_volume_rate",
            metric_definition={
                "name": "fraud_volume_rate",
                "description": "Fraudulent volume divided by total volume, returned as a percentage.",
                "aggregation": "ratio",
                "source": "manual.md section 7 and payments.csv",
            },
            numerator={"column": "eur_amount", "filter": {"has_fraudulent_dispute": True}, "aggregation": "sum"},
            denominator={"column": "eur_amount", "aggregation": "sum"},
            filters=filters,
            parameters={"table": "payments"},
            output_format=output_format | {"answer_type": "number", "decimals": _decimal_places(guidelines, 3)},
        )

    if ("percentage" in lowered or "proportion" in lowered or "share" in lowered) and (
        "credit" in lowered or "debit" in lowered
    ):
        return make_logic_form(
            task_type="aggregation",
            operation="boolean_percentage",
            metric="row_percentage",
            metric_definition={
                "name": "row_percentage",
                "description": "Percentage of rows matching a boolean field condition.",
                "aggregation": "ratio",
                "source": "payments.csv",
            },
            filters={"year": _extract_year(question) if re.search(r"\b20\d{2}\b", question) else None},
            parameters={"table": "payments", "field": "is_credit", "value": _extract_credit_filter(question)},
            output_format=output_format | {"answer_type": "number", "decimals": _decimal_places(guidelines, 3)},
        )

    if _is_ranking_question(lowered) and ("transaction value" in lowered or "eur_amount" in lowered or "amount" in lowered):
        group_by = _extract_field_name(question, context) or _extract_group_by(question, default="merchant")
        if "country" in lowered:
            group_by = "ip_country" if "ip" in lowered else "issuing_country"
        filters = {
            "merchant": _extract_merchant(question, context),
            "card_scheme": _extract_card_scheme(question),
            "year": _extract_year(question),
            "month_range": _extract_quarter_month_range(question),
        }
        filters = {key: value for key, value in filters.items() if value is not None}
        return make_logic_form(
            task_type="ranking",
            operation="filtered_metric_ranking",
            metric="eur_amount",
            group_by=group_by,
            filters=filters,
            parameters={
                "table": "payments",
                "metric": "eur_amount",
                "dimension": group_by,
                "aggregation": _infer_aggregation(lowered, default="mean" if "avg" in lowered or "average" in lowered else "sum"),
                "sort_order": "asc" if _is_bottom_question(lowered) else "desc",
                "limit": _extract_limit(question, default=1),
            },
            output_format=output_format | {"answer_type": "table"},
        )

    if "highest number of transactions" in lowered:
        group_by = _extract_group_by(question, default="issuing_country" if "issuing country" in lowered else "merchant")
        return make_logic_form(
            task_type="ranking",
            operation="top_count",
            metric="transaction_count",
            metric_definition={
                "name": "transaction_count",
                "description": "Count of payment transactions.",
                "aggregation": "count",
                "source": "payments.csv",
            },
            group_by=group_by,
            objective="maximum",
            parameters={"table": "payments", "group_by": group_by},
            output_format=output_format | {"answer_type": "country_code"},
        )

    if _is_most_common_value_question(lowered):
        group_by = _extract_field_name(question, context) or _extract_group_by(question, default="shopper_interaction")
        return make_logic_form(
            task_type="ranking",
            operation="top_count",
            metric="transaction_count",
            metric_definition={
                "name": "transaction_count",
                "description": "Count of payment transactions grouped by the requested categorical field.",
                "aggregation": "count",
                "source": "payments.csv",
            },
            group_by=group_by,
            objective="maximum",
            parameters={"table": "payments", "group_by": group_by},
            output_format=output_format | {"answer_type": "text"},
        )

    if "fraudulent transactions" in lowered and ("most common" in lowered or "commonly used" in lowered or "most commonly" in lowered):
        group_by = _extract_group_by(question, default="device_type" if "device" in lowered else "shopper_interaction")
        return make_logic_form(
            task_type="ranking",
            operation="top_count",
            metric="transaction_count",
            metric_definition={
                "name": "transaction_count",
                "description": "Count of fraudulent transactions after applying filters.",
                "aggregation": "count",
                "source": "payments.csv",
            },
            group_by=group_by,
            objective="maximum",
            filters={"has_fraudulent_dispute": True, "year": _extract_year(question) if re.search(r"\b20\d{2}\b", question) else None},
            parameters={"table": "payments", "group_by": group_by},
            output_format=output_format | {"answer_type": "text"},
        )

    if "top country" in lowered and "fraud" in lowered:
        group_by = "ip_country" if "ip_country" in question else "issuing_country"
        options = _extract_options(question)
        return make_logic_form(
            task_type="ranking",
            operation="rank_by_metric",
            metric="fraud_volume_rate",
            metric_definition={
                "name": "fraud_volume_rate",
                "description": "Fraud is defined in the manual as fraudulent volume divided by total volume.",
                "aggregation": "ratio",
                "source": "manual.md section 7 and payments.csv",
            },
            numerator={"column": "eur_amount", "filter": {"has_fraudulent_dispute": True}, "aggregation": "sum"},
            denominator={"column": "eur_amount", "aggregation": "sum"},
            group_by=group_by,
            objective="maximum",
            options=options,
            parameters={
                "table": "payments",
                "group_by": group_by,
                "metric": "fraud_volume_rate",
                "sort_order": "desc",
                "limit": 1,
                "options": options,
            },
            output_format=output_format | {"answer_type": "multiple_choice_country"},
        )

    if _is_metric_per_distinct_entity_question(lowered):
        metric = _extract_outlier_metric(question, context)
        return make_logic_form(
            task_type="aggregation",
            operation="metric_per_distinct_entity",
            metric=metric,
            parameters={
                "table": "payments",
                "metric": metric,
                "entity_field": _extract_missing_field(question, context) or "email_address",
                "aggregation": "sum",
            },
            output_format=output_format | {"answer_type": "number", "decimals": _decimal_places(guidelines, 2)},
        )

    if "average transaction value grouped by" in lowered:
        month_range = _extract_quarter_month_range(question)
        return make_logic_form(
            task_type="aggregation",
            operation="group_average",
            filters={
                "merchant": _extract_merchant(question, context),
                "card_scheme": _extract_card_scheme(question),
                "year": _extract_year(question),
                "month_range": month_range,
            },
            parameters={"group_by": _extract_group_by(question), "metric": "eur_amount"},
            output_format=output_format | {"answer_type": "grouped_amounts", "decimals": 2},
        )

    if "average fee" in lowered and "transaction value" in lowered:
        return make_logic_form(
            task_type="fee_rule",
            operation="average_fee_for_filters",
            filters={
                "card_scheme": _extract_card_scheme(question),
                "account_type": _extract_account_type(question),
                "is_credit": True if "credit transactions" in lowered else None,
                "mcc_description": _extract_mcc_description(question),
            },
            parameters={"transaction_value": _extract_transaction_value(question)},
            output_format=output_format | {"answer_type": "number", "decimals": _decimal_places(guidelines, 6)},
        )

    if "excessive retry" in lowered and "fee" in lowered:
        return make_logic_form(
            task_type="unsupported",
            operation="not_applicable",
            parameters={"reason": "Uploaded fee rules do not define an excessive retry fee amount; the manual describes excessive retrying as a downgrade risk."},
            output_format=output_format | {"answer_type": "text"},
        )

    if "fee id" in lowered and "account_type" in lowered and "aci" in lowered:
        return make_logic_form(
            task_type="fee_rule",
            operation="fee_ids_for_filters",
            filters={"account_type": _extract_account_type(question), "aci": _extract_aci(question)},
            output_format=output_format | {"answer_type": "list"},
        )

    if "applicable fee ids" in lowered or "fee ids applicable" in lowered:
        return make_logic_form(
            task_type="fee_rule",
            operation="applicable_fee_ids",
            filters={
                "merchant": _extract_merchant(question, context),
                "year": _extract_year(question),
                "month": _extract_month(question),
                "day_of_year": _extract_day_of_year(question),
            },
            output_format=output_format | {"answer_type": "list"},
        )

    if "total fees" in lowered:
        return make_logic_form(
            task_type="fee_rule",
            operation="total_fees",
            filters={
                "merchant": _extract_merchant(question, context),
                "year": _extract_year(question),
                "month": _extract_month(question),
                "day_of_year": _extract_day_of_year(question),
            },
            output_format=output_format | {"answer_type": "number", "decimals": _decimal_places(guidelines, 2)},
        )

    if "delta" in lowered and "fee" in lowered and "changed to" in lowered:
        return make_logic_form(
            task_type="fee_rule",
            operation="fee_rate_delta",
            filters={
                "merchant": _extract_merchant(question, context),
                "year": _extract_year(question),
                "month": _extract_month(question),
            },
            parameters={"fee_id": _extract_fee_id(question), "new_rate": _extract_new_rate(question)},
            output_format=output_format | {"answer_type": "number", "decimals": _decimal_places(guidelines, 14)},
        )

    if "steer traffic" in lowered and "card scheme" in lowered:
        objective = "maximum" if "maximum" in lowered else "minimum"
        return make_logic_form(
            task_type="fee_rule",
            operation="card_scheme_steering",
            filters={"merchant": _extract_merchant(question, context), "year": _extract_year(question), "month": _extract_month(question)},
            parameters={"objective": objective},
            output_format=output_format | {"answer_type": "scheme_fee", "decimals": 2},
        )

    if (
        "card scheme" in lowered
        and "transaction value" in lowered
        and "aci" not in lowered
        and ("cheapest fee" in lowered or "lowest fee" in lowered or "most expensive" in lowered or "highest fee" in lowered)
    ):
        objective = "maximum" if "most expensive" in lowered or "highest fee" in lowered else "minimum"
        return make_logic_form(
            task_type="fee_rule",
            operation="cheapest_card_scheme_for_transaction",
            parameters={"transaction_value": _extract_transaction_value(question), "objective": objective},
            output_format=output_format | {"answer_type": "card_scheme"},
        )

    if "only applied to account type" in lowered and "merchants" in lowered:
        return make_logic_form(
            task_type="fee_rule",
            operation="fee_restriction_affected_merchants",
            filters={"year": _extract_year(question), "new_account_type": _extract_account_type(question)},
            parameters={"fee_id": _extract_fee_id(question)},
            output_format=output_format | {"answer_type": "list"},
        )

    if "merchants" in lowered and "affected by" in lowered and "fee" in lowered:
        return make_logic_form(
            task_type="fee_rule",
            operation="fee_restriction_affected_merchants",
            filters={"year": _extract_year(question), "new_account_type": _extract_account_type(question)},
            parameters={"fee_id": _extract_fee_id(question)},
            output_format=output_format | {"answer_type": "list"},
        )

    if "changed its mcc code to" in lowered:
        return make_logic_form(
            task_type="fee_rule",
            operation="mcc_change_delta",
            filters={"merchant": _extract_merchant(question, context), "year": _extract_year(question), "month": _extract_month(question)},
            parameters={"new_mcc": _extract_new_mcc(question)},
            output_format=output_format | {"answer_type": "number", "decimals": _decimal_places(guidelines, 6)},
        )

    if "fraudulent transactions" in lowered and "aci" in lowered and "lowest possible fees" in lowered:
        return make_logic_form(
            task_type="fee_rule",
            operation="best_fraud_aci_choice",
            filters={"merchant": _extract_merchant(question, context), "year": _extract_year(question), "month": _extract_month(question)},
            output_format=output_format | {"answer_type": "scheme_fee", "decimals": 2},
        )

    if "aci" in lowered and ("transaction value" in lowered or re.search(r"transaction of\s+\d", lowered)) and (
        "most expensive" in lowered or "highest fee" in lowered or "cheapest" in lowered or "lowest fee" in lowered
    ):
        objective = "maximum" if "most expensive" in lowered or "highest fee" in lowered else "minimum"
        return make_logic_form(
            task_type="fee_rule",
            operation="aci_fee_extreme",
            metric="hypothetical_fee",
            metric_definition={
                "name": "hypothetical_fee",
                "description": "Sum of matching fee-rule components for one hypothetical transaction value under each ACI.",
                "aggregation": "sum",
                "source": "fees.json",
            },
            objective=objective,
            filters={"card_scheme": _extract_card_scheme(question), "is_credit": _extract_credit_filter(question)},
            parameters={"transaction_value": _extract_transaction_value(question), "objective": objective},
            output_format=output_format | {"answer_type": "aci"},
        )

    if "mcc" in lowered and ("transaction value" in lowered or re.search(r"transaction of\s+\d", lowered)) and (
        "most expensive" in lowered or "highest fee" in lowered or "cheapest" in lowered or "lowest fee" in lowered
    ):
        objective = "maximum" if "most expensive" in lowered or "highest fee" in lowered else "minimum"
        return make_logic_form(
            task_type="fee_rule",
            operation="fee_extreme_by_dimension",
            metric="fee",
            group_by="merchant_category_code",
            objective=objective,
            parameters={
                "table": "fees",
                "dimension": "merchant_category_code",
                "transaction_value": _extract_transaction_value(question),
                "objective": objective,
            },
            output_format=output_format | {"answer_type": "list"},
        )

    return make_logic_form(
        task_type="unsupported",
        operation="not_applicable",
        parameters={"reason": "No supported general analysis pattern matched."},
        output_format=output_format | {"answer_type": "text"},
    )


def _is_worst_fraud_segment_question(lowered: str) -> bool:
    return "fraud rate" in lowered and "segment" in lowered and any(token in lowered for token in ("worst", "highest", "target"))


def _extract_segment_dimensions(question: str) -> list[str]:
    lowered = question.lower()
    dimensions: list[str] = []
    aliases = (
        ("merchant", "merchant"),
        ("issuer country", "issuing_country"),
        ("issuing country", "issuing_country"),
        ("card_scheme", "card_scheme"),
        ("card scheme", "card_scheme"),
        ("shopper interaction", "shopper_interaction"),
        ("payment interaction", "shopper_interaction"),
        ("device type", "device_type"),
        ("aci", "aci"),
    )
    for text, column in aliases:
        if text in lowered and column not in dimensions:
            dimensions.append(column)
    return dimensions or ["merchant", "issuing_country", "card_scheme", "shopper_interaction"]


def _is_correlation_threshold_question(lowered: str) -> bool:
    return "correlation" in lowered and ("fraud" in lowered or "fraudulent" in lowered)


def _extract_threshold(question: str, default: float) -> float:
    match = re.search(r">\s*(\d+(?:\.\d+)?)", question)
    return float(match.group(1)) if match else default


def _is_outlier_fraud_rate_comparison_question(lowered: str) -> bool:
    return "outlier" in lowered and "inlier" in lowered and "fraud rate" in lowered


def _is_outlier_target_percentage_question(lowered: str) -> bool:
    return (
        "outlier" in lowered
        and any(token in lowered for token in ("percentage", "proportion", "share"))
        and ("fraud" in lowered or "fraudulent" in lowered)
    )


def _is_high_value_percentage_question(lowered: str) -> bool:
    return (
        any(token in lowered for token in ("high-value", "high value", "transaction amount", "transaction amounts", "eur_amount"))
        and any(token in lowered for token in ("percentage", "proportion", "share"))
        and any(token in lowered for token in ("percentile", "分位"))
    )


def _extract_percentile(question: str, default: float) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)(?:st|nd|rd|th)?\s+percentile", question, re.I)
    if match:
        value = float(match.group(1))
        return value / 100 if value > 1 else value
    return default


def _is_missing_value_top_count_question(lowered: str) -> bool:
    return any(token in lowered for token in ("most frequent", "most common", "highest number")) and any(
        token in lowered for token in ("missing", "null", "empty", "blank")
    )


def _extract_missing_field(question: str, context: dict[str, Any] | None = None) -> str | None:
    lowered = question.lower()
    if "email" in lowered:
        return "email_address"
    return _extract_field_name(question, context)


def _extract_outlier_metric(question: str, context: dict[str, Any] | None = None) -> str:
    """Resolve the numeric metric for outlier/high-value questions.

    Temporal words such as "during the year 2023" should act as filters, not
    as the outlier metric. If no explicit numeric metric is named, DABstep-style
    payment questions default to transaction amount.
    """

    lowered = question.lower()
    if any(token in lowered for token in ("amount", "value", "金额", "交易额", "支付额")):
        return "eur_amount"
    field = _extract_field_name(question, context)
    if field in {"year", "day_of_year", "month", "hour_of_day", "minute_of_hour"}:
        return "eur_amount"
    return field or "eur_amount"


def _is_fee_factor_direction_question(lowered: str) -> bool:
    return "fee" in lowered and "cheaper" in lowered and "factors" in lowered and any(
        token in lowered
        for token in ("increased", "increase", "decreased", "decrease", "reduced", "reduce", "lowered", "lower", "set to true", "set to false")
    )


def _fee_factor_direction_objective(lowered: str) -> str:
    if "set to true" in lowered:
        return "cheaper_when_true"
    if "set to false" in lowered:
        return "cheaper_when_false"
    if any(token in lowered for token in ("decreased", "decrease", "reduced", "reduce", "lowered", "lower")):
        return "cheaper_when_decreased"
    return "cheaper_when_increased"


def _is_fee_volume_threshold_question(lowered: str) -> bool:
    return "volume" in lowered and "fees" in lowered and "become cheaper" in lowered


def parse_generic_table_question(question: str, tables: dict[str, pd.DataFrame], guidelines: str = "") -> LogicForm:
    """Parse a simple uploaded-table question into a generic LogicForm.

    This is a conservative rule guardrail for common analytical questions. LLM
    stages can propose plans, but this parser keeps execution grounded in
    uploaded table columns.
    """

    retail_logic_form = parse_chinese_retail_question(question, tables, guidelines)
    if retail_logic_form is not None:
        return retail_logic_form

    vds_bi_logic_form = parse_vds_bi_question(question, tables, guidelines)
    if vds_bi_logic_form is not None:
        return vds_bi_logic_form

    lowered = question.lower()
    table_name, df = _select_primary_table(tables)
    metric = _find_metric_column(question, df)
    dimension = _find_dimension_column(question, df, metric)
    filters = _infer_value_filters(question, df, exclude={metric, dimension})
    output_format = {"guidelines": guidelines}

    if _is_top_outlier_group_question(lowered):
        return make_logic_form(
            task_type="ranking",
            operation="top_outlier_group",
            filters=filters,
            parameters={
                "table": table_name,
                "group_by": _find_named_column(question, df) or _extract_group_by(question, default=dimension or "hour_of_day"),
                "metric": metric,
                "method": "zscore" if "z-score" in lowered or "z score" in lowered else "iqr",
                "z_threshold": _extract_zscore_threshold(question) or 3.0,
            },
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_top_group_count_question(lowered):
        return make_logic_form(
            task_type="ranking",
            operation="top_count",
            filters=filters,
            parameters={"group_by": _find_named_column(question, df) or _extract_group_by(question, default=dimension or "hour_of_day")},
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_most_common_value_question(lowered):
        group_by = _find_named_column(question, df) or _find_entity_column(question, df) or dimension
        return make_logic_form(
            task_type="ranking",
            operation="top_count",
            filters=filters,
            parameters={"table": table_name, "group_by": group_by},
            output_format=output_format | {"answer_type": "text"},
        )

    if _is_row_count_question(lowered):
        return make_logic_form(
            task_type="aggregation",
            operation="row_count",
            filters=filters,
            parameters={"table": table_name},
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_metric_per_distinct_entity_question(lowered):
        field = _find_named_column(question, df) or _find_entity_column(question, df) or dimension
        return make_logic_form(
            task_type="aggregation",
            operation="metric_per_distinct_entity",
            metric=metric,
            filters=filters,
            parameters={"table": table_name, "metric": metric, "entity_field": field, "aggregation": "sum"},
            output_format=output_format | {"answer_type": "number", "decimals": _decimal_places(guidelines, 2)},
        )

    if _is_distinct_count_question(lowered):
        field = _find_named_column(question, df) or _find_entity_column(question, df) or dimension
        return make_logic_form(
            task_type="schema_query",
            operation="distinct_count",
            filters=filters,
            parameters={"table": table_name, "field": field},
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_repeat_entity_percentage_question(lowered):
        field = _find_named_column(question, df) or _find_entity_column(question, df) or dimension
        return make_logic_form(
            task_type="aggregation",
            operation="repeat_entity_percentage",
            filters=filters,
            parameters={"table": table_name, "field": field},
            output_format=output_format | {"answer_type": "percentage", "decimals": _decimal_places(guidelines, 2)},
        )

    if _is_outlier_count_question(lowered):
        return make_logic_form(
            task_type="data_quality",
            operation="outlier_count",
            filters=filters,
            parameters={
                "table": table_name,
                "metric": metric,
                "method": "zscore" if "z-score" in lowered or "z score" in lowered else "iqr",
            },
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_null_check_question(lowered):
        field = _find_named_column(question, df)
        return make_logic_form(
            task_type="data_quality",
            operation="null_check",
            filters=filters,
            parameters={"table": table_name, "field": field, "mode": _null_check_mode(lowered)},
            output_format=output_format | {"answer_type": "yes_no" if _null_check_mode(lowered) == "exists" else "number"},
        )

    if _is_top_k_share_question(lowered) and dimension:
        return make_logic_form(
            task_type="aggregation",
            operation="top_k_share",
            metric=metric,
            group_by=dimension,
            filters=filters,
            parameters={
                "table": table_name,
                "metric": metric,
                "dimension": dimension,
                "aggregation": _infer_aggregation(lowered, default="sum" if metric else "count"),
                "limit": _extract_limit(question, default=3),
            },
            output_format=output_format | {"answer_type": "percentage", "decimals": _decimal_places(guidelines, 2)},
        )

    if _is_unique_values_question(lowered):
        return make_logic_form(
            task_type="schema_query",
            operation="field_values",
            parameters={"table": table_name, "field": _find_named_column(question, df) or _find_entity_column(question, df) or dimension},
            output_format=output_format | {"answer_type": "list"},
        )

    if "duplicate" in lowered and ("row" in lowered or "record" in lowered or "transaction" in lowered):
        return make_logic_form(
            task_type="data_quality",
            operation="duplicate_check",
            parameters={"table": table_name, "subset": "all"},
            output_format=output_format | {"answer_type": "yes_no"},
        )

    if _is_ranking_question(lowered) and dimension:
        aggregation = _infer_aggregation(lowered, default="sum" if metric else "count")
        return make_logic_form(
            task_type="ranking",
            operation="filtered_metric_ranking" if filters else "ranking",
            filters=filters,
            parameters={
                "table": table_name,
                "metric": metric,
                "dimension": dimension,
                "aggregation": aggregation,
                "sort_order": "asc" if _is_bottom_question(lowered) else "desc",
                "limit": _extract_limit(question, default=1),
            },
            output_format=output_format | {"answer_type": "table"},
        )

    if _is_aggregation_question(lowered):
        aggregation = _infer_aggregation(lowered, default="sum")
        return make_logic_form(
            task_type="aggregation",
            operation="aggregation",
            parameters={
                "table": table_name,
                "metric": metric,
                "dimension": dimension if _has_grouping_language(lowered) else None,
                "aggregation": aggregation,
            },
            output_format=output_format | {"answer_type": "table" if dimension and _has_grouping_language(lowered) else "number"},
        )

    if _is_filtering_question(lowered):
        return make_logic_form(
            task_type="filtering",
            operation="filtering",
            parameters={
                "table": table_name,
                "conditions": _extract_simple_conditions(question, df),
                "limit": _extract_limit(question, default=20),
            },
            output_format=output_format | {"answer_type": "table"},
        )

    return make_logic_form(
        task_type="detail_lookup",
        operation="detail_lookup",
        parameters={"table": table_name, "limit": _extract_limit(question, default=20)},
        output_format=output_format | {"answer_type": "table"},
    )


def _extract_fee_id(question: str) -> int | None:
    match = re.search(r"\bID\s*=?\s*(\d+)|fee with ID\s*=?\s*(\d+)|Fee with ID\s+(\d+)", question, re.I)
    if not match:
        return None
    for value in match.groups():
        if value:
            return int(value)
    return None


def _decimal_places(guidelines: str, default: int | None = None) -> int | None:
    match = re.search(r"(\d+)\s+decimals?", guidelines, re.I)
    return int(match.group(1)) if match else default


def _select_primary_table(tables: dict[str, pd.DataFrame]) -> tuple[str, pd.DataFrame]:
    if not tables:
        raise ValueError("No parsed tables are available.")
    return max(tables.items(), key=lambda item: (len(item[1]), len(item[1].columns)))


def _find_metric_column(question: str, df: pd.DataFrame) -> str | None:
    lowered = question.lower()
    for column in df.columns:
        name = str(column)
        if name.lower() in lowered or name in question:
            if pd.api.types.is_numeric_dtype(df[column]):
                return name
    numeric_columns = [str(column) for column in df.columns if pd.api.types.is_numeric_dtype(df[column])]
    if not numeric_columns:
        return None
    metric_keywords = ("sales", "revenue", "amount", "fee", "cost", "price", "profit", "销售", "金额", "收入", "费用", "利润")
    for column in numeric_columns:
        if any(keyword in column.lower() for keyword in metric_keywords):
            return column
    return numeric_columns[0]


def _find_dimension_column(question: str, df: pd.DataFrame, metric: str | None) -> str | None:
    lowered = question.lower()
    for column in df.columns:
        name = str(column)
        if name == metric:
            continue
        if name.lower() in lowered or name in question:
            return name
    categorical = [
        str(column)
        for column in df.columns
        if str(column) != metric and not pd.api.types.is_numeric_dtype(df[column])
    ]
    dimension_keywords = ("city", "country", "region", "category", "merchant", "城市", "国家", "地区", "类别", "分类", "商户")
    for column in categorical:
        if any(keyword in column.lower() for keyword in dimension_keywords):
            return column
    return categorical[0] if categorical else None


def _find_named_column(question: str, df: pd.DataFrame) -> str | None:
    lowered = question.lower()
    for column in df.columns:
        name = str(column)
        if name.lower() in lowered or name in question:
            return name
    return None


def _find_entity_column(question: str, df: pd.DataFrame) -> str | None:
    lowered = question.lower()
    entity_terms = {
        "merchant": ("merchant", "商户"),
        "shopper": ("shopper", "customer", "email", "客户", "用户", "邮箱"),
        "customer": ("customer", "cust", "store", "客户", "门店", "终端"),
        "card": ("card", "卡"),
        "city": ("city", "城市"),
        "country": ("country", "国家"),
        "device": ("device", "设备"),
        "employee": ("employee", "emp", "业代", "员工"),
    }
    requested_terms: list[str] = []
    for aliases in entity_terms.values():
        if any(term in lowered or term in question for term in aliases):
            requested_terms.extend(aliases)
    if not requested_terms:
        return None
    for column in df.columns:
        column_text = str(column).lower()
        if any(term.lower() in column_text for term in requested_terms):
            return str(column)
    return None


def _is_ranking_question(lowered: str) -> bool:
    return any(token in lowered for token in ("highest", "lowest", "top", "bottom", "max", "min", "最多", "最高", "最低", "最少", "前"))


def _is_bottom_question(lowered: str) -> bool:
    return any(token in lowered for token in ("lowest", "bottom", "min", "最低", "最少"))


def _is_aggregation_question(lowered: str) -> bool:
    return any(token in lowered for token in ("total", "sum", "average", "avg", "mean", "count", "number", "总", "合计", "平均", "数量", "多少"))


def _is_filtering_question(lowered: str) -> bool:
    return any(token in lowered for token in ("where", "filter", "show", "list", "greater than", "less than", "筛选", "列出", "大于", "小于"))


def _has_grouping_language(lowered: str) -> bool:
    return any(token in lowered for token in (" by ", "group", "per ", "each", "按", "各", "每"))


def _is_row_count_question(lowered: str) -> bool:
    if _is_ranking_question(lowered):
        return False
    return any(
        token in lowered
        for token in (
            "how many rows",
            "number of rows",
            "row count",
            "record count",
            "how many transactions",
            "how many records",
            "total records",
            "total transactions",
            "number of transactions",
            "总行数",
            "多少行",
            "记录数",
            "多少条",
            "交易数",
            "总交易",
        )
    ) and not _is_distinct_count_question(lowered)


def _is_distinct_count_question(lowered: str) -> bool:
    return any(token in lowered for token in ("distinct", "unique", "不同", "唯一", "去重")) and any(
        token in lowered for token in ("count", "number", "how many", "多少", "数量", "个数")
    )


def _is_unique_values_question(lowered: str) -> bool:
    return any(token in lowered for token in ("possible values", "unique values", "distinct values", "unique set", "set of", "有哪些取值", "唯一值"))


def _is_metric_per_distinct_entity_question(lowered: str) -> bool:
    return any(token in lowered for token in ("average", "avg", "mean", "平均")) and any(
        token in lowered
        for token in (
            "per unique",
            "per distinct",
            "每个不同",
            "每个唯一",
            "按唯一",
            "每个客户",
            "每个用户",
            "每个邮箱",
        )
    )


def _metric_per_distinct_entity_metric(question: str, context: dict[str, Any] | None = None) -> tuple[str, str]:
    """Resolve numerator semantics for average-per-unique-entity questions."""

    lowered = question.lower()
    count_phrases = (
        "number of transactions",
        "transaction count",
        "transactions per unique",
        "transactions per distinct",
        "交易笔数",
        "交易次数",
        "订单数",
        "记录数",
    )
    amount_phrases = ("transaction amount", "transaction value", "amount", "value", "交易金额", "交易额", "金额")
    if any(token in lowered for token in count_phrases) and not any(token in lowered for token in amount_phrases):
        return "__row_count__", "count"
    return _extract_outlier_metric(question, context), "sum"


def _is_most_common_value_question(lowered: str) -> bool:
    if "fraud" in lowered or "fraudulent" in lowered:
        return False
    return any(token in lowered for token in ("most common", "most frequent", "most commonly", "出现次数最多", "最常见", "最频繁"))


def _is_boolean_ratio_question(lowered: str) -> bool:
    return "ratio" in lowered and "credit card" in lowered and "debit card" in lowered


def _is_device_transaction_count_question(lowered: str) -> bool:
    return "transactions" in lowered and "conducted on" in lowered and "devices" in lowered


def _extract_device_type(question: str) -> str | None:
    for value in ("Windows", "Linux", "MacOS", "iOS", "Android", "Other"):
        if re.search(rf"\b{re.escape(value)}\b", question, re.I):
            return value
    return None


def _is_repeat_entity_percentage_question(lowered: str) -> bool:
    return any(token in lowered for token in ("repeat", "returning", "重复", "复购", "回头", "老客")) and any(
        token in lowered for token in ("percentage", "proportion", "share", "rate", "占比", "比例", "百分比")
    )


def _is_top_group_count_question(lowered: str) -> bool:
    if "outlier" in lowered or "anomaly" in lowered or "异常" in lowered or "离群" in lowered:
        return False
    return (
        any(token in lowered for token in ("which hour", "during which hour", "哪个小时", "哪一小时"))
        and any(token in lowered for token in ("most transactions", "most records", "最多交易", "记录最多"))
    )


def _is_top_outlier_group_question(lowered: str) -> bool:
    return (
        any(token in lowered for token in ("outlier", "anomaly", "anomalies", "异常", "离群"))
        and any(token in lowered for token in ("which hour", "during which hour", "哪个小时", "哪一小时"))
        and any(token in lowered for token in ("most", "最多"))
    )


def _is_outlier_count_question(lowered: str) -> bool:
    return any(token in lowered for token in ("outlier", "anomaly", "anomalies", "异常", "离群")) and any(
        token in lowered for token in ("count", "number", "how many", "多少", "数量", "个数")
    )


def _is_schema_field_lookup_question(lowered: str) -> bool:
    return (
        any(token in lowered for token in ("name of the column", "which column", "what column", "column name", "字段名", "哪一列", "哪个字段"))
        and any(token in lowered for token in ("indicates", "represents", "stores", "shows", "表示", "代表", "标识", "记录"))
    )


def _extract_schema_concept(question: str) -> str:
    lowered = question.lower()
    if "fraud" in lowered or "欺诈" in question:
        return "fraud"
    if "email" in lowered or "邮箱" in question:
        return "email"
    if "country" in lowered or "国家" in question:
        return "country"
    return "field"


def _schema_field_for_concept(question: str, context: dict[str, Any] | None = None) -> str:
    concept = _extract_schema_concept(question)
    concept_fields = {
        "fraud": ("has_fraudulent_dispute", "is_fraud", "fraud"),
        "email": ("email_address", "email"),
        "country": ("issuing_country", "ip_country", "acquirer_country", "country"),
    }
    payments = None if context is None else context.get("payments")
    if payments is not None:
        columns = {str(column) for column in payments.columns}
        for field in concept_fields.get(concept, ()):
            if field in columns:
                return field
    return concept_fields.get(concept, ("",))[0]


def _is_present_percentage_question(lowered: str) -> bool:
    return (
        any(token in lowered for token in ("percentage", "proportion", "share", "rate"))
        and any(token in lowered for token in ("have", "has", "with", "associated"))
        and any(token in lowered for token in ("email address", "email", "card number", "ip address"))
    )


def _is_average_transaction_amount_question(lowered: str) -> bool:
    return (
        ("average transaction amount" in lowered or "avg transaction amount" in lowered)
        and not any(token in lowered for token in (" per ", " by ", "top ", "which ", "scenario"))
    )


def _is_day_of_year_top_count_question(lowered: str) -> bool:
    return (
        "day of the year" in lowered
        and any(token in lowered for token in ("most transactions", "highest number of transactions", "most transaction"))
    )


def _is_most_missing_column_question(lowered: str) -> bool:
    return any(token in lowered for token in ("which column", "what column", "column has")) and any(
        token in lowered for token in ("most missing", "highest missing", "missing data")
    )


def _is_repeat_entity_count_question(lowered: str) -> bool:
    return (
        any(token in lowered for token in ("how many", "number of", "count"))
        and any(token in lowered for token in ("more than one", "multiple", "repeat", "repeated"))
        and any(token in lowered for token in ("shopper", "customer", "email"))
        and "transaction" in lowered
    )


def _repeat_entity_field_for_question(lowered: str) -> str:
    if "email" in lowered or "shopper" in lowered or "customer" in lowered:
        return "email_address"
    if "card" in lowered:
        return "card_number"
    if "ip" in lowered:
        return "ip_address"
    return "email_address"


def _present_field_for_question(lowered: str) -> str:
    if "email" in lowered:
        return "email_address"
    if "ip address" in lowered:
        return "ip_address"
    if "card number" in lowered:
        return "card_number"
    return "email_address"


def _is_fraud_percentage_question(lowered: str) -> bool:
    return any(token in lowered for token in ("percentage", "proportion", "share", "rate")) and any(
        token in lowered for token in ("fraudulent", "fraud")
    )


def _is_fraudulent_transaction_percentage_question(lowered: str) -> bool:
    return (
        any(token in lowered for token in ("percentage", "proportion", "share"))
        and any(token in lowered for token in ("fraudulent", "fraud"))
        and "transaction" in lowered
    )


def _is_null_check_question(lowered: str) -> bool:
    return any(token in lowered for token in ("null", "missing", "empty", "blank", "nan", "空值", "缺失", "空白")) and any(
        token in lowered for token in ("count", "number", "how many", "any", "exist", "percentage", "proportion", "share", "rate", "有", "多少", "数量", "个数", "占比", "比例", "百分比")
    )


def _is_missing_columns_choice_question(lowered: str) -> bool:
    return "which columns" in lowered and "missing data" in lowered


def _extract_columns_mentioned(question: str, context: dict[str, Any] | None = None) -> list[str]:
    lowered = question.lower()
    fields: list[str] = []
    for alias, column in FIELD_ALIASES.items():
        if column in fields:
            continue
        if re.search(rf"\b{re.escape(alias)}\b", lowered) or column in lowered:
            fields.append(column)
    payments = None if context is None else context.get("payments")
    if payments is not None:
        for column in payments.columns:
            name = str(column)
            if name not in fields and (name.lower() in lowered or name in question):
                fields.append(name)
    return fields


def _null_check_mode(lowered: str) -> str:
    if any(token in lowered for token in ("percentage", "proportion", "rate", "占比", "比例", "百分比")):
        return "rate"
    if re.search(r"\b(any|exist|exists|existing)\b", lowered) or any(token in lowered for token in ("是否", "有没有", "有无")):
        return "exists"
    return "count"


def _is_fraud_likelihood_ranking_question(lowered: str) -> bool:
    likelihood_terms = (
        "fraud likelihood",
        "fraudulent dispute likelihood",
        "likely to result in a fraudulent dispute",
        "most likely to result in fraud",
        "least likely to result in fraud",
        "more likely to result in fraud",
        "fraudulent transaction rate",
    )
    return any(term in lowered for term in likelihood_terms) and any(
        token in lowered for token in ("which", "what", "highest", "lowest", "most likely", "least likely")
    )


def _extract_shopper_interaction_filter(question: str) -> str | None:
    lowered = question.lower()
    if "ecommerce" in lowered or "e-commerce" in lowered:
        return "Ecommerce"
    if "in-person" in lowered or "in person" in lowered or "in-store" in lowered or "in store" in lowered or "pos" in lowered:
        return "POS"
    return None


def _is_top_k_share_question(lowered: str) -> bool:
    return any(token in lowered for token in ("top", "前")) and any(
        token in lowered for token in ("share", "percentage", "proportion", "占比", "比例", "百分比")
    )


def _infer_aggregation(lowered: str, default: str) -> str:
    if any(token in lowered for token in ("average", "avg", "mean", "平均")):
        return "mean"
    if re.search(r"\b(count|number)\b", lowered) or any(token in lowered for token in ("数量", "多少")):
        return "count"
    if any(token in lowered for token in ("max", "最高")):
        return "max"
    if any(token in lowered for token in ("min", "最低")):
        return "min"
    return default


def _extract_limit(question: str, default: int) -> int:
    match = re.search(r"(?:top|前)\s*(\d+)", question, re.I)
    return int(match.group(1)) if match else default


def _infer_value_filters(question: str, df: pd.DataFrame, exclude: set[str | None] | None = None) -> dict[str, Any]:
    lowered = question.lower()
    excluded = {str(item) for item in (exclude or set()) if item}
    filters: dict[str, Any] = {}
    for column in df.columns:
        name = str(column)
        if name in excluded:
            continue
        series = df[column]
        if pd.api.types.is_numeric_dtype(series):
            continue
        unique_values = [value for value in series.dropna().unique().tolist() if str(value)]
        if len(unique_values) > 50:
            continue
        for value in sorted(unique_values, key=lambda item: len(str(item)), reverse=True):
            text = str(value)
            if text and _value_in_question(text, question, lowered):
                filters[name] = value
                break
    return filters


def _value_in_question(text: str, question: str, lowered: str) -> bool:
    if re.search(r"[\u4e00-\u9fff]", text):
        return text in question
    return bool(re.search(rf"(?<![A-Za-z0-9_]){re.escape(text.lower())}(?![A-Za-z0-9_])", lowered))


def _extract_simple_conditions(question: str, df: pd.DataFrame) -> list[dict[str, Any]]:
    conditions: list[dict[str, Any]] = []
    for column in df.columns:
        name = str(column)
        pattern = rf"{re.escape(name)}\s*(>=|<=|=|>|<)\s*([\w.\-\u4e00-\u9fff]+)"
        for op, value in re.findall(pattern, question):
            conditions.append({"column": name, "operator": op, "value": value})
    return conditions
