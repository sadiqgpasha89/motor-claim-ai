# Responsible AI: evaluation, safety suites, override tracking, cost and latency

All data is DEMO and SYNTHETIC. Thresholds are illustrative. Token counts and costs are estimates.

## What the release gate checks now

The AI release gate (`python -m evals.gate`) already ran regression, tool permission, coverage grounding, financial, prompt injection, PII and human escalation checks. Phase 4 adds three more required checks. See [ai-evaluation.md](ai-evaluation.md) for the base framework.

| Check | File | What it proves |
|---|---|---|
| Tool misuse | `evals/safety/tool_misuse.py` | The tool gateway denies unknown tools, wrong roles, wrong agents, cross-tenant calls, closed claim states and every payment attempt. Missing parameters and idempotency keys are rejected. A reused key with a changed request is refused. A replay does not run the tool twice. Hostile text in parameters creates no payment. Each policy denial has one audit event. The audit chain stays valid. A call flood hits the rate limit. |
| Hallucination and citation accuracy | `evals/safety/hallucination.py` | Customer messages state only amounts and reference numbers that were in their input. Coverage citations point to real clauses (sampled, 100% required). The LLM gateway blocks model output that decides a claim, says money moved, holds raw PII or is too long. The model never receives raw PII. Negative controls prove the checkers can fail. |
| Bias and fairness | `evals/safety/fairness.py` | Counterfactual tests change location, name, gender, age and religion. Triage, fraud and coverage outcomes must stay the same. A control shows that a real risk driver (loss amount) does change the outcome. |

The fairness values and tolerance live in `rules/common/responsible_ai.json` (rule `IN-RESPONSIBLE-AI-2026`). Agents receive minimised facts and do not use protected attributes. The test proves that they have no influence, so it guards against a future change that adds one.

A failure in any suite blocks the release. Tests in `tests/evals` already sabotage each suite and prove that the gate blocks.

## Synthetic datasets and regression

The seeded generators in `evals/synthetic.py` (OCR noise, injection payloads) and the counterfactual sets above are deterministic. The baseline (`evals/baseline.json`) and the drift limit (2 points) continue to guard the metric regression.

## Human-override tracking

`GET /api/v1/operations/human-overrides` (manager, auditor, admin).

- An override is a decided approval that is not `approved`.
- The report groups by action type, adds the human-intervention markers from agent traces, and raises an alert when the rate is above `override_rate_alert_pct` and there are enough decisions (`min_decisions_for_alert`).
- A high rate means the agent needs review. A very low rate with many decisions can mean rubber-stamping. The report shows the numbers. It does not judge.

## Cost and latency

`GET /api/v1/operations/cost-latency` (manager, auditor, admin).

- Per agent: executions, average and p95 duration, tokens, cost, cost share and retry rate.
- Budgets come from the rule file: latency per agent, cost per claim, cost share and retry rate.
- Hints are advisory and never change agent behaviour. They cover slow agents, a large cost share, frequent retries and the estimated saving if the same tokens ran on the cheapest rate-card model.

## What is not built

- No live model is evaluated. The model gateway is a deterministic stub, so hallucination checks measure grounding rules and output validation, not a real model.
- Fairness covers the listed attributes only. It is not a statistical audit of real outcomes.
- Override rates need real reviewer volume to mean anything.
