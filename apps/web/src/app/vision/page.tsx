"use client";

import React from "react";
import Link from "next/link";
import { Card, PageHeader, Status, Table, usePortal } from "@/components/PortalKit";

interface Cap {
  vision: string;
  capability_model: { capability: string; target_state: string; state: string; evidence: string }[];
  assessment: { area: string; rating: string; basis: string }[];
  portal_sections: { id: string; name: string; description: string; href: string }[];
  note: string;
}

export default function VisionPage() {
  const { data, error } = usePortal<Cap>("/api/v1/portal/capability-model");
  return (
    <div className="space-y-6">
      <PageHeader title="Vision, capability model and honest assessment" intro="Where the platform stands against its target. Built means working in this repository. Partial means built with a simulated or sandbox dependency." />
      <Status error={error} ready={!!data} />
      {data && (
        <>
          <Card title="Portal sections">
            <Table head={["Section", "What it shows"]} rows={data.portal_sections.map((s) => [<Link key={s.id} href={s.href} className="text-blue-700 underline">{s.name}</Link>, s.description])} />
          </Card>
          <Card title="Target capability model">
            <Table head={["Capability", "Target state", "State", "Evidence"]} rows={data.capability_model.map((c) => [c.capability, c.target_state, c.state, c.evidence])} />
          </Card>
          <Card title="Honest assessment">
            <Table head={["Area", "Rating", "Basis"]} rows={data.assessment.map((a) => [a.area, a.rating, a.basis])} />
          </Card>
          <p className="text-xs text-slate-500">{data.vision} {data.note}</p>
        </>
      )}
    </div>
  );
}
