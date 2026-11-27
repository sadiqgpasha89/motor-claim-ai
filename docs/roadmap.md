# Roadmap status

Status of the five roadmap phases. "Built" means working code and tests in this repository. Where a dependency is simulated or a sandbox, the item says so. All data is DEMO and SYNTHETIC.

## Phase 1: make the claims journey real

| Item | Where |
|---|---|
| Claim 360 | `services/claims/claim360.py`, web `/claims/{id}/claim-360` |
| End-to-end workflow visualization | `ClaimExecutionChain` and `MotorClaimTracker` components |
| Agent execution timeline | Claim 360 and the trace store (`AgentExecutionRecord`) |
| Live state transitions | Claim 360 live refresh and workflow state history |
| Orchestration and dependencies | `services/workflow/orchestrator.py` |
| Human approval queue | `/human-review` and the approval routes |
| Real action logs | Audit hash chain and trace tool calls |
| One working OD claim demo | `scripts/od_claim_demo.py` and demo 1 |

## Phase 2: intelligence upgrades

Multimodal damage fusion, component confidence, repair or replace, benchmarking, fraud graph, complexity prediction, SLA risk and supplementary estimates. See [claim-intelligence.md](claim-intelligence.md). The vision model is simulated.

## Phase 3: enterprise integrations

Adapters, tool gateway, sandbox payment gateway and messaging, event bus, recovery and resilience. See [event-driven-architecture.md](event-driven-architecture.md) and [security-controls.md](security-controls.md). Every adapter is a sandbox implementation. No real vendor is connected.

## Phase 4: AI quality and responsible AI

Evaluation framework, synthetic datasets, regression gate, prompt injection, tool misuse, hallucination, citation accuracy, fairness, human override tracking, and cost and latency reports. See [responsible-ai.md](responsible-ai.md) and [ai-evaluation.md](ai-evaluation.md). No live model is evaluated.

## Phase 5: product experience

| Item | Where |
|---|---|
| Executive dashboard | `/executive-dashboard` |
| Claim 360 | `/claims/{id}/claim-360` |
| Agent Command Center | `/agent-command-center` |
| Customer claim tracking | `/portal` |
| Claims officer workspace | `/` (workbench) and Claim 360 |
| SIU workspace | `/siu` |
| Garage and surveyor portal | `/partners` (role-scoped) |
| Performance dashboard | `/performance` |
| Interactive guided demos | `/demos` and site section 2K |
| Architecture and engineering docs | `docs/` and [product-portal.md](product-portal.md) |

## Known limits

The tracked gaps are listed in `evals/known_gaps.json` and shown on every gate run. The portal has not been tested with real claims officers.
