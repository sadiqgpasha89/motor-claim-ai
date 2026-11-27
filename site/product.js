/* Phase 5 product showcase. Reads window.PRODUCT_DEMO (generated, see product-data.js).
 * DEMO / SYNTHETIC data. Every figure is a real response from the portal API. Targets are illustrative.
 */
(function () {
  "use strict";
  var D = window.PRODUCT_DEMO;
  var tabsEl = document.getElementById("prod-tabs");
  var body = document.getElementById("prod-body");
  if (!D || !tabsEl || !body) return;

  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function table(head, rows) {
    return "<div class=\"table-wrap\"><table><thead><tr>" + head.map(function (h) { return "<th>" + esc(h) + "</th>"; }).join("") +
      "</tr></thead><tbody>" + rows.map(function (r) { return "<tr>" + r.map(function (c) { return "<td>" + esc(c) + "</td>"; }).join("") + "</tr>"; }).join("") + "</tbody></table></div>";
  }
  var QUESTIONS = [
    ["what_has_happened", "What has happened?"], ["what_is_happening_now", "What is happening right now?"], ["what_is_blocked", "What is blocked?"],
    ["why_blocked", "Why is it blocked?"], ["what_did_ai_do", "What did the AI do?"], ["what_did_ai_find", "What did the AI find?"],
    ["next_action", "What is the next action?"], ["do_i_need_to_act", "Do I need to do anything?"]
  ];
  function flat(v) {
    if (Array.isArray(v)) return v.length ? v.join("; ") : "Nothing";
    if (v && typeof v === "object") return (v.required ? "Yes. " : "No. ") + (v.reason || "");
    return v || "Nothing";
  }

  var VIEWS = {
    "Portal": function () {
      var s = D.capability_model.portal_sections, e = D.executive_dashboard;
      return "<p class=\"section-sub\">Nine sections plus Claim 360. The numbers below come from the Executive Dashboard API on seeded demo data.</p>" +
        table(["Section", "What it shows"], s.map(function (x) { return [x.name, x.description]; })) +
        "<p class=\"section-sub\">Executive Dashboard now: " + esc(e.claims_total) + " claims, " + esc(e.fraud_alerts_open) + " open fraud alerts, " + esc(e.human_tasks_open) + " open human tasks. Status mix: " + esc(JSON.stringify(e.by_status)) + ".</p>";
    },
    "Claim 360": function () {
      var rows = QUESTIONS.map(function (q) {
        return [q[1]].concat(D.demos.demos.map(function (d) { var a = D.demo_claim_360_answers[d.id]; return a ? flat(a[q[0]]) : "Claim not seeded"; }));
      });
      return "<p class=\"section-sub\">One screen answers eight questions. Each column is a live Claim 360 answer for a demo claim. Seeded claims have no agent run yet, so \"What did the AI do?\" fills in after an orchestration run.</p>" +
        table(["Question"].concat(D.demos.demos.map(function (d) { return d.claim_number; })), rows);
    },
    "KPIs": function () {
      var k = D.kpi_framework;
      return "<p class=\"section-sub\">" + esc(k.measured_count) + " of " + esc(k.total_count) + " KPIs are measured from the demo database. A KPI with no data source is shown as not measured. " + esc(k.targets_note) + "</p>" +
        table(["KPI", "Measured", "Unit", "Traditional (illustr.)", "Agentic target (illustr.)", "Basis"], k.kpis.map(function (x) {
          return [x.name, x.value == null ? "Not measured" : x.value, x.unit, x.traditional_illustrative == null ? "" : x.traditional_illustrative, x.agentic_target_illustrative == null ? "" : x.agentic_target_illustrative, x.basis];
        })) + "<h4>Outcome targets (illustrative)</h4>" + table(["Outcome", "Target reduction %"], k.outcome_targets.map(function (o) { return [o.name, o.target_pct]; }));
    },
    "Before and after": function () {
      return "<p class=\"section-sub\">Traditional handling against the agentic target, and what exists in this repository.</p>" +
        table(["Process", "Traditional", "Agentic target", "State", "Built as"], D.kpi_framework.before_after.map(function (r) { return [r.process, r.traditional, r.agentic_target, r.state, r.built_as]; }));
    },
    "Guided demos": function () {
      return "<p class=\"section-sub\">Five curated claims. They show more than the happy path.</p>" + D.demos.demos.map(function (d, i) {
        return "<h4>Demo " + (i + 1) + ". " + esc(d.title) + " <small>(" + esc(d.tag) + ", " + esc(d.claim_number) + ")</small></h4><p>" + esc(d.summary) + "</p><ol>" +
          d.steps.map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("") + "</ol>";
      }).join("") + "<p class=\"section-sub\">" + esc(D.demos.note) + "</p>";
    },
    "Capability model": function () {
      var c = D.capability_model;
      return "<p class=\"section-sub\">" + esc(c.vision) + " " + esc(c.note) + "</p>" +
        table(["Capability", "Target state", "State", "Evidence"], c.capability_model.map(function (x) { return [x.capability, x.target_state, x.state, x.evidence]; }));
    },
    "Honest assessment": function () {
      return "<p class=\"section-sub\">The next investment is a visible, complete claims journey with measured outcomes, not more diagrams or agents.</p>" +
        table(["Area", "Rating", "Basis"], D.capability_model.assessment.map(function (x) { return [x.area, x.rating, x.basis]; }));
    }
  };

  var names = Object.keys(VIEWS);
  function show(name) {
    body.innerHTML = VIEWS[name]();
    Array.prototype.forEach.call(tabsEl.children, function (b) { b.setAttribute("aria-selected", String(b.textContent === name)); b.classList.toggle("active", b.textContent === name); });
  }
  tabsEl.innerHTML = "";
  names.forEach(function (n) {
    var b = document.createElement("button");
    b.type = "button"; b.setAttribute("role", "tab"); b.className = "tab-btn"; b.textContent = n;
    b.addEventListener("click", function () { show(n); });
    tabsEl.appendChild(b);
  });
  show(names[0]);
})();
