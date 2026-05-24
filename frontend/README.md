# VDS Frontend Workbench

Phase 9 static frontend plus Phase 10 result-experience panels for the backend Data Agent API.

It connects to:

- `POST /api/data-agent/upload`
- `POST /api/data-agent/upload-batch`
- `POST /api/data-agent/analyze`
- `POST /api/data-agent/chat`

The frontend only handles upload, no-dataset chat entry, question submission, result rendering, chart rendering from backend `chart`, insight rendering, a user-facing process timeline, and run history. File selection is quiet: the composer shows an attachment chip, but the chat area does not render upload results, profile panels, or upload-error analysis cards. When the user sends a question, the composer first calls the upload API if needed, then submits analyze with the returned dataset; if no dataset exists, it calls `/api/data-agent/chat` so VDS can discuss analysis goals or metric definitions without fabricating business results. Backend audit details such as quality reports, warnings/errors, verification internals, and join-plan traces remain backend/API data and are not shown in the main user shell. The frontend does not implement metrics, joins, scoring, chart selection, anomaly rules, cleaning logic, or data calculation.

Run the backend from the repo root, then open `frontend/index.html` through a static server or serve it from the same host as the API.
