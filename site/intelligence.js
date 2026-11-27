/* Phase 2 claim intelligence showcase. Reads window.INTELLIGENCE_DEMO (generated, see intelligence-data.js).
 * DEMO / SYNTHETIC data. Thresholds are illustrative. All results are advisory.
 */
(function () {
  "use strict";
  var D = window.INTELLIGENCE_DEMO;
  var tabsEl = document.getElementById("intel-tabs");
  var body = document.getElementById("intel-body");
  if (!D || !tabsEl || !body) return;

  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function table(head, rows) {
    return "<div class=\"table-wrap\"><table><thead><tr>" + head.map(function (h) { return "<th>" + esc(h) + "</th>"; }).join("") +
      "</tr></thead><tbody>" + rows.map(function (r) { return "<tr>" + r.map(function (c) { return "<td>" + esc(c) + "</td>"; }).join("") + "</tr>"; }).join("") + "</tbody></table></div>";
  }
  function list(items) { return "<ul>" + items.map(function (i) { return "<li>" + esc(i) + "</li>"; }).join("") + "</ul>"; }

  var VIEWS = {
    "Repair vs replace": function () {
      var r = D.repair_replace;
      return "<p class=\"section-sub\">Safety critical and EV battery parts are never decided from photos. Total repair cost INR " + esc(r.claim_repair_total_inr) + ".</p>" +
        table(["Part", "Category", "Decision", "Repair INR", "Replace INR", "Human review"], r.components.map(function (c) {
          return [c.part_code, c.category, c.decision, c.repair_cost_inr, c.replace_cost_inr, c.human_review_required ? "yes" : "no"];
        }));
    },
    "Estimate benchmark": function () {
      var b = D.benchmark;
      return "<p class=\"section-sub\">" + esc(b.disclaimer) + " Labour tier: " + esc(b.city_tier) + ".</p>" +
        table(["Part", "Type", "Claimed INR", "Band low", "Band high", "Flags"], b.lines.map(function (l) {
          return [l.part_code, l.line_type, l.claimed_inr, l.band_low_inr, l.band_high_inr, l.flags.join(" ") || "none"];
        }));
    },
    "Multimodal fusion": function () {
      var f = D.fusion;
      return "<p>Fused confidence <strong>" + esc(f.fused_confidence) + "</strong>. Agreed zones: " + esc(f.agreed_zones.join(", ") || "none") +
        ". Human review: " + (f.human_review_required ? "required" : "not required") + ".</p>" +
        table(["Source", "Zones reported"], Object.keys(f.zones_by_modality).map(function (k) { return [k, f.zones_by_modality[k].join(", ") || "no data"]; })) +
        (f.contradictions.length ? list(f.contradictions.map(function (c) { return c.message; })) : "<p class=\"section-sub\">No contradictions.</p>");
    },
    "Supplementary estimate": function () {
      var s = D.supplementary;
      return "<p>Base INR " + esc(s.base_total_inr) + ", supplements INR " + esc(s.supplement_total_inr) + ", cumulative INR " + esc(s.cumulative_gross_inr) +
        ". Cumulative variance " + esc(s.cumulative_variance) + " against the limit " + esc(s.variance_threshold) + ". Re-inspection: <strong>" +
        (s.reinspection_required ? "required" : "not required") + "</strong>.</p>" + list(s.reasons);
    },
    "Predicted complexity": function () {
      var c = D.complexity, b = D.complexity_backtest;
      return "<p>Band <strong>" + esc(c.band) + "</strong> (score " + esc(c.score) + "). About " + esc(c.expected_handling_hours) + " hours, " +
        esc(c.expected_human_touchpoints) + " human touchpoints. Skill: " + esc(c.recommended_skill) + ".</p>" +
        table(["Driver", "Points", "Why"], c.drivers.map(function (d) { return [d.driver, d.points, d.why]; })) +
        "<p class=\"section-sub\">" + esc(c.disclaimer) + " Backtest on " + esc(b.claims_scored) + " claims: " + esc(JSON.stringify(b.distribution)) + ".</p>";
    },
    "Fraud network": function () {
      var g = D.fraud_network;
      return "<p>" + esc(g.component_size) + " linked claims. Network score <strong>" + esc(g.network_score) + "</strong>. Ring suspected: " + (g.ring_suspected ? "yes" : "no") +
        ". SIU lead recommended: " + (g.siu_case_recommended ? "yes" : "no") + ". The claim is never auto-rejected.</p>" +
        table(["From", "To", "Weight", "Reasons"], g.edges.map(function (e) {
          return [e.from, e.to, e.weight, e.reasons.map(function (r) { return r.link_type; }).join(", ")];
        })) + list(g.explanation);
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
