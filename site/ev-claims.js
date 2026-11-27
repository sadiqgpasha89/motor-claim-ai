/* Electric-vehicle (EV) claims workflow showcase (IN-EV-CLAIMS-2026).
 * Mirrors rules/india/ev_claims_controls.json and services/workflow/ev_claims.py.
 * DEMO / SYNTHETIC: thresholds, bands and clearances are illustrative and need OEM and EV safety-officer sign-off.
 * Hard rule: nothing here (or in the product) infers that an EV is safe to operate from external photographs.
 */
(function () {
  "use strict";

  var STAGES = [
    { id: "INTAKE_TRIAGE", queue: "ev_triage_intake", owner: "claims_handler", sla: 2, gate: "EV safety triage recorded, the HV hold placed, and every safety escalation acknowledged by a manager. The vehicle stays on hold: customer-declared 'drivable' is recorded but never accepted.", api: "POST /claims/{id}/ev/triage · /safety-escalations", what: "Safety triage and HV hold (opens automatically at FNOL)." },
    { id: "SAFE_RECOVERY_ISOLATION", queue: "ev_safe_recovery", owner: "claims_handler", sla: 12, gate: "Flatbed (or on-site isolation) by an EV-HV qualified provider, HV isolation verified, quarantine location with the minimum clearance. Every escalation must now be resolved with an evidence reference.", api: "POST /claims/{id}/ev/recovery", what: "Flatbed recovery, HV isolation and quarantine." },
    { id: "SPECIALIST_SURVEY", queue: "ev_specialist_survey", owner: "surveyor", sla: 48, gate: "A physical inspection by an EV-HV certified surveyor with an unexpired verified licence, assigned to this claim. Photo, video and customer-declared inspections are rejected.", api: "POST /claims/{id}/ev/specialist-survey", what: "EV-HV certified physical survey." },
    { id: "OEM_DIAGNOSTICS", queue: "ev_oem_diagnostics", owner: "garage", sla: 72, gate: "The full OEM diagnostic test set (DTC, BMS cell delta, insulation, HV interlock, coolant pressure, pack leak/IP, state of health) with an OEM report reference. A reported pass that contradicts the measured value is refused.", api: "POST /claims/{id}/ev/oem-diagnostics", what: "OEM diagnostic scan and HV tests." },
    { id: "BATTERY_DISPOSITION", queue: "ev_battery_disposition", owner: "claims_manager", sla: 72, gate: "A human records repair vs replacement with an OEM engineer reference. The software recommendation is advisory; a critical test failure bars in-place repair; the inspecting surveyor cannot be the OEM engineer.", api: "POST /claims/{id}/ev/battery-disposition", what: "Battery repair-versus-replacement decision." },
    { id: "COST_BENCHMARKING", queue: "ev_cost_benchmark", owner: "claims_handler", sla: 48, gate: "EV parts and HV labour benchmarked against bands. Flagged lines or high-value quotes need a claims manager review note.", api: "POST /claims/{id}/ev/cost-benchmark · /review", what: "EV-specific parts cost benchmarks." },
    { id: "TECHNICAL_SIGN_OFF", queue: "ev_technical_signoff", owner: "claims_manager", sla: 48, gate: "The only step that lifts the settlement hold. The person who recorded the battery disposition cannot sign off (separation of duties).", api: "POST /claims/{id}/ev/technical-sign-off", what: "EV technical sign-off and settlement clearance." },
    { id: "SETTLEMENT_CLEARED", queue: "ev_settlement_in_od_engine", owner: "claims_handler", sla: 72, gate: "The OD engine now computes the settlement (EV-flagged: never fast-tracked). Repair cannot start until an approved settlement exists.", api: "POST /claims/{id}/settlement-recommendations", what: "Settlement in the OD engine, human-approved." },
    { id: "REPAIR_RECERTIFICATION", queue: "ev_recertification", owner: "garage", sla: 96, gate: "Post-repair HV recertification: insulation, DTC cleared, interlock, charge test, thermal scan, physical road test and an OEM certificate. A battery-critical claim also needs its thermal watch cleared.", api: "POST /claims/{id}/ev/recertification · /thermal-watch/clear", what: "Post-repair HV recertification and release." },
    { id: "SALVAGE_DISPOSAL", queue: "ev_salvage_disposal", owner: "claims_handler", sla: 240, gate: "Removed packs follow a serial-tracked chain: removed, quarantined, handed to a registered recycler in dangerous-goods compliant transport, disposal certificate. Resale as a used part is forbidden.", api: "POST /claims/{id}/ev/salvage-events", what: "Battery salvage and disposal controls (only if a pack is removed)." },
    { id: "CLOSED", queue: "ev_closed", owner: "auditor", sla: 0, gate: "Terminal. The OD claim cannot close before the EV case does.", api: "POST /claims/{id}/ev/close", what: "Closed." }
  ];

  var SKIP_FOR_SCREENING = ["SAFE_RECOVERY_ISOLATION", "SPECIALIST_SURVEY", "BATTERY_DISPOSITION", "SALVAGE_DISPOSAL"];

  var SIGNALS = {
    underbody_impact: { label: "Underbody / pack-zone strike", cat: "impact", sev: "high", w: 30 },
    pack_zone_deformation: { label: "Deformation of pack enclosure, tray or side sill", cat: "impact", sev: "high", w: 30 },
    side_sill_intrusion: { label: "Side-sill / floor intrusion", cat: "impact", sev: "high", w: 25 },
    airbags_deployed: { label: "Airbags deployed", cat: "impact", sev: "high", w: 20 },
    collision_impact_any: { label: "Any collision or road-hazard impact", cat: "impact", sev: "moderate", w: 10 },
    ground_strike_debris_pothole: { label: "Strike by debris, kerb or pothole", cat: "impact", sev: "moderate", w: 15 },
    hv_warning_light: { label: "HV / battery warning light on dash", cat: "hv", sev: "high", w: 25 },
    isolation_fault_warning: { label: "Isolation fault / insulation warning", cat: "hv", sev: "critical", w: 40 },
    orange_cable_damage: { label: "Damaged or exposed orange HV cable", cat: "hv", sev: "critical", w: 40 },
    loss_of_drive_power: { label: "Loss of drive power / vehicle immobile", cat: "hv", sev: "moderate", w: 10 },
    coolant_leak_near_pack: { label: "Coolant leak at or near the pack", cat: "thermal", sev: "high", w: 25 },
    smoke_or_fire: { label: "Smoke or fire", cat: "thermal", sev: "critical", w: 50 },
    burning_or_chemical_smell: { label: "Burning or sweet chemical smell", cat: "thermal", sev: "critical", w: 40 },
    venting_hissing_swelling: { label: "Venting, hissing or swelling of the pack", cat: "thermal", sev: "critical", w: 45 },
    abnormal_heat_from_pack: { label: "Abnormal heat from the pack area", cat: "thermal", sev: "critical", w: 40 },
    thermal_event_warning: { label: "Thermal event / thermal runaway warning", cat: "thermal", sev: "critical", w: 50 },
    charge_port_damage: { label: "Charge port or inlet damaged", cat: "charging", sev: "high", w: 20 },
    charging_fault_behaviour: { label: "Charging fault or abnormal charging behaviour", cat: "charging", sev: "high", w: 20 },
    flood_or_immersion: { label: "Flood or water immersion", cat: "water", sev: "high", w: 35 }
  };

  var CATEGORY_LABEL = { impact: "Battery pack impact", hv: "High-voltage system", thermal: "Thermal risk", charging: "Charging system", water: "Water / immersion" };

  var BANDS = [
    { key: "not_excluded", min: 0, label: "Battery impact not excluded" },
    { key: "possible", min: 20, label: "Battery impact possible" },
    { key: "probable", min: 50, label: "Battery impact probable" },
    { key: "severe", min: 75, label: "Severe battery impact suspected" }
  ];

  var HV_PERILS = ["road_accident", "collision", "flood", "fire", "ev_high_voltage", "natural_calamity", "total_loss", "malicious_damage"];

  var PARTS = {
    "PRT-EV-BAT-TRAY": { name: "Battery underbody shield & tray", min: 18000, max: 42000 },
    "PRT-EV-PACK-FULL": { name: "Traction battery pack (complete, new)", min: 900000, max: 1650000 },
    "PRT-EV-MODULE": { name: "Battery module (each)", min: 85000, max: 190000 },
    "PRT-EV-BMS": { name: "Battery management system unit", min: 35000, max: 95000 },
    "PRT-EV-HV-JB": { name: "HV junction box / PDU", min: 40000, max: 110000 },
    "PRT-EV-HV-HARNESS": { name: "Orange HV cable harness", min: 15000, max: 60000 },
    "PRT-EV-INVERTER": { name: "Inverter / motor controller", min: 90000, max: 240000 },
    "PRT-EV-MOTOR": { name: "Drive motor assembly", min: 120000, max: 320000 },
    "PRT-EV-DCDC": { name: "DC-DC converter", min: 22000, max: 60000 },
    "PRT-EV-OBC": { name: "Onboard charger", min: 35000, max: 95000 },
    "PRT-EV-CHG-PORT": { name: "Charge port / inlet assembly", min: 9000, max: 32000 },
    "PRT-EV-COOLANT-PLATE": { name: "Battery cooling plate / coolant circuit kit", min: 25000, max: 78000 }
  };
  var TOLERANCE = 0.15;
  var LOW_RATIO = 0.5;
  var MANAGER_REVIEW_ABOVE = 50000;
  var INSULATION_MIN = 500;
  var IDV_DEMO = 2800000;

  var STANDARD_STEPS = ["Photographs of the damage", "Garage estimate", "AI damage assessment", "Depreciation & deductible", "Settlement or cashless repair", "Repair and delivery"];

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
    var box = el("ev-compare");
    if (!box) return;
    var std = STANDARD_STEPS.map(function (s, i) {
      return '<li><span class="tp-step-no">' + (i + 1) + "</span>" + esc(s) + "</li>";
    }).join("");
    var ev = STAGES.slice(0, 10).map(function (s, i) {
      return '<li><span class="tp-step-no ev">' + (i + 1) + "</span>" + esc(s.what) + "</li>";
    }).join("");
    box.innerHTML =
      '<div class="card tp-col od"><div class="stat-label">Ordinary vehicle damage</div><h3 style="margin:4px 0 8px;">Visible damage, repairable from an estimate</h3>' +
      '<p class="section-sub" style="margin:0 0 10px;">Photographs and a garage estimate are usually enough to decide. LOW-risk claims up to ₹25,000 can be straight-through.</p><ol class="tp-steps">' + std + "</ol>" +
      '<div class="btn-row"><span class="badge badge-blue">Photo-led assessment</span><span class="badge badge-green">Fast-track eligible</span></div></div>' +
      '<div class="card tp-col evc"><div class="stat-label">Electric vehicle (EV)</div><h3 style="margin:4px 0 8px;">The dangerous damage is the damage you cannot see</h3>' +
      '<p class="section-sub" style="margin:0 0 10px;">A damaged traction battery can fail hours or days later. Nothing is cleared from a photograph; specialists and OEM tests decide.</p><ol class="tp-steps">' + ev + "</ol>" +
      '<div class="btn-row"><span class="badge badge-rose">No photo-only clearance</span><span class="badge badge-amber">HV hold from FNOL</span><span class="badge badge-purple">Dedicated queues</span></div></div>';
  }

  var selectedStage = "SPECIALIST_SURVEY";

  window.evSelectStage = function (id) {
    selectedStage = id;
    renderStages();
  };

  function renderStages() {
    var strip = el("ev-stage-strip");
    var insp = el("ev-stage-inspector");
    if (!strip || !insp) return;
    strip.innerHTML = STAGES.map(function (s) {
      var cls = "state-pill-btn" + (s.id === selectedStage ? " active" : "");
      return '<button type="button" class="' + cls + '" onclick="evSelectStage(\'' + s.id + '\')">' + esc(stageLabel(s.id)) + "</button>";
    }).join("");
    var s = STAGES.filter(function (x) { return x.id === selectedStage; })[0];
    insp.innerHTML =
      '<div class="card" style="margin-top:12px;"><div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;">' +
      '<h3 style="margin:0;">' + esc(stageLabel(s.id)) + '</h3><div class="btn-row">' +
      '<span class="badge badge-purple">Queue: ' + esc(s.queue) + "</span>" +
      '<span class="badge badge-slate">Owner: ' + esc(s.owner) + "</span>" +
      '<span class="badge badge-amber">SLA: ' + (s.sla ? s.sla + "h" : "n/a") + "</span>" +
      '<span class="badge ' + (s.id === "CLOSED" ? "badge-slate" : "badge-rose") + '">' + (s.id === "CLOSED" ? "Terminal" : "Human gate") + "</span></div></div>" +
      '<p style="margin:10px 0 6px;"><strong>Exit gate.</strong> ' + esc(s.gate) + "</p>" +
      '<p style="margin:0;font-size:13px;color:#475569;"><code>' + esc(s.api) + "</code></p></div>";
  }

  function renderSignalPicker() {
    var box = el("ev-signal-picker");
    if (!box) return;
    var cats = ["impact", "hv", "thermal", "charging", "water"];
    box.innerHTML = cats.map(function (c) {
      var items = Object.keys(SIGNALS).filter(function (k) { return SIGNALS[k].cat === c; }).map(function (k) {
        var s = SIGNALS[k];
        return '<label class="risk-check-label ev-sig"><input type="checkbox" class="ev-sig-cb" value="' + k + '" onchange="runEvLab()" /> ' +
          esc(s.label) + ' <span class="ev-sev ev-sev-' + s.sev + '">' + s.sev + "</span></label>";
      }).join("");
      return '<fieldset class="ev-fieldset"><legend>' + esc(CATEGORY_LABEL[c]) + "</legend>" + items + "</fieldset>";
    }).join("");
  }

  function selectedSignals() {
    var out = [];
    var boxes = document.querySelectorAll(".ev-sig-cb");
    for (var i = 0; i < boxes.length; i++) {
      if (boxes[i].checked) out.push(boxes[i].value);
    }
    return out;
  }

  /* Mirrors classify_signals(): there is deliberately no "safe" outcome. */
  function classify(signals, peril, flagged) {
    var score = 0;
    var critical = [];
    var high = [];
    var byCat = {};
    signals.forEach(function (k) {
      var s = SIGNALS[k];
      score += s.w;
      if (s.sev === "critical") critical.push(k);
      if (s.sev === "high") high.push(k);
      (byCat[s.cat] = byCat[s.cat] || []).push(k);
    });
    score = Math.min(100, score);
    var isFlagged = flagged || peril === "ev_high_voltage";
    if (isFlagged) score = Math.max(score, 50);
    var cls;
    if (critical.length || high.length >= 2 || isFlagged) cls = "battery_critical";
    else if (signals.length || HV_PERILS.indexOf(peril) >= 0) cls = "hv_suspected";
    else cls = "screening_only";
    var band = BANDS[0];
    BANDS.forEach(function (b) { if (score >= b.min) band = b; });
    var thermal = byCat.thermal || [];
    var thermalLevel;
    if (thermal.some(function (k) { return SIGNALS[k].sev === "critical"; })) thermalLevel = "emergency";
    else if (thermal.length) thermalLevel = "elevated";
    else if (cls === "battery_critical") thermalLevel = "watch";
    else thermalLevel = "not_excluded";
    var esc_level = null;
    if (thermalLevel === "emergency") esc_level = "emergency";
    else if (critical.length || byCat.hv || byCat.charging || byCat.water || byCat.thermal) esc_level = "urgent";
    return { score: score, band: band, cls: cls, thermalLevel: thermalLevel, escalation: esc_level, byCat: byCat };
  }

  var CLASS_LABEL = { battery_critical: "Battery critical", hv_suspected: "HV system suspected", screening_only: "HV screening only" };

  function badge(text, kind) {
    return '<span class="badge badge-' + kind + '">' + esc(text) + "</span>";
  }

  window.runEvLab = function () {
    var out = el("ev-lab-output");
    var sum = el("ev-lab-summary");
    if (!out || !sum) return;
    var signals = selectedSignals();
    var peril = el("ev-peril").value;
    var flagged = el("ev-flagged").checked;
    var r = classify(signals, peril, flagged);
    var path = STAGES.map(function (s) {
      var skip = null;
      if (r.cls === "screening_only" && SKIP_FOR_SCREENING.indexOf(s.id) >= 0) skip = s.id === "SALVAGE_DISPOSAL" ? "no pack removed" : "screening-only class";
      if (r.cls !== "screening_only" && s.id === "SALVAGE_DISPOSAL") skip = "only if the disposition removes the pack";
      return { id: s.id, skip: skip };
    });
    var applicable = path.filter(function (p) { return !p.skip; }).length;
    var lines = [];
    lines.push("[Classification] risk class: " + CLASS_LABEL[r.cls] + " | impact score " + r.score + "/100 | band: " + r.band.label);
    lines.push("[Thermal] level: " + r.thermalLevel + (r.cls === "battery_critical" ? " | thermal watch REQUIRED (cleared only with an OEM reference)" : ""));
    lines.push("[Escalation] " + (r.escalation === "emergency" ? "EMERGENCY (15 min SLA): customer told to keep clear and call 112; EV safety officer alerted" : r.escalation === "urgent" ? "URGENT (60 min SLA): do not drive, charge or touch orange cables; flatbed recovery to an EV-certified centre" : "none from the declared signals (this does not mean safe)"));
    lines.push("[Operation status] HOLD - do not operate pending inspection");
    lines.push("[safe_to_operate] not_determinable_from_photographs  (photo_only_clearance_allowed: false)");
    lines.push("");
    lines.push("[Required specialists]");
    if (r.cls === "screening_only") {
      lines.push("  • OEM HV health screening (DTC, insulation, HV interlock, state of health) by an EV-HV qualified OEM workshop");
      lines.push("  • Specialist survey and flatbed recovery are skipped ONLY while no signal exists; any new evidence escalates the class and rewinds the case");
    } else {
      lines.push("  • Flatbed recovery + HV isolation by an EV-HV qualified provider (wheel-lift, dolly and driving are refused)");
      lines.push("  • Physical survey by an EV-HV certified surveyor (photo/video/customer-declared inspections are rejected)");
      lines.push("  • Full OEM diagnostics (7 tests) by an OEM-authorised EV workshop, then an OEM engineer reference on the battery decision");
    }
    lines.push("");
    lines.push("[Stage path] " + applicable + " of " + STAGES.length + " stages apply");
    path.forEach(function (p) {
      lines.push("  " + (p.skip ? "○ " : "● ") + stageLabel(p.id) + (p.skip ? "  (skipped: " + p.skip + ")" : ""));
    });
    lines.push("");
    lines.push("[Settlement] OD settlement, approval, payment and closure endpoints return 409 HUMAN_REVIEW_REQUIRED until technical sign-off.");
    out.textContent = lines.join("\n");

    var tone = r.cls === "battery_critical" ? "rose" : r.cls === "hv_suspected" ? "amber" : "blue";
    sum.innerHTML =
      '<div class="tp-sum-grid">' +
      '<div class="card"><div class="stat-label">Risk class</div><div class="stat-num" style="font-size:20px;">' + badge(CLASS_LABEL[r.cls], tone) + "</div></div>" +
      '<div class="card"><div class="stat-label">Battery impact score</div><div class="stat-num">' + r.score + "</div><div class=\"stat-label\">" + esc(r.band.label) + "</div></div>" +
      '<div class="card"><div class="stat-label">Applicable stages</div><div class="stat-num">' + applicable + " / " + STAGES.length + "</div></div>" +
      '<div class="card"><div class="stat-label">Safe to operate?</div><div class="stat-num" style="color:#be123c;font-size:18px;">Not determinable from photographs</div></div>' +
      "</div>";
  };

  window.evPreset = function (name) {
    var presets = {
      glass: { peril: "glass_damage", flagged: false, signals: [] },
      pothole: { peril: "road_accident", flagged: false, signals: ["underbody_impact", "ground_strike_debris_pothole"] },
      smoke: { peril: "road_accident", flagged: false, signals: ["underbody_impact", "smoke_or_fire"] },
      flood: { peril: "flood", flagged: false, signals: ["flood_or_immersion", "charging_fault_behaviour"] }
    };
    var p = presets[name];
    if (!p) return;
    el("ev-peril").value = p.peril;
    el("ev-flagged").checked = p.flagged;
    var boxes = document.querySelectorAll(".ev-sig-cb");
    for (var i = 0; i < boxes.length; i++) boxes[i].checked = p.signals.indexOf(boxes[i].value) >= 0;
    window.runEvLab();
  };

  /* Mirrors compute_benchmark(). */
  window.runEvBenchmark = function () {
    var out = el("ev-bench-output");
    if (!out) return;
    var code = el("ev-part").value;
    var quote = Number(el("ev-quote").value) || 0;
    var p = PARTS[code];
    var status;
    if (quote > p.max * (1 + TOLERANCE)) status = "above_benchmark";
    else if (quote < p.min * LOW_RATIO) status = "suspiciously_low";
    else status = "within_benchmark";
    var manager = status !== "within_benchmark" || quote > MANAGER_REVIEW_ABOVE;
    var lines = [
      p.name + " (" + code + ")",
      "  benchmark band: " + inr(p.min) + " - " + inr(p.max) + " (tolerance +" + Math.round(TOLERANCE * 100) + "% above the ceiling; below " + Math.round(LOW_RATIO * 100) + "% of the floor is suspiciously low)",
      "  quoted: " + inr(quote) + "  ->  " + status,
      "  manager review required: " + (manager ? "YES (flagged line or quote above " + inr(MANAGER_REVIEW_ABOVE) + ")" : "no"),
      "  The benchmark is advisory and non-binding; a claims manager reviews flagged lines with a written note."
    ];
    out.textContent = lines.join("\n");
  };

  /* Mirrors the insulation-resistance threshold and the disposition rules. */
  window.runEvDiag = function () {
    var out = el("ev-diag-output");
    if (!out) return;
    var reading = Number(el("ev-insulation").value) || 0;
    var reported = el("ev-reported").value;
    var lines = [];
    lines.push("insulation_resistance measured: " + reading + " ohm/V (OEM minimum " + INSULATION_MIN + " ohm/V)");
    var breach = reading < INSULATION_MIN;
    if (reported === "pass" && breach) {
      lines.push("-> 400 VALIDATION_ERROR: reported 'pass' contradicts the measured value. The record is refused, not stored.");
    } else if (breach) {
      lines.push("-> recorded as FAIL. insulation_resistance is a critical-fail test:");
      lines.push("   • repair_in_place and no_battery_work are barred (409)");
      lines.push("   • advisory: replace_pack" + (IDV_DEMO > 0 ? " (or total_loss_review if the pack is ≥ 40% of IDV)" : ""));
      lines.push("   • a human still decides, with an OEM engineer reference; the surveyor cannot be that engineer");
    } else {
      lines.push("-> within threshold. This one test passing does not clear the vehicle: all 7 OEM tests, the survey and the technical sign-off are still required.");
    }
    out.textContent = lines.join("\n");
  };

  window.evAutonomyDemo = function (mode) {
    var out = el("ev-lab-output");
    if (!out) return;
    var logs = {
      photo_only:
        "Customer uploads 6 sharp photos of a lightly scraped EV and ticks 'the car is drivable'.\n" +
        "[Damage AI] ev_safety_determination: { safe_to_operate: 'not_determinable_from_photographs', photo_only_clearance_allowed: false }\n" +
        "            route_to_human_assessor: true -> recommended role: ev_specialist (mandatory HV isolation & physical BMS inspection)\n" +
        "[EV case] operation_status: hold_do_not_operate_pending_inspection\n" +
        "          triage.customer_declared_drivable: true  ->  recorded, 'NOT accepted' as evidence of safety.",
      od_endpoint:
        "POST /api/v1/claims/{ev_claim}/settlement-recommendations\n" +
        "-> 409 HUMAN_REVIEW_REQUIRED\n" +
        "   \"EV claims need specialist inspection, OEM diagnostics and technical sign-off before OD settlement; the vehicle cannot be cleared from photographs (IN-EV-CLAIMS-2026).\"\n" +
        "   details: { rule_id: 'IN-EV-CLAIMS-2026', ev_workflow_url: '/api/v1/claims/{id}/ev', blockers: [...] }\n" +
        "Same guard on: /approvals, /payments, /payments/agent-release, /close.",
      agent:
        "[SettlementRecommendationAgent] risk_tier=LOW (forced input), straight_through_eligible=true, allow_fast_track_auto_approve=true, ev_workflow_required=true, ev_settlement_cleared=false\n" +
        "-> status: NEEDS_HUMAN | auto_approved: false | actions_executed: []\n" +
        "-> suggested_next_action: route_to_ev_workflow | reason codes: RC_EV_TECHNICAL_SIGN_OFF_REQUIRED, RC_NO_PHOTO_ONLY_EV_CLEARANCE\n" +
        "The risk engine also never marks an EV straight-through eligible (MEDIUM_EV_HV_SCREENING driver).",
      thermal:
        "Policyholder, after the claim was triaged: POST /claims/{id}/ev/safety-escalations {signals: ['smoke_or_fire']}\n" +
        "-> emergency escalation (15 min SLA), risk class forced to battery_critical, thermal watch required, task 'ev_case_escalation' opened for the manager\n" +
        "-> policyholder sees only: 'Move well away... call 112 now' (no internal data)\n" +
        "Manager acknowledges -> resolve needs: evidence reference + thermal-stable confirmation, and cannot be the user who raised it.\n" +
        "Until resolved: stage advance and every OD path return 409. If it happens after technical sign-off, the clearance is REVOKED and the case rewinds to recovery.",
      salvage:
        "Pack PACK-SN-884412 removed during repair (serial recorded)\n" +
        "  pack_removed -> quarantined -> handed_over -> disposal_certified   (serial must match at every step)\n" +
        "  handed_over needs: registered recycler number + dangerous-goods compliant transport\n" +
        "  sold_for_reuse / sold_as_used_part / retained_by_insured -> 409 (forbidden by rule; BWMR 2022 reference, compliance sign-off required)\n" +
        "  The case cannot close without the disposal certificate reference, and the OD claim cannot close before the EV case."
    };
    out.textContent = logs[mode] || logs.photo_only;
  };

  document.addEventListener("DOMContentLoaded", function () {
    renderCompare();
    renderStages();
    renderSignalPicker();
    window.evPreset("pothole");
    window.runEvBenchmark();
    window.runEvDiag();
  });
})();
