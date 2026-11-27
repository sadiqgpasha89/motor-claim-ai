# Model Governance & AI Risk Controls

- **Model Gateway (`services/agent_runtime/gateway.py`):** Supports `stub`, `gemini`, and `anthropic` adapters with explicit `model_id`, `model_version`, and `prompt_version` logged on every invocation.
- **Abstention & Human Routing:** When confidence is low, documents mismatch, prompt injection is detected, or `AI_SIMULATE_OUTAGE=true`, agents return `AgentStatus.NEEDS_HUMAN` and route to human queues without blocking deterministic intake or manual workflows.
- **Zero Unverified Decisions:** LLMs never compute money, mutate policy wording, reject claims, or execute payouts.
- **Evaluation Suite (`tests/model_eval/`):** Validates schema conformance across all 12 agents and outage fallback behavior.
- **Predictive SLA model (`sla-risk-baseline-v1`):** An explainable heuristic whose weights live in `rules/common/sla_rules.json` (`risk_model`), not in code. Every probability carries its drivers. It has not been calibrated against production breach outcomes; treat probabilities as ranking signals until it has. The SLA agent can only create tasks, reminders and approval requests; reassignment, payment, settlement and state changes are outside its authority (`agent_guardrails.never_autonomous`).
