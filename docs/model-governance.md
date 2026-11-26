# Model Governance & AI Risk Controls

- **Model Gateway (`services/agent_runtime/gateway.py`):** Supports `stub`, `gemini`, and `anthropic` adapters with explicit `model_id`, `model_version`, and `prompt_version` logged on every invocation.
- **Abstention & Human Routing:** When confidence is low, documents mismatch, prompt injection is detected, or `AI_SIMULATE_OUTAGE=true`, agents return `AgentStatus.NEEDS_HUMAN` and route to human queues without blocking deterministic intake or manual workflows.
- **Zero Unverified Decisions:** LLMs never compute money, mutate policy wording, reject claims, or execute payouts.
- **Evaluation Suite (`tests/model_eval/`):** Validates schema conformance across all 11 agents and outage fallback behavior.
