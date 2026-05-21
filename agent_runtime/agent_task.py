"""Internal Agent task contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agent_runtime.agent_role import AgentRole


@dataclass
class AgentTask:
    """Serializable task passed between internal agents or adapters."""

    task_id: str
    role: AgentRole
    input_payload: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready task dict."""

        data = asdict(self)
        data["role"] = self.role.value
        return data
