from __future__ import annotations

import re

from scripts.sync_site_sla import TARGET, render

SITE = TARGET.parent


def test_site_catalogue_is_in_sync_with_the_rule_files():
    assert TARGET.read_text(encoding="utf-8") == render(), "run `python scripts/sync_site_sla.py` to regenerate site/sla-catalogue.js"


def test_site_sla_script_hardcodes_no_deadlines():
    src = (SITE / "sla.js").read_text(encoding="utf-8")
    # deadlines/regulatory windows come from the catalogue, never from literals in the UI script
    assert not re.search(r"\b(168|360|72|48|24)\s*(h|hours)\b", src)
    assert "window.SLA_CATALOGUE" in src


def test_site_advertises_twelve_agents_and_the_sla_agent_row():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert "11-Agent" not in html and "12-Agent Matrix" in html
    assert 'id="sla-operations"' in html and "sla-catalogue.js" in html and "sla.js" in html
    assert 'agentName: "sla_intelligence"' in (SITE / "workflow-data.js").read_text(encoding="utf-8")
