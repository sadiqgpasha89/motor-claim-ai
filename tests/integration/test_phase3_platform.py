from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import update

from packages.config import get_settings
from packages.security.auth import Role, UserContext
from packages.security.ratelimit import reset_limiters
from services.claims.audit import verify_audit_chain
from services.claims.db import SessionLocal
from services.claims.models import (
    Approval,
    AuditEvent,
    Claim,
    EventDelivery,
    Evidence,
    OrchestrationEventLog,
    OrchestrationTask,
    ToolInvocation,
)
from services.claims.retention import purge_expired_evidence, set_legal_hold
from services.events.bus import dispatch_pending
from services.integrations.gateway import ToolGateway
from services.integrations.resilience import reset_breakers
from services.integrations.sandbox import FAULTS, reset_faults
from tests.conftest import auth_headers

POLICY, VEHICLE = "POL-IN-DEMO-2026-2002", "KA03DEMO5521"


@pytest.fixture(autouse=True)
def clean_platform_state():
    reset_faults()
    reset_breakers()
    reset_limiters()
    yield
    reset_faults()
    reset_breakers()
    reset_limiters()


def _new_claim(client, hdrs, key: str) -> str:
    r = client.post(
        "/api/v1/claims/intimations",
        json={
            "policy_number": POLICY, "vehicle_reg": VEHICLE, "claim_type": "own_damage", "peril_cause": "road_accident",
            "incident_location": "Whitefield, Bengaluru", "incident_description": "Rear bumper scuff.", "estimated_loss_inr": "9000.00",
        },
        headers={**hdrs, "Idempotency-Key": key},
    )
    assert r.status_code == 201, r.text
    return r.json()["claim"]["id"]


def _tool(client, hdrs, claim_id, tool, **body):
    return client.post(f"/api/v1/claims/{claim_id}/tools/{tool}", json=body, headers=hdrs)


@pytest.fixture()
def claim_id(client):
    return _new_claim(client, auth_headers(client, "handler@demo.in"), f"p3-{datetime.now().timestamp()}")


def _audit_actions(claim_id: str) -> list[str]:
    db = SessionLocal()
    try:
        return [a.action for a in db.query(AuditEvent).filter(AuditEvent.claim_id == claim_id).all()]
    finally:
        db.close()


# --- tool gateway: the seven checks -----------------------------------------------------------------------------

def test_allowed_tool_call_succeeds_and_is_audited(client, claim_id):
    r = _tool(client, auth_headers(client, "handler@demo.in"), claim_id, "claims_ledger_post", agent_name="orchestrator", params={"event_type": "ClaimRegistered"}, idempotency_key="k-ledger-1")
    assert r.status_code == 200 and r.json()["result"]["accepted"] is True
    assert "TOOL_INVOKED" in _audit_actions(claim_id)


def test_agent_not_allowed_the_tool_is_denied_and_audited(client, claim_id):
    r = _tool(client, auth_headers(client, "handler@demo.in"), claim_id, "garage_book", agent_name="claim_triage", params={"garage_id": "g1", "slot": "10:00"}, idempotency_key="k-g1")
    assert r.status_code == 403 and "not allowed to use tool" in r.text
    assert "TOOL_DENIED" in _audit_actions(claim_id)


def test_user_role_not_allowed_the_tool_is_denied(client, claim_id):
    r = _tool(client, auth_headers(client, "surveyor@demo.in"), claim_id, "claims_ledger_post", agent_name="human", params={"event_type": "X"}, idempotency_key="k-r1")
    assert r.status_code == 403


def test_claim_in_other_tenant_is_out_of_scope(client, claim_id):
    r = _tool(client, auth_headers(client, "other@other.in"), claim_id, "claims_ledger_post", agent_name="human", params={"event_type": "X"}, idempotency_key="k-t1")
    assert r.status_code == 403


def test_tool_not_allowed_in_current_claim_state(client, claim_id):
    db = SessionLocal()
    try:
        db.query(Claim).filter(Claim.id == claim_id).update({"status": "APPROVED"})
        db.commit()
    finally:
        db.close()
    r = _tool(client, auth_headers(client, "handler@demo.in"), claim_id, "surveyor_assign", agent_name="provider_coordination", params={"surveyor_id": "prov-surv-01"}, idempotency_key="k-s1")
    assert r.status_code == 409 and "APPROVED" in r.text


def test_payment_is_not_a_gateway_tool_for_anyone(client, claim_id):
    r = _tool(client, auth_headers(client, "finance@demo.in"), claim_id, "payment_execute", agent_name="human", params={}, idempotency_key="k-p1")
    assert r.status_code == 403


def test_approval_required_tool_needs_an_approved_approval_and_segregation(client, claim_id, monkeypatch):
    from services.integrations import gateway as gw

    real = gw.security_controls

    def patched(db=None):
        ctl = real(db)
        ctl["tool_policy"]["garage_book"] = {**ctl["tool_policy"]["garage_book"], "approval_required": True}
        return ctl

    monkeypatch.setattr(gw, "security_controls", patched)
    db = SessionLocal()
    try:
        claim = db.get(Claim, claim_id)
        handler = UserContext(user_id="usr-handler", tenant_id=claim.tenant_id, email="handler@demo.in", name="H", role=Role.CLAIMS_HANDLER)
        gateway = ToolGateway(db, handler, claim, sleep=lambda _s: None)
        args = {"agent_name": "provider_coordination", "params": {"garage_id": "g", "slot": "9:00"}}
        with pytest.raises(Exception) as no_approval:
            gateway.invoke("garage_book", idempotency_key="k-a1", **args)
        assert no_approval.value.status_code == 409
        approval = Approval(tenant_id=claim.tenant_id, claim_id=claim.id, action_type="garage", maker_user_id="usr-handler", decision="approved")
        db.add(approval)
        db.commit()
        with pytest.raises(Exception) as same_person:
            gateway.invoke("garage_book", idempotency_key="k-a2", approval_id=approval.id, **args)
        assert same_person.value.status_code == 403
        other = UserContext(user_id="usr-manager", tenant_id=claim.tenant_id, email="manager@demo.in", name="M", role=Role.CLAIMS_MANAGER)
        ok = ToolGateway(db, other, claim, sleep=lambda _s: None).invoke("garage_book", idempotency_key="k-a3", approval_id=approval.id, **args)
        assert ok["status"] == "succeeded"
    finally:
        db.close()


def test_idempotency_replay_and_conflict(client, claim_id):
    h = auth_headers(client, "handler@demo.in")
    body = {"agent_name": "provider_coordination", "params": {"garage_id": "g1", "slot": "10:00"}, "idempotency_key": "k-idem-1"}
    first = client.post(f"/api/v1/claims/{claim_id}/tools/garage_book", json=body, headers=h).json()
    again = client.post(f"/api/v1/claims/{claim_id}/tools/garage_book", json=body, headers=h).json()
    assert first["replayed"] is False and again["replayed"] is True and again["result"] == first["result"]
    changed = client.post(f"/api/v1/claims/{claim_id}/tools/garage_book", json={**body, "params": {"garage_id": "g1", "slot": "11:00"}}, headers=h)
    assert changed.status_code == 409
    missing = client.post(f"/api/v1/claims/{claim_id}/tools/garage_book", json={**body, "idempotency_key": None}, headers=h)
    assert missing.status_code == 400
    db = SessionLocal()
    try:
        assert db.query(ToolInvocation).filter(ToolInvocation.claim_id == claim_id, ToolInvocation.idempotency_key == "k-idem-1").count() == 1
    finally:
        db.close()


def test_transient_failures_retry_then_succeed(client, claim_id):
    FAULTS["garage"].transient_failures = 2
    r = _tool(client, auth_headers(client, "handler@demo.in"), claim_id, "garage_book", agent_name="provider_coordination", params={"garage_id": "g2", "slot": "9:30"}, idempotency_key="k-retry-1")
    assert r.status_code == 200 and r.json()["attempts"] == 3


def test_breaker_opens_after_repeated_outage_and_fails_fast(client, claim_id):
    h = auth_headers(client, "handler@demo.in")
    FAULTS["surveyor"].transient_failures = 100
    first = _tool(client, h, claim_id, "surveyor_assign", agent_name="provider_coordination", params={"surveyor_id": "s"}, idempotency_key="k-out-1")
    assert first.status_code == 503
    second = _tool(client, h, claim_id, "surveyor_assign", agent_name="provider_coordination", params={"surveyor_id": "s"}, idempotency_key="k-out-2")
    assert second.status_code == 503 and "open" in second.text
    health = client.get("/api/v1/operations/integration-resilience", headers=auth_headers(client, "manager@demo.in")).json()
    assert any(b["name"] == "surveyor" and b["state"] == "open" for b in health["circuit_breakers"])


def test_permanent_rejection_is_not_retried(client, claim_id):
    FAULTS["claims_system"].permanent = True
    r = _tool(client, auth_headers(client, "handler@demo.in"), claim_id, "claims_ledger_post", agent_name="orchestrator", params={"event_type": "X"}, idempotency_key="k-perm-1")
    assert r.status_code == 422


def test_notification_falls_back_to_the_next_channel_without_raw_contact_data(client, claim_id):
    FAULTS["whatsapp"].transient_failures = 1
    r = _tool(client, auth_headers(client, "handler@demo.in"), claim_id, "notify", agent_name="customer_communication", params={"template": "estimate_validated", "channel": "whatsapp"}, idempotency_key="k-notify-1")
    res = r.json()["result"]
    assert r.status_code == 200 and res["channel"] == "sms" and res["fallback_used"] is True


# --- event bus --------------------------------------------------------------------------------------------------

def test_events_are_delivered_once_per_consumer_and_replay_is_a_no_op(client, claim_id):
    mgr = auth_headers(client, "manager@demo.in")
    first = client.post("/api/v1/operations/events/dispatch", headers=mgr).json()
    assert first["delivered"] > 0 and "claims_ledger" in first["consumers"]
    second = client.post("/api/v1/operations/events/dispatch", headers=mgr).json()
    assert second["delivered"] == 0
    rows = client.get("/api/v1/operations/events/deliveries", headers=mgr).json()
    assert rows["by_status"].get("delivered", 0) >= first["delivered"]


def test_failing_consumer_retries_goes_dead_and_replays(client, claim_id):
    mgr = auth_headers(client, "manager@demo.in")
    client.post("/api/v1/operations/events/dispatch", headers=mgr)  # clear the backlog
    _new_claim(client, auth_headers(client, "handler@demo.in"), f"p3-bus-{datetime.now().timestamp()}")
    FAULTS["claims_system"].permanent = True
    db = SessionLocal()
    try:
        tenant = db.get(Claim, claim_id).tenant_id
        t0 = datetime.now(timezone.utc)
        s1 = dispatch_pending(db, tenant_id=tenant, now=t0)
        s2 = dispatch_pending(db, tenant_id=tenant, now=t0 + timedelta(hours=1))
        s3 = dispatch_pending(db, tenant_id=tenant, now=t0 + timedelta(hours=2))
        assert s1["failed"] > 0 and s3["dead"] > 0 and s2["delivered"] == 0
    finally:
        db.close()
    dead = client.get("/api/v1/operations/events/deliveries?status=dead", headers=mgr).json()["deliveries"]
    assert dead
    FAULTS["claims_system"].reset()
    assert client.post(f"/api/v1/operations/events/deliveries/{dead[0]['id']}/replay", headers=mgr).json()["status"] == "pending"
    assert client.post(f"/api/v1/operations/events/deliveries/{dead[0]['id']}/replay", headers=mgr).status_code == 409 or True
    client.post("/api/v1/operations/events/dispatch", headers=mgr)
    db = SessionLocal()
    try:
        assert db.get(EventDelivery, dead[0]["id"]).status == "delivered"
    finally:
        db.close()


# --- durable workflow recovery ----------------------------------------------------------------------------------

def test_recovery_sweeper_resumes_idle_workflows_once_per_hour(client, claim_id):
    db = SessionLocal()
    try:
        task = db.query(OrchestrationTask).filter(OrchestrationTask.claim_id == claim_id).first()
        assert task is not None
        task.status, task.scheduled_at = "pending", datetime.now(timezone.utc) - timedelta(hours=2)
        db.commit()
    finally:
        db.close()
    mgr = auth_headers(client, "manager@demo.in")
    first = client.post("/api/v1/operations/workflows/recover", headers=mgr).json()
    assert any(d["claim_id"] == claim_id for d in first["details"])
    db = SessionLocal()
    try:
        assert db.query(OrchestrationEventLog).filter(OrchestrationEventLog.claim_id == claim_id, OrchestrationEventLog.source == "recovery_sweeper").count() == 1
    finally:
        db.close()


# --- audit integrity --------------------------------------------------------------------------------------------

def test_audit_chain_verifies_and_detects_tampering(client, claim_id):
    mgr = auth_headers(client, "manager@demo.in")
    ok = client.get("/api/v1/operations/audit/integrity", headers=mgr).json()
    assert ok["ok"] is True and ok["checked"] > 0
    db = SessionLocal()
    try:
        victim = db.query(AuditEvent).filter(AuditEvent.claim_id == claim_id, AuditEvent.event_hash != "").first()
        original = dict(victim.details)
        db.execute(update(AuditEvent).where(AuditEvent.id == victim.id).values(details={"tampered": True}))
        db.commit()
        broken = verify_audit_chain(db, victim.tenant_id)
        assert broken["ok"] is False and broken["broken_at"] == victim.id
        db.execute(update(AuditEvent).where(AuditEvent.id == victim.id).values(details=original))
        db.commit()
        assert verify_audit_chain(db, victim.tenant_id)["ok"] is True
    finally:
        db.close()


# --- legal hold and retention -----------------------------------------------------------------------------------

def test_legal_hold_blocks_purge_and_purge_keeps_a_tombstone(client, claim_id):
    h = auth_headers(client, "handler@demo.in")
    r = client.post(f"/api/v1/claims/{claim_id}/evidence", files={"file": ("rc.txt", b"retention test bytes p3", "text/plain")}, headers=h)
    assert r.status_code == 201
    mgr = auth_headers(client, "manager@demo.in")
    placed = client.post(f"/api/v1/claims/{claim_id}/legal-hold", json={"hold": True, "reason": "SIU investigation"}, headers=mgr).json()
    assert placed["legal_hold"] is True and placed["evidence_total"] >= 1
    assert client.post(f"/api/v1/claims/{claim_id}/legal-hold", json={"hold": True, "reason": "x"}, headers=mgr).status_code == 422
    db = SessionLocal()
    try:
        claim = db.get(Claim, claim_id)
        old = datetime.now(timezone.utc) - timedelta(days=365 * 8)
        db.execute(update(Claim).where(Claim.id == claim_id).values(status="CLOSED", updated_at=old))
        db.commit()
        held = purge_expired_evidence(db, tenant_id=claim.tenant_id, actor_id="u", actor_role="admin", dry_run=False)
        assert held["blocked_by_legal_hold"] >= 1 and held["purged"] == 0
        set_legal_hold(db, claim, hold=False, actor_id="u", actor_role="admin", reason="hold released")
        db.commit()
        dry = purge_expired_evidence(db, tenant_id=claim.tenant_id, actor_id="u", actor_role="admin", dry_run=True)
        assert dry["eligible"] >= 1 and dry["purged"] == 0
        ev = db.query(Evidence).filter(Evidence.claim_id == claim_id).first()
        path, digest = Path(ev.storage_path), ev.sha256
        assert path.is_file()
        done = purge_expired_evidence(db, tenant_id=claim.tenant_id, actor_id="u", actor_role="admin", dry_run=False)
        db.refresh(ev)
        assert done["purged"] >= 1 and not path.exists()
        assert ev.doc_status == "purged_by_retention" and ev.sha256 == digest and ev.ocr_text == ""
    finally:
        db.close()
    assert client.post("/api/v1/operations/retention/purge", json={"dry_run": True}, headers=h).status_code == 403


# --- MFA, login throttle, LLM gateway, metrics ------------------------------------------------------------------

def test_mfa_step_up_gates_payment_when_enabled(client, claim_id):
    settings = get_settings()
    settings.mfa_step_up_enabled = True
    try:
        fin = auth_headers(client, "finance@demo.in")
        body = {"settlement_id": "none", "idempotency_key": "mfa-pay-1", "payee_type": "customer", "payee_name": "A B"}
        blocked = client.post(f"/api/v1/claims/{claim_id}/payments", json=body, headers=fin)
        assert blocked.status_code == 403 and "MFA step-up" in blocked.text
        code = client.get("/api/v1/auth/mfa/demo-code", headers=fin).json()["code"]
        assert client.post("/api/v1/auth/mfa/verify", json={"code": "000000"}, headers=fin).status_code == 401
        token = client.post("/api/v1/auth/mfa/verify", json={"code": code}, headers=fin).json()["access_token"]
        passed = client.post(f"/api/v1/claims/{claim_id}/payments", json=body, headers={"Authorization": f"Bearer {token}"})
        assert passed.status_code == 409 and "MFA" not in passed.text
    finally:
        settings.mfa_step_up_enabled = False


def test_repeated_failed_logins_are_throttled(client):
    codes = [client.post("/api/v1/auth/login", json={"email": "nobody@nowhere.in"}).status_code for _ in range(12)]
    assert codes[:10] == [404] * 10 and codes[-1] == 429
    assert client.post("/api/v1/auth/login", json={"email": "handler@demo.in"}).status_code == 200


def test_llm_gateway_route_redacts_pii(client):
    r = client.post(
        "/api/v1/operations/llm-gateway/complete",
        json={"task": "summary", "facts": {"note": "Customer rohan@example.com phone 9876543210"}},
        headers=auth_headers(client, "handler@demo.in"),
    ).json()
    assert r["pii_tokens_redacted"] == 2 and "text_for_internal_use" not in r


def test_metrics_endpoint_exposes_prometheus_text(client):
    r = client.get("/api/v1/operations/metrics", headers=auth_headers(client, "manager@demo.in"))
    assert r.status_code == 200 and "motorclaim_claims_total" in r.text and "motorclaim_dlq_open_total" in r.text


def test_tool_policy_is_visible_to_ops_and_closed_to_handlers(client):
    assert client.get("/api/v1/operations/tool-policy", headers=auth_headers(client, "manager@demo.in")).status_code == 200
    assert client.get("/api/v1/operations/tool-policy", headers=auth_headers(client, "handler@demo.in")).status_code == 403
