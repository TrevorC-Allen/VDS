from __future__ import annotations

from scripts.run_uk_retail_random_user_gate import (
    ExpectedContract,
    score_response,
    _single_ambiguous,
)


def _response(
    *,
    success: bool = True,
    semantic_status: str = "passed",
    answer: str = "ok",
    columns: list[str] | None = None,
    rows: list[dict[str, object]] | None = None,
    params: dict[str, object] | None = None,
    trace: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "success": success,
        "semantic_status": semantic_status,
        "answer": answer,
        "result": {"columns": columns or [], "rows": rows or []},
        "logic_form": {"parameters": params or {}},
        "debug": {"execution_trace": trace or {}},
    }


def test_blocked_answer_cannot_be_semantic_passed() -> None:
    response = _response(
        success=False,
        semantic_status="passed",
        answer="这个问题暂时不能可靠回答，当前还缺少字段。",
    )

    score = score_response(
        question="销售额最高的前5个商品是什么？",
        response=response,
        http_status=200,
        expected=ExpectedContract("product TopN", required_columns=("Description", "Sales"), answerable=True),
    )

    assert score.score == "hard_fail"
    assert "false_semantic_passed_blocked_answer" in score.hard_reasons
    assert "false_semantic_passed_success_false" in score.hard_reasons


def test_country_share_requires_total_and_share_columns() -> None:
    response = _response(
        columns=["Country", "Sales"],
        rows=[{"Country": "UK", "Sales": 100}],
        params={"dimension": "Country", "metric": "Sales", "derived_metric": {"formula": "Quantity * UnitPrice"}},
        trace={"formula": "Quantity * UnitPrice", "groupby_columns": ["Country"]},
    )

    score = score_response(
        question="Country 销售额占比是多少？",
        response=response,
        http_status=200,
        expected=ExpectedContract(
            "country share",
            required_columns=("Country", "Sales", "total_Sales", "Sales_share"),
            allowed_dimensions=("Country",),
            allowed_metrics=("Sales",),
            require_formula=True,
            require_share=True,
        ),
    )

    assert score.score == "hard_fail"
    assert "required_columns_missing:total_Sales,Sales_share" in score.hard_reasons
    assert "share_column_missing" in score.hard_reasons
    assert "share_denominator_missing" in score.hard_reasons


def test_monthly_trend_rejects_raw_invoice_date_rows() -> None:
    response = _response(
        columns=["InvoiceDate", "Sales"],
        rows=[{"InvoiceDate": "2011-12-09T09:15:00", "Sales": 100}],
        params={"dimension": "InvoiceDate", "metric": "Sales", "derived_metric": {"formula": "Quantity * UnitPrice"}},
        trace={"formula": "Quantity * UnitPrice", "groupby_columns": ["InvoiceDate"], "time_column": "InvoiceDate"},
    )

    score = score_response(
        question="按月份看整体销售额趋势。",
        response=response,
        http_status=200,
        expected=ExpectedContract(
            "time trend",
            required_columns=("month", "Sales"),
            allowed_dimensions=("month",),
            allowed_metrics=("Sales",),
            require_formula=True,
            require_month_bucket=True,
            forbidden_columns=("InvoiceDate",),
        ),
    )

    assert score.score == "hard_fail"
    assert "required_columns_missing:month" in score.hard_reasons
    assert "forbidden_columns_present:InvoiceDate" in score.hard_reasons
    assert "month_bucket_missing" in score.hard_reasons
    assert "raw_invoice_date_returned" in score.hard_reasons


def test_nonexistent_field_safe_failure_is_acceptable_soft_fail() -> None:
    response = _response(
        success=False,
        semantic_status="failed",
        answer="当前上传表结构里没有 FooBar 字段，不能编造结果。",
        columns=[],
        rows=[],
    )

    score = score_response(
        question="按 FooBar 看销售额。",
        response=response,
        http_status=200,
        expected=ExpectedContract("ambiguous / dirty input", answerable=False, safe_failure_expected=True),
    )

    assert score.score == "soft_fail"
    assert score.soft_reasons == ["expected_safe_failure"]


def test_customer_order_count_must_use_distinct_invoice_no() -> None:
    response = _response(
        columns=["CustomerID", "Quantity"],
        rows=[{"CustomerID": "C1", "Quantity": 99}],
        params={"dimension": "CustomerID", "metric": "Quantity", "aggregation": "sum"},
        trace={"groupby_columns": ["CustomerID"], "metric_columns": ["Quantity"], "aggregation": "sum"},
    )

    score = score_response(
        question="订单数量最多的前5个客户是谁？",
        response=response,
        http_status=200,
        expected=ExpectedContract(
            "customer",
            required_columns=("CustomerID", "count"),
            allowed_dimensions=("CustomerID",),
            allowed_metrics=("InvoiceNo",),
            require_distinct_order=True,
        ),
    )

    assert score.score == "hard_fail"
    assert "required_columns_missing:count" in score.hard_reasons
    assert "metric_mismatch:expected_one_of=InvoiceNo" in score.hard_reasons
    assert "order_count_not_distinct_invoiceno" in score.hard_reasons


def test_scalar_order_count_accepts_distinct_invoice_no_trace() -> None:
    response = _response(
        columns=["answer"],
        rows=[{"answer": 22061}],
        params={},
        trace={"metric_columns": ["InvoiceNo"], "aggregation": "nunique", "groupby_columns": []},
    )

    score = score_response(
        question="这个数据集有多少订单？按 InvoiceNo 去重算。",
        response=response,
        http_status=200,
        expected=ExpectedContract(
            "count distinct",
            min_rows=1,
            allowed_metrics=("InvoiceNo",),
            require_distinct_order=True,
        ),
    )

    assert score.score == "pass"


def test_product_topn_with_description_and_sales_formula_passes() -> None:
    response = _response(
        columns=["Description", "Sales"],
        rows=[
            {"Description": "A", "Sales": 10, "metric_formula": "Quantity * UnitPrice"},
            {"Description": "B", "Sales": 9, "metric_formula": "Quantity * UnitPrice"},
        ],
        params={"dimension": "Description", "metric": "Sales", "derived_metric": {"formula": "Quantity * UnitPrice"}},
        trace={"formula": "Quantity * UnitPrice", "groupby_columns": ["Description"], "metric_columns": ["Quantity", "UnitPrice"]},
    )

    score = score_response(
        question="销售额最高的前2个商品是什么？",
        response=response,
        http_status=200,
        expected=ExpectedContract(
            "product TopN",
            min_rows=2,
            required_columns=("Description", "Sales"),
            allowed_dimensions=("Description", "StockCode"),
            allowed_metrics=("Sales",),
            require_formula=True,
            require_topn=True,
            expected_n=2,
        ),
    )

    assert score.score == "pass"


def test_sentence_summary_template_is_scored_as_overview() -> None:
    import random

    seen = {}
    for seed in range(100):
        question, expected = _single_ambiguous(random.Random(seed))
        seen[question] = expected

    expected = seen["把所有字段汇总成一句话。"]
    assert expected.category == "overview"
    assert expected.safe_failure_expected is False
    assert expected.answerable is True
