from __future__ import annotations

import unittest
import re
import pandas as pd

from data_agent_core.contracts.analysis_contracts import LogicForm, UserQuestion
from data_agent_core.contracts.execution_contracts import ExecutionResult
from data_agent_core.core.analysis_planner import build_analysis_plan
from data_agent_core.core.conversation_actions import build_analysis_context, plan_followup_actions
from data_agent_core.task_contract_builder import apply_referent_contract
from data_agent_core.executors.pandas_executor import execute_plan
from data_agent_core.oracle_results import build_oracle_result
from data_agent_core.output.response_builder import build_response
from data_agent_core.task_execution_contracts import TaskExecutionContract, build_task_execution_contract
from data_agent_core.verifier.rule_checker import verify_execution


class MultiFileJoinTrendFollowupUsesPreviousTopObjects(unittest.TestCase):
    def test_topn_first_turn_uses_join_and_stores_join_artifact_fields(self) -> None:
        first_turn = _run_topn_first_turn()

        self.assertIsNotNone(first_turn['top_artifact'])
        self.assertIn('top_objects', first_turn['top_artifact'])
        self.assertIn('source_tables', first_turn['top_artifact'])
        self.assertIn('join_plan', first_turn['top_artifact'])
        self.assertIn('join_keys', first_turn['top_artifact'])

        top_artifact = first_turn['top_artifact']
        self.assertEqual(["orders", "customers"], top_artifact['source_tables'])
        self.assertEqual(_join_plan(), top_artifact['join_plan'])
        self.assertEqual(3, len(top_artifact['top_objects']))
        self.assertEqual(['深圳', '北京', '上海'], [item['value'] for item in top_artifact['top_objects']])
        join_keys = top_artifact['join_keys']
        self.assertTrue(isinstance(join_keys, (dict, list, tuple)))
        join_key_lines = [str(item) for item in (join_keys if isinstance(join_keys, (list, tuple)) else [join_keys])]
        join_key_text = ' '.join(join_key_lines)
        self.assertIn('orders', join_key_text)
        self.assertIn('customers', join_key_text)
        self.assertIn('customer_id', join_key_text)
        self.assertTrue(any('customer_id' in str(item) for item in join_key_lines))
        self.assertTrue(any('orders' in str(item) and 'customers' in str(item) and 'customer_id' in str(item) for item in join_key_lines))
        # top_objects must保留维度值（city），而非 customer_id
        top_object_cities = [item.get('city') for item in top_artifact['top_objects']]
        top_object_customer_ids = [item.get('customer_id') for item in top_artifact['top_objects']]
        self.assertTrue(all(city is not None for city in top_object_cities))
        self.assertTrue(all(customer_id is None for customer_id in top_object_customer_ids))

    def test_trend_followup_inherits_top3_city_scope_and_runs_city_month_series(self) -> None:
        first_turn = _run_topn_first_turn()
        actions = plan_followup_actions("这些 Top 城市按月份的订单金额趋势怎么样？", first_turn['context'])
        self.assertEqual(1, len(actions))

        contract = actions[0]['referent_contract']
        self.assertEqual(['orders', 'customers'], contract['inherited_parameters']['source_tables'])
        self.assertEqual(_join_plan(), contract['inherited_parameters']['join_plan'])
        self.assertIn('referent_dimension', contract)
        self.assertIn(contract['referent_dimension'], ['city', 'customer_city'])
        self.assertIn(contract.get('action_parameters', {}).get('metric', ''), ['amount', 'order_amount'])
        self.assertEqual(3, len(contract['referent_values']))
        self.assertEqual(['深圳', '北京', '上海'], contract['referent_values'])

        trend = _run_trend_followup(contract)
        self.assertEqual({'city', 'month', 'order_amount'}, set(trend['result'].columns))
        self.assertIn('series_dimension', trend['logic'].parameters)
        self.assertEqual('city', trend['logic'].parameters['series_dimension'])
        self.assertEqual(6, len(trend['result'].rows))
        trend_rows = trend['result'].rows
        self.assertIsNotNone(trend_rows)
        rows = trend_rows if isinstance(trend_rows, list) else []
        self.assertEqual(6, len(rows))
        for row in rows:
            self.assertIn('city', row)
            self.assertIn('month', row)
            self.assertIn('order_amount', row)
            self.assertNotIn('customer_id', row)
            self.assertIn(row['city'], ['深圳', '北京', '上海'])
            self.assertRegex(str(row['month']), r"^\d{4}-\d{2}$")
        unique_cities = {str(row['city']) for row in rows}
        unique_months = {str(row['month']) for row in rows}
        self.assertEqual({'深圳', '北京', '上海'}, unique_cities)
        self.assertTrue(len(unique_cities) >= 3)
        self.assertTrue(len(unique_months) >= 2)
        self.assertEqual(6, len(set((str(row['city']), str(row['month'])) for row in rows)))

        self.assertTrue(trend['verification'].passed, trend['verification'].semantic_verification_notes)
        self.assertEqual("trend", trend['verification'].task_contract['task_family'])
        self.assertIn(trend['verification'].task_contract['metric'], ['amount', 'order_amount'])
        self.assertEqual('month', trend['verification'].task_contract['time_dimension'])
        self.assertEqual(['深圳', '北京', '上海'], trend['verification'].task_contract['referent_values'])
        self.assertIn(trend['verification'].task_contract['referent_dimension'], ['city', 'customer_city'])
        self.assertNotIn({'city': '广州', 'order_amount': 80, 'month': '2026-01'}, rows)

    def test_trend_contract_layer_requires_referent_time_metric_and_series_requirements(self) -> None:
        first_turn = _run_topn_first_turn()
        actions = plan_followup_actions("这些 Top 城市按月份的订单金额趋势怎么样？", first_turn['context'])
        contract_payload = actions[0]['referent_contract']

        trend_logic = LogicForm(
            task_type='analysis',
            operation='aggregation',
            metric='order_amount',
            group_by='month',
            filters={},
            parameters={'table': 'orders', 'metric': 'order_amount', 'dimension': 'month', 'aggregation': 'sum'},
            output_format={'answer_type': 'table'},
        )
        apply_referent_contract(trend_logic, contract_payload)

        trend_contract = build_task_execution_contract(trend_logic, question='这些 Top 城市按月份的订单金额趋势怎么样？')
        self.assertIsNotNone(trend_contract)
        assert trend_contract is not None

        self.assertEqual('trend', trend_contract.task_family)
        self.assertTrue(trend_contract.requires_previous_artifact)
        self.assertIn(trend_contract.referent_dimension, ['city', 'customer_city'])
        self.assertEqual(['深圳', '北京', '上海'], trend_contract.referent_values)
        self.assertEqual('month', trend_contract.time_dimension)
        self.assertIn(trend_contract.metric, ['amount', 'order_amount'])
        self.assertEqual(['time_grain', 'metric_series'], trend_contract.required_answer_elements)
        self.assertEqual(['month', 'order_amount'], trend_contract.required_output_columns)
        self.assertTrue(trend_contract.verification_rules['trend_time_series_required'])
        self.assertTrue(trend_contract.verification_rules['trend_description_matches_values'])
        self.assertEqual(['orders', 'customers'], trend_logic.parameters['source_tables'])
        self.assertEqual(_join_plan(), trend_logic.parameters['join_plan'])

    def test_oracle_trend_followup_flags_missing_top_objects_and_missing_time_scope(self) -> None:
        first_turn = _run_topn_first_turn()
        trend = _run_trend_followup(plan_followup_actions("这些 Top 城市按月份的订单金额趋势怎么样？", first_turn['context'])[0]['referent_contract'])

        contract_payload = trend['verification'].task_contract
        assert isinstance(contract_payload, dict)
        contract = _build_trend_contract(contract_payload, question='这些 Top 城市按月份的订单金额趋势怎么样？')
        self.assertIsNotNone(contract)
        self.assertIsNotNone(trend['result'].rows)

        normal_rows = trend['result'].rows or []
        oracle_ok = build_oracle_result(
            contract,
            ExecutionResult(backend='pandas', success=True, columns=['city', 'month', 'order_amount'], rows=list(normal_rows)),
        )
        self.assertTrue(oracle_ok.passed, oracle_ok.diff_summary)
        expected = oracle_ok.expected_result or {}
        actual = oracle_ok.actual_result or {}
        self.assertIsInstance(expected, dict)
        self.assertIsInstance(actual, dict)
        self.assertEqual('trend_followup', expected.get('task_family'))
        self.assertIn('series_by_referent', expected)
        self.assertIsNotNone(expected.get('series_by_referent'))
        expected_series = expected.get('series_by_referent') or {}
        self.assertEqual({ '深圳': 2, '北京': 2, '上海': 2}, {city: len(series_points or []) for city, series_points in expected_series.items()})
        self.assertEqual({'深圳', '北京', '上海'}, set(expected_series.keys()))

        # 缺少 Top 城市应失败。
        missing_city_rows = [row for row in trend['result'].rows if row['city'] != '上海']
        missing_city_oracle = build_oracle_result(
            contract,
            ExecutionResult(backend='pandas', success=True, columns=['city', 'month', 'order_amount'], rows=missing_city_rows),
        )
        self.assertFalse(missing_city_oracle.passed)
        self.assertIn('trend_referent_values_missing', missing_city_oracle.issue_codes)
        self.assertTrue(_contains_any_issue_code(missing_city_oracle.issue_codes, ('trend_referent_missing', 'trend_referent_values_missing')))

        # 缺少月度字段应失败（约束链条不能构建完整时间序列约束）。
        missing_month_rows = [{'city': row['city'], 'order_amount': row['order_amount']} for row in trend['result'].rows]
        missing_time_oracle = build_oracle_result(
            contract,
            ExecutionResult(backend='pandas', success=True, columns=['city', 'order_amount'], rows=missing_month_rows),
        )
        self.assertFalse(missing_time_oracle.passed)
        self.assertTrue(
            any(code in missing_time_oracle.issue_codes for code in ('trend_time_dimension_missing', 'trend_time_missing', 'oracle_expected_result_missing')),
            missing_time_oracle.issue_codes,
        )
        self.assertIsNotNone(missing_time_oracle.issue_metadata)
        self.assertIn('missing_expected_result_for_time_series_trend', str(missing_time_oracle.issue_metadata.get('reason')))
        self.assertTrue(_contains_any_issue_code(missing_time_oracle.issue_codes, ('trend_time_missing', 'trend_time_dimension_missing', 'oracle_expected_result_missing')))

        # 若 join scope 丢失到 customer_id 或错误维度，contract 应该提示 referent 缺失。
        wrong_dimension_rows = [
            {'month': row['month'], 'customer_id': row.get('customer_id', 'C_UNKNOWN'), 'order_amount': row['order_amount']}
            for row in trend['result'].rows
        ]
        wrong_scope_oracle = build_oracle_result(
            contract,
            ExecutionResult(backend='pandas', success=True, columns=['month', 'customer_id', 'order_amount'], rows=wrong_dimension_rows),
        )
        self.assertFalse(wrong_scope_oracle.passed)
        self.assertTrue(
            any(code in wrong_scope_oracle.issue_codes for code in ('trend_referent_values_missing', 'trend_wrong_dimension', 'trend_join_scope_missing')),
            wrong_scope_oracle.issue_codes,
        )

        # 包含非 Top3 城市应失败且给出明确的 extra_referent/extra 相关 issue。
        extra_city_rows = list(trend['result'].rows) + [{'city': '广州', 'month': '2026-01', 'order_amount': 80}]
        extra_city_oracle = build_oracle_result(
            contract,
            ExecutionResult(backend='pandas', success=True, columns=['city', 'month', 'order_amount'], rows=extra_city_rows),
        )
        self.assertFalse(extra_city_oracle.passed)
        self.assertTrue(
            _contains_any_issue_code(
                extra_city_oracle.issue_codes,
                (
                    'trend_extra_referent',
                    'trend_extra_referent_values',
                    'trend_wrong_dimension',
                    'trend_referent_values_missing',
                ),
            )
        )

    def test_trend_response_first_sentence_reports_city_month_series_not_global_only(self) -> None:
        first_turn = _run_topn_first_turn()
        trend = _run_trend_followup(plan_followup_actions("这些 Top 城市按月份的订单金额趋势怎么样？", first_turn['context'])[0]['referent_contract'])
        response = trend['response']

        first_sentence = str(response['answer']).split('。', 1)[0]
        self.assertNotIn('这些 Top 对象', first_sentence)
        self.assertNotIn('可以进一步分析', first_sentence)
        self.assertIn('上海', first_sentence)
        self.assertIn('北京', first_sentence)
        self.assertIn('深圳', first_sentence)
        self.assertIn('2026-01', first_sentence)
        self.assertIn('2026-02', first_sentence)
        self.assertRegex(first_sentence, r"\d+(?:\.\d+)?")
        self.assertNotIn('总体', first_sentence)
        self.assertNotIn('整体', first_sentence)
        self.assertNotIn('全局', first_sentence)
        trend_rows = trend['result'].rows or []
        trend_amount_values = sorted({str(row['order_amount']) for row in trend_rows if isinstance(row, dict) and 'order_amount' in row})
        self.assertTrue(any(value in first_sentence for value in trend_amount_values))
        self.assertNotEqual('本次分析对象来自上一轮 Top 结果，共 3 个城市：深圳、北京、上海', first_sentence)


def _run_topn_first_turn() -> dict[str, object]:
    question = '按客户城市统计订单金额 Top 3 是哪些？'
    logic = LogicForm(
        task_type='ranking',
        operation='ranking',
        metric='order_amount',
        group_by='city',
        filters={},
        parameters={
            'table': 'orders',
            'metric': 'order_amount',
            'dimension': 'city',
            'aggregation': 'sum',
            'sort_order': 'desc',
            'limit': 3,
            'join_plan': _join_plan(),
            'source_tables': ['orders', 'customers'],
        },
        source_tables=['orders', 'customers'],
        join_plan=_join_plan(),
        output_format={'answer_type': 'table'},
    )

    plan = build_analysis_plan(logic, question=question)
    result = execute_plan(plan, _analysis_context())
    verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id='ds', question=question))
    response = build_response(
        run_id='run_multifile_topn',
        user_question=UserQuestion(dataset_id='ds', question=question),
        plan=plan,
        execution_result=result,
        verification=verification,
    ).to_dict()
    context = build_analysis_context(
        {
            'success': response['success'],
            'run_id': response['run_id'],
            'dataset_id': 'ds',
            'question': response['question'],
            'logic_form': {
                'task_type': 'ranking',
                'operation': 'ranking',
                'metric': 'order_amount',
                'group_by': 'city',
                'filters': {},
                'parameters': {
                    'table': 'orders',
                    'metric': 'order_amount',
                    'dimension': 'city',
                    'aggregation': 'sum',
                    'sort_order': 'desc',
                    'limit': 3,
                    'join_plan': _join_plan(),
                    'source_tables': ['orders', 'customers'],
                },
                'source_tables': ['orders', 'customers'],
                'join_plan': _join_plan(),
                'output_format': {'answer_type': 'table'},
            },
            'result': {
                'columns': response['result']['columns'],
                'rows': response['result']['rows'],
            },
        },
        original_question=question,
    )

    active_artifacts = [artifact for artifact in context.get('active_result_artifacts', []) if isinstance(artifact, dict) and str(artifact.get('artifact_type') or '') in {'ranking', 'topn'}]
    top_artifact = active_artifacts[0] if active_artifacts else None

    return {
        'question': question,
        'logic': logic,
        'plan': plan,
        'result': result,
        'verification': verification,
        'response': response,
        'context': context,
        'top_artifact': top_artifact,
    }


def _run_trend_followup(contract: dict[str, object]) -> dict[str, object]:
    question = '这些 Top 城市按月份的订单金额趋势怎么样？'
    logic = LogicForm(
        task_type='analysis',
        operation='aggregation',
        metric='order_amount',
        group_by='month',
        filters={},
        parameters={'table': 'orders', 'metric': 'order_amount', 'dimension': 'month', 'aggregation': 'sum'},
        output_format={'answer_type': 'table'},
    )
    apply_referent_contract(logic, contract)

    plan = build_analysis_plan(logic, question=question)
    result = execute_plan(plan, _analysis_context())
    verification = verify_execution(result, plan=plan, user_question=UserQuestion(dataset_id='ds', question=question))
    response = build_response(
        run_id='run_trend_followup',
        user_question=UserQuestion(dataset_id='ds', question=question),
        plan=plan,
        execution_result=result,
        verification=verification,
    ).to_dict()

    return {
        'question': question,
        'logic': logic,
        'plan': plan,
        'result': result,
        'verification': verification,
        'response': response,
    }


def _build_trend_contract(contract: dict[str, object], question: str) -> TaskExecutionContract:
    logic = LogicForm(
        task_type='analysis',
        operation='aggregation',
        metric='order_amount',
        group_by='month',
        filters={},
        parameters={'table': 'orders', 'metric': 'order_amount', 'dimension': 'month', 'aggregation': 'sum'},
        output_format={'answer_type': 'table'},
    )
    apply_referent_contract(logic, contract)
    built_contract = build_task_execution_contract(logic, question=question)
    assert built_contract is not None
    return built_contract


def _analysis_context() -> dict[str, object]:
    return {
        'tables': {
            'orders': _orders_table(),
            'customers': _customers_table(),
        },
        'primary_table': 'orders',
    }


def _orders_table() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {'customer_id': 'C1', 'month': '2026-01', 'order_amount': 100},
            {'customer_id': 'C1', 'month': '2026-02', 'order_amount': 80},
            {'customer_id': 'C2', 'month': '2026-01', 'order_amount': 120},
            {'customer_id': 'C2', 'month': '2026-02', 'order_amount': 90},
            {'customer_id': 'C3', 'month': '2026-01', 'order_amount': 200},
            {'customer_id': 'C3', 'month': '2026-02', 'order_amount': 40},
            {'customer_id': 'C4', 'month': '2026-01', 'order_amount': 80},
            {'customer_id': 'C4', 'month': '2026-02', 'order_amount': 40},
        ]
    )


def _customers_table() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {'customer_id': 'C1', 'city': '上海'},
            {'customer_id': 'C2', 'city': '北京'},
            {'customer_id': 'C3', 'city': '深圳'},
            {'customer_id': 'C4', 'city': '广州'},
        ]
    )


def _join_plan() -> dict[str, object]:
    return {
        'trusted': True,
        'left_table': 'orders',
        'right_table': 'customers',
        'left_key': 'customer_id',
        'right_key': 'customer_id',
        'relationship': 'many_to_one',
    }


def _contains_any_issue_code(issue_codes: list[object] | set[object], candidates: tuple[str, ...]) -> bool:
    normalized = {str(code) for code in issue_codes}
    return any(code in normalized for code in candidates)


if __name__ == '__main__':
    unittest.main()
