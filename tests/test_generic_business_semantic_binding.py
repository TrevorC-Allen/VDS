from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from backend.routers.data_agent import _http_status_for_response
from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.intent_parser import parse_question
from data_agent_core.llm.client import MockLLMClient
from data_agent_core.task_execution_contracts import (
    TaskExecutionContract,
    semantic_status_from_report,
    verify_task_execution_contract,
)


@pytest.fixture()
def generic_order_service() -> tuple[DataAgentService, str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        csv_path = root / "orders.csv"
        csv_path.write_text(
            "\n".join(
                [
                    "InvoiceNo,StockCode,Description,Quantity,InvoiceDate,UnitPrice,CustomerID,Country",
                    "1001,S1,Alpha Lamp,10,2024-01-05,5.0,C1,US",
                    "1002,S2,Beta Bowl,3,2024-01-15,20.0,C2,US",
                    "1003,S1,Alpha Lamp,7,2024-02-02,5.0,C1,CA",
                    "1004,S3,Gamma Mug,12,2024-02-08,3.0,C3,CA",
                    "1005,S2,Beta Bowl,-2,2024-02-10,20.0,C2,US",
                    "1006,S3,Gamma Mug,-5,2024-03-01,3.0,C3,CA",
                    "1007,S4,Delta Pen,4,2024-03-15,2.5,C1,UK",
                    "1007,S4,Delta Pen,1,2024-03-16,2.5,C1,UK",
                    "1008,S5,Epsilon Vase,-1,2024-03-20,10.0,C4,FR",
                    "1009,S6,Zeta Plate,-4,2024-03-22,4.0,C5,DE",
                    "1010,S1,Alpha Lamp,-1,2024-03-25,5.0,C6,US",
                    "1011,S4,Delta Pen,-3,2024-03-26,2.5,C4,UK",
                ]
            ),
            encoding="utf-8",
        )
        service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
        upload = service.upload_dataset(csv_path, original_filename="orders.csv")
        yield service, str(upload["dataset_id"])


def _ask(service: DataAgentService, dataset_id: str, question: str, *, conversation_id: str = "") -> dict[str, Any]:
    return service.respond_to_message(
        dataset_id=dataset_id,
        conversation_id=conversation_id,
        question=question,
        execution_mode="dual",
        agent_mode="multi_agent",
    )


def _params(response: dict[str, Any]) -> dict[str, Any]:
    return ((response.get("logic_form") or {}).get("parameters") or {})


def _rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in ((response.get("result") or {}).get("rows") or []) if isinstance(row, dict)]


def _dabstep_context() -> dict[str, Any]:
    return {
        "payments": pd.DataFrame(
            {
                "psp_reference": ["P1", "P2", "P3"],
                "merchant": ["M1", "M2", "M1"],
                "issuing_country": ["NL", "BE", "NL"],
                "ip_country": ["BE", "NL", "BE"],
                "acquirer_country": ["NL", "US", "NL"],
                "card_scheme": ["NexPay", "GlobalCard", "NexPay"],
                "shopper_interaction": ["Ecommerce", "POS", "Ecommerce"],
                "eur_amount": [10.0, 20.0, 5.0],
                "has_fraudulent_dispute": [True, False, True],
                "is_refused_by_adyen": [False, True, False],
                "aci": ["A", "B", "A"],
            }
        )
    }


def test_dabstep_chinese_amount_topn_binds_metric_dimension_and_sum() -> None:
    logic = parse_question("按 merchant 看 eur_amount 总金额最高的前5个商户。", context=_dabstep_context())

    assert logic.operation == "filtered_metric_ranking"
    assert logic.metric == "eur_amount"
    assert logic.group_by == "merchant"
    assert logic.parameters["dimension"] == "merchant"
    assert logic.parameters["metric"] == "eur_amount"
    assert logic.parameters["aggregation"] == "sum"
    assert logic.parameters["limit"] == 5


def test_dabstep_recommended_amount_topn_keeps_explicit_country_dimension() -> None:
    logic = parse_question("按 issuing_country 看 eur_amount 总金额最高的前5。", context=_dabstep_context())

    assert logic.operation == "filtered_metric_ranking"
    assert logic.metric == "eur_amount"
    assert logic.group_by == "issuing_country"
    assert logic.parameters["dimension"] == "issuing_country"
    assert logic.parameters["metric"] == "eur_amount"
    assert logic.parameters["aggregation"] == "sum"
    assert logic.parameters["limit"] == 5


def test_dabstep_chinese_transaction_count_topn_binds_dimension_count_metric() -> None:
    logic = parse_question("按 acquirer_country 看交易数量排名前5。", context=_dabstep_context())

    assert logic.operation == "ranking"
    assert logic.group_by == "acquirer_country"
    assert logic.metric is None
    assert logic.parameters["dimension"] == "acquirer_country"
    assert logic.parameters["aggregation"] == "count"
    assert logic.parameters["limit"] == 5


def test_dabstep_recommended_count_override_does_not_inherit_amount_metric() -> None:
    logic = parse_question("按 merchant 看交易最多的前5个商户，不要按 eur_amount，要按交易笔数统计。", context=_dabstep_context())

    assert logic.operation == "ranking"
    assert logic.group_by == "merchant"
    assert logic.metric is None
    assert logic.parameters["dimension"] == "merchant"
    assert logic.parameters["aggregation"] == "count"
    assert logic.parameters["limit"] == 5


def test_dabstep_payment_transaction_count_question_binds_row_count_without_empty_filter() -> None:
    logic = parse_question("这个 DABstep 数据有多少笔 payment transaction？", context=_dabstep_context())

    assert logic.operation == "row_count"
    assert logic.filters == {}
    assert logic.parameters["table"] == "payments"


def test_dabstep_shopper_interaction_amount_topn_binds_sum_metric() -> None:
    logic = parse_question("按 shopper_interaction 看 eur_amount 总金额排名前2。", context=_dabstep_context())

    assert logic.operation == "filtered_metric_ranking"
    assert logic.metric == "eur_amount"
    assert logic.group_by == "shopper_interaction"
    assert logic.parameters["dimension"] == "shopper_interaction"
    assert logic.parameters["aggregation"] == "sum"
    assert logic.parameters["limit"] == 2


def test_dabstep_amount_topn_prefers_explicit_group_by_over_metric_column_order() -> None:
    context = _dabstep_context()
    context["payments"] = context["payments"][
        [
            "psp_reference",
            "eur_amount",
            "merchant",
            "issuing_country",
            "ip_country",
            "acquirer_country",
            "card_scheme",
            "shopper_interaction",
            "has_fraudulent_dispute",
            "is_refused_by_adyen",
            "aci",
        ]
    ]

    logic = parse_question("按 shopper_interaction 看 eur_amount 总金额排名前2。", context=context)

    assert logic.operation == "filtered_metric_ranking"
    assert logic.metric == "eur_amount"
    assert logic.group_by == "shopper_interaction"
    assert logic.parameters["dimension"] == "shopper_interaction"


def test_dabstep_chinese_fraud_count_topn_uses_fraud_dispute_filter() -> None:
    logic = parse_question("按 ip_country 看欺诈交易数量前5，欺诈按 has_fraudulent_dispute=True 统计。", context=_dabstep_context())

    assert logic.operation == "filtered_metric_ranking"
    assert logic.group_by == "ip_country"
    assert logic.filters == {"has_fraudulent_dispute": True}
    assert logic.parameters["dimension"] == "ip_country"
    assert logic.parameters["aggregation"] == "count"
    assert logic.parameters["limit"] == 5
    assert logic.numerator == {
        "aggregation": "count",
        "field": "__row_count__",
        "filter": {"has_fraudulent_dispute": True},
        "scope": "filtered_rows",
    }


def test_dabstep_amount_metric_override_is_not_misread_as_transaction_count() -> None:
    logic = parse_question("按 merchant 看总交易金额前5，总金额用 eur_amount 求和，不是交易笔数。", context=_dabstep_context())

    assert logic.operation == "filtered_metric_ranking"
    assert logic.group_by == "merchant"
    assert logic.metric == "eur_amount"
    assert logic.parameters["aggregation"] == "sum"


def test_product_ranking_binds_generic_product_label_and_explicit_formula(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "销售额最高的前5个商品是什么？销售额按 Quantity * UnitPrice 算。")
    params = _params(response)
    trace = ((response.get("debug") or {}).get("execution_trace") or {})

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed"
    assert params.get("dimension") == "Description"
    assert params.get("derived_metric", {}).get("formula") == "Quantity * UnitPrice"
    assert trace.get("formula") == "Quantity * UnitPrice"
    assert trace.get("groupby_columns") == ["Description"]
    assert len(_rows(response)) == 5


def test_product_gap_followup_does_not_require_product_key_column(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service
    conversation_id = "conv_generic_business_product_gap"

    first = _ask(
        service,
        dataset_id,
        "销售额最高的前5个商品是什么？销售额按 Quantity * UnitPrice 算。",
        conversation_id=conversation_id,
    )
    second = _ask(
        service,
        dataset_id,
        "第一名和第二名差多少？",
        conversation_id=str(first.get("conversation_id") or conversation_id),
    )
    task_contract = ((second.get("verification") or {}).get("task_contract") or {})
    required_columns = task_contract.get("required_output_columns") or []
    gap_rows = ((second.get("debug") or {}).get("result_artifacts") or {}).get("gap_rows") or []

    assert first.get("success") is True, first.get("answer")
    assert second.get("success") is True, second.get("answer")
    assert second.get("semantic_status") == "passed"
    assert task_contract.get("task_family") == "gap"
    assert "Description" in required_columns
    assert "Sales" in required_columns
    assert "StockCode" not in required_columns
    assert len(gap_rows) >= 2
    assert "adjacent_gap" in gap_rows[1]


def test_total_explicit_formula_does_not_require_dimension(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "这个数据的总销售额是多少？销售额按 Quantity * UnitPrice 算。")
    params = _params(response)
    result = response.get("result") or {}
    trace = ((response.get("debug") or {}).get("execution_trace") or {})

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed"
    assert not params.get("dimension")
    assert result.get("value", {}).get("Sales") == pytest.approx(100.0)
    assert trace.get("formula") == "Quantity * UnitPrice"
    assert trace.get("groupby_columns") == []


def test_english_revenue_formula_is_not_treated_as_filter(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "total revenue 是多少？revenue = quantity times unit price。")
    trace = ((response.get("debug") or {}).get("execution_trace") or {})

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed"
    assert (response.get("result") or {}).get("columns") == ["Sales"]
    assert (response.get("result") or {}).get("value", {}).get("Sales") == pytest.approx(100.0)
    assert trace.get("formula") == "Quantity * UnitPrice"


def test_customer_order_count_uses_distinct_order_key(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "订单数量最多的前5个客户是谁？")
    params = _params(response)

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed"
    assert params.get("dimension") == "CustomerID"
    assert params.get("metric") == "InvoiceNo"
    assert params.get("aggregation") in {"nunique", "distinct_count"}
    rows = _rows(response)
    assert rows[0]["CustomerID"] == "C1"
    assert rows[0]["count"] == 3


def test_grouped_customer_distinct_count_by_country_passes(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "按国家看客户数，客户按 CustomerID 去重。")
    trace = ((response.get("debug") or {}).get("execution_trace") or {})

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed"
    assert (response.get("result") or {}).get("columns") == ["Country", "count"]
    assert trace.get("aggregation") == "nunique"
    assert "CustomerID" in (trace.get("metric_columns") or [])


def test_customer_sales_topn_ignores_planner_metadata_conditions(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "销售额最高的前10个客户是谁？销售额按 Quantity * UnitPrice 算。")
    trace = ((response.get("debug") or {}).get("execution_trace") or {})

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed"
    assert _params(response).get("dimension") == "CustomerID"
    assert _params(response).get("derived_metric", {}).get("formula") == "Quantity * UnitPrice"
    assert trace.get("formula") == "Quantity * UnitPrice"
    assert not any(item.get("column") == "conditions" for item in trace.get("filters_applied") or [])


def test_returns_by_product_uses_negative_quantity_evidence(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "退货数量最多的前5个商品是什么？")
    params = _params(response)

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed"
    assert params.get("dimension") == "Description"
    assert params.get("metric") == "Quantity"
    assert params.get("aggregation") == "sum_abs"
    assert params.get("return_quantity_evidence") == "negative_quantity"
    assert (response.get("logic_form") or {}).get("filters", {}).get("Quantity") == {"operator": "<", "value": 0}
    rows = _rows(response)
    assert rows[0]["Description"] == "Gamma Mug"
    assert rows[0]["Quantity"] == pytest.approx(5.0)


def test_monthly_sales_trend_uses_invoice_month_bucket(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "按月份看整体销售额趋势，哪些月份最高？")
    params = _params(response)
    columns = (response.get("result") or {}).get("columns") or []

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed"
    assert params.get("dimension") == "month"
    assert params.get("time_column") == "InvoiceDate"
    assert params.get("time_bucket") == "month"
    assert params.get("derived_metric", {}).get("formula") == "Quantity * UnitPrice"
    assert "InvoiceDate" not in columns
    assert columns == ["month", "Sales"]


def test_explicit_description_probe_still_passes(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "按 Description 分组，销售额最高的前5个 Description 是什么？销售额按 Quantity * UnitPrice 算。")

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed"
    assert _params(response).get("dimension") == "Description"


def test_followup_top_products_drills_down_to_country_sales(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service
    conversation_id = "conv_generic_business_followup"

    first = _ask(
        service,
        dataset_id,
        "销售额最高的前5个商品是什么？销售额按 Quantity * UnitPrice 算。",
        conversation_id=conversation_id,
    )
    second = _ask(
        service,
        dataset_id,
        "这些 Top 商品主要卖给哪些国家？分别列出主要国家和销售额。",
        conversation_id=str(first.get("conversation_id") or conversation_id),
    )
    params = _params(second)
    filters = (second.get("logic_form") or {}).get("filters") or {}
    rows = _rows(second)

    assert first.get("success") is True, first.get("answer")
    assert second.get("success") is True, second.get("answer")
    assert second.get("semantic_status") == "passed"
    assert params.get("dimension") == "Country"
    assert params.get("derived_metric", {}).get("formula") == "Quantity * UnitPrice"
    assert params.get("capability_family") == "drilldown_followup"
    assert filters.get("Description") == ["Alpha Lamp", "Gamma Mug", "Beta Bowl", "Delta Pen", "Epsilon Vase"]
    assert rows
    assert set(row["Country"] for row in rows).issubset({"US", "CA", "UK", "FR"})
    assert rows[0]["Country"] == "US"
    assert rows[0]["Sales"] == pytest.approx(65.0)
    assert "范围城市" not in str(second.get("answer") or "")
    assert "范围产品" in str(second.get("answer") or "")


def test_followup_top_products_monthly_trend_inherits_filter_and_formula(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service
    conversation_id = "conv_generic_business_top_products_monthly_trend"

    first = _ask(
        service,
        dataset_id,
        "销售额最高的前5个商品是什么？销售额按 Quantity * UnitPrice 算。",
        conversation_id=conversation_id,
    )
    second = _ask(
        service,
        dataset_id,
        "前5商品按月份趋势怎么看？",
        conversation_id=str(first.get("conversation_id") or conversation_id),
    )
    params = _params(second)
    filters = (second.get("logic_form") or {}).get("filters") or {}
    trace = ((second.get("debug") or {}).get("execution_trace") or {})
    columns = (second.get("result") or {}).get("columns") or []

    assert first.get("success") is True, first.get("answer")
    assert second.get("success") is True, second.get("answer")
    assert second.get("semantic_status") == "passed"
    assert params.get("dimension") == "month"
    assert params.get("time_column") == "InvoiceDate"
    assert params.get("time_bucket") == "month"
    assert params.get("derived_metric", {}).get("formula") == "Quantity * UnitPrice"
    assert filters.get("Description") == ["Alpha Lamp", "Gamma Mug", "Beta Bowl", "Delta Pen", "Epsilon Vase"]
    assert trace.get("formula") == "Quantity * UnitPrice"
    assert trace.get("time_grain") == "month"
    assert trace.get("time_column") == "InvoiceDate"
    assert trace.get("groupby_columns") == ["month", "Description"]
    assert any(item.get("column") == "Description" and item.get("operator") == "in" for item in trace.get("filters_applied") or [])
    assert columns == ["month", "Description", "Sales"]


def test_followup_country_share_inherits_sales_formula(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service
    conversation_id = "conv_generic_business_country_share"

    first = _ask(
        service,
        dataset_id,
        "销售额最高的前3个国家是什么？销售额按 Quantity * UnitPrice 算。",
        conversation_id=conversation_id,
    )
    second = _ask(
        service,
        dataset_id,
        "这些国家分别占总销售额的比例是多少？",
        conversation_id=str(first.get("conversation_id") or conversation_id),
    )
    params = _params(second)
    trace = ((second.get("debug") or {}).get("execution_trace") or {})
    rows = _rows(second)

    assert first.get("success") is True, first.get("answer")
    assert second.get("success") is True, second.get("answer")
    assert second.get("semantic_status") == "passed"
    assert params.get("derived_metric", {}).get("formula") == "Quantity * UnitPrice"
    assert params.get("dimension") == "Country"
    assert trace.get("formula") == "Quantity * UnitPrice"
    assert trace.get("groupby_columns") == ["Country"]
    assert rows
    assert len(rows) == 3
    assert all("Sales_share" in row for row in rows)
    assert all(row.get("total_Sales") == pytest.approx(100.0) for row in rows)
    assert sum(float(row["Sales"]) for row in rows) != pytest.approx(100.0)


def test_followup_customer_sales_formula_overrides_previous_order_count(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service
    conversation_id = "conv_generic_business_customer_metric_override"

    first = _ask(
        service,
        dataset_id,
        "订单数量最多的前5个客户是谁？",
        conversation_id=conversation_id,
    )
    second = _ask(
        service,
        dataset_id,
        "这些客户的销售额分别是多少？销售额按 Quantity * UnitPrice 算。",
        conversation_id=str(first.get("conversation_id") or conversation_id),
    )
    params = _params(second)
    trace = ((second.get("debug") or {}).get("execution_trace") or {})
    columns = (second.get("result") or {}).get("columns") or []
    rows = _rows(second)

    assert first.get("success") is True, first.get("answer")
    assert second.get("success") is True, second.get("answer")
    assert second.get("semantic_status") == "passed"
    assert params.get("dimension") == "CustomerID"
    assert params.get("metric") == "Sales"
    assert params.get("derived_metric", {}).get("formula") == "Quantity * UnitPrice"
    assert trace.get("formula") == "Quantity * UnitPrice"
    assert {"Quantity", "UnitPrice"} <= set(trace.get("metric_columns") or [])
    assert trace.get("groupby_columns") == ["CustomerID"]
    assert columns == ["CustomerID", "Sales"]
    assert all("count" not in row for row in rows)
    assert next(row for row in rows if row["CustomerID"] == "C1")["Sales"] == pytest.approx(97.5)


def test_exact_order_mini_country_share_then_customer_sales_override(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service
    conversation_id = "conv_generic_business_exact_order_mini"

    first = _ask(
        service,
        dataset_id,
        "销售额最高的前5个国家是什么？销售额按 Quantity * UnitPrice 算。",
        conversation_id=conversation_id,
    )
    second = _ask(
        service,
        dataset_id,
        "这些国家分别占总销售额的比例是多少？",
        conversation_id=str(first.get("conversation_id") or conversation_id),
    )
    third = _ask(
        service,
        dataset_id,
        "订单数量最多的前5个客户是谁？",
        conversation_id=str(second.get("conversation_id") or conversation_id),
    )
    fourth = _ask(
        service,
        dataset_id,
        "这些客户的销售额分别是多少？销售额按 Quantity * UnitPrice 算。",
        conversation_id=str(third.get("conversation_id") or conversation_id),
    )

    assert first.get("success") is True, first.get("answer")
    assert second.get("success") is True, second.get("answer")
    assert second.get("semantic_status") == "passed"
    assert all("Sales_share" in row and "total_Sales" in row for row in _rows(second))
    assert third.get("success") is True, third.get("answer")
    assert third.get("semantic_status") == "passed"
    assert _params(third).get("dimension") == "CustomerID"
    assert _params(third).get("metric") == "InvoiceNo"
    assert _params(third).get("aggregation") in {"nunique", "distinct_count"}
    assert (third.get("result") or {}).get("columns") == ["CustomerID", "count"]
    assert len(_rows(third)) == 5
    assert fourth.get("success") is True, fourth.get("answer")
    assert fourth.get("semantic_status") == "passed"
    assert (fourth.get("result") or {}).get("columns") == ["CustomerID", "Sales"]


def test_country_sales_share_explicit_formula_uses_derived_metric(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "Country 销售额占比是多少？销售额按 Quantity * UnitPrice 算。")
    params = _params(response)
    trace = ((response.get("debug") or {}).get("execution_trace") or {})
    rows = _rows(response)

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed"
    assert params.get("dimension") == "Country"
    assert params.get("derived_metric", {}).get("formula") == "Quantity * UnitPrice"
    assert trace.get("formula") == "Quantity * UnitPrice"
    assert trace.get("groupby_columns") == ["Country"]
    assert rows
    assert all("Sales_share" in row for row in rows)


def test_country_sales_share_named_sales_columns_infer_derived_metric(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "Country, Sales, total_Sales, Sales_share 分别是多少？")
    params = _params(response)
    rows = _rows(response)

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed"
    assert params.get("dimension") == "Country"
    assert params.get("derived_metric", {}).get("formula") == "Quantity * UnitPrice"
    assert (response.get("result") or {}).get("columns") == ["Country", "Sales", "total_Sales", "Sales_share"]
    assert rows
    assert all("Sales_share" in row and "total_Sales" in row for row in rows)


def test_product_sales_share_explicit_formula_uses_description_denominator_and_share(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "各商品销售额占比是多少？销售额按 Quantity * UnitPrice 算。")
    params = _params(response)
    rows = _rows(response)

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed"
    assert params.get("dimension") == "Description"
    assert params.get("derived_metric", {}).get("formula") == "Quantity * UnitPrice"
    assert (response.get("result") or {}).get("columns") == ["Description", "Sales", "total_Sales", "Sales_share"]
    assert rows
    assert all("Sales_share" in row for row in rows)
    assert all(row.get("total_Sales") == pytest.approx(100.0) for row in rows)


def test_scalar_distinct_count_does_not_require_groupby(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "有多少个客户？按 CustomerID 去重算。")
    trace = ((response.get("debug") or {}).get("execution_trace") or {})

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed"
    assert _params(response).get("field") == "CustomerID"
    assert trace.get("operation") == "distinct_count"
    assert trace.get("groupby_columns") == []
    assert (response.get("result") or {}).get("value") == 6


def test_return_quantity_monthly_trend_uses_month_bucket(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "按月看退货数量趋势，退货按 Quantity<0 统计。")
    columns = (response.get("result") or {}).get("columns") or []
    trace = ((response.get("debug") or {}).get("execution_trace") or {})

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed"
    assert columns == ["month", "Quantity"]
    assert "InvoiceDate" not in columns
    assert trace.get("time_grain") == "month"
    assert trace.get("groupby_columns") == ["month"]


def test_unknown_named_field_fails_safely_without_default_ranking(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "按 FooBar 看销售额。")

    assert response.get("success") is False
    assert response.get("semantic_status") in {"failed", "needs_clarification"}
    assert (response.get("logic_form") or {}).get("operation") == "not_applicable"
    params = _params(response)
    assert params.get("dimension") != "FooBar"
    assert params.get("metric") != "Sales"
    assert (response.get("result") or {}).get("columns") == ["answer"]


def test_ambiguous_meaningful_customer_ranking_fails_safely(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "找最有意义的5个客户。")

    assert response.get("success") is False
    assert response.get("semantic_status") in {"failed", "needs_clarification"}
    assert (response.get("logic_form") or {}).get("operation") == "not_applicable"
    assert (response.get("result") or {}).get("columns") == ["answer"]


def test_grouped_product_order_count_uses_distinct_order_key(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "每个商品被多少订单购买过？按 InvoiceNo 去重。")
    trace = ((response.get("debug") or {}).get("execution_trace") or {})

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed"
    assert _params(response).get("dimension") == "Description"
    assert _params(response).get("metric") == "InvoiceNo"
    assert _params(response).get("aggregation") in {"nunique", "distinct_count"}
    assert (response.get("result") or {}).get("columns") == ["Description", "count"]
    assert trace.get("aggregation") == "nunique"
    assert "InvoiceNo" in (trace.get("metric_columns") or [])
    assert "Description" in (trace.get("groupby_columns") or [])


def test_customer_purchase_count_plural_defaults_to_top5_distinct_orders(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "客户购买次数最多的是哪些？购买次数按 InvoiceNo 去重。")
    trace = ((response.get("debug") or {}).get("execution_trace") or {})

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed"
    assert _params(response).get("dimension") == "CustomerID"
    assert _params(response).get("metric") == "InvoiceNo"
    assert _params(response).get("aggregation") in {"nunique", "distinct_count"}
    assert _params(response).get("limit") == 5
    assert len(_rows(response)) == 5
    assert trace.get("aggregation") == "nunique"
    assert "InvoiceNo" in (trace.get("metric_columns") or [])


def test_country_monthly_sales_trend_uses_month_bucket_and_country_series(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service

    response = _ask(service, dataset_id, "按国家再看销售趋势，月粒度。")
    trace = ((response.get("debug") or {}).get("execution_trace") or {})
    columns = (response.get("result") or {}).get("columns") or []

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed"
    assert _params(response).get("dimension") == "month"
    assert _params(response).get("series_dimension") == "Country"
    assert _params(response).get("time_bucket") == "month"
    assert columns == ["month", "Country", "Sales"]
    assert trace.get("time_grain") == "month"
    assert trace.get("groupby_columns") == ["month", "Country"]


def test_month_ranking_followup_keeps_month_bucket_context(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service
    conversation_id = "conv_generic_business_month_ranking_followup"

    first = _ask(
        service,
        dataset_id,
        "按月份看整体销售额趋势，销售额按 Quantity * UnitPrice 算。",
        conversation_id=conversation_id,
    )
    second = _ask(
        service,
        dataset_id,
        "哪些月份最高？",
        conversation_id=str(first.get("conversation_id") or conversation_id),
    )
    trace = ((second.get("debug") or {}).get("execution_trace") or {})

    assert first.get("success") is True, first.get("answer")
    assert second.get("success") is True, second.get("answer")
    assert second.get("semantic_status") == "passed"
    assert _params(second).get("dimension") == "month"
    assert (second.get("result") or {}).get("columns") == ["month", "Sales"]
    assert trace.get("time_grain") == "month"
    assert trace.get("groupby_columns") == ["month"]


def test_gap_followup_with_two_ordinals_uses_previous_ranking_not_single_rank(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service
    conversation_id = "conv_generic_business_two_ordinal_gap"

    first = _ask(
        service,
        dataset_id,
        "销售额最高的前3个国家是什么？销售额按 Quantity * UnitPrice 算。",
        conversation_id=conversation_id,
    )
    second = _ask(
        service,
        dataset_id,
        "第二名比第一名少多少？",
        conversation_id=str(first.get("conversation_id") or conversation_id),
    )
    gap_rows = ((second.get("debug") or {}).get("result_artifacts") or {}).get("gap_rows") or []

    assert first.get("success") is True, first.get("answer")
    assert second.get("success") is True, second.get("answer")
    assert second.get("semantic_status") == "passed"
    assert _params(second).get("dimension") == "Country"
    assert len(gap_rows) >= 2
    assert gap_rows[1].get("gap_to_leader") is not None


def test_followup_top_products_short_reference_drills_down_to_country_sales(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service
    conversation_id = "conv_generic_business_top_products_short_ref_country"

    first = _ask(
        service,
        dataset_id,
        "销售额最高的前5个商品是什么？销售额按 Quantity * UnitPrice 算。",
        conversation_id=conversation_id,
    )
    second = _ask(
        service,
        dataset_id,
        "这前5商品主要卖给哪些国家？",
        conversation_id=str(first.get("conversation_id") or conversation_id),
    )
    params = _params(second)
    filters = (second.get("logic_form") or {}).get("filters") or {}
    trace = ((second.get("debug") or {}).get("execution_trace") or {})

    assert first.get("success") is True, first.get("answer")
    assert second.get("success") is True, second.get("answer")
    assert second.get("semantic_status") == "passed"
    assert params.get("dimension") == "Country"
    assert params.get("metric") == "Sales"
    assert params.get("derived_metric", {}).get("formula") == "Quantity * UnitPrice"
    assert params.get("capability_family") == "drilldown_followup"
    assert filters.get("Description") == ["Alpha Lamp", "Gamma Mug", "Beta Bowl", "Delta Pen", "Epsilon Vase"]
    assert (second.get("result") or {}).get("columns") == ["Country", "Sales"]
    assert trace.get("formula") == "Quantity * UnitPrice"
    assert trace.get("groupby_columns") == ["Country"]


def test_followup_country_order_count_uses_distinct_invoice_not_quantity(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service
    conversation_id = "conv_generic_business_country_order_count_after_share"

    first = _ask(
        service,
        dataset_id,
        "销售额最高的前5个国家是什么？销售额按 Quantity * UnitPrice 算。",
        conversation_id=conversation_id,
    )
    second = _ask(
        service,
        dataset_id,
        "这些国家分别占总销售额的比例是多少？",
        conversation_id=str(first.get("conversation_id") or conversation_id),
    )
    third = _ask(
        service,
        dataset_id,
        "按这些国家看订单数量前5。",
        conversation_id=str(second.get("conversation_id") or conversation_id),
    )
    trace = ((third.get("debug") or {}).get("execution_trace") or {})

    assert first.get("success") is True, first.get("answer")
    assert second.get("success") is True, second.get("answer")
    assert third.get("success") is True, third.get("answer")
    assert third.get("semantic_status") == "passed"
    assert _params(third).get("dimension") == "Country"
    assert _params(third).get("metric") == "InvoiceNo"
    assert _params(third).get("aggregation") in {"nunique", "distinct_count"}
    assert (third.get("result") or {}).get("columns") == ["Country", "count"]
    assert "Quantity" not in (third.get("result") or {}).get("columns", [])
    assert trace.get("aggregation") == "nunique"
    assert trace.get("metric_columns") == ["InvoiceNo"]


def test_month_referent_country_ranking_uses_virtual_month_filter_only(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service
    conversation_id = "conv_generic_business_month_referent_country"

    first = _ask(
        service,
        dataset_id,
        "按月份看整体销售额趋势，销售额按 Quantity * UnitPrice 算。",
        conversation_id=conversation_id,
    )
    second = _ask(
        service,
        dataset_id,
        "哪些月份最高？",
        conversation_id=str(first.get("conversation_id") or conversation_id),
    )
    third = _ask(
        service,
        dataset_id,
        "这些高月份里销售额最高的国家是哪些？",
        conversation_id=str(second.get("conversation_id") or conversation_id),
    )
    filters = (third.get("logic_form") or {}).get("filters") or {}
    trace = ((third.get("debug") or {}).get("execution_trace") or {})

    assert first.get("success") is True, first.get("answer")
    assert second.get("success") is True, second.get("answer")
    assert third.get("success") is True, third.get("answer")
    assert third.get("semantic_status") == "passed"
    assert _params(third).get("dimension") == "Country"
    assert filters.get("month") == ["2024-01", "2024-02", "2024-03"]
    assert "InvoiceDate" not in filters
    assert (third.get("result") or {}).get("columns") == ["Country", "Sales"]
    assert not any(item.get("operator") == "date_part" for item in trace.get("filters_applied") or [])
    assert any(item.get("column") == "month" and item.get("operator") == "in" for item in trace.get("filters_applied") or [])


def test_followup_top_customers_drills_down_to_product_quantity(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service
    conversation_id = "conv_generic_business_top_customers_product_drilldown"

    first = _ask(
        service,
        dataset_id,
        "订单数量最多的前5个客户是谁？",
        conversation_id=conversation_id,
    )
    second = _ask(
        service,
        dataset_id,
        "这5个客户在哪些月份最活跃？",
        conversation_id=str(first.get("conversation_id") or conversation_id),
    )
    third = _ask(
        service,
        dataset_id,
        "列出这5个客户买最多的前5个商品。",
        conversation_id=str(second.get("conversation_id") or conversation_id),
    )
    filters = (third.get("logic_form") or {}).get("filters") or {}
    trace = ((third.get("debug") or {}).get("execution_trace") or {})

    assert first.get("success") is True, first.get("answer")
    assert second.get("success") is True, second.get("answer")
    assert third.get("success") is True, third.get("answer")
    assert third.get("semantic_status") == "passed"
    assert _params(third).get("dimension") == "Description"
    assert _params(third).get("metric") == "Quantity"
    assert filters.get("CustomerID") == ["C1", "C2", "C3", "C4", "C5"]
    assert (third.get("result") or {}).get("columns") == ["Description", "Quantity"]
    assert trace.get("groupby_columns") == ["Description"]


def test_followup_stockcode_monthly_trend_keeps_stockcode_series(
    generic_order_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = generic_order_service
    conversation_id = "conv_generic_business_stockcode_monthly_trend"

    first = _ask(
        service,
        dataset_id,
        "按 StockCode 查看销售额最高的前5个商品。",
        conversation_id=conversation_id,
    )
    second = _ask(
        service,
        dataset_id,
        "这些 StockCode 按月份趋势怎么看？",
        conversation_id=str(first.get("conversation_id") or conversation_id),
    )
    filters = (second.get("logic_form") or {}).get("filters") or {}
    trace = ((second.get("debug") or {}).get("execution_trace") or {})

    assert first.get("success") is True, first.get("answer")
    assert second.get("success") is True, second.get("answer")
    assert second.get("semantic_status") == "passed"
    assert _params(second).get("dimension") == "month"
    assert _params(second).get("series_dimension") == "StockCode"
    assert _params(second).get("derived_metric", {}).get("formula") == "Quantity * UnitPrice"
    assert filters.get("StockCode") == ["S1", "S3", "S2", "S4", "S5"]
    assert (second.get("result") or {}).get("columns") == ["month", "StockCode", "Sales"]
    assert trace.get("groupby_columns") == ["month", "StockCode"]


def test_contribution_contract_rejects_share_result_without_share_column() -> None:
    contract = TaskExecutionContract(
        contract_id="contract_missing_share",
        task_family="contribution_followup",
        metric="Sales",
        dimension="Country",
        referent_dimension="Country",
        referent_values=["US", "CA"],
        required_output_columns=["Country", "Sales", "total_Sales", "Sales_share"],
        required_answer_elements=["referent_value", "metric_value", "total_metric_value", "share"],
        verification_rules={
            "share_column": "Sales_share",
            "denominator_total_metric": "total_Sales",
            "per_referent_share_required": True,
        },
    )
    result = ExecutionResult(
        backend="unit",
        success=True,
        columns=["Country", "Sales"],
        rows=[{"Country": "US", "Sales": 65.0}, {"Country": "CA", "Sales": 56.0}],
        value=[{"Country": "US", "Sales": 65.0}, {"Country": "CA", "Sales": 56.0}],
        summary="US and CA sales.",
    )

    report = verify_task_execution_contract(contract, result)
    codes = {violation.code for violation in report.violations}

    assert report.passed is False
    assert semantic_status_from_report(contract=contract, report=report) != "passed"
    assert "CONTRIBUTION_SHARE_MISSING" in codes


def test_semantic_failure_with_user_answer_is_not_http_500() -> None:
    response = {"success": False, "semantic_status": "failed", "answer": "需要补充字段。", "errors": []}

    assert _http_status_for_response(response) == 200
