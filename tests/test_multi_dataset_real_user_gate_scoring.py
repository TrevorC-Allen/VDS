from __future__ import annotations

from pathlib import Path

from data_agent_core.contracts.analysis_contracts import AnalysisPlan, LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.contracts.verification_contracts import VerificationResult
from data_agent_core.output.response_builder import build_response
from data_agent_core.output.source_overview import build_dataset_source_overview_response
from scripts.run_multi_dataset_real_user_gate import (
    build_dataset_manifest,
    collect_recommended_questions,
    dataset_files,
    dataset_upload_files,
    infer_recommendation_expected,
    random_gate_cases,
    summarize_recommendations,
)
from scripts.run_uk_retail_random_user_gate import ExpectedContract, score_response


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


def test_dabstep_manifest_discovers_context_package_from_dataset_root(tmp_path: Path) -> None:
    context = tmp_path / "data" / "context"
    tasks = tmp_path / "data" / "tasks"
    context.mkdir(parents=True)
    tasks.mkdir(parents=True)
    (context / "payments.csv").write_text(
        "\n".join(
            [
                "psp_reference,merchant,issuing_country,ip_country,eur_amount,has_fraudulent_dispute,aci,acquirer_country,year",
                "P1,M1,NL,BE,10.5,true,A,NL,2023",
                "P2,M2,BE,NL,20.0,false,B,US,2023",
            ]
        ),
        encoding="utf-8",
    )
    (context / "merchant_category_codes.csv").write_text("mcc,description\n5812,Restaurants\n", encoding="utf-8")
    (context / "acquirer_countries.csv").write_text("acquirer,country_code\ngringotts,GB\n", encoding="utf-8")
    (context / "fees.json").write_text("[{\"ID\": 1, \"rate\": 10}]", encoding="utf-8")
    (context / "merchant_data.json").write_text("[{\"merchant\": \"M1\", \"merchant_category_code\": 5812}]", encoding="utf-8")
    (context / "manual.md").write_text("# Manual\nFees are rule context.\n", encoding="utf-8")
    (tasks / "dev.jsonl").write_text('{"task_id":"1","question":"q"}\n', encoding="utf-8")
    (tasks / "all.jsonl").write_text('{"task_id":"2","question":"q"}\n', encoding="utf-8")

    manifest = build_dataset_manifest(tmp_path, dataset_name="dab_bm")
    upload_names = {Path(path).name for path in manifest["upload_files"]}

    assert manifest["dataset_type"] == "dabstep_context"
    assert manifest["context_dir"] == str(context)
    assert upload_names == {
        "payments.csv",
        "merchant_category_codes.csv",
        "acquirer_countries.csv",
        "fees.json",
        "merchant_data.json",
        "manual.md",
    }
    assert {Path(path).name for path in manifest["knowledge_files"]} == {"fees.json", "merchant_data.json", "manual.md"}
    assert {Path(path).name for path in manifest["task_files"]} == {"dev.jsonl", "all.jsonl"}
    assert {path.name for path in dataset_files(tmp_path)} == {
        "payments.csv",
        "merchant_category_codes.csv",
        "acquirer_countries.csv",
    }
    assert {path.name for path in dataset_upload_files(tmp_path)} == upload_names
    assert "payments" in manifest["columns"]
    assert "eur_amount" in manifest["detected_measures"]["payments"]
    assert "DABstep task JSONL files are benchmark questions" in manifest["known_limitations"][0]


def test_source_overview_response_has_semantic_status_for_gate_scoring() -> None:
    response = build_dataset_source_overview_response(
        run_id="run_source_overview",
        dataset_id="ds_source_overview",
        question="这个上传数据包含哪些表？每张表的行数和字段是什么？",
        source_manifest={
            "dataset_kind": "dabstep_context",
            "sources": [
                {
                    "file_name": "payments.csv",
                    "source_type": "table",
                    "read_status": "loaded",
                    "row_count": 2,
                    "columns": ["psp_reference", "merchant", "eur_amount"],
                },
                {
                    "file_name": "manual.md",
                    "source_type": "knowledge",
                    "read_status": "loaded",
                    "summary": "Payment rules manual.",
                },
            ],
        },
        tables={},
    )

    score = score_response(
        question="这个上传数据包含哪些表？每张表的行数和字段是什么？",
        response=response,
        http_status=200,
        expected=ExpectedContract("overview", min_rows=1),
    )

    assert response["semantic_status"] == "passed"
    assert response["semantic_success"] is True
    assert score.score == "pass", score.hard_reasons


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


def test_generic_random_gate_keeps_independent_questions_out_of_shared_context(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "\n".join(
            [
                "order_id,order_date,revenue,country",
                "O1,2024-01-01,10.5,US",
                "O2,2024-01-02,20.0,CA",
            ]
        ),
        encoding="utf-8",
    )
    manifest = build_dataset_manifest(csv_path, dataset_name="synthetic_orders")

    cases = random_gate_cases("synthetic_orders", manifest, seed=7, total_questions=12)

    assert len(cases) == 12
    assert all(case.conversation_key == "" for case in cases)


def test_dabstep_random_gate_keeps_safe_failure_bounded_and_distinct_topn_answerable() -> None:
    manifest = {"dataset_type": "dabstep_context"}
    cases = random_gate_cases("dab_bm", manifest, seed=2026060701, total_questions=80)
    questions = [case.question for case in cases]

    assert len(cases) == 80
    assert sum(1 for case in cases if case.expected.safe_failure_expected) == 1
    assert "按 card_scheme 看交易数量前4。" in questions
    assert "按 card_scheme 看交易数量前5。" not in questions
    assert "按 shopper_interaction 看 eur_amount 总金额排名前2。" in questions


def test_score_response_accepts_dabstep_row_count_as_transaction_count_metric() -> None:
    response = {
        "success": True,
        "semantic_status": "passed",
        "answer": "138236",
        "logic_form": {
            "operation": "row_count",
            "parameters": {"table": "payments"},
        },
        "result": {
            "columns": ["answer"],
            "rows": [{"answer": 138236}],
            "value": 138236,
        },
        "debug": {
            "execution_trace": {"operation": "row_count"},
        },
    }

    score = score_response(
        question="这个 DABstep 数据有多少笔 payment transaction？",
        response=response,
        http_status=200,
        expected=ExpectedContract("dab count", min_rows=1, allowed_metrics=("count", "psp_reference")),
    )

    assert score.score == "pass", score.hard_reasons


def test_response_success_uses_semantic_contract_when_backend_consistency_differs() -> None:
    plan = AnalysisPlan(
        plan_id="plan_trend",
        logic_form=LogicForm(
            task_type="trend",
            operation="aggregation",
            metric="开通天数",
            group_by="month",
            parameters={"metric": "开通天数", "dimension": "month", "time_bucket": "month"},
            output_format={"answer_type": "table"},
        ),
    )
    result = ExecutionResult(
        backend="pandas",
        success=True,
        columns=["month", "开通天数"],
        rows=[{"month": "2025-01", "开通天数": 10}, {"month": "2025-02", "开通天数": 20}],
        value=[{"month": "2025-01", "开通天数": 10}, {"month": "2025-02", "开通天数": 20}],
    )
    verification = VerificationResult(
        passed=False,
        pandas_sql_consistent=False,
        semantic_passed=True,
        issues=["Execution values differ after normalization."],
    )
    verification.semantic_status = "passed"  # type: ignore[attr-defined]
    verification.contract_report = {"task_family": "trend", "passed": True, "violations": [], "warnings": []}  # type: ignore[attr-defined]
    verification.task_contract = {"task_family": "trend", "required_output_columns": ["month", "开通天数"]}  # type: ignore[attr-defined]

    response = build_response(
        run_id="run_trend",
        user_question=UserQuestion(dataset_id="ds", question="按月份看开通天数趋势。", execution_mode="dual"),
        plan=plan,
        execution_result=result,
        verification=verification,
    )

    assert response.success is True
    assert response.semantic_status == "passed"
    assert response.result["columns"] == ["month", "开通天数"]
