"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Bell,
  CheckCircle2,
  Circle,
  Clock,
  Headphones,
  Languages,
  Mail,
  MessageSquare,
  PhoneCall,
  Send,
  ShieldCheck,
  Sparkles,
  Upload,
} from "lucide-react";
import { apiFetch } from "@/lib/api";

export interface JourneyStage {
  key: string;
  step: number;
  title: string;
  status: "completed" | "in_progress" | "action_required" | "delayed" | "pending";
  detail: string;
  date_label?: string | null;
}

export interface CustomerJourney {
  tracker_title: string;
  claim_id: string;
  claim_number: string;
  vehicle_reg: string;
  vehicle_label: string;
  claim_status: string;
  canonical_state: string;
  risk_tier: string;
  operational_path: string;
  language: string;
  progress_pct: number;
  current_stage_key: string;
  next_step_customer_friendly: string;
  stages: JourneyStage[];
}

export interface TriggerMatrixItem {
  trigger: string;
  label: string;
  message_type: string;
  urgency: string;
  active_in_state: boolean;
  already_communicated: boolean;
  active_reason?: string | null;
}

export interface CustomerExperiencePayload {
  journey: CustomerJourney;
  intelligence: {
    claim_id: string;
    claim_number: string;
    claim_status: string;
    primary_trigger: string;
    detected_triggers: Array<{ trigger: string; label: string; urgency: string; reason: string }>;
    trigger_matrix: TriggerMatrixItem[];
    preferences: {
      preferred_language: string;
      preferred_channel: string;
      consent_whatsapp: boolean;
      consent_sms: boolean;
      consent_email: boolean;
      proactive_updates_enabled: boolean;
      whatsapp_consent_updated_at?: string | null;
      phone_masked: string;
      email_masked: string;
    };
    requested_channel: string;
    effective_channel: string;
    whatsapp_blocked_no_consent: boolean;
    channel_resolution_note: string;
    recommended_message: {
      trigger_event: string;
      language: string;
      channel: string;
      subject: string;
      body: string;
      action_cta: string;
      message_type: string;
    };
    human_escalations: Array<{
      task_id: string;
      title: string;
      description: string;
      assigned_role: string;
      status: string;
      priority: string;
      due_at?: string | null;
      created_at: string;
    }>;
  };
  communications: Array<{
    id: string;
    channel: string;
    language: string;
    template_id?: string;
    trigger_event?: string;
    claim_state_snapshot?: string;
    subject: string;
    body: string;
    requires_human_review: boolean;
    delivery_status: string;
    consent_verified?: boolean;
    whatsapp_message_id?: string | null;
    created_at: string;
  }>;
}

const LANG_OPTIONS = [
  { code: "en-IN", label: "English (en-IN)" },
  { code: "hi-IN", label: "हिन्दी (hi-IN)" },
  { code: "mr-IN", label: "मराठी (mr-IN)" },
  { code: "ta-IN", label: "தமிழ் (ta-IN)" },
  { code: "kn-IN", label: "ಕನ್ನಡ (kn-IN)" },
];

const CHANNEL_OPTIONS = [
  { id: "whatsapp", label: "WhatsApp", icon: MessageSquare },
  { id: "email", label: "Email", icon: Mail },
  { id: "sms", label: "SMS", icon: PhoneCall },
  { id: "portal", label: "Portal", icon: Bell },
];

interface Props {
  claimId: string;
  token: string;
  allowUpload?: boolean;
  onClaimUpdated?: () => void;
}

export function MotorClaimTracker({ claimId, token, allowUpload = false, onClaimUpdated }: Props) {
  const [cx, setCx] = useState<CustomerExperiencePayload | null>(null);
  const [previewLang, setPreviewLang] = useState<string>("");
  const [selectedTrigger, setSelectedTrigger] = useState<string>("");
  const [prefLang, setPrefLang] = useState<string>("en-IN");
  const [prefChannel, setPrefChannel] = useState<string>("whatsapp");
  const [consentWa, setConsentWa] = useState<boolean>(true);
  const [consentSms, setConsentSms] = useState<boolean>(true);
  const [consentEmail, setConsentEmail] = useState<boolean>(true);
  const [proactiveEnabled, setProactiveEnabled] = useState<boolean>(true);

  const [escReason, setEscReason] = useState<string>("surveyor_delay");
  const [escNotes, setEscNotes] = useState<string>("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [busy, setBusy] = useState<boolean>(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const loadCx = useCallback(
    async (langOverride?: string, triggerOverride?: string) => {
      if (!token || !claimId) return;
      try {
        const q = new URLSearchParams();
        if (langOverride) q.set("language", langOverride);
        if (triggerOverride) q.set("trigger", triggerOverride);
        const qs = q.toString() ? `?${q.toString()}` : "";
        const res = await apiFetch<CustomerExperiencePayload>(
          `/api/v1/claims/${claimId}/customer-experience${qs}`,
          {},
          token
        );
        setCx(res);
        const p = res.intelligence.preferences;
        setPrefLang(p.preferred_language);
        setPrefChannel(p.preferred_channel);
        setConsentWa(p.consent_whatsapp);
        setConsentSms(p.consent_sms);
        setConsentEmail(p.consent_email);
        setProactiveEnabled(p.proactive_updates_enabled);
        if (!langOverride) setPreviewLang(p.preferred_language);
        if (!triggerOverride) setSelectedTrigger(res.intelligence.primary_trigger);
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Failed to load customer experience data");
      }
    },
    [token, claimId]
  );

  useEffect(() => {
    setPreviewLang("");
    setSelectedTrigger("");
    loadCx();
  }, [claimId, loadCx]);

  const handlePreviewChange = async (nextLang: string, nextTrigger: string) => {
    setPreviewLang(nextLang);
    setSelectedTrigger(nextTrigger);
    await loadCx(nextLang || undefined, nextTrigger || undefined);
  };

  const handleSavePreferences = async () => {
    setBusy(true);
    setErr(null);
    setNotice(null);
    try {
      await apiFetch(
        `/api/v1/claims/${claimId}/customer-preferences`,
        {
          method: "PATCH",
          body: JSON.stringify({
            preferred_language: prefLang,
            preferred_channel: prefChannel,
            consent_whatsapp: consentWa,
            consent_sms: consentSms,
            consent_email: consentEmail,
            proactive_updates_enabled: proactiveEnabled,
          }),
        },
        token
      );
      setPreviewLang(prefLang);
      setNotice(
        `Preferences saved (${prefLang} · ${prefChannel.toUpperCase()} · WhatsApp consent: ${consentWa ? "Opted In" : "Opted Out"}).`
      );
      await loadCx(prefLang, selectedTrigger || undefined);
      onClaimUpdated?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save preferences");
    } finally {
      setBusy(false);
    }
  };

  const handleSendProactive = async (triggerToUse?: string) => {
    setBusy(true);
    setErr(null);
    setNotice(null);
    try {
      const trig = triggerToUse || selectedTrigger || cx?.intelligence.primary_trigger;
      const res = await apiFetch<{
        dispatched: boolean;
        channel: string;
        language: string;
        delivery_status: string;
        whatsapp_blocked_no_consent?: boolean;
        whatsapp_message_id?: string | null;
      }>(
        `/api/v1/claims/${claimId}/proactive-updates`,
        {
          method: "POST",
          body: JSON.stringify({
            trigger_event: trig,
            language: previewLang || prefLang,
            channel: prefChannel,
            force: true,
          }),
        },
        token
      );
      setNotice(
        res.whatsapp_blocked_no_consent
          ? `WhatsApp consent is opted out — guardrail routed update safely via ${res.channel.toUpperCase()} (${res.language}).`
          : `Proactive '${trig}' update dispatched via ${res.channel.toUpperCase()} (${res.language})${
              res.whatsapp_message_id ? ` · ${res.whatsapp_message_id}` : ""
            }.`
      );
      await loadCx(previewLang || undefined, trig);
      onClaimUpdated?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to dispatch proactive update");
    } finally {
      setBusy(false);
    }
  };

  const handleEscalate = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setNotice(null);
    try {
      const res = await apiFetch<{
        escalation_ref: string;
        assigned_role: string;
        callback_channel: string;
        callback_language: string;
      }>(
        `/api/v1/claims/${claimId}/customer-escalation`,
        {
          method: "POST",
          body: JSON.stringify({
            reason_category: escReason,
            notes: escNotes,
            preferred_language: previewLang || prefLang,
            preferred_channel: prefChannel,
          }),
        },
        token
      );
      setEscNotes("");
      setNotice(
        `Human specialist escalation ${res.escalation_ref} created (${res.assigned_role}). Confirmation sent via ${res.callback_channel.toUpperCase()} (${res.callback_language}).`
      );
      await loadCx(previewLang || undefined, selectedTrigger || undefined);
      onClaimUpdated?.();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Escalation failed");
    } finally {
      setBusy(false);
    }
  };

  const handleUploadEvidence = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile) return;
    setBusy(true);
    setErr(null);
    setNotice(null);
    try {
      const fd = new FormData();
      fd.append("file", uploadFile);
      await apiFetch(`/api/v1/claims/${claimId}/evidence`, { method: "POST", body: fd }, token);
      setNotice(`Uploaded ${uploadFile.name} cleanly. Claim tracker refreshed.`);
      setUploadFile(null);
      await loadCx(previewLang || undefined, selectedTrigger || undefined);
      onClaimUpdated?.();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  if (!cx) {
    return (
      <div className="bg-white p-6 rounded-xl border border-slate-200 text-sm text-slate-500">
        Loading Motor Claim Tracker &amp; Customer Experience Intelligence...
      </div>
    );
  }

  const { journey, intelligence, communications } = cx;

  return (
    <div className="space-y-6">
      {notice && (
        <div className="p-3 bg-emerald-50 border border-emerald-300 text-emerald-950 rounded-xl text-xs font-medium flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-700" />
          <span>{notice}</span>
        </div>
      )}
      {err && (
        <div className="p-3 bg-rose-50 border border-rose-300 text-rose-950 rounded-xl text-xs font-medium flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0 text-rose-700" />
          <span>{err}</span>
        </div>
      )}

      {/* 1. MOTOR CLAIM TRACKER */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="bg-gradient-to-r from-slate-900 via-slate-800 to-indigo-950 text-white p-5 flex flex-wrap items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider bg-white/15 rounded-full">
                {journey.tracker_title}
              </span>
              <span className="px-2 py-0.5 text-[11px] font-semibold bg-emerald-500/20 text-emerald-200 border border-emerald-400/30 rounded-full">
                {journey.progress_pct}% Complete
              </span>
              <span className="px-2 py-0.5 text-[11px] font-mono bg-white/10 rounded-full">
                {journey.risk_tier} · {journey.operational_path}
              </span>
            </div>
            <h2 className="text-xl font-bold tracking-tight">
              {journey.claim_number} · {journey.vehicle_label}
            </h2>
            <p className="text-xs text-slate-300">
              Next expected milestone: <strong className="text-white">{journey.next_step_customer_friendly}</strong>
            </p>
          </div>

          <div className="flex items-center gap-2 bg-white/10 px-3 py-2 rounded-xl border border-white/15">
            <Languages className="w-4 h-4 text-slate-200" />
            <label htmlFor="cx-lang-preview" className="text-xs font-semibold text-slate-200">
              Language:
            </label>
            <select
              id="cx-lang-preview"
              value={previewLang || journey.language}
              onChange={(e) => handlePreviewChange(e.target.value, selectedTrigger)}
              className="text-xs font-semibold bg-slate-900 text-white border border-white/25 rounded-lg px-2.5 py-1 focus:outline-none"
            >
              {LANG_OPTIONS.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Progress Bar */}
        <div className="h-1.5 bg-slate-100 w-full">
          <div
            className="h-full bg-gradient-to-r from-emerald-500 to-indigo-600 transition-all duration-300"
            style={{ width: `${journey.progress_pct}%` }}
          />
        </div>

        {/* 5-Stage Customer Journey Stepper */}
        <div className="p-5 grid grid-cols-1 md:grid-cols-5 gap-3">
          {journey.stages.map((st) => {
            const cardStyles =
              st.status === "completed"
                ? "bg-emerald-50/70 border-emerald-300 text-emerald-950"
                : st.status === "action_required"
                ? "bg-amber-50 border-amber-300 text-amber-950"
                : st.status === "delayed"
                ? "bg-rose-50 border-rose-300 text-rose-950"
                : st.status === "in_progress"
                ? "bg-blue-50 border-blue-300 text-blue-950"
                : "bg-slate-50 border-slate-200 text-slate-600";

            const badgeText =
              st.status === "completed"
                ? "Completed"
                : st.status === "action_required"
                ? "Action Needed"
                : st.status === "delayed"
                ? "Delayed"
                : st.status === "in_progress"
                ? "In Progress"
                : "Pending";

            return (
              <div key={st.key} className={`p-3.5 rounded-xl border flex flex-col justify-between gap-2 ${cardStyles}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-bold uppercase tracking-wide opacity-80">
                    Step {st.step}
                  </span>
                  {st.status === "completed" ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                  ) : st.status === "action_required" || st.status === "delayed" ? (
                    <AlertTriangle
                      className={`w-4 h-4 shrink-0 ${st.status === "delayed" ? "text-rose-600" : "text-amber-600"}`}
                    />
                  ) : st.status === "in_progress" ? (
                    <Clock className="w-4 h-4 text-blue-600 shrink-0" />
                  ) : (
                    <Circle className="w-4 h-4 text-slate-400 shrink-0" />
                  )}
                </div>
                <div>
                  <div className="font-bold text-sm leading-snug">{st.title}</div>
                  <div className="text-xs mt-1 leading-relaxed opacity-90">{st.detail}</div>
                </div>
                <div className="flex items-center justify-between pt-1 border-t border-black/10 text-[10px] font-semibold">
                  <span>{badgeText}</span>
                  {st.date_label && <span className="font-mono opacity-80">{st.date_label}</span>}
                </div>
              </div>
            );
          })}
        </div>

        {/* Optional quick upload when docs or photos are needed */}
        {allowUpload &&
          (intelligence.detected_triggers.some((t) => t.trigger === "documents_missing" || t.trigger === "photos_insufficient") ||
            journey.stages.some((s) => s.status === "action_required")) && (
            <form
              onSubmit={handleUploadEvidence}
              className="mx-5 mb-5 p-3.5 bg-amber-50 border border-amber-300 rounded-xl flex flex-wrap items-center justify-between gap-3"
            >
              <div className="text-xs text-amber-950">
                <strong className="block">Action Requested: Upload missing documents or clear daylight vehicle photos</strong>
                <span>Accepted formats: PDF, PNG, JPG, TXT (malware &amp; quality verified automatically).</span>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="file"
                  onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                  className="text-xs text-slate-700"
                />
                <button
                  type="submit"
                  disabled={!uploadFile || busy}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-900 text-white text-xs font-semibold rounded-lg disabled:opacity-50"
                >
                  <Upload className="w-3.5 h-3.5" />
                  Upload Now
                </button>
              </div>
            </form>
          )}
      </div>

      {/* 2. STATE-AWARE PROACTIVE COMMUNICATION INTELLIGENCE & PREFERENCES */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left 2 cols: 10 Proactive Triggers + Live State-Aware Composer */}
        <div className="lg:col-span-2 bg-white p-5 rounded-2xl border border-slate-200 space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-indigo-600" />
                <h3 className="text-base font-bold text-slate-900">
                  State-Aware Proactive Communication Intelligence (10 Lifecycle Triggers)
                </h3>
              </div>
              <p className="text-xs text-slate-600 mt-0.5">
                <code>CustomerCommunicationAgent</code> inspects live claim state, missing evidence, surveyor SLA, parts ETA,
                settlement DoA status, and UTR payment confirmation — never blind static templates.
              </p>
            </div>
            <span className="px-2.5 py-1 text-[11px] font-bold bg-indigo-50 text-indigo-900 border border-indigo-200 rounded-full">
              {intelligence.detected_triggers.length} Active Signal(s)
            </span>
          </div>

          {/* 10 Triggers Matrix */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {intelligence.trigger_matrix.map((tm) => {
              const isSelected = (selectedTrigger || intelligence.primary_trigger) === tm.trigger;
              return (
                <button
                  key={tm.trigger}
                  type="button"
                  onClick={() => handlePreviewChange(previewLang || prefLang, tm.trigger)}
                  className={`p-2.5 rounded-xl border text-left transition-all text-xs ${
                    isSelected
                      ? "bg-slate-900 text-white border-slate-900 shadow-sm"
                      : tm.active_in_state
                      ? "bg-amber-50 border-amber-300 text-amber-950 hover:border-amber-500"
                      : "bg-slate-50 border-slate-200 text-slate-700 hover:border-slate-300"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-bold">{tm.label}</span>
                    <div className="flex items-center gap-1">
                      {tm.active_in_state && (
                        <span
                          className={`px-1.5 py-0.5 text-[10px] font-bold rounded ${
                            isSelected ? "bg-amber-400 text-slate-950" : "bg-amber-200 text-amber-950"
                          }`}
                        >
                          ACTIVE
                        </span>
                      )}
                      {tm.already_communicated && (
                        <span
                          className={`px-1.5 py-0.5 text-[10px] font-bold rounded ${
                            isSelected ? "bg-emerald-400 text-slate-950" : "bg-emerald-100 text-emerald-900"
                          }`}
                        >
                          SENT
                        </span>
                      )}
                    </div>
                  </div>
                  <div className={`text-[11px] mt-0.5 ${isSelected ? "text-slate-300" : "text-slate-500"}`}>
                    {tm.active_reason || `Trigger: ${tm.trigger}`}
                  </div>
                </button>
              );
            })}
          </div>

          {/* Live State-Aware Preview + Dispatch */}
          <div className="p-4 rounded-xl border border-indigo-200 bg-indigo-50/50 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <div className="font-bold text-indigo-950">
                Synthesized Update Preview ·{" "}
                <span className="font-mono">{intelligence.recommended_message.trigger_event}</span> (
                {intelligence.recommended_message.language})
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={`px-2 py-0.5 rounded font-semibold ${
                    intelligence.whatsapp_blocked_no_consent
                      ? "bg-amber-100 text-amber-950 border border-amber-300"
                      : "bg-emerald-100 text-emerald-950 border border-emerald-300"
                  }`}
                >
                  Channel: {intelligence.effective_channel.toUpperCase()}
                </span>
              </div>
            </div>

            {intelligence.whatsapp_blocked_no_consent && (
              <div className="p-2.5 rounded-lg bg-amber-100 border border-amber-300 text-amber-950 text-xs">
                <strong>WhatsApp Consent Guardrail Active:</strong> {intelligence.channel_resolution_note}
              </div>
            )}

            <div className="bg-white p-3.5 rounded-lg border border-indigo-200 space-y-1.5">
              <div className="text-xs font-bold text-slate-900">{intelligence.recommended_message.subject}</div>
              <p className="text-xs text-slate-700 leading-relaxed">{intelligence.recommended_message.body}</p>
              <div className="text-[11px] font-semibold text-indigo-700 pt-1">
                CTA: {intelligence.recommended_message.action_cta}
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-[11px] text-slate-500">
                Dispatches through <code>CustomerCommunicationAgent</code> + logs Decision Intelligence &amp; Outbox event.
              </span>
              <button
                type="button"
                disabled={busy}
                onClick={() => handleSendProactive()}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold bg-slate-900 text-white rounded-lg hover:bg-slate-800 disabled:opacity-50"
              >
                <Send className="w-3.5 h-3.5" />
                Send Proactive Update Now
              </button>
            </div>
          </div>
        </div>

        {/* Right col: Communication Preferences + WhatsApp Consent + Human Escalation */}
        <div className="space-y-6">
          {/* Preferences & WhatsApp Consent */}
          <div className="bg-white p-5 rounded-2xl border border-slate-200 space-y-3.5">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-slate-900">Communication Preferences</h3>
              <ShieldCheck className="w-4 h-4 text-emerald-600" />
            </div>
            <p className="text-xs text-slate-600">
              Choose your preferred language, delivery channel, and explicit WhatsApp notification consent.
            </p>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Preferred Language</label>
              <select
                value={prefLang}
                onChange={(e) => setPrefLang(e.target.value)}
                className="w-full px-3 py-2 text-xs font-medium border border-slate-300 rounded-lg bg-white"
              >
                {LANG_OPTIONS.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Preferred Channel</label>
              <div className="grid grid-cols-2 gap-2">
                {CHANNEL_OPTIONS.map((ch) => {
                  const Icon = ch.icon;
                  const active = prefChannel === ch.id;
                  return (
                    <button
                      key={ch.id}
                      type="button"
                      onClick={() => setPrefChannel(ch.id)}
                      className={`px-2.5 py-2 rounded-lg border text-xs font-semibold flex items-center gap-1.5 ${
                        active
                          ? "bg-slate-900 text-white border-slate-900"
                          : "bg-slate-50 text-slate-800 border-slate-200 hover:bg-slate-100"
                      }`}
                    >
                      <Icon className="w-3.5 h-3.5" />
                      {ch.label}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="p-3 rounded-xl bg-emerald-50/70 border border-emerald-200 space-y-2 text-xs">
              <label className="flex items-start gap-2 cursor-pointer font-semibold text-emerald-950">
                <input
                  type="checkbox"
                  checked={consentWa}
                  onChange={(e) => setConsentWa(e.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  WhatsApp Opt-In Consent ({intelligence.preferences.phone_masked}) — Receive proactive claim milestones,
                  photo reminders &amp; payout alerts via WhatsApp.
                </span>
              </label>
              <div className="flex flex-wrap gap-3 text-[11px] text-slate-700 pl-5">
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input type="checkbox" checked={consentSms} onChange={(e) => setConsentSms(e.target.checked)} />
                  SMS Opt-In
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input type="checkbox" checked={consentEmail} onChange={(e) => setConsentEmail(e.target.checked)} />
                  Email Opt-In
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={proactiveEnabled}
                    onChange={(e) => setProactiveEnabled(e.target.checked)}
                  />
                  Proactive Alerts
                </label>
              </div>
            </div>

            <button
              type="button"
              disabled={busy}
              onClick={handleSavePreferences}
              className="w-full py-2 bg-slate-900 text-white text-xs font-semibold rounded-lg hover:bg-slate-800 disabled:opacity-50"
            >
              Save Preferences &amp; Consent
            </button>
          </div>

          {/* Human Escalation Path */}
          <form onSubmit={handleEscalate} className="bg-white p-5 rounded-2xl border border-slate-200 space-y-3">
            <div className="flex items-center gap-2">
              <Headphones className="w-4 h-4 text-rose-600" />
              <h3 className="text-base font-bold text-slate-900">Escalate to Human Specialist</h3>
            </div>
            <p className="text-xs text-slate-600">
              Need direct human assistance? Connect with a specialist in your preferred language (4-hour callback SLA).
            </p>
            <select
              value={escReason}
              onChange={(e) => setEscReason(e.target.value)}
              className="w-full px-3 py-2 text-xs border border-slate-300 rounded-lg bg-white"
            >
              <option value="surveyor_delay">Surveyor assignment / report delayed</option>
              <option value="parts_delay">Spare parts delay / repair timeline</option>
              <option value="missing_doc_help">Need help uploading documents or photos</option>
              <option value="settlement_dispute">Clarify repair estimate or settlement deductions</option>
              <option value="callback_request">Speak directly with a claims specialist</option>
            </select>
            <textarea
              rows={2}
              value={escNotes}
              onChange={(e) => setEscNotes(e.target.value)}
              placeholder="Optional note for the human specialist..."
              className="w-full px-3 py-2 text-xs border border-slate-300 rounded-lg"
            />
            <button
              type="submit"
              disabled={busy}
              className="w-full py-2 bg-rose-700 text-white text-xs font-semibold rounded-lg hover:bg-rose-800 disabled:opacity-50"
            >
              Request Human Specialist Callback
            </button>

            {intelligence.human_escalations.length > 0 && (
              <div className="pt-2 border-t border-slate-200 space-y-1.5">
                <div className="text-[11px] font-bold uppercase text-slate-500">
                  Active Human Escalations ({intelligence.human_escalations.length})
                </div>
                {intelligence.human_escalations.map((esc) => (
                  <div key={esc.task_id} className="p-2 bg-rose-50 border border-rose-200 rounded-lg text-[11px]">
                    <div className="font-bold text-rose-950">{esc.title}</div>
                    <div className="text-rose-800">
                      Assigned: {esc.assigned_role} · Status: {esc.status}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </form>
        </div>
      </div>

      {/* 3. PROACTIVE COMMUNICATION LOG */}
      <div className="bg-white p-5 rounded-2xl border border-slate-200 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-base font-bold text-slate-900">
            Proactive Customer Communication Feed ({communications.length})
          </h3>
          <span className="text-xs text-slate-500">
            Every outbound message records trigger, claim state, language, channel, and WhatsApp consent verification.
          </span>
        </div>
        <div className="space-y-2.5">
          {communications.map((cm) => (
            <div key={cm.id} className="p-3.5 rounded-xl border border-slate-200 bg-slate-50/70 space-y-1.5 text-xs">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span
                    className={`px-2 py-0.5 font-bold uppercase rounded text-[10px] ${
                      cm.channel === "whatsapp"
                        ? "bg-emerald-100 text-emerald-900 border border-emerald-300"
                        : "bg-slate-200 text-slate-800"
                    }`}
                  >
                    {cm.channel}
                  </span>
                  <span className="px-2 py-0.5 font-mono bg-indigo-100 text-indigo-900 rounded text-[10px]">
                    {cm.language}
                  </span>
                  {cm.trigger_event && (
                    <span className="px-2 py-0.5 font-mono bg-blue-100 text-blue-900 rounded text-[10px]">
                      {cm.trigger_event}
                    </span>
                  )}
                  {cm.whatsapp_message_id && (
                    <span className="px-2 py-0.5 font-mono bg-emerald-50 text-emerald-800 border border-emerald-200 rounded text-[10px]">
                      {cm.whatsapp_message_id}
                    </span>
                  )}
                  <span className="font-bold text-slate-900">{cm.subject}</span>
                </div>
                <span className="font-mono text-[11px] text-slate-500">
                  {cm.delivery_status} · {cm.created_at.slice(0, 19).replace("T", " ")}Z
                </span>
              </div>
              <p className="text-slate-700 leading-relaxed">{cm.body}</p>
            </div>
          ))}
          {communications.length === 0 && (
            <div className="text-xs text-slate-500">No proactive communications dispatched yet for this claim.</div>
          )}
        </div>
      </div>
    </div>
  );
}
