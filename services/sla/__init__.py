"""Predictive SLA management: rules service, SLA clock engine, risk predictor and authorised-action planner.

SLA values live in the versioned rule catalogue ``COMMON-SLA-RULES-V2`` (rules/common/sla_rules.json),
never in prompts or UI code. Every layer here reads that catalogue.
"""
