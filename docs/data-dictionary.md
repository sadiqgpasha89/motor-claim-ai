# Canonical Data Dictionary (`services/claims/models.py`)

All tables use UUID string primary keys (never PAN, phone, policy number, or registration plate), `Numeric(14, 2)` for currency, and UTC timestamps.

- `tenants`: Multi-tenant isolation boundary.
- `users`: Role, branch, partner linkage (`partner_id`).
- `customers`: Tokenised phone (`phone_token`), masked contact fields, language preference.
- `vehicles`: Registration, VIN/chassis, engine, fuel/EV flag, `first_registration_date`.
- `policies`: Policy number, UIN, period, `idv_inr`, deductibles, `addons`, `endorsements`.
- `providers`: Verified surveyors (IIISLA licence) and network/EV garages.
- `claims`: Canonical claim record, `idempotency_key`, workflow state, severity, queue, missing docs.
- `tp_claim_cases`: Third-Party liability case (1:1 with a `third_party` claim): `stage` (`TPStage`), `queue_name`, `stage_history`, third parties (restricted medical flag), accident facts & evidence, police/FIR, liability assessment, legal documents, tribunal, advocates, medical review, legal review, `reserve_inr` + history, settlement proposals with approvals, payment authorisation, closure. Created by `services/workflow/tp_liability.py`.
- `ev_claim_cases`: Electric-vehicle case (1:1 with an EV claim, `case_number` `EV-...`): `stage` (`EVStage`), `queue_name`, `stage_history`, `risk_class` (monotonic), `operation_status` (`hold_do_not_operate_pending_inspection` until recertification), triage signals, `safety_escalations`, `thermal_watch`, recovery, specialist survey, OEM diagnostics, battery disposition (OEM engineer reference), cost benchmark, technical sign-off, settlement clearance, recertification, salvage chain and closure.
- `claim_parties`: Insured, driver, third-party (`is_restricted_tp_medical` flag).
- `evidence` & `extracted_facts`: Immutable file SHA-256, malware status, prompt-injection flag, OCR fields with provenance & human verification status.
- `damage_assessments`: Assistive visual findings (`visible_observed` vs `inferred_possible`) + reviewer outcome.
- `estimates` & `estimate_lines`: Garage quotes, supplements, rate-card comparison, variance flags.
- `survey_assignments`: Surveyor SLA dates, signed inspection report.
- `fraud_alerts`: Explainable indicators, benign explanations, entity links, SIU disposition.
- `settlements`, `approvals`, `payments`: Itemised `Decimal` calculation trace, maker-checker approvals, idempotent payment + bank verification.
- `sla_timers`, `communications`, `grievances`, `rule_versions`, `audit_events`, `outbox_events`.
