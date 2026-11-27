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
- `POST /api/v1/claims/{claim_id}/provider-coordination` · `POST .../payments/agent-release`
- `GET /api/v1/rules` · `POST /api/v1/rules/{rule_id}/simulate` · `POST .../publish`
- `GET /api/v1/knowledge/search` · `GET /api/v1/providers`
- `GET /api/v1/operations/sla` · `GET /api/v1/operations/integrations` · `GET /api/v1/operations/analytics`

## Standard Error Codes (`packages/contracts/errors.py`)
`VALIDATION_ERROR`, `NOT_AUTHORISED`, `NOT_FOUND`, `STATE_CONFLICT`, `DUPLICATE_REQUEST`, `DEPENDENCY_UNAVAILABLE`, `RATE_LIMITED`, `AI_UNAVAILABLE`, `HUMAN_REVIEW_REQUIRED`, `INTEGRATION_REJECTED`. All errors return `correlation_id` and strip stack traces/PII.
