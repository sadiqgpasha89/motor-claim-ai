# Claim Intelligence (Phase 2)

This page covers the Phase 2 items of the roadmap. All data is DEMO / SYNTHETIC. Thresholds are illustrative.
Every result is advisory. A human keeps the decision.

All thresholds live in `rules/india/intelligence_rules.json` (rule `IN-INTELLIGENCE-2026`). Code reads them with
`services/rules_engine/intelligence.py`. No threshold is hardcoded in a prompt or a route.

## Capabilities

| Capability | Code | Endpoint |
|---|---|---|
| Repair vs replace, component confidence, CTL check | `services/damage_ai/repair_replace.py` | `GET /claims/{id}/repair-replace-analysis` |
| Parts and labour benchmarking | `services/damage_ai/benchmarking.py` | `GET /claims/{id}/estimate-benchmark` |
| Multimodal damage fusion | `services/damage_ai/multimodal.py` | `GET /claims/{id}/multimodal-fusion` |
| Supplementary estimate review | `services/claims/supplementary.py` | `POST /claims/{id}/estimates` with `is_supplement=true` |
| Predicted claim complexity | `services/workflow/complexity.py` | `GET /claims/{id}/complexity`, `GET /operations/complexity-backtest` |
| Fraud relationship graph | `services/fraud_intelligence/graph.py` | `GET /claims/{id}/fraud-network`, `POST /claims/{id}/fraud-network/siu-lead` |
| Predicted SLA risk | `services/sla/` (existing engine) | Shown in `GET /claims/{id}/claim-360` under `intelligence.sla_risk` |

## Rules that matter

- **Repair vs replace.** Plastic, metal and glass parts follow a severity limit and a repair-to-replace cost ratio.
  Safety critical parts and the EV traction battery are never decided from photographs. They go to a human.
- **Confidence floor.** A decision under the floor needs a human assessor.
- **Constructive total loss.** If the claim repair cost is near the IDV, the result asks for a total loss review.
- **Benchmarking.** Parts use an OES to OEM band. Labour uses the city tier multiplier. Adjacent panels get an overlap
  discount on labour and a blend discount on paint. A flag is a review item. It is not proof of overcharging.
- **Supplements.** Variance and gross are checked on the cumulative total of all estimates. A supplement above the
  variance limit, or outside the original damage zone, opens one re-inspection task. The settlement already sums
  all estimates, so approval authority uses the cumulative total. A supplement is refused in claim states that
  have no estimate yet.
- **Payment guard.** `POST /claims/{id}/payments` now pays only the settlement net minus money already paid or in
  flight on the claim. If nothing is left, it returns 409. This stops a double payout on a revised settlement.
- **Complexity.** A transparent additive rules baseline with named drivers. It is not a trained model. The backtest
  compares the simple band with the fast-track path on current data.
- **Fraud graph.** Shared evidence, bank account, phone, vehicle, garage, surveyor, location and customer links have
  weights. Links combine as `1 - product(1 - weight)`. A dense cluster of three or more claims is a possible ring.
  A high score opens an SIU lead. The system never rejects a claim from this score.

## Interfaces

- Web: the Claim 360 page now refreshes every 10 seconds (toggle on the page) and has a Claim intelligence panel.
- Site: section 2I shows a capture of live API calls. Regenerate it with `python scripts/export_intelligence_demo_data.py`.
