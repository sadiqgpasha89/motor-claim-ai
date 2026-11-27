"use client";

import React, { useState } from "react";

export interface ClaimExecutionData {
  claim: {
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
    missing_documents: string[];
    coverage_factsheet?: Record<string, unknown> | null;
    triage_summary?: Record<string, unknown> | null;
    ev_battery_impacted: boolean;
    injury_or_fatality: boolean;
    assigned_surveyor_id?: string | null;
    assigned_garage_id?: string | null;
  };
  policy: {
    policy_number: string;
    status: string;
    idv_inr: string;
    addons: Record<string, boolean>;
  } | null;
  evidence: Array<{
    id: string;
    doc_type: string;
    doc_status: string;
    filename: string;
    sha256: string;
    prompt_injection_flagged: boolean;
    image_quality_status?: string;
  }>;
  extracted_facts: Array<{
    id: string;
    field_name: string;
    extracted_value: string;
    verified_value?: string;
    confidence: string;
    validation_status: string;
  }>;
  damage_assessments: Array<{
    id: string;
    component_name: string;
    observation_type: string;
    recommended_action: string;
    confidence: string;
    reviewer_outcome: string;
  }>;
  estimates: Array<{
    id: string;
    version: number;
    status: string;
    total_claimed_inr: string;
    total_approved_inr: string;
    anomalies: Array<{ type: string; message: string }>;
  }>;
  surveys: Array<{
    id: string;
    status: string;
    signed_by_surveyor: boolean;
  }>;
  fraud_alerts_restricted: boolean;
  fraud_alerts: Array<{
    id: string;
    indicator_code: string;
    title: string;
    severity_band: string;
    status: string;
  }>;
  settlements: Array<{
    id: string;
    version: number;
    gross_assessed_inr: string;
    net_payable_inr: string;
    approval_status: string;
    policy_citations: string[];
  }>;
  approvals: Array<{
    id: string;
    decision: string;
    maker_user_id: string;
    checker_user_id?: string;
  }>;
  payments: Array<{
    id: string;
    amount_inr: string;
    status: string;
    gateway_reference?: string;
  }>;
  tasks?: Array<{
    id: string;
    task_type: string;
    title: string;
    status: string;
    assigned_role: string;
    created_by_agent: string;
  }>;
  decisions?: Array<{
    id: string;
    agent_name: string;
    routing_outcome: string;
    reason_codes: string[];
    policy_rule_refs: string[];
    confidence: string;
    explanation: string;
  }>;
  orchestration_summary?: {
    current_state?: string;
    canonical_state?: string;
    triage_track?: string | null;
    paused?: boolean;
    pause_reason?: string | null;
    parallel_waves?: Array<{ wave_id: string; wave_name: string; agents: string[]; wall_duration_ms: number }>;
    scheduled_tasks?: Array<{ task_key: string; execution_mode: string; status: string }>;
    dlq_items?: Array<{ id: string; status: string }>;
    stage_statuses: Record<string, string>;
    rework_queue: Array<{ id: string; from_agent: string; to_agent: string; reason_code: string; status: string }>;
    escalations: Array<{ id: string; agent_name: string; reason: string; status: string }>;
  };
}

interface StageCard {
  key: string;
  index: number;
  agent: string;
  primaryAgentKey: string;
  status: string;
  tone: "green" | "amber" | "rose" | "slate" | "blue";
  evidence: string;
  output: string;
  confidence: string;
  rules: string;
  nextAction: string;
}

export function ClaimExecutionChain({ data }: { data: ClaimExecutionData }) {
  const c = data.claim;
  const hasMismatch = data.extracted_facts.some((f) => f.validation_status === "mismatch");
  const hasInjection = data.evidence.some((e) => e.prompt_injection_flagged);
  const hasRecapture = data.evidence.some((e) => e.image_quality_status === "recapture_needed");
  const latestEst = data.estimates[data.estimates.length - 1];
  const latestSettlement = data.settlements[0];
  const latestPayment = data.payments[0];
  const latestSurvey = data.surveys[0];

  const covConf =
    c.coverage_factsheet && typeof c.coverage_factsheet["confidence"] === "number"
      ? `${Math.round((c.coverage_factsheet["confidence"] as number) * 100)}%`
      : c.coverage_factsheet
      ? "0.91"
      : "Pending";

  const triageConf =
    c.triage_summary && typeof c.triage_summary["confidence"] === "number"
      ? `${Math.round((c.triage_summary["confidence"] as number) * 100)}%`
      : "0.93 (Rule)";

  const openAlerts = data.fraud_alerts.filter((a) =>
    ["new", "assigned", "investigating"].includes(a.status)
  );

  const stages: StageCard[] = [
    {
      key: "FNOL",
      index: 1,
      agent: "fnol_concierge",
      primaryAgentKey: "fnol_concierge",
      status: "COMPLETED",
      tone: "green",
      evidence: `${c.claim_number} · ${c.missing_documents.length} missing docs`,
      output: `Registered (${c.claim_type}) without blocking; checklist issued`,
      confidence: "94% (HIGH)",
      rules: "IN-IRDAI-MC-2024 (No doc-block)",
      nextAction:
        c.missing_documents.length > 0
          ? `Upload: ${c.missing_documents.join(", ")}`
          : "Evidence uploaded -> Document & Coverage validation",
    },
    {
      key: "Validation",
      index: 2,
      agent: "document_intelligence + coverage_intelligence",
      primaryAgentKey: "coverage_intelligence",
      status: hasInjection || hasMismatch ? "NEEDS_HUMAN" : c.coverage_factsheet ? "COMPLETED" : "IN_PROGRESS",
      tone: hasInjection ? "rose" : hasMismatch || hasRecapture ? "amber" : c.coverage_factsheet ? "green" : "blue",
      evidence: `${data.evidence.length} vault files · ${data.extracted_facts.length} facts · ${
        data.policy ? data.policy.policy_number : "Unmatched Policy"
      }`,
      output: hasInjection
        ? "Prompt injection quarantined in OCR text"
        : hasMismatch
        ? "RC/Policy mismatch requires human fact correction"
        : c.coverage_factsheet
        ? "Policy period active & wording clauses retrieved"
        : "Run Coverage Check to retrieve RAG clauses",
      confidence: hasMismatch || hasInjection ? "52% (LOW)" : covConf,
      rules: "sanitizer.py · POL-WORDING-PC/EV",
      nextAction:
        hasMismatch || hasInjection
          ? "Verify extracted facts in Evidence tab"
          : "Run Claim Triage",
    },
    {
      key: "Triage",
      index: 3,
      agent: "claim_triage",
      primaryAgentKey: "claim_triage",
      status: c.triage_summary || c.status !== "REGISTERED" ? "COMPLETED" : "PENDING",
      tone: c.ev_battery_impacted || c.injury_or_fatality ? "amber" : "green",
      evidence: `Loss ₹${Number(c.estimated_loss_inr).toLocaleString("en-IN")} vs ₹50,000 threshold`,
      output: `Queue: ${c.queue_name} (${c.severity_band}) · Survey=${c.requires_mandatory_survey ? "YES" : "NO"}`,
      confidence: triageConf,
      rules: "IN-IRDAI-MC-2024 ₹50k Survey Rule",
      nextAction: c.requires_mandatory_survey
        ? "Assign verified surveyor & run Damage AI"
        : "Fast-track AI Damage Assessment",
    },
    {
      key: "Assessment",
      index: 4,
      agent: "damage_assessment + estimate_validation",
      primaryAgentKey: "estimate_validation",
      status: latestEst?.anomalies?.length
        ? "FLAGGED_ANOMALY"
        : data.damage_assessments.length > 0 || latestEst
        ? "COMPLETED"
        : "PENDING",
      tone: latestEst?.anomalies?.length ? "amber" : data.damage_assessments.length > 0 ? "green" : "slate",
      evidence: `${data.damage_assessments.length} vision obs · ${data.estimates.length} estimate(s)`,
      output: latestEst
        ? `Claimed ₹${latestEst.total_claimed_inr} -> Rec ₹${latestEst.total_approved_inr} (${latestEst.anomalies.length} anomalies)`
        : "Run Damage Vision & submit garage estimate",
      confidence: latestEst?.anomalies?.length ? "74% (MEDIUM)" : data.damage_assessments.length > 0 ? "88% (HIGH)" : "-",
      rules: "RC-IN-2026-DEMO-V1 (12% Variance Cap)",
      nextAction: latestEst?.anomalies?.length
        ? "Adjuster/Surveyor reviews flagged estimate lines"
        : "Proceed to Investigation & Survey",
    },
    {
      key: "Investigation",
      index: 5,
      agent: "fraud_intelligence + provider_coordination",
      primaryAgentKey: "provider_coordination",
      status: openAlerts.length > 0 ? "SIU_REVIEW" : latestSurvey?.signed_by_surveyor ? "COMPLETED" : latestSurvey ? "IN_PROGRESS" : "PENDING",
      tone: openAlerts.length > 0 ? "amber" : latestSurvey?.signed_by_surveyor ? "green" : "blue",
      evidence: `${data.fraud_alerts_restricted ? "SIU Restricted" : `${data.fraud_alerts.length} alert(s)`} · Survey: ${latestSurvey?.status || "unassigned"}`,
      output:
        openAlerts.length > 0
          ? `${openAlerts.length} open SIU lead(s) (blocks L1 approval until dispositioned)`
          : latestSurvey?.signed_by_surveyor
          ? "Signed survey report received & SIU cleared"
          : "Coordinate verified IIISLA surveyor & run fraud signals",
      confidence: openAlerts.length > 0 ? "81% (MEDIUM)" : "92% (HIGH)",
      rules: "IRDAI Fraud Due Process · 15d Survey SLA",
      nextAction:
        openAlerts.length > 0
          ? "SIU Investigator dispositions alert"
          : "Submit survey report -> Calculate Settlement",
    },
    {
      key: "Settlement",
      index: 6,
      agent: "settlement_recommendation + Human DoA",
      primaryAgentKey: "settlement_recommendation",
      status: latestSettlement ? latestSettlement.approval_status.toUpperCase() : "PENDING",
      tone:
        latestSettlement?.approval_status === "approved"
          ? "green"
          : latestSettlement
          ? "amber"
          : "slate",
      evidence: latestSettlement
        ? `Gross ₹${latestSettlement.gross_assessed_inr} -> Net ₹${latestSettlement.net_payable_inr}`
        : "No settlement generated yet",
      output: latestSettlement
        ? `Deterministic Decimal calc (${latestSettlement.policy_citations.length} clauses cited)`
        : "Generate Decimal settlement recommendation",
      confidence: latestSettlement ? "96% + DoA Gate" : "-",
      rules: "IN-MOTOR-DEPRECIATION-2024 · IN-DOA-MATRIX-2026",
      nextAction:
        latestSettlement?.approval_status === "approved"
          ? "Finance releases idempotent payout"
          : "Independent Checker DoA approval required",
    },
    {
      key: "Payment",
      index: 7,
      agent: "Payment & Reconciliation Services",
      primaryAgentKey: "settlement_recommendation",
      status: latestPayment ? latestPayment.status.toUpperCase() : "PENDING",
      tone:
        latestPayment?.status === "confirmed"
          ? "green"
          : latestPayment?.status === "timeout_reconcile_pending"
          ? "rose"
          : "slate",
      evidence: latestPayment
        ? `₹${latestPayment.amount_inr} (${latestPayment.gateway_reference || "pending"})`
        : "Awaiting settlement approval",
      output:
        latestPayment?.status === "confirmed"
          ? "UTR confirmed cleanly"
          : latestPayment?.status === "timeout_reconcile_pending"
          ? "Gateway timed out; locked against double payout"
          : "Finance role initiates penny-drop & payment",
      confidence: latestPayment ? "100% (Deterministic)" : "-",
      rules: "Idempotency-Key · Finance Role Gate",
      nextAction:
        latestPayment?.status === "timeout_reconcile_pending"
          ? "Click Reconcile Safely"
          : latestPayment?.status === "confirmed"
          ? "Proceed to QA & Closure"
          : "Release payment after approval",
    },
    {
      key: "Closure",
      index: 8,
      agent: "qa_compliance + customer_communication",
      primaryAgentKey: "qa_compliance",
      status: c.status === "CLOSED" ? "CLOSED" : "GATED",
      tone: c.status === "CLOSED" ? "green" : "slate",
      evidence: `Claim State: ${c.status}`,
      output:
        c.status === "CLOSED"
          ? "All QA controls passed; audit retained"
          : "Requires confirmed payment & zero open grievances",
      confidence: c.status === "CLOSED" ? "97% (HIGH)" : "-",
      rules: "IN-IRDAI-MC-2024 Pre-Closure Audit",
      nextAction: c.status === "CLOSED" ? "Archived" : c.next_expected_action,
    },
  ];

  const [selectedIdx, setSelectedIdx] = useState(0);
  const selected = stages[selectedIdx] || stages[0];
  const matchedDecision = (data.decisions || []).find(
    (d) => d.agent_name === selected.primaryAgentKey
  );
  const openTasksCount = (data.tasks || []).filter((t) => t.status === "open").length;
  const openReworkCount = (data.orchestration_summary?.rework_queue || []).filter(
    (r) => r.status === "open"
  ).length;

  const toneClasses: Record<StageCard["tone"], string> = {
    green: "bg-emerald-50 border-emerald-300 text-emerald-900",
    amber: "bg-amber-50 border-amber-300 text-amber-950",
    rose: "bg-rose-50 border-rose-300 text-rose-900",
    blue: "bg-blue-50 border-blue-300 text-blue-900",
    slate: "bg-slate-50 border-slate-200 text-slate-700",
  };

  return (
    <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-bold text-slate-900">
            Claim Orchestration Engine — Deterministic State &amp; Execution Chain
          </h2>
          <p className="text-xs text-slate-500">
            Orchestrator owns state transitions (<code>{data.orchestration_summary?.canonical_state || c.status}</code>
            {data.orchestration_summary?.triage_track ? ` · Track: ${data.orchestration_summary.triage_track}` : ""}
            {data.orchestration_summary?.paused ? " · PAUSED" : ""}), parallel waves, retries, DLQ, and human gates.
          </p>
        </div>
        <span className="text-xs font-semibold text-slate-600">
          {data.orchestration_summary?.parallel_waves?.length
            ? `${data.orchestration_summary.parallel_waves.length} Parallel Wave(s) · `
            : ""}
          SUBMITTED &rarr; REGISTERED &rarr; VALIDATION &rarr; TRIAGE &rarr; ASSESSMENT &rarr; ESTIMATE &rarr; APPROVAL &rarr; PAYMENT &rarr; CLOSED
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2">
        {stages.map((st, idx) => (
          <button
            key={st.key}
            type="button"
            onClick={() => setSelectedIdx(idx)}
            className={`text-left p-2.5 rounded-lg border transition-all ${toneClasses[st.tone]} ${
              idx === selectedIdx ? "ring-2 ring-slate-900" : "hover:opacity-90"
            }`}
          >
            <div className="text-[10px] font-bold uppercase opacity-75">0{st.index}</div>
            <div className="text-xs font-extrabold mt-0.5">{st.key}</div>
            <div className="text-[10px] font-semibold mt-1 truncate">{st.status}</div>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 p-4 bg-slate-50 rounded-lg border border-slate-200 text-xs">
        <div>
          <div className="text-[10px] font-bold uppercase text-slate-500">Stage &amp; Agent / Service</div>
          <div className="font-bold text-slate-900 mt-0.5">
            {selected.index}. {selected.key} (<code>{selected.agent}</code>)
          </div>
          <div className="text-slate-600 mt-2">
            <strong>Status:</strong> {selected.status} · <strong>Confidence:</strong> {selected.confidence}
          </div>
        </div>
        <div>
          <div className="text-[10px] font-bold uppercase text-slate-500">Evidence &amp; Agent Output</div>
          <div className="text-slate-800 mt-0.5">{selected.output}</div>
          <div className="text-slate-600 mt-1">
            <strong>Evidence:</strong> {selected.evidence}
          </div>
        </div>
        <div>
          <div className="text-[10px] font-bold uppercase text-slate-500">Rules Applied &amp; Next Action</div>
          <div className="text-slate-700 mt-0.5">
            <strong>Rules:</strong> {selected.rules}
          </div>
          <div className="text-slate-900 font-semibold mt-1">
            <strong>Next:</strong> {selected.nextAction}
          </div>
          {(openTasksCount > 0 || openReworkCount > 0) && (
            <div className="text-[11px] font-semibold text-amber-800 mt-1">
              Active Tasks: {openTasksCount} · Open Rework: {openReworkCount}
            </div>
          )}
        </div>
      </div>

      {matchedDecision && (
        <div className="p-3 bg-indigo-50 border border-indigo-200 rounded-lg text-xs space-y-1">
          <div className="flex flex-wrap items-center justify-between gap-2 font-bold text-indigo-950">
            <span>
              Decision Intelligence ({matchedDecision.agent_name}) &rarr;{" "}
              <code>{matchedDecision.routing_outcome}</code>
            </span>
            <span className="font-mono">
              {matchedDecision.reason_codes.join(", ")}
            </span>
          </div>
          <div className="text-indigo-900">{matchedDecision.explanation}</div>
          <div className="text-indigo-700">
            <strong>Rules:</strong> {matchedDecision.policy_rule_refs.join(" | ")}
          </div>
        </div>
      )}
    </div>
  );
}
