# Pipelines — MotorClaim AI Intelligence Solution

This document details every operational, AI, financial, and engineering pipeline in the platform.

---

## 1. End-to-End Orchestrator-Driven Claim Pipeline

`ClaimOrchestrator` (`services/workflow/orchestrator.py`) owns state progression, Post-FNOL parallel wave fan-out, conditional/parallel assessment gating, exponential-backoff retries, DLQ/Saga compensation, and approval/payment gates.

```mermaid
flowchart TD
    A["1. SUBMITTED & REGISTERED\nFNOL Concierge\n(Idempotency-Key + Duplicate-Event Dedup)"] --> B1["2a. Policy Validation\nCoverageIntelligenceAgent\n(Parallel after FNOL)"]
    A --> B2["2b. Document Extraction\nDocumentIntelligenceAgent\n(Parallel OCR + Injection Quarantine)"]
    A --> B3["2c. Duplicate Claim Check\nOrchestrator / Fraud Screening\n(Parallel after FNOL)"]
    A --> B4["2d. Customer Communication\nCustomerCommunicationAgent\n(Parallel after FNOL)"]
    B1 --> D["3. VALIDATION -> TRIAGE\nClaimTriageAgent (Sequential)\n(IRDAI ₹50k Rule -> FAST_TRACK / SURVEY_REQUIRED / INVESTIGATION_REQUIRED / HUMAN_REVIEW)"]
    B2 --> D
    B3 --> D
    D --> E{"Conditional Branches\n(Photos / Survey / Peril)"}
    E -->|"Photos & Vehicle Ready"| F["4a. Damage Assessment\nDamageAssessmentAgent\n(Conditional Parallel)"]
    E -->|"Survey Required"| S["4b. Provider Coordination\nProviderCoordinationAgent\n(Surveyor + Garage + Towing)"]
    D --> G["4c. Fraud Analysis\nFraudIntelligenceAgent\n(Alert-Only, Parallel with Assessment)"]
    F --> H["5. ESTIMATE_VALIDATION\nEstimateValidationAgent\n(Rate Card RC-IN-2026 + Sequential Gate)"]
    S --> H
    G --> H
    B1 --> J
    H --> J["6. SETTLEMENT_PENDING_APPROVAL\nSettlementRecommendationAgent\n(Decimal Calculator + Policy Citations)"]
    J --> K["7. Human Approval Gate (DoA Maker-Checker)\nPOST /approvals\n(Forbids Same-User & Bulk Approval)"]
    K -->|"Approved -> APPROVED"| L["8. PAYMENT_PENDING & PAYMENT_RECONCILIATION\nPOST /payments + POST /reconcile"]
    K -->|"Returned / Rework"| B2
    L --> M["9. CLOSED\nQAComplianceAgent + Audit Retention"]
```

---

## 2. Document AI & Prompt-Injection Quarantine Pipeline

```mermaid
sequenceDiagram
    autonumber
    participant Client as Uploader (Web / API)
    participant API as FastAPI Edge
    participant Sec as packages/security/sanitizer.py
    participant DocAI as services/document_ai/processor.py
    participant Agent as DocumentIntelligenceAgent
    participant Vault as Evidence Vault + DB

    Client->>API: POST /claims/{id}/evidence (file)
    API->>Sec: validate_upload_bytes(filename, mime, bytes, max=25MB)
    Sec->>Sec: Sniff magic bytes (%PDF / JPEG / PNG / WEBP)
    Sec->>Sec: Scan EICAR malware signature & compute SHA-256
    alt Invalid MIME, oversized, or malware
        Sec-->>Client: 400 VALIDATION_ERROR
    else Clean binary
        API->>Vault: Persist immutable original file (sha256_filename)
        API->>DocAI: extract_document_facts(expected_policy, expected_reg)
        DocAI->>Sec: sanitize_untrusted_text(raw_text)
        Note over Sec: Strips "ignore previous instructions",<br/>"bypass maker-checker", script tags
        DocAI->>DocAI: Classify doc + Extract RC / Policy / DL fields + Check image quality
        DocAI->>Agent: Execute with minimised_facts
        alt Prompt injection flagged OR field mismatch
            Agent-->>API: status = needs_human (human_fact_verification)
        else Clean & matched
            Agent-->>API: status = completed
        end
        API-->>Client: 201 Created (doc_type, sha256, facts, agent_response)
    end
```

---

## 3. Hybrid Policy Retrieval (RAG) Pipeline

Implemented in `services/rules_engine/knowledge.py` (`HybridPolicyRetriever`):

1. **Corpus Indexing (`knowledge/synthetic_policy_samples/policies.json`):**
   - Loads `POL-WORDING-PC-2024` (Private Car Package) and `POL-WORDING-EV-2025` (EV Traction Battery Protect).
   - Splits into clause-level chunks retaining `document_id`, `uin`, `section`, `page`, and `clause_id`.
2. **IDF Pre-Computation:**
   - Tokenizes `title + section + text` and computes smoothed IDF weights across all policy clauses.
3. **Hybrid Scoring at Query Time:**
   - Computes TF-IDF vector cosine similarity (`weight = 0.65`) and exact keyword overlap ratio (`weight = 0.35`).
   - Returns top-`k` clauses with formatted provenance references (e.g., `POL-WORDING-PC-2024 ADDON-ZD-01 p.11`) attached to `CoverageIntelligenceAgent` and `SettlementCalculator` outputs.

---

## 4. Visual Damage Assessment (10-Step Pipeline) & Rate-Card Estimate Validation

Implemented in `services/damage_ai/assessor.py` & `agents/specialists.py` (`DamageAssessmentAgent`):

1. **10-Step Visual Damage Workflow:**
   1. Upload accident photos (`POST /api/v1/claims/{claim_id}/evidence`)
   2. Validate image quality (`good` / `poor` / `recapture` via resolution, luminance & contrast checks)
   3. Detect vehicle (`make`, `model`, `variant`) and localize visible damaged regions with bounding boxes
   4. Classify damaged components (`Bumper`, `Headlight`, `Door`, `Fender`, `Windshield`, `Bonnet`, `Rear Bumper`, `Tail Lamp`, `EV Battery Tray`, `Radiator Core Support`)
   5. Compare damage across photos (`corroborated`, `single_angle_only`, `conflicting`, `no_photo_coverage`)
   6. Identify inconsistencies (FNOL-vs-photo location mismatch, duplicate SHA-256 photo hash, vehicle identity mismatch)
   7. Generate `repair` / `replace` / `uncertain` recommendations governed by **per-component confidence** (high overall image quality never forces beyond-repair on an occluded/uncertain component)
   8. Estimate parts (OEM & OES), labour, and paint via `RC-IN-2026-DEMO-V1`
   9. Request additional photos where necessary (`request_documents`)
   10. Route uncertain cases (`repairability == "uncertain"`, `component_confidence < 0.72`, inconsistencies, `poor`/`recapture` frames, EV HV impact) to a human assessor (`NEEDS_HUMAN` + `ClaimTask`)
2. **Structured Output Fields:**
   - Emits `vehicle`, `damage_location`, `damaged_component`, `damage_severity`, `repairability`, `visible_damage`, `possible_hidden_damage`, `image_quality`, per-component `component_confidence` + `confidence_factors`, and bounding-box `evidence` refs.
3. **Estimate Line Validation (`validate_estimate_lines`):**
   - Compares each garage estimate line against `RC-IN-2026-DEMO-V1` (`knowledge/synthetic_policy_samples/rate_cards.json`):
     - **Duplicate Detection:** Repeated `(part_code, line_type)` triggers `DUPLICATE_LINE` anomaly and defaults recommended amount to `0.00` (without accusing fraud).
     - **Rate Variance:** Unit prices exceeding OEM rate card by `> 12.00%` trigger `RATE_VARIANCE` and cap recommended amount at OEM price.
     - **Quantity Anomaly:** `quantity > 2` on single-panel parts flags `QUANTITY_ANOMALY` for human review.
     - **Visible Damage Mismatch:** Parts absent from `DamageAssessment` are flagged `NOT_IN_VISIBLE_DAMAGE` for surveyor physical inspection.

---

## 5. Settlement, Maker-Checker & Idempotent Payment Pipeline

```mermaid
sequenceDiagram
    autonumber
    participant H1 as Handler 1 (Maker)
    participant Calc as SettlementCalculator
    participant DoA as validate_approval_authority
    participant H2 as Handler 2 / Manager (Checker)
    participant Fin as Finance Approver
    participant PG as Payment Gateway Adapter

    H1->>Calc: POST /settlement-recommendations
    Calc->>Calc: Decimal line depreciation + Zero Dep/Consumables waiver + Excess + CTL check
    Calc-->>H1: Settlement (pending_checker) + Approval (pending)
    H1->>DoA: Attempt self-approval (user_id == maker_user_id)
    DoA-->>H1: 403 NOT_AUTHORISED (Maker-checker violation)
    H2->>DoA: POST /approvals (different user, within DoA tier & conditions)
    DoA-->>H2: 200 APPROVED
    Fin->>PG: POST /payments (idempotency_key="pay-001", simulate_timeout=true)
    PG-->>Fin: 201 timeout_reconcile_pending (PG-PEND-...)
    Fin->>PG: Replay POST /payments (idempotency_key="pay-001")
    PG-->>Fin: 200 idempotent_replay=true (no duplicate transfer)
    Fin->>PG: POST /payments/{id}/reconcile
    PG-->>Fin: 200 status=confirmed (UTR-RECON-...)
```

---

## 6. CI/CD & Quality Gate Pipeline (`.github/workflows/ci.yml`)

Triggered on every push to `main` / `feat/**` and on pull requests to `main`:

| Job | Steps Executed | Target |
|---|---|---|
| `backend-checks` | `pip install -e ".[dev]"` -> `ruff check` -> `mypy --explicit-package-bases` -> `pytest -v` (unit, integration, security, model_eval) | Python 3.12 |
| `frontend-checks` | `npm ci` -> `npm run typecheck` (`tsc --noEmit`) -> `npm run lint` (`next lint`) -> `npm run build` | Node 20 / Next.js 14 |

## 7. AI Release Gate Pipeline (`.github/workflows/ai-release-gate.yml`)

Triggered on pushes and pull requests that touch agents, the agent runtime, prompts, contracts, security helpers, rules or `evals/`:

| Step | What it does |
|---|---|
| `pytest tests/evals` | Framework tests, including mutation tests proving the gate blocks sabotaged metrics, suites and registries |
| `python -m evals.gate --json --markdown` | Runs all datasets and six safety suites; writes the verdict to the job summary; exits 1 when the release is blocked |
| Site snapshot check | Fails if `site/eval-report.js` is out of sync with the gate output |

Details: [ai-evaluation.md](ai-evaluation.md).
