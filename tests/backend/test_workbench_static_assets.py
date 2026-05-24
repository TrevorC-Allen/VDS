"""Static checks for the backend-mounted workbench shell."""

from __future__ import annotations

import unittest
from pathlib import Path


class WorkbenchStaticAssetsTest(unittest.TestCase):
    def test_workbench_uses_backend_mounted_asset_paths(self) -> None:
        html = Path("frontend/index.html").read_text(encoding="utf-8")

        self.assertIn('href="/frontend/styles.css"', html)
        self.assertIn('href="/frontend/favicon.svg"', html)
        self.assertIn('src="/frontend/app.js"', html)
        self.assertNotIn('href="./styles.css"', html)
        self.assertNotIn('src="./app.js"', html)

    def test_workbench_uses_chat_first_shell(self) -> None:
        html = Path("frontend/index.html").read_text(encoding="utf-8")

        self.assertIn('aria-label="历史 Chat"', html)
        self.assertIn('id="chat-messages"', html)
        self.assertIn('class="composer-shell"', html)
        self.assertIn('class="upload-controls"', html)
        self.assertIn('id="upload-button"', html)
        self.assertNotIn('class="upload-card"', html)
        self.assertNotIn('id="dropzone"', html)
        self.assertNotIn('class="work-grid"', html)
        self.assertNotIn('class="inspector"', html)

    def test_workbench_hides_backend_audit_panels_from_user_shell(self) -> None:
        html = Path("frontend/index.html").read_text(encoding="utf-8")

        self.assertIn("分析过程", html)
        self.assertNotIn("数据质量", html)
        self.assertNotIn("Join / Verification", html)
        self.assertNotIn("Warnings / Errors", html)
        self.assertNotIn("source_tables", html)
        self.assertNotIn("join_plan", html)
        self.assertNotIn("dataset_id:", html)

    def test_workbench_allows_chat_without_uploaded_dataset(self) -> None:
        js = Path("frontend/app.js").read_text(encoding="utf-8")

        self.assertIn('"/api/data-agent/chat"', js)
        self.assertIn('answer_type === "chat"', js)
        self.assertNotIn("!state.datasetId || !question", js)
        self.assertIn("当前没有上传数据，我会直接回复可讨论的部分，不编造业务结论。", js)


if __name__ == "__main__":
    unittest.main()
