"use client";

import React, { useEffect, useState } from "react";
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
  ev_capable: boolean;
  is_network: boolean;
  active_load: number;
  max_capacity: number;
  quality_score: string;
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
  const [providers, setProviders] = useState<ProviderRow[]>([]);
  const [claims, setClaims] = useState<ClaimRow[]>([]);

  useEffect(() => {
    if (!token) return;
    apiFetch<{ items: ProviderRow[] }>("/api/v1/providers", {}, token)
      .then((r) => setProviders(r.items))
      .catch(() => {});
    apiFetch<{ items: ClaimRow[] }>("/api/v1/claims", {}, token)
      .then((r) => setClaims(r.items))
      .catch(() => {});
  }, [token]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Surveyor & Garage Partner Portal</h1>
          <p className="text-sm text-slate-600">
            Verified IIISLA surveyors, EV-certified & network garages, capacity scorecards, and partner-isolated assignments.
          </p>
        </div>
        <div className="flex gap-2">
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

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {providers.map((p) => (
          <div key={p.id} className="bg-white p-4 rounded-xl border border-slate-200 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase px-2 py-0.5 rounded bg-slate-100 text-slate-800">
                {p.provider_type}
              </span>
              <span className="text-xs font-semibold text-emerald-800">
                Licence: {p.licence_status.toUpperCase()} ({p.licence_or_contract_id})
              </span>
            </div>
            <div className="font-bold text-slate-900">{p.name}</div>
            <div className="text-xs text-slate-600 flex flex-wrap gap-3">
              <span>City: {p.city}</span>
              <span>Load: {p.active_load}/{p.max_capacity}</span>
              <span>Quality: {p.quality_score}/5.0</span>
              {p.ev_capable && <span className="font-semibold text-indigo-800">EV HV Certified</span>}
            </div>
          </div>
        ))}
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
