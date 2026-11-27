"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

interface Kpis {
  workflow_success_rate_pct: number;
  human_escalation_rate_pct: number;
  avg_ai_execution_time_ms: number;
  ai_cost_per_claim_inr: string;
  workflow_runs: number;
  agent_executions: number;
  total_tokens_estimated: number;
}
interface CostRow { cost_inr: string; executions: number; tokens: number; agent_name?: string; claim_id?: string; claim_number?: string; complexity?: string; claims?: number }
interface Row { claim_id: string; claim_number?: string; [k: string]: unknown }
interface Dashboard {
  kpis: Kpis;
  failed_agent_executions: (Row & { agent_name: string; outcome: string; retry_count: number; error_details: { error_message: string } | null })[];
  stuck_workflows: (Row & { status: string; reasons: string[]; idle_hours: number })[];
  claims_breaching_sla: (Row & { stage: string; owner_role: string })[];
  human_approval_backlog: { pending_approvals: { approval_id: string; claim_id: string; claim_number: string; amount_inr: string; age_hours: number }[]; open_human_tasks: number; claims_in_human_review: number };
  fraud_investigation_queue: { open_alerts: number; claims_in_investigation: number };
  payment_reconciliation_failures: (Row & { status: string; amount_inr: string })[];
  model_api_outages: { model_gateway_outage_active: boolean; executions_degraded_by_outage: number; degraded_adapters: { name: string; status: string }[] };
  cost: { by_claim: CostRow[]; by_agent: CostRow[]; by_claim_complexity: CostRow[] };
  note: string;
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white p-4 rounded-xl border border-slate-200">
      <div className="text-2xl font-bold text-slate-900">{value}</div>
      <div className="text-xs font-semibold text-slate-600">{label}</div>
      {sub && <div className="text-[11px] text-slate-400">{sub}</div>}
    </div>
  );
}

function Panel({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="bg-white p-5 rounded-xl border border-slate-200 space-y-2">
      <h2 className="text-base font-bold text-slate-900">{title}{count !== undefined && <span className="ml-2 text-xs px-2 py-0.5 rounded-full bg-slate-100">{count}</span>}</h2>
      {children}
    </section>
  );
}

const ClaimLink = ({ id, label }: { id: string; label?: string }) => (
  <Link className="text-indigo-700 underline" href={`/claims/${id}/claim-360`}>{label || id}</Link>
);

function CostTable({ rows, keyOf }: { rows: CostRow[]; keyOf: (r: CostRow) => string }) {
  return (
    <table className="w-full text-xs"><tbody>
      {rows.slice(0, 8).map((r, i) => (
        <tr key={i} className="border-t border-slate-100"><td className="py-1">{keyOf(r)}</td><td className="text-right">{r.executions} runs</td><td className="text-right font-semibold">₹{r.cost_inr}</td></tr>
      ))}
    </tbody></table>
  );
}

export default function AgentCommandCenterPage() {
  const { token } = useAuth();
  const [d, setD] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    apiFetch<Dashboard>("/api/v1/operations/agent-observability/dashboard", {}, token).then(setD).catch((e: Error) => setError(e.message));
  }, [token]);

  if (error) return <div className="p-4 bg-red-50 border border-red-300 text-red-900 rounded-lg text-sm">{error} — switch to the Claims Manager, Auditor or Admin persona.</div>;
  if (!d) return <div className="text-sm text-slate-600">Loading agent observability…</div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Agent Command Center</h1>
        <p className="text-sm text-slate-600">What the AI system is doing, not just where each claim ended up. Every figure is computed from the agent trace store.</p>
        <p className="text-xs text-amber-800 mt-1">{d.note}</p>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Kpi label="Workflow success rate" value={`${d.kpis.workflow_success_rate_pct}%`} sub={`${d.kpis.workflow_runs} workflow runs`} />
        <Kpi label="Human escalation rate" value={`${d.kpis.human_escalation_rate_pct}%`} sub={`${d.kpis.agent_executions} agent executions`} />
        <Kpi label="Avg AI execution time" value={`${d.kpis.avg_ai_execution_time_ms} ms`} sub="per workflow run" />
        <Kpi label="AI cost per claim" value={`₹${d.kpis.ai_cost_per_claim_inr}`} sub={`${d.kpis.total_tokens_estimated} tokens (estimated)`} />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Panel title="Failed agent executions" count={d.failed_agent_executions.length}>
          {d.failed_agent_executions.length === 0 && <p className="text-xs text-slate-500">None.</p>}
          {d.failed_agent_executions.map((f, i) => (
            <div key={i} className="text-xs border-t border-slate-100 pt-1"><ClaimLink id={f.claim_id} label={f.claim_number} /> · <b>{f.agent_name}</b> {f.outcome} after {f.retry_count} retries<div className="text-slate-500">{f.error_details?.error_message}</div></div>
          ))}
        </Panel>
        <Panel title="Stuck workflows" count={d.stuck_workflows.length}>
          {d.stuck_workflows.length === 0 && <p className="text-xs text-slate-500">None.</p>}
          {d.stuck_workflows.slice(0, 10).map((s, i) => (
            <div key={i} className="text-xs border-t border-slate-100 pt-1"><ClaimLink id={s.claim_id} label={s.claim_number} /> · {s.status} · {s.reasons.join(", ")}</div>
          ))}
        </Panel>
        <Panel title="Claims breaching SLA" count={d.claims_breaching_sla.length}>
          {d.claims_breaching_sla.slice(0, 10).map((s, i) => (
            <div key={i} className="text-xs border-t border-slate-100 pt-1"><ClaimLink id={s.claim_id} label={s.claim_number} /> · {s.stage} · owner {s.owner_role}</div>
          ))}
        </Panel>
        <Panel title="Human approval backlog" count={d.human_approval_backlog.pending_approvals.length}>
          <p className="text-xs text-slate-600">{d.human_approval_backlog.open_human_tasks} open human tasks · {d.human_approval_backlog.claims_in_human_review} claims in human review</p>
          {d.human_approval_backlog.pending_approvals.map((a) => (
            <div key={a.approval_id} className="text-xs border-t border-slate-100 pt-1"><ClaimLink id={a.claim_id} label={a.claim_number} /> · ₹{a.amount_inr} · waiting {a.age_hours} h</div>
          ))}
        </Panel>
        <Panel title="Fraud investigation queue" count={d.fraud_investigation_queue.open_alerts}>
          <p className="text-xs text-slate-600">{d.fraud_investigation_queue.claims_in_investigation} claims in investigation. <Link className="text-indigo-700 underline" href="/siu">Open SIU desk</Link></p>
        </Panel>
        <Panel title="Payment reconciliation failures" count={d.payment_reconciliation_failures.length}>
          {d.payment_reconciliation_failures.map((p, i) => (
            <div key={i} className="text-xs border-t border-slate-100 pt-1"><ClaimLink id={p.claim_id} label={p.claim_number} /> · {p.status} · ₹{p.amount_inr}</div>
          ))}
        </Panel>
        <Panel title="Model / API outages">
          <p className="text-xs">Model gateway: <b>{d.model_api_outages.model_gateway_outage_active ? "OUTAGE (simulated)" : "healthy"}</b> · {d.model_api_outages.executions_degraded_by_outage} executions degraded</p>
          {d.model_api_outages.degraded_adapters.map((a, i) => (<div key={i} className="text-xs text-red-800">{a.name}: {a.status}</div>))}
        </Panel>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Panel title="Cost by claim"><CostTable rows={d.cost.by_claim} keyOf={(r) => r.claim_number || r.claim_id || ""} /></Panel>
        <Panel title="Cost by agent"><CostTable rows={d.cost.by_agent} keyOf={(r) => r.agent_name || ""} /></Panel>
        <Panel title="Cost by claim complexity"><CostTable rows={d.cost.by_claim_complexity} keyOf={(r) => `${r.complexity} (${r.claims} claims)`} /></Panel>
      </div>
    </div>
  );
}
