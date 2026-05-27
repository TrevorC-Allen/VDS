"""LLM client transport behavior tests."""

from __future__ import annotations

import http.client
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from data_agent_core.llm.client import LLMConfig, OpenAICompatibleChatClient


class _FakeChatResponse:
    def __init__(self, content: str = '{"operation": "ok"}') -> None:
        self._payload = {
            "choices": [
                {
                    "message": {
                        "content": content,
                    }
                }
            ]
        }

    def __enter__(self) -> "_FakeChatResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class OpenAICompatibleChatClientTests(unittest.TestCase):
    def test_retries_transient_incomplete_read(self) -> None:
        calls: list[object] = []

        def fake_urlopen(request: object, timeout: int) -> _FakeChatResponse:
            calls.append((request, timeout))
            if len(calls) == 1:
                raise http.client.IncompleteRead(b"")
            return _FakeChatResponse()

        client = OpenAICompatibleChatClient(
            LLMConfig(
                provider="deepseek",
                api_key="test-key",
                model="deepseek-chat",
                base_url="https://example.test/v1",
                timeout_seconds=7,
                max_retries=2,
                retry_backoff_seconds=0,
            )
        )

        with patch("data_agent_core.llm.client.urllib.request.urlopen", side_effect=fake_urlopen):
            result = client.complete_json([{"role": "user", "content": "{}"}])

        self.assertEqual(result, {"operation": "ok"})
        self.assertEqual(len(calls), 2)

    def test_retries_retryable_http_status(self) -> None:
        calls: list[object] = []

        def fake_urlopen(request: object, timeout: int) -> _FakeChatResponse:
            calls.append((request, timeout))
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    url="https://example.test/v1/chat/completions",
                    code=429,
                    msg="too many requests",
                    hdrs=None,
                    fp=io.BytesIO(b"rate limited"),
                )
            return _FakeChatResponse()

        client = OpenAICompatibleChatClient(
            LLMConfig(
                provider="deepseek",
                api_key="test-key",
                model="deepseek-chat",
                base_url="https://example.test/v1",
                max_retries=1,
                retry_backoff_seconds=0,
            )
        )

        with patch("data_agent_core.llm.client.urllib.request.urlopen", side_effect=fake_urlopen):
            result = client.complete_json([{"role": "user", "content": "{}"}])

        self.assertEqual(result, {"operation": "ok"})
        self.assertEqual(len(calls), 2)

    def test_does_not_retry_non_retryable_http_status(self) -> None:
        calls: list[object] = []

        def fake_urlopen(request: object, timeout: int) -> _FakeChatResponse:
            calls.append((request, timeout))
            raise urllib.error.HTTPError(
                url="https://example.test/v1/chat/completions",
                code=400,
                msg="bad request",
                hdrs=None,
                fp=io.BytesIO(b"bad request body"),
            )

        client = OpenAICompatibleChatClient(
            LLMConfig(
                provider="deepseek",
                api_key="test-key",
                model="deepseek-chat",
                base_url="https://example.test/v1",
                max_retries=3,
                retry_backoff_seconds=0,
            )
        )

        with patch("data_agent_core.llm.client.urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaisesRegex(RuntimeError, "LLM HTTP error 400"):
                client.complete_json([{"role": "user", "content": "{}"}])

        self.assertEqual(len(calls), 1)

    def test_omits_temperature_for_gpt5_family_models(self) -> None:
        payloads: list[dict[str, object]] = []

        def fake_urlopen(request: object, timeout: int) -> _FakeChatResponse:
            payloads.append(json.loads(request.data.decode("utf-8")))  # type: ignore[attr-defined]
            return _FakeChatResponse()

        client = OpenAICompatibleChatClient(
            LLMConfig(
                provider="openai",
                api_key="test-key",
                model="gpt-5.5",
                base_url="https://example.test/v1",
            )
        )

        with patch("data_agent_core.llm.client.urllib.request.urlopen", side_effect=fake_urlopen):
            result = client.complete_json([{"role": "user", "content": "{}"}], temperature=0.2)

        self.assertEqual(result, {"operation": "ok"})
        self.assertNotIn("temperature", payloads[0])


if __name__ == "__main__":
    unittest.main()
