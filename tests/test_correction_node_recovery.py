from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.llm.client import MockLLMClient
from scripts.run_multi_dataset_real_user_gate import correction_gate_cases
from scripts.run_uk_retail_random_user_gate import _customer_order_count, _customer_sales, _product_month_trend, _product_topn


def _make_service() -> tuple[DataAgentService, str, tempfile.TemporaryDirectory[str]]:
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
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
            ]
        ),
        encoding="utf-8",
    )
    service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
    upload = service.upload_dataset(csv_path, original_filename="orders.csv")
    return service, str(upload["dataset_id"]), temp_dir


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


def test_formula_correction_reruns_previous_turn_with_revised_metric() -> None:
    service, dataset_id, temp_dir = _make_service()
    try:
        first = _ask(
            service,
            dataset_id,
            "卖得最多的前3个商品是什么？",
            conversation_id="conv_correction_formula",
        )
        second = _ask(
            service,
            dataset_id,
            "不是销量口径，改用 Quantity * UnitPrice 重新计算销售额。",
            conversation_id=str(first.get("conversation_id") or "conv_correction_formula"),
        )
        correction_context = second.get("correction_context") or {}
        debug = second.get("debug") or {}

        assert first.get("success") is True, first.get("answer")
        assert second.get("success") is True, second.get("answer")
        assert second.get("semantic_status") == "passed"
        assert correction_context.get("is_correction") is True
        assert "metric_formula" in (correction_context.get("changed_scope") or [])
        assert "Quantity * UnitPrice" in str(correction_context.get("revised_formula") or "")
        assert debug.get("correction_rerun", {}).get("previous_run_id")
        assert _params(second).get("derived_metric", {}).get("formula") == "Quantity * UnitPrice"
    finally:
        temp_dir.cleanup()


def test_uk_retail_correction_gate_cases_cover_metric_time_and_focus_recovery() -> None:
    cases = correction_gate_cases("uk_retail", {})

    assert [case.question for case in cases] == [
        "销售额最高的前5个商品是什么？销售额按 Quantity * UnitPrice 算。",
        "前5商品按月份趋势怎么看？",
        "订单数量最多的前5个客户是谁？",
        "这些客户的销售额分别是多少？销售额按 Quantity * UnitPrice 算。",
    ]
    assert cases[0].expected == _product_topn(5)
    assert cases[1].expected == _product_month_trend()
    assert cases[2].expected == _customer_order_count(5)
    assert cases[3].expected == _customer_sales()
    assert [case.conversation_key for case in cases] == ["corr_product", "corr_product", "corr_customer", "corr_customer"]
