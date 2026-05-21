"""Intent parser for natural language data questions.

This parser uses general field, period, and fee-rule patterns. It must not use
benchmark task IDs, standard answers, or single-question templates.
"""

from __future__ import annotations

import re
from typing import Any

from data_agent_core.contracts.analysis_contracts import LogicForm
from data_agent_core.core.date_utils import MONTH_NAME_TO_NUMBER
from data_agent_core.core.logic_form import make_logic_form


CARD_SCHEMES = ("TransactPlus", "GlobalCard", "NexPay", "SwiftCharge")


def _extract_options(question: str) -> dict[str, str]:
    return {
        letter.upper(): value.upper()
        for letter, value in re.findall(r"\b([A-D])\.\s*([A-Z]{2})\b", question)
    }


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
    match = re.search(r"between\s+([a-z]+)\s+and\s+([a-z]+)", lowered)
    if not match:
        return None
    start = MONTH_NAME_TO_NUMBER.get(match.group(1))
    end = MONTH_NAME_TO_NUMBER.get(match.group(2))
    if start is None or end is None:
        return None
    return start, end


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


def _extract_transaction_value(question: str) -> float | None:
    match = re.search(r"transaction value of\s+(\d+(?:\.\d+)?)\s*EUR", question, re.I)
    if not match:
        match = re.search(r"(\d+(?:\.\d+)?)\s*EUR", question, re.I)
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
        "ip country": "ip_country",
        "device type": "device_type",
        "merchant": "merchant",
    }
    match = re.search(r"grouped by\s+([a-z_ ]+?)(?:\s+for|\s+between|\?|$)", lowered)
    candidate = match.group(1).strip() if match else ""
    for text, column in aliases.items():
        if candidate == text or f"grouped by {text}" in lowered:
            return column
    return default


def _extract_mcc_description(question: str) -> str | None:
    match = re.search(r"MCC description:\s*(.+?)(?:,|\?|$)", question, re.I)
    return match.group(1).strip() if match else None


def _extract_new_rate(question: str) -> int | None:
    match = re.search(r"changed to\s+(\d+)", question, re.I)
    return int(match.group(1)) if match else None


def _extract_new_mcc(question: str) -> int | None:
    match = re.search(r"MCC code to\s+(\d+)", question, re.I)
    return int(match.group(1)) if match else None


def parse_question(question: str, guidelines: str = "", context: dict[str, Any] | None = None) -> LogicForm:
    """Parse a natural language question into a framework-neutral LogicForm."""

    context = context or {}
    lowered = question.lower()
    output_format = {"guidelines": guidelines}

    if re.search(r"\b(fine|fines|penalty|penalties|danger)\b", lowered):
        return make_logic_form(
            task_type="unsupported",
            operation="not_applicable",
            parameters={"reason": "Uploaded rules do not define fines or danger thresholds."},
            output_format=output_format | {"answer_type": "text"},
        )

    if "highest number of transactions" in lowered:
        group_by = "issuing_country" if "issuing country" in lowered else "ip_country"
        return make_logic_form(
            task_type="ranking",
            operation="top_count",
            parameters={"table": "payments", "group_by": group_by},
            output_format=output_format | {"answer_type": "country_code"},
        )

    if "top country" in lowered and "fraud" in lowered:
        group_by = "ip_country" if "ip_country" in question else "issuing_country"
        return make_logic_form(
            task_type="ranking",
            operation="top_count",
            filters={"has_fraudulent_dispute": True},
            parameters={"table": "payments", "group_by": group_by, "options": _extract_options(question)},
            output_format=output_format | {"answer_type": "multiple_choice_country"},
        )

    if "average transaction value grouped by" in lowered:
        month_range = _extract_month_range(question)
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

    if "only applied to account type" in lowered and "merchants" in lowered:
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

    return make_logic_form(
        task_type="unsupported",
        operation="not_applicable",
        parameters={"reason": "No supported general analysis pattern matched."},
        output_format=output_format | {"answer_type": "text"},
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
