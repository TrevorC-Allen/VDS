"""Tests for reusable conversation follow-up action planning."""

from __future__ import annotations

import unittest

from data_agent_core.core.conversation_actions import plan_followup_actions


class ConversationActionsTest(unittest.TestCase):
    def test_generic_dimension_switch_followup_does_not_use_retail_action(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "ranking",
            "logic_form": {
                "operation": "ranking",
                "metric": "sales",
                "group_by": "city",
                "parameters": {
                    "table": "regional_sales",
                    "metric": "sales",
                    "dimension": "city",
                    "available_columns": ["month", "city", "product", "sales", "profit"],
                },
            },
            "scope": {"metric": "sales", "dimension": "city"},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("那按产品拆一下", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_generic_dimension", actions[0]["action_id"])
        self.assertEqual("ranking", actions[0]["operation"])
        self.assertEqual("product", actions[0]["dimension"])
        self.assertEqual({"metric": "sales", "dimension": "product"}, actions[0]["parameters"])
        self.assertNotEqual("retail_distribution_topn_chart", actions[0]["operation"])

    def test_contextual_city_followup_carries_top_entity_into_time_trend(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "ranking",
            "logic_form": {
                "operation": "ranking",
                "metric": "amount",
                "group_by": "city",
                "parameters": {
                    "table": "orders",
                    "metric": "amount",
                    "dimension": "city",
                    "available_columns": ["month", "customer_id", "amount", "profit", "city", "segment"],
                },
            },
            "scope": {"metric": "amount", "dimension": "city", "filters": {}},
            "last_result": {"first_row": {"city": "上海", "amount": 325}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("这个城市在1月、2月、3月的订单金额月度趋势如何？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_to_time_trend", actions[0]["action_id"])
        self.assertEqual("aggregation", actions[0]["operation"])
        self.assertIn("筛选上海城市的数据", actions[0]["question"])
        self.assertIn("按月份展示订单金额趋势", actions[0]["question"])

    def test_contextual_change_wording_routes_to_time_trend(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "ranking",
            "logic_form": {
                "operation": "ranking",
                "metric": "amount",
                "group_by": "city",
                "parameters": {
                    "table": "orders",
                    "metric": "amount",
                    "dimension": "city",
                    "available_columns": ["month", "customer_id", "amount", "profit", "city", "segment"],
                },
            },
            "scope": {"metric": "amount", "dimension": "city", "filters": {}},
            "last_result": {"first_row": {"city": "上海", "amount": 325}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("刚才排名第一的城市，其订单金额在这三个月中是如何变化的？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_to_time_trend", actions[0]["action_id"])
        self.assertEqual("aggregation", actions[0]["operation"])
        self.assertIn("筛选上海城市的数据", actions[0]["question"])

    def test_contextual_top_entity_drilldown_switches_to_customer_dimension(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "ranking",
            "logic_form": {
                "operation": "ranking",
                "metric": "amount",
                "group_by": "city",
                "parameters": {
                    "table": "orders",
                    "metric": "amount",
                    "dimension": "city",
                    "available_columns": ["month", "customer_id", "amount", "profit", "city", "segment"],
                },
            },
            "scope": {"metric": "amount", "dimension": "city", "filters": {}},
            "last_result": {"first_row": {"city": "上海", "amount": 325}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("在订单金额最高的城市中，哪个客户贡献的订单金额最多？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_generic_dimension", actions[0]["action_id"])
        self.assertEqual("ranking", actions[0]["operation"])
        self.assertEqual("customer_id", actions[0]["dimension"])
        self.assertIn("筛选上海城市的数据", actions[0]["question"])

    def test_plural_focus_set_switches_to_requested_product_dimension(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "aggregation",
            "logic_form": {
                "operation": "aggregation",
                "metric": "sales",
                "group_by": "month",
                "filters": {"city": ["上海", "北京", "广州"]},
                "parameters": {
                    "table": "regional_performance",
                    "metric": "sales",
                    "dimension": "month",
                    "available_columns": ["month", "city", "product", "sales", "profit"],
                },
            },
            "scope": {"metric": "sales", "dimension": "month", "filters": {"city": ["上海", "北京", "广州"]}},
            "last_result": {"first_row": {"month": "2026-02", "sales": 606}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("在这些城市中，哪个产品销售额最高？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_generic_dimension", actions[0]["action_id"])
        self.assertEqual("product", actions[0]["dimension"])
        self.assertEqual({"metric": "sales", "dimension": "product"}, actions[0]["parameters"])
        self.assertIn("筛选上海、北京、广州城市的数据", actions[0]["question"])

    def test_contextual_customer_ranking_uses_explicit_profit_metric(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "aggregation",
            "logic_form": {
                "operation": "aggregation",
                "metric": "amount",
                "group_by": "month",
                "filters": {"city": "上海"},
                "parameters": {
                    "table": "orders",
                    "metric": "amount",
                    "dimension": "month",
                    "available_columns": ["month", "customer_id", "amount", "profit", "city", "segment"],
                },
            },
            "scope": {"metric": "amount", "dimension": "month", "filters": {"city": "上海"}},
            "last_result": {"first_row": {"month": "2026-01", "amount": 120}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("在这个城市中，利润最高的前3个客户是谁？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_generic_dimension", actions[0]["action_id"])
        self.assertEqual("ranking", actions[0]["operation"])
        self.assertEqual("customer_id", actions[0]["dimension"])
        self.assertEqual({"metric": "profit", "dimension": "customer_id"}, actions[0]["parameters"])
        self.assertIn("筛选上海城市的数据", actions[0]["question"])
        self.assertIn("按客户看利润排名前3", actions[0]["question"])

    def test_pronoun_profit_margin_followup_carries_focus_filter(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "aggregation",
            "logic_form": {
                "operation": "aggregation",
                "metric": "sales",
                "group_by": "month",
                "filters": {"city": "深圳"},
                "parameters": {
                    "table": "service_metrics",
                    "metric": "sales",
                    "dimension": "month",
                    "available_columns": ["month", "city", "service_line", "sales", "profit", "tickets"],
                },
            },
            "scope": {"metric": "sales", "dimension": "month", "filters": {"city": "深圳"}},
            "last_result": {"first_row": {"month": "2026-02", "sales": 302}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("它的利润率表现怎么样？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_to_profit_margin", actions[0]["action_id"])
        self.assertEqual("ranking", actions[0]["operation"])
        self.assertIn("筛选深圳城市的数据", actions[0]["question"])
        self.assertTrue("利润率最高" in actions[0]["question"] or "利润率排名" in actions[0]["question"])

    def test_product_profit_margin_scalar_followup_beats_dimension_switch(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "filtered_metric_ranking",
            "logic_form": {
                "operation": "filtered_metric_ranking",
                "metric": "sales",
                "group_by": "product",
                "filters": {"city": "上海"},
                "parameters": {
                    "table": "regional_performance",
                    "metric": "sales",
                    "dimension": "product",
                    "available_columns": ["month", "city", "product", "sales", "profit"],
                },
            },
            "scope": {"metric": "sales", "dimension": "product", "filters": {"city": "上海"}},
            "last_result": {"first_row": {"product": "数据治理", "sales": 245}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("这个产品在2026年1月的利润率是多少？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_to_profit_margin_scalar", actions[0]["action_id"])
        self.assertEqual("aggregation", actions[0]["operation"])
        self.assertEqual("利润率", actions[0]["parameters"]["metric"])
        self.assertIn("上海城市", actions[0]["question"])
        self.assertIn("数据治理产品", actions[0]["question"])
        self.assertIn("在2026年1月", actions[0]["question"])

    def test_product_profit_margin_scalar_followup_carries_parent_filter_and_product_focus(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "filtered_metric_ranking",
            "logic_form": {
                "operation": "filtered_metric_ranking",
                "metric": "sales",
                "group_by": "product",
                "filters": {"city": "深圳"},
                "parameters": {
                    "table": "regional_performance",
                    "metric": "sales",
                    "dimension": "product",
                    "available_columns": ["month", "city", "product", "sales", "profit"],
                },
            },
            "scope": {"metric": "sales", "dimension": "product", "filters": {"city": "深圳"}},
            "last_result": {"first_row": {"product": "数据治理", "sales": 388}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("这款产品的利润率是多少？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_to_profit_margin_scalar", actions[0]["action_id"])
        self.assertEqual("aggregation", actions[0]["operation"])
        self.assertIn("筛选深圳城市、数据治理产品的数据", actions[0]["question"])
        self.assertEqual("利润率", actions[0]["parameters"]["metric"])

    def test_growth_fastest_two_cities_routes_to_growth_ranking_not_trend(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "filtered_metric_ranking",
            "logic_form": {
                "operation": "filtered_metric_ranking",
                "metric": "sales",
                "group_by": "city",
                "filters": {"month": {"year": 2026, "month": 1}},
                "parameters": {
                    "table": "regional_performance",
                    "metric": "sales",
                    "dimension": "city",
                    "available_columns": ["month", "city", "product", "sales", "profit"],
                },
            },
            "scope": {"metric": "sales", "dimension": "city", "filters": {"month": {"year": 2026, "month": 1}}},
            "last_result": {"first_row": {"city": "上海", "sales": 318}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("从1月到2月，销售额增长最快的两个城市是哪些？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("growth_ranking", actions[0]["action_id"])
        self.assertEqual("growth_ranking", actions[0]["operation"])
        self.assertEqual("city", actions[0]["dimension"])
        self.assertEqual("city", actions[0]["parameters"]["dimension"])
        self.assertIn("1月到2月", actions[0]["question"])

    def test_change_largest_city_routes_to_growth_delta_ranking_not_month_trend(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "filtered_metric_ranking",
            "logic_form": {
                "operation": "filtered_metric_ranking",
                "metric": "sales",
                "group_by": "city",
                "filters": {"month": {"year": 2026, "month": 1}},
                "parameters": {
                    "table": "regional_performance",
                    "metric": "sales",
                    "dimension": "city",
                    "available_columns": ["month", "city", "product", "sales", "profit"],
                },
            },
            "scope": {"metric": "sales", "dimension": "city", "filters": {"month": {"year": 2026, "month": 1}}},
            "last_result": {"first_row": {"city": "上海", "sales": 318}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("那么，从1月到2月，销售额变化最大的城市是哪个？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("growth_ranking", actions[0]["action_id"])
        self.assertEqual("growth_ranking", actions[0]["operation"])
        self.assertEqual("city", actions[0]["dimension"])
        self.assertEqual("abs_delta", actions[0]["parameters"]["growth_mode"])
        self.assertIn("1月到2月", actions[0]["question"])
        self.assertNotIn("filters", actions[0]["inherited_parameters"])

    def test_focus_city_set_growth_fastest_routes_to_growth_ranking_not_trend(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "ranking",
            "logic_form": {
                "operation": "ranking",
                "metric": "sales",
                "group_by": "city",
                "filters": {"month": {"month_range": [1, 3]}},
                "parameters": {
                    "table": "regional_performance",
                    "metric": "sales",
                    "dimension": "city",
                    "available_columns": ["month", "city", "product", "sales", "profit"],
                },
            },
            "scope": {"metric": "sales", "dimension": "city", "filters": {"month": {"month_range": [1, 3]}}},
            "last_result": {"first_row": {"city": "深圳", "sales": 586}},
            "focus_sets": [{"dimension": "city", "metric": "sales", "limit": 3, "filters": {"month": {"month_range": [1, 3]}}}],
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("这些城市中，销售额增长最快的是哪个？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("growth_ranking", actions[0]["action_id"])
        self.assertEqual("growth_ranking", actions[0]["operation"])
        self.assertEqual("city", actions[0]["dimension"])

    def test_growth_entity_product_followup_keeps_entity_filter_and_product_dimension(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "growth_ranking",
            "logic_form": {
                "operation": "growth_ranking",
                "metric": "sales",
                "group_by": "city",
                "filters": {"month": {"month_range": [1, 3]}},
                "parameters": {
                    "table": "regional_performance",
                    "metric": "sales",
                    "dimension": "city",
                    "available_columns": ["month", "city", "product", "sales", "profit"],
                },
            },
            "scope": {"metric": "sales", "dimension": "city", "filters": {"month": {"month_range": [1, 3]}}},
            "last_result": {"first_row": {"city": "深圳", "sales_growth_rate": 0.07}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("在增长最快的城市中，哪个产品销售额最高？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_generic_dimension", actions[0]["action_id"])
        self.assertEqual("ranking", actions[0]["operation"])
        self.assertEqual("product", actions[0]["dimension"])
        self.assertIn("筛选深圳城市的数据", actions[0]["question"])

    def test_ranked_city_set_metric_change_routes_to_month_trend(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "ranking",
            "logic_form": {
                "operation": "ranking",
                "metric": "sales",
                "group_by": "city",
                "parameters": {
                    "table": "service_metrics",
                    "metric": "sales",
                    "dimension": "city",
                    "available_columns": ["month", "city", "service_line", "sales", "profit", "tickets"],
                },
            },
            "scope": {"metric": "sales", "dimension": "city", "filters": {}},
            "focus_sets": [{"dimension": "city", "metric": "sales", "limit": 3, "filters": {}}],
            "last_result": {"first_row": {"city": "深圳", "sales": 586}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("排名前3的城市在2026年1月到3月的销售额变化趋势如何？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_to_time_trend", actions[0]["action_id"])
        self.assertEqual("aggregation", actions[0]["operation"])
        self.assertEqual("month", actions[0]["dimension"])
        self.assertIn("按月份展示销售额趋势", actions[0]["question"])

    def test_question_target_dimension_beats_secondary_product_wording(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "growth_ranking",
            "logic_form": {
                "operation": "growth_ranking",
                "metric": "sales",
                "group_by": "city",
                "filters": {"month": {"month_range": [1, 2]}},
                "parameters": {
                    "table": "regional_performance",
                    "metric": "sales",
                    "dimension": "city",
                    "available_columns": ["month", "city", "product", "sales", "profit"],
                },
            },
            "scope": {"metric": "sales", "dimension": "city", "filters": {"month": {"month_range": [1, 2]}}},
            "last_result": {"first_row": {"city": "上海", "sales_growth_rate": 0.2}},
            "focus_sets": [{"dimension": "city", "metric": "sales", "limit": 3, "filters": {"month": {"month": 2}}}],
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("在2月销售额排名前3的城市中，哪个城市的产品销售最集中？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_generic_dimension", actions[0]["action_id"])
        self.assertEqual("city", actions[0]["dimension"])
        self.assertEqual("city", actions[0]["parameters"]["dimension"])

    def test_product_ordinal_followup_keeps_city_filter_and_rank_position(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "aggregation",
            "logic_form": {
                "operation": "aggregation",
                "metric": "sales",
                "group_by": "month",
                "filters": {"city": "上海", "month": {"month_range": [2, 3]}},
                "parameters": {
                    "table": "regional_performance",
                    "metric": "sales",
                    "dimension": "month",
                    "available_columns": ["month", "city", "product", "sales", "profit"],
                },
            },
            "scope": {"metric": "sales", "dimension": "month", "filters": {"city": "上海", "month": {"month_range": [2, 3]}}},
            "last_result": {"first_row": {"month": "2026-02", "sales": 245}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("那这个城市销售额排名第二的产品是什么？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_generic_dimension", actions[0]["action_id"])
        self.assertEqual("ranking", actions[0]["operation"])
        self.assertEqual("product", actions[0]["dimension"])
        self.assertIn("筛选上海城市的数据", actions[0]["question"])
        self.assertIn("销售额排名第二的产品是什么", actions[0]["question"])

    def test_focus_entity_rank_position_uses_focus_dimension_without_entity_filter(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "aggregation",
            "logic_form": {
                "operation": "aggregation",
                "metric": "sales",
                "group_by": None,
                "filters": {"city": "上海", "month": {"year": 2026, "month": 1}},
                "parameters": {
                    "table": "regional_performance",
                    "metric": "sales",
                    "dimension": None,
                    "available_columns": ["month", "city", "product", "sales", "profit"],
                },
            },
            "scope": {"metric": "sales", "dimension": "", "filters": {"city": "上海", "month": {"year": 2026, "month": 1}}},
            "last_result": {"first_row": {"answer": 318}},
            "focus_sets": [
                {
                    "source": "ranking_result",
                    "dimension": "city",
                    "metric": "sales",
                    "limit": 1,
                    "filters": {"month": {"year": 2026, "month": 1}},
                    "values": ["上海"],
                }
            ],
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("在2月份，这个城市销售额排第几？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("focus_entity_rank_position", actions[0]["action_id"])
        self.assertEqual("ranking", actions[0]["operation"])
        self.assertEqual("city", actions[0]["dimension"])
        self.assertEqual("city", actions[0]["parameters"]["dimension"])
        self.assertEqual({"dimension": "city", "value": "上海"}, actions[0]["parameters"]["rank_target"])
        self.assertNotIn("filters", actions[0]["inherited_parameters"])
        self.assertIn("在2月", actions[0]["question"])
        self.assertIn("上海城市的销售额在全部城市中排第几", actions[0]["question"])

    def test_segment_followup_is_dimension_switch_not_month_ranking(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "aggregation",
            "logic_form": {
                "operation": "aggregation",
                "metric": "amount",
                "group_by": "month",
                "filters": {"city": "北京", "month": {"month_range": [1, 3]}},
                "parameters": {
                    "table": "orders",
                    "metric": "amount",
                    "dimension": "month",
                    "available_columns": ["month", "customer_id", "amount", "profit", "city", "segment"],
                },
            },
            "scope": {"metric": "amount", "dimension": "month", "filters": {"city": "北京", "month": {"month_range": [1, 3]}}},
            "last_result": {"first_row": {"month": "2026-01", "amount": 310}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("这个城市在这三个月里，哪个细分市场的订单金额排名第一？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_generic_dimension", actions[0]["action_id"])
        self.assertEqual("segment", actions[0]["dimension"])
        self.assertIn("1月到3月", actions[0]["question"])
        self.assertIn("筛选北京城市的数据", actions[0]["question"])
        self.assertIn("订单金额排名第一的客群是什么", actions[0]["question"])

    def test_customer_segment_wording_switches_to_segment_dimension(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "aggregation",
            "logic_form": {
                "operation": "aggregation",
                "metric": "amount",
                "group_by": "month",
                "filters": {"city": "上海", "month": {"year": 2026, "month_range": [1, 3]}},
                "parameters": {
                    "table": "orders",
                    "metric": "amount",
                    "dimension": "month",
                    "available_columns": ["month", "customer_id", "amount", "profit", "city", "segment"],
                },
            },
            "scope": {"metric": "amount", "dimension": "month", "filters": {"city": "上海", "month": {"year": 2026, "month_range": [1, 3]}}},
            "last_result": {"first_row": {"month": "2026-02", "amount": 205}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("在这些月份中，该城市各客户分段的订单金额排名是怎样的？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_generic_dimension", actions[0]["action_id"])
        self.assertEqual("segment", actions[0]["dimension"])
        self.assertIn("筛选上海城市的数据", actions[0]["question"])
        self.assertIn("订单金额排名", actions[0]["question"])

        actions = plan_followup_actions("在这些月份中，该城市哪个客户段的订单金额最高？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_generic_dimension", actions[0]["action_id"])
        self.assertEqual("segment", actions[0]["dimension"])
        self.assertIn("筛选上海城市的数据", actions[0]["question"])

    def test_growth_entity_profit_margin_followup_stays_entity_ranking(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "growth_ranking",
            "logic_form": {
                "operation": "growth_ranking",
                "metric": "sales",
                "group_by": "city",
                "filters": {"month": {"month_range": [2, 3]}},
                "parameters": {
                    "table": "regional_performance",
                    "metric": "sales",
                    "dimension": "city",
                    "available_columns": ["month", "city", "product", "sales", "profit"],
                },
            },
            "scope": {"metric": "sales", "dimension": "city", "filters": {"month": {"month_range": [2, 3]}}},
            "last_result": {"first_row": {"city": "深圳", "sales_growth_rate": 0.07}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("这些增长最快城市的利润率如何？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_to_profit_margin", actions[0]["action_id"])
        self.assertEqual("ranking", actions[0]["operation"])
        self.assertEqual("city", actions[0]["dimension"])
        self.assertIn("哪个城市利润率最高", actions[0]["question"])

    def test_top_gap_followup_explicit_metric_overrides_previous_profit_margin_context(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "ranking",
            "logic_form": {
                "operation": "ranking",
                "metric": "利润率",
                "group_by": "city",
                "parameters": {
                    "table": "regional_performance",
                    "metric": "利润率",
                    "dimension": "city",
                    "available_columns": ["month", "city", "product", "sales", "profit"],
                    "derived_metric": {
                        "name": "利润率",
                        "numerator": "profit",
                        "denominator": "sales",
                        "formula": "sum(profit)/sum(sales)",
                    },
                },
            },
            "scope": {"metric": "利润率", "dimension": "city", "filters": {}},
            "last_result": {"first_row": {"city": "深圳", "利润率": 0.3258}},
            "available_followup_actions": [
                {
                    "action_id": "drilldown_top_results",
                    "operation": "ranking",
                    "question": "按city看利润率排名前3。",
                    "parameters": {"metric": "利润率", "dimension": "city"},
                    "dimension": "city",
                }
            ],
        }

        actions = plan_followup_actions("比较 Top 2 的销售额差距。", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("drilldown_top_results", actions[0]["action_id"])
        self.assertEqual("sales", actions[0]["parameters"]["metric"])
        self.assertEqual("city", actions[0]["parameters"]["dimension"])
        self.assertIn("销售额排名前3", actions[0]["question"])
        self.assertNotIn("利润率", actions[0]["question"])

    def test_profit_customer_followup_uses_profit_metric_and_customer_dimension(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "aggregation",
            "logic_form": {
                "operation": "aggregation",
                "metric": "amount",
                "group_by": "month",
                "filters": {"city": "北京", "month": {"year": 2026, "month_range": [1, 3]}},
                "parameters": {
                    "table": "orders",
                    "metric": "amount",
                    "dimension": "month",
                    "available_columns": ["month", "customer_id", "amount", "profit", "city"],
                },
            },
            "scope": {"metric": "amount", "dimension": "month", "filters": {"city": "北京", "month": {"year": 2026, "month_range": [1, 3]}}},
            "last_result": {"first_row": {"month": "2026-01", "amount": 310}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("这三个月里，该城市利润最高的客户是哪个？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_generic_dimension", actions[0]["action_id"])
        self.assertEqual("customer_id", actions[0]["dimension"])
        self.assertEqual({"metric": "profit", "dimension": "customer_id"}, actions[0]["parameters"])
        self.assertIn("筛选北京城市的数据", actions[0]["question"])
        self.assertIn("按客户看利润排名前3", actions[0]["question"])

    def test_extreme_month_then_top_customer_followup_keeps_context_filter(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "aggregation",
            "logic_form": {
                "operation": "aggregation",
                "metric": "amount",
                "group_by": "month",
                "filters": {"city": "上海", "month": {"year": 2026, "month_range": [1, 3]}},
                "parameters": {
                    "table": "orders",
                    "metric": "amount",
                    "dimension": "month",
                    "available_columns": ["month", "customer_id", "amount", "profit", "city", "segment"],
                },
            },
            "scope": {"metric": "amount", "dimension": "month", "filters": {"city": "上海", "month": {"year": 2026, "month_range": [1, 3]}}},
            "last_result": {"first_row": {"month": "2026-02", "amount": 205}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("在这三个月中，哪个月份的订单金额最高？该月份的前三大客户是哪些？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("extreme_time_scoped_dimension_drilldown", actions[0]["action_id"])
        self.assertEqual("ranking", actions[0]["operation"])
        self.assertEqual("customer_id", actions[0]["dimension"])
        self.assertEqual({"metric": "amount", "dimension": "customer_id", "time_column": "month", "limit": 3}, actions[0]["parameters"])
        self.assertIn("筛选上海城市的数据", actions[0]["question"])
        self.assertIn("哪个月份的订单金额最高", actions[0]["question"])
        self.assertIn("排名前3的客户", actions[0]["question"])

    def test_profit_margin_trend_keeps_derived_metric_and_time_dimension(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "ranking",
            "logic_form": {
                "operation": "ranking",
                "metric": "利润率",
                "group_by": "city",
                "parameters": {
                    "table": "orders",
                    "metric": "利润率",
                    "dimension": "city",
                    "available_columns": ["month", "customer_id", "amount", "profit", "city", "segment"],
                },
            },
            "scope": {"metric": "利润率", "dimension": "city", "filters": {}},
            "last_result": {"first_row": {"city": "上海", "利润率": 0.31}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("这个城市在1月、2月、3月的利润率变化趋势是怎样的？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_profit_margin_time_trend", actions[0]["action_id"])
        self.assertEqual("aggregation", actions[0]["operation"])
        self.assertEqual("month", actions[0]["dimension"])
        self.assertEqual("利润率", actions[0]["parameters"]["metric"])
        self.assertEqual({"name": "利润率", "numerator": "profit", "denominator": "amount", "formula": "sum(profit)/sum(amount)"}, actions[0]["parameters"]["derived_metric"])
        self.assertIn("筛选上海城市的数据", actions[0]["question"])
        self.assertIn("按月份展示利润率趋势", actions[0]["question"])

    def test_profit_margin_compute_and_find_highest_routes_to_ranking(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "aggregation",
            "logic_form": {
                "operation": "aggregation",
                "metric": "sales",
                "group_by": "city",
                "filters": {"month": {"year": 2026, "month_range": [1, 3]}},
                "parameters": {
                    "table": "service_metrics",
                    "metric": "sales",
                    "dimension": "city",
                    "available_columns": ["month", "city", "service_line", "sales", "profit", "tickets"],
                },
            },
            "scope": {"metric": "sales", "dimension": "city", "filters": {"month": {"year": 2026, "month_range": [1, 3]}}},
            "last_result": {"first_row": {"city": "上海", "sales": 428}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("计算每个城市第一季度的利润率，并找出利润率最高的城市。", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_to_profit_margin", actions[0]["action_id"])
        self.assertEqual("ranking", actions[0]["operation"])
        self.assertEqual("city", actions[0]["dimension"])
        self.assertEqual("利润率", actions[0]["parameters"]["metric"])

    def test_grouped_profit_margin_display_uses_aggregation_not_ranking(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "aggregation",
            "logic_form": {
                "operation": "aggregation",
                "metric": "sales",
                "group_by": "month",
                "filters": {"city": "上海", "month": {"year": 2026}},
                "parameters": {
                    "table": "service_metrics",
                    "metric": "sales",
                    "dimension": "month",
                    "available_columns": ["month", "city", "service_line", "sales", "profit", "tickets"],
                },
            },
            "scope": {"metric": "sales", "dimension": "month", "filters": {"city": "上海", "month": {"year": 2026}}},
            "last_result": {"first_row": {"month": "2026-02", "sales": 248}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("2026年1月各城市的利润率如何？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_profit_margin_breakdown", actions[0]["action_id"])
        self.assertEqual("aggregation", actions[0]["operation"])
        self.assertEqual("city", actions[0]["dimension"])
        self.assertEqual("利润率", actions[0]["parameters"]["metric"])
        self.assertIn("按城市汇总利润率", actions[0]["question"])

    def test_reasonableness_followup_preserves_explicit_multiple_metrics(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "aggregation",
            "logic_form": {
                "operation": "aggregation",
                "metric": "sales",
                "group_by": "month",
                "filters": {"city": "深圳", "month": {"month_range": [1, 3]}},
                "parameters": {
                    "table": "service_metrics",
                    "metric": "sales",
                    "dimension": "month",
                    "available_columns": ["month", "city", "service_line", "sales", "profit", "tickets"],
                },
            },
            "scope": {"metric": "sales", "dimension": "month", "filters": {"city": "深圳", "month": {"month_range": [1, 3]}}},
            "last_result": {"first_row": {"month": "2026-03", "sales": 284}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("这个城市3月份的工单数量与销售额相比是否合理？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("grouped_metric_distribution", actions[0]["action_id"])
        self.assertEqual("aggregation", actions[0]["operation"])
        self.assertEqual("city", actions[0]["dimension"])
        self.assertEqual("sales", actions[0]["parameters"]["metric"])
        self.assertEqual(["sales", "tickets"], actions[0]["parameters"]["metrics"])
        self.assertTrue(actions[0]["parameters"]["requires_reasonableness_baseline"])
        self.assertIn("筛选深圳城市的数据", actions[0]["question"])
        self.assertIn("按城市汇总销售额和工单量", actions[0]["question"])
        self.assertIn("是否合理需要哪些基准", actions[0]["question"])

    def test_negative_metric_followup_routes_to_quality_rule_action(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "aggregation",
            "logic_form": {
                "operation": "aggregation",
                "metric": "sales",
                "group_by": "month",
                "filters": {"city": ["上海", "深圳"], "month": {"year": 2026, "month_range": [1, 3]}},
                "parameters": {
                    "table": "service_metrics",
                    "metric": "sales",
                    "dimension": "month",
                    "available_columns": ["month", "city", "service_line", "sales", "profit", "tickets"],
                },
            },
            "scope": {"metric": "sales", "dimension": "month", "filters": {"city": ["上海", "深圳"], "month": {"year": 2026, "month_range": [1, 3]}}},
            "last_result": {"first_row": {"month": "2026-01", "sales": 566}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("这些城市中，有没有哪个月份的利润出现负值？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("check_metric_anomaly", actions[0]["action_id"])
        self.assertEqual("anomaly_rules", actions[0]["operation"])
        self.assertEqual("profit", actions[0]["parameters"]["metric"])
        self.assertEqual("negative_value", actions[0]["parameters"]["quality_check"])
        self.assertIn("利润是否存在负值", actions[0]["question"])
        self.assertIn("异常规则", actions[0]["question"])

    def test_grouped_service_line_profit_margin_ranking_beats_city_context(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "aggregation",
            "logic_form": {
                "operation": "aggregation",
                "metric": "sales",
                "group_by": "month",
                "filters": {"city": "深圳", "month": {"month_range": [1, 3]}},
                "parameters": {
                    "table": "service_metrics",
                    "metric": "sales",
                    "dimension": "month",
                    "available_columns": ["month", "city", "service_line", "sales", "profit", "tickets"],
                },
            },
            "scope": {"metric": "sales", "dimension": "month", "filters": {"city": "深圳", "month": {"month_range": [1, 3]}}},
            "last_result": {"first_row": {"month": "2026-02", "sales": 302}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("这个城市各服务线的利润率排名是怎样的？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_to_profit_margin", actions[0]["action_id"])
        self.assertEqual("service_line", actions[0]["dimension"])
        self.assertEqual("service_line", actions[0]["parameters"]["dimension"])
        self.assertIn("筛选深圳城市的数据", actions[0]["question"])
        self.assertIn("哪个服务线利润率最高", actions[0]["question"])

    def test_profit_margin_trend_for_best_service_line_uses_ranked_result_filter(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "filtered_metric_ranking",
            "logic_form": {
                "operation": "filtered_metric_ranking",
                "metric": "利润率",
                "group_by": "service_line",
                "filters": {"city": "深圳"},
                "parameters": {
                    "table": "service_metrics",
                    "metric": "利润率",
                    "dimension": "service_line",
                    "available_columns": ["month", "city", "service_line", "sales", "profit", "tickets"],
                },
            },
            "scope": {"metric": "利润率", "dimension": "service_line", "filters": {"city": "深圳"}},
            "last_result": {"first_row": {"service_line": "客户成功", "利润率": 0.32}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("那利润率最高的服务线在1月到3月的利润率变化趋势呢？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_profit_margin_time_trend", actions[0]["action_id"])
        self.assertEqual("aggregation", actions[0]["operation"])
        self.assertEqual("month", actions[0]["dimension"])
        self.assertEqual("利润率", actions[0]["parameters"]["metric"])
        self.assertIn("筛选深圳城市、客户成功服务线的数据", actions[0]["question"])
        self.assertIn("按月份展示利润率趋势", actions[0]["question"])

    def test_explicit_entity_time_trend_preserves_named_filter(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "ranking",
            "logic_form": {
                "operation": "ranking",
                "metric": "sales",
                "group_by": "city",
                "parameters": {
                    "table": "service_metrics",
                    "metric": "sales",
                    "dimension": "city",
                    "available_columns": ["month", "city", "service_line", "sales", "profit", "tickets"],
                },
            },
            "scope": {"metric": "sales", "dimension": "city", "filters": {}},
            "last_result": {"first_row": {"city": "上海", "sales": 318}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("成都的销售额在1月到3月之间如何变化？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_to_time_trend", actions[0]["action_id"])
        self.assertEqual("month", actions[0]["dimension"])
        self.assertIn("1月到3月", actions[0]["question"])
        self.assertIn("筛选成都城市的数据", actions[0]["question"])

    def test_profit_margin_breakdown_then_highest_city_returns_compound_actions(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "aggregation",
            "logic_form": {
                "operation": "aggregation",
                "metric": "sales",
                "group_by": "month",
                "parameters": {
                    "table": "service_metrics",
                    "metric": "sales",
                    "dimension": "month",
                    "available_columns": ["month", "city", "service_line", "sales", "profit", "tickets"],
                },
            },
            "scope": {"metric": "sales", "dimension": "month", "filters": {}},
            "last_result": {"first_row": {"month": "2026-02", "sales": 550}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("计算每个城市各月的利润率，并找出利润率最高的城市。", context)

        self.assertEqual(2, len(actions))
        self.assertEqual(["switch_profit_margin_breakdown", "switch_to_profit_margin"], [action["action_id"] for action in actions])
        self.assertEqual(["aggregation", "ranking"], [action["operation"] for action in actions])
        self.assertEqual(["city", "city"], [action["dimension"] for action in actions])
        self.assertIn("按城市汇总利润率", actions[0]["question"])
        self.assertIn("城市利润率最高", actions[1]["question"])

    def test_profit_margin_highest_month_uses_time_dimension_over_candidate_city(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "aggregation",
            "logic_form": {
                "operation": "aggregation",
                "metric": "amount",
                "group_by": "month",
                "filters": {"month": {"year": 2026, "month_range": [1, 3]}},
                "parameters": {
                    "table": "orders",
                    "metric": "amount",
                    "dimension": "month",
                    "candidate_filter": {
                        "dimension": "city",
                        "metric": "amount",
                        "aggregation": "sum",
                        "limit": 5,
                        "sort_order": "desc",
                        "filters": {"month": {"year": 2026, "month": 1}},
                    },
                    "available_columns": ["month", "customer_id", "amount", "profit", "city", "segment"],
                },
            },
            "scope": {"metric": "amount", "dimension": "month", "filters": {"month": {"year": 2026, "month_range": [1, 3]}}},
            "last_result": {"first_row": {"month": "2026-01", "amount": 430}},
            "focus_sets": [
                {
                    "source": "ranking_result",
                    "dimension": "city",
                    "metric": "amount",
                    "limit": 5,
                    "filters": {"month": {"year": 2026, "month": 1}},
                    "values": ["北京", "上海"],
                }
            ],
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("对于金额最高的那个城市，哪个月份的利润率最高？", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("switch_to_profit_margin", actions[0]["action_id"])
        self.assertEqual("ranking", actions[0]["operation"])
        self.assertEqual("month", actions[0]["dimension"])
        self.assertEqual("利润率", actions[0]["parameters"]["metric"])
        self.assertIn("按月份看利润率排名前3", actions[0]["question"])

    def test_topn_entity_count_question_is_left_to_ranking_parser(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "aggregation",
            "logic_form": {
                "operation": "aggregation",
                "metric": "amount",
                "group_by": "city",
                "parameters": {
                    "table": "orders",
                    "metric": "amount",
                    "dimension": "city",
                    "available_columns": ["month", "customer_id", "amount", "profit", "city", "segment"],
                },
            },
            "scope": {"metric": "amount", "dimension": "city", "filters": {}},
            "last_result": {"first_row": {"city": "上海", "amount": 325}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("在这些城市中，按总金额排名前3的城市是哪些？它们的客户数量分别是多少？", context)

        self.assertEqual([], actions)

    def test_quality_followup_is_not_rewritten_to_ranking_action(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "ranking",
            "logic_form": {
                "operation": "ranking",
                "metric": "sales",
                "group_by": "month",
                "parameters": {
                    "table": "service_metrics",
                    "metric": "sales",
                    "dimension": "month",
                    "available_columns": ["month", "city", "service_line", "sales", "profit", "tickets"],
                },
            },
            "scope": {"metric": "sales", "dimension": "month", "filters": {"city": "深圳"}},
            "last_result": {"first_row": {"month": "2026-02", "sales": 302}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("该城市销售额最高的月份是否存在数据质量问题？", context)

        self.assertEqual([], actions)

    def test_self_contained_ranking_after_overview_is_not_rewritten_from_previous_metric(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "dataset_overview",
            "logic_form": {
                "operation": "dataset_overview",
                "metric": "profit",
                "group_by": "month",
                "parameters": {
                    "table": "orders",
                    "metric": "profit",
                    "dimension": "month",
                    "available_columns": ["month", "customer_id", "amount", "profit", "city", "segment"],
                },
            },
            "scope": {"metric": "profit", "dimension": "month", "filters": {}},
            "last_result": {"first_row": {"month": "2026-01", "profit": 124}},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("基于上一步的概况，哪个城市的客户贡献的订单总金额最高？", context)

        self.assertEqual([], actions)

    def test_retail_dimension_switch_still_uses_retail_action_contract(self) -> None:
        context = {
            "state_name": "analysis_ready",
            "operation": "retail_distribution_topn_chart",
            "logic_form": {
                "operation": "retail_distribution_topn_chart",
                "parameters": {
                    "start_ym": 202604,
                    "end_ym": 202605,
                    "metric": "sign_amt",
                    "dimension": "cust_name",
                    "available_columns": ["sign_time", "sign_amt", "cust_name", "sku_name"],
                },
            },
            "scope": {"metric": "sign_amt", "dimension": "cust_name"},
            "available_followup_actions": [],
        }

        actions = plan_followup_actions("按产品也看一下", context)

        self.assertEqual(1, len(actions))
        self.assertEqual("retail_distribution_topn_chart", actions[0]["operation"])
        self.assertEqual("sku_name", actions[0]["dimension"])
        self.assertIn("2026年4月至2026年5月", actions[0]["question"])


if __name__ == "__main__":
    unittest.main()
