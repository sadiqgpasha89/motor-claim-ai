# Canonical Data Dictionary (`services/claims/models.py`)

All tables use UUID string primary keys (never PAN, phone, policy number, or registration plate), `Numeric(14, 2)` for currency, and UTC timestamps.

- `tenants`: Multi-tenant isolation boundary.
- `users`: Role, branch, partner linkage (`partner_id`).
- `customers`: Tokenised phone (`phone_token`), masked contact fields, language preference.
- `vehicles`: Registration, VIN/chassis, engine, fuel/EV flag, `first_registration_date`.
- `policies`: Policy number, UIN, period, `idv_inr`, deductibles, `addons`, `endorsements`.
- `providers`: Verified surveyors (IIISLA licence) and network/EV garages.
- `claims`: Canonical claim record, `idempotency_key`, workflow state, severity, queue, missing docs.
- `claim_parties`: Insured, driver, third-party (`is_restricted_tp_medical` flag).
- `evidence` & `extracted_facts`: Immutable file SHA-256, malware status, prompt-injection flag, OCR fields with provenance & human verification status.
- `damage_assessments`: Assistive visual findings (`visible_observed` vs `inferred_possible`) + reviewer outcome.
- `estimates` & `estimate_lines`: Garage quotes, supplements, rate-card comparison, variance flags.
- `survey_assignments`: Surveyor SLA dates, signed inspection report.
- `fraud_alerts`: Explainable indicators, benign explanations, entity links, SIU disposition.
- `settlements`, `approvals`, `payments`: Itemised `Decimal` calculation trace, maker-checker approvals, idempotent payment + bank verification.
- `sla_timers`, `communications`, `grievances`, `rule_versions`, `audit_events`, `outbox_events`.
