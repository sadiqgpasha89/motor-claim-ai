# Architecture — MotorClaim AI Intelligence Solution

## 1. Design Principles
- **Workflow-first, agent-assisted:** Relational DB (`services/claims/models.py`) and explicit state machine (`services/claims/state_machine.py`) own claim state, SLA timers, and transactional outbox events.
- **Deterministic financial & legal core:** All depreciation, excess, salvage, total-loss, and Delegation-of-Authority math uses Python `Decimal` and effective-dated JSON rules (`rules/india/`).
- **Replaceable AI & enterprise adapters:** Model Gateway (`services/agent_runtime/gateway.py`) and Integration Registry (`services/integrations/adapters.py`) isolate external providers behind contracts and support manual fallback during outages.

## 2. Logical Component Flow
1. **Channels (`apps/web`, Partner REST API)** -> **FastAPI Edge (`apps/api/main.py`)** with Correlation ID middleware and structured error catalogue.
2. **Security Layer (`packages/security/`)** enforces JWT authentication, server-side tenant isolation, ABAC (`enforce_claim_abac`, `enforce_siu_access`, `enforce_tp_medical_access`), PII masking, MIME/malware checks, and prompt-injection filtering.
3. **Domain & Workflow (`services/claims/`, `services/workflow/`)** persists state transitions, append-only `AuditEvent` SHA-256 hashes, `SLATimer` deadlines, and `OutboxEvent` records.
4. **Specialised Agents (`agents/specialists.py`)** execute bounded tasks using strict tool allowlists and typed Pydantic contracts (`packages/contracts/agents.py`).
