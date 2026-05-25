# VDS Frontend Workbench

Phase 9 static frontend plus Phase 10 result-experience panels for the backend Data Agent API.

It connects to:

- `POST /api/data-agent/upload`
- `POST /api/data-agent/upload-batch`
- `POST /api/data-agent/message`
- `POST /api/data-agent/benchmark/run`
- `GET /api/data-agent/conversations`
- `GET /api/data-agent/conversations/{conversation_id}`
- `PATCH /api/data-agent/conversations/{conversation_id}`

The frontend only handles upload, message submission, per-turn assistant rendering, chart display from backend `chart`, insight rendering, a user-facing process timeline from backend `process_view_v2`, safe monitor-event display, and conversation history display. Run history now uses backend `conversation_id` records: page load fetches the conversation list, selecting a history item restores saved user/assistant messages, and rename calls the backend PATCH endpoint. When `chart.image_data_uri` is present, the workbench displays the backend-rendered image directly; frontend SVG rendering is only a fallback for chart specs without a backend image. File selection is quiet: the composer shows an attachment chip, but the chat area does not render upload results, profile panels, or upload-error analysis cards. Rule Mode is hidden under advanced options and uploads user rules as `file_role=rule, rule_scope=user_analysis`; the message request passes only the returned `user_rule_file_id`. Benchmark rules are uploaded separately as `rule_scope=benchmark` and run only through `/api/data-agent/benchmark/run`. `.json` and `.md` are accepted for dataset JSON, complete DAB context packages, or explicit rule uploads; the browser does not inspect `fees.json`, `merchant_data.json`, `manual.md`, or rule contents. When the user sends a question, the composer first calls the upload API if needed, then submits one `/api/data-agent/message` request with the current `conversation_id` and optional `monitor_run_id` when available. Backend routing decides whether the message is ordinary chat, dataset overview, or full analysis. Backend audit details such as quality reports, warnings/errors, verification internals, and join-plan traces remain backend/API data and are not shown in the main user shell. `process_view_v2` is a safe narrative field, not raw Chain of Thought, and the monitor final event only carries run status plus this safe summary instead of full response / trace payloads. The frontend does not implement metrics, joins, scoring, chart selection, anomaly rules, cleaning logic, DAB rule parsing, user rule parsing, Benchmark parsing, process inference, or data calculation.

Run the backend from the repo root, then open `frontend/index.html` through a static server or serve it from the same host as the API.
