"""Guardrails that keep answerable dataset questions out of Not Applicable."""

from __future__ import annotations

import unittest

import pandas as pd

from agent_runtime.data_analysis_roles import _validated_logic_form as validate_multi_agent_logic_form
from data_agent_core.agent.single_agent import UploadedDatasetAgent
from data_agent_core.contracts.analysis_contracts import LogicForm, UserQuestion
from data_agent_core.contracts.verification_contracts import VerificationResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.intent_parser import parse_generic_table_question
from data_agent_core.executors import pandas_executor
from data_agent_core.llm.client import MockLLMClient
from data_agent_core.output.response_builder import build_response, classify_not_applicable


class NotApplicableGuardrailsTest(unittest.TestCase):
    def test_single_agent_rescues_supported_llm_plan_from_low_information_guardrail(self) -> None:
        table = pd.DataFrame({"amount": [10.0, 20.0], "region": ["East", "West"]})
        agent = UploadedDatasetAgent({"payments": table}, "dataset_test", llm_client=MockLLMClient())
        guardrail = LogicForm(
            task_type="unsupported",
            operation="not_applicable",
            parameters={"reason": "No supported general analysis pattern matched."},
            output_format={"answer_type": "text"},
        )
        llm = LogicForm(
            task_type="aggregation",
            operation="aggregation",
            parameters={"table": "payments", "metric": "amount", "aggregation": "sum"},
            output_format={"answer_type": "number"},
        )

        selected = agent._validated_logic_form(llm, guardrail)

        self.assertEqual("aggregation", selected.operation)
        self.assertEqual("amount", selected.parameters["metric"])

    def test_multi_agent_rescues_supported_llm_plan_from_detail_lookup_guardrail(self) -> None:
        table = pd.DataFrame({"amount": [10.0, 20.0], "region": ["East", "West"]})
        guardrail = LogicForm(
            task_type="detail_lookup",
            operation="detail_lookup",
            parameters={"table": "payments", "limit": 20},
            output_format={"answer_type": "table"},
        )
        llm = LogicForm(
            task_type="aggregation",
            operation="row_count",
            parameters={"table": "payments"},
            output_format={"answer_type": "number"},
        )

        selected = validate_multi_agent_logic_form(llm, guardrail, {"tables": {"payments": table}})

        self.assertEqual("row_count", selected.operation)

    def test_llm_fallback_rejects_unknown_columns_and_benchmark_leaks(self) -> None:
        table = pd.DataFrame({"amount": [10.0], "region": ["East"]})
        agent = UploadedDatasetAgent({"payments": table}, "dataset_test", llm_client=MockLLMClient())
        guardrail = LogicForm(task_type="detail_lookup", operation="detail_lookup", parameters={"table": "payments"})
        unknown_column = LogicForm(
            task_type="aggregation",
            operation="aggregation",
            parameters={"table": "payments", "metric": "missing_amount", "aggregation": "sum"},
        )
        leaked = LogicForm(
            task_type="aggregation",
            operation="aggregation",
            parameters={"table": "payments", "metric": "amount", "task_id": "123"},
        )

        self.assertEqual("detail_lookup", agent._validated_logic_form(unknown_column, guardrail).operation)
        self.assertEqual("detail_lookup", agent._validated_logic_form(leaked, guardrail).operation)

    def test_classify_not_applicable_catches_structured_answer_variants(self) -> None:
        logic = LogicForm(task_type="ranking", operation="ranking", parameters={"table": "payments"})
        attribution = classify_not_applicable({"answer": "N/A", "candidate_table": []}, build_analysis_plan(logic))

        self.assertEqual("capability_gap", attribution["category"])

    def test_empty_results_are_scoreable_not_not_applicable(self) -> None:
        table = pd.DataFrame({"region": ["East"], "merchant": ["A"], "amount": [10.0]})
        logic = LogicForm(
            task_type="ranking",
            operation="top_count",
            filters={"region": "West"},
            parameters={"table": "payments", "group_by": "merchant"},
            output_format={"answer_type": "text"},
        )
        plan = build_analysis_plan(logic)
        result = pandas_executor.execute_plan(plan, {"tables": {"payments": table}})
        response = build_response(
            run_id="run_empty",
            user_question=UserQuestion(dataset_id="dataset_test", question="West top merchant"),
            plan=plan,
            execution_result=result,
            verification=VerificationResult(passed=True),
        )

        self.assertEqual("没有匹配记录", response.answer)
        self.assertNotIn("not_applicable_attribution", response.debug)

    def test_generic_parser_keeps_broad_answerable_questions_executable(self) -> None:
        table = pd.DataFrame({"amount": [10.0, None], "region": ["East", "West"]})
        logic = parse_generic_table_question("帮我看看哪里有问题。", {"payments": table})

        self.assertNotEqual("not_applicable", logic.operation)


if __name__ == "__main__":
    unittest.main()
