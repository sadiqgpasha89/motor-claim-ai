# Operations Runbook

## Common Operational Scenarios
1. **Model Provider Outage:** Toggle `AI_SIMULATE_OUTAGE=true` (or use `POST /api/v1/operations/ai-outage-toggle`). FNOL intake, deterministic settlement, approvals, and payment reconciliation continue uninterrupted; agent steps cleanly emit `needs_human`.
2. **Payment Gateway Timeout:** Do NOT create a new payment with a different idempotency key. Use `POST /api/v1/claims/{claim_id}/payments/{payment_id}/reconcile` (or the "Reconcile Safely" button in Claim 360) to verify upstream UTR safely.
3. **Outbox Backlog / Event Delivery Failure:** Inspect `GET /api/v1/operations/integrations` and trigger `POST /api/v1/operations/outbox/{event_id}/retry`.
4. **Dead-Letter Queue (DLQ) Inspection, Replay & Compensation:** When exponential-backoff retries exhaust on an orchestration step, inspect `GET /api/v1/orchestration/dlq`. Recover transient failures via `POST /api/v1/orchestration/dlq/{dlq_id}/replay` or trigger Saga rollback via `POST /api/v1/orchestration/dlq/{dlq_id}/compensate` (or per-claim `POST /api/v1/claims/{claim_id}/orchestration/compensate`).
5. **Workflow Pause, Resume & Duplicate-Event Protection:** Temporarily halt progression using `POST /api/v1/claims/{claim_id}/orchestration/pause` (pauses active SLA timers), then resume via `POST /api/v1/claims/{claim_id}/orchestration/resume`. Re-delivery of identical event IDs/keys to `POST /api/v1/claims/{claim_id}/orchestration/events` is safely deduplicated via `uq_orch_event_dedup`.
6. **SLA Sweep & Escalation:** Execute `POST /api/v1/orchestration/sla/sweep` to evaluate active state timers, emit idempotent `SLABreached` events, and enqueue escalation tasks.
7. **Rule Rollback:** Update `status` to `retired` on the faulty `RuleVersion` row and republish the prior immutable version.
8. **Demo Data Reset:** Authorised `admin` or `claims_manager` can reset synthetic data via `POST /api/v1/operations/seed-reset`.
