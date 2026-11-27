"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { StatusPill } from "@/components/Badges";

interface ProviderRow {
  id: string;
  provider_type: string;
  name: string;
  licence_or_contract_id: string;
  licence_status: string;
  city: string;
  service_zones?: string[];
  skills?: string[];
  ev_capable: boolean;
  is_network: boolean;
  contract_tier?: string;
  active_load: number;
  max_capacity: number;
  load_ratio_pct?: number;
  current_load?: string;
  availability?: string;
  is_available?: boolean;
  sla?: string;
  sla_status?: string;
  rating?: number;
  quality_score: string;
  parts_stock_status?: string;
  parts_lead_time_days?: number;
  pickup_drop_available?: boolean;
}

interface CoordinationRow {
  id: string;
  claim_id: string;
  claim_number: string;
  claim_status: string;
  vehicle_reg: string;
  surveyor: ProviderRow | null;
  surveyor_license_verified: boolean;
  surveyor_selection_explanation: string;
  garage: ProviderRow | null;
  customer_preferred_garage: ProviderRow | null;
  customer_preference_honoured: boolean;
  override_applied: boolean;
  garage_selection_explanation: string;
  inspection_status: string;
  inspection_reschedule_count: number;
  towing_required: boolean;
  towing_status: string;
  pickup_delivery_status: string;
  parts_status: string;
  repair_status: string;
  repair_completion_confirmed: boolean;
  surveyor_followup_count: number;
  surveyor_followup_status: string;
  coordination_explanation: string;
}

interface EcosystemDashboardResponse {
  summary: {
    total_providers: number;
    available_providers: number;
    within_sla_providers: number;
    delayed_providers: number;
    active_coordinations: number;
    scheduled_inspections: number;
    rescheduled_inspections: number;
    open_surveyor_followups: number;
    parts_backorders: number;
    repairs_completed_confirmed: number;
    active_towing_or_pickup: number;
  };
  providers: ProviderRow[];
  coordinations: CoordinationRow[];
}

interface ClaimRow {
  id: string;
  claim_number: string;
  vehicle_reg_input: string;
  status: string;
  next_expected_action: string;
}

export default function PartnersPage() {
  const { token, user, switchUser } = useAuth();
  const [dashboard, setDashboard] = useState<EcosystemDashboardResponse | null>(null);
  const [claims, setClaims] = useState<ClaimRow[]>([]);
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [slaFilter, setSlaFilter] = useState<string>("all");

  const loadData = useCallback(() => {
    if (!token) return;
    apiFetch<EcosystemDashboardResponse>("/api/v1/ecosystem/dashboard", {}, token)
      .then(setDashboard)
      .catch(() => {});
    apiFetch<{ items: ClaimRow[] }>("/api/v1/claims", {}, token)
      .then((r) => setClaims(r.items))
      .catch(() => {});
  }, [token]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const filteredProviders = useMemo(() => {
    const list = dashboard?.providers || [];
    return list.filter((p) => {
      if (typeFilter !== "all" && p.provider_type !== typeFilter) return false;
      if (slaFilter !== "all" && (p.sla || "Within SLA") !== slaFilter) return false;
      return true;
    });
  }, [dashboard, typeFilter, slaFilter]);

  const summary = dashboard?.summary;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Claims Ecosystem Dashboard &amp; Partner Portal</h1>
          <p className="text-sm text-slate-600">
            Unified orchestration across IIISLA surveyors, network/EV garages, towing, parts stock, pickup/delivery, and SLA adherence with explainable selection &amp; customer-choice protection.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => switchUser("handler@demo.in")}
            className="px-3 py-1.5 text-xs font-semibold border border-slate-300 bg-white rounded-lg hover:bg-slate-50"
          >
            Handler View
          </button>
          <button
            type="button"
            onClick={() => switchUser("surveyor@demo.in")}
            className="px-3 py-1.5 text-xs font-semibold border border-slate-300 bg-white rounded-lg hover:bg-slate-50"
          >
            Preview Surveyor View
          </button>
          <button
            type="button"
            onClick={() => switchUser("garage@demo.in")}
            className="px-3 py-1.5 text-xs font-semibold border border-slate-300 bg-white rounded-lg hover:bg-slate-50"
          >
            Preview Garage View
          </button>
        </div>
      </div>

      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
          <div className="bg-white p-3.5 rounded-xl border border-slate-200">
            <div className="text-[11px] font-semibold text-slate-500 uppercase">Available Providers</div>
            <div className="text-xl font-bold text-emerald-700 mt-1">
              {summary.available_providers} / {summary.total_providers}
            </div>
          </div>
          <div className="bg-white p-3.5 rounded-xl border border-slate-200">
            <div className="text-[11px] font-semibold text-slate-500 uppercase">Within SLA / Delayed</div>
            <div className="text-xl font-bold text-slate-900 mt-1">
              {summary.within_sla_providers} <span className="text-xs font-semibold text-rose-700">({summary.delayed_providers} delayed)</span>
            </div>
          </div>
          <div className="bg-white p-3.5 rounded-xl border border-slate-200">
            <div className="text-[11px] font-semibold text-slate-500 uppercase">Inspections / Resched.</div>
            <div className="text-xl font-bold text-blue-700 mt-1">
              {summary.scheduled_inspections} <span className="text-xs font-normal text-slate-500">({summary.rescheduled_inspections} resched.)</span>
            </div>
          </div>
          <div className="bg-white p-3.5 rounded-xl border border-slate-200">
            <div className="text-[11px] font-semibold text-slate-500 uppercase">Surveyor Follow-ups</div>
            <div className="text-xl font-bold text-amber-700 mt-1">{summary.open_surveyor_followups}</div>
          </div>
          <div className="bg-white p-3.5 rounded-xl border border-slate-200">
            <div className="text-[11px] font-semibold text-slate-500 uppercase">Parts Backorders</div>
            <div className="text-xl font-bold text-rose-700 mt-1">{summary.parts_backorders}</div>
          </div>
          <div className="bg-white p-3.5 rounded-xl border border-slate-200">
            <div className="text-[11px] font-semibold text-slate-500 uppercase">Repairs Confirmed</div>
            <div className="text-xl font-bold text-emerald-700 mt-1">{summary.repairs_completed_confirmed}</div>
          </div>
        </div>
      )}

      {/* Ecosystem Dashboard Table */}
      <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-bold text-slate-900">Ecosystem Provider Scorecard Dashboard</h2>
            <p className="text-xs text-slate-600">
              Live availability, SLA health, quality rating, current load band, IIISLA licence verification, skills, geography, and parts stock.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            <select
              aria-label="Filter provider type"
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="px-2.5 py-1.5 border border-slate-300 rounded-lg bg-white font-medium"
            >
              <option value="all">All Provider Types</option>
              <option value="garage">Garages</option>
              <option value="surveyor">Surveyors</option>
              <option value="towing">Towing &amp; Recovery</option>
            </select>
            <select
              aria-label="Filter SLA status"
              value={slaFilter}
              onChange={(e) => setSlaFilter(e.target.value)}
              className="px-2.5 py-1.5 border border-slate-300 rounded-lg bg-white font-medium"
            >
              <option value="all">All SLA States</option>
              <option value="Within SLA">Within SLA</option>
              <option value="At Risk">At Risk</option>
              <option value="Delayed">Delayed</option>
            </select>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs text-left border-collapse">
            <thead className="bg-slate-50 border-b border-slate-200 text-slate-700">
              <tr>
                <th className="p-2.5">Provider</th>
                <th className="p-2.5">Availability</th>
                <th className="p-2.5">SLA</th>
                <th className="p-2.5">Rating</th>
                <th className="p-2.5">Current load</th>
                <th className="p-2.5">Geography &amp; Skills</th>
                <th className="p-2.5">Licence &amp; Parts</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filteredProviders.map((p) => {
                const avail = p.availability || "Available";
                const slaLabel = p.sla || "Within SLA";
                const loadBand = p.current_load || "Low";
                const availCls =
                  avail === "Available"
                    ? "bg-emerald-100 text-emerald-900"
                    : avail === "Busy"
                    ? "bg-amber-100 text-amber-950"
                    : "bg-rose-100 text-rose-900";
                const slaCls =
                  slaLabel === "Within SLA"
                    ? "bg-emerald-100 text-emerald-900"
                    : slaLabel === "At Risk"
                    ? "bg-amber-100 text-amber-950"
                    : "bg-rose-100 text-rose-900";
                const loadCls =
                  loadBand === "Low"
                    ? "bg-emerald-50 text-emerald-900 border-emerald-200"
                    : loadBand === "Medium"
                    ? "bg-amber-50 text-amber-950 border-amber-200"
                    : "bg-rose-50 text-rose-900 border-rose-200";
                return (
                  <tr key={p.id} className="hover:bg-slate-50/60">
                    <td className="p-2.5">
                      <div className="font-bold text-slate-900">{p.name}</div>
                      <div className="text-[11px] text-slate-500 uppercase">
                        {p.provider_type} · {p.contract_tier || (p.is_network ? "network" : "non_network")}
                      </div>
                    </td>
                    <td className="p-2.5">
                      <span className={`px-2 py-0.5 rounded font-semibold ${availCls}`}>{avail}</span>
                    </td>
                    <td className="p-2.5">
                      <span className={`px-2 py-0.5 rounded font-semibold ${slaCls}`}>{slaLabel}</span>
                    </td>
                    <td className="p-2.5 font-mono font-bold text-slate-900">
                      {Number(p.rating ?? p.quality_score).toFixed(1)}
                    </td>
                    <td className="p-2.5">
                      <span className={`px-2 py-0.5 rounded border font-semibold ${loadCls}`}>
                        {loadBand}
                      </span>
                      <span className="ml-1.5 text-[11px] font-mono text-slate-500">
                        ({p.active_load}/{p.max_capacity})
                      </span>
                    </td>
                    <td className="p-2.5 text-[11px] text-slate-600">
                      <div>
                        <strong>{p.city}</strong> {(p.service_zones || []).slice(0, 2).join(", ")}
                      </div>
                      <div className="flex flex-wrap gap-1 mt-0.5">
                        {p.ev_capable && (
                          <span className="px-1.5 py-0.2 bg-indigo-100 text-indigo-900 rounded font-semibold">
                            EV HV
                          </span>
                        )}
                        {(p.skills || []).slice(0, 3).map((sk) => (
                          <span key={sk} className="px-1.5 py-0.2 bg-slate-100 text-slate-700 rounded">
                            {sk}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="p-2.5 text-[11px]">
                      <div className={p.licence_status === "verified" ? "text-emerald-800 font-semibold" : "text-rose-800 font-bold"}>
                        {p.licence_status.toUpperCase()} ({p.licence_or_contract_id})
                      </div>
                      {p.provider_type === "garage" && (
                        <div className="text-slate-600 mt-0.5">
                          Parts: <strong>{p.parts_stock_status}</strong> ({p.parts_lead_time_days}d) ·{" "}
                          {p.pickup_drop_available ? "Pickup/Drop" : "No Pickup"}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Active Ecosystem Coordinations */}
      <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
        <h2 className="text-base font-bold text-slate-900">
          Ecosystem Coordination &amp; Selection Explainability ({dashboard?.coordinations.length || 0})
        </h2>
        <div className="space-y-3">
          {(dashboard?.coordinations || []).map((cd) => (
            <div key={cd.id} className="p-4 border border-slate-200 rounded-xl text-xs space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-bold text-sm text-slate-900">
                    {cd.claim_number} · {cd.vehicle_reg}
                  </span>
                  <StatusPill status={cd.claim_status} />
                  {cd.customer_preference_honoured ? (
                    <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-900 font-semibold">
                      Customer Choice Honoured
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded bg-amber-100 text-amber-950 font-semibold">
                      Authorized Contractual Override
                    </span>
                  )}
                  {cd.repair_completion_confirmed && (
                    <span className="px-2 py-0.5 rounded bg-blue-100 text-blue-900 font-semibold">
                      Repair Completion Confirmed
                    </span>
                  )}
                </div>
                <Link href={`/claims/${cd.claim_id}`} className="px-3 py-1.5 bg-slate-900 text-white rounded font-semibold">
                  Manage in Claim 360
                </Link>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-2 bg-slate-50 p-2.5 rounded-lg border border-slate-200">
                <div><span className="text-slate-500">Inspection:</span> <strong>{cd.inspection_status}</strong> {cd.inspection_reschedule_count > 0 ? `(resched ${cd.inspection_reschedule_count}x)` : ""}</div>
                <div><span className="text-slate-500">Follow-ups:</span> <strong>{cd.surveyor_followup_count}</strong> ({cd.surveyor_followup_status})</div>
                <div><span className="text-slate-500">Parts:</span> <strong>{cd.parts_status}</strong></div>
                <div><span className="text-slate-500">Towing / Pickup:</span> <strong>{cd.towing_status} / {cd.pickup_delivery_status}</strong></div>
                <div><span className="text-slate-500">Repair:</span> <strong>{cd.repair_status}</strong></div>
              </div>
              {cd.coordination_explanation && (
                <div className="text-slate-700">
                  <strong>Why Selected:</strong> {cd.coordination_explanation}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
        <h2 className="text-base font-bold text-slate-900">
          Assigned Jobs for Current Persona ({user?.role})
        </h2>
        <div className="space-y-2">
          {claims.map((c) => (
            <div key={c.id} className="p-3 border border-slate-200 rounded-lg flex items-center justify-between gap-3">
              <div>
                <div className="font-semibold text-sm">{c.claim_number} · {c.vehicle_reg_input}</div>
                <div className="text-xs text-slate-600">{c.next_expected_action}</div>
              </div>
              <div className="flex items-center gap-2">
                <StatusPill status={c.status} />
                <Link href={`/claims/${c.id}`} className="px-3 py-1.5 text-xs font-semibold bg-slate-900 text-white rounded">
                  Open Job
                </Link>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
