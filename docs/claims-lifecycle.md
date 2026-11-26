# Claims Lifecycle & State Machine

## Validated Claim States (`services/claims/state_machine.py`)
`INTIMATED` -> `REGISTERED` -> `EVIDENCE_PENDING` -> `COVERAGE_CHECKED` -> `TRIAGED` -> `SURVEY_ASSIGNED` / `AI_ASSESSMENT` -> `ESTIMATE_REVIEW` -> `SETTLEMENT_RECOMMENDED` -> `APPROVAL_PENDING` -> `APPROVED` -> `PAYMENT_INITIATED` -> `REPAIR_IN_PROGRESS` -> `CLOSED` (plus `CLARIFICATION_REQUESTED`, `DECLINED_PARTIAL`, `REOPENED`).

## Pathway Controls
- **Incomplete Intimation:** Always accepted (`REGISTERED` / `EVIDENCE_PENDING`) with structured document checklist; never auto-rejected.
- **Mandatory Survey:** Triggered deterministically when `estimated_loss_inr >= 50000.00` or for `theft`, `fire`, `flood`, `total_loss`, `injury_or_fatality`, or `ev_battery_impacted`.
- **TP Injury / Fatality:** Routed to `legal_tp_specialist` queue; medical/legal party records restricted to authorised TP/Legal roles.
- **EV High-Voltage:** Flagged with HV isolation alert and routed to `ev_specialist` queue & EV-certified network garage.
