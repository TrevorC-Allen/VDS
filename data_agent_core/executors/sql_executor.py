"""SQL executor boundary for AnalysisPlan execution.

TODO:
- Translate AnalysisPlan into SQL for DuckDB-backed analysis.
- Execute against registered temporary tables.
- Return ExecutionResult in the same shape as the Pandas path.
- Avoid reinterpreting user questions inside the executor.
"""
