"""Tests for DABstep post-response proxy observation reporting."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from data_agent_core.benchmark.dabstep_proxy_observation import build_dabstep_proxy_observation


class DabstepProxyObservationTest(unittest.TestCase):
    def test_proxy_observation_scores_current_report_by_level_and_family(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tasks_dir = root / "data" / "tasks"
            scores_dir = root / "data" / "task_scores"
            tasks_dir.mkdir(parents=True)
            scores_dir.mkdir(parents=True)
            (tasks_dir / "all.jsonl").write_text(
                "\n".join(
                    json.dumps(row)
                    for row in (
                        {"task_id": "synthetic-easy", "question": "List ids", "answer": "", "guidelines": "", "level": "easy"},
                        {"task_id": "synthetic-hard", "question": "Choose ACI", "answer": "", "guidelines": "", "level": "hard"},
                    )
                )
                + "\n"
            )
            (scores_dir / "scores.jsonl").write_text(
                "\n".join(
                    json.dumps(row)
                    for row in (
                        {"submission_id": "s1", "task_id": "synthetic-easy", "score": True, "level": "easy", "agent_answer": "1, 2, 3"},
                        {"submission_id": "s2", "task_id": "synthetic-hard", "score": True, "level": "hard", "agent_answer": "E:16.63"},
                    )
                )
                + "\n"
            )
            report_path = root / "report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "details": [
                            {
                                "task_id": "synthetic-easy",
                                "agent_answer": "3, 1, 2",
                                "operation": "applicable_fee_ids",
                                "capability_family": "business_rule_what_if",
                                "success": True,
                            },
                            {
                                "task_id": "synthetic-hard",
                                "agent_answer": "D:20.00",
                                "operation": "best_fraud_aci_choice",
                                "capability_family": "business_rule_what_if",
                                "success": True,
                            },
                        ],
                        "metrics": {"risk_taxonomy": {"format_risk": {"count": 0}}},
                    }
                )
            )

            observation = build_dabstep_proxy_observation(dataset_root=root, report_path=report_path)

        self.assertEqual(2, observation["proxy_scored"])
        self.assertEqual(1, observation["proxy_correct"])
        self.assertEqual(1, observation["proxy_by_level"]["easy"]["proxy_correct"])
        self.assertEqual(0, observation["proxy_by_level"]["hard"]["proxy_correct"])
        self.assertEqual({"best_fraud_aci_choice": 1}, observation["failure_by_operation"])
        self.assertEqual({"business_rule_what_if": 1}, observation["failure_by_capability_family"])
        easy_row = observation["rows"][0]
        self.assertEqual("1, 2, 3", easy_row["canonical_agent_answer"])
        self.assertTrue(easy_row["list_answer_normalized"])


if __name__ == "__main__":
    unittest.main()
