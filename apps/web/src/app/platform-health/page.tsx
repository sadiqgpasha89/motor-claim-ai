"use client";

import React, { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

interface Integrity { ok: boolean; checked: number; legacy_unchained: number; broken_at?: string; reason?: string }
interface Deliveries { by_status: Record<string, number>; deliveries: { id: string; consumer: string; status: string; attempts: number; last_error: string | null }[] }
interface Resilience { circuit_breakers: { name: string; state: string; consecutive_failures: number }[]; tool_invocations: Record<string, number> }
interface Policy { tool_policy: Record<string, { port: string; allowed_agents: string[]; allowed_roles: string[]; approval_required: boolean; route_only?: boolean }>; checks: string[] }

export default function PlatformHealthPage() {
  const { token } = useAuth();
  const [integrity, setIntegrity] = useState<Integrity | null>(null);
  const [deliveries, setDeliveries] = useState<Deliveries | null>(null);
  const [resilience, setResilience] = useState<Resilience | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    const get = <T,>(path: string) => apiFetch<T>(path, {}, token).catch(() => null);
    const [i, d, r, p] = await Promise.all([
      get<Integrity>("/api/v1/operations/audit/integrity"),
      get<Deliveries>("/api/v1/operations/events/deliveries"),
      get<Resilience>("/api/v1/operations/integration-resilience"),
      get<Policy>("/api/v1/operations/tool-policy"),
    ]);
    setIntegrity(i); setDeliveries(d); setResilience(r); setPolicy(p);
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const act = async (label: string, path: string) => {
    if (!token) return;
    try {
      await apiFetch(path, { method: "POST" }, token);
      setMessage(`${label} done.`);
      await load();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : `${label} failed`);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Platform health</h1>
        <p className="text-sm text-slate-600">Audit integrity, event bus, dependency circuits and the tool policy. Manager, auditor and admin roles. DEMO / SYNTHETIC.</p>
      </div>
      {message && <div className="p-3 bg-slate-50 border border-slate-200 rounded text-sm">{message}</div>}

      <section className="bg-white p-5 rounded-xl border border-slate-200 text-sm space-y-1">
        <h2 className="text-base font-bold text-slate-900">Audit log integrity</h2>
        {integrity ? (
          <p className={integrity.ok ? "text-emerald-800" : "text-red-800"}>
            {integrity.ok ? "Hash chain verified" : `Chain broken at ${integrity.broken_at}: ${integrity.reason}`} · {integrity.checked} events checked · {integrity.legacy_unchained} older events without a hash
          </p>
        ) : <p className="text-slate-500">Not available for your role.</p>}
      </section>

      <section className="bg-white p-5 rounded-xl border border-slate-200 text-sm space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-bold text-slate-900">Event bus</h2>
          <button type="button" onClick={() => act("Dispatch", "/api/v1/operations/events/dispatch")} className="px-3 py-1.5 text-xs font-semibold bg-slate-900 text-white rounded-lg">Dispatch pending events</button>
        </div>
        {deliveries ? (
          <>
            <p>{Object.entries(deliveries.by_status).map(([k, v]) => `${k}: ${v}`).join(" · ") || "No deliveries yet."}</p>
            {deliveries.deliveries.filter((d) => d.status === "dead").map((d) => (
              <div key={d.id} className="flex items-center justify-between p-2 bg-red-50 border border-red-200 rounded text-xs">
                <span>{d.consumer} · dead after {d.attempts} attempts · {d.last_error}</span>
                <button type="button" onClick={() => act("Replay", `/api/v1/operations/events/deliveries/${d.id}/replay`)} className="px-2 py-1 bg-white border border-red-300 rounded">Replay</button>
              </div>
            ))}
          </>
        ) : <p className="text-slate-500">Not available for your role.</p>}
        <button type="button" onClick={() => act("Recovery sweep", "/api/v1/operations/workflows/recover")} className="px-3 py-1.5 text-xs font-semibold border border-slate-300 rounded-lg">Sweep stalled workflows</button>
      </section>

      <section className="bg-white p-5 rounded-xl border border-slate-200 text-sm space-y-1">
        <h2 className="text-base font-bold text-slate-900">Dependency circuits and tool calls</h2>
        {resilience ? (
          <>
            <p>{resilience.circuit_breakers.length ? resilience.circuit_breakers.map((b) => `${b.name}: ${b.state}`).join(" · ") : "No dependency has been called yet."}</p>
            <p className="text-xs text-slate-600">Tool calls: {Object.entries(resilience.tool_invocations).map(([k, v]) => `${k} ${v}`).join(" · ") || "none"}</p>
          </>
        ) : <p className="text-slate-500">Not available for your role.</p>}
      </section>

      <section className="bg-white p-5 rounded-xl border border-slate-200 text-xs space-y-2 overflow-x-auto">
        <h2 className="text-base font-bold text-slate-900">Tool policy (enforced in the backend, not in prompts)</h2>
        {policy ? (
          <>
            <p>Checks on every call: {policy.checks.join(", ")}.</p>
            <table className="w-full"><thead><tr className="text-left text-slate-500"><th>Tool</th><th>System</th><th>Agents</th><th>Roles</th><th>Approval</th></tr></thead><tbody>
              {Object.entries(policy.tool_policy).map(([name, t]) => (
                <tr key={name} className="border-t border-slate-100">
                  <td className="py-1 font-semibold">{name}</td><td>{t.port}</td><td>{t.allowed_agents.join(", ") || "none"}</td><td>{t.allowed_roles.join(", ")}</td>
                  <td>{t.route_only ? "API route only" : t.approval_required ? "required" : "no"}</td>
                </tr>
              ))}
            </tbody></table>
          </>
        ) : <p className="text-slate-500">Not available for your role.</p>}
      </section>
    </div>
  );
}
