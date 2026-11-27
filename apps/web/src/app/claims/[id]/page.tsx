"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AlertTriangle, Camera, CheckCircle2, Eye, ShieldAlert, Upload } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { ProvenanceBadge, RiskTierBadge, SlaBadge, StatusPill } from "@/components/Badges";
import { ClaimExecutionChain } from "@/components/ClaimExecutionChain";
import { MotorClaimTracker } from "@/components/MotorClaimTracker";

type TabId = "overview" | "customer_experience" | "orchestration" | "ecosystem" | "decisions" | "evidence" | "damage_estimate" | "siu" | "settlement" | "audit";

interface RiskDriver {
  code: string;
  tier: string;
  category: string;
  points: number;
  summary: string;
}

interface RiskAssessment {
  risk_tier: string;
  operational_path: string;
  operational_path_label: string;
  handling_mode: string;
  goal: string;
  risk_score: number;
  fraud_signal_score?: string | null;
  fraud_score_can_reject: boolean;
  fraud_guardrail_note?: string;
  rule_version: string;
  trigger_event: string;
  recalculated_at: string;
  drivers: RiskDriver[];
  low_risk_criteria_check: Record<string, boolean>;
  automation_eligibility: {
    straight_through_eligible: boolean;
    auto_approval_limit_inr: string;
    within_auto_approval_limit: boolean;
    fast_track_assisted_limit_inr: string;
    requires_mandatory_survey: boolean;
    evidence_preservation_active: boolean;
    recommended_queue: string;
    recommended_triage_track: string;
    routing_priority: string;
  };
  explanation: string;
}

interface RiskHistoryEntry {
  event_id: string;
  trigger_event: string;
  previous_tier?: string | null;
  new_tier: string;
  previous_path?: string | null;
  new_path: string;
  previous_score?: number | null;
  new_score: number;
  fraud_signal_score?: string | null;
  driver_codes: string[];
  explanation: string;
  timestamp: string;
}

interface DamageEvidenceRef {
  evidence_id?: string | null;
  filename: string;
  angle: string;
  location_hint?: string;
  image_quality: string;
  sha256_prefix?: string;
  region_label?: string;
  bbox?: {
    x: number;
    y: number;
    w: number;
    h: number;
    norm_x: number;
    norm_y: number;
    norm_w: number;
    norm_h: number;
  };
}

interface DamageReportObservation {
  damaged_component: string;
  component_name: string;
  part_code: string;
  part_category: string;
  damage_location: string;
  zone: string;
  damage_severity: string;
  repairability: string;
  recommended_action: string;
  observation_type: string;
  visible_damage: string;
  possible_hidden_damage: string;
  image_quality: string;
  confidence: number;
  component_confidence: number;
  confidence_band: string;
  confidence_factors?: {
    overall_image_quality?: number;
    component_image_quality?: string;
    angles_supporting_count?: number;
    rationale?: string;
  };
  evidence?: DamageEvidenceRef[];
  estimated_cost?: {
    parts_oem_inr: string;
    parts_oes_inr: string;
    labour_inr: string;
    paint_inr: string;
    subtotal_oem_inr: string;
    subtotal_oes_inr: string;
    estimate_range_inr: string;
  };
  repair_vs_replace_rationale?: string;
  limitations?: string;
}

interface DamageReport {
  model_version: string;
  vehicle?: {
    make: string;
    model: string;
    variant: string;
    year: number;
    registration_number: string;
    is_ev: boolean;
    detection_status: string;
    detection_confidence: number;
    display_label: string;
  };
  observations: DamageReportObservation[];
  damage_zones: string[];
  damage_locations?: string[];
  overall_severity: string;
  overall_image_quality?: string;
  image_quality_confidence: number;
  missing_angles: string[];
  recapture_required_files: string[];
  poor_quality_files?: string[];
  per_image_quality?: Array<{
    evidence_id?: string;
    filename: string;
    angle: string;
    normalized_quality: string;
    quality_confidence: number;
    issues: string[];
  }>;
  cross_photo_comparison?: Array<{
    damage_location: string;
    zone: string;
    photos_covering: string[];
    angles_covered: string[];
    agreement_status: string;
    notes: string;
  }>;
  inconsistencies?: Array<{
    inconsistency_id: string;
    type: string;
    severity: string;
    summary: string;
    resolution_required: string;
  }>;
  parts_labour_estimate?: {
    rate_card_id: string;
    parts_oem_total_inr: string;
    parts_oes_total_inr: string;
    labour_total_inr: string;
    paint_total_inr: string;
    total_recommended_inr: string;
    uncertain_exposure_min_inr: string;
    uncertain_exposure_max_inr: string;
  };
  additional_photo_requests?: Array<{
    angle: string;
    reason_code: string;
    priority: string;
    reason: string;
    guidance: string;
  }>;
  human_assessor_routing?: {
    route_to_human_assessor: boolean;
    recommended_role: string;
    trigger_reasons: string[];
    uncertain_components: string[];
    confidence_guardrail_triggered: boolean;
  };
  structured_assessment_table?: Array<{
    field: string;
    value: string;
    detail: string;
  }>;
  visual_workflow_steps?: Array<{
    step_number: number;
    step_key: string;
    title: string;
    status: string;
    summary: string;
  }>;
  ev_safety_alerts?: string[];
  disclaimer?: string;
}

interface Claim360 {
  claim: Record<string, unknown> & {
    id: string;
    claim_number: string;
    status: string;
    risk_tier?: string;
    operational_path?: string;
    risk_score?: number;
    fraud_signal_score?: string | null;
    multiple_vehicles_involved?: boolean;
    involved_vehicles_count?: number;
    legal_dispute?: boolean;
    claim_type: string;
    peril_cause: string;
    severity_band: string;
    queue_name: string;
    estimated_loss_inr: string;
    requires_mandatory_survey: boolean;
    next_expected_action: string;
    incident_location: string;
    incident_description: string;
    missing_documents: string[];
    coverage_factsheet?: Record<string, unknown> | null;
    triage_summary?: Record<string, unknown> | null;
    risk_assessment?: RiskAssessment | null;
    risk_history?: RiskHistoryEntry[];
    ev_battery_impacted: boolean;
    injury_or_fatality: boolean;
  };
  risk_assessment?: RiskAssessment | null;
  risk_history?: RiskHistoryEntry[];
  policy: {
    policy_number: string;
    product_code: string;
    uin: string;
    status: string;
    idv_inr: string;
    compulsory_deductible_inr: string;
    addons: Record<string, boolean>;
  } | null;
  vehicle: {
    registration_number: string;
    make: string;
    model: string;
    year: number;
    fuel_type: string;
    is_ev: boolean;
  } | null;
  customer: { name: string; phone_masked: string; email_masked: string } | null;
  parties: Array<{ id: string; party_role: string; name: string; is_restricted_tp_medical: boolean; notes: string }>;
  evidence: Array<{
    id: string;
    doc_type: string;
    doc_status: string;
    filename: string;
    sha256: string;
    prompt_injection_flagged: boolean;
    ocr_text: string;
    legal_hold?: boolean;
    image_quality_status?: string;
  }>;
  extracted_facts: Array<{
    id: string;
    evidence_id: string;
    field_name: string;
    extracted_value: string;
    verified_value?: string;
    confidence: string;
    validation_status: string;
  }>;
  damage_report?: DamageReport | null;
  damage_assessments: Array<{
    id: string;
    component_name: string;
    part_code?: string;
    damage_location?: string;
    damage_severity?: string;
    repairability?: string;
    damage_class: string;
    observation_type: string;
    recommended_action: string;
    visible_damage?: string;
    possible_hidden_damage?: string;
    image_quality?: string;
    confidence: string;
    confidence_factors?: Record<string, unknown>;
    evidence_refs?: DamageEvidenceRef[];
    estimated_parts_inr?: string;
    estimated_labour_inr?: string;
    estimated_paint_inr?: string;
    limitations: string;
    reviewer_outcome: string;
  }>;
  estimates: Array<{
    id: string;
    version: number;
    status: string;
    total_claimed_inr: string;
    total_approved_inr: string;
    anomalies: Array<{ type: string; message: string }>;
    lines: Array<{
      id: string;
      part_code: string;
      description: string;
      line_type: string;
      unit_price_inr: string;
      rate_card_price_inr?: string;
      approved_amount_inr?: string;
      variance_flag?: string;
      reviewer_status: string;
    }>;
  }>;
  surveys: Array<{
    id: string;
    surveyor_id?: string;
    status: string;
    appointment_at?: string | null;
    inspection_location?: string;
    reschedule_count?: number;
    reschedule_reason?: string | null;
    followup_count?: number;
    report_due_at: string;
    signed_by_surveyor: boolean;
    report_summary?: Record<string, unknown>;
  }>;
  ecosystem?: {
    id: string;
    surveyor: { id: string; name: string; city: string; licence_status: string; licence_or_contract_id: string; availability?: string; sla?: string; rating?: number; current_load?: string } | null;
    surveyor_license_verified: boolean;
    surveyor_selection_explanation: string;
    surveyor_score_breakdown: Record<string, unknown>;
    garage: { id: string; name: string; city: string; ev_capable: boolean; is_network: boolean; availability?: string; sla?: string; rating?: number; current_load?: string } | null;
    customer_preferred_garage: { id: string; name: string } | null;
    customer_preference_honoured: boolean;
    override_applied: boolean;
    override_authorized: boolean;
    override_authorized_by?: string | null;
    override_reason_code?: string | null;
    override_justification?: string;
    garage_selection_explanation: string;
    garage_score_breakdown: Record<string, unknown>;
    inspection_status: string;
    inspection_scheduled_at?: string | null;
    inspection_reschedule_count: number;
    inspection_reschedule_reason?: string | null;
    towing_required: boolean;
    towing_status: string;
    towing_ev_flatbed: boolean;
    pickup_delivery_status: string;
    pickup_scheduled_at?: string | null;
    delivery_scheduled_at?: string | null;
    pickup_driver_note?: string;
    parts_status: string;
    parts_availability: Array<{ part_code: string; description: string; availability: string; eta_days: number; source: string }>;
    repair_status: string;
    repair_milestones: Array<{ milestone: string; notes: string; actor: string; timestamp: string }>;
    repair_completion_confirmed: boolean;
    repair_confirmed_by?: string | null;
    repair_confirmed_at?: string | null;
    surveyor_followup_count: number;
    surveyor_followup_status: string;
    customer_notifications: Array<{ event: string; channel: string; message: string; sent_at: string }>;
    contractual_compliance: Record<string, boolean>;
    coordination_explanation: string;
  } | null;
  fraud_alerts_restricted: boolean;
  fraud_alerts: Array<{
    id: string;
    indicator_code: string;
    title: string;
    severity_band: string;
    evidence_summary: string;
    benign_explanation: string;
    status: string;
  }>;
  settlements: Array<{
    id: string;
    version: number;
    pathway: string;
    gross_assessed_inr: string;
    depreciation_deduction_inr: string;
    addon_waiver_inr: string;
    compulsory_excess_inr: string;
    net_payable_inr: string;
    approval_status: string;
    policy_citations: string[];
    calculation_trace: Array<Record<string, unknown>>;
  }>;
  approvals: Array<{
    id: string;
    settlement_id?: string;
    action_type: string;
    amount_inr: string;
    maker_user_id: string;
    checker_user_id?: string;
    decision: string;
    rationale: string;
  }>;
  payments: Array<{
    id: string;
    payee_name: string;
    bank_account_masked: string;
    amount_inr: string;
    status: string;
    gateway_reference?: string;
  }>;
  sla_timers: Array<{ id: string; stage: string; status: string; due_at: string }>;
  audit_events: Array<{ id: string; action: string; actor_role: string; before_hash: string; after_hash: string; created_at: string }>;
  tasks: Array<{
    id: string;
    task_type: string;
    title: string;
    description: string;
    assigned_role: string;
    created_by_agent: string;
    priority: string;
    status: string;
    reason_code: string;
  }>;
  decisions: Array<{
    id: string;
    agent_name: string;
    stage: string;
    decision_id: string;
    routing_outcome: string;
    reason_codes: string[];
    evidence: string[];
    policy_rule_refs: string[];
    confidence: string;
    confidence_band: string;
    explanation: string;
    alternatives_considered: string[];
    created_at: string;
  }>;
  agent_executions: Array<{
    id: string;
    agent_name: string;
    attempt_number: number;
    status: string;
    dependencies_satisfied: boolean;
    depends_on: string[];
    actions_executed: Array<{ action_type: string; status: string; summary: string }>;
    rework_requests: Array<{ from_agent: string; to_agent: string; reason_code: string; instructions: string }>;
    error_message?: string | null;
    duration_ms: number;
    created_at: string;
  }>;
  settlement_scenarios: Array<{
    scenario_code: string;
    label: string;
    pathway: string;
    recommended: boolean;
    gross_assessed_inr: string;
    depreciation_deduction_inr: string;
    addon_waiver_inr: string;
    deductibles_total_inr: string;
    salvage_deduction_inr: string;
    policy_idv_limit_inr: string;
    net_payable_inr: string;
    rationale: string;
  }>;
  orchestration_summary: {
    orchestration_order: string[];
    current_state?: string;
    canonical_state?: string;
    triage_track?: string | null;
    paused?: boolean;
    pause_reason?: string | null;
    state_contract?: {
      state: string;
      display_name: string;
      phase: string;
      description: string;
      entry_conditions: string[];
      required_data: string[];
      allowed_actions: string[];
      exit_conditions: string[];
      responsible_agent_or_service: string;
      sla: { stage: string; target_hours: number; escalation_role: string; daily_penalty_inr: string };
      retry_strategy: { max_retries: number; base_delay_ms: number; backoff_multiplier: number; max_delay_ms: number };
      human_escalation_criteria: string[];
    } | null;
    state_history?: Array<{ from_state: string; to_state: string; reason: string; actor: string; timestamp?: string }>;
    parallel_waves?: Array<{ wave_id: string; wave_name: string; agents: string[]; wall_duration_ms: number; outcomes: Record<string, string> }>;
    scheduled_tasks?: Array<{
      id: string;
      task_key: string;
      title: string;
      agent_or_service: string;
      execution_mode: string;
      parallel_group?: string | null;
      depends_on: string[];
      condition_expression?: string | null;
      target_state: string;
      status: string;
      attempt_count: number;
      max_retries: number;
      backoff_delay_ms: number;
      retry_history: Array<{ attempt: number; backoff_delay_ms: number; backoff_formula: string }>;
      error_message?: string | null;
    }>;
    dlq_items?: Array<{
      id: string;
      task_key: string;
      agent_or_service: string;
      failure_reason: string;
      attempt_count: number;
      status: string;
    }>;
    compensations?: Array<{
      id: string;
      trigger_reason: string;
      compensating_action: string;
      target_object_type: string;
      status: string;
    }>;
    events?: Array<{
      id: string;
      event_id: string;
      event_type: string;
      processing_status: string;
      duplicate_hits: number;
    }>;
    stage_statuses: Record<string, string>;
    rework_queue: Array<{ id: string; from_agent: string; to_agent: string; reason_code: string; instructions: string; status: string }>;
    escalations: Array<{ id: string; agent_name: string; reason: string; status: string }>;
  };
  communications?: Array<{
    id: string;
    channel: string;
    language: string;
    subject: string;
    body: string;
  }>;
}

export default function Claim360Page() {
  const params = useParams<{ id: string }>();
  const claimId = params?.id;
  const { token, user } = useAuth();

  const [tab, setTab] = useState<TabId>("overview");
  const [data, setData] = useState<Claim360 | null>(null);
  const [entityGraph, setEntityGraph] = useState<Record<string, unknown> | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [factEdits, setFactEdits] = useState<Record<string, string>>({});
  const [reworkFrom, setReworkFrom] = useState("estimate_validation");
  const [reworkTo, setReworkTo] = useState("damage_assessment");
  const [reworkInstructions, setReworkInstructions] = useState("Verify repair vs replacement teardown evidence.");
  const [eventIdInput, setEventIdInput] = useState("evt-ui-advance-001");
  const [rescheduleReason, setRescheduleReason] = useState("Customer requested afternoon inspection slot at garage");
  const [rescheduleAt, setRescheduleAt] = useState("2026-12-01T14:30:00Z");
  const [followupNotes, setFollowupNotes] = useState("IRDAI 15-day report SLA follow-up requested");
  const [repairMilestone, setRepairMilestone] = useState("body_paint_in_progress");
  const [repairNotes, setRepairNotes] = useState("Body work and OEM paint curing underway");
  const [overrideGarageId, setOverrideGarageId] = useState("prov-gar-ev-02");
  const [overrideReason, setOverrideReason] = useState("");

  const loadClaim = useCallback(async () => {
    if (!token || !claimId) return;
    setErrMsg(null);
    try {
      const res = await apiFetch<Claim360>(`/api/v1/claims/${claimId}`, {}, token);
      setData(res);
      if (!res.fraud_alerts_restricted) {
        apiFetch<Record<string, unknown>>(`/api/v1/claims/${claimId}/entity-graph`, {}, token)
          .then(setEntityGraph)
          .catch(() => { });
      } else {
        setEntityGraph(null);
      }
    } catch (e) {
      setErrMsg(e instanceof Error ? e.message : "Unable to load claim");
    }
  }, [token, claimId]);

  useEffect(() => {
    loadClaim();
  }, [loadClaim]);

  const runAction = async (label: string, path: string, method = "POST", body?: unknown) => {
    if (!token) return;
    setErrMsg(null);
    setStatusMsg(null);
    try {
      await apiFetch(
        path,
        { method, body: body ? JSON.stringify(body) : undefined },
        token
      );
      setStatusMsg(`${label} completed.`);
      await loadClaim();
    } catch (e) {
      setErrMsg(e instanceof Error ? e.message : `${label} failed`);
    }
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !uploadFile) return;
    setErrMsg(null);
    const fd = new FormData();
    fd.append("file", uploadFile);
    try {
      await apiFetch(`/api/v1/claims/${claimId}/evidence`, { method: "POST", body: fd }, token);
      setStatusMsg(`Uploaded ${uploadFile.name} cleanly (malware scanned & OCR extracted).`);
      setUploadFile(null);
      await loadClaim();
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "Upload failed");
    }
  };

  if (errMsg && !data) {
    return (
      <div className="bg-red-50 border border-red-300 text-red-900 p-5 rounded-xl flex items-start gap-3">
        <ShieldAlert className="w-5 h-5 shrink-0 mt-0.5" />
        <div>
          <div className="font-bold">Access / Lookup Blocked</div>
          <div className="text-sm mt-1">{errMsg}</div>
        </div>
      </div>
    );
  }

  if (!data) {
    return <div className="p-8 text-center text-sm text-slate-500">Loading Claim 360...</div>;
  }

  const c = data.claim;

  return (
    <div className="space-y-6">
      {/* Header Summary */}
      <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-bold text-slate-900">{c.claim_number}</h1>
              <StatusPill status={c.status} />
              <RiskTierBadge tier={c.risk_tier} path={c.operational_path} score={c.risk_score} />
              {data.sla_timers[0] && <SlaBadge status={data.sla_timers[0].status} />}
              {c.ev_battery_impacted && (
                <span className="px-2 py-0.5 text-xs font-bold bg-purple-100 text-purple-900 rounded">
                  EV HIGH-VOLTAGE SAFETY
                </span>
              )}
              {c.multiple_vehicles_involved && (
                <span className="px-2 py-0.5 text-xs font-bold bg-rose-100 text-rose-900 rounded">
                  MULTI-VEHICLE ({c.involved_vehicles_count || 2})
                </span>
              )}
              {c.legal_dispute && (
                <span className="px-2 py-0.5 text-xs font-bold bg-rose-100 text-rose-900 rounded">
                  LEGAL / COVERAGE DISPUTE
                </span>
              )}
            </div>
            <p className="text-sm text-slate-600 mt-1">
              {data.vehicle ? `${data.vehicle.make} ${data.vehicle.model} (${data.vehicle.registration_number})` : c.claim_number}
              {data.policy ? ` · Policy ${data.policy.policy_number} (IDV ₹${Number(data.policy.idv_inr).toLocaleString("en-IN")})` : ""}
              {data.customer ? ` · Insured: ${data.customer.name}` : ""}
            </p>
          </div>
          <div className="text-right">
            <div className="text-xs text-slate-500">Estimated Loss</div>
            <div className="text-xl font-bold font-mono text-slate-900">
              &#8377;{Number(c.estimated_loss_inr).toLocaleString("en-IN")}
            </div>
            <div className="text-xs text-slate-500">Queue: {c.queue_name}</div>
          </div>
        </div>

        <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs flex flex-wrap items-center justify-between gap-2">
          <span>
            <span className="font-bold text-slate-900">Next Expected Action: </span>
            {c.next_expected_action}
          </span>
          <span className="text-slate-500">Acting as: {user?.name} ({user?.role})</span>
        </div>
      </div>

      {statusMsg && (
        <div className="bg-emerald-50 border border-emerald-300 text-emerald-900 p-3 rounded-lg text-sm flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4" />
          {statusMsg}
        </div>
      )}
      {errMsg && (
        <div className="bg-red-50 border border-red-300 text-red-900 p-3 rounded-lg text-sm flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" />
          {errMsg}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-200 overflow-x-auto">
        {(
          [
            ["overview", "Overview & AI Workflow"],
            ["customer_experience", `Customer Journey & Comms (${data.communications?.length || 0})`],
            ["orchestration", `Orchestration & Actions (${data.tasks?.length || 0})`],
            ["ecosystem", "Ecosystem & Repair"],
            ["decisions", `Decision Intelligence (${data.decisions?.length || 0})`],
            ["evidence", `Evidence & OCR (${data.evidence.length})`],
            ["damage_estimate", `Damage & Estimate (${data.estimates.length})`],
            ["siu", `Fraud / SIU (${data.fraud_alerts_restricted ? "Restricted" : data.fraud_alerts.length})`],
            ["settlement", `Settlement & Payment (${data.settlements.length})`],
            ["audit", `Audit Trail (${data.audit_events.length})`],
          ] as Array<[TabId, string]>
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`px-4 py-2 text-sm font-medium whitespace-nowrap border-b-2 ${tab === id ? "border-slate-900 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-900"
              }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* TAB 1: OVERVIEW */}
      {tab === "overview" && (
        <div className="space-y-6">
          <ClaimExecutionChain data={data} />

          {/* Risk-Based Claim Processing & Dynamic Recalculation */}
          {(data.risk_assessment || c.risk_assessment) && (
            <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-4">
              {(() => {
                const risk = (data.risk_assessment || c.risk_assessment)!;
                const hist = data.risk_history || c.risk_history || [];
                const tierCls =
                  risk.risk_tier === "LOW"
                    ? "bg-emerald-50 border-emerald-300 text-emerald-950"
                    : risk.risk_tier === "HIGH"
                    ? "bg-rose-50 border-rose-300 text-rose-950"
                    : "bg-amber-50 border-amber-300 text-amber-950";
                return (
                  <>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h2 className="text-base font-bold text-slate-900">
                            Risk-Based Claim Processing &amp; Operational Path
                          </h2>
                          <RiskTierBadge tier={risk.risk_tier} path={risk.operational_path} score={risk.risk_score} />
                        </div>
                        <p className="text-xs text-slate-600">
                          <strong>{risk.operational_path_label}</strong> ({risk.handling_mode}) ·{" "}
                          <strong>Goal:</strong> {risk.goal} · Rule <code>{risk.rule_version}</code>
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {risk.fraud_signal_score !== null && risk.fraud_signal_score !== undefined && (
                          <span className="px-2.5 py-1 text-xs rounded-lg border border-slate-300 bg-slate-50 font-mono">
                            Advisory Fraud Score: <strong>{risk.fraud_signal_score}</strong> · Never auto-rejects
                          </span>
                        )}
                        {risk.automation_eligibility.evidence_preservation_active && (
                          <span className="px-2.5 py-1 text-xs font-bold rounded-lg border border-rose-300 bg-rose-100 text-rose-950">
                            Evidence Legal Hold Active
                          </span>
                        )}
                      </div>
                    </div>

                    <div className={`p-3 rounded-lg border text-xs ${tierCls}`}>
                      {risk.explanation}
                    </div>

                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <div className="text-xs font-bold uppercase text-slate-500">Explainable Risk Drivers</div>
                        {risk.drivers.map((d) => (
                          <div key={d.code} className="p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-xs">
                            <div className="flex items-center justify-between font-bold text-slate-900">
                              <span>{d.category}</span>
                              <span className="font-mono text-[11px]">{d.tier} (+{d.points})</span>
                            </div>
                            <div className="text-slate-600 mt-0.5">{d.summary}</div>
                          </div>
                        ))}
                      </div>

                      <div className="space-y-3">
                        <div className="text-xs font-bold uppercase text-slate-500">Low-Risk Fast-Track Criteria</div>
                        <div className="grid grid-cols-2 gap-2 text-xs">
                          {Object.entries(risk.low_risk_criteria_check || {}).map(([k, ok]) => (
                            <div
                              key={k}
                              className={`px-2.5 py-1.5 rounded border ${
                                ok ? "bg-emerald-50 border-emerald-200 text-emerald-950" : "bg-slate-50 border-slate-200 text-slate-600"
                              }`}
                            >
                              {ok ? "✓" : "✕"} {k.replace(/_/g, " ")}
                            </div>
                          ))}
                        </div>

                        <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg space-y-2">
                          <div className="text-xs font-bold text-slate-900">
                            Dynamic Evidence &amp; Risk Recalculation Lab
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() =>
                                runAction("Recalculate Risk", `/api/v1/claims/${claimId}/risk/recalculate`, "POST", {
                                  trigger_event: "manual_recalculation",
                                })
                              }
                              className="px-2.5 py-1 text-xs font-semibold bg-slate-900 text-white rounded hover:bg-slate-800"
                            >
                              Recalculate Now
                            </button>
                            <button
                              type="button"
                              onClick={() =>
                                runAction("Simulate Late EV Battery Evidence", `/api/v1/claims/${claimId}/risk/recalculate`, "POST", {
                                  trigger_event: "late_ev_bms_evidence",
                                  ev_battery_impacted: true,
                                  new_evidence_summary: "Late undercarriage photo & BMS diagnostic detected EV HV cell deformation.",
                                })
                              }
                              className="px-2.5 py-1 text-xs font-semibold bg-rose-50 border border-rose-300 text-rose-950 rounded hover:bg-rose-100"
                            >
                              + Late EV Battery Evidence
                            </button>
                            <button
                              type="button"
                              onClick={() =>
                                runAction("Report Multi-Vehicle Collision", `/api/v1/claims/${claimId}/risk/recalculate`, "POST", {
                                  trigger_event: "late_multi_vehicle_report",
                                  multiple_vehicles_involved: true,
                                  involved_vehicles_count: 3,
                                  new_evidence_summary: "Police spot panchanama identifies 3 vehicles involved in chain impact.",
                                })
                              }
                              className="px-2.5 py-1 text-xs font-semibold bg-rose-50 border border-rose-300 text-rose-950 rounded hover:bg-rose-100"
                            >
                              + Multi-Vehicle Evidence
                            </button>
                            <button
                              type="button"
                              onClick={() =>
                                runAction("Raise High Fraud Lead (Non-Rejecting)", `/api/v1/claims/${claimId}/risk/recalculate`, "POST", {
                                  trigger_event: "high_fraud_signal_lead",
                                  fraud_signal_score_override_attempt: "0.860",
                                  new_evidence_summary: "Entity graph detected cross-claim workshop phone overlap (escalate to SIU; do not auto-reject).",
                                })
                              }
                              className="px-2.5 py-1 text-xs font-semibold bg-amber-50 border border-amber-300 text-amber-950 rounded hover:bg-amber-100"
                            >
                              + Fraud Signal (Escalates, Never Rejects)
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>

                    {hist.length > 0 && (
                      <div className="space-y-1.5 pt-1">
                        <div className="text-xs font-bold uppercase text-slate-500">Risk Transition History ({hist.length})</div>
                        <div className="space-y-1.5">
                          {hist.map((h) => (
                            <div key={h.event_id} className="p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-xs flex flex-wrap items-center justify-between gap-2">
                              <div>
                                <span className="font-bold text-slate-900">
                                  {h.previous_tier ? `${h.previous_tier} → ${h.new_tier}` : `INITIAL ${h.new_tier}`}
                                </span>{" "}
                                <span className="text-slate-600">({h.trigger_event})</span>
                                <div className="text-slate-600 mt-0.5">{h.explanation}</div>
                              </div>
                              <span className="font-mono text-[11px] text-slate-500">{h.timestamp.slice(0, 19).replace("T", " ")}Z</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                );
              })()}
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 space-y-4">
              <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
                <div className="flex items-center justify-between">
                  <h2 className="text-base font-bold text-slate-900">Incident & Parties</h2>
                  <ProvenanceBadge kind="verified" />
                </div>
                <p className="text-sm text-slate-700">{c.incident_description}</p>
                <div className="text-xs text-slate-500">Location: {c.incident_location}</div>
                {c.missing_documents.length > 0 && (
                  <div className="p-3 bg-amber-50 border border-amber-200 rounded text-xs text-amber-950">
                    <strong>Missing Documents (Follow-up Active):</strong> {c.missing_documents.join(", ")}
                  </div>
                )}
                {data.parties.length > 0 && (
                  <div className="space-y-1 pt-2">
                    <div className="text-xs font-bold text-slate-700">Claim Parties</div>
                    {data.parties.map((p) => (
                      <div key={p.id} className="text-xs p-2 bg-slate-50 rounded border border-slate-200">
                        <span className="font-semibold uppercase">{p.party_role}:</span> {p.name} — {p.notes}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {c.coverage_factsheet && (
                <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-2">
                  <div className="flex items-center justify-between">
                    <h2 className="text-base font-bold text-slate-900">Coverage Intelligence Factsheet</h2>
                    <ProvenanceBadge kind="ai_assistive" />
                  </div>
                  <pre className="text-xs bg-slate-50 p-3 rounded border border-slate-200 overflow-x-auto">
                    {JSON.stringify(c.coverage_factsheet, null, 2)}
                  </pre>
                </div>
              )}
            </div>

            <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-2.5 h-fit">
              <h2 className="text-base font-bold text-slate-900">Orchestrator Actions</h2>
              <p className="text-xs text-slate-500">
                Dependency-gated agents execute actions safely; human approvals remain mandatory.
              </p>
              <button
                type="button"
                onClick={() => runAction("Autonomous DAG Orchestrator", `/api/v1/claims/${claimId}/orchestrate`, "POST", { stop_on_human_gate: true })}
                className="w-full py-2 px-3 text-xs font-semibold bg-blue-700 text-white rounded-lg hover:bg-blue-800 text-left"
              >
                0. Run Autonomous DAG Orchestrator
              </button>
              <button
                type="button"
                onClick={() => runAction("Coverage Check", `/api/v1/claims/${claimId}/coverage-checks`)}
                className="w-full py-2 px-3 text-xs font-semibold bg-slate-900 text-white rounded-lg hover:bg-slate-800 text-left"
              >
                1. Run Coverage Check (Policy RAG + Rules)
              </button>
              <button
                type="button"
                onClick={() => runAction("Claim Triage", `/api/v1/claims/${claimId}/triage`)}
                className="w-full py-2 px-3 text-xs font-semibold bg-slate-900 text-white rounded-lg hover:bg-slate-800 text-left"
              >
                2. Run Claim Triage & Survey Threshold
              </button>
              <button
                type="button"
                onClick={() => runAction("Coordinate Providers", `/api/v1/claims/${claimId}/provider-coordination`, "POST", {})}
                className="w-full py-2 px-3 text-xs font-semibold bg-white border border-slate-300 text-slate-900 rounded-lg hover:bg-slate-50 text-left"
              >
                3. Coordinate Surveyor, Garage &amp; Towing
              </button>
              <button
                type="button"
                onClick={() => runAction("Damage Assessment", `/api/v1/claims/${claimId}/damage-assessments`)}
                className="w-full py-2 px-3 text-xs font-semibold bg-white border border-slate-300 text-slate-900 rounded-lg hover:bg-slate-50 text-left"
              >
                4. Run Assistive Damage Vision Check
              </button>
              <button
                type="button"
                onClick={() => runAction("Fraud Signals", `/api/v1/claims/${claimId}/fraud-checks`)}
                className="w-full py-2 px-3 text-xs font-semibold bg-white border border-slate-300 text-slate-900 rounded-lg hover:bg-slate-50 text-left"
              >
                5. Evaluate Explainable Fraud Signals
              </button>
              <button
                type="button"
                onClick={() => runAction("Submit Survey Report", `/api/v1/claims/${claimId}/survey-reports`, "POST", {
                  inspection_notes: "Physical inspection completed; visible front panel damage matches incident.",
                  assessed_gross_inr: c.estimated_loss_inr,
                  signed: true,
                })}
                className="w-full py-2 px-3 text-xs font-semibold bg-white border border-slate-300 text-slate-900 rounded-lg hover:bg-slate-50 text-left"
              >
                6. Submit Signed Surveyor Report
              </button>
              <button
                type="button"
                onClick={() => runAction("Recover & Resume", `/api/v1/claims/${claimId}/orchestration/recover`, "POST", { resolution_notes: "Manual recovery trigger", resume_pipeline: true })}
                className="w-full py-2 px-3 text-xs font-semibold bg-amber-50 border border-amber-300 text-amber-950 rounded-lg hover:bg-amber-100 text-left"
              >
                7. Recover Rework / Timeout &amp; Resume
              </button>
              <button
                type="button"
                onClick={() => runAction("Close Claim", `/api/v1/claims/${claimId}/close`)}
                className="w-full py-2 px-3 text-xs font-semibold bg-emerald-800 text-white rounded-lg hover:bg-emerald-900 text-left"
              >
                8. QA Check &amp; Close Claim
              </button>
            </div>
          </div>
        </div>
      )}

      {/* TAB: CUSTOMER EXPERIENCE INTELLIGENCE & MOTOR CLAIM TRACKER */}
      {tab === "customer_experience" && token && (
        <MotorClaimTracker claimId={claimId} token={token} allowUpload={true} onClaimUpdated={loadClaim} />
      )}

      {/* TAB: ORCHESTRATION, ACTIONS & TASKS */}
      {tab === "orchestration" && (
        <div className="space-y-6">
          <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-bold text-slate-900">
                  Claim Orchestration Engine — State Control, DAG Scheduler &amp; Recovery
                </h2>
                <p className="text-xs text-slate-500">
                  Orchestrator owns state transitions, parallel waves, exponential-backoff retries, DLQ, compensation, SLA tracking, and duplicate-event protection.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => runAction("Autonomous Orchestrate", `/api/v1/claims/${claimId}/orchestrate`, "POST", { stop_on_human_gate: true })}
                  className="px-3 py-1.5 text-xs font-semibold bg-slate-900 text-white rounded-lg"
                >
                  Run Ready Waves
                </button>
                {data.orchestration_summary?.paused ? (
                  <button
                    type="button"
                    onClick={() => runAction("Resume Workflow", `/api/v1/claims/${claimId}/orchestration/resume`, "POST", { resolution_notes: "Resumed from Claim 360", run_ready_stages: true })}
                    className="px-3 py-1.5 text-xs font-semibold bg-emerald-700 text-white rounded-lg"
                  >
                    Resume Workflow
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => runAction("Pause Workflow", `/api/v1/claims/${claimId}/orchestration/pause`, "POST", { reason: "Paused for Claim 360 operational check" })}
                    className="px-3 py-1.5 text-xs font-semibold bg-amber-600 text-white rounded-lg"
                  >
                    Pause Workflow
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => runAction("Compensation Saga", `/api/v1/claims/${claimId}/orchestration/compensate`, "POST", { trigger_reason: "Operator-triggered compensation rollback" })}
                  className="px-3 py-1.5 text-xs font-semibold bg-rose-700 text-white rounded-lg"
                >
                  Run Compensation
                </button>
              </div>
            </div>

            {data.orchestration_summary?.paused && (
              <div className="p-3 bg-amber-50 border border-amber-300 text-amber-950 rounded-lg text-xs font-semibold">
                WORKFLOW PAUSED: {data.orchestration_summary.pause_reason || "Manual pause active (SLA timers paused)"}
              </div>
            )}

            {data.orchestration_summary?.state_contract && (
              <div className="p-4 bg-slate-50 border border-slate-200 rounded-lg text-xs space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-bold text-slate-900">
                    Active State Contract: {data.orchestration_summary.state_contract.state} ({data.orchestration_summary.state_contract.phase})
                  </span>
                  <span className="font-mono text-slate-600">
                    SLA: {data.orchestration_summary.state_contract.sla.stage} ({data.orchestration_summary.state_contract.sla.target_hours}h) · Retry: {data.orchestration_summary.state_contract.retry_strategy.max_retries}x exp ({data.orchestration_summary.state_contract.retry_strategy.base_delay_ms}ms)
                  </span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-4 gap-3 pt-1">
                  <div>
                    <div className="font-bold text-slate-600 uppercase text-[10px]">Entry Conditions</div>
                    <ul className="list-disc pl-4 text-slate-700 mt-0.5">
                      {data.orchestration_summary.state_contract.entry_conditions.map((x) => (
                        <li key={x}>{x}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <div className="font-bold text-slate-600 uppercase text-[10px]">Required Data &amp; Owner</div>
                    <div className="text-slate-700 mt-0.5">{data.orchestration_summary.state_contract.required_data.join(", ")}</div>
                    <div className="text-blue-800 font-semibold mt-1">{data.orchestration_summary.state_contract.responsible_agent_or_service}</div>
                  </div>
                  <div>
                    <div className="font-bold text-slate-600 uppercase text-[10px]">Allowed Actions &amp; Exit</div>
                    <div className="text-slate-700 mt-0.5">{data.orchestration_summary.state_contract.allowed_actions.join(", ")}</div>
                    <div className="text-emerald-800 mt-1">Exit: {data.orchestration_summary.state_contract.exit_conditions.join("; ")}</div>
                  </div>
                  <div>
                    <div className="font-bold text-slate-600 uppercase text-[10px]">Human Escalation Criteria</div>
                    <ul className="list-disc pl-4 text-amber-900 mt-0.5">
                      {data.orchestration_summary.state_contract.human_escalation_criteria.map((x) => (
                        <li key={x}>{x}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            )}

            <div>
              <h3 className="text-xs font-bold uppercase text-slate-600 mb-2">
                Scheduled DAG Tasks ({data.orchestration_summary?.scheduled_tasks?.length || 0}) — Parallel, Sequential, Conditional &amp; Approval-Gated
              </h3>
              <div className="overflow-x-auto border border-slate-200 rounded-lg">
                <table className="w-full text-left text-xs border-collapse">
                  <thead className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase text-slate-600">
                    <tr>
                      <th className="px-3 py-2">Task</th>
                      <th className="px-3 py-2">Dependencies</th>
                      <th className="px-3 py-2">Execution</th>
                      <th className="px-3 py-2">Owner</th>
                      <th className="px-3 py-2">Status &amp; Retries</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {(data.orchestration_summary?.scheduled_tasks || []).map((t) => (
                      <tr key={t.id}>
                        <td className="px-3 py-2 font-semibold text-slate-900">
                          {t.task_key}
                          <div className="text-[11px] font-normal text-slate-500">{t.title}</div>
                        </td>
                        <td className="px-3 py-2 text-slate-600 font-mono">
                          {t.depends_on.length > 0 ? t.depends_on.join(", ") : "Entry"}
                        </td>
                        <td className="px-3 py-2">
                          <span className="px-2 py-0.5 rounded bg-indigo-50 text-indigo-900 font-semibold uppercase">
                            {t.execution_mode}
                          </span>
                          {t.parallel_group && (
                            <div className="text-[10px] text-slate-500 mt-0.5">{t.parallel_group}</div>
                          )}
                        </td>
                        <td className="px-3 py-2 font-mono text-slate-700">{t.agent_or_service}</td>
                        <td className="px-3 py-2">
                          <span className="px-2 py-0.5 rounded bg-slate-100 font-semibold uppercase">{t.status}</span>
                          {t.attempt_count > 0 && (
                            <span className="ml-1 text-[11px] text-slate-500">
                              (attempts: {t.attempt_count}/{t.max_retries + 1}{t.backoff_delay_ms ? `, backoff ${t.backoff_delay_ms}ms` : ""})
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs pt-2">
              <div className="p-3 border border-slate-200 rounded-lg space-y-2">
                <div className="font-bold text-slate-900">Duplicate-Event Protection Test</div>
                <div className="flex gap-2">
                  <input
                    value={eventIdInput}
                    onChange={(e) => setEventIdInput(e.target.value)}
                    className="flex-1 px-2 py-1 border border-slate-300 rounded font-mono"
                    placeholder="event_id"
                  />
                  <button
                    type="button"
                    onClick={() => runAction("Dispatch Event", `/api/v1/claims/${claimId}/orchestration/events`, "POST", { event_id: eventIdInput, event_type: "ManualAdvance", auto_advance: true })}
                    className="px-2.5 py-1 bg-blue-700 text-white rounded font-semibold"
                  >
                    Send Event
                  </button>
                </div>
                {(data.orchestration_summary?.events || []).slice(0, 3).map((ev) => (
                  <div key={ev.id} className="text-[11px] text-slate-600">
                    <code>{ev.event_id}</code> ({ev.event_type}) · hits={ev.duplicate_hits}
                  </div>
                ))}
              </div>
              <div className="p-3 border border-slate-200 rounded-lg space-y-1">
                <div className="font-bold text-slate-900">
                  Dead-Letter Queue ({data.orchestration_summary?.dlq_items?.length || 0})
                </div>
                {(data.orchestration_summary?.dlq_items || []).map((d) => (
                  <div key={d.id} className="text-[11px] text-rose-800">
                    <code>{d.task_key}</code> [{d.status}]: {d.failure_reason}
                  </div>
                ))}
                {(data.orchestration_summary?.dlq_items?.length || 0) === 0 && (
                  <div className="text-[11px] text-slate-500">Zero exhausted tasks in DLQ.</div>
                )}
              </div>
              <div className="p-3 border border-slate-200 rounded-lg space-y-1">
                <div className="font-bold text-slate-900">
                  Compensation Saga Logs ({data.orchestration_summary?.compensations?.length || 0})
                </div>
                {(data.orchestration_summary?.compensations || []).map((cp) => (
                  <div key={cp.id} className="text-[11px] text-slate-700">
                    <code>{cp.compensating_action}</code> [{cp.status}]
                  </div>
                ))}
                {(data.orchestration_summary?.compensations?.length || 0) === 0 && (
                  <div className="text-[11px] text-slate-500">No compensation rollbacks triggered.</div>
                )}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
              <h3 className="text-base font-bold text-slate-900">Action-Taking Agent Tasks ({data.tasks?.length || 0})</h3>
              {(data.tasks || []).map((t) => (
                <div key={t.id} className="p-3 border border-slate-200 rounded-lg text-xs space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-bold text-slate-900">{t.title}</span>
                    <span className="px-2 py-0.5 rounded bg-slate-100 font-semibold uppercase">{t.status}</span>
                  </div>
                  <div className="text-slate-600">{t.description}</div>
                  <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-500">
                    <span>
                      Agent: <code>{t.created_by_agent}</code> · Role: <strong>{t.assigned_role}</strong> · Priority: {t.priority}
                    </span>
                    {t.status !== "completed" && (
                      <button
                        type="button"
                        onClick={() => runAction("Complete Task", `/api/v1/claims/${claimId}/tasks/${t.id}`, "PATCH", { status: "completed" })}
                        className="px-2.5 py-1 bg-slate-900 text-white rounded font-semibold"
                      >
                        Mark Complete
                      </button>
                    )}
                  </div>
                </div>
              ))}
              {(!data.tasks || data.tasks.length === 0) && (
                <p className="text-xs text-slate-500">No claim tasks created yet.</p>
              )}
            </div>

            <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-4">
              <h3 className="text-base font-bold text-slate-900">Request Rework / Recover Escalation</h3>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <label className="block font-semibold text-slate-600 mb-1">From Stage</label>
                  <select value={reworkFrom} onChange={(e) => setReworkFrom(e.target.value)} className="w-full p-2 border border-slate-300 rounded bg-white">
                    <option value="estimate_validation">estimate_validation</option>
                    <option value="coverage_intelligence">coverage_intelligence</option>
                    <option value="qa_compliance">qa_compliance</option>
                  </select>
                </div>
                <div>
                  <label className="block font-semibold text-slate-600 mb-1">To Earlier Stage</label>
                  <select value={reworkTo} onChange={(e) => setReworkTo(e.target.value)} className="w-full p-2 border border-slate-300 rounded bg-white">
                    <option value="damage_assessment">damage_assessment</option>
                    <option value="document_intelligence">document_intelligence</option>
                    <option value="provider_coordination">provider_coordination</option>
                  </select>
                </div>
              </div>
              <input
                value={reworkInstructions}
                onChange={(e) => setReworkInstructions(e.target.value)}
                className="w-full px-3 py-2 text-xs border border-slate-300 rounded-lg"
                placeholder="Rework instructions..."
              />
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() =>
                    runAction("Request Rework", `/api/v1/claims/${claimId}/rework`, "POST", {
                      from_agent: reworkFrom,
                      to_agent: reworkTo,
                      reason_code: "RC_MANUAL_STAGE_REWORK",
                      instructions: reworkInstructions,
                      blocking: true,
                    })
                  }
                  className="px-3 py-1.5 text-xs font-semibold bg-amber-700 text-white rounded"
                >
                  Send Blocking Rework Request
                </button>
                <button
                  type="button"
                  onClick={() =>
                    runAction("Recover Orchestration", `/api/v1/claims/${claimId}/orchestration/recover`, "POST", {
                      resolution_notes: "Resolved and recovered via Claim 360",
                      resume_pipeline: true,
                    })
                  }
                  className="px-3 py-1.5 text-xs font-semibold bg-emerald-700 text-white rounded"
                >
                  Recover &amp; Resume
                </button>
              </div>

              <div className="space-y-2 pt-2 border-t border-slate-200">
                <div className="text-xs font-bold text-slate-700">Recent Controlled Agent Actions</div>
                {(data.agent_executions || []).slice(0, 6).map((ex) => (
                  <div key={ex.id} className="p-2.5 bg-slate-50 rounded border border-slate-200 text-xs space-y-1">
                    <div className="flex justify-between font-semibold">
                      <span>
                        <code>{ex.agent_name}</code> (attempt #{ex.attempt_number})
                      </span>
                      <span className="uppercase">{ex.status}</span>
                    </div>
                    {ex.actions_executed.map((act, idx) => (
                      <div key={idx} className="text-slate-600">
                        • <code>{act.action_type}</code> [{act.status}]: {act.summary}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB: ECOSYSTEM & REPAIR COORDINATION */}
      {tab === "ecosystem" && (
        <div className="space-y-6">
          {(() => {
            const eco = data.ecosystem;
            return (
              <>
                <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h2 className="text-base font-bold text-slate-900">
                        Claims Ecosystem Orchestration &amp; Provider Selection Explainability
                      </h2>
                      <p className="text-xs text-slate-600">
                        Surveyor availability &amp; IIISLA licence check, geography/skill/capacity/SLA assignment, customer preferred garage protection, parts, logistics, and repair completion.
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => runAction("Coordinate Ecosystem", `/api/v1/claims/${claimId}/provider-coordination`, "POST", { towing_needed: Boolean(c.ev_battery_impacted || c.vehicle_immobile), pickup_required: true })}
                      className="px-3.5 py-2 text-xs font-semibold bg-slate-900 text-white rounded-lg hover:bg-slate-800"
                    >
                      Run Ecosystem Coordination
                    </button>
                  </div>

                  {eco?.coordination_explanation && (
                    <div className="p-3 rounded-lg border border-blue-200 bg-blue-50/70 text-xs text-blue-950">
                      <strong>Why Selected:</strong> {eco.coordination_explanation}
                    </div>
                  )}

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                    <div className="p-4 border border-slate-200 rounded-xl space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-slate-900">Surveyor Assignment &amp; Licence Verification</span>
                        <span className={`px-2 py-0.5 rounded font-semibold ${eco?.surveyor_license_verified ? "bg-emerald-100 text-emerald-900" : "bg-amber-100 text-amber-950"}`}>
                          {eco?.surveyor_license_verified ? "IIISLA VERIFIED" : "PENDING VERIFICATION"}
                        </span>
                      </div>
                      {eco?.surveyor ? (
                        <div className="space-y-1 text-slate-700">
                          <div className="font-semibold text-slate-900">{eco.surveyor.name}</div>
                          <div>City: {eco.surveyor.city} · Licence: <code>{eco.surveyor.licence_or_contract_id}</code></div>
                          <div>Availability: <strong>{eco.surveyor.availability}</strong> · SLA: <strong>{eco.surveyor.sla}</strong> · Load: <strong>{eco.surveyor.current_load}</strong> · Rating: <strong>{eco.surveyor.rating}</strong></div>
                          {eco.surveyor_selection_explanation && (
                            <div className="text-[11px] text-slate-600 bg-slate-50 p-2 rounded border border-slate-200">
                              {eco.surveyor_selection_explanation}
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="text-slate-500">No surveyor assigned yet (or bypassed on LOW risk fast-track).</div>
                      )}
                    </div>

                    <div className="p-4 border border-slate-200 rounded-xl space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-slate-900">Garage Selection &amp; Customer Choice Guardrail</span>
                        <span className={`px-2 py-0.5 rounded font-semibold ${eco?.customer_preference_honoured ? "bg-emerald-100 text-emerald-900" : "bg-amber-100 text-amber-950"}`}>
                          {eco?.customer_preference_honoured ? "CUSTOMER CHOICE HONOURED" : "CONTRACTUAL / AUTH OVERRIDE"}
                        </span>
                      </div>
                      {eco?.garage ? (
                        <div className="space-y-1 text-slate-700">
                          <div className="font-semibold text-slate-900">{eco.garage.name}</div>
                          <div>City: {eco.garage.city} · EV Capable: <strong>{eco.garage.ev_capable ? "Yes" : "No"}</strong> · Network: <strong>{eco.garage.is_network ? "Yes" : "No"}</strong></div>
                          <div>Availability: <strong>{eco.garage.availability}</strong> · SLA: <strong>{eco.garage.sla}</strong> · Load: <strong>{eco.garage.current_load}</strong> · Rating: <strong>{eco.garage.rating}</strong></div>
                          {eco.garage_selection_explanation && (
                            <div className="text-[11px] text-slate-600 bg-slate-50 p-2 rounded border border-slate-200">
                              {eco.garage_selection_explanation}
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="text-slate-500">No garage selected yet.</div>
                      )}
                    </div>
                  </div>

                  {/* Authorized Override Control (Blocked for non-Managers / missing rationale) */}
                  <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-xl text-xs space-y-2">
                    <div className="font-bold text-slate-900">
                      Customer Choice &amp; Contractual Override Control (Manager / Admin Authorization Required)
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                      <select
                        value={overrideGarageId}
                        onChange={(e) => setOverrideGarageId(e.target.value)}
                        className="p-2 border border-slate-300 rounded bg-white"
                      >
                        <option value="prov-gar-01">Garage A — Apex Motors (Mumbai)</option>
                        <option value="prov-gar-ev-02">VoltCare OEM EV Specialist Centre</option>
                        <option value="prov-gar-02">Garage B — Metro Collision Works (Thane)</option>
                        <option value="prov-gar-nonnet">Independent Custom Bodyshop (Non-Network)</option>
                      </select>
                      <input
                        value={overrideReason}
                        onChange={(e) => setOverrideReason(e.target.value)}
                        placeholder="Authorized override reason (required)..."
                        className="p-2 border border-slate-300 rounded bg-white"
                      />
                      <button
                        type="button"
                        onClick={() =>
                          runAction("Override Garage Choice", `/api/v1/claims/${claimId}/provider-coordination`, "POST", {
                            selected_garage_id: overrideGarageId,
                            override_customer_preference: true,
                            override_reason: overrideReason,
                          })
                        }
                        className="px-3 py-2 bg-amber-700 text-white rounded font-semibold hover:bg-amber-800"
                      >
                        Attempt Override (Auth Enforced)
                      </button>
                    </div>
                  </div>
                </div>

                {/* Inspection Scheduling, Rescheduling & Surveyor Follow-ups */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3 text-xs">
                    <div className="flex items-center justify-between">
                      <h3 className="text-base font-bold text-slate-900">Inspection Schedule, Reschedule &amp; Follow-up</h3>
                      <span className="px-2 py-0.5 rounded bg-slate-100 font-semibold uppercase">{eco?.inspection_status || "pending"}</span>
                    </div>
                    <div className="text-slate-600">
                      Scheduled: <strong>{eco?.inspection_scheduled_at ? eco.inspection_scheduled_at.slice(0, 16) : "Not scheduled"}</strong> · Reschedules: <strong>{eco?.inspection_reschedule_count || 0}</strong> · Follow-ups sent: <strong>{eco?.surveyor_followup_count || 0}</strong> ({eco?.surveyor_followup_status || "none"})
                    </div>
                    <div className="space-y-2 pt-2 border-t border-slate-100">
                      <div className="font-semibold text-slate-800">Reschedule Inspection</div>
                      <input
                        value={rescheduleAt}
                        onChange={(e) => setRescheduleAt(e.target.value)}
                        className="w-full p-2 border border-slate-300 rounded font-mono"
                        placeholder="ISO timestamp (e.g. 2026-12-01T14:30:00Z)"
                      />
                      <input
                        value={rescheduleReason}
                        onChange={(e) => setRescheduleReason(e.target.value)}
                        className="w-full p-2 border border-slate-300 rounded"
                        placeholder="Reschedule reason"
                      />
                      <button
                        type="button"
                        onClick={() =>
                          runAction("Reschedule Inspection", `/api/v1/claims/${claimId}/ecosystem/inspection/reschedule`, "POST", {
                            appointment_at: rescheduleAt,
                            reason: rescheduleReason,
                          })
                        }
                        className="px-3 py-1.5 bg-slate-900 text-white rounded font-semibold"
                      >
                        Reschedule Inspection &amp; Notify Customer
                      </button>
                    </div>
                    <div className="space-y-2 pt-2 border-t border-slate-100">
                      <div className="font-semibold text-slate-800">Surveyor Report Follow-up</div>
                      <input
                        value={followupNotes}
                        onChange={(e) => setFollowupNotes(e.target.value)}
                        className="w-full p-2 border border-slate-300 rounded"
                      />
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() =>
                            runAction("Surveyor Follow-up", `/api/v1/claims/${claimId}/ecosystem/surveyor-followup`, "POST", {
                              notes: followupNotes,
                              escalate_to_manager: false,
                            })
                          }
                          className="px-3 py-1.5 bg-blue-700 text-white rounded font-semibold"
                        >
                          Send Surveyor Follow-up
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            runAction("Escalate Surveyor SLA", `/api/v1/claims/${claimId}/ecosystem/surveyor-followup`, "POST", {
                              notes: followupNotes,
                              escalate_to_manager: true,
                            })
                          }
                          className="px-3 py-1.5 bg-rose-700 text-white rounded font-semibold"
                        >
                          Escalate Delay to Manager
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Towing, Pickup/Delivery, Parts & Repair Completion */}
                  <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3 text-xs">
                    <div className="flex items-center justify-between">
                      <h3 className="text-base font-bold text-slate-900">Parts, Logistics &amp; Repair Completion</h3>
                      {eco?.repair_completion_confirmed && (
                        <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-900 font-bold">
                          REPAIR COMPLETED &amp; CONFIRMED
                        </span>
                      )}
                    </div>
                    <div className="grid grid-cols-3 gap-2 bg-slate-50 p-2.5 rounded border border-slate-200">
                      <div><span className="text-slate-500">Towing:</span> <strong>{eco?.towing_status || "not_required"}</strong></div>
                      <div><span className="text-slate-500">Pickup/Delivery:</span> <strong>{eco?.pickup_delivery_status || "not_scheduled"}</strong></div>
                      <div><span className="text-slate-500">Parts:</span> <strong>{eco?.parts_status || "pending_check"}</strong></div>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      <button
                        type="button"
                        onClick={() => runAction("Parts Check", `/api/v1/claims/${claimId}/ecosystem/parts-check`, "POST", {})}
                        className="px-2.5 py-1 border border-slate-300 rounded font-semibold hover:bg-slate-50"
                      >
                        Check Parts Stock
                      </button>
                      <button
                        type="button"
                        onClick={() => runAction("Schedule Pickup", `/api/v1/claims/${claimId}/ecosystem/logistics`, "POST", { pickup_delivery_status: "pickup_scheduled", pickup_driver_note: "Doorstep pickup booked" })}
                        className="px-2.5 py-1 border border-slate-300 rounded font-semibold hover:bg-slate-50"
                      >
                        Schedule Pickup
                      </button>
                      <button
                        type="button"
                        onClick={() => runAction("Dispatch Tow", `/api/v1/claims/${claimId}/ecosystem/logistics`, "POST", { towing_status: "dispatched" })}
                        className="px-2.5 py-1 border border-slate-300 rounded font-semibold hover:bg-slate-50"
                      >
                        Dispatch Towing
                      </button>
                      <button
                        type="button"
                        onClick={() => runAction("Schedule Delivery", `/api/v1/claims/${claimId}/ecosystem/logistics`, "POST", { pickup_delivery_status: "delivery_scheduled" })}
                        className="px-2.5 py-1 border border-slate-300 rounded font-semibold hover:bg-slate-50"
                      >
                        Schedule Delivery
                      </button>
                    </div>
                    {(eco?.parts_availability || []).length > 0 && (
                      <div className="space-y-1">
                        {eco!.parts_availability.map((pt, idx) => (
                          <div key={idx} className="flex justify-between p-1.5 bg-slate-50 rounded border border-slate-200">
                            <span><code>{pt.part_code}</code> · {pt.description}</span>
                            <span className="font-semibold">{pt.availability} ({pt.eta_days}d · {pt.source})</span>
                          </div>
                        ))}
                      </div>
                    )}
                    <div className="space-y-2 pt-2 border-t border-slate-100">
                      <div className="font-semibold text-slate-800">Repair Status &amp; Completion Confirmation</div>
                      <div className="flex gap-2">
                        <select
                          value={repairMilestone}
                          onChange={(e) => setRepairMilestone(e.target.value)}
                          className="p-2 border border-slate-300 rounded bg-white"
                        >
                          <option value="intake_confirmed">intake_confirmed</option>
                          <option value="teardown_in_progress">teardown_in_progress</option>
                          <option value="awaiting_parts">awaiting_parts</option>
                          <option value="body_paint_in_progress">body_paint_in_progress</option>
                          <option value="qc_pending">qc_pending</option>
                          <option value="repair_completed">repair_completed</option>
                          <option value="handover_confirmed">handover_confirmed</option>
                        </select>
                        <input
                          value={repairNotes}
                          onChange={(e) => setRepairNotes(e.target.value)}
                          className="flex-1 p-2 border border-slate-300 rounded"
                        />
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => runAction("Update Repair Status", `/api/v1/claims/${claimId}/repair-status`, "POST", { milestone: repairMilestone, notes: repairNotes, confirm_completion: false })}
                          className="px-3 py-1.5 bg-slate-900 text-white rounded font-semibold"
                        >
                          Update Repair Milestone
                        </button>
                        <button
                          type="button"
                          onClick={() => runAction("Confirm Repair Completion", `/api/v1/claims/${claimId}/ecosystem/repair-completion`, "POST", { milestone: "repair_completed", notes: repairNotes, confirm_completion: true })}
                          className="px-3 py-1.5 bg-emerald-700 text-white rounded font-semibold"
                        >
                          Confirm Repair Completion &amp; Notify Customer
                        </button>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Customer Coordination Notifications */}
                <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-2 text-xs">
                  <h3 className="text-base font-bold text-slate-900">
                    Ecosystem Customer Notifications ({eco?.customer_notifications?.length || 0})
                  </h3>
                  {(eco?.customer_notifications || []).map((n, idx) => (
                    <div key={idx} className="p-2.5 bg-slate-50 border border-slate-200 rounded flex flex-wrap justify-between gap-2">
                      <span><strong>[{n.event}]</strong> ({n.channel}): {n.message}</span>
                      <span className="text-slate-500 font-mono">{n.sent_at.slice(0, 19)}</span>
                    </div>
                  ))}
                  {(!eco?.customer_notifications || eco.customer_notifications.length === 0) && (
                    <div className="text-slate-500">No ecosystem customer notifications logged yet.</div>
                  )}
                </div>
              </>
            );
          })()}
        </div>
      )}

      {/* TAB: DECISION INTELLIGENCE */}
      {tab === "decisions" && (
        <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-4">
          <div>
            <h2 className="text-base font-bold text-slate-900">Decision Intelligence Ledger</h2>
            <p className="text-xs text-slate-500">
              Every decision records evidence, policy/rule references, reason codes, confidence, routing outcome, and explanation.
            </p>
          </div>
          <div className="space-y-3">
            {(data.decisions || []).map((d) => (
              <div key={d.id} className="p-4 border border-slate-200 rounded-xl text-xs space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <span className="font-mono font-bold text-blue-800">{d.agent_name}</span> ·{" "}
                    <span className="font-bold text-slate-900">Routing: {d.routing_outcome}</span>
                  </div>
                  <span className="px-2 py-0.5 bg-slate-100 rounded font-semibold">
                    Conf: {d.confidence} ({d.confidence_band.toUpperCase()})
                  </span>
                </div>
                <div className="text-slate-800 font-medium">{d.explanation}</div>
                <div className="flex flex-wrap gap-1.5">
                  {d.reason_codes.map((rc) => (
                    <span key={rc} className="px-2 py-0.5 bg-indigo-50 border border-indigo-200 text-indigo-900 rounded font-mono">
                      {rc}
                    </span>
                  ))}
                  {d.policy_rule_refs.map((pr) => (
                    <span key={pr} className="px-2 py-0.5 bg-emerald-50 border border-emerald-200 text-emerald-900 rounded font-mono">
                      {pr}
                    </span>
                  ))}
                </div>
                {d.evidence.length > 0 && (
                  <div className="text-slate-600">
                    <strong>Evidence:</strong> {d.evidence.join(" | ")}
                  </div>
                )}
              </div>
            ))}
            {(!data.decisions || data.decisions.length === 0) && (
              <p className="text-xs text-slate-500">Run any agent or orchestrator step to emit Decision Intelligence traces.</p>
            )}
          </div>
        </div>
      )}

      {/* TAB 2: EVIDENCE & OCR */}
      {tab === "evidence" && (
        <div className="space-y-6">
          <form onSubmit={handleUpload} className="bg-white p-5 rounded-xl border border-slate-200 flex flex-wrap items-center gap-3">
            <input
              type="file"
              onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
              className="text-sm"
            />
            <button
              type="submit"
              disabled={!uploadFile}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold bg-slate-900 text-white rounded-lg disabled:opacity-40"
            >
              <Upload className="w-4 h-4" />
              Upload to Immutable Vault
            </button>
          </form>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
              <h2 className="text-base font-bold text-slate-900">Evidence Vault Records</h2>
              {data.evidence.map((ev) => (
                <div key={ev.id} className="p-3 border border-slate-200 rounded-lg text-xs space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-slate-900">{ev.filename}</span>
                    <div className="flex items-center gap-1.5">
                      {ev.legal_hold && (
                        <span className="px-2 py-0.5 text-[10px] font-bold bg-rose-100 text-rose-900 border border-rose-300 rounded">
                          LEGAL HOLD PRESERVED
                        </span>
                      )}
                      <span className="px-2 py-0.5 bg-slate-100 rounded">{ev.doc_type}</span>
                    </div>
                  </div>
                  <div className="text-slate-500">SHA-256: {ev.sha256.slice(0, 20)}... · Status: {ev.doc_status}</div>
                  {ev.image_quality_status === "recapture_needed" && (
                    <div className="text-amber-800 font-semibold">Quality: Recapture Recommended</div>
                  )}
                  {ev.prompt_injection_flagged && (
                    <div className="text-red-700 font-bold">SECURITY: Prompt injection quarantined in OCR text!</div>
                  )}
                </div>
              ))}
            </div>

            <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-base font-bold text-slate-900">Extracted Facts & Human Verification</h2>
                <ProvenanceBadge kind="extracted" />
              </div>
              {data.extracted_facts.map((f) => (
                <div key={f.id} className="p-3 border border-slate-200 rounded-lg text-xs space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-bold">{f.field_name}</span>
                    <span className="font-semibold uppercase">{f.validation_status} (conf {f.confidence})</span>
                  </div>
                  <div>Extracted: <code className="bg-slate-100 px-1.5 py-0.5 rounded">{f.extracted_value}</code></div>
                  {f.verified_value && <div>Verified: <strong className="text-emerald-800">{f.verified_value}</strong></div>}
                  <div className="flex gap-2">
                    <input
                      placeholder="Verified / corrected value..."
                      value={factEdits[f.id] ?? f.extracted_value}
                      onChange={(e) => setFactEdits({ ...factEdits, [f.id]: e.target.value })}
                      className="flex-1 px-2 py-1 border border-slate-300 rounded"
                    />
                    <button
                      type="button"
                      onClick={() =>
                        runAction(
                          "Verify Fact",
                          `/api/v1/claims/${claimId}/evidence/${f.evidence_id}/facts/${f.id}`,
                          "PATCH",
                          { verified_value: factEdits[f.id] ?? f.extracted_value, validation_status: "verified" }
                        )
                      }
                      className="px-3 py-1 bg-slate-900 text-white rounded font-semibold"
                    >
                      Confirm
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: DAMAGE & ESTIMATE */}
      {tab === "damage_estimate" && (
        <div className="space-y-6">
          {/* Visual Damage AI Header & Controls */}
          <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-base font-bold text-slate-900 flex items-center gap-1.5">
                    <Camera className="w-4 h-4 text-blue-700" />
                    Visual Damage Assessment AI (10-Step Pipeline)
                  </h2>
                  <ProvenanceBadge kind="ai_assistive" />
                  {data.damage_report?.human_assessor_routing?.route_to_human_assessor && (
                    <span className="px-2.5 py-0.5 text-xs font-bold bg-amber-100 text-amber-950 border border-amber-300 rounded-full">
                      ROUTED TO HUMAN ASSESSOR ({data.damage_report.human_assessor_routing.recommended_role.toUpperCase()})
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-600 mt-1">
                  Component-level confidence calibration: overall photo confidence never forces a beyond-repair decision on an occluded or uncertain part.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => runAction("Visual Damage Assessment", `/api/v1/claims/${claimId}/damage-assessments`)}
                  className="px-3.5 py-2 text-xs font-semibold bg-slate-900 text-white rounded-lg hover:bg-slate-800"
                >
                  Run 10-Step Damage AI
                </button>
              </div>
            </div>

            {/* Quick Accident Photo Upload */}
            <form onSubmit={handleUpload} className="p-3 bg-slate-50 border border-slate-200 rounded-lg flex flex-wrap items-center gap-3 text-xs">
              <span className="font-semibold text-slate-700">Step 1 · Upload Accident Photo:</span>
              <input
                type="file"
                accept="image/*,.txt,.pdf"
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                className="text-xs"
              />
              <button
                type="submit"
                disabled={!uploadFile}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-blue-700 text-white rounded disabled:opacity-40"
              >
                <Upload className="w-3.5 h-3.5" />
                Upload &amp; Validate Photo
              </button>
              <span className="text-slate-500">
                Tip: Include angle in filename (e.g. <code>front_left.jpg</code>, <code>closeup.jpg</code>, <code>dark_blurry.jpg</code>, <code>shadow_bumper.jpg</code>).
              </span>
            </form>

            {/* 10-Step Workflow Strip */}
            {data.damage_report?.visual_workflow_steps && (
              <div className="space-y-2">
                <div className="text-xs font-bold uppercase text-slate-500">10-Step Visual Damage Workflow</div>
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                  {data.damage_report.visual_workflow_steps.map((st) => {
                    const cls =
                      st.status === "needs_human"
                        ? "bg-rose-50 border-rose-300 text-rose-950"
                        : st.status === "warning"
                        ? "bg-amber-50 border-amber-300 text-amber-950"
                        : st.status === "completed"
                        ? "bg-emerald-50 border-emerald-300 text-emerald-950"
                        : "bg-slate-50 border-slate-200 text-slate-600";
                    return (
                      <div key={st.step_key} className={`p-2.5 rounded-lg border text-xs ${cls}`}>
                        <div className="flex items-center justify-between font-bold">
                          <span>Step {st.step_number}</span>
                          <span className="uppercase text-[10px]">{st.status}</span>
                        </div>
                        <div className="font-semibold mt-0.5">{st.title}</div>
                        <div className="text-[11px] opacity-85 mt-1">{st.summary}</div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Guardrail / Human Assessor Routing Banner */}
            {data.damage_report?.human_assessor_routing?.route_to_human_assessor && (
              <div className="p-3.5 bg-amber-50 border border-amber-300 rounded-lg text-xs text-amber-950 space-y-1">
                <div className="font-bold flex items-center gap-1.5">
                  <AlertTriangle className="w-4 h-4 text-amber-700" />
                  Uncertain Case Routed to Human Assessor ({data.damage_report.human_assessor_routing.recommended_role})
                </div>
                {data.damage_report.human_assessor_routing.confidence_guardrail_triggered && (
                  <div className="font-semibold text-rose-800">
                    Component-Confidence Guardrail Triggered: Overall image score is {(data.damage_report.image_quality_confidence * 100).toFixed(0)}%, but one or more components are uncertain (&lt;72% confidence) and withheld from automatic replacement.
                  </div>
                )}
                <ul className="list-disc pl-5 space-y-0.5">
                  {data.damage_report.human_assessor_routing.trigger_reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Vehicle Detection + Bounding Box Visualizer + Structured 10-Field Table */}
            {data.damage_report && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Interactive Bounding Box Region Schematic */}
                <div className="p-4 bg-slate-950 text-slate-100 rounded-xl space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                    <div>
                      <span className="text-slate-400">Detected Vehicle:</span>{" "}
                      <strong className="text-white">
                        {data.damage_report.vehicle?.display_label || "Vehicle"} ({data.damage_report.vehicle?.registration_number})
                      </strong>
                    </div>
                    <span className="px-2 py-0.5 rounded bg-slate-800 text-emerald-300 font-mono">
                      Overall Img: {data.damage_report.overall_image_quality || "good"} ({Math.round(data.damage_report.image_quality_confidence * 100)}%)
                    </span>
                  </div>

                  <div className="relative w-full aspect-[16/9] bg-slate-900 border border-slate-700 rounded-lg overflow-hidden">
                    <svg viewBox="0 0 100 100" className="w-full h-full">
                      {/* Stylized Top-Down / 3/4 Vehicle Wireframe */}
                      <rect x="14" y="16" width="72" height="68" rx="14" fill="#1e293b" stroke="#475569" strokeWidth="1.2" />
                      <rect x="24" y="24" width="52" height="18" rx="5" fill="#0f172a" stroke="#64748b" strokeWidth="0.8" />
                      <rect x="24" y="58" width="52" height="14" rx="4" fill="#0f172a" stroke="#64748b" strokeWidth="0.8" />
                      <text x="50" y="51" textAnchor="middle" fill="#94a3b8" fontSize="3.4" fontFamily="monospace">
                        {data.damage_report.vehicle?.make || "VEHICLE"} · {data.damage_report.vehicle?.model || ""}
                      </text>
                      {/* Bounding Boxes from Evidence Refs */}
                      {data.damage_report.observations.map((obs, idx) => {
                        const bbox = obs.evidence?.[0]?.bbox;
                        const nx = (bbox?.norm_x ?? 0.22 + (idx % 3) * 0.18) * 100;
                        const ny = (bbox?.norm_y ?? 0.35 + Math.floor(idx / 3) * 0.22) * 100;
                        const nw = (bbox?.norm_w ?? 0.22) * 100;
                        const nh = (bbox?.norm_h ?? 0.18) * 100;
                        const stroke =
                          obs.repairability === "uncertain"
                            ? "#f59e0b"
                            : obs.repairability === "replace"
                            ? "#f43f5e"
                            : "#10b981";
                        return (
                          <g key={obs.part_code + idx}>
                            <rect
                              x={nx}
                              y={ny}
                              width={nw}
                              height={nh}
                              fill={stroke}
                              fillOpacity="0.18"
                              stroke={stroke}
                              strokeWidth="1.1"
                              strokeDasharray={obs.repairability === "uncertain" ? "2 1" : undefined}
                              rx="1.5"
                            />
                            <text x={nx + 1.2} y={Math.max(5, ny - 1.2)} fill={stroke} fontSize="3.2" fontWeight="bold">
                              {obs.damaged_component} · {Math.round(obs.component_confidence * 100)}% ({obs.repairability})
                            </text>
                          </g>
                        );
                      })}
                    </svg>
                  </div>
                  <div className="flex flex-wrap gap-3 text-[11px] text-slate-300">
                    <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-emerald-500 inline-block" /> Repair</span>
                    <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-rose-500 inline-block" /> Replace</span>
                    <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-amber-500 inline-block" /> Uncertain (Human Assessor)</span>
                  </div>
                </div>

                {/* Structured 10-Field Assessment Output Table */}
                <div className="border border-slate-200 rounded-xl overflow-hidden">
                  <div className="bg-slate-50 px-3 py-2 border-b border-slate-200 text-xs font-bold text-slate-800 flex items-center justify-between">
                    <span className="flex items-center gap-1.5"><Eye className="w-3.5 h-3.5" /> Structured Damage Assessment</span>
                    <span className="font-mono text-[11px] text-slate-500">{data.damage_report.model_version}</span>
                  </div>
                  <table className="w-full text-xs text-left border-collapse">
                    <tbody className="divide-y divide-slate-100">
                      {(data.damage_report.structured_assessment_table || []).map((row) => (
                        <tr key={row.field}>
                          <th className="p-2 bg-slate-50/70 font-semibold text-slate-700 w-36 align-top">{row.field}</th>
                          <td className="p-2 text-slate-900">
                            <div className="font-medium">{row.value}</div>
                            {row.detail && <div className="text-[11px] text-slate-500">{row.detail}</div>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Cross-Photo Comparison, Inconsistencies, Parts & Labour, Photo Requests */}
            {data.damage_report && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 text-xs">
                <div className="p-3.5 border border-slate-200 rounded-lg space-y-2">
                  <div className="font-bold text-slate-900">Cross-Photo Comparison &amp; Inconsistencies</div>
                  {(data.damage_report.cross_photo_comparison || []).map((cp, i) => (
                    <div key={i} className="p-2 bg-slate-50 rounded border border-slate-200">
                      <div className="flex items-center justify-between font-semibold">
                        <span>{cp.damage_location}</span>
                        <span className={cp.agreement_status === "corroborated" ? "text-emerald-700" : cp.agreement_status === "conflicting" ? "text-rose-700" : "text-amber-700"}>
                          {cp.agreement_status}
                        </span>
                      </div>
                      <div className="text-[11px] text-slate-600 mt-0.5">{cp.notes}</div>
                    </div>
                  ))}
                  {(data.damage_report.inconsistencies || []).map((inc) => (
                    <div key={inc.inconsistency_id} className="p-2 bg-rose-50 border border-rose-200 rounded text-rose-950">
                      <div className="font-bold">[{inc.type}] ({inc.severity})</div>
                      <div>{inc.summary}</div>
                      <div className="text-[11px] mt-0.5 text-rose-800">{inc.resolution_required}</div>
                    </div>
                  ))}
                </div>

                <div className="p-3.5 border border-slate-200 rounded-lg space-y-2">
                  <div className="font-bold text-slate-900">
                    Parts &amp; Labour Pre-Estimate ({data.damage_report.parts_labour_estimate?.rate_card_id})
                  </div>
                  {data.damage_report.parts_labour_estimate && (
                    <div className="grid grid-cols-2 gap-2 p-2.5 bg-slate-50 rounded border border-slate-200">
                      <div><span className="text-slate-500">OEM Parts:</span> <strong className="font-mono">&#8377;{data.damage_report.parts_labour_estimate.parts_oem_total_inr}</strong></div>
                      <div><span className="text-slate-500">OES Alt:</span> <strong className="font-mono">&#8377;{data.damage_report.parts_labour_estimate.parts_oes_total_inr}</strong></div>
                      <div><span className="text-slate-500">Labour:</span> <strong className="font-mono">&#8377;{data.damage_report.parts_labour_estimate.labour_total_inr}</strong></div>
                      <div><span className="text-slate-500">Paint:</span> <strong className="font-mono">&#8377;{data.damage_report.parts_labour_estimate.paint_total_inr}</strong></div>
                      <div className="col-span-2 pt-1 border-t border-slate-200 flex justify-between">
                        <span className="font-bold">Total Baseline:</span>
                        <strong className="font-mono text-slate-900">&#8377;{data.damage_report.parts_labour_estimate.total_recommended_inr}</strong>
                      </div>
                      {Number(data.damage_report.parts_labour_estimate.uncertain_exposure_max_inr) > 0 && (
                        <div className="col-span-2 text-[11px] text-amber-800">
                          Uncertain exposure range: &#8377;{data.damage_report.parts_labour_estimate.uncertain_exposure_min_inr} – &#8377;{data.damage_report.parts_labour_estimate.uncertain_exposure_max_inr}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                <div className="p-3.5 border border-slate-200 rounded-lg space-y-2">
                  <div className="font-bold text-slate-900">
                    Additional Photo Requests ({(data.damage_report.additional_photo_requests || []).length})
                  </div>
                  {(data.damage_report.additional_photo_requests || []).slice(0, 4).map((req, idx) => (
                    <div key={idx} className="p-2 bg-amber-50/70 border border-amber-200 rounded">
                      <div className="flex justify-between font-bold text-amber-950">
                        <span>Angle: {req.angle}</span>
                        <span className="uppercase text-[10px]">{req.priority}</span>
                      </div>
                      <div className="text-slate-700">{req.reason}</div>
                      <div className="text-[11px] text-slate-500 mt-0.5">{req.guidance}</div>
                    </div>
                  ))}
                  {(data.damage_report.additional_photo_requests || []).length === 0 && (
                    <div className="text-emerald-800 bg-emerald-50 p-2 rounded border border-emerald-200">
                      All 6 angles uploaded with good quality.
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Per-Component Damage Observations & Human Assessor Disposition */}
          <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-bold text-slate-900">
                Component-Level Damage Breakdown &amp; Human Assessor Review ({data.damage_assessments.length})
              </h2>
              <ProvenanceBadge kind="ai_assistive" />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {data.damage_assessments.map((d) => {
                const confPct = Math.round(Number(d.confidence) * 100);
                const rep = d.repairability || d.recommended_action;
                const repCls =
                  rep === "uncertain" || rep === "inspect"
                    ? "bg-amber-100 text-amber-950 border-amber-300"
                    : rep === "replace"
                    ? "bg-rose-100 text-rose-900 border-rose-300"
                    : "bg-emerald-100 text-emerald-900 border-emerald-300";
                const factors = (d.confidence_factors || {}) as Record<string, unknown>;
                return (
                  <div key={d.id} className="p-3.5 border border-slate-200 rounded-lg text-xs space-y-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <span className="font-bold text-slate-900 text-sm">{d.component_name}</span>
                        <div className="text-[11px] text-slate-500">
                          Location: <strong>{d.damage_location || "exterior"}</strong> · Severity: <strong>{d.damage_severity || "moderate"}</strong> · Quality: <strong>{d.image_quality || "good"}</strong>
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className={`px-2 py-0.5 border rounded font-bold uppercase text-[10px] ${repCls}`}>
                          {rep}
                        </span>
                        <span className="px-2 py-0.5 bg-indigo-100 text-indigo-900 rounded font-semibold">
                          {d.observation_type}
                        </span>
                      </div>
                    </div>

                    {/* Per-Component Confidence Meter */}
                    <div className="space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-slate-700">Component Confidence: {confPct}% ({d.confidence})</span>
                        <span className="text-slate-600">Reviewer: <strong>{d.reviewer_outcome}</strong></span>
                      </div>
                      <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
                        <div
                          className={`h-full ${confPct >= 80 ? "bg-emerald-600" : confPct >= 65 ? "bg-amber-500" : "bg-rose-600"}`}
                          style={{ width: `${confPct}%` }}
                        />
                      </div>
                      {typeof factors.rationale === "string" && (
                        <div className="text-[11px] text-slate-600">{factors.rationale}</div>
                      )}
                    </div>

                    {d.visible_damage && (
                      <div className="p-2 bg-slate-50 rounded border border-slate-200">
                        <strong>Visible Damage:</strong> {d.visible_damage}
                      </div>
                    )}
                    {d.possible_hidden_damage && (
                      <div className="p-2 bg-amber-50/60 rounded border border-amber-200 text-amber-950">
                        <strong>Possible Hidden Damage (Requires Inspection):</strong> {d.possible_hidden_damage}
                      </div>
                    )}

                    <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-600">
                      <span>
                        Est: Parts &#8377;{d.estimated_parts_inr || "0.00"} · Labour &#8377;{d.estimated_labour_inr || "0.00"} · Paint &#8377;{d.estimated_paint_inr || "0.00"}
                      </span>
                      {(d.evidence_refs || []).length > 0 && (
                        <span className="font-mono">
                          Ref: {d.evidence_refs![0].filename} ({d.evidence_refs![0].angle})
                        </span>
                      )}
                    </div>

                    <div className="text-slate-500">{d.limitations}</div>
                    <div className="flex gap-2 pt-1">
                      <button
                        type="button"
                        onClick={() => runAction("Accept Damage", `/api/v1/claims/${claimId}/damage-assessments/${d.id}`, "PATCH", { reviewer_outcome: "accepted" })}
                        className="px-2.5 py-1 bg-emerald-700 text-white rounded font-semibold"
                      >
                        Accept
                      </button>
                      <button
                        type="button"
                        onClick={() => runAction("Reject Damage", `/api/v1/claims/${claimId}/damage-assessments/${d.id}`, "PATCH", { reviewer_outcome: "rejected" })}
                        className="px-2.5 py-1 border border-slate-300 rounded"
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {data.estimates.map((est) => (
            <div key={est.id} className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-base font-bold text-slate-900">
                  Garage Estimate v{est.version} — Claimed &#8377;{est.total_claimed_inr} · Recommended/Approved &#8377;{est.total_approved_inr}
                </h3>
                <StatusPill status={est.status} />
              </div>
              {est.anomalies.length > 0 && (
                <div className="p-3 bg-amber-50 border border-amber-200 rounded text-xs text-amber-950 space-y-1">
                  {est.anomalies.map((a, idx) => (
                    <div key={idx}><strong>[{a.type}]</strong> {a.message}</div>
                  ))}
                </div>
              )}
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left border-collapse">
                  <thead className="bg-slate-50 border-b border-slate-200">
                    <tr>
                      <th className="p-2">Part / Line</th>
                      <th className="p-2">Claimed</th>
                      <th className="p-2">Rate Card</th>
                      <th className="p-2">Approved</th>
                      <th className="p-2">Variance Flag</th>
                      <th className="p-2">Review</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {est.lines.map((ln) => (
                      <tr key={ln.id}>
                        <td className="p-2 font-medium">{ln.description} ({ln.line_type})</td>
                        <td className="p-2 font-mono">&#8377;{ln.unit_price_inr}</td>
                        <td className="p-2 font-mono">{ln.rate_card_price_inr ? `₹${ln.rate_card_price_inr}` : "-"}</td>
                        <td className="p-2 font-mono font-bold">&#8377;{ln.approved_amount_inr || "0.00"}</td>
                        <td className="p-2 text-amber-800">{ln.variance_flag || "OK"}</td>
                        <td className="p-2 flex gap-1">
                          <button
                            type="button"
                            onClick={() => runAction("Accept Line", `/api/v1/claims/${claimId}/estimates/${est.id}/lines/${ln.id}`, "PATCH", { reviewer_status: "accepted" })}
                            className="px-2 py-0.5 bg-slate-900 text-white rounded"
                          >
                            Accept
                          </button>
                          <button
                            type="button"
                            onClick={() => runAction("Reject Line", `/api/v1/claims/${claimId}/estimates/${est.id}/lines/${ln.id}`, "PATCH", { reviewer_status: "rejected" })}
                            className="px-2 py-0.5 border border-slate-300 rounded"
                          >
                            Reject
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* TAB 4: FRAUD / SIU */}
      {tab === "siu" && (
        <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-4">
          {data.fraud_alerts_restricted ? (
            <div className="text-sm text-amber-900 bg-amber-50 p-4 rounded-lg border border-amber-200">
              SIU investigation files and entity graphs are restricted to SIU Investigators, Managers, and Auditors.
            </div>
          ) : (
            <>
              <h2 className="text-base font-bold text-slate-900">SIU Indicators & Entity Graph</h2>
              {data.fraud_alerts.map((a) => (
                <div key={a.id} className="p-3 border border-slate-200 rounded-lg text-xs space-y-1">
                  <div className="font-bold">{a.indicator_code} — {a.title} ({a.status})</div>
                  <div>Evidence: {a.evidence_summary}</div>
                  <div className="text-emerald-800">Benign explanation: {a.benign_explanation}</div>
                </div>
              ))}
              {entityGraph && (
                <pre className="text-xs bg-slate-50 p-3 rounded border border-slate-200 overflow-x-auto">
                  {JSON.stringify(entityGraph, null, 2)}
                </pre>
              )}
            </>
          )}
        </div>
      )}

      {/* TAB 5: SETTLEMENT & PAYMENT */}
      {tab === "settlement" && (
        <div className="space-y-6">
          <div className="bg-white p-5 rounded-xl border border-slate-200 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-bold text-slate-900">Deterministic Settlement & Maker-Checker Desk</h2>
              <p className="text-xs text-slate-600">
                Calculated using Python Decimal arithmetic, IMT depreciation rules, and policy add-ons.
              </p>
            </div>
            <button
              type="button"
              onClick={() => runAction("Recommend Settlement", `/api/v1/claims/${claimId}/settlement-recommendations`, "POST", { requested_pathway: "cashless" })}
              className="px-4 py-2 text-xs font-semibold bg-slate-900 text-white rounded-lg"
            >
              Generate Deterministic Settlement Recommendation
            </button>
          </div>

          {data.settlements.map((s) => (
            <div key={s.id} className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-base font-bold text-slate-900">
                  Settlement v{s.version} ({s.pathway}) — Net Payable: &#8377;{s.net_payable_inr}
                </h3>
                <div className="flex items-center gap-2">
                  <ProvenanceBadge kind="human_decision" />
                  <StatusPill status={s.approval_status} />
                </div>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-xs bg-slate-50 p-3 rounded border border-slate-200">
                <div><span className="text-slate-500">Gross:</span> <strong>&#8377;{s.gross_assessed_inr}</strong></div>
                <div><span className="text-slate-500">Depreciation:</span> <strong>-&#8377;{s.depreciation_deduction_inr}</strong></div>
                <div><span className="text-slate-500">Zero-Dep Waiver:</span> <strong className="text-emerald-700">&#8377;{s.addon_waiver_inr}</strong></div>
                <div><span className="text-slate-500">Compulsory Excess:</span> <strong>-&#8377;{s.compulsory_excess_inr}</strong></div>
                <div><span className="text-slate-500">Net Payable:</span> <strong className="text-slate-900">&#8377;{s.net_payable_inr}</strong></div>
              </div>
              <div className="text-xs text-slate-600">
                <strong>Policy Citations:</strong> {s.policy_citations.join(" | ")}
              </div>

              {s.approval_status === "approved" && (
                <div className="flex flex-wrap gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() =>
                      runAction("Initiate Payment", `/api/v1/claims/${claimId}/payments`, "POST", {
                        settlement_id: s.id,
                        idempotency_key: `ui-pay-${s.id}`,
                        payee_type: "garage",
                        payee_name: "Apex Motors Cashless Hub",
                        simulate_timeout: false,
                      })
                    }
                    className="px-3 py-1.5 text-xs font-semibold bg-emerald-700 text-white rounded"
                  >
                    Release Idempotent Payment (Finance Role)
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      runAction("Finance Agent Controlled Release", `/api/v1/claims/${claimId}/payments/agent-release`, "POST", {
                        settlement_id: s.id,
                        idempotency_key: `agent-ui-pay-${s.id}`,
                        payee_type: "garage",
                        payee_name: "Apex Motors Cashless Hub",
                        simulate_timeout: false,
                      })
                    }
                    className="px-3 py-1.5 text-xs font-semibold bg-blue-700 text-white rounded"
                  >
                    Agent-Controlled Approved Payout
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      runAction("Simulate Timeout Payment", `/api/v1/claims/${claimId}/payments`, "POST", {
                        settlement_id: s.id,
                        idempotency_key: `ui-pay-to-${s.id}`,
                        payee_type: "garage",
                        payee_name: "Apex Motors Cashless Hub",
                        simulate_timeout: true,
                      })
                    }
                    className="px-3 py-1.5 text-xs font-semibold border border-amber-400 bg-amber-50 text-amber-950 rounded"
                  >
                    Simulate Payment Timeout
                  </button>
                </div>
              )}
            </div>
          ))}

          {data.settlement_scenarios && data.settlement_scenarios.length > 0 && (
            <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
              <h3 className="text-base font-bold text-slate-900">
                Multi-Scenario Settlement Comparison (Depreciation, Deductibles, Salvage &amp; IDV Limits)
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left border-collapse">
                  <thead className="bg-slate-50 border-b border-slate-200">
                    <tr>
                      <th className="p-2">Scenario</th>
                      <th className="p-2">Pathway</th>
                      <th className="p-2">Gross</th>
                      <th className="p-2">Dep</th>
                      <th className="p-2">Waiver</th>
                      <th className="p-2">Deductibles</th>
                      <th className="p-2">Salvage</th>
                      <th className="p-2">Net Payable</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.settlement_scenarios.map((sc) => (
                      <tr key={sc.scenario_code} className={sc.recommended ? "bg-emerald-50/50 font-semibold" : ""}>
                        <td className="p-2">
                          <div>{sc.label}</div>
                          <div className="text-[11px] text-slate-500 font-normal">{sc.rationale}</div>
                        </td>
                        <td className="p-2">{sc.pathway}</td>
                        <td className="p-2 font-mono">&#8377;{sc.gross_assessed_inr}</td>
                        <td className="p-2 font-mono">&#8377;{sc.depreciation_deduction_inr}</td>
                        <td className="p-2 font-mono text-emerald-700">&#8377;{sc.addon_waiver_inr}</td>
                        <td className="p-2 font-mono">&#8377;{sc.deductibles_total_inr}</td>
                        <td className="p-2 font-mono">&#8377;{sc.salvage_deduction_inr}</td>
                        <td className="p-2 font-mono font-bold">&#8377;{sc.net_payable_inr}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {data.approvals.length > 0 && (
            <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
              <h3 className="text-base font-bold text-slate-900">Maker-Checker Approvals</h3>
              {data.approvals.map((a) => (
                <div key={a.id} className="p-3 border border-slate-200 rounded-lg text-xs flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <strong>{a.action_type}</strong> · &#8377;{a.amount_inr} · Decision: <strong>{a.decision}</strong>
                    <div className="text-slate-500">{a.rationale}</div>
                  </div>
                  {a.decision === "pending" && (
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => runAction("Approve Settlement", `/api/v1/claims/${claimId}/approvals`, "POST", {
                          approval_id: a.id,
                          decision: "approved",
                          rationale: "Checker verified calculation & policy wording",
                        })}
                        className="px-3 py-1.5 bg-emerald-700 text-white font-semibold rounded"
                      >
                        Approve (Different Checker)
                      </button>
                      <button
                        type="button"
                        onClick={() => runAction("Return Settlement", `/api/v1/claims/${claimId}/approvals`, "POST", {
                          approval_id: a.id,
                          decision: "returned",
                          rationale: "Needs further estimate verification",
                        })}
                        className="px-3 py-1.5 border border-slate-300 rounded"
                      >
                        Return
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {data.payments.length > 0 && (
            <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
              <h3 className="text-base font-bold text-slate-900">Payments & Safe Reconciliation</h3>
              {data.payments.map((p) => (
                <div key={p.id} className="p-3 border border-slate-200 rounded-lg text-xs flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <strong>{p.payee_name}</strong> ({p.bank_account_masked}) · &#8377;{p.amount_inr} · Status: <strong>{p.status}</strong>
                    <div className="text-slate-500">Ref: {p.gateway_reference}</div>
                  </div>
                  {p.status === "timeout_reconcile_pending" && (
                    <button
                      type="button"
                      onClick={() => runAction("Safe Reconcile", `/api/v1/claims/${claimId}/payments/${p.id}/reconcile`, "POST")}
                      className="px-3 py-1.5 bg-slate-900 text-white font-semibold rounded"
                    >
                      Reconcile Safely (No Double Payout)
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* TAB 6: AUDIT TRAIL */}
      {tab === "audit" && (
        <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
          <h2 className="text-base font-bold text-slate-900">Immutable Audit Ledger</h2>
          <div className="space-y-2">
            {data.audit_events.map((au) => (
              <div key={au.id} className="p-3 border border-slate-200 rounded-lg text-xs flex flex-wrap justify-between gap-2">
                <div>
                  <span className="font-bold text-slate-900">{au.action}</span> · Role: {au.actor_role}
                </div>
                <div className="font-mono text-slate-500">
                  hash: {au.after_hash || "-"} · {au.created_at.slice(0, 19)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
