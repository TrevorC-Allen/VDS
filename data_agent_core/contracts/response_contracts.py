"""Response contract drafts for API-facing final results.

TODO:
- Define InsightResult, ChartSpec, and FinalResponse.
- Ensure every API response includes response_version, warnings, and errors.
- Ensure analyze responses include run_id and stable fields for frontend use.
- Keep debug optional and unstable; frontend must not depend on it.

Draft structures:
- InsightResult: summary, key_numbers, suggestions, caveats, next_questions
- ChartSpec: chart_type, x, y, title, data, reason
- FinalResponse: response_version, success, run_id, dataset_id, question,
  answer_type, execution_mode, logic_form, result, verification, insight,
  chart, warnings, errors, debug
"""
