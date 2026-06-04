from __future__ import annotations

import unittest

import pandas as pd

from data_agent_core.contracts.analysis_contracts import LogicForm, UserQuestion
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.conversation_actions import build_analysis_context, plan_followup_actions
from data_agent_core.executors.pandas_executor import execute_plan
from data_agent_core.output.response_builder import build_response
from data_agent_core.result_artifacts import resolve_followup_referent
from data_agent_core.task_contract_builder import apply_referent_contract
from data_agent_core.verifier.rule_checker import verify_execution


class GapFollowupAutoExpandTopNTest(unittest.TestCase):
    def test_top1_gap_followup_auto_expands_to_top3(self) -> None:
        context = _ranking_context([{"city": "上海", "amount": 325}], limit=1)
        question = "比较 Top 城市之间的差距。"

        resolved = resolve_followup_referent(question, context)
        self.assertTrue(resolved["resolved"])
        self.assertEqual(["上海"], resolved["referent_values"])

        actions = plan_followup_actions(question, context)
        self.assertEqual(1, len(actions))
        contract = actions[0]["referent_contract"]
        self.assertTrue(contract["auto_expand_topn_if_needed"])
        self.assertEqual(2, contract["minimum_required_objects"])
        self.assertEqual(3, contract["preferred_top_n"])

        result, verification = _run_gap(actions[0]["question"], contract, {"tables": {"orders": _orders_frame()}, "primary_table": "orders"})

        self.assertTrue(verification.passed, verification.semantic_verification_notes)
        self.assertEqual("passed", verification.semantic_status)
        self.assertEqual(["上海", "北京", "深圳"], [row["city"] for row in result.rows])
        artifacts = _gap_artifacts(verification, result)
        self.assertEqual([15.0, 22.0], artifacts["adjacent_gaps"])
        self.assertEqual([0.0, 15.0, 37.0], artifacts["gap_to_leader"])
        issue_codes = set((verification.oracle_result or {}).get("issue_codes") or [])
        self.assertNotIn("insufficient_objects_for_gap", issue_codes)

    def test_multi_file_gap_followup_auto_expand_preserves_join_plan(self) -> None:
        join_plan = {
            "trusted": True,
            "left_table": "orders",
            "right_table": "customers",
            "left_key": "customer_id",
            "right_key": "customer_id",
            "relationship": "many_to_one",
        }
        context = _ranking_context(
            [{"city": "上海", "amount": 325}],
            limit=1,
            join_plan=join_plan,
            source_tables=["orders", "customers"],
        )
        actions = plan_followup_actions("比较 Top 城市之间的差距。", context)
        contract = actions[0]["referent_contract"]

        self.assertEqual(["orders", "customers"], contract["inherited_parameters"]["source_tables"])
        self.assertEqual("customer_id", contract["inherited_parameters"]["join_plan"]["left_key"])

        result, verification = _run_gap(
            actions[0]["question"],
            contract,
            {"tables": {"orders": _orders_join_frame(), "customers": _customers_frame()}, "primary_table": "orders"},
        )

        self.assertTrue(verification.passed, verification.semantic_verification_notes)
        self.assertEqual(["上海", "北京", "深圳"], [row["city"] for row in result.rows])
        artifacts = _gap_artifacts(verification, result)
        self.assertEqual([15.0, 22.0], artifacts["adjacent_gaps"])

    def test_gap_after_trend_followup_still_expands_from_previous_ranking_artifact(self) -> None:
        join_plan = {
            "trusted": True,
            "left_table": "orders",
            "right_table": "customers",
            "left_key": "customer_id",
            "right_key": "customer_id",
            "relationship": "many_to_one",
        }
        ranking_context = _ranking_context(
            [{"city": "上海", "amount": 325}],
            limit=1,
            join_plan=join_plan,
            source_tables=["orders", "customers"],
        )
        trend_context = build_analysis_context(
            {
                "success": True,
                "run_id": "run_trend_after_top1",
                "dataset_id": "ds",
                "question": "按月份看这个指标的趋势。",
                "logic_form": {
                    "task_type": "aggregation",
                    "operation": "aggregation",
                    "metric": "amount",
                    "group_by": "month",
                    "filters": {"city": ["上海"]},
                    "parameters": {
                        "table": "orders",
                        "metric": "amount",
                        "dimension": "month",
                        "aggregation": "sum",
                        "join_plan": join_plan,
                        "source_tables": ["orders", "customers"],
                        "requires_previous_artifact": True,
                        "referent_artifact_id": ranking_context["last_ranking_artifact_id"],
                        "referent_dimension": "city",
                        "referent_values": ["上海"],
                    },
                },
                "result": {"columns": ["month", "amount"], "rows": [{"month": "2026-01", "amount": 120}, {"month": "2026-02", "amount": 205}]},
            },
            previous_context=ranking_context,
            original_question="按月份看这个指标的趋势。",
        )

        actions = plan_followup_actions("比较 Top 城市之间的差距。", trend_context)
        self.assertEqual(1, len(actions))
        self.assertTrue(actions[0]["referent_contract"]["auto_expand_topn_if_needed"])

        result, verification = _run_gap(
            actions[0]["question"],
            actions[0]["referent_contract"],
            {"tables": {"orders": _orders_join_frame(), "customers": _customers_frame()}, "primary_table": "orders"},
        )

        self.assertTrue(verification.passed, verification.semantic_verification_notes)
        self.assertEqual(["上海", "北京", "深圳"], [row["city"] for row in result.rows])

    def test_single_distinct_city_returns_valid_insufficient_gap_answer(self) -> None:
        context = _ranking_context([{"city": "上海", "amount": 300}], limit=1)
        actions = plan_followup_actions("比较 Top 城市之间的差距。", context)
        result, verification = _run_gap(
            actions[0]["question"],
            actions[0]["referent_contract"],
            {"tables": {"orders": _single_city_frame()}, "primary_table": "orders"},
        )

        self.assertTrue(verification.passed, verification.semantic_verification_notes)
        self.assertIn(verification.semantic_status, {"passed", "partial", "passed_with_insufficient_data"})
        response = build_response(
            run_id="run_gap_single_city",
            user_question=UserQuestion(dataset_id="ds", question=actions[0]["question"]),
            plan=build_analysis_plan(_logic_for_contract(actions[0]["referent_contract"]), question=actions[0]["question"]),
            execution_result=result,
            verification=verification,
        ).to_dict()
        answer = str(response["answer"] or "")
        self.assertIn("只有 1 个可比较城市", answer)
        self.assertIn("无法计算城市之间的差距", answer)
        issue_codes = set((verification.oracle_result or {}).get("issue_codes") or [])
        self.assertNotIn("insufficient_objects_for_gap", issue_codes)

    def test_existing_top3_gap_followup_uses_referent_without_auto_expand(self) -> None:
        context = _ranking_context(
            [
                {"city": "上海", "amount": 325},
                {"city": "北京", "amount": 310},
                {"city": "深圳", "amount": 288},
            ]
        )
        actions = plan_followup_actions("比较 Top 城市之间的差距。", context)
        contract = actions[0]["referent_contract"]

        self.assertFalse(contract.get("auto_expand_topn_if_needed", False))
        result, verification = _run_gap(actions[0]["question"], contract, {"tables": {"orders": _orders_frame()}, "primary_table": "orders"})

        self.assertTrue(verification.passed, verification.semantic_verification_notes)
        self.assertEqual(["上海", "北京", "深圳"], [row["city"] for row in result.rows])
        self.assertEqual(["上海", "北京", "深圳"], verification.task_contract["referent_values"])


def _ranking_context(
    rows: list[dict[str, object]],
    *,
    limit: int = 3,
    join_plan: dict[str, object] | None = None,
    source_tables: list[str] | None = None,
) -> dict[str, object]:
    return build_analysis_context(
        {
            "success": True,
            "run_id": "run_previous_top",
            "dataset_id": "ds",
            "question": "按城市汇总金额，Top 3 是哪些？",
            "logic_form": {
                "task_type": "ranking",
                "operation": "ranking",
                "metric": "amount",
                "group_by": "city",
                "filters": {},
                "parameters": {
                    "table": "orders",
                    "metric": "amount",
                    "dimension": "city",
                    "aggregation": "sum",
                    "sort_order": "desc",
                    "limit": limit,
                    **({"join_plan": join_plan} if join_plan else {}),
                    **({"source_tables": source_tables} if source_tables else {}),
                },
                **({"source_tables": source_tables} if source_tables else {}),
                **({"join_plan": join_plan} if join_plan else {}),
            },
            "result": {"columns": ["city", "amount"], "rows": rows},
        },
        original_question="按城市汇总金额，Top 3 是哪些？",
    )


def _run_gap(question: str, contract: dict[str, object], context: dict[str, object]):
    logic = _logic_for_contract(contract)
    plan = build_analysis_plan(logic, question=question)
    result = execute_plan(plan, context)
    verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))
    return result, verification


def _logic_for_contract(contract: dict[str, object]) -> LogicForm:
    logic = LogicForm(
        task_type="ranking",
        operation="ranking",
        metric="amount",
        group_by="city",
        filters={},
        parameters={"table": "orders", "metric": "amount", "dimension": "city", "aggregation": "sum", "sort_order": "desc", "limit": 3},
        output_format={"answer_type": "table"},
    )
    apply_referent_contract(logic, contract)
    return logic


def _gap_artifacts(verification: object, result: object) -> dict[str, object]:
    from data_agent_core.result_artifacts import build_task_artifacts

    return build_task_artifacts(task_contract=verification.task_contract or {}, rows=result.rows, answer="")


def _orders_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"city": "上海", "amount": 325},
            {"city": "北京", "amount": 310},
            {"city": "深圳", "amount": 288},
        ]
    )


def _orders_join_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"customer_id": 1, "amount": 120, "month": "2026-01"},
            {"customer_id": 2, "amount": 205, "month": "2026-02"},
            {"customer_id": 3, "amount": 310, "month": "2026-01"},
            {"customer_id": 4, "amount": 288, "month": "2026-01"},
        ]
    )


def _customers_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"customer_id": 1, "city": "上海"},
            {"customer_id": 2, "city": "上海"},
            {"customer_id": 3, "city": "北京"},
            {"customer_id": 4, "city": "深圳"},
        ]
    )


def _single_city_frame() -> pd.DataFrame:
    return pd.DataFrame([{"city": "上海", "amount": 100}, {"city": "上海", "amount": 200}])


if __name__ == "__main__":
    unittest.main()
