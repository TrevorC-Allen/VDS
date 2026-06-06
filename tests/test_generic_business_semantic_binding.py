from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from backend.routers.data_agent import _http_status_for_response
from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.llm.client import MockLLMClient


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
        "销售额最高的前5个国家是什么？销售额按 Quantity * UnitPrice 算。",
        conversation_id=conversation_id,
    )
    second = _ask(
        service,
        dataset_id,
        "这些国家占比是多少？",
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
    assert all("Sales_share" in row for row in rows)


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


def test_semantic_failure_with_user_answer_is_not_http_500() -> None:
    response = {"success": False, "semantic_status": "failed", "answer": "需要补充字段。", "errors": []}

    assert _http_status_for_response(response) == 200
