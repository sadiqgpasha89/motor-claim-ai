"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

interface WorkflowNode {
  order: number;
  agent_name: string;
  display_name: string;
  stage: string;
  depends_on: string[];
  status: string;
  last_outcome: string | null;
  last_latency_ms: number | null;
  last_confidence: number | null;
}

interface TimelineItem {
  at: string;
  kind: string;
  title: string;
  detail: string;
}

interface Trace {
  id: string;
  agent_name: string;
  agent_version: string;
  model_name: string;
  prompt_version: string;
  outcome: string;
  latency_ms: number;
  retry_count: number;
  confidence: number | null;
  cost_inr: string;
  final_action: string;
  token_usage: { total: number };
  tool_calls: { tool: string; status: string }[];
  human_intervention: { required: boolean; resolved: boolean } | null;
}

interface Complexity {
  score: number;
  band: string;
  drivers: { driver: string; points: number; why: string }[];
  expected_handling_hours: number;
  expected_human_touchpoints: number;
  recommended_skill: string;
  disclaimer: string;
}

interface SlaPrediction {
  [key: string]: unknown;
}

interface Analysis {
  repair_replace: { components: { part_code: string; decision: string; confidence: number; human_review_required: boolean; reasons: string[] }[] } | null;
  benchmark: { city_tier: string; flagged_lines: number; lines: { part_code: string; line_type: string; flags: string[] }[] } | null;
  fusion: { fused_confidence: number; agreed_zones: string[]; contradictions: { message: string }[]; human_review_required: boolean } | null;
}

interface Claim360 {
  claim_id: string;
  intelligence: { complexity: Complexity; sla_risk: { predictions: SlaPrediction[] } };
  overview: {
    claim_number: string;
    status: string;
    canonical_state: string;
    claim_type: string;
    risk_tier: string;
    operational_path: string;
    estimated_loss_inr: string;
    queue_name: string;
    paused: boolean;
    policy: { policy_number: string; idv_inr: string; status: string } | null;
    vehicle: { registration: string; make: string; model: string; year: number; is_ev: boolean } | null;
    customer: { name: string; phone: string; email: string } | null;
    sla: { stage: string; status: string; due_at: string }[];
  };
  answers: {
    what_has_happened: string[];
    what_is_happening_now: string;
    what_is_blocked: string[];
    why_blocked: string[];
    what_did_ai_do: string[];
    what_did_ai_find: string[];
    next_action: string;
    do_i_need_to_act: { required: boolean; role: string; reason: string };
  };
  blockers: { code: string; why: string; owner: string }[];
  workflow: WorkflowNode[];
  execution_timeline: TimelineItem[];
  agent_executions: Trace[];
  agent_summary: { executions: number; total_cost_inr: string; total_tokens: number; human_interventions: number };
  evidence: {
    documents: { id: string; doc_type: string; status: string; filename: string; sha256: string; malware_scan: string }[];
    extracted_facts: { field: string; value: string; confidence: number; validation_status: string }[];
  };
  settlement_and_approvals: {
    settlements: { id: string; gross_assessed_inr: string; net_payable_inr: string; approval_status: string }[];
    approvals: { id: string; action_type: string; amount_inr: string; decision: string }[];
    payments: { id: string; status: string; amount_inr: string }[];
  };
}

const outcomeCls = (o: string | null) =>
  o === "success"
    ? "bg-emerald-100 text-emerald-900 border-emerald-300"
    : o === "failed" || o === "timeout"
    ? "bg-red-100 text-red-900 border-red-300"
    : o
    ? "bg-amber-100 text-amber-900 border-amber-300"
    : "bg-slate-100 text-slate-700 border-slate-300";

function List({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <p className="text-sm text-slate-500">{empty}</p>;
  return (
    <ul className="list-disc pl-5 space-y-1 text-sm text-slate-800">
      {items.map((t, i) => (
        <li key={i}>{t}</li>
      ))}
    </ul>
  );
}

export default function Claim360Page() {
  const { id } = useParams<{ id: string }>();
  const { token } = useAuth();
  const [data, setData] = useState<Claim360 | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(true);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);

  useEffect(() => {
    if (!token || !id) return;
    const load = () =>
      apiFetch<Claim360>(`/api/v1/claims/${id}/claim-360`, {}, token)
        .then(setData)
        .catch((e: Error) => setError(e.message));
    load();
    if (!live) return;
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, [token, id, live]);

  const runAnalysis = async () => {
    if (!token) return;
    const get = <T,>(path: string) => apiFetch<T>(`/api/v1/claims/${id}/${path}`, {}, token).catch(() => null);
    const [repair_replace, benchmark, fusion] = await Promise.all([
      get<NonNullable<Analysis["repair_replace"]>>("repair-replace-analysis"),
      get<NonNullable<Analysis["benchmark"]>>("estimate-benchmark"),
      get<NonNullable<Analysis["fusion"]>>("multimodal-fusion"),
    ]);
    setAnalysis({ repair_replace, benchmark, fusion });
  };

  if (error) return <div className="p-4 bg-red-50 border border-red-300 text-red-900 rounded-lg text-sm">{error}</div>;
  if (!data) return <div className="text-sm text-slate-600">Loading Claim 360…</div>;
  const o = data.overview;
  const a = data.answers;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Claim 360 — {o.claim_number}</h1>
          <p className="text-sm text-slate-600">
            State <b>{o.canonical_state}</b> · {o.claim_type} · risk {o.risk_tier} · path {o.operational_path} · queue {o.queue_name}
            {o.paused && <span className="ml-2 px-2 py-0.5 text-xs bg-amber-100 border border-amber-300 rounded">PAUSED</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => setLive(!live)} className="px-3 py-2 text-xs font-semibold border border-slate-300 rounded-lg">
            {live ? "Live: refreshing every 10s" : "Live refresh off"}
          </button>
          <Link href={`/claims/${data.claim_id}`} className="px-3 py-2 text-xs font-semibold bg-slate-900 text-white rounded-lg">
            Open full claim workspace
          </Link>
        </div>
      </div>

      <section className={`p-5 rounded-xl border ${a.do_i_need_to_act.required ? "bg-amber-50 border-amber-300" : "bg-white border-slate-200"}`}>
        <h2 className="text-base font-bold text-slate-900 mb-3">What the claims officer needs to know</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div><h3 className="font-semibold text-slate-700">What has happened?</h3><List items={a.what_has_happened} empty="Nothing yet." /></div>
          <div><h3 className="font-semibold text-slate-700">What is happening right now?</h3><p>{a.what_is_happening_now}</p></div>
          <div><h3 className="font-semibold text-slate-700">What is blocked, and why?</h3>
            {data.blockers.length === 0 ? <p className="text-slate-500">Nothing is blocked.</p> : (
              <ul className="space-y-1">{data.blockers.map((b, i) => (<li key={i}><b>{b.code}</b> — {b.why} <span className="text-slate-500">(owner: {b.owner})</span></li>))}</ul>
            )}
          </div>
          <div><h3 className="font-semibold text-slate-700">What did the AI do?</h3><List items={a.what_did_ai_do} empty="No agent has run." /></div>
          <div><h3 className="font-semibold text-slate-700">What did the AI find?</h3><List items={a.what_did_ai_find} empty="No findings yet." /></div>
          <div><h3 className="font-semibold text-slate-700">Next action</h3><p>{a.next_action}</p>
            <p className="mt-2 font-semibold">{a.do_i_need_to_act.required ? "Yes — action needed from your role." : "No action is assigned to your role."}</p>
            <p className="text-xs text-slate-500">{a.do_i_need_to_act.reason}</p></div>
        </div>
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <section className="bg-white p-5 rounded-xl border border-slate-200 space-y-2 text-sm">
          <h2 className="text-base font-bold text-slate-900">Claim overview</h2>
          <div>Estimated loss: <b>₹{o.estimated_loss_inr}</b></div>
          {o.policy && <div>Policy {o.policy.policy_number} · IDV ₹{o.policy.idv_inr} · {o.policy.status}</div>}
          {o.vehicle && <div>Vehicle {o.vehicle.registration} · {o.vehicle.make} {o.vehicle.model} {o.vehicle.year}{o.vehicle.is_ev ? " · EV" : ""}</div>}
          {o.customer && <div>Customer {o.customer.name} · {o.customer.phone} · {o.customer.email}</div>}
          <div className="pt-2 border-t border-slate-100">
            <div className="font-semibold">SLA clocks</div>
            {o.sla.length === 0 ? <div className="text-slate-500">No timers.</div> : o.sla.map((s, i) => (
              <div key={i} className="flex justify-between text-xs"><span>{s.stage}</span><span className={`px-1.5 rounded border ${outcomeCls(s.status === "breached" ? "failed" : s.status === "on_track" || s.status === "completed" ? "success" : "warn")}`}>{s.status}</span></div>
            ))}
          </div>
        </section>

        <section className="lg:col-span-2 bg-white p-5 rounded-xl border border-slate-200">
          <h2 className="text-base font-bold text-slate-900 mb-3">Workflow DAG (live status per agent)</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {data.workflow.map((n) => (
              <div key={n.agent_name} className="p-2 border border-slate-200 rounded-lg text-xs flex items-center justify-between">
                <div>
                  <div className="font-bold text-slate-900">{n.order}. {n.display_name}</div>
                  <div className="text-slate-500">after: {n.depends_on.length ? n.depends_on.join(", ") : "—"}</div>
                </div>
                <div className="text-right">
                  <span className={`px-1.5 py-0.5 rounded border ${outcomeCls(n.last_outcome)}`}>{n.status}</span>
                  {n.last_latency_ms !== null && <div className="text-slate-500">{n.last_latency_ms} ms{n.last_confidence !== null ? ` · conf ${n.last_confidence}` : ""}</div>}
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="bg-white p-5 rounded-xl border border-slate-200 space-y-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-bold text-slate-900">Claim intelligence</h2>
          <button type="button" onClick={runAnalysis} className="px-3 py-1.5 text-xs font-semibold bg-indigo-600 text-white rounded-lg">
            Run damage analysis
          </button>
        </div>
        <p>
          Predicted complexity: <b>{data.intelligence.complexity.band}</b> (score {data.intelligence.complexity.score}) · about{" "}
          {data.intelligence.complexity.expected_handling_hours}h · {data.intelligence.complexity.expected_human_touchpoints} human touchpoints ·
          skill: {data.intelligence.complexity.recommended_skill}
        </p>
        <ul className="list-disc pl-5 text-xs text-slate-700">
          {data.intelligence.complexity.drivers.map((d) => (
            <li key={d.driver}>+{d.points} {d.why}</li>
          ))}
        </ul>
        <p className="text-xs text-slate-500">{data.intelligence.complexity.disclaimer} SLA risk predictions: {data.intelligence.sla_risk.predictions.length}.</p>
        {analysis && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
            <div className="p-3 bg-slate-50 rounded border border-slate-200">
              <h3 className="font-semibold">Repair vs replace</h3>
              {analysis.repair_replace
                ? analysis.repair_replace.components.map((c) => (
                    <p key={c.part_code}>{c.part_code}: <b>{c.decision}</b>{c.human_review_required ? " (human review)" : ""}</p>
                  ))
                : <p>Not available.</p>}
            </div>
            <div className="p-3 bg-slate-50 rounded border border-slate-200">
              <h3 className="font-semibold">Estimate benchmark</h3>
              {analysis.benchmark ? <p>{analysis.benchmark.city_tier} labour tier · {analysis.benchmark.flagged_lines} flagged line(s)</p> : <p>Not available.</p>}
            </div>
            <div className="p-3 bg-slate-50 rounded border border-slate-200">
              <h3 className="font-semibold">Multimodal check</h3>
              {analysis.fusion ? (
                <p>Confidence {analysis.fusion.fused_confidence} · zones {analysis.fusion.agreed_zones.join(", ") || "none agreed"}{analysis.fusion.contradictions.map((x) => ` · ${x.message}`)}</p>
              ) : <p>Not available.</p>}
            </div>
          </div>
        )}
      </section>

      <section className="bg-white p-5 rounded-xl border border-slate-200">
        <h2 className="text-base font-bold text-slate-900 mb-1">AI execution timeline</h2>
        <p className="text-xs text-slate-500 mb-3">{data.agent_summary.executions} executions · {data.agent_summary.total_tokens} tokens (estimated) · ₹{data.agent_summary.total_cost_inr} AI cost · {data.agent_summary.human_interventions} human interventions</p>
        <ol className="space-y-1.5 text-xs">
          {data.execution_timeline.map((t, i) => (
            <li key={i} className="flex gap-3">
              <span className="w-40 shrink-0 text-slate-500">{t.at.replace("T", " ").slice(0, 19)}</span>
              <span className="w-28 shrink-0 font-semibold text-slate-600">{t.kind.replace("_", " ")}</span>
              <span className="text-slate-900">{t.title}{t.detail ? ` — ${t.detail}` : ""}</span>
            </li>
          ))}
        </ol>
      </section>

      <section className="bg-white p-5 rounded-xl border border-slate-200 overflow-x-auto">
        <h2 className="text-base font-bold text-slate-900 mb-3">Agent trace (model, prompt, tools, cost)</h2>
        <table className="w-full text-xs text-left">
          <thead><tr className="text-slate-500"><th className="py-1">Agent</th><th>Model / prompt</th><th>Outcome</th><th>Latency</th><th>Retries</th><th>Tokens</th><th>Cost ₹</th><th>Tools</th><th>Final action</th></tr></thead>
          <tbody>
            {data.agent_executions.map((t) => (
              <tr key={t.id} className="border-t border-slate-100">
                <td className="py-1 font-semibold">{t.agent_name} <span className="text-slate-400">v{t.agent_version}</span></td>
                <td>{t.model_name}<div className="text-slate-400">prompt {t.prompt_version}</div></td>
                <td><span className={`px-1.5 py-0.5 rounded border ${outcomeCls(t.outcome)}`}>{t.outcome}</span>{t.human_intervention && <span className="ml-1">👤{t.human_intervention.resolved ? "✓" : ""}</span>}</td>
                <td>{t.latency_ms} ms</td><td>{t.retry_count}</td><td>{t.token_usage.total}</td><td>{t.cost_inr}</td>
                <td>{t.tool_calls.map((c) => c.tool).join(", ") || "—"}</td><td>{t.final_action}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section className="bg-white p-5 rounded-xl border border-slate-200 text-xs space-y-2">
          <h2 className="text-base font-bold text-slate-900">Evidence & documents</h2>
          {data.evidence.documents.map((d) => (
            <div key={d.id} className="flex justify-between border-b border-slate-100 pb-1"><span>{d.doc_type} · {d.filename}</span><span className="text-slate-500">{d.status} · scan {d.malware_scan} · {d.sha256.slice(0, 10)}…</span></div>
          ))}
          {data.evidence.extracted_facts.map((f, i) => (
            <div key={i} className="flex justify-between"><span>{f.field}: <b>{f.value}</b></span><span className={f.confidence < 0.7 ? "text-red-700" : "text-slate-500"}>conf {f.confidence} · {f.validation_status}</span></div>
          ))}
        </section>
        <section className="bg-white p-5 rounded-xl border border-slate-200 text-xs space-y-2">
          <h2 className="text-base font-bold text-slate-900">Settlement & approvals</h2>
          {data.settlement_and_approvals.settlements.map((s) => (<div key={s.id}>Gross ₹{s.gross_assessed_inr} → net ₹{s.net_payable_inr} · {s.approval_status}</div>))}
          {data.settlement_and_approvals.approvals.map((p) => (<div key={p.id}>Approval {p.action_type} ₹{p.amount_inr}: <b>{p.decision}</b></div>))}
          {data.settlement_and_approvals.payments.map((p) => (<div key={p.id}>Payment ₹{p.amount_inr}: <b>{p.status}</b></div>))}
        </section>
      </div>
    </div>
  );
}
