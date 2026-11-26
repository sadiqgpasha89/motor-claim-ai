# Pipelines — MotorClaim AI Intelligence Solution

This document details every operational, AI, financial, and engineering pipeline in the platform.

---

## 1. End-to-End Claim Processing Pipeline

```mermaid
flowchart TD
    A["1. FNOL Intimation\nPOST /api/v1/claims/intimations\n(Idempotency-Key + FNOLConciergeAgent)"] --> B["2. Evidence Vault & OCR\nPOST /api/v1/claims/{id}/evidence\n(MIME + EICAR + Prompt-Injection + DocumentIntelligenceAgent)"]
    B --> C["3. Coverage & Policy RAG\nPOST /api/v1/claims/{id}/coverage-checks\n(HybridPolicyRetriever + CoverageIntelligenceAgent)"]
    C --> D["4. Deterministic Triage & SLA\nPOST /api/v1/claims/{id}/triage\n(IN-IRDAI-MC-2024 ₹50,000 Rule + ClaimTriageAgent)"]
    D --> E{"Mandatory Survey\nor Special Peril?"}
    E -->|"Yes (>= ₹50k / EV / TP / Theft / Fire)"| F["5a. Assign Verified Surveyor\nPOST /surveyor-assignments\n(15-day SLA Timer + SMS/Portal Notice)"]
    E -->|"No (< ₹50k standard OD)"| G["5b. AI-Assisted Assessment\nPOST /damage-assessments"]
    F --> H["6. Damage AI + Garage Estimate\nPOST /estimates\n(Rate Card RC-IN-2026 + Duplicate Detection)"]
    G --> H
    H --> I["7. Surveyor Signed Report & SIU Check\nPOST /survey-reports & POST /fraud-checks\n(Alert-Only FraudIntelligenceAgent)"]
    I --> J["8. Deterministic Settlement\nPOST /settlement-recommendations\n(Decimal Calculator + Policy Citations)"]
    J --> K["9. Maker-Checker DoA Approval\nPOST /approvals\n(Forbids Same-User & Bulk Approval)"]
    K -->|"Approved"| L["10. Idempotent Payment & Recon\nPOST /payments + POST /reconcile"]
    K -->|"Returned"| B
    L --> M["11. Repair Milestones & QA Closure\nPOST /repair-status + POST /close\n(QAComplianceAgent + Audit Retention)"]
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

## 4. Damage Vision & Rate-Card Estimate Validation Pipeline

Implemented in `services/damage_ai/assessor.py`:

1. **Image Coverage & Quality Gate:**
   - Checks uploaded images across the 6 required views (`front`, `rear`, `left`, `right`, `odometer`, `closeup`) and flags files marked `recapture_needed` (blurry, dark, or resolution `< 320x240`).
2. **Assistive Damage Observation Separation:**
   - Emits `visible_observed` observations (e.g., `PRT-FRT-BMP-01` Front Bumper, `PRT-HL-LED-RH` Headlamp) separately from `inferred_possible` items (e.g., `PRT-RAD-SUP-01` Radiator Core Support, `PRT-EV-BAT-TRAY` EV Underbody Tray) with explicit limitations.
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
