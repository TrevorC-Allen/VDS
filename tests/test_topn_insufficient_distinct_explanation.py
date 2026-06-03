from __future__ import annotations

import unittest

from data_agent_core.analysis_contracts import LogicForm
from data_agent_core.contracts.analysis_contracts import UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.output.response_builder import build_response
from data_agent_core.rule_checker import verify_execution


class TopnInsufficientDistinctExplanationTest(unittest.TestCase):
    def test_topn_with_distinct_objects_fewer_than_requested_shows_clear_explanation(self) -> None:
        question = "按城市看销售额排名前 5。"
        plan = build_analysis_plan(_ranking_logic(), question=question)
        rows = [
            {"城市": "深圳", "销售额": 749},
            {"城市": "上海", "销售额": 563},
            {"城市": "北京", "销售额": 276},
            {"城市": "广州", "销售额": 206},
        ]
        result = ExecutionResult(backend="pandas", success=True, columns=["城市", "销售额"], rows=rows, value=rows)

        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))
        response = build_response(
            run_id="run_topn_insufficient_explanation",
            user_question=UserQuestion(dataset_id="ds", question=question),
            plan=plan,
            execution_result=result,
            verification=verification,
        ).to_dict()

        self.assertEqual("topn", response["contract_family"])
        self.assertEqual(5, response["verification"]["task_contract"]["required_n"])
        self.assertEqual(4, response["debug"]["result_artifacts"]["distinct_count"])
        self.assertEqual(4, len(response["result"]["rows"]))
        self.assertIn("只有 4 个", response["answer"])
        self.assertIn("城市", response["answer"])
        self.assertTrue("无法返回 Top 5" in response["answer"] or "只能展示 Top 4" in response["answer"])
        self.assertIn(response["semantic_status"], {"partial", "passed_with_insufficient_data"})
        self.assertNotEqual("failed", response["semantic_status"])


def _ranking_logic() -> LogicForm:
    return LogicForm(
        task_type="ranking",
        operation="ranking",
        metric="销售额",
        group_by="城市",
        parameters={
            "metric": "销售额",
            "dimension": "城市",
            "aggregation": "sum",
            "sort_order": "desc",
            "limit": 5,
        },
        output_format={"answer_type": "table"},
    )


if __name__ == "__main__":
    unittest.main()
