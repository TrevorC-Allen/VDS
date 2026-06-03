"""Tests for preserving top object payload for referent followups."""

from __future__ import annotations

import unittest

from data_agent_core.contracts.analysis_contracts import LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.conversation_actions import build_analysis_context
from data_agent_core.output.response_builder import build_response
from data_agent_core.verifier.rule_checker import verify_execution


class TopNArtifactTopObjectsTest(unittest.TestCase):
    def test_top5_result_artifact_keeps_full_top_objects_and_context_links(self) -> None:
        question = "按城市看销售额排名前5。"
        rows = [
            {"city": "深圳", "销售额": 749},
            {"city": "上海", "销售额": 563},
            {"city": "北京", "销售额": 276},
            {"city": "广州", "销售额": 206},
        ]
        expected_order = [
            (1, "深圳", 749),
            (2, "上海", 563),
            (3, "北京", 276),
            (4, "广州", 206),
        ]

        plan = build_analysis_plan(_topn_logic(limit=5), question=question)
        execution = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["city", "销售额"],
            rows=rows,
            value=rows,
        )
        verification = verify_execution(execution, plan=plan, user_question=UserQuestion(dataset_id="ds", question=question))
        response = build_response(
            run_id="run_topn_artifact_full",
            user_question=UserQuestion(dataset_id="ds", question=question),
            plan=plan,
            execution_result=execution,
            verification=verification,
        ).to_dict()

        task_contract = response["debug"].get("task_contract") or {}
        self.assertIn(str(task_contract.get("task_family", "")), {"topn", "ranking"})
        self.assertIn(response["contract_family"], {"topn", "ranking"})
        task_artifacts = response["debug"].get("result_artifacts")
        self.assertIsNotNone(task_artifacts)
        top_objects = task_artifacts["top_objects"]
        self.assertEqual(4, len(top_objects))

        for index, (rank, value, metric_value) in enumerate(expected_order, start=1):
            item = top_objects[index - 1]
            self.assertEqual(rank, item["rank"])
            self.assertEqual(value, item["value"])
            self.assertEqual(metric_value, item["metric_value"])
            self.assertIn("rank", item)
            self.assertIn("value", item)
            self.assertIn("metric_value", item)

        conversation_context = build_analysis_context(
            {
                "success": response["success"],
                "run_id": response["run_id"],
                "dataset_id": "ds",
                "question": response["question"],
                "logic_form": response["logic_form"],
                "result": {
                    "columns": response["result"]["columns"],
                    "rows": rows,
                },
            },
            original_question=response["question"],
        )

        self.assertTrue(conversation_context.get("last_result_artifact_id"))
        active_artifacts = [artifact for artifact in conversation_context.get("active_result_artifacts") if isinstance(artifact, dict)]
        self.assertTrue(active_artifacts)
        artifact_ids = {str(artifact.get("artifact_id") or "") for artifact in active_artifacts}
        last_result_artifact_id = str(conversation_context.get("last_result_artifact_id") or "")
        self.assertIn(last_result_artifact_id, artifact_ids)

        last_ranking_artifact_id = str(conversation_context.get("last_ranking_artifact_id") or "")
        if last_ranking_artifact_id:
            self.assertIn(last_ranking_artifact_id, artifact_ids)
        else:
            self.assertTrue(any(str(artifact.get("artifact_type") or "") in {"ranking", "topn"} for artifact in active_artifacts))

        self.assertTrue(conversation_context.get("focus_sets"))


def _topn_logic(*, limit: int) -> LogicForm:
    return LogicForm(
        task_type="ranking",
        operation="ranking",
        metric="销售额",
        group_by="city",
        parameters={
            "metric": "销售额",
            "dimension": "city",
            "aggregation": "sum",
            "sort_order": "desc",
            "limit": limit,
        },
        output_format={"answer_type": "table"},
    )


if __name__ == "__main__":
    unittest.main()
