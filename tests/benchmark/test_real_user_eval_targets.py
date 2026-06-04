from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any, Mapping
import unittest

from scripts.real_user_eval.http_target import HttpEvalTarget, HttpTargetError
from scripts.real_user_eval.service_target import ServiceEvalTarget


FORBIDDEN_KEYS = {"oracle", "expected_facts", "standard_answer", "answer_key", "task_id"}


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(str(key) in FORBIDDEN_KEYS or _contains_forbidden_key(child) for key, child in value.items())
    if isinstance(value, list | tuple):
        return any(_contains_forbidden_key(item) for item in value)
    return False


class FakeService:
    def __init__(self) -> None:
        self.uploads: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []

    def upload_datasets(self, file_paths: list[Path], *, original_filenames: list[str]) -> dict[str, Any]:
        self.uploads.append({"file_paths": file_paths, "original_filenames": original_filenames})
        return {"success": True, "dataset_id": "ds_service", "uploaded_file_count": len(file_paths)}

    def respond_to_message(self, **payload: Any) -> dict[str, Any]:
        self.messages.append(payload)
        return {
            "success": True,
            "run_id": payload.get("run_id") or "run_service",
            "dataset_id": payload.get("dataset_id") or "",
            "conversation_id": payload.get("conversation_id") or "conv_service",
            "answer": "service answer",
        }


class FakeHttpClient:
    def __init__(self) -> None:
        self.uploads: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self.statuses = ["completed"]
        self.result: dict[str, Any] = {
            "success": True,
            "result": {
                "success": True,
                "run_id": "run_nested",
                "dataset_id": "ds_http",
                "conversation_id": "conv_http",
                "answer": "http answer",
            },
        }

    def multipart_upload(self, url: str, files: Any, *, timeout: float) -> dict[str, Any]:
        self.uploads.append({"url": url, "files": files, "timeout": timeout})
        return {"success": True, "dataset_id": "ds_http"}

    def request_json(
        self,
        method: str,
        url: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        self.requests.append({"method": method, "url": url, "payload": payload, "timeout": timeout})
        if url.endswith("/message/jobs"):
            return {"success": True, "run_id": "wrong_top_level", "run": {"run_id": "run_nested", "status": "queued"}}
        if url.endswith("/runs/run_nested") or url.endswith("/runs/run_resume"):
            status = self.statuses.pop(0) if self.statuses else "completed"
            run_id = "run_resume" if url.endswith("/runs/run_resume") else "run_nested"
            return {"success": True, "run": {"run_id": run_id, "status": status, "result_available": status == "completed"}}
        if url.endswith("/runs/run_nested/result") or url.endswith("/runs/run_resume/result"):
            return self.result
        raise AssertionError(f"unexpected request: {method} {url}")


class ErrorHttpClient(FakeHttpClient):
    def __init__(self, status_code: int) -> None:
        super().__init__()
        self.status_code = status_code

    def request_json(
        self,
        method: str,
        url: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        raise HttpTargetError("service unavailable", status_code=self.status_code)


class RealUserEvalTargetsTest(unittest.TestCase):
    def test_service_target_uploads_then_calls_respond_without_oracle_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "sales.csv"
            csv_path.write_text("city,sales\nShanghai,100\n", encoding="utf-8")
            service = FakeService()
            target = ServiceEvalTarget(service)

            result = target.run(
                {
                    "question": "这个表讲什么？",
                    "file_paths": [csv_path],
                    "conversation_id": "conv_existing",
                    "oracle": {"answer": "secret"},
                    "expected_facts": {"city": "Shanghai"},
                    "standard_answer": "secret answer",
                    "metadata": {"answer_key": "hidden"},
                },
                run_id="run_resume_service",
            )

        self.assertTrue(result.success)
        self.assertEqual("service", result.target)
        self.assertEqual("ds_service", result.dataset_id)
        self.assertEqual("run_resume_service", result.run_id)
        self.assertEqual(1, len(service.uploads))
        self.assertEqual(1, len(service.messages))
        self.assertFalse(_contains_forbidden_key(service.messages[0]))
        self.assertEqual("这个表讲什么？", service.messages[0]["question"])
        self.assertEqual("conv_existing", service.messages[0]["conversation_id"])

    def test_http_target_uses_nested_run_id_and_keeps_oracle_out_of_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "sales.csv"
            csv_path.write_text("city,sales\nShanghai,100\n", encoding="utf-8")
            client = FakeHttpClient()
            target = HttpEvalTarget("http://localhost:8000", client=client, poll_interval_seconds=0)

            result = target.run(
                question="分析销售额",
                files=[csv_path],
                oracle={"answer": "secret"},
                expected_facts={"sales": 100},
                standard_answer="secret answer",
            )

        self.assertTrue(result.success)
        self.assertEqual("http", result.target)
        self.assertEqual("run_nested", result.run_id)
        self.assertEqual("run_nested", result.evidence_id)
        message_jobs = [request for request in client.requests if request["url"].endswith("/message/jobs")]
        self.assertEqual(1, len(message_jobs))
        self.assertFalse(_contains_forbidden_key(message_jobs[0]["payload"]))
        self.assertEqual("ds_http", message_jobs[0]["payload"]["dataset_id"])

    def test_http_target_resume_uses_existing_run_evidence_without_upload_or_submit(self) -> None:
        client = FakeHttpClient()
        client.result = {
            "success": True,
            "result": {
                "success": True,
                "run_id": "run_resume",
                "dataset_id": "ds_existing",
                "conversation_id": "conv_existing",
                "answer": "resumed answer",
            },
        }
        target = HttpEvalTarget("http://localhost:8000", client=client, poll_interval_seconds=0)

        result = target.run(question="继续读取结果", resume_run_id="run_resume", dataset_id="ds_existing")

        self.assertTrue(result.success)
        self.assertEqual("run_resume", result.run_id)
        self.assertEqual([], client.uploads)
        self.assertFalse(any(request["url"].endswith("/message/jobs") for request in client.requests))

    def test_http_target_poll_timeout_has_clear_issue(self) -> None:
        client = FakeHttpClient()
        client.statuses = ["running"]
        target = HttpEvalTarget("http://localhost:8000", client=client, poll_interval_seconds=0, max_poll_seconds=0)

        result = target.run(question="分析", dataset_id="ds_http")

        self.assertFalse(result.success)
        self.assertEqual("timeout", result.status)
        self.assertIn("http_poll_timeout", result.issues[0])

    def test_http_target_503_has_clear_issue(self) -> None:
        target = HttpEvalTarget("http://localhost:8000", client=ErrorHttpClient(503), poll_interval_seconds=0)

        result = target.run(question="分析", dataset_id="ds_http")

        self.assertFalse(result.success)
        self.assertIn("HTTP 503", result.issues[0])

    def test_http_target_missing_result_has_clear_issue(self) -> None:
        client = FakeHttpClient()
        client.result = {"success": True}
        target = HttpEvalTarget("http://localhost:8000", client=client, poll_interval_seconds=0)

        result = target.run(question="分析", dataset_id="ds_http")

        self.assertFalse(result.success)
        self.assertEqual("failed", result.status)
        self.assertIn("http_result_missing", result.issues[0])

    def test_service_and_http_result_shapes_match_for_runner(self) -> None:
        service_result = ServiceEvalTarget(FakeService()).run(question="分析", dataset_id="ds_service")
        http_result = HttpEvalTarget("http://localhost:8000", client=FakeHttpClient(), poll_interval_seconds=0).run(
            question="分析",
            dataset_id="ds_http",
        )

        self.assertEqual(list(service_result.to_dict().keys()), list(http_result.to_dict().keys()))


if __name__ == "__main__":
    unittest.main()
