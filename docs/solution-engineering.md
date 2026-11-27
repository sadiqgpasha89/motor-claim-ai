# Solution Engineering & Design Patterns

This document details the concrete engineering patterns implemented across **MotorClaim AI** to make agentic AI safe, auditable, deterministic, and production-ready in a regulated insurance domain.

---

## 1. Separating Probabilistic AI from Deterministic Authority

A core failure mode in naive AI demos is letting an LLM calculate payouts, interpret coverage autonomously, or mutate database state directly. MotorClaim AI enforces a strict **two-plane boundary**:

- **Probabilistic / Assistive Plane (`agents/`, `services/document_ai/`, `services/damage_ai/`, `services/fraud_intelligence/`):**
  - Extracts OCR fields (marked `extracted_unverified` until human confirmation).
  - Retrieves exact policy wording clauses via hybrid TF-IDF + cosine vector search (`HybridPolicyRetriever`).
  - Identifies visible exterior damage vs inferred possible internal damage (`visible_observed` vs `inferred_possible`).
  - Flags estimate anomalies (`DUPLICATE_LINE`, `RATE_VARIANCE`, `QUANTITY_ANOMALY`) and explainable fraud leads with benign explanations.
- **Deterministic / Authoritative Plane (`services/claims/`, `services/rules_engine/`, `services/settlement/`):**
  - Enforces valid state transitions (`ALLOWED_TRANSITIONS` in `services/claims/state_machine.py`).
  - Computes every rupee using `Decimal` with `ROUND_HALF_UP` (`SettlementCalculator.calculate()`).
  - Enforces Delegation of Authority (`validate_approval_authority()`) and Maker-Checker separation of duties.
  - Emits immutable `AuditEvent` SHA-256 hashes and idempotent `OutboxEvent` records.

---

## 2. Deterministic Financial Calculation (`SettlementCalculator`)

Located in `services/settlement/calculator.py`, `SettlementCalculator` accepts typed `SettlementLineInput` items and applies effective-dated rules from `IN-MOTOR-DEPRECIATION-2024` and `IN-IRDAI-MC-2024`:

1. **Line-Type & Material Depreciation:**
   - `labour`: `0%`
   - `paint`: `50%` material component × `50%` = `25%` effective deduction
   - `consumable`: `0%` if `consumables` add-on is active (`ADDON-CONS-01`), otherwise `100%` excluded
   - `glass`: `0%`
   - `fibreglass`: `30%`
   - `rubber_nylon_plastic_tyres_tubes_batteries_airbags`: `50%`
   - `metal`: age-graded from `0%` (<= 6 months) up to `50%` (> 10 years) using vehicle `first_registration_date` vs `incident_at`
2. **Zero Depreciation Add-On Waiver (`ADDON-ZD-01`):**
   - When `addons["zero_depreciation"]` is `True`, part and paint depreciation is waived and tracked explicitly in `addon_waiver_inr`.
3. **Constructive Total Loss (CTL) Check (`SEC-1-4`):**
   - Computes `ctl_threshold = idv_inr * 0.75`. If net repair cost >= `ctl_threshold` (or `requested_pathway == "total_loss"`), switches pathway to `total_loss` and calculates `idv_inr - compulsory_excess - voluntary_excess - salvage`.
4. **Traceability:**
   - Stores a complete JSON `calculation_trace`, `rule_versions`, and `policy_citations` on the `Settlement` entity so any customer or auditor can trace every deduction to a policy clause.

### 2.1 Settlement Decision Workbench (`services/settlement/workbench.py`)

The calculator is wrapped by a workbench that evaluates **twelve scenarios** on the synthetic demo claim, always through `SettlementCalculator` so no second copy of the money rules exists: cashless repair, reimbursement, repair vs replacement, partial approval, supplementary estimate, total loss, constructive total loss, salvage recovery, Zero-Depreciation add-on, Consumables add-on, different deductibles, and underinsurance / IDV implications.

Every scenario returns the same eight-part decision record:

1. **Claimed** - amount and basis (garage quote, market value, structural estimate).
2. **Assessed** - after assessment adjustments (duplicate line, rate above benchmark, repair substitution, IDV basis).
3. **Approved** - after lines withheld pending evidence.
4. **Deducted** - tariff depreciation, compulsory/voluntary excess, retained salvage, pro-rata reduction, with add-on benefits shown separately.
5. **Policy clauses applied** - clause id, page and the reason it applied (`SEC-1-2`, `SEC-1-5`, `SEC-1-6`, `SEC-1-7`, `SEC-1-8`, `COND-CLAIM-02/03`, add-ons).
6. **Who approves** - resolved from `IN-DOA-MATRIX-2026` by `resolve_required_authority()` (checker role, limit, why lower tiers were skipped, payment-release role). The demo records no real approval.
7. **What the customer receives** - payee, outcome and what the customer still pays.
8. **Why it differs from the request** - an itemised reconciliation that must balance exactly (`why_different.balanced`).

Parameters, wording and the clause map live in `rules/india/settlement_scenario_rules.json` (`IN-SETTLEMENT-SCENARIOS-2026`); the demo claim is `knowledge/synthetic_policy_samples/demo_claim_settlement.json`. The API exposes it at `POST /api/v1/settlement/workbench` (what-if overrides, read-only).

**Static site mirror.** `site/settlement-engine.js` reproduces the engine with integer-paise `BigInt` arithmetic. `scripts/export_settlement_workbench_data.py` generates `site/settlement-workbench-data.js` from the same rule files, and `tests/unit/test_settlement_workbench.py` fails if that file is stale or if the JS and Python engines ever return different output.

---

## 3. Bounded Multi-Agent Runtime & Guardrails

Every agent in `agents/specialists.py` subclasses `BoundedAgent` (`services/agent_runtime/base.py`):

- **Tool Allowlist Enforcement:** `call_tool()` verifies `name in self.allowed_tools and name in request.allowed_tools`. Any unauthorized call raises `ToolPermissionError`.
- **PII Stripping at Execution Boundary:** Before `_run()` executes, `BoundedAgent.execute()` runs `mask_text_pii()` across string fields in `minimised_facts` to redact phone numbers, emails, PAN, and Aadhaar tokens.
- **Model Gateway Outage Fallback:** If `ModelGateway.is_outage_active()` is true, `ModelOutageError` is caught cleanly in `BoundedAgent.execute()` and converted into `AgentStatus.NEEDS_HUMAN` with `fallback_mode="manual_workflow"`, keeping claim intake and manual processing 100% operational.

---

## 4. Security, Isolation & Adversarial Defense

Implemented in `packages/security/`:

- **Server-Side Tenant & ABAC Isolation (`auth.py`):**
  - `enforce_claim_abac()`: Blocks cross-tenant requests (`403 NOT_AUTHORISED`). Scopes `policyholder` to `customer_id`, `garage` to `assigned_garage_id`, and `surveyor` to `assigned_surveyor_id`.
  - `enforce_siu_access()`: Restricts `/api/v1/siu/alerts`, `/entity-graph`, and `fraud_alerts` on Claim 360 to `{siu_investigator, claims_manager, auditor, admin}`. Garages also never receive customer contact details.
  - `enforce_tp_medical_access()`: Redacts third-party medical/legal party records for unauthorized roles.
- **Upload & Prompt-Injection Sanitization (`sanitizer.py`):**
  - `validate_upload_bytes()` enforces size limits (`25 MB`), magic-byte MIME sniffing (`%PDF`, JPEG, PNG, WEBP), EICAR malware signature rejection, and SHA-256 hashing.
  - `sanitize_untrusted_text()` scans uploaded OCR/text payloads and FNOL descriptions for injection directives (e.g., `"ignore previous instructions"`, `"bypass maker-checker"`, `"approve claim immediately"`, `<script>`), replacing them with `[FILTERED_UNTRUSTED_DIRECTIVE]` and routing the document to `needs_human`.
- **Maker-Checker & Anti-Bulk Controls (`authority.py`, `routes/claims.py`):**
  - Same-user approval (`user_id == maker_user_id`) raises `403 NOT_AUTHORISED`.
  - Open fraud alerts, EV battery impact, or TP injury block L1 `claims_handler` approval (`403 HUMAN_REVIEW_REQUIRED`) and force escalation to `claims_manager` / `legal_tp`.
  - `POST /api/v1/claims/{claim_id}/approvals/bulk` always returns `403 NOT_AUTHORISED`.

---

## 5. Reliability, Idempotency & Auditability

- **Idempotency Keys:**
  - `Claim` (`uq_claim_idempotency`) and `Payment` (`uq_payment_idempotency`) enforce `(tenant_id, idempotency_key)` uniqueness. Replayed requests return the original entity with `idempotent_replay: true` and never create duplicate claims or double payouts.
- **Safe Payment Reconciliation:**
  - Simulated gateway timeouts store `status="timeout_reconcile_pending"` with a pending gateway reference. Finance operators reconcile via `POST /api/v1/claims/{claim_id}/payments/{payment_id}/reconcile` rather than blindly retrying a second transfer.
- **Append-Only Audit Ledger & Transactional Outbox:**
  - `record_audit_event()` computes SHA-256 `before_hash` and `after_hash` payloads linked to `X-Correlation-ID`.
  - `emit_outbox_event()` persists domain events atomically in the same DB transaction, supporting operator retry via `POST /api/v1/operations/outbox/{event_id}/retry`.
