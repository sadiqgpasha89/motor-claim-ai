"use client";

import React from "react";
import Link from "next/link";
import { Card, PageHeader, Stat, Status, Table, fmtInr, usePortal } from "@/components/PortalKit";

interface Hr {
  pending_approvals: { claim_number: string; claim_id: string; action_type: string; amount_inr: number; age_hours: number }[];
  open_tasks: { claim_number: string; claim_id: string; title: string; assigned_role: string | null; priority: string | null; reason_code: string | null; created_by_agent: string | null; age_hours: number }[];
  workload_by_role: Record<string, Record<string, number>>;
  overrides: { approvals_decided: number; overridden: number; override_rate_pct: number; alerts: string[]; note: string };
  note: string;
}

export default function HumanReviewPage() {
  const { data, error } = usePortal<Hr>("/api/v1/portal/human-review");
  return (
    <div className="space-y-6">
      <PageHeader title="Human Review" intro="Approval tasks, escalations, overrides, decisions and reviewer workload. DEMO / SYNTHETIC." />
      <Status error={error} ready={!!data} />
      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Stat label="Pending approvals" value={data.pending_approvals.length} />
            <Stat label="Open tasks" value={data.open_tasks.length} />
            <Stat label="Decisions made" value={data.overrides.approvals_decided} />
            <Stat label="Override rate" value={`${data.overrides.override_rate_pct}%`} hint={`${data.overrides.overridden} not approved`} />
          </div>
          {data.overrides.alerts.map((a) => <div key={a} className="p-3 bg-amber-50 border border-amber-200 rounded text-sm">{a}</div>)}
          <Card title="Pending approvals">
            <Table head={["Claim", "Action", "Amount", "Waiting (h)"]} rows={data.pending_approvals.map((a) => [<Link key={a.claim_id + a.action_type} href={`/claims/${a.claim_id}/claim-360`} className="text-blue-700 underline">{a.claim_number}</Link>, a.action_type, fmtInr(a.amount_inr), a.age_hours])} />
          </Card>
          <Card title="Open human tasks">
            <Table head={["Claim", "Task", "Role", "Priority", "Reason", "Raised by", "Age (h)"]} rows={data.open_tasks.map((t) => [<Link key={t.claim_id + t.title} href={`/claims/${t.claim_id}/claim-360`} className="text-blue-700 underline">{t.claim_number}</Link>, t.title, t.assigned_role ?? "unassigned", t.priority ?? "", t.reason_code ?? "", t.created_by_agent ?? "", t.age_hours])} />
          </Card>
          <Card title="Reviewer workload by role">
            <Table head={["Role", "Open tasks by priority"]} rows={Object.entries(data.workload_by_role).map(([r, c]) => [r, Object.entries(c).map(([k, v]) => `${k}: ${v}`).join(" · ")])} />
          </Card>
          <p className="text-xs text-slate-500">{data.overrides.note}</p>
        </>
      )}
    </div>
  );
}
