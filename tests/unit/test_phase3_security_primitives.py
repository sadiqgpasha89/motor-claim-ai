from __future__ import annotations

import pytest

from packages.config import Settings
from packages.contracts.errors import DomainError
from packages.security.mfa import totp, verify_totp
from packages.security.pii import PiiVault, contains_pii, redact_text, redact_value, rehydrate_text
from packages.security.ratelimit import SlidingWindowLimiter
from packages.security.secrets import assert_production_secrets
from services.agent_runtime.llm_gateway import LLMGateway, validate_model_output
from services.integrations.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    PermanentIntegrationError,
    RetryPolicy,
    TransientIntegrationError,
    call_with_resilience,
)


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_retry_succeeds_after_transient_failures_and_uses_backoff():
    calls, sleeps = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise TransientIntegrationError("503")
        return "ok"

    result, attempts = call_with_resilience(flaky, breaker=CircuitBreaker("t"), policy=RetryPolicy(max_attempts=3, base_delay_s=0.1), sleep=sleeps.append)
    assert (result, attempts) == ("ok", 3)
    assert sleeps == [0.1, 0.2]


def test_permanent_error_is_not_retried_and_does_not_trip_the_breaker():
    breaker = CircuitBreaker("p", failure_threshold=1)
    calls = []

    def reject():
        calls.append(1)
        raise PermanentIntegrationError("bad request")

    with pytest.raises(PermanentIntegrationError):
        call_with_resilience(reject, breaker=breaker, sleep=lambda _s: None)
    assert len(calls) == 1 and breaker.state == "closed"


def test_circuit_opens_then_half_opens_then_closes_on_success():
    clock = Clock()
    breaker = CircuitBreaker("c", failure_threshold=2, reset_seconds=30, clock=clock)

    def down():
        raise TransientIntegrationError("down")

    with pytest.raises(TransientIntegrationError):
        call_with_resilience(down, breaker=breaker, policy=RetryPolicy(max_attempts=2), sleep=lambda _s: None)
    assert breaker.state == "open"
    with pytest.raises(CircuitOpenError):
        call_with_resilience(lambda: "x", breaker=breaker)
    clock.t += 31
    assert breaker.state == "half_open"
    assert call_with_resilience(lambda: "x", breaker=breaker)[0] == "x"
    assert breaker.state == "closed"


def test_pii_round_trip_and_aadhaar_is_not_read_as_account():
    vault = PiiVault()
    text = "Mail rohan@example.com or call 9876543210. Aadhaar 1234 5678 9012. PAN ABCDE1234F. Acct 123456789012345."
    red = redact_text(text, vault)
    assert "rohan@example.com" not in red and "9876543210" not in red and "ABCDE1234F" not in red
    assert "[PII:AADHAAR:" in red and "[PII:ACCOUNT:" in red
    assert rehydrate_text(red, vault) == text
    assert not contains_pii(red)
    nested = redact_value({"a": ["call 9876543210"], "n": 5}, PiiVault())
    assert "9876543210" not in str(nested) and nested["n"] == 5


def test_same_value_gets_the_same_token():
    vault = PiiVault()
    assert redact_text("a@b.com and a@b.com", vault).count("[PII:EMAIL:1]") == 2


def test_sliding_window_limiter():
    clock = Clock()
    lim = SlidingWindowLimiter(limit=2, window_seconds=60, clock=clock)
    assert lim.allow("u") and lim.allow("u") and not lim.allow("u")
    assert lim.allow("other")
    clock.t += 61
    assert lim.allow("u")


def test_totp_matches_rfc6238_vector_and_window():
    secret = b"12345678901234567890"
    assert totp(secret, at=59, digits=8) == "94287082"
    code = totp(secret, at=1000)
    assert verify_totp(secret, code, at=1000) and verify_totp(secret, code, at=1030)
    assert not verify_totp(secret, code, at=1000 + 300)


def test_production_refuses_the_demo_signing_key():
    with pytest.raises(RuntimeError):
        assert_production_secrets(Settings(app_env="production", jwt_secret_key="demo-synthetic-dev-secret"))
    assert_production_secrets(Settings(app_env="production", jwt_secret_key="a-real-secret-value-0123456789abcd"))
    assert_production_secrets(Settings(app_env="local"))


def test_output_validation_blocks_decisions_and_raw_pii():
    assert validate_model_output("Summary of the claim facts.") == []
    assert validate_model_output("I will approve the claim now.")
    assert validate_model_output("Call 9876543210")
    assert validate_model_output("x" * 5000)


def test_llm_gateway_sends_redacted_facts_and_rehydrates_only_internally():
    seen = {}

    def fake_model(*, task, facts):
        seen.update(facts)
        return f"Contact {facts['contact']} about the bumper."

    res = LLMGateway.complete(task="t", facts={"contact": "rohan@example.com"}, user_id="u-llm-1", model_call=fake_model)
    assert "rohan@example.com" not in str(seen)
    assert res["pii_tokens_redacted"] == 1 and "rohan@example.com" not in res["text"]
    assert "rohan@example.com" in res["text_for_internal_use"]
    assert res["usage"]["source"] == "estimated"


def test_llm_gateway_blocks_a_decision_in_the_output():
    with pytest.raises(DomainError) as exc:
        LLMGateway.complete(task="t", facts={}, user_id="u-llm-2", model_call=lambda **_: "We reject the claim.")
    assert exc.value.status_code == 422
