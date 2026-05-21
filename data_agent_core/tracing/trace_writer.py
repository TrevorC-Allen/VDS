"""Trace writer draft for future trace.json persistence.

TODO:
- Write run trace summaries to storage/runs/{run_id}/trace.json in Phase 1 or
  later.
- Keep writes explicit and testable.
- Do not record full Chain of Thought; store structured analysis plan,
  reasoning summary, execution trace, and verification notes only.
"""
