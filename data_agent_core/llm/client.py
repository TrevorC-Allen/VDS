"""OpenAI-compatible LLM client for structured planning.

API keys are read from environment variables only. They must never be written
to repo files, docs, traces, or logs.
"""

from __future__ import annotations

import json
import os
import http.client
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


class LLMClient(Protocol):
    """Protocol for chat-completion clients used by the planner."""

    def complete_json(self, messages: list[dict[str, str]], temperature: float = 0.0) -> dict[str, Any]:
        """Return a parsed JSON object from chat messages."""


@dataclass(frozen=True)
class LLMConfig:
    """Runtime LLM configuration loaded from environment variables."""

    provider: str
    api_key: str
    model: str
    base_url: str
    timeout_seconds: int = 60
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0


class MissingLLMConfigError(RuntimeError):
    """Raised when no runtime LLM key is configured."""


class OpenAICompatibleChatClient:
    """Minimal OpenAI-compatible /chat/completions client using stdlib only."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def complete_json(self, messages: list[dict[str, str]], temperature: float = 0.0) -> dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        payload_bytes = json.dumps(payload).encode("utf-8")
        attempts = max(1, self.config.max_retries + 1)
        for attempt_index in range(attempts):
            request = urllib.request.Request(
                url=self.config.base_url.rstrip("/") + "/chat/completions",
                data=payload_bytes,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if _is_retryable_http_status(exc.code) and attempt_index < attempts - 1:
                    _sleep_before_llm_retry(attempt_index, self.config.retry_backoff_seconds)
                    continue
                raise RuntimeError(f"LLM HTTP error {exc.code}: {body[:500]}") from exc
            except _TRANSIENT_LLM_ERRORS as exc:
                if attempt_index < attempts - 1:
                    _sleep_before_llm_retry(attempt_index, self.config.retry_backoff_seconds)
                    continue
                raise RuntimeError(
                    f"LLM transient error after {attempts} attempts: {type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        content = data["choices"][0]["message"]["content"]
        return _parse_json_content(content)


class MockLLMClient:
    """Test-only client that returns a deterministic empty planning marker."""

    def complete_json(self, messages: list[dict[str, str]], temperature: float = 0.0) -> dict[str, Any]:
        stage_name = "analysis_planner"
        try:
            payload = json.loads(messages[-1]["content"])
            if isinstance(payload, dict) and payload.get("stage_name"):
                stage_name = str(payload["stage_name"])
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            pass
        return {
            "stage_name": stage_name,
            "task_type": "llm_mock",
            "operation": "use_guardrail_plan",
            "filters": {},
            "parameters": {},
            "output_format": {},
            "confidence": 0.0,
            "reasoning_summary": f"Mock LLM stage {stage_name} was called for test wiring.",
        }


def load_llm_client_from_env() -> LLMClient:
    """Create an LLM client from environment variables."""

    provider = os.environ.get("VDS_LLM_PROVIDER", "").strip().lower()
    if provider == "mock":
        return MockLLMClient()

    if not provider:
        if os.environ.get("DEEPSEEK_API_KEY"):
            provider = "deepseek"
        elif os.environ.get("OPENAI_API_KEY"):
            provider = "openai"

    if provider == "deepseek":
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise MissingLLMConfigError("DEEPSEEK_API_KEY is required when VDS_LLM_PROVIDER=deepseek.")
        return OpenAICompatibleChatClient(
            LLMConfig(
                provider="deepseek",
                api_key=key,
                model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
                base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
                timeout_seconds=int(os.environ.get("VDS_LLM_TIMEOUT_SECONDS", "60")),
                max_retries=int(os.environ.get("VDS_LLM_MAX_RETRIES", "3")),
                retry_backoff_seconds=float(os.environ.get("VDS_LLM_RETRY_BACKOFF_SECONDS", "1.0")),
            )
        )

    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise MissingLLMConfigError("OPENAI_API_KEY is required when VDS_LLM_PROVIDER=openai.")
        return OpenAICompatibleChatClient(
            LLMConfig(
                provider="openai",
                api_key=key,
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                timeout_seconds=int(os.environ.get("VDS_LLM_TIMEOUT_SECONDS", "60")),
                max_retries=int(os.environ.get("VDS_LLM_MAX_RETRIES", "3")),
                retry_backoff_seconds=float(os.environ.get("VDS_LLM_RETRY_BACKOFF_SECONDS", "1.0")),
            )
        )

    raise MissingLLMConfigError(
        "Set VDS_LLM_PROVIDER=openai or deepseek and provide the matching API key environment variable."
    )


_TRANSIENT_LLM_ERRORS = (
    http.client.IncompleteRead,
    http.client.RemoteDisconnected,
    TimeoutError,
    socket.timeout,
    urllib.error.URLError,
    ConnectionError,
)


def _is_retryable_http_status(status_code: int) -> bool:
    return status_code in {408, 409, 425, 429} or 500 <= status_code <= 599


def _sleep_before_llm_retry(attempt_index: int, retry_backoff_seconds: float) -> None:
    if retry_backoff_seconds <= 0:
        return
    time.sleep(min(retry_backoff_seconds * (2**attempt_index), 8.0))


def _parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("LLM response must be a JSON object.")
    return data
