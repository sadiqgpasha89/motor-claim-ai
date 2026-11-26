from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from packages.contracts.agents import (
    AgentInvocationRequest,
    AgentInvocationResponse,
    AgentStatus,
    ConfidenceBand,
    ToolPermissionError,
)
from packages.security.sanitizer import mask_text_pii
from services.agent_runtime.gateway import ModelGateway, ModelOutageError


class BoundedAgent(ABC):
    agent_name: str = "base_agent"
    prompt_version: str = "1.0.0"
    allowed_tools: set[str] = set()
    tool_versions: dict[str, str] = {"core_tools": "1.0.0"}

    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}

    def register_tool(self, name: str, fn: Callable[..., Any]) -> None:
        if name not in self.allowed_tools:
            raise ToolPermissionError(
                f"Cannot bind tool '{name}' to agent '{self.agent_name}': not in allowlist {sorted(self.allowed_tools)}"
            )
        self._tools[name] = fn

    def call_tool(self, name: str, request: AgentInvocationRequest, **kwargs: Any) -> Any:
        if name not in self.allowed_tools or name not in request.allowed_tools:
            raise ToolPermissionError(
                f"Agent '{self.agent_name}' denied tool '{name}'. Allowed={sorted(self.allowed_tools)}"
            )
        if name not in self._tools:
            return {"tool": name, "status": "ok", "kwargs": kwargs}
        return self._tools[name](**kwargs)

    @staticmethod
    def _band(confidence: float) -> ConfidenceBand:
        if confidence >= 0.85:
            return ConfidenceBand.HIGH
        if confidence >= 0.65:
            return ConfidenceBand.MEDIUM
        return ConfidenceBand.LOW

    def execute(self, request: AgentInvocationRequest) -> AgentInvocationResponse:
        model_id, model_version = ModelGateway.get_model_metadata()
        safe_facts = {
            k: mask_text_pii(v) if isinstance(v, str) else v
            for k, v in request.minimised_facts.items()
        }
        safe_req = request.model_copy(update={"minimised_facts": safe_facts})

        try:
            return self._run(safe_req, model_id=model_id, model_version=model_version)
        except ModelOutageError as exc:
            return AgentInvocationResponse(
                agent_name=self.agent_name,
                status=AgentStatus.NEEDS_HUMAN,
                result={"fallback_mode": "manual_workflow", "reason": str(exc)},
                confidence=0.0,
                confidence_band=ConfidenceBand.LOW,
                assumptions=["AI model provider unavailable; deterministic workflow remains active."],
                missing_information=[],
                contradictions=[],
                limitations=["Model gateway outage active; human reviewer must complete this step manually."],
                model_id=model_id,
                model_version=model_version,
                prompt_version=self.prompt_version,
                tool_versions=self.tool_versions,
                rule_versions=request.rule_versions,
                suggested_next_action="route_to_human_queue",
            )

    @abstractmethod
    def _run(
        self, request: AgentInvocationRequest, *, model_id: str, model_version: str
    ) -> AgentInvocationResponse:
        raise NotImplementedError
