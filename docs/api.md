# REST API & Error Catalogue

Interactive OpenAPI 3.1 schema is served at `GET /openapi.json` and `GET /docs`.

## Representative Endpoints (`/api/v1`)
- `POST /api/v1/auth/login` · `GET /api/v1/auth/users` · `GET /api/v1/auth/me`
- `GET /api/v1/claims` · `POST /api/v1/claims/intimations` (supports `Idempotency-Key`)
- `GET /api/v1/claims/{claim_id}` · `GET /api/v1/claims/{claim_id}/timeline`
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
- `GET /api/v1/rules` · `POST /api/v1/rules/{rule_id}/simulate` · `POST .../publish`
- `GET /api/v1/knowledge/search` · `GET /api/v1/providers`
- `GET /api/v1/operations/sla` · `GET /api/v1/operations/integrations` · `GET /api/v1/operations/analytics`

## Standard Error Codes (`packages/contracts/errors.py`)
`VALIDATION_ERROR`, `NOT_AUTHORISED`, `NOT_FOUND`, `STATE_CONFLICT`, `DUPLICATE_REQUEST`, `DEPENDENCY_UNAVAILABLE`, `RATE_LIMITED`, `AI_UNAVAILABLE`, `HUMAN_REVIEW_REQUIRED`, `INTEGRATION_REJECTED`. All errors return `correlation_id` and strip stack traces/PII.
