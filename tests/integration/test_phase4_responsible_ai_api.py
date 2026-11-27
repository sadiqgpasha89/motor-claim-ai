from tests.conftest import auth_headers


def test_override_and_cost_reports_are_ops_only(client):
    for path in ("/api/v1/operations/human-overrides", "/api/v1/operations/cost-latency"):
        assert client.get(path, headers=auth_headers(client, "manager@demo.in")).status_code == 200
        assert client.get(path, headers=auth_headers(client, "handler@demo.in")).status_code == 403


def test_reports_return_the_documented_shape(client):
    hdr = auth_headers(client, "manager@demo.in")
    ov = client.get("/api/v1/operations/human-overrides", headers=hdr).json()
    assert {"approvals_decided", "override_rate_pct", "by_action", "alerts", "note"} <= set(ov)
    cl = client.get("/api/v1/operations/cost-latency", headers=hdr).json()
    assert {"cost_per_claim_inr", "agents", "optimisation_hints", "note"} <= set(cl)
