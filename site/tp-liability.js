/* Third-Party (TP) Liability workflow showcase (IN-TP-LIABILITY-2026).
 * Mirrors rules/india/tp_liability_controls.json and services/workflow/tp_liability.py.
 * DEMO / SYNTHETIC: statutory limits and tiers require legal sign-off before production use.
 */
(function () {
  "use strict";

  var STAGES = [
    { id: "INTAKE", queue: "tp_intake", owner: "claims_handler", sla: 24, gate: "At least one third party recorded and coverage validated for the incident date (a lapsed policy is flagged for Legal, never auto-declined).", api: "POST /claims/{id}/tp/open · /third-parties · /coverage-check", what: "Injury / property-damage intake and third-party details." },
    { id: "EVIDENCE_AND_FACTS", queue: "tp_evidence_facts", owner: "claims_handler", sla: 72, gate: "Accident date, place and factual narrative recorded with at least one evidence item (placed under legal hold).", api: "POST /claims/{id}/tp/facts", what: "Accident facts and evidence preservation." },
    { id: "POLICE_FIR", queue: "tp_police_fir", owner: "claims_handler", sla: 72, gate: "FIR number recorded (or a documented waiver by a manager/legal, property damage only). DAR and charge-sheet status tracked.", api: "POST /claims/{id}/tp/police-report", what: "Police report and FIR information (skipped for minor property damage without police)." },
    { id: "LIABILITY_INVESTIGATION", queue: "tp_liability_investigation", owner: "claims_handler", sla: 240, gate: "A human records fault split, contributory negligence, policy defences and a reasoned rationale. Software never determines liability.", api: "POST /claims/{id}/tp/liability-assessment", what: "Liability assessment and investigation." },
    { id: "LEGAL_DOCUMENTATION", queue: "tp_legal_documentation", owner: "legal_tp", sla: 168, gate: "Every category-required legal document received or verified. Only Legal/TP can advance this stage.", api: "POST /claims/{id}/tp/legal-documents · /tribunal", what: "Legal documentation and MACT petition tracking." },
    { id: "ADVOCATE_COORDINATION", queue: "tp_advocate_coordination", owner: "legal_tp", sla: 72, gate: "Panel advocate assigned after a conflict-of-interest check (required for injury, fatality or contested cases).", api: "POST /claims/{id}/tp/advocates", what: "Advocate coordination." },
    { id: "MEDICAL_REVIEW", queue: "tp_medical_review", owner: "legal_tp", sla: 168, gate: "Medical opinion recorded: severity, disability %, causation. Records are restricted-access (masked for other roles).", api: "POST /claims/{id}/tp/medical-review", what: "Medical document processing (injury and fatality only)." },
    { id: "LEGAL_SPECIALIST_REVIEW", queue: "tp_legal_specialist_review", owner: "legal_tp", sla: 120, gate: "Legal sign-off with a decision (negotiate / contest / pay-and-recover) and a reserve on file.", api: "POST /claims/{id}/tp/reserve · /legal-review", what: "Legal / claims specialist review and reserve." },
    { id: "SETTLEMENT_CONTROL", queue: "tp_settlement_control", owner: "claims_manager", sla: 120, gate: "A proposal within reserve and consistent with the legal decision, approved under dual control. The legal reviewer cannot propose; the proposer cannot approve.", api: "POST /claims/{id}/tp/settlement-proposals · /{pid}/decision", what: "Controlled settlement workflow." },
    { id: "SETTLEMENT_APPROVED", queue: "tp_payment_authorisation", owner: "finance_approver", sla: 48, gate: "Finance (not involved in proposal, approvals or legal review) releases payment; idempotent, no duplicate payout.", api: "POST /claims/{id}/tp/payment-authorisation", what: "Payment authorisation." },
    { id: "PAYMENT_AUTHORISED", queue: "tp_closure_review", owner: "claims_manager", sla: 72, gate: "Manager closure review; if a policy defence exists, recovery action against the insured must be opened first.", api: "POST /claims/{id}/tp/close", what: "Closure review." },
    { id: "CLOSED", queue: "tp_closed", owner: "auditor", sla: 0, gate: "Terminal. Immutable audit trail.", api: "GET /claims/{id}/tp", what: "Closed." }
  ];

  var CATEGORIES = {
    property_damage: { label: "TP Property Damage", police: false, medical: false, advocate: false, reserve: 75000, docs: ["claimant_id", "property_damage_photos", "repair_estimate_or_invoice", "ownership_proof"] },
    bodily_injury: { label: "TP Bodily Injury", police: true, medical: true, advocate: true, reserve: 500000, docs: ["claimant_id", "fir_copy", "medical_records", "discharge_summary", "medico_legal_certificate", "income_proof"] },
    fatality: { label: "TP Fatality", police: true, medical: true, advocate: true, reserve: 1500000, docs: ["claimant_id", "fir_copy", "death_certificate", "postmortem_report", "legal_heir_certificate", "income_proof_of_deceased"] }
  };

  var SEVERITY_RESERVE = { minor: 150000, moderate: 500000, grievous: 1200000, permanent_disability: 2500000, fatality: 1500000 };
  var TPPD_LIMIT = 750000;

  var OD_STEPS = ["Policy coverage validation", "Vehicle inspection", "Damage assessment", "Garage coordination", "Repair estimate validation", "Depreciation & deductible calculation", "Settlement or cashless repair", "Payment & reconciliation"];

  function el(id) {
    return document.getElementById(id);
  }

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function inr(n) {
    return "₹" + Number(n).toLocaleString("en-IN");
  }

  function stageLabel(id) {
    return id.replace(/_/g, " ");
  }

  function renderCompare() {
    var box = el("tp-compare");
    if (!box) return;
    var od = OD_STEPS.map(function (s, i) {
      return "<li><span class=\"tp-step-no\">" + (i + 1) + "</span>" + esc(s) + "</li>";
    }).join("");
    var tp = STAGES.slice(0, 11).map(function (s, i) {
      return "<li><span class=\"tp-step-no tp\">" + (i + 1) + "</span>" + esc(s.what) + "</li>";
    }).join("");
    box.innerHTML =
      '<div class="card tp-col od"><div class="stat-label">Own Damage (OD)</div><h3 style="margin:4px 0 8px;">First-party repair claim</h3>' +
      '<p class="section-sub" style="margin:0 0 10px;">Deterministic arithmetic on an estimate. LOW-risk claims up to ₹25,000 can be straight-through.</p><ol class="tp-steps">' + od + "</ol>" +
      '<div class="btn-row"><span class="badge badge-green">Deterministic Decimal settlement</span><span class="badge badge-blue">Auto-approval ≤ ₹25,000 (LOW risk)</span></div></div>' +
      '<div class="card tp-col tpc"><div class="stat-label">Third-Party (TP) Liability</div><h3 style="margin:4px 0 8px;">Legal-liability claim by someone else</h3>' +
      '<p class="section-sub" style="margin:0 0 10px;">Amount depends on fault, evidence, medical opinion and tribunal practice. Every stage is human-gated.</p><ol class="tp-steps">' + tp + "</ol>" +
      '<div class="btn-row"><span class="badge badge-rose">No autonomous settlement</span><span class="badge badge-purple">Dedicated queues</span><span class="badge badge-amber">Dual-control approval</span></div></div>';
  }

  var selectedStage = "LIABILITY_INVESTIGATION";

  window.tpSelectStage = function (id) {
    selectedStage = id;
    renderStages();
  };

  function renderStages() {
    var strip = el("tp-stage-strip");
    var insp = el("tp-stage-inspector");
    if (!strip || !insp) return;
    strip.innerHTML = STAGES.map(function (s) {
      var cls = "state-pill-btn" + (s.id === selectedStage ? " active" : "");
      return '<button type="button" class="' + cls + '" onclick="tpSelectStage(\'' + s.id + '\')">' + esc(stageLabel(s.id)) + "</button>";
    }).join("");
    var s = STAGES.filter(function (x) { return x.id === selectedStage; })[0];
    insp.innerHTML =
      '<div class="card" style="margin-top:12px;"><div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;">' +
      "<h3 style=\"margin:0;\">" + esc(stageLabel(s.id)) + "</h3><div class=\"btn-row\">" +
      '<span class="badge badge-purple">Queue: ' + esc(s.queue) + "</span>" +
      '<span class="badge badge-slate">Owner: ' + esc(s.owner) + "</span>" +
      '<span class="badge badge-amber">SLA: ' + (s.sla ? s.sla + "h" : "n/a") + "</span>" +
      '<span class="badge ' + (s.id === "CLOSED" ? "badge-slate" : "badge-rose") + '">' + (s.id === "CLOSED" ? "Terminal" : "Human gate") + "</span></div></div>" +
      '<p style="margin:10px 0 6px;"><strong>Exit gate.</strong> ' + esc(s.gate) + "</p>" +
      '<p style="margin:0;font-size:13px;color:#475569;"><code>' + esc(s.api) + "</code></p></div>";
  }

  function pathFor(cat, opts) {
    var c = CATEGORIES[cat];
    var out = [];
    STAGES.forEach(function (s) {
      var skip = null;
      if (s.id === "POLICE_FIR" && !(c.police || opts.police)) skip = "no police report required";
      if (s.id === "ADVOCATE_COORDINATION" && !(c.advocate || opts.litigation || opts.decision === "contest_liability")) skip = "no litigation";
      if (s.id === "MEDICAL_REVIEW" && !c.medical) skip = "no bodily injury";
      out.push({ id: s.id, skip: skip });
    });
    return out;
  }

  function tierFor(amount, cat) {
    if (amount <= 500000 && cat !== "fatality") return { tier: "TP-L1", roles: ["claims_manager"] };
    if (amount <= 1500000) return { tier: "TP-L2", roles: ["claims_manager", "legal_tp"] };
    return { tier: "TP-L3-COMMITTEE", roles: ["claims_manager", "legal_tp", "admin (claims committee)"] };
  }

  window.runTpLab = function () {
    var out = el("tp-lab-output");
    var sum = el("tp-lab-summary");
    if (!out || !sum) return;
    var cat = el("tp-category").value;
    var severity = el("tp-severity").value;
    var amount = Number(el("tp-amount").value) || 0;
    var decision = el("tp-decision").value;
    var defence = el("tp-defence").checked;
    var police = el("tp-police").checked;
    var litigation = el("tp-litigation").checked;
    var c = CATEGORIES[cat];

    var reserveSuggested = cat === "property_damage" ? c.reserve : (SEVERITY_RESERVE[cat === "fatality" ? "fatality" : severity] || c.reserve);
    var path = pathFor(cat, { police: police, litigation: litigation, decision: decision });
    var tier = tierFor(amount, cat);
    var problems = [];
    var basis = decision === "negotiate_settlement" ? "negotiated" : decision === "contest_liability" ? "tribunal_award (only after a recorded award)" : "pay_and_recover (or tribunal_award)";

    if (decision === "pay_and_recover" && !defence) problems.push("pay_and_recover rejected: no policy defence is recorded in the liability assessment.");
    if (amount <= 0) problems.push("Settlement amount must be greater than zero.");
    if (amount > reserveSuggested) problems.push("Proposal " + inr(amount) + " exceeds the advisory reserve band " + inr(reserveSuggested) + ": a manager or legal must raise the reserve (with a basis) before proposing.");
    if (cat === "property_damage" && decision === "negotiate_settlement" && amount > TPPD_LIMIT) problems.push("Exceeds the statutory TP property damage limit " + inr(TPPD_LIMIT) + ": Legal must record excess-liability handling.");
    if (decision === "contest_liability") problems.push("Contested: no negotiated payment is allowed; only a recorded tribunal award can be complied with.");

    var skipped = path.filter(function (p) { return p.skip; });
    var lines = [];
    lines.push("[TP case] " + c.label + " | legal decision: " + decision + " | claimed amount: " + inr(amount));
    lines.push("  • Stages: " + path.filter(function (p) { return !p.skip; }).length + " of " + STAGES.length + " apply" + (skipped.length ? " (skipped by rule: " + skipped.map(function (p) { return stageLabel(p.id) + " - " + p.skip; }).join("; ") + ")" : ""));
    lines.push("  • Required legal documents: " + c.docs.join(", "));
    lines.push("  • Advisory reserve band (non-binding): " + inr(reserveSuggested) + " - a human sets the actual reserve");
    lines.push("  • Permitted settlement basis: " + basis);
    lines.push("  • Approval tier: " + tier.tier + " -> distinct approvers required: " + tier.roles.join(" + "));
    lines.push("  • Separation of duties: legal reviewer ≠ proposer; proposer ≠ approver; finance releaser ≠ proposer/approver/legal reviewer");
    lines.push("  • Payment: finance_approver only, idempotent, mock gateway in DEMO; no duplicate payout");
    lines.push("  • OD fast-track auto-approval eligible: NO (straight_through_eligible=false, risk tier forced HIGH)");
    if (defence) lines.push("  • Policy defence recorded -> recovery rights flagged; closure needs recovery action opened");
    if (problems.length) {
      lines.push("");
      lines.push("[Blocked / needs human action]");
      problems.forEach(function (p) { lines.push("  ✗ " + p); });
    } else {
      lines.push("");
      lines.push("[Result] Proposal can enter " + tier.tier + " dual-control approval (still human decisions at every step).");
    }
    out.textContent = lines.join("\n");

    sum.innerHTML =
      '<div class="tp-sum-grid">' +
      '<div class="card"><div class="stat-label">Applicable stages</div><div class="stat-num">' + path.filter(function (p) { return !p.skip; }).length + " / " + STAGES.length + "</div></div>" +
      '<div class="card"><div class="stat-label">Approval tier</div><div class="stat-num">' + esc(tier.tier) + "</div></div>" +
      '<div class="card"><div class="stat-label">Approvers needed</div><div class="stat-num">' + tier.roles.length + "</div></div>" +
      '<div class="card"><div class="stat-label">Autonomous settlement</div><div class="stat-num" style="color:#be123c;">Never</div></div>' +
      "</div>";
  };

  window.tpAutonomyDemo = function (mode) {
    var out = el("tp-lab-output");
    if (!out) return;
    var logs = {
      od_endpoint:
        "POST /api/v1/claims/{tp_claim}/settlement-recommendations\n" +
        "-> 409 HUMAN_REVIEW_REQUIRED\n" +
        "   \"'OD settlement recommendation' is an Own Damage operation. Third-Party liability claims use the dedicated TP workflow\n" +
        "    (/api/v1/claims/{id}/tp) with legal oversight and dual-control settlement; autonomous or OD-style settlement is prohibited (IN-TP-LIABILITY-2026).\"\n" +
        "Same guard on: /approvals, /payments, /payments/agent-release, /close.",
      agent:
        "[SettlementRecommendationAgent] claim_type=third_party, risk_tier=LOW (forced input), straight_through_eligible=true, allow_fast_track_auto_approve=true\n" +
        "-> status: NEEDS_HUMAN | auto_approved: false | tp_workflow_required: true | actions_executed: []\n" +
        "-> routing_outcome: route_to_tp_legal_workflow | reason codes: RC_TP_LIABILITY_LEGAL_WORKFLOW_REQUIRED, RC_NO_AUTONOMOUS_TP_SETTLEMENT\n" +
        "No OD approval request, settlement row or payment instruction is created.",
      od_spawns_tp:
        "OD claim CLM-DEMO-2026-0001 (own_damage) also damaged a parked third-party car.\n" +
        "POST /api/v1/claims/clm-demo-0001/tp/exposures {tp_category: property_damage}\n" +
        "-> NEW linked claim (claim_type=third_party) + TP case TP-DEMO-... in queue tp_intake; the OD claim stays on its own OD lifecycle.\n" +
        "   Repeat call is idempotent (same TP claim returned).",
      self_approval:
        "Settlement proposal tps-9a1 (INR 9,50,000, tier TP-L2: claims_manager + legal_tp)\n" +
        "  • Proposer (claims_handler) tries to approve -> 403 (role has no TP approval authority)\n" +
        "  • Manager approves #1 -> proposal stays pending_approval\n" +
        "  • Same manager approves again -> 403 (each approver must be a distinct user)\n" +
        "  • Legal approves #2 -> approved -> stage SETTLEMENT_APPROVED -> queue tp_payment_authorisation\n" +
        "  • Finance releases (not involved in the case) -> PAYMENT_AUTHORISED; replay with same idempotency key returns the same payment."
    };
    out.textContent = logs[mode] || logs.od_endpoint;
  };

  document.addEventListener("DOMContentLoaded", function () {
    renderCompare();
    renderStages();
    if (window.runTpLab) window.runTpLab();
  });
})();
