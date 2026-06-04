from __future__ import annotations

import unittest

from data_agent_core.contracts.analysis_contracts import LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.task_execution_contracts import build_task_execution_contract
from data_agent_core.verifier.rule_checker import verify_execution


class FirstTurnOverviewFileScopeNotReferentTest(unittest.TestCase):
    def test_customer_revenue_file_structure_overview_is_not_previous_referent(self) -> None:
        question = "不直接下结论，先概览这些客户订单收入文件的数据结构。"
        contract = build_task_execution_contract(
            {
                "task_type": "overview",
                "operation": "multi_table_dataset_overview",
                "source_tables": ["orders", "customers"],
                "parameters": {},
                "output_format": {"answer_type": "overview"},
            },
            question=question,
        )

        self.assertIsNotNone(contract)
        self.assertIn(contract.task_family, {"overview", "multi_file_overview"})
        self.assertFalse(contract.requires_previous_artifact)
        self.assertIsNone(contract.referent_artifact_id)
        self.assertEqual([], contract.referent_values)

        verification = _verify_with_contract(question=question, contract_payload=contract.__dict__)
        self.assertNotIn("REFERENT_ARTIFACT_MISSING", _violation_codes(verification))
        self.assertNotIn("REFERENT_VALUES_MISSING", _violation_codes(verification))
        self.assertNotEqual("needs_clarification", str(verification.semantic_status or ""))

    def test_uploaded_file_analysis_direction_overview_is_not_previous_referent(self) -> None:
        question = "帮我概览这批客户订单收入上传文件能支持哪些分析。"
        contract = build_task_execution_contract(
            {
                "task_type": "overview",
                "operation": "multi_table_dataset_overview",
                "source_tables": ["orders", "customers"],
                "parameters": {},
                "output_format": {"answer_type": "overview"},
            },
            question=question,
        )

        self.assertIsNotNone(contract)
        self.assertIn(contract.task_family, {"overview", "multi_file_overview"})
        self.assertFalse(contract.requires_previous_artifact)
        self.assertIsNone(contract.referent_artifact_id)
        self.assertEqual([], contract.referent_values)

        verification = _verify_with_contract(question=question, contract_payload=contract.__dict__)
        self.assertNotIn("REFERENT_ARTIFACT_MISSING", _violation_codes(verification))
        self.assertNotIn("REFERENT_VALUES_MISSING", _violation_codes(verification))
        self.assertNotEqual("needs_clarification", str(verification.semantic_status or ""))

    def test_first_turn_data_quality_is_not_previous_referent(self) -> None:
        question = "做分析前先看这些数据的质量，重点查缺失、重复和异常值。"
        contract = build_task_execution_contract(
            {
                "task_type": "quality",
                "operation": "data_quality_report",
                "source_tables": ["orders"],
                "parameters": {},
                "output_format": {"answer_type": "data_quality"},
            },
            question=question,
        )

        self.assertIsNotNone(contract)
        self.assertEqual("data_quality", contract.task_family)
        self.assertFalse(contract.requires_previous_artifact)
        self.assertIsNone(contract.referent_artifact_id)
        self.assertEqual([], contract.referent_values)

        verification = _verify_with_contract(question=question, contract_payload=contract.__dict__)
        self.assertNotIn("REFERENT_ARTIFACT_MISSING", _violation_codes(verification))
        self.assertNotIn("REFERENT_VALUES_MISSING", _violation_codes(verification))
        self.assertNotEqual("needs_clarification", str(verification.semantic_status or ""))

    def test_top_object_trend_followup_keeps_previous_referent(self) -> None:
        question = "这些 Top 对象按月份的金额趋势怎么样？"
        contract = build_task_execution_contract(
            {
                "task_type": "analysis",
                "operation": "trend",
                "source_tables": ["orders"],
                "parameters": {
                    "metric": "amount",
                    "time_dimension": "month",
                    "referent_artifact_id": "artifact_top_cities",
                    "referent_dimension": "city",
                    "referent_values": ["上海", "北京"],
                    "requires_previous_artifact": True,
                },
                "filters": {"city": ["上海", "北京"]},
                "output_format": {"answer_type": "trend", "metric": "amount"},
            },
            question=question,
        )

        self.assertIsNotNone(contract)
        self.assertEqual("trend", contract.task_family)
        self.assertTrue(contract.requires_previous_artifact)
        self.assertEqual("artifact_top_cities", contract.referent_artifact_id)
        self.assertEqual(["上海", "北京"], contract.referent_values)


def _verify_with_contract(*, question: str, contract_payload: dict) -> object:
    logic = LogicForm(
        task_type="overview",
        operation=str(contract_payload.get("task_family") or "dataset_overview"),
        metric="amount",
        group_by="city",
        parameters={},
        output_format={"answer_type": str(contract_payload.get("task_family") or "overview")},
    )
    plan = build_analysis_plan(logic, question=question)
    plan.task_contract = contract_payload
    result = ExecutionResult(
        backend="pandas",
        success=True,
        columns=["month", "city", "amount"],
        rows=[{"month": "2026-01", "city": "上海", "amount": 1000}],
        value={"answer": "已生成结构概览。"},
        summary="",
    )
    return verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))


def _violation_codes(verification: object) -> set[str]:
    report = getattr(verification, "contract_report", {}) or {}
    return {str(item.get("code") or "") for item in report.get("violations", [])}


if __name__ == "__main__":
    unittest.main()
