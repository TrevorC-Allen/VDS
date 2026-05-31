"""HTTP status behavior for Data Agent API endpoints."""

from __future__ import annotations

import asyncio
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

    @unittest.skipUnless(hasattr(data_agent_router, "MessagePayload"), "FastAPI route payload is not available.")
    def test_message_route_rejects_invalid_agent_mode_with_actionable_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_service = data_agent_router.service
            original_run_store = data_agent_router.run_store
            data_agent_router.service = DataAgentService(
                file_store=TempFileStore(Path(temp_dir) / "storage"),
                llm_client=MockLLMClient(),
            )
            try:
                response = data_agent_router.message(
                    data_agent_router.MessagePayload(question="你好", agent_mode="invalid_mode")
                )
            finally:
                data_agent_router.service = original_service
                data_agent_router.run_store = original_run_store

        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(422, response.status_code)
        self.assertFalse(body["success"])
        self.assertEqual("LOGIC_FORM_ERROR", body["errors"][0]["error_type"])
        self.assertIn("Unsupported agent_mode", body["errors"][0]["error_message"])
        self.assertIn("multi_agent", body["errors"][0]["suggested_fix"])

    @unittest.skipUnless(hasattr(data_agent_router, "MessagePayload"), "FastAPI route payload is not available.")
    def test_sync_message_route_persists_returned_run_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            csv_path.write_text("city,sales\n上海,100\n北京,120\n", encoding="utf-8")
            original_service = data_agent_router.service
            original_run_store = data_agent_router.run_store
            data_agent_router.service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )
            try:
                upload = data_agent_router.service.upload_dataset(csv_path, original_filename="sales.csv")
                response = data_agent_router.message(
                    data_agent_router.MessagePayload(dataset_id=upload["dataset_id"], question="哪个城市销售额最高？")
                )
                body = json.loads(response.body.decode("utf-8"))
                run_id = body["run_id"]
                status_body = json.loads(data_agent_router.get_run(run_id).body.decode("utf-8"))
                result_body = json.loads(data_agent_router.get_run_result(run_id).body.decode("utf-8"))
            finally:
                data_agent_router.service = original_service
                data_agent_router.run_store = original_run_store

        self.assertEqual(200, response.status_code)
        self.assertTrue(body["success"], body.get("errors"))
        self.assertTrue(run_id.startswith("run_"))
        self.assertTrue(status_body["success"])
        self.assertEqual("completed", status_body["run"]["status"])
        self.assertTrue(status_body["run"]["result_available"])
        self.assertTrue(result_body["success"])
        self.assertEqual(run_id, result_body["result"]["run_id"])
        self.assertEqual(body["answer"], result_body["result"]["answer"])

    @unittest.skipUnless(hasattr(data_agent_router, "_create_message_job"), "Async message job helper is not available.")
    def test_message_job_returns_nested_run_id_and_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "sales.csv"
            csv_path.write_text("city,sales\n上海,100\n北京,120\n", encoding="utf-8")
            original_service = data_agent_router.service
            original_run_store = data_agent_router.run_store
            data_agent_router.service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )

            async def run_job() -> tuple[dict[str, object], str, dict[str, object], object, dict[str, object]]:
                upload = data_agent_router.service.upload_dataset(csv_path, original_filename="sales.csv")
                body = await data_agent_router._create_message_job(
                    {"dataset_id": upload["dataset_id"], "question": "哪个城市销售额最高？"}
                )
                run_id = body["run"]["run_id"]
                status_body: dict[str, object] = {}
                for _ in range(50):
                    status_body = json.loads(data_agent_router.get_run(run_id).body.decode("utf-8"))
                    if status_body.get("run", {}).get("status") == "completed":
                        break
                    await asyncio.sleep(0.05)
                result_response = data_agent_router.get_run_result(run_id)
                result_body = json.loads(result_response.body.decode("utf-8"))
                return body, run_id, status_body, result_response, result_body

            try:
                body, run_id, status_body, result_response, result_body = asyncio.run(run_job())
            finally:
                data_agent_router.service = original_service
                data_agent_router.run_store = original_run_store

        self.assertTrue(body["success"], body.get("errors"))
        self.assertNotIn("run_id", body)
        self.assertTrue(run_id.startswith("run_"))
        self.assertTrue(status_body["success"])
        self.assertEqual("completed", status_body["run"]["status"])
        self.assertTrue(status_body["run"]["result_available"])
        self.assertEqual(200, result_response.status_code)
        self.assertTrue(result_body["success"])
        self.assertEqual(run_id, result_body["result"]["run_id"])

    @unittest.skipUnless(hasattr(data_agent_router, "MessagePayload"), "FastAPI route payload is not available.")
    def test_legacy_sync_message_run_recovers_from_conversation_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_service = data_agent_router.service
            original_run_store = data_agent_router.run_store
            data_agent_router.service = DataAgentService(
                file_store=TempFileStore(root / "storage"),
                llm_client=MockLLMClient(),
            )
            try:
                run_id = "run_legacy_sync_message"
                legacy_response = {
                    "response_version": "v1",
                    "success": True,
                    "run_id": run_id,
                    "dataset_id": "ds_legacy",
                    "question": "哪个城市销售额最高？",
                    "answer_type": "table",
                    "answer": "上海销售额最高。",
                    "result": {"columns": ["city", "sales"], "rows": [{"city": "上海", "sales": 200}]},
                }
                data_agent_router.service.conversation_store.append_turn(
                    question="哪个城市销售额最高？",
                    response=legacy_response,
                    dataset_id="ds_legacy",
                )

                status_response = data_agent_router.get_run(run_id)
                result_response = data_agent_router.get_run_result(run_id)
                status_body = json.loads(status_response.body.decode("utf-8"))
                result_body = json.loads(result_response.body.decode("utf-8"))
            finally:
                data_agent_router.service = original_service
                data_agent_router.run_store = original_run_store

        self.assertEqual(200, status_response.status_code)
        self.assertTrue(status_body["success"])
        self.assertEqual("completed", status_body["run"]["status"])
        self.assertTrue(status_body["run"]["result_available"])
        self.assertEqual("ds_legacy", status_body["run"]["dataset_id"])
        self.assertEqual(200, result_response.status_code)
        self.assertTrue(result_body["success"])
        self.assertEqual(run_id, result_body["result"]["run_id"])
        self.assertEqual("上海销售额最高。", result_body["result"]["answer"])


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

    def test_message_job_rejects_invalid_agent_mode_immediately(self) -> None:
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
                    "/api/data-agent/message/jobs",
                    json={"question": "你好", "agent_mode": "invalid_mode"},
                )
            finally:
                data_agent_router.service = original_service

        body = response.json()
        self.assertEqual(422, response.status_code)
        self.assertFalse(body["success"])
        self.assertEqual("LOGIC_FORM_ERROR", body["errors"][0]["error_type"])
        self.assertIn("Unsupported agent_mode", body["errors"][0]["error_message"])

    def test_message_job_rejects_missing_dataset_immediately(self) -> None:
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
                    "/api/data-agent/message/jobs",
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
