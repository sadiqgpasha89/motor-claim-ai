# Model Governance & AI Risk Controls

- **Model Gateway (`services/agent_runtime/gateway.py`):** Supports `stub`, `gemini`, and `anthropic` adapters with explicit `model_id`, `model_version`, and `prompt_version` logged on every invocation.
- **Abstention & Human Routing:** When confidence is low, documents mismatch, prompt injection is detected, or `AI_SIMULATE_OUTAGE=true`, agents return `AgentStatus.NEEDS_HUMAN` and route to human queues without blocking deterministic intake or manual workflows.
- **Zero Unverified Decisions:** LLMs never compute money, mutate policy wording, reject claims, or execute payouts.
- **Evaluation Suite (`tests/model_eval/`):** Validates schema conformance across all 11 agents and outage fallback behavior.
- **AI Release Gate (`evals/`):** Every AI, prompt, contract or rules change must pass `python -m evals.gate` (CI: `ai-release-gate.yml`) before it ships: regression, agent tool permissions, coverage grounding, financial calculations, prompt injection, PII leakage and human escalation. Thresholds live in `evals/thresholds.json`; accepted metrics in `evals/baseline.json`; defects found by the framework in `evals/known_gaps.json`. See [ai-evaluation.md](ai-evaluation.md).
