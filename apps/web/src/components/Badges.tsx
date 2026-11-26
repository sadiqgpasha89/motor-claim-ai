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
    status === "CLOSED" || status === "APPROVED"
      ? "bg-emerald-50 text-emerald-800 border-emerald-300"
      : status === "CLARIFICATION_REQUESTED" || status === "DECLINED_PARTIAL"
      ? "bg-rose-50 text-rose-800 border-rose-300"
      : "bg-blue-50 text-blue-900 border-blue-200";
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 text-xs font-semibold rounded-full border ${cls}`}>
      {status}
    </span>
  );
}
