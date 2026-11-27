from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from services.claims.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    jurisdiction: Mapped[str] = mapped_column(String(16), default="IN")
    is_synthetic_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(64), index=True)
    partner_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    branch: Mapped[str] = mapped_column(String(64), default="MUM-WEST")
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    phone_token: Mapped[str] = mapped_column(String(64), index=True)
    phone_masked: Mapped[str] = mapped_column(String(32))
    email_masked: Mapped[str] = mapped_column(String(120))
    preferred_language: Mapped[str] = mapped_column(String(16), default="en-IN")
    consent_whatsapp: Mapped[bool] = mapped_column(Boolean, default=True)
    is_synthetic_demo: Mapped[bool] = mapped_column(Boolean, default=True)


class Vehicle(Base):
    __tablename__ = "vehicles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    registration_number: Mapped[str] = mapped_column(String(32), index=True)
    vin_chassis: Mapped[str] = mapped_column(String(64), index=True)
    engine_number: Mapped[str] = mapped_column(String(64))
    make: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(80))
    year: Mapped[int] = mapped_column(Integer)
    vehicle_category: Mapped[str] = mapped_column(String(40), default="private_car")
    fuel_type: Mapped[str] = mapped_column(String(24), default="petrol")
    is_ev: Mapped[bool] = mapped_column(Boolean, default=False)
    cc_class: Mapped[str] = mapped_column(String(40), default="private_car_under_1500cc")
    first_registration_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("customers.id"), index=True)
    vehicle_id: Mapped[str] = mapped_column(String(36), ForeignKey("vehicles.id"), index=True)
    policy_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    product_code: Mapped[str] = mapped_column(String(64))
    uin: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(32), default="V1")
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="active")
    idv_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    compulsory_deductible_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("1000.00"))
    voluntary_deductible_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    addons: Mapped[dict] = mapped_column(JSON, default=dict)
    endorsements: Mapped[list] = mapped_column(JSON, default=list)
    wording_doc_id: Mapped[str] = mapped_column(String(64), default="POL-WORDING-PC-2024")


class Provider(Base):
    __tablename__ = "providers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    provider_type: Mapped[str] = mapped_column(String(24), index=True)
    name: Mapped[str] = mapped_column(String(200))
    licence_or_contract_id: Mapped[str] = mapped_column(String(64))
    licence_status: Mapped[str] = mapped_column(String(32), default="verified")
    city: Mapped[str] = mapped_column(String(64))
    ev_capable: Mapped[bool] = mapped_column(Boolean, default=False)
    is_network: Mapped[bool] = mapped_column(Boolean, default=True)
    active_load: Mapped[int] = mapped_column(Integer, default=0)
    max_capacity: Mapped[int] = mapped_column(Integer, default=15)
    quality_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("4.50"))
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_claim_idempotency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    claim_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    policy_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("policies.id"), nullable=True)
    customer_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("customers.id"), nullable=True)
    vehicle_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("vehicles.id"), nullable=True)

    claim_type: Mapped[str] = mapped_column(String(32), default="own_damage")
    peril_cause: Mapped[str] = mapped_column(String(64), default="road_accident")
    intake_channel: Mapped[str] = mapped_column(String(32), default="web")
    status: Mapped[str] = mapped_column(String(40), default="INTIMATED", index=True)
    severity_band: Mapped[str] = mapped_column(String(24), default="medium")
    queue_name: Mapped[str] = mapped_column(String(64), default="fnol_intake", index=True)

    incident_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    incident_timezone: Mapped[str] = mapped_column(String(40), default="Asia/Kolkata")
    incident_location: Mapped[str] = mapped_column(String(240))
    incident_description: Mapped[str] = mapped_column(Text)

    policy_number_input: Mapped[str] = mapped_column(String(64))
    vehicle_reg_input: Mapped[str] = mapped_column(String(32))
    driver_name: Mapped[str] = mapped_column(String(120), default="")
    driver_licence_ref: Mapped[str] = mapped_column(String(64), default="")

    vehicle_immobile: Mapped[bool] = mapped_column(Boolean, default=False)
    airbags_deployed: Mapped[bool] = mapped_column(Boolean, default=False)
    injury_or_fatality: Mapped[bool] = mapped_column(Boolean, default=False)
    police_involved: Mapped[bool] = mapped_column(Boolean, default=False)
    towing_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    ev_battery_impacted: Mapped[bool] = mapped_column(Boolean, default=False)

    estimated_loss_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    requires_mandatory_survey: Mapped[bool] = mapped_column(Boolean, default=False)
    preferred_language: Mapped[str] = mapped_column(String(16), default="en-IN")

    assigned_handler_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    assigned_surveyor_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    assigned_garage_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    next_expected_action: Mapped[str] = mapped_column(String(200), default="Verify policy and upload documents")
    missing_documents: Mapped[list] = mapped_column(JSON, default=list)
    coverage_factsheet: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    triage_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    workflow_state: Mapped[dict] = mapped_column(JSON, default=dict)
    duplicate_candidate_claim_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    is_synthetic_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class ClaimParty(Base):
    __tablename__ = "claim_parties"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    party_role: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    contact_masked: Mapped[str] = mapped_column(String(80))
    is_restricted_tp_medical: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(64), default="unknown")
    doc_status: Mapped[str] = mapped_column(String(40), default="awaiting_verification")
    filename: Mapped[str] = mapped_column(String(240))
    mime_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(400))
    uploader_user_id: Mapped[str] = mapped_column(String(36))
    upload_source: Mapped[str] = mapped_column(String(40), default="web")
    malware_scan_status: Mapped[str] = mapped_column(String(24), default="clean")
    prompt_injection_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_version: Mapped[str] = mapped_column(String(32), default="ocr-stub-v1")
    ocr_text: Mapped[str] = mapped_column(Text, default="")
    image_angle: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    image_quality_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ExtractedFact(Base):
    __tablename__ = "extracted_facts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    evidence_id: Mapped[str] = mapped_column(String(36), ForeignKey("evidence.id"), index=True)
    field_name: Mapped[str] = mapped_column(String(80))
    extracted_value: Mapped[str] = mapped_column(String(300))
    verified_value: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.850"))
    page_number: Mapped[int] = mapped_column(Integer, default=1)
    bbox: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(32), default="unverified")
    verified_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)


class DamageAssessment(Base):
    __tablename__ = "damage_assessments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    evidence_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    component_name: Mapped[str] = mapped_column(String(120))
    part_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    damage_class: Mapped[str] = mapped_column(String(64))
    observation_type: Mapped[str] = mapped_column(String(32), default="visible_observed")
    recommended_action: Mapped[str] = mapped_column(String(32), default="repair")
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.820"))
    limitations: Mapped[str] = mapped_column(String(300), default="Assistive visual check only; hidden internal damage requires physical survey.")
    reviewer_outcome: Mapped[str] = mapped_column(String(32), default="pending")
    reviewer_notes: Mapped[str] = mapped_column(Text, default="")
    model_version: Mapped[str] = mapped_column(String(48), default="cv-adapter-stub-v1")


class Estimate(Base):
    __tablename__ = "estimates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    garage_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_supplement: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="submitted")
    total_claimed_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    total_approved_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    anomalies: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class EstimateLine(Base):
    __tablename__ = "estimate_lines"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    estimate_id: Mapped[str] = mapped_column(String(36), ForeignKey("estimates.id"), index=True)
    part_code: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(200))
    part_category: Mapped[str] = mapped_column(String(64), default="metal")
    line_type: Mapped[str] = mapped_column(String(24), default="part")
    action: Mapped[str] = mapped_column(String(24), default="replace")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    rate_card_price_inr: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    approved_amount_inr: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    variance_flag: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    reviewer_status: Mapped[str] = mapped_column(String(24), default="pending")


class SurveyAssignment(Base):
    __tablename__ = "survey_assignments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    surveyor_id: Mapped[str] = mapped_column(String(36), ForeignKey("providers.id"))
    status: Mapped[str] = mapped_column(String(32), default="assigned")
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    notified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    appointment_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    report_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    report_received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    delay_reason: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    report_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    signed_by_surveyor: Mapped[bool] = mapped_column(Boolean, default=False)


class FraudAlert(Base):
    __tablename__ = "fraud_alerts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    indicator_code: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    severity_band: Mapped[str] = mapped_column(String(24), default="medium")
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.700"))
    evidence_summary: Mapped[str] = mapped_column(Text)
    benign_explanation: Mapped[str] = mapped_column(Text)
    recommended_action: Mapped[str] = mapped_column(String(240))
    entity_links: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="new")
    assigned_investigator_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    investigator_notes: Mapped[str] = mapped_column(Text, default="")
    disposition_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Settlement(Base):
    __tablename__ = "settlements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    pathway: Mapped[str] = mapped_column(String(32), default="cashless")
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    gross_assessed_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    depreciation_deduction_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    compulsory_excess_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    voluntary_excess_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    salvage_deduction_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    addon_waiver_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    net_payable_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    is_total_loss: Mapped[bool] = mapped_column(Boolean, default=False)
    calculation_trace: Mapped[list] = mapped_column(JSON, default=list)
    rule_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    policy_citations: Mapped[list] = mapped_column(JSON, default=list)
    approval_status: Mapped[str] = mapped_column(String(32), default="pending_maker")
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    settlement_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("settlements.id"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(40))
    amount_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    maker_user_id: Mapped[str] = mapped_column(String(36))
    checker_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    decision: Mapped[str] = mapped_column(String(32), default="pending")
    rationale: Mapped[str] = mapped_column(Text, default="")
    authority_rule_version: Mapped[str] = mapped_column(String(40), default="IN-DOA-MATRIX-2026:1.0.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_payment_idempotency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    settlement_id: Mapped[str] = mapped_column(String(36), ForeignKey("settlements.id"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    payee_type: Mapped[str] = mapped_column(String(24))
    payee_name: Mapped[str] = mapped_column(String(200))
    bank_account_masked: Mapped[str] = mapped_column(String(32))
    bank_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    amount_inr: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    status: Mapped[str] = mapped_column(String(32), default="initiated")
    gateway_reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    approved_by_finance_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SLATimer(Base):
    __tablename__ = "sla_timers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    stage: Mapped[str] = mapped_column(String(64))
    start_event: Mapped[str] = mapped_column(String(64))
    stop_event: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    pause_reason: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="on_track")
    owner_role: Mapped[str] = mapped_column(String(40), default="claims_handler")
    daily_penalty_inr: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))


class Communication(Base):
    __tablename__ = "communications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    channel: Mapped[str] = mapped_column(String(24), default="email")
    language: Mapped[str] = mapped_column(String(16), default="en-IN")
    template_id: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(String(240))
    body: Mapped[str] = mapped_column(Text)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(24), default="sent_mock")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Grievance(Base):
    __tablename__ = "grievances"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    category: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="acknowledged")
    owner_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolution_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RuleVersion(Base):
    __tablename__ = "rule_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    rule_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32))
    jurisdiction: Mapped[str] = mapped_column(String(16), default="IN")
    title: Mapped[str] = mapped_column(String(200))
    source_reference: Mapped[str] = mapped_column(String(240))
    owner: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24), default="published")
    payload: Mapped[dict] = mapped_column(JSON)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    approved_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)


class AuditEvent(Base):
    """Append-only immutable audit and decision ledger."""
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    actor_role: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(80), index=True)
    object_type: Mapped[str] = mapped_column(String(64))
    object_id: Mapped[str] = mapped_column(String(64))
    before_hash: Mapped[str] = mapped_column(String(64), default="")
    after_hash: Mapped[str] = mapped_column(String(64), default="")
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    outcome: Mapped[str] = mapped_column(String(32), default="success")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class OutboxEvent(Base):
    """Transactional outbox for reliable enterprise event publishing & DLQ."""
    __tablename__ = "outbox_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    schema_version: Mapped[str] = mapped_column(String(16), default="1.0")
    correlation_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="published_mock")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ClaimTask(Base):
    """Actionable workflow task created by bounded action-taking agents or human adjusters."""

    __tablename__ = "claim_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    task_type: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    assigned_role: Mapped[str] = mapped_column(String(40), default="claims_handler")
    assigned_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_by_agent: Mapped[str] = mapped_column(String(64), default="orchestrator")
    priority: Mapped[str] = mapped_column(String(24), default="medium")
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    reason_code: Mapped[str] = mapped_column(String(64), default="TASK_CREATED")
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentExecutionRecord(Base):
    """Structured publication & orchestration execution log for every bounded agent run."""

    __tablename__ = "agent_execution_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    workflow_run_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    stage_order: Mapped[int] = mapped_column(Integer, default=1)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), index=True)
    dependencies_satisfied: Mapped[bool] = mapped_column(Boolean, default=True)
    depends_on: Mapped[list] = mapped_column(JSON, default=list)
    published_result: Mapped[dict] = mapped_column(JSON, default=dict)
    actions_executed: Mapped[list] = mapped_column(JSON, default=list)
    rework_requests: Mapped[list] = mapped_column(JSON, default=list)
    decision: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class DecisionRecord(Base):
    """First-class Decision Intelligence ledger recording evidence, rules, codes, and rationale."""

    __tablename__ = "decision_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    stage: Mapped[str] = mapped_column(String(64))
    decision_id: Mapped[str] = mapped_column(String(64), index=True)
    routing_outcome: Mapped[str] = mapped_column(String(80))
    reason_codes: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    policy_rule_refs: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.900"))
    confidence_band: Mapped[str] = mapped_column(String(16), default="high")
    explanation: Mapped[str] = mapped_column(Text, default="")
    alternatives_considered: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class OrchestrationTask(Base):
    """Scheduled DAG work unit owned exclusively by the Claim Orchestration Engine."""

    __tablename__ = "orchestration_tasks"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_orch_task_idempotency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    workflow_run_id: Mapped[str] = mapped_column(String(64), index=True)
    task_key: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    agent_or_service: Mapped[str] = mapped_column(String(64), index=True)
    execution_mode: Mapped[str] = mapped_column(String(24), default="sequential")
    parallel_group: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    depends_on: Mapped[list] = mapped_column(JSON, default=list)
    condition_expression: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    target_state: Mapped[str] = mapped_column(String(40), default="VALIDATION")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    backoff_delay_ms: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_history: Mapped[list] = mapped_column(JSON, default=list)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=15)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    input_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    output_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class OrchestrationEventLog(Base):
    """Inbound workflow event ledger enforcing duplicate-event protection per claim."""

    __tablename__ = "orchestration_events"
    __table_args__ = (UniqueConstraint("tenant_id", "claim_id", "event_id", name="uq_orch_event_dedup"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    event_id: Mapped[str] = mapped_column(String(100), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(64), default="api")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    processing_status: Mapped[str] = mapped_column(String(32), default="processed")
    resulting_state: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    duplicate_hits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class DeadLetterRecord(Base):
    """Dead-Letter Queue (DLQ) capturing exhausted tasks or poison workflow events for replay or compensation."""

    __tablename__ = "dead_letter_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    task_key: Mapped[str] = mapped_column(String(64))
    agent_or_service: Mapped[str] = mapped_column(String(64))
    state_at_failure: Mapped[str] = mapped_column(String(40))
    error_code: Mapped[str] = mapped_column(String(64), default="ORCH_RETRY_EXHAUSTED")
    failure_reason: Mapped[str] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_history: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class CompensationLog(Base):
    """Saga compensation ledger recording deterministic rollback/release steps on workflow failure or cancellation."""

    __tablename__ = "compensation_workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    trigger_reason: Mapped[str] = mapped_column(String(200))
    failed_state: Mapped[str] = mapped_column(String(40))
    compensating_action: Mapped[str] = mapped_column(String(80))
    target_object_type: Mapped[str] = mapped_column(String(64))
    target_object_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="executed")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
