from __future__ import annotations

import unittest

from data_agent_core.contracts.analysis_contracts import LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.output.response_builder import build_response
from data_agent_core.verifier.rule_checker import verify_execution


class TopNGapTrendContractTest(unittest.TestCase):
    def test_topn_insufficient_data_is_explicit_partial_success(self) -> None:
        question = "按城市看销售额排名前 5。"
        plan = build_analysis_plan(_ranking_logic(limit=5), question=question)
        rows = [
            {"城市": "上海", "销售额": 900},
            {"城市": "北京", "销售额": 800},
            {"城市": "深圳", "销售额": 700},
            {"城市": "广州", "销售额": 600},
        ]
        result = ExecutionResult(backend="pandas", success=True, columns=["城市", "销售额"], rows=rows, value=rows)

        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))
        response = build_response(
            run_id="run_topn_short",
            user_question=UserQuestion(dataset_id="ds", question=question),
            plan=plan,
            execution_result=result,
            verification=verification,
        ).to_dict()

        self.assertEqual("topn", response["contract_family"])
        self.assertEqual(5, response["verification"]["task_contract"]["required_n"])
        self.assertEqual(4, len(response["result"]["rows"]))
        self.assertEqual(4, response["debug"]["result_artifacts"]["distinct_count"])
        self.assertIn("数据集中只有 4 个不同城市", response["answer"])
        self.assertIn(response["semantic_status"], {"partial", "passed_with_insufficient_data"})
        self.assertNotEqual("failed", response["semantic_status"])

    def test_topn_three_rows_sorted_desc_passes_and_saves_top_objects(self) -> None:
        question = "城市销售额 Top 3 是哪些？"
        plan = build_analysis_plan(_ranking_logic(limit=3), question=question)
        rows = [
            {"城市": "上海", "销售额": 900},
            {"城市": "北京", "销售额": 800},
            {"城市": "深圳", "销售额": 700},
        ]
        result = ExecutionResult(backend="pandas", success=True, columns=["城市", "销售额"], rows=rows, value=rows)

        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))
        response = build_response(
            run_id="run_topn_3",
            user_question=UserQuestion(dataset_id="ds", question=question),
            plan=plan,
            execution_result=result,
            verification=verification,
        ).to_dict()

        self.assertEqual("passed", response["semantic_status"])
        self.assertEqual([900, 800, 700], [row["销售额"] for row in response["result"]["rows"]])
        self.assertEqual(3, len(response["debug"]["result_artifacts"]["top_objects"]))

    def test_gap_contract_derives_adjacent_and_leader_gaps_with_direct_summary(self) -> None:
        question = "比较 Top 3 的销售额差距。"
        plan = build_analysis_plan(_ranking_logic(limit=3), question=question)
        rows = [
            {"城市": "上海", "销售额": 900},
            {"城市": "北京", "销售额": 800},
            {"城市": "深圳", "销售额": 700},
        ]
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["城市", "销售额"],
            rows=rows,
            value={"answer": "第一名与第二名销售额差距为 100；第二名与第三名差距为 100。", "candidate_table": rows},
        )

        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))
        response = build_response(
            run_id="run_gap",
            user_question=UserQuestion(dataset_id="ds", question=question),
            plan=plan,
            execution_result=result,
            verification=verification,
        ).to_dict()

        gap_rows = response["debug"]["result_artifacts"]["gap_rows"]
        self.assertEqual("passed", response["semantic_status"])
        self.assertTrue(any("adjacent_gap" in row for row in gap_rows))
        self.assertTrue(any("gap_to_leader" in row for row in gap_rows))
        self.assertIn("差距", response["answer"])

    def test_trend_contract_rejects_monotonic_label_for_up_then_down_values(self) -> None:
        question = "按月份看销售额趋势。"
        plan = build_analysis_plan(
            LogicForm(
                task_type="trend",
                operation="aggregation",
                metric="销售额",
                group_by="月份",
                parameters={"metric": "销售额", "dimension": "月份", "aggregation": "sum"},
                output_format={"answer_type": "table"},
            ),
            question=question,
        )
        rows = [
            {"月份": "1月", "销售额": 396},
            {"月份": "2月", "销售额": 550},
            {"月份": "3月", "销售额": 482},
        ]
        result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["月份", "销售额"],
            rows=rows,
            value={"answer": "销售额先升后降，2月峰值后回落。", "candidate_table": rows},
        )
        bad_result = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["月份", "销售额"],
            rows=rows,
            value={"answer": "销售额整体上升。", "candidate_table": rows},
        )

        verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))
        bad_verification = verify_execution(bad_result, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))
        response = build_response(
            run_id="run_trend",
            user_question=UserQuestion(dataset_id="ds", question=question),
            plan=plan,
            execution_result=result,
            verification=verification,
        ).to_dict()

        self.assertEqual("passed", response["semantic_status"])
        self.assertEqual("先升后降", response["debug"]["result_artifacts"]["trend_description"])
        self.assertNotIn("整体上升", response["answer"])
        self.assertEqual("failed", bad_verification.semantic_status)


def _ranking_logic(*, limit: int) -> LogicForm:
    return LogicForm(
        task_type="ranking",
        operation="ranking",
        metric="销售额",
        group_by="城市",
        parameters={"metric": "销售额", "dimension": "城市", "aggregation": "sum", "sort_order": "desc", "limit": limit},
        output_format={"answer_type": "table"},
    )


if __name__ == "__main__":
    unittest.main()
