from __future__ import annotations

from scripts.run_uk_retail_frontend_manual_gate import _manual_recommendation_expected, _score_manual_response


def _response(
    *,
    success: bool = True,
    semantic_status: str = "passed",
    columns: list[str] | None = None,
    rows: list[dict[str, object]] | None = None,
    params: dict[str, object] | None = None,
    trace: dict[str, object] | None = None,
    answer: str = "ok",
) -> dict[str, object]:
    return {
        "success": success,
        "semantic_status": semantic_status,
        "answer": answer,
        "result": {"columns": columns or [], "rows": rows or []},
        "logic_form": {"parameters": params or {}},
        "debug": {"execution_trace": trace or {}},
    }


def test_manual_gate_rejects_invoice_lookup_filter_mismatch() -> None:
    response = _response(
        columns=["InvoiceNo", "Quantity"],
        rows=[{"InvoiceNo": "536365", "Quantity": 6}, {"InvoiceNo": "536366", "Quantity": 2}],
        params={"conditions": [{"column": "InvoiceNo", "operator": "=", "value": "536365"}]},
        trace={"filters_applied": [{"column": "InvoiceNo", "operator": "eq", "values": ["536365"]}]},
    )

    reasons = _score_manual_response(
        question="提供invoice no 536365的所有数据行",
        response=response,
        http_status=200,
        expected="invoice_lookup",
    )

    assert "invoice_filter_mismatch:536366" in reasons


def test_manual_gate_accepts_numeric_invoice_lookup_filter_equivalence() -> None:
    response = _response(
        columns=["InvoiceNo", "Quantity"],
        rows=[{"InvoiceNo": 536365.0, "Quantity": 6}],
        params={"conditions": [{"column": "InvoiceNo", "operator": "=", "value": "536365"}]},
        trace={"filters_applied": [{"column": "InvoiceNo", "operator": "eq", "values": ["536365"]}]},
    )

    reasons = _score_manual_response(
        question="提供invoice no 536365的所有数据行",
        response=response,
        http_status=200,
        expected="invoice_lookup",
    )

    assert reasons == []


def test_manual_gate_rejects_store_safe_failure_invoice_no_fallback() -> None:
    response = _response(
        success=True,
        semantic_status="passed",
        columns=["InvoiceNo", "Sales"],
        rows=[{"InvoiceNo": "536365", "Sales": 100.0}],
        params={"dimension": "InvoiceNo", "metric": "Sales", "derived_metric": {"formula": "Quantity * UnitPrice"}},
        trace={"groupby_columns": ["InvoiceNo"], "formula": "Quantity * UnitPrice"},
    )

    reasons = _score_manual_response(
        question="销售额最大的店家",
        response=response,
        http_status=200,
        expected="store_safe_failure",
    )

    assert "store_missing_dimension_marked_passed" in reasons
    assert "store_missing_dimension_fabricated_rows" in reasons
    assert "store_missing_dimension_fell_back_to_invoice_no" in reasons


def test_manual_gate_accepts_customer_spend_with_filter_and_formula() -> None:
    response = _response(
        columns=["Sales"],
        rows=[{"Sales": 5391.21, "metric_formula": "Quantity * UnitPrice"}],
        params={"metric": "Sales", "derived_metric": {"formula": "Quantity * UnitPrice"}},
        trace={
            "formula": "Quantity * UnitPrice",
            "metric_columns": ["Quantity", "UnitPrice"],
            "filters_applied": [{"column": "CustomerID", "operator": "eq", "values": ["17850"]}],
        },
    )

    reasons = _score_manual_response(
        question="CustomerID=17850 的销售额是多少？",
        response=response,
        http_status=200,
        expected="customer_spend",
    )

    assert reasons == []


def test_manual_gate_rejects_country_drilldown_without_month_bucket_or_filter() -> None:
    response = _response(
        columns=["InvoiceDate", "Quantity"],
        rows=[{"InvoiceDate": "2011-01-01", "Quantity": 10}],
        params={"dimension": "InvoiceDate", "metric": "Quantity", "time_column": "InvoiceDate"},
        trace={"groupby_columns": ["InvoiceDate"], "time_column": "InvoiceDate"},
    )

    reasons = _score_manual_response(
        question="把排名靠前的Country按InvoiceDate继续下钻",
        response=response,
        http_status=200,
        expected="country_invoice_date_month_drilldown",
    )

    assert "required_columns_missing:month,Country" in reasons
    assert "month_bucket_missing" in reasons
    assert "country_filter_missing" in reasons


def test_manual_recommendation_expected_keeps_country_quantity_metric() -> None:
    assert _manual_recommendation_expected("按 Country 看 Quantity 的 Top 排名") == "country_quantity_topn"
    assert _manual_recommendation_expected("比较 Top 结果之间的Quantity差距有多大") == "country_quantity_gap"
    assert _manual_recommendation_expected("这些客户的销售额分别是多少？销售额按 Quantity * UnitPrice 算") == ""
