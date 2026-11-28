# Product portal, KPI framework, guided demos and honest assessment

All data is DEMO and SYNTHETIC. Targets are illustrative ambition levels. They are not results.

## Nine portal sections and Claim 360

| Section | Web route | API |
|---|---|---|
| Executive Dashboard | `/executive-dashboard` | `GET /api/v1/portal/executive-dashboard` |
| Claims Workbench (search, filters, queue, Claim 360 links) | `/` | `GET /api/v1/claims` and `POST /api/v1/claims/{id}/assign` |
| Agent Command Center | `/agent-command-center` | `GET /api/v1/operations/agent-observability/dashboard` |
| Evidence Intelligence | `/evidence-intelligence` | `GET /api/v1/portal/evidence-intelligence` |
| Damage Assessment | `/damage-assessment` | `GET /api/v1/portal/damage-assessment` |
| Fraud & SIU | `/siu` | claim fraud-alert routes |
| Settlement Workbench | `/settlement-workbench` | `GET /api/v1/portal/settlement-workbench` |
| Human Review | `/human-review` | `GET /api/v1/portal/human-review` |
| Performance & Evaluation | `/performance` | `GET /api/v1/portal/performance` |

Extra pages: `/demos` (guided demos), `/vision` (capability model and assessment), `/portal` (customer tracking), `/partners` (garage and surveyor portal). Claim 360 is at `/claims/{id}/claim-360`. It answers: what happened, what is happening now, what is blocked, why, what the AI did, what the AI found, the next action, and whether you must act.

Management sections (executive dashboard, KPI framework, performance) need the manager, auditor or admin role. Other sections need an internal role. Garage, surveyor and policyholder roles do not get the portal API. The code is in `services/analytics/portal.py` and `apps/api/routes/portal.py`.

## KPI framework

`GET /api/v1/portal/kpi-framework`. The 17 KPIs, the 12-row traditional and agentic table and the five outcome targets come from `rules/common/product_framework.json`.

- Measured from the database: processing time (closed claims), stage times (SLA timers, as a proxy), approval-to-payment time, claims per handler, straight-through rate, human touchpoints, SLA breach rate, average settlement, estimate variance, fraud yield, false positive rate, rework rate and AI cost per claim.
- Not measured: customer satisfaction and cost per claim. There is no data source. The API returns `null` and the reason. It never invents a number.
- A KPI with no rows yet (for example no closed claims) is also `null`.
- Traditional baselines and agentic targets are illustrative. Many are empty on purpose.

## Five guided demos

`GET /api/v1/portal/demos` links each demo to a seeded claim and its Claim 360 screen.

1. Zero-touch eligible OD claim: `CLM-DEMO-2026-0012`.
2. Complex damage and estimate anomaly: `CLM-DEMO-2026-0001`.
3. Fraud intelligence: `CLM-DEMO-2026-0008`.
4. EV accident: `CLM-DEMO-2026-0011`.
5. Third-party injury claim, human-led: `CLM-DEMO-2026-0010`.

The seed runs the agents once on demos 2 to 5. Each run stops at the first human gate. Demo 1 stays in its approved state, because a run would send it back to document verification. Start a run with `POST /api/v1/claims/{id}/orchestrate` or `scripts/od_claim_demo.py`.

## Capability model and honest assessment

`GET /api/v1/portal/capability-model` returns the 16 capabilities with a state of `built` or `partial`, and the 10-row assessment. Partial means built with a simulated or sandbox dependency. The ratings are set by the team. Examples of what is not done: no real insurer system is connected, the vision model is simulated, no live model is evaluated, and no real officer has used the portal.

## Roadmap status

See [roadmap.md](roadmap.md).

## GitHub Pages

Section 2K of `site/index.html` shows the same views from `site/product-data.js`. Regenerate it with `python scripts/export_product_demo_data.py`.
