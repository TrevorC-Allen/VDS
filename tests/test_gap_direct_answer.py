from __future__ import annotations

import re
import unittest

from data_agent_core.contracts.analysis_contracts import LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.conversation_actions import build_next_actions
from data_agent_core.output.response_builder import build_response
from data_agent_core.rule_checker import verify_execution


class GapDirectAnswerTest(unittest.TestCase):
    def test_gap_direct_answer_shows_direct_differences_and_filters_noisy_followups(self) -> None:
        question = "比较 Top 3 的销售额差距。"
        plan = build_analysis_plan(_ranking_logic(), question=question)
        rows = [
            {"城市": "深圳", "销售额": 749},
            {"城市": "上海", "销售额": 563},
            {"城市": "北京", "销售额": 276},
        ]
        execution = ExecutionResult(
            backend="pandas",
            success=True,
            columns=["城市", "销售额"],
            rows=rows,
            value={"answer": "第一名与第二名销售额差距为 186；第二名与第三名销售额差距为 287。", "candidate_table": rows},
        )

        verification = verify_execution(
            execution,
            plan=plan,
            user_question=UserQuestion(dataset_id="ds", question=question),
        )
        response = build_response(
            run_id="run_gap_direct_answer",
            user_question=UserQuestion(dataset_id="ds", question=question),
            plan=plan,
            execution_result=execution,
            verification=verification,
        ).to_dict()

        self.assertEqual("passed", response["semantic_status"])

        answer = str(response["answer"] or "")
        first_sentence = answer.split("。", 1)[0]
        for token in ("深圳", "上海", "北京", "186", "287"):
            self.assertIn(token, first_sentence)

        for prefix in ("数据摘要", "分析洞察", "业务建议", "口径与边界"):
            self.assertFalse(first_sentence.startswith(prefix))

        normalized = re.sub(r"\s+", "", answer)
        for pair in ("深圳比上海高186", "上海比北京高287"):
            self.assertLessEqual(normalized.count(pair), 2)

        actions = build_next_actions(question=question, plan=plan, rows=rows)
        forbidden_fragments = ("继续比较 Top 3 差距", "计算相邻差距")
        for action in actions:
            action_text = str(action.get("question") or "")
            for fragment in forbidden_fragments:
                self.assertNotIn(fragment, action_text)


def _ranking_logic() -> LogicForm:
    return LogicForm(
        task_type="ranking",
        operation="ranking",
        metric="销售额",
        group_by="城市",
        parameters={"metric": "销售额", "dimension": "城市", "aggregation": "sum", "sort_order": "desc", "limit": 3},
        output_format={"answer_type": "table"},
    )


if __name__ == "__main__":
    unittest.main()
