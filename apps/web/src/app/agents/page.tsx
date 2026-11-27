"use client";

import React, { useEffect, useState } from "react";
import { Cpu, GitBranch, ShieldCheck, Zap } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

interface AgentContract {
  agent_name: string;
  display_name: string;
  stage: string;
  operational_responsibility: string;
  required_capabilities: string[];
  input_contract: Record<string, string>;
  output_contract: Record<string, string>;
  allowed_tools: string[];
  authorised_actions: string[];
  prohibited_actions: string[];
  depends_on: string[];
  can_request_rework_from: string[];
  human_gate_condition: string;
  timeout_seconds: number;
  max_retries: number;
}

export default function AgentCapabilityMatrixPage() {
  const { token } = useAuth();
  const [contracts, setContracts] = useState<AgentContract[]>([]);
  const [selectedName, setSelectedName] = useState<string>("fnol_concierge");

  useEffect(() => {
    if (!token) return;
    apiFetch<{ contracts: AgentContract[] }>("/api/v1/agents/contracts", {}, token)
      .then((res) => {
        setContracts(res.contracts);
        if (res.contracts.length > 0) setSelectedName(res.contracts[0].agent_name);
      })
      .catch(() => {});
  }, [token]);

  const selected = contracts.find((c) => c.agent_name === selectedName) || contracts[0];

  return (
    <div className="space-y-6">
      <div className="bg-white p-5 rounded-xl border border-slate-200 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">
              11 Bounded Agents — Capability Matrix &amp; Orchestration Contracts
            </h1>
            <p className="text-sm text-slate-600">
              Upgraded in-place (zero agent duplication). Each bounded agent enforces typed input/output contracts,
              DAG dependencies, controlled action execution, rework requests, and explainable Decision Intelligence.
            </p>
          </div>
          <span className="px-3 py-1 text-xs font-bold bg-slate-900 text-white rounded-full">
            {contracts.length || 11} Bounded Agents
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2 text-xs">
          <div className="p-3 rounded-lg bg-blue-50 border border-blue-200 text-blue-950">
            <div className="font-bold flex items-center gap-1.5">
              <GitBranch className="w-4 h-4" /> A. Agent-to-Agent Orchestration
            </div>
            <p className="mt-1">
              Structured publications, strict upstream dependency gating, stage rework loops, retries, timeout escalation,
              and recovery.
            </p>
          </div>
          <div className="p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-950">
            <div className="font-bold flex items-center gap-1.5">
              <Zap className="w-4 h-4" /> B. Controlled Action-Taking
            </div>
            <p className="mt-1">
              Creates claim tasks, requests documents, schedules surveyors, notifies garages, dispatches towing, updates
              statuses, generates approvals, and releases Finance-approved payments.
            </p>
          </div>
          <div className="p-3 rounded-lg bg-indigo-50 border border-indigo-200 text-indigo-950">
            <div className="font-bold flex items-center gap-1.5">
              <ShieldCheck className="w-4 h-4" /> C. Decision Intelligence
            </div>
            <p className="mt-1">
              Every decision emits evidence, policy/rule references, reason codes, confidence, routing outcome, and
              human-readable explanation.
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="space-y-2">
          {contracts.map((c, idx) => (
            <button
              key={c.agent_name}
              type="button"
              onClick={() => setSelectedName(c.agent_name)}
              className={`w-full text-left p-3.5 rounded-xl border transition-all ${
                selected?.agent_name === c.agent_name
                  ? "bg-slate-900 text-white border-slate-900"
                  : "bg-white text-slate-900 border-slate-200 hover:border-slate-400"
              }`}
            >
              <div className="flex items-center justify-between text-[11px] font-bold uppercase opacity-75">
                <span>
                  #{idx + 1} · {c.stage}
                </span>
                <span>{c.timeout_seconds}s / {c.max_retries} retries</span>
              </div>
              <div className="font-bold text-sm mt-0.5 flex items-center gap-1.5">
                <Cpu className="w-4 h-4" />
                {c.display_name}
              </div>
              <div className="text-xs opacity-80 mt-0.5 font-mono">{c.agent_name}</div>
            </button>
          ))}
        </div>

        {selected && (
          <div className="lg:col-span-2 bg-white p-6 rounded-xl border border-slate-200 space-y-5 h-fit">
            <div className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-200 pb-4">
              <div>
                <span className="text-xs font-bold uppercase text-blue-700">{selected.stage}</span>
                <h2 className="text-xl font-bold text-slate-900">{selected.display_name}</h2>
                <p className="text-sm text-slate-600 mt-1">{selected.operational_responsibility}</p>
              </div>
              <code className="px-2.5 py-1 bg-slate-100 rounded text-xs font-semibold text-slate-800">
                {selected.agent_name}
              </code>
            </div>

            <div>
              <h3 className="text-xs font-bold uppercase text-slate-500 mb-2">Upgraded Capabilities</h3>
              <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
                {selected.required_capabilities.map((cap) => (
                  <li key={cap} className="p-2 bg-slate-50 border border-slate-200 rounded font-medium text-slate-800">
                    {cap}
                  </li>
                ))}
              </ul>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
              <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 space-y-1.5">
                <div className="font-bold uppercase text-slate-500">Input Contract</div>
                {Object.entries(selected.input_contract).map(([k, v]) => (
                  <div key={k}>
                    <code className="font-semibold text-slate-900">{k}</code>: <span className="text-slate-600">{v}</span>
                  </div>
                ))}
              </div>
              <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 space-y-1.5">
                <div className="font-bold uppercase text-slate-500">Published Output Contract</div>
                {Object.entries(selected.output_contract).map(([k, v]) => (
                  <div key={k}>
                    <code className="font-semibold text-slate-900">{k}</code>: <span className="text-slate-600">{v}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
              <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg space-y-1.5">
                <div className="font-bold uppercase text-emerald-900">Authorised Controlled Actions</div>
                <div className="flex flex-wrap gap-1.5">
                  {selected.authorised_actions.map((a) => (
                    <span key={a} className="px-2 py-0.5 bg-white border border-emerald-300 rounded font-mono text-emerald-900">
                      {a}
                    </span>
                  ))}
                </div>
              </div>
              <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg space-y-1.5">
                <div className="font-bold uppercase text-rose-900">Prohibited Boundaries</div>
                <div className="flex flex-wrap gap-1.5">
                  {selected.prohibited_actions.map((a) => (
                    <span key={a} className="px-2 py-0.5 bg-white border border-rose-300 rounded font-mono text-rose-900">
                      {a}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
              <div className="p-3 border border-slate-200 rounded-lg">
                <div className="font-bold uppercase text-slate-500 mb-1">DAG Dependencies &amp; Rework Paths</div>
                <div>
                  <strong>Depends on:</strong>{" "}
                  {selected.depends_on.length > 0 ? selected.depends_on.join(", ") : "None (Entry stage)"}
                </div>
                <div className="mt-1">
                  <strong>Can request rework from:</strong>{" "}
                  {selected.can_request_rework_from.length > 0
                    ? selected.can_request_rework_from.join(", ")
                    : "None"}
                </div>
              </div>
              <div className="p-3 border border-amber-200 bg-amber-50 rounded-lg">
                <div className="font-bold uppercase text-amber-900 mb-1">Human Gate Condition</div>
                <div className="text-amber-950">{selected.human_gate_condition}</div>
              </div>
            </div>

            <div className="text-xs">
              <div className="font-bold uppercase text-slate-500 mb-1.5">Allowlisted Tools</div>
              <div className="flex flex-wrap gap-1.5">
                {selected.allowed_tools.map((t) => (
                  <span key={t} className="px-2 py-0.5 bg-blue-50 border border-blue-200 text-blue-900 rounded font-mono">
                    {t}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
