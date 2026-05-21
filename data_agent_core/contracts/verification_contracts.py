"""Verification contract drafts for result comparison and correction.

TODO:
- Define ComparisonResult, VerificationResult, and CorrectionResult.
- Capture pandas/sql consistency, confidence, issues, correction attempts,
  and non-recoverable failure reasons.
- Keep verification summaries auditable without requiring full Chain of Thought.

Draft structures:
- ComparisonResult: consistent, column_match, row_match, value_match, issues
- VerificationResult: passed, confidence, pandas_sql_consistent, issues, notes
- CorrectionResult: attempted, attempt_count, success, fixed_issues, errors
"""
