"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Search, PlusCircle, AlertCircle, RefreshCw } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { RiskTierBadge, SlaBadge, StatusPill } from "@/components/Badges";

interface ClaimRow {
  id: string;
  claim_number: string;
  claim_type: string;
  peril_cause: string;
  status: string;
  risk_tier?: string;
  operational_path?: string;
  risk_score?: number;
  multiple_vehicles_involved?: boolean;
  legal_dispute?: boolean;
  severity_band: string;
  queue_name: string;
  policy_number_input: string;
  vehicle_reg_input: string;
  estimated_loss_inr: string;
  requires_mandatory_survey: boolean;
  next_expected_action: string;
  sla_health: string;
  injury_or_fatality: boolean;
  ev_battery_impacted: boolean;
}

export default function CommandCentrePage() {
  const { token, user, loading: authLoading } = useAuth();
  const [claims, setClaims] = useState<ClaimRow[]>([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [riskFilter, setRiskFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const loadClaims = useCallback(async () => {
    if (!token) return;
    setBusy(true);
    setErr(null);
    try {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      if (statusFilter) params.set("status", statusFilter);
      if (riskFilter) params.set("risk_tier", riskFilter);
      if (typeFilter) params.set("claim_type", typeFilter);
      const q = params.toString() ? `?${params.toString()}` : "";
      const res = await apiFetch<{ items: ClaimRow[]; total: number }>(
        `/api/v1/claims${q}`,
        {},
        token
      );
      setClaims(res.items);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load claims");
    } finally {
      setBusy(false);
    }
  }, [token, search, statusFilter, riskFilter, typeFilter]);

  useEffect(() => {
    if (!authLoading && token) loadClaims();
  }, [authLoading, token, loadClaims]);

  const breachedCount = claims.filter((c) => c.sla_health === "breached").length;
  const lowRiskCount = claims.filter((c) => (c.risk_tier || "MEDIUM") === "LOW").length;
  const highRiskCount = claims.filter((c) => (c.risk_tier || "MEDIUM") === "HIGH").length;
  const evOrTpCount = claims.filter(
    (c) => c.injury_or_fatality || c.ev_battery_impacted || c.multiple_vehicles_involved
  ).length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Claims Command Centre</h1>
          <p className="text-sm text-slate-600">
            Viewing scoped claims for{" "}
            <span className="font-semibold text-slate-900">{user?.name || "Loading..."}</span>{" "}
            ({user?.role || "..."})
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={loadClaims}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium bg-white border border-slate-300 rounded-lg hover:bg-slate-50"
          >
            <RefreshCw className={`w-4 h-4 ${busy ? "animate-spin" : ""}`} />
            Refresh
          </button>
          <Link
            href="/fnol"
            className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-semibold bg-slate-900 text-white rounded-lg hover:bg-slate-800"
          >
            <PlusCircle className="w-4 h-4" />
            New FNOL Intimation
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white p-4 rounded-xl border border-slate-200">
          <p className="text-xs font-semibold text-slate-500 uppercase">Visible Portfolio</p>
          <p className="text-2xl font-bold text-slate-900 mt-1">{claims.length}</p>
          <p className="text-xs text-slate-500 mt-1">Tenant & ABAC filtered server-side</p>
        </div>
        <div className="bg-white p-4 rounded-xl border border-slate-200">
          <p className="text-xs font-semibold text-slate-500 uppercase">SLA Breached</p>
          <p className={`text-2xl font-bold mt-1 ${breachedCount > 0 ? "text-red-700" : "text-emerald-700"}`}>
            {breachedCount}
          </p>
          <p className="text-xs text-slate-500 mt-1">IRDAI 24h alloc / 15d survey / 7d decision</p>
        </div>
        <div className="bg-white p-4 rounded-xl border border-slate-200">
          <p className="text-xs font-semibold text-slate-500 uppercase">Low Risk (Fast-Track)</p>
          <p className="text-2xl font-bold text-emerald-700 mt-1">{lowRiskCount}</p>
          <p className="text-xs text-slate-500 mt-1">Straight-through &le; &#8377;25k auto-limit</p>
        </div>
        <div className="bg-white p-4 rounded-xl border border-slate-200">
          <p className="text-xs font-semibold text-slate-500 uppercase">High Risk / Complex</p>
          <p className="text-2xl font-bold text-rose-700 mt-1">{highRiskCount}</p>
          <p className="text-xs text-slate-500 mt-1">
            {evOrTpCount} TP / Multi-Veh / EV · {breachedCount} SLA breached
          </p>
        </div>
      </div>

      <div className="bg-white p-4 rounded-xl border border-slate-200 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search claim #, vehicle reg, policy #..."
            className="w-full pl-9 pr-3 py-2 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-slate-900"
          />
        </div>
        <select
          aria-label="Filter by status"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="text-sm border border-slate-300 rounded-lg px-3 py-2 bg-white"
        >
          <option value="">All Statuses</option>
          <option value="SUBMITTED">SUBMITTED</option>
          <option value="REGISTERED">REGISTERED</option>
          <option value="VALIDATION">VALIDATION</option>
          <option value="TRIAGE">TRIAGE</option>
          <option value="FAST_TRACK">FAST_TRACK</option>
          <option value="SURVEY_REQUIRED">SURVEY_REQUIRED</option>
          <option value="INVESTIGATION_REQUIRED">INVESTIGATION_REQUIRED</option>
          <option value="HUMAN_REVIEW">HUMAN_REVIEW</option>
          <option value="ASSESSMENT">ASSESSMENT</option>
          <option value="ESTIMATE_VALIDATION">ESTIMATE_VALIDATION</option>
          <option value="SETTLEMENT_PENDING_APPROVAL">SETTLEMENT_PENDING_APPROVAL</option>
          <option value="APPROVED">APPROVED</option>
          <option value="PAYMENT_PENDING">PAYMENT_PENDING</option>
          <option value="PAYMENT_RECONCILIATION">PAYMENT_RECONCILIATION</option>
          <option value="EVIDENCE_PENDING">EVIDENCE_PENDING</option>
          <option value="TRIAGED">TRIAGED</option>
          <option value="SURVEY_ASSIGNED">SURVEY_ASSIGNED</option>
          <option value="ESTIMATE_REVIEW">ESTIMATE_REVIEW</option>
          <option value="APPROVAL_PENDING">APPROVAL_PENDING</option>
          <option value="PAYMENT_INITIATED">PAYMENT_INITIATED</option>
          <option value="REPAIR_IN_PROGRESS">REPAIR_IN_PROGRESS</option>
          <option value="CLARIFICATION_REQUESTED">CLARIFICATION_REQUESTED</option>
          <option value="CLOSED">CLOSED</option>
        </select>
        <select
          aria-label="Filter by risk tier"
          value={riskFilter}
          onChange={(e) => setRiskFilter(e.target.value)}
          className="text-sm border border-slate-300 rounded-lg px-3 py-2 bg-white"
        >
          <option value="">All Risk Tiers</option>
          <option value="LOW">LOW RISK — Fast-Track</option>
          <option value="MEDIUM">MEDIUM RISK — Standard</option>
          <option value="HIGH">HIGH RISK — Complex / SIU</option>
        </select>
        <select
          aria-label="Filter by claim type"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="text-sm border border-slate-300 rounded-lg px-3 py-2 bg-white"
        >
          <option value="">All Claim Types</option>
          <option value="cashless">Cashless</option>
          <option value="own_damage">Own Damage</option>
          <option value="reimbursement">Reimbursement</option>
          <option value="third_party">Third Party (TP)</option>
        </select>
      </div>

      {err && (
        <div className="bg-red-50 border border-red-200 text-red-900 p-3 rounded-lg text-sm flex items-center gap-2">
          <AlertCircle className="w-4 h-4" />
          {err}
        </div>
      )}

      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-sm">
            <thead className="bg-slate-50 border-b border-slate-200 text-xs uppercase text-slate-600">
              <tr>
                <th className="px-4 py-3">Claim # / Vehicle</th>
                <th className="px-4 py-3">Risk Path &amp; Type</th>
                <th className="px-4 py-3">Status & SLA</th>
                <th className="px-4 py-3">Est. Loss (INR)</th>
                <th className="px-4 py-3">Next Expected Action</th>
                <th className="px-4 py-3 text-right">Workspace</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {claims.map((c) => (
                <tr key={c.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <div className="font-semibold text-slate-900">{c.claim_number}</div>
                    <div className="text-xs text-slate-500">
                      {c.vehicle_reg_input} · {c.policy_number_input}
                    </div>
                  </td>
                  <td className="px-4 py-3 space-y-1">
                    <div>
                      <RiskTierBadge tier={c.risk_tier} path={c.operational_path} score={c.risk_score} />
                    </div>
                    <div className="text-xs font-medium text-slate-700 capitalize">
                      {c.claim_type.replace("_", " ")} · <span className="text-slate-500 font-normal">{c.queue_name}</span>
                    </div>
                    {(c.injury_or_fatality || c.ev_battery_impacted || c.multiple_vehicles_involved) && (
                      <span className="inline-block px-1.5 py-0.5 text-[10px] font-bold bg-purple-100 text-purple-900 rounded">
                        {c.injury_or_fatality ? "TP INJURY" : c.ev_battery_impacted ? "EV HV BATTERY" : "MULTI-VEHICLE"}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 space-y-1">
                    <div>
                      <StatusPill status={c.status} />
                    </div>
                    <div>
                      <SlaBadge status={c.sla_health} />
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono font-medium text-slate-900">
                    &#8377;{Number(c.estimated_loss_inr).toLocaleString("en-IN")}
                    {c.requires_mandatory_survey && (
                      <div className="text-[11px] text-amber-800 font-sans">Survey Required</div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-700 max-w-xs">
                    {c.next_expected_action}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      href={`/claims/${c.id}`}
                      className="inline-flex items-center px-3 py-1.5 text-xs font-semibold bg-slate-900 text-white rounded-md hover:bg-slate-800"
                    >
                      Open Claim 360
                    </Link>
                  </td>
                </tr>
              ))}
              {claims.length === 0 && !busy && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-slate-500">
                    No claims visible for this role/filter. Try switching persona or registering a new FNOL.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
