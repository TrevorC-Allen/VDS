"""Generic capability-family tests for non-hardcoded analysis operations."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from data_agent_core.contracts.analysis_contracts import AnalysisPlan, LogicForm
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.dabstep_fee_engine import DabstepFeeEngine
from data_agent_core.core.intent_parser import parse_generic_table_question, parse_question
from data_agent_core.executors import pandas_executor, sql_executor
from data_agent_core.output.response_builder import build_response, format_answer
from data_agent_core.verifier.rule_checker import verify_execution


class GenericCapabilityOperationsTest(unittest.TestCase):
    def test_field_values_are_read_from_data_column(self) -> None:
        payments = pd.DataFrame({"aci": ["C", "A", "B", "A"]})
        logic = parse_question("What are the possible values for the field aci?")
        result = pandas_executor.execute_plan(build_analysis_plan(logic), {"payments": payments})

        self.assertTrue(result.success)
        self.assertEqual(["A", "B", "C"], result.value)
        self.assertEqual("A, B, C", format_answer(result.value, logic.output_format))

    def test_boolean_percentage_counts_matching_rows(self) -> None:
        payments = pd.DataFrame(
            {
                "year": [2023, 2023, 2023, 2024],
                "is_credit": [True, False, True, False],
            }
        )
        logic = parse_question("What percentage of the transactions in 2023 use credit cards?")
        plan = build_analysis_plan(logic)
        pandas_result = pandas_executor.execute_plan(plan, {"payments": payments})
        sql_result = sql_executor.execute_plan(plan, {"payments": payments})

        self.assertTrue(pandas_result.success)
        self.assertTrue(sql_result.success)
        self.assertAlmostEqual(66.666666, float(pandas_result.value), places=5)
        self.assertAlmostEqual(float(pandas_result.value), float(sql_result.value), places=5)

    def test_numeric_range_filters_are_shared_by_pandas_and_sql(self) -> None:
        payments = pd.DataFrame(
            {
                "day_of_year": [181, 182, 220, 273, 274],
                "eur_amount": [10.0, 20.0, 30.0, 40.0, 50.0],
            }
        )
        logic = LogicForm(
            task_type="aggregation",
            operation="row_count",
            filters={"day_of_year": {"min": 182, "max": 273}},
            parameters={"table": "payments"},
            output_format={"answer_type": "number"},
        )
        plan = build_analysis_plan(logic)
        pandas_result = pandas_executor.execute_plan(plan, {"payments": payments})
        sql_result = sql_executor.execute_plan(plan, {"payments": payments})

        self.assertTrue(pandas_result.success, pandas_result.errors)
        self.assertTrue(sql_result.success, sql_result.errors)
        self.assertEqual(3, pandas_result.value)
        self.assertEqual(pandas_result.value, sql_result.value)

    def test_duplicate_check_reports_yes_without_exposing_rows(self) -> None:
        table = pd.DataFrame(
            [
                {"transaction_id": "a", "amount": 10},
                {"transaction_id": "a", "amount": 10},
                {"transaction_id": "b", "amount": 20},
            ]
        )
        logic = parse_generic_table_question("Are there duplicate rows in this table?", {"transactions": table})
        result = pandas_executor.execute_plan(build_analysis_plan(logic), {"tables": {"transactions": table}})

        self.assertTrue(result.success)
        self.assertEqual("yes", result.value["answer"])
        self.assertEqual(2, result.value["duplicate_row_count"])

    def test_null_check_counts_missing_values_in_pandas_and_sql(self) -> None:
        table = pd.DataFrame(
            [
                {"customer": "A", "amount": 10.0},
                {"customer": "", "amount": 20.0},
                {"customer": None, "amount": 30.0},
            ]
        )
        logic = parse_generic_table_question("How many missing customer values are in this table?", {"payments": table})
        plan = build_analysis_plan(logic)
        pandas_result = pandas_executor.execute_plan(plan, {"tables": {"payments": table}})
        sql_result = sql_executor.execute_plan(plan, {"tables": {"payments": table}})

        self.assertEqual("null_check", logic.operation)
        self.assertTrue(pandas_result.success, pandas_result.errors)
        self.assertTrue(sql_result.success, sql_result.errors)
        self.assertEqual(2, pandas_result.value)
        self.assertEqual(pandas_result.value, sql_result.value)

    def test_present_percentage_and_schema_field_lookup_are_generic(self) -> None:
        payments = pd.DataFrame(
            {
                "email_address": ["a@example.com", None, "", "b@example.com"],
                "has_fraudulent_dispute": [False, True, False, False],
            }
        )
        present_logic = parse_question("What percentage of transactions have an associated email address?")
        present_plan = build_analysis_plan(present_logic)
        pandas_present = pandas_executor.execute_plan(present_plan, {"payments": payments})
        sql_present = sql_executor.execute_plan(present_plan, {"payments": payments})

        self.assertEqual("null_check", present_logic.operation)
        self.assertEqual("present_rate", present_logic.parameters["mode"])
        self.assertTrue(pandas_present.success, pandas_present.errors)
        self.assertTrue(sql_present.success, sql_present.errors)
        self.assertEqual("50.00%", format_answer(pandas_present.value, present_logic.output_format))
        self.assertEqual(pandas_present.value, sql_present.value)

        field_logic = parse_question("What is the name of the column that indicates fraud?", context={"payments": payments})
        field_result = pandas_executor.execute_plan(build_analysis_plan(field_logic), {"payments": payments})

        self.assertEqual("schema_field_lookup", field_logic.operation)
        self.assertTrue(field_result.success, field_result.errors)
        self.assertEqual("has_fraudulent_dispute", field_result.value)

    def test_basic_profile_questions_cover_average_top_missing_and_repeats(self) -> None:
        payments = pd.DataFrame(
            {
                "eur_amount": [10.0, 20.0, 30.0, 40.0],
                "day_of_year": [2, 2, 3, 4],
                "card_scheme": ["NexPay", "GlobalCard", "NexPay", "NexPay"],
                "email_address": ["a@example.com", "a@example.com", None, "b@example.com"],
                "ip_address": ["1.1.1.1", None, None, None],
            }
        )

        avg_logic = parse_question("What is the average transaction amount (in EUR)?")
        avg_plan = build_analysis_plan(avg_logic)
        avg_pandas = pandas_executor.execute_plan(avg_plan, {"payments": payments})
        avg_sql = sql_executor.execute_plan(avg_plan, {"payments": payments})
        self.assertEqual("aggregation", avg_logic.operation)
        self.assertAlmostEqual(25.0, float(avg_pandas.value))
        self.assertAlmostEqual(float(avg_pandas.value), float(avg_sql.value))

        top_day_logic = parse_question("On which day of the year are the most transactions recorded?")
        top_day_plan = build_analysis_plan(top_day_logic)
        self.assertEqual("top_count", top_day_logic.operation)
        self.assertEqual("2", pandas_executor.execute_plan(top_day_plan, {"payments": payments}).value)
        self.assertEqual("2", sql_executor.execute_plan(top_day_plan, {"payments": payments}).value)

        missing_logic = parse_question("Which column has the most missing data in the payments dataset?")
        missing_plan = build_analysis_plan(missing_logic)
        self.assertEqual("null_check", missing_logic.operation)
        self.assertEqual("ip_address", pandas_executor.execute_plan(missing_plan, {"payments": payments}).value)
        self.assertEqual("ip_address", sql_executor.execute_plan(missing_plan, {"payments": payments}).value)

        count_logic = parse_question("How many transactions were made using NexPay cards?")
        count_plan = build_analysis_plan(count_logic)
        self.assertEqual("row_count", count_logic.operation)
        self.assertEqual({"card_scheme": "NexPay"}, count_logic.filters)
        self.assertEqual(3, pandas_executor.execute_plan(count_plan, {"payments": payments}).value)
        self.assertEqual(3, sql_executor.execute_plan(count_plan, {"payments": payments}).value)

        repeat_logic = parse_question("How many shoppers have made more than one transaction based on email addresses?")
        repeat_plan = build_analysis_plan(repeat_logic)
        self.assertEqual("repeat_entity_count", repeat_logic.operation)
        self.assertEqual(1, pandas_executor.execute_plan(repeat_plan, {"payments": payments}).value)
        self.assertEqual(1, sql_executor.execute_plan(repeat_plan, {"payments": payments}).value)

        threshold_logic = parse_question("Are there any merchants under the excessive fraud threshold?")
        self.assertEqual("not_applicable", threshold_logic.operation)
        self.assertEqual("true_unsupported", threshold_logic.output_format["not_applicable_type"])

    def test_chinese_null_check_detects_exists_mode(self) -> None:
        table = pd.DataFrame([{"客户": "A"}, {"客户": ""}])
        logic = parse_generic_table_question("客户字段有没有空值？", {"sales": table})
        result = pandas_executor.execute_plan(build_analysis_plan(logic), {"tables": {"sales": table}})

        self.assertEqual("null_check", logic.operation)
        self.assertEqual("exists", logic.parameters["mode"])
        self.assertEqual("yes", result.value["answer"])

    def test_fraudulent_subset_top_count_uses_filtered_dimension(self) -> None:
        payments = pd.DataFrame(
            {
                "device_type": ["Mobile", "Desktop", "Mobile", "Tablet"],
                "has_fraudulent_dispute": [True, True, True, False],
            }
        )
        logic = parse_question("Which device type is most commonly used in fraudulent transactions?")
        result = pandas_executor.execute_plan(build_analysis_plan(logic), {"payments": payments})

        self.assertTrue(result.success)
        self.assertEqual("Mobile", result.value)

    def test_filtered_fraud_rate_uses_fraudulent_volume_percentage(self) -> None:
        payments = pd.DataFrame(
            {
                "year": [2023, 2023, 2023, 2023],
                "shopper_interaction": ["POS", "POS", "Ecommerce", "POS"],
                "eur_amount": [20.0, 80.0, 100.0, 100.0],
                "has_fraudulent_dispute": [True, False, True, False],
            }
        )
        logic = parse_question("What is the fraud rate for in-person transactions for year 2023?")
        plan = build_analysis_plan(logic)
        pandas_result = pandas_executor.execute_plan(plan, {"payments": payments})
        sql_result = sql_executor.execute_plan(plan, {"payments": payments})

        self.assertTrue(pandas_result.success)
        self.assertTrue(sql_result.success)
        self.assertAlmostEqual(10.0, float(pandas_result.value))
        self.assertAlmostEqual(float(pandas_result.value), float(sql_result.value))

    def test_fraudulent_percentage_wording_routes_to_fraud_rate(self) -> None:
        payments = pd.DataFrame(
            {
                "year": [2023, 2023, 2023, 2024],
                "eur_amount": [100.0, 300.0, 100.0, 999.0],
                "has_fraudulent_dispute": [True, False, False, True],
            }
        )
        logic = parse_question("What percentage of transactions are fraudulent in year 2023?")
        plan = build_analysis_plan(logic)
        pandas_result = pandas_executor.execute_plan(plan, {"payments": payments})
        sql_result = sql_executor.execute_plan(plan, {"payments": payments})

        self.assertEqual("boolean_percentage", logic.operation)
        self.assertTrue(pandas_result.success, pandas_result.errors)
        self.assertTrue(sql_result.success, sql_result.errors)
        self.assertAlmostEqual(33.333333, float(pandas_result.value), places=5)
        self.assertAlmostEqual(float(pandas_result.value), float(sql_result.value))

    def test_aci_fee_extreme_uses_fee_rules_and_tie_breaks_alphabetically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "fees.json").write_text(
                json.dumps(
                    [
                        _fee_rule(1, "GlobalCard", [], fixed_amount=0.10, rate=0),
                        _fee_rule(2, "GlobalCard", ["A"], fixed_amount=0.00, rate=100),
                        _fee_rule(3, "GlobalCard", ["B"], fixed_amount=0.30, rate=0),
                        _fee_rule(4, "GlobalCard", ["C"], fixed_amount=0.30, rate=0),
                    ]
                )
            )
            (root / "merchant_data.json").write_text(
                json.dumps([{"merchant": "SyntheticMerchant", "account_type": "A", "capture_delay": "manual", "merchant_category_code": 5411}])
            )
            (root / "merchant_category_codes.csv").write_text("mcc,description\n5411,Grocery Stores\n")
            (root / "payments.csv").write_text(
                "merchant,year,day_of_year,hour_of_day,minute_of_hour,eur_amount,is_credit,has_fraudulent_dispute,is_refused_by_adyen,aci,card_scheme,issuing_country,acquirer_country\n"
                "SyntheticMerchant,2023,1,0,0,10.0,true,false,false,A,GlobalCard,NL,NL\n"
            )

            engine = DabstepFeeEngine(root)
            aci, fee, candidates = engine.aci_fee_extreme_for_transaction_value(
                transaction_value=10.0,
                card_scheme="GlobalCard",
                is_credit=True,
                objective="maximum",
            )

        self.assertEqual("B", aci)
        self.assertAlmostEqual(0.40, fee)
        self.assertEqual(["B", "C"], [key for key, value in candidates.items() if value["fee"] == fee])

    def test_aci_fee_extreme_parser_accepts_transaction_of_euros_wording(self) -> None:
        logic = parse_question(
            "For a credit transaction of 10 euros on GlobalCard, what would be the most expensive Authorization Characteristics Indicator (ACI)?"
        )

        self.assertEqual("aci_fee_extreme", logic.operation)
        self.assertEqual("GlobalCard", logic.filters["card_scheme"])
        self.assertTrue(logic.filters["is_credit"])
        self.assertEqual(10.0, logic.parameters["transaction_value"])

    def test_fee_affected_merchants_parser_uses_fee_id_without_account_type_change(self) -> None:
        logic = parse_question("In 2023, which merchants were affected by the Fee with ID 17?")

        self.assertEqual("fee_restriction_affected_merchants", logic.operation)
        self.assertEqual(17, logic.parameters["fee_id"])
        self.assertIsNone(logic.filters["new_account_type"])

    def test_fee_affected_merchants_engine_uses_rule_constraints_without_monthly_rescan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fee_rule = _fee_rule(10, "GlobalCard", [], fixed_amount=0.10, rate=0)
            fee_rule["account_type"] = ["A", "B"]
            fee_rule["is_credit"] = None
            (root / "fees.json").write_text(json.dumps([fee_rule]))
            (root / "merchant_data.json").write_text(
                json.dumps(
                    [
                        {"merchant": "MerchantA", "account_type": "A", "capture_delay": "manual", "merchant_category_code": 5411},
                        {"merchant": "MerchantB", "account_type": "B", "capture_delay": "manual", "merchant_category_code": 5411},
                        {"merchant": "MerchantO", "account_type": "O", "capture_delay": "manual", "merchant_category_code": 5411},
                    ]
                )
            )
            (root / "merchant_category_codes.csv").write_text("mcc,description\n5411,Grocery Stores\n")
            (root / "payments.csv").write_text(
                "merchant,year,day_of_year,hour_of_day,minute_of_hour,eur_amount,is_credit,has_fraudulent_dispute,is_refused_by_adyen,aci,card_scheme,issuing_country,acquirer_country\n"
                "MerchantA,2023,1,0,0,10.0,true,false,false,A,GlobalCard,NL,NL\n"
                "MerchantB,2023,1,0,0,10.0,false,false,false,B,GlobalCard,NL,NL\n"
                "MerchantO,2023,1,0,0,10.0,true,false,false,A,GlobalCard,NL,NL\n"
            )

            engine = DabstepFeeEngine(root)

            self.assertEqual(["MerchantA", "MerchantB"], engine.fee_restriction_affected_merchants(fee_id=10, year=2023))
            self.assertEqual(["MerchantA"], engine.fee_restriction_affected_merchants(fee_id=10, new_account_type="B", year=2023))

    def test_row_and_distinct_count_work_for_english_and_chinese_questions(self) -> None:
        table = pd.DataFrame(
            [
                {"城市": "上海", "客户": "C1", "销售额": 100},
                {"城市": "北京", "客户": "C2", "销售额": 200},
                {"城市": "上海", "客户": "C1", "销售额": 300},
            ]
        )
        row_logic = parse_generic_table_question("这张表总行数是多少？", {"sales": table})
        distinct_logic = parse_generic_table_question("How many unique customers are in the table?", {"sales": table})

        self.assertEqual("row_count", row_logic.operation)
        self.assertEqual("distinct_count", distinct_logic.operation)
        self.assertEqual(3, pandas_executor.execute_plan(build_analysis_plan(row_logic), {"tables": {"sales": table}}).value)
        self.assertEqual(2, pandas_executor.execute_plan(build_analysis_plan(distinct_logic), {"tables": {"sales": table}}).value)

    def test_repeat_outlier_top_share_and_filtered_ranking_are_generic(self) -> None:
        table = pd.DataFrame(
            [
                {"merchant": "A", "region": "East", "email": "u1", "amount": 100.0},
                {"merchant": "A", "region": "East", "email": "u1", "amount": 150.0},
                {"merchant": "B", "region": "East", "email": "u2", "amount": 50.0},
                {"merchant": "C", "region": "West", "email": "u3", "amount": 1000.0},
            ]
        )
        repeat_logic = parse_generic_table_question("What percentage of repeat customers are in this table?", {"payments": table})
        outlier_logic = parse_generic_table_question("How many amount outliers are there by IQR?", {"payments": table})
        share_logic = parse_generic_table_question("What share do the top 2 merchants by amount represent?", {"payments": table})
        ranking_logic = parse_generic_table_question("In East, which merchant has the highest amount?", {"payments": table})

        self.assertEqual("repeat_entity_percentage", repeat_logic.operation)
        self.assertEqual("outlier_count", outlier_logic.operation)
        self.assertEqual("top_k_share", share_logic.operation)
        self.assertEqual("filtered_metric_ranking", ranking_logic.operation)
        repeat = pandas_executor.execute_plan(build_analysis_plan(repeat_logic), {"tables": {"payments": table}})
        outliers = pandas_executor.execute_plan(build_analysis_plan(outlier_logic), {"tables": {"payments": table}})
        share = pandas_executor.execute_plan(build_analysis_plan(share_logic), {"tables": {"payments": table}})
        ranking = pandas_executor.execute_plan(build_analysis_plan(ranking_logic), {"tables": {"payments": table}})

        self.assertTrue(repeat.success)
        self.assertAlmostEqual(33.333333, float(repeat.value), places=5)
        self.assertEqual(1, outliers.value)
        self.assertAlmostEqual((1250.0 / 1300.0) * 100, float(share.value), places=5)
        self.assertEqual([{"merchant": "A", "amount": 250.0}], ranking.value)

    def test_hour_of_day_top_count_and_outlier_group_are_generic(self) -> None:
        payments = pd.DataFrame(
            [{"hour_of_day": 1, "eur_amount": 10.0} for _ in range(15)]
            + [{"hour_of_day": 2, "eur_amount": 12.0} for _ in range(8)]
            + [{"hour_of_day": 5, "eur_amount": 1000.0}]
        )
        count_logic = parse_question("During which hour of the day do the most transactions occur?", context={"payments": payments})
        outlier_logic = parse_question(
            "During which hour of the day do the most outlier transactions occur (using Z-Score > 3)?",
            context={"payments": payments},
        )

        self.assertEqual("top_count", count_logic.operation)
        self.assertEqual("top_outlier_group", outlier_logic.operation)
        count = pandas_executor.execute_plan(build_analysis_plan(count_logic), {"payments": payments})
        outlier = pandas_executor.execute_plan(build_analysis_plan(outlier_logic), {"payments": payments})

        self.assertTrue(count.success)
        self.assertTrue(outlier.success)
        self.assertEqual("1", format_answer(count.value, count_logic.output_format))
        self.assertEqual("5", format_answer(outlier.value, outlier_logic.output_format))

    def test_common_value_unique_set_and_average_per_unique_entity_are_generic(self) -> None:
        payments = pd.DataFrame(
            [
                {"merchant": "A", "shopper_interaction": "POS", "email_address": "u1", "eur_amount": 10.0},
                {"merchant": "B", "shopper_interaction": "POS", "email_address": "u1", "eur_amount": 20.0},
                {"merchant": "A", "shopper_interaction": "Ecommerce", "email_address": "u2", "eur_amount": 30.0},
            ]
        )
        common_logic = parse_question("What is the most common shopper interaction type?", context={"payments": payments})
        set_logic = parse_question("What is the unique set of merchants in the dataset?", context={"payments": payments})
        per_unique_logic = parse_question("What is the average transaction amount per unique email?", context={"payments": payments})
        count_per_unique_logic = parse_question(
            "What is the average number of transactions per unique shopper based on email addresses?",
            context={"payments": payments},
        )

        common = pandas_executor.execute_plan(build_analysis_plan(common_logic), {"payments": payments})
        values = pandas_executor.execute_plan(build_analysis_plan(set_logic), {"payments": payments})
        per_unique_pandas = pandas_executor.execute_plan(build_analysis_plan(per_unique_logic), {"payments": payments})
        per_unique_sql = sql_executor.execute_plan(build_analysis_plan(per_unique_logic), {"payments": payments})
        count_per_unique_pandas = pandas_executor.execute_plan(build_analysis_plan(count_per_unique_logic), {"payments": payments})
        count_per_unique_sql = sql_executor.execute_plan(build_analysis_plan(count_per_unique_logic), {"payments": payments})

        self.assertEqual("top_count", common_logic.operation)
        self.assertEqual("field_values", set_logic.operation)
        self.assertEqual("metric_per_distinct_entity", per_unique_logic.operation)
        self.assertEqual("metric_per_distinct_entity", count_per_unique_logic.operation)
        self.assertEqual("__row_count__", count_per_unique_logic.parameters["metric"])
        self.assertEqual("count", count_per_unique_logic.parameters["aggregation"])
        self.assertTrue(common.success, common.errors)
        self.assertTrue(values.success, values.errors)
        self.assertTrue(per_unique_pandas.success, per_unique_pandas.errors)
        self.assertTrue(per_unique_sql.success, per_unique_sql.errors)
        self.assertTrue(count_per_unique_pandas.success, count_per_unique_pandas.errors)
        self.assertTrue(count_per_unique_sql.success, count_per_unique_sql.errors)
        self.assertEqual("POS", common.value)
        self.assertEqual(["A", "B"], values.value)
        self.assertAlmostEqual(22.5, float(per_unique_pandas.value))
        self.assertAlmostEqual(float(per_unique_pandas.value), float(per_unique_sql.value))
        self.assertAlmostEqual(1.5, float(count_per_unique_pandas.value))
        self.assertAlmostEqual(float(count_per_unique_pandas.value), float(count_per_unique_sql.value))

    def test_boolean_ratio_device_count_ip_distinct_and_missing_columns_are_generic(self) -> None:
        payments = pd.DataFrame(
            [
                {"is_credit": True, "device_type": "iOS", "ip_address": "", "email_address": "u1"},
                {"is_credit": True, "device_type": "Android", "ip_address": "ip2", "email_address": ""},
                {"is_credit": False, "device_type": "iOS", "ip_address": "ip2", "email_address": "u3"},
            ]
        )
        ratio_logic = parse_question("What is the ratio of credit card transactions to debit card transactions?", context={"payments": payments})
        device_logic = parse_question("How many transactions were conducted on iOS devices?", context={"payments": payments})
        ip_logic = parse_question("How many unique IP addresses are present in the payments dataset?", context={"payments": payments})
        missing_logic = parse_question(
            "Which columns in the payments dataset contain missing data? A. ip_address, B. email_address, C. both ip_address and email_address, D. neither",
            context={"payments": payments},
        )

        ratio = pandas_executor.execute_plan(build_analysis_plan(ratio_logic), {"payments": payments})
        ratio_sql = sql_executor.execute_plan(build_analysis_plan(ratio_logic), {"payments": payments})
        device_count = pandas_executor.execute_plan(build_analysis_plan(device_logic), {"payments": payments})
        ip_count = pandas_executor.execute_plan(build_analysis_plan(ip_logic), {"payments": payments})
        missing = pandas_executor.execute_plan(build_analysis_plan(missing_logic), {"payments": payments})

        self.assertEqual("boolean_count_ratio", ratio_logic.operation)
        self.assertEqual("row_count", device_logic.operation)
        self.assertEqual("distinct_count", ip_logic.operation)
        self.assertEqual("missing_columns_choice", missing_logic.operation)
        self.assertAlmostEqual(2.0, float(ratio.value))
        self.assertAlmostEqual(float(ratio.value), float(ratio_sql.value))
        self.assertEqual(2, device_count.value)
        self.assertEqual(2, ip_count.value)
        self.assertEqual("C. both ip_address and email_address", missing.value)

    def test_sql_matches_generic_count_share_and_filtered_ranking(self) -> None:
        table = pd.DataFrame(
            [
                {"merchant": "A", "region": "East", "email": "u1", "amount": 100.0},
                {"merchant": "A", "region": "East", "email": "u1", "amount": 150.0},
                {"merchant": "B", "region": "East", "email": "u2", "amount": 50.0},
                {"merchant": "C", "region": "West", "email": "u3", "amount": 1000.0},
            ]
        )
        for question in (
            "How many unique customers are in the table?",
            "What percentage of repeat customers are in this table?",
            "What share do the top 2 merchants by amount represent?",
            "In East, which merchant has the highest amount?",
        ):
            logic = parse_generic_table_question(question, {"payments": table})
            plan = build_analysis_plan(logic)
            pandas_result = pandas_executor.execute_plan(plan, {"tables": {"payments": table}})
            sql_result = sql_executor.execute_plan(plan, {"tables": {"payments": table}})
            self.assertTrue(pandas_result.success, question)
            self.assertTrue(sql_result.success, sql_result.errors)
            self.assertEqual(pandas_result.value, sql_result.value)

    def test_uploaded_table_filter_dimension_count_and_mode_generalize_in_chinese(self) -> None:
        table = pd.DataFrame(
            [
                {"区域": "华北", "城市": "北京", "产品类别": "饮料", "销售额": 100.0},
                {"区域": "华北", "城市": "天津", "产品类别": "零食", "销售额": 200.0},
                {"区域": "华东", "城市": "上海", "产品类别": "饮料", "销售额": 500.0},
            ]
        )

        filtered_logic = parse_generic_table_question("区域为华北时，哪个城市销售额最高？", {"sales": table})
        grouped_count_logic = parse_generic_table_question("按区域统计记录数", {"sales": table})
        mode_logic = parse_generic_table_question("产品类别的众数是什么？", {"sales": table})

        self.assertEqual("filtered_metric_ranking", filtered_logic.operation)
        self.assertEqual({"区域": "华北"}, filtered_logic.filters)
        self.assertEqual("城市", filtered_logic.parameters["dimension"])
        self.assertEqual("销售额", filtered_logic.parameters["metric"])
        self.assertEqual("aggregation", grouped_count_logic.operation)
        self.assertEqual("count", grouped_count_logic.parameters["aggregation"])
        self.assertIsNone(grouped_count_logic.parameters["metric"])
        self.assertEqual("区域", grouped_count_logic.parameters["dimension"])
        self.assertEqual("top_count", mode_logic.operation)
        self.assertEqual("产品类别", mode_logic.parameters["group_by"])

        for logic in (filtered_logic, grouped_count_logic, mode_logic):
            plan = build_analysis_plan(logic)
            pandas_result = pandas_executor.execute_plan(plan, {"tables": {"sales": table}})
            sql_result = sql_executor.execute_plan(plan, {"tables": {"sales": table}})
            self.assertTrue(pandas_result.success, pandas_result.errors)
            self.assertTrue(sql_result.success, sql_result.errors)
            self.assertEqual(pandas_result.value, sql_result.value)

        self.assertEqual([{"城市": "天津", "销售额": 200.0}], pandas_executor.execute_plan(build_analysis_plan(filtered_logic), {"tables": {"sales": table}}).value)
        self.assertEqual("饮料", pandas_executor.execute_plan(build_analysis_plan(mode_logic), {"tables": {"sales": table}}).value)

    def test_uploaded_table_top_k_share_distinguishes_metric_share_from_count_share(self) -> None:
        table = pd.DataFrame(
            [
                {"城市": "北京", "销售额": 300.0},
                {"城市": "上海", "销售额": 200.0},
                {"城市": "上海", "销售额": 50.0},
                {"城市": "天津", "销售额": 100.0},
                {"城市": "广州", "销售额": 10.0},
            ]
        )
        metric_share_logic = parse_generic_table_question("前2个城市销售额占比是多少？", {"sales": table})
        count_share_logic = parse_generic_table_question("前2个城市记录数占比是多少？", {"sales": table})

        self.assertEqual("top_k_share", metric_share_logic.operation)
        self.assertEqual("sum", metric_share_logic.parameters["aggregation"])
        self.assertEqual("销售额", metric_share_logic.parameters["metric"])
        self.assertEqual("top_k_share", count_share_logic.operation)
        self.assertEqual("count", count_share_logic.parameters["aggregation"])
        self.assertIsNone(count_share_logic.parameters["metric"])

        metric_share = pandas_executor.execute_plan(build_analysis_plan(metric_share_logic), {"tables": {"sales": table}})
        count_share = pandas_executor.execute_plan(build_analysis_plan(count_share_logic), {"tables": {"sales": table}})
        metric_share_sql = sql_executor.execute_plan(build_analysis_plan(metric_share_logic), {"tables": {"sales": table}})
        count_share_sql = sql_executor.execute_plan(build_analysis_plan(count_share_logic), {"tables": {"sales": table}})

        self.assertTrue(metric_share.success, metric_share.errors)
        self.assertTrue(count_share.success, count_share.errors)
        self.assertAlmostEqual(((300.0 + 250.0) / 660.0) * 100, float(metric_share.value), places=5)
        self.assertAlmostEqual(60.0, float(count_share.value), places=5)
        self.assertAlmostEqual(float(metric_share.value), float(metric_share_sql.value), places=5)
        self.assertAlmostEqual(float(count_share.value), float(count_share_sql.value), places=5)

    def test_not_applicable_distinguishes_capability_gap_from_true_unsupported(self) -> None:
        capability_gap = parse_question("Can you answer a currently unsupported but data-answerable pattern?")
        gap_result = pandas_executor.execute_plan(build_analysis_plan(capability_gap), {"payments": pd.DataFrame({"merchant": ["A"]})})
        gap_response = build_response(
            run_id="run_gap",
            user_question=_user_question("ds_gap", "unsupported data-answerable pattern"),
            plan=build_analysis_plan(capability_gap),
            execution_result=gap_result,
            verification=verify_execution(gap_result),
        )

        true_unsupported = parse_question("What is the danger fine threshold?")
        unsupported_result = pandas_executor.execute_plan(build_analysis_plan(true_unsupported), {"payments": pd.DataFrame({"merchant": ["A"]})})
        unsupported_response = build_response(
            run_id="run_true_unsupported",
            user_question=_user_question("ds_true", "danger fine threshold"),
            plan=build_analysis_plan(true_unsupported),
            execution_result=unsupported_result,
            verification=verify_execution(unsupported_result),
        )

        self.assertFalse(gap_response.success)
        self.assertEqual("capability_gap", gap_response.debug["not_applicable_attribution"]["category"])
        self.assertEqual("true_unsupported", unsupported_response.debug["not_applicable_attribution"]["category"])
        self.assertTrue(unsupported_response.success)

    def test_fraud_likelihood_credit_debit_uses_transaction_rate(self) -> None:
        payments = pd.DataFrame(
            {
                "year": [2023, 2023, 2023, 2023],
                "is_credit": [True, True, False, False],
                "has_fraudulent_dispute": [True, False, False, False],
            }
        )
        logic = parse_question("Are credit payments more likely to result in a fraudulent dispute compared to debit card payments?")
        result = pandas_executor.execute_plan(build_analysis_plan(logic), {"payments": payments})

        self.assertEqual("fraud_rate_comparison", logic.operation)
        self.assertEqual("fraud_transaction_rate", logic.metric)
        self.assertTrue(result.success)
        self.assertEqual("yes", result.value)

    def test_fraud_likelihood_ranks_by_generic_dimension_with_filters(self) -> None:
        payments = pd.DataFrame(
            {
                "year": [2023, 2023, 2023, 2023, 2023],
                "day_of_year": [20, 40, 45, 80, 100],
                "card_scheme": ["GlobalCard", "GlobalCard", "NexPay", "NexPay", "NexPay"],
                "shopper_interaction": ["Ecommerce", "Ecommerce", "Ecommerce", "POS", "POS"],
                "has_fraudulent_dispute": [True, False, True, False, False],
                "eur_amount": [10.0, 20.0, 30.0, 40.0, 50.0],
            }
        )
        logic = parse_question("Which card scheme has the highest fraud likelihood for Ecommerce transactions in Q1 2023?")
        plan = build_analysis_plan(logic)
        pandas_result = pandas_executor.execute_plan(plan, {"payments": payments})
        sql_result = sql_executor.execute_plan(plan, {"payments": payments})

        self.assertEqual("rank_by_metric", logic.operation)
        self.assertEqual("fraud_transaction_rate", logic.metric)
        self.assertEqual({"year": 2023, "month_range": (1, 3)}, {k: v for k, v in logic.filters.items() if k in {"year", "month_range"}})
        self.assertTrue(pandas_result.success, pandas_result.errors)
        self.assertTrue(sql_result.success, sql_result.errors)
        self.assertEqual("NexPay", pandas_result.value["answer"])
        self.assertEqual(pandas_result.value, sql_result.value)

    def test_dabstep_filtered_metric_ranking_parses_last_quarter_filters(self) -> None:
        payments = pd.DataFrame(
            [
                {"merchant": "Crossfit_Hanna", "card_scheme": "NexPay", "year": 2023, "day_of_year": 280, "ip_country": "NL", "eur_amount": 100.0},
                {"merchant": "Crossfit_Hanna", "card_scheme": "NexPay", "year": 2023, "day_of_year": 300, "ip_country": "BE", "eur_amount": 300.0},
                {"merchant": "Crossfit_Hanna", "card_scheme": "Other", "year": 2023, "day_of_year": 300, "ip_country": "FR", "eur_amount": 900.0},
            ]
        )
        context = {"payments": payments, "merchant_data": [{"merchant": "Crossfit_Hanna"}]}
        logic = parse_question(
            "What are the top 1 countries (ip_country) by avg transaction value for Crossfit_Hanna's NexPay transactions in the last quarter of 2023?",
            context=context,
        )
        plan = build_analysis_plan(logic)
        pandas_result = pandas_executor.execute_plan(plan, context)
        sql_result = sql_executor.execute_plan(plan, context)

        self.assertEqual("filtered_metric_ranking", logic.operation)
        self.assertEqual({"merchant": "Crossfit_Hanna", "card_scheme": "NexPay", "year": 2023, "month_range": (10, 12)}, logic.filters)
        self.assertTrue(pandas_result.success, pandas_result.errors)
        self.assertTrue(sql_result.success, sql_result.errors)
        self.assertEqual([{"ip_country": "BE", "eur_amount": 300.0}], pandas_result.value)
        self.assertEqual(pandas_result.value, sql_result.value)

    def test_country_associated_with_highest_total_amount_uses_country_dimension(self) -> None:
        payments = pd.DataFrame(
            [
                {"issuing_country": "NL", "eur_amount": 100.0, "psp_reference": "p1", "year": 2023},
                {"issuing_country": "BE", "eur_amount": 350.0, "psp_reference": "p2", "year": 2023},
                {"issuing_country": "NL", "eur_amount": 50.0, "psp_reference": "p3", "year": 2023},
            ]
        )
        logic = parse_question("Which country is associated with the highest transaction amount in total?", context={"payments": payments})
        plan = build_analysis_plan(logic)
        pandas_result = pandas_executor.execute_plan(plan, {"payments": payments})
        sql_result = sql_executor.execute_plan(plan, {"payments": payments})

        self.assertEqual("filtered_metric_ranking", logic.operation)
        self.assertEqual("issuing_country", logic.parameters["dimension"])
        self.assertTrue(pandas_result.success, pandas_result.errors)
        self.assertTrue(sql_result.success, sql_result.errors)
        self.assertEqual([{"issuing_country": "BE", "eur_amount": 350.0}], pandas_result.value)
        self.assertEqual(pandas_result.value, sql_result.value)

    def test_quarter_parser_supports_named_and_chinese_quarters(self) -> None:
        self.assertEqual((1, 3), parse_question("Which card scheme has highest fraud likelihood in first quarter of 2023?").filters["month_range"])
        self.assertEqual((7, 9), parse_question("Which card scheme has highest fraud likelihood in Q3 2023?").filters["month_range"])
        self.assertEqual((4, 6), parse_question("Which card scheme has highest fraud likelihood in 2023年第二季度?").filters["month_range"])

    def test_card_scheme_fee_extreme_accepts_most_expensive_wording(self) -> None:
        logic = parse_question("In the average scenario, which card scheme would provide the most expensive fee for a transaction value of 4321 EUR?")

        self.assertEqual("cheapest_card_scheme_for_transaction", logic.operation)
        self.assertEqual("maximum", logic.parameters["objective"])

    def test_card_scheme_fee_extreme_returns_candidate_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "fees.json").write_text(
                json.dumps(
                    [
                        _fee_rule(1, "GlobalCard", [], fixed_amount=0.10, rate=0),
                        _fee_rule(2, "NexPay", [], fixed_amount=0.20, rate=0),
                    ]
                )
            )
            (root / "merchant_data.json").write_text(
                json.dumps([{"merchant": "SyntheticMerchant", "account_type": "A", "capture_delay": "manual", "merchant_category_code": 5411}])
            )
            (root / "merchant_category_codes.csv").write_text("mcc,description\n5411,Grocery Stores\n")
            (root / "payments.csv").write_text(
                "merchant,year,day_of_year,hour_of_day,minute_of_hour,eur_amount,is_credit,has_fraudulent_dispute,is_refused_by_adyen,aci,card_scheme,issuing_country,acquirer_country\n"
                "SyntheticMerchant,2023,1,0,0,10.0,true,false,false,A,GlobalCard,NL,NL\n"
            )
            logic = parse_question("Which card scheme would provide the cheapest fee for a transaction value of 10 EUR?")
            result = pandas_executor.execute_plan(build_analysis_plan(logic), {"context_dir": root})

        self.assertTrue(result.success, result.errors)
        self.assertEqual("GlobalCard", result.value["card_scheme"])
        self.assertEqual(["GlobalCard", "NexPay"], [row["card_scheme"] for row in result.value["candidate_table"]])

    def test_fee_extreme_by_mcc_returns_all_tied_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "fees.json").write_text(
                json.dumps(
                    [
                        _fee_rule(1, "GlobalCard", [], fixed_amount=0.10, rate=0, mcc=[1111]),
                        _fee_rule(2, "GlobalCard", [], fixed_amount=0.30, rate=0, mcc=[2222]),
                        _fee_rule(3, "NexPay", [], fixed_amount=0.30, rate=0, mcc=[3333]),
                    ]
                )
            )
            (root / "merchant_data.json").write_text(
                json.dumps([{"merchant": "SyntheticMerchant", "account_type": "A", "capture_delay": "manual", "merchant_category_code": 1111}])
            )
            (root / "merchant_category_codes.csv").write_text("mcc,description\n1111,A\n2222,B\n3333,C\n")
            (root / "payments.csv").write_text(
                "merchant,year,day_of_year,hour_of_day,minute_of_hour,eur_amount,is_credit,has_fraudulent_dispute,is_refused_by_adyen,aci,card_scheme,issuing_country,acquirer_country\n"
                "SyntheticMerchant,2023,1,0,0,10.0,true,false,false,A,GlobalCard,NL,NL\n"
            )
            logic = parse_question("What is the most expensive MCC for a transaction of 10 euros, in general?")
            result = pandas_executor.execute_plan(build_analysis_plan(logic), {"context_dir": root})

        self.assertEqual("fee_extreme_by_dimension", logic.operation)
        self.assertTrue(result.success, result.errors)
        self.assertEqual(["2222", "3333"], result.value["answer"])

    def test_highest_transaction_count_defaults_to_merchant(self) -> None:
        payments = pd.DataFrame(
            {
                "merchant": ["A", "A", "A", "B", "B"],
                "issuing_country": ["NL", "BE", "FR", "NL", "NL"],
            }
        )
        logic = parse_question("Which merchant has the highest number of transactions?")
        result = pandas_executor.execute_plan(build_analysis_plan(logic), {"payments": payments})

        self.assertEqual("top_count", logic.operation)
        self.assertEqual("merchant", logic.group_by)
        self.assertTrue(result.success, result.errors)
        self.assertEqual("A", result.value)

    def test_missing_value_top_count_uses_null_filter_and_dimension(self) -> None:
        payments = pd.DataFrame(
            {
                "card_scheme": ["GlobalCard", "GlobalCard", "NexPay", "NexPay"],
                "email_address": ["", None, "", "person@example.com"],
            }
        )
        logic = parse_question("What is the most frequent card scheme among transactions with missing email addresses?")
        plan = build_analysis_plan(logic)
        result = pandas_executor.execute_plan(plan, {"payments": payments})
        sql_result = sql_executor.execute_plan(plan, {"payments": payments})

        self.assertEqual("top_count", logic.operation)
        self.assertEqual("card_scheme", logic.group_by)
        self.assertEqual({"email_address": "__NULL__"}, logic.filters)
        self.assertTrue(result.success, result.errors)
        self.assertTrue(sql_result.success, sql_result.errors)
        self.assertEqual("GlobalCard", result.value)
        self.assertEqual(result.value, sql_result.value)

    def test_dabstep_null_check_percentage_mode_is_generic(self) -> None:
        payments = pd.DataFrame({"psp_reference": ["a", "b", "c", ""], "email_address": ["x@example.com", "", None, "z@example.com"]})
        logic = parse_question("What percentage of payments dataset is missing email address?")
        result = pandas_executor.execute_plan(build_analysis_plan(logic), {"payments": payments})

        self.assertEqual("null_check", logic.operation)
        self.assertEqual("rate", logic.parameters["mode"])
        self.assertEqual("percentage", logic.output_format["answer_type"])
        self.assertTrue(result.success, result.errors)
        self.assertAlmostEqual(50.0, float(result.value))

    def test_dabstep_alias_row_count_and_boolean_filters_are_generic(self) -> None:
        payments = pd.DataFrame(
            {
                "ip_address": ["1.1.1.1", "", None, "2.2.2.2"],
                "ip_country": ["NL", "BE", "BE", "BE"],
                "has_fraudulent_dispute": [True, False, True, False],
            }
        )
        context = {"payments": payments}
        missing_logic = parse_question("How many transactions have missing IP addresses?", context=context)
        fraud_logic = parse_question("How many transactions were flagged as fraudulent?", context=context)
        country_logic = parse_question("Which IP country has the highest number of transactions?", context=context)

        missing_plan = build_analysis_plan(missing_logic)
        fraud_plan = build_analysis_plan(fraud_logic)
        country_plan = build_analysis_plan(country_logic)
        missing = pandas_executor.execute_plan(missing_plan, context)
        fraud = pandas_executor.execute_plan(fraud_plan, context)
        country = pandas_executor.execute_plan(country_plan, context)
        missing_sql = sql_executor.execute_plan(missing_plan, context)
        fraud_sql = sql_executor.execute_plan(fraud_plan, context)
        country_sql = sql_executor.execute_plan(country_plan, context)

        self.assertEqual("row_count", missing_logic.operation)
        self.assertEqual({"ip_address": "__NULL__"}, missing_logic.filters)
        self.assertEqual({"has_fraudulent_dispute": True}, fraud_logic.filters)
        self.assertEqual("ip_country", country_logic.parameters["group_by"])
        self.assertEqual(2, missing.value)
        self.assertEqual(2, fraud.value)
        self.assertEqual("BE", country.value)
        self.assertEqual(missing.value, missing_sql.value)
        self.assertEqual(fraud.value, fraud_sql.value)
        self.assertEqual(country.value, country_sql.value)

    def test_grouped_fraud_rate_metric_and_answer_targets_are_generic(self) -> None:
        payments = pd.DataFrame(
            {
                "year": [2023, 2023, 2023, 2023],
                "day_of_year": [1, 1, 1, 1],
                "merchant": ["M1", "M1", "M2", "M2"],
                "card_scheme": ["AlphaPay", "AlphaPay", "BetaPay", "BetaPay"],
                "eur_amount": [10.0, 90.0, 20.0, 80.0],
                "has_fraudulent_dispute": [True, False, True, False],
            }
        )
        context = {"payments": payments}
        metric_logic = parse_question("What is the highest avg fraud rate for the year 2023? (by card_scheme)", context=context)
        entity_logic = parse_question("Which payment method (card_scheme) has the lowest avg fraud rate for the year 2023?", context=context)
        metric_result = pandas_executor.execute_plan(build_analysis_plan(metric_logic), context)
        entity_result = pandas_executor.execute_plan(build_analysis_plan(entity_logic), context)

        self.assertEqual("rank_by_metric", metric_logic.operation)
        self.assertEqual("metric_only", metric_logic.answer_target)
        self.assertEqual("entity_only", entity_logic.answer_target)
        self.assertEqual("20.000", format_answer(metric_result.value, metric_logic.output_format))
        self.assertEqual("AlphaPay", format_answer(entity_result.value, entity_logic.output_format))

    def test_fraud_rate_fluctuation_uses_period_std_not_single_group_rate(self) -> None:
        payments = pd.DataFrame(
            {
                "year": [2023] * 8,
                "day_of_year": [1, 1, 32, 32, 1, 1, 32, 32],
                "merchant": ["Volatile", "Volatile", "Volatile", "Volatile", "Stable", "Stable", "Stable", "Stable"],
                "eur_amount": [10.0, 90.0, 30.0, 70.0, 20.0, 80.0, 20.0, 80.0],
                "has_fraudulent_dispute": [True, False, True, False, True, False, True, False],
            }
        )
        logic = parse_question("Which merchant had the highest fluctuation (std) in fraud rate during the year 2023?")
        result = pandas_executor.execute_plan(build_analysis_plan(logic), {"payments": payments})

        self.assertEqual("fraud_rate_fluctuation", logic.operation)
        self.assertEqual("merchant", logic.parameters["group_by"])
        self.assertTrue(result.success, result.errors)
        self.assertEqual("Volatile", format_answer(result.value, logic.output_format))

    def test_top_k_share_can_rank_by_amount_but_share_transaction_count(self) -> None:
        payments = pd.DataFrame(
            {
                "merchant": ["A", "A", "B", "C", "C", "C", "C", "C"],
                "eur_amount": [100.0, 100.0, 80.0, 70.0, 70.0, 70.0, 70.0, 70.0],
            }
        )
        logic = parse_question("What percentage of transactions came from the top 2 merchants in amount volume?")
        plan = build_analysis_plan(logic)
        pandas_result = pandas_executor.execute_plan(plan, {"payments": payments})
        sql_result = sql_executor.execute_plan(plan, {"payments": payments})

        self.assertEqual("top_k_share", logic.operation)
        self.assertEqual("eur_amount", logic.parameters["ranking_metric"])
        self.assertEqual("__row_count__", logic.parameters["share_metric"])
        self.assertTrue(pandas_result.success, pandas_result.errors)
        self.assertTrue(sql_result.success, sql_result.errors)
        self.assertAlmostEqual(87.5, float(pandas_result.value))
        self.assertAlmostEqual(float(pandas_result.value), float(sql_result.value))

    def test_quantile_percentage_can_target_repeat_entities_with_changed_values(self) -> None:
        payments = pd.DataFrame(
            {
                "eur_amount": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
                "email_address": ["repeat@example.com", "b", "c", "d", "e", "f", "g", "h", "repeat@example.com", "single@example.com"],
            }
        )
        logic = parse_question("What percentage of high-value transactions (above the 80th percentile of amount) are made by repeat customers?")
        result = pandas_executor.execute_plan(build_analysis_plan(logic), {"payments": payments})

        self.assertEqual("quantile_percentage", logic.operation)
        self.assertEqual("repeat_entity", logic.parameters["target_mode"])
        self.assertTrue(result.success, result.errors)
        self.assertAlmostEqual(50.0, float(result.value))

    def test_outlier_fraud_percentage_and_rate_comparison_are_generic(self) -> None:
        payments = pd.DataFrame(
            {
                "year": [2023] * 51,
                "eur_amount": [10.0] * 50 + [1000.0],
                "has_fraudulent_dispute": [False] * 50 + [True],
            }
        )
        context = {"payments": payments}
        percentage_logic = parse_question("What percentage of outlier transactions identified using Z-Score > 3 are fraudulent during the year 2023?", context=context)
        comparison_logic = parse_question("Do outlier transactions have a higher fraud rate than inlier transactions using Z-Score > 3 during the year 2023?", context=context)
        percentage = pandas_executor.execute_plan(build_analysis_plan(percentage_logic), {"payments": payments})
        comparison = pandas_executor.execute_plan(build_analysis_plan(comparison_logic), {"payments": payments})

        self.assertEqual("outlier_target_percentage", percentage_logic.operation)
        self.assertEqual("outlier_rate_comparison", comparison_logic.operation)
        self.assertEqual("eur_amount", percentage_logic.parameters["metric"])
        self.assertEqual("eur_amount", comparison_logic.parameters["metric"])
        self.assertEqual({"year": 2023}, percentage_logic.filters)
        self.assertTrue(percentage.success, percentage.errors)
        self.assertTrue(comparison.success, comparison.errors)
        self.assertAlmostEqual(100.0, float(percentage.value))
        self.assertEqual("yes", comparison.value)

    def test_correlation_threshold_and_quantile_percentage_are_generic(self) -> None:
        payments = pd.DataFrame(
            {
                "eur_amount": [1.0, 2.0, 3.0, 4.0, 100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
                "has_fraudulent_dispute": [False, False, False, False, True, True, True, True, True, True],
            }
        )
        correlation_logic = parse_question("Is correlation between transaction amount and fraudulent disputes > 0.5?")
        quantile_logic = parse_question("What percentage of high-value transactions are above the 90th percentile?")
        correlation = pandas_executor.execute_plan(build_analysis_plan(correlation_logic), {"payments": payments})
        quantile = pandas_executor.execute_plan(build_analysis_plan(quantile_logic), {"payments": payments})

        self.assertEqual("correlation_threshold", correlation_logic.operation)
        self.assertEqual("quantile_percentage", quantile_logic.operation)
        self.assertTrue(correlation.success, correlation.errors)
        self.assertTrue(quantile.success, quantile.errors)
        self.assertEqual("yes", correlation.value["answer"])
        self.assertAlmostEqual(10.0, float(quantile.value))

        below_logic = parse_question("What is the percentage of transactions below the 25th percentile of transaction amounts?")
        below = pandas_executor.execute_plan(build_analysis_plan(below_logic), {"payments": payments})
        self.assertEqual("quantile_percentage", below_logic.operation)
        self.assertTrue(below.success, below.errors)
        self.assertAlmostEqual(30.0, float(below.value))

    def test_worst_fraud_segment_uses_volume_rate_across_dimensions(self) -> None:
        payments = pd.DataFrame(
            {
                "merchant": ["A", "A", "B", "B"],
                "card_scheme": ["GlobalCard", "GlobalCard", "NexPay", "NexPay"],
                "shopper_interaction": ["Ecommerce", "POS", "Ecommerce", "POS"],
                "issuing_country": ["NL", "NL", "BE", "BE"],
                "eur_amount": [100.0, 100.0, 50.0, 50.0],
                "has_fraudulent_dispute": [False, False, True, False],
            }
        )
        logic = parse_question("Which segment has the worst fraud rate?")
        result = pandas_executor.execute_plan(build_analysis_plan(logic), {"payments": payments})

        self.assertEqual("worst_fraud_segment", logic.operation)
        self.assertEqual("fraud_volume_rate", logic.metric)
        self.assertTrue(result.success, result.errors)
        self.assertEqual("card_scheme", result.value["segment"])
        self.assertEqual("NexPay", result.value["value"])

    def test_fee_factor_direction_and_volume_threshold_use_rule_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cheap_rule = _fee_rule(1, "GlobalCard", [], fixed_amount=0.10, rate=0)
            cheap_rule["monthly_volume"] = "<10k"
            cheap_rule["capture_delay"] = "manual"
            cheap_rule["is_credit"] = None
            volume_rule = _fee_rule(2, "GlobalCard", [], fixed_amount=0.05, rate=0)
            volume_rule["monthly_volume"] = ">10k"
            volume_rule["is_credit"] = None
            credit_rule = _fee_rule(3, "GlobalCard", [], fixed_amount=0.01, rate=30)
            credit_rule["is_credit"] = True
            credit_rule["monthly_fraud_level"] = ">8.3%"
            credit_rule["intracountry"] = None
            debit_rule = _fee_rule(4, "GlobalCard", [], fixed_amount=0.01, rate=10)
            debit_rule["is_credit"] = False
            debit_rule["intracountry"] = None
            intra_rule = _fee_rule(5, "GlobalCard", [], fixed_amount=0.01, rate=5)
            intra_rule["is_credit"] = None
            intra_rule["intracountry"] = True
            cross_border_rule = _fee_rule(6, "GlobalCard", [], fixed_amount=0.01, rate=20)
            cross_border_rule["is_credit"] = None
            cross_border_rule["intracountry"] = False
            (root / "fees.json").write_text(json.dumps([cheap_rule, volume_rule, credit_rule, debit_rule, intra_rule, cross_border_rule]))
            (root / "merchant_data.json").write_text(
                json.dumps([{"merchant": "SyntheticMerchant", "account_type": "A", "capture_delay": "manual", "merchant_category_code": 5411}])
            )
            (root / "merchant_category_codes.csv").write_text("mcc,description\n5411,Grocery Stores\n")
            (root / "manual.md").write_text(
                "## 2. Account Type\n\n"
                "| Account Type | Description |\n"
                "|--------------|-------------|\n"
                "| A | Alpha |\n"
                "| O | Other |\n"
            )
            (root / "payments.csv").write_text(
                "merchant,year,day_of_year,hour_of_day,minute_of_hour,eur_amount,is_credit,has_fraudulent_dispute,is_refused_by_adyen,aci,card_scheme,issuing_country,acquirer_country\n"
                "SyntheticMerchant,2023,1,0,0,10.0,true,false,false,A,GlobalCard,NL,NL\n"
            )
            factor_logic = parse_question("Which factors contribute to a cheaper fee rate if factors value is increased?")
            decrease_logic = parse_question("Which factors contribute to a cheaper fee rate if the factors' value is decreased?")
            true_logic = parse_question("What boolean factors contribute to a cheaper fee rate if set to True?")
            false_logic = parse_question("What boolean factors contribute to a cheaper fee rate if set to False?")
            volume_logic = parse_question("What is the highest volume where fees do not become cheaper?")
            field_logic = parse_question("What are the possible values for the field account_type?")
            factor_result = pandas_executor.execute_plan(build_analysis_plan(factor_logic), {"context_dir": root})
            decrease_result = pandas_executor.execute_plan(build_analysis_plan(decrease_logic), {"context_dir": root})
            true_result = pandas_executor.execute_plan(build_analysis_plan(true_logic), {"context_dir": root})
            false_result = pandas_executor.execute_plan(build_analysis_plan(false_logic), {"context_dir": root})
            volume_result = pandas_executor.execute_plan(build_analysis_plan(volume_logic), {"context_dir": root})
            field_result = pandas_executor.execute_plan(build_analysis_plan(field_logic), {"payments": pd.DataFrame(), "context_dir": root})

        self.assertEqual("fee_factor_direction", factor_logic.operation)
        self.assertEqual("fee_factor_direction", decrease_logic.operation)
        self.assertEqual("fee_factor_direction", true_logic.operation)
        self.assertEqual("fee_factor_direction", false_logic.operation)
        self.assertEqual("fee_volume_threshold", volume_logic.operation)
        self.assertEqual("field_values", field_logic.operation)
        self.assertTrue(factor_result.success, factor_result.errors)
        self.assertTrue(decrease_result.success, decrease_result.errors)
        self.assertTrue(true_result.success, true_result.errors)
        self.assertTrue(false_result.success, false_result.errors)
        self.assertTrue(volume_result.success, volume_result.errors)
        self.assertTrue(field_result.success, field_result.errors)
        self.assertEqual(["monthly_volume", "capture_delay"], factor_result.value)
        self.assertEqual(["monthly_fraud_level"], decrease_result.value)
        self.assertEqual(["intracountry"], true_result.value)
        self.assertEqual(["is_credit"], false_result.value)
        self.assertEqual(">10k", volume_result.value)
        self.assertEqual(["A", "O"], field_result.value)

    def test_excessive_retry_fee_is_classified_as_true_unsupported(self) -> None:
        logic = parse_question("How much, if exists, is the excessive retry fee?")

        self.assertEqual("not_applicable", logic.operation)
        self.assertIn("excessive retry", logic.parameters["reason"])


def _fee_rule(fee_id: int, card_scheme: str, aci: list[str], *, fixed_amount: float, rate: int, mcc: list[int] | None = None) -> dict[str, object]:
    return {
        "ID": fee_id,
        "card_scheme": card_scheme,
        "account_type": [],
        "capture_delay": None,
        "monthly_fraud_level": None,
        "monthly_volume": None,
        "merchant_category_code": mcc or [],
        "is_credit": True,
        "aci": aci,
        "fixed_amount": fixed_amount,
        "rate": rate,
        "intracountry": None,
    }


def _user_question(dataset_id: str, question: str):
    from data_agent_core.contracts.analysis_contracts import UserQuestion

    return UserQuestion(dataset_id=dataset_id, question=question)


if __name__ == "__main__":
    unittest.main()
