"""Run trace contract draft for analyze requests.

TODO:
- Define a run trace structure for each /api/data-agent/analyze request.
- Require run_id for every analyze chain.
- Store auditable execution summaries, not full Chain of Thought.

Draft fields:
- run_id
- dataset_id
- question
- logic_form
- analysis_plan
- pandas_result_summary
- sql_result_summary
- verification_result
- correction_attempts
- final_response
- latency_ms
- errors
- warnings
"""
