"""Tests for changelog GPT-like audit utilities."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import run_changelog_gpt_like_audit as audit


class _FakeAuditJudge:
    def complete_json(self, messages: list[dict[str, str]], temperature: float = 0.0) -> dict[str, object]:
        content = messages[-1]["content"]
        if "docs/test-runs" in content:
            return {
                "overall": "pass",
                "severity": "none",
                "reason": "有测试文档和 GPT-like 证据。",
                "required_followup": "",
            }
        return {
            "overall": "fail",
            "severity": "P1",
            "reason": "缺少测试运行文档。",
            "required_followup": "补充 docs/test-runs 证据。",
        }


class ChangelogGPTLikeAuditTest(unittest.TestCase):
    def test_parse_changelog_records_returns_newest_first(self) -> None:
        text = """# AI CHANGELOG

2026-05-26 10:50 CST

### 本次目标

旧记录。

2026-05-26 13:14 CST

### 本次目标

新记录。
"""
        records = audit.parse_changelog_records(text)

        self.assertEqual(["2026-05-26 13:14 CST", "2026-05-26 10:50 CST"], [record["timestamp"] for record in records])
        self.assertIn("新记录", records[0]["body"])

    def test_deterministic_audit_flags_missing_test_run_doc(self) -> None:
        record = {
            "timestamp": "2026-05-26 13:14 CST",
            "body": """2026-05-26 13:14 CST

### 本次目标

优化 GPT-like overview。

### 修改文件

- frontend/app.js

### 修改内容

新增 GPT-like 展示。

### 测试方式

- API smoke

### 测试结果

- OK

### 是否已同步 README

否，未改契约。
""",
        }

        result = audit.deterministic_record_audit(record)

        self.assertFalse(result["passed"])
        self.assertEqual("P1", result["severity"])
        issues = {item["issue"] for item in result["issues"]}
        self.assertIn("missing_test_run_document_reference", issues)

    def test_audit_record_combines_llm_and_deterministic_results(self) -> None:
        record = {
            "timestamp": "2026-05-26 13:14 CST",
            "body": """2026-05-26 13:14 CST

### 本次目标

优化 GPT-like overview。

### 修改文件

- docs/test-runs/2026-05-26-1314.md

### 修改内容

按能力族补充 GPT-like 对比和同类泛化验证。

### 测试方式

- API smoke

### 测试结果

- OK，docs/test-runs/2026-05-26-1314.md 已记录。

### 是否已同步 README

README 无需更新，原因已记录。
""",
        }

        row = audit.audit_record(record, _FakeAuditJudge())

        self.assertEqual("pass", row["overall"])
        self.assertEqual("none", row["severity"])

    def test_run_changelog_audit_writes_docs(self) -> None:
        changelog = """# AI CHANGELOG

2026-05-26 13:14 CST

### 本次目标

优化 GPT-like overview。

### 修改文件

- docs/test-runs/2026-05-26-1314.md

### 修改内容

按能力族补充 GPT-like 对比和同类泛化验证。

### 测试方式

- API smoke

### 测试结果

- OK，docs/test-runs/2026-05-26-1314.md 已记录。

### 是否已同步 README

README 无需更新，原因已记录。
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "CHANGELOG_AI.md"
            path.write_text(changelog, encoding="utf-8")
            (root / "out").mkdir()
            (root / "docs").mkdir()

            report = audit.run_changelog_audit(
                changelog_path=path,
                limit=5,
                output_dir=root / "out",
                doc_dir=root / "docs",
                run_id="2026-05-26-1330-changelog-gpt-like",
                judge_client=_FakeAuditJudge(),
            )

            self.assertEqual("pass", report["status"])
            self.assertTrue((root / "out" / "summary.json").exists())
            self.assertTrue((root / "out" / "changelog_audit.jsonl").exists())
            doc = root / "docs" / "2026-05-26-1330-changelog-gpt-like.md"
            self.assertTrue(doc.exists())
            self.assertIn("required durable changelog-audit evidence", doc.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
