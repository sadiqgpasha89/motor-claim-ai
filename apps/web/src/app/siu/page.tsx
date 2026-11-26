"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ShieldAlert } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

interface AlertItem {
  id: string;
  claim_id: string;
  indicator_code: string;
  title: string;
  severity_band: string;
  confidence: string;
  evidence_summary: string;
  benign_explanation: string;
  recommended_action: string;
  status: string;
  disposition_reason?: string;
}

export default function SIUWorkbenchPage() {
  const { token, user, switchUser } = useAuth();
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [reason, setReason] = useState("Verified repair records & benign explanation confirmed.");

  const loadAlerts = useCallback(async () => {
    if (!token) return;
    setErr(null);
    try {
      const res = await apiFetch<{ items: AlertItem[] }>("/api/v1/siu/alerts", {}, token);
      setAlerts(res.items);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Access restricted");
      setAlerts([]);
    }
  }, [token]);

  useEffect(() => {
    loadAlerts();
  }, [loadAlerts]);

  const dispose = async (a: AlertItem, status: string) => {
    if (!token) return;
    await apiFetch(
      `/api/v1/claims/${a.claim_id}/fraud-alerts/${a.id}/disposition`,
      {
        method: "POST",
        body: JSON.stringify({ status, disposition_reason: reason }),
      },
      token
    );
    loadAlerts();
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">SIU / Fraud Intelligence Workbench</h1>
          <p className="text-sm text-slate-600">
            Indicators are investigative leads only. Alerts never auto-reject claims or hold payouts without human SIU review.
          </p>
        </div>
        {user?.role !== "siu_investigator" && (
          <button
            type="button"
            onClick={() => switchUser("siu@demo.in")}
            className="px-3 py-2 text-xs font-semibold bg-slate-900 text-white rounded-lg"
          >
            Switch to SIU Investigator
          </button>
        )}
      </div>

      {err ? (
        <div className="bg-amber-50 border border-amber-300 p-5 rounded-xl text-amber-950 flex items-start gap-3">
          <ShieldAlert className="w-5 h-5 shrink-0 mt-0.5" />
          <div>
            <div className="font-bold">Restricted SIU Access Enforced Server-Side</div>
            <div className="text-sm mt-1">{err}</div>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="bg-white p-4 rounded-xl border border-slate-200">
            <label className="block text-xs font-semibold text-slate-600 mb-1">
              Disposition Rationale (for investigator actions below)
            </label>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg"
            />
          </div>

          {alerts.map((a) => (
            <div key={a.id} className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span className="text-xs font-mono font-bold text-slate-500">{a.indicator_code}</span>
                  <h2 className="text-base font-bold text-slate-900">{a.title}</h2>
                </div>
                <div className="flex items-center gap-2">
                  <span className="px-2.5 py-0.5 text-xs font-semibold rounded bg-slate-100">
                    Band: {a.severity_band.toUpperCase()} ({a.confidence})
                  </span>
                  <span className="px-2.5 py-0.5 text-xs font-semibold rounded bg-indigo-100 text-indigo-900">
                    Status: {a.status}
                  </span>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                <div className="p-3 bg-slate-50 rounded border border-slate-200">
                  <span className="font-semibold text-slate-800">Signal Evidence: </span>
                  {a.evidence_summary}
                </div>
                <div className="p-3 bg-emerald-50 rounded border border-emerald-200">
                  <span className="font-semibold text-emerald-900">Potential Benign Explanation: </span>
                  {a.benign_explanation}
                </div>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                <Link href={`/claims/${a.claim_id}`} className="text-xs font-semibold text-slate-900 underline">
                  Inspect Claim 360 & Entity Graph &rarr;
                </Link>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => dispose(a, "investigating")}
                    className="px-3 py-1.5 text-xs font-semibold border border-slate-300 rounded hover:bg-slate-50"
                  >
                    Mark Investigating
                  </button>
                  <button
                    type="button"
                    onClick={() => dispose(a, "not_substantiated")}
                    className="px-3 py-1.5 text-xs font-semibold bg-emerald-700 text-white rounded hover:bg-emerald-800"
                  >
                    Not Substantiated (Clear)
                  </button>
                  <button
                    type="button"
                    onClick={() => dispose(a, "substantiated")}
                    className="px-3 py-1.5 text-xs font-semibold bg-rose-700 text-white rounded hover:bg-rose-800"
                  >
                    Substantiated
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
