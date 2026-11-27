"use client";

import React from "react";
import { Card, Counts, PageHeader, Stat, Status, Table, fmtInr, usePortal } from "@/components/PortalKit";

interface Dmg {
  components_assessed: number; by_damage_class: Record<string, number>; by_recommended_action: Record<string, number>; avg_confidence: number | null;
  low_confidence_components: number; reviewer_outcomes: Record<string, number>; estimates_total: number;
  estimates_with_anomalies: { claim_number: string; anomalies: number; claimed_inr: number; approved_inr: number; is_supplement: boolean }[]; note: string;
}

export default function DamageAssessmentPage() {
  const { data, error } = usePortal<Dmg>("/api/v1/portal/damage-assessment");
  return (
    <div className="space-y-6">
      <PageHeader title="Damage Assessment" intro="Damage identification, component analysis and estimate validation. The vision model is simulated. DEMO / SYNTHETIC." />
      <Status error={error} ready={!!data} />
      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Stat label="Components assessed" value={data.components_assessed} />
            <Stat label="Average confidence" value={data.avg_confidence ?? "n/a"} />
            <Stat label="Low-confidence components" value={data.low_confidence_components} hint="Below 0.8. Sent to a reviewer." />
            <Stat label="Estimates" value={data.estimates_total} />
          </div>
          <Card title="Damage class"><Counts data={data.by_damage_class} /></Card>
          <Card title="Recommended action (repair or replace)"><Counts data={data.by_recommended_action} /></Card>
          <Card title="Reviewer outcomes"><Counts data={data.reviewer_outcomes} /></Card>
          <Card title="Estimates with anomalies">
            <Table head={["Claim", "Anomalies", "Claimed", "Approved", "Supplement"]} rows={data.estimates_with_anomalies.map((e) => [e.claim_number, e.anomalies, fmtInr(e.claimed_inr), fmtInr(e.approved_inr), e.is_supplement ? "yes" : "no"])} />
          </Card>
        </>
      )}
    </div>
  );
}
