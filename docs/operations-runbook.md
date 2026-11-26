# Operations Runbook

## Common Operational Scenarios
1. **Model Provider Outage:** Toggle `AI_SIMULATE_OUTAGE=true` (or use `POST /api/v1/operations/ai-outage-toggle`). FNOL intake, deterministic settlement, approvals, and payment reconciliation continue uninterrupted; agent steps cleanly emit `needs_human`.
2. **Payment Gateway Timeout:** Do NOT create a new payment with a different idempotency key. Use `POST /api/v1/claims/{claim_id}/payments/{payment_id}/reconcile` (or the "Reconcile Safely" button in Claim 360) to verify upstream UTR safely.
3. **Outbox Backlog / Event Delivery Failure:** Inspect `GET /api/v1/operations/integrations` and trigger `POST /api/v1/operations/outbox/{event_id}/retry`.
4. **Rule Rollback:** Update `status` to `retired` on the faulty `RuleVersion` row and republish the prior immutable version.
5. **Demo Data Reset:** Authorised `admin` or `claims_manager` can reset synthetic data via `POST /api/v1/operations/seed-reset`.
