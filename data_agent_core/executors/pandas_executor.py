"""Pandas and NumPy executor boundary.

TODO:
- Execute AnalysisPlan with Pandas / NumPy in a restricted environment.
- Use only whitelisted functions.
- Forbid non-workspace file access, network calls, and dangerous code.
- Run static checks before execution.
- Return ExecutionResult without changing AnalysisPlan or reinterpreting the
  user question.
"""
