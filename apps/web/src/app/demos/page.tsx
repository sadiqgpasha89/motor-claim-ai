"use client";

import React from "react";
import Link from "next/link";
import { Card, PageHeader, Status, usePortal } from "@/components/PortalKit";

interface Demo { id: string; title: string; tag: string; claim_number: string; summary: string; steps: string[]; portal_sections: string; available: boolean; claim_360_path: string | null; status: string | null; risk_tier: string | null }

export default function DemosPage() {
  const { data, error } = usePortal<{ demos: Demo[]; note: string }>("/api/v1/portal/demos");
  return (
    <div className="space-y-6">
      <PageHeader title="Guided demos" intro="Five curated claims that show more than the happy path. Each opens in Claim 360. DEMO / SYNTHETIC." />
      <Status error={error} ready={!!data} />
      {data?.demos.map((d, i) => (
        <Card key={d.id} title={`Demo ${i + 1} — ${d.title}`}>
          <p className="text-xs font-semibold text-slate-500">{d.tag} · {d.claim_number}{d.status ? ` · ${d.status}` : ""}{d.risk_tier ? ` · ${d.risk_tier} risk` : ""}</p>
          <p>{d.summary}</p>
          <ol className="list-decimal list-inside text-xs text-slate-700">{d.steps.map((s) => <li key={s}>{s}</li>)}</ol>
          <p className="text-xs text-slate-500">Look at: {d.portal_sections}</p>
          {d.available && d.claim_360_path ? <Link href={d.claim_360_path} className="inline-block px-3 py-1.5 text-xs font-semibold bg-slate-900 text-white rounded-lg">Open in Claim 360</Link> : <p className="text-xs text-amber-800">This demo claim is not seeded. Reset the demo data.</p>}
        </Card>
      ))}
      {data && <p className="text-xs text-slate-500">{data.note}</p>}
    </div>
  );
}
