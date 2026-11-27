"""LLM gateway. The one path from the platform to a model.

It redacts PII before the call, rate limits per user, calls the model gateway (which has the outage circuit),
validates the output, and rehydrates tokens only for the internal caller. Token counts are estimates.
"""
from __future__ import annotations

from typing import Any

from packages.contracts.errors import DomainError, ErrorCode
from packages.security.pii import PiiVault, contains_pii, redact_value, rehydrate_text
from packages.security.ratelimit import enforce as enforce_rate_limit
from services.agent_runtime.gateway import ModelGateway, ModelOutageError
from services.observability.traces import estimate_cost_inr, estimate_tokens
from services.rules_engine.security import security_controls


def validate_model_output(text: str) -> list[str]:
    """Return the problems found in a model output. An empty list means the output is acceptable."""
    ctl = security_controls()["output_validation"]
    problems: list[str] = []
    if len(text) > int(ctl["max_output_chars"]):
        problems.append("Output is longer than the allowed size.")
    low = text.lower()
    for phrase in ctl["forbidden_decision_phrases"]:
        if phrase in low:
            problems.append(f"Output makes a decision that only a human or a rule may make: '{phrase}'.")
    if contains_pii(text):
        problems.append("Output contains raw personal data.")
    return problems


class LLMGateway:
    @staticmethod
    def complete(*, task: str, facts: dict[str, Any], user_id: str, model_call: Any = None) -> dict[str, Any]:
        enforce_rate_limit("llm", user_id, int(security_controls()["rate_limits_per_minute"]["llm_call_per_user"]))
        vault = PiiVault()
        safe_facts = redact_value(facts, vault)
        call = model_call or ModelGateway.generate_structured_summary
        try:
            raw = call(task=task, facts=safe_facts)
        except ModelOutageError as exc:
            raise DomainError(ErrorCode.AI_UNAVAILABLE, str(exc), status_code=503) from exc
        problems = validate_model_output(raw)
        if problems:
            raise DomainError(
                ErrorCode.HUMAN_REVIEW_REQUIRED, "Model output failed validation. A human must review.", status_code=422,
                details={"problems": problems},
            )
        tokens_in = estimate_tokens(str(safe_facts))
        tokens_out = estimate_tokens(raw)
        model_name, model_version = ModelGateway.get_model_metadata()
        return {
            "text": raw,
            "text_for_internal_use": rehydrate_text(raw, vault),
            "pii_tokens_redacted": len(vault),
            "model": model_name,
            "model_version": model_version,
            "usage": {"tokens_input": tokens_in, "tokens_output": tokens_out, "source": "estimated", "cost_inr": str(estimate_cost_inr(model_name, tokens_in, tokens_out))},
        }
