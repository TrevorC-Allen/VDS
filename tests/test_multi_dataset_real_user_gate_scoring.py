from __future__ import annotations

from pathlib import Path

from scripts.run_multi_dataset_real_user_gate import (
    build_dataset_manifest,
    collect_recommended_questions,
    infer_recommendation_expected,
    summarize_recommendations,
)


def test_build_dataset_manifest_detects_keys_time_measures_and_dimensions(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "\n".join(
            [
                "order_id,customer_id,order_date,revenue,country,status",
                "O1,C1,2024-01-01,10.5,US,paid",
                "O2,C2,2024-01-02,20.0,CA,paid",
                "O3,C1,2024-02-01,15.0,US,refund",
            ]
        ),
        encoding="utf-8",
    )

    manifest = build_dataset_manifest(csv_path, dataset_name="synthetic_orders")
    table = "orders"

    assert manifest["dataset_name"] == "synthetic_orders"
    assert manifest["dataset_type"] == "single_file"
    assert manifest["files"] == [str(csv_path)]
    assert manifest["row_counts"][table] == 3
    assert manifest["columns"][table] == ["order_id", "customer_id", "order_date", "revenue", "country", "status"]
    assert {"order_id", "customer_id"} <= set(manifest["detected_keys"][table])
    assert manifest["detected_time_columns"][table] == ["order_date"]
    assert "revenue" in manifest["detected_measures"][table]
    assert {"country", "status"} <= set(manifest["detected_dimensions"][table])


def test_collect_recommended_questions_dedupes_filters_and_limits_to_three() -> None:
    response = {
        "insight": {
            "next_questions": [
                "1. 第一名和第二名差多少？",
                "告诉我应该使用哪个字段作为指标",
                "第一名和第二名差多少？",
            ],
            "follow_up_questions": ["按月份看整体销售额趋势。", "Country 销售额占比是多少？"],
        },
        "structured_answer_sections": {
            "next_questions": ["检查缺失、重复和异常值对分析的影响"],
        },
        "debug": {"recommended_questions": ["按客户拆分销售额。"]},
    }

    assert collect_recommended_questions(response) == [
        "第一名和第二名差多少？",
        "按月份看整体销售额趋势",
        "Country 销售额占比是多少？",
    ]


def test_infer_recommendation_expected_maps_common_followup_families() -> None:
    gap = infer_recommendation_expected("第一名和第二名差多少？")
    quantity_gap = infer_recommendation_expected("第一名和第二名数量差多少？")
    trend = infer_recommendation_expected("这些 Top 商品按月份趋势怎么看？")
    share = infer_recommendation_expected("这些国家分别占总销售额的比例是多少？")
    drilldown = infer_recommendation_expected("这些 Top 商品主要卖给哪些国家？分别列出主要国家和销售额。")

    assert gap.category == "follow-up gap"
    assert gap.require_formula is True
    assert quantity_gap.category == "follow-up gap"
    assert quantity_gap.require_formula is False
    assert trend.category == "time trend"
    assert trend.require_month_bucket is True
    assert share.category == "country share"
    assert share.require_share is True
    assert drilldown.category == "follow-up drilldown"
    assert "Country" in drilldown.allowed_dimensions


def test_recommendation_summary_requires_every_record_to_pass() -> None:
    summary = summarize_recommendations(
        [
            {"score": "pass", "hard_reasons": [], "soft_reasons": []},
            {
                "source_question": "source",
                "recommended_question": "bad followup",
                "score": "soft_fail",
                "hard_reasons": [],
                "soft_reasons": ["safe_failure_no_clear_status"],
                "failure_layer": "answerability",
            },
        ]
    )

    assert summary["passed"] is False
    assert summary["total"] == 2
    assert summary["pass"] == 1
    assert summary["soft_fail"] == 1
    assert summary["answerability_rate"] == 0.5
    assert summary["failed_questions"][0]["recommended_question"] == "bad followup"
