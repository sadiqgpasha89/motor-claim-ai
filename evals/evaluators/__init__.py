"""Per-agent evaluators. Each module exposes ``evaluate() -> AgentEval``."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module

from evals.core import AgentEval
from evals.taxonomy import AGENT_ORDER

_MODULES: dict[str, str] = {
    "fnol_concierge": "fnol",
    "document_intelligence": "document",
    "coverage_intelligence": "coverage",
    "claim_triage": "triage",
    "damage_assessment": "damage",
    "estimate_validation": "estimate",
    "fraud_intelligence": "fraud",
    "provider_coordination": "coordination",
    "settlement_recommendation": "settlement",
    "customer_communication": "communication",
    "qa_compliance": "qa",
}


def get_evaluator(agent: str) -> Callable[[], AgentEval]:
    module = import_module(f"evals.evaluators.{_MODULES[agent]}")
    evaluate: Callable[[], AgentEval] = module.evaluate
    return evaluate


def evaluate_all() -> dict[str, AgentEval]:
    return {agent: get_evaluator(agent)() for agent in AGENT_ORDER}
