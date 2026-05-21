"""Correction loop boundary for controlled self-correction.

TODO:
- Limit correction to at most two attempts.
- First attempt should address fields, types, and aggregation issues.
- Second attempt should address logic, sorting, and filtering issues.
- Return failure reasons instead of fabricating conclusions.
- Never bypass Verifier.
"""
