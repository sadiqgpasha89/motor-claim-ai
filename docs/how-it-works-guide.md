# How MotorClaim AI Works — Complete Operator, Developer & Demo Guide

> **Notice:** All seeded policies, vehicles, customers, surveyors, garages, rate cards, and payments are clearly labelled `DEMO / SYNTHETIC`.

---

## 1. Getting Started Locally

### Option A: Local Python + Next.js (Zero External DB Required)
```bash
# 1. Start the FastAPI backend (auto-creates SQLite DB and seeds demo data)
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/uvicorn apps.api.main:app --reload --port 8000

# 2. In a second terminal, start the Next.js portal
cd apps/web
npm install
npm run dev
```
- **Web Portal:** `http://localhost:3000`
- **Interactive OpenAPI Docs:** `http://localhost:8000/docs`

### Option B: Full Container Stack (PostgreSQL + pgvector + Redis + API + Web)
```bash
docker compose up --build
```

---

## 2. Role-Based Workspaces & Persona Switcher

In the top-right header of the web portal (`Active Persona` dropdown), you can instantly switch between 12 seeded demo users backed by real server-side JWT tokens (`POST /api/v1/auth/login`):

| Email | Role | What They Can Do & Server-Side Restrictions |
|---|---|---|
| `policyholder@demo.in` | `policyholder` | Register FNOL (`/fnol`), upload evidence, view own claims (`/portal`), raise grievances. Cannot view other customers' claims or SIU alerts. |
| `fnol@demo.in` | `fnol_executive` | Assisted claim intake, coverage checks, triage, surveyor assignment. |
| `handler@demo.in` | `claims_handler` | Full Claim 360 management, OCR verification, coverage/triage, settlement recommendation (L1 authority up to ₹75,000, blocked if fraud alert/EV/TP active). |
| `handler2@demo.in` | `claims_handler` | Independent second handler used as **Checker** for maker-checker approvals. |
| `surveyor@demo.in` | `surveyor` | Sees only assigned claims (`/partners`), reviews AI damage lines, submits signed survey reports. |
| `garage@demo.in` | `garage` | Sees only claims assigned to their workshop (`prov-gar-01`), submits estimates/supplements, updates repair milestones. Customer contact PII & SIU alerts are hidden. |
| `garage.ev@demo.in` | `garage` | The EV-certified, OEM-authorised workshop (`prov-gar-ev-02`). Records OEM diagnostics, post-repair HV recertification and battery salvage events on assigned EV claims only. A non-EV garage is refused (`403`). |
| `siu@demo.in` | `siu_investigator` | Accesses restricted SIU Fraud Desk (`/siu`), entity relationship graphs, and records alert dispositions (`substantiated` / `not_substantiated` / etc.). |
| `manager@demo.in` | `claims_manager` | Queue oversight, L2 approval up to ₹5,00,000 (including claims with open fraud alerts/EV), SLA monitoring, rule simulation, AI outage toggle. |
| `legal@demo.in` | `legal_tp` | Accesses restricted Third-Party bodily injury/medical party records (`CLM-DEMO-2026-0010`), owns the legal stages of the TP workflow (legal review, advocates, medical review), second approver at TP-L2, L3 authority up to ₹15,00,000. |
| `finance@demo.in` | `finance_approver` | Releases payments (`POST /payments`), validates bank penny-drop, reconciles gateway timeouts (`POST /reconcile`). |
| `auditor@demo.in` | `auditor` | Read-only audit trail, rule publication (`POST /rules/{id}/publish`), analytics, SLA & SIU oversight. |
| `admin@demo.in` | `admin` | Full governance, rule publishing, AI outage simulation, and demo seed reset (`POST /api/v1/operations/seed-reset`). |

---

## 3. Walkthrough: Primary End-to-End Demo (`CLM-DEMO-2026-0001`)

1. **Open Command Centre (`/`):** Log in as `handler@demo.in` and click `CLM-DEMO-2026-0001` (Maruti Baleno `MH02DEMO1042`, policy `POL-IN-DEMO-2026-1001` with Zero Depreciation + Consumables active).
2. **Inspect Evidence & OCR (`/claims/clm-demo-0001` → Evidence Tab):** View the 6 vehicle angle photos (`front`, `rear`, `left`, `right`, `odometer`, `closeup`) plus Policy Schedule, RC, and DL with SHA-256 checksums and extracted facts.
3. **Review Damage & Estimate Comparison (Damage & Estimate Tab):**
   - AI assistive damage marks `PRT-FRT-BMP-01` (Front Bumper), `PRT-HL-LED-RH` (LED Headlamp), and `PRT-FND-RH-01` (Front Fender) as `visible_observed`.
   - Garage estimate (`₹64,200`) shows two flagged anomalies against `RC-IN-2026-DEMO-V1`:
     - `DUPLICATE_LINE`: Front Bumper repeated twice (recommended amount automatically zeroed to `₹0.00`).
     - `RATE_VARIANCE`: Front Fender claimed at `₹10,800` vs OEM rate card `₹7,800` (+38.5%).
4. **Check SIU Alert Isolation:** Switch persona to `garage@demo.in` — the SIU Fraud tab shows restricted access and customer PII is hidden. Switch to `siu@demo.in` to view `FRD-EST-ANOMALY` with its benign explanation ("Common clerk copy-paste error in draft garage quotes") and mark it `not_substantiated`.
5. **Calculate Settlement & Maker-Checker Approval (Settlement Tab):**
   - As `handler@demo.in`, click **Generate Deterministic Settlement**. The calculator computes `₹48,700.00` gross, `₹0.00` depreciation (waived by Zero Dep), `₹1,000.00` compulsory excess = `₹47,700.00` net payable.
   - Try approving as `handler@demo.in`: blocked with `403 NOT_AUTHORISED` (same-user maker-checker violation).
   - Switch to `handler2@demo.in` (after SIU clears the alert) or `manager@demo.in` and approve!
6. **Idempotent Payment & Closure:** Switch to `finance@demo.in`, initiate payment (optionally tick **Simulate Gateway Timeout** -> then click **Reconcile Payment Safely**), switch to `garage@demo.in` to mark `handover_complete`, and close as `handler@demo.in`.

---

## 4. Seeded Edge-Case Scenarios (`CLM-DEMO-2026-0002` to `0012`)

| Claim Number | Scenario Demonstrated | Where to Inspect |
|---|---|---|
| `CLM-DEMO-2026-0002` | **Incomplete Documents Accepted:** Claim registered without RC/DL/Photos; follow-up checklist active (never auto-rejected per IRDAI 2024). | Command Centre / Portal |
| `CLM-DEMO-2026-0003` | **Policy/Vehicle Registration Mismatch:** OCR extracted `KA03DEMO9999` vs `KA03DEMO5521`; routed to `document_exception` for human correction. | Claim 360 → Evidence |
| `CLM-DEMO-2026-0004` | **Low-Quality Photo Recapture:** `dark_blurry_front.jpg` flagged `recapture_needed` with guided recapture instructions. | Claim 360 → Evidence |
| `CLM-DEMO-2026-0005` | **Survey Threshold Boundary (`₹49,500`):** Just below the ₹50,000 IRDAI mandatory survey threshold -> routed to `low_risk_od_assisted`. | Claim 360 → Triage |
| `CLM-DEMO-2026-0006` | **Surveyor SLA Breached:** Report overdue >15 days; `SLA Breached` badge and ₹500/day penalty exposure + open grievance. | Operations (`/operations`) |
| `CLM-DEMO-2026-0007` | **Hidden Structural Damage Supplement:** Radiator core support found during teardown while in `REPAIR_IN_PROGRESS`. | Claim 360 → Estimate |
| `CLM-DEMO-2026-0008` | **Fraud Alert Cleared (`not_substantiated`):** Early inception alert cleared after dashcam/NCB verification; claim approved. | SIU Desk (`/siu`) |
| `CLM-DEMO-2026-0009` | **Payment Timeout Awaiting Safe Reconciliation:** `timeout_reconcile_pending`; Finance reconciles safely without double payout. | Claim 360 → Settlement |
| `CLM-DEMO-2026-0010` | **Third-Party Bodily Injury:** Runs on the dedicated TP lifecycle (`GET /api/v1/claims/clm-demo-0010/tp`), seeded at `LIABILITY_INVESTIGATION` with queue `tp_liability_investigation`. OD settlement/approval/payment endpoints refuse it (`409`); medical/FIR party record masked unless logged in as `legal@demo.in` / authorised handler. | Claim 360 → Overview, `/api/v1/tp/queues` |
| `CLM-DEMO-2026-0011` | **EV Traction Battery Impact (dedicated EV workflow):** Tata Nexon EV on its own 11-stage EV lifecycle (`GET /api/v1/claims/clm-demo-0011/ev`). HV hold, triage and escalations acknowledged and resolved, flatbed recovery (`prov-tow-01`) and an EV-HV certified physical survey (`prov-surv-01`) are done; the case waits at `OEM_DIAGNOSTICS` for `garage.ev@demo.in`. The vehicle is never cleared from photographs, and OD settlement/approval/payment endpoints return `409` until technical sign-off. Also shows `LOW -> HIGH` risk transition in `risk_history`. | `/api/v1/ev/queues`, Claim 360 → `ev_workflow` |
| `CLM-DEMO-2026-0012` | **LOW RISK Fast-Track Auto-Approved (`₹16,500`):** Minor scuff, complete docs, valid policy, zero anomalies; straight-through auto-approved within `<= ₹25,000` limit (`IN-RISK-PROCESSING-2026`). | Claim 360 → Overview & Settlement |
| `CLM-OTH-2026-0001` | **Cross-Tenant Isolation:** Lives in `tenant-other-demo`; invisible and returns `403` to all `tenant-in-demo` users. | API / Security Tests |

---

## 5. Testing Governance, Rule Simulation & AI Outage Fallback

1. **Rule Threshold Simulation (`/governance`):** Log in as `manager@demo.in`, enter a proposed mandatory survey threshold (e.g. `₹75,000`) and run **Simulate Rule** (`POST /api/v1/rules/{rule_id}/simulate`) to preview the impact across all synthetic claims before publishing.
2. **AI Outage Simulation (`/operations`):** Log in as `admin@demo.in` or `manager@demo.in` and toggle **Simulate AI Model Outage** (`POST /api/v1/operations/ai-outage-toggle`). Notice that FNOL intake (`/fnol`), deterministic settlement math, and human approvals continue to work while AI agents cleanly return `needs_human` (`manual_workflow`).
