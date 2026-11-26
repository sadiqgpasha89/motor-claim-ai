"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { StatusPill } from "@/components/Badges";

interface ClaimItem {
  id: string;
  claim_number: string;
  vehicle_reg_input: string;
  status: string;
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

  useEffect(() => {
    if (!token) return;
    apiFetch<{ items: ClaimItem[] }>("/api/v1/claims", {}, token)
      .then((res) => {
        setClaims(res.items);
        if (res.items.length > 0 && !selectedId) setSelectedId(res.items[0].id);
      })
      .catch(() => {});
  }, [token, selectedId]);

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
    setMsg(`Grievance acknowledged immediately (ID: ${res.grievance_id}). IRDAI 14-day resolution due by ${res.due_at.slice(0, 10)}.`);
    setGrievanceDesc("");
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Customer Self-Service Portal</h1>
          <p className="text-sm text-slate-600">
            Track live claim status, upload missing documents, view itemized settlement reasons, or raise a grievance.
          </p>
        </div>
        {user?.role !== "policyholder" && (
          <button
            type="button"
            onClick={() => switchUser("policyholder@demo.in")}
            className="px-3 py-2 text-xs font-semibold bg-indigo-900 text-white rounded-lg hover:bg-indigo-800"
          >
            Preview as Policyholder (Aarav Deshmukh)
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-white p-5 rounded-xl border border-slate-200 space-y-4">
          <h2 className="text-base font-bold text-slate-900">Your Motor Claims</h2>
          <div className="space-y-3">
            {claims.map((c) => (
              <div key={c.id} className="p-4 rounded-lg border border-slate-200 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="font-bold text-slate-900">{c.claim_number} · {c.vehicle_reg_input}</div>
                  <div className="text-xs text-slate-600 mt-0.5">Next step: {c.next_expected_action}</div>
                </div>
                <div className="flex items-center gap-3">
                  <StatusPill status={c.status} />
                  <Link
                    href={`/claims/${c.id}`}
                    className="px-3 py-1.5 text-xs font-semibold bg-slate-900 text-white rounded-md"
                  >
                    View Details / Upload
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </div>

        <form onSubmit={submitGrievance} className="bg-white p-5 rounded-xl border border-slate-200 space-y-3 h-fit">
          <h2 className="text-base font-bold text-slate-900">Raise a Grievance / Request Callback</h2>
          <p className="text-xs text-slate-600">
            Immediate acknowledgement & 14-day resolution SLA per IRDAI Master Circular 2024.
          </p>
          {msg && <div className="p-2.5 bg-emerald-50 border border-emerald-300 text-emerald-900 text-xs rounded">{msg}</div>}
          <select
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
            className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white"
          >
            {claims.map((c) => (
              <option key={c.id} value={c.id}>{c.claim_number}</option>
            ))}
          </select>
          <select
            value={grievanceCat}
            onChange={(e) => setGrievanceCat(e.target.value)}
            className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white"
          >
            <option value="surveyor_delay">Surveyor Delay</option>
            <option value="settlement_clarification">Settlement Deduction Clarification</option>
            <option value="repair_quality">Garage Repair Quality</option>
            <option value="callback_request">Callback Request</option>
          </select>
          <textarea
            required
            rows={3}
            value={grievanceDesc}
            onChange={(e) => setGrievanceDesc(e.target.value)}
            placeholder="Describe your concern or appeal..."
            className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg"
          />
          <button
            type="submit"
            className="w-full py-2 bg-slate-900 text-white text-sm font-semibold rounded-lg hover:bg-slate-800"
          >
            Submit Grievance
          </button>
        </form>
      </div>
    </div>
  );
}
