# Phase 14 P0 File / Semantic / Correction - 2026-05-29

- Status: in progress
- Branch: `codex/vds-p0-file-semantic-correction`
- CWD: `/Users/trevorcui/Documents/VDS`
- Runtime verified: pending
- URL: pending
- Generated at: 2026-05-29 CST

## Scope

本轮实现 Phase 14 首轮 P0 hardening：

- 真实文件理解：Excel sheet/block candidate、表角色、header rows、range、CSV encoding/delimiter/bad-line diagnostics、PDF/图片边界。
- 语义正确性：显式 `sum(numerator)/sum(denominator)` 口径进入 derived metric 和 formula lineage，chart planner 优先绑定 logic form 中的 dimension/metric。
- 多轮纠错：`conversation_id` 可恢复上一轮 dataset 和 logic form；“不是这个口径，用利润率=sum利润/sum销售重新算”会强制重跑并返回 `correction_context`；不完整修正先澄清。
- 前端边界：只展示后端返回的 table role/range 和 correction summary，不实现解析、公式、join、排序或聚合。

## Focused Checks

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.core.test_file_parser -v
```

Result: `Ran 4 tests ... OK`.

```bash
VDS_LLM_PROVIDER=mock /Users/trevorcui/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.backend.test_data_agent_message_semantics -v
```

Result: `Ran 13 tests ... OK`.

```bash
node --check frontend/app.js
```

Result: passed.

## Pending Gates

- Full `scripts/run_tests.py`.
- VDS 95 standard-answer runner.
- Microsoft 300 scorer.
- DAB dev/all mock smoke where runtime budget allows.
- Real `127.0.0.1:8001/workbench` runtime validation.

## Residual Risks

- Excel candidate detection is heuristic and must keep expanding with real files; current support covers vertical blocks, merged-style header rows, rule/notes and field dictionary sheets.
- PDF/image table extraction is intentionally a boundary response unless a text table extractor/OCR path is added later.
- Explicit formula support is ratio-first; nested formulas and multi-metric expressions are future capability families.
