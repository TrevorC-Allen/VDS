from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.llm.client import MockLLMClient
from scripts.run_multi_dataset_real_user_gate import (
    collect_recommended_questions,
    infer_recommendation_expected,
    summarize_recommendations,
)
from scripts.run_uk_retail_random_user_gate import score_response


@pytest.fixture()
def retail_like_service() -> tuple[DataAgentService, str]:
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


def _assert_recommendation_passes(
    service: DataAgentService,
    dataset_id: str,
    *,
    conversation_id: str,
    question: str,
) -> dict[str, Any]:
    response = _ask(service, dataset_id, question, conversation_id=conversation_id)
    score = score_response(
        question=question,
        response=response,
        http_status=200,
        expected=infer_recommendation_expected(question),
    )

    assert response.get("success") is True, response.get("answer")
    assert response.get("semantic_status") == "passed", response.get("answer")
    assert score.score == "pass", score.hard_reasons + score.soft_reasons
    return response


def test_topn_recommendations_are_executable_in_same_conversation(
    retail_like_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = retail_like_service
    first = _ask(
        service,
        dataset_id,
        "销售额最高的前5个商品是什么？销售额按 Quantity * UnitPrice 算。",
        conversation_id="conv_recommendation_topn",
    )
    questions = collect_recommended_questions(first)

    assert first.get("success") is True, first.get("answer")
    assert first.get("semantic_status") == "passed"
    assert questions[:3] == [
        "第一名和第二名差多少？",
        "这些 Top 商品按月份趋势怎么看？",
        "这些 Top 商品主要卖给哪些国家？分别列出主要国家和销售额",
    ]

    conversation_id = str(first.get("conversation_id") or "conv_recommendation_topn")
    for question in questions[:3]:
        _assert_recommendation_passes(service, dataset_id, conversation_id=conversation_id, question=question)


def test_country_ranking_recommendations_cover_share_trend_and_gap(
    retail_like_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = retail_like_service
    first = _ask(
        service,
        dataset_id,
        "销售额最高的前3个国家是什么？销售额按 Quantity * UnitPrice 算。",
        conversation_id="conv_recommendation_country",
    )
    questions = collect_recommended_questions(first)

    assert first.get("success") is True, first.get("answer")
    assert first.get("semantic_status") == "passed"
    assert questions[:3] == [
        "这些国家分别占总销售额的比例是多少？",
        "按这些国家看月份销售趋势",
        "第一名和第二名差多少？",
    ]

    conversation_id = str(first.get("conversation_id") or "conv_recommendation_country")
    for question in questions[:3]:
        _assert_recommendation_passes(service, dataset_id, conversation_id=conversation_id, question=question)


def test_return_quantity_recommendations_do_not_switch_to_sales_formula(
    retail_like_service: tuple[DataAgentService, str],
) -> None:
    service, dataset_id = retail_like_service
    first = _ask(
        service,
        dataset_id,
        "退货数量最多的前5个商品是什么？",
        conversation_id="conv_recommendation_returns",
    )
    questions = collect_recommended_questions(first)

    assert first.get("success") is True, first.get("answer")
    assert first.get("semantic_status") == "passed"
    assert questions[:1] == [
        "第一名和第二名数量差多少？",
    ]
    assert not any("销售额" in question for question in questions)

    conversation_id = str(first.get("conversation_id") or "conv_recommendation_returns")
    for question in questions[:1]:
        _assert_recommendation_passes(service, dataset_id, conversation_id=conversation_id, question=question)


def test_missing_recommendation_is_a_hard_gate_failure() -> None:
    summary = summarize_recommendations(
        [
            {
                "source_question": "销售额最高的前5个商品是什么？",
                "recommended_question": "",
                "score": "hard_fail",
                "hard_reasons": ["missing_recommended_question"],
                "soft_reasons": [],
                "failure_layer": "recommendation_generation",
            }
        ]
    )

    assert summary["passed"] is False
    assert summary["hard_fail"] == 1
    assert summary["answerability_rate"] == 0.0
    assert summary["failed_questions"][0]["failure_layer"] == "recommendation_generation"
