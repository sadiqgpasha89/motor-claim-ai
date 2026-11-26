"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, AlertTriangle } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

const LABELS = {
  "en-IN": {
    title: "Guided Motor Claim Intimation (FNOL)",
    subtitle: "Incomplete documents never block registration (IRDAI Master Circular 2024).",
    policyLabel: "Policy Number",
    vehicleLabel: "Vehicle Registration Number",
    locationLabel: "Incident Location",
    descLabel: "What happened? (Incident Description)",
    submitBtn: "Register & Acknowledge Claim",
  },
  "hi-IN": {
    title: "मोटर दावा सूचना पंजीकरण (FNOL)",
    subtitle: "अधूरे दस्तावेज़ों के कारण दावा पंजीकरण रोका नहीं जाएगा (IRDAI 2024)।",
    policyLabel: "पॉलिसी संख्या (Policy Number)",
    vehicleLabel: "वाहन पंजीकरण संख्या (Vehicle Reg)",
    locationLabel: "दुर्घटना स्थान (Location)",
    descLabel: "घटना का विवरण (Incident Description)",
    submitBtn: "दावा पंजीकृत करें (Register Claim)",
  },
};

export default function FNOLPage() {
  const { token } = useAuth();
  const [lang, setLang] = useState<"en-IN" | "hi-IN">("en-IN");
  const [policyNumber, setPolicyNumber] = useState("POL-IN-DEMO-2026-1001");
  const [vehicleReg, setVehicleReg] = useState("MH02DEMO1042");
  const [claimType, setClaimType] = useState("cashless");
  const [perilCause, setPerilCause] = useState("road_accident");
  const [location, setLocation] = useState("Link Road, Malad West, Mumbai");
  const [description, setDescription] = useState(
    "Front bumper and right headlamp impacted at traffic signal."
  );
  const [estimatedLoss, setEstimatedLoss] = useState("58000.00");
  const [injury, setInjury] = useState(false);
  const [evBattery, setEvBattery] = useState(false);
  const [immobile, setImmobile] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    claim: { id: string; claim_number: string; requires_mandatory_survey: boolean };
    acknowledgement: string;
    duplicate_review_alert?: string | null;
  } | null>(null);

  // Auto-save draft to localStorage
  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(
      "mc_fnol_draft",
      JSON.stringify({ policyNumber, vehicleReg, location, description, estimatedLoss })
    );
  }, [policyNumber, vehicleReg, location, description, estimatedLoss]);

  const t = LABELS[lang];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;
    setSubmitting(true);
    setError(null);
    try {
      const idemKey = `ui-fnol-${Date.now()}`;
      const res = await apiFetch<typeof result>(
        "/api/v1/claims/intimations",
        {
          method: "POST",
          headers: { "Idempotency-Key": idemKey },
          body: JSON.stringify({
            idempotency_key: idemKey,
            policy_number: policyNumber,
            vehicle_reg: vehicleReg,
            claim_type: claimType,
            peril_cause: perilCause,
            intake_channel: "web",
            incident_location: location,
            incident_description: description,
            estimated_loss_inr: estimatedLoss,
            injury_or_fatality: injury,
            ev_battery_impacted: evBattery,
            vehicle_immobile: immobile,
            preferred_language: lang,
          }),
        },
        token
      );
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to register claim");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{t.title}</h1>
          <p className="text-sm text-slate-600">{t.subtitle}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setLang(lang === "en-IN" ? "hi-IN" : "en-IN")}
            className="px-3 py-1.5 text-xs font-semibold border border-slate-300 rounded-lg bg-white hover:bg-slate-50"
          >
            Language: {lang === "en-IN" ? "English (Switch to हिन्दी)" : "हिन्दी (Switch to English)"}
          </button>
        </div>
      </div>

      <div className="bg-slate-100 p-3 rounded-lg flex flex-wrap gap-2 text-xs">
        <span className="font-semibold text-slate-700">Quick-fill Synthetic Policy:</span>
        <button
          type="button"
          onClick={() => {
            setPolicyNumber("POL-IN-DEMO-2026-1001");
            setVehicleReg("MH02DEMO1042");
            setEvBattery(false);
            setClaimType("cashless");
          }}
          className="px-2.5 py-1 bg-white border border-slate-300 rounded hover:bg-slate-50"
        >
          Private Car (Maruti Baleno)
        </button>
        <button
          type="button"
          onClick={() => {
            setPolicyNumber("POL-IN-DEMO-2026-EV02");
            setVehicleReg("MH01EVDEMO99");
            setEvBattery(true);
            setPerilCause("ev_high_voltage");
            setEstimatedLoss("160000.00");
          }}
          className="px-2.5 py-1 bg-white border border-slate-300 rounded hover:bg-slate-50"
        >
          EV High-Voltage (Tata Nexon EV)
        </button>
      </div>

      {result && (
        <div className="bg-emerald-50 border border-emerald-300 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2 text-emerald-900 font-bold text-lg">
            <CheckCircle2 className="w-5 h-5" />
            Claim Registered: {result.claim.claim_number}
          </div>
          <p className="text-sm text-emerald-900">{result.acknowledgement}</p>
          {result.duplicate_review_alert && (
            <div className="bg-amber-100 text-amber-950 p-2.5 rounded text-xs font-medium">
              Review Notice: {result.duplicate_review_alert} (flagged for handler review; never auto-merged)
            </div>
          )}
          <div className="flex gap-3 pt-1">
            <Link
              href={`/claims/${result.claim.id}`}
              className="px-4 py-2 bg-slate-900 text-white text-sm font-semibold rounded-lg hover:bg-slate-800"
            >
              Open Claim 360 & Upload Evidence
            </Link>
          </div>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-300 text-red-900 p-3 rounded-lg text-sm flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" />
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="bg-white p-6 rounded-xl border border-slate-200 space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">{t.policyLabel}</label>
            <input
              required
              value={policyNumber}
              onChange={(e) => setPolicyNumber(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">{t.vehicleLabel}</label>
            <input
              required
              value={vehicleReg}
              onChange={(e) => setVehicleReg(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">Claim Type</label>
            <select
              value={claimType}
              onChange={(e) => setClaimType(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white"
            >
              <option value="cashless">Cashless Network Repair</option>
              <option value="own_damage">Own Damage (OD)</option>
              <option value="reimbursement">Reimbursement</option>
              <option value="theft">Theft</option>
              <option value="third_party">Third-Party (TP)</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">Estimated Loss (INR)</label>
            <input
              type="number"
              step="0.01"
              value={estimatedLoss}
              onChange={(e) => setEstimatedLoss(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">{t.locationLabel}</label>
          <input
            required
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg"
          />
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">{t.descLabel}</label>
          <textarea
            required
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg"
          />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1 text-sm">
          <label className="flex items-center gap-2 p-2.5 border border-slate-200 rounded-lg cursor-pointer">
            <input type="checkbox" checked={immobile} onChange={(e) => setImmobile(e.target.checked)} />
            <span>Vehicle Immobile / Towing</span>
          </label>
          <label className="flex items-center gap-2 p-2.5 border border-slate-200 rounded-lg cursor-pointer">
            <input type="checkbox" checked={injury} onChange={(e) => setInjury(e.target.checked)} />
            <span>Injury / Fatality (TP Queue)</span>
          </label>
          <label className="flex items-center gap-2 p-2.5 border border-slate-200 rounded-lg cursor-pointer">
            <input type="checkbox" checked={evBattery} onChange={(e) => setEvBattery(e.target.checked)} />
            <span>EV Battery / HV Warning</span>
          </label>
        </div>

        <button
          type="submit"
          disabled={submitting || !token}
          className="w-full py-2.5 bg-slate-900 text-white font-semibold text-sm rounded-lg hover:bg-slate-800 disabled:opacity-50"
        >
          {submitting ? "Registering..." : t.submitBtn}
        </button>
      </form>
    </div>
  );
}
