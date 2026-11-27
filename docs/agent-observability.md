# Agent Observability, Claim 360 and the OD Demo

This page covers feedback items 16 and 19, and Phase 1 of the roadmap. All data is DEMO / SYNTHETIC.

## Agent trace store

Every agent execution writes one `agent_execution_records` row. The row holds these fields:

| Field | Column | Note |
|---|---|---|
| Claim ID | `claim_id` | |
| Workflow ID | `workflow_run_id` | |
| Agent name and version | `agent_name`, `agent_version` | Version comes from `BoundedAgent.agent_version`. |
| Model name | `model_name`, `model_version` | |
| Prompt version | `prompt_version` | |
| Task input reference | `task_input_ref` | Holds a SHA-256 of the input. It never holds raw facts. |
| Tool calls and outputs | `tool_calls`, `tool_outputs` | Outputs are truncated to 600 characters. |
| Start and end time | `started_at`, `ended_at` | |
| Token usage | `tokens_input`, `tokens_output`, `usage_source` | `usage_source` is `estimated` with the stub model. |
| Latency | `duration_ms` | |
| Retry count | `retry_count` | |
| Outcome | `outcome` | `success`, `escalated_to_human`, `timeout`, `failed`, `blocked`, `rework_requested`, `insufficient_evidence`. |
| Confidence | `confidence` | Empty for blocked runs. |
| Error details | `error_details` | Message, reason codes and a `retryable` flag. |
| Human intervention | `human_intervention` | Opened when an agent needs a human. Closed by an approval decision or a workflow resume. |
| Final action | `final_action` | |

`services/observability/traces.py` builds these fields. `record_agent_publication` in the orchestrator writes them.
Cost uses an illustrative rate card in INR per 1,000 tokens. It is not a vendor invoice.

## Endpoints

| Endpoint | Roles | Purpose |
|---|---|---|
| `GET /api/v1/operations/agent-observability/dashboard` | claims manager, auditor, admin | KPIs, failed executions, stuck workflows, SLA breaches, approval backlog, fraud queue, payment reconciliation failures, outages, cost. |
| `GET /api/v1/operations/agent-observability/traces` | same | Trace explorer. Filters: `claim_id`, `agent_name`, `outcome`, `limit`. |
| `GET /api/v1/operations/approval-queue` | approver roles and auditor | Pending approvals, human tasks and agent escalations. `can_decide` is false for the maker. |
| `GET /api/v1/claims/{id}/claim-360` | internal roles | One view of the claim. |
| `GET /api/v1/claims/{id}/agent-timeline` | internal roles | Workflow DAG, merged timeline and trace rows. |

Every query is tenant scoped. Claim endpoints also apply claim-level ABAC. Fraud findings show only to SIU-allowed roles.

## Dashboard KPIs

The KPIs are measured from the trace store. They are not the illustrative figures in the brief.
A workflow run succeeds when the latest execution of each agent in that run is not `failed` or `timeout`.
Claim complexity is `claims.risk_tier`: LOW is simple, MEDIUM is standard, HIGH is complex.
A workflow is stuck when it is paused, has an open dead letter, or has no movement for 24 hours.

## Claim 360

The view answers eight questions: what happened, what is happening now, what is blocked, why it is blocked,
what the AI did, what the AI found, the next action, and whether the viewer must act.

## OD claim demo

```bash
python -m scripts.od_claim_demo                          # fresh in-process database
python -m scripts.od_claim_demo --base-url http://localhost:8000 --out od.json
python scripts/export_claim360_demo_data.py              # refresh site/claim360-data.js
```

The demo uses policy `POL-IN-DEMO-2026-OD01` and vehicle `MH04OD2026`. They have no claim history, so the claim stays LOW risk.
A second run on the same data sees a repeat claim. Pass `reset_demo_data=True` to reseed first.
The journey is FNOL, evidence, agent wave 1, estimate, agent wave 2 with automatic approval inside authority, payment, and closure.

## UI

- Next.js: `/claims/[id]/claim-360` and `/agent-command-center`.
- GitHub Pages: section 2H, built from `site/claim360-data.js`.
