from __future__ import annotations

import json
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "site"


def _payload() -> dict:
    text = (SITE / "claim360-data.js").read_text(encoding="utf-8")
    return json.loads(text.split("window.CLAIM360_DEMO = ", 1)[1].rstrip().rstrip(";"))


def test_site_capture_is_a_closed_od_claim_with_full_traces():
    data = _payload()
    assert data["claim_360"]["overview"]["canonical_state"] == "CLOSED"
    assert [j["step"] for j in data["journey"]][-1] == "Closure"
    assert len(data["claim_360"]["agent_executions"]) >= 5
    assert {"kpis", "cost", "failed_agent_executions", "human_approval_backlog"} <= set(data["dashboard"])


def test_site_section_and_scripts_are_wired():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert 'id="agent-ops"' in html and 'href="#agent-ops"' in html
    assert html.index("claim360-data.js") < html.index("agent-ops.js")


def test_intelligence_section_and_data_are_wired():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert 'id="claim-intelligence"' in html and 'href="#claim-intelligence"' in html
    assert html.index("intelligence-data.js") < html.index('src="intelligence.js"')
    text = (SITE / "intelligence-data.js").read_text(encoding="utf-8")
    data = json.loads(text.split("window.INTELLIGENCE_DEMO = ", 1)[1].rstrip().rstrip(";"))
    assert data["fraud_network"]["never_auto_reject"] is True
    assert data["supplementary"]["reinspection_required"] is True
    assert any(c["decision"] == "replace_and_inspect" for c in data["repair_replace"]["components"])


def test_platform_section_and_data_are_wired():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert 'id="platform-security"' in html and 'href="#platform-security"' in html
    assert html.index("platform-data.js") < html.index('src="platform.js"')
    text = (SITE / "platform-data.js").read_text(encoding="utf-8")
    data = json.loads(text.split("window.PLATFORM_DEMO = ", 1)[1].rstrip().rstrip(";"))
    assert data["tool_calls"]["denied_agent"]["http_status"] == 403
    assert data["tool_calls"]["denied_payment_tool"]["http_status"] == 403
    assert data["audit_integrity"]["ok"] is True


def test_product_section_and_data_are_wired():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert 'id="product-portal"' in html and 'href="#product-portal"' in html
    assert html.index("product-data.js") < html.index('src="product.js"')
    text = (SITE / "product-data.js").read_text(encoding="utf-8")
    data = json.loads(text.split("window.PRODUCT_DEMO = ", 1)[1].rstrip().rstrip(";"))
    assert data["kpi_framework"]["total_count"] == 17
    assert len(data["demos"]["demos"]) == 5 and len(data["capability_model"]["capability_model"]) == 16
    assert all(k["value"] is None for k in data["kpi_framework"]["kpis"] if k["id"] in {"customer_satisfaction", "cost_per_claim"})
