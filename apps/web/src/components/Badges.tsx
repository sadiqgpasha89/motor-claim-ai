import React from "react";

export function ProvenanceBadge({
  kind,
}: {
  kind: "verified" | "extracted" | "ai_assistive" | "human_decision";
}) {
  const styles = {
    verified: "bg-emerald-100 text-emerald-900 border-emerald-300",
    extracted: "bg-amber-100 text-amber-900 border-amber-300",
    ai_assistive: "bg-indigo-100 text-indigo-900 border-indigo-300",
    human_decision: "bg-slate-900 text-white border-slate-900",
  }[kind];

  const labels = {
    verified: "VERIFIED FACT",
    extracted: "EXTRACTED (UNVERIFIED)",
    ai_assistive: "AI ASSISTIVE ONLY",
    human_decision: "HUMAN DECISION",
  }[kind];

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 text-[11px] font-semibold rounded border ${styles}`}
    >
      {labels}
    </span>
  );
}

export function SlaBadge({ status }: { status: string }) {
  const cls =
    status === "breached"
      ? "bg-red-100 text-red-900 border-red-300"
      : status === "warning"
      ? "bg-amber-100 text-amber-900 border-amber-300"
      : status === "completed"
      ? "bg-slate-100 text-slate-700 border-slate-300"
      : "bg-emerald-100 text-emerald-900 border-emerald-300";

  return (
    <span className={`inline-flex items-center px-2 py-0.5 text-xs font-medium rounded border ${cls}`}>
      SLA: {status.toUpperCase()}
    </span>
  );
}

export function StatusPill({ status }: { status: string }) {
  const cls =
    status === "CLOSED" || status === "APPROVED" || status === "FAST_TRACK"
      ? "bg-emerald-50 text-emerald-800 border-emerald-300"
      : status === "CLARIFICATION_REQUESTED" ||
        status === "DECLINED_PARTIAL" ||
        status === "HUMAN_REVIEW" ||
        status === "INVESTIGATION_REQUIRED"
      ? "bg-rose-50 text-rose-800 border-rose-300"
      : status === "SETTLEMENT_PENDING_APPROVAL" || status === "SURVEY_REQUIRED" || status === "PAYMENT_RECONCILIATION"
      ? "bg-amber-50 text-amber-900 border-amber-300"
      : "bg-blue-50 text-blue-900 border-blue-200";
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 text-xs font-semibold rounded-full border ${cls}`}>
      {status}
    </span>
  );
}

export function RiskTierBadge({
  tier,
  path,
  score,
}: {
  tier?: string;
  path?: string;
  score?: number;
}) {
  const norm = (tier || "MEDIUM").toUpperCase();
  const cls =
    norm === "LOW"
      ? "bg-emerald-100 text-emerald-950 border-emerald-400"
      : norm === "HIGH"
      ? "bg-rose-100 text-rose-950 border-rose-400"
      : "bg-amber-100 text-amber-950 border-amber-400";
  const pathLabel =
    path === "fast_track"
      ? "Fast-Track"
      : path === "complex_investigation"
      ? "Complex / SIU"
      : "Standard AI-Assisted";
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 text-xs font-bold rounded-full border ${cls}`}>
      <span>{norm} RISK</span>
      <span className="font-medium opacity-80">· {pathLabel}</span>
      {typeof score === "number" && score > 0 && <span className="font-mono text-[11px] opacity-75">({score})</span>}
    </span>
  );
}
