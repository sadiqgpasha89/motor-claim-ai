"""Exports the rules, labels, clauses and demo claim used by the settlement workbench to the static site.

The site cannot import the Python rule files, so this script writes ``site/settlement-workbench-data.js`` from the
same JSON sources the backend reads. A unit test regenerates the file in memory and fails when the committed copy
is stale, so the site and the backend can never silently drift apart.

Usage:  python scripts/export_settlement_workbench_data.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.rules_engine.loader import load_rule_files  # noqa: E402
from services.settlement.workbench import (  # noqa: E402
    DEMO_CLAIM_FILE,
    DEPRECIATION_RULE_ID,
    DOA_RULE_ID,
    SCENARIO_RULE_ID,
    load_policy_clauses,
)

OUTPUT = ROOT / "site" / "settlement-workbench-data.js"

HEADER = (
    "/* GENERATED FILE - do not edit by hand.\n"
    " * Source: rules/india/*.json, knowledge/synthetic_policy_samples/*.json\n"
    " * Regenerate with: python scripts/export_settlement_workbench_data.py\n"
    " */\n"
)


def build_payload() -> dict[str, object]:
    rules = load_rule_files()
    scenario_rule = rules[SCENARIO_RULE_ID]
    dep = rules[DEPRECIATION_RULE_ID]
    doa = rules[DOA_RULE_ID]
    clauses = load_policy_clauses(scenario_rule["policy_document_id"])
    return {
        "depreciation": {
            k: dep[k]
            for k in (
                "rule_id",
                "version",
                "part_category_rates",
                "metal_wood_age_schedule",
                "compulsory_deductible_by_vehicle_class_inr",
                "zero_depreciation_addon_waives_part_depreciation",
                "consumables_addon_covers_consumables",
                "constructive_total_loss_idv_ratio_threshold",
            )
        },
        "doa": {k: doa[k] for k in ("rule_id", "version", "authority_tiers")},
        "scenario_rule": scenario_rule,
        "clauses": {cid: {"clause_id": c["clause_id"], "page": c["page"], "title": c["title"]} for cid, c in clauses.items()},
        "demo": json.loads(DEMO_CLAIM_FILE.read_text(encoding="utf-8")),
    }


def render() -> str:
    body = json.dumps(build_payload(), indent=2, ensure_ascii=False)
    return (
        HEADER
        + "(function (root) {\n"
        + '  "use strict";\n'
        + f"  var data = {body};\n"
        + '  if (typeof module === "object" && module.exports) {\n'
        + "    module.exports = data;\n"
        + "  } else {\n"
        + "    root.SETTLEMENT_WORKBENCH_DATA = data;\n"
        + "  }\n"
        + '})(typeof self !== "undefined" ? self : this);\n'
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if the committed file is stale")
    args = parser.parse_args()
    rendered = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print(f"{OUTPUT.relative_to(ROOT)} is stale; run scripts/export_settlement_workbench_data.py")
            return 1
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
