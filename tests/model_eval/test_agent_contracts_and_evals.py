from __future__ import annotations

from agents.specialists import AGENT_REGISTRY
from packages.contracts.agents import AgentInvocationRequest, AgentInvocationResponse, AgentStatus
from services.agent_runtime.gateway import ModelGateway


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
    finally:
        ModelGateway.set_simulated_outage(None)
