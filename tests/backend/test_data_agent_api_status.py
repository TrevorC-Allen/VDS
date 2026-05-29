"""HTTP status behavior for Data Agent API endpoints."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.services.data_agent_service import DataAgentService
from backend.storage.temp_file_store import TempFileStore
import backend.routers.data_agent as data_agent_router
from data_agent_core.llm.client import MockLLMClient
from data_agent_core.tracing.live_monitor import GLOBAL_MONITOR_RUN_ID, live_run_monitor

try:
    from fastapi.testclient import TestClient

    from backend.main import app
except (ImportError, RuntimeError):  # pragma: no cover - optional FastAPI runtime.
    TestClient = None
    app = None


class DataAgentHttpStatusHelperTest(unittest.TestCase):
    def test_missing_dataset_error_maps_to_404(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = DataAgentService(
                file_store=TempFileStore(Path(temp_dir) / "storage"),
                llm_client=MockLLMClient(),
            )
            response = service.respond_to_message(dataset_id="ds_missing", question="哪个城市销售额最高？")

        self.assertEqual(404, data_agent_router._http_status_for_response(response))
        self.assertFalse(response["success"])
        self.assertEqual("FILE_PARSE_ERROR", response["errors"][0]["error_type"])

    def test_verification_failed_clarification_stays_user_visible(self) -> None:
        response = {
            "success": False,
            "answer": "需要先确认 orders.customer_id 和 customers.customer_id 的关联关系。",
            "errors": [{"error_type": "VERIFICATION_FAILED"}],
        }

        self.assertEqual(200, data_agent_router._http_status_for_response(response))

    def test_executor_clarification_stays_user_visible(self) -> None:
        response = {
            "success": False,
            "answer": "这个问题需要先确认跨表关联，不能直接把单表结果当成城市口径。",
            "errors": [{"error_type": "PANDAS_EXECUTION_ERROR"}],
        }

        self.assertEqual(200, data_agent_router._http_status_for_response(response))

    @unittest.skipUnless(hasattr(data_agent_router, "MessagePayload"), "FastAPI route payload is not available.")
    def test_message_route_returns_json_response_with_404_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_service = data_agent_router.service
            data_agent_router.service = DataAgentService(
                file_store=TempFileStore(Path(temp_dir) / "storage"),
                llm_client=MockLLMClient(),
            )
            try:
                response = data_agent_router.message(
                    data_agent_router.MessagePayload(dataset_id="ds_missing", question="哪个城市销售额最高？")
                )
            finally:
                data_agent_router.service = original_service

        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(404, response.status_code)
        self.assertFalse(body["success"])
        self.assertEqual("FILE_PARSE_ERROR", body["errors"][0]["error_type"])


@unittest.skipIf(app is None or TestClient is None, "FastAPI test client is not available.")
class DataAgentApiStatusTest(unittest.TestCase):
    def test_message_missing_dataset_id_returns_404_with_error_body(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            assert data_agent_router is not None
            original_service = data_agent_router.service
            data_agent_router.service = DataAgentService(
                file_store=TempFileStore(Path(temp_dir) / "storage"),
                llm_client=MockLLMClient(),
            )
            try:
                client = TestClient(app)
                response = client.post(
                    "/api/data-agent/message",
                    json={"dataset_id": "ds_missing", "question": "哪个城市销售额最高？"},
                )
            finally:
                data_agent_router.service = original_service

        body = response.json()
        self.assertEqual(404, response.status_code)
        self.assertFalse(body["success"])
        self.assertEqual("FILE_PARSE_ERROR", body["errors"][0]["error_type"])
        self.assertIn("Dataset not found", body["errors"][0]["error_message"])

    def test_monitor_summary_and_health_routes_are_available(self) -> None:
        live_run_monitor.clear(GLOBAL_MONITOR_RUN_ID)
        live_run_monitor.publish(
            GLOBAL_MONITOR_RUN_ID,
            "message_requested",
            title="收到用户消息",
            summary="monitor api smoke",
            stage="message",
            status="completed",
            payload={"question": "smoke"},
        )
        client = TestClient(app)

        summary = client.get("/api/data-agent/monitor/summary")
        health = client.get("/api/data-agent/monitor/health")
        summary_alias = client.get("/api/monitor/summary")
        health_alias = client.get("/api/monitor/health")

        self.assertEqual(200, summary.status_code)
        self.assertEqual(200, health.status_code)
        self.assertEqual(200, summary_alias.status_code)
        self.assertEqual(200, health_alias.status_code)
        self.assertTrue(summary.json()["success"])
        self.assertEqual(GLOBAL_MONITOR_RUN_ID, summary.json()["monitor_run_id"])
        self.assertGreaterEqual(summary.json()["total"], 1)
        self.assertEqual("ok", health.json()["status"])
        self.assertEqual("in_memory_sse", health_alias.json()["transport"])


if __name__ == "__main__":
    unittest.main()
