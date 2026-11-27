"use client";

import React from "react";
import { Card, Counts, PageHeader, Stat, Status, fmtInr, usePortal } from "@/components/PortalKit";

interface Kpi { id: string; name: string; unit: string; value: number | null; basis: string; agentic_target_illustrative: number | null }
interface Dash {
  claims_total: number; by_status: Record<string, number>; by_risk_tier: Record<string, number>; by_claim_type: Record<string, number>;
  settlement_net_total_inr: number; fraud_alerts_open: number; fraud_alerts_total: number; human_tasks_open: number; headline_kpis: Kpi[]; note: string;
}

export default function ExecutiveDashboardPage() {
  const { data, error } = usePortal<Dash>("/api/v1/portal/executive-dashboard");
  return (
    <div className="space-y-6">
      <PageHeader title="Executive Dashboard" intro="Claims volume, processing time, SLA, settlement, fraud alerts and operational KPIs. Manager, auditor and admin roles. DEMO / SYNTHETIC." />
      <Status error={error} ready={!!data} />
      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Stat label="Claims" value={data.claims_total} />
            <Stat label="Net settlement (all versions)" value={fmtInr(data.settlement_net_total_inr)} />
            <Stat label="Open fraud alerts" value={`${data.fraud_alerts_open} / ${data.fraud_alerts_total}`} />
            <Stat label="Open human tasks" value={data.human_tasks_open} />
          </div>
          <Card title="Headline KPIs">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {data.headline_kpis.map((k) => (
                <Stat key={k.id} label={k.name} value={k.value === null ? "Not measured" : `${k.value} ${k.unit}`} hint={k.basis} />
              ))}
            </div>
          </Card>
          <Card title="By status"><Counts data={data.by_status} /></Card>
          <Card title="By risk tier"><Counts data={data.by_risk_tier} /></Card>
          <Card title="By claim type"><Counts data={data.by_claim_type} /></Card>
          <p className="text-xs text-slate-500">{data.note}</p>
        </>
      )}
    </div>
  );
}
