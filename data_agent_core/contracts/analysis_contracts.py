"""Analysis contract drafts for user questions, logic forms, and plans.

TODO:
- Define UserQuestion, LogicForm, and AnalysisPlan as serializable contracts.
- Support future task types: detail_lookup, aggregation, ranking, filtering,
  trend, and comparison.
- Keep logic forms reusable by Pandas Executor, SQL Executor, Verifier,
  Benchmark Runner, Planner Agent, and future framework adapters.

Draft structures:
- UserQuestion: dataset_id, question, execution_mode, requested_at
- LogicForm: task_type, metric, dimension, aggregation, filters, sort, limit
- AnalysisPlan: plan_id, logic_form, steps, expected_result_shape, constraints
"""
