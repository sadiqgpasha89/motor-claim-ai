"use client";

import React from "react";
import { Card, PageHeader, Stat, Status, Table, usePortal } from "@/components/PortalKit";

interface Kpi { id: string; name: string; unit: string; value: number | null; basis: string; traditional_illustrative: number | null; agentic_target_illustrative: number | null }
interface Perf {
  agents: { agent: string; executions: number; success_rate_pct: number; escalation_rate_pct: number; failure_rate_pct: number; avg_confidence: number | null }[];
  cost_latency: { cost_per_claim_inr: string; cost_per_claim_budget_inr: number; agents: { agent: string; avg_duration_ms: number; p95_duration_ms: number; latency_budget_ms: number; cost_inr: string; retry_rate_pct: number }[]; optimisation_hints: string[] };
  kpi_framework: { kpis: Kpi[]; outcome_targets: { name: string; target_pct: number }[]; before_after: { process: string; traditional: string; agentic_target: string; state: string; built_as: string }[]; targets_note: string };
  quality_gate: string; note: string;
}

export default function PerformancePage() {
  const { data, error } = usePortal<Perf>("/api/v1/portal/performance");
  return (
    <div className="space-y-6">
      <PageHeader title="Performance & Evaluation" intro="Agent quality, cost, latency and business outcomes. Targets are illustrative ambition levels, not results. DEMO / SYNTHETIC." />
      <Status error={error} ready={!!data} />
      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <Stat label="AI cost per claim (estimated)" value={`INR ${data.cost_latency.cost_per_claim_inr}`} hint={`Budget INR ${data.cost_latency.cost_per_claim_budget_inr}`} />
            <Stat label="KPIs measured" value={`${data.kpi_framework.kpis.filter((k) => k.value !== null).length} / ${data.kpi_framework.kpis.length}`} />
            <Stat label="Agents with traces" value={data.agents.length} />
          </div>
          {data.cost_latency.optimisation_hints.map((h) => <div key={h} className="p-3 bg-amber-50 border border-amber-200 rounded text-sm">{h}</div>)}
          <Card title="Agent quality from the trace store">
            <Table head={["Agent", "Runs", "Success %", "Escalated %", "Failed %", "Avg confidence"]} rows={data.agents.map((a) => [a.agent, a.executions, a.success_rate_pct, a.escalation_rate_pct, a.failure_rate_pct, a.avg_confidence ?? "n/a"])} />
            <p className="text-xs text-slate-500">{data.quality_gate}</p>
          </Card>
          <Card title="Latency and cost by agent">
            <Table head={["Agent", "Avg ms", "p95 ms", "Budget ms", "Cost INR", "Retried %"]} rows={data.cost_latency.agents.map((a) => [a.agent, a.avg_duration_ms, a.p95_duration_ms, a.latency_budget_ms, a.cost_inr, a.retry_rate_pct])} />
          </Card>
          <Card title="Business KPIs (17)">
            <Table head={["KPI", "Measured", "Traditional (illustr.)", "Agentic target (illustr.)", "Basis"]} rows={data.kpi_framework.kpis.map((k) => [k.name, k.value === null ? "Not measured" : `${k.value} ${k.unit}`, k.traditional_illustrative ?? "", k.agentic_target_illustrative ?? "", k.basis])} />
            <p className="text-xs text-slate-500">{data.kpi_framework.targets_note}</p>
          </Card>
          <Card title="Outcome targets (illustrative)">
            <Table head={["Outcome", "Target reduction"]} rows={data.kpi_framework.outcome_targets.map((o) => [o.name, `${o.target_pct}%`])} />
          </Card>
          <Card title="Traditional vs agentic">
            <Table head={["Process", "Traditional", "Agentic target", "State in this platform"]} rows={data.kpi_framework.before_after.map((r) => [r.process, r.traditional, r.agentic_target, `${r.state}: ${r.built_as}`])} />
          </Card>
        </>
      )}
    </div>
  );
}
