"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { RiskTierBadge, StatusPill } from "@/components/Badges";
import { MotorClaimTracker } from "@/components/MotorClaimTracker";

interface ClaimItem {
  id: string;
  claim_number: string;
  vehicle_reg_input: string;
  status: string;
  risk_tier?: string;
  operational_path?: string;
  next_expected_action: string;
  estimated_loss_inr: string;
}

export default function CustomerPortalPage() {
  const { token, user, switchUser } = useAuth();
  const [claims, setClaims] = useState<ClaimItem[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [grievanceCat, setGrievanceCat] = useState("settlement_clarification");
  const [grievanceDesc, setGrievanceDesc] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const loadClaims = useCallback(() => {
    if (!token) return;
    apiFetch<{ items: ClaimItem[] }>("/api/v1/claims", {}, token)
      .then((res) => {
        setClaims(res.items);
        if (res.items.length > 0 && !res.items.some((c) => c.id === selectedId)) {
          setSelectedId(res.items[0].id);
        }
      })
      .catch(() => {});
  }, [token, selectedId]);

  useEffect(() => {
    loadClaims();
  }, [loadClaims]);

  const submitGrievance = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !selectedId) return;
    const res = await apiFetch<{ grievance_id: string; due_at: string }>(
      `/api/v1/claims/${selectedId}/grievances`,
      {
        method: "POST",
        body: JSON.stringify({ category: grievanceCat, description: grievanceDesc }),
      },
      token
    );
    setMsg(
      `Grievance acknowledged immediately (ID: ${res.grievance_id}). IRDAI 14-day resolution due by ${res.due_at.slice(
        0,
        10
      )}.`
    );
    setGrievanceDesc("");
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Customer Self-Service &amp; Claim Journey Portal</h1>
          <p className="text-sm text-slate-600">
            Track your live Motor Claim Tracker, manage multilingual &amp; WhatsApp consent preferences, upload missing
            documents/photos, or escalate directly to a human specialist.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {user?.role !== "policyholder" && (
            <button
              type="button"
              onClick={() => switchUser("policyholder@demo.in")}
              className="px-3.5 py-2 text-xs font-semibold bg-indigo-900 text-white rounded-lg hover:bg-indigo-800"
            >
              Preview as Policyholder (Aarav Deshmukh)
            </button>
          )}
          <Link
            href="/fnol"
            className="px-3.5 py-2 text-xs font-semibold bg-slate-900 text-white rounded-lg hover:bg-slate-800"
          >
            + Report New Claim
          </Link>
        </div>
      </div>

      {/* Claim Switcher Cards */}
      <div className="bg-white p-4 rounded-2xl border border-slate-200 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wide">
            Select Your Motor Claim ({claims.length})
          </h2>
          {selectedId && (
            <Link href={`/claims/${selectedId}`} className="text-xs font-semibold text-indigo-700 hover:underline">
              Open Full Claim 360 &rarr;
            </Link>
          )}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {claims.map((c) => {
            const active = c.id === selectedId;
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => setSelectedId(c.id)}
                className={`p-3.5 rounded-xl border text-left transition-all space-y-2 ${
                  active
                    ? "bg-slate-900 text-white border-slate-900 shadow-sm"
                    : "bg-slate-50 text-slate-900 border-slate-200 hover:border-slate-400"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-bold text-xs">{c.claim_number}</span>
                  <StatusPill status={c.status} />
                </div>
                <div className={`text-xs ${active ? "text-slate-300" : "text-slate-600"}`}>
                  {c.vehicle_reg_input} · &#8377;{Number(c.estimated_loss_inr).toLocaleString("en-IN")}
                </div>
                <div className="flex items-center justify-between gap-2">
                  <RiskTierBadge tier={c.risk_tier || "MEDIUM"} path={c.operational_path} />
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Live Motor Claim Tracker + Proactive AI Communication Intelligence + Preferences + Human Escalation */}
      {token && selectedId && (
        <MotorClaimTracker claimId={selectedId} token={token} allowUpload={true} onClaimUpdated={loadClaims} />
      )}

      {/* Formal IRDAI 14-Day Grievance Form */}
      <form onSubmit={submitGrievance} className="bg-white p-5 rounded-2xl border border-slate-200 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-base font-bold text-slate-900">Formal IRDAI Grievance / Appeal Filing</h2>
            <p className="text-xs text-slate-600">
              Immediate acknowledgement &amp; 14-day statutory resolution SLA per IRDAI Master Circular 2024.
            </p>
          </div>
          <span className="px-2.5 py-1 text-[11px] font-bold bg-slate-100 text-slate-800 rounded-full">
            14-Day SLA Timer
          </span>
        </div>
        {msg && (
          <div className="p-2.5 bg-emerald-50 border border-emerald-300 text-emerald-900 text-xs rounded-lg">{msg}</div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <select
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
            className="px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white"
          >
            {claims.map((c) => (
              <option key={c.id} value={c.id}>
                {c.claim_number}
              </option>
            ))}
          </select>
          <select
            value={grievanceCat}
            onChange={(e) => setGrievanceCat(e.target.value)}
            className="px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white"
          >
            <option value="surveyor_delay">Surveyor Delay</option>
            <option value="settlement_clarification">Settlement Deduction Clarification</option>
            <option value="repair_quality">Garage Repair Quality</option>
            <option value="callback_request">Callback Request</option>
          </select>
          <button
            type="submit"
            className="py-2 bg-slate-900 text-white text-sm font-semibold rounded-lg hover:bg-slate-800"
          >
            Submit Formal Grievance
          </button>
        </div>
        <textarea
          required
          rows={2}
          value={grievanceDesc}
          onChange={(e) => setGrievanceDesc(e.target.value)}
          placeholder="Describe your formal grievance or appeal..."
          className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg"
        />
      </form>
    </div>
  );
}
