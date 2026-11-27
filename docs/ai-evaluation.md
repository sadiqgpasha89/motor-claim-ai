# AI Evaluation Framework & Release Gate

A production insurance AI must show that its agents work **reliably, safely and measurably**. The `evals/` package does that with golden datasets, per-agent metrics, safety suites and a release gate that runs in CI.

```bash
python -m evals.gate                    # verdict; exit code 1 blocks the release
python -m evals.gate --json report.json # machine-readable report
python -m evals.gate --markdown         # job-summary markdown
python -m evals.gate --update-baseline  # accept current metrics as the drift baseline (review the diff)
python -m evals.gate --site-snapshot    # regenerate site/eval-report.js for the public dashboard
pytest tests/evals -q                   # framework tests, including "gate has teeth" mutation tests
```

## 1. Datasets (`evals/datasets/*.json`)

264 curated cases, one file per agent, each tagged with one of 17 scenario categories: clean claims, incomplete claims, incorrect policy data, conflicting documents, low-quality photographs, duplicate evidence, fraud signals, prompt injection, high-value, injury, third-party, EV, expired policies, policy exclusions, network/API outages, settlement boundary conditions, and payment timeout/retry. The gate requires at least five cases per category.

Cases carry `critical` (a failure always blocks), `statistical` (contributes to metrics only) and `known_gap` (a tracked, registered defect). Seeded generators in `evals/synthetic.py` add OCR-noise documents and the injection and PII corpora. Money and payment scenarios use an isolated in-memory database with the production schema.

## 2. Metrics per agent

| Agent | Metrics |
|---|---|
| FNOL | completeness, field extraction accuracy, intake success, action accuracy |
| Document AI | field accuracy, OCR char accuracy and robustness, validation precision/recall, conflict F1, injection recall and false positives |
| Coverage | interpretation accuracy, citation validity (grounded in the policy corpus), citation recall, escalation recall |
| Triage | tier and routing accuracy, survey trigger, missed and over-escalation rate |
| Damage AI | classification precision/recall/F1, image quality, recapture recall, confidence ECE and Brier |
| Estimate validation | anomaly precision/recall, false-positive rate, total accuracy |
| Fraud | signal precision/recall, false-positive rate, never-reject compliance |
| Coordination | assignment success, guardrail compliance, routing, provider SLA |
| Settlement | calculation correctness, oracle agreement, rule adherence, payment safety |
| Communication | factual accuracy, approved-template compliance, consent, adverse-notice gating, localisation |
| QA | defect detection recall, closure checklist accuracy, rework routing, false-closure rate |
| Predictive SLA | action authorisation accuracy, guardrail compliance, prediction monotonicity, unsafe autonomy count |

Settlement numbers are checked against hand-verified golden values and an independent exact-arithmetic (`Fraction`) oracle in `evals/oracles/`.

## 3. Release gate

| Check | What must hold |
|---|---|
| Regression tests | All scored cases pass; every metric meets its floor in `thresholds.json`; no metric drifts more than 0.02 from `baseline.json`; category coverage intact; every gap id registered |
| Agent tool permissions | Contracts consistent; runtime allowlists equal contracts; every recorded agent execution stays inside its tools, actions and rework targets; denial mechanisms proven by positive controls |
| Coverage grounding | 192 coverage scenarios; every citation resolves to a real clause on the right page with a quoted excerpt; fabricated citations are rejected |
| Financial calculations | 300 seeded random settlements equal the oracle; invariants hold; rule-file thresholds match code at the boundary (INR 25,000 / 50,000 / 75,000, 75% CTL, 12% variance) |
| Prompt injection tests | Sanitizer flags all direct injections with zero false positives; no agent takes an adverse action, gains privileges, inflates confidence or echoes hostile text under attack |
| PII leakage tests | Masker and agent outputs scanned for phone, email, PAN, Aadhaar and bank accounts planted in inputs; internal SIU notes never reach customers |
| Human escalation tests | Model outage and timeout degrade every agent to a human route with no side effects; 15 must-escalate conditions; every escalation is explained |

`evals.gate.judge()` is a pure function, so `tests/evals` proves the gate blocks a regressed metric, baseline drift, a failing critical case, a missing baseline, an unregistered gap, any failing or missing suite and a threshold breach.

## 4. Known gaps found by the framework

The framework found real defects. They are registered in `evals/known_gaps.json`, reported on every run and shown on the site; they do not block a release, and the gate warns when one is fixed so its entry can be retired. Anything new or worse blocks.

| Id | Severity | Agent | Finding |
|---|---|---|---|
| GAP-COMM-001 | critical | customer_communication | Caller-supplied draft bypasses the approved templates |
| GAP-QA-001 | critical | qa_compliance | QA approves closure on an empty or mostly-missing checklist |
| GAP-SET-001 | critical | settlement_recommendation | Second payment possible with a fresh idempotency key |
| GAP-COMM-002 | high | customer_communication | SMS opt-out silently falls back to email |
| GAP-COMM-003 | high | customer_communication | Injection text inside list-valued facts is echoed into messages |
| GAP-COORD-001 | high | provider_coordination | EV claim can be assigned to a non-EV-certified garage |
| GAP-COV-001 | high | coverage_intelligence | Exclusion narratives (DUI, invalid licence, wear and tear) are not escalated |
| GAP-DMG-001 | high | damage_assessment | Zero photos proceeds straight to estimate validation |
| GAP-EST-001 | high | estimate_validation | Part code not on the rate card is silently accepted |
| GAP-EST-002 | high | estimate_validation | Negative or zero quantities and prices are accepted |
| GAP-INJ-001 | high | document_intelligence | Sanitizer is regex-only and misses paraphrased, multilingual, obfuscated and markup injections |
| GAP-PII-001 | high | customer_communication | PII masking covers top-level strings only |
| GAP-PII-002 | high | fnol_concierge | Bank account numbers and UPI handles are never masked |
| GAP-QA-002 | high | qa_compliance | QA treats the string 'false' as a passed control |
| GAP-TOOL-001 | high | fnol_concierge | Request-level allowed_tools is not enforced on the action path |
| GAP-COV-002 | medium | coverage_intelligence | EV claim without the EV endorsement is not treated as ambiguous |
| GAP-COV-003 | medium | coverage_intelligence | Retrieval no longer cites the depreciation clause SEC-1-2 after the settlement clauses were added |
| GAP-DMG-002 | medium | damage_assessment | Damage classifier over-predicts damaged components |
| GAP-DMG-003 | medium | damage_assessment | Damage confidence is poorly calibrated |
| GAP-DOC-001 | medium | document_intelligence | OCR accuracy degrades under character-noise |
| GAP-EST-003 | medium | estimate_validation | Parts outside the visible damage are not routed to the surveyor |
| GAP-PII-003 | medium | fnol_concierge | Masker misses separated phone numbers and lower-case PAN |

## 5. Honest scope

* Agents run on the deterministic stub model, so the injection and PII agent-level suites prove the contract a live model must keep, not that a live model resists attack. Re-run the same suites with a live gateway before enabling one.
* Datasets are synthetic and hand-curated; thresholds are floors near measured values for the weak damage and OCR metrics, and targets show where they should end up.
