from __future__ import annotations

from agents.specialists import AGENT_REGISTRY
from packages.contracts.agents import AgentInvocationRequest, AgentInvocationResponse, AgentStatus
from services.agent_runtime.gateway import ModelGateway
from tests.conftest import auth_headers


def test_all_11_agents_return_valid_typed_contracts():
    assert len(AGENT_REGISTRY) == 11
    for name, agent in AGENT_REGISTRY.items():
        req = AgentInvocationRequest(
            tenant_id="tenant-in-demo",
            claim_id="clm-demo-0001",
            correlation_id="corr-eval-1",
            workflow_run_id="wf-eval-1",
            actor_user_id="usr-handler",
            actor_role="claims_handler",
            minimised_facts={
                "policy_number": "POL-IN-DEMO-2026-1001",
                "vehicle_reg": "MH02DEMO1042",
                "incident_description": "Front bumper collision",
                "incident_location": "Mumbai",
                "estimated_loss_inr": "55000.00",
                "checks": {"confirmed_payment_or_declined": True, "no_open_grievance": True},
            },
            allowed_tools=sorted(agent.allowed_tools),
        )
        res = agent.execute(req)
        assert isinstance(res, AgentInvocationResponse)
        assert res.agent_name == name
        assert 0.0 <= res.confidence <= 1.0
        assert res.prompt_version
        assert res.decision is not None
        assert len(res.decision.reason_codes) >= 1
        assert res.decision.routing_outcome
        assert res.decision.explanation
        assert res.published_result


def test_ai_outage_falls_back_gracefully_to_needs_human(client):
    ModelGateway.set_simulated_outage(True)
    try:
        agent = AGENT_REGISTRY["coverage_intelligence"]
        req = AgentInvocationRequest(
            tenant_id="tenant-in-demo",
            claim_id="clm-demo-0001",
            correlation_id="corr-outage-1",
            workflow_run_id="wf-outage-1",
            actor_user_id="usr-handler",
            actor_role="claims_handler",
            allowed_tools=sorted(agent.allowed_tools),
        )
        res = agent.execute(req)
        assert res.status == AgentStatus.NEEDS_HUMAN
        assert res.result["fallback_mode"] == "manual_workflow"
        assert res.suggested_next_action == "route_to_human_queue"
        assert res.decision is not None
        assert "RC_MODEL_GATEWAY_OUTAGE" in res.decision.reason_codes
    finally:
        ModelGateway.set_simulated_outage(None)


def test_agent_contracts_endpoint_and_capability_matrix(client):
    hdrs = auth_headers(client, "handler@demo.in")
    resp = client.get("/api/v1/agents/contracts", headers=hdrs)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_agents"] == 11
    assert len(body["contracts"]) == 11
    names = {c["agent_name"] for c in body["contracts"]}
    assert names == set(AGENT_REGISTRY.keys())
    for c in body["contracts"]:
        assert c["operational_responsibility"]
        assert len(c["required_capabilities"]) >= 3
        assert len(c["input_contract"]) >= 1
        assert len(c["output_contract"]) >= 1


def test_upgraded_agent_capabilities_across_matrix():
    # 1. FNOL Concierge: WhatsApp/voice + multilingual + towing
    fnol = AGENT_REGISTRY["fnol_concierge"].execute(
        AgentInvocationRequest(
            tenant_id="t1",
            claim_id="c1",
            correlation_id="corr1",
            workflow_run_id="wf1",
            actor_user_id="u1",
            actor_role="fnol_executive",
            locale="hi-IN",
            minimised_facts={
                "policy_number": "POL-1",
                "vehicle_reg": "MH02AB1234",
                "intake_channel": "whatsapp",
                "preferred_language": "hi-IN",
                "incident_location": "Bandra West",
                "incident_description": "Front impact",
                "vehicle_immobile": True,
                "towing_needed": True,
            },
            allowed_tools=sorted(AGENT_REGISTRY["fnol_concierge"].allowed_tools),
        )
    )
    assert fnol.result["normalised_channel"] == "whatsapp"
    assert fnol.result["language"] == "hi-IN"
    assert fnol.result["structured_incident"]["drivable_status"] == "immobile"
    assert any(a.action_type == "dispatch_towing" for a in fnol.actions_executed)

    # 2. Document Intelligence: multi-doc reconciliation & conflict detection
    doc = AGENT_REGISTRY["document_intelligence"].execute(
        AgentInvocationRequest(
            tenant_id="t1",
            claim_id="c1",
            correlation_id="corr2",
            workflow_run_id="wf1",
            actor_user_id="u1",
            actor_role="claims_handler",
            minimised_facts={
                "policy_number": "POL-1",
                "vehicle_reg": "MH02AB1234",
                "evidences": [
                    {"id": "ev1", "doc_type": "registration_certificate", "filename": "rc.pdf", "sha256": "abc123"},
                    {"id": "ev2", "doc_type": "policy_schedule", "filename": "pol.pdf", "sha256": "def456"},
                ],
                "extracted_facts": [
                    {"evidence_id": "ev1", "field_name": "vehicle_registration", "extracted_value": "MH02AB1234", "confidence": 0.94, "validation_status": "verified"},
                    {"evidence_id": "ev2", "field_name": "vehicle_registration", "extracted_value": "MH02ZZ9999", "confidence": 0.89, "validation_status": "mismatch"},
                ],
            },
            allowed_tools=sorted(AGENT_REGISTRY["document_intelligence"].allowed_tools),
        )
    )
    assert doc.status == AgentStatus.NEEDS_HUMAN
    assert doc.result["reconciliation_status"] == "conflicts_detected"
    assert len(doc.result["conflicts"]) >= 1
    assert "vehicle_registration" in doc.result["field_confidences"]

    # 3. Coverage Intelligence: matrix, deductibles, exclusions, rework request on mismatch
    cov = AGENT_REGISTRY["coverage_intelligence"].execute(
        AgentInvocationRequest(
            tenant_id="t1",
            claim_id="c1",
            correlation_id="corr3",
            workflow_run_id="wf1",
            actor_user_id="u1",
            actor_role="claims_handler",
            minimised_facts={"has_document_mismatch": True, "addons": {"zero_depreciation": True}},
            allowed_tools=sorted(AGENT_REGISTRY["coverage_intelligence"].allowed_tools),
        )
    )
    assert cov.status == AgentStatus.REWORK_REQUIRED
    assert len(cov.result["coverage_matrix"]) >= 5
    assert cov.rework_requests[0].to_agent == "document_intelligence"

    # 4. Customer Communication: multilingual delay advisory & adverse hold
    comm = AGENT_REGISTRY["customer_communication"].execute(
        AgentInvocationRequest(
            tenant_id="t1",
            claim_id="c1",
            correlation_id="corr4",
            workflow_run_id="wf1",
            actor_user_id="u1",
            actor_role="claims_handler",
            minimised_facts={
                "claim_number": "CLM-DEMO-2026-0006",
                "language": "ta-IN",
                "channel": "whatsapp",
                "message_type": "delay_advisory",
                "delay_reason": "Surveyor report pending",
            },
            allowed_tools=sorted(AGENT_REGISTRY["customer_communication"].allowed_tools),
        )
    )
    assert comm.status == AgentStatus.COMPLETED
    assert comm.result["language"] == "ta-IN"
    assert comm.result["message_type"] == "delay_advisory"
