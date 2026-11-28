import pytest

from services.rules_engine.product import product_framework
from tests.conftest import auth_headers

SECTIONS = ["executive-dashboard", "kpi-framework", "evidence-intelligence", "damage-assessment", "settlement-workbench", "human-review", "performance", "demos", "capability-model"]


@pytest.mark.parametrize("section", SECTIONS)
def test_every_section_loads_for_a_manager(client, section):
    r = client.get(f"/api/v1/portal/{section}", headers=auth_headers(client, "manager@demo.in"))
    assert r.status_code == 200, r.text
    assert "note" in r.json()


@pytest.mark.parametrize("section", ["executive-dashboard", "kpi-framework", "performance"])
def test_management_sections_are_closed_to_handlers(client, section):
    assert client.get(f"/api/v1/portal/{section}", headers=auth_headers(client, "handler@demo.in")).status_code == 403


def test_portal_is_closed_to_unauthenticated_users(client):
    assert client.get("/api/v1/portal/demos").status_code in {401, 403}


def test_kpi_framework_has_all_17_and_never_invents_values(client):
    body = client.get("/api/v1/portal/kpi-framework", headers=auth_headers(client, "manager@demo.in")).json()
    assert body["total_count"] == 17 and len(body["kpis"]) == 17 and len(body["before_after"]) == 12
    by_id = {k["id"]: k for k in body["kpis"]}
    for key in ("customer_satisfaction", "cost_per_claim"):
        assert by_id[key]["value"] is None and by_id[key]["basis"].startswith("not measured")
    assert "Illustrative" in body["targets_note"]


def test_five_demos_point_at_seeded_claims(client):
    body = client.get("/api/v1/portal/demos", headers=auth_headers(client, "manager@demo.in")).json()
    assert [d["id"] for d in body["demos"]] == ["demo-1", "demo-2", "demo-3", "demo-4", "demo-5"]
    assert all(d["available"] and d["claim_360_path"] for d in body["demos"])


def test_capability_model_and_assessment_are_complete(client):
    body = client.get("/api/v1/portal/capability-model", headers=auth_headers(client, "handler@demo.in")).json()
    assert len(body["capability_model"]) == 16 and len(body["assessment"]) == 10 and len(body["portal_sections"]) == 9
    assert {c["state"] for c in body["capability_model"]} <= {"built", "partial"}


def test_framework_rule_is_consistent():
    spec = product_framework()
    assert [d["claim_number"] for d in spec["demos"]] == [f"CLM-DEMO-2026-{n:04d}" for n in (12, 1, 8, 11, 10)]
    assert all(k["measure"] is None or isinstance(k["measure"], str) for k in spec["kpis"])


def test_seed_runs_agents_on_demos_two_to_five(client):
    hdr = auth_headers(client, "manager@demo.in")
    demos = {d["id"]: d for d in client.get("/api/v1/portal/demos", headers=hdr).json()["demos"]}
    for demo_id in ("demo-2", "demo-3", "demo-4", "demo-5"):
        answers = client.get(f"/api/v1/claims/{demos[demo_id]['claim_id']}/claim-360", headers=hdr).json()["answers"]
        assert answers["what_did_ai_do"], demo_id
    assert demos["demo-1"]["status"] == "APPROVED"
