from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from services.claims.audit import emit_outbox_event, record_audit_event
from services.claims.db import Base, engine
from services.claims.models import (
    Claim,
    ClaimParty,
    Customer,
    DamageAssessment,
    Estimate,
    EstimateLine,
    Evidence,
    ExtractedFact,
    FraudAlert,
    Grievance,
    Payment,
    Policy,
    Provider,
    Settlement,
    SLATimer,
    SurveyAssignment,
    Tenant,
    User,
    Vehicle,
)
from services.rules_engine.loader import sync_rules_to_db


def ensure_seeded(db: Session) -> None:
    if db.query(Tenant).count() == 0:
        seed_all(db)


def reset_and_seed(db: Session) -> None:
    db.close()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from services.claims.db import SessionLocal

    fresh = SessionLocal()
    try:
        seed_all(fresh)
    finally:
        fresh.close()


def seed_all(db: Session) -> None:
    now = datetime.now(timezone.utc)
    sync_rules_to_db(db)

    t1 = Tenant(id="tenant-in-demo", code="IN-MOTOR-DEMO", name="Bharat Suraksha Motor Insurance (DEMO / SYNTHETIC)", jurisdiction="IN")
    t2 = Tenant(id="tenant-other-demo", code="IN-OTHER-DEMO", name="Isolated Secondary Tenant (DEMO / SYNTHETIC)", jurisdiction="IN")
    db.add_all([t1, t2])
    db.flush()

    surv1 = Provider(
        id="prov-surv-01",
        tenant_id=t1.id,
        provider_type="surveyor",
        name="R. K. Sharma & Associates (IIISLA-DEMO-4421)",
        licence_or_contract_id="IRDAI-SLA-DEMO-4421",
        licence_status="verified",
        city="Mumbai",
        ev_capable=True,
        active_load=3,
        max_capacity=12,
        quality_score=Decimal("4.80"),
        is_available=True,
    )
    surv2 = Provider(
        id="prov-surv-02",
        tenant_id=t1.id,
        provider_type="surveyor",
        name="Meera Nair Loss Assessors (IIISLA-DEMO-7890)",
        licence_or_contract_id="IRDAI-SLA-DEMO-7890",
        licence_status="verified",
        city="Bengaluru",
        ev_capable=True,
        active_load=2,
        max_capacity=10,
        quality_score=Decimal("4.75"),
        is_available=True,
    )
    gar1 = Provider(
        id="prov-gar-01",
        tenant_id=t1.id,
        provider_type="garage",
        name="Apex Motors Cashless Hub — Andheri (DEMO)",
        licence_or_contract_id="GAR-NET-MUM-101",
        licence_status="verified",
        city="Mumbai",
        ev_capable=False,
        is_network=True,
        active_load=5,
        max_capacity=20,
        quality_score=Decimal("4.60"),
    )
    gar_ev = Provider(
        id="prov-gar-ev-02",
        tenant_id=t1.id,
        provider_type="garage",
        name="VoltCare OEM EV Specialist Centre (DEMO)",
        licence_or_contract_id="GAR-EV-MUM-202",
        licence_status="verified",
        city="Mumbai",
        ev_capable=True,
        is_network=True,
        active_load=2,
        max_capacity=10,
        quality_score=Decimal("4.90"),
    )
    db.add_all([surv1, surv2, gar1, gar_ev])

    cust1 = Customer(
        id="cust-demo-01",
        tenant_id=t1.id,
        name="Aarav Deshmukh (DEMO)",
        phone_token="TOK-PH-98201",
        phone_masked="******4321",
        email_masked="aa***@demo.in",
        preferred_language="en-IN",
    )
    cust2 = Customer(
        id="cust-demo-02",
        tenant_id=t1.id,
        name="Priya Subramanian (DEMO)",
        phone_token="TOK-PH-98452",
        phone_masked="******7788",
        email_masked="pr***@demo.in",
        preferred_language="hi-IN",
    )
    cust_other = Customer(
        id="cust-other-01",
        tenant_id=t2.id,
        name="Other Tenant Customer (DEMO)",
        phone_token="TOK-PH-00001",
        phone_masked="******9999",
        email_masked="ot***@other.in",
    )
    db.add_all([cust1, cust2, cust_other])

    users = [
        User(id="usr-policyholder", tenant_id=t1.id, email="policyholder@demo.in", name="Aarav Deshmukh (Customer)", role="policyholder", partner_id=cust1.id),
        User(id="usr-fnol", tenant_id=t1.id, email="fnol@demo.in", name="Neha Kapoor (FNOL Exec)", role="fnol_executive"),
        User(id="usr-handler", tenant_id=t1.id, email="handler@demo.in", name="Vikram Mehta (Claims Handler)", role="claims_handler"),
        User(id="usr-handler2", tenant_id=t1.id, email="handler2@demo.in", name="Ananya Rao (Checker Handler)", role="claims_handler"),
        User(id="usr-surveyor", tenant_id=t1.id, email="surveyor@demo.in", name="R. K. Sharma (Surveyor)", role="surveyor", partner_id=surv1.id),
        User(id="usr-garage", tenant_id=t1.id, email="garage@demo.in", name="Apex Motors Advisor", role="garage", partner_id=gar1.id),
        User(id="usr-siu", tenant_id=t1.id, email="siu@demo.in", name="Karan Malhotra (SIU Analyst)", role="siu_investigator"),
        User(id="usr-manager", tenant_id=t1.id, email="manager@demo.in", name="Sunita Iyer (Claims Manager)", role="claims_manager"),
        User(id="usr-legal", tenant_id=t1.id, email="legal@demo.in", name="Adv. Ritu Verma (Legal / TP)", role="legal_tp"),
        User(id="usr-finance", tenant_id=t1.id, email="finance@demo.in", name="Rajesh Joshi (Finance Approver)", role="finance_approver"),
        User(id="usr-auditor", tenant_id=t1.id, email="auditor@demo.in", name="Deepak Kulkarni (Compliance Auditor)", role="auditor"),
        User(id="usr-admin", tenant_id=t1.id, email="admin@demo.in", name="Platform Admin", role="admin"),
        User(id="usr-other-tenant", tenant_id=t2.id, email="other@other.in", name="Other Tenant Handler", role="claims_handler"),
    ]
    db.add_all(users)

    veh1 = Vehicle(
        id="veh-demo-01",
        tenant_id=t1.id,
        registration_number="MH02DEMO1042",
        vin_chassis="MA3DEMO0000104291",
        engine_number="K12NDEMO4412",
        make="Maruti Suzuki",
        model="Baleno Alpha",
        year=2024,
        vehicle_category="private_car",
        fuel_type="petrol",
        is_ev=False,
        cc_class="private_car_under_1500cc",
        first_registration_date=now - timedelta(days=540),
    )
    veh_ev = Vehicle(
        id="veh-demo-ev",
        tenant_id=t1.id,
        registration_number="MH01EVDEMO99",
        vin_chassis="MATDEMOEV00009911",
        engine_number="EVDRV9911",
        make="Tata",
        model="Nexon EV Max",
        year=2025,
        vehicle_category="private_car",
        fuel_type="ev",
        is_ev=True,
        cc_class="ev_private_car",
        first_registration_date=now - timedelta(days=320),
    )
    veh2 = Vehicle(
        id="veh-demo-02",
        tenant_id=t1.id,
        registration_number="KA03DEMO5521",
        vin_chassis="MALDEMO0000552100",
        engine_number="G4LADEMO8821",
        make="Hyundai",
        model="Creta SX",
        year=2023,
        vehicle_category="private_car",
        fuel_type="diesel",
        is_ev=False,
        cc_class="private_car_over_1500cc",
        first_registration_date=now - timedelta(days=900),
    )
    veh_other = Vehicle(
        id="veh-other-01",
        tenant_id=t2.id,
        registration_number="DL01OTH0001",
        vin_chassis="OTHVIN0001",
        engine_number="OTHENG01",
        make="Honda",
        model="City",
        year=2024,
        first_registration_date=now - timedelta(days=400),
    )
    db.add_all([veh1, veh_ev, veh2, veh_other])

    pol1 = Policy(
        id="pol-demo-01",
        tenant_id=t1.id,
        customer_id=cust1.id,
        vehicle_id=veh1.id,
        policy_number="POL-IN-DEMO-2026-1001",
        product_code="PRIVATE_CAR_PACKAGE",
        uin="DEMO-IRDAI-PC-2024-V1",
        period_start=now - timedelta(days=90),
        period_end=now + timedelta(days=275),
        status="active",
        idv_inr=Decimal("780000.00"),
        compulsory_deductible_inr=Decimal("1000.00"),
        voluntary_deductible_inr=Decimal("0.00"),
        addons={"zero_depreciation": True, "consumables": True, "rsa": True},
        endorsements=["IMT-22 Compulsory Deductible", "Zero Depreciation Add-on"],
    )
    pol_ev = Policy(
        id="pol-demo-ev",
        tenant_id=t1.id,
        customer_id=cust1.id,
        vehicle_id=veh_ev.id,
        policy_number="POL-IN-DEMO-2026-EV02",
        product_code="EV_PRIVATE_CAR_PACKAGE",
        uin="DEMO-IRDAI-EV-2025-V1",
        period_start=now - timedelta(days=60),
        period_end=now + timedelta(days=305),
        status="active",
        idv_inr=Decimal("1550000.00"),
        compulsory_deductible_inr=Decimal("1500.00"),
        voluntary_deductible_inr=Decimal("0.00"),
        addons={"zero_depreciation": True, "consumables": True, "ev_protect": True},
        endorsements=["EV Traction Battery & HV Protect"],
        wording_doc_id="POL-WORDING-EV-2025",
    )
    pol2 = Policy(
        id="pol-demo-02",
        tenant_id=t1.id,
        customer_id=cust2.id,
        vehicle_id=veh2.id,
        policy_number="POL-IN-DEMO-2026-2002",
        product_code="PRIVATE_CAR_PACKAGE",
        uin="DEMO-IRDAI-PC-2024-V1",
        period_start=now - timedelta(days=6),
        period_end=now + timedelta(days=359),
        status="active",
        idv_inr=Decimal("1120000.00"),
        compulsory_deductible_inr=Decimal("2000.00"),
        voluntary_deductible_inr=Decimal("2500.00"),
        addons={"zero_depreciation": False, "consumables": False},
    )
    pol_other = Policy(
        id="pol-other-01",
        tenant_id=t2.id,
        customer_id=cust_other.id,
        vehicle_id=veh_other.id,
        policy_number="POL-OTH-2026-9999",
        product_code="PRIVATE_CAR_PACKAGE",
        uin="DEMO-IRDAI-PC-2024-V1",
        period_start=now - timedelta(days=30),
        period_end=now + timedelta(days=335),
        status="active",
        idv_inr=Decimal("900000.00"),
    )
    db.add_all([pol1, pol_ev, pol2, pol_other])
    db.flush()

    c1 = Claim(
        id="clm-demo-0001",
        tenant_id=t1.id,
        claim_number="CLM-DEMO-2026-0001",
        policy_id=pol1.id,
        customer_id=cust1.id,
        vehicle_id=veh1.id,
        claim_type="cashless",
        peril_cause="road_accident",
        intake_channel="web",
        status="ESTIMATE_REVIEW",
        severity_band="medium",
        queue_name="standard_survey_queue",
        incident_at=now - timedelta(days=2),
        incident_location="Western Express Highway, Andheri East, Mumbai",
        incident_description="Front bumper, RH LED headlamp, and front RH fender impacted during sudden braking in slow traffic.",
        policy_number_input=pol1.policy_number,
        vehicle_reg_input=veh1.registration_number,
        driver_name="Aarav Deshmukh",
        driver_licence_ref="MH02-20180044129",
        estimated_loss_inr=Decimal("64200.00"),
        requires_mandatory_survey=True,
        assigned_handler_id="usr-handler",
        assigned_surveyor_id=surv1.id,
        assigned_garage_id=gar1.id,
        missing_documents=[],
        next_expected_action="Adjuster/Surveyor to review duplicated estimate line and generate settlement recommendation",
        coverage_factsheet={
            "agent_name": "coverage_intelligence",
            "status": "completed",
            "confidence": 0.91,
            "confidence_band": "high",
            "result": {
                "supported_facts": ["Policy active; incident within period", "Zero Depreciation & Consumables add-ons active"],
                "possible_exclusions_to_verify": ["Valid DL verified (MH02-20180044129)"],
            },
            "evidence_refs": [{"source_type": "policy_clause", "source_id": "POL-WORDING-PC-2024", "reference": "POL-WORDING-PC-2024 SEC-1-1 p.3"}],
        },
        workflow_state={"workflow_run_id": "wf-demo-0001", "steps_completed": ["FNOL", "EVIDENCE", "COVERAGE", "TRIAGE", "SURVEY_ASSIGNED"]},
    )
    db.add(c1)
    db.flush()

    for idx, angle in enumerate(["front", "rear", "left", "right", "odometer", "closeup"]):
        ev = Evidence(
            tenant_id=t1.id,
            claim_id=c1.id,
            doc_type="damage_photo",
            doc_status="verified",
            filename=f"demo_car_{angle}_{idx+1}.jpg",
            mime_type="image/jpeg",
            size_bytes=184200,
            sha256=f"demo_hash_c1_{angle}_{idx}",
            storage_path=f"./evidence_store/demo_{angle}.jpg",
            uploader_user_id="usr-policyholder",
            image_angle=angle,
            image_quality_status="acceptable",
        )
        db.add(ev)

    for doc_type, fname, text in [
        ("policy_schedule", "policy_schedule_demo.pdf", f"Policy {pol1.policy_number} Vehicle {veh1.registration_number}"),
        ("registration_certificate", "rc_demo.pdf", f"Registration {veh1.registration_number} Chassis {veh1.vin_chassis}"),
        ("driving_licence", "dl_demo.pdf", "DL MH02-20180044129 Valid till 2038"),
    ]:
        ev_doc = Evidence(
            tenant_id=t1.id,
            claim_id=c1.id,
            doc_type=doc_type,
            doc_status="verified",
            filename=fname,
            mime_type="application/pdf",
            size_bytes=92400,
            sha256=f"demo_doc_{doc_type}",
            storage_path=f"./evidence_store/{fname}",
            uploader_user_id="usr-policyholder",
            ocr_text=text,
        )
        db.add(ev_doc)
        db.flush()
        db.add(
            ExtractedFact(
                tenant_id=t1.id,
                claim_id=c1.id,
                evidence_id=ev_doc.id,
                field_name="document_identity",
                extracted_value=text,
                verified_value=text,
                confidence=Decimal("0.940"),
                validation_status="verified",
            )
        )

    db.add_all(
        [
            DamageAssessment(
                tenant_id=t1.id,
                claim_id=c1.id,
                component_name="Front Bumper Assembly (Primed)",
                part_code="PRT-FRT-BMP-01",
                damage_class="deformation",
                observation_type="visible_observed",
                recommended_action="replace",
                confidence=Decimal("0.890"),
                reviewer_outcome="accepted",
            ),
            DamageAssessment(
                tenant_id=t1.id,
                claim_id=c1.id,
                component_name="Headlamp Assembly LED RH",
                part_code="PRT-HL-LED-RH",
                damage_class="crack",
                observation_type="visible_observed",
                recommended_action="replace",
                confidence=Decimal("0.860"),
                reviewer_outcome="accepted",
            ),
            DamageAssessment(
                tenant_id=t1.id,
                claim_id=c1.id,
                component_name="Front Fender Panel RH (Steel)",
                part_code="PRT-FND-RH-01",
                damage_class="dent",
                observation_type="visible_observed",
                recommended_action="repair",
                confidence=Decimal("0.810"),
                reviewer_outcome="pending",
            ),
        ]
    )

    est1 = Estimate(
        id="est-demo-0001",
        tenant_id=t1.id,
        claim_id=c1.id,
        garage_id=gar1.id,
        version=1,
        status="disputed",
        total_claimed_inr=Decimal("64200.00"),
        total_approved_inr=Decimal("48700.00"),
        anomalies=[
            {
                "type": "duplicate_line",
                "severity": "medium",
                "part_code": "PRT-FRT-BMP-01",
                "message": "Duplicate estimate line for Front Bumper Assembly (part). Explainable billing error—not proof of fraud.",
            },
            {
                "type": "rate_variance",
                "severity": "medium",
                "part_code": "PRT-FND-RH-01",
                "message": "Claimed INR 10800 exceeds OEM rate card INR 7800 by 38.5%",
            },
        ],
    )
    db.add(est1)
    db.flush()
    db.add_all(
        [
            EstimateLine(
                estimate_id=est1.id,
                part_code="PRT-FRT-BMP-01",
                description="Front Bumper Assembly (Primed)",
                part_category="rubber_nylon_plastic_tyres_tubes_batteries_airbags",
                line_type="part",
                quantity=1,
                unit_price_inr=Decimal("12500.00"),
                rate_card_price_inr=Decimal("12500.00"),
                approved_amount_inr=Decimal("12500.00"),
                reviewer_status="accepted",
            ),
            EstimateLine(
                estimate_id=est1.id,
                part_code="PRT-FRT-BMP-01",
                description="Front Bumper Assembly (Primed) [DUPLICATE ENTRY]",
                part_category="rubber_nylon_plastic_tyres_tubes_batteries_airbags",
                line_type="part",
                quantity=1,
                unit_price_inr=Decimal("12500.00"),
                rate_card_price_inr=Decimal("12500.00"),
                approved_amount_inr=Decimal("0.00"),
                variance_flag="DUPLICATE_LINE: repeats line #1 for PRT-FRT-BMP-01 (part)",
                reviewer_status="pending",
            ),
            EstimateLine(
                estimate_id=est1.id,
                part_code="PRT-HL-LED-RH",
                description="Headlamp Assembly LED RH",
                part_category="glass",
                line_type="part",
                quantity=1,
                unit_price_inr=Decimal("18400.00"),
                rate_card_price_inr=Decimal("18400.00"),
                approved_amount_inr=Decimal("18400.00"),
                reviewer_status="accepted",
            ),
            EstimateLine(
                estimate_id=est1.id,
                part_code="PRT-FND-RH-01",
                description="Front Fender Panel RH (Steel)",
                part_category="metal",
                line_type="part",
                quantity=1,
                unit_price_inr=Decimal("10800.00"),
                rate_card_price_inr=Decimal("7800.00"),
                approved_amount_inr=Decimal("7800.00"),
                variance_flag="RATE_VARIANCE: +38.5% vs OEM rate card (7800.00)",
                reviewer_status="pending",
            ),
            EstimateLine(
                estimate_id=est1.id,
                part_code="PRT-FRT-BMP-01",
                description="Bumper + Fender R&R Labour & Painting",
                part_category="labour",
                line_type="labour",
                quantity=1,
                unit_price_inr=Decimal("7600.00"),
                rate_card_price_inr=Decimal("7600.00"),
                approved_amount_inr=Decimal("7600.00"),
                reviewer_status="accepted",
            ),
            EstimateLine(
                estimate_id=est1.id,
                part_code="PRT-CONS-KIT-01",
                description="AC Gas, Coolant & Fasteners Kit",
                part_category="consumables_default",
                line_type="consumable",
                quantity=1,
                unit_price_inr=Decimal("2400.00"),
                rate_card_price_inr=Decimal("2400.00"),
                approved_amount_inr=Decimal("2400.00"),
                reviewer_status="accepted",
            ),
        ]
    )

    db.add(
        SurveyAssignment(
            tenant_id=t1.id,
            claim_id=c1.id,
            surveyor_id=surv1.id,
            status="inspected",
            assigned_at=now - timedelta(hours=20),
            report_due_at=now + timedelta(days=14),
            report_summary={"inspection_notes": "Front impact confirmed; duplicate bumper line noted for deduction."},
        )
    )
    db.add(
        FraudAlert(
            tenant_id=t1.id,
            claim_id=c1.id,
            indicator_code="FRD-EST-ANOMALY",
            title="Repair estimate contains duplicated Front Bumper line",
            severity_band="low",
            confidence=Decimal("0.680"),
            evidence_summary="Garage estimate repeats PRT-FRT-BMP-01 (INR 12,500) twice.",
            benign_explanation="Common clerk copy-paste error in draft garage quotes.",
            recommended_action="Remove duplicate line and confirm with garage advisor.",
            entity_links=[{"type": "garage", "id": gar1.id}],
            status="new",
        )
    )
    db.add(
        SLATimer(
            tenant_id=t1.id,
            claim_id=c1.id,
            stage="survey_report_submission",
            start_event="SurveyorAssigned",
            stop_event="SurveyReportReceived",
            started_at=now - timedelta(hours=20),
            due_at=now + timedelta(days=14),
            owner_role="surveyor",
            daily_penalty_inr=Decimal("500.00"),
            status="on_track",
        )
    )

    edge_claims = [
        Claim(
            id="clm-demo-0002",
            tenant_id=t1.id,
            claim_number="CLM-DEMO-2026-0002",
            policy_id=pol1.id,
            customer_id=cust1.id,
            vehicle_id=veh1.id,
            claim_type="own_damage",
            status="EVIDENCE_PENDING",
            severity_band="low",
            queue_name="evidence_follow_up",
            incident_at=now - timedelta(hours=10),
            incident_location="Bandra Reclamation, Mumbai",
            incident_description="Minor rear bumper scuff in parking lot. Documents to follow.",
            policy_number_input=pol1.policy_number,
            vehicle_reg_input=veh1.registration_number,
            estimated_loss_inr=Decimal("14000.00"),
            missing_documents=["Registration Certificate (RC)", "Driving Licence (DL)", "6-Angle Photos"],
            next_expected_action="Follow-up workflow active for missing RC/DL/Photos (IRDAI: never reject for missing docs)",
            assigned_handler_id="usr-handler",
        ),
        Claim(
            id="clm-demo-0003",
            tenant_id=t1.id,
            claim_number="CLM-DEMO-2026-0003",
            policy_id=pol2.id,
            customer_id=cust2.id,
            vehicle_id=veh2.id,
            claim_type="own_damage",
            status="CLARIFICATION_REQUESTED",
            severity_band="medium",
            queue_name="document_exception",
            incident_at=now - timedelta(days=1),
            incident_location="Indiranagar, Bengaluru",
            incident_description="OCR extracted KA03DEMO9999 on RC copy vs KA03DEMO5521 on policy schedule.",
            policy_number_input=pol2.policy_number,
            vehicle_reg_input=veh2.registration_number,
            estimated_loss_inr=Decimal("32000.00"),
            next_expected_action="Human handler to verify & correct vehicle registration mismatch in Evidence tab",
            assigned_handler_id="usr-handler",
        ),
        Claim(
            id="clm-demo-0004",
            tenant_id=t1.id,
            claim_number="CLM-DEMO-2026-0004",
            policy_id=pol1.id,
            customer_id=cust1.id,
            vehicle_id=veh1.id,
            claim_type="own_damage",
            status="EVIDENCE_PENDING",
            severity_band="low",
            queue_name="evidence_follow_up",
            incident_at=now - timedelta(hours=18),
            incident_location="Powai, Mumbai",
            incident_description="Dark/blurry night photos uploaded; guided recapture requested.",
            policy_number_input=pol1.policy_number,
            vehicle_reg_input=veh1.registration_number,
            estimated_loss_inr=Decimal("18500.00"),
            next_expected_action="Customer to recapture clear daylight front & close-up photos",
        ),
        Claim(
            id="clm-demo-0005",
            tenant_id=t1.id,
            claim_number="CLM-DEMO-2026-0005",
            policy_id=pol1.id,
            customer_id=cust1.id,
            vehicle_id=veh1.id,
            claim_type="own_damage",
            status="TRIAGED",
            severity_band="low",
            queue_name="low_risk_od_assisted",
            incident_at=now - timedelta(days=1),
            incident_location="Thane West, Maharashtra",
            incident_description="Windshield & wiper cowl damage near INR 50,000 survey threshold boundary.",
            policy_number_input=pol1.policy_number,
            vehicle_reg_input=veh1.registration_number,
            estimated_loss_inr=Decimal("49500.00"),
            requires_mandatory_survey=False,
            next_expected_action="Eligible for AI-assisted assessment (just below INR 50,000 threshold); monitor supplements",
        ),
        Claim(
            id="clm-demo-0006",
            tenant_id=t1.id,
            claim_number="CLM-DEMO-2026-0006",
            policy_id=pol2.id,
            customer_id=cust2.id,
            vehicle_id=veh2.id,
            claim_type="own_damage",
            status="SURVEY_ASSIGNED",
            severity_band="high",
            queue_name="sla_escalated",
            incident_at=now - timedelta(days=18),
            incident_location="Koramangala, Bengaluru",
            incident_description="Side impact collision; surveyor report overdue beyond 15-day IRDAI SLA.",
            policy_number_input=pol2.policy_number,
            vehicle_reg_input=veh2.registration_number,
            estimated_loss_inr=Decimal("115000.00"),
            requires_mandatory_survey=True,
            assigned_surveyor_id=surv2.id,
            assigned_handler_id="usr-handler",
            next_expected_action="SLA BREACHED: Escalate overdue survey report (INR 500/day penalty exposure)",
        ),
        Claim(
            id="clm-demo-0007",
            tenant_id=t1.id,
            claim_number="CLM-DEMO-2026-0007",
            policy_id=pol1.id,
            customer_id=cust1.id,
            vehicle_id=veh1.id,
            claim_type="cashless",
            status="REPAIR_IN_PROGRESS",
            severity_band="medium",
            queue_name="standard_survey_queue",
            incident_at=now - timedelta(days=7),
            incident_location="Lower Parel, Mumbai",
            incident_description="Hidden radiator core support deformation discovered during bumper teardown.",
            policy_number_input=pol1.policy_number,
            vehicle_reg_input=veh1.registration_number,
            estimated_loss_inr=Decimal("58000.00"),
            requires_mandatory_survey=True,
            assigned_surveyor_id=surv1.id,
            assigned_garage_id=gar1.id,
            next_expected_action="Review supplementary estimate for hidden radiator core support",
        ),
        Claim(
            id="clm-demo-0008",
            tenant_id=t1.id,
            claim_number="CLM-DEMO-2026-0008",
            policy_id=pol2.id,
            customer_id=cust2.id,
            vehicle_id=veh2.id,
            claim_type="reimbursement",
            status="APPROVED",
            severity_band="medium",
            queue_name="siu_cleared",
            incident_at=now - timedelta(days=3),
            incident_location="Whitefield, Bengaluru",
            incident_description="Early policy-inception collision; SIU verified prior NCB & dashcam—cleared as genuine.",
            policy_number_input=pol2.policy_number,
            vehicle_reg_input=veh2.registration_number,
            estimated_loss_inr=Decimal("42000.00"),
            assigned_handler_id="usr-handler",
            next_expected_action="Proceed to Finance payment release (SIU alert marked not_substantiated)",
        ),
        Claim(
            id="clm-demo-0009",
            tenant_id=t1.id,
            claim_number="CLM-DEMO-2026-0009",
            policy_id=pol1.id,
            customer_id=cust1.id,
            vehicle_id=veh1.id,
            claim_type="cashless",
            status="PAYMENT_INITIATED",
            severity_band="medium",
            queue_name="finance_reconciliation",
            incident_at=now - timedelta(days=9),
            incident_location="Dadar, Mumbai",
            incident_description="Payment gateway timed out during NEFT instruction; awaiting safe reconciliation.",
            policy_number_input=pol1.policy_number,
            vehicle_reg_input=veh1.registration_number,
            estimated_loss_inr=Decimal("54000.00"),
            requires_mandatory_survey=True,
            assigned_garage_id=gar1.id,
            next_expected_action="Finance to run safe payment reconciliation (do not issue duplicate payout)",
        ),
        Claim(
            id="clm-demo-0010",
            tenant_id=t1.id,
            claim_number="CLM-DEMO-2026-0010",
            policy_id=pol2.id,
            customer_id=cust2.id,
            vehicle_id=veh2.id,
            claim_type="third_party",
            peril_cause="tp_bodily_injury",
            status="TRIAGED",
            severity_band="critical",
            queue_name="legal_tp_specialist",
            incident_at=now - timedelta(days=4),
            incident_location="NH-48 Expressway, Pune-Mumbai",
            incident_description="Third-party motorcyclist sustained leg injury; FIR registered. Legal/TP specialist review mandatory.",
            policy_number_input=pol2.policy_number,
            vehicle_reg_input=veh2.registration_number,
            injury_or_fatality=True,
            police_involved=True,
            estimated_loss_inr=Decimal("350000.00"),
            requires_mandatory_survey=True,
            next_expected_action="Legal/TP Specialist to review FIR, medical records, and MACT liability notice",
        ),
        Claim(
            id="clm-demo-0011",
            tenant_id=t1.id,
            claim_number="CLM-DEMO-2026-0011",
            policy_id=pol_ev.id,
            customer_id=cust1.id,
            vehicle_id=veh_ev.id,
            claim_type="cashless",
            peril_cause="ev_high_voltage",
            status="SURVEY_ASSIGNED",
            severity_band="high",
            queue_name="ev_specialist",
            incident_at=now - timedelta(days=1),
            incident_location="BKC, Mumbai",
            incident_description="Underbody stone hit near EV traction battery pack; HV isolation warning active on dash.",
            policy_number_input=pol_ev.policy_number,
            vehicle_reg_input=veh_ev.registration_number,
            ev_battery_impacted=True,
            vehicle_immobile=True,
            towing_needed=True,
            estimated_loss_inr=Decimal("185000.00"),
            requires_mandatory_survey=True,
            assigned_surveyor_id=surv1.id,
            assigned_garage_id=gar_ev.id,
            next_expected_action="EV Specialist inspection + OEM BMS diagnostic scan at VoltCare EV Hub",
        ),
        Claim(
            id="clm-other-0001",
            tenant_id=t2.id,
            claim_number="CLM-OTH-2026-0001",
            policy_id=pol_other.id,
            customer_id=cust_other.id,
            vehicle_id=veh_other.id,
            claim_type="own_damage",
            status="REGISTERED",
            severity_band="low",
            queue_name="fnol_intake",
            incident_at=now - timedelta(days=1),
            incident_location="Connaught Place, New Delhi",
            incident_description="Isolated tenant claim record (must never be visible to tenant-in-demo).",
            policy_number_input=pol_other.policy_number,
            vehicle_reg_input=veh_other.registration_number,
            estimated_loss_inr=Decimal("20000.00"),
        ),
    ]
    db.add_all(edge_claims)
    db.flush()

    db.add(
        SLATimer(
            tenant_id=t1.id,
            claim_id="clm-demo-0006",
            stage="survey_report_submission",
            start_event="SurveyorAssigned",
            stop_event="SurveyReportReceived",
            started_at=now - timedelta(days=17),
            due_at=now - timedelta(days=2),
            owner_role="surveyor",
            daily_penalty_inr=Decimal("500.00"),
            status="breached",
        )
    )
    db.add(
        ClaimParty(
            tenant_id=t1.id,
            claim_id="clm-demo-0010",
            party_role="third_party",
            name="Suresh Patil (Injured Claimant - Medical File)",
            contact_masked="******1199",
            is_restricted_tp_medical=True,
            notes="Hospital discharge summary & FIR #441/2026 under MACT review.",
        )
    )
    db.add(
        FraudAlert(
            tenant_id=t1.id,
            claim_id="clm-demo-0008",
            indicator_code="FRD-EARLY-INCIDENT",
            title="Incident within 6 days of policy inception",
            severity_band="medium",
            confidence=Decimal("0.720"),
            evidence_summary="Policy started 6 days prior to accident.",
            benign_explanation="Dashcam timestamp and prior insurer NCB certificate confirmed genuine new accident.",
            recommended_action="Verify NCB & dashcam",
            status="not_substantiated",
            assigned_investigator_id="usr-siu",
            disposition_reason="Verified dashcam footage & police diary; cleared for settlement.",
        )
    )

    stl9 = Settlement(
        id="stl-demo-0009",
        tenant_id=t1.id,
        claim_id="clm-demo-0009",
        pathway="cashless",
        gross_assessed_inr=Decimal("52000.00"),
        depreciation_deduction_inr=Decimal("0.00"),
        compulsory_excess_inr=Decimal("1000.00"),
        addon_waiver_inr=Decimal("6500.00"),
        net_payable_inr=Decimal("51000.00"),
        approval_status="approved",
        created_by="usr-handler",
    )
    db.add(stl9)
    db.flush()
    db.add(
        Payment(
            id="pmt-demo-0009",
            tenant_id=t1.id,
            claim_id="clm-demo-0009",
            settlement_id=stl9.id,
            idempotency_key="IDEM-DEMO-0009-V1",
            payee_type="garage",
            payee_name="Apex Motors Cashless Hub — Andheri (DEMO)",
            bank_account_masked="XXXXXX4821",
            bank_verified=True,
            amount_inr=Decimal("51000.00"),
            status="timeout_reconcile_pending",
            gateway_reference="PG-PEND-DEMO0009",
            approved_by_finance_id="usr-finance",
        )
    )
    db.add(
        Evidence(
            tenant_id=t1.id,
            claim_id="clm-demo-0004",
            doc_type="damage_photo",
            doc_status="extracted_unverified",
            filename="dark_blurry_front.jpg",
            mime_type="image/jpeg",
            size_bytes=42100,
            sha256="blurry_demo_hash_004",
            storage_path="./evidence_store/dark_blurry_front.jpg",
            uploader_user_id="usr-policyholder",
            image_angle="front",
            image_quality_status="recapture_needed",
        )
    )
    db.add(
        Grievance(
            tenant_id=t1.id,
            claim_id="clm-demo-0006",
            category="surveyor_delay",
            description="Survey report delayed beyond 15 days; requesting urgent status update.",
            status="acknowledged",
            due_at=now + timedelta(days=12),
        )
    )

    record_audit_event(
        db,
        tenant_id=t1.id,
        claim_id=c1.id,
        actor_id="system-seed",
        actor_role="system",
        action="SYNTHETIC_DEMO_SEEDED",
        object_type="claim",
        object_id=c1.id,
        details={"label": "DEMO / SYNTHETIC"},
    )
    emit_outbox_event(
        db,
        tenant_id=t1.id,
        aggregate_id=c1.id,
        event_type="ClaimCreated",
        payload={"claim_number": c1.claim_number, "synthetic": True},
        idempotency_key="seed-c1-created",
    )
    db.commit()
