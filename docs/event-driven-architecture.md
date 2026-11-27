# Event-Driven Architecture and Integrations (Phase 3)

This page covers feedback item 18 and Phase 3 of the roadmap. All data is DEMO / SYNTHETIC.
The table says what is built and what is only an interface. It does not claim more than the code does.

## Component map

| Component | Status | Where | Production upgrade |
|---|---|---|---|
| Event bus | Built, database backed | `services/events/bus.py` | Move delivery to Kafka or SQS. Keep the consumer interface. |
| Transactional outbox | Built | `services/claims/audit.py` (`emit_outbox_event`) | None needed. |
| Idempotent consumers | Built | `event_deliveries` table, unique per (event, consumer) | None needed. |
| Dead letter queue | Built, two levels | Orchestrator DLQ (`dead_letter_queue`) and dead event deliveries | Alert on queue depth. |
| Durable workflow engine | Partly built | State lives in `orchestration_tasks`. `services/workflow/recovery.py` resumes idle workflows | Use Temporal for timers, signals and long waits. |
| Agent task queue | Partly built | `orchestration_tasks` (`pending`, `scheduled`) | A real queue with worker pools. |
| LLM gateway | Built | `services/agent_runtime/llm_gateway.py` | Add a real provider adapter. |
| Tool gateway | Built | `services/integrations/gateway.py` | None needed. |
| Trace store | Built | `agent_execution_records` | Export to an OpenTelemetry backend. |
| Object storage | Interface only | Evidence goes to a local folder (`evidence_storage_dir`) | S3 or Blob with object lock for legal hold. |
| Cache | Not built | None | Redis. Nothing in the demo needs it. |
| Secrets manager | Interface only | `packages/security/secrets.py` | A cloud secrets manager behind `SecretsProvider`. |
| Metrics, logs, traces | Built for metrics and logs | `GET /api/v1/operations/metrics` (Prometheus text), JSON logs with correlation id | Scrape the metrics. Add distributed traces. |

## Event flow

1. A business change writes an outbox row in the same transaction.
2. `POST /api/v1/operations/events/dispatch` runs the relay. It sends each event to each registered consumer.
3. One `event_deliveries` row per (event, consumer) gives idempotent delivery. A delivered row is never sent again.
4. A failed delivery retries with backoff (2, 4 seconds and so on). After three attempts it is `dead`.
5. An operator replays a dead delivery with `POST /api/v1/operations/events/deliveries/{id}/replay`.

Built-in consumers: `claims_ledger` (all events) and `customer_notifications` (payment, estimate and closure events).

`shortcut:` the relay is a function that scans the newest 200 events of a tenant. It is not a long-running broker.

## Integration adapters

`services/integrations/sandbox.py` has sandbox adapters for the six systems: claims system, policy admin, garage,
surveyor roster, payment gateway and messaging (WhatsApp, SMS, email). Each can be told to fail,
so retry, circuit and fallback are testable. A live adapter implements the same methods.

External API resilience (`services/integrations/resilience.py`):

- Retry with exponential backoff for transient errors only.
- A permanent error (a rejected request) is not retried and does not trip the circuit.
- A circuit breaker per dependency: closed, open after repeated failures, half-open after the reset time.
- Messaging falls back from WhatsApp to SMS to email. The channel gets a customer token, never a phone number.

## Durable workflow recovery

Task state is stored, so a crash loses no task. `POST /api/v1/operations/workflows/recover` finds open claims that have
runnable tasks idle for more than 15 minutes. It sends each one a recovery event. The event id has the claim and the hour,
so a second sweep in the same hour is ignored by the orchestrator.

## Honest limits

- The orchestrator is still our own engine. It does not give Temporal features such as durable timers and signals.
- The relay and the recovery sweeper run when called. Schedule them in production.
- Rate limits and circuit state live in process memory. With more than one API instance, move them to a shared store.
