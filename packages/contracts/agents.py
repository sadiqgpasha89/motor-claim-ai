from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    COMPLETED = "completed"
    NEEDS_HUMAN = "needs_human"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
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
    evidence_refs: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    timeout_seconds: int = 15
    token_budget: int = 2000


class AgentInvocationResponse(BaseModel):
    agent_name: str
    status: AgentStatus
    result: dict[str, Any]
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_band: ConfidenceBand
    evidence_refs: list[EvidenceCitation] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    model_id: str
    model_version: str
    prompt_version: str
    tool_versions: dict[str, str] = Field(default_factory=dict)
    rule_versions: dict[str, str] = Field(default_factory=dict)
    suggested_next_action: str
    tools_invoked: list[str] = Field(default_factory=list)


class ToolPermissionError(Exception):
    """Raised when an agent attempts to call a tool outside its explicit allowlist."""
