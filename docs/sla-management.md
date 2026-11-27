# Predictive SLA Operations

SLA management is predictive and operational: it answers *what is breached*, *what is about to breach and why*, and *what should be done about it*, and it lets a bounded agent do the safe part. No SLA value is hardcoded in prompts, API handlers or the UI.

| Layer | Where | Role |
|---|---|---|
| Rules service | `rules/common/sla_rules.json`, `services/sla/rules.py` | Versioned, effective-dated catalogue; validation; claim-type families |
| Clock engine | `services/sla/events.py`, `services/sla/engine.py` | Event-derived clocks with pause intervals, breach status and penalty accrual |
| Predictor | `services/sla/predictor.py` | Explainable breach probability (`sla-risk-baseline-v1`) with ranked drivers |
| Portfolio | `services/sla/portfolio.py`, `services/sla/service.py` | Dashboard, rankings, surveyor/garage/document/queue reports |
| Actions | `services/sla/actions.py` | Recommendation planner and the single authorisation gate |
| Agent | `PredictiveSLAAgent` (`sla_intelligence`) in `agents/specialists.py` | Re-predicts, plans, authorises and applies through `ControlledActionExecutor` |
| API | `apps/api/routes/sla.py` | Read endpoints and the agent run endpoint |
| Showcase | `site/sla.js`, `site/sla-catalogue.js` | Dashboard, rule explorer, predictive lab (catalogue is generated, not copied by hand) |

## 1. The eight metrics

| Metric | Default target in the shipped catalogue | Regulatory window (where one exists) |
|---|---|---|
| Claim registration | Near real-time (5 min) | Acknowledgement within 24 h |
| Document verification | Configurable (v1.0.0 36 h, v1.1.0 24 h from 2026-07-01; third-party 72 h) | none |
| Surveyor assignment | Configurable (6 h) | 24 h |
| Survey completion | Internal 7 days | Surveyor report within 15 days; penalty accrues after it |
| Estimate approval | Configurable (48 h) | Decision within 7 days of the survey report |
| Repair completion | Configurable (10 days) | none |
| Payment processing | Configurable (72 h own damage, 120 h third party) | none |
| Claim closure | Configurable (72 h) | none |

These are demonstration values from `sla_rules.json`. Regulatory references are taken from the catalogue and need compliance sign-off before production use; tenants are expected to tune the configurable ones by publishing a new rule version.

## 2. SLA rules service

Every rule carries: **rule version**, **applicable claim types**, **trigger event**, **start condition**, **pause conditions**, **deadline**, **escalation sequence**, **responsible team** and **breach action** (plus the stop event, owner role and queue).

- **Versioning.** A clock uses the highest rule version in force *at the moment the clock starts*, so changing a rule never rewrites the history of claims already running.
- **Claim types.** `own_damage`, `cashless`, `reimbursement`, `total_loss` and `theft` resolve to the own-damage family; `third_party` has its own rules (and no estimate-approval, repair or survey clocks).
- **Start conditions** use a small declarative DSL (`all` / `any` / `fact` + `op`). Unknown facts, events and actions are rejected at validation, not at 2 a.m. in production.
- **Validation.** `POST /api/v1/sla/rules/validate` dry-runs a draft catalogue (unknown events, facts or actions, escalation steps that are not ascending, duplicate versions, metrics with no rule). It never publishes anything.
- **Source.** `get_active_rule` reads the database and falls back to the files, the same as every other rule catalogue.

## 3. Clocks

Clocks are derived from claim events rather than stored counters. Each event is resolved from a table timestamp, an audit event, or (when the system does not record it) inferred from the claim status; the provenance (`table` / `audit` / `inferred`) is reported with every clock, and the dashboard shows the share of inferred events so the figures are not over-trusted.

Pause intervals come from task lifecycle and claim status (for example, document verification pauses while a `document_request` task is open). Overlapping pauses are merged so time is never double counted, and the deadline moves out by the paused time. Clock statuses: `running`, `paused`, `breached`, `met`, `met_late`.

## 4. Predictive model

`sla-risk-baseline-v1` compares the **expected remaining work** with the **remaining SLA budget** under a normal uncertainty band. Expected work starts from the rule's typical duration and is scaled by factors the catalogue defines (`risk_model`): owner capacity, slow owner turnaround, inspection reschedules, unanswered follow-ups, risk tier, EV specialist scarcity and queue pressure; additive delays cover a missing inspection slot, parts lead time and outstanding customer documents.

A clock that has already outrun its typical duration is deliberately *not* treated as nearly done: its residual-work floor grows with the overrun, because late work tends to run later still.

It is a transparent heuristic, not a trained model. Every probability ships with its drivers, and the `predict_instance` contract (instance + signals in, prediction out) lets a trained model replace it without touching callers. Calibration against real breach outcomes is a prerequisite for production use.

## 5. What the agent predicts and recommends

| Question | Endpoint / report |
|---|---|
| Which claims are likely to breach | `GET /api/v1/sla/predictions` (ranked, with drivers) |
| Which garages are causing delays | `GET /api/v1/sla/insights` → `garages` |
| Which surveyors are overloaded | `GET /api/v1/sla/insights` → `surveyors` |
| Which documents are likely to delay processing | `GET /api/v1/sla/insights` → `documents` |
| Which queues have bottlenecks | `GET /api/v1/sla/insights` → `queues` |

Recommended actions: reassignment, escalation, reminder, scheduling and prioritisation. Each recommendation carries its urgency, a plain-language rationale and its autonomy class.

## 6. What the agent may execute

`POST /api/v1/sla/agent/run` takes `mode` = `recommend` (read-only; nothing is written) or `execute`.

| Action | Authority | Tool |
|---|---|---|
| Reminder to owner, surveyor follow-up, customer document reminder | Agent executes | `create_claim_task`, `send_surveyor_followup`, `request_documents` |
| Escalate to team lead / claims manager, prioritise in queue, schedule slot | Agent executes (as a task) | `create_claim_task` |
| Reassign surveyor, reassign garage, rebalance queue | **Human approval**: becomes a `claims_manager` approval task | none; the agent never reassigns |

Guardrails (all from the catalogue's `agent_guardrails`): act only above the minimum breach probability; a per-claim action budget per run; a cooldown on repeat reminders; execute mode only for `claims_manager` / `admin`; third-party claims allow task-level actions only (no customer or partner contact); and a never-autonomous list (initiate payment, approve settlement, repudiate claim, change claim state, override the customer's garage choice). The customer's chosen garage is never offered for reassignment; the agent escalates instead.

Every decision passes through one function, `authorise_action`. Runs are idempotent: re-running reuses open tasks rather than creating duplicates. Executed or gated actions are audited as `SLA_AGENT_ACTIONS_EXECUTED`, attributed to `agent:sla_intelligence/on-behalf-of:<user>`.

## 7. Limitations

- The breach model is a heuristic baseline with no calibration against production outcomes yet.
- Some event timestamps are inferred from claim status; pause derivation is approximate where the system does not record the exact customer-wait window.
- Clocks are computed on request over the tenant's claims; very large tenants will want a materialised snapshot.
- The legacy `SLATimer` sweep (`services/workflow/sla_engine.py`) and `GET /api/v1/operations/sla` are unchanged and remain the reactive alerting path.
