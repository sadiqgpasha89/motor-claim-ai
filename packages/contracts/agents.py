from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    COMPLETED = "completed"
    NEEDS_HUMAN = "needs_human"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    REWORK_REQUIRED = "rework_required"
    BLOCKED_DEPENDENCY = "blocked_dependency"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


class ConfidenceBand(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvidenceCitation(BaseModel):
    source_type: str
    source_id: str
    reference: str
    excerpt: str = ""


class AgentActionExecution(BaseModel):
    """Structured record of a safe operational action taken through a controlled tool."""

    action_id: str
    action_type: str
    tool_name: str
    status: str = "executed"  # executed | gated_human_review | blocked_policy | simulated
    target_type: str = "claim"
    target_id: str = ""
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ReworkRequest(BaseModel):
    """Typed request emitted by a downstream agent asking an earlier stage to re-verify or rework."""

    from_agent: str
    to_agent: str
    reason_code: str
    instructions: str
    blocking: bool = True
    evidence_refs: list[EvidenceCitation] = Field(default_factory=list)


class DecisionIntelligence(BaseModel):
    """Explainable decision trace attached to every agent execution and workflow transition."""

    decision_id: str
    reason_codes: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    policy_rule_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_band: ConfidenceBand
    routing_outcome: str
    explanation: str
    alternatives_considered: list[str] = Field(default_factory=list)


class AgentContractSpec(BaseModel):
    """Formal operational responsibility, I/O contract, tool boundary, and orchestration metadata."""

    agent_name: str
    display_name: str
    stage: str
    operational_responsibility: str
    required_capabilities: list[str] = Field(default_factory=list)
    input_contract: dict[str, str] = Field(default_factory=dict)
    output_contract: dict[str, str] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    authorised_actions: list[str] = Field(default_factory=list)
    prohibited_actions: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    can_request_rework_from: list[str] = Field(default_factory=list)
    human_gate_condition: str = ""
    timeout_seconds: int = 15
    max_retries: int = 2


class AgentInvocationRequest(BaseModel):
    tenant_id: str
    claim_id: str
    correlation_id: str
    workflow_run_id: str
    actor_user_id: str
    actor_role: str
    jurisdiction: str = "IN"
    product_code: str = "PRIVATE_CAR_PACKAGE"
    claim_type: str = "own_damage"
    locale: str = "en-IN"
    rule_versions: dict[str, str] = Field(default_factory=dict)
    minimised_facts: dict[str, Any] = Field(default_factory=dict)
    upstream_results: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    attempt_number: int = 1
    rework_context: dict[str, Any] | None = None
    timeout_seconds: int = 15
    token_budget: int = 2000


class AgentInvocationResponse(BaseModel):
    agent_name: str
    status: AgentStatus
    result: dict[str, Any]
    published_result: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_band: ConfidenceBand
    evidence_refs: list[EvidenceCitation] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    actions_executed: list[AgentActionExecution] = Field(default_factory=list)
    rework_requests: list[ReworkRequest] = Field(default_factory=list)
    decision: DecisionIntelligence | None = None
    model_id: str
    model_version: str
    prompt_version: str
    tool_versions: dict[str, str] = Field(default_factory=dict)
    rule_versions: dict[str, str] = Field(default_factory=dict)
    suggested_next_action: str
    tools_invoked: list[str] = Field(default_factory=list)
    attempt_number: int = 1
    duration_ms: int = 0


class ToolPermissionError(Exception):
    """Raised when an agent attempts to call a tool outside its explicit allowlist."""
