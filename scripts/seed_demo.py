from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from services.claims.audit import emit_outbox_event, record_audit_event
from services.claims.db import Base, engine
from services.claims.models import (
    Claim,
    ClaimParty,
    ClaimTask,
    Customer,
    DamageAssessment,
    DeadLetterRecord,
    DecisionRecord,
    EcosystemCoordination,
    Estimate,
    EstimateLine,
    Evidence,
    ExtractedFact,
    FraudAlert,
    Grievance,
    OrchestrationEventLog,
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
from services.damage_ai.assessor import assess_damage_from_evidence
from services.rules_engine.loader import sync_rules_to_db
from services.workflow.risk_engine import evaluate_and_persist_risk


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
        licence_expiry_at=now + timedelta(days=365),
        city="Mumbai",
        service_zones=["Mumbai", "Andheri", "Bandra", "Worli", "Western Express Highway"],
        skills=["ev_hv", "adas_calibration", "oem_maruti", "complex_peril"],
        ev_capable=True,
        active_load=3,
        max_capacity=12,
        sla_target_hours=24,
        sla_status="within_sla",
        avg_turnaround_hours=14,
        quality_score=Decimal("4.80"),
        pickup_drop_available=False,
        is_available=True,
    )
    surv2 = Provider(
        id="prov-surv-02",
        tenant_id=t1.id,
        provider_type="surveyor",
        name="Meera Nair Loss Assessors (IIISLA-DEMO-7890)",
        licence_or_contract_id="IRDAI-SLA-DEMO-7890",
        licence_status="verified",
        licence_expiry_at=now + timedelta(days=400),
        city="Bengaluru",
        service_zones=["Bengaluru", "Koramangala", "Whitefield"],
        skills=["ev_hv", "oem_hyundai", "complex_peril"],
        ev_capable=True,
        active_load=2,
        max_capacity=10,
        sla_target_hours=24,
        sla_status="within_sla",
        avg_turnaround_hours=16,
        quality_score=Decimal("4.75"),
        pickup_drop_available=False,
        is_available=True,
    )
    surv3 = Provider(
        id="prov-surv-03",
        tenant_id=t1.id,
        provider_type="surveyor",
        name="Surveyor C — Kavita Kulkarni (IIISLA-DEMO-9102)",
        licence_or_contract_id="IRDAI-SLA-DEMO-9102",
        licence_status="verified",
        licence_expiry_at=now + timedelta(days=300),
        city="Pune",
        service_zones=["Pune", "Mumbai", "Thane"],
        skills=["oem_maruti", "oem_tata", "bodyshop"],
        ev_capable=False,
        active_load=6,
        max_capacity=10,
        sla_target_hours=24,
        sla_status="within_sla",
        avg_turnaround_hours=19,
        quality_score=Decimal("4.80"),
        pickup_drop_available=False,
        is_available=True,
    )
    surv_exp = Provider(
        id="prov-surv-expired",
        tenant_id=t1.id,
        provider_type="surveyor",
        name="Legacy Unverified Assessor (EXPIRED-DEMO-0009)",
        licence_or_contract_id="IRDAI-SLA-EXP-0009",
        licence_status="expired",
        licence_expiry_at=now - timedelta(days=30),
        city="Mumbai",
        service_zones=["Mumbai"],
        skills=["bodyshop"],
        ev_capable=False,
        active_load=0,
        max_capacity=8,
        sla_target_hours=24,
        sla_status="delayed",
        avg_turnaround_hours=42,
        quality_score=Decimal("3.40"),
        pickup_drop_available=False,
        is_available=True,
    )
    gar1 = Provider(
        id="prov-gar-01",
        tenant_id=t1.id,
        provider_type="garage",
        name="Garage A — Apex Motors Cashless Hub (Andheri DEMO)",
        licence_or_contract_id="GAR-NET-MUM-101",
        licence_status="verified",
        licence_expiry_at=now + timedelta(days=500),
        city="Mumbai",
        service_zones=["Mumbai", "Andheri", "Bandra", "Western Express Highway"],
        skills=["oem_maruti", "oem_hyundai", "adas_calibration", "bodyshop"],
        ev_capable=False,
        is_network=True,
        contract_tier="preferred_network",
        active_load=5,
        max_capacity=20,
        sla_target_hours=24,
        sla_status="within_sla",
        avg_turnaround_hours=16,
        quality_score=Decimal("4.70"),
        parts_stock_status="in_stock",
        parts_lead_time_days=1,
        pickup_drop_available=True,
        towing_capable=False,
        is_available=True,
    )
    gar_ev = Provider(
        id="prov-gar-ev-02",
        tenant_id=t1.id,
        provider_type="garage",
        name="VoltCare OEM EV Specialist Centre (DEMO)",
        licence_or_contract_id="GAR-EV-MUM-202",
        licence_status="verified",
        licence_expiry_at=now + timedelta(days=500),
        city="Mumbai",
        service_zones=["Mumbai", "Worli", "Bandra", "Andheri"],
        skills=["ev_hv", "oem_tata", "adas_calibration", "bodyshop"],
        ev_capable=True,
        is_network=True,
        contract_tier="oem_authorised",
        active_load=2,
        max_capacity=10,
        sla_target_hours=24,
        sla_status="within_sla",
        avg_turnaround_hours=15,
        quality_score=Decimal("4.90"),
        parts_stock_status="partial_backorder",
        parts_lead_time_days=3,
        pickup_drop_available=True,
        towing_capable=True,
        is_available=True,
    )
    gar_busy = Provider(
        id="prov-gar-02",
        tenant_id=t1.id,
        provider_type="garage",
        name="Garage B — Metro Collision Works (Thane DEMO)",
        licence_or_contract_id="GAR-NET-THN-303",
        licence_status="verified",
        licence_expiry_at=now + timedelta(days=365),
        city="Mumbai",
        service_zones=["Thane", "Mumbai"],
        skills=["bodyshop", "oem_hyundai"],
        ev_capable=False,
        is_network=True,
        contract_tier="preferred_network",
        active_load=13,
        max_capacity=15,
        sla_target_hours=24,
        sla_status="delayed",
        avg_turnaround_hours=38,
        quality_score=Decimal("4.20"),
        parts_stock_status="partial_backorder",
        parts_lead_time_days=5,
        pickup_drop_available=True,
        towing_capable=False,
        is_available=True,
    )
    gar_non_net = Provider(
        id="prov-gar-nonnet",
        tenant_id=t1.id,
        provider_type="garage",
        name="Independent Custom Bodyshop (Non-Network DEMO)",
        licence_or_contract_id="GAR-NONNET-999",
        licence_status="verified",
        city="Mumbai",
        service_zones=["Mumbai"],
        skills=["bodyshop"],
        ev_capable=False,
        is_network=False,
        contract_tier="non_network",
        active_load=1,
        max_capacity=8,
        sla_target_hours=48,
        sla_status="at_risk",
        avg_turnaround_hours=30,
        quality_score=Decimal("4.10"),
        parts_stock_status="backordered",
        parts_lead_time_days=7,
        pickup_drop_available=False,
        is_available=True,
    )
    tow1 = Provider(
        id="prov-tow-01",
        tenant_id=t1.id,
        provider_type="towing",
        name="SafeTow EV Flatbed & Roadside Recovery (DEMO)",
        licence_or_contract_id="TOW-RSA-MUM-501",
        licence_status="verified",
        licence_expiry_at=now + timedelta(days=400),
        city="Mumbai",
        service_zones=["Mumbai", "Andheri", "Bandra", "Worli", "Thane"],
        skills=["ev_hv", "flatbed_recovery"],
        ev_capable=True,
        is_network=True,
        contract_tier="preferred_network",
        active_load=2,
        max_capacity=12,
        sla_target_hours=2,
        sla_status="within_sla",
        avg_turnaround_hours=1,
        quality_score=Decimal("4.85"),
        parts_stock_status="in_stock",
        parts_lead_time_days=0,
        pickup_drop_available=True,
        towing_capable=True,
        is_available=True,
    )
    db.add_all([surv1, surv2, surv3, surv_exp, gar1, gar_ev, gar_busy, gar_non_net, tow1])

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
    cust_ft = Customer(
        id="cust-demo-ft01",
        tenant_id=t1.id,
        name="Meera Nair (DEMO)",
        phone_token="TOK-PH-98555",
        phone_masked="******8811",
        email_masked="me***@demo.in",
        preferred_language="en-IN",
    )
    db.add_all([cust1, cust2, cust_other, cust_ft])

    users = [
        User(id="usr-policyholder", tenant_id=t1.id, email="policyholder@demo.in", name="Aarav Deshmukh (Customer)", role="policyholder", partner_id=cust1.id),
        User(id="usr-fnol", tenant_id=t1.id, email="fnol@demo.in", name="Neha Kapoor (FNOL Exec)", role="fnol_executive"),
        User(id="usr-handler", tenant_id=t1.id, email="handler@demo.in", name="Vikram Mehta (Claims Handler)", role="claims_handler"),
        User(id="usr-handler2", tenant_id=t1.id, email="handler2@demo.in", name="Ananya Rao (Checker Handler)", role="claims_handler"),
        User(id="usr-surveyor", tenant_id=t1.id, email="surveyor@demo.in", name="R. K. Sharma (Surveyor)", role="surveyor", partner_id=surv1.id),
        User(id="usr-garage", tenant_id=t1.id, email="garage@demo.in", name="Apex Motors Advisor", role="garage", partner_id=gar1.id),
        User(id="usr-garage-ev", tenant_id=t1.id, email="garage.ev@demo.in", name="VoltCare OEM EV Technician", role="garage", partner_id=gar_ev.id),
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
    veh_ft = Vehicle(
        id="veh-demo-ft01",
        tenant_id=t1.id,
        registration_number="MH12FT2026",
        vin_chassis="MA3FHEB1S00991122",
        engine_number="K12N991122",
        make="Maruti Suzuki",
        model="Swift ZXi+",
        year=2024,
        vehicle_category="private_car",
        fuel_type="petrol",
        is_ev=False,
        cc_class="private_car_1000_to_1500cc",
        first_registration_date=now - timedelta(days=500),
    )
    db.add_all([veh1, veh_ev, veh2, veh_other, veh_ft])

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
    pol_ft = Policy(
        id="pol-demo-ft01",
        tenant_id=t1.id,
        customer_id=cust_ft.id,
        vehicle_id=veh_ft.id,
        policy_number="POL-IN-DEMO-2026-FT01",
        product_code="PRIVATE_CAR_PACKAGE",
        uin="DEMO-IRDAI-PC-2024-V1",
        period_start=now - timedelta(days=120),
        period_end=now + timedelta(days=245),
        status="active",
        idv_inr=Decimal("680000.00"),
        compulsory_deductible_inr=Decimal("1000.00"),
        voluntary_deductible_inr=Decimal("0.00"),
        addons={"zero_depreciation": True, "consumables": True},
        endorsements=["IMT-22 Compulsory Deductible", "Zero Depreciation Add-on"],
    )
    db.add_all([pol1, pol_ev, pol2, pol_other, pol_ft])
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
        workflow_state={
            "workflow_run_id": "wf-demo-0001",
            "current_state": "ESTIMATE_REVIEW",
            "canonical_state": "ESTIMATE_VALIDATION",
            "triage_track": "SURVEY_REQUIRED",
            "paused": False,
            "state_history": [
                {"from_state": "SUBMITTED", "to_state": "REGISTERED", "canonical_state": "REGISTERED", "reason": "FNOL registered cleanly", "actor": "orchestrator"},
                {"from_state": "REGISTERED", "to_state": "VALIDATION", "canonical_state": "VALIDATION", "reason": "Post-FNOL parallel validation wave", "actor": "orchestrator"},
                {"from_state": "VALIDATION", "to_state": "TRIAGE", "canonical_state": "TRIAGE", "reason": "Policy & docs reconciled", "actor": "orchestrator"},
                {"from_state": "TRIAGE", "to_state": "SURVEY_REQUIRED", "canonical_state": "SURVEY_REQUIRED", "reason": "Estimated loss >= INR 50,000 IRDAI gate", "actor": "orchestrator"},
                {"from_state": "SURVEY_REQUIRED", "to_state": "ASSESSMENT", "canonical_state": "ASSESSMENT", "reason": "Conditional Damage + Parallel Fraud wave", "actor": "orchestrator"},
                {"from_state": "ASSESSMENT", "to_state": "ESTIMATE_VALIDATION", "canonical_state": "ESTIMATE_VALIDATION", "reason": "Garage estimate submitted for benchmarking", "actor": "orchestrator"},
            ],
            "parallel_waves": [
                {
                    "wave_id": "wave-seed-postfnol",
                    "wave_name": "post_fnol_parallel",
                    "agents": ["document_intelligence", "coverage_intelligence", "customer_communication"],
                    "wall_duration_ms": 14,
                    "outcomes": {"document_intelligence": "completed", "coverage_intelligence": "completed", "customer_communication": "completed"},
                },
                {
                    "wave_id": "wave-seed-assess",
                    "wave_name": "assessment_and_fraud_parallel",
                    "agents": ["damage_assessment", "fraud_intelligence"],
                    "wall_duration_ms": 18,
                    "outcomes": {"damage_assessment": "completed", "fraud_intelligence": "needs_human"},
                },
            ],
            "steps_completed": [
                "fnol_concierge",
                "document_intelligence",
                "coverage_intelligence",
                "claim_triage",
                "provider_coordination",
                "damage_assessment",
            ],
            "stage_statuses": {
                "fnol_concierge": "completed",
                "document_intelligence": "completed",
                "coverage_intelligence": "completed",
                "claim_triage": "completed",
                "provider_coordination": "completed",
                "damage_assessment": "completed",
                "estimate_validation": "needs_human",
            },
            "published_results": {
                "fnol_concierge": {"status": "completed", "confidence": 0.94, "data": {"normalised_channel": "web"}},
                "document_intelligence": {"status": "completed", "confidence": 0.91, "data": {"reconciliation_status": "reconciled", "conflicts": []}},
                "coverage_intelligence": {"status": "completed", "confidence": 0.92, "data": {"ambiguities": []}},
                "claim_triage": {"status": "completed", "confidence": 0.94, "data": {"recommended_queue": "standard_survey_queue", "routing_priority": "P3_NORMAL"}},
                "provider_coordination": {"status": "completed", "confidence": 0.92, "data": {"customer_preference_honoured": True}},
                "damage_assessment": {"status": "completed", "confidence": 0.88, "data": {"overall_severity": "moderate", "damage_zones": ["front_fascia", "front_right_lighting", "front_right_quarter"]}},
                "estimate_validation": {"status": "needs_human", "confidence": 0.74, "data": {"total_claimed_inr": "64200.00", "total_recommended_inr": "48700.00"}},
            },
        },
    )
    db.add(c1)
    db.flush()

    c1_imgs = []
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
        db.flush()
        c1_imgs.append(
            {
                "id": ev.id,
                "filename": ev.filename,
                "image_angle": ev.image_angle,
                "image_quality_status": ev.image_quality_status,
                "sha256": ev.sha256,
            }
        )

    c1_report = assess_damage_from_evidence(
        claim_description=c1.incident_description,
        is_ev=veh1.is_ev,
        ev_battery_impacted=False,
        image_records=c1_imgs,
        vehicle_info={
            "make": veh1.make,
            "model": veh1.model,
            "variant": "Alpha AGS",
            "year": veh1.year,
            "registration_number": veh1.registration_number,
            "is_ev": veh1.is_ev,
            "fuel_type": veh1.fuel_type,
        },
    )
    c1.damage_report = c1_report
    if isinstance(c1.workflow_state, dict):
        wf1 = dict(c1.workflow_state)
        pub1 = dict(wf1.get("published_results", {}))
        pub1["damage_assessment"] = {"status": "completed", "confidence": 0.88, "data": c1_report}
        wf1["published_results"] = pub1
        c1.workflow_state = wf1

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

    for idx_o, obs in enumerate(c1_report["observations"]):
        cost = obs.get("estimated_cost", {})
        ev_refs = obs.get("evidence", [])
        db.add(
            DamageAssessment(
                tenant_id=t1.id,
                claim_id=c1.id,
                evidence_id=ev_refs[0]["evidence_id"] if ev_refs else None,
                component_name=obs["component_name"],
                part_code=obs.get("part_code"),
                damage_location=obs["damage_location"],
                damage_severity=obs["damage_severity"],
                repairability=obs["repairability"],
                damage_class=obs["damage_class"],
                observation_type=obs["observation_type"],
                recommended_action=obs["recommended_action"],
                visible_damage=obs["visible_damage"],
                possible_hidden_damage=obs["possible_hidden_damage"],
                image_quality=obs["image_quality"],
                confidence=Decimal(str(obs["component_confidence"])),
                confidence_factors=obs["confidence_factors"],
                evidence_refs=ev_refs,
                estimated_parts_inr=Decimal(str(cost.get("parts_oem_inr", "0.00"))),
                estimated_labour_inr=Decimal(str(cost.get("labour_inr", "0.00"))),
                estimated_paint_inr=Decimal(str(cost.get("paint_inr", "0.00"))),
                limitations=obs["limitations"],
                reviewer_outcome="accepted" if idx_o < 2 else "pending",
                model_version=c1_report["model_version"],
            )
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
            multiple_vehicles_involved=True,
            involved_vehicles_count=2,
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
            id="clm-demo-0012",
            tenant_id=t1.id,
            claim_number="CLM-DEMO-2026-0012",
            policy_id=pol1.id,
            customer_id=cust1.id,
            vehicle_id=veh1.id,
            claim_type="cashless",
            peril_cause="road_accident",
            status="APPROVED",
            severity_band="low",
            queue_name="low_risk_od_assisted",
            incident_at=now - timedelta(hours=8),
            incident_location="Juhu Tara Road, Mumbai",
            incident_description="Minor left ORVM housing & bumper corner scuff in society parking; all documents uploaded & verified.",
            policy_number_input=pol1.policy_number,
            vehicle_reg_input=veh1.registration_number,
            estimated_loss_inr=Decimal("16500.00"),
            requires_mandatory_survey=False,
            assigned_garage_id=gar1.id,
            missing_documents=[],
            next_expected_action="LOW RISK Fast-Track auto-approved within INR 25,000 limit; ready for Finance payout",
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
    db.add_all(
        [
            ClaimTask(
                tenant_id=t1.id,
                claim_id=c1.id,
                task_type="estimate_review",
                title="Review duplicated Front Bumper line & +38.5% Fender rate variance",
                description="EstimateValidationAgent detected duplicate PRT-FRT-BMP-01 and +38.5% OEM variance on PRT-FND-RH-01.",
                assigned_role="claims_handler",
                created_by_agent="estimate_validation",
                priority="high",
                status="open",
                reason_code="RC_ESTIMATE_ANOMALIES",
                due_at=now + timedelta(hours=12),
            ),
            ClaimTask(
                tenant_id=t1.id,
                claim_id=c1.id,
                task_type="siu_investigation",
                title="SIU Review: FRD-EST-ANOMALY (Alert-only lead)",
                description="Evaluate duplicated bumper entry with benign clerk error context.",
                assigned_role="siu_investigator",
                created_by_agent="fraud_intelligence",
                priority="medium",
                status="open",
                reason_code="RC_SIU_INVESTIGATIVE_LEAD",
                due_at=now + timedelta(hours=24),
            ),
            DecisionRecord(
                tenant_id=t1.id,
                claim_id=c1.id,
                agent_name="claim_triage",
                stage="3. Triage",
                decision_id="dec-seed-tri-01",
                routing_outcome="standard_survey_queue:P3_NORMAL",
                reason_codes=["RC_MANDATORY_SURVEY_TRIGGERED", "RC_PRIORITY_P3_NORMAL"],
                evidence=["Estimated loss INR 64200.00 >= INR 50000.00 threshold"],
                policy_rule_refs=["IN-IRDAI-MC-2024:1.0.0"],
                confidence=Decimal("0.940"),
                confidence_band="high",
                explanation="Mandatory IRDAI survey triggered because claimed loss exceeds INR 50,000.",
                alternatives_considered=["low_risk_od_assisted (excluded >= 50k)"],
            ),
            DecisionRecord(
                tenant_id=t1.id,
                claim_id=c1.id,
                agent_name="estimate_validation",
                stage="4. Assessment",
                decision_id="dec-seed-est-01",
                routing_outcome="hold_anomalies_flagged",
                reason_codes=["RC_RATE_CARD_BENCHMARKED", "RC_DUPLICATE_LINE", "RC_RATE_VARIANCE"],
                evidence=["Claimed INR 64200.00 vs Recommended INR 48700.00 (2 anomalies)"],
                policy_rule_refs=["RATE_CARD:RC-IN-2026-DEMO-V1"],
                confidence=Decimal("0.740"),
                confidence_band="medium",
                explanation="Flagged duplicate bumper part and +38.5% fender variance for adjuster sign-off.",
                alternatives_considered=["silently_overwrite_garage_quote (prohibited)"],
            ),
        ]
    )
    emit_outbox_event(
        db,
        tenant_id=t1.id,
        aggregate_id=c1.id,
        event_type="ClaimCreated",
        payload={"claim_number": c1.claim_number, "synthetic": True},
        idempotency_key="seed-c1-created",
    )
    db.add(
        OrchestrationEventLog(
            tenant_id=t1.id,
            claim_id=c1.id,
            event_id="evt-seed-fnol-0001",
            event_type="FNOLSubmitted",
            source="web",
            payload={"claim_number": c1.claim_number},
            processing_status="processed",
            resulting_state="REGISTERED",
        )
    )
    db.add(
        DeadLetterRecord(
            tenant_id=t1.id,
            claim_id="clm-demo-0006",
            task_key="provider_coordination",
            agent_or_service="provider_coordination",
            state_at_failure="SURVEY_ASSIGNED",
            error_code="ORCH_SURVEY_SLA_TIMEOUT",
            failure_reason="Surveyor reminder webhook timed out after 3 exponential-backoff retries (200ms, 400ms, 800ms).",
            attempt_count=3,
            retry_history=[
                {"attempt": 1, "status": "timed_out", "backoff_delay_ms": 200, "backoff_formula": "200 * 2.0^0"},
                {"attempt": 2, "status": "timed_out", "backoff_delay_ms": 400, "backoff_formula": "200 * 2.0^1"},
                {"attempt": 3, "status": "timed_out", "backoff_delay_ms": 800, "backoff_formula": "200 * 2.0^2"},
            ],
            payload={"claim_number": "CLM-DEMO-2026-0006"},
            status="open",
        )
    )

    stl12 = Settlement(
        id="stl-demo-0012",
        tenant_id=t1.id,
        claim_id="clm-demo-0012",
        pathway="cashless",
        gross_assessed_inr=Decimal("16500.00"),
        depreciation_deduction_inr=Decimal("0.00"),
        compulsory_excess_inr=Decimal("1000.00"),
        addon_waiver_inr=Decimal("2100.00"),
        net_payable_inr=Decimal("15500.00"),
        approval_status="approved",
        created_by="system:fast_track_engine",
    )
    db.add(stl12)
    db.flush()

    for clm_obj in db.query(Claim).all():
        evaluate_and_persist_risk(
            db,
            clm_obj,
            trigger_event="initial_seed_classification",
            actor_id="system-seed",
            actor_role="system",
            record_decision=False,
            escalate_state=False,
        )

    # Seed realistic dynamic transition histories for clm-demo-0008 (HIGH -> LOW after SIU cleared) and clm-demo-0011 (LOW -> HIGH on EV BMS evidence)
    clm8 = db.query(Claim).filter(Claim.id == "clm-demo-0008").first()
    if clm8:
        clm8.risk_history = [
            {
                "event_id": "rsk-seed-0008-1",
                "trigger_event": "fraud_checks_evaluated",
                "previous_tier": "MEDIUM",
                "new_tier": "HIGH",
                "previous_path": "standard",
                "new_path": "complex_investigation",
                "previous_score": 40,
                "new_score": 90,
                "fraud_signal_score": "0.648",
                "driver_codes": ["HIGH_SUSPECTED_FRAUD"],
                "explanation": "Early policy inception (6 days) escalated claim to HIGH risk SIU investigation; fraud score NEVER auto-rejects.",
                "timestamp": (now - timedelta(days=2)).isoformat(),
            },
            *(clm8.risk_history or []),
        ]

    # Seed rich Damage AI reports on clm-demo-0004 (recapture), clm-demo-0007 (teardown uncertain), clm-demo-0011 (EV underbody)
    clm4 = db.query(Claim).filter(Claim.id == "clm-demo-0004").first()
    if clm4:
        clm4.damage_report = assess_damage_from_evidence(
            claim_description="Front bumper shadowed corner impact; uncertain mounting tab condition.",
            is_ev=False,
            ev_battery_impacted=False,
            image_records=[{"id": "ev-0004-blur", "filename": "dark_blurry_front.jpg", "image_angle": "front", "image_quality_status": "recapture_needed", "sha256": "blurry_demo_hash_004"}],
            vehicle_info={"make": veh1.make, "model": veh1.model, "variant": "Alpha AGS", "year": veh1.year, "registration_number": veh1.registration_number, "is_ev": False},
        )
    clm7 = db.query(Claim).filter(Claim.id == "clm-demo-0007").first()
    if clm7:
        r7 = assess_damage_from_evidence(
            claim_description="Front bumper shadow partial occlusion & hidden radiator core support deformation discovered during bonnet teardown.",
            is_ev=False,
            ev_battery_impacted=False,
            image_records=[{"id": "ev-0007-front", "filename": "front_daylight_teardown.jpg", "image_angle": "front", "image_quality_status": "acceptable", "sha256": "demo_hash_0007_front"}],
            vehicle_info={"make": veh1.make, "model": veh1.model, "variant": "Alpha AGS", "year": veh1.year, "registration_number": veh1.registration_number, "is_ev": False},
        )
        clm7.damage_report = r7
        for obs in r7["observations"]:
            cost = obs.get("estimated_cost", {})
            db.add(
                DamageAssessment(
                    tenant_id=t1.id,
                    claim_id=clm7.id,
                    component_name=obs["component_name"],
                    part_code=obs.get("part_code"),
                    damage_location=obs["damage_location"],
                    damage_severity=obs["damage_severity"],
                    repairability=obs["repairability"],
                    damage_class=obs["damage_class"],
                    observation_type=obs["observation_type"],
                    recommended_action=obs["recommended_action"],
                    visible_damage=obs["visible_damage"],
                    possible_hidden_damage=obs["possible_hidden_damage"],
                    image_quality=obs["image_quality"],
                    confidence=Decimal(str(obs["component_confidence"])),
                    confidence_factors=obs["confidence_factors"],
                    evidence_refs=obs.get("evidence", []),
                    estimated_parts_inr=Decimal(str(cost.get("parts_oem_inr", "0.00"))),
                    estimated_labour_inr=Decimal(str(cost.get("labour_inr", "0.00"))),
                    estimated_paint_inr=Decimal(str(cost.get("paint_inr", "0.00"))),
                    limitations=obs["limitations"],
                    reviewer_outcome="pending",
                    model_version=r7["model_version"],
                )
            )

    clm11 = db.query(Claim).filter(Claim.id == "clm-demo-0011").first()
    if clm11:
        clm11.damage_report = assess_damage_from_evidence(
            claim_description=clm11.incident_description,
            is_ev=True,
            ev_battery_impacted=True,
            image_records=[
                {"id": "ev-0011-front", "filename": "ev_front_left.jpg", "image_angle": "front", "image_quality_status": "acceptable", "sha256": "demo_hash_0011_front"},
                {"id": "ev-0011-under", "filename": "ev_underbody_shadow.jpg", "image_angle": "underbody", "image_quality_status": "poor", "sha256": "demo_hash_0011_under"},
            ],
            vehicle_info={"make": veh_ev.make, "model": veh_ev.model, "variant": "Empowered+ LR", "year": veh_ev.year, "registration_number": veh_ev.registration_number, "is_ev": True, "fuel_type": "electric"},
        )
        clm11.risk_history = [
            {
                "event_id": "rsk-seed-0011-1",
                "trigger_event": "fnol_intake",
                "previous_tier": None,
                "new_tier": "LOW",
                "previous_path": None,
                "new_path": "fast_track",
                "previous_score": 0,
                "new_score": 12,
                "fraud_signal_score": "0.000",
                "driver_codes": ["LOW_FAST_TRACK_ELIGIBLE"],
                "explanation": "Initial pothole scrape report started as LOW RISK before underbody EV traction battery HV isolation alert arrived.",
                "timestamp": (now - timedelta(days=1, hours=4)).isoformat(),
            },
            *(clm11.risk_history or []),
        ]

    # Seed EcosystemCoordination state for demo claims
    db.add_all(
        [
            EcosystemCoordination(
                id="eco-seed-0001",
                tenant_id=t1.id,
                claim_id="clm-demo-0001",
                surveyor_id=surv1.id,
                surveyor_license_verified=True,
                surveyor_license_checked_at=now - timedelta(days=1),
                surveyor_selection_explanation=(
                    "Selected R. K. Sharma & Associates (score 93.6/100) based on geography (zone_exact_match in Andheri, Mumbai), "
                    "skills (oem_maruti), capacity (Low: 3/12), SLA (Within SLA), and rating (4.8/5.0)."
                ),
                surveyor_score_breakdown={"total_score": 93.6, "breakdown": {"geography_score": 30, "skill_score": 25, "capacity_score": 15, "sla_score": 15, "rating_score": 9.6}},
                garage_id=gar1.id,
                customer_preferred_garage_id=gar1.id,
                customer_preference_honoured=True,
                override_applied=False,
                garage_selection_explanation=(
                    "Honoured customer-preferred garage Garage A — Apex Motors Cashless Hub (score 92.4/100: zone_exact_match in Andheri, "
                    "load Low 5/20, SLA Within SLA, rating 4.7/5.0)."
                ),
                garage_score_breakdown={"total_score": 92.4, "breakdown": {"geography_score": 30, "skill_score": 25, "capacity_score": 15, "sla_score": 15, "rating_score": 9.4}},
                inspection_status="completed",
                inspection_scheduled_at=now - timedelta(days=1, hours=6),
                towing_required=False,
                towing_status="not_required",
                pickup_delivery_status="at_garage",
                pickup_scheduled_at=now - timedelta(days=1, hours=10),
                parts_status="all_available",
                parts_availability=[
                    {"part_code": "PRT-FRT-BMP-01", "description": "Front Bumper Assembly", "availability": "in_stock", "eta_days": 1, "source": "Garage A Stock"},
                    {"part_code": "PRT-HDL-RH-01", "description": "RH LED Headlamp Assembly", "availability": "in_stock", "eta_days": 1, "source": "Garage A Stock"},
                ],
                repair_status="teardown_in_progress",
                repair_milestones=[
                    {"milestone": "intake_confirmed", "notes": "Vehicle checked in at Andheri Hub", "actor": "Apex Motors Advisor (garage)", "timestamp": (now - timedelta(days=1, hours=8)).isoformat()},
                    {"milestone": "teardown_in_progress", "notes": "Bumper & headlamp estimate lines benchmarked", "actor": "Apex Motors Advisor (garage)", "timestamp": (now - timedelta(hours=12)).isoformat()},
                ],
                surveyor_followup_status="report_received",
                customer_notifications=[
                    {"event": "ECOSYSTEM_COORDINATED", "channel": "whatsapp", "message": "Garage A & Surveyor R. K. Sharma scheduled.", "sent_at": (now - timedelta(days=1, hours=12)).isoformat()}
                ],
                contractual_compliance={"irdai_iiisla_verified": True, "ev_hv_safety_enforced": True, "cashless_network_enforced": True, "customer_preference_protected": True},
                coordination_explanation="Honoured customer choice (Garage A) + lowest-load verified Mumbai IIISLA surveyor within SLA.",
            ),
            EcosystemCoordination(
                id="eco-seed-0006",
                tenant_id=t1.id,
                claim_id="clm-demo-0006",
                surveyor_id=surv1.id,
                surveyor_license_verified=True,
                surveyor_license_checked_at=now - timedelta(days=16),
                surveyor_selection_explanation="Selected R. K. Sharma & Associates (verified IIISLA, Mumbai).",
                garage_id=gar_busy.id,
                customer_preferred_garage_id=gar_busy.id,
                customer_preference_honoured=True,
                garage_selection_explanation="Honoured customer-preferred Garage B (Thane); currently high load / delayed SLA.",
                inspection_status="rescheduled",
                inspection_scheduled_at=now - timedelta(days=10),
                inspection_reschedule_count=1,
                inspection_reschedule_reason="Garage bay availability shifted due to backlog",
                parts_status="partial_backorder",
                parts_availability=[
                    {"part_code": "PRT-FND-RH-01", "description": "Fender Panel", "availability": "in_stock", "eta_days": 2, "source": "Garage B Stock"},
                    {"part_code": "PRT-RAD-SUP-01", "description": "Radiator Core Support", "availability": "backordered", "eta_days": 5, "source": "OEM Warehouse"},
                ],
                repair_status="awaiting_parts",
                surveyor_followup_count=2,
                last_surveyor_followup_at=now - timedelta(hours=6),
                surveyor_followup_status="escalated_sla",
                customer_notifications=[
                    {"event": "SURVEYOR_FOLLOWUP_SENT", "channel": "whatsapp", "message": "15-day IRDAI SLA escalation active for surveyor report.", "sent_at": (now - timedelta(hours=6)).isoformat()}
                ],
                contractual_compliance={"irdai_iiisla_verified": True, "ev_hv_safety_enforced": True, "cashless_network_enforced": True, "customer_preference_protected": True},
                coordination_explanation="Active 15-day surveyor SLA breach follow-up & OEM parts backorder tracking.",
            ),
            EcosystemCoordination(
                id="eco-seed-0011",
                tenant_id=t1.id,
                claim_id="clm-demo-0011",
                surveyor_id=surv1.id,
                surveyor_license_verified=True,
                surveyor_license_checked_at=now - timedelta(hours=10),
                surveyor_selection_explanation="Selected EV-HV certified surveyor R. K. Sharma & Associates (Mumbai, Within SLA).",
                garage_id=gar_ev.id,
                customer_preferred_garage_id=gar1.id,
                customer_preference_honoured=False,
                override_applied=True,
                override_authorized=True,
                override_authorized_by="POL-WORDING-EV-2025:EV-SAFE-01",
                override_reason_code="RC_EV_SAFETY_CONTRACT_RULE",
                override_justification="EV traction battery HV impact requires EV-certified workshop.",
                garage_selection_explanation=(
                    "Contractual EV HV safety mandate (POL-WORDING-EV-2025:EV-SAFE-01) redirected non-EV Garage A "
                    "to VoltCare OEM EV Specialist Centre (rating 4.9/5.0, EV HV certified)."
                ),
                inspection_status="scheduled",
                inspection_scheduled_at=now + timedelta(hours=6),
                towing_required=True,
                towing_status="dispatched",
                towing_provider_id=tow1.id,
                towing_ev_flatbed=True,
                pickup_delivery_status="pickup_scheduled",
                pickup_scheduled_at=now + timedelta(hours=2),
                parts_status="partial_backorder",
                parts_availability=[
                    {"part_code": "PRT-EV-PACK-01", "description": "EV High-Voltage Battery Tray & Coolant Guard", "availability": "ordered_oem", "eta_days": 3, "source": "OEM Warehouse"},
                ],
                repair_status="intake_confirmed",
                customer_notifications=[
                    {"event": "ECOSYSTEM_COORDINATED", "channel": "whatsapp", "message": "EV Flatbed recovery dispatched to VoltCare OEM EV Specialist Centre.", "sent_at": (now - timedelta(hours=5)).isoformat()}
                ],
                contractual_compliance={"irdai_iiisla_verified": True, "ev_hv_safety_enforced": True, "cashless_network_enforced": True, "customer_preference_protected": True},
                coordination_explanation="EV HV safety rule enforced with flatbed recovery & OEM EV workshop.",
            ),
            EcosystemCoordination(
                id="eco-seed-0009",
                tenant_id=t1.id,
                claim_id="clm-demo-0009",
                surveyor_id=surv1.id,
                surveyor_license_verified=True,
                surveyor_selection_explanation="Verified Mumbai IIISLA surveyor completed inspection.",
                garage_id=gar1.id,
                customer_preferred_garage_id=gar1.id,
                customer_preference_honoured=True,
                garage_selection_explanation="Honoured customer-preferred Garage A — Apex Motors Cashless Hub.",
                inspection_status="completed",
                pickup_delivery_status="delivered",
                parts_status="all_available",
                repair_status="repair_completed",
                repair_completion_confirmed=True,
                repair_confirmed_by="Apex Motors Advisor (garage)",
                repair_confirmed_at=now - timedelta(hours=4),
                surveyor_followup_status="report_received",
                contractual_compliance={"irdai_iiisla_verified": True, "ev_hv_safety_enforced": True, "cashless_network_enforced": True, "customer_preference_protected": True},
                coordination_explanation="Repair completion confirmed & vehicle delivered.",
            ),
        ]
    )

    db.flush()
    _seed_tp_liability_case(db, t1.id)
    _seed_ev_claim_case(db, t1.id)
    _seed_sla_scenarios(db, t1.id, now)

    db.commit()


def _seed_tp_liability_case(db: Session, tenant_id: str) -> None:
    """CLM-DEMO-2026-0010: a Third-Party bodily-injury claim worked through the dedicated TP lifecycle (IN-TP-LIABILITY-2026)."""
    from packages.security.auth import Role, UserContext
    from services.claims.models import Claim as _Claim
    from services.workflow import tp_liability as tp

    claim = db.query(_Claim).filter(_Claim.id == "clm-demo-0010").first()
    if not claim:
        return
    handler = UserContext(user_id="usr-handler", tenant_id=tenant_id, email="handler@demo.in", name="Vikram Mehta (Claims Handler)", role=Role.CLAIMS_HANDLER)
    case = tp.open_tp_case(db, claim, handler, tp_category="bodily_injury")
    tp.add_third_party(
        db,
        case,
        handler,
        role="injured",
        name="Suresh Patil (Injured Claimant)",
        contact="+91 98765 41199",
        vehicle_reg="MH12DEMO7788",
        injury_severity="grievous",
        claimant_demand_inr=Decimal("1800000.00"),
        notes="Two-wheeler rider; fracture of left femur, hospitalised. DEMO / SYNTHETIC.",
    )
    tp.add_third_party(db, case, handler, role="claimant", name="Meena Patil (Spouse, authorised claimant)", contact="+91 98765 41200")
    db.flush()
    tp.record_accident_facts(
        db,
        case,
        handler,
        narrative="Insured private car and a two-wheeler collided on NH-48 near Khalapur toll; rider thrown and injured. Both drivers dispute right of way.",
        evidence=[
            {"kind": "spot_panchnama", "description": "Police spot panchnama copy", "source": "Khalapur Police Station"},
            {"kind": "video_cctv", "description": "Toll-plaza CCTV clip requested (legal hold applied)", "source": "NH-48 toll operator"},
        ],
    )
    tp.record_police_report(
        db,
        case,
        handler,
        fir_number="FIR-441/2026",
        police_station="Khalapur PS (DEMO)",
        fir_date=claim.incident_at,
        sections_invoked=["BNS rash driving (illustrative)"],
        dar_status="pending",
    )
    for stage_note in ("Intake complete", "Facts and evidence preserved", "FIR on file"):
        tp.advance_stage(db, case, claim, handler, note=stage_note)



def _seed_sla_scenarios(db: Session, tenant_id: str, now: datetime) -> None:
    """DEMO / SYNTHETIC claims with backdated events so the predictive SLA dashboard has real signal.

    All scenarios sit in Nagpur with dedicated partners so they never compete with the Mumbai/Pune/Bengaluru
    provider-selection demos. Timestamps are relative to ``now`` so the scenarios stay fresh after every reseed.
    """
    from services.claims.models import Approval, Communication

    pol = db.query(Policy).filter(Policy.tenant_id == tenant_id).first()
    if pol is None:
        return
    base = {
        "tenant_id": tenant_id,
        "policy_id": pol.id,
        "customer_id": pol.customer_id,
        "vehicle_id": pol.vehicle_id,
        "policy_number_input": pol.policy_number,
        "vehicle_reg_input": "MH31DEMO0101",
        "incident_location": "Wardha Road, Nagpur",
        "assigned_handler_id": "usr-handler",
    }
    hrs = lambda h: now - timedelta(hours=h)  # noqa: E731

    surv_busy = Provider(
        id="prov-surv-sla-01", tenant_id=tenant_id, provider_type="surveyor", name="Nagpur Loss Assessors (IIISLA-DEMO-5501)",
        licence_or_contract_id="IRDAI-SLA-DEMO-5501", licence_status="verified", licence_expiry_at=now + timedelta(days=300),
        city="Nagpur", service_zones=["Nagpur", "Wardha Road"], skills=["oem_maruti"], active_load=9, max_capacity=10,
        sla_target_hours=24, sla_status="at_risk", avg_turnaround_hours=32, quality_score=Decimal("4.10"), is_available=True,
    )
    surv_free = Provider(
        id="prov-surv-sla-02", tenant_id=tenant_id, provider_type="surveyor", name="Vidarbha Surveyors LLP (IIISLA-DEMO-5502)",
        licence_or_contract_id="IRDAI-SLA-DEMO-5502", licence_status="verified", licence_expiry_at=now + timedelta(days=320),
        city="Nagpur", service_zones=["Nagpur", "Hingna"], skills=["oem_maruti", "oem_tata"], active_load=3, max_capacity=10,
        sla_target_hours=24, sla_status="within_sla", avg_turnaround_hours=18, quality_score=Decimal("4.60"), is_available=True,
    )
    gar_slow = Provider(
        id="prov-gar-sla-01", tenant_id=tenant_id, provider_type="garage", name="Orange City Auto Works (Nagpur DEMO)",
        licence_or_contract_id="GAR-NET-NAG-201", licence_status="verified", licence_expiry_at=now + timedelta(days=400),
        city="Nagpur", service_zones=["Nagpur", "Wardha Road"], skills=["bodyshop", "oem_maruti"], is_network=True,
        contract_tier="preferred_network", active_load=18, max_capacity=20, sla_target_hours=24, sla_status="delayed",
        avg_turnaround_hours=40, quality_score=Decimal("4.00"), parts_stock_status="low", parts_lead_time_days=5, is_available=True,
    )
    gar_free = Provider(
        id="prov-gar-sla-02", tenant_id=tenant_id, provider_type="garage", name="Vidarbha Motors Cashless Hub (Nagpur DEMO)",
        licence_or_contract_id="GAR-NET-NAG-202", licence_status="verified", licence_expiry_at=now + timedelta(days=400),
        city="Nagpur", service_zones=["Nagpur", "Hingna"], skills=["bodyshop", "oem_maruti", "oem_tata"], is_network=True,
        contract_tier="preferred_network", active_load=4, max_capacity=20, sla_target_hours=24, sla_status="within_sla",
        avg_turnaround_hours=18, quality_score=Decimal("4.60"), parts_stock_status="in_stock", parts_lead_time_days=1, is_available=True,
    )
    db.add_all([surv_busy, surv_free, gar_slow, gar_free])
    db.flush()

    def claim(num: int, status: str, queue: str, created_h: float, *, claim_type: str = "own_damage", tier: str = "MEDIUM", **extra: object) -> Claim:
        c = Claim(
            id=f"clm-sla-{num:04d}", claim_number=f"CLM-DEMO-2026-{num:04d}", claim_type=claim_type, status=status, queue_name=queue,
            risk_tier=tier, incident_at=hrs(created_h + 6), incident_description="DEMO / SYNTHETIC SLA scenario claim.",
            created_at=hrs(created_h), updated_at=hrs(created_h), triage_summary={"seeded_sla_scenario": True}, **base, **extra,  # type: ignore[arg-type]
        )
        db.add(c)
        db.flush()
        return c

    def settlement(c: Claim, created_h: float, *, approved: bool = False) -> Settlement:
        st = Settlement(
            tenant_id=tenant_id, claim_id=c.id, gross_assessed_inr=Decimal("42000.00"), depreciation_deduction_inr=Decimal("4200.00"),
            compulsory_excess_inr=Decimal("1000.00"), net_payable_inr=Decimal("36800.00"), created_by="usr-handler",
            approval_status="approved" if approved else "pending_maker", created_at=hrs(created_h),
        )
        db.add(st)
        db.flush()
        return st

    def estimate(c: Claim, created_h: float, garage_id: str, status: str = "submitted") -> None:
        db.add(Estimate(tenant_id=tenant_id, claim_id=c.id, garage_id=garage_id, version=1, status=status,
                        total_claimed_inr=Decimal("42000.00"), total_approved_inr=Decimal("0.00"), anomalies=[], created_at=hrs(created_h)))

    # S1: survey about to breach: overloaded surveyor, 2 unanswered follow-ups, a reschedule, and no inspection slot yet.
    c1 = claim(101, "SURVEY_ASSIGNED", "standard_survey_queue", 150, tier="HIGH")
    db.add(SurveyAssignment(
        tenant_id=tenant_id, claim_id=c1.id, surveyor_id=surv_busy.id, status="assigned", assigned_at=hrs(132), notified_at=hrs(132),
        report_due_at=hrs(132) + timedelta(days=15), followup_count=2, last_followup_at=hrs(30), reschedule_count=1,
    ))

    # S2: surveyor assignment already breached (6h rule, triaged 9h ago, still no surveyor).
    claim(102, "SURVEY_REQUIRED", "standard_survey_queue", 9)

    # S3: cashless repair stalled by parts at a slow, non-customer-chosen garage.
    c3 = claim(103, "REPAIR_IN_PROGRESS", "garage_repair", 260, claim_type="cashless")
    settlement(c3, 170)
    db.add(EcosystemCoordination(
        tenant_id=tenant_id, claim_id=c3.id, surveyor_id=surv_free.id, garage_id=gar_slow.id, customer_preferred_garage_id=None,
        inspection_status="completed", parts_status="awaiting_parts", repair_status="awaiting_parts",
        coordination_explanation="DEMO / SYNTHETIC: parts backorder at Orange City Auto Works.",
    ))

    # S4: same slow garage, but it is the customer's own choice: reassignment must NOT be offered.
    c4 = claim(104, "REPAIR_IN_PROGRESS", "garage_repair", 200, claim_type="cashless")
    settlement(c4, 130)
    db.add(EcosystemCoordination(
        tenant_id=tenant_id, claim_id=c4.id, surveyor_id=surv_free.id, garage_id=gar_slow.id,
        customer_preferred_garage_id=gar_slow.id, customer_preference_honoured=True, inspection_status="completed",
        parts_status="awaiting_parts", repair_status="body_paint_in_progress",
        coordination_explanation="DEMO / SYNTHETIC: customer-chosen garage with slow turnaround.",
    ))

    # S5: documents owed for 80h; customer clock paused, request is stale.
    c5 = claim(105, "EVIDENCE_PENDING", "document_exception", 90, missing_documents=["Registration Certificate (RC)", "FIR copy"])
    db.add(ClaimTask(
        tenant_id=tenant_id, claim_id=c5.id, task_type="document_request", title="Collect missing evidence: RC, FIR copy",
        assigned_role="policyholder", created_by_agent="document_intelligence", priority="high", status="open",
        reason_code="DOCUMENTS_REQUESTED", due_at=hrs(32), created_at=hrs(80),
    ))
    db.add(Communication(
        tenant_id=tenant_id, claim_id=c5.id, channel="whatsapp", template_id="DOCUMENT_REQUEST", subject="Action Needed: Upload Documents",
        body="Please upload: Registration Certificate (RC), FIR copy.", delivery_status="sent_mock", created_at=hrs(80),
    ))
    db.add(Evidence(
        tenant_id=tenant_id, claim_id=c5.id, doc_type="damage_photo", doc_status="extracted_unverified", filename="front_left.jpg",
        mime_type="image/jpeg", size_bytes=120_000, sha256="5" * 64, storage_path="synthetic/front_left.jpg", uploader_user_id="usr-policyholder",
        created_at=hrs(88),
    ))

    # S6-S8: estimate review pile-up (3 clocks at 75-90% of a 48h SLA in one queue) -> queue bottleneck.
    for num, age_h in ((106, 38), (107, 42), (108, 36)):
        cx = claim(num, "ESTIMATE_REVIEW", "estimate_review_queue", age_h + 24, claim_type="cashless")
        estimate(cx, age_h, gar_free.id)
        db.add(ClaimTask(
            tenant_id=tenant_id, claim_id=cx.id, task_type="estimate_review", title="Review garage estimate", assigned_role="claims_handler",
            created_by_agent="estimate_validation", priority="medium", status="open", reason_code="ESTIMATE_REVIEW", due_at=hrs(age_h - 24), created_at=hrs(age_h),
        ))

    # S9-S10: completed claims so attainment and cycle-time statistics have a baseline (one met, one late survey).
    # Timeline in "hours ago": created -> surveyor assigned (+5h) -> report (+survey_hours) -> estimate (+4h)
    # -> estimate approved/settlement (+20h) -> settlement approved (+10h) -> repair done (+20h) -> payment (+10h more) -> closed (+30h).
    for num, survey_hours, base_h in ((109, 60, 600), (110, 210, 700)):
        cc = claim(num, "CLOSED", "closure_qa", base_h, claim_type="cashless")
        assigned_ago = base_h - 5
        report_ago = assigned_ago - survey_hours
        est_ago = report_ago - 4
        settled_ago = est_ago - 20
        approved_ago = settled_ago - 10
        repair_ago = approved_ago - 20
        paid_ago = approved_ago - 20
        closed_ago = paid_ago - 30
        db.add(SurveyAssignment(
            tenant_id=tenant_id, claim_id=cc.id, surveyor_id=surv_free.id, status="report_received", assigned_at=hrs(assigned_ago),
            notified_at=hrs(assigned_ago), report_due_at=hrs(assigned_ago) + timedelta(days=15), report_received_at=hrs(report_ago), signed_by_surveyor=True,
        ))
        estimate(cc, est_ago, gar_free.id, status="approved")
        st = settlement(cc, settled_ago, approved=True)
        db.add(Approval(tenant_id=tenant_id, claim_id=cc.id, settlement_id=st.id, action_type="settlement_approval", amount_inr=Decimal("36800.00"),
                        maker_user_id="usr-handler", checker_user_id="usr-manager", decision="approved", decided_at=hrs(approved_ago), created_at=hrs(approved_ago)))
        db.add(Payment(tenant_id=tenant_id, claim_id=cc.id, settlement_id=st.id, idempotency_key=f"pay-sla-{num}", payee_type="garage",
                       payee_name="Vidarbha Motors Cashless Hub", bank_account_masked="XXXX1234", bank_verified=True, amount_inr=Decimal("36800.00"),
                       status="confirmed", approved_by_finance_id="usr-finance", created_at=hrs(paid_ago)))
        db.add(EcosystemCoordination(
            tenant_id=tenant_id, claim_id=cc.id, surveyor_id=surv_free.id, garage_id=gar_free.id, inspection_status="completed",
            parts_status="all_available", repair_status="handover_confirmed", repair_completion_confirmed=True,
            repair_confirmed_at=hrs(repair_ago), repair_confirmed_by="garage",
        ))
        cc.updated_at = hrs(closed_ago)
    db.flush()


def _seed_ev_claim_case(db: Session, tenant_id: str) -> None:
    """CLM-DEMO-2026-0011: an EV underbody strike worked through the dedicated EV lifecycle (IN-EV-CLAIMS-2026)."""
    from packages.security.auth import Role, UserContext
    from services.claims.models import Claim as _Claim
    from services.workflow import ev_claims as evw

    claim = db.query(_Claim).filter(_Claim.id == "clm-demo-0011").first()
    if not claim:
        return
    handler = UserContext(user_id="usr-handler", tenant_id=tenant_id, email="handler@demo.in", name="Vikram Mehta (Claims Handler)", role=Role.CLAIMS_HANDLER)
    surveyor = UserContext(user_id="usr-surveyor", tenant_id=tenant_id, email="surveyor@demo.in", name="R. K. Sharma (Surveyor)", role=Role.SURVEYOR, partner_id="prov-surv-01")
    case = evw.open_ev_case(db, claim, handler, system_initiated=True)
    evw.record_triage(
        db,
        case,
        claim,
        handler,
        signals=["underbody_impact", "hv_warning_light", "coolant_leak_near_pack", "loss_of_drive_power"],
        notes="Stone strike on the pack underbody shield; HV warning lit on the dash. Customer says the car 'still moves' - not accepted as clearance. DEMO / SYNTHETIC.",
        customer_declared_drivable=True,
        vehicle_location="BKC, Mumbai",
    )
    db.flush()
    manager = UserContext(user_id="usr-manager", tenant_id=tenant_id, email="manager@demo.in", name="Sunita Iyer (Claims Manager)", role=Role.CLAIMS_MANAGER)
    urgent_ids = [e["id"] for e in evw.open_escalations(case)]
    for esc_id in urgent_ids:
        evw.acknowledge_safety_escalation(db, case, manager, escalation_id=esc_id, actions_taken="EV flatbed recovery dispatched; customer told not to drive, charge or touch orange cables.")
    evw.advance_stage(db, case, claim, handler, note="Triage confirmed; HV hold applied")
    evw.record_recovery(
        db,
        case,
        claim,
        handler,
        provider_id="prov-tow-01",
        tow_method="flatbed",
        hv_isolation_method="Service disconnect removed by EV-certified technician; 12V isolated",
        hv_isolation_verified=True,
        quarantine_location="Open-air quarantine bay B3, VoltCare OEM EV Specialist Centre",
        quarantine_clearance_m=Decimal("8"),
        notes="Flatbed recovery; vehicle never driven after the event.",
    )
    for esc_id in urgent_ids:
        evw.resolve_safety_escalation(
            db, case, claim, manager, escalation_id=esc_id,
            resolution="Vehicle flatbedded to the EV centre and the HV system isolated; no thermal indicators on arrival.",
            evidence_ref="ISOLATION-LOG-EV-0011", thermal_stable_confirmed=False,
        )
    evw.advance_stage(db, case, claim, handler, note="Recovered and isolated")
    evw.record_specialist_survey(
        db,
        case,
        claim,
        surveyor,
        surveyor_provider_id="prov-surv-01",
        inspection_mode="physical_on_lift",
        hv_isolation_verified=True,
        pack_findings=["Underbody shield cracked with a 40 mm indentation over the pack tray", "Coolant weep at the left pack coolant port"],
        hv_system_findings=["Orange HV harness clips displaced; no insulation breach visible"],
        charging_system_findings=["Charge port intact"],
        thermal_indicators_observed=False,
        pack_removal_required=True,
        report_ref="SURV-EV-2026-0011-A",
        notes="Physical inspection on lift. Pack condition still requires OEM diagnostics.",
    )
    evw.advance_stage(db, case, claim, handler, note="Specialist survey on file")
