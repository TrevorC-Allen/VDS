"""Data Agent API router boundary.

TODO:
- Reserve POST /api/data-agent/upload.
- Reserve POST /api/data-agent/analyze.
- Reserve GET /api/data-agent/datasets/{dataset_id}/profile.
- Delegate all core analysis to backend.services and data_agent_core.
- Do not implement Pandas, SQL, verifier, or benchmark logic in the router.
"""
