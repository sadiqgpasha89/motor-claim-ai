/*
 * Settlement decision workbench UI (section 9).
 * Renders the output of SettlementEngine.build() - the browser mirror of services/settlement/workbench.py.
 */
(function () {
  "use strict";

  var data = window.SETTLEMENT_WORKBENCH_DATA;
  var Engine = window.SettlementEngine;
  if (!data || !Engine || !document.getElementById("swb-ledger")) return;

  var nf = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  var state = { selected: "cashless_repair", result: null };
  var defaults = data.demo.defaults;

  function el(id) {
    return document.getElementById(id);
  }

  function esc(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function inr(value) {
    var n = Number(value);
    return (n < 0 ? "−" : "") + "₹" + nf.format(Math.abs(n));
  }

  function signedInr(value) {
    var n = Number(value);
    return (n < 0 ? "−" : "+") + "₹" + nf.format(Math.abs(n));
  }

  function pct(ratioStr) {
    return (Number(ratioStr) * 100).toFixed(2).replace(/\.?0+$/, "") + "%";
  }

  function clauseChip(id) {
    return id ? ' <span class="chip chip-rule">' + esc(id) + "</span>" : "";
  }

  function statusBadge(status) {
    if (status === "recommended") return '<span class="badge badge-green">Recommended path</span>';
    if (status === "alternative") return '<span class="badge badge-blue">Alternative path</span>';
    return '<span class="badge badge-amber">What-if</span>';
  }

  // ------------------------------------------------------------------ controls

  function ageBands() {
    var schedule = data.depreciation.metal_wood_age_schedule;
    var prev = 0;
    return schedule.map(function (band) {
      var max = parseInt(band.max_months, 10);
      var rep = max >= 9999 ? prev + 10 : prev + Math.ceil((max - prev) / 2);
      var out = { rep: rep, min: prev, max: max, label: band.label, rate: band.rate };
      prev = max;
      return out;
    });
  }

  function fillControls() {
    var bands = ageBands();
    var defAge = parseInt(defaults.vehicle_age_months, 10);
    var ageSel = el("swb-age");
    ageSel.innerHTML = bands
      .map(function (b) {
        var selected = defAge > b.min && defAge <= b.max ? " selected" : "";
        return (
          '<option value="' + b.rep + '"' + selected + ">" + esc(b.label) + " (" +
          Math.round(Number(b.rate) * 100) + "% metal)</option>"
        );
      })
      .join("");
    if (defAge <= 0) ageSel.selectedIndex = 0;

    var classSel = el("swb-class");
    var map = data.depreciation.compulsory_deductible_by_vehicle_class_inr;
    classSel.innerHTML =
      '<option value="">Custom</option>' +
      Object.keys(map)
        .map(function (k) {
          return '<option value="' + esc(map[k]) + '">' + esc(k.replace(/_/g, " ")) + " (" + inr(map[k]) + ")</option>";
        })
        .join("");

    el("swb-vol").innerHTML = data.scenario_rule.parameters.voluntary_deductible_options_inr
      .map(function (v) {
        var selected = Number(v) === Number(defaults.voluntary_deductible_inr) ? " selected" : "";
        return '<option value="' + esc(v) + '"' + selected + ">" + inr(v) + "</option>";
      })
      .join("");

    setControlValues();
    el("swb-claim-ref").textContent = data.demo.claim_ref + " — " + data.demo.title;
  }

  function setControlValues() {
    el("swb-zd").checked = !!defaults.zero_depreciation;
    el("swb-cons").checked = !!defaults.consumables;
    el("swb-comp").value = Number(defaults.compulsory_deductible_inr);
    el("swb-idv").value = Number(defaults.idv_inr);
    el("swb-mv").value = Number(defaults.market_value_inr);
    el("swb-salvage").value = Number(defaults.salvage_value_inr);
    el("swb-class").value = "";
  }

  function amountValue(id, fallback) {
    var raw = el(id).value;
    var n = parseFloat(raw);
    if (raw === "" || isNaN(n) || n < 0) return fallback;
    return raw;
  }

  function readInputs() {
    return {
      vehicle_age_months: parseInt(el("swb-age").value, 10),
      zero_depreciation: el("swb-zd").checked,
      consumables: el("swb-cons").checked,
      compulsory_deductible_inr: amountValue("swb-comp", "0"),
      voluntary_deductible_inr: el("swb-vol").value,
      idv_inr: amountValue("swb-idv", "0"),
      market_value_inr: amountValue("swb-mv", "0"),
      salvage_value_inr: amountValue("swb-salvage", "0")
    };
  }

  // ------------------------------------------------------------------ top section renderers

  function renderLedger(r) {
    var rows = r.ledger.steps
      .map(function (s) {
        var muted = s.amount === "0.00" ? " swb-muted" : "";
        return (
          '<tr class="' + muted + '"><td>' + esc(s.label) + clauseChip(s.clause_id) + "</td>" +
          '<td class="swb-num">' + (s.amount === "0.00" ? "" : s.sign === "-" ? "−" : "+") + "₹" + nf.format(Number(s.amount)) + "</td>" +
          '<td class="swb-num swb-muted">' + inr(s.running_total) + "</td></tr>"
        );
      })
      .join("");
    el("swb-ledger").innerHTML =
      '<table class="swb-ledger"><thead><tr><th>Step</th><th class="swb-num">Amount</th><th class="swb-num">Running</th></tr></thead><tbody>' +
      rows +
      '<tr class="swb-total"><td colspan="2">Illustrative net payable</td><td class="swb-num">' +
      inr(r.ledger.net_payable) + "</td></tr></tbody></table>";
  }

  function renderSummary(r) {
    var s = r.summary;
    var gap = Number(s.claimed_inr) - Number(s.net_payable_inr);
    el("swb-summary").innerHTML =
      '<div class="swb-stats">' +
      stat("Claimed (garage quote)", inr(s.claimed_inr), "") +
      stat("Assessed / approved", inr(s.assessed_inr), "") +
      stat("Net payable", inr(s.net_payable_inr), "swb-good") +
      "</div>" +
      '<p class="swb-note">The insurer pays <strong>' + inr(s.net_payable_inr) + "</strong>, which is <strong>" + inr(gap) +
      "</strong> less than the quote. Open scenario 1 below to see exactly why, line by line, and which clause and approver sit behind each step.</p>" +
      '<p class="swb-note swb-muted">Rules: <code>' + esc(r.rule_versions.depreciation) + "</code>, <code>" +
      esc(r.rule_versions.authority) + "</code>, <code>" + esc(r.rule_versions.scenarios) + "</code></p>";
  }

  function stat(labelText, value, cls) {
    return '<div class="swb-stat"><div class="stat-label">' + esc(labelText) + '</div><div class="stat-num ' + cls + '">' + value + "</div></div>";
  }

  function renderTrace(r) {
    el("swb-trace-body").innerHTML = r.line_trace
      .map(function (t) {
        var removed = Number(t.assessed_inr) === 0;
        var tag = t.assessment_code ? ' <span class="badge badge-amber">' + esc(t.assessment_code.replace(/_/g, " ")) + "</span>" : "";
        return (
          '<tr class="' + (removed ? "swb-removed" : "") + '"><td><code>' + esc(t.part_code) + "</code>" + tag +
          '<br/><small class="swb-muted">' + esc(t.description) + "</small></td>" +
          "<td>" + inr(t.claimed_inr) + "</td><td>" + inr(t.assessed_inr) + "</td><td>" + inr(t.approved_inr) + "</td>" +
          "<td>" + inr(t.raw_depreciation_inr) + "</td><td>" + inr(t.applied_depreciation_inr) + "</td>" +
          "<td><strong>" + inr(t.net_line_inr) + "</strong></td>" +
          '<td class="swb-rule">' + esc(t.note) + "</td></tr>"
        );
      })
      .join("");
  }

  function renderCompare(r) {
    el("swb-compare-body").innerHTML = r.scenarios
      .map(function (sc) {
        var active = sc.scenario_code === state.selected ? " swb-row-active" : "";
        return (
          '<tr class="swb-row' + active + '" data-code="' + esc(sc.scenario_code) + '" tabindex="0" role="button" aria-label="Open scenario ' + sc.number + '">' +
          "<td>" + sc.number + "</td>" +
          "<td><strong>" + esc(sc.label) + '</strong><br/><small class="swb-muted">' + esc(sc.group) + "</small></td>" +
          "<td>" + inr(sc.claimed.amount) + "</td><td>" + inr(sc.approved.amount) + "</td>" +
          "<td>" + inr(sc.deducted.total) + "</td><td>" + inr(sc.addon_benefits.total) + "</td>" +
          "<td><strong>" + inr(sc.net_payable) + "</strong></td>" +
          "<td>" + inr(sc.customer_receives.customer_pays) + "</td>" +
          "<td>" + esc(sc.approval.checker_label) + "</td></tr>"
        );
      })
      .join("");
  }

  function renderPicker(r) {
    el("swb-picker").innerHTML = r.scenarios
      .map(function (sc) {
        return (
          '<button type="button" class="tab-btn' + (sc.scenario_code === state.selected ? " active" : "") +
          '" data-code="' + esc(sc.scenario_code) + '">' + sc.number + ". " + esc(sc.label) + "</button>"
        );
      })
      .join("");
  }

  // ------------------------------------------------------------------ decision record

  function panel(number, title, body, extraClass) {
    return (
      '<div class="swb-panel ' + (extraClass || "") + '"><div class="swb-panel-head"><span class="swb-step">' + number +
      "</span><h4>" + esc(title) + "</h4></div>" + body + "</div>"
    );
  }

  function itemList(items, emptyText) {
    if (!items.length) return '<p class="swb-note swb-muted">' + esc(emptyText) + "</p>";
    return (
      '<ul class="swb-list">' +
      items
        .map(function (i) {
          return "<li><span>" + esc(i.label) + clauseChip(i.clause_id) + '</span><span class="swb-num">' + signedInr(i.amount) + "</span></li>";
        })
        .join("") +
      "</ul>"
    );
  }

  function renderDetail(r) {
    var sc = r.scenarios.filter(function (s) {
      return s.scenario_code === state.selected;
    })[0];
    if (!sc) return;
    var a = sc.approval;

    var claimed = '<div class="swb-big">' + inr(sc.claimed.amount) + '</div><p class="swb-note">' + esc(sc.claimed.basis) + "</p>";

    var assessed =
      '<div class="swb-big">' + inr(sc.assessed.amount) + "</div>" +
      itemList(sc.assessed.adjustments, "No assessment adjustments - quoted amounts accepted.");

    var approved =
      '<div class="swb-big">' + inr(sc.approved.amount) + "</div>" +
      itemList(sc.approved.withheld, "Nothing withheld - every assessed line is approved.");

    var deducted =
      '<div class="swb-big">' + inr(sc.deducted.total) + "</div>" +
      itemList(
        sc.deducted.items.map(function (i) {
          return { label: i.label, clause_id: i.clause_id, amount: "-" + i.amount };
        }),
        "No deductions."
      ) +
      (sc.addon_benefits.items.length
        ? '<p class="swb-sub">Add-on benefits restored</p>' + itemList(sc.addon_benefits.items, "")
        : "");

    var clauses =
      '<ul class="swb-clauses">' +
      sc.policy_clauses
        .map(function (c) {
          return (
            "<li><span class=\"chip chip-rule\">" + esc(c.clause_id) + " · p." + c.page + "</span> <strong>" +
            esc(c.title) + "</strong><br/><small>" + esc(c.applied_for) + "</small></li>"
          );
        })
        .join("") +
      "</ul>";

    var skipped = a.skipped_tiers.length
      ? '<p class="swb-sub">Why not a lower tier</p><ul class="swb-list swb-small">' +
        a.skipped_tiers
          .map(function (t) {
            return "<li><span>" + esc(t.label) + "</span><span class=\"swb-muted\">" + esc(t.reason) + "</span></li>";
          })
          .join("") +
        "</ul>"
      : "";
    var who =
      '<ol class="swb-chain">' +
      "<li><strong>Recommended by</strong><br/>" + esc(a.recommended_by) + "</li>" +
      "<li><strong>Maker</strong><br/>" + esc(a.maker) + "</li>" +
      "<li><strong>Checker (approver)</strong><br/>" + esc(a.checker_label) +
      '<br/><small class="swb-muted">authority limit ' + inr(a.authority_limit_inr) + " · assessed on " + inr(a.authority_amount_inr) + "</small></li>" +
      "<li><strong>Payment release</strong><br/>" + esc(a.payment_release_label) + "</li>" +
      "</ol>" +
      (a.assessor_note ? '<p class="swb-note">' + esc(a.assessor_note) + ".</p>" : "") +
      skipped +
      '<p class="swb-note swb-muted">' + esc(a.maker_checker_note) + " " + esc(a.demo_note) + "</p>";

    var receives =
      '<div class="swb-big swb-good">' + inr(sc.customer_receives.amount) + "</div>" +
      '<ul class="swb-list"><li><span>Paid to</span><span>' + esc(sc.customer_receives.payee) + "</span></li>" +
      "<li><span>Customer pays</span><span class=\"swb-num\">" + inr(sc.customer_receives.customer_pays) + "</span></li></ul>" +
      '<p class="swb-note">' + esc(sc.customer_receives.outcome) + ".</p>" +
      (sc.insurer_net_cost !== sc.net_payable
        ? '<p class="swb-note"><strong>Insurer net cost after salvage recovery:</strong> ' + inr(sc.insurer_net_cost) + "</p>"
        : "");

    var why = sc.why_different;
    var whyRows =
      '<tr class="swb-total"><td>Requested</td><td class="swb-num">' + inr(why.requested) + "</td></tr>" +
      why.items
        .map(function (i) {
          return "<tr><td>" + esc(i.label) + clauseChip(i.clause_id) + '</td><td class="swb-num">' + signedInr(i.amount) + "</td></tr>";
        })
        .join("") +
      '<tr class="swb-total"><td>Customer receives</td><td class="swb-num">' + inr(why.receives) + "</td></tr>";
    var whyBody =
      '<table class="swb-ledger"><tbody>' + whyRows + "</tbody></table>" +
      '<p class="swb-note">The requested amount is ' + inr(why.gap) + " " + (Number(why.gap) >= 0 ? "higher" : "lower") +
      " than what is paid. " + (why.balanced
        ? '<span class="badge badge-green">Reconciles to the rupee</span>'
        : '<span class="badge badge-rose">Does not reconcile</span>') + "</p>";

    el("swb-detail").innerHTML =
      '<div class="swb-detail-head"><div><h3>Scenario ' + sc.number + ": " + esc(sc.label) + "</h3>" +
      '<p class="swb-note">' + esc(sc.summary) + "</p></div><div>" + statusBadge(sc.status) +
      ' <span class="badge badge-slate">' + esc(sc.group) + "</span></div></div>" +
      '<div class="swb-grid">' +
      panel(1, "What was claimed", claimed) +
      panel(2, "What was assessed", assessed) +
      panel(3, "What was approved", approved) +
      panel(4, "What was deducted", deducted) +
      panel(5, "Which policy clauses applied", clauses) +
      panel(6, "Who approves it", who) +
      panel(7, "What the customer receives", receives) +
      panel(8, "Why it differs from the requested amount", whyBody) +
      "</div>" +
      insight(sc) +
      '<div class="swb-assumptions"><strong>Assumptions</strong><ul>' +
      sc.assumptions.map(function (t) { return "<li>" + esc(t) + "</li>"; }).join("") +
      "</ul></div>";
  }

  // ------------------------------------------------------------------ scenario-specific insight

  function kv(rows) {
    return (
      '<table class="swb-ledger"><tbody>' +
      rows
        .map(function (r) {
          return "<tr" + (r[2] ? ' class="swb-total"' : "") + "><td>" + esc(r[0]) + '</td><td class="swb-num">' + r[1] + "</td></tr>";
        })
        .join("") +
      "</tbody></table>"
    );
  }

  function insightBox(title, body) {
    return '<div class="swb-insight"><h4>' + esc(title) + "</h4>" + body + "</div>";
  }

  function insight(sc) {
    var c = sc.comparison;
    switch (sc.scenario_code) {
      case "reimbursement":
        return insightBox(
          "Cashless vs reimbursement: who funds the repair",
          kv([
            ["Customer pays if cashless (network garage)", inr(c.customer_pays_if_cashless_inr)],
            ["Customer funds up front if reimbursed", inr(c.customer_funds_upfront_inr)],
            ["Insurer reimburses later", inr(c.reimbursed_inr)],
            ["Customer ends up paying if reimbursed", inr(c.customer_pays_if_reimbursed_inr), true]
          ]) +
            '<p class="swb-sub">Documents required before payment</p><ul class="swb-bullets">' +
            c.documents_required.map(function (d) { return "<li>" + esc(d) + "</li>"; }).join("") + "</ul>"
        );
      case "repair_vs_replacement":
        return insightBox(
          "Repair vs replacement",
          '<div class="table-wrap"><table><thead><tr><th>Option</th><th>Gross</th><th>Applied depreciation</th><th>Net payable</th></tr></thead><tbody>' +
            c.options
              .map(function (o) {
                return (
                  "<tr" + (o.code === c.recommended_option ? ' class="swb-row-active"' : "") + "><td>" + esc(o.label) +
                  (o.code === c.recommended_option ? ' <span class="badge badge-green">Lower cost</span>' : "") + "</td><td>" +
                  inr(o.gross_inr) + "</td><td>" + inr(o.applied_depreciation_inr) + "</td><td><strong>" + inr(o.net_payable_inr) + "</strong></td></tr>"
                );
              })
              .join("") +
            "</tbody></table></div>" +
            '<p class="swb-note">Repairing saves the insurer <strong>' + inr(c.insurer_saving_inr) +
            "</strong>. The surveyor must still certify that each panel is repairable; safety-critical parts are always replaced.</p>"
        );
      case "partial_approval":
        return insightBox(
          "Withheld lines and release",
          '<ul class="swb-list">' +
            c.withheld_lines
              .map(function (l) {
                return "<li><span><code>" + esc(l.part_code) + "</code> " + esc(l.description) + '</span><span class="swb-num">' + inr(l.amount_inr) + "</span></li>";
              })
              .join("") +
            "</ul>" +
            kv([
              ["Net payable now", inr(sc.net_payable)],
              ["Additional payable once evidence is accepted", inr(c.additional_payable_on_release_inr)],
              ["Net payable after release", inr(c.net_if_released_inr), true]
            ])
        );
      case "supplementary_estimate":
        return insightBox(
          "Supplementary estimate: only the increment is new money",
          kv([
            ["Initial settlement", inr(c.initial_net_inr)],
            ["Supplementary lines assessed", signedInr(c.supplementary_assessed_inr)],
            ["Revised settlement on cumulative estimate", inr(c.revised_net_inr)],
            ["Incremental payable", inr(c.incremental_payable_inr), true]
          ]) +
            '<p class="swb-note">Uplift is <strong>' + pct(c.variance_ratio) + "</strong> of the approved estimate against a re-inspection threshold of <strong>" +
            pct(c.variance_threshold) + "</strong>: " +
            (c.reinspection_required
              ? '<span class="badge badge-amber">Surveyor re-inspection required</span>'
              : '<span class="badge badge-green">No re-inspection needed</span>') +
            " The excess is applied once on the cumulative claim.</p>" +
            '<ul class="swb-list">' +
            c.lines.map(function (l) {
              return "<li><span><code>" + esc(l.part_code) + "</code> " + esc(l.description) + '</span><span class="swb-num">' + inr(l.amount_inr) + "</span></li>";
            }).join("") + "</ul>"
        );
      case "total_loss":
        return insightBox(
          "Agreed value vs market value",
          kv([
            ["Market value the customer expected", inr(c.market_value_inr)],
            ["IDV (agreed value, maximum payable)", inr(c.idv_inr)],
            ["Shortfall against market value", inr(c.shortfall_vs_market_inr)],
            ["Net payable on surrender", inr(c.surrender_net_inr), true]
          ])
        );
      case "constructive_total_loss":
        return insightBox(
          "Constructive total loss test",
          kv([
            ["Stress structural estimate", inr(c.stress_estimate_inr)],
            ["Net repair cost after depreciation", inr(c.net_repair_inr)],
            ["CTL threshold (75% of IDV)", inr(c.ctl_threshold_inr)],
            ["Constructive total loss triggered?", c.ctl_triggered ? "Yes" : "No", true]
          ]) +
            (c.ctl_triggered
              ? '<p class="swb-note">Owner keeps the wreck: payout <strong>' + inr(c.retention_net_inr) +
                "</strong>. If the owner surrenders the vehicle instead, payout would be <strong>" + inr(c.surrender_net_inr) + "</strong>.</p>"
              : '<p class="swb-note">At the current age and add-on settings the net repair cost stays below the threshold, so the repair settlement stands. Switch off Zero Depreciation or lower the vehicle age band to see the threshold change.</p>')
        );
      case "salvage_recovery":
        return insightBox(
          "Insurer view: surrender vs owner retention",
          '<div class="table-wrap"><table><thead><tr><th></th><th>Surrender basis</th><th>Owner retains wreck</th></tr></thead><tbody>' +
            "<tr><td>Customer payout</td><td>" + inr(c.surrender.customer_payout_inr) + "</td><td>" + inr(c.retention.customer_payout_inr) + "</td></tr>" +
            "<tr><td>Salvage proceeds</td><td>" + inr(c.surrender.salvage_proceeds_inr) + "</td><td>—</td></tr>" +
            "<tr><td>Disposal cost</td><td>" + signedInr("-" + c.surrender.disposal_cost_inr) + "</td><td>—</td></tr>" +
            "<tr><td>Net salvage recovery</td><td>" + inr(c.surrender.net_recovery_inr) + "</td><td>—</td></tr>" +
            "<tr class=\"swb-total\"><td>Insurer net claim cost</td><td>" + inr(c.surrender.insurer_net_cost_inr) + "</td><td>" + inr(c.retention.insurer_net_cost_inr) + "</td></tr>" +
            "</tbody></table></div>" +
            '<p class="swb-note">Owner retention is cheaper for the insurer by <strong>' + inr(c.retention_saving_for_insurer_inr) +
            "</strong> (no disposal cost). The salvage sale is approved by <strong>" + esc(c.salvage_sale_checker_label) + "</strong>.</p>"
        );
      case "zero_dep_addon":
      case "consumables_addon":
        return insightBox(
          sc.scenario_code === "zero_dep_addon" ? "What the Zero Depreciation add-on is worth" : "What the Consumables add-on is worth",
          '<div class="table-wrap"><table><thead><tr><th></th><th>Without add-on</th><th>With add-on</th></tr></thead><tbody>' +
            "<tr><td>Depreciation applied</td><td>" + inr(c.without_addon.applied_depreciation_inr) + "</td><td>" + inr(c.with_addon.applied_depreciation_inr) + "</td></tr>" +
            '<tr class="swb-total"><td>Net payable</td><td>' + inr(c.without_addon.net_payable_inr) + "</td><td>" + inr(c.with_addon.net_payable_inr) + "</td></tr>" +
            "</tbody></table></div>" +
            '<p class="swb-note">The add-on is worth <strong>' + inr(c.benefit_inr) + "</strong> on this claim. " +
            (c.active_on_policy
              ? '<span class="badge badge-green">Active on this policy</span>'
              : '<span class="badge badge-amber">Not on this policy (what-if)</span>') + "</p>"
        );
      case "different_deductibles":
        return insightBox("Net payable by compulsory excess and voluntary deductible", deductibleMatrix(c));
      case "underinsurance_idv":
        return insightBox(
          "IDV against market value",
          kv([
            ["IDV (cap on any payout)", inr(c.idv_cap_inr)],
            ["Market value of the vehicle", inr(c.market_value_inr)],
            ["IDV as a share of market value", pct(c.idv_ratio)],
            ["Shortfall if the car were a total loss", inr(c.shortfall_on_total_loss_inr)],
            ["Net payable with no pro-rata (synthetic wording default)", inr(c.net_without_pro_rata_inr)],
            ["Net payable if a pro-rata average applied", inr(c.net_with_pro_rata_inr), true]
          ]) +
            '<p class="swb-note">' + (c.underinsured
              ? "The vehicle is underinsured: a pro-rata condition would cut a partial loss by <strong>" + inr(c.pro_rata_reduction_inr) + "</strong>, and a total loss would pay only the IDV."
              : "IDV is at or above market value, so no pro-rata reduction arises.") +
            "</p>"
        );
      default:
        return "";
    }
  }

  function deductibleMatrix(c) {
    var head = c.voluntary_options_inr
      .map(function (v) {
        return "<th>" + (Number(v) === 0 ? "No voluntary" : "Voluntary " + inr(v)) + "</th>";
      })
      .join("");
    var rows = c.matrix
      .map(function (row) {
        var cells = row.cells
          .map(function (cell) {
            var current = Number(row.compulsory_inr) === Number(c.current_compulsory_inr) && Number(cell.voluntary_inr) === Number(c.current_voluntary_inr);
            return '<td class="' + (current ? "swb-cell-current" : "") + '">' + inr(cell.net_payable_inr) + "</td>";
          })
          .join("");
        return "<tr><td><strong>" + esc(row.vehicle_class.replace(/_/g, " ")) + "</strong><br/><small class=\"swb-muted\">compulsory " + inr(row.compulsory_inr) + "</small></td>" + cells + "</tr>";
      })
      .join("");
    return (
      '<div class="table-wrap"><table><thead><tr><th>Vehicle class</th>' + head + "</tr></thead><tbody>" + rows + "</tbody></table></div>" +
      '<p class="swb-note swb-muted">Highlighted cell = the excess currently entered. Excesses are deducted once per claim after depreciation; the premium discount for a higher voluntary deductible is not modelled.</p>'
    );
  }

  // ------------------------------------------------------------------ orchestration

  function render() {
    state.result = Engine.build(data, Engine.inputsFromMapping(data, readInputs()));
    renderLedger(state.result);
    renderSummary(state.result);
    renderTrace(state.result);
    renderCompare(state.result);
    renderPicker(state.result);
    renderDetail(state.result);
  }

  function select(code) {
    state.selected = code;
    if (!state.result) return;
    renderCompare(state.result);
    renderPicker(state.result);
    renderDetail(state.result);
    var detail = el("swb-detail");
    if (detail && detail.scrollIntoView) detail.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function bind() {
    ["swb-zd", "swb-cons", "swb-age", "swb-vol", "swb-comp", "swb-idv", "swb-mv", "swb-salvage"].forEach(function (id) {
      el(id).addEventListener("input", render);
      el(id).addEventListener("change", render);
    });
    el("swb-class").addEventListener("change", function () {
      if (this.value !== "") {
        el("swb-comp").value = Number(this.value);
        render();
      }
    });
    el("swb-reset").addEventListener("click", function () {
      fillControls();
      render();
    });
    function pick(evt) {
      var node = evt.target.closest("[data-code]");
      if (node) select(node.getAttribute("data-code"));
    }
    el("swb-compare-body").addEventListener("click", pick);
    el("swb-compare-body").addEventListener("keydown", function (evt) {
      if (evt.key === "Enter" || evt.key === " ") {
        evt.preventDefault();
        pick(evt);
      }
    });
    el("swb-picker").addEventListener("click", pick);
  }

  fillControls();
  bind();
  render();
  window.swbSelectScenario = select;
})();
