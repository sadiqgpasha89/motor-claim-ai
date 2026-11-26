"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AlertTriangle, CheckCircle2, ShieldAlert, Upload } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { ProvenanceBadge, SlaBadge, StatusPill } from "@/components/Badges";

type TabId = "overview" | "evidence" | "damage_estimate" | "siu" | "settlement" | "audit";

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

  const loadClaim = useCallback(async () => {
    if (!token || !claimId) return;
    setErrMsg(null);
    try {
      const res = await apiFetch<Claim360>(`/api/v1/claims/${claimId}`, {}, token);
      setData(res);
      if (!res.fraud_alerts_restricted) {
        apiFetch<Record<string, unknown>>(`/api/v1/claims/${claimId}/entity-graph`, {}, token)
          .then(setEntityGraph)
          .catch(() => {});
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
            className={`px-4 py-2 text-sm font-medium whitespace-nowrap border-b-2 ${
              tab === id ? "border-slate-900 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-900"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* TAB 1: OVERVIEW */}
      {tab === "overview" && (
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
              Bounded agents execute within workflow rules; human approvals remain mandatory.
            </p>
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
              onClick={() => runAction("Assign Surveyor", `/api/v1/claims/${claimId}/surveyor-assignments`, "POST", {})}
              className="w-full py-2 px-3 text-xs font-semibold bg-white border border-slate-300 text-slate-900 rounded-lg hover:bg-slate-50 text-left"
            >
              3. Auto-Assign Verified Surveyor
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
              onClick={() => runAction("Close Claim", `/api/v1/claims/${claimId}/close`)}
              className="w-full py-2 px-3 text-xs font-semibold bg-emerald-800 text-white rounded-lg hover:bg-emerald-900 text-left"
            >
              7. QA Check & Close Claim
            </button>
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
