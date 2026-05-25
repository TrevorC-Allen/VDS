# VDS Frontend Workbench

Phase 9 static frontend plus Phase 10 result-experience panels for the backend Data Agent API.

It connects to:

- `POST /api/data-agent/upload`
- `POST /api/data-agent/upload-batch`
- `POST /api/data-agent/message`
- `GET /api/data-agent/conversations`
- `GET /api/data-agent/conversations/{conversation_id}`
- `PATCH /api/data-agent/conversations/{conversation_id}`

The frontend only handles upload, message submission, per-turn assistant rendering, chart display from backend `chart`, insight rendering, a user-facing process timeline, safe monitor-event display, and conversation history display. Run history now uses backend `conversation_id` records: page load fetches the conversation list, selecting a history item restores saved user/assistant messages, and rename calls the backend PATCH endpoint. When `chart.image_data_uri` is present, the workbench displays the backend-rendered image directly; frontend SVG rendering is only a fallback for chart specs without a backend image. File selection is quiet: the composer shows an attachment chip, but the chat area does not render upload results, profile panels, or upload-error analysis cards. `.json` and `.md` are accepted only so users can upload a complete DAB context package; the browser does not inspect `fees.json`, `merchant_data.json`, or `manual.md`. When the user sends a question, the composer first calls the upload API if needed, then submits one `/api/data-agent/message` request with the current `conversation_id` and optional `monitor_run_id` when available. Backend routing decides whether the message is ordinary chat, dataset overview, or full analysis. Backend audit details such as quality reports, warnings/errors, verification internals, and join-plan traces remain backend/API data and are not shown in the main user shell. The frontend does not implement metrics, joins, scoring, chart selection, anomaly rules, cleaning logic, DAB rule parsing, or data calculation.

Run the backend from the repo root, then open `frontend/index.html` through a static server or serve it from the same host as the API.
