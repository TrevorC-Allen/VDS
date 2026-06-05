"""Retail single-CSV Product Floor paraphrase regression tests."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.llm.client import MockLLMClient


SELECTED_FAMILY_ID = "F4"

RETAIL_INTENT_FAMILIES: list[dict[str, Any]] = [
    {
        "family_id": "F1",
        "canonical_intent": "Rank countries by total Quantity in a single Online Retail table.",
        "required_fields": ["Country", "Quantity"],
        "metric": "Quantity",
        "dimension": "Country",
        "operation": "topn/ranking",
        "context_needed": "Single Online Retail fact table; no prior conversation required.",
        "query_variants": [
            "按 Country 看 Quantity 的 Top 排名",
            "哪些国家的销量最高？",
            "各国家购买数量排名",
            "Quantity 最大的国家有哪些？",
            "按国家统计销量，排个序",
            "country 维度下 quantity top",
            "哪个国家买得最多？",
            "给我国家销量排行榜",
            "Top countries by quantity",
            "Rank countries by total quantity",
            "按国家汇总件数，看看前几名",
            "哪些 Country 的 Quantity 总和最高？",
        ],
        "forbidden_behavior": [
            "Do not rank raw InvoiceDate rows.",
            "Do not return a missing-field clarification when Country and Quantity exist.",
            "Do not use UnitPrice as the metric.",
        ],
    },
    {
        "family_id": "F2",
        "canonical_intent": "Show Country contribution/share of total Quantity.",
        "required_fields": ["Country", "Quantity"],
        "metric": "Quantity",
        "dimension": "Country",
        "operation": "share/contribution/composition",
        "context_needed": "Single Online Retail fact table; share denominator is total Quantity.",
        "query_variants": [
            "按 Country 拆分 Quantity 的构成和集中度",
            "各国家销量占比是多少？",
            "UK 占总 Quantity 的比例是多少？",
            "国家维度的 Quantity 贡献",
            "看看销量主要集中在哪些国家",
            "Quantity by country share",
            "country contribution to total quantity",
            "各国家贡献了多少销量？",
            "国家销量结构",
            "按国家看数量分布和占比",
        ],
        "forbidden_behavior": [
            "Do not count rows when Quantity is requested.",
            "Do not omit share/contribution columns.",
            "Do not block the analysis because CustomerID has missing values.",
        ],
    },
    {
        "family_id": "F3",
        "canonical_intent": "Rank countries by derived Sales/Revenue = Quantity * UnitPrice.",
        "required_fields": ["Country", "Quantity", "UnitPrice"],
        "metric": "Sales",
        "dimension": "Country",
        "operation": "topn/ranking or aggregation",
        "context_needed": "Formula must be retained as Quantity * UnitPrice.",
        "query_variants": [
            "哪个国家销售额最高？",
            "按 Country 看销售额排名",
            "Top countries by revenue",
            "用 Quantity 乘 UnitPrice 算销售额，按国家排名",
            "哪些国家贡献的金额最多？",
            "国家收入排行榜",
            "sales by country",
            "revenue ranking by country",
            "按国家汇总订单金额",
            "Country 维度销售额 TopN",
        ],
        "forbidden_behavior": [
            "Do not rank UnitPrice alone.",
            "Do not drop Country from the result shape.",
            "Do not hide the derived formula.",
        ],
    },
    {
        "family_id": "F4",
        "canonical_intent": "Bucket InvoiceDate by month and show Quantity or Sales trend.",
        "required_fields": ["InvoiceDate", "Quantity", "UnitPrice"],
        "metric": "Quantity or Sales",
        "dimension": "InvoiceDate month",
        "operation": "trend",
        "context_needed": "Time bucket is month; Sales requires Quantity * UnitPrice.",
        "query_variants": [
            "按月看 Quantity 趋势",
            "Quantity 的月度变化",
            "每个月销量是多少？",
            "monthly quantity trend",
            "按 InvoiceDate 汇总到月份看走势",
            "销售额月度趋势",
            "revenue by month",
            "过去一年每月销售额变化",
            "月度销量曲线",
            "按月份统计销售额",
        ],
        "forbidden_behavior": [
            "Do not group by raw day when month is requested.",
            "Do not ignore InvoiceDate.",
            "Do not rank countries instead of returning a time series.",
        ],
    },
    {
        "family_id": "F5",
        "canonical_intent": "Find top 3 countries by Sales, then monthly Sales trend for those countries.",
        "required_fields": ["Country", "InvoiceDate", "Quantity", "UnitPrice"],
        "metric": "Sales",
        "dimension": "Country + InvoiceDate month",
        "operation": "topn + trend",
        "context_needed": "Top country focus set must be preserved into the monthly trend.",
        "query_variants": [
            "选择过去一年销售额前 3 的国家，分别给出其月度趋势图",
            "找出最近一年收入最高的三个国家，再看它们每月走势",
            "Top 3 countries by revenue, monthly trend",
            "销售额最高的三个国家，按月展开",
            "前三大国家的月度销售额变化",
            "过去一年 top countries revenue trend by month",
            "先找销售额前三国家，再画月度趋势",
            "三个最高收入国家的 monthly revenue trend",
        ],
        "forbidden_behavior": [
            "Do not compute a global monthly trend without top-country filtering.",
            "Do not lose the top 3 focus set.",
            "Do not rank UnitPrice alone.",
        ],
    },
    {
        "family_id": "F6",
        "canonical_intent": "Segment CustomerID with RFM using Recency, Frequency, and Monetary.",
        "required_fields": ["CustomerID", "InvoiceNo", "InvoiceDate", "Quantity", "UnitPrice"],
        "metric": "R/F/M components",
        "dimension": "CustomerID",
        "operation": "RFM segmentation",
        "context_needed": "Missing CustomerID is a caveat, not a total blocker.",
        "query_variants": [
            "哪些客户在最近 6 个月内出现高频低额或低频高额异常行为？请用 RFM 分成至少 4 类，并解释每类运营策略。",
            "最近半年做一个 RFM 客户分群",
            "用 RFM 给客户分层，并给运营建议",
            "找出高频低消费和低频高消费客户",
            "RFM segmentation for the last 6 months",
            "按 Recency Frequency Monetary 给客户打标签",
            "最近 6 个月客户价值分层",
            "高频低额客户有哪些？低频高额客户有哪些？",
            "帮我做客户 RFM，至少分四类",
            "customer segmentation using RFM",
        ],
        "forbidden_behavior": [
            "Do not dump raw transaction rows.",
            "Do not block all analysis because some CustomerID values are missing.",
            "Do not omit R/F/M component evidence or strategy text.",
        ],
    },
    {
        "family_id": "F7",
        "canonical_intent": "Diagnose data quality issues in Online Retail.",
        "required_fields": ["InvoiceNo", "Quantity", "InvoiceDate", "UnitPrice", "CustomerID"],
        "metric": "quality evidence",
        "dimension": "field/rule level",
        "operation": "data_quality",
        "context_needed": "Quality caveats must not block valid aggregation questions.",
        "query_variants": [
            "这个数据有什么质量问题？",
            "检查缺失值、重复和异常值",
            "Quantity 负数是什么情况？",
            "CustomerID 缺失会影响什么？",
            "data quality check",
            "找出可能的数据清洗问题",
            "有退款或负数订单吗？",
            "UnitPrice 有没有异常？",
            "哪些字段缺失最严重？",
            "做一次数据质量诊断",
        ],
        "forbidden_behavior": [
            "Do not say the data is fully clean when negative Quantity or missing CustomerID exists.",
            "Do not hide field-level evidence.",
            "Do not treat quality caveats as a blocker for all analysis.",
        ],
    },
]

AUTOMATED_QUERY_VARIANTS: dict[str, list[str]] = {
    "F1": [
        "哪些国家的销量最高？",
        "country 维度下 quantity top",
        "Top countries by quantity",
        "Rank countries by total quantity",
        "按国家汇总件数，看看前几名",
    ],
    "F2": [
        "各国家销量占比是多少？",
        "Quantity by country share",
        "国家维度的 Quantity 贡献",
    ],
    "F3": [
        "哪个国家销售额最高？",
        "按 Country 看销售额排名",
        "Top countries by revenue",
        "用 Quantity 乘 UnitPrice 算销售额，按国家排名",
        "哪些国家贡献的金额最多？",
        "国家收入排行榜",
        "sales by country",
        "revenue ranking by country",
        "按国家汇总订单金额",
        "Country 维度销售额 TopN",
    ],
    "F4": [
        "按月看 Quantity 趋势",
        "Quantity 的月度变化",
        "每个月销量是多少？",
        "monthly quantity trend",
        "按 InvoiceDate 汇总到月份看走势",
        "销售额月度趋势",
        "revenue by month",
        "过去一年每月销售额变化",
        "月度销量曲线",
        "按月份统计销售额",
    ],
    "F5": [
        "Top 3 countries by revenue, monthly trend",
        "销售额最高的三个国家，按月展开",
        "先找销售额前三国家，再画月度趋势",
    ],
    "F6": [
        "最近半年做一个 RFM 客户分群",
        "RFM segmentation for the last 6 months",
        "帮我做客户 RFM，至少分四类",
    ],
    "F7": [
        "这个数据有什么质量问题？",
        "CustomerID 缺失会影响什么？",
        "data quality check",
    ],
}


@pytest.fixture()
def retail_service_context() -> tuple[DataAgentService, str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        csv_path = root / "online_retail.csv"
        csv_path.write_text(_retail_fixture_csv(), encoding="utf-8")
        service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
        upload = service.upload_dataset(csv_path, original_filename="online_retail.csv")
        yield service, str(upload["dataset_id"])


@pytest.mark.parametrize("question", AUTOMATED_QUERY_VARIANTS["F1"])
def test_f1_country_quantity_topn_paraphrases_share_semantic_contract(
    retail_service_context: tuple[DataAgentService, str],
    question: str,
) -> None:
    service, dataset_id = retail_service_context

    response = service.respond_to_message(dataset_id=dataset_id, question=question, execution_mode="dual")

    _assert_country_quantity_topn_contract(response)


@pytest.mark.parametrize("question", AUTOMATED_QUERY_VARIANTS["F3"])
def test_f3_retail_revenue_by_country_paraphrases_use_derived_sales_contract(
    retail_service_context: tuple[DataAgentService, str],
    question: str,
) -> None:
    service, dataset_id = retail_service_context

    response = service.respond_to_message(dataset_id=dataset_id, question=question, execution_mode="dual")

    _assert_sales_by_country_contract(response)


@pytest.mark.parametrize("question", AUTOMATED_QUERY_VARIANTS["F4"])
def test_f4_retail_monthly_trend_paraphrases_use_invoice_month_bucket(
    retail_service_context: tuple[DataAgentService, str],
    question: str,
) -> None:
    service, dataset_id = retail_service_context

    response = service.respond_to_message(dataset_id=dataset_id, question=question, execution_mode="dual")

    _assert_monthly_trend_contract(response, question)


@pytest.mark.parametrize(
    ("family_id", "question"),
    [
        (family_id, question)
        for family_id, questions in AUTOMATED_QUERY_VARIANTS.items()
        if family_id != SELECTED_FAMILY_ID
        for question in questions
    ],
)
@pytest.mark.xfail(reason="Product Floor baseline manifest records non-selected family gaps for later stages.", strict=False)
def test_non_selected_retail_product_floor_families_are_in_baseline_manifest(
    retail_service_context: tuple[DataAgentService, str],
    family_id: str,
    question: str,
) -> None:
    service, dataset_id = retail_service_context

    response = service.respond_to_message(dataset_id=dataset_id, question=question, execution_mode="dual")

    if family_id == "F3":
        _assert_sales_by_country_contract(response)
    elif family_id == "F6":
        _assert_rfm_contract(response)
    else:
        assert response.get("success") is True
        assert response.get("answer_type") not in {"clarification", "chat"}


def test_retail_product_floor_manifest_covers_required_families_and_variants() -> None:
    required = {"F1", "F2", "F3", "F4", "F5", "F6", "F7"}
    family_ids = {str(family["family_id"]) for family in RETAIL_INTENT_FAMILIES}

    assert required <= family_ids
    for family in RETAIL_INTENT_FAMILIES:
        assert family["canonical_intent"]
        assert len(family["query_variants"]) >= 8
        assert family["required_fields"]
        assert family["metric"]
        assert family["dimension"]
        assert family["operation"]
        assert family["context_needed"]
        assert family["forbidden_behavior"]
        assert len(AUTOMATED_QUERY_VARIANTS[str(family["family_id"])]) >= 3


def _assert_country_quantity_topn_contract(response: dict[str, Any]) -> None:
    logic = response.get("logic_form") or {}
    params = logic.get("parameters") or {}
    task_contract = (response.get("verification") or {}).get("task_contract") or logic.get("task_contract") or {}
    result = response.get("result") or {}
    columns = [str(column) for column in result.get("columns") or []]
    answer_blob = str(response.get("answer") or "")

    assert response.get("success") is True, response.get("errors")
    assert response.get("contract_family") == "topn"
    assert response.get("semantic_status") == "passed"
    assert logic.get("operation") in {"ranking", "filtered_metric_ranking"}
    assert params.get("dimension") == "Country"
    assert task_contract.get("dimension") == "Country"
    assert params.get("metric") == "Quantity"
    assert task_contract.get("metric") == "Quantity"
    assert params.get("table") == "online_retail"
    assert params.get("source_tables") == ["online_retail"]
    assert columns == ["Country", "Quantity"]
    assert result.get("rows")
    assert "InvoiceDate" not in columns
    assert "InvoiceDate" not in answer_blob
    assert "缺少" not in answer_blob
    assert "missing" not in answer_blob.lower()


def _assert_sales_by_country_contract(response: dict[str, Any]) -> None:
    logic = response.get("logic_form") or {}
    params = logic.get("parameters") or {}
    task_contract = (response.get("verification") or {}).get("task_contract") or logic.get("task_contract") or {}
    result = response.get("result") or {}
    columns = [str(column) for column in result.get("columns") or []]
    serialized = str(response)

    assert response.get("success") is True, response.get("errors")
    answer_blob = str(response.get("answer") or "")
    formula = (
        task_contract.get("metric_formula")
        or params.get("metric_formula")
        or (params.get("derived_metric") or {}).get("formula")
        or ""
    )

    assert response.get("success") is True, response.get("errors")
    assert response.get("semantic_status") == "passed"
    assert logic.get("operation") in {"ranking", "filtered_metric_ranking", "aggregation"}
    assert params.get("dimension") == "Country"
    assert task_contract.get("dimension") == "Country"
    assert "Country" in columns
    assert params.get("metric") in {"Sales", "sales", "Revenue", "revenue"}
    assert task_contract.get("metric") in {"Sales", "sales", "Revenue", "revenue"}
    assert params.get("metric") not in {"UnitPrice", "Quantity"}
    assert columns == ["Country", params.get("metric")]
    assert "Quantity" in formula and "UnitPrice" in formula and "*" in formula
    assert task_contract.get("metric_formula") == "Quantity * UnitPrice"
    assert params.get("table") == "online_retail"
    assert params.get("source_tables") == ["online_retail"]
    assert result.get("rows")
    assert {"InvoiceNo", "StockCode", "Description", "InvoiceDate", "CustomerID"}.isdisjoint(columns)
    assert "UnitPrice最高" not in answer_blob
    assert "Quantity最高" not in answer_blob
    assert "缺少" not in answer_blob
    assert "missing" not in answer_blob.lower()
    assert "Quantity" in serialized and "UnitPrice" in serialized


def _assert_monthly_trend_contract(response: dict[str, Any], question: str) -> None:
    logic = response.get("logic_form") or {}
    params = logic.get("parameters") or {}
    task_contract = (response.get("verification") or {}).get("task_contract") or logic.get("task_contract") or {}
    result = response.get("result") or {}
    columns = [str(column) for column in result.get("columns") or []]
    rows = result.get("rows") or []
    answer_blob = str(response.get("answer") or "")
    serialized = str(response)
    sales_question = _f4_query_requests_sales(question)
    expected_metric = "Sales" if sales_question else "Quantity"
    formula = (
        task_contract.get("metric_formula")
        or params.get("metric_formula")
        or (params.get("derived_metric") or {}).get("formula")
        or ""
    )

    assert response.get("success") is True, response.get("errors")
    assert response.get("semantic_status") == "passed"
    assert logic.get("operation") in {"trend", "time_series", "aggregation"}
    if logic.get("operation") == "aggregation":
        assert params.get("capability_family") == "time_series"
        assert task_contract.get("task_family") == "trend"
    assert params.get("time_column") == "InvoiceDate"
    assert params.get("time_bucket") == "month"
    assert params.get("dimension") == "month"
    assert task_contract.get("time_dimension") == "month"
    assert columns == ["month", expected_metric]
    assert rows
    assert all("InvoiceDate" not in row for row in rows if isinstance(row, dict))
    assert all(str(row.get("month") or "").count("-") == 1 for row in rows if isinstance(row, dict))
    assert params.get("metric") == expected_metric
    if sales_question:
        assert "Quantity" in formula and "UnitPrice" in formula and "*" in formula
        assert task_contract.get("metric_formula") == "Quantity * UnitPrice"
        assert "Quantity" in serialized and "UnitPrice" in serialized
    assert "InvoiceDate" not in columns
    assert "缺少" not in answer_blob
    assert "missing" not in answer_blob.lower()
    assert any(token in answer_blob.lower() for token in ("趋势", "变化", "trend"))


def _f4_query_requests_sales(question: str) -> bool:
    lowered = question.lower()
    return any(token in question for token in ("销售额", "金额", "收入")) or any(token in lowered for token in ("revenue", "sales"))


def _assert_rfm_contract(response: dict[str, Any]) -> None:
    result = response.get("result") or {}
    columns = {str(column).lower() for column in result.get("columns") or []}
    answer = str(response.get("answer") or "").lower()

    assert response.get("success") is True, response.get("errors")
    assert "customerid" in "".join(columns)
    assert {"recency", "frequency", "monetary"} <= columns
    assert len(result.get("rows") or []) >= 4
    assert "strategy" in answer or "运营" in answer
    assert "customerid 缺失" in answer or "missing customerid" in answer


def _retail_fixture_csv() -> str:
    return """InvoiceNo,StockCode,Description,Quantity,InvoiceDate,UnitPrice,CustomerID,Country
536365,85123A,WHITE HEART,6,2025-01-05,2.50,17850,United Kingdom
536366,22633,HAND WARMER,10,2025-01-10,1.80,13047,France
536367,22632,HAND WARMER RED,5,2025-02-11,2.00,13047,France
536368,84879,ASSORTED COLOUR,12,2025-02-15,1.20,12583,Germany
536369,22745,PLAYHOUSE,8,2025-03-20,3.00,17850,United Kingdom
536370,22748,KITCHEN,7,2025-03-22,4.00,14911,EIRE
536371,84969,TEASPOONS,9,2025-04-01,2.50,14911,EIRE
536372,22623,JIGSAW,4,2025-04-10,5.00,,United Kingdom
536373,22624,JIGSAW BLUE,-2,2025-04-12,5.00,17850,United Kingdom
536374,22625,JIGSAW RED,3,2025-05-01,0.00,13047,France
"""
