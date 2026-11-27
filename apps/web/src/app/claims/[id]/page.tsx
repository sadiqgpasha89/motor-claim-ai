"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AlertTriangle, CheckCircle2, ShieldAlert, Upload } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { ProvenanceBadge, SlaBadge, StatusPill } from "@/components/Badges";
import { ClaimExecutionChain } from "@/components/ClaimExecutionChain";

type TabId = "overview" | "orchestration" | "decisions" | "evidence" | "damage_estimate" | "siu" | "settlement" | "audit";

interface Claim360 {
  claim: Record<string, unknown> & {
    id: string;
    claim_number: string;
    status: string;
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
    ev_battery_impacted: boolean;
    injury_or_fatality: boolean;
  };
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
  damage_assessments: Array<{
    id: string;
    component_name: string;
    part_code?: string;
    damage_class: string;
    observation_type: string;
    recommended_action: string;
    confidence: string;
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
    status: string;
    report_due_at: string;
    signed_by_surveyor: boolean;
    report_summary?: Record<string, unknown>;
  }>;
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
              {data.sla_timers[0] && <SlaBadge status={data.sla_timers[0].status} />}
              {c.ev_battery_impacted && (
                <span className="px-2 py-0.5 text-xs font-bold bg-purple-100 text-purple-900 rounded">
                  EV HIGH-VOLTAGE SAFETY
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
            ["orchestration", `Orchestration & Actions (${data.tasks?.length || 0})`],
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
                    <span className="px-2 py-0.5 bg-slate-100 rounded">{ev.doc_type}</span>
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
          <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-bold text-slate-900">Damage Observations</h2>
              <ProvenanceBadge kind="ai_assistive" />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {data.damage_assessments.map((d) => (
                <div key={d.id} className="p-3 border border-slate-200 rounded-lg text-xs space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-slate-900">{d.component_name}</span>
                    <span className="px-2 py-0.5 bg-indigo-100 text-indigo-900 rounded font-semibold">
                      {d.observation_type}
                    </span>
                  </div>
                  <div>Action: <strong>{d.recommended_action.toUpperCase()}</strong> · Conf: {d.confidence} · Outcome: <strong>{d.reviewer_outcome}</strong></div>
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
              ))}
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
