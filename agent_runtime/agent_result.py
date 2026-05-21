"""Internal Agent result contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agent_runtime.agent_role import AgentRole


@dataclass
class AgentResult:
    """Serializable output from an internal agent or adapter step."""

    task_id: str
    role: AgentRole
    success: bool
    output_payload: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready result dict."""

        data = asdict(self)
        data["role"] = self.role.value
        return data
