"""Execution contract drafts for Pandas, NumPy, SQL, and DuckDB paths.

TODO:
- Define ExecutionResult as the standard output for every execution backend.
- Ensure Pandas and SQL paths return comparable columns, rows, metadata,
  warnings, and errors.
- Prevent executors from changing AnalysisPlan or reinterpreting the question.

Draft structures:
- ExecutionResult: backend, success, columns, rows, summary, latency_ms,
  warnings, errors, debug
"""
