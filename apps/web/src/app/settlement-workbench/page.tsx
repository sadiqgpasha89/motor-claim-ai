"use client";

import React from "react";
import Link from "next/link";
import { Card, Counts, PageHeader, Stat, Status, Table, fmtInr, usePortal } from "@/components/PortalKit";

interface Set {
  settlements: { claim_number: string; claim_id: string; pathway: string; gross_inr: number; deductions_inr: number; net_inr: number; total_loss: boolean; approval_status: string }[];
  approvals_by_decision: Record<string, number>; payments_by_status: Record<string, number>; paid_total_inr: number; note: string;
}

export default function SettlementWorkbenchPage() {
  const { data, error } = usePortal<Set>("/api/v1/portal/settlement-workbench");
  return (
    <div className="space-y-6">
      <PageHeader title="Settlement Workbench" intro="Deterministic calculations, deductions, approvals and payment status. Open a claim for the full trace. DEMO / SYNTHETIC." />
      <Status error={error} ready={!!data} />
      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <Stat label="Settlements" value={data.settlements.length} />
            <Stat label="Paid (sandbox gateway)" value={fmtInr(data.paid_total_inr)} />
            <Stat label="Payments" value={Object.values(data.payments_by_status).reduce((a, b) => a + b, 0)} />
          </div>
          <Card title="Latest settlement per claim">
            <Table
              head={["Claim", "Pathway", "Gross", "Deductions", "Net", "Approval"]}
              rows={data.settlements.map((s) => [
                <Link key={s.claim_id} href={`/claims/${s.claim_id}/claim-360`} className="text-blue-700 underline">{s.claim_number}</Link>,
                s.total_loss ? `${s.pathway} (total loss)` : s.pathway, fmtInr(s.gross_inr), fmtInr(s.deductions_inr), fmtInr(s.net_inr), s.approval_status,
              ])}
            />
          </Card>
          <Card title="Approvals by decision"><Counts data={data.approvals_by_decision} /></Card>
          <Card title="Payments by status"><Counts data={data.payments_by_status} /></Card>
        </>
      )}
    </div>
  );
}
