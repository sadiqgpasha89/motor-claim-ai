"use client";

import React, { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

interface RuleRow {
  id: string;
  rule_id: string;
  version: string;
  jurisdiction: string;
  title: string;
  source_reference: string;
  owner: string;
  status: string;
  effective_from: string;
  payload: Record<string, unknown>;
}

interface ClauseHit {
  document_id: string;
  clause_id: string;
  section: string;
  page: number;
  title: string;
  text: string;
  score: number;
  reference: string;
}

export default function GovernancePage() {
  const { token } = useAuth();
  const [rules, setRules] = useState<RuleRow[]>([]);
  const [threshold, setThreshold] = useState("75000.00");
  const [simResult, setSimResult] = useState<Record<string, unknown> | null>(null);
  const [kbQuery, setKbQuery] = useState("zero depreciation ev battery total loss");
  const [kbHits, setKbHits] = useState<ClauseHit[]>([]);
  const [outageSim, setOutageSim] = useState(false);

  useEffect(() => {
    if (!token) return;
    apiFetch<{ items: RuleRow[] }>("/api/v1/rules", {}, token).then((r) => setRules(r.items)).catch(() => {});
    apiFetch<{ ai_outage_simulated: boolean }>("/api/v1/operations/integrations", {}, token)
      .then((r) => setOutageSim(r.ai_outage_simulated))
      .catch(() => {});
  }, [token]);

  const runSim = async (ruleId: string) => {
    if (!token) return;
    const res = await apiFetch<Record<string, unknown>>(
      `/api/v1/rules/${ruleId}/simulate`,
      {
        method: "POST",
        body: JSON.stringify({ sample_estimated_loss_inr: "60000.00", proposed_threshold_inr: threshold }),
      },
      token
    );
    setSimResult(res);
  };

  const searchKb = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;
    const res = await apiFetch<{ results: ClauseHit[] }>(
      `/api/v1/knowledge/search?q=${encodeURIComponent(kbQuery)}`,
      {},
      token
    );
    setKbHits(res.results);
  };

  const toggleOutage = async () => {
    if (!token) return;
    const res = await apiFetch<{ ai_outage_simulated: boolean }>(
      "/api/v1/operations/ai-outage-toggle",
      { method: "POST", body: JSON.stringify({ enabled: !outageSim }) },
      token
    );
    setOutageSim(res.ai_outage_simulated);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Rules, Policy Knowledge & Model Governance</h1>
          <p className="text-sm text-slate-600">
            Effective-dated regulatory rules, policy clause hybrid retrieval, threshold simulation, and model-outage fallback control.
          </p>
        </div>
        <button
          type="button"
          onClick={toggleOutage}
          className={`px-3 py-2 text-xs font-semibold rounded-lg border ${
            outageSim
              ? "bg-red-700 text-white border-red-800"
              : "bg-white text-slate-900 border-slate-300 hover:bg-slate-50"
          }`}
        >
          {outageSim ? "AI Outage Simulation: ON (Manual Fallback)" : "Simulate AI Provider Outage"}
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-4">
          <h2 className="text-base font-bold text-slate-900">Effective-Dated Rules Catalogue</h2>
          <div className="flex items-center gap-2 bg-slate-50 p-3 rounded-lg border border-slate-200">
            <label className="text-xs font-semibold text-slate-700">Simulate Survey Threshold (INR):</label>
            <input
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              className="w-28 px-2 py-1 text-xs border border-slate-300 rounded bg-white"
            />
            <button
              type="button"
              onClick={() => runSim("IN-IRDAI-MC-2024")}
              className="px-3 py-1 text-xs font-semibold bg-slate-900 text-white rounded"
            >
              Run Simulation
            </button>
          </div>
          {simResult && (
            <pre className="text-xs bg-indigo-50 border border-indigo-200 p-3 rounded overflow-x-auto">
              {JSON.stringify(simResult, null, 2)}
            </pre>
          )}

          <div className="space-y-3">
            {rules.map((r) => (
              <div key={r.id} className="p-3 border border-slate-200 rounded-lg text-xs space-y-1">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-slate-900">{r.rule_id} (v{r.version})</span>
                  <span className="px-2 py-0.5 bg-emerald-100 text-emerald-900 rounded font-semibold">
                    {r.status.toUpperCase()}
                  </span>
                </div>
                <div className="font-medium text-slate-800">{r.title}</div>
                <div className="text-slate-500">Source: {r.source_reference} · Owner: {r.owner}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-4">
          <h2 className="text-base font-bold text-slate-900">Hybrid Policy Knowledge Retrieval (BM25 + Vector)</h2>
          <form onSubmit={searchKb} className="flex gap-2">
            <input
              value={kbQuery}
              onChange={(e) => setKbQuery(e.target.value)}
              placeholder="Search approved policy wordings..."
              className="flex-1 px-3 py-2 text-sm border border-slate-300 rounded-lg"
            />
            <button type="submit" className="px-4 py-2 text-sm font-semibold bg-slate-900 text-white rounded-lg">
              Search
            </button>
          </form>
          <div className="space-y-3">
            {kbHits.map((h) => (
              <div key={h.reference} className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs space-y-1">
                <div className="flex items-center justify-between font-bold text-slate-900">
                  <span>{h.reference} — {h.title}</span>
                  <span className="text-indigo-800">score: {h.score}</span>
                </div>
                <div className="text-slate-500">{h.section}</div>
                <p className="text-slate-700 leading-relaxed">{h.text}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
