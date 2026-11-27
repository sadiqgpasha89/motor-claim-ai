"""Tool gateway. Every external action by an agent or an officer passes the same checks, in code.

The checks are: user authorised, agent allowed the tool, claim in scope, action allowed in the claim state,
approval present when required, idempotent, and safe (valid input, rate limit, resilient call, valid output).
Prompts do not enforce any of this. A denied call is audited and raises an error.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.contracts.errors import DomainError, ErrorCode
from packages.security.auth import Role, UserContext, enforce_claim_abac
from packages.security.ratelimit import enforce as enforce_rate_limit
from services.claims.audit import record_audit_event
from services.claims.models import Approval, Claim, ToolInvocation
from services.integrations.resilience import (
    CircuitOpenError,
    PermanentIntegrationError,
    RetryPolicy,
    TransientIntegrationError,
    breaker_for,
    call_with_resilience,
)
from services.integrations.sandbox import PORTS
from services.rules_engine.security import security_controls

REQUIRED_PARAMS: dict[str, tuple[str, ...]] = {
    "policy_lookup": ("policy_number",),
    "claims_ledger_post": ("event_type",),
    "garage_book": ("garage_id", "slot"),
    "surveyor_assign": ("surveyor_id",),
    "notify": ("template",),
}
FALLBACK_CHANNELS = ("whatsapp", "sms", "email")


def _request_hash(tool: str, params: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({"tool": tool, "params": params}, sort_keys=True, default=str).encode()).hexdigest()


class ToolGateway:
    def __init__(self, db: Session, user: UserContext, claim: Claim, *, sleep: Callable[[float], None] | None = None) -> None:
        self.db = db
        self.user = user
        self.claim = claim
        self._sleep = sleep
        self.policy: dict[str, dict[str, Any]] = security_controls(db)["tool_policy"]

    def _deny(self, tool: str, agent_name: str, code: ErrorCode, message: str, status: int, check: str) -> DomainError:
        record_audit_event(
            self.db, tenant_id=self.claim.tenant_id, claim_id=self.claim.id, actor_id=self.user.user_id,
            actor_role=self.user.role.value, action="TOOL_DENIED", object_type="tool", object_id=tool,
            outcome="denied", details={"agent": agent_name, "check": check, "reason": message},
        )
        self.db.commit()
        return DomainError(code, message, status_code=status)

    def _authorise(self, tool: str, agent_name: str, params: dict[str, Any], approval_id: str | None) -> dict[str, Any]:
        spec = self.policy.get(tool)
        if spec is None:
            raise DomainError(ErrorCode.NOT_FOUND, f"Unknown tool '{tool}'", status_code=404)
        user, claim = self.user, self.claim
        if user.role != Role.ADMIN and user.role.value not in spec["allowed_roles"]:
            raise self._deny(tool, agent_name, ErrorCode.NOT_AUTHORISED, f"Role '{user.role.value}' may not use tool '{tool}'.", 403, "user_role")
        if agent_name not in spec["allowed_agents"]:
            raise self._deny(tool, agent_name, ErrorCode.NOT_AUTHORISED, f"Agent '{agent_name}' is not allowed to use tool '{tool}'.", 403, "agent_tool")
        try:
            enforce_claim_abac(user, claim)
        except DomainError as exc:
            raise self._deny(tool, agent_name, ErrorCode.NOT_AUTHORISED, exc.message, 403, "claim_scope") from exc
        states = spec["allowed_states"]
        if "*" not in states and claim.status not in states:
            raise self._deny(tool, agent_name, ErrorCode.STATE_CONFLICT, f"Tool '{tool}' is not allowed while the claim is in {claim.status}.", 409, "claim_state")
        if spec.get("route_only"):
            raise self._deny(tool, agent_name, ErrorCode.NOT_AUTHORISED, f"Tool '{tool}' is not exposed through the gateway. Use its API route.", 403, "route_only")
        missing = [k for k in REQUIRED_PARAMS.get(tool, ()) if not params.get(k)]
        if missing:
            raise DomainError(ErrorCode.VALIDATION_ERROR, f"Missing parameter(s): {', '.join(missing)}", status_code=400)
        if spec["approval_required"]:
            approval = self.db.query(Approval).filter(Approval.id == (approval_id or ""), Approval.claim_id == claim.id).first()
            if approval is None or approval.decision != "approved":
                raise self._deny(tool, agent_name, ErrorCode.HUMAN_REVIEW_REQUIRED, f"Tool '{tool}' needs an approved approval for this claim.", 409, "approval")
            if user.user_id in {approval.maker_user_id}:
                raise self._deny(tool, agent_name, ErrorCode.NOT_AUTHORISED, "The maker of an approval cannot execute the action it authorises.", 403, "segregation_of_duties")
        return spec

    def invoke(
        self, tool: str, *, agent_name: str = "human", params: dict[str, Any] | None = None,
        idempotency_key: str | None = None, approval_id: str | None = None,
    ) -> dict[str, Any]:
        params = params or {}
        spec = self._authorise(tool, agent_name, params, approval_id)
        enforce_rate_limit(f"tool:{self.user.user_id}", self.user.user_id, int(security_controls(self.db)["rate_limits_per_minute"]["tool_call_per_user"]))

        req_hash = _request_hash(tool, params)
        if spec["idempotency_required"]:
            if not idempotency_key:
                raise DomainError(ErrorCode.VALIDATION_ERROR, f"Tool '{tool}' needs an idempotency key.", status_code=400)
            prior = (
                self.db.query(ToolInvocation)
                .filter(ToolInvocation.tenant_id == self.claim.tenant_id, ToolInvocation.tool == tool, ToolInvocation.idempotency_key == idempotency_key)
                .first()
            )
            if prior is not None:
                if prior.request_hash != req_hash:
                    raise DomainError(ErrorCode.DUPLICATE_REQUEST, "This idempotency key was used with a different request.", status_code=409)
                return {"tool": tool, "replayed": True, "status": prior.status, "result": prior.result, "attempts": prior.attempts}

        breaker = breaker_for(spec["port"])
        policy = RetryPolicy()
        kwargs: dict[str, Any] = {"policy": policy}
        if self._sleep is not None:
            kwargs["sleep"] = self._sleep
        try:
            result, attempts = call_with_resilience(lambda: self._call_port(tool, spec["port"], params), breaker=breaker, **kwargs)
        except CircuitOpenError as exc:
            raise self._deny(tool, agent_name, ErrorCode.DEPENDENCY_UNAVAILABLE, str(exc), 503, "circuit_open") from exc
        except TransientIntegrationError as exc:
            self._record(tool, agent_name, idempotency_key, req_hash, "failed", {}, str(exc), policy.max_attempts, spec)
            raise DomainError(ErrorCode.DEPENDENCY_UNAVAILABLE, f"{spec['port']} is unavailable after {policy.max_attempts} attempts.", status_code=503) from exc
        except PermanentIntegrationError as exc:
            self._record(tool, agent_name, idempotency_key, req_hash, "rejected", {}, str(exc), 1, spec)
            raise DomainError(ErrorCode.INTEGRATION_REJECTED, str(exc), status_code=422) from exc

        if not self._record(tool, agent_name, idempotency_key, req_hash, "succeeded", result, None, attempts, spec):
            # Two requests with the same key raced. The unique constraint kept the first. Return its result.
            prior = (
                self.db.query(ToolInvocation)
                .filter(ToolInvocation.tenant_id == self.claim.tenant_id, ToolInvocation.tool == tool, ToolInvocation.idempotency_key == idempotency_key)
                .one()
            )
            return {"tool": tool, "replayed": True, "status": prior.status, "result": prior.result, "attempts": prior.attempts}
        return {"tool": tool, "replayed": False, "status": "succeeded", "result": result, "attempts": attempts}

    def _call_port(self, tool: str, port: str, params: dict[str, Any]) -> dict[str, Any]:
        adapter = PORTS[port]
        c = self.claim
        out: dict[str, Any]
        if tool == "policy_lookup":
            out = adapter.lookup(policy_number=params["policy_number"])
            return out
        if tool == "claims_ledger_post":
            out = adapter.post_event(claim_number=c.claim_number, event_type=params["event_type"], payload=params.get("payload", {}))
            return out
        if tool == "garage_book":
            out = adapter.book_slot(garage_id=params["garage_id"], claim_number=c.claim_number, slot=params["slot"])
            return out
        if tool == "surveyor_assign":
            out = adapter.assign(surveyor_id=params["surveyor_id"], claim_number=c.claim_number)
            return out
        if tool == "notify":
            # The channel gets a token, never a phone number or email address.
            order = [params.get("channel") or "whatsapp"]
            order += [ch for ch in FALLBACK_CHANNELS if ch not in order]
            token = f"cust:{c.customer_id}"
            tried: list[str] = []
            for channel in order:
                try:
                    res: dict[str, Any] = adapter.send(channel=channel, recipient_token=token, template=params["template"])
                    return {**res, "fallback_used": bool(tried), "channels_tried": [*tried, channel]}
                except TransientIntegrationError:
                    tried.append(channel)
            raise TransientIntegrationError("All messaging channels failed")
        raise DomainError(ErrorCode.NOT_FOUND, f"No adapter call for tool '{tool}'", status_code=404)

    def _record(
        self, tool: str, agent_name: str, key: str | None, req_hash: str, status: str,
        result: dict[str, Any], error: str | None, attempts: int, spec: dict[str, Any],
    ) -> bool:
        if spec["idempotency_required"] and key:
            self.db.add(ToolInvocation(
                tenant_id=self.claim.tenant_id, claim_id=self.claim.id, tool=tool, agent_name=agent_name,
                actor_id=self.user.user_id, idempotency_key=key, request_hash=req_hash, status=status,
                result=result, error=error, attempts=attempts,
            ))
        record_audit_event(
            self.db, tenant_id=self.claim.tenant_id, claim_id=self.claim.id, actor_id=self.user.user_id,
            actor_role=self.user.role.value, action="TOOL_INVOKED", object_type="tool", object_id=tool,
            outcome="success" if status == "succeeded" else "failure",
            details={"agent": agent_name, "status": status, "attempts": attempts, "port": spec["port"]},
        )
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            return False
        return True
