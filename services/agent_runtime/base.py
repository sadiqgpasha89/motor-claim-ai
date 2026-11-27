from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable

from packages.contracts.agents import (
    AgentInvocationRequest,
    AgentInvocationResponse,
    AgentStatus,
    ConfidenceBand,
    DecisionIntelligence,
    ToolPermissionError,
)
from packages.security.sanitizer import mask_text_pii
from services.agent_runtime.actions import ControlledActionExecutor
from services.agent_runtime.gateway import ModelGateway, ModelOutageError


class AgentTimeoutError(Exception):
    """Raised when an agent exceeds its configured execution timeout budget."""


class BoundedAgent(ABC):
    agent_name: str = "base_agent"
    prompt_version: str = "2.0.0"
    allowed_tools: set[str] = set()
    tool_versions: dict[str, str] = {"core_tools": "2.0.0"}

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

    @staticmethod
    def _decision_id(agent_name: str) -> str:
        return f"dec-{agent_name[:6]}-{uuid.uuid4().hex[:8]}"

    def execute(
        self,
        request: AgentInvocationRequest,
        *,
        action_executor: ControlledActionExecutor | None = None,
    ) -> AgentInvocationResponse:
        start = time.perf_counter()
        model_id, model_version = ModelGateway.get_model_metadata()
        safe_facts = {
            k: mask_text_pii(v) if isinstance(v, str) else v
            for k, v in request.minimised_facts.items()
        }
        safe_req = request.model_copy(update={"minimised_facts": safe_facts})
        executor = action_executor or ControlledActionExecutor()

        try:
            if safe_req.minimised_facts.get("_simulate_timeout"):
                raise AgentTimeoutError(
                    f"Agent '{self.agent_name}' exceeded timeout budget ({safe_req.timeout_seconds}s)"
                )
            response = self._run(
                safe_req,
                model_id=model_id,
                model_version=model_version,
                executor=executor,
            )
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            if not response.published_result:
                response = response.model_copy(update={"published_result": response.result})
            return response.model_copy(
                update={
                    "attempt_number": request.attempt_number,
                    "duration_ms": elapsed_ms,
                }
            )
        except AgentTimeoutError as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return AgentInvocationResponse(
                agent_name=self.agent_name,
                status=AgentStatus.TIMED_OUT,
                result={"fallback_mode": "retry_or_escalate", "reason": str(exc)},
                published_result={"timed_out": True, "reason": str(exc)},
                confidence=0.0,
                confidence_band=ConfidenceBand.LOW,
                limitations=["Execution timed out; orchestrator retry/escalation policy active."],
                decision=DecisionIntelligence(
                    decision_id=self._decision_id(self.agent_name),
                    reason_codes=["RC_AGENT_TIMEOUT"],
                    evidence=[str(exc)],
                    policy_rule_refs=["ORCH-TIMEOUT-RECOVERY-V1"],
                    confidence=0.0,
                    confidence_band=ConfidenceBand.LOW,
                    routing_outcome="retry_or_escalate_human",
                    explanation=f"Agent {self.agent_name} timed out after attempt #{request.attempt_number}.",
                ),
                model_id=model_id,
                model_version=model_version,
                prompt_version=self.prompt_version,
                tool_versions=self.tool_versions,
                rule_versions=request.rule_versions,
                suggested_next_action="retry_or_escalate",
                attempt_number=request.attempt_number,
                duration_ms=elapsed_ms,
            )
        except ModelOutageError as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return AgentInvocationResponse(
                agent_name=self.agent_name,
                status=AgentStatus.NEEDS_HUMAN,
                result={"fallback_mode": "manual_workflow", "reason": str(exc)},
                published_result={"fallback_mode": "manual_workflow", "reason": str(exc)},
                confidence=0.0,
                confidence_band=ConfidenceBand.LOW,
                assumptions=["AI model provider unavailable; deterministic workflow remains active."],
                missing_information=[],
                contradictions=[],
                limitations=["Model gateway outage active; human reviewer must complete this step manually."],
                decision=DecisionIntelligence(
                    decision_id=self._decision_id(self.agent_name),
                    reason_codes=["RC_MODEL_GATEWAY_OUTAGE", "RC_MANUAL_FALLBACK_ACTIVE"],
                    evidence=[str(exc)],
                    policy_rule_refs=["INVARIANT-5-GRACEFUL-DEGRADATION"],
                    confidence=0.0,
                    confidence_band=ConfidenceBand.LOW,
                    routing_outcome="route_to_human_queue",
                    explanation="Model gateway circuit open; claim preserved for deterministic manual handling.",
                ),
                model_id=model_id,
                model_version=model_version,
                prompt_version=self.prompt_version,
                tool_versions=self.tool_versions,
                rule_versions=request.rule_versions,
                suggested_next_action="route_to_human_queue",
                attempt_number=request.attempt_number,
                duration_ms=elapsed_ms,
            )

    @abstractmethod
    def _run(
        self,
        request: AgentInvocationRequest,
        *,
        model_id: str,
        model_version: str,
        executor: ControlledActionExecutor,
    ) -> AgentInvocationResponse:
        raise NotImplementedError
