"""Service-level semantic checks for /message analysis flow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.services.data_agent_service import DataAgentService, _looks_like_correction_request
from backend.storage.temp_file_store import TempFileStore
from data_agent_core.llm.client import MockLLMClient


class DataAgentMessageSemanticsTest(unittest.TestCase):
    def test_message_grouped_chart_request_returns_aggregated_chart_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "city.csv"
            csv_path.write_text(
                "city,sales\n"
                "上海,100\n"
                "北京,120\n"
                "上海,140\n"
                "北京,160\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="city.csv")
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="按城市展示销售额，生成柱状图。")

        rows_by_city = {row["city"]: row["sales"] for row in response["result"]["rows"]}
        self.assertTrue(response["success"])
        self.assertEqual("aggregation", response["debug"]["operation"])
        self.assertEqual({"上海": 240, "北京": 280}, rows_by_city)
        self.assertTrue(response["verification"]["passed"])
        self.assertEqual("bar", response["chart"]["chart_type"])
        self.assertEqual(rows_by_city, {row["city"]: row["sales"] for row in response["chart"]["data"]})

    def test_message_same_schema_multi_file_uses_all_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            a_path = root / "a.csv"
            b_path = root / "b.csv"
            a_path.write_text("门店,产品,sales\nA店,苹果,150\n", encoding="utf-8")
            b_path.write_text("门店,产品,sales\nB店,苹果,170\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets([a_path, b_path], original_filenames=["a.csv", "b.csv"])
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="A店和B店哪个门店总销售额最高？")

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual("ranking", response["debug"]["operation"])
        self.assertEqual([{"门店": "B店", "sales": 170}], response["result"]["rows"])
        self.assertEqual(["a", "b"], response["debug"]["source_tables"])
        self.assertIn("same_schema_union", response["debug"]["table_selection_reason"])
        self.assertTrue(response["verification"]["passed"])

    def test_message_explicit_file_product_question_returns_product_not_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            a_path = root / "qa_store_a.csv"
            b_path = root / "qa_store_b.csv"
            a_path.write_text("store,product,sales\nA店,苹果,80\nA店,香蕉,70\n", encoding="utf-8")
            b_path.write_text("store,product,sales\nB店,苹果,80\nB店,香蕉,90\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets([a_path, b_path], original_filenames=["qa_store_a.csv", "qa_store_b.csv"])
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="qa_store_b.csv里面哪个产品销售额最高？")

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual([{"product": "香蕉", "sales": 90}], response["result"]["rows"])
        self.assertEqual(["qa_store_b"], response["debug"]["source_tables"])
        self.assertEqual("product", response["logic_form"]["parameters"]["dimension"])
        self.assertNotIn("当前结果表只返回", response["answer"])

    def test_message_profit_margin_uses_derived_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "city_profit.csv"
            csv_path.write_text("city,sales,profit\n上海,100,40\n北京,280,56\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="city_profit.csv")
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪个城市利润率最高？")

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual([{"city": "上海", "利润率": 0.4}], response["result"]["rows"])
        self.assertEqual("利润率", response["logic_form"]["parameters"]["derived_metric"]["name"])
        self.assertNotEqual("sales", response["logic_form"]["parameters"]["metric"])
        self.assertIn("sum(profit)/sum(sales)", response["answer"])
        self.assertNotIn("当前结果表只返回", response["answer"])
        self.assertNotIn("仍需按当前数据范围和指标口径解读", response["answer"])

    def test_message_ranking_word_routes_to_ranking_not_plain_aggregation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "monthly_city.csv"
            csv_path.write_text(
                "month,city,sales\n"
                "2026-01,上海,318\n"
                "2026-01,北京,276\n"
                "2026-02,上海,245\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="monthly_city.csv")
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="2026年1月各城市销售额排名如何？")

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual("filtered_metric_ranking", response["logic_form"]["operation"])
        self.assertEqual({"city": "上海", "sales": 318}, response["result"]["rows"][0])

    def test_message_quality_followup_routes_to_cleaning_guidance_not_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "service_metrics.csv"
            csv_path.write_text(
                "month,city,service_line,sales,profit,tickets\n"
                "2026-01,上海,实施交付,180,42,35\n"
                "2026-01,北京,客户成功,216,68,28\n"
                "2026-02,深圳,实施交付,302,96,44\n"
                "2026-03,深圳,客户成功,284,91,39\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="service_metrics.csv")
            first = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪个城市销售额最高？")
            response = service.respond_to_message(
                conversation_id=first["conversation_id"],
                question="该城市销售额最高的月份是否存在数据质量问题？",
            )

        self.assertTrue(response["success"], response["errors"])
        self.assertIn(response["logic_form"]["operation"], {"cleaning_policy", "quality_summary"})
        self.assertNotIn(response["logic_form"]["operation"], {"ranking", "filtered_metric_ranking", "detail_lookup"})
        self.assertTrue(response["followup_context"]["is_followup"])

    def test_message_correction_reruns_with_revised_formula_from_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "city_profit.csv"
            csv_path.write_text("city,sales,profit\n上海,100,40\n北京,300,60\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="city_profit.csv")
            first = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪个城市利润最高？")
            response = service.respond_to_message(
                conversation_id=first["conversation_id"],
                question="不是这个口径，用利润率=sum利润/sum销售重新算",
            )

        self.assertTrue(first["success"], first["errors"])
        self.assertEqual([{"city": "北京", "profit": 60}], first["result"]["rows"])
        self.assertTrue(response["success"], response["errors"])
        self.assertEqual(first["conversation_id"], response["conversation_id"])
        self.assertEqual([{"city": "上海", "利润率": 0.4}], response["result"]["rows"])
        self.assertTrue(response["correction_context"]["is_correction"])
        self.assertEqual(first["run_id"], response["correction_context"]["previous_run_id"])
        self.assertEqual(["metric_formula"], response["correction_context"]["changed_scope"])
        self.assertIn("sum(profit)/sum(sales)", response["answer"])
        self.assertIn("首行结果", response["correction_context"]["difference_summary"])

    def test_message_incomplete_correction_asks_for_formula_without_reusing_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "city_profit.csv"
            csv_path.write_text("city,sales,profit\n上海,100,40\n北京,300,60\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="city_profit.csv")
            first = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪个城市利润最高？")
            response = service.respond_to_message(
                conversation_id=first["conversation_id"],
                question="不是这个口径，重新算",
            )

        self.assertFalse(response["success"])
        self.assertEqual("clarification", response["answer_type"])
        self.assertEqual("missing_revised_formula", response["correction_context"]["reason"])
        self.assertEqual([], response["result"]["rows"])
        self.assertIn("利润率=sum利润/sum销售", response["answer"])

    def test_message_followup_high_low_slash_is_not_formula_correction(self) -> None:
        self.assertFalse(_looks_like_correction_request("先复核这些异常高/低点是否为真实业务事件，再按客户拆分来源。"))
        self.assertTrue(_looks_like_correction_request("不是这个口径，用利润率=sum利润/sum销售重新算"))

    def test_message_short_drilldown_followup_reuses_previous_retail_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "v_trd_dist_ord_dtl.csv"
            csv_path.write_text(
                "sign_time,sign_amt,emp_name,cust_code,cust_name,ctg_name,sku_name\n"
                "2026-04-01,100,张三,C1,一号店,天然水,S1\n"
                "2026-05-01,200,李四,C2,二号店,东方树叶,S2\n"
                "2026-05-02,50,张三,C1,一号店,天然水,S1\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="v_trd_dist_ord_dtl.csv")
            first = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="请展示2026年4月至5月分品类历史分销金额趋势，选总金额最高的2个品类，生成折线图。",
            )
            response = service.respond_to_message(
                conversation_id=first["conversation_id"],
                question="按客户拆分来源",
            )

        self.assertTrue(first["success"], first["errors"])
        self.assertTrue(response["success"], response["errors"])
        self.assertTrue(response["followup_context"]["is_followup"])
        self.assertEqual("structured_followup_action", response["followup_context"]["reason"])
        self.assertEqual("retail_distribution_topn_chart", response["logic_form"]["operation"])
        self.assertEqual("cust_name", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual("二号店", response["result"]["rows"][0]["客户"])
        self.assertEqual("analysis_ready", response["current_analysis_context"]["state_name"])
        self.assertEqual("retail_distribution_topn_chart", response["current_analysis_context"]["operation"])
        self.assertTrue(response["current_analysis_context"]["available_followup_actions"])

    def test_message_compound_followup_executes_ordered_structured_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "v_trd_dist_ord_dtl.csv"
            csv_path.write_text(
                "sign_time,sign_amt,emp_name,cust_code,cust_name,ctg_name,sku_name\n"
                "2026-04-01,100,张三,C1,一号店,天然水,S1\n"
                "2026-05-01,200,李四,C2,二号店,东方树叶,S2\n"
                "2026-05-02,50,张三,C1,一号店,天然水,S1\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="v_trd_dist_ord_dtl.csv")
            first = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="请展示2026年4月至5月分品类历史分销金额趋势，选总金额最高的2个品类，生成折线图。",
            )
            response = service.respond_to_message(
                conversation_id=first["conversation_id"],
                question="先复核这些异常高/低点是否为真实业务事件，再按客户拆分来源。",
            )

        self.assertTrue(first["success"], first["errors"])
        self.assertTrue(response["success"], response["errors"])
        self.assertEqual("compound_analysis", response["answer_type"])
        self.assertEqual("compound_followup_actions", response["followup_context"]["reason"])
        self.assertEqual(
            ["retail_category_distribution_monthly_trend", "retail_distribution_topn_chart"],
            [action["result_operation"] for action in response["agent_actions"]],
        )
        self.assertEqual(
            ["retail_category_distribution_monthly_trend", "retail_distribution_topn_chart"],
            [item["logic_form"]["operation"] for item in response["result"]["sub_results"]],
        )
        self.assertIn("2 个结构化动作", response["answer"])
        self.assertEqual("retail_distribution_topn_chart", response["current_analysis_context"]["operation"])
        self.assertEqual("cust_name", response["current_analysis_context"]["scope"]["dimension"])

    def test_message_llm_simulated_random_followup_sequence_keeps_agent_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "v_trd_dist_ord_dtl.csv"
            csv_path.write_text(
                "sign_time,sign_amt,emp_name,cust_code,cust_name,ctg_name,sku_name\n"
                "2026-04-01,100,张三,C1,一号店,天然水,S1\n"
                "2026-04-02,130,王五,C3,三号店,天然水,S3\n"
                "2026-05-01,260,李四,C2,二号店,东方树叶,S2\n"
                "2026-05-02,50,张三,C1,一号店,天然水,S1\n"
                "2026-05-03,90,王五,C3,三号店,东方树叶,S2\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="v_trd_dist_ord_dtl.csv")
            turns = [
                "请展示2026年4月至5月分品类历史分销金额趋势，选总金额最高的2个品类，生成折线图。",
                "这些高低点先复核一下",
                "按客户拆分来源",
                "按产品也看一下",
            ]
            responses = [service.respond_to_message(dataset_id=upload["dataset_id"], question=turns[0])]
            for question in turns[1:]:
                responses.append(service.respond_to_message(conversation_id=responses[-1]["conversation_id"], question=question))

        self.assertTrue(all(response["success"] for response in responses), [response.get("errors") for response in responses])
        self.assertEqual(responses[0]["conversation_id"], responses[-1]["conversation_id"])
        self.assertEqual("retail_category_distribution_monthly_trend", responses[1]["logic_form"]["operation"])
        self.assertEqual("retail_distribution_topn_chart", responses[2]["logic_form"]["operation"])
        self.assertEqual("cust_name", responses[2]["logic_form"]["parameters"]["dimension"])
        self.assertEqual("retail_distribution_topn_chart", responses[3]["logic_form"]["operation"])
        self.assertEqual("sku_name", responses[3]["logic_form"]["parameters"]["dimension"])
        self.assertEqual("analysis_ready", responses[-1]["current_analysis_context"]["state_name"])
        self.assertGreaterEqual(responses[-1]["current_analysis_context"]["history_depth"], 4)

    def test_message_retail_trend_uses_guardrail_when_llm_provider_fails(self) -> None:
        class FailingLLMClient:
            def complete_json(self, messages, temperature=0.0):  # noqa: ANN001
                raise RuntimeError("provider unavailable")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "v_trd_dist_ord_dtl.csv"
            csv_path.write_text(
                "sign_time,sign_amt,cust_name,ctg_name,sku_name\n"
                "2026-04-01,100,一号店,天然水,S1\n"
                "2026-05-01,200,二号店,东方树叶,S2\n"
                "2026-05-02,50,一号店,天然水,S1\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=FailingLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="v_trd_dist_ord_dtl.csv")
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="请展示2026年4月至5月分品类历史分销金额趋势，选总金额最高的2个品类，生成折线图。",
            )

        self.assertTrue(response["success"], response["errors"])
        self.assertIn(response["logic_form"]["operation"], {"retail_category_distribution_monthly_trend", "aggregation"})
        self.assertGreaterEqual(len(response["result"]["rows"]), 1)
        self.assertNotIn("provider unavailable", response["answer"])

    def test_message_retail_sales_composition_uses_fact_table_without_overview_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "v_trd_dist_ord_dtl.csv"
            csv_path.write_text(
                "ctg_name,sign_amt,sign_sales_amt_550_6d1_share,sign_time,cooperate_start_date,capacity,cmdt_name,emp_name,cust_code\n"
                "天然水,100,0.2,2026-05-01,2024-01-01,550mL,天然水550,张三,C1\n"
                "茶π,50,0.1,2026-05-02,2024-01-02,500mL,茶π500,李四,C2\n"
                "天然水,80,0.3,2026-06-01,2024-02-01,550mL,天然水550,张三,C1\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="v_trd_dist_ord_dtl.csv")
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="看一下天然水的销售组成")

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual("aggregation", response["logic_form"]["operation"])
        self.assertEqual("v_trd_dist_ord_dtl", response["logic_form"]["parameters"]["table"])
        self.assertEqual("sign_amt", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("capacity", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"ctg_name": "天然水"}, response["logic_form"]["filters"])
        self.assertEqual([{"capacity": "550mL", "sign_amt": 180}], response["result"]["rows"])
        self.assertIsNone(response["debug"].get("raw_detail_answer_guard"))

    def test_message_explicit_time_column_does_not_turn_rate_substring_into_share_metric(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "v_trd_dist_ord_dtl.csv"
            csv_path.write_text(
                "ctg_name,sign_amt,sign_sales_amt_550_6d1_share,sign_time,cooperate_start_date,capacity,emp_name,cust_code\n"
                "天然水,100,0.2,2026-05-01,2024-01-01,550mL,张三,C1\n"
                "天然水,80,0.3,2026-06-01,2024-02-01,550mL,张三,C1\n"
                "茶π,50,0.1,2026-05-02,2024-01-02,500mL,李四,C2\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="v_trd_dist_ord_dtl.csv")
            response = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="天然水销售金额随时间（cooperate_start_date）的趋势是怎样的？",
            )

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual("sign_amt", response["logic_form"]["parameters"]["metric"])
        self.assertEqual("cooperate_start_date", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual(
            [
                {"cooperate_start_date": "2024-01-01", "sign_amt": 100},
                {"cooperate_start_date": "2024-02-01", "sign_amt": 80},
            ],
            response["result"]["rows"],
        )

    def test_message_retail_route_scope_followups_keep_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            history = root / "v_trd_dist_ord_dtl.csv"
            route = root / "v_chl_route_plan_cust_cnt_1d_df.csv"
            customer = root / "终端客户月度维表.csv"
            history.write_text(
                "sign_time,sign_amt,sign_box_cnt,emp_name,p_emp_name,cust_code,cust_name,ctg_name,ord_status_name\n"
                "2026-05-05,3275.093626,118.588969,赵云,刘备,C_IN,线路内店,天然水,已签收\n"
                "2026-05-06,5000,200,马超振,刘备,C_OUT1,线路外店1,天然水,已签收\n"
                "2026-05-07,3000,120,姜维,刘备,C_OUT2,线路外店2,东方树叶,已签收\n"
                "2026-05-08,2417.495328,114.150701,俞恺,刘备,C_OUT3,线路外店3,茶π,已签收\n",
                encoding="utf-8",
            )
            route.write_text(
                "visit_date,cust_code,cust_name,emp_name,route_code\n"
                "2026-05-19,C_IN,线路内店,赵云,R1\n",
                encoding="utf-8",
            )
            customer.write_text(
                "年月,终端客户编码,终端客户,是否合约店,业代,主任\n"
                "202605,C_IN,线路内店,是,赵云,刘备\n"
                "202605,C_OUT1,线路外店1,否,马超振,刘备\n"
                "202605,C_OUT2,线路外店2,否,姜维,刘备\n"
                "202605,C_OUT3,线路外店3,否,俞恺,刘备\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(
                [history, route, customer],
                original_filenames=[history.name, route.name, customer.name],
            )
            first = service.respond_to_message(
                dataset_id=upload["dataset_id"],
                question="线路内/线路外的签收金额和签收箱数分别是多少？",
                execution_mode="dual",
            )
            why = service.respond_to_message(conversation_id=first["conversation_id"], question="为什么线路外会更高", execution_mode="dual")
            split = service.respond_to_message(conversation_id=first["conversation_id"], question="刚才线路外里按业代拆开", execution_mode="dual")
            top = service.respond_to_message(conversation_id=first["conversation_id"], question="刚才贡献最大的人", execution_mode="dual")
            boxes = service.respond_to_message(conversation_id=first["conversation_id"], question="不要看签收金额，改看签收箱数", execution_mode="dual")

        self.assertTrue(upload["success"], upload.get("errors"))
        self.assertTrue(first["success"], first["errors"])
        self.assertEqual("retail_route_scope_metric_summary", first["logic_form"]["operation"])
        first_rows = {row["线路范围"]: row for row in first["result"]["rows"]}
        self.assertAlmostEqual(10417.495328, first_rows["线路外"]["签收金额"])
        self.assertAlmostEqual(434.150701, first_rows["线路外"]["签收箱数"])
        self.assertAlmostEqual(3275.093626, first_rows["线路内"]["签收金额"])
        self.assertAlmostEqual(118.588969, first_rows["线路内"]["签收箱数"])

        self.assertTrue(why["success"], why["errors"])
        self.assertEqual("retail_route_scope_difference_reason", why["logic_form"]["operation"])
        self.assertTrue(why["followup_context"]["is_followup"])
        self.assertIn("线路外签收金额更高", why["answer"])
        self.assertIn("马超振", why["answer"])

        self.assertTrue(split["success"], split["errors"])
        self.assertEqual("retail_route_scope_employee_ranking", split["logic_form"]["operation"])
        self.assertEqual("线路外", split["logic_form"]["parameters"]["route_scope"])
        self.assertEqual(["马超振", "姜维", "俞恺"], [row["业代"] for row in split["result"]["rows"]])

        self.assertTrue(top["success"], top["errors"])
        self.assertEqual("retail_route_scope_employee_ranking", top["logic_form"]["operation"])
        self.assertEqual([{"业代": "马超振", "线路范围": "线路外", "签收金额": 5000.0}], top["result"]["rows"])

        self.assertTrue(boxes["success"], boxes["errors"])
        self.assertEqual("retail_route_scope_employee_ranking", boxes["logic_form"]["operation"])
        self.assertEqual("sign_box_cnt", boxes["logic_form"]["parameters"]["metric"])
        self.assertEqual(["马超振", "姜维", "俞恺"], [row["业代"] for row in boxes["result"]["rows"]])

    def test_message_trusted_join_returns_joined_city_top1_without_audit_noise(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            orders_path = root / "orders.csv"
            customers_path = root / "customers.csv"
            orders_path.write_text("customer_id,sales\nC1,100\nC2,120\nC3,70\n", encoding="utf-8")
            customers_path.write_text("customer_id,city\nC1,北京\nC2,上海\nC3,北京\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets([orders_path, customers_path], original_filenames=["orders.csv", "customers.csv"])
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪个城市总销售额最高？")

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual([{"city": "北京", "sales": 170}], response["result"]["rows"])
        self.assertIn("orders.customer_id", response["answer"])
        self.assertIn("customers.customer_id", response["answer"])
        self.assertNotIn("当前结果表只返回", response["answer"])
        self.assertNotIn("仍需按当前数据范围和指标口径解读", response["answer"])

    def test_message_untrusted_join_key_explains_candidate_link(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            orders_path = root / "orders.csv"
            customers_path = root / "customers.csv"
            orders_path.write_text("customer_id,sales\nC1,100\nC2,120\n", encoding="utf-8")
            customers_path.write_text("customer_id,city\nX1,北京\nX2,上海\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets([orders_path, customers_path], original_filenames=["orders.csv", "customers.csv"])
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪个城市总销售额最高？")

        self.assertFalse(response["success"])
        self.assertFalse(response["verification"]["passed"])
        self.assertIn("orders.customer_id", response["answer"])
        self.assertIn("customers.customer_id", response["answer"])
        self.assertIn("关联", response["answer"])

    def test_message_same_schema_union_product_ranking_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            a_path = root / "qa_store_a.csv"
            b_path = root / "qa_store_b.csv"
            a_path.write_text("store,product,sales\nA店,苹果,100\nA店,香蕉,70\n", encoding="utf-8")
            b_path.write_text("store,product,sales\nB店,苹果,80\nB店,香蕉,90\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets([a_path, b_path], original_filenames=["qa_store_a.csv", "qa_store_b.csv"])
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="A店和B店合起来哪个产品销售额最高？")

        self.assertTrue(response["success"], response["errors"])
        self.assertTrue(response["verification"]["passed"], response["verification"])
        self.assertEqual([{"product": "苹果", "sales": 180}], response["result"]["rows"])
        self.assertEqual(["qa_store_a", "qa_store_b"], response["debug"]["source_tables"])
        self.assertIn("same_schema_union", response["debug"]["table_selection_reason"])
        self.assertNotIn("__same_schema_union__", response["answer"])

    def test_message_monthly_trend_uses_month_dimension_for_chart_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            csv_path.write_text(
                "month,city,sales\n"
                "2026-01,上海,100\n"
                "2026-01,北京,250\n"
                "2026-02,广州,180\n",
                encoding="utf-8",
            )
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="sales.csv")
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="按月份展示销售额趋势，生成折线图。")

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual("month", response["logic_form"]["parameters"]["dimension"])
        self.assertEqual({"2026-01": 350, "2026-02": 180}, {row["month"]: row["sales"] for row in response["result"]["rows"]})
        self.assertEqual("line", response["chart"]["chart_type"])
        self.assertEqual("month", response["chart"]["x"])
        self.assertEqual({"2026-01": 350, "2026-02": 180}, {row["month"]: row["sales"] for row in response["chart"]["data"]})
        self.assertNotIn("city", response["chart"]["data"][0])

    def test_message_missing_channel_dimension_does_not_fallback_to_city(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            csv_path.write_text("city,sales\n北京,280\n上海,100\n", encoding="utf-8")
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_dataset(csv_path, original_filename="sales.csv")
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪个渠道销售额最高？")

        self.assertFalse(response["success"])
        self.assertFalse(response["verification"]["passed"])
        self.assertNotEqual("city", response["logic_form"]["parameters"].get("dimension"))
        self.assertIn("渠道", response["answer"])
        self.assertNotIn("北京 280", response["answer"])

    def test_message_category_join_uses_products_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            orders_path, products_path, customers_path = _write_order_product_customer_files(root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(
                [orders_path, products_path, customers_path],
                original_filenames=["orders.csv", "products.csv", "customers.csv"],
            )
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="哪个品类总销售额最高？")

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual([{"category": "水果", "sales": 180}], response["result"]["rows"])
        self.assertEqual("category", response["logic_form"]["parameters"]["dimension"])
        self.assertIn("products", response["debug"]["source_tables"])
        self.assertTrue(response["debug"]["join_plan"]["trusted"])

    def test_message_category_join_with_city_filter_uses_customers_and_products(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            orders_path, products_path, customers_path = _write_order_product_customer_files(root)
            service = DataAgentService(file_store=TempFileStore(root / "storage"), llm_client=MockLLMClient())
            upload = service.upload_datasets(
                [orders_path, products_path, customers_path],
                original_filenames=["orders.csv", "products.csv", "customers.csv"],
            )
            response = service.respond_to_message(dataset_id=upload["dataset_id"], question="北京哪个品类销售额最高？")

        self.assertTrue(response["success"], response["errors"])
        self.assertEqual([{"category": "零食", "sales": 120}], response["result"]["rows"])
        self.assertEqual({"city": "北京"}, response["logic_form"]["filters"])
        self.assertEqual({"orders", "products", "customers"}, set(response["debug"]["source_tables"]))
        self.assertTrue(response["debug"]["join_plan"]["trusted"])
        self.assertEqual(2, len(response["debug"]["join_plan"]["steps"]))


def _write_order_product_customer_files(root: Path) -> tuple[Path, Path, Path]:
    orders_path = root / "orders.csv"
    products_path = root / "products.csv"
    customers_path = root / "customers.csv"
    orders_path.write_text(
        "order_id,customer_id,product_id,sales\n"
        "O1,C1,P1,100\n"
        "O2,C2,P2,80\n"
        "O3,C1,P3,120\n",
        encoding="utf-8",
    )
    products_path.write_text("product_id,category\nP1,水果\nP2,水果\nP3,零食\n", encoding="utf-8")
    customers_path.write_text("customer_id,city\nC1,北京\nC2,上海\n", encoding="utf-8")
    return orders_path, products_path, customers_path


if __name__ == "__main__":
    unittest.main()
