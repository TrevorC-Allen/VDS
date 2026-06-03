from __future__ import annotations

import unittest
from typing import Any

from data_agent_core.core.conversation_actions import build_next_actions


class NextActionDedupTest(unittest.TestCase):
    def test_topn_followups_do_not_repeat_the_same_rank_request(self) -> None:
        question = "城市销售额 Top 3 是哪些？"
        actions = build_next_actions(
            question=question,
            plan={"operation": "ranking", "parameters": {"metric": "sales", "dimension": "city"}},
            rows=[
                {"city": "深圳", "sales": 586},
                {"city": "上海", "sales": 428},
                {"city": "北京", "sales": 414},
            ],
        )

        self.assertGreater(len(actions), 0)
        for action in actions:
            self.assertFalse(self._looks_like_same_topn_request(action))
            self.assertGreaterEqual(self._action_element_count(action), 2)

    def test_gap_followups_do_not_recommend_gap_repeats(self) -> None:
        question = "比较 Top 3 的销售额差距。"
        actions = build_next_actions(
            question=question,
            plan={"operation": "ranking", "parameters": {"metric": "sales", "dimension": "city"}},
            rows=[
                {"city": "深圳", "sales": 749},
                {"city": "上海", "sales": 563},
                {"city": "北京", "sales": 276},
            ],
        )

        self.assertGreater(len(actions), 0)
        forbidden_fragments = (
            "比较 Top 3 差距",
            "比较top3差距",
            "计算相邻差距",
            "计算第一名和第二名差距",
            "相邻排名与第一名的差距",
        )
        for action in actions:
            text = self._action_text(action)
            for fragment in forbidden_fragments:
                self.assertNotIn(fragment, text)
            self.assertGreaterEqual(self._action_element_count(action), 2)

    def test_trend_followups_do_not_repeat_peak_low_extreme_actions(self) -> None:
        question = "继续按月份看销售额趋势。"
        actions = build_next_actions(
            question=question,
            plan={"operation": "trend", "parameters": {"metric": "sales", "dimension": "month"}},
            rows=[
                {"month": "2026-01", "sales": 396},
                {"month": "2026-02", "sales": 550},
                {"month": "2026-03", "sales": 482},
            ],
        )

        self.assertGreater(len(actions), 0)
        forbidden_fragments = ("标出峰值", "标出低点", "标出最大波动期")
        for action in actions:
            text = self._action_text(action)
            for fragment in forbidden_fragments:
                self.assertNotIn(fragment, text)
            self.assertGreaterEqual(self._action_element_count(action), 2)

    def test_next_actions_are_concrete_and_executable(self) -> None:
        actions = build_next_actions(
            question="城市销售额 Top 3 是哪些？",
            plan={"operation": "ranking", "parameters": {"metric": "sales", "dimension": "city"}},
            rows=[
                {"city": "深圳", "sales": 586},
                {"city": "上海", "sales": 428},
                {"city": "北京", "sales": 414},
            ],
        )

        self.assertTrue(actions)
        for action in actions:
            self.assertIn("operation", action)
            self.assertIsInstance(action.get("question"), str)
            self.assertTrue(str(action.get("question") or "").strip())
            self.assertGreaterEqual(self._action_element_count(action), 2)

    def _action_text(self, action: dict[str, Any]) -> str:
        parts: list[str] = [
            str(action.get("action_id") or ""),
            str(action.get("label") or ""),
            str(action.get("operation") or ""),
            str(action.get("question") or ""),
            str(action.get("dimension") or ""),
        ]
        parameters = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
        inherited = action.get("inherited_parameters") if isinstance(action.get("inherited_parameters"), dict) else {}
        parts.extend(
            [
                str(parameters.get("metric") or ""),
                str(parameters.get("dimension") or ""),
                str(parameters.get("time_column") or ""),
                str(parameters.get("quality_check") or ""),
                str(inherited.get("filters") or ""),
                str(inherited.get("time_window") or ""),
                str(inherited.get("start_ym") or ""),
                str(inherited.get("end_ym") or ""),
            ]
        )
        return " ".join(part for part in parts if part).lower()

    def _looks_like_same_topn_request(self, action: dict[str, Any]) -> bool:
        text = self._action_text(action)
        return self._contains_any(text, ("city", "城市")) and self._contains_any(
            text,
            ("sales", "销售额", "销售金额", "收入", "金额"),
        ) and self._contains_any(text, ("top3", "top 3", "前3", "前三", "排名前3", "ranking", "排名"))

    def _action_element_count(self, action: dict[str, Any]) -> int:
        count = 0
        text = self._action_text(action)
        parameters = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
        inherited = action.get("inherited_parameters") if isinstance(action.get("inherited_parameters"), dict) else {}

        if str(action.get("operation") or "").strip():
            count += 1
        if parameters.get("metric") or self._contains_any(text, ("sales", "销售额", "金额", "收入", "利润", "数量")):
            count += 1
        if parameters.get("dimension") or action.get("dimension") or self._contains_any(text, ("city", "城市", "month", "月份", "date", "日期", "time", "时间")):
            count += 1
        if parameters.get("time_column") or inherited.get("time_window") or inherited.get("start_ym") or inherited.get("end_ym") or self._contains_any(
            text,
            ("月份", "month", "日期", "date", "时间", "time"),
        ):
            count += 1
        if inherited.get("filters") or inherited.get("value_filters") or self._contains_any(text, ("筛选", "过滤", "只看", "条件")):
            count += 1
        return count

    def _contains_any(self, text: str, tokens: tuple[str, ...]) -> bool:
        return any(token.lower() in text for token in tokens)


if __name__ == "__main__":
    unittest.main()
