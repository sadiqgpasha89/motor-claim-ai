# REST API & Error Catalogue

Interactive OpenAPI 3.1 schema is served at `GET /openapi.json` and `GET /docs`.

## Representative Endpoints (`/api/v1`)
- `POST /api/v1/auth/login` · `GET /api/v1/auth/users` · `GET /api/v1/auth/me`
- `GET /api/v1/claims` (supports `risk_tier`, `operational_path`, `status`, `queue_name`, `claim_type`, `search` filters) · `POST /api/v1/claims/intimations` (supports `Idempotency-Key`, `multiple_vehicles_involved`, `legal_dispute`, `documents_complete_at_fnol`)
- `GET /api/v1/claims/{claim_id}` · `GET /api/v1/claims/{claim_id}/risk` · `POST /api/v1/claims/{claim_id}/risk/recalculate` · `GET /api/v1/claims/{claim_id}/timeline`
- `POST /api/v1/claims/{claim_id}/evidence` · `PATCH /api/v1/claims/{claim_id}/evidence/{ev_id}/facts/{fact_id}`
- `POST /api/v1/claims/{claim_id}/coverage-checks` · `POST /api/v1/claims/{claim_id}/triage`
- `POST /api/v1/claims/{claim_id}/damage-assessments` · `PATCH .../damage-assessments/{id}`
- `POST /api/v1/claims/{claim_id}/estimates` · `PATCH .../estimates/{est_id}/lines/{line_id}`
- `POST /api/v1/claims/{claim_id}/surveyor-assignments` · `POST .../survey-reports`
- `POST /api/v1/claims/{claim_id}/fraud-checks` · `GET /api/v1/siu/alerts` · `POST .../fraud-alerts/{id}/disposition` · `GET .../entity-graph`
- `POST /api/v1/claims/{claim_id}/settlement-recommendations` · `POST .../approvals`
- `POST /api/v1/claims/{claim_id}/payments` · `POST .../payments/{id}/reconcile`
- `POST /api/v1/claims/{claim_id}/repair-status` · `POST .../close` · `POST .../reopen`
- `POST /api/v1/claims/{claim_id}/communications` · `POST .../grievances` · `PATCH .../grievances/{id}`
- `GET /api/v1/agents/contracts` (11-agent capability matrix & I/O contracts)
- `GET /api/v1/orchestration/workflow-model` (Canonical 15-state workflow specification with 8-part state contracts & 15-task DAG schedule)
- `GET /api/v1/orchestration/dlq` · `POST /api/v1/orchestration/dlq/{dlq_id}/replay` · `POST /api/v1/orchestration/dlq/{dlq_id}/compensate`
- `POST /api/v1/orchestration/sla/sweep` (Sweep active state SLA timers, mark breaches, and enqueue escalation tasks)
- `GET /api/v1/claims/{claim_id}/orchestration` · `POST .../orchestrate` · `POST .../orchestrate/{agent_name}`
- `POST /api/v1/claims/{claim_id}/orchestration/events` (Idempotent orchestration event ingestion with duplicate-event protection)
- `POST /api/v1/claims/{claim_id}/orchestration/pause` · `POST .../orchestration/resume` · `POST .../orchestration/recover` · `POST .../orchestration/compensate`
- `POST /api/v1/claims/{claim_id}/rework`
- `GET /api/v1/claims/{claim_id}/tasks` · `PATCH .../tasks/{task_id}` · `GET .../decisions`
- `POST /api/v1/claims/{claim_id}/provider-coordination` · `GET /api/v1/claims/{claim_id}/ecosystem` · `POST .../ecosystem/inspection/reschedule` · `POST .../ecosystem/surveyor-followup` · `POST .../ecosystem/parts-check` · `POST .../ecosystem/logistics` · `POST .../ecosystem/repair-completion` · `POST .../payments/agent-release`
- **Third-Party (TP) liability workflow** (`IN-TP-LIABILITY-2026`; human-only, no autonomous endpoint):
  - `GET /api/v1/tp/lifecycle` · `GET /api/v1/tp/queues` · `GET /api/v1/tp/cases`
  - `POST /api/v1/claims/{claim_id}/tp/open` · `POST .../tp/exposures` (OD claim raises a separate linked TP claim) · `GET .../tp`
  - Intake & investigation: `POST .../tp/coverage-check` · `.../tp/third-parties` · `.../tp/facts` · `.../tp/police-report` · `.../tp/liability-assessment`
  - Legal: `POST .../tp/legal-documents` · `.../tp/tribunal` · `.../tp/advocates` · `.../tp/medical-review` · `.../tp/legal-review` · `.../tp/reserve`
  - Control: `POST .../tp/advance` · `.../tp/settlement-proposals` · `.../tp/settlement-proposals/{proposal_id}/decision` · `.../tp/payment-authorisation` (+ `/reconcile`) · `.../tp/close`
  - OD-only endpoints (`settlement-recommendations`, `approvals`, `payments`, `payments/agent-release`, `close`) return `409 HUMAN_REVIEW_REQUIRED` for TP claims.
- **Electric-vehicle (EV) claims workflow** (`IN-EV-CLAIMS-2026`; human-gated, never cleared from photographs):
  - `GET /api/v1/ev/lifecycle` · `GET /api/v1/ev/queues` · `GET /api/v1/ev/cases`
  - `POST /api/v1/claims/{claim_id}/ev/open` (also opened automatically at FNOL for an EV, an EV high-voltage peril or `ev_battery_impacted`) · `GET .../ev` (policyholders receive only a customer safety view)
  - Safety: `POST .../ev/triage` · `.../ev/safety-escalations` (raisable by the policyholder) · `.../ev/safety-escalations/{escalation_id}/acknowledge` · `.../resolve` (evidence reference + thermal-stable confirmation; resolver differs from raiser) · `.../ev/thermal-watch/clear`
  - Specialist path: `POST .../ev/recovery` (flatbed, EV-HV qualified provider, HV isolation, quarantine) · `.../ev/specialist-survey` (physical inspection by an EV-HV certified surveyor) · `.../ev/oem-diagnostics` · `.../ev/battery-disposition` (OEM engineer reference required)
  - Cost & sign-off: `POST .../ev/cost-benchmark` · `.../ev/cost-benchmark/review` · `.../ev/technical-sign-off` (the only call that lifts the settlement hold)
  - After settlement: `POST .../ev/recertification` · `.../ev/salvage-events` · `.../ev/advance` · `.../ev/close`
  - OD-only endpoints (`settlement-recommendations`, `approvals`, `payments`, `payments/agent-release`) return `409 HUMAN_REVIEW_REQUIRED` for an EV claim until technical sign-off, and `close` until the EV case is closed. The error `details` carry `rule_id`, `ev_workflow_url` and the `blockers`.
- **Predictive SLA operations** (`docs/sla-management.md`; read endpoints for internal roles, execute mode for `claims_manager` / `admin`):
  - `GET /api/v1/sla/rules` · `POST /api/v1/sla/rules/validate` (dry run, never publishes)
  - `GET /api/v1/sla/dashboard` · `GET /api/v1/sla/predictions?min_risk_band=&limit=` · `GET /api/v1/sla/insights` · `GET /api/v1/claims/{claim_id}/sla`
  - `POST /api/v1/sla/agent/run` `{mode: recommend|execute, claim_ids?, min_risk_band?, limit?}`
- `GET /api/v1/rules` · `POST /api/v1/rules/{rule_id}/simulate` · `POST .../publish`
- `GET /api/v1/knowledge/search` · `GET /api/v1/providers` · `GET /api/v1/ecosystem/dashboard`
- `GET /api/v1/operations/sla` · `GET /api/v1/operations/integrations` · `GET /api/v1/operations/analytics`
- `GET /api/v1/claims/{claim_id}/claim-360` · `GET /api/v1/claims/{claim_id}/agent-timeline` · `GET /api/v1/operations/agent-observability/dashboard` · `GET /api/v1/operations/agent-observability/traces` · `GET /api/v1/operations/approval-queue` (see [agent-observability.md](agent-observability.md))

## Standard Error Codes (`packages/contracts/errors.py`)
`VALIDATION_ERROR`, `NOT_AUTHORISED`, `NOT_FOUND`, `STATE_CONFLICT`, `DUPLICATE_REQUEST`, `DEPENDENCY_UNAVAILABLE`, `RATE_LIMITED`, `AI_UNAVAILABLE`, `HUMAN_REVIEW_REQUIRED`, `INTEGRATION_REJECTED`. All errors return `correlation_id` and strip stack traces/PII.
