"""Static checks for the backend-mounted workbench shell."""

from __future__ import annotations

import unittest
from pathlib import Path


class WorkbenchStaticAssetsTest(unittest.TestCase):
    def test_workbench_uses_backend_mounted_asset_paths(self) -> None:
        html = Path("frontend/index.html").read_text(encoding="utf-8")

        self.assertIn('href="/frontend/styles.css?v=20260525-agent-monitor"', html)
        self.assertIn('href="/frontend/favicon.svg"', html)
        self.assertIn('src="/frontend/app.js?v=20260525-agent-monitor"', html)
        self.assertNotIn('href="./styles.css"', html)
        self.assertNotIn('src="./app.js"', html)

    def test_workbench_assets_are_cache_busted_and_not_cached_by_backend(self) -> None:
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        backend = Path("backend/main.py").read_text(encoding="utf-8")

        self.assertIn("?v=20260525-agent-monitor", html)
        self.assertIn("NO_CACHE_HEADERS", backend)
        self.assertIn('"Cache-Control": "no-store, max-age=0"', backend)
        self.assertIn('"Pragma": "no-cache"', backend)
        self.assertIn('"Expires": "0"', backend)
        self.assertIn("class NoCacheStaticFiles(StaticFiles)", backend)
        self.assertIn("headers=NO_CACHE_HEADERS", backend)

    def test_runtime_sync_preserves_workbench_storage(self) -> None:
        script = Path("scripts/sync_workbench_runtime.sh").read_text(encoding="utf-8")

        self.assertIn('--exclude "/storage/"', script)
        self.assertNotIn('--exclude "storage"', script)
        self.assertIn("--delete", script)

    def test_workbench_chart_svg_overrides_global_icon_svg_size(self) -> None:
        js = Path("frontend/app.js").read_text(encoding="utf-8")
        css = Path("frontend/styles.css").read_text(encoding="utf-8")

        self.assertIn("const displayValues = values.slice(0, horizontal ? 18 : 16)", js)
        self.assertIn("420 / displayValues.length", js)
        self.assertIn(".chart-svg", css)
        self.assertIn("height: auto;", css)
        self.assertIn("max-height: none;", css)
        self.assertIn("min-height: 230px;", css)

    def test_workbench_prefers_backend_rendered_chart_images(self) -> None:
        js = Path("frontend/app.js").read_text(encoding="utf-8")
        css = Path("frontend/styles.css").read_text(encoding="utf-8")

        self.assertIn("chart?.image_data_uri", js)
        self.assertIn("renderChartImage", js)
        self.assertIn('class="chart-image"', js)
        self.assertIn(".chart-image", css)
        self.assertIn("object-fit: contain;", css)

    def test_workbench_uses_chat_first_shell(self) -> None:
        html = Path("frontend/index.html").read_text(encoding="utf-8")

        self.assertIn('aria-label="历史 Chat"', html)
        self.assertIn('id="chat-messages"', html)
        self.assertIn('href="/workbench-monitor"', html)
        self.assertIn('class="composer-shell"', html)
        self.assertIn('class="upload-controls"', html)
        self.assertIn('id="upload-button"', html)
        self.assertIn('accept=".csv,.xlsx,.xls,.json,.md"', html)
        self.assertIn("上传数据文件，然后直接提问", html)
        self.assertIn("支持 CSV、Excel 等数据文件多选", html)
        self.assertNotIn('class="upload-card"', html)
        self.assertNotIn('id="dropzone"', html)
        self.assertNotIn('class="work-grid"', html)
        self.assertNotIn('class="inspector"', html)

    def test_workbench_rule_package_support_stays_backend_routed_and_hidden_from_ui(self) -> None:
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        js = Path("frontend/app.js").read_text(encoding="utf-8")

        self.assertIn('accept=".csv,.xlsx,.xls,.json,.md"', html)
        self.assertNotIn("DAB 规则包", html)
        self.assertNotIn("DAB 规则包", js)
        self.assertIn('"/api/data-agent/upload-batch"', js)
        self.assertNotIn("fees.json", js)
        self.assertNotIn("merchant_data.json", js)
        self.assertNotIn("manual.md", js)

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

        self.assertIn('"/api/data-agent/message"', js)
        self.assertIn('answer_type === "chat"', js)
        self.assertNotIn("!state.datasetId || !question", js)
        self.assertNotIn('state.datasetId ? "/api/data-agent/analyze"', js)
        self.assertIn("当前没有上传数据，我会直接回复可讨论的部分，不编造业务结论。", js)

    def test_workbench_creates_one_assistant_result_per_turn(self) -> None:
        js = Path("frontend/app.js").read_text(encoding="utf-8")
        css = Path("frontend/styles.css").read_text(encoding="utf-8")

        self.assertIn("createAssistantResultMessage", js)
        self.assertIn("cloneNode(true)", js)
        self.assertIn("assistant-result-message", js)
        self.assertIn(".assistant-message.thinking-only .result-panel", css)

    def test_workbench_enter_sends_and_shift_enter_keeps_newline(self) -> None:
        js = Path("frontend/app.js").read_text(encoding="utf-8")

        self.assertIn('addEventListener("keydown", handleQuestionKeydown)', js)
        self.assertIn('event.key !== "Enter" || event.shiftKey || event.isComposing', js)
        self.assertIn("event.preventDefault()", js)
        self.assertIn("runAnalysis()", js)

    def test_workbench_history_items_can_be_renamed(self) -> None:
        js = Path("frontend/app.js").read_text(encoding="utf-8")
        css = Path("frontend/styles.css").read_text(encoding="utf-8")

        self.assertIn("renderHistory()", js)
        self.assertIn("startHistoryRename", js)
        self.assertIn("commitHistoryRename", js)
        self.assertIn("handleHistoryRenameKeydown", js)
        self.assertIn("history-rename-button", js)
        self.assertIn("history-rename-input", js)
        self.assertIn('event.key === "Enter"', js)
        self.assertIn('event.key === "Escape"', js)
        self.assertIn("dataset.cancelRename", js)
        self.assertIn('input.addEventListener("blur"', js)
        self.assertIn('fetch(`/api/data-agent/conversations/${encodeURIComponent(runId)}`', js)
        self.assertIn(".history-item", css)
        self.assertIn(".history-item.active", css)
        self.assertIn(".history-rename-button", css)
        self.assertIn(".history-rename-input", css)
        self.assertIn(".history-item.editing .history-title", css)

    def test_workbench_loads_persistent_conversations(self) -> None:
        js = Path("frontend/app.js").read_text(encoding="utf-8")

        self.assertIn("conversationId", js)
        self.assertIn("loadConversations()", js)
        self.assertIn('"/api/data-agent/conversations?limit=30"', js)
        self.assertIn("loadConversation", js)
        self.assertIn("restoreConversation", js)
        self.assertIn('item.last_answer_type === "chat" ? "chat" : "analysis"', js)
        self.assertIn("conversation_id: state.conversationId", js)
        self.assertIn("updateHistory: false", js)

    def test_workbench_exposes_standalone_agent_monitor_page(self) -> None:
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        monitor_html = Path("frontend/monitor.html").read_text(encoding="utf-8")
        monitor_js = Path("frontend/monitor.js").read_text(encoding="utf-8")
        css = Path("frontend/styles.css").read_text(encoding="utf-8")
        backend = Path("backend/main.py").read_text(encoding="utf-8")

        self.assertIn('href="/workbench-monitor"', html)
        self.assertNotIn('id="monitor-panel"', html)
        self.assertIn("workbench_monitor", backend)
        self.assertIn("monitor.html", backend)
        self.assertIn("Agent 监看", monitor_html)
        self.assertIn('id="monitor-event-list"', monitor_html)
        self.assertIn('src="/frontend/monitor.js?v=20260525-agent-monitor"', monitor_html)
        self.assertIn("monitor_run_id", monitor_js)
        self.assertIn("new EventSource", monitor_js)
        self.assertIn("/api/data-agent/monitor/stream", monitor_js)
        self.assertIn("renderFinalAgentFlow", monitor_js)
        self.assertIn("renderFinalToolCalls", monitor_js)
        self.assertIn("formatJsonPreview", monitor_js)
        self.assertIn(".monitor-dashboard", css)
        self.assertIn(".monitor-json", css)


if __name__ == "__main__":
    unittest.main()
