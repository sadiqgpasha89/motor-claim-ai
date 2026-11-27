"use client";

import React, { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

export function usePortal<T>(path: string): { data: T | null; error: string | null } {
  const { token } = useAuth();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!token) return;
    apiFetch<T>(path, {}, token).then(setData).catch((e) => setError(e instanceof Error ? e.message : "Not available for your role."));
  }, [token, path]);
  return { data, error };
}

export function PageHeader({ title, intro }: { title: string; intro: string }) {
  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-900">{title}</h1>
      <p className="text-sm text-slate-600">{intro}</p>
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="bg-white p-4 rounded-xl border border-slate-200">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-xl font-bold text-slate-900">{value}</div>
      {hint && <div className="text-[11px] text-slate-500 mt-1">{hint}</div>}
    </div>
  );
}

export function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-white p-5 rounded-xl border border-slate-200 text-sm space-y-2 overflow-x-auto">
      <h2 className="text-base font-bold text-slate-900">{title}</h2>
      {children}
    </section>
  );
}

export function Counts({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data);
  if (!entries.length) return <p className="text-slate-500">No data yet.</p>;
  return (
    <div className="flex flex-wrap gap-2">
      {entries.map(([k, v]) => (
        <span key={k} className="px-2 py-1 bg-slate-100 rounded text-xs">{k}: <b>{v}</b></span>
      ))}
    </div>
  );
}

export function Table({ head, rows }: { head: string[]; rows: React.ReactNode[][] }) {
  if (!rows.length) return <p className="text-slate-500">Nothing to show.</p>;
  return (
    <table className="w-full text-xs">
      <thead><tr className="text-left text-slate-500">{head.map((h) => <th key={h} className="pr-3 py-1">{h}</th>)}</tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className="border-t border-slate-100">{r.map((c, j) => <td key={j} className="pr-3 py-1 align-top">{c}</td>)}</tr>
        ))}
      </tbody>
    </table>
  );
}

export function Status({ error, ready }: { error: string | null; ready: boolean }) {
  if (error) return <div className="p-3 bg-slate-50 border border-slate-200 rounded text-sm">{error}</div>;
  if (!ready) return <p className="text-sm text-slate-500">Loading…</p>;
  return null;
}

export const fmtInr = (n: number) => `INR ${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
