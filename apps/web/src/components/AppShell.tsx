"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ShieldCheck, AlertTriangle } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const NAV_ITEMS = [
  { href: "/", label: "Command Centre" },
  { href: "/fnol", label: "FNOL Intake" },
  { href: "/agents", label: "11 Agents & Matrix" },
  { href: "/portal", label: "Customer Portal" },
  { href: "/siu", label: "SIU Fraud Desk" },
  { href: "/partners", label: "Ecosystem & Partners" },
  { href: "/governance", label: "Rules & Policy KB" },
  { href: "/operations", label: "Operations & SLA" },
  { href: "/agent-command-center", label: "Agent Command Center" },
  { href: "/platform-health", label: "Platform health" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, demoUsers, switchUser, error } = useAuth();

  return (
    <div className="min-h-screen flex flex-col">
      <div className="bg-amber-950 text-amber-50 text-xs px-4 py-1.5 flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">
          DEMO / SYNTHETIC ENVIRONMENT — All policies, claims, vehicles, rate cards, and payments are synthetic test data.
        </span>
        <span className="opacity-90">
          India-First IRDAI 2024 Controls Active · Deterministic Money Math · Human-in-the-Loop Enforced
        </span>
      </div>

      <header className="bg-white border-b border-slate-200 sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-slate-900 text-white flex items-center justify-center">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <Link href="/" className="text-base font-bold text-slate-900 tracking-tight">
                MotorClaim AI Intelligence
              </Link>
              <p className="text-xs text-slate-500">
                Enterprise Governed Claims Automation
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <label htmlFor="persona-switch" className="text-xs font-semibold text-slate-600">
              Active Persona:
            </label>
            <select
              id="persona-switch"
              aria-label="Switch active demo persona"
              value={user?.email || ""}
              onChange={(e) => switchUser(e.target.value)}
              className="text-xs border border-slate-300 rounded-md px-2.5 py-1.5 bg-slate-50 text-slate-900 font-medium focus:outline-none focus:ring-2 focus:ring-slate-900"
            >
              {demoUsers.map((u) => (
                <option key={u.id} value={u.email}>
                  {u.name} [{u.role}]
                </option>
              ))}
            </select>
          </div>
        </div>

        <nav
          aria-label="Primary Navigation"
          className="max-w-7xl mx-auto px-4 sm:px-6 flex items-center gap-1 overflow-x-auto border-t border-slate-100"
        >
          {NAV_ITEMS.map((item) => {
            const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`px-3 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
                  active
                    ? "border-slate-900 text-slate-900"
                    : "border-transparent text-slate-600 hover:text-slate-900 hover:border-slate-300"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </header>

      {error && (
        <div className="max-w-7xl mx-auto w-full px-4 sm:px-6 mt-4">
          <div className="bg-red-50 border border-red-300 text-red-900 px-4 py-3 rounded-lg text-sm flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>Backend connection notice: {error}</span>
          </div>
        </div>
      )}

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-6">
        {children}
      </main>
    </div>
  );
}
