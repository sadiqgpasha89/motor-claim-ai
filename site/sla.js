/* Predictive SLA Operations showcase.
 * Every SLA value (deadline, regulatory window, version, pause condition, escalation step, guardrail, risk-model weight)
 * is read from window.SLA_CATALOGUE, a generated projection of rules/common/sla_rules.json. Nothing is hardcoded here.
 * The lab is a browser port of services/sla/predictor.py (model sla-risk-baseline-v1) and services/sla/actions.py.
 * DEMO / SYNTHETIC data; deadlines are configurable per tenant and need compliance sign-off before production use.
 */
(function () {
  "use strict";

  var CAT = window.SLA_CATALOGUE || { rules: [], risk_model: {}, agent_guardrails: {}, action_catalogue: {}, claim_type_families: {} };
  var RM = CAT.risk_model || {};
  var GUARD = CAT.agent_guardrails || {};
  var ACTIONS = CAT.action_catalogue || {};
  var SURVEY_METRICS = ["surveyor_assignment", "survey_completion"];
  var SPECIALIST_METRICS = ["surveyor_assignment", "survey_completion", "repair_completion"];
  var BAND_LABEL = { on_track: "On track", watch: "Watch", at_risk: "At risk", critical: "Critical", breached: "Breached" };
  var BAND_BADGE = { on_track: "badge-green", watch: "badge-blue", at_risk: "badge-amber", critical: "badge-rose", breached: "badge-rose" };
  var URGENCY = { immediate: 0, today: 1, watch: 2 };

  function el(id) { return document.getElementById(id); }
  function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function label(s) { return String(s).replace(/_/g, " "); }

  function hoursOf(deadline) {
    var mult = { minutes: 1 / 60, hours: 1, days: 24 }[deadline.unit];
    return deadline.value * (mult || 1);
  }

  function fmtDuration(h) {
    if (h < 1) return Math.round(h * 60) + " min";
    if (h % 24 === 0 && h >= 48) return h / 24 + " days";
    return (Math.round(h * 10) / 10) + " h";
  }

  function metricsInOrder() {
    var seen = [];
    CAT.rules.forEach(function (r) { if (seen.indexOf(r.metric) < 0) seen.push(r.metric); });
    return seen;
  }

  function familyOf(claimType) {
    var fams = CAT.claim_type_families || {};
    for (var f in fams) if (fams[f].indexOf(claimType) >= 0) return f;
    return "own_damage";
  }

  // Which rule version governs a clock that starts on `at`, for a claim of the given family (mirrors SLARulesService.resolve).
  function rulesInForce(metric, family, at) {
    var t = at.getTime();
    var cands = CAT.rules.filter(function (r) {
      return r.metric === metric && r.applicable_claim_types.some(function (c) { return familyOf(c) === family; }) &&
        Date.parse(r.effective_from) <= t && (!r.effective_to || t <= Date.parse(r.effective_to));
    });
    cands.sort(function (a, b) { return cmpVer(b.rule_version, a.rule_version); });
    return cands[0] || null;
  }

  function cmpVer(a, b) {
    var x = a.split(".").map(Number), y = b.split(".").map(Number);
    for (var i = 0; i < 3; i++) { if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) - (y[i] || 0); }
    return 0;
  }

  function asOfDate() {
    var v = el("sla-asof") && el("sla-asof").value;
    return v ? new Date(v + "T12:00:00Z") : new Date();
  }

  // ------------------------------------------------------------------------------------------------ dashboard
  function renderDashboard() {
    var box = el("sla-dashboard-body");
    if (!box) return;
    var at = asOfDate();
    var family = (el("sla-family") && el("sla-family").value) || "own_damage";
    var rows = metricsInOrder().map(function (m) {
      var r = rulesInForce(m, family, at);
      if (!r) {
        return "<tr><td><strong>" + esc(label(m)) + "</strong></td><td colspan=\"6\" style=\"color:#64748b;\">No separate rule for this claim family (e.g. third-party claims follow their own lifecycle).</td></tr>";
      }
      var reg = r.deadline.regulatory_hours ? fmtDuration(r.deadline.regulatory_hours) : "&mdash;";
      var esc1 = r.escalation_sequence.map(function (s) { return s.at_pct + "% " + label(s.action); }).join(" &rarr; ");
      var pauses = r.pause_conditions.length ? r.pause_conditions.map(function (p) { return esc(p.code); }).join(", ") : "none";
      return "<tr>" +
        "<td><strong>" + esc(r.title) + "</strong><div style=\"font-size:.78rem;color:#64748b;\">" + esc(r.sla_id) + " &middot; v" + esc(r.rule_version) + "</div></td>" +
        "<td>" + esc(r.deadline.target_label) + "<div style=\"font-size:.78rem;color:#64748b;\">enforced: " + esc(fmtDuration(hoursOf(r.deadline))) + "</div></td>" +
        "<td>" + reg + (r.deadline.regulatory_reference ? "<div style=\"font-size:.74rem;color:#64748b;\">" + esc(r.deadline.regulatory_reference) + "</div>" : "") + "</td>" +
        "<td><code>" + esc(r.trigger_event) + "</code> &rarr; <code>" + esc(r.stop_event) + "</code></td>" +
        "<td style=\"font-size:.82rem;\">" + esc1 + "</td>" +
        "<td>" + esc(r.responsible_team) + "</td>" +
        "<td style=\"font-size:.82rem;\">" + pauses + "</td></tr>";
    });
    box.innerHTML = rows.join("");
    var note = el("sla-asof-note");
    if (note) {
      var docs = rulesInForce("document_verification", family, at);
      note.textContent = docs ? "Document verification is governed by rule v" + docs.rule_version + " (" + fmtDuration(hoursOf(docs.deadline)) + ") for clocks starting on this date." : "";
    }
  }

  // ------------------------------------------------------------------------------------------------ rule explorer
  function renderRuleExplorer() {
    var sel = el("sla-rule-metric");
    var out = el("sla-rule-detail");
    if (!sel || !out) return;
    var metric = sel.value;
    var versions = CAT.rules.filter(function (r) { return r.metric === metric; })
      .sort(function (a, b) { return a.sla_id.localeCompare(b.sla_id) || cmpVer(a.rule_version, b.rule_version); });
    out.innerHTML = versions.map(function (r) {
      var win = r.effective_from.slice(0, 10) + " &rarr; " + (r.effective_to ? r.effective_to.slice(0, 10) : "open");
      var fields = [
        ["Rule version", "v" + r.rule_version + " &middot; " + win],
        ["Applicable claim types", r.applicable_claim_types.join(", ")],
        ["Trigger event", r.trigger_event],
        ["Start condition", Object.keys(r.start_condition).length && (r.start_condition.all || []).length + (r.start_condition.any || []).length ? "<code>" + esc(JSON.stringify(r.start_condition)) + "</code>" : "always (on trigger)"],
        ["Stop event", r.stop_event],
        ["Pause conditions", r.pause_conditions.length ? r.pause_conditions.map(function (p) { return "<strong>" + esc(p.code) + "</strong> &mdash; " + esc(p.description); }).join("<br/>") : "none"],
        ["Deadline", esc(fmtDuration(hoursOf(r.deadline))) + " (" + esc(r.deadline.target_label) + ")" + (r.deadline.regulatory_hours ? "; regulatory " + esc(fmtDuration(r.deadline.regulatory_hours)) : "")],
        ["Escalation sequence", r.escalation_sequence.map(function (s) { return "step " + s.step + " @ " + s.at_pct + "% &rarr; " + esc(label(s.action)) + " (" + esc(s.to_team) + ")"; }).join("<br/>")],
        ["Responsible team", esc(r.responsible_team) + " &middot; owner role " + esc(r.owner_role)],
        ["Breach action", esc(r.breach_action.code) + " &rarr; " + esc(r.breach_action.assigned_role) + " (" + esc(r.breach_action.priority) + ")" + (Number(r.breach_action.daily_penalty_inr) > 0 ? "; penalty accrues &#8377;" + esc(r.breach_action.daily_penalty_inr) + "/day after the regulatory window" : "")]
      ];
      return '<div class="card" style="margin-bottom:10px;"><div class="stat-label">' + esc(r.sla_id) + "</div>" +
        '<table class="sla-kv"><tbody>' + fields.map(function (f) { return "<tr><th>" + esc(f[0]) + "</th><td>" + f[1] + "</td></tr>"; }).join("") + "</tbody></table></div>";
    }).join("");
  }

  // ------------------------------------------------------------------------------------------------ predictive lab
  function phi(z) {
    // Abramowitz-Stegun erf approximation; matches the Python model to ~1e-7.
    var t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2);
    var y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-(z * z) / 2);
    return 0.5 * (1 + (z < 0 ? -y : y));
  }

  function bandFor(p) {
    var th = RM.band_thresholds || {};
    if (p >= th.critical) return "critical";
    if (p >= th.at_risk) return "at_risk";
    if (p >= th.watch) return "watch";
    return "on_track";
  }

  function readLab() {
    return {
      metric: el("sla-lab-metric").value,
      family: el("sla-lab-family").value,
      elapsed: Math.max(Number(el("sla-lab-elapsed").value) || 0, 0),
      load: (Number(el("sla-lab-load").value) || 0) / 100,
      reschedules: Number(el("sla-lab-resched").value) || 0,
      followups: Number(el("sla-lab-followups").value) || 0,
      tier: el("sla-lab-tier").value,
      ev: el("sla-lab-ev").checked,
      queue: (Number(el("sla-lab-queue").value) || 0) / 100,
      docs: el("sla-lab-docs").checked,
      docAge: Number(el("sla-lab-docage").value) || 0,
      customerGarage: el("sla-lab-custgarage").checked,
      mode: el("sla-lab-mode").value,
      role: el("sla-lab-role").value
    };
  }

  function predict(rule, s) {
    var drivers = [];
    var mult = 1;
    var typical = Math.max(rule.typical_duration_hours, 0.01);
    var deadline = hoursOf(rule.deadline);
    function add(code, text, factor, hours) { drivers.push({ code: code, label: text, factor: factor || null, hours: hours || null }); }

    var hasOwner = s.metric === "repair_completion" || SURVEY_METRICS.indexOf(s.metric) >= 0;
    var ownerKind = s.metric === "repair_completion" ? "garage" : "surveyor";
    if (hasOwner) {
      var bands = (RM.load_factors || []).slice().sort(function (a, b) { return b.min_ratio - a.min_ratio; });
      for (var i = 0; i < bands.length; i++) {
        if (s.load >= bands[i].min_ratio) { mult *= bands[i].multiplier; add("OWNER_OVERLOADED", ownerKind + " at " + Math.round(s.load * 100) + "% of capacity", bands[i].multiplier); break; }
      }
    }
    if (s.reschedules) {
      var rm = Math.min(1 + (RM.reschedule_step || 0) * s.reschedules, RM.reschedule_cap || 1.5);
      mult *= rm; add("RESCHEDULES", s.reschedules + " inspection reschedule(s)", rm);
    }
    if (s.followups && SURVEY_METRICS.indexOf(s.metric) >= 0) {
      var fm = Math.min(1 + (RM.followup_step || 0) * s.followups, RM.followup_cap || 1.4);
      mult *= fm; add("UNANSWERED_FOLLOWUPS", s.followups + " follow-up(s) without a report", fm);
    }
    var tm = (RM.risk_tier_multipliers || {})[s.tier] || 1;
    if (tm > 1) { mult *= tm; add("CLAIM_COMPLEXITY", s.tier + " risk-tier handling path", tm); }
    if (s.ev && SPECIALIST_METRICS.indexOf(s.metric) >= 0) { mult *= RM.ev_multiplier || 1; add("EV_SPECIALIST_SCARCITY", "EV high-voltage work needs scarce certified capacity", RM.ev_multiplier); }
    if (s.queue > 0) {
      var qm = 1 + (RM.queue_pressure_weight || 0) * s.queue;
      mult *= qm;
      if (s.queue >= 0.3) add("QUEUE_PRESSURE", "Queue pressure " + Math.round(s.queue * 100) + "%", qm);
    }
    var expectedTotal = typical * mult;
    var overrun = Math.max(s.elapsed - expectedTotal, 0);
    var remainingWork = Math.max(expectedTotal - s.elapsed, 0.35 * expectedTotal + 0.25 * overrun, 0.05);
    if (s.docs && s.metric !== "document_verification") {
      var typicalWait = RM.typical_customer_response_hours || 36;
      var wait = Math.max(typicalWait - s.docAge, 0.25 * typicalWait);
      remainingWork += wait;
      add("DOCUMENTS_OUTSTANDING", "Customer documents still owed", null, wait);
    }
    var budget = deadline - s.elapsed;
    var sigma = (RM.uncertainty_pct_of_expected || 0.3) * remainingWork + (RM.uncertainty_floor_hours || 0.5);
    var p, band;
    if (budget <= 0) { p = 1; band = "breached"; add("SLA_ALREADY_BREACHED", "SLA exceeded by " + fmtDuration(-budget), null, -budget); }
    else { p = Math.max(0, Math.min(1, 1 - phi((budget - remainingWork) / sigma))); band = bandFor(p); }
    drivers.sort(function (a, b) { return (Math.abs((b.factor || 1) - 1) * 100 + (b.hours || 0) / 4) - (Math.abs((a.factor || 1) - 1) * 100 + (a.hours || 0) / 4); });
    return { p: p, band: band, expected: remainingWork, budget: budget, deadline: deadline, drivers: drivers, consumed: s.elapsed / deadline * 100 };
  }

  function planActions(rule, s, pred) {
    var minP = GUARD.min_probability_to_act || 0.6;
    if (!(pred.band === "breached" || pred.p >= minP)) return [];
    var urgency = pred.band === "breached" || pred.band === "critical" ? "immediate" : "today";
    var codes = pred.drivers.map(function (d) { return d.code; });
    var pct = Math.max(pred.consumed, (s.elapsed + pred.expected) / pred.deadline * 100);
    var due = rule.escalation_sequence.filter(function (st) { return st.at_pct <= pct; });
    var recs = {};
    function put(action, why) {
      if (!ACTIONS[action]) return;
      if (!recs[action]) recs[action] = { action: action, why: why, urgency: urgency };
    }
    put(due.length ? due[due.length - 1].action : "remind_owner", "Escalation step reached at " + Math.round(pct) + "% projected consumption.");
    due.forEach(function (st) { if (st.action === "remind_surveyor" || st.action === "chase_documents") put(st.action, "Earlier reminder step still useful (cheap, idempotent)."); });
    if (codes.indexOf("OWNER_OVERLOADED") >= 0) {
      if (s.metric === "repair_completion") {
        if (s.customerGarage) put("escalate_manager", "Garage is overloaded but customer-chosen, so reassignment is not offered.");
        else put("reassign_garage", "Garage over capacity; a candidate with headroom exists.");
      } else {
        put("reassign_surveyor", "Surveyor over capacity; a candidate with headroom exists.");
      }
    }
    if (codes.indexOf("DOCUMENTS_OUTSTANDING") >= 0) put("chase_documents", "Documents owed; clock is not paused for this metric.");
    if (codes.indexOf("QUEUE_PRESSURE") >= 0 && s.queue >= (RM.bottleneck_score_threshold || 0.45)) {
      put("prioritize_claim", "Queue is bottlenecked.");
      put("rebalance_queue", "Queue is bottlenecked; rebalance needs a manager.");
    }
    return Object.keys(recs).map(function (k) { return recs[k]; }).sort(function (a, b) { return URGENCY[a.urgency] - URGENCY[b.urgency]; });
  }

  function authorise(rec, s) {
    var pol = ACTIONS[rec.action] || {};
    if ((GUARD.never_autonomous || []).indexOf(rec.action) >= 0) return { d: "blocked", why: "never autonomous" };
    if (s.mode !== "execute") return { d: "recommend only", why: "recommend mode: nothing is executed" };
    if (GUARD.execution_roles.indexOf(s.role) < 0 && s.role !== "admin") return { d: "denied", why: "role '" + s.role + "' may not run the agent in execute mode (needs " + GUARD.execution_roles.join(" / ") + ")" };
    if (pol.autonomy === "human_approval") return { d: "gated", why: "approval task raised for " + (pol.approver_role || "a manager") + "; the agent does not act" };
    if (familyOf(s.family) === "third_party" && GUARD.tp_claims_autonomy === "tasks_only" && pol.tool !== "create_claim_task") return { d: "blocked", why: "third-party claims allow task-level actions only (no customer/partner contact)" };
    return { d: "executes", why: "autonomous-class action via the authorised tool '" + pol.tool + "'" };
  }

  window.runSlaLab = function () {
    var out = el("sla-lab-output");
    var sum = el("sla-lab-summary");
    if (!out || !sum) return;
    var s = readLab();
    var rule = rulesInForce(s.metric, familyOf(s.family), new Date());
    if (!rule) {
      sum.innerHTML = "";
      out.textContent = "No SLA rule applies to metric '" + s.metric + "' for family '" + s.family + "'.";
      return;
    }
    var pred = predict(rule, s);
    var recs = planActions(rule, s, pred).map(function (r) { return { rec: r, auth: authorise(r, s) }; });
    var lines = [];
    lines.push("[Clock] " + rule.title + " | rule " + rule.sla_id + " v" + rule.rule_version + " | deadline " + fmtDuration(pred.deadline) + " | " + Math.round(pred.consumed) + "% consumed");
    lines.push("[Model] sla-risk-baseline-v1: ~" + fmtDuration(pred.expected) + " of work expected vs " + (pred.budget > 0 ? fmtDuration(pred.budget) + " left" : "no time left") + " => breach probability " + (pred.p * 100).toFixed(1) + "% (" + BAND_LABEL[pred.band] + ")");
    if (pred.drivers.length) {
      lines.push("[Drivers]");
      pred.drivers.forEach(function (d) { lines.push("  • " + d.label + (d.factor ? "  (x" + d.factor.toFixed(2) + ")" : "") + (d.hours ? "  (+" + fmtDuration(d.hours) + ")" : "")); });
    } else lines.push("[Drivers] none: nothing in the signals slows this clock.");
    lines.push("");
    if (!recs.length) {
      lines.push("[Agent] Probability is below the action threshold (" + Math.round((GUARD.min_probability_to_act || 0) * 100) + "%): no action recommended.");
    } else {
      lines.push("[Agent: mode=" + s.mode + ", role=" + s.role + ", family=" + s.family + "]");
      recs.forEach(function (x) { lines.push("  " + x.auth.d.toUpperCase().padEnd(15) + " " + (ACTIONS[x.rec.action].label || x.rec.action) + "  — " + x.auth.why); });
    }
    out.textContent = lines.join("\n");
    sum.innerHTML = '<div class="tp-sum-grid">' +
      '<div class="card"><div class="stat-label">Breach probability</div><div class="stat-num">' + (pred.p * 100).toFixed(0) + "%</div></div>" +
      '<div class="card"><div class="stat-label">Risk band</div><div class="stat-num"><span class="badge ' + BAND_BADGE[pred.band] + '">' + esc(BAND_LABEL[pred.band]) + "</span></div></div>" +
      '<div class="card"><div class="stat-label">Recommended actions</div><div class="stat-num">' + recs.length + "</div></div>" +
      '<div class="card"><div class="stat-label">Executed autonomously</div><div class="stat-num">' + recs.filter(function (x) { return x.auth.d === "executes"; }).length + "</div></div></div>";
  };

  // ------------------------------------------------------------------------------------------------ authorisation matrix
  function renderMatrix() {
    var body = el("sla-action-matrix");
    if (!body) return;
    body.innerHTML = Object.keys(ACTIONS).map(function (k) {
      var a = ACTIONS[k];
      var auto = a.autonomy === "autonomous";
      return "<tr><td><strong>" + esc(a.label) + "</strong><div style=\"font-size:.76rem;color:#64748b;\"><code>" + esc(k) + "</code></div></td>" +
        "<td><span class=\"badge " + (auto ? "badge-green" : "badge-amber") + "\">" + (auto ? "Agent may execute" : "Human approval") + "</span></td>" +
        "<td><code>" + esc(a.tool) + "</code></td><td>" + esc(a.approver_role ? label(a.approver_role) : "—") + "</td><td style=\"font-size:.84rem;\">" + esc(a.description) + "</td></tr>";
    }).join("");
    var g = el("sla-guardrails");
    if (g) {
      g.innerHTML = "<ul style=\"margin:0;padding-left:18px;font-size:.88rem;line-height:1.6;\">" +
        "<li>Acts only above <strong>" + Math.round(GUARD.min_probability_to_act * 100) + "%</strong> breach probability; at most <strong>" + GUARD.max_autonomous_actions_per_claim_per_run + "</strong> autonomous actions per claim per run; <strong>" + GUARD.cooldown_hours + "h</strong> cooldown on repeat reminders.</li>" +
        "<li>Execution is limited to <strong>" + GUARD.execution_roles.map(label).join(" / ") + "</strong>; recommendations are available to " + GUARD.recommendation_roles.map(label).join(", ") + ".</li>" +
        "<li>Third-party claims: <strong>" + esc(label(GUARD.tp_claims_autonomy)) + "</strong> (no customer or partner contact).</li>" +
        "<li>Never autonomous: " + GUARD.never_autonomous.map(function (x) { return "<code>" + esc(x) + "</code>"; }).join(", ") + ".</li>" +
        "<li>Reassignments and queue rebalancing always become a manager approval task; the customer's chosen garage is never reassigned.</li></ul>";
    }
  }

  function initSelectors() {
    var m = metricsInOrder();
    ["sla-rule-metric", "sla-lab-metric"].forEach(function (id) {
      var sel = el(id);
      if (!sel || sel.options.length) return;
      sel.innerHTML = m.map(function (x) { return '<option value="' + esc(x) + '">' + esc(label(x)) + "</option>"; }).join("");
    });
    var lab = el("sla-lab-metric");
    if (lab) lab.value = "survey_completion";
    var asof = el("sla-asof");
    if (asof && !asof.value) asof.value = new Date().toISOString().slice(0, 10);
  }

  window.renderSlaDashboard = renderDashboard;
  window.renderSlaRuleExplorer = renderRuleExplorer;

  document.addEventListener("DOMContentLoaded", function () {
    initSelectors();
    renderDashboard();
    renderRuleExplorer();
    renderMatrix();
    window.runSlaLab();
  });
})();
