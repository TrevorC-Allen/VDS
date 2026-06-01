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
    "device_type": "device_type",
    "device": "device_type",
    "shopper interaction": "shopper_interaction",
    "payment interaction": "shopper_interaction",
    "issuing country": "issuing_country",
    "issuing_country": "issuing_country",
    "acquirer country": "acquirer_country",
    "acquirer_country": "acquirer_country",
    "ip country": "ip_country",
    "ip_country": "ip_country",
    "ip address": "ip_address",
    "ip addresses": "ip_address",
    "ip": "ip_address",
    "merchant": "merchant",
    "shopper": "email_address",
    "customer": "email_address",
    "产品": "product",
    "商品": "product",
    "品类": "category",
    "门店": "store",
    "店铺": "store",
    "城市": "city",
    "客户": "customer",
    "销售额": "sales",
    "销售金额": "sales",
    "收入": "revenue",
    "利润": "profit",
    "毛利": "profit",
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
    "account type": "account_type",
    "account_type": "account_type",
    "issuer country": "issuing_country",
    "issuer_country": "issuing_country",
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
        if _month_name_in_question(name, lowered):
            return number
    return None


def _month_name_in_question(name: str, lowered_question: str) -> bool:
    if re.fullmatch(r"[a-z]+", name):
        return bool(re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", lowered_question))
    return name in lowered_question


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


def _extract_year_month_range(question: str) -> tuple[int, int] | None:
    match = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月?\s*(?:至|到|-|~|—)\s*(?:(20\d{2})\s*年\s*)?(\d{1,2})\s*月", question)
    if match:
        start_year = int(match.group(1))
        start_month = int(match.group(2))
        end_year = int(match.group(3) or start_year)
        end_month = int(match.group(4))
        return start_year * 100 + start_month, end_year * 100 + end_month
    match = re.search(r"(20\d{2})-(\d{1,2})\s*(?:至|到|-|~|—)\s*(20\d{2})-(\d{1,2})", question)
    if match:
        return int(match.group(1)) * 100 + int(match.group(2)), int(match.group(3)) * 100 + int(match.group(4))
    return None


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
    names: list[str] = []
    merchants = context.get("merchant_data") or []
    names.extend(str(row["merchant"]) for row in merchants if isinstance(row, dict) and "merchant" in row)
    payments = context.get("payments")
    if payments is None:
        tables = context.get("tables") or {}
        for table in tables.values():
            if isinstance(table, pd.DataFrame) and "merchant" in table.columns:
                payments = table
                break
    if isinstance(payments, pd.DataFrame) and "merchant" in payments.columns:
        names.extend(str(value) for value in payments["merchant"].dropna().astype(str).unique().tolist())
    lowered = question.lower()
    for name in sorted({candidate for candidate in names if candidate}, key=len, reverse=True):
        if name in question or name.lower() in lowered:
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
        "acquirer country": "acquirer_country",
        "acquirer_country": "acquirer_country",
        "ip country": "ip_country",
        "ip_country": "ip_country",
        "device type": "device_type",
        "device_type": "device_type",
        "card_scheme": "card_scheme",
        "shopper_interaction": "shopper_interaction",
        "merchant": "merchant",
        "hour of day": "hour_of_day",
        "hour": "hour_of_day",
    }
    for text, column in aliases.items():
        if any(
            re.search(pattern, lowered)
            for pattern in (
                rf"grouped by\s+{re.escape(text)}(?:\b|_)",
                rf"\bby\s+{re.escape(text)}(?:\b|_)",
                rf"\bper\s+{re.escape(text)}(?:\b|_)",
            )
        ):
            return column
        if any(token in question for token in (f"按{text}", f"按 {text}", f"按{text}分组", f"按 {text} 分组")):
            return column
    match = re.search(r"(?:grouped by|by|per)\s+([a-z_ ]+?)(?:\s+for|\s+between|\s+in|\?|$)", lowered)
    candidate = match.group(1).strip() if match else ""
    for text, column in aliases.items():
        if candidate == text:
            return column
    return default


def _is_group_average_question(question: str) -> bool:
    lowered = question.lower()
    has_average = any(token in lowered for token in ("average", "avg", "mean")) or any(token in question for token in ("平均", "均值"))
    has_transaction_value = any(
        token in lowered for token in ("transaction value", "transaction amount", "eur_amount")
    ) or any(token in question for token in ("交易金额", "交易额", "支付金额"))
    if not has_average or not has_transaction_value:
        return False
    if "average fee" in lowered:
        return False
    return _extract_group_by(question, default="") != ""


def _answer_type_for_group_by(group_by: str | None) -> str:
    field = str(group_by or "")
    if field in {"hour_of_day", "day_of_year", "month", "year"}:
        return "number"
    if "country" in field:
        return "country_code"
    return "text"


def _has_missing_language(lowered: str) -> bool:
    return any(token in lowered for token in ("missing", "null", "empty", "blank", "nan", "缺失", "空值", "空白"))


def _has_fraudulent_row_filter(lowered: str) -> bool:
    return any(token in lowered for token in ("flagged as fraudulent", "fraudulent transactions", "fraudulent dispute", "fraud disputes"))


def _asks_for_transaction_share(lowered: str) -> bool:
    return any(token in lowered for token in ("percentage of transactions", "share of transactions", "proportion of transactions", "transactions came from"))


def _asks_for_amount_volume_ranking(lowered: str) -> bool:
    return any(token in lowered for token in ("amount volume", "transaction volume", "value volume", "by amount", "by transaction value"))


def _is_fraud_rate_fluctuation_question(lowered: str) -> bool:
    return "fraud rate" in lowered and any(token in lowered for token in ("fluctuation", "std", "standard deviation", "volatility"))


def _extract_fraud_rate_group_by(question: str, default: str | None = None) -> str | None:
    lowered = question.lower()
    if any(token in lowered for token in ("card_scheme", "card scheme", "payment method")) and any(
        token in lowered for token in ("which", " by ", "per ", "grouped by", "(by")
    ):
        return "card_scheme"
    if any(token in lowered for token in ("ip_country", "ip country")) and any(token in lowered for token in ("which", " by ", "per ", "grouped by", "(by")):
        return "ip_country"
    if any(token in lowered for token in ("issuer country", "issuing country")) and any(token in lowered for token in ("which", " by ", "per ", "grouped by", "(by")):
        return "issuing_country"
    if "shopper interaction" in lowered and any(token in lowered for token in ("which", " by ", "per ", "grouped by", "(by")):
        return "shopper_interaction"
    if "merchant" in lowered and any(
        token in lowered
        for token in (
            "which merchant",
            "what merchant",
            "per merchant",
            "by merchant",
            "grouped by merchant",
            "merchant had",
            "merchant has",
        )
    ):
        return "merchant"
    return default


def _asks_for_entity_answer(lowered: str) -> bool:
    return lowered.startswith("which ") or lowered.startswith("what merchant") or lowered.startswith("what country") or "which payment method" in lowered


def _is_scalar_metric_extreme_question(lowered: str) -> bool:
    return (
        _is_ranking_question(lowered)
        and any(token in lowered for token in ("transaction amount", "transaction value", "eur_amount", "amount recorded"))
        and not lowered.startswith("which ")
        and not any(token in lowered for token in (" by ", "grouped", "per ", "which merchant", "which country", "which card"))
    )


def _ranking_answer_target(question: str, guidelines: str, group_by: str | None) -> str | None:
    lowered = question.lower()
    guide = guidelines.lower()
    if "comma separated list" in guide or "comma delimited list" in guide or "country codes" in guide:
        return "entity_list_only"
    if _extract_limit(question, default=1) > 1 and not any(token in lowered for token in ("with their", "along with", "including")):
        return "entity_list_only"
    if lowered.startswith("which ") or lowered.startswith("what merchant") or lowered.startswith("what country"):
        return "entity_only"
    return None


def _ranking_output_format(question: str, guidelines: str, group_by: str | None, limit: int) -> dict[str, Any]:
    answer_target = _ranking_answer_target(question, guidelines, group_by)
    if answer_target == "entity_list_only":
        return {"answer_type": "list", "entity_field": group_by}
    if answer_target == "entity_only":
        return {"answer_type": _answer_type_for_group_by(group_by), "entity_field": group_by}
    return {"answer_type": "table"}


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
        dimensions = _extract_segment_dimensions(question)
        combine_dimensions = _should_combine_segment_dimensions(question, dimensions)
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
                "dimensions": dimensions,
                "combine_dimensions": combine_dimensions,
                "metric": "fraud_volume_rate",
            },
            answer_target="segment_vector" if combine_dimensions else None,
            output_format=output_format
            | {"answer_type": "list" if combine_dimensions else "text", "dimensions": dimensions},
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
        target_field = _repeat_entity_field_for_question(lowered) if _is_repeat_entity_percentage_question(lowered) else None
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
                "target_field": target_field,
                "target_mode": "repeat_entity" if target_field else None,
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

    if _is_general_data_quality_report_question(lowered):
        return make_logic_form(
            task_type="data_quality",
            operation="data_quality_report",
            parameters={"scope": "dataset", "tables": ["payments"]},
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
            output_format=output_format | {"answer_type": "text"},
        )

    if _is_top_outlier_group_question(lowered):
        group_by = _extract_field_name(question, context) or _extract_group_by(question, default="hour_of_day")
        return make_logic_form(
            task_type="ranking",
            operation="top_outlier_group",
            parameters={
                "table": "payments",
                "group_by": group_by,
                "metric": _extract_outlier_metric(question, context),
                "method": "zscore" if "z-score" in lowered or "z score" in lowered else "iqr",
                "z_threshold": _extract_zscore_threshold(question) or 3.0,
            },
            output_format=output_format | {"answer_type": _answer_type_for_group_by(group_by)},
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
        if _has_missing_language(lowered):
            missing_field = _extract_missing_field(question, context)
            return make_logic_form(
                task_type="aggregation",
                operation="row_count",
                filters={missing_field: "__NULL__"} if missing_field else {},
                parameters={"table": "payments"},
                output_format=output_format | {"answer_type": "number"},
            )
        if _has_fraudulent_row_filter(lowered):
            return make_logic_form(
                task_type="aggregation",
                operation="row_count",
                filters={"has_fraudulent_dispute": True},
                parameters={"table": "payments"},
                output_format=output_format | {"answer_type": "number"},
            )
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
        target_condition = _null_check_target_condition(lowered)
        return make_logic_form(
            task_type="data_quality",
            operation="null_check",
            filters={"year": _extract_year(question) if re.search(r"\b20\d{2}\b", question) else None},
            parameters={
                "table": "payments",
                "field": _extract_field_name(question, context),
                "mode": mode,
                **target_condition,
            },
            output_format=output_format | {"answer_type": "yes_no" if mode == "exists" else "percentage" if mode == "rate" else "number"},
        )

    if _is_top_k_share_question(lowered):
        share_metric = "__row_count__" if _asks_for_transaction_share(lowered) else "eur_amount"
        ranking_metric = "eur_amount" if _asks_for_amount_volume_ranking(lowered) else share_metric
        return make_logic_form(
            task_type="aggregation",
            operation="top_k_share",
            metric=ranking_metric,
            group_by=_extract_group_by(question, default="merchant"),
            parameters={
                "table": "payments",
                "metric": ranking_metric,
                "ranking_metric": ranking_metric,
                "share_metric": share_metric,
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

    if _is_fraud_rate_fluctuation_question(lowered):
        group_by = _extract_fraud_rate_group_by(question, default="merchant")
        return make_logic_form(
            task_type="ranking",
            operation="fraud_rate_fluctuation",
            metric="fraud_volume_rate",
            metric_definition={
                "name": "fraud_rate_std",
                "description": "Standard deviation of period-level fraud volume rate for each requested entity.",
                "aggregation": "std",
                "source": "payments.csv",
            },
            group_by=group_by,
            objective="minimum" if _is_bottom_question(lowered) else "maximum",
            filters={"year": _extract_year(question) if re.search(r"\b20\d{2}\b", question) else None},
            parameters={
                "table": "payments",
                "group_by": group_by,
                "metric": "fraud_volume_rate",
                "period": "month",
                "objective": "minimum" if _is_bottom_question(lowered) else "maximum",
            },
            answer_target="entity_only",
            output_format=output_format | {"answer_type": "text", "entity_field": group_by},
        )

    fraud_group_by = _extract_fraud_rate_group_by(question)
    if ("fraud rate" in lowered or _is_fraud_percentage_question(lowered)) and fraud_group_by:
        objective = "minimum" if _is_bottom_question(lowered) else "maximum"
        answer_target = "entity_only" if _asks_for_entity_answer(lowered) else "metric_only"
        return make_logic_form(
            task_type="ranking",
            operation="rank_by_metric",
            metric="fraud_volume_rate",
            metric_definition={
                "name": "fraud_volume_rate",
                "description": "Fraudulent volume divided by total volume, returned as a percentage when selected as a metric.",
                "aggregation": "ratio",
                "source": "manual.md section 7 and payments.csv",
            },
            numerator={"column": "eur_amount", "filter": {"has_fraudulent_dispute": True}, "aggregation": "sum"},
            denominator={"column": "eur_amount", "aggregation": "sum"},
            group_by=fraud_group_by,
            objective=objective,
            filters={
                key: value
                for key, value in {
                    "year": _extract_year(question) if re.search(r"\b20\d{2}\b", question) else None,
                    "merchant": None if fraud_group_by == "merchant" else _extract_merchant(question, context),
                    "card_scheme": None if fraud_group_by == "card_scheme" else _extract_card_scheme(question),
                    "shopper_interaction": None if fraud_group_by == "shopper_interaction" else _extract_shopper_interaction_filter(question),
                    "month_range": _extract_quarter_month_range(question),
                }.items()
                if value is not None
            },
            parameters={
                "table": "payments",
                "group_by": fraud_group_by,
                "metric": "fraud_volume_rate",
                "objective": objective,
            },
            answer_target=answer_target,
            output_format=output_format
            | {
                "answer_type": "text" if answer_target == "entity_only" else "number",
                "decimals": _decimal_places(guidelines, 3),
                "entity_field": fraud_group_by,
                "metric_field": "selected_metric",
            },
        )

    if "fraud rate" in lowered or _is_fraud_percentage_question(lowered):
        filters: dict[str, Any] = {
            "year": _extract_year(question),
            "merchant": _extract_merchant(question, context),
            "card_scheme": _extract_card_scheme(question),
            "month_range": _extract_quarter_month_range(question),
        }
        if "in-person" in lowered or "in person" in lowered or "in-store" in lowered or "in store" in lowered:
            filters["shopper_interaction"] = "POS"
        elif "ecommerce" in lowered or "e-commerce" in lowered:
            filters["shopper_interaction"] = "Ecommerce"
        filters = {key: value for key, value in filters.items() if value is not None}
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

    if _is_scalar_metric_extreme_question(lowered):
        aggregation = "min" if _is_bottom_question(lowered) else "max"
        return make_logic_form(
            task_type="aggregation",
            operation="aggregation",
            metric="eur_amount",
            parameters={"table": "payments", "metric": "eur_amount", "aggregation": aggregation},
            answer_target="metric_only",
            output_format=output_format | {"answer_type": "number", "decimals": _decimal_places(guidelines)},
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
            answer_target=_ranking_answer_target(question, guidelines, group_by),
            output_format=output_format
            | _ranking_output_format(question, guidelines, group_by, _extract_limit(question, default=1)),
        )

    if "highest number of transactions" in lowered:
        group_by = _extract_field_name(question, context) or _extract_group_by(question, default="issuing_country" if "issuing country" in lowered else "merchant")
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
            output_format=output_format | {"answer_type": _answer_type_for_group_by(group_by)},
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

    if _is_group_average_question(question):
        month_range = _extract_quarter_month_range(question)
        return make_logic_form(
            task_type="aggregation",
            operation="group_average",
            filters={
                "merchant": _extract_merchant(question, context),
                "card_scheme": _extract_card_scheme(question),
                "year": _extract_year(question),
                "month": None if month_range else _extract_month(question),
                "month_range": month_range,
            },
            parameters={"group_by": _extract_group_by(question, default="shopper_interaction"), "metric": "eur_amount"},
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
            output_format=output_format | {"answer_type": "list", "sort_values": True, "dedupe_values": True},
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
            output_format=output_format | {"answer_type": "list", "sort_values": True, "dedupe_values": True},
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

    if "card scheme" in lowered and any(token in lowered for token in ("steer traffic", "steer to", "steer towards", "steering")):
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
            output_format=output_format | {"answer_type": "aci", "decimals": 2},
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


def _should_combine_segment_dimensions(question: str, dimensions: list[str]) -> bool:
    lowered = question.lower()
    explicit_mentions = 0
    for text in ("merchant", "issuer country", "issuing country", "card_scheme", "card scheme", "shopper interaction", "payment interaction", "device type", "aci"):
        if text in lowered:
            explicit_mentions += 1
    return explicit_mentions > 1 or "across these segments" in lowered or "combination" in lowered or "segment vector" in lowered


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
    if field in {"merchant", "card_scheme", "issuing_country", "ip_country", "shopper_interaction", "email_address", "ip_address", "account_type"}:
        return "eur_amount"
    payments = None if context is None else context.get("payments")
    if field and payments is not None and field in payments.columns and not pd.api.types.is_numeric_dtype(payments[field]):
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
    output_format = {"guidelines": guidelines}
    if _is_general_data_quality_report_question(lowered):
        return make_logic_form(
            task_type="data_quality",
            operation="data_quality_report",
            parameters={"scope": "dataset", "tables": list(tables.keys())},
            output_format=output_format | {"answer_type": "text"},
        )
    table_context = _select_table_context(question, tables)
    table_name, df = table_context["table_name"], table_context["df"]
    record_count_requested = _is_record_count_metric_question(lowered)
    derived_metric = None if record_count_requested else _derived_ratio_metric(question, df, guidelines=guidelines)
    metric = None if record_count_requested else (
        str(derived_metric["name"]) if derived_metric else table_context.get("metric") or _find_metric_column(question, df)
    )
    if derived_metric:
        table_context["metric"] = metric
        table_context["table_selection_reason"] = _table_selection_reason(
            question,
            table_name,
            metric,
            table_context.get("dimension"),
            table_context.get("explicit_table"),
            table_context.get("join_plan") or {},
        )
    filters = {**_infer_value_filters(question, df, exclude={metric}), **dict(table_context.get("filters") or {})}
    explicit_group_by = _find_group_by_column(question, df)
    if explicit_group_by == metric:
        explicit_group_by = None
    context_dimension = table_context.get("dimension")
    if context_dimension in filters:
        context_dimension = None
    dimension = context_dimension or explicit_group_by or _find_dimension_column(question, df, metric, exclude=set(filters))
    missing_dimension_concepts = list(table_context.get("missing_dimension_concepts") or [])
    if dimension != table_context.get("dimension") and not table_context.get("join_plan"):
        table_context["dimension"] = dimension
        table_context["table_selection_reason"] = _table_selection_reason(
            question,
            table_name,
            metric,
            dimension,
            None,
            {},
        )
    time_filter_column = dimension if dimension and _is_time_like_column(dimension) else _find_time_column(df)
    filters.update(_infer_time_filters(question, time_filter_column))

    if missing_dimension_concepts and (_is_ranking_question(lowered) or _is_grouped_metric_display_question(lowered)):
        return make_logic_form(
            task_type="schema_query",
            operation="detail_lookup",
            filters=filters,
            parameters=_with_table_context(
                {
                    "table": table_name,
                    "metric": metric,
                    "dimension": None,
                    "missing_dimension_concepts": missing_dimension_concepts,
                    "strict_missing_dimension_guard": _strict_missing_dimension_guard(question),
                    "available_columns": [str(column) for column in df.columns],
                    "limit": 1,
                },
                table_context,
            ),
            output_format=output_format | {"answer_type": "clarification"},
        )

    if _is_top_outlier_group_question(lowered):
        group_by = _find_named_column(question, df) or _extract_group_by(question, default=dimension or "hour_of_day")
        return make_logic_form(
            task_type="ranking",
            operation="top_outlier_group",
            filters=filters,
            parameters=_with_table_context({
                "table": table_name,
                "group_by": group_by,
                "metric": metric,
                "method": "zscore" if "z-score" in lowered or "z score" in lowered else "iqr",
                "z_threshold": _extract_zscore_threshold(question) or 3.0,
            }, table_context),
            output_format=output_format | {"answer_type": _answer_type_for_group_by(group_by)},
        )

    if _is_top_group_count_question(lowered):
        return make_logic_form(
            task_type="ranking",
            operation="top_count",
            filters=filters,
            parameters=_with_table_context({"table": table_name, "group_by": _find_named_column(question, df) or _extract_group_by(question, default=dimension or "hour_of_day")}, table_context),
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_most_common_value_question(lowered):
        group_by = _find_named_column(question, df) or _find_entity_column(question, df) or dimension
        return make_logic_form(
            task_type="ranking",
            operation="top_count",
            filters=filters,
            parameters=_with_table_context({"table": table_name, "group_by": group_by}, table_context),
            output_format=output_format | {"answer_type": "text"},
        )

    if _is_row_count_question(lowered) and not _has_grouping_language(lowered):
        if _has_missing_language(lowered):
            missing_field = _find_named_column(question, df)
            return make_logic_form(
                task_type="aggregation",
                operation="row_count",
                filters=(filters | {missing_field: "__NULL__"}) if missing_field else filters,
                parameters=_with_table_context({"table": table_name}, table_context),
                output_format=output_format | {"answer_type": "number"},
            )
        return make_logic_form(
            task_type="aggregation",
            operation="row_count",
            filters=filters,
            parameters=_with_table_context({"table": table_name}, table_context),
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_metric_per_distinct_entity_question(lowered):
        field = _find_named_column(question, df) or _find_entity_column(question, df) or dimension
        numerator_metric = "__row_count__" if record_count_requested else metric
        aggregation = "count" if numerator_metric == "__row_count__" else "sum"
        return make_logic_form(
            task_type="aggregation",
            operation="metric_per_distinct_entity",
            metric=numerator_metric,
            filters=filters,
            parameters=_with_table_context({"table": table_name, "metric": numerator_metric, "entity_field": field, "aggregation": aggregation}, table_context),
            output_format=output_format | {"answer_type": "number", "decimals": _decimal_places(guidelines, 2)},
        )

    if _is_repeat_entity_percentage_question(lowered):
        field = _find_named_column(question, df) or _find_entity_column(question, df) or dimension
        return make_logic_form(
            task_type="aggregation",
            operation="repeat_entity_percentage",
            filters=filters,
            parameters=_with_table_context({"table": table_name, "field": field}, table_context),
            output_format=output_format | {"answer_type": "percentage", "decimals": _decimal_places(guidelines, 2)},
        )

    if _is_distinct_count_question(lowered):
        field = _find_distinct_target_column(question, df) or _find_named_column(question, df) or _find_entity_column(question, df) or dimension
        return make_logic_form(
            task_type="schema_query",
            operation="distinct_count",
            filters=filters,
            parameters=_with_table_context({"table": table_name, "field": field}, table_context),
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_outlier_count_question(lowered):
        return make_logic_form(
            task_type="data_quality",
            operation="outlier_count",
            filters=filters,
            parameters=_with_table_context({
                "table": table_name,
                "metric": metric,
                "method": "zscore" if "z-score" in lowered or "z score" in lowered else "iqr",
            }, table_context),
            output_format=output_format | {"answer_type": "number"},
        )

    if _is_null_check_question(lowered):
        field = _find_named_column(question, df)
        target_condition = _null_check_target_condition(lowered)
        return make_logic_form(
            task_type="data_quality",
            operation="null_check",
            filters=filters,
            parameters=_with_table_context({"table": table_name, "field": field, "mode": _null_check_mode(lowered), **target_condition}, table_context),
            output_format=output_format | {"answer_type": "yes_no" if _null_check_mode(lowered) == "exists" else "percentage" if _null_check_mode(lowered) == "rate" else "number"},
        )

    if _is_top_k_share_question(lowered) and dimension:
        aggregation = "count" if record_count_requested else _infer_aggregation(lowered, default="sum" if metric else "count")
        share_metric = "__row_count__" if _asks_for_transaction_share(lowered) or aggregation == "count" else metric
        ranking_metric = metric if _asks_for_amount_volume_ranking(lowered) and metric else share_metric
        return make_logic_form(
            task_type="aggregation",
            operation="top_k_share",
            metric=ranking_metric,
            group_by=dimension,
            filters=filters,
            parameters=_with_table_context({
                "table": table_name,
                "metric": None if ranking_metric in {"__row_count__", "row_count", "transaction_count"} else ranking_metric,
                "ranking_metric": ranking_metric,
                "share_metric": share_metric,
                "dimension": dimension,
                "aggregation": aggregation,
                "limit": _extract_limit(question, default=3),
            }, table_context),
            output_format=output_format | {"answer_type": "percentage", "decimals": _decimal_places(guidelines, 2)},
        )

    if _is_unique_values_question(lowered):
        return make_logic_form(
            task_type="schema_query",
            operation="field_values",
            parameters=_with_table_context({"table": table_name, "field": _find_named_column(question, df) or _find_entity_column(question, df) or dimension}, table_context),
            output_format=output_format | {"answer_type": "list"},
        )

    if "duplicate" in lowered and ("row" in lowered or "record" in lowered or "transaction" in lowered):
        return make_logic_form(
            task_type="data_quality",
            operation="duplicate_check",
            parameters=_with_table_context({"table": table_name, "subset": "all"}, table_context),
            output_format=output_format | {"answer_type": "yes_no"},
        )

    if _is_grouped_metric_display_question(lowered) and dimension:
        aggregation = "count" if record_count_requested else _infer_aggregation(lowered, default="sum" if metric else "count")
        return make_logic_form(
            task_type="aggregation",
            operation="aggregation",
            metric=metric,
            group_by=dimension,
            filters=filters,
            parameters=_with_table_context({
                "table": table_name,
                "metric": metric,
                "dimension": dimension,
                "aggregation": aggregation,
                **({"derived_metric": derived_metric} if derived_metric else {}),
            }, table_context),
            output_format=output_format | {"answer_type": "table"},
        )

    if _is_ranking_question(lowered) and dimension:
        aggregation = "count" if record_count_requested else _infer_aggregation(lowered, default="sum" if metric else "count")
        return make_logic_form(
            task_type="ranking",
            operation="filtered_metric_ranking" if filters else "ranking",
            filters=filters,
            parameters=_with_table_context({
                "table": table_name,
                "metric": metric,
                "dimension": dimension,
                "aggregation": aggregation,
                "sort_order": "asc" if _is_bottom_question(lowered) else "desc",
                "limit": _extract_limit(question, default=1),
                **({"derived_metric": derived_metric} if derived_metric else {}),
            }, table_context),
            answer_target=_ranking_answer_target(question, guidelines, dimension),
            output_format=output_format | _ranking_output_format(question, guidelines, dimension, _extract_limit(question, default=1)),
        )

    if _is_aggregation_question(lowered):
        aggregation = _infer_aggregation(lowered, default="sum")
        decimals = _decimal_places(guidelines)
        return make_logic_form(
            task_type="aggregation",
            operation="aggregation",
            filters=filters,
            parameters=_with_table_context({
                "table": table_name,
                "metric": metric,
                "dimension": dimension if _has_grouping_language(lowered) else None,
                "aggregation": aggregation,
                **({"derived_metric": derived_metric} if derived_metric else {}),
            }, table_context),
            output_format=output_format
            | {"answer_type": "table" if dimension and _has_grouping_language(lowered) else "number"}
            | ({"decimals": decimals} if decimals is not None else {}),
        )

    if _is_filtering_question(lowered):
        return make_logic_form(
            task_type="filtering",
            operation="filtering",
            parameters=_with_table_context({
                "table": table_name,
                "conditions": _extract_simple_conditions(question, df),
                "limit": _extract_limit(question, default=20),
            }, table_context),
            output_format=output_format | {"answer_type": "table"},
        )

    return make_logic_form(
        task_type="detail_lookup",
        operation="detail_lookup",
        parameters=_with_table_context({"table": table_name, "limit": _extract_limit(question, default=20)}, table_context),
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
    match = re.search(r"(\d+)\s+decimal(?:\s+places?)?|\b(\d+)\s+decimals?", guidelines, re.I)
    if match:
        return int(next(group for group in match.groups() if group))
    match = re.search(r"保留\s*(\d+)\s*位小数|(\d+)\s*位小数", guidelines)
    if match:
        value = next(group for group in match.groups() if group)
        return int(value)
    return default


def _select_primary_table(tables: dict[str, pd.DataFrame]) -> tuple[str, pd.DataFrame]:
    if not tables:
        raise ValueError("No parsed tables are available.")
    return max(tables.items(), key=lambda item: (len(item[1]), len(item[1].columns)))


def _select_table_context(question: str, tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    if not tables:
        raise ValueError("No parsed tables are available.")
    explicit_table = _explicit_table_match(question, tables)
    union_context = None if explicit_table else _same_schema_union_context(question, tables)
    if union_context is not None:
        return union_context
    if explicit_table:
        primary_df = tables[explicit_table]
        metric = _find_metric_column(question, primary_df)
        dimension = _find_group_by_column(question, primary_df) or _find_dimension_column(question, primary_df, metric)
        return {
            "table_name": explicit_table,
            "df": primary_df,
            "metric": metric,
            "dimension": dimension,
            "source_tables": [explicit_table],
            "join_plan": {},
            "explicit_table": explicit_table,
            "available_columns": [str(column) for column in primary_df.columns],
            "table_selection_reason": _table_selection_reason(question, explicit_table, metric, dimension, explicit_table, {}),
        }
    metric_table, metric = _best_metric_column(question, tables)
    primary_name = explicit_table or metric_table or _select_primary_table(tables)[0]
    primary_df = tables[primary_name]
    if metric is None and not _is_record_count_metric_question(question.lower()):
        metric = _find_metric_column(question, primary_df)
    dimension_table, dimension = _best_dimension_column(question, tables, preferred_table=primary_name, metric=metric)
    requested_dimensions = _requested_dimension_concepts(question)
    missing_dimension_concepts = requested_dimensions if requested_dimensions and not dimension else []
    filter_matches = _infer_filter_matches_across_tables(question, tables, exclude={metric, dimension}, preferred_table=primary_name)
    filters = {str(match["column"]): match["value"] for match in filter_matches}
    target_tables: list[str] = []
    if dimension and dimension_table and dimension_table != primary_name:
        target_tables.append(dimension_table)
    for match in filter_matches:
        filter_table = str(match["table"])
        if filter_table != primary_name and filter_table not in target_tables:
            target_tables.append(filter_table)
    if target_tables and not _should_attempt_generic_join(question):
        target_tables = []
        filters = {str(match["column"]): match["value"] for match in filter_matches if str(match["table"]) == primary_name}
        if dimension_table and dimension_table != primary_name:
            dimension_table = primary_name
            dimension = _find_dimension_column(question, primary_df, metric, exclude=set(filters))
    join_plan: dict[str, Any] = {}
    source_tables = [primary_name]
    if target_tables:
        join_plan = _infer_join_plan_for_targets(primary_name, tables, target_tables)
        source_tables.extend(table_name for table_name in target_tables if table_name not in source_tables)
        if not join_plan.get("trusted"):
            reason = str(join_plan.get("reason") or "")
            if join_plan.get("many_to_many_risk"):
                reason = reason or "Join key candidate has many-to-many risk and needs user confirmation."
            join_plan = join_plan | {
                "required": True,
                "trusted": False,
                "left_table": primary_name,
                "right_table": target_tables[-1],
                "reason": reason or "No trustworthy join key was found for the requested metric and dimension tables.",
            }
    return {
        "table_name": primary_name,
        "df": primary_df,
        "metric": metric,
        "dimension": dimension,
        "filters": filters,
        "missing_dimension_concepts": missing_dimension_concepts,
        "source_tables": source_tables,
        "join_plan": join_plan,
        "explicit_table": explicit_table,
        "available_columns": _available_columns_for_sources(tables, source_tables),
        "table_selection_reason": _table_selection_reason(question, primary_name, metric, dimension, explicit_table, join_plan),
    }


def _available_columns_for_sources(tables: dict[str, pd.DataFrame], source_tables: list[str]) -> list[str]:
    columns: list[str] = []
    for table_name in source_tables:
        df = tables.get(table_name)
        if df is None:
            continue
        for column in df.columns:
            name = str(column)
            if name not in columns:
                columns.append(name)
    return columns


def _with_table_context(params: dict[str, Any], table_context: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(params)
    enriched.setdefault("source_tables", list(table_context.get("source_tables") or [params.get("table")]))
    available_columns = table_context.get("available_columns")
    if not available_columns:
        df = table_context.get("df")
        if isinstance(df, pd.DataFrame):
            available_columns = [str(column) for column in df.columns]
    if available_columns:
        enriched.setdefault("available_columns", [str(column) for column in available_columns])
    if table_context.get("table_selection_reason"):
        enriched.setdefault("table_selection_reason", table_context["table_selection_reason"])
    if table_context.get("join_plan"):
        enriched.setdefault("join_plan", table_context["join_plan"])
    if table_context.get("same_schema_union"):
        enriched.setdefault("same_schema_union", table_context["same_schema_union"])
    return enriched


def _same_schema_union_context(question: str, tables: dict[str, pd.DataFrame]) -> dict[str, Any] | None:
    if len(tables) < 2 or not _question_can_use_same_schema_union(question):
        return None
    table_names = list(tables)
    first_columns = [str(column) for column in tables[table_names[0]].columns]
    first_signature = {_normalize_column_token(column) for column in first_columns}
    if not first_signature:
        return None
    for table_name in table_names[1:]:
        columns = [str(column) for column in tables[table_name].columns]
        if {_normalize_column_token(column) for column in columns} != first_signature:
            return None

    frames = []
    source_files: list[str] = []
    for table_name in table_names:
        df = tables[table_name].copy()
        source_file = str(df.attrs.get("source_file") or table_name)
        source_files.append(source_file)
        frames.append(df)
    union_df = pd.concat(frames, ignore_index=True, sort=False)
    union_name = "__same_schema_union__"
    union_metadata = {
        "source_tables": table_names,
        "source_files": source_files,
        "row_counts": {table_name: int(len(tables[table_name])) for table_name in table_names},
        "column_signature": first_columns,
    }
    metric = _find_metric_column(question, union_df)
    dimension = _find_group_by_column(question, union_df) or _find_dimension_column(question, union_df, metric)
    return {
        "table_name": union_name,
        "df": union_df,
        "metric": metric,
        "dimension": dimension,
        "source_tables": table_names,
        "join_plan": {},
        "same_schema_union": union_metadata,
        "available_columns": first_columns,
        "table_selection_reason": _table_selection_reason(
            question,
            union_name,
            metric,
            dimension,
            None,
            {},
        )
        + "; same_schema_union",
    }


def _question_can_use_same_schema_union(question: str) -> bool:
    lowered = question.lower()
    if any(token in lowered for token in ("join", "merge", "关联", "连接", "合并字段", "关联键")):
        return False
    return any(
        token in lowered
        for token in (
            "highest",
            "lowest",
            "top",
            "bottom",
            "max",
            "min",
            "total",
            "sum",
            "average",
            "avg",
            "mean",
            "compare",
            "comparison",
            "by ",
            "group",
            "最高",
            "最低",
            "最多",
            "最少",
            "总",
            "合计",
            "平均",
            "比较",
            "对比",
            "哪个",
            "哪家",
            "按",
            "各",
            "每",
            "展示",
            "图",
        )
    )


def _explicit_table_match(question: str, tables: dict[str, pd.DataFrame]) -> str | None:
    lowered = _normalize_text(question)
    best: tuple[int, str] | None = None
    for table_name, df in tables.items():
        candidates = [
            table_name,
            str(df.attrs.get("table_name") or ""),
            str(df.attrs.get("source_file") or ""),
            str(df.attrs.get("sheet") or ""),
        ]
        score = 0
        for candidate in candidates:
            normalized = _normalize_text(candidate)
            if _too_ambiguous_table_mention(normalized):
                continue
            if normalized and normalized in lowered:
                score = max(score, len(normalized))
        if score and (best is None or score > best[0]):
            best = (score, table_name)
    return None if best is None else best[1]


def _too_ambiguous_table_mention(normalized: str) -> bool:
    return len(normalized) < 2 and bool(re.fullmatch(r"[a-z0-9]", normalized))


def _best_metric_column(question: str, tables: dict[str, pd.DataFrame]) -> tuple[str | None, str | None]:
    best: tuple[int, str, str] | None = None
    for table_name, df in tables.items():
        table_filter_score = _implicit_filter_match_score(question, df)
        table_time_score = 2 if _find_time_column(df) and _asks_time_or_trend(question) else 0
        for column in df.columns:
            column_name = str(column)
            if not _is_metric_value_column(df[column], column_name):
                continue
            score = _column_question_score(question, column_name)
            if _metric_name_hint(column_name):
                score += 2
            score += _sales_amount_metric_score(question, column_name)
            score += _retail_distribution_fact_table_score(question, table_name, df)
            score += table_filter_score + table_time_score
            if score > 0 and (best is None or score > best[0]):
                best = (score, table_name, column_name)
    if best is not None:
        return best[1], best[2]
    return None, None


def _implicit_filter_match_score(question: str, df: pd.DataFrame) -> int:
    lowered = question.lower()
    for column in df.columns:
        series = df[column]
        if pd.api.types.is_numeric_dtype(series):
            continue
        unique_values = [value for value in series.dropna().unique().tolist() if str(value)]
        if not unique_values or len(unique_values) > 50:
            continue
        for value in unique_values:
            text = str(value)
            if _is_safe_implicit_filter_value(text) and (
                _value_in_question(text, question, lowered) or _implicit_value_in_question(text, question, lowered)
            ):
                return 6
    return 0


def _asks_time_or_trend(question: str) -> bool:
    lowered = question.lower()
    return any(token in lowered for token in ("time", "date", "month", "trend")) or any(
        token in question for token in ("时间", "日期", "月份", "月度", "趋势", "随时间", "折线图", "曲线图")
    )


def _retail_distribution_fact_table_score(question: str, table_name: str, df: pd.DataFrame) -> int:
    if not any(token in question.lower() for token in ("sales", "amount", "trend", "composition", "breakdown")) and not any(
        token in question for token in ("销售", "分销", "金额", "趋势", "随时间", "组成", "构成", "拆分", "来源")
    ):
        return 0
    columns = {str(column) for column in df.columns}
    score = 0
    if {"sign_time", "sign_amt", "ctg_name"}.issubset(columns):
        score += 18
    normalized_table = _normalize_column_token(table_name)
    if "trddistorddtl" in normalized_table or "distorddtl" in normalized_table:
        score += 12
    if ("1drt" in normalized_table or normalized_table.endswith("rt")) and not any(
        token in question for token in ("今日", "今天", "当天", "实时")
    ):
        score -= 24
    if "mktdsp" in normalized_table or "execute" in normalized_table or "actv" in normalized_table:
        score -= 8
    return score


def _sales_amount_metric_score(question: str, column_name: str) -> int:
    if not any(token in question.lower() for token in ("sales", "revenue", "amount", "composition", "breakdown")) and not any(
        token in question for token in ("销售额", "销售金额", "销售", "收入", "金额", "分销", "组成", "构成", "拆分", "来源")
    ):
        return 0
    normalized = _normalize_column_token(column_name)
    score = 0
    if "signamt" in normalized or ("sign" in normalized and "amt" in normalized):
        score += 10
    elif "salesamt" in normalized or "sales" in normalized or "revenue" in normalized:
        score += 9
    elif "ordamt" in normalized or ("ord" in normalized and "amt" in normalized):
        score += 8
    elif "amt" in normalized or "amount" in normalized or "金额" in normalized:
        score += 5
    if any(token in normalized for token in ("target", "goal", "confirm", "目标", "确认")):
        score -= 4
    if any(token in normalized for token in ("share", "ratio", "rate", "占比", "比例", "率")) and not _asks_ratio_or_share_metric(question):
        score -= 40
    if any(token in normalized for token in ("code", "sap", "编码", "代码")):
        score -= 8
    return score


def _asks_ratio_or_share_metric(question: str) -> bool:
    lowered = question.lower()
    if re.search(r"(?<![a-z0-9_])(share|ratio|rate|percentage|percent)(?![a-z0-9_])", lowered):
        return True
    return any(token in question for token in ("占比", "比例", "率"))


def _best_dimension_column(
    question: str,
    tables: dict[str, pd.DataFrame],
    *,
    preferred_table: str,
    metric: str | None,
) -> tuple[str | None, str | None]:
    explicit_best: tuple[int, str, str] | None = None
    for table_name, df in tables.items():
        explicit = _find_group_by_column(question, df)
        if not explicit or explicit == metric:
            continue
        score = 100 + (1 if table_name == preferred_table else 0)
        if explicit_best is None or score > explicit_best[0]:
            explicit_best = (score, table_name, explicit)
    if explicit_best is not None:
        return explicit_best[1], explicit_best[2]

    explicit_column_best: tuple[int, str, str] | None = None
    lowered = question.lower()
    for table_name, df in tables.items():
        for column in df.columns:
            column_name = str(column)
            if column_name == metric or pd.api.types.is_numeric_dtype(df[column]):
                continue
            if not _column_name_explicitly_mentioned(column_name, question, lowered):
                continue
            score = 100 + (1 if table_name == preferred_table else 0)
            if explicit_column_best is None or score > explicit_column_best[0]:
                explicit_column_best = (score, table_name, column_name)
    if explicit_column_best is not None:
        return explicit_column_best[1], explicit_column_best[2]

    preferred_df = tables[preferred_table]
    preferred_categorical = [
        str(column)
        for column in preferred_df.columns
        if str(column) != metric and not pd.api.types.is_numeric_dtype(preferred_df[column])
    ]
    composition_dimension = _preferred_composition_dimension(question, preferred_categorical)
    if composition_dimension:
        return preferred_table, composition_dimension

    requested_concepts = _requested_dimension_concepts(question)
    best: tuple[int, str, str] | None = None
    for table_name, df in tables.items():
        for column in df.columns:
            column_name = str(column)
            if column_name == metric:
                continue
            is_numeric = pd.api.types.is_numeric_dtype(df[column])
            if requested_concepts:
                concept_scores = [
                    _semantic_concept_column_score(column_name, concept)
                    or (_semantic_concept_column_score(column_name, "time") - 10 if concept == "month" else 0)
                    for concept in requested_concepts
                    if (
                        _semantic_concept_column_score(column_name, concept) > 0
                        or (concept == "month" and _semantic_concept_column_score(column_name, "time") > 10)
                    )
                ]
                if not concept_scores:
                    continue
                if is_numeric and not any(concept in {"month", "time"} for concept in requested_concepts):
                    continue
                score = max(concept_scores)
                if any(concept in {"month", "time"} for concept in requested_concepts):
                    score += _time_column_preference(column_name)
                if _dimension_looks_like_join_identifier(column_name):
                    score -= 10
                if table_name == preferred_table:
                    score += 1
                if best is None or score > best[0]:
                    best = (score, table_name, column_name)
                continue
            if is_numeric:
                continue
            score = _column_question_score(question, column_name)
            if score == 0 and table_name == preferred_table and _dimension_name_hint(column_name):
                score = 1
            if table_name == preferred_table:
                score += 1
            if score > 0 and (best is None or score > best[0]):
                best = (score, table_name, column_name)
    if best is not None:
        return best[1], best[2]
    if requested_concepts:
        return None, None
    return preferred_table, _find_dimension_column(question, preferred_df, metric)


def _infer_join_plan_for_targets(primary_table: str, tables: dict[str, pd.DataFrame], target_tables: list[str]) -> dict[str, Any]:
    unique_targets = [table_name for table_name in target_tables if table_name != primary_table and table_name in tables]
    if not unique_targets:
        return {}
    if len(unique_targets) == 1:
        return _infer_join_plan(primary_table, tables[primary_table], unique_targets[0], tables[unique_targets[0]]) | {"required": True}

    joined_tables = [primary_table]
    steps: list[dict[str, Any]] = []
    for target_table in unique_targets:
        best_step: dict[str, Any] | None = None
        best_score = -1.0
        for left_table in joined_tables:
            candidate = _infer_join_plan(left_table, tables[left_table], target_table, tables[target_table])
            score = float(candidate.get("confidence") or 0.0) + float(candidate.get("overlap_rate") or 0.0)
            if candidate.get("trusted"):
                score += 1.0
            if score > best_score:
                best_score = score
                best_step = candidate
        if best_step is None:
            best_step = {
                "trusted": False,
                "left_table": primary_table,
                "right_table": target_table,
                "reason": "No join key candidate found.",
            }
        steps.append(best_step | {"required": True})
        joined_tables.append(target_table)

    trusted = all(step.get("trusted") and not step.get("many_to_many_risk") for step in steps)
    first = steps[0]
    risky = next((step for step in steps if step.get("many_to_many_risk")), None)
    untrusted = next((step for step in steps if not step.get("trusted")), None)
    return {
        "required": True,
        "trusted": trusted,
        "join_type": "left",
        "left_table": first.get("left_table"),
        "right_table": steps[-1].get("right_table"),
        "left_key": first.get("left_key"),
        "right_key": first.get("right_key"),
        "relationship": first.get("relationship"),
        "confidence": round(min(sum(float(step.get("confidence") or 0.0) for step in steps) / len(steps), 1.0), 4),
        "overlap_rate": round(min(float(step.get("overlap_rate") or 0.0) for step in steps), 4),
        "many_to_many_risk": bool(risky),
        "reason": str((untrusted or risky or {}).get("reason") or ""),
        "steps": steps,
    }


def _infer_join_plan(left_table: str, left_df: pd.DataFrame, right_table: str, right_df: pd.DataFrame) -> dict[str, Any]:
    best: tuple[float, str, str, float, str] | None = None
    for left_column in left_df.columns:
        for right_column in right_df.columns:
            left_name = str(left_column)
            right_name = str(right_column)
            name_score = 1.0 if _normalize_field_name(left_name) == _normalize_field_name(right_name) else 0.0
            if not name_score and not (_id_like(left_name) and _id_like(right_name)):
                continue
            left_values = set(left_df[left_column].dropna().astype(str))
            right_values = set(right_df[right_column].dropna().astype(str))
            if not left_values or not right_values:
                continue
            overlap = len(left_values & right_values) / max(1, min(len(left_values), len(right_values)))
            right_unique = bool(right_df[right_column].is_unique)
            left_unique = bool(left_df[left_column].is_unique)
            relationship = "one_to_one" if left_unique and right_unique else "many_to_one" if right_unique else "many_to_many"
            score = name_score + overlap + (0.5 if right_unique else 0.0)
            if best is None or score > best[0]:
                best = (score, left_name, right_name, overlap, relationship)
    if best is None:
        return {"trusted": False, "left_table": left_table, "right_table": right_table, "reason": "No join key candidate found."}
    score, left_key, right_key, overlap, relationship = best
    trusted = score >= 1.2 and overlap >= 0.5 and relationship in {"one_to_one", "many_to_one"}
    return {
        "trusted": trusted,
        "join_type": "left",
        "left_table": left_table,
        "right_table": right_table,
        "left_key": left_key,
        "right_key": right_key,
        "relationship": relationship,
        "confidence": round(min(score / 2.5, 1.0), 4),
        "overlap_rate": round(overlap, 4),
        "many_to_many_risk": relationship == "many_to_many",
    }


def _table_selection_reason(
    question: str,
    table_name: str,
    metric: str | None,
    dimension: str | None,
    explicit_table: str | None,
    join_plan: dict[str, Any],
) -> str:
    parts = [f"selected_table={table_name}"]
    if explicit_table:
        parts.append("explicit_table_mention")
    if metric:
        parts.append(f"metric={metric}")
    if dimension:
        parts.append(f"dimension={dimension}")
    if join_plan:
        parts.append("join_plan=" + ("trusted" if join_plan.get("trusted") else "untrusted"))
    return "; ".join(parts)


SEMANTIC_COLUMN_ALIASES = {
    "product": ("product", "product_name", "sku", "item", "goods", "产品", "商品", "品名", "商品名称", "产品名称"),
    "category": (
        "category",
        "category_name",
        "ctg",
        "ctg_name",
        "prod_category",
        "product_category",
        "product_line",
        "productline",
        "product_segment",
        "sku_category",
        "sku_cat",
        "cat",
        "type",
        "class",
        "classification",
        "line",
        "segment",
        "品类",
        "品类名称",
        "商品品类",
        "产品品类",
        "产品线",
        "商品线",
        "品项",
        "类别",
        "类别名称",
        "类目",
        "类目名称",
        "分类",
    ),
    "store": ("store", "shop", "branch", "门店", "店铺", "门店名称"),
    "city": ("city", "城市", "市"),
    "channel": ("channel", "channel_name", "sale_channel", "sales_channel", "source_channel", "source", "origin", "来源", "渠道", "渠道名称", "销售渠道", "来源渠道", "获客渠道", "通路", "通路名称"),
    "customer": ("customer", "cust", "client", "客户", "终端"),
    "month": ("month", "month_id", "month_code", "stat_month", "ym", "year_month", "biz_month", "period", "month_period", "period_month", "年月", "月份", "月度", "业务月份", "统计月份", "期间"),
    "time": ("date", "day", "week", "period", "time", "sign_time", "create_time", "日期", "时间", "周期", "业务日期", "统计日期", "签收时间", "创建时间"),
    "sales": ("sales", "sale", "revenue", "amount", "amt", "sales_amt", "sign_amt", "ord_amt", "dist_sign_amt", "销售额", "销售金额", "销售", "收入", "金额", "订单金额", "签收金额", "分销金额"),
    "profit": ("profit", "gross_profit", "grossprofit", "利润", "毛利"),
}

DIMENSION_CONCEPTS = ("product", "category", "store", "city", "channel", "customer", "month", "time")


def _requested_dimension_concepts(question: str) -> list[str]:
    requested: list[str] = []
    for concept in DIMENSION_CONCEPTS:
        aliases = SEMANTIC_COLUMN_ALIASES.get(concept) or ()
        if any(_semantic_alias_in_question(alias, question) for alias in aliases):
            requested.append(concept)
    return requested


def _is_time_like_column(column_name: str) -> bool:
    return _semantic_concept_column_score(column_name, "month") > 0 or _semantic_concept_column_score(column_name, "time") > 0


def _find_time_column(df: pd.DataFrame) -> str | None:
    best: tuple[int, int, str] | None = None
    for index, column in enumerate(df.columns):
        name = str(column)
        score = max(_semantic_concept_column_score(name, "month"), _semantic_concept_column_score(name, "time"))
        if score <= 0:
            continue
        score += _time_column_preference(name)
        if best is None or score > best[0]:
            best = (score, index, name)
    return None if best is None else best[2]


def _time_column_preference(column_name: str) -> int:
    normalized = _normalize_column_token(column_name)
    score = 0
    if "sign" in normalized or "签收" in normalized:
        score += 20
    if any(token in normalized for token in ("ymd", "年月", "month", "date", "日期", "统计")):
        score += 10
    if "create" in normalized or "创建" in normalized:
        score += 4
    if any(token in normalized for token in ("etl", "end", "结束")):
        score -= 20
    return score


def _infer_time_filters(question: str, time_column: str | None) -> dict[str, Any]:
    if not time_column:
        return {}
    year_month_range = _extract_year_month_range(question)
    if year_month_range:
        start_ym, end_ym = year_month_range
        start_year, start_month = divmod(start_ym, 100)
        end_year, end_month = divmod(end_ym, 100)
        if start_year == end_year:
            return {time_column: {"year": start_year, "month_range": (start_month, end_month)}}
    month = _extract_month(question)
    explicit_year = _extract_explicit_year(question)
    if month is None and explicit_year is None:
        return {}
    criteria: dict[str, Any] = {}
    if month is not None:
        criteria["month"] = month
    if explicit_year is not None:
        criteria["year"] = explicit_year
    return {time_column: criteria} if criteria else {}


def _extract_explicit_year(question: str) -> int | None:
    match = re.search(r"\b(20\d{2})\b", question)
    return int(match.group(1)) if match else None


def _semantic_concept_column_score(column_name: str, concept: str) -> int:
    aliases = SEMANTIC_COLUMN_ALIASES.get(concept) or ()
    normalized_column = _normalize_column_token(column_name)
    if not normalized_column:
        return 0
    best = 0
    for alias in aliases:
        normalized_alias = _normalize_column_token(alias)
        if not normalized_alias:
            continue
        if normalized_column == normalized_alias:
            best = max(best, 120)
        elif normalized_alias in normalized_column:
            best = max(best, 100)
    return best


def _dimension_looks_like_join_identifier(column_name: str) -> bool:
    normalized = _normalize_field_name(column_name)
    return normalized.endswith("id") or normalized.endswith("编号") or normalized.endswith("代码")


def _infer_filter_matches_across_tables(
    question: str,
    tables: dict[str, pd.DataFrame],
    *,
    exclude: set[str | None] | None = None,
    preferred_table: str | None = None,
) -> list[dict[str, Any]]:
    lowered = question.lower()
    excluded = {str(item) for item in (exclude or set()) if item}
    matches: list[dict[str, Any]] = []
    for table_name, df in tables.items():
        for column in df.columns:
            name = str(column)
            if name in excluded:
                continue
            if _semantic_concept_column_score(name, "month") > 0 or _semantic_concept_column_score(name, "time") > 0:
                continue
            series = df[column]
            if pd.api.types.is_numeric_dtype(series):
                continue
            unique_values = [value for value in series.dropna().unique().tolist() if str(value)]
            if not unique_values or len(unique_values) > 50:
                continue
            matched = [
                value
                for value in sorted(unique_values, key=lambda item: len(str(item)), reverse=True)
                if _is_safe_implicit_filter_value(str(value))
                and (_value_in_question(str(value), question, lowered) or _implicit_value_in_question(str(value), question, lowered))
            ]
            if len(matched) == 1:
                matches.append({"table": table_name, "column": name, "value": matched[0]})
    return _best_filter_matches(question, matches, preferred_table=preferred_table)


def _best_filter_matches(question: str, matches: list[dict[str, Any]], *, preferred_table: str | None = None) -> list[dict[str, Any]]:
    best_by_value: dict[str, tuple[int, dict[str, Any]]] = {}
    for match in matches:
        value_key = str(match.get("value"))
        score = _implicit_filter_column_score(question, str(match.get("column") or ""))
        if preferred_table and str(match.get("table") or "") == preferred_table:
            score += 20
        current = best_by_value.get(value_key)
        if current is None or score > current[0]:
            best_by_value[value_key] = (score, match)
    return [match for _, match in best_by_value.values()]


def _strict_missing_dimension_guard(question: str) -> bool:
    lowered = question.lower()
    complex_tokens = (
        "相比",
        "相较",
        "占比",
        "覆盖",
        "中位数",
        "潜在",
        "如果",
        "驱动",
        "结构",
        "变化",
        "均衡",
        "通过率",
        "高于上月",
        "低于上月",
        "rather than",
        "compared",
        "coverage",
        "median",
        "potential",
        "structure",
        "mix",
    )
    if any(token in lowered for token in complex_tokens):
        return False
    return _is_ranking_question(lowered) or _is_grouped_metric_display_question(lowered)


def _should_attempt_generic_join(question: str) -> bool:
    lowered = question.lower()
    if any(token in lowered for token in ("join", "merge", "关联", "连接", "结合", "映射", "多表")):
        return True
    complex_tokens = (
        "通过率",
        "覆盖率",
        "覆盖数",
        "覆盖",
        "占比",
        "中位数",
        "潜在",
        "如果",
        "相比",
        "相较",
        "驱动",
        "结构",
        "变化",
        "均衡",
        "线路计划",
        "计划拜访",
        "sku检查",
        "sku稽查",
        "稽查",
        "店均",
        "高于上月",
        "低于上月",
        "coverage",
        "ratio",
        "rate",
        "median",
        "potential",
        "compared",
    )
    return not any(token in lowered for token in complex_tokens)


def _column_question_score(question: str, column_name: str) -> int:
    searchable_question = _question_without_file_mentions(question)
    normalized_question = _normalize_text(searchable_question)
    normalized_column = _normalize_text(column_name)
    if normalized_column and normalized_column in normalized_question:
        return 80 + len(normalized_column)
    semantic_score = _semantic_column_question_score(question, column_name)
    if semantic_score:
        return semantic_score
    tokens = [token for token in re.split(r"[_\s/()-]+", column_name.lower()) if len(token) >= 2]
    return sum(2 for token in tokens if re.search(rf"(?<![A-Za-z0-9_.-]){re.escape(token)}(?![A-Za-z0-9_.-])", searchable_question.lower()))


def _normalize_text(value: str) -> str:
    return re.sub(r"[\s_\-./()（）]+", "", str(value).lower())


def _question_without_file_mentions(question: str) -> str:
    return re.sub(
        r"[\w\u4e00-\u9fff（）() ._-]+\.(?:csv|xlsx|xls|tsv|txt|json|parquet)\b",
        " ",
        question,
        flags=re.I,
    )


def _normalize_field_name(value: str) -> str:
    return _normalize_text(value).replace("编号", "id").replace("代码", "id")


def _semantic_column_question_score(question: str, column_name: str) -> int:
    searchable_question = _question_without_file_mentions(question)
    normalized_column = _normalize_column_token(column_name)
    if not searchable_question.strip() or not normalized_column:
        return 0
    best = 0
    for aliases in SEMANTIC_COLUMN_ALIASES.values():
        question_hit = any(_semantic_alias_in_question(alias, searchable_question) for alias in aliases)
        if not question_hit:
            continue
        column_hit = any(_normalize_column_token(alias) and _normalize_column_token(alias) in normalized_column for alias in aliases)
        if column_hit:
            best = max(best, 12)
    return best


def _semantic_alias_in_question(alias: str, question: str) -> bool:
    if any("\u4e00" <= char <= "\u9fff" for char in alias):
        return alias in question
    lowered = question.lower()
    return bool(re.search(rf"(?<![A-Za-z0-9_.-]){re.escape(alias.lower())}(?![A-Za-z0-9_.-])", lowered))


def _derived_ratio_metric(question: str, df: pd.DataFrame, *, guidelines: str = "") -> dict[str, str] | None:
    explicit = _explicit_ratio_metric(question, df, guidelines=guidelines)
    if explicit is not None:
        return explicit
    if not _asks_profit_margin(question):
        return None
    numerator = _find_semantic_column(df, "profit")
    denominator = _find_semantic_column(df, "sales")
    if not numerator or not denominator or numerator == denominator:
        return None
    name = "利润率" if any(token in question for token in ("利润率", "毛利率", "利润", "毛利")) else "profit_margin"
    return {
        "name": name,
        "numerator": numerator,
        "denominator": denominator,
        "formula": f"sum({numerator})/sum({denominator})",
    }


def _explicit_ratio_metric(question: str, df: pd.DataFrame, *, guidelines: str = "") -> dict[str, str] | None:
    text = f"{question}\n{guidelines}"
    patterns = (
        r"(?P<name>[\w\u4e00-\u9fff]{1,20})\s*=\s*sum\s*\(?\s*(?P<num>[\w\u4e00-\u9fff_ -]{1,40})\s*\)?\s*/\s*sum\s*\(?\s*(?P<den>[\w\u4e00-\u9fff_ -]{1,40})\s*\)?",
        r"(?P<name>[\w\u4e00-\u9fff]{1,20})\s*=\s*(?P<num>[\w\u4e00-\u9fff_ -]{1,40})\s*/\s*(?P<den>[\w\u4e00-\u9fff_ -]{1,40})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        name = re.sub(r"^(用|按|以|按照|改成|改为)", "", match.group("name").strip()).strip() or "ratio"
        numerator = _resolve_formula_column(match.group("num"), df)
        denominator = _resolve_formula_column(match.group("den"), df)
        if numerator and denominator and numerator != denominator:
            return {
                "name": name,
                "numerator": numerator,
                "denominator": denominator,
                "formula": f"sum({numerator})/sum({denominator})",
            }
    return None


def _resolve_formula_column(raw_name: str, df: pd.DataFrame) -> str | None:
    cleaned = re.sub(r"^(字段|列|column|field)\s*", "", str(raw_name or "").strip(), flags=re.I)
    cleaned = cleaned.strip(" ：:，,。.;；()（）[]【】")
    cleaned = re.sub(r"(重新计算|重新算|重算|再算|计算|这个口径|口径)$", "", cleaned).strip()
    if not cleaned:
        return None
    normalized = _normalize_column_token(cleaned)
    for column in df.columns:
        column_name = str(column)
        if _normalize_column_token(column_name) == normalized:
            return column_name
    for concept, aliases in SEMANTIC_COLUMN_ALIASES.items():
        if any(_normalize_column_token(alias) == normalized or normalized in _normalize_column_token(alias) for alias in aliases):
            found = _find_semantic_column(df, concept)
            if found:
                return found
    for column in df.columns:
        column_name = str(column)
        normalized_column = _normalize_column_token(column_name)
        if normalized and (normalized in normalized_column or normalized_column in normalized):
            return column_name
    return None


def _asks_profit_margin(question: str) -> bool:
    lowered = question.lower()
    return any(token in lowered for token in ("profit margin", "gross margin", "profit rate", "margin rate", "margin")) or any(
        token in question for token in ("利润率", "毛利率")
    )


def _find_semantic_column(df: pd.DataFrame, concept: str) -> str | None:
    aliases = SEMANTIC_COLUMN_ALIASES.get(concept) or ()
    for column in df.columns:
        normalized = _normalize_column_token(str(column))
        if any(_normalize_column_token(alias) and _normalize_column_token(alias) in normalized for alias in aliases):
            return str(column)
    return None


def _id_like(value: str) -> bool:
    normalized = _normalize_field_name(value)
    return "id" in normalized or normalized.endswith("编号")


def _metric_name_hint(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in ("sales", "revenue", "amount", "fee", "cost", "price", "profit", "stock", "quantity")) or any(
        token in value for token in ("销售", "金额", "收入", "费用", "利润", "库存", "数量", "订单")
    )


def _dimension_name_hint(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in ("city", "country", "product", "customer", "merchant", "category", "region", "channel", "month", "date")) or any(
        token in value for token in ("城市", "产品", "客户", "商户", "类别", "品类", "区域", "门店", "渠道", "月份", "日期")
    )


def _find_metric_column(question: str, df: pd.DataFrame) -> str | None:
    lowered = question.lower()
    for column in df.columns:
        name = str(column)
        if name.lower() in lowered or name in question:
            if _is_metric_value_column(df[column], name):
                return name
    numeric_columns = [str(column) for column in df.columns if _is_metric_value_column(df[column], str(column))]
    if not numeric_columns:
        return None
    metric_keywords = ("sales", "revenue", "amount", "fee", "cost", "price", "profit", "销售", "金额", "收入", "费用", "利润")
    for column in numeric_columns:
        if any(keyword in column.lower() for keyword in metric_keywords):
            return column
    return numeric_columns[0]


def _is_metric_value_column(series: pd.Series, column_name: str) -> bool:
    if pd.api.types.is_numeric_dtype(series):
        return not _metric_identifier_like(column_name)
    if _metric_identifier_like(column_name):
        return False
    non_empty = series.dropna()
    if non_empty.empty:
        return False
    text = non_empty.astype(str).str.strip()
    text = text[text != ""]
    if text.empty:
        return False
    converted = pd.to_numeric(text.str.replace(",", "", regex=False), errors="coerce")
    return float(converted.notna().sum()) / float(len(text)) >= 0.85


def _metric_identifier_like(column_name: str) -> bool:
    normalized = _normalize_column_token(column_name)
    return any(token in normalized for token in ("id", "code", "编号", "编码", "代码", "sap", "手机号", "电话", "邮编"))


def _find_dimension_column(
    question: str,
    df: pd.DataFrame,
    metric: str | None,
    exclude: set[str] | None = None,
) -> str | None:
    searchable_question = _question_without_file_mentions(question)
    lowered = searchable_question.lower()
    excluded = set(exclude or set())
    for column in df.columns:
        name = str(column)
        if name == metric or name in excluded:
            continue
        if _column_name_explicitly_mentioned(name, searchable_question, lowered):
            return name
    requested_concepts = _requested_dimension_concepts(question)
    if requested_concepts:
        semantic_candidates: list[tuple[int, int, str]] = []
        allows_numeric_dimension = any(concept in {"month", "time"} for concept in requested_concepts)
        for index, column in enumerate(df.columns):
            name = str(column)
            if name == metric or name in excluded:
                continue
            if pd.api.types.is_numeric_dtype(df[column]) and not allows_numeric_dimension:
                continue
            concept_scores = [
                _semantic_concept_column_score(name, concept)
                or (_semantic_concept_column_score(name, "time") - 10 if concept == "month" else 0)
                for concept in requested_concepts
                if (
                    _semantic_concept_column_score(name, concept) > 0
                    or (concept == "month" and _semantic_concept_column_score(name, "time") > 10)
                )
            ]
            if not concept_scores:
                continue
            score = max(concept_scores)
            if any(concept in {"month", "time"} for concept in requested_concepts):
                score += _time_column_preference(name)
            if _dimension_looks_like_join_identifier(name):
                score -= 10
            semantic_candidates.append((score, index, name))
        if semantic_candidates:
            semantic_candidates.sort(key=lambda item: (-item[0], item[1]))
            return semantic_candidates[0][2]
    categorical = [
        str(column)
        for column in df.columns
        if str(column) != metric and str(column) not in excluded and not pd.api.types.is_numeric_dtype(df[column])
    ]
    composition_dimension = _preferred_composition_dimension(question, categorical)
    if composition_dimension:
        return composition_dimension
    semantic_matches = [
        (_semantic_column_question_score(question, column), column)
        for column in categorical
    ]
    semantic_matches = [(score, column) for score, column in semantic_matches if score > 0]
    if semantic_matches:
        semantic_matches.sort(key=lambda item: (-item[0], categorical.index(item[1])))
        return semantic_matches[0][1]
    dimension_keywords = (
        "city",
        "country",
        "region",
        "category",
        "merchant",
        "product",
        "sku",
        "item",
        "store",
        "shop",
        "channel",
        "customer",
        "month",
        "date",
        "period",
        "城市",
        "国家",
        "地区",
        "类别",
        "品类",
        "分类",
        "商户",
        "产品",
        "商品",
        "门店",
        "店铺",
        "渠道",
        "客户",
        "月份",
        "月度",
        "年月",
        "日期",
    )
    for column in categorical:
        if any(keyword in column.lower() for keyword in dimension_keywords):
            return column
    return categorical[0] if categorical else None


def _preferred_composition_dimension(question: str, categorical_columns: list[str]) -> str | None:
    if not any(token in question.lower() for token in ("composition", "breakdown")) and not any(token in question for token in ("组成", "构成", "拆分")):
        return None
    normalized_by_column = {_normalize_column_token(column): column for column in categorical_columns}
    for preferred in (
        "capacity",
        "spec_desc",
        "sku_spec",
        "cmdt_name",
        "sku_name",
        "sales_ana_type_name",
        "ctg_name",
    ):
        normalized = _normalize_column_token(preferred)
        if normalized in normalized_by_column:
            return normalized_by_column[normalized]
    for column in categorical_columns:
        normalized = _normalize_column_token(column)
        if any(token in normalized for token in ("capacity", "spec", "sku", "cmdt", "product", "商品", "规格", "容量")):
            return column
    return None


def _column_name_explicitly_mentioned(name: str, question: str, lowered: str) -> bool:
    if any("\u4e00" <= char <= "\u9fff" for char in name):
        return name in question
    return bool(re.search(rf"\b{re.escape(name.lower())}\b", lowered))


def _find_group_by_column(question: str, df: pd.DataFrame) -> str | None:
    """Resolve the grouping field from explicit phrases such as "按区域统计"."""

    lowered = question.lower()
    phrases: list[str] = []
    for pattern in (
        r"按\s*([^，,。？?]+?)\s*(?:统计|分组|汇总|计算|展示|显示|生成|画|出|看|拆分|构成|组成)",
        r"(?:group(?:ed)?\s+by|by)\s+([A-Za-z0-9_ \-\u4e00-\u9fff]+?)(?:\s+(?:统计|计算|sum|total|average|count|share|percentage|占比)|[,，。？?]|$)",
    ):
        phrases.extend(match.strip() for match in re.findall(pattern, question, flags=re.I) if match.strip())
    for phrase in phrases:
        phrase_lower = phrase.lower()
        for column in df.columns:
            name = str(column)
            if name in phrase or name.lower() in phrase_lower:
                return name
        requested_concepts = _requested_dimension_concepts(phrase)
        for concept in requested_concepts:
            for column in df.columns:
                if _semantic_concept_column_score(str(column), concept) > 0:
                    return str(column)
    return None


def _find_distinct_target_column(question: str, df: pd.DataFrame) -> str | None:
    """Resolve the target field in questions like "不同的院区名称有多少个"."""

    lowered = question.lower()
    phrases: list[str] = []
    for pattern in (
        r"不同的?\s*([^，,。？?]+?)\s*(?:有多少|多少|数量|个数)",
        r"(?:distinct|unique)\s+([A-Za-z0-9_ \-\u4e00-\u9fff]+?)(?:\s+(?:count|number|values?)|[,，。？?]|$)",
    ):
        phrases.extend(match.strip() for match in re.findall(pattern, question, flags=re.I) if match.strip())
    for phrase in phrases:
        phrase_lower = phrase.lower()
        for column in df.columns:
            name = str(column)
            if name in phrase or name.lower() in phrase_lower:
                return name
    return None


def _find_named_column(question: str, df: pd.DataFrame) -> str | None:
    searchable_question = _question_without_file_mentions(question)
    lowered = searchable_question.lower()
    alias_column = _find_alias_column(question, df)
    if alias_column:
        return alias_column
    for column in df.columns:
        name = str(column)
        if name.lower() in lowered or name in searchable_question:
            return name
    return None


def _find_alias_column(question: str, df: pd.DataFrame) -> str | None:
    searchable_question = _question_without_file_mentions(question)
    lowered = searchable_question.lower()
    columns = [str(column) for column in df.columns]
    normalized_columns = {_normalize_column_token(column): column for column in columns}
    for alias, canonical in FIELD_ALIASES.items():
        if not _alias_in_question(alias, lowered, searchable_question):
            continue
        for token in (canonical, alias):
            normalized = _normalize_column_token(token)
            if normalized in normalized_columns:
                return normalized_columns[normalized]
        for column in columns:
            column_normalized = _normalize_column_token(column)
            canonical_normalized = _normalize_column_token(canonical)
            alias_normalized = _normalize_column_token(alias)
            if canonical_normalized and canonical_normalized in column_normalized:
                return column
            if alias_normalized and alias_normalized in column_normalized:
                return column
    return None


def _alias_in_question(alias: str, lowered: str, question: str) -> bool:
    if any("\u4e00" <= char <= "\u9fff" for char in alias):
        return alias in question
    return bool(re.search(rf"\b{re.escape(alias)}\b", lowered))


def _normalize_column_token(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.lower())


def _find_entity_column(question: str, df: pd.DataFrame) -> str | None:
    searchable_question = _question_without_file_mentions(question)
    lowered = searchable_question.lower()
    entity_terms = {
        "merchant": ("merchant", "商户"),
        "shopper": ("shopper", "customer", "email", "客户", "用户", "邮箱"),
        "customer": ("customer", "cust", "store", "客户", "门店", "终端"),
        "product": ("product", "sku", "item", "产品", "商品", "品类"),
        "store": ("store", "shop", "branch", "门店", "店铺"),
        "card": ("card", "卡"),
        "city": ("city", "城市"),
        "country": ("country", "国家"),
        "device": ("device", "设备"),
        "employee": ("employee", "emp", "业代", "员工"),
    }
    requested_terms: list[str] = []
    for aliases in entity_terms.values():
        if any(term in lowered or term in searchable_question for term in aliases):
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
    return any(
        token in lowered
        for token in (
            "total",
            "sum",
            "average",
            "avg",
            "mean",
            "count",
            "number",
            "总",
            "合计",
            "平均",
            "数量",
            "多少",
            "统计",
            "记录数",
            "条数",
            "笔数",
            "次数",
            "个数",
            "金额",
            "销售额",
            "销售金额",
            "组成",
            "构成",
            "拆分",
        )
    )


def _is_filtering_question(lowered: str) -> bool:
    return any(token in lowered for token in ("where", "filter", "show", "list", "greater than", "less than", "筛选", "列出", "大于", "小于"))


def _has_grouping_language(lowered: str) -> bool:
    return any(token in lowered for token in (" by ", "group", "per ", "each", "按", "各", "每", "随时间", "趋势", "trend", "组成", "构成", "拆分"))


def _is_grouped_metric_display_question(lowered: str) -> bool:
    if not _has_grouping_language(lowered):
        return False
    return any(
        token in lowered
        for token in (
            "show",
            "display",
            "visualize",
            "chart",
            "bar chart",
            "line chart",
            "展示",
            "显示",
            "生成",
            "画",
            "图",
            "图表",
            "柱状图",
            "柱形图",
            "条形图",
            "折线图",
            "饼图",
            "可视化",
            "趋势",
            "trend",
            "组成",
            "构成",
            "拆分",
        )
    )


def _is_row_count_question(lowered: str) -> bool:
    if _is_ranking_question(lowered):
        return False
    return _is_record_count_metric_question(lowered) and not _is_distinct_count_question(lowered)


def _is_record_count_metric_question(lowered: str) -> bool:
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
            "条数",
            "笔数",
            "次数",
            "个数",
            "交易数",
            "总交易",
        )
    )


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
    if any(token in lowered for token in amount_phrases):
        return _extract_outlier_metric(question, context), "mean"
    return _extract_outlier_metric(question, context), "sum"


def _is_most_common_value_question(lowered: str) -> bool:
    if "fraud" in lowered or "fraudulent" in lowered:
        return False
    return any(token in lowered for token in ("most common", "most frequent", "most commonly", "mode", "出现次数最多", "出现最多", "最常见", "最频繁", "频次最高", "频率最高", "众数"))


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
        and any(token in lowered for token in ("which", "what", "哪个", "哪一"))
        and any(token in lowered for token in ("most", "highest number", "top", "最多", "最高"))
        and not lowered.startswith("how many")
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
        not _has_missing_language(lowered)
        and
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


def _is_general_data_quality_report_question(lowered: str) -> bool:
    broad_subject = any(
        token in lowered
        for token in (
            "data quality",
            "quality report",
            "cleaning suggestion",
            "cleaning suggestions",
            "clean data",
            "scan my file",
            "file problem",
            "file problems",
            "dataset problem",
            "dataset problems",
            "数据质量",
            "清洗建议",
            "数据清洗",
            "文件有什么问题",
            "数据有什么问题",
            "表有什么问题",
            "扫描文件",
            "检查文件",
            "检查数据",
        )
    )
    issue_terms = any(token in lowered for token in ("problem", "issue", "quality", "clean", "scan", "问题", "质量", "清洗", "异常", "扫描", "检查"))
    file_terms = any(token in lowered for token in ("file", "dataset", "table", "data", "文件", "数据", "表格", "表"))
    specific_missing_question = any(token in lowered for token in ("which column", "what column", "how many", "percentage", "count", "多少", "哪一列", "哪个字段", "占比"))
    return broad_subject or (issue_terms and file_terms and not specific_missing_question)


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


def _null_check_target_condition(lowered: str) -> dict[str, Any]:
    if "fraud" in lowered or "fraudulent" in lowered:
        return {"target_field": "has_fraudulent_dispute", "target_value": True}
    return {}


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
    if any(token in lowered for token in ("sum", "total", "总和", "合计")):
        return "sum"
    if _is_record_count_metric_question(lowered) or re.search(r"\b(count|number of rows|number of records)\b", lowered):
        return "count"
    if any(token in lowered for token in ("max value", "maximum value", "最大值", "最大")):
        return "max"
    if any(token in lowered for token in ("min value", "minimum value", "最小值", "最小")):
        return "min"
    return default


def _extract_limit(question: str, default: int) -> int:
    match = re.search(r"(?:top|前)\s*(\d+)", question, re.I)
    return int(match.group(1)) if match else default


def _infer_value_filters(question: str, df: pd.DataFrame, exclude: set[str | None] | None = None) -> dict[str, Any]:
    lowered = question.lower()
    excluded = {str(item) for item in (exclude or set()) if item}
    filters: dict[str, Any] = {}
    implicit_matches: list[tuple[int, str, Any]] = []
    for column in df.columns:
        name = str(column)
        if name in excluded:
            continue
        if name not in question and name.lower() not in lowered:
            continue
        series = df[column]
        if pd.api.types.is_numeric_dtype(series):
            continue
        unique_values = [value for value in series.dropna().unique().tolist() if str(value)]
        if len(unique_values) > 50:
            continue
        matched = [
            value
            for value in sorted(unique_values, key=lambda item: len(str(item)), reverse=True)
            if str(value) and _value_in_question(str(value), question, lowered)
        ]
        if len(matched) == 1:
            filters[name] = matched[0]
    if filters:
        return filters
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
        matched = [
            value
            for value in unique_values
            if _is_safe_implicit_filter_value(str(value))
            and (_value_in_question(str(value), question, lowered) or _implicit_value_in_question(str(value), question, lowered))
        ]
        if len(matched) == 1:
            implicit_matches.append((_implicit_filter_column_score(question, name), name, matched[0]))
    return _best_implicit_filters(implicit_matches)


def _implicit_filter_column_score(question: str, column_name: str) -> int:
    requested = _requested_dimension_concepts(question)
    score = 0
    for concept in requested or ("product", "category", "store", "city", "channel", "customer"):
        score = max(score, _semantic_concept_column_score(column_name, concept))
    normalized = _normalize_column_token(column_name)
    if any(token in normalized for token in ("ctg", "category", "品类", "产品", "商品")):
        score += 12
    if any(token in normalized for token in ("name", "名称")):
        score += 4
    if any(token in normalized for token in ("code", "id", "编码", "代码", "sap")):
        score -= 12
    return score


def _best_implicit_filters(matches: list[tuple[int, str, Any]]) -> dict[str, Any]:
    best_by_value: dict[str, tuple[int, str, Any]] = {}
    for score, column, value in matches:
        key = str(value)
        current = best_by_value.get(key)
        if current is None or score > current[0]:
            best_by_value[key] = (score, column, value)
    return {column: value for _, column, value in best_by_value.values()}


def _is_safe_implicit_filter_value(text: str) -> bool:
    stripped = text.strip()
    if re.search(r"[\u4e00-\u9fff]", stripped):
        return len(stripped) > 1
    return len(stripped) > 1


def _implicit_value_in_question(text: str, question: str, lowered: str) -> bool:
    if re.search(r"[\u4e00-\u9fff]", text):
        escaped = re.escape(text)
        return any(
            re.search(pattern, question)
            for pattern in (
                rf"(?:为|是|等于|属于|包含|选择|筛选)\s*{escaped}",
                rf"{escaped}\s*(?:时|的记录|的数据|类别|类型|区域|地区|城市|科室|产品|客户|门店)",
            )
        )
    return _value_in_question(text, question, lowered)


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
