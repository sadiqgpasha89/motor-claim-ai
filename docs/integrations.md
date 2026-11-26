# Enterprise Integrations (`services/integrations/adapters.py`)

In local/MVP mode (`INTEGRATION_MODE=mock`), all external adapters run in clearly labelled `MOCK (DEMO)` mode while preserving full contract validation, idempotency keys, timeout simulation, and reconciliation:

1. **Core Policy Admin & Wording Repo** — Policy lookup, UIN, endorsements, wording clauses.
2. **Core Claims Ledger** — Outbox event publishing (`ClaimCreated`, `SettlementRecommended`, `PaymentConfirmed`, `ClaimClosed`).
3. **Payment Gateway & Bank Penny-Drop** — Validates payee account, enforces `idempotency_key`, supports `simulate_timeout=true` -> `timeout_reconcile_pending` -> `POST .../reconcile` without double payout.
4. **Surveyor IIISLA Roster & Garage Parts Catalogue** — Licence status verification and synthetic OEM/OES rate card (`RC-IN-2026-DEMO-V1`).
5. **WhatsApp / Email / SMS Notification Bus** — Template dispatch with human-review hold on adverse communications.
6. **Model Gateway** — Provider-neutral LLM/Vision/OCR abstraction with runtime outage simulation (`POST /api/v1/operations/ai-outage-toggle`).
