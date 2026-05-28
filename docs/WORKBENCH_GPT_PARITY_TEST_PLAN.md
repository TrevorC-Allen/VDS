# Workbench GPT-like Quality Gate

## Purpose

This document defines the repeatable quality gate for VDS Workbench user-facing behavior. The gate checks whether Workbench answers are actually useful to a user and aligned with the project redlines, rather than merely detailed-looking.

Every formal test run must write a test-run document under `docs/test-runs/`. A command output, chat message, screenshot, or changelog entry is not enough evidence by itself.

## Redlines

1. GPT-like parity is a product acceptance gate, not a visual theme. File understanding, answer structure, table/chart choice, insight, process display, and user-facing wording must be compared against GPT / ChatGPT Data Analysis behavior or frozen GPT-like references.
2. `Not Applicable` must not be a generic fallback. Each occurrence must be attributed to `true_unsupported`, `needs_clarification`, or `capability_gap`.
3. User-visible tests must produce durable documentation. Missing `docs/test-runs/...md` evidence means the test is not accepted.
4. Standard answers, task ids, hidden answers, public proxy answers, raw prompt, raw Chain of Thought, raw trace, and API keys must not enter Agent workflow, LLM judge payloads, reports, or user-facing output.
5. Frontend tests may verify rendering only. The frontend must not calculate metrics, joins, rankings, cleaning rules, benchmark scores, or chart semantics.
6. Chinese questions, Chinese field names, Chinese business wording, and Chinese final answers are primary acceptance paths. English compatibility remains required but cannot replace Chinese validation.
7. Any fix or claimed improvement must map to a reusable capability family and must not depend on current screenshots, fixed field values, fixed prompts, benchmark task ids, or current sample-specific errors.
8. Semantic correctness outranks presentation. `success=true`, empty errors, a nice overview, or GPT-like prose cannot hide a wrong metric, wrong dimension, wrong join, or wrong derived formula.
9. 已修能力不得下降 / non-regression: fixes to overview or answer templates must not regress file targeting, join, charts, cleaning boundaries, Project context, or previously fixed GPT-like output.

## Automation

Run the default quick gate with a real provider:

```bash
VDS_LLM_PROVIDER=deepseek bash scripts/run_vds_llm_quality_gate.sh --suite quick
```

Supported suites:

- `quick`: P0/P1 smoke across chat, overview, TopN, quality, cleaning, multi-file, multi-table, payments-style data, and unsupported boundaries.
- `full`: all configured Workbench cases.
- `api`: API-only Workbench cases.
- `ui`: user-visible UI-facing cases that still run through the API runner unless a browser smoke is added later.
- `changelog`: `CHANGELOG_AI.md` GPT-like evidence audit only.

Every run writes:

- `outputs/llm_quality_gate/<run_id>/summary.json`
- `outputs/llm_quality_gate/<run_id>/responses.jsonl`
- `outputs/llm_quality_gate/<run_id>/llm_judgements.jsonl`
- `outputs/llm_quality_gate/<run_id>/failures.md`
- `outputs/llm_quality_gate/<run_id>/report.md`
- `docs/test-runs/<run_id>.md`

## GPT-like Rubric

The LLM judge must return 0-5 scores for:

- `problem_understanding`: the answer addresses the user's real request.
- `data_grounding`: facts, numbers, columns, and boundaries are grounded in the uploaded data and stable API fields.
- `answer_usefulness`: the answer gives a concrete conclusion, evidence, and next useful action.
- `gpt_like_structure`: the answer is organized like GPT Data Analysis: conclusion first, evidence and table/chart second, boundaries and follow-ups after.
- `safety_boundary`: the answer avoids unsupported certainty, internal leakage, and forbidden artifacts.

The judge also returns:

- `overall`: `pass`, `risk`, or `fail`
- `severity`: `P0`, `P1`, `P2`, `P3`, or `none`
- `reason`
- `required_followup`

Deterministic assertions run before the LLM judge and cannot be overruled by the LLM judge. Examples: expected `answer_type`, required terms, forbidden terms, `Not Applicable`, and obvious internal artifact leakage.

Required semantic assertions for Phase 12 correctness hardening:

- named-file product ranking: `qa_store_b.csv里面哪个产品销售额最高？` must use only `qa_store_b.csv` and return the product, not the store.
- profit-margin ranking: `哪个城市利润率最高？` must use a derived ratio such as `sum(profit)/sum(sales)`, not raw sales or raw profit.
- trusted join: `orders(customer_id,sales)` + `customers(customer_id,city)` must join on `customer_id` before city aggregation when the key is trustworthy.
- untrusted join: when key overlap or relationship is unsafe, the main answer must name the candidate key and risk instead of returning success.
- overview: knowledge base / table description / data structure workbooks must be classified as metadata or knowledge sources, even when parsed as spreadsheet tables.
- simple Top1: short answers must remove audit noise while preserving correctness and source scope.

## Changelog Audit

The changelog audit checks recent functionally meaningful records for:

- minute-precision timestamp
- clear goal and impact surface
- capability-family or user-experience target
- GPT-like comparison evidence
- test commands and test result evidence
- runtime, browser, or API proof for user-visible changes
- README / docs sync statement
- linked or mentioned `docs/test-runs` evidence
- no sign of "looks implemented" without acceptance evidence

Records without test-run documentation are reported as risk or fail. A changelog entry does not substitute for a test-run document.

## Case Format

`configs/eval_gate/workbench_gpt_like_cases.jsonl` contains one JSON object per case:

```json
{
  "id": "CHAT-002",
  "suite": "quick",
  "tags": ["api", "chat"],
  "question": "我能干什么？",
  "dataset_fixture": "sales_cn",
  "expected_answer_type": "chat",
  "must_include": ["可以"],
  "must_not_include": ["Not Applicable", "标准答案"],
  "capability_family": "chat_with_dataset",
  "gpt_like_expectation": "Explain what can be analyzed with the current dataset without entering a failed analysis route.",
  "severity_on_fail": "P0"
}
```

## Failure Severity

- `P0`: wrong conclusion, `Not Applicable` abuse, internal leakage, standard-answer leakage, frontend computation, project context leakage, or raw detail dump in the main answer.
- `P1`: user question unresolved, wrong metric/grain/join/chart, wrong cleaning boundary, or missing GPT-like evidence for a user-visible change.
- `P2`: answer works but is template-like, poorly grounded, weakly structured, or missing useful follow-up.
- `P3`: minor interaction, wording, display, or history metadata issue.

## Acceptance

A run is accepted only if:

- the configured fail threshold is not exceeded,
- every formal run produced `docs/test-runs/<run_id>.md`,
- JSON / JSONL / Markdown evidence was written,
- no raw prompt, raw Chain of Thought, API key, task id, hidden answer, proxy answer, or standard answer entered judge payloads or reports,
- all `Not Applicable` occurrences are attributed and actionable.
