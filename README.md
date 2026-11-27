# MotorClaim AI Intelligence Solution

> **Enterprise Agentic AI Motor-Insurance Claims Platform (India-first)**  
> **Live Project Site (GitHub Pages):** https://sadiqgpasha89.github.io/motor-claim-ai/  
> **Data Mode:** `DEMO / SYNTHETIC` — All seeded customers, policies, vehicles, garages, surveyors, rate cards, and payments are synthetic test data.

An enterprise, human-accountable motor-insurance claims platform implementing the full vertical slice from FNOL intake to evidence vault, OCR extraction, policy-clause RAG coverage verification, IRDAI 2024 triage & SLA timers, assistive damage & rate-card estimate validation, explainable SIU fraud governance, deterministic `Decimal` settlement calculation, maker-checker approvals, idempotent payment reconciliation, and immutable audit trails.

## Architecture & Repository Layout

- `apps/api/` — FastAPI backend REST API (`/api/v1/...`), OpenAPI docs at `/docs`, correlation ID middleware, domain error handler.
- `apps/web/` — Next.js 14 + TypeScript + Tailwind enterprise Command Centre, Claim 360, Guided FNOL, Customer Portal, SIU Workbench, Surveyor/Garage Portal, Rules & Policy KB, and Operations/SLA console.
- `agents/` — 12 bounded, tool-permissioned specialised agents upgraded in-place, including the cross-cutting predictive `sla_intelligence` operations agent (`fnol_concierge`, `document_intelligence`, `coverage_intelligence`, `claim_triage`, `damage_assessment`, `estimate_validation`, `fraud_intelligence`, `provider_coordination`, `settlement_recommendation`, `customer_communication`, `qa_compliance`) with formal I/O contracts, prohibited state mutations, controlled actions, rework requests, and Decision Intelligence traces.
- `services/` — Modular domain services (`claims`, `workflow` including first-class DAG `ClaimOrchestrator`, 8-part `StateContractSpec` in `state_specs.py`, and explainable dynamic 3-tier `risk_engine.py`, `agent_runtime` including `ControlledActionExecutor` & contracts, `document_ai`, `damage_ai`, `fraud_intelligence`, `rules_engine`, `settlement`, `integrations`).
- `packages/` — Shared `contracts`, `security` (JWT, tenant/ABAC isolation, PII masking, prompt-injection & malware upload checks), `observability`, and `config`.
- `rules/` — Effective-dated, versioned JSON rule catalogues (`IN-IRDAI-MC-2024`, `IN-RISK-PROCESSING-2026`, `IN-MOTOR-DEPRECIATION-2024`, `IN-DOA-MATRIX-2026`, `COMMON-SLA-CATALOGUE-V1`, `IN-TP-LIABILITY-2026`, `IN-EV-CLAIMS-2026`).
- `knowledge/` — Synthetic Indian motor policy wordings (`POL-WORDING-PC-2024`, `POL-WORDING-EV-2025`) & OEM/OES parts rate card (`RC-IN-2026-DEMO-V1`).
- `migrations/` — Alembic database migrations (`alembic upgrade head` / `alembic downgrade -1`).
- `tests/` — Unit, E2E integration, security/IDOR/prompt-injection, and model-eval/outage-fallback suites.

## Documentation, Diagrams, Guide & Article

| Deliverable | Document | Description |
|---|---|---|
| **GitHub Pages Showcase** | [sadiqgpasha89.github.io/motor-claim-ai](https://sadiqgpasha89.github.io/motor-claim-ai/) | First-class Claim Orchestration Engine showcase: 15-state deterministic workflow, 3-tier Risk-Based Claim Processing (Fast-Track / Standard / Complex-SIU) & Dynamic Escalation Lab, 10-step Visual Damage Assessment AI & Per-Component Confidence Lab, Claims Ecosystem Coordination Dashboard & Authorization Guardrail Lab, Third-Party (TP) Liability Workflow & Controls Lab, Predictive SLA Operations (8-metric rule-driven dashboard, versioned SLA rules explorer, explainable breach-risk lab, agent authorisation matrix), Customer Experience Intelligence (5-stage Motor Claim Tracker, 10 proactive triggers, 5 languages, WhatsApp consent & 4h human escalation), Post-FNOL parallel/conditional DAG scheduler, DLQ/Saga/Pause-Resume Resilience Lab, 12-agent capability matrix, the 12-scenario Settlement Decision Workbench, and the EV Safety Lab (impact detection, thermal risk, specialist routing, OEM diagnostics, parts benchmark) |
| **TP Liability Workflow** | [docs/claims-lifecycle.md](docs/claims-lifecycle.md#6-third-party-tp-liability-lifecycle-in-tp-liability-2026-servicesworkflowtp_liabilitypy) | Third-Party claims run on their own 12-stage lifecycle with dedicated queues, legal/medical controls, reserve discipline, dual-control settlement and no autonomous settlement; OD paths refuse TP claims |
| **AI Evaluation & Release Gate** | [docs/ai-evaluation.md](docs/ai-evaluation.md) | 264 golden cases over 17 scenario categories, per-agent metrics for all 11 agents, an independent settlement oracle, six safety suites, a CI release gate and a registry of defects the framework found |
| **EV Claims Workflow** | [docs/claims-lifecycle.md](docs/claims-lifecycle.md#7-electric-vehicle-ev-claims-lifecycle-in-ev-claims-2026-servicesworkflowev_claimspy) | EV claims run on a dedicated 11-stage safety-first lifecycle: HV hold from FNOL, flatbed recovery, EV-HV certified physical survey, OEM diagnostics, battery repair-vs-replace decision, EV parts benchmarks, technical sign-off, recertification and salvage controls. An EV is **never cleared from photographs**; OD paths refuse EV claims until sign-off |
| **Agent Observability & Claim 360** | [docs/agent-observability.md](docs/agent-observability.md) | Agent trace store (model, prompt, tools, tokens, latency, retries, outcome, human intervention), ops dashboard, Claim 360 view, approval queue and the intake-to-closure OD claim demo |
| **Claim Intelligence** | [docs/claim-intelligence.md](docs/claim-intelligence.md) | Repair vs replace, benchmarking, multimodal fusion, supplementary estimates, predicted complexity and SLA risk, weighted fraud graph, double-payment guard |
| **Predictive SLA Operations** | [docs/sla-management.md](docs/sla-management.md) | Versioned SLA rules service, 8-metric dashboard, event-derived clocks with pauses, explainable breach prediction, and the bounded SLA agent (recommend vs authorised execute) |
| **System Design** | [docs/architecture.md](docs/architecture.md) | Layered system design, C4/deployment Mermaid diagrams, invariants, and ADRs |
| **Solution Engineering** | [docs/solution-engineering.md](docs/solution-engineering.md) | Two-plane architecture, `Decimal` math, settlement decision workbench (12 scenarios), RBAC/ABAC, prompt-injection defense, idempotency |
| **Class Diagrams** | [docs/class-diagrams.md](docs/class-diagrams.md) | Mermaid UML class diagrams for domain models, 12 agents, settlement, and security |
| **Pipelines** | [docs/pipelines.md](docs/pipelines.md) | End-to-end claim, Document AI, Hybrid RAG, Estimate validation, Payment, and CI/CD pipelines |
| **How It Works Guide** | [docs/how-it-works-guide.md](docs/how-it-works-guide.md) | Role-by-role guide, `CLM-DEMO-2026-0001` walkthrough, and all 11 edge-case scenarios |
| **Medium Article** | [docs/medium-article.md](docs/medium-article.md) | Publication-ready engineering article explaining the architecture and design lessons |
| **Lifecycle & Agents** | [docs/claims-lifecycle.md](docs/claims-lifecycle.md), [docs/agents.md](docs/agents.md) | State transitions, pathway controls, and agent tool allowlists |
| **API & Data** | [docs/api.md](docs/api.md), [docs/data-dictionary.md](docs/data-dictionary.md), [docs/integrations.md](docs/integrations.md) | REST endpoints, canonical entities, and mock/live adapter contracts |
| **Governance & Ops** | [docs/security-and-privacy.md](docs/security-and-privacy.md), [docs/model-governance.md](docs/model-governance.md), [docs/regulatory-matrix.md](docs/regulatory-matrix.md), [docs/operations-runbook.md](docs/operations-runbook.md), [docs/test-strategy.md](docs/test-strategy.md) | Security/DPDP controls, IRDAI matrix, runbooks, and test strategy |

## Quick Start (Local)

### 1. Backend API (FastAPI + SQLite / PostgreSQL)

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/uvicorn apps.api.main:app --reload --port 8000
```

The API automatically initializes the schema and seeds the `DEMO / SYNTHETIC` dataset (including `CLM-DEMO-2026-0001` and 12 edge-case scenarios covering LOW fast-track <= ₹25k auto-limit, MEDIUM standard, HIGH complex/EV/TP/SIU) on startup. Interactive OpenAPI docs are available at `http://localhost:8000/docs`.

### 2. Frontend Web Portal (Next.js)

```bash
cd apps/web
npm install
npm run dev
```

Open `http://localhost:3000`. Use the **Active Persona** switcher in the top header to test different roles (`policyholder@demo.in`, `fnol@demo.in`, `handler@demo.in`, `handler2@demo.in`, `surveyor@demo.in`, `garage@demo.in`, `garage.ev@demo.in`, `siu@demo.in`, `manager@demo.in`, `legal@demo.in`, `finance@demo.in`, `auditor@demo.in`, `admin@demo.in`).

### 3. Docker Compose (PostgreSQL + pgvector + Redis + API + Web)

```bash
docker compose up --build
```

## Running Tests & Quality Checks

```bash
# Backend unit, integration, security & model eval tests
.venv/bin/pytest -v

# Backend lint & type check
.venv/bin/ruff check apps services packages agents scripts tests evals
.venv/bin/mypy --explicit-package-bases apps packages services agents evals

# AI release gate: 264 golden cases, 6 safety suites, thresholds and drift baseline (exit 1 = release blocked)
.venv/bin/python -m evals.gate
.venv/bin/pytest tests/evals -q

# Frontend typecheck, lint & production build
cd apps/web && npm run typecheck && npm run lint && npm run build
```

## Known Limitations (Synthetic MVP Scope)

- External core policy/claims, IIISLA surveyor registry, OEM parts, WhatsApp/SMS, and NEFT/IMPS payment integrations operate through clearly labelled `MOCK` adapters (`INTEGRATION_MODE=mock`).
- AI/OCR/Vision models default to deterministic local adapters (`AI_PROVIDER_MODE=stub`) unless live provider credentials and private endpoints are configured.
- Production deployment requires legal/compliance sign-off on the effective-dated regulatory rules in `rules/india/` and enterprise OIDC/SAML SSO wiring.
