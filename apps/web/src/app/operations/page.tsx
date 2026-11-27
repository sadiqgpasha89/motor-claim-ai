"use client";

import React, { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { SlaBadge } from "@/components/Badges";

interface AdapterRow {
  name: string;
  code: string;
  mode: string;
  status: string;
  latency_ms: number;
}

interface OutboxRow {
  id: string;
  event_type: string;
  aggregate_id: string;
  status: string;
  retry_count: number;
  created_at: string;
}

interface SLARow {
  id: string;
  claim_id: string;
  stage: string;
  status: string;
  due_at: string;
  owner_role: string;
  daily_penalty_inr: string;
}

interface DLQRow {
  id: string;
  claim_id: string;
  task_key: string;
  agent_or_service: string;
  state_at_failure: string;
  failure_reason: string;
  attempt_count: number;
  status: string;
}

export default function OperationsPage() {
  const { token } = useAuth();
  const [adapters, setAdapters] = useState<AdapterRow[]>([]);
  const [outbox, setOutbox] = useState<OutboxRow[]>([]);
  const [dlq, setDlq] = useState<DLQRow[]>([]);
  const [sla, setSla] = useState<{ summary: Record<string, number>; timers: SLARow[] } | null>(null);
  const [analytics, setAnalytics] = useState<Record<string, unknown> | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    if (!token) return;
    apiFetch<{ adapters: AdapterRow[]; outbox_events: OutboxRow[] }>("/api/v1/operations/integrations", {}, token)
      .then((r) => {
        setAdapters(r.adapters);
        setOutbox(r.outbox_events);
      })
      .catch(() => {});
    apiFetch<{ summary: Record<string, number>; timers: SLARow[] }>("/api/v1/operations/sla", {}, token)
      .then(setSla)
      .catch(() => {});
    apiFetch<Record<string, unknown>>("/api/v1/operations/analytics", {}, token)
      .then(setAnalytics)
      .catch(() => {});
    apiFetch<{ items: DLQRow[] }>("/api/v1/orchestration/dlq", {}, token)
      .then((r) => setDlq(r.items))
      .catch(() => {});
  }, [token]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const retryOutbox = async (id: string) => {
    if (!token) return;
    await apiFetch(`/api/v1/operations/outbox/${id}/retry`, { method: "POST" }, token);
    loadAll();
  };

  const replayDlq = async (id: string) => {
    if (!token) return;
    await apiFetch(`/api/v1/orchestration/dlq/${id}/replay`, { method: "POST", body: JSON.stringify({ resolution_notes: "Replayed from Operations Console" }) }, token);
    setMsg(`Replayed DLQ task ${id}.`);
    loadAll();
  };

  const compensateDlq = async (id: string) => {
    if (!token) return;
    await apiFetch(`/api/v1/orchestration/dlq/${id}/compensate`, { method: "POST", body: JSON.stringify({ resolution_notes: "Compensated from Operations Console" }) }, token);
    setMsg(`Executed compensation saga for DLQ task ${id}.`);
    loadAll();
  };

  const sweepSla = async () => {
    if (!token) return;
    const res = await apiFetch<{ breached_count: number; warning_count: number }>("/api/v1/orchestration/sla/sweep", { method: "POST" }, token);
    setMsg(`SLA sweep completed: ${res.breached_count} breached, ${res.warning_count} warning.`);
    loadAll();
  };

  const resetSeed = async () => {
    if (!token) return;
    const res = await apiFetch<{ status: string; note: string }>("/api/v1/operations/seed-reset", { method: "POST" }, token);
    setMsg(res.note);
    loadAll();
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Operations, SLA & Integration Health</h1>
          <p className="text-sm text-slate-600">
            Enterprise adapter health, transactional outbox retries, IRDAI SLA timers, and synthetic portfolio analytics.
          </p>
        </div>
        <button
          type="button"
          onClick={resetSeed}
          className="px-3 py-2 text-xs font-semibold bg-amber-900 text-white rounded-lg hover:bg-amber-800"
        >
          Reset & Reseed Synthetic Demo Data
        </button>
      </div>

      {msg && <div className="p-3 bg-emerald-50 border border-emerald-300 text-emerald-900 text-sm rounded-lg">{msg}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
          <h2 className="text-base font-bold text-slate-900">Integration Adapters Health</h2>
          <div className="space-y-2">
            {adapters.map((a) => (
              <div key={a.code} className="p-3 border border-slate-200 rounded-lg flex items-center justify-between text-xs">
                <div>
                  <div className="font-bold text-slate-900">{a.name}</div>
                  <div className="text-slate-500">Mode: {a.mode} · {a.latency_ms}ms</div>
                </div>
                <span className={`px-2 py-0.5 font-semibold rounded ${a.status === "healthy" ? "bg-emerald-100 text-emerald-900" : "bg-amber-100 text-amber-900"}`}>
                  {a.status}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
          <h2 className="text-base font-bold text-slate-900">Portfolio Analytics (Synthetic Demo)</h2>
          {analytics ? (
            <pre className="text-xs bg-slate-50 p-3 rounded border border-slate-200 overflow-x-auto">
              {JSON.stringify(analytics, null, 2)}
            </pre>
          ) : (
            <p className="text-xs text-slate-500">Switch to Manager/Handler/Auditor role to view analytics.</p>
          )}
        </div>
      </div>

      {sla && (
        <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-base font-bold text-slate-900">
              Active SLA Timers (Breached: {sla.summary.breached}, Warning: {sla.summary.warning})
            </h2>
            <button
              type="button"
              onClick={sweepSla}
              className="px-3 py-1.5 text-xs font-semibold bg-slate-900 text-white rounded-lg"
            >
              Run SLA Breach Sweep
            </button>
          </div>
          <div className="space-y-2">
            {sla.timers.map((t) => (
              <div key={t.id} className="p-3 border border-slate-200 rounded-lg flex flex-wrap items-center justify-between gap-2 text-xs">
                <div>
                  <span className="font-bold text-slate-900">{t.stage}</span> · Owner: {t.owner_role} · Due: {t.due_at.slice(0, 16)}
                  {Number(t.daily_penalty_inr) > 0 && <span className="ml-2 text-red-700 font-semibold">(Penalty &#8377;{t.daily_penalty_inr}/day)</span>}
                </div>
                <SlaBadge status={t.status} />
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
        <h2 className="text-base font-bold text-slate-900">
          Orchestration Dead-Letter Queue (DLQ) ({dlq.length})
        </h2>
        <div className="space-y-2">
          {dlq.map((d) => (
            <div key={d.id} className="p-3 border border-slate-200 rounded-lg flex flex-wrap items-center justify-between gap-2 text-xs">
              <div>
                <div className="font-bold text-slate-900">
                  <code>{d.task_key}</code> ({d.agent_or_service}) · State: {d.state_at_failure} · Attempts: {d.attempt_count} · Status: <span className="uppercase">{d.status}</span>
                </div>
                <div className="text-slate-600 mt-0.5">{d.failure_reason}</div>
              </div>
              {d.status === "open" && (
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => replayDlq(d.id)}
                    className="px-2.5 py-1 bg-slate-900 text-white rounded font-semibold"
                  >
                    Replay Task
                  </button>
                  <button
                    type="button"
                    onClick={() => compensateDlq(d.id)}
                    className="px-2.5 py-1 bg-rose-700 text-white rounded font-semibold"
                  >
                    Compensate
                  </button>
                </div>
              )}
            </div>
          ))}
          {dlq.length === 0 && <p className="text-xs text-slate-500">Zero items in orchestration DLQ.</p>}
        </div>
      </div>

      <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-3">
        <h2 className="text-base font-bold text-slate-900">Transactional Outbox Events</h2>
        <div className="space-y-2">
          {outbox.map((e) => (
            <div key={e.id} className="p-2.5 border border-slate-200 rounded flex items-center justify-between text-xs">
              <span>
                <span className="font-bold">{e.event_type}</span> · Claim {e.aggregate_id.slice(0, 12)} · Retries: {e.retry_count}
              </span>
              <button
                type="button"
                onClick={() => retryOutbox(e.id)}
                className="px-2.5 py-1 border border-slate-300 rounded hover:bg-slate-50"
              >
                Retry ({e.status})
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
