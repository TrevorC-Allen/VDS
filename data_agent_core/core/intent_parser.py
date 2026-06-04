"""Intent parser for natural language data questions.

This parser uses general field, period, and fee-rule patterns. It must not use
benchmark task IDs, standard answers, or single-question templates.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

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
    "客户细分": "segment",
    "客户群体": "segment",
    "客户分区": "segment",
    "客户段": "segment",
    "客群": "segment",
    "segment": "segment",
    "工单": "tickets",
    "工单量": "tickets",
    "工单数": "tickets",
    "票据数": "tickets",
    "tickets": "tickets",
    "ticket": "tickets",
    "服务线": "service_line",
    "业务线": "service_line",
    "service_line": "service_line",
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
    match = re.search(r"(?<!\d)(20\d{2})(?!\d)", question)
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


def _extract_chinese_month_range(question: str) -> tuple[int, int] | None:
    first_months = re.search(r"前\s*(\d+|[一二两三四五六七八九十]+)\s*个月", question)
    if first_months:
        prefix = question[max(0, first_months.start() - 8) : first_months.start()]
        if any(token in prefix for token in ("列出", "展示", "显示", "返回", "排名")):
            return None
        end_month = int(first_months.group(1)) if first_months.group(1).isdigit() else (_small_chinese_number(first_months.group(1)) or 0)
        if 1 <= end_month <= 12:
            return 1, end_month
    listed_months = [int(value) for value in re.findall(r"(?<!\d)(\d{1,2})\s*月", question)]
    if len(listed_months) >= 2 and all(1 <= month <= 12 for month in listed_months):
        return min(listed_months), max(listed_months)
    match = re.search(r"(?<!\d)(\d{1,2})\s*月?\s*(?:至|到|-|~|—)\s*(\d{1,2})\s*月", question)
    if not match:
        return None
    start_month = int(match.group(1))
    end_month = int(match.group(2))
    if 1 <= start_month <= 12 and 1 <= end_month <= 12 and start_month <= end_month:
        return start_month, end_month
    return None


def _extract_chinese_month_comparison_range(question: str) -> tuple[int, int] | None:
    match = re.search(
        r"(?<!\d)(\d{1,2})\s*月[^，。；;]*?(?:相比|相较|比|对比|较|和|与)[^，。；;]*?(\d{1,2})\s*月",
        question,
    )
    if not match:
        return None
    first_month = int(match.group(1))
    second_month = int(match.group(2))
    if 1 <= first_month <= 12 and 1 <= second_month <= 12:
        return min(first_month, second_month), max(first_month, second_month)
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
    if _entity_count_is_secondary_ranking_metric(question, lowered):
        return None
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
    metric_question = _metric_target_question(question)
    derived_metric = None if record_count_requested else _derived_ratio_metric(metric_question, df, guidelines=guidelines)
    metric = None if record_count_requested else (
        str(derived_metric["name"]) if derived_metric else _find_metric_column(metric_question, df) or table_context.get("metric")
    )
    if metric and metric != table_context.get("metric"):
        table_context["metric"] = metric
        table_context["table_selection_reason"] = _table_selection_reason(
            question,
            table_name,
            metric,
            table_context.get("dimension"),
            table_context.get("explicit_table"),
            table_context.get("join_plan") or {},
        )
    requested_metric_candidates = [] if record_count_requested or derived_metric else _find_metric_columns(metric_question, df)
    derived_raw_metrics = _raw_metrics_requested_with_derived(question, df, derived_metric) if derived_metric else []
    requested_metrics = requested_metric_candidates if _should_use_multi_metric_aggregation(lowered, requested_metric_candidates) else []
    if len(requested_metrics) > 1:
        metric = requested_metrics[0]
        table_context["metric"] = metric
        table_context["table_selection_reason"] = _table_selection_reason(
            question,
            table_name,
            metric,
            table_context.get("dimension"),
            table_context.get("explicit_table"),
            table_context.get("join_plan") or {},
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
    metric_excludes = {metric, *requested_metrics}
    rank_position_target = _rank_position_target_from_question(question, df)
    filter_excludes = set(metric_excludes)
    if isinstance(rank_position_target, dict) and rank_position_target.get("dimension"):
        filter_excludes.add(str(rank_position_target["dimension"]))
    filters = {**_infer_value_filters(question, df, exclude=filter_excludes), **dict(table_context.get("filters") or {})}
    explicit_group_by = _find_group_by_column(question, df)
    if explicit_group_by == metric:
        explicit_group_by = None
    context_dimension = table_context.get("dimension")
    if context_dimension in filters:
        context_dimension = None
    explicit_time_dimension = _find_time_column(df) if _question_targets_time_dimension(question) and not _result_dimension_after_extreme_time_scope(question) else None
    if explicit_time_dimension == metric or explicit_time_dimension in set(filters):
        explicit_time_dimension = None
    rank_position_dimension = str(rank_position_target.get("dimension") or "") if isinstance(rank_position_target, dict) else ""
    direct_target_dimension_concepts = _direct_target_dimension_concepts(question)
    target_dimension_concepts = _target_dimension_concepts(question)
    override_target_concepts = direct_target_dimension_concepts or target_dimension_concepts
    explicit_dimension_override = (
        explicit_group_by
        if (
            explicit_group_by
            and explicit_group_by != context_dimension
            and (_is_ranking_question(lowered) or _is_grouped_metric_display_question(lowered))
            and (
                not override_target_concepts
                or _dimension_matches_any_concept(str(explicit_group_by), override_target_concepts)
            )
        )
        else None
    )
    dimension = (
        rank_position_dimension
        or explicit_time_dimension
        or explicit_dimension_override
        or context_dimension
        or explicit_group_by
        or _find_dimension_column(question, df, metric, exclude=set(filters))
    )
    if (
        _question_requests_time_series(question)
        and not _is_growth_ranking_question(question, lowered)
        and not (dimension and _column_name_explicitly_mentioned(str(dimension), question, lowered))
        and not (
            dimension
            and _dimension_matches_any_concept(
                str(dimension),
                [concept for concept in target_dimension_concepts if concept not in {"month", "time"}],
            )
        )
    ):
        time_dimension = _find_time_column(df)
        if time_dimension and time_dimension != metric and time_dimension not in set(filters):
            dimension = time_dimension
    metric_specs = (
        []
        if record_count_requested
        else (
            _metric_specs_for_fields(derived_raw_metrics)
            if derived_metric
            else _metric_specs_for_aggregation_question(question, df, metric, requested_metrics)
        )
    )
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
    candidate_filter = _candidate_topn_filter_from_question(
        question,
        df,
        target_metric=metric,
        target_dimension=dimension,
        time_column=time_filter_column,
        available_columns=[str(column) for column in table_context.get("available_columns") or []],
    )
    result_time_filters = {}
    if isinstance(candidate_filter, dict):
        result_time_filters = candidate_filter.pop("result_time_filters", {}) or {}
    if isinstance(result_time_filters, dict) and result_time_filters:
        filters.update(result_time_filters)
    if (
        isinstance(candidate_filter, dict)
        and _entity_count_is_secondary_ranking_metric(question, lowered)
        and dimension
        and str(candidate_filter.get("dimension") or "") != str(dimension)
    ):
        candidate_filter = None

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

    grouped_child_ranking = _grouped_child_ranking_spec(
        question,
        lowered,
        df,
        metric=metric,
        candidate_filter=candidate_filter,
        current_dimension=dimension,
        available_columns=[str(column) for column in table_context.get("available_columns") or []],
    )
    if grouped_child_ranking:
        parent_dimension = grouped_child_ranking["parent_dimension"]
        child_dimension = grouped_child_ranking["child_dimension"]
        child_limit = grouped_child_ranking["child_limit"]
        aggregation = "count" if record_count_requested else _infer_aggregation(lowered, default="sum" if metric else "count")
        metric_name = metric or "__row_count__"
        return make_logic_form(
            task_type="ranking",
            operation="grouped_child_ranking",
            metric=None if metric_name == "__row_count__" else metric_name,
            group_by=child_dimension,
            filters=filters,
            candidate_set=_candidate_set_from_topn_filter(candidate_filter, parent_dimension),
            metric_definition={
                "name": metric_name if metric_name != "__row_count__" else "count",
                "capability_family": "grouped_child_ranking",
                "aggregation": aggregation,
                "business_definition": (
                    f"Within each {parent_dimension}, rank {child_dimension} by {metric_name} after filters and candidate-set selection."
                ),
            },
            numerator={"aggregation": aggregation, "field": metric_name, "scope": "filtered_rows"},
            denominator={"scope": "not_required"},
            entity_grain={"field": child_dimension, "role": "child_group_by", "parent_field": parent_dimension},
            parameters=_with_table_context({
                "table": table_name,
                "metric": None if metric_name == "__row_count__" else metric_name,
                "dimension": child_dimension,
                "parent_dimension": parent_dimension,
                "child_dimension": child_dimension,
                "aggregation": aggregation,
                "sort_order": "asc" if _is_bottom_question(lowered) else "desc",
                "limit": child_limit,
                "child_limit": child_limit,
                **({"candidate_filter": candidate_filter} if candidate_filter else {}),
            }, table_context),
            output_format=output_format | {"answer_type": "table", "chart_type": "bar"},
            output_contract={
                "answer_type": "table",
                "expected_result_shape": "one or more child-ranked rows per parent group",
                "capability_family": "grouped_child_ranking",
            },
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

    if _is_grouped_share_question(question, lowered) and dimension:
        aggregation = "count" if record_count_requested else _infer_aggregation(lowered, default="sum" if metric else "count")
        share_metric = "__row_count__" if _asks_for_transaction_share(lowered) or aggregation == "count" else metric
        share_column = _share_column_name(share_metric, aggregation)
        return make_logic_form(
            task_type="aggregation",
            operation="aggregation",
            metric=None if share_metric in {"__row_count__", "row_count", "transaction_count"} else share_metric,
            group_by=dimension,
            filters=filters,
            parameters=_with_table_context({
                "table": table_name,
                "metric": None if share_metric in {"__row_count__", "row_count", "transaction_count"} else share_metric,
                "share_metric": share_metric,
                "share_of_total": True,
                "share_column": share_column,
                "dimension": dimension,
                "aggregation": aggregation,
            }, table_context),
            output_format=output_format | {"answer_type": "table"},
        )

    if _is_grouped_entity_count_display_question(question, lowered):
        count_target = _find_count_target_column(question, df, dimension=None)
        count_dimension = _entity_count_display_dimension(
            question,
            df,
            metric=metric,
            current_dimension=dimension,
            count_target=count_target,
            available_columns=[str(column) for column in table_context.get("available_columns") or []],
        )
        if count_dimension:
            count_metric = count_target if count_target and count_target != count_dimension else None
            count_aggregation = "nunique" if count_metric else "count"
            count_metric_name = _entity_count_output_metric_name(question, count_metric)
            metric_spec = {
                "name": count_metric_name,
                "field": count_metric or "__row_count__",
                "aggregation": count_aggregation,
            }
            entity_count_context = dict(table_context)
            if count_dimension != table_context.get("dimension"):
                entity_count_context["dimension"] = count_dimension
                entity_count_context["table_selection_reason"] = _table_selection_reason(
                    question,
                    table_name,
                    count_metric,
                    count_dimension,
                    table_context.get("explicit_table"),
                    table_context.get("join_plan") or {},
                )
            return make_logic_form(
                task_type="aggregation",
                operation="aggregation",
                metric=count_metric,
                group_by=count_dimension,
                filters=filters,
                metric_definition={
                    "name": _count_metric_label(question, count_metric),
                    "capability_family": "grouped_entity_count",
                    "aggregation": count_aggregation,
                    "business_definition": (
                        f"Count distinct {count_metric} values per {count_dimension} after filters."
                        if count_metric
                        else f"Count rows per {count_dimension} after filters."
                    ),
                },
                numerator={
                    "aggregation": count_aggregation,
                    "field": count_metric or "__row_count__",
                    "scope": "filtered_rows",
                },
                denominator={"scope": "not_required"},
                parameters=_with_table_context({
                    "table": table_name,
                    "metric": count_metric,
                    "metrics": [count_metric_name],
                    "metric_specs": [metric_spec],
                    "dimension": count_dimension,
                    "aggregation": count_aggregation,
                }, entity_count_context),
                output_format=output_format | {"answer_type": "table"},
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

    if _is_grouped_entity_count_ranking_question(question, lowered) and dimension:
        count_target = _find_count_target_column(question, df, dimension=dimension)
        count_metric = count_target if count_target and count_target != dimension else None
        count_aggregation = "nunique" if count_metric else "count"
        metric_label = _count_metric_label(question, count_metric)
        return make_logic_form(
            task_type="ranking",
            operation="filtered_metric_ranking" if filters else "ranking",
            metric=count_metric,
            group_by=dimension,
            filters=filters,
            metric_definition={
                "name": metric_label,
                "capability_family": "filtered_ranking" if filters else "ranking",
                "aggregation": count_aggregation,
                "business_definition": (
                    f"Count distinct {count_metric} values per {dimension} after filters."
                    if count_metric
                    else f"Count rows per {dimension} after filters."
                ),
            },
            numerator={
                "aggregation": count_aggregation,
                "field": count_metric or "__row_count__",
                "scope": "filtered_rows",
            },
            denominator={"scope": "not_required"},
            parameters=_with_table_context({
                "table": table_name,
                "metric": count_metric,
                "dimension": dimension,
                "aggregation": count_aggregation,
                "metric_label": metric_label,
                "sort_order": "asc" if _is_bottom_question(lowered) else "desc",
                "limit": _extract_limit(question, default=1),
            }, table_context),
            output_format=output_format | {"answer_type": "table"},
        )

    if (
        _is_growth_ranking_question(question, lowered)
        and not (isinstance(candidate_filter, dict) and candidate_filter.get("operation") == "growth_ranking" and candidate_filter.get("dimension") != dimension)
        and dimension
        and metric
        and time_filter_column
    ):
        aggregation = _infer_aggregation(lowered, default="sum")
        growth_mode = _growth_mode(question, lowered)
        metric_label = f"{metric}_growth_rate" if growth_mode == "rate" else f"{metric}_growth_delta"
        return make_logic_form(
            task_type="ranking",
            operation="growth_ranking",
            metric=metric,
            group_by=dimension,
            filters=filters,
            metric_definition={
                "name": metric_label,
                "capability_family": "growth_ranking",
                "aggregation": aggregation,
                "business_definition": (
                    f"Rank {dimension} by {metric} growth between each entity's first and last available "
                    f"{time_filter_column} value after filters."
                ),
            },
            numerator={
                "field": metric,
                "aggregation": aggregation,
                "scope": "end_period_minus_start_period",
            },
            denominator={"field": metric, "scope": "start_period_abs"} if growth_mode == "rate" else {"scope": "not_required"},
            parameters=_with_table_context({
                "table": table_name,
                "metric": metric,
                "dimension": dimension,
                "time_column": time_filter_column,
                "aggregation": aggregation,
                "growth_mode": growth_mode,
                "sort_order": "asc" if _is_bottom_question(lowered) else "desc",
                "limit": _extract_limit(question, default=1),
            }, table_context),
            answer_target=_ranking_answer_target(question, guidelines, dimension),
            output_format=output_format | {"answer_type": "table", "chart_type": "bar"},
        )

    if _is_grouped_metric_display_question(lowered) and dimension and not _is_ranking_question(lowered):
        aggregation = "count" if record_count_requested else _infer_aggregation(lowered, default="sum" if metric else "count")
        metric_spec_payload = _apply_default_aggregation(metric_specs, aggregation)
        metric_names = _metric_names_for_payload(metric_spec_payload, requested_metrics, derived_metric)
        return make_logic_form(
            task_type="aggregation",
            operation="aggregation",
            metric=metric,
            group_by=dimension,
            filters=filters,
            candidate_set=_candidate_set_from_topn_filter(candidate_filter, dimension),
            parameters=_with_table_context({
                "table": table_name,
                "metric": metric,
                **({"metrics": metric_names} if metric_names else {}),
                **({"metric_specs": metric_spec_payload} if metric_spec_payload else {}),
                "dimension": dimension,
                "aggregation": aggregation,
                **({"derived_metric": derived_metric} if derived_metric else {}),
                **({"candidate_filter": candidate_filter} if candidate_filter else {}),
            }, table_context),
            output_format=output_format | {"answer_type": "table"},
        )

    if (
        candidate_filter
        and _is_candidate_filtered_metric_display_question(question, lowered)
        and dimension
        and not _same_dimension_ranking_with_secondary_entity_count(question, lowered, candidate_filter, dimension)
    ):
        aggregation = "count" if record_count_requested else _infer_aggregation(lowered, default="sum" if metric else "count")
        metric_spec_payload = _apply_default_aggregation(metric_specs, aggregation)
        metric_names = _metric_names_for_payload(metric_spec_payload, requested_metrics, derived_metric)
        result_dimension = None if _is_candidate_filtered_scalar_aggregation_question(question) else dimension
        return make_logic_form(
            task_type="aggregation",
            operation="aggregation",
            metric=metric,
            group_by=result_dimension,
            filters=filters,
            candidate_set=_candidate_set_from_topn_filter(candidate_filter, dimension),
            parameters=_with_table_context({
                "table": table_name,
                "metric": metric,
                **({"metrics": metric_names} if metric_names else {}),
                **({"metric_specs": metric_spec_payload} if metric_spec_payload else {}),
                "dimension": result_dimension,
                "aggregation": aggregation,
                **({"derived_metric": derived_metric} if derived_metric else {}),
                "candidate_filter": candidate_filter,
            }, table_context),
            output_format=output_format | {"answer_type": "table" if result_dimension else "number"},
        )

    if _is_ranking_question(lowered) and dimension and (not _question_requests_time_series(question) or _asks_result_ranking_question(question, lowered)):
        aggregation = "count" if record_count_requested else _infer_aggregation(lowered, default="sum" if metric else "count")
        rank_position = _extract_rank_position(question)
        metric_spec_payload = _supplemental_ranking_metric_specs(
            _apply_default_aggregation(metric_specs, aggregation),
            primary_metric=metric,
        )
        return make_logic_form(
            task_type="ranking",
            operation="filtered_metric_ranking" if filters else "ranking",
            filters=filters,
            candidate_set=_candidate_set_from_topn_filter(candidate_filter, dimension),
            parameters=_with_table_context({
                "table": table_name,
                "metric": metric,
                "dimension": dimension,
                "aggregation": aggregation,
                "sort_order": "asc" if _is_bottom_question(lowered) else "desc",
                "limit": _extract_limit(question, default=1),
                **({"rank_position": rank_position} if rank_position else {}),
                **({"rank_target": rank_position_target} if rank_position_target and rank_position_dimension == dimension else {}),
                **({"candidate_filter": candidate_filter} if candidate_filter else {}),
                **({"derived_metric": derived_metric} if derived_metric else {}),
                **({"metric_specs": metric_spec_payload} if metric_spec_payload else {}),
            }, table_context),
            answer_target=_ranking_answer_target(question, guidelines, dimension),
            output_format=output_format | _ranking_output_format(question, guidelines, dimension, _extract_limit(question, default=1)),
        )

    if _is_aggregation_question(lowered):
        aggregation = _infer_aggregation(lowered, default="sum")
        decimals = _decimal_places(guidelines)
        metric_spec_payload = _apply_default_aggregation(metric_specs, aggregation)
        metric_names = _metric_names_for_payload(metric_spec_payload, requested_metrics, derived_metric)
        has_multi_metric_result = len(requested_metrics) > 1 or bool(metric_spec_payload)
        return make_logic_form(
            task_type="aggregation",
            operation="aggregation",
            filters=filters,
            candidate_set=_candidate_set_from_topn_filter(candidate_filter, dimension),
            parameters=_with_table_context({
                "table": table_name,
                "metric": metric,
                **({"metrics": metric_names} if metric_names else {}),
                **({"metric_specs": metric_spec_payload} if metric_spec_payload else {}),
                "dimension": dimension if _has_grouping_language(lowered) else None,
                "aggregation": aggregation,
                **({"derived_metric": derived_metric} if derived_metric else {}),
                **({"candidate_filter": candidate_filter} if candidate_filter else {}),
            }, table_context),
            output_format=output_format
            | {"answer_type": "table" if has_multi_metric_result or (dimension and _has_grouping_language(lowered)) else "number"}
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
    explicit_table_matches = _explicit_table_matches(question, tables)
    explicit_table = explicit_table_matches[0] if len(explicit_table_matches) == 1 else None
    union_context = None if explicit_table else _same_schema_union_context(question, tables)
    if union_context is not None:
        return union_context
    if explicit_table:
        primary_df = tables[explicit_table]
        metric = _find_metric_column(question, primary_df)
        dimension_table = explicit_table
        dimension = _find_group_by_column(question, primary_df) or _find_dimension_column(question, primary_df, metric)
        target_concepts = _target_dimension_concepts(question)
        if target_concepts:
            best_dimension_table, best_dimension = _best_dimension_column(question, tables, preferred_table=explicit_table, metric=metric)
            if best_dimension and (
                not dimension
                or not _dimension_matches_any_concept(dimension, target_concepts)
                or (best_dimension_table != explicit_table and _dimension_looks_like_join_identifier(dimension))
            ):
                dimension_table, dimension = best_dimension_table, best_dimension
        target_tables: list[str] = []
        if dimension and dimension_table and dimension_table != explicit_table:
            target_tables.append(dimension_table)
        filter_matches = _infer_filter_matches_across_tables(question, tables, exclude={metric, dimension}, preferred_table=explicit_table)
        filters = {str(match["column"]): match["value"] for match in filter_matches}
        for match in filter_matches:
            filter_table = str(match["table"])
            if filter_table != explicit_table and filter_table not in target_tables:
                target_tables.append(filter_table)
        join_plan: dict[str, Any] = {}
        source_tables = [explicit_table]
        if target_tables and _should_attempt_generic_join(question):
            join_plan = _infer_join_plan_for_targets(explicit_table, tables, target_tables)
            source_tables.extend(table_name for table_name in target_tables if table_name not in source_tables)
            if not join_plan.get("trusted"):
                reason = str(join_plan.get("reason") or "")
                if join_plan.get("many_to_many_risk"):
                    reason = reason or "Join key candidate has many-to-many risk and needs user confirmation."
                join_plan = join_plan | {
                    "required": True,
                    "trusted": False,
                    "left_table": explicit_table,
                    "right_table": target_tables[-1],
                    "reason": reason or "No trustworthy join key was found for the requested metric and dimension tables.",
                }
        else:
            filters = {str(match["column"]): match["value"] for match in filter_matches if str(match["table"]) == explicit_table}
            if dimension_table and dimension_table != explicit_table:
                dimension_table = explicit_table
                dimension = _find_dimension_column(question, primary_df, metric, exclude=set(filters))
        requested_dimensions = _requested_dimension_concepts(question)
        missing_dimension_concepts = requested_dimensions if requested_dimensions and not dimension else []
        return {
            "table_name": explicit_table,
            "df": primary_df,
            "metric": metric,
            "dimension": dimension,
            "filters": filters,
            "missing_dimension_concepts": missing_dimension_concepts,
            "source_tables": source_tables,
            "join_plan": join_plan,
            "explicit_table": explicit_table,
            "explicit_table_mentions": explicit_table_matches,
            "available_columns": _available_columns_for_sources(tables, source_tables),
            "table_selection_reason": _table_selection_reason(question, explicit_table, metric, dimension, explicit_table, join_plan),
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
    candidate_dimension_target = _candidate_dimension_table(question, tables, preferred_table=primary_name)
    target_tables: list[str] = []
    if dimension and dimension_table and dimension_table != primary_name:
        target_tables.append(dimension_table)
    if candidate_dimension_target and candidate_dimension_target[0] != primary_name:
        target_tables.append(candidate_dimension_target[0])
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
        "explicit_table_mentions": explicit_table_matches,
        "available_columns": _available_columns_for_sources(tables, source_tables),
        "table_selection_reason": _table_selection_reason(question, primary_name, metric, dimension, explicit_table, join_plan),
    }


def _candidate_dimension_table(
    question: str,
    tables: dict[str, pd.DataFrame],
    *,
    preferred_table: str,
) -> tuple[str, str] | None:
    candidate_phrase = _candidate_topn_phrase(question)
    if candidate_phrase is None:
        return None
    _, _, dimension_phrase, _ = candidate_phrase
    concepts = _requested_dimension_concepts(dimension_phrase)
    if not concepts:
        return None
    matches: list[tuple[int, int, str, str]] = []
    for concept in concepts:
        for table_index, (table_name, df) in enumerate(tables.items()):
            column = _find_semantic_column(df, concept)
            if not column:
                continue
            score = _semantic_concept_column_score(column, concept) + (8 if table_name == preferred_table else 0)
            matches.append((score, -table_index, table_name, column))
    if not matches:
        return None
    matches.sort(key=lambda item: (-item[0], item[1]))
    return matches[0][2], matches[0][3]


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
    explicit_table_mentions = table_context.get("explicit_table_mentions")
    if explicit_table_mentions:
        enriched.setdefault("explicit_table_mentions", [str(table_name) for table_name in explicit_table_mentions])
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
    matches = _explicit_table_matches(question, tables)
    return matches[0] if len(matches) == 1 else None


def _explicit_table_matches(question: str, tables: dict[str, pd.DataFrame]) -> list[str]:
    lowered = _normalize_text(question)
    matches: list[tuple[int, int, str]] = []
    for table_name, df in tables.items():
        candidates = [
            table_name,
            str(df.attrs.get("table_name") or ""),
            str(df.attrs.get("source_file") or ""),
            str(df.attrs.get("sheet") or ""),
        ]
        score = 0
        position: int | None = None
        for candidate in candidates:
            normalized = _normalize_text(candidate)
            if _too_ambiguous_table_mention(normalized):
                continue
            if normalized and normalized in lowered:
                candidate_position = lowered.find(normalized)
                score = max(score, len(normalized))
                if position is None or candidate_position < position:
                    position = candidate_position
        if score:
            matches.append((position if position is not None else len(lowered), -score, table_name))
    matches.sort(key=lambda item: (item[0], item[1]))
    return [table_name for _position, _score, table_name in matches]


def _too_ambiguous_table_mention(normalized: str) -> bool:
    return len(normalized) < 2 and bool(re.fullmatch(r"[a-z0-9]", normalized))


def _best_metric_column(question: str, tables: dict[str, pd.DataFrame]) -> tuple[str | None, str | None]:
    best: tuple[int, str, str] | None = None
    target_metric_concepts = _target_metric_concepts(question)
    for table_name, df in tables.items():
        alias_metric = _find_alias_metric_column(question, df)
        specific_explicit_metric = _find_specific_explicit_metric_column(question, df)
        table_filter_score = _implicit_filter_match_score(question, df)
        table_time_score = 2 if _find_time_column(df) and _asks_time_or_trend(question) else 0
        for column in df.columns:
            column_name = str(column)
            if not _is_metric_value_column(df[column], column_name):
                continue
            if column_name != specific_explicit_metric and not _metric_candidate_allowed_for_question(question, column_name):
                continue
            score = _column_question_score(question, column_name)
            if specific_explicit_metric and column_name == specific_explicit_metric:
                score += 120
            if alias_metric and column_name == alias_metric:
                score += 80
            if _metric_name_hint(column_name):
                score += 2
            for concept in target_metric_concepts:
                if _semantic_concept_column_score(column_name, concept) > 0:
                    score += 120
            if not target_metric_concepts or "sales" in target_metric_concepts:
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


def _question_targets_time_dimension(question: str) -> bool:
    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    return any(token in compact for token in ("哪个月", "哪月", "哪个月份", "各月", "每月", "每个月", "按月", "按月份", "月度排名")) or any(
        token in lowered for token in ("which month", "by month", "by monthly", "month by month")
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
    direct_target_best = None
    if not _result_dimension_after_extreme_time_scope(question) and _direct_target_dimension_concepts(question):
        direct_target_best = _best_target_dimension_column(question, tables, preferred_table=preferred_table, metric=metric)
        if direct_target_best is not None:
            return direct_target_best

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

    target_best = direct_target_best or _best_target_dimension_column(question, tables, preferred_table=preferred_table, metric=metric)
    if target_best is not None:
        return target_best

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
    target_concepts = _target_dimension_concepts(question)
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
                if any(_semantic_concept_column_score(column_name, concept) > 0 for concept in target_concepts):
                    score += 40
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
    "segment": ("segment", "customer_segment", "cust_segment", "客户细分", "客户群", "客户群体", "客户分区", "客户分段", "客户段", "客群", "细分"),
    "service_line": ("service_line", "business_line", "service", "line", "服务线", "业务线", "服务", "业务"),
    "month": ("month", "month_id", "month_code", "stat_month", "ym", "year_month", "biz_month", "period", "month_period", "period_month", "年月", "月份", "月度", "业务月份", "统计月份", "期间"),
    "time": ("date", "day", "week", "period", "time", "sign_time", "create_time", "日期", "时间", "周期", "业务日期", "统计日期", "签收时间", "创建时间"),
    "sales": (
        "sales",
        "sale",
        "revenue",
        "amount",
        "amt",
        "sales_amt",
        "sign_amt",
        "ord_amt",
        "dist_sign_amt",
        "销售额",
        "销售金额",
        "销售",
        "收入",
        "金额",
        "总金额",
        "总额",
        "订单金额",
        "订单总金额",
        "订单总额",
        "订单额",
        "签收金额",
        "分销金额",
    ),
    "profit": ("profit", "gross_profit", "grossprofit", "利润", "毛利"),
    "tickets": ("tickets", "ticket", "工单量", "工单数", "票据数", "工单", "票据"),
}

DIMENSION_CONCEPTS = ("product", "category", "store", "city", "channel", "segment", "customer", "service_line", "month", "time")


def _requested_dimension_concepts(question: str) -> list[str]:
    requested: list[str] = []
    for concept in DIMENSION_CONCEPTS:
        aliases = SEMANTIC_COLUMN_ALIASES.get(concept) or ()
        if any(_semantic_alias_in_question(alias, question) for alias in aliases):
            requested.append(concept)
    if _question_requests_time_series(question) and "month" not in requested:
        requested.append("month")
    return requested


def _direct_target_dimension_concepts(question: str) -> list[str]:
    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    if any(token in compact for token in ("客户城市", "客户所在城市", "客户所属城市", "客户的城市")) or any(
        token in lowered for token in ("customer city", "customer cities")
    ):
        return ["city"]
    direct_patterns = (
        ("segment", ("哪个客户细分", "哪些客户细分", "哪个客户群体", "哪些客户群体", "哪个客户分段", "哪些客户分段", "哪个客户段", "哪些客户段", "哪个客群", "哪些客群", "客户分段排名", "客户段排名", "segment ranking", "which segment")),
        ("product", ("哪个产品", "哪种产品", "哪些产品", "产品是哪个", "产品是哪", "产品是什么", "产品有哪些", "产品是哪些", "产品排名", "which product", "product ranking")),
        ("customer", ("哪个客户", "哪些客户", "哪几个客户", "客户是哪个", "客户是哪", "客户是谁", "客户是什么", "客户有哪些", "客户是哪些", "客户排名", "前3个客户", "前三个客户", "前5个客户", "前五个客户", "which customer", "customer ranking")),
        ("service_line", ("哪个服务线", "哪些服务线", "哪条服务线", "各条服务线", "每条服务线", "服务线分布", "服务线是哪个", "服务线是哪", "服务线有哪些", "哪个业务线", "哪些业务线", "各条业务线", "每条业务线", "业务线分布", "业务线排名", "which service line", "business line ranking")),
        ("city", ("哪个城市", "哪些城市", "哪几个城市", "城市是哪个", "城市是哪", "城市有哪些", "城市是哪些", "城市排名", "前3个城市", "前三个城市", "前5个城市", "前五个城市", "which city", "city ranking")),
        ("category", ("哪个品类", "哪些品类", "哪几个品类", "品类是哪个", "品类是哪", "品类有哪些", "品类是哪些", "品类排名", "which category", "category ranking")),
        ("month", ("哪个月份", "哪个季度", "哪些月份", "哪些季度", "月度趋势", "季度趋势", "变化趋势", "which month", "monthly trend")),
    )
    matches: list[tuple[int, str]] = []
    for concept, patterns in direct_patterns:
        positions = [
            (compact.find(pattern) if any("\u4e00" <= char <= "\u9fff" for char in pattern) else lowered.find(pattern))
            for pattern in patterns
        ]
        positions = [position for position in positions if position >= 0]
        if positions:
            matches.append((min(positions), concept))
    quantity_targets = (
        ("city", r"哪(?:\d+|[一二两三四五六七八九十]+)?个城市"),
        ("customer", r"哪(?:\d+|[一二两三四五六七八九十]+)?个客户"),
        ("product", r"哪(?:\d+|[一二两三四五六七八九十]+)?(?:个|种)?产品"),
        ("service_line", r"哪(?:\d+|[一二两三四五六七八九十]+)?(?:个|条)?(?:服务线|业务线)"),
    )
    for concept, pattern in quantity_targets:
        match = re.search(pattern, compact)
        if match:
            matches.append((match.start(), concept))
    ordered: list[str] = []
    for _, concept in sorted(matches, key=lambda item: item[0]):
        if concept not in ordered:
            ordered.append(concept)
    return ordered


def _target_dimension_concepts(question: str) -> list[str]:
    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    if any(token in compact for token in ("客户城市", "客户所在城市", "客户所属城市", "客户的城市")) or any(
        token in lowered for token in ("customer city", "customer cities")
    ):
        return ["city"]
    ordered_patterns = (
        ("segment", ("客户细分", "客户群体", "客户分区", "客户分段", "客户段", "细分市场", "哪个客群", "哪些客群", "客群是什么", "客群是哪", "按客群", "客群排名", "segment")),
        ("product", ("哪个产品", "哪种产品", "哪些产品", "产品是哪个", "产品是哪", "产品是什么", "产品有哪些", "产品是哪些", "按产品", "产品排名", "which product", "by product")),
        ("customer", ("哪个客户", "哪些客户", "客户是哪个", "客户是哪", "客户是谁", "客户是什么", "客户有哪些", "客户是哪些", "按客户", "客户排名", "which customer", "by customer")),
        ("service_line", ("各服务线", "每个服务线", "各条服务线", "每条服务线", "哪个服务线", "哪些服务线", "服务线分布", "服务线是哪个", "服务线是哪", "服务线有哪些", "按服务线", "服务线排名", "各业务线", "每个业务线", "各条业务线", "每条业务线", "哪个业务线", "哪些业务线", "业务线分布", "按业务线", "业务线排名", "which service line", "by service line", "business line")),
        ("city", ("各城市", "各个城市", "每个城市", "所有城市", "全部城市", "哪个城市", "哪些城市", "城市分布", "城市是哪个", "城市是哪", "城市有哪些", "城市是哪些", "这些城市", "这几个城市", "按城市", "城市排名", "which city", "by city")),
        ("category", ("哪个品类", "哪些品类", "品类是哪个", "品类是哪", "品类有哪些", "品类是哪些", "按品类", "品类排名", "which category", "by category")),
        (
            "month",
            (
                "按月份",
                "按季度",
                "哪个月份",
                "哪个季度",
                "月度趋势",
                "季度趋势",
                "各月",
                "每月",
                "各季度",
                "变化趋势",
                "差距变化",
                "如何变化",
                "怎么变化",
                "怎样变化",
                "by month",
                "monthly",
                "change over time",
            ),
        ),
    )
    result_dimension = _result_dimension_after_extreme_time_scope(question)
    scoped_growth_dimension = _dimension_after_growth_entity_scope(compact, lowered)
    targets: list[str] = [result_dimension] if result_dimension else ([scoped_growth_dimension] if scoped_growth_dimension else _direct_target_dimension_concepts(question))
    for concept, patterns in ordered_patterns:
        if any((pattern in compact if any("\u4e00" <= char <= "\u9fff" for char in pattern) else pattern in lowered) for pattern in patterns):
            if concept not in targets:
                targets.append(concept)
    quantity_targets = (
        ("city", r"哪(?:\d+|[一二两三四五六七八九十]+)?个城市"),
        ("customer", r"哪(?:\d+|[一二两三四五六七八九十]+)?个客户"),
        ("product", r"哪(?:\d+|[一二两三四五六七八九十]+)?(?:个|种)?产品"),
        ("service_line", r"哪(?:\d+|[一二两三四五六七八九十]+)?(?:个|条)?(?:服务线|业务线)"),
    )
    for concept, pattern in quantity_targets:
        if re.search(pattern, compact) and concept not in targets:
            targets.append(concept)
    return targets


def _dimension_after_growth_entity_scope(compact: str, lowered: str) -> str:
    scope_match = re.search(
        r"(?:增长最快|增长最多|增速最快|增幅最大|提升最快|提升最多|下降最快|下降最多|变化最明显|变化最大|变化最多|变动最大|变动最多|波动最大|波动最多)的?(?:那个|该|这个)?(?:城市|客户|产品|服务线|业务线)(?:中|里|内)?",
        compact,
    )
    suffix = compact[scope_match.end() :] if scope_match else ""
    if not suffix and any(token in lowered for token in ("fastest growing city", "city with fastest growth", "fastest growth city")):
        suffix = lowered
    if not suffix:
        return ""
    targets = (
        ("segment", ("客户细分", "客户群体", "客户分区", "客户分段", "客户段", "细分市场", "哪个客群", "哪些客群", "segment")),
        ("customer", ("哪个客户", "哪些客户", "客户是哪个", "客户是哪", "客户是谁", "按客户", "which customer", "by customer")),
        ("product", ("哪个产品", "哪种产品", "哪些产品", "产品是哪个", "产品是哪", "按产品", "which product", "by product")),
        ("service_line", ("哪个服务线", "哪些服务线", "哪个业务线", "哪些业务线", "按服务线", "按业务线", "which service line", "by service line", "business line")),
        ("city", ("哪个城市", "哪些城市", "按城市", "which city", "by city")),
    )
    for concept, patterns in targets:
        if any((pattern in suffix if any("\u4e00" <= char <= "\u9fff" for char in pattern) else pattern in lowered) for pattern in patterns):
            return concept
    return ""


def _result_dimension_after_extreme_time_scope(question: str) -> str:
    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    asks_extreme_time = (
        any(token in compact for token in ("哪个月份", "哪个月", "哪月份", "哪月"))
        and any(token in compact for token in ("最高", "最大", "最多", "最低", "最小", "最少"))
    ) or bool(re.search(r"(?:which|what)\s+month.+(?:highest|top|largest|most|lowest|smallest|least)", lowered))
    if not asks_extreme_time:
        return ""
    suffix_target_patterns = (
        ("city", r"前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?(?:大)?的?城市"),
        ("customer", r"前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?(?:大)?的?客户"),
        ("product", r"前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?(?:大)?的?(?:产品|商品)"),
        ("service_line", r"前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位|条)?(?:大)?的?(?:服务线|业务线)"),
    )
    for concept, pattern in suffix_target_patterns:
        if re.search(pattern, compact):
            return concept
    if "top" in lowered:
        if "city" in lowered:
            return "city"
        if "customer" in lowered:
            return "customer"
        if "product" in lowered:
            return "product"
        if "service line" in lowered or "business line" in lowered:
            return "service_line"
    return ""


def _question_requests_time_series(question: str) -> bool:
    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    has_month_range = bool(re.search(r"\d{1,2}月(?:到|至|-|~|—|和)\d{1,2}月", compact))
    has_separate_language = "分别" in compact
    has_month_output_language = any(token in compact for token in ("趋势", "月度变化", "季度变化", "按月份", "按月度", "按季度", "如何变化", "怎么变化", "怎样变化", "变化趋势", "差距变化", "每月", "各月", "各季度"))
    return (
        has_month_output_language
        or (has_month_range and (has_month_output_language or has_separate_language))
        or any(token in lowered for token in ("trend", "monthly", "month by month", "change over time"))
    )


def _target_metric_concepts(question: str) -> list[str]:
    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    targets: list[str] = []
    condition_split = re.split(r"(?:那个月|该月|这个月|月份|月，|月,)", compact, maxsplit=1)
    target_clause = condition_split[1] if len(condition_split) > 1 else compact
    if (
        any(token in target_clause for token in ("贡献利润", "利润贡献", "最多的利润", "利润最高", "总利润", "利润总额", "利润合计", "利润汇总", "利润是多少", "利润多少", "利润排名"))
        or "profit" in lowered
        or "gross profit" in lowered
    ):
        targets.append("profit")
        return targets
    if any(token in target_clause for token in ("订单总金额", "订单总额", "订单金额", "订单额", "总金额", "总额", "收入", "营收", "销售额", "销售金额", "销售总额", "总销售额")) or any(
        token in lowered for token in ("amount", "revenue", "sales", "sale amount")
    ):
        targets.append("sales")
        return targets
    if any(token in compact for token in ("销售额", "销售金额", "销售总额", "总销售额", "销售排名", "销售业绩")) or "sales" in lowered:
        targets.append("sales")
    if any(token in compact for token in ("工单", "工单量", "工单数", "票据数", "工单数量")) or any(token in lowered for token in ("tickets", "ticket count")):
        targets.append("tickets")
    return targets


def _target_metric_concepts_all(question: str) -> list[str]:
    text = str(question or "")
    mentions: list[tuple[int, str]] = []
    for concept in ("sales", "profit", "tickets"):
        positions = [
            position
            for alias in SEMANTIC_COLUMN_ALIASES.get(concept, ())
            if (position := _semantic_alias_position(alias, text)) >= 0
        ]
        if positions:
            mentions.append((min(positions), concept))
    mentions.sort(key=lambda item: item[0])
    ordered: list[str] = []
    for _, concept in mentions:
        if concept not in ordered:
            ordered.append(concept)
    return ordered


def _metric_target_question(question: str) -> str:
    candidate_phrase = _candidate_topn_phrase(question)
    if candidate_phrase is None:
        return question
    suffix = str(candidate_phrase[3] or "").strip()
    if not suffix:
        return question
    if _target_metric_concepts_all(suffix) or any(token in suffix for token in ("利润率", "毛利率")):
        return suffix
    return question


def _candidate_topn_filter_from_question(
    question: str,
    df: pd.DataFrame,
    *,
    target_metric: str | None,
    target_dimension: str | None,
    time_column: str | None = None,
    available_columns: list[str] | None = None,
) -> dict[str, Any] | None:
    """Extract a candidate-set restriction such as "sales top 3 cities"."""

    growth_filter = _growth_candidate_filter_from_question(
        question,
        df,
        target_dimension=target_dimension,
        time_column=time_column,
        available_columns=available_columns,
    )
    if growth_filter:
        return growth_filter

    extreme_time_filter = _extreme_time_candidate_filter_from_question(
        question,
        df,
        target_metric=target_metric,
        target_dimension=target_dimension,
        time_column=time_column,
    )
    if extreme_time_filter:
        return extreme_time_filter

    candidate_phrase = _candidate_topn_phrase(question)
    if candidate_phrase is None:
        return None
    prefix, raw_limit, dimension_phrase, suffix = candidate_phrase
    limit = int(raw_limit) if raw_limit.isdigit() else (_small_chinese_number(raw_limit) or 0)
    if limit <= 0:
        return None

    derived_candidate_metric = _derived_ratio_metric(prefix, df)
    metric = str(derived_candidate_metric.get("name") or "") if isinstance(derived_candidate_metric, dict) and derived_candidate_metric else ""
    if not metric:
        metric = _find_metric_column(prefix, df)
    if not metric or (metric not in df.columns and not derived_candidate_metric):
        metric = _find_candidate_metric_before_limit(question, df)
    if not metric or (metric not in df.columns and not derived_candidate_metric):
        return None

    candidate_dimension = _find_candidate_dimension_from_phrase(dimension_phrase, df)
    valid_dimensions = {str(column) for column in df.columns} | {str(column) for column in available_columns or []}
    if (not candidate_dimension or candidate_dimension not in valid_dimensions) and available_columns:
        candidate_dimension = _find_candidate_dimension_from_column_names(dimension_phrase, available_columns)
    if not candidate_dimension and target_dimension and _phrase_mentions_dimension(dimension_phrase, target_dimension):
        candidate_dimension = target_dimension
    if not candidate_dimension or candidate_dimension not in valid_dimensions:
        return None

    suffix_has_result_scope = bool(suffix and time_column and _infer_time_filters(suffix, time_column))
    suffix_requests_same_dimension_display = bool(
        suffix
        and any(token in re.sub(r"\s+", "", str(suffix or "")) for token in ("按", "排名", "排行", "分别", "各自", "每个", "各个"))
    )
    if (
        metric == target_metric
        and candidate_dimension == target_dimension
        and not _candidate_suffix_requests_scalar_display(suffix)
        and not suffix_has_result_scope
        and not suffix_requests_same_dimension_display
    ):
        return None
    candidate_filters = _infer_time_filters(prefix, time_column) if time_column else {}
    result_time_filters = _infer_time_filters(suffix, time_column) if time_column and suffix else {}
    return {
        "dimension": candidate_dimension,
        "metric": metric,
        "aggregation": "ratio" if derived_candidate_metric else "sum",
        "limit": limit,
        "sort_order": "desc",
        **({"derived_metric": derived_candidate_metric} if derived_candidate_metric else {}),
        **({"filters": candidate_filters} if candidate_filters else {}),
        **({"result_time_filters": result_time_filters} if result_time_filters else {}),
    }


def _growth_candidate_filter_from_question(
    question: str,
    df: pd.DataFrame,
    *,
    target_dimension: str | None,
    time_column: str | None,
    available_columns: list[str] | None = None,
) -> dict[str, Any] | None:
    if not time_column or time_column not in df.columns:
        return None
    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    growth_tokens = ("增长最快", "增长最多", "增速最快", "增幅最大", "提升最快", "提升最多", "下降最快", "下降最多")
    if not any(token in compact for token in growth_tokens) and not any(
        token in lowered for token in ("fastest growth", "largest growth", "highest growth", "biggest increase", "largest increase", "fastest decline")
    ):
        return None
    candidate_dimension = _growth_candidate_dimension_from_question(compact, lowered, df, available_columns=available_columns)
    valid_dimensions = {str(column) for column in df.columns} | {str(column) for column in available_columns or []}
    if not candidate_dimension or candidate_dimension not in valid_dimensions:
        return None
    if target_dimension and candidate_dimension == target_dimension:
        return None
    prefix = _growth_candidate_prefix(compact)
    metric = _find_metric_column(prefix or question, df)
    if not metric or metric not in df.columns:
        return None
    candidate_filters = _infer_time_filters(prefix, time_column) if prefix else {}
    return {
        "operation": "growth_ranking",
        "dimension": candidate_dimension,
        "metric": metric,
        "aggregation": _infer_aggregation(lowered, default="sum"),
        "time_column": time_column,
        "growth_mode": _growth_mode(question, lowered),
        "limit": 1,
        "sort_order": "asc" if any(token in compact for token in ("下降最快", "下降最多")) or "fastest decline" in lowered else "desc",
        **({"filters": candidate_filters} if candidate_filters else {}),
    }


def _growth_candidate_dimension_from_question(
    compact: str,
    lowered: str,
    df: pd.DataFrame,
    *,
    available_columns: list[str] | None,
) -> str:
    patterns = (
        ("city", ("城市", "地区", "区域"), ("city", "region", "area", "province", "城市", "地区", "区域")),
        ("customer", ("客户", "顾客"), ("customer", "cust", "client", "buyer", "客户", "顾客")),
        ("product", ("产品", "商品"), ("product", "sku", "item", "goods", "产品", "商品")),
        ("service_line", ("服务线", "业务线"), ("service_line", "line", "business_line", "channel", "服务线", "业务线")),
    )
    columns = [str(column) for column in df.columns] + [str(column) for column in available_columns or []]
    for _concept, labels, aliases in patterns:
        if not any(re.search(rf"(?:增长最快|增长最多|增速最快|增幅最大|提升最快|提升最多|下降最快|下降最多)的?(?:那个|该|这个)?{label}", compact) for label in labels):
            continue
        column = _pick_column_by_aliases(columns, aliases)
        if column:
            return column
    if "fastest" in lowered and "city" in lowered:
        return _pick_column_by_aliases(columns, ("city", "region", "area", "城市", "地区", "区域"))
    return ""


def _growth_candidate_prefix(compact: str) -> str:
    match = re.search(r"(?:增长最快|增长最多|增速最快|增幅最大|提升最快|提升最多|下降最快|下降最多)", compact)
    return compact[: match.start()] if match else ""


def _pick_column_by_aliases(columns: list[str], aliases: tuple[str, ...]) -> str:
    lowered = [(str(column), str(column).lower()) for column in columns if str(column or "").strip()]
    for alias in aliases:
        alias_lower = str(alias or "").lower()
        for column, lowered_column in lowered:
            if alias_lower == lowered_column or alias_lower in lowered_column:
                return column
    return ""


def _extreme_time_candidate_filter_from_question(
    question: str,
    df: pd.DataFrame,
    *,
    target_metric: str | None,
    target_dimension: str | None,
    time_column: str | None,
) -> dict[str, Any] | None:
    if not time_column or time_column not in df.columns:
        return None
    result_dimension = _result_dimension_after_extreme_time_scope(question)
    if not result_dimension or not target_dimension or not _dimension_matches_any_concept(target_dimension, [result_dimension]):
        return None
    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    if not (
        (any(token in compact for token in ("哪个月份", "哪个月", "哪月份", "哪月")) and any(token in compact for token in ("最高", "最大", "最多", "最低", "最小", "最少")))
        or bool(re.search(r"(?:which|what)\s+month.+(?:highest|top|largest|most|lowest|smallest|least)", lowered))
    ):
        return None
    metric = _find_metric_column(question, df) or target_metric
    if not metric or metric not in df.columns:
        return None
    sort_order = "asc" if any(token in compact for token in ("最低", "最小", "最少")) or any(token in lowered for token in ("lowest", "smallest", "least")) else "desc"
    return {
        "dimension": time_column,
        "metric": metric,
        "aggregation": "sum",
        "limit": 1,
        "sort_order": sort_order,
    }


def _candidate_topn_phrase(question: str) -> tuple[str, str, str, str] | None:
    patterns = (
        r"(?P<prefix>[^，,。？?；;]{0,60}?)排名\s*前\s*(?P<limit>\d+|[一二两三四五六七八九十]+)\s*(?:个|名|位)?\s*(?:大)?\s*的?\s*(?P<dimension>[^，,。？?；;]{0,30}?)(?:在|是|中|里|内|,|，|。|$)(?P<suffix>.*)",
        r"(?P<prefix>[^，,。？?；;]{0,60}?)(?:最高|最大|最多|从高到低|排名)?的?\s*前\s*(?P<limit>\d+|[一二两三四五六七八九十]+)\s*(?:个|名|位)?\s*(?:大)?\s*的?\s*(?P<dimension>[^，,。？?；;]{0,30}?)(?:中|里|内|,|，|。|$)(?P<suffix>.*)",
        r"(?P<prefix>[^，,。？?；;]{0,60}?)(?:最高|最大|最多|最低|最少|从高到低|排名)的?\s*(?P<limit>\d+|[一二两三四五六七八九十]+)\s*(?:个|名|位)?\s*(?:大)?\s*的?\s*(?P<dimension>[^，,。？?；;]{0,30}?)(?:中|里|内|,|，|。|$)(?P<suffix>.*)",
        r"(?P<prefix>[^，,。？?；;]{0,60}?)\s*top\s*(?P<limit>\d+)\s*(?P<dimension>[^，,。？?；;]{0,30}?)(?:中|里|内|,|，|$)(?P<suffix>.*)",
    )
    for pattern in patterns:
        match = re.search(pattern, question, re.I)
        if match:
            return match.group("prefix"), match.group("limit"), match.group("dimension"), match.group("suffix") or ""

    lowered = question.lower()
    match = re.search(r"\btop\s*(?P<limit>\d+)\s+(?P<dimension>[a-z_ -]{2,30})\s+by\s+(?P<metric>[a-z_ -]{2,30})", lowered)
    if match:
        return match.group("metric"), match.group("limit"), match.group("dimension"), ""
    return None


def _find_candidate_metric_before_limit(question: str, df: pd.DataFrame) -> str | None:
    limit_pos = question.find("前")
    if limit_pos < 0:
        top_match = re.search(r"\btop\s*\d+", question, re.I)
        limit_pos = -1 if top_match is None else top_match.start()
    search_area = question[:limit_pos] if limit_pos >= 0 else question
    for concept in reversed(_target_metric_concepts_all(search_area)):
        semantic_column = _find_semantic_column(df, concept)
        if semantic_column and _is_metric_value_column(df[semantic_column], semantic_column):
            return semantic_column
    return None


def _find_candidate_dimension_from_phrase(phrase: str, df: pd.DataFrame) -> str | None:
    cleaned = re.sub(r"^(的|这些|这几个|the)\s*", "", str(phrase or "").strip(), flags=re.I)
    if not cleaned:
        return None
    for column in df.columns:
        name = str(column)
        if _column_name_explicitly_mentioned(name, cleaned, cleaned.lower()):
            return name
    for concept in _requested_dimension_concepts(cleaned):
        semantic_column = _find_semantic_column(df, concept)
        if semantic_column:
            return semantic_column
    return None


def _find_candidate_dimension_from_column_names(phrase: str, columns: list[str]) -> str | None:
    cleaned = re.sub(r"^(的|这些|这几个|the)\s*", "", str(phrase or "").strip(), flags=re.I)
    if not cleaned:
        return None
    available = [str(column) for column in columns if str(column or "").strip()]
    for concept in _requested_dimension_concepts(cleaned):
        candidates = [
            (index, column)
            for index, column in enumerate(available)
            if _semantic_concept_column_score(column, concept) > 0
        ]
        if candidates:
            candidates.sort(key=lambda item: item[0])
            return candidates[0][1]
    lowered = cleaned.lower()
    for column in available:
        name = str(column)
        if name in cleaned or name.lower() in lowered:
            return name
    return None


def _phrase_mentions_dimension(phrase: str, dimension: str) -> bool:
    normalized_phrase = _normalize_column_token(phrase)
    normalized_dimension = _normalize_column_token(dimension)
    return bool(normalized_phrase and normalized_dimension and normalized_dimension in normalized_phrase)


def _grouped_child_ranking_spec(
    question: str,
    lowered: str,
    df: pd.DataFrame,
    *,
    metric: str | None,
    candidate_filter: dict[str, Any] | None,
    current_dimension: str | None,
    available_columns: list[str] | None = None,
) -> dict[str, Any] | None:
    compact = re.sub(r"\s+", "", str(question or ""))
    if not compact:
        return None
    if _entity_count_is_secondary_ranking_metric(question, lowered):
        return None
    grouped_parent_language = any(token in compact for token in ("每个", "各个", "各", "逐个")) or any(
        token in lowered for token in ("each ", "per ")
    )
    child_question_language = any(token in compact for token in ("哪个", "哪些", "哪类", "哪种", "哪几个")) or "which " in lowered
    ranking_language = _is_ranking_question(lowered)
    if not (grouped_parent_language and child_question_language and ranking_language):
        return None

    parent_dimension = ""
    if isinstance(candidate_filter, dict) and candidate_filter.get("dimension"):
        parent_dimension = str(candidate_filter["dimension"])
    if not parent_dimension:
        parent_dimension = _parent_dimension_from_grouped_child_question(question, df) or str(current_dimension or "")
    valid_dimensions = {str(column) for column in df.columns} | {str(column) for column in available_columns or []}
    if not parent_dimension or parent_dimension not in valid_dimensions:
        return None
    if (
        _entity_count_is_secondary_ranking_metric(question, lowered)
        and (not current_dimension or str(parent_dimension) == str(current_dimension))
    ):
        return None

    child_search_text = _grouped_child_ranking_suffix(question)
    child_dimension = _find_child_dimension_from_columns(child_search_text, available_columns or [], exclude={parent_dimension}) if available_columns else ""
    if not child_dimension:
        child_dimension = _find_dimension_column(child_search_text, df, metric, exclude={parent_dimension})
    if not child_dimension or child_dimension == parent_dimension:
        child_dimension = _child_dimension_from_grouped_child_question(child_search_text, df, parent_dimension)
    if (not child_dimension or child_dimension == parent_dimension or child_dimension not in valid_dimensions) and available_columns:
        child_dimension = _find_child_dimension_from_columns(child_search_text, available_columns, exclude={parent_dimension})
    if not child_dimension or child_dimension == parent_dimension or child_dimension not in valid_dimensions:
        return None
    return {
        "parent_dimension": parent_dimension,
        "child_dimension": child_dimension,
        "child_limit": _extract_limit(child_search_text, default=1),
    }


def _grouped_child_ranking_suffix(question: str) -> str:
    candidate_phrase = _candidate_topn_phrase(question)
    suffix = str(candidate_phrase[3] or "") if candidate_phrase is not None else ""
    return suffix or question


def _parent_dimension_from_grouped_child_question(question: str, df: pd.DataFrame) -> str:
    compact = re.sub(r"\s+", "", str(question or ""))
    for concept in DIMENSION_CONCEPTS:
        if concept in {"month", "time"}:
            continue
        aliases = SEMANTIC_COLUMN_ALIASES.get(concept) or ()
        if any(f"每个{alias}" in compact or f"各个{alias}" in compact for alias in aliases):
            column = _find_semantic_column(df, concept)
            if column:
                return column
    return ""


def _child_dimension_from_grouped_child_question(question: str, df: pd.DataFrame, parent_dimension: str) -> str:
    for concept in _requested_dimension_concepts(question):
        column = _find_semantic_column(df, concept)
        if column and column != parent_dimension:
            return column
    return ""


def _find_child_dimension_from_columns(question: str, columns: list[str], *, exclude: set[str]) -> str:
    available = [str(column) for column in columns if str(column or "").strip() and str(column) not in exclude]
    for concept in _requested_dimension_concepts(question):
        candidates = [
            (index, column)
            for index, column in enumerate(available)
            if _semantic_concept_column_score(column, concept) > 0
        ]
        if candidates:
            candidates.sort(key=lambda item: item[0])
            return candidates[0][1]
    return ""


def _candidate_set_from_topn_filter(candidate_filter: dict[str, Any] | None, fallback_dimension: str | None) -> dict[str, object] | None:
    if not candidate_filter:
        return None
    return {
        "source": "data_top_n",
        "field": str(candidate_filter.get("dimension") or fallback_dimension or ""),
        "metric": str(candidate_filter.get("metric") or ""),
        "limit": int(candidate_filter.get("limit") or 0),
    }


def _candidate_suffix_requests_scalar_display(suffix: str) -> bool:
    compact = re.sub(r"\s+", "", str(suffix or ""))
    if not compact:
        return False
    if any(token in compact for token in ("每个", "各个", "各自", "分别", "按", "排名", "排行", "哪个", "哪些", "哪几个")):
        return False
    return any(token in compact for token in ("是多少", "多少", "总", "合计", "汇总"))


def _semantic_alias_position(alias: str, question: str) -> int:
    if any("\u4e00" <= char <= "\u9fff" for char in alias):
        return question.find(alias)
    lowered = question.lower()
    match = re.search(rf"(?<![A-Za-z0-9_.-]){re.escape(alias.lower())}(?![A-Za-z0-9_.-])", lowered)
    return -1 if match is None else match.start()


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
    quarter_month_range = _extract_quarter_month_range(question)
    if quarter_month_range:
        criteria = {"month_range": quarter_month_range}
        explicit_year = _extract_explicit_year(question)
        if explicit_year is not None:
            criteria["year"] = explicit_year
        return {time_column: criteria}
    leading_month = _extract_leading_single_month_scope(question)
    if leading_month is not None:
        criteria = {"month": leading_month}
        explicit_year = _extract_explicit_year(question)
        if explicit_year is not None:
            criteria["year"] = explicit_year
        return {time_column: criteria}
    month_range = _extract_chinese_month_range(question)
    if month_range:
        return {time_column: {"month_range": month_range}}
    comparison_month_range = _extract_chinese_month_comparison_range(question)
    if comparison_month_range:
        criteria = {"month_range": comparison_month_range}
        explicit_year = _extract_explicit_year(question)
        if explicit_year is not None:
            criteria["year"] = explicit_year
        return {time_column: criteria}
    listed_month_range = _extract_chinese_month_list_range(question)
    if listed_month_range:
        criteria = {"month_range": listed_month_range}
        explicit_year = _extract_explicit_year(question)
        if explicit_year is not None:
            criteria["year"] = explicit_year
        return {time_column: criteria}
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


def _extract_chinese_month_list_range(question: str) -> tuple[int, int] | None:
    months = [int(item) for item in re.findall(r"(?<!\d)(\d{1,2})\s*月", question)]
    unique_months = sorted({month for month in months if 1 <= month <= 12})
    if len(unique_months) < 2:
        return None
    return unique_months[0], unique_months[-1]


def _extract_explicit_year(question: str) -> int | None:
    match = re.search(r"(20\d{2})\s*年|(?<!\d)(20\d{2})(?!\d)", question)
    return int(match.group(1) or match.group(2)) if match else None


def _extract_leading_single_month_scope(question: str) -> int | None:
    first_clause = re.split(r"[，,。；;]", str(question or ""), maxsplit=1)[0]
    if any(token in first_clause for token in ("前", "top", "Top", "排名", "排行")):
        return None
    if any(token in first_clause for token in ("到", "至", "和", "第一季度", "第二季度", "第三季度", "第四季度", "季度")):
        return None
    if len(re.findall(r"(?<!\d)\d{1,2}\s*月份?", first_clause)) >= 2:
        return None
    if re.search(r"\d{1,2}\s*月\s*(?:-|~|—)", first_clause):
        return None
    match = re.search(r"(?<!\d)(\d{1,2})\s*月份?", first_clause)
    if match:
        month = int(match.group(1))
        return month if 1 <= month <= 12 else None
    chinese_match = re.search(r"([一二两三四五六七八九十]+)\s*月份?", first_clause)
    if chinese_match:
        month = _small_chinese_number(chinese_match.group(1)) or 0
        return month if 1 <= month <= 12 else None
    return None


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


def _dimension_matches_any_concept(column_name: str, concepts: list[str]) -> bool:
    return any(_semantic_concept_column_score(column_name, concept) > 0 for concept in concepts)


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
    if _profit_margin_is_candidate_condition_for_amount_display(question):
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


def _profit_margin_is_candidate_condition_for_amount_display(question: str) -> bool:
    compact = re.sub(r"\s+", "", str(question or ""))
    match = re.search(r"(?:利润率|毛利率)[^，,。？?；;]{0,20}(?:排名)?前(?:\d+|[一二两三四五六七八九十]+)", compact)
    if not match:
        return False
    suffix = compact[match.end() :]
    return any(token in suffix for token in ("月收入", "收入", "订单总额", "订单总金额", "订单金额", "订单额", "总金额", "金额", "销售额", "销售金额"))


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


def _find_semantic_metric_column(question: str, df: pd.DataFrame, concept: str) -> str | None:
    aliases = SEMANTIC_COLUMN_ALIASES.get(concept) or ()
    for column in df.columns:
        column_name = str(column)
        normalized = _normalize_column_token(column_name)
        if not any(_normalize_column_token(alias) and _normalize_column_token(alias) in normalized for alias in aliases):
            continue
        if _is_metric_value_column(df[column], column_name) and _metric_candidate_allowed_for_question(question, column_name):
            return column_name
    return None


def _metric_candidate_allowed_for_question(question: str, column_name: str) -> bool:
    normalized = _normalize_column_token(column_name)
    if not any(token in normalized for token in ("share", "ratio", "rate", "percent", "pct", "占比", "比例", "率")):
        return True
    return _asks_ratio_or_share_metric(question)


def _id_like(value: str) -> bool:
    normalized = _normalize_field_name(value)
    return "id" in normalized or normalized.endswith("编号")


def _metric_name_hint(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in ("sales", "revenue", "amount", "fee", "cost", "price", "profit", "stock", "quantity")) or any(
        token in value for token in ("销售", "金额", "收入", "费用", "利润", "库存", "数量", "订单")
    )


def _find_target_dimension_column(
    question: str,
    df: pd.DataFrame,
    metric: str | None,
    exclude: set[str] | None = None,
) -> str | None:
    excluded = set(exclude or set())
    for concept in _target_dimension_concepts(question):
        candidates: list[tuple[int, int, str]] = []
        allows_numeric_dimension = concept in {"month", "time"}
        for index, column in enumerate(df.columns):
            name = str(column)
            if name == metric or name in excluded:
                continue
            if pd.api.types.is_numeric_dtype(df[column]) and not allows_numeric_dimension:
                continue
            score = _semantic_concept_column_score(name, concept)
            if concept == "month" and score == 0:
                score = max(0, _semantic_concept_column_score(name, "time") - 10)
            if score <= 0:
                continue
            if _dimension_looks_like_join_identifier(name):
                score -= 10
            candidates.append((score, index, name))
        if candidates:
            candidates.sort(key=lambda item: (-item[0], item[1]))
            return candidates[0][2]
    return None


def _dimension_name_hint(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in ("city", "country", "product", "customer", "segment", "service_line", "business_line", "merchant", "category", "region", "channel", "month", "date")) or any(
        token in value for token in ("城市", "产品", "客户", "客群", "细分", "服务线", "业务线", "商户", "类别", "品类", "区域", "门店", "渠道", "月份", "日期")
    )


def _find_metric_column(question: str, df: pd.DataFrame) -> str | None:
    lowered = question.lower()
    explicit_specific_metric = _find_specific_explicit_metric_column(question, df)
    if explicit_specific_metric:
        return explicit_specific_metric
    for concept in _target_metric_concepts(question):
        semantic_column = _find_semantic_metric_column(question, df, concept)
        if semantic_column and _is_metric_value_column(df[semantic_column], semantic_column):
            return semantic_column
    alias_metric = _find_alias_metric_column(question, df)
    if alias_metric:
        return alias_metric
    for column in df.columns:
        name = str(column)
        if name.lower() in lowered or name in question:
            if _is_metric_value_column(df[column], name) and _metric_candidate_allowed_for_question(question, name):
                return name
    numeric_columns = [str(column) for column in df.columns if _is_metric_value_column(df[column], str(column))]
    if not numeric_columns:
        return None
    sales_amount_metric = _find_sales_amount_metric_column(question, df, numeric_columns)
    if sales_amount_metric:
        return sales_amount_metric
    metric_keywords = ("sales", "revenue", "amount", "fee", "cost", "price", "profit", "ticket", "工单", "票据", "销售", "金额", "收入", "费用", "利润")
    for column in numeric_columns:
        if any(keyword in column.lower() for keyword in metric_keywords):
            return column
    return numeric_columns[0]


def _find_sales_amount_metric_column(question: str, df: pd.DataFrame, numeric_columns: list[str]) -> str | None:
    candidates: list[tuple[int, int, str]] = []
    for index, column in enumerate(numeric_columns):
        score = _sales_amount_metric_score(question, column)
        if score <= 0:
            continue
        candidates.append((score, index, column))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][2]


def _find_specific_explicit_metric_column(question: str, df: pd.DataFrame) -> str | None:
    """Prefer fully mentioned business metrics over short semantic aliases.

    Project memory can add columns such as "项目净销售额".  The shorter alias
    "销售额" should not force the parser back to a raw "sales" column when the
    user explicitly asks for the more specific derived metric.
    """

    lowered = question.lower()
    metric_aliases = _metric_alias_tokens()
    matches: list[tuple[int, int, str]] = []
    for index, column in enumerate(df.columns):
        name = str(column)
        if not _is_metric_value_column(df[column], name):
            continue
        if not _column_name_explicitly_mentioned(name, question, lowered):
            continue
        normalized = _normalize_column_token(name)
        if not normalized:
            continue
        has_specific_alias = any(alias and alias in normalized and alias != normalized for alias in metric_aliases)
        if not has_specific_alias and normalized in metric_aliases:
            continue
        specificity = len(normalized)
        if specificity <= 2:
            continue
        matches.append((specificity, -index, name))
    if not matches:
        return None
    matches.sort(key=lambda item: (-item[0], item[1]))
    return matches[0][2]


def _metric_alias_tokens() -> set[str]:
    tokens: set[str] = set()
    for alias, canonical in FIELD_ALIASES.items():
        for value in (alias, canonical):
            normalized = _normalize_column_token(value)
            if normalized:
                tokens.add(normalized)
    for concept in ("sales", "profit", "tickets"):
        for alias in SEMANTIC_COLUMN_ALIASES.get(concept, ()):
            normalized = _normalize_column_token(alias)
            if normalized:
                tokens.add(normalized)
    return tokens


def _find_metric_columns(question: str, df: pd.DataFrame) -> list[str]:
    columns: list[str] = []
    explicit_specific_metric = _find_specific_explicit_metric_column(question, df)
    if explicit_specific_metric:
        columns.append(explicit_specific_metric)
    for concept in _target_metric_concepts_all(question):
        semantic_column = _find_semantic_metric_column(question, df, concept)
        if semantic_column and _is_metric_value_column(df[semantic_column], semantic_column) and semantic_column not in columns:
            columns.append(semantic_column)
    lowered = question.lower()
    for column in df.columns:
        name = str(column)
        if name in columns:
            continue
        if (
            (name.lower() in lowered or name in question)
            and _is_metric_value_column(df[column], name)
            and _metric_candidate_allowed_for_question(question, name)
        ):
            columns.append(name)
    return columns


def _should_use_multi_metric_aggregation(lowered: str, requested_metrics: list[str]) -> bool:
    if len(requested_metrics) <= 1:
        return False
    if _is_ranking_question(lowered) or _is_top_k_share_question(lowered):
        return False
    return _is_aggregation_question(lowered) or _is_grouped_metric_display_question(lowered)


def _metric_specs_for_aggregation_question(
    question: str,
    df: pd.DataFrame,
    metric: str | None,
    requested_metrics: list[str],
) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    for field in requested_metrics or ([metric] if metric else []):
        field_name = str(field or "").strip()
        if field_name and field_name in df.columns and _is_metric_value_column(df[field_name], field_name):
            specs.append({"name": field_name, "field": field_name, "aggregation": "sum"})
    entity_count = _entity_count_metric_spec(question, df)
    if entity_count and all(str(spec.get("name")) != entity_count["name"] for spec in specs):
        specs.append(entity_count)
    row_count = _row_count_metric_spec(question)
    if row_count and all(str(spec.get("name")) != row_count["name"] for spec in specs):
        specs.append(row_count)
    return specs if len(specs) > 1 else []


def _raw_metrics_requested_with_derived(question: str, df: pd.DataFrame, derived_metric: dict[str, Any] | None) -> list[str]:
    if not isinstance(derived_metric, dict) or not derived_metric:
        return []
    candidate_phrase = _candidate_topn_phrase(question)
    if candidate_phrase is not None and candidate_phrase[3]:
        question = candidate_phrase[3]
    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    raw_metrics: list[str] = []
    denominator = str(derived_metric.get("denominator") or "")
    numerator = str(derived_metric.get("numerator") or "")
    asks_denominator = any(
        token in compact
        for token in ("销售额", "销售金额", "订单总金额", "订单总额", "订单金额", "订单额", "总金额", "总额", "收入", "营收")
    ) or any(token in lowered for token in ("sales", "revenue", "amount"))
    compact_without_rate = compact.replace("利润率", "").replace("毛利率", "")
    lowered_without_rate = lowered.replace("profit margin", "").replace("gross margin", "").replace("profit rate", "").replace("margin rate", "")
    asks_numerator = any(
        token in compact_without_rate
        for token in ("总利润", "利润额", "利润金额", "利润贡献", "利润", "毛利额", "毛利金额", "毛利贡献", "毛利")
    ) or any(token in lowered_without_rate for token in ("total profit", "profit amount", "gross profit", "profit contribution", "profit"))
    if asks_denominator and denominator in df.columns:
        raw_metrics.append(denominator)
    if asks_numerator and numerator in df.columns and numerator not in raw_metrics:
        raw_metrics.append(numerator)
    return raw_metrics


def _metric_specs_for_fields(fields: list[str]) -> list[dict[str, str]]:
    return [{"name": str(field), "field": str(field), "aggregation": "sum"} for field in fields if str(field or "").strip()]


def _metric_names_for_payload(
    metric_specs: list[dict[str, str]],
    requested_metrics: list[str],
    derived_metric: dict[str, Any] | None,
) -> list[str]:
    names = [str(spec["name"]) for spec in metric_specs if str(spec.get("name") or "").strip()]
    if not names and len(requested_metrics) > 1:
        names = [str(metric) for metric in requested_metrics if str(metric or "").strip()]
    if isinstance(derived_metric, dict) and derived_metric:
        derived_name = str(derived_metric.get("name") or "").strip()
        if derived_name and derived_name not in names:
            names.append(derived_name)
    return names


def _entity_count_metric_spec(question: str, df: pd.DataFrame) -> dict[str, str] | None:
    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    candidates = (
        ("customer", "customer_count", ("客户数量", "客户数", "客户总数", "总客户数", "客户个数", "多少客户", "有多少客户", "顾客数量", "顾客数", "多少顾客", "有多少顾客", "number of customers", "customer count", "customers count")),
        ("product", "product_count", ("产品数量", "产品数", "商品数量", "商品数", "多少产品", "有多少产品", "多少商品", "有多少商品", "number of products", "product count")),
        ("store", "store_count", ("门店数量", "门店数", "店铺数量", "店铺数", "store count")),
    )
    for concept, metric_name, aliases in candidates:
        matched = any(_entity_count_alias_matches(alias, compact, lowered) for alias in aliases)
        if not matched:
            continue
        field = _find_semantic_column(df, concept)
        if field:
            return {"name": metric_name, "field": field, "aggregation": "nunique"}
    return None


def _row_count_metric_spec(question: str) -> dict[str, str] | None:
    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    if re.search(r"订单数量|订单数(?!据)|订单笔数|交易数量|交易数(?!据)|交易笔数|记录数|行数|条数", compact) or any(
        token in lowered
        for token in (
            "order count",
            "number of orders",
            "transaction count",
            "number of transactions",
            "record count",
            "row count",
        )
    ):
        return {"name": "order_count", "field": "__row_count__", "aggregation": "count"}
    return None


def _entity_count_alias_matches(alias: str, compact: str, lowered: str) -> bool:
    if any("\u4e00" <= char <= "\u9fff" for char in alias):
        if alias.endswith("数"):
            return bool(re.search(rf"{re.escape(alias)}(?!据)", compact))
        return alias in compact
    return alias in lowered


def _apply_default_aggregation(metric_specs: list[dict[str, str]], aggregation: str) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for spec in metric_specs:
        payload = dict(spec)
        if payload.get("aggregation") == "sum":
            payload["aggregation"] = aggregation
        normalized.append(payload)
    return normalized


def _supplemental_ranking_metric_specs(metric_specs: list[dict[str, str]], *, primary_metric: str | None) -> list[dict[str, str]]:
    primary = str(primary_metric or "").strip()
    supplemental: list[dict[str, str]] = []
    for spec in metric_specs:
        name = str(spec.get("name") or "").strip()
        field = str(spec.get("field") or "").strip()
        if not name or not field:
            continue
        if primary and (name == primary or field == primary):
            continue
        supplemental.append(dict(spec))
    return supplemental


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


def _best_target_dimension_column(
    question: str,
    tables: dict[str, pd.DataFrame],
    *,
    preferred_table: str,
    metric: str | None,
) -> tuple[str, str] | None:
    target_concepts = _target_dimension_concepts(question)
    if not target_concepts:
        return None
    for concept in target_concepts:
        candidates: list[tuple[int, int, str, str]] = []
        for table_index, (table_name, df) in enumerate(tables.items()):
            column = _find_target_dimension_column(question, df, metric, concepts=[concept])
            if not column:
                continue
            score = _semantic_concept_column_score(column, concept) + (8 if table_name == preferred_table else 0)
            candidates.append((score, -table_index, table_name, column))
        if candidates:
            candidates.sort(key=lambda item: (-item[0], item[1]))
            return candidates[0][2], candidates[0][3]
    return None


def _find_target_dimension_column(
    question: str,
    df: pd.DataFrame,
    metric: str | None,
    *,
    exclude: set[str] | None = None,
    concepts: list[str] | None = None,
) -> str | None:
    target_concepts = concepts or _target_dimension_concepts(question)
    if not target_concepts:
        return None
    excluded = set(exclude or set())
    for concept in target_concepts:
        candidates: list[tuple[int, int, str]] = []
        allows_numeric_dimension = concept in {"month", "time"}
        for index, column in enumerate(df.columns):
            name = str(column)
            if name == metric or name in excluded:
                continue
            if pd.api.types.is_numeric_dtype(df[column]) and not allows_numeric_dimension:
                continue
            score = _semantic_concept_column_score(name, concept)
            if concept == "month" and score <= 0:
                score = _semantic_concept_column_score(name, "time") - 10
            if score <= 0:
                continue
            if _dimension_looks_like_join_identifier(name):
                score -= 10
            candidates.append((score, index, name))
        if candidates:
            candidates.sort(key=lambda item: (-item[0], item[1]))
            return candidates[0][2]
    return None


def _find_dimension_column(
    question: str,
    df: pd.DataFrame,
    metric: str | None,
    exclude: set[str] | None = None,
) -> str | None:
    searchable_question = _question_without_file_mentions(question)
    lowered = searchable_question.lower()
    excluded = set(exclude or set())
    target_column = _find_target_dimension_column(question, df, metric, exclude=excluded)
    if target_column:
        return target_column
    for column in df.columns:
        name = str(column)
        if name == metric or name in excluded:
            continue
        if _column_name_explicitly_mentioned(name, searchable_question, lowered):
            return name
    target_concepts = _target_dimension_concepts(question)
    requested_concepts = _requested_dimension_concepts(question)
    if _question_requests_time_series(question):
        time_column = _find_time_column(df)
        if time_column and time_column != metric and time_column not in excluded:
            return time_column
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
            if any(_semantic_concept_column_score(name, concept) > 0 for concept in target_concepts):
                score += 40
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
        "segment",
        "service_line",
        "business_line",
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
        "客群",
        "客户细分",
        "客户段",
        "服务线",
        "业务线",
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


def _find_alias_metric_column(question: str, df: pd.DataFrame) -> str | None:
    searchable_question = _question_without_file_mentions(question)
    lowered = searchable_question.lower()
    columns = [str(column) for column in df.columns]
    normalized_columns = {_normalize_column_token(column): column for column in columns}
    for alias, canonical in FIELD_ALIASES.items():
        if not _alias_in_question(alias, lowered, searchable_question):
            continue
        for token in (canonical, alias):
            normalized = _normalize_column_token(token)
            column = normalized_columns.get(normalized)
            if column and _is_metric_value_column(df[column], column) and _alias_metric_candidate_allowed(question, column):
                return column
        canonical_normalized = _normalize_column_token(canonical)
        alias_normalized = _normalize_column_token(alias)
        for column in columns:
            column_normalized = _normalize_column_token(column)
            if canonical_normalized and canonical_normalized in column_normalized and _is_metric_value_column(df[column], column) and _alias_metric_candidate_allowed(question, column):
                return column
            if alias_normalized and alias_normalized in column_normalized and _is_metric_value_column(df[column], column) and _alias_metric_candidate_allowed(question, column):
                return column
    return None


def _alias_metric_candidate_allowed(question: str, column_name: str) -> bool:
    normalized = _normalize_column_token(column_name)
    if any(token in normalized for token in ("share", "ratio", "rate", "percent", "pct", "占比", "比例", "率")):
        return _asks_ratio_or_share_metric(question)
    return True


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
        "service_line": ("service_line", "business_line", "服务线", "业务线"),
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
    top_entity_pattern = re.search(
        r"前\s*(?:\d+|[一二两三四五六七八九十]+)\s*(?:个|名|位)?(?:大)?的?(?:城市|客户|产品|商品|服务线|业务线|品类|门店|区域|地区)",
        lowered,
    )
    ordinal_entity_pattern = re.search(
        r"(?:销售额|销售金额|订单金额|订单总额|订单总金额|销量|收入|利润|金额)\s*(?:排名)?(?:第)?(?:一|二|三|四|五|六|七|八|九|十|1|2|3|4|5|6|7|8|9|10)\s*(?:名)?的?(?:城市|客户|产品|商品|服务线|业务线|品类|门店|区域|地区)",
        lowered,
    )
    rank_position_question = re.search(r"(?:排|排名|排行|名次|位次)(?:在)?第?几", lowered)
    return any(token in lowered for token in ("highest", "lowest", "top", "bottom", "max", "min", "best", "worst", "ranking", "rank", "sort", "order by", "最多", "最高", "最低", "最少", "最大", "最小", "最好", "最佳", "最优", "最差", "排名", "排行", "名次", "排序", "排列", "从高到低", "从低到高")) or bool(top_entity_pattern) or bool(
        ordinal_entity_pattern
    ) or bool(
        rank_position_question
    ) or bool(
        re.search(r"(?:第\s*(?:\d+|[一二两三四五六七八九十]+)\s*(?:高|低)|排名\s*第\s*(?:\d+|[一二两三四五六七八九十]+))", lowered)
    )


def _is_bottom_question(lowered: str) -> bool:
    return any(token in lowered for token in ("lowest", "bottom", "min", "worst", "ascending", "asc", "从低到高", "最低", "最少", "最差"))


def _is_growth_ranking_question(question: str, lowered: str) -> bool:
    compact = re.sub(r"\s+", "", str(question or ""))
    growth_tokens = (
        "增长最快",
        "增长最多",
        "增速最快",
        "增幅最大",
        "提升最快",
        "提升最多",
        "下降最快",
        "下降最多",
        "增长趋势最明显",
        "增长最明显",
        "变化最明显",
        "变化最大",
        "变化最多",
        "变动最大",
        "变动最多",
        "波动最大",
        "波动最多",
    )
    return any(token in compact for token in growth_tokens) or any(
        token in lowered for token in ("fastest growth", "largest growth", "highest growth", "biggest increase", "largest increase", "fastest decline")
    )


def _growth_mode(question: str, lowered: str) -> str:
    compact = re.sub(r"\s+", "", str(question or ""))
    if any(token in compact for token in ("变化最大", "变化最多", "变动最大", "变动最多", "波动最大", "波动最多")):
        return "abs_delta"
    if any(token in compact for token in ("增长率", "增速", "增幅")) or any(token in lowered for token in ("growth rate", "rate of growth")):
        return "rate"
    if any(token in compact for token in ("增长最快", "提升最快", "增长趋势最明显", "增长最明显")) or "fastest growth" in lowered:
        return "rate"
    return "delta"


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
            "销售",
            "销售额",
            "销售金额",
            "销售业绩",
            "组成",
            "构成",
            "拆分",
        )
    )


def _is_filtering_question(lowered: str) -> bool:
    return any(token in lowered for token in ("where", "filter", "show", "list", "greater than", "less than", "筛选", "列出", "大于", "小于"))


def _has_grouping_language(lowered: str) -> bool:
    compact = re.sub(r"\s+", "", str(lowered or ""))
    if re.search(r"(?:所有|全部)(?:城市|地区|区域|品类|产品|商品|服务线|业务线|客户细分|客户分区|客户分段|客户段|客群|渠道|门店|店铺)", compact):
        return True
    return any(
        token in lowered
        for token in (" by ", "group", "per ", "each", "按", "各", "每", "不同", "分别", "随时间", "趋势", "如何变化", "怎么变化", "怎样变化", "变化", "trend", "组成", "构成", "拆分", "分布")
    )


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
            "看一下",
            "看看",
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
            "如何",
            "分别",
            "如何变化",
            "怎么变化",
            "怎样变化",
            "变化",
            "情况",
            "表现",
            "trend",
            "组成",
            "构成",
            "拆分",
            "分布",
            "是否合理",
            "合理",
        )
    )


def _is_candidate_filtered_metric_display_question(question: str, lowered: str) -> bool:
    compact = re.sub(r"\s+", "", str(question or ""))
    candidate_phrase = _candidate_topn_phrase(question)
    if candidate_phrase is not None:
        suffix_compact = re.sub(r"\s+", "", str(candidate_phrase[3] or ""))
        suffix_strong_display = any(token in suffix_compact for token in ("分别", "各自", "是多少", "多少", "汇总", "总", "合计"))
        if any(token in suffix_compact for token in ("排名", "排行", "名次")) and not suffix_strong_display:
            return False
        if any(token in suffix_compact for token in ("分别", "各自", "每个", "各个", "是多少", "多少", "如何", "怎样", "按", "展示", "显示", "汇总")):
            return True
    if _asks_result_ranking_question(question, lowered):
        return False
    strong_display_language = any(token in compact for token in ("分别", "是多少", "多少", "汇总", "总", "合计")) or any(
        token in lowered for token in ("what is", "how much", "total", "sum")
    )
    grouped_display_language = any(token in compact for token in ("每个", "各个", "如何", "怎样")) or any(
        token in lowered for token in ("each", "per ")
    )
    if any(token in compact for token in ("排名", "排行", "名次")) and not strong_display_language:
        return False
    display_language = strong_display_language or grouped_display_language
    asks_extreme_entity = any(token in compact for token in ("哪个", "哪些", "哪种", "哪类")) and any(
        token in compact for token in ("最高", "最低", "最多", "最少", "排名", "排行", "top", "Top")
    )
    return display_language and not asks_extreme_entity


def _same_dimension_ranking_with_secondary_entity_count(
    question: str,
    lowered: str,
    candidate_filter: Any,
    dimension: str | None,
) -> bool:
    if not isinstance(candidate_filter, Mapping) or not dimension:
        return False
    if str(candidate_filter.get("dimension") or "") != str(dimension):
        return False
    return _is_ranking_question(lowered) and _entity_count_is_secondary_ranking_metric(question, lowered)


def _is_candidate_filtered_scalar_aggregation_question(question: str) -> bool:
    candidate_phrase = _candidate_topn_phrase(question)
    suffix = candidate_phrase[3] if candidate_phrase is not None else question
    return _candidate_suffix_requests_scalar_display(suffix)


def _asks_result_ranking_question(question: str, lowered: str) -> bool:
    candidate_phrase = _candidate_topn_phrase(question)
    if candidate_phrase is not None and candidate_phrase[3]:
        question = candidate_phrase[3]
        lowered = str(question or "").lower()
    compact = re.sub(r"\s+", "", str(question or ""))
    if _question_requests_time_series(question) and re.search(
        r"(?:排名)?前(?:\d+|[一二两三四五六七八九十]+)(?:个|名|位)?(?:大)?的?(?:城市|客户|产品|商品|服务线|业务线|品类|门店|区域|地区)",
        compact,
    ):
        return False
    if any(token in compact for token in ("排名", "排行", "名次", "排第")):
        return True
    if any(token in lowered for token in ("ranking", "ranked", "rank ")):
        return True
    if re.search(
        r"(?:最高|最低|最多|最少|最大|最小)的?(?:客户细分|客户分段|客户段|客群|城市|客户|产品|商品|品类|服务线|业务线)(?:是什么|是哪|有哪些|为谁|是谁)?",
        compact,
    ):
        return True
    return bool(re.search(r"哪个.+(?:最高|最低|最多|最少|最大|最小)", compact))


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
    if any(token in lowered for token in ("金额", "销售", "收入", "利润", "工单量", "订单总额", "订单金额", "sales", "revenue", "amount", "profit")):
        return False
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


def _is_grouped_entity_count_ranking_question(question: str, lowered: str) -> bool:
    compact = re.sub(r"\s+", "", str(question or ""))
    count_tokens = (
        "客户数量",
        "客户数",
        "顾客数量",
        "多少客户",
        "有多少客户",
        "多少顾客",
        "有多少顾客",
        "产品数量",
        "商品数量",
        "多少产品",
        "有多少产品",
        "多少商品",
        "有多少商品",
        "订单数",
        "记录数",
        "工单数",
        "票据数",
        "数量最多",
        "数量最少",
        "number of customers",
        "customer count",
        "number of products",
        "product count",
        "order count",
        "record count",
    )
    if not (_is_ranking_question(lowered) and any(_entity_count_alias_matches(token, compact, lowered) for token in count_tokens)):
        return False
    if _entity_count_is_secondary_ranking_metric(question, lowered):
        return False
    return True


def _is_grouped_entity_count_display_question(question: str, lowered: str) -> bool:
    if _is_ranking_question(lowered):
        return False
    if not _has_grouping_language(lowered):
        return False
    if _has_explicit_business_metric_request(question):
        return False
    compact = re.sub(r"\s+", "", str(question or ""))
    return any(_entity_count_alias_matches(token, compact, lowered) for token in _entity_count_question_tokens())


def _has_explicit_business_metric_request(question: str) -> bool:
    return bool(_target_metric_concepts_all(question) or _target_metric_concepts(question) or _asks_profit_margin(question))


def _entity_count_question_tokens() -> tuple[str, ...]:
    return (
        "客户数量",
        "客户数",
        "客户总数",
        "总客户数",
        "客户个数",
        "多少客户",
        "有多少客户",
        "各有多少客户",
        "顾客数量",
        "顾客数",
        "多少顾客",
        "有多少顾客",
        "产品数量",
        "产品数",
        "商品数量",
        "商品数",
        "多少产品",
        "有多少产品",
        "多少商品",
        "有多少商品",
        "number of customers",
        "customer count",
        "customers count",
        "number of products",
        "product count",
    )


def _entity_count_target_concepts(question: str) -> list[str]:
    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    concepts: list[str] = []
    if any(
        token in compact
        for token in (
            "客户数量",
            "客户数",
            "客户总数",
            "总客户数",
            "客户个数",
            "多少客户",
            "有多少客户",
            "各有多少客户",
            "顾客数量",
            "顾客数",
            "多少顾客",
            "有多少顾客",
        )
    ) or any(token in lowered for token in ("customer count", "number of customers", "customers count")):
        concepts.append("customer")
    if any(
        token in compact
        for token in (
            "产品数量",
            "产品数",
            "商品数量",
            "商品数",
            "多少产品",
            "有多少产品",
            "多少商品",
            "有多少商品",
        )
    ) or any(token in lowered for token in ("product count", "number of products")):
        concepts.append("product")
    return concepts


def _entity_count_display_dimension(
    question: str,
    df: pd.DataFrame,
    *,
    metric: str | None,
    current_dimension: str | None,
    count_target: str | None,
    available_columns: list[str] | None = None,
) -> str | None:
    count_concepts = set(_entity_count_target_concepts(question))
    preferred_concepts = [
        concept
        for concept in _target_dimension_concepts(question)
        if concept not in count_concepts and concept not in {"month", "time"}
    ]
    requested_concepts = [
        concept
        for concept in _requested_dimension_concepts(question)
        if concept not in count_concepts and concept not in {"month", "time"} and concept not in preferred_concepts
    ]
    candidate_concepts = [*preferred_concepts, *requested_concepts]
    if len(candidate_concepts) > 1:
        candidate_concepts = [
            concept
            for _, concept in sorted(
                enumerate(candidate_concepts),
                key=lambda item: (-_dimension_concept_last_position(question, item[1]), item[0]),
            )
        ]
    for concept in candidate_concepts:
        column = _find_target_dimension_column(question, df, metric, exclude={count_target} if count_target else None, concepts=[concept])
        if column and column != count_target:
            return column
        available_column = _find_target_dimension_name_in_columns(
            question,
            available_columns or [],
            concept,
            metric=metric,
            exclude={count_target} if count_target else None,
        )
        if available_column and available_column != count_target:
            return available_column
    if current_dimension and current_dimension != count_target:
        return current_dimension
    return _find_dimension_column(question, df, metric, exclude={count_target} if count_target else None)


def _find_target_dimension_name_in_columns(
    question: str,
    columns: list[str],
    concept: str,
    *,
    metric: str | None,
    exclude: set[str] | None = None,
) -> str | None:
    excluded = set(exclude or set())
    candidates: list[tuple[int, int, str]] = []
    for index, column in enumerate(columns):
        name = str(column)
        if name == metric or name in excluded:
            continue
        score = _semantic_concept_column_score(name, concept)
        if score <= 0:
            continue
        if _dimension_looks_like_join_identifier(name):
            score -= 10
        candidates.append((score, index, name))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][2]


def _dimension_concept_last_position(question: str, concept: str) -> int:
    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    positions: list[int] = []
    for alias in SEMANTIC_COLUMN_ALIASES.get(concept, ()):
        alias_text = str(alias or "")
        if not alias_text:
            continue
        if any("\u4e00" <= char <= "\u9fff" for char in alias_text):
            position = compact.rfind(alias_text)
        else:
            position = lowered.rfind(alias_text.lower())
        if position >= 0:
            positions.append(position)
    return max(positions) if positions else -1


def _entity_count_output_metric_name(question: str, metric: str | None) -> str:
    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    if any(token in compact for token in ("客户", "顾客")) or any(token in lowered for token in ("customer", "client")):
        return "customer_count"
    if any(token in compact for token in ("产品", "商品")) or any(token in lowered for token in ("product", "item", "goods")):
        return "product_count"
    return f"{metric}_count" if metric else "count"


def _entity_count_is_secondary_ranking_metric(question: str, lowered: str) -> bool:
    compact = re.sub(r"\s+", "", str(question or ""))
    secondary_count = any(
        token in compact
        for token in (
            "及各自的客户数量",
            "及各自客户数量",
            "及各自的客户数",
            "及各自客户数",
            "及各自的客户总数",
            "及各自客户总数",
            "及其客户数量",
            "及其客户数",
            "及其客户总数",
            "及其的客户数量",
            "及其的客户数",
            "及其的客户总数",
            "各自的客户数量",
            "各自客户数量",
            "各自的客户数",
            "各自客户数",
            "各自的客户总数",
            "各自客户总数",
            "分别的客户数量",
            "分别客户数量",
            "分别的客户数",
            "分别客户数",
            "分别的客户总数",
            "分别客户总数",
            "客户数量分别",
            "客户数分别",
            "客户总数分别",
            "它们的客户数量",
            "它们客户数量",
            "它们的客户数",
            "它们客户数",
            "它们的客户总数",
            "它们客户总数",
            "他们的客户数量",
            "他们客户数量",
            "他们的客户数",
            "他们客户数",
            "他们的客户总数",
            "他们客户总数",
        )
    ) or any(token in lowered for token in ("and their customer count", "with customer count", "with number of customers"))
    if not secondary_count:
        return False
    primary_metric = any(
        token in compact
        for token in ("订单总金额", "订单总额", "订单金额", "总金额", "总额", "销售额", "销售金额", "收入", "营收", "利润")
    ) or any(token in lowered for token in ("amount", "sales", "revenue", "profit"))
    primary_extreme = any(token in compact for token in ("最高", "最多", "最大", "排名", "前3", "前三", "前5", "前五")) or any(
        token in lowered for token in ("highest", "top", "rank")
    )
    return bool(primary_metric and primary_extreme)


def _find_count_target_column(question: str, df: pd.DataFrame, *, dimension: str | None = None) -> str | None:
    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    concepts: list[str] = []
    if any(token in compact for token in ("客户数量", "客户数", "客户总数", "总客户数", "顾客数量", "顾客数", "多少客户", "有多少客户", "多少顾客", "有多少顾客")) or any(
        token in lowered for token in ("customer count", "number of customers")
    ):
        concepts.append("customer")
    if any(token in compact for token in ("产品数量", "产品数", "商品数量", "商品数", "多少产品", "有多少产品", "多少商品", "有多少商品")) or any(
        token in lowered for token in ("product count", "number of products")
    ):
        concepts.append("product")
    for concept in concepts:
        candidates = [
            (index, str(column))
            for index, column in enumerate(df.columns)
            if str(column) != str(dimension or "") and _semantic_concept_column_score(str(column), concept) > 0
        ]
        if candidates:
            candidates.sort(key=lambda item: (0 if item[1].lower().endswith("_id") else 1, item[0]))
            return candidates[0][1]
    named = _find_named_column(question, df) or _find_entity_column(question, df)
    if named and named != dimension:
        return named
    return None


def _count_metric_label(question: str, metric: str | None) -> str:
    compact = re.sub(r"\s+", "", str(question or ""))
    if any(token in compact for token in ("客户数量", "客户数", "客户总数", "总客户数", "顾客数量", "顾客数", "多少客户", "有多少客户", "多少顾客", "有多少顾客")):
        return "客户数"
    if any(token in compact for token in ("产品数量", "产品数", "商品数量", "商品数", "多少产品", "有多少产品", "多少商品", "有多少商品")):
        return "产品数"
    if any(token in compact for token in ("订单数", "记录数", "工单数", "票据数")):
        return "count"
    return f"{metric}_count" if metric else "count"


def _is_top_outlier_group_question(lowered: str) -> bool:
    return (
        any(token in lowered for token in ("outlier", "anomaly", "anomalies", "异常", "离群"))
        and any(token in lowered for token in ("which", "what", "哪个", "哪一"))
        and any(token in lowered for token in ("most", "highest number", "top", "最多", "最高"))
        and not lowered.startswith("how many")
    )


def _is_outlier_count_question(lowered: str) -> bool:
    if not any(token in lowered for token in ("outlier", "anomaly", "anomalies", "异常", "离群")):
        return False
    return any(
        token in lowered
        for token in ("count", "number", "how many", "多少", "数量", "个数", "是否异常", "是否有异常", "有没有异常", "有异常吗", "是否存在异常", "明显异常")
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
        token in lowered for token in ("count", "number", "how many", "any", "exist", "percentage", "proportion", "share", "rate", "有", "存在", "是否", "有没有", "有无", "多少", "数量", "个数", "占比", "比例", "百分比")
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
    specific_missing_question = any(
        token in lowered
        for token in (
            "which column",
            "what column",
            "how many",
            "percentage",
            "count",
            "多少",
            "哪一列",
            "哪个字段",
            "占比",
            "是否异常",
            "有没有异常",
            "是否存在异常",
        )
    )
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
    has_selection_scope = any(token in lowered for token in ("top", "前", "排名第一", "排名第1", "第一名", "第1名", "top1", "首位"))
    return has_selection_scope and any(
        token in lowered for token in ("share", "percentage", "proportion", "占比", "比例", "百分比")
    )


def _is_grouped_share_question(question: str, lowered: str) -> bool:
    compact = re.sub(r"\s+", "", str(question or ""))
    asks_share = any(token in compact for token in ("占比", "比例", "百分比")) or any(
        token in lowered for token in ("share", "percentage", "proportion")
    )
    if not asks_share:
        return False
    if _is_top_k_share_question(lowered):
        return False
    grouped_language = any(token in compact for token in ("各", "每个", "分别", "按")) or any(
        token in lowered for token in ("by ", "per ", "each")
    )
    return grouped_language


def _share_column_name(metric: Any, aggregation: str) -> str:
    metric_name = str(metric or "").strip()
    if not metric_name or metric_name in {"__row_count__", "row_count", "transaction_count"} or aggregation == "count":
        return "count_share"
    return f"{metric_name}_share"


def _infer_aggregation(lowered: str, default: str) -> str:
    if any(token in lowered for token in ("average", "avg", "mean", "平均")):
        return "mean"
    if any(token in lowered for token in ("sum", "total", "总和", "合计")):
        return "sum"
    if _is_record_count_metric_question(lowered) or re.search(r"\b(count|number of rows|number of records)\b", lowered):
        return "count"
    if any(token in lowered for token in ("max value", "maximum value", "最大值")):
        return "max"
    if any(token in lowered for token in ("min value", "minimum value", "最小值")):
        return "min"
    return default


def _extract_limit(question: str, default: int) -> int:
    match = re.search(r"(?:top|前|最高的?|最低的?|最大的?|最小的?|最多的?|最少的?)\s*(\d+|[一二两三四五六七八九十]+)", question, re.I)
    if not match:
        return default
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    return _small_chinese_number(raw) or default


def _extract_rank_position(question: str) -> int | None:
    for pattern in (
        r"第\s*(\d+|[一二两三四五六七八九十]+)\s*(?:高|低)",
        r"排名\s*第\s*(\d+|[一二两三四五六七八九十]+)",
    ):
        match = re.search(pattern, question)
        if not match:
            continue
        raw = match.group(1)
        value = int(raw) if raw.isdigit() else (_small_chinese_number(raw) or 0)
        if value > 0:
            return value
    lowered = question.lower()
    for token, value in (("second highest", 2), ("second lowest", 2), ("third highest", 3), ("third lowest", 3)):
        if token in lowered:
            return value
    return None


def _small_chinese_number(text: str) -> int | None:
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    text = str(text or "").strip()
    if text in digits:
        return digits[text]
    if text == "十":
        return 10
    if text.startswith("十") and len(text) == 2 and text[1] in digits:
        return 10 + digits[text[1]]
    if text.endswith("十") and len(text) == 2 and text[0] in digits:
        return digits[text[0]] * 10
    if "十" in text and len(text) == 3 and text[0] in digits and text[2] in digits:
        return digits[text[0]] * 10 + digits[text[2]]
    return None


def _infer_value_filters(question: str, df: pd.DataFrame, exclude: set[str | None] | None = None) -> dict[str, Any]:
    lowered = question.lower()
    excluded = {str(item) for item in (exclude or set()) if item}
    numeric_filters = _explicit_numeric_value_filters(question, df)
    explicit_filters = _explicit_semantic_value_filters(question, df, exclude=excluded)
    if numeric_filters or explicit_filters:
        return {**numeric_filters, **explicit_filters}
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


def _rank_position_target_from_question(question: str, df: pd.DataFrame) -> dict[str, Any] | None:
    compact = re.sub(r"\s+", "", str(question or ""))
    lowered = str(question or "").lower()
    if not re.search(r"(?:排|排名|排行|名次|位次)(?:在)?第?几", compact):
        return None
    concept_labels = {
        "city": ("城市", "地区", "区域"),
        "customer": ("客户", "顾客"),
        "product": ("产品", "商品"),
        "category": ("品类", "类别", "类目"),
        "store": ("门店", "店铺"),
        "service_line": ("服务线", "业务线"),
    }
    for concept, labels in concept_labels.items():
        columns = [
            str(column)
            for column in df.columns
            if not pd.api.types.is_numeric_dtype(df[column]) and _semantic_concept_column_score(str(column), concept) > 0
        ]
        if not columns:
            continue
        for column in columns:
            series = df[column]
            unique_values = [value for value in series.dropna().unique().tolist() if str(value)]
            if len(unique_values) > 200:
                continue
            for value in sorted(unique_values, key=lambda item: len(str(item)), reverse=True):
                if _rank_target_value_matches_question(str(value), question, compact, lowered, labels):
                    return {"dimension": column, "value": value}
    return None


def _rank_target_value_matches_question(value_text: str, question: str, compact: str, lowered: str, labels: tuple[str, ...]) -> bool:
    if not value_text or not _value_in_question(value_text, question, lowered):
        return False
    escaped = re.escape(value_text)
    for label in labels:
        if re.search(rf"{escaped}(?:的)?{label}", compact):
            return True
        if re.search(rf"{label}(?:=|为|是)?{escaped}", compact):
            return True
        if any(token in compact for token in (f"全部{label}", f"所有{label}", f"全体{label}", f"{label}中", f"{label}里")):
            return True
    return False


def _explicit_numeric_value_filters(question: str, df: pd.DataFrame) -> dict[str, Any]:
    compact = re.sub(r"\s+", "", str(question or "")).lower()
    if not compact:
        return {}
    filters: dict[str, Any] = {}
    for concept in ("profit", "sales", "tickets"):
        column = _find_semantic_metric_column(question, df, concept)
        if not column:
            continue
        condition = _numeric_condition_for_aliases(compact, SEMANTIC_COLUMN_ALIASES.get(concept) or ())
        if condition:
            filters[column] = condition
    return filters


def _numeric_condition_for_aliases(compact: str, aliases: tuple[str, ...]) -> dict[str, Any]:
    alias_pattern = _numeric_alias_pattern(aliases)
    if not alias_pattern:
        return {}
    if re.search(rf"(?:{alias_pattern})(?:为|是)?(?:正|正数|正值)", compact) or re.search(
        rf"(?:正|正数|正值)的?(?:{alias_pattern})",
        compact,
    ):
        return {"operator": ">", "value": 0}
    if re.search(rf"(?:{alias_pattern})(?:为|是)?(?:负|负数|负值)", compact) or re.search(
        rf"(?:负|负数|负值)的?(?:{alias_pattern})",
        compact,
    ):
        return {"operator": "<", "value": 0}
    comparison_patterns = (
        (">=", (r"不低于", r"不少于", r"大于等于", r"高于等于", r">=")),
        ("<=", (r"不超过", r"不高于", r"小于等于", r"低于等于", r"<=")),
        (">", (r"大于", r"超过", r"高于", r">")),
        ("<", (r"小于", r"低于", r"少于", r"<")),
    )
    number_pattern = r"(-?\d+(?:\.\d+)?|零|一|二|两|三|四|五|六|七|八|九|十)"
    for operator, operator_tokens in comparison_patterns:
        operator_pattern = "|".join(operator_tokens)
        match = re.search(rf"(?:{alias_pattern})(?:的)?(?:{operator_pattern}){number_pattern}", compact)
        if not match:
            continue
        value = _parse_numeric_filter_value(match.group(1))
        if value is not None:
            return {"operator": operator, "value": value}
    return {}


def _numeric_alias_pattern(aliases: tuple[str, ...]) -> str:
    tokens: set[str] = set()
    for alias in aliases:
        text = str(alias or "").strip().lower()
        if not text:
            continue
        tokens.add(text)
        normalized = _normalize_column_token(text)
        if normalized:
            tokens.add(normalized)
    ordered = sorted(tokens, key=len, reverse=True)
    return "|".join(re.escape(token) for token in ordered)


def _parse_numeric_filter_value(raw: str) -> float | int | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        value = float(text)
        return int(value) if value.is_integer() else value
    if text == "零":
        return 0
    value = _small_chinese_number(text)
    return value if value is not None else None


def _explicit_semantic_value_filters(question: str, df: pd.DataFrame, *, exclude: set[str]) -> dict[str, Any]:
    compact = re.sub(r"\s+", "", str(question or ""))
    if not compact:
        return {}
    concept_labels = {
        "city": ("城市", "地区", "区域"),
        "customer": ("客户", "顾客"),
        "product": ("产品", "商品"),
        "category": ("品类", "类别", "类目"),
        "store": ("门店", "店铺"),
    }
    generic_values = {"这个", "那个", "这些", "上述", "刚才", "上一轮", "该", "其", "每个", "各", "哪个", "哪些", "哪家", "哪位", "哪一位", "谁", "哪一个", "哪几个", "多少", "什么", "啥"}
    for concept, labels in concept_labels.items():
        fallback_columns = [
            str(column)
            for column in df.columns
            if str(column) not in exclude
            and not pd.api.types.is_numeric_dtype(df[column])
            and _semantic_concept_column_score(str(column), concept) > 0
        ]
        if not fallback_columns:
            continue
        for label in labels:
            columns = _semantic_filter_columns_for_label(label, df, exclude=exclude, fallback_columns=fallback_columns)
            if not columns:
                continue
            column = columns[0]
            patterns = (
                rf"筛选([\u4e00-\u9fffA-Za-z0-9_-]{{2,30}}){label}的数据",
                rf"{label}(?:=|为|是)([\u4e00-\u9fffA-Za-z0-9_-]{{1,30}})",
            )
            for pattern in patterns:
                match = re.search(pattern, compact)
                if not match:
                    continue
                value = match.group(1).strip("，,。；;:：")
                value = _coerce_explicit_filter_value(value, df[column])
                if value is not None and str(value) not in generic_values:
                    return {column: value}
    return {}


def _semantic_filter_columns_for_label(
    label: str,
    df: pd.DataFrame,
    *,
    exclude: set[str],
    fallback_columns: list[str],
) -> list[str]:
    normalized_label = _normalize_column_token(label)
    direct_columns = [
        str(column)
        for column in df.columns
        if str(column) not in exclude
        and not pd.api.types.is_numeric_dtype(df[column])
        and normalized_label
        and normalized_label in _normalize_column_token(str(column))
    ]
    return direct_columns or fallback_columns


def _coerce_explicit_filter_value(raw_value: str, series: pd.Series) -> Any | None:
    value = str(raw_value or "").strip("，,。；;:：")
    if not value:
        return None
    unique_values = [(str(item), item) for item in series.dropna().unique().tolist() if str(item)]
    for text, original in sorted(unique_values, key=lambda item: len(item[0]), reverse=True):
        if value == text:
            return original
    for text, original in sorted(unique_values, key=lambda item: len(item[0]), reverse=True):
        if not value.startswith(text):
            continue
        suffix = value[len(text):].strip("，,。；;:：")
        if _explicit_filter_suffix_allowed(suffix):
            return original
    return value


def _explicit_filter_suffix_allowed(suffix: str) -> bool:
    if not suffix:
        return True
    return suffix.startswith(("时", "的时候", "期间", "下", "中", "内", "里", "的"))


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
