"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, AlertTriangle, Mic, MessageSquare, Smartphone, Globe } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

type LangCode = "en-IN" | "hi-IN" | "mr-IN" | "ta-IN" | "kn-IN";
type IntakeChannel = "web" | "mobile" | "whatsapp" | "voice";

const LABELS: Record<
  LangCode,
  {
    title: string;
    subtitle: string;
    policyLabel: string;
    vehicleLabel: string;
    locationLabel: string;
    descLabel: string;
    submitBtn: string;
  }
> = {
  "en-IN": {
    title: "Guided Omnichannel Motor Claim Intimation (FNOL)",
    subtitle: "Web, Mobile, WhatsApp & Voice intake. Incomplete documents never block registration (IRDAI 2024).",
    policyLabel: "Policy Number",
    vehicleLabel: "Vehicle Registration Number",
    locationLabel: "Accident Location & Landmark",
    descLabel: "Structured Incident Description / Transcript",
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
  "mr-IN": {
    title: "मोटर दावा नोंदणी (FNOL)",
    subtitle: "अपूर्ण कागदपत्रांमुळे दावा नोंदणी थांबवली जाणार नाही (IRDAI 2024).",
    policyLabel: "पॉलिसी क्रमांक",
    vehicleLabel: "वाहन नोंदणी क्रमांक",
    locationLabel: "अपघात ठिकाण",
    descLabel: "घटनेचा तपशील",
    submitBtn: "दावा नोंदवा",
  },
  "ta-IN": {
    title: "மோட்டார் காப்பீட்டு கோரிக்கை பதிவு (FNOL)",
    subtitle: "ஆவணங்கள் குறைவாக இருந்தாலும் பதிவு தடுக்கப்படாது (IRDAI 2024).",
    policyLabel: "பாலிசி எண்",
    vehicleLabel: "வாகன பதிவு எண்",
    locationLabel: "விபத்து இடம்",
    descLabel: "விபத்து விவரம்",
    submitBtn: "கோரிக்கையை பதிவு செய்க",
  },
  "kn-IN": {
    title: "ಮೋಟಾರ್ ಕ್ಲೈಮ್ ನೋಂದಣಿ (FNOL)",
    subtitle: "ದಾಖಲೆಗಳ ಕೊರತೆಯಿಂದ ನೋಂದಣಿ ತಡೆಯಲಾಗುವುದಿಲ್ಲ (IRDAI 2024).",
    policyLabel: "ಪಾಲಿಸಿ ಸಂಖ್ಯೆ",
    vehicleLabel: "ವಾಹನ ನೋಂದಣಿ ಸಂಖ್ಯೆ",
    locationLabel: "ಅಪಘಾತದ ಸ್ಥಳ",
    descLabel: "ಘಟನೆಯ ವಿವರ",
    submitBtn: "ಕ್ಲೈಮ್ ನೋಂದಾಯಿಸಿ",
  },
};

export default function FNOLPage() {
  const { token } = useAuth();
  const [lang, setLang] = useState<LangCode>("en-IN");
  const [intakeChannel, setIntakeChannel] = useState<IntakeChannel>("web");
  const [policyNumber, setPolicyNumber] = useState("POL-IN-DEMO-2026-1001");
  const [vehicleReg, setVehicleReg] = useState("MH02DEMO1042");
  const [claimType, setClaimType] = useState("cashless");
  const [perilCause, setPerilCause] = useState("road_accident");
  const [location, setLocation] = useState("Link Road, Malad West, Mumbai");
  const [geoCoords, setGeoCoords] = useState("19.1872, 72.8354");
  const [description, setDescription] = useState(
    "Front bumper and right headlamp impacted at traffic signal."
  );
  const [estimatedLoss, setEstimatedLoss] = useState("58000.00");
  const [injury, setInjury] = useState(false);
  const [evBattery, setEvBattery] = useState(false);
  const [immobile, setImmobile] = useState(false);
  const [towingNeeded, setTowingNeeded] = useState(false);
  const [airbags, setAirbags] = useState(false);
  const [policeInvolved, setPoliceInvolved] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    claim: { id: string; claim_number: string; requires_mandatory_survey: boolean };
    acknowledgement: string;
    duplicate_review_alert?: string | null;
    agent_response?: {
      result?: { localized_acknowledgement?: string; normalised_channel?: string; language?: string };
      actions_executed?: Array<{ action_type: string; summary: string; status: string }>;
      decision?: { routing_outcome: string; reason_codes: string[]; explanation: string };
    };
  } | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(
      "mc_fnol_draft",
      JSON.stringify({ policyNumber, vehicleReg, location, description, estimatedLoss, intakeChannel, lang })
    );
  }, [policyNumber, vehicleReg, location, description, estimatedLoss, intakeChannel, lang]);

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
            intake_channel: intakeChannel,
            incident_location: location,
            geo_coords: geoCoords,
            incident_description: description,
            channel_transcript:
              intakeChannel === "voice" || intakeChannel === "whatsapp" ? description : undefined,
            estimated_loss_inr: estimatedLoss,
            injury_or_fatality: injury,
            ev_battery_impacted: evBattery,
            vehicle_immobile: immobile,
            towing_needed: towingNeeded || immobile,
            airbags_deployed: airbags,
            police_involved: policeInvolved,
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
          <label htmlFor="fnol-lang" className="text-xs font-semibold text-slate-600">
            Language:
          </label>
          <select
            id="fnol-lang"
            value={lang}
            onChange={(e) => setLang(e.target.value as LangCode)}
            className="px-3 py-1.5 text-xs font-semibold border border-slate-300 rounded-lg bg-white"
          >
            <option value="en-IN">English (en-IN)</option>
            <option value="hi-IN">हिन्दी (hi-IN)</option>
            <option value="mr-IN">मराठी (mr-IN)</option>
            <option value="ta-IN">தமிழ் (ta-IN)</option>
            <option value="kn-IN">ಕನ್ನಡ (kn-IN)</option>
          </select>
        </div>
      </div>

      {/* Omnichannel Selector */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 space-y-3">
        <div className="text-xs font-bold uppercase text-slate-500">
          Intake Channel (FNOLConciergeAgent)
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {(
            [
              ["web", "Web Portal", Globe],
              ["mobile", "Mobile App + GPS", Smartphone],
              ["whatsapp", "WhatsApp Bot", MessageSquare],
              ["voice", "Voice Call ASR", Mic],
            ] as Array<[IntakeChannel, string, React.ComponentType<{ className?: string }>]>
          ).map(([ch, label, Icon]) => (
            <button
              key={ch}
              type="button"
              onClick={() => setIntakeChannel(ch)}
              className={`p-2.5 rounded-lg border text-xs font-semibold flex items-center gap-2 ${
                intakeChannel === ch
                  ? "bg-slate-900 text-white border-slate-900"
                  : "bg-slate-50 text-slate-800 border-slate-200 hover:bg-slate-100"
              }`}
            >
              <Icon className="w-4 h-4" />
              {label}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap gap-2 text-xs pt-1">
          <span className="font-semibold text-slate-700">Quick-fill Scenarios:</span>
          <button
            type="button"
            onClick={() => {
              setPolicyNumber("POL-IN-DEMO-2026-1001");
              setVehicleReg("MH02DEMO1042");
              setEvBattery(false);
              setClaimType("cashless");
              setIntakeChannel("whatsapp");
              setLang("hi-IN");
              setImmobile(true);
              setTowingNeeded(true);
              setDescription("मेरी कार बंपर से टकराई है और आगे नहीं चल रही, कृपया टोइंग भेजें।");
            }}
            className="px-2.5 py-1 bg-white border border-slate-300 rounded hover:bg-slate-50"
          >
            WhatsApp Hindi + Towing
          </button>
          <button
            type="button"
            onClick={() => {
              setPolicyNumber("POL-IN-DEMO-2026-EV02");
              setVehicleReg("MH01EVDEMO99");
              setEvBattery(true);
              setImmobile(true);
              setTowingNeeded(true);
              setIntakeChannel("voice");
              setLang("en-IN");
              setPerilCause("ev_high_voltage");
              setEstimatedLoss("160000.00");
              setDescription("Voice ASR: Hit rock on BKC road, EV high voltage warning light on.");
            }}
            className="px-2.5 py-1 bg-white border border-slate-300 rounded hover:bg-slate-50"
          >
            Voice EV High-Voltage
          </button>
        </div>
      </div>

      {result && (
        <div className="bg-emerald-50 border border-emerald-300 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2 text-emerald-900 font-bold text-lg">
            <CheckCircle2 className="w-5 h-5" />
            Claim Registered: {result.claim.claim_number}
          </div>
          <p className="text-sm text-emerald-900">
            {result.agent_response?.result?.localized_acknowledgement || result.acknowledgement}
          </p>
          {result.agent_response?.decision && (
            <div className="p-3 bg-white border border-emerald-200 rounded-lg text-xs space-y-1">
              <div className="font-bold text-slate-900">
                Decision Intelligence: {result.agent_response.decision.routing_outcome}
              </div>
              <div className="text-slate-700">{result.agent_response.decision.explanation}</div>
              <div className="text-slate-500 font-mono">
                Codes: {result.agent_response.decision.reason_codes.join(", ")}
              </div>
            </div>
          )}
          {result.agent_response?.actions_executed && result.agent_response.actions_executed.length > 0 && (
            <div className="text-xs text-emerald-950 space-y-1">
              <div className="font-bold">Controlled Actions Executed:</div>
              {result.agent_response.actions_executed.map((a, idx) => (
                <div key={idx}>
                  • <code>{a.action_type}</code> ({a.status}): {a.summary}
                </div>
              ))}
            </div>
          )}
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
              Open Claim 360 &amp; Orchestration
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

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
            <label className="block text-xs font-semibold text-slate-700 mb-1">GPS Coordinates (Optional)</label>
            <input
              value={geoCoords}
              onChange={(e) => setGeoCoords(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg"
            />
          </div>
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

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1 text-xs">
          <label className="flex items-center gap-2 p-2.5 border border-slate-200 rounded-lg cursor-pointer">
            <input type="checkbox" checked={immobile} onChange={(e) => setImmobile(e.target.checked)} />
            <span>Vehicle Immobile</span>
          </label>
          <label className="flex items-center gap-2 p-2.5 border border-slate-200 rounded-lg cursor-pointer">
            <input type="checkbox" checked={towingNeeded} onChange={(e) => setTowingNeeded(e.target.checked)} />
            <span>Towing Needed</span>
          </label>
          <label className="flex items-center gap-2 p-2.5 border border-slate-200 rounded-lg cursor-pointer">
            <input type="checkbox" checked={airbags} onChange={(e) => setAirbags(e.target.checked)} />
            <span>Airbags Deployed</span>
          </label>
          <label className="flex items-center gap-2 p-2.5 border border-slate-200 rounded-lg cursor-pointer">
            <input type="checkbox" checked={policeInvolved} onChange={(e) => setPoliceInvolved(e.target.checked)} />
            <span>Police / FIR Filed</span>
          </label>
          <label className="flex items-center gap-2 p-2.5 border border-slate-200 rounded-lg cursor-pointer">
            <input type="checkbox" checked={injury} onChange={(e) => setInjury(e.target.checked)} />
            <span>Injury / Fatality (TP)</span>
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
