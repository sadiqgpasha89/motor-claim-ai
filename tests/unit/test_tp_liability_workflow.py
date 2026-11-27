"""Third-Party (TP) liability workflow (IN-TP-LIABILITY-2026): distinct lifecycle, human oversight, no autonomous settlement."""

from __future__ import annotations

import uuid

from agents.specialists import AGENT_REGISTRY
from packages.contracts.agents import AgentInvocationRequest, AgentStatus
from services.workflow.risk_engine import classify_claim_risk_from_facts
from services.workflow.tp_liability import STAGE_ORDER, TPStage
from tests.conftest import auth_headers

POLICY = "POL-IN-DEMO-2026-1001"
VEHICLE = "MH02DEMO1042"

BI_DOCS = ["claimant_id", "fir_copy", "medical_records", "discharge_summary", "medico_legal_certificate", "income_proof"]


def _tp_claim(client, *, category: str = "bodily_injury") -> str:
    ph = auth_headers(client, "policyholder@demo.in")
    peril = {"bodily_injury": "tp_bodily_injury", "fatality": "tp_fatality", "property_damage": "tp_property_damage"}[category]
    r = client.post(
        "/api/v1/claims/intimations",
        json={
            "policy_number": POLICY,
            "vehicle_reg": VEHICLE,
            "claim_type": "third_party",
            "peril_cause": peril,
            "incident_location": "Lonavala bypass",
            "incident_description": "Insured car hit a two-wheeler; third-party rider injured.",
            "injury_or_fatality": category != "property_damage",
            "police_involved": category != "property_damage",
        },
        headers={**ph, "Idempotency-Key": f"tp-{uuid.uuid4().hex}"},
    )
    assert r.status_code == 201, r.text
    return r.json()["claim"]["id"]


def _post(client, hdrs, path, body=None, expect=200):
    r = client.post(path, json=body or {}, headers=hdrs)
    assert r.status_code == expect, f"{path} -> {r.status_code} {r.text}"
    return r.json()


def _add_party(client, hdrs, base, body):
    return _post(client, hdrs, f"{base}/third-parties", body, 201)


def _advance(client, hdrs, cid, expect=200):
    return _post(client, hdrs, f"/api/v1/claims/{cid}/tp/advance", {}, expect)


def _to_legal_specialist_review(client, cid):
    handler = auth_headers(client, "handler@demo.in")
    legal = auth_headers(client, "legal@demo.in")
    manager = auth_headers(client, "manager@demo.in")
    base = f"/api/v1/claims/{cid}/tp"

    _add_party(client, handler, base, {"role": "injured", "name": "Ravi Kulkarni", "contact": "9812345678", "injury_severity": "grievous", "claimant_demand_inr": "1500000"})
    _advance(client, handler, cid)  # -> EVIDENCE_AND_FACTS
    _post(
        client, handler, f"{base}/facts",
        {"narrative": "Car struck rider at junction; rider fell and fractured femur.", "evidence": [{"kind": "photo", "description": "Scene photos"}]},
    )
    _advance(client, handler, cid)  # -> POLICE_FIR
    _post(client, handler, f"{base}/police-report", {"fir_number": "FIR-100/2026", "police_station": "Lonavala PS", "dar_status": "pending"})
    _advance(client, handler, cid)  # -> LIABILITY_INVESTIGATION
    _post(
        client, handler, f"{base}/liability-assessment",
        {"insured_fault_pct": 60, "third_party_fault_pct": 30, "contributory_negligence": True, "rationale": "Scene sketch and witness statements indicate insured entered the junction on amber; rider partly contributed."},
    )
    _advance(client, handler, cid)  # -> LEGAL_DOCUMENTATION
    for doc in BI_DOCS:
        _post(client, handler, f"{base}/legal-documents", {"doc_type": doc, "status": "received"}, 201)
    _advance(client, legal, cid)  # -> ADVOCATE_COORDINATION
    _post(client, legal, f"{base}/advocates", {"advocate_name": "Adv. S. Nair", "bar_enrolment_ref": "MAH/1234/2010", "conflict_check_cleared": True}, 201)
    _advance(client, legal, cid)  # -> MEDICAL_REVIEW
    _post(
        client, legal, f"{base}/medical-review",
        {"injury_severity": "grievous", "disability_percent": 25, "causation_consistent": True, "opinion": "Injury pattern consistent with a low-speed collision and fall.", "reviewer_name": "Dr. A. Shah"},
    )
    _advance(client, legal, cid)  # -> LEGAL_SPECIALIST_REVIEW
    _post(client, manager, f"{base}/reserve", {"amount_inr": "1200000", "basis": "Grievous injury band with 25% disability"})
    _post(client, legal, f"{base}/legal-review", {"decision": "negotiate_settlement", "notes": "Liability is arguable but the exposure favours an early negotiated settlement."})
    return _advance(client, legal, cid)  # -> SETTLEMENT_CONTROL


# --------------------------------------------------------------------------------------
# Distinct lifecycle and intake
# ----------------------------------------------------------------------------------------
def test_fnol_for_third_party_claim_opens_dedicated_tp_case_and_queue(client):
    cid = _tp_claim(client)
    handler = auth_headers(client, "handler@demo.in")
    tp = client.get(f"/api/v1/claims/{cid}/tp", headers=handler).json()
    assert tp["stage"] == "INTAKE"
    assert tp["queue"] == "tp_intake"
    assert tp["tp_category"] == "bodily_injury"
    assert tp["controls"]["autonomous_settlement_allowed"] is False
    assert tp["controls"]["shared_with_od_fast_track"] is False
    assert tp["tasks"][0]["queue"] == "tp_intake"
    assert tp["stage_path"] == [s for s in STAGE_ORDER]  # bodily injury uses every stage
    claim = client.get(f"/api/v1/claims/{cid}", headers=handler).json()
    assert claim["tp_workflow_required"] is True


def test_policyholder_cannot_read_tp_workflow(client):
    cid = _tp_claim(client)
    ph = auth_headers(client, "policyholder@demo.in")
    assert client.get(f"/api/v1/claims/{cid}/tp", headers=ph).status_code == 403


def test_property_damage_path_skips_medical_police_and_advocate_stages(client):
    cid = _tp_claim(client, category="property_damage")
    handler = auth_headers(client, "handler@demo.in")
    tp = client.get(f"/api/v1/claims/{cid}/tp", headers=handler).json()
    assert TPStage.MEDICAL_REVIEW.value not in tp["stage_path"]
    assert TPStage.ADVOCATE_COORDINATION.value not in tp["stage_path"]
    assert TPStage.POLICE_FIR.value not in tp["stage_path"]
    assert tp["required_documents"] == ["claimant_id", "property_damage_photos", "repair_estimate_or_invoice", "ownership_proof"]


def test_stage_gate_blocks_advance_until_intake_complete(client):
    cid = _tp_claim(client)
    handler = auth_headers(client, "handler@demo.in")
    r = client.post(f"/api/v1/claims/{cid}/tp/advance", json={}, headers=handler)
    assert r.status_code == 409
    body = r.json()
    assert body["error_code"] == "HUMAN_REVIEW_REQUIRED"
    assert any(b["code"] == "THIRD_PARTY_REQUIRED" for b in body["details"]["blockers"])


def test_restricted_medical_party_data_is_masked_for_finance(client):
    finance = auth_headers(client, "finance@demo.in")
    legal = auth_headers(client, "legal@demo.in")
    seeded = client.get("/api/v1/claims/clm-demo-0010/tp", headers=legal).json()
    assert seeded["stage"] == "LIABILITY_INVESTIGATION"
    assert any("Suresh Patil" in p["name"] for p in seeded["third_parties"])
    masked = client.get("/api/v1/claims/clm-demo-0010/tp", headers=finance).json()
    assert all("Suresh" not in p["name"] for p in masked["third_parties"])
    assert masked["controls"]["restricted_medical_visible"] is False


# --------------------------------------------------------------------------------------
# Full lifecycle with human gates and dual control
# ----------------------------------------------------------------------------------------
def test_full_tp_lifecycle_with_dual_control_and_separated_duties(client):
    cid = _tp_claim(client)
    handler = auth_headers(client, "handler@demo.in")
    legal = auth_headers(client, "legal@demo.in")
    manager = auth_headers(client, "manager@demo.in")
    finance = auth_headers(client, "finance@demo.in")
    base = f"/api/v1/claims/{cid}/tp"

    state = _to_legal_specialist_review(client, cid)
    assert state["stage"] == "SETTLEMENT_CONTROL"
    assert state["queue"] == "tp_settlement_control"
    assert [h["to"] for h in state["stage_history"]][-1] == "SETTLEMENT_CONTROL"

    # The legal reviewer cannot also propose the settlement.
    r = client.post(f"{base}/settlement-proposals", json={"basis": "negotiated", "amount_inr": "900000", "rationale": "Negotiated figure after tribunal benchmarks."}, headers=legal)
    assert r.status_code == 403

    # Proposal above the reserve is refused until the reserve is revised.
    r = client.post(f"{base}/settlement-proposals", json={"basis": "negotiated", "amount_inr": "1300000", "rationale": "Negotiated figure after tribunal benchmarks."}, headers=handler)
    assert r.status_code == 409

    proposal = _post(client, handler, f"{base}/settlement-proposals", {"basis": "negotiated", "amount_inr": "950000", "components": {"general_damages": "700000", "medical_expenses": "250000"}, "rationale": "Negotiated figure after tribunal benchmarks and medical costs."}, 201)["proposal"]
    assert proposal["approval_tier"] == "TP-L2"
    assert proposal["required_approver_roles"] == ["claims_manager", "legal_tp"]
    pid = proposal["proposal_id"]

    # Claims handler has no TP approval authority at all.
    assert client.post(f"{base}/settlement-proposals/{pid}/decision", json={"decision": "approved", "rationale": "Looks fine to me."}, headers=handler).status_code == 403

    # Dual control: manager alone does not complete the approval.
    first = _post(client, manager, f"{base}/settlement-proposals/{pid}/decision", {"decision": "approved", "rationale": "Within reserve and legal advice."})
    assert first["proposal"]["status"] == "pending_approval"
    assert first["tp_case"]["stage"] == "SETTLEMENT_CONTROL"
    # ... and the same manager cannot approve twice.
    assert client.post(f"{base}/settlement-proposals/{pid}/decision", json={"decision": "approved", "rationale": "Approving again."}, headers=manager).status_code == 403

    second = _post(client, legal, f"{base}/settlement-proposals/{pid}/decision", {"decision": "approved", "rationale": "Legal concurrence recorded."})
    assert second["proposal"]["status"] == "approved"
    assert second["tp_case"]["stage"] == "SETTLEMENT_APPROVED"
    assert second["tp_case"]["queue"] == "tp_payment_authorisation"

    # Payment: only finance, idempotent, no duplicate payout.
    pay_body = {"idempotency_key": "tp-pay-1", "payee_type": "claimant", "payee_name": "Ravi Kulkarni", "account_last4": "4321", "ifsc": "HDFC0001234"}
    assert client.post(f"{base}/payment-authorisation", json=pay_body, headers=manager).status_code == 403
    paid = _post(client, finance, f"{base}/payment-authorisation", pay_body, 201)
    assert paid["payment"]["status"] == "released"
    assert paid["payment"]["amount_inr"] == "950000.00"
    assert paid["tp_case"]["stage"] == "PAYMENT_AUTHORISED"
    replay = _post(client, finance, f"{base}/payment-authorisation", pay_body, 201)
    assert replay["payment"]["idempotent_replay"] is True
    dup = client.post(f"{base}/payment-authorisation", json={**pay_body, "idempotency_key": "tp-pay-2"}, headers=finance)
    assert dup.status_code == 409

    # Closure review by a manager only.
    assert client.post(f"{base}/close", json={"closure_notes": "All steps complete."}, headers=handler).status_code == 403
    closed = _post(client, manager, f"{base}/close", {"closure_notes": "Award paid, documents archived, no recovery action required."})
    assert closed["stage"] == "CLOSED"
    claim = client.get(f"/api/v1/claims/{cid}", headers=manager).json()
    assert claim["claim"]["status"] == "CLOSED"


def test_maker_checker_proposer_cannot_decide_own_settlement(client):
    cid = _tp_claim(client)
    manager = auth_headers(client, "manager@demo.in")
    base = f"/api/v1/claims/{cid}/tp"
    _to_legal_specialist_review(client, cid)
    # Manager proposes a small amount (tier TP-L1), then tries to approve it themself.
    pid = _post(client, manager, f"{base}/settlement-proposals", {"basis": "negotiated", "amount_inr": "400000", "rationale": "Small negotiated figure within the reserve."}, 201)["proposal"]["proposal_id"]
    r = client.post(f"{base}/settlement-proposals/{pid}/decision", json={"decision": "approved", "rationale": "Self approval."}, headers=manager)
    assert r.status_code == 403
    assert "Maker-checker" in r.json()["message"]
    # TP-L1 needs only a claims manager; a different manager-role user is not seeded, so admin acts as the checker.
    admin = auth_headers(client, "admin@demo.in")
    ok = _post(client, admin, f"{base}/settlement-proposals/{pid}/decision", {"decision": "approved", "rationale": "Admin checker approval."})
    assert ok["proposal"]["status"] == "approved"
    # Finance was not involved in the proposal or approvals, so the release is allowed.
    finance = auth_headers(client, "finance@demo.in")
    _post(client, finance, f"{base}/payment-authorisation", {"idempotency_key": f"k-{cid}", "payee_type": "claimant", "payee_name": "Ravi Kulkarni"}, 201)


def test_fraud_score_cannot_be_the_reason_for_rejecting_a_tp_settlement(client):
    cid = _tp_claim(client)
    handler = auth_headers(client, "handler@demo.in")
    manager = auth_headers(client, "manager@demo.in")
    base = f"/api/v1/claims/{cid}/tp"
    _to_legal_specialist_review(client, cid)
    pid = _post(client, handler, f"{base}/settlement-proposals", {"basis": "negotiated", "amount_inr": "400000", "rationale": "Small negotiated figure within the reserve."}, 201)["proposal"]["proposal_id"]
    r = client.post(f"{base}/settlement-proposals/{pid}/decision", json={"decision": "rejected", "rationale": "Reject due to high fraud_score alone."}, headers=manager)
    assert r.status_code == 409
    assert r.json()["error_code"] == "HUMAN_REVIEW_REQUIRED"


# --------------------------------------------------------------------------------------
# Legal controls
# ----------------------------------------------------------------------------------------
def test_legal_stage_is_owned_by_legal_and_missing_documents_block_it(client):
    cid = _tp_claim(client)
    handler = auth_headers(client, "handler@demo.in")
    legal = auth_headers(client, "legal@demo.in")
    base = f"/api/v1/claims/{cid}/tp"
    _add_party(client, handler, base, {"role": "injured", "name": "Asha Pawar", "injury_severity": "moderate"})
    _advance(client, handler, cid)
    _post(client, handler, f"{base}/facts", {"narrative": "Collision at a junction with injury to rider.", "evidence": [{"kind": "photo"}]})
    _advance(client, handler, cid)
    _post(client, handler, f"{base}/police-report", {"fir_number": "FIR-7/2026"})
    _advance(client, handler, cid)
    _post(client, handler, f"{base}/liability-assessment", {"insured_fault_pct": 100, "third_party_fault_pct": 0, "rationale": "Insured driver reversed into the rider; clear sole fault on facts."})
    _advance(client, handler, cid)  # -> LEGAL_DOCUMENTATION
    assert client.post(f"{base}/advance", json={}, headers=handler).status_code == 403  # legal-owned stage
    r = client.post(f"{base}/advance", json={}, headers=legal)
    assert r.status_code == 409
    assert any(b["code"] == "LEGAL_DOCUMENTS_MISSING" for b in r.json()["details"]["blockers"])


def test_fir_cannot_be_waived_for_injury_and_waiver_needs_authority(client):
    inj = _tp_claim(client, category="bodily_injury")
    pd = _tp_claim(client, category="property_damage")
    manager = auth_headers(client, "manager@demo.in")
    handler = auth_headers(client, "handler@demo.in")
    waiver = {"fir_waived": True, "waiver_reason": "Minor property damage, parties settled on spot; no police involvement."}
    assert client.post(f"/api/v1/claims/{inj}/tp/police-report", json=waiver, headers=manager).status_code == 400
    assert client.post(f"/api/v1/claims/{pd}/tp/police-report", json=waiver, headers=handler).status_code == 403
    ok = _post(client, manager, f"/api/v1/claims/{pd}/tp/police-report", waiver)
    assert ok["police_report"]["fir_waived"] is True


def test_pay_and_recover_requires_policy_defence_and_flags_recovery_at_closure(client):
    cid = _tp_claim(client)
    legal = auth_headers(client, "legal@demo.in")
    handler = auth_headers(client, "handler@demo.in")
    manager = auth_headers(client, "manager@demo.in")
    finance = auth_headers(client, "finance@demo.in")
    base = f"/api/v1/claims/{cid}/tp"
    _add_party(client, handler, base, {"role": "injured", "name": "Dilip Rane", "injury_severity": "moderate"})
    _advance(client, handler, cid)
    _post(client, handler, f"{base}/facts", {"narrative": "Insured drove under influence and struck a pedestrian.", "evidence": [{"kind": "witness_statement"}]})
    _advance(client, handler, cid)
    _post(client, handler, f"{base}/police-report", {"fir_number": "FIR-9/2026"})
    _advance(client, handler, cid)
    _post(client, handler, f"{base}/liability-assessment", {"insured_fault_pct": 100, "third_party_fault_pct": 0, "policy_defences": ["drunk_driving"], "rationale": "Breathalyser report shows the insured driver was over the limit; sole fault."})
    _advance(client, handler, cid)
    for doc in BI_DOCS:
        _post(client, handler, f"{base}/legal-documents", {"doc_type": doc}, 201)
    _advance(client, legal, cid)
    _post(client, legal, f"{base}/advocates", {"advocate_name": "Adv. P. Deshpande", "conflict_check_cleared": True}, 201)
    _advance(client, legal, cid)
    _post(client, legal, f"{base}/medical-review", {"injury_severity": "moderate", "disability_percent": 10, "opinion": "Consistent with pedestrian impact injury.", "reviewer_name": "Dr. K. Rao"})
    _advance(client, legal, cid)
    _post(client, manager, f"{base}/reserve", {"amount_inr": "500000", "basis": "Moderate injury band reserve"})
    # pay_and_recover is valid only because a defence is on record; a plain decision without one is refused elsewhere.
    _post(client, legal, f"{base}/legal-review", {"decision": "pay_and_recover", "notes": "Insurer remains liable to the third party; recover from the insured under the policy defence."})
    _advance(client, legal, cid)
    pid = _post(client, handler, f"{base}/settlement-proposals", {"basis": "pay_and_recover", "amount_inr": "350000", "rationale": "Compensation to third party with recovery rights against the insured."}, 201)["proposal"]["proposal_id"]
    _post(client, manager, f"{base}/settlement-proposals/{pid}/decision", {"decision": "approved", "rationale": "Pay and recover is approved."})
    _post(client, finance, f"{base}/payment-authorisation", {"idempotency_key": f"par-{cid}", "payee_type": "claimant", "payee_name": "Dilip Rane"}, 201)
    r = client.post(f"{base}/close", json={"closure_notes": "Paid; closing the file.", "recovery_action_opened": False}, headers=manager)
    assert r.status_code == 409
    done = _post(client, manager, f"{base}/close", {"closure_notes": "Paid; recovery action opened against insured.", "recovery_action_opened": True})
    assert done["stage"] == "CLOSED"


def test_pay_and_recover_decision_rejected_without_policy_defence(client):
    cid = _tp_claim(client)
    legal = auth_headers(client, "legal@demo.in")
    base = f"/api/v1/claims/{cid}/tp"
    handler = auth_headers(client, "handler@demo.in")
    manager = auth_headers(client, "manager@demo.in")
    # Reach LEGAL_SPECIALIST_REVIEW without signing off.
    _add_party(client, handler, base, {"role": "injured", "name": "Kiran Joshi", "injury_severity": "grievous"})
    _advance(client, handler, cid)
    _post(client, handler, f"{base}/facts", {"narrative": "Junction collision with injury to a motorcyclist.", "evidence": [{"kind": "photo"}]})
    _advance(client, handler, cid)
    _post(client, handler, f"{base}/police-report", {"fir_number": "FIR-11/2026"})
    _advance(client, handler, cid)
    _post(client, handler, f"{base}/liability-assessment", {"insured_fault_pct": 50, "third_party_fault_pct": 50, "rationale": "Both parties share responsibility based on the site sketch."})
    _advance(client, handler, cid)
    for doc in BI_DOCS:
        _post(client, handler, f"{base}/legal-documents", {"doc_type": doc}, 201)
    _advance(client, legal, cid)
    _post(client, legal, f"{base}/advocates", {"advocate_name": "Adv. M. Gupta", "conflict_check_cleared": True}, 201)
    _advance(client, legal, cid)
    _post(client, legal, f"{base}/medical-review", {"injury_severity": "grievous", "disability_percent": 20, "opinion": "Fracture consistent with the accident mechanism.", "reviewer_name": "Dr. N. Iyer"})
    _advance(client, legal, cid)
    r = client.post(f"{base}/legal-review", json={"decision": "pay_and_recover", "notes": "Attempting recovery route without any recorded defence on file."}, headers=legal)
    assert r.status_code == 400
    # reserve above INR 5 lakh needs manager/legal authority
    assert client.post(f"{base}/reserve", json={"amount_inr": "900000", "basis": "Grievous injury reserve basis"}, headers=handler).status_code == 403
    assert client.post(f"{base}/reserve", json={"amount_inr": "900000", "basis": "Grievous injury reserve basis"}, headers=manager).status_code == 200


def test_tribunal_award_basis_requires_recorded_award_and_matching_amount(client):
    cid2 = _tp_claim(client)
    legal = auth_headers(client, "legal@demo.in")
    handler = auth_headers(client, "handler@demo.in")
    manager = auth_headers(client, "manager@demo.in")
    base2 = f"/api/v1/claims/{cid2}/tp"
    _add_party(client, handler, base2, {"role": "injured", "name": "Sunil More", "injury_severity": "grievous"})
    _advance(client, handler, cid2)
    _post(client, handler, f"{base2}/facts", {"narrative": "Disputed junction collision with rider injury.", "evidence": [{"kind": "dashcam"}]})
    _advance(client, handler, cid2)
    _post(client, handler, f"{base2}/police-report", {"fir_number": "FIR-21/2026"})
    _advance(client, handler, cid2)
    _post(client, handler, f"{base2}/liability-assessment", {"insured_fault_pct": 10, "third_party_fault_pct": 90, "rationale": "Dashcam shows the rider jumped the signal; insured fault minimal."})
    _advance(client, handler, cid2)
    for doc in BI_DOCS:
        _post(client, handler, f"{base2}/legal-documents", {"doc_type": doc}, 201)
    _advance(client, legal, cid2)
    _post(client, legal, f"{base2}/advocates", {"advocate_name": "Adv. R. Menon", "role": "defence_counsel", "conflict_check_cleared": True}, 201)
    _advance(client, legal, cid2)
    _post(client, legal, f"{base2}/medical-review", {"injury_severity": "grievous", "disability_percent": 15, "opinion": "Injury documented; causation disputed by insured.", "reviewer_name": "Dr. T. Bose"})
    _advance(client, legal, cid2)
    _post(client, manager, f"{base2}/reserve", {"amount_inr": "800000", "basis": "Contested grievous injury reserve"})
    _post(client, legal, f"{base2}/legal-review", {"decision": "contest_liability", "notes": "Contest before the tribunal; negotiated payment is not recommended on this record."})
    _advance(client, legal, cid2)
    # contest_liability: negotiated payment is refused
    r = client.post(f"{base2}/settlement-proposals", json={"basis": "negotiated", "amount_inr": "300000", "rationale": "Trying a negotiated payment despite the contest decision."}, headers=handler)
    assert r.status_code == 409
    # tribunal award not yet recorded
    r = client.post(f"{base2}/settlement-proposals", json={"basis": "tribunal_award", "amount_inr": "600000", "award_reference": "MACT/2026/55", "rationale": "Complying with the tribunal award as passed."}, headers=handler)
    assert r.status_code == 400
    _post(client, legal, f"{base2}/tribunal", {"claim_petition_filed": True, "tribunal_name": "MACT Pune (DEMO)", "petition_number": "MACT/2026/55", "award_amount_inr": "600000", "award_reference": "MACT/2026/55"})
    r = client.post(f"{base2}/settlement-proposals", json={"basis": "tribunal_award", "amount_inr": "550000", "award_reference": "MACT/2026/55", "rationale": "Complying with the tribunal award as passed."}, headers=handler)
    assert r.status_code == 400  # must equal the recorded award
    ok = _post(client, handler, f"{base2}/settlement-proposals", {"basis": "tribunal_award", "amount_inr": "600000", "award_reference": "MACT/2026/55", "rationale": "Complying with the tribunal award as passed."}, 201)
    assert ok["proposal"]["approval_tier"] == "TP-L2"


# --------------------------------------------------------------------------------------
# TP is isolated from the OD autonomous settlement logic
# ----------------------------------------------------------------------------------------
def test_od_settlement_approval_payment_and_close_paths_refuse_tp_claims(client):
    cid = _tp_claim(client)
    handler = auth_headers(client, "handler@demo.in")
    manager = auth_headers(client, "manager@demo.in")
    finance = auth_headers(client, "finance@demo.in")
    r = client.post(f"/api/v1/claims/{cid}/settlement-recommendations", json={}, headers=handler)
    assert r.status_code == 409
    assert r.json()["error_code"] == "HUMAN_REVIEW_REQUIRED"
    assert "TP" in r.json()["message"]
    r = client.post(f"/api/v1/claims/{cid}/approvals", json={"approval_id": "x", "decision": "approved", "rationale": "ok ok ok ok"}, headers=manager)
    assert r.status_code == 409
    r = client.post(
        f"/api/v1/claims/{cid}/payments",
        json={"settlement_id": "x", "idempotency_key": "k1", "payee_name": "X", "payee_type": "claimant", "account_last4": "1234", "ifsc": "HDFC0000001"},
        headers=finance,
    )
    assert r.status_code == 409
    assert client.post(f"/api/v1/claims/{cid}/close", headers=manager).status_code == 409


def test_settlement_agent_never_auto_approves_third_party_claims():
    agent = AGENT_REGISTRY["settlement_recommendation"]
    resp = agent.execute(
        AgentInvocationRequest(
            tenant_id="tenant-in-demo",
            claim_id="clm-demo-0010",
            correlation_id="corr-tp-1",
            workflow_run_id="wf-tp-1",
            actor_user_id="usr-handler",
            actor_role="claims_handler",
            claim_type="third_party",
            minimised_facts={
                "risk_tier": "LOW",
                "straight_through_eligible": True,
                "allow_fast_track_auto_approve": True,
                "active_conditions": [],
                "calculation": {"net": "10000.00"},
            },
            allowed_tools=sorted(agent.allowed_tools),
        )
    )
    assert resp.status == AgentStatus.NEEDS_HUMAN
    assert resp.result["auto_approved"] is False
    assert resp.result["tp_workflow_required"] is True
    assert resp.actions_executed == []
    assert resp.suggested_next_action == "route_to_tp_legal_workflow"


def test_risk_engine_never_marks_third_party_straight_through_eligible():
    low_facts = {
        "effective_loss_inr": "5000.00",
        "estimated_loss_inr": "5000.00",
        "idv_inr": "780000.00",
        "claim_type": "cashless",
        "peril_cause": "road_accident",
        "claim_status": "REGISTERED",
        "policy_matched": True,
        "missing_documents": [],
    }
    od = classify_claim_risk_from_facts(low_facts, trigger_event="od_control")
    assert od["automation_eligibility"]["straight_through_eligible"] is True  # control: OD can be straight-through

    tp = classify_claim_risk_from_facts({**low_facts, "claim_type": "third_party", "peril_cause": "tp_property_damage"}, trigger_event="tp_unit")
    assert tp["automation_eligibility"]["straight_through_eligible"] is False
    assert tp["risk_tier"] == "HIGH"


def test_od_claim_spawns_separate_linked_tp_claim_not_a_variant_of_the_same_workflow(client):
    handler = auth_headers(client, "handler@demo.in")
    r = _post(client, handler, "/api/v1/claims/clm-demo-0001/tp/exposures", {"tp_category": "property_damage", "description": "Insured car also damaged a parked third-party car."}, 201)
    assert r["tp_claim_id"] != "clm-demo-0001"
    assert r["tp_case"]["linked_od_claim_id"] == "clm-demo-0001"
    assert r["tp_case"]["tp_category"] == "property_damage"
    again = _post(client, handler, "/api/v1/claims/clm-demo-0001/tp/exposures", {"tp_category": "property_damage"}, 201)
    assert again["tp_claim_id"] == r["tp_claim_id"]  # idempotent per category
    od = client.get("/api/v1/claims/clm-demo-0001", headers=handler).json()
    assert od["claim"]["claim_type"] != "third_party"
    # OD claim cannot itself carry a TP case.
    r2 = client.post("/api/v1/claims/clm-demo-0001/tp/open", json={}, headers=handler)
    assert r2.status_code == 409


def test_tp_queue_dashboard_lists_dedicated_queues_and_no_autonomy(client):
    _tp_claim(client)
    handler = auth_headers(client, "handler@demo.in")
    d = client.get("/api/v1/tp/queues", headers=handler).json()
    names = {q["queue"] for q in d["queues"]}
    assert {"tp_intake", "tp_liability_investigation", "tp_legal_specialist_review", "tp_settlement_control", "tp_payment_authorisation"} <= names
    assert d["autonomous_settlement_allowed"] is False
    assert d["open_cases"] >= 2
    life = client.get("/api/v1/tp/lifecycle", headers=handler).json()
    assert [s["stage"] for s in life["stages"]] == STAGE_ORDER
    assert life["controls"]["ai_may_determine_liability"] is False


def test_advisory_is_non_binding_and_never_determines_liability(client):
    cid = _tp_claim(client)
    legal = auth_headers(client, "legal@demo.in")
    tp = client.get(f"/api/v1/claims/{cid}/tp", headers=legal).json()
    adv = tp["advisory"]
    assert adv["binding"] is False
    assert adv["ai_determines_liability"] is False
    assert tp["liability_assessment"] == {}  # nothing is pre-filled by software
