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
