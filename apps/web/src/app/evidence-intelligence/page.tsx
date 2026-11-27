"use client";

import React from "react";
import { Card, Counts, PageHeader, Stat, Status, Table, usePortal } from "@/components/PortalKit";

interface Ev {
  evidence_total: number; by_doc_type: Record<string, number>; by_doc_status: Record<string, number>; image_quality: Record<string, number>;
  integrity: { duplicate_files: number; prompt_injection_flagged: number; malware_scan: Record<string, number>; legal_hold: number };
  extracted_facts: { total: number; avg_confidence: number | null; by_validation_status: Record<string, number>; low_confidence: { claim_number: string; field: string; confidence: number; validation_status: string }[] };
  note: string;
}

export default function EvidenceIntelligencePage() {
  const { data, error } = usePortal<Ev>("/api/v1/portal/evidence-intelligence");
  return (
    <div className="space-y-6">
      <PageHeader title="Evidence Intelligence" intro="Documents, OCR, extracted data, photos, evidence integrity and validation. DEMO / SYNTHETIC." />
      <Status error={error} ready={!!data} />
      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Stat label="Evidence files" value={data.evidence_total} />
            <Stat label="Extracted facts" value={data.extracted_facts.total} hint={`Average confidence ${data.extracted_facts.avg_confidence ?? "n/a"}`} />
            <Stat label="Duplicate files" value={data.integrity.duplicate_files} />
            <Stat label="Injection flagged" value={data.integrity.prompt_injection_flagged} hint={`${data.integrity.legal_hold} on legal hold`} />
          </div>
          <Card title="Document types"><Counts data={data.by_doc_type} /></Card>
          <Card title="Document status"><Counts data={data.by_doc_status} /></Card>
          <Card title="Image quality"><Counts data={data.image_quality} /></Card>
          <Card title="Malware scan"><Counts data={data.integrity.malware_scan} /></Card>
          <Card title="Fact validation"><Counts data={data.extracted_facts.by_validation_status} /></Card>
          <Card title="Lowest-confidence extracted facts">
            <Table head={["Claim", "Field", "Confidence", "Validation"]} rows={data.extracted_facts.low_confidence.map((f) => [f.claim_number, f.field, f.confidence, f.validation_status])} />
          </Card>
        </>
      )}
    </div>
  );
}
