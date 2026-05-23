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


if __name__ == "__main__":
    unittest.main()
