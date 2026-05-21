"""Error type draft list for the Data Agent.

TODO:
- Convert this draft list into stable enum-like values in a future phase.
- Use these types in every module failure instead of returning ad hoc strings.
- Keep Benchmark error attribution, Verifier, and Correction Loop aligned.

Draft error types:
- FILE_PARSE_ERROR
- SCHEMA_INFERENCE_ERROR
- COLUMN_MAPPING_ERROR
- INTENT_PARSE_ERROR
- LOGIC_FORM_ERROR
- PLAN_GENERATION_ERROR
- PANDAS_EXECUTION_ERROR
- SQL_EXECUTION_ERROR
- RESULT_MISMATCH_ERROR
- VERIFICATION_FAILED
- CHART_CONFIG_ERROR
- INSIGHT_UNSUPPORTED
- BENCHMARK_EVALUATION_ERROR
- SECURITY_VIOLATION
"""
