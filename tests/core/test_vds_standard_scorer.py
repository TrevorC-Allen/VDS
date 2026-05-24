"""Tests for VDS standard-answer post-response scoring."""

from __future__ import annotations

import unittest

from data_agent_core.benchmark.vds_standard_scorer import score_vds_standard_answer


class VdsStandardScorerTest(unittest.TestCase):
    def test_count_share_uses_structured_raw_value(self) -> None:
        result = score_vds_standard_answer(
            "PSD本周高于上周的门店有5个，占本周有记录门店的55.56%。",
            "可比较门店共9家；PSD较上周增长5家，占比55.56%。",
            raw_value={"count": 5, "share": 55.555555, "total": 9},
            operation="vds_period_growth_count_share",
        )

        self.assertTrue(result.correct)
        self.assertEqual("count_share_structured", result.scorer)

    def test_peer_anomaly_accepts_entity_match_with_peer_prefix(self) -> None:
        result = score_vds_standard_answer(
            "本周AT高于同商圈平均值2倍的门店有1家。武汉：本周1219.46，上周/对比值399.06，变化820.39，环比205.58%",
            "文旅商圈 / 武汉：本周AT=1219.46，对比值385.84，变化833.62，环比316.06%",
            operation="vds_peer_anomaly",
        )

        self.assertTrue(result.correct)
        self.assertEqual("peer_anomaly_entity_subset", result.scorer)

    def test_peer_anomaly_accepts_same_metric_tie_order(self) -> None:
        expected = (
            "金融服务 / 云启客户13：本周DAU=3.29，对比值8.70，变化-5.42，环比37.76%；"
            "金融服务 / 云启客户20：本周DAU=3.29，对比值8.70，变化-5.42，环比37.76%"
        )
        predicted = (
            "金融服务 / 云启客户20：本周DAU=3.29，对比值8.70，变化-5.42，环比37.76%；"
            "金融服务 / 云启客户13：本周DAU=3.29，对比值8.70，变化-5.42，环比37.76%"
        )

        result = score_vds_standard_answer(expected, predicted, operation="vds_peer_anomaly")

        self.assertTrue(result.correct)
        self.assertEqual("peer_anomaly_tie_tolerant", result.scorer)

    def test_status_impact_accepts_zero_delta_boundary_ties(self) -> None:
        expected = (
            "1. 云启客户31：本周含流失/暂停ARR=10.00，对比值1.00，变化9.00，环比900.00%；"
            "2. 云启客户01：本周含流失/暂停ARR=5.00，对比值5.00，变化0.00，环比0.00%"
        )
        predicted = (
            "1. 云启客户31：本周含流失/暂停ARR=10.00，对比值1.00，变化9.00，环比900.00%；"
            "2. 云启客户34：本周含流失/暂停ARR=7.00，对比值7.00，变化0.00，环比0.00%"
        )

        result = score_vds_standard_answer(
            expected,
            predicted,
            raw_value={"candidate_table": [{"客户名称": "云启客户31", "delta": 9.0}, {"客户名称": "云启客户34", "delta": 0.0}]},
            operation="vds_status_impact_top",
        )

        self.assertTrue(result.correct)


if __name__ == "__main__":
    unittest.main()
