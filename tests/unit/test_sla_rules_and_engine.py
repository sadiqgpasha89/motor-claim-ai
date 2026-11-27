from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.rules_engine.loader import load_rule_files
from services.sla.engine import build_claim_instances, build_instance
from services.sla.events import ClaimSLAContext
from services.sla.rules import (
    SLA_CATALOGUE_ID,
    SLA_METRICS,
    SLARulesService,
    evaluate_condition,
    parse_version,
    validate_catalogue,
)

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def rules() -> SLARulesService:
    return SLARulesService(load_rule_files()[SLA_CATALOGUE_ID])


def _claim(**kw):
    base = dict(
        id="c1", claim_number="CLM-T-1", claim_type="own_damage", queue_name="q", status="SURVEY_ASSIGNED", risk_tier="MEDIUM",
        operational_path="standard", missing_documents=[], ev_battery_impacted=False, triage_summary=None,
        created_at=NOW - timedelta(hours=100), updated_at=NOW - timedelta(hours=1),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _ctx(claim=None, **kw) -> ClaimSLAContext:
    return ClaimSLAContext(claim=claim or _claim(), now=NOW, **kw)  # type: ignore[arg-type]


def _assignment(hours_ago: float, report_after: float | None = None):
    assigned = NOW - timedelta(hours=hours_ago)
    return SimpleNamespace(
        assigned_at=assigned, surveyor_id="s1", report_received_at=assigned + timedelta(hours=report_after) if report_after is not None else None,
    )


# ---------------------------------------------------------------------------------------------------------------------
# Catalogue integrity: nothing hardcoded, everything validated
# ---------------------------------------------------------------------------------------------------------------------
def test_shipped_catalogue_is_valid_and_covers_all_eight_metrics(rules):
    assert validate_catalogue(rules.catalogue) == []
    assert {r.metric for r in rules.rules} == set(SLA_METRICS)
    assert len(SLA_METRICS) == 8


def test_every_rule_defines_the_full_contract(rules):
    for r in rules.rules:
        assert r.rule_version and r.applicable_claim_types and r.trigger_event and r.stop_event
        assert r.deadline_hours > 0 and r.responsible_team and r.breach_action and r.escalation_sequence
        assert r.start_condition is not None and isinstance(r.pause_conditions, tuple)


def test_regulatory_values_come_from_the_catalogue_not_code(rules):
    survey = rules.resolve("survey_completion", "own_damage", NOW)
    assert survey.regulatory_hours == 360 and survey.deadline_hours == 168
    assert "15 days" in survey.regulatory_reference
    # Configurable metrics carry no invented regulatory deadline.
    assert rules.resolve("payment_processing", "own_damage", NOW).regulatory_hours is None
    assert rules.resolve("claim_closure", "own_damage", NOW).regulatory_hours is None


# ---------------------------------------------------------------------------------------------------------------------
# Rule versions, effective dating and claim-type families
# ---------------------------------------------------------------------------------------------------------------------
def test_rule_version_is_resolved_at_the_time_the_clock_starts(rules):
    old = rules.resolve("document_verification", "own_damage", datetime(2026, 3, 1, tzinfo=timezone.utc))
    new = rules.resolve("document_verification", "own_damage", datetime(2026, 8, 1, tzinfo=timezone.utc))
    assert (old.rule_version, old.deadline_hours) == ("1.0.0", 36)
    assert (new.rule_version, new.deadline_hours) == ("1.1.0", 24)


def test_claim_type_families_route_cashless_and_reimbursement_to_own_damage_and_tp_to_its_own_rule(rules):
    for stored in ("own_damage", "cashless", "reimbursement"):
        assert rules.resolve("estimate_approval", stored, NOW).sla_id == "SLA-ESTIMATE-APPROVAL"
    tp = rules.resolve("document_verification", "third_party", NOW)
    assert tp.sla_id == "SLA-DOCUMENT-VERIFICATION-TP" and tp.deadline_hours == 72
    assert rules.resolve("estimate_approval", "third_party", NOW) is None  # TP has its own lifecycle


def test_parse_version_orders_semver_numerically():
    assert parse_version("1.10.0") > parse_version("1.9.0")
    assert parse_version("2.0.0") > parse_version("1.99.99")


def test_condition_dsl():
    facts = {"survey_required": True, "evidence_count": 0, "missing_document_count": 2, "claim_status": "TRIAGE"}
    assert evaluate_condition({"all": []}, facts)
    assert evaluate_condition({"all": [{"fact": "survey_required", "op": "==", "value": True}]}, facts)
    assert evaluate_condition({"any": [{"fact": "evidence_count", "op": ">", "value": 0}, {"fact": "missing_document_count", "op": ">", "value": 0}]}, facts)
    assert not evaluate_condition({"all": [{"fact": "evidence_count", "op": ">", "value": 0}]}, facts)
    assert evaluate_condition({"fact": "claim_status", "op": "in", "value": ["TRIAGE", "TRIAGED"]}, facts)
    assert not evaluate_condition({"fact": "missing_fact", "op": ">=", "value": 1}, facts)
    with pytest.raises(ValueError):
        evaluate_condition({"fact": "claim_status", "op": "regex", "value": "x"}, facts)


# ---------------------------------------------------------------------------------------------------------------------
# Validation catches bad configuration before it governs a claim
# ---------------------------------------------------------------------------------------------------------------------
def _mutated(rules: SLARulesService, mutate) -> list[str]:
    cat = copy.deepcopy(rules.catalogue)
    mutate(cat)
    return validate_catalogue(cat)


def test_validation_rejects_unknown_action_event_and_fact(rules):
    errs = _mutated(rules, lambda c: c["rules"][0]["escalation_sequence"].append({"step": 9, "at_pct": 150, "action": "delete_claim", "to_team": "x"}))
    assert any("delete_claim" in e for e in errs)
    errs = _mutated(rules, lambda c: c["rules"][0].update(stop_event="ClaimTeleported"))
    assert any("ClaimTeleported" in e for e in errs)
    errs = _mutated(rules, lambda c: c["rules"][0].update(start_condition={"all": [{"fact": "vibes", "op": "==", "value": 1}]}))
    assert any("vibes" in e for e in errs)


def test_validation_rejects_bad_ordering_missing_metric_and_duplicate_versions(rules):
    errs = _mutated(rules, lambda c: c["rules"][0].update(escalation_sequence=[
        {"step": 1, "at_pct": 90, "action": "remind_owner", "to_team": "a"}, {"step": 2, "at_pct": 40, "action": "escalate_manager", "to_team": "b"}]))
    assert any("ascending" in e for e in errs)
    errs = _mutated(rules, lambda c: c.update(rules=[r for r in c["rules"] if r["metric"] != "claim_closure"]))
    assert any("claim_closure" in e and "no rule" in e for e in errs)
    errs = _mutated(rules, lambda c: c["rules"].append({**copy.deepcopy(c["rules"][0]), "sla_id": "SLA-DUPLICATE"}))
    assert any("duplicate rule_version" in e for e in errs)


# ---------------------------------------------------------------------------------------------------------------------
# Clock engine: elapsed, pauses, deadlines, breach, escalation step
# ---------------------------------------------------------------------------------------------------------------------
def test_running_clock_reports_consumption_and_due_escalation_step(rules):
    ctx = _ctx(assignments=[_assignment(126)])  # 126h of a 168h survey SLA = 75%
    inst = next(i for i in build_claim_instances(ctx, rules) if i.metric == "survey_completion")
    assert inst.status == "running" and inst.rule_version == "1.0.0"
    assert inst.consumed_pct == pytest.approx(75.0, abs=0.1)
    assert inst.escalation_due["action"] == "escalate_team_lead"  # step at 75%
    assert inst.regulatory_hours == 360 and inst.regulatory_due_at is not None


def test_breached_open_clock_and_accrued_penalty_only_after_regulatory_window(rules):
    ctx = _ctx(assignments=[_assignment(200)])  # past 168h internal, inside 360h regulatory
    inst = next(i for i in build_claim_instances(ctx, rules) if i.metric == "survey_completion")
    assert inst.status == "breached" and inst.penalty_accrued_inr == "0.00"
    ctx = _ctx(assignments=[_assignment(400)])  # 40h past the regulatory 15 days -> 2 started days x 500
    inst = next(i for i in build_claim_instances(ctx, rules) if i.metric == "survey_completion")
    assert inst.penalty_accrued_inr == "1000.00"


def test_completed_clock_is_met_or_met_late(rules):
    ok = next(i for i in build_claim_instances(_ctx(assignments=[_assignment(100, report_after=60)]), rules) if i.metric == "survey_completion")
    late = next(i for i in build_claim_instances(_ctx(assignments=[_assignment(300, report_after=200)]), rules) if i.metric == "survey_completion")
    assert ok.status == "met" and ok.stopped_at is not None
    assert late.status == "met_late"


def test_pause_stops_the_clock_and_extends_the_deadline(rules):
    claim = _claim(missing_documents=["RC"], status="EVIDENCE_PENDING", created_at=NOW - timedelta(hours=60))
    evidence = [SimpleNamespace(doc_status="extracted_unverified", doc_type="damage_photo", created_at=NOW - timedelta(hours=58))]
    open_request = SimpleNamespace(task_type="document_request", status="open", created_at=NOW - timedelta(hours=40), completed_at=None)
    inst = next(i for i in build_claim_instances(_ctx(claim, evidence=evidence, tasks=[open_request]), rules) if i.metric == "document_verification")
    assert inst.status == "paused" and inst.pause_codes_active == ["AWAITING_CUSTOMER_DOCUMENTS"]
    assert inst.paused_hours == pytest.approx(40.0, abs=0.01)
    assert inst.active_elapsed_hours == pytest.approx(20.0, abs=0.01)  # 60h wall clock - 40h paused
    due = datetime.fromisoformat(inst.due_at)
    assert due == datetime.fromisoformat(inst.started_at) + timedelta(hours=24 + 40)


def test_completed_pause_windows_are_removed_and_overlaps_not_double_counted(rules):
    claim = _claim(missing_documents=["RC"], created_at=NOW - timedelta(hours=60))
    evidence = [SimpleNamespace(doc_status="extracted_unverified", doc_type="x", created_at=NOW - timedelta(hours=58))]
    done = SimpleNamespace(task_type="document_request", status="completed", created_at=NOW - timedelta(hours=50), completed_at=NOW - timedelta(hours=30))
    overlapping = SimpleNamespace(task_type="document_request", status="completed", created_at=NOW - timedelta(hours=40), completed_at=NOW - timedelta(hours=20))
    inst = next(i for i in build_claim_instances(_ctx(claim, evidence=evidence, tasks=[done, overlapping]), rules) if i.metric == "document_verification")
    assert inst.paused_hours == pytest.approx(30.0, abs=0.01)  # union of [50..30] and [40..20] = 30h, not 40h
    assert inst.status in {"running", "breached"}  # no open pause -> clock is running again


def test_start_condition_gates_applicability(rules):
    fast_track = _ctx(_claim(status="FAST_TRACK", operational_path="fast_track", triage_summary={"x": 1}))
    assert not any(i.metric == "surveyor_assignment" for i in build_claim_instances(fast_track, rules))
    survey_path = _ctx(_claim(status="SURVEY_REQUIRED", triage_summary={"x": 1}, created_at=NOW - timedelta(hours=9)))
    inst = next(i for i in build_claim_instances(survey_path, rules) if i.metric == "surveyor_assignment")
    assert inst.status == "breached"  # 9h > 6h and no surveyor yet


def test_clock_uses_the_rule_version_in_force_when_it_started(rules):
    old_start = _claim(status="EVIDENCE_PENDING", missing_documents=["RC"], created_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
    inst = next(i for i in build_claim_instances(_ctx(old_start), rules) if i.metric == "document_verification")
    assert inst.rule_version == "1.0.0" and inst.deadline_hours == 36


def test_build_instance_event_provenance_is_reported(rules):
    ctx = _ctx(assignments=[_assignment(10)])
    rule = rules.resolve("survey_completion", "own_damage", NOW)
    inst = build_instance(rule, ctx, NOW - timedelta(hours=10), "table")
    assert inst.event_sources == {"start": "table", "stop": "pending"}
