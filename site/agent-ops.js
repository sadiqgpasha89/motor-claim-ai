/* Claim 360 and Agent Command Center showcase.
 * Reads window.CLAIM360_DEMO, a generated capture of a live run of scripts/od_claim_demo.py (see claim360-data.js).
 * DEMO / SYNTHETIC data. Token counts are estimates; cost uses an illustrative rate card.
 */
(function () {
  "use strict";
  var D = window.CLAIM360_DEMO;
  var body = document.getElementById("aops-body");
  var tabsEl = document.getElementById("aops-tabs");
  var journeyEl = document.getElementById("aops-journey");
  if (!D || !body || !tabsEl) return;

  var C = D.claim_360, DASH = D.dashboard;
  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function list(items, empty) {
    if (!items || !items.length) return "<p class=\"section-sub\">" + esc(empty) + "</p>";
    return "<ul>" + items.map(function (i) { return "<li>" + esc(i) + "</li>"; }).join("") + "</ul>";
  }
  function badge(outcome) {
    var cls = outcome === "success" ? "badge-green" : (outcome === "failed" || outcome === "timeout") ? "badge-rose" : "badge-amber";
    return "<span class=\"badge " + cls + "\">" + esc(outcome) + "</span>";
  }
  function time(iso) { return String(iso || "").replace("T", " ").slice(0, 19); }
  function table(head, rows) {
    return "<div class=\"table-wrap\"><table><thead><tr>" + head.map(function (h) { return "<th>" + esc(h) + "</th>"; }).join("") +
      "</tr></thead><tbody>" + rows.join("") + "</tbody></table></div>";
  }
  function tr(cells) { return "<tr>" + cells.map(function (c) { return "<td>" + c + "</td>"; }).join("") + "</tr>"; }
  function kpi(label, value, sub) {
    return "<div class=\"card\"><div style=\"font-size:24px;font-weight:800;\">" + esc(value) + "</div><div><strong>" + esc(label) +
      "</strong></div><div class=\"section-sub\" style=\"margin:0;\">" + esc(sub) + "</div></div>";
  }

  journeyEl.innerHTML = D.journey.map(function (j, i) {
    return "<span class=\"state-pill-btn\" title=\"" + esc(j.note) + "\">" + (i + 1) + ". " + esc(j.step) + " &rarr; " + esc(j.claim_status) + "</span>";
  }).join("");

  var VIEWS = {
    "Claim 360": function () {
      var a = C.answers, o = C.overview;
      var blockers = C.blockers.length ? list(C.blockers.map(function (b) { return b.code + ": " + b.why + " (owner " + b.owner + ")"; }), "") : "<p class=\"section-sub\">Nothing is blocked.</p>";
      return "<h3>" + esc(o.claim_number) + " &middot; " + esc(o.canonical_state) + " &middot; risk " + esc(o.risk_tier) + " &middot; path " + esc(o.operational_path) + "</h3>" +
        "<div class=\"grid-2\">" +
        "<div><h4>What has happened?</h4>" + list(a.what_has_happened, "Nothing yet.") + "<h4>What is happening now?</h4><p>" + esc(a.what_is_happening_now) + "</p><h4>What is blocked, and why?</h4>" + blockers + "</div>" +
        "<div><h4>What did the AI do?</h4>" + list(a.what_did_ai_do, "No agent ran.") + "<h4>What did the AI find?</h4>" + list(a.what_did_ai_find, "No findings.") +
        "<h4>Next action</h4><p>" + esc(a.next_action) + "</p><p><strong>Do I need to act?</strong> " + (a.do_i_need_to_act.required ? "Yes" : "No") + " &mdash; " + esc(a.do_i_need_to_act.reason) + "</p></div></div>" +
        "<h4>Workflow DAG</h4>" + table(["#", "Agent", "Depends on", "Status", "Latency", "Confidence"], C.workflow.map(function (n) {
          return tr([n.order, esc(n.display_name), esc((n.depends_on || []).join(", ") || "-"), badge(n.last_outcome || n.status), n.last_latency_ms == null ? "-" : n.last_latency_ms + " ms", n.last_confidence == null ? "-" : n.last_confidence]);
        }));
    },
    "AI execution timeline": function () {
      return "<p class=\"section-sub\">" + C.agent_summary.executions + " executions &middot; " + C.agent_summary.total_tokens + " tokens (estimated) &middot; &#8377;" + esc(C.agent_summary.total_cost_inr) + " AI cost &middot; " + C.agent_summary.human_interventions + " human interventions</p>" +
        table(["Time (UTC)", "Kind", "Event", "Detail"], C.execution_timeline.map(function (t) {
          return tr([esc(time(t.at)), esc(String(t.kind).replace(/_/g, " ")), esc(t.title), esc(t.detail || "")]);
        }));
    },
    "Agent traces": function () {
      return table(["Agent", "Model / prompt", "Outcome", "Latency", "Retries", "Tokens", "Cost &#8377;", "Tools", "Final action", "Input ref"], C.agent_executions.map(function (t) {
        return tr([esc(t.agent_name) + " v" + esc(t.agent_version), esc(t.model_name) + "<br><small>prompt " + esc(t.prompt_version) + "</small>", badge(t.outcome), t.latency_ms + " ms", t.retry_count,
          t.token_usage.total, esc(t.cost_inr), esc((t.tool_calls || []).map(function (c) { return c.tool; }).join(", ") || "-"), esc(t.final_action), "<small>" + esc(t.task_input_ref.split("/").pop()) + "</small>"]);
      }));
    },
    "Evidence & settlement": function () {
      var E = C.evidence, S = C.settlement_and_approvals;
      return "<div class=\"grid-2\"><div><h4>Evidence &amp; documents</h4>" + table(["Type", "File", "Status", "sha256"], E.documents.map(function (d) {
        return tr([esc(d.doc_type), esc(d.filename), esc(d.status), "<small>" + esc(d.sha256.slice(0, 12)) + "&hellip;</small>"]);
      })) + "<h4>Extracted facts</h4>" + table(["Field", "Value", "Confidence", "Validation"], E.extracted_facts.map(function (f) {
        return tr([esc(f.field), esc(f.value), f.confidence, esc(f.validation_status)]);
      })) + "</div><div><h4>Settlement &amp; approvals</h4>" + table(["Gross &#8377;", "Depreciation", "Excess", "Net &#8377;", "Approval"], S.settlements.map(function (s) {
        return tr([esc(s.gross_assessed_inr), esc(s.depreciation_inr), esc(s.compulsory_excess_inr), esc(s.net_payable_inr), esc(s.approval_status)]);
      })) + table(["Approval", "Amount &#8377;", "Decision"], S.approvals.map(function (a) { return tr([esc(a.action_type), esc(a.amount_inr), esc(a.decision)]); })) +
        table(["Payment", "Amount &#8377;", "Status"], S.payments.map(function (p) { return tr([esc(p.payee_type), esc(p.amount_inr), esc(p.status)]); })) + "</div></div>";
    },
    "Agent Command Center": function () {
      var K = DASH.kpis, H = DASH.human_approval_backlog, M = DASH.model_api_outages, X = DASH.cost;
      function costRows(rows, key) { return rows.map(function (r) { return tr([esc(r[key]), r.executions, esc(r.cost_inr)]); }); }
      return "<div class=\"grid-2\" style=\"grid-template-columns:repeat(auto-fit,minmax(190px,1fr));\">" +
        kpi("Workflow success rate", K.workflow_success_rate_pct + "%", K.workflow_runs + " workflow runs") +
        kpi("Human escalation rate", K.human_escalation_rate_pct + "%", K.agent_executions + " agent executions") +
        kpi("Avg AI execution time", K.avg_ai_execution_time_ms + " ms", "per workflow run") +
        kpi("AI cost per claim", "₹" + K.ai_cost_per_claim_inr, K.total_tokens_estimated + " tokens (estimated)") + "</div>" +
        "<p class=\"section-sub\">Measured from this demo's trace store, not the illustrative targets in the brief.</p>" +
        "<div class=\"grid-2\"><div><h4>Operational queues</h4>" + table(["Queue", "Count"], [
          tr(["Failed agent executions", DASH.failed_agent_executions.length]), tr(["Stuck workflows", DASH.stuck_workflows.length]),
          tr(["Claims breaching SLA", DASH.claims_breaching_sla.length]), tr(["Pending human approvals", H.pending_approvals.length]),
          tr(["Open human tasks", H.open_human_tasks]), tr(["Fraud investigation queue (open alerts)", DASH.fraud_investigation_queue.open_alerts]),
          tr(["Payment reconciliation failures", DASH.payment_reconciliation_failures.length]),
          tr(["Model gateway outage active", M.model_gateway_outage_active ? "yes" : "no"]), tr(["Degraded adapters", M.degraded_adapters.length])]) + "</div>" +
        "<div><h4>Cost by agent</h4>" + table(["Agent", "Runs", "&#8377;"], costRows(X.by_agent, "agent_name")) +
        "<h4>Cost by claim complexity</h4>" + table(["Complexity", "Runs", "&#8377;"], costRows(X.by_claim_complexity, "complexity")) +
        "<h4>Cost by claim</h4>" + table(["Claim", "Runs", "&#8377;"], costRows(X.by_claim, "claim_number")) + "</div></div>";
    }
  };

  var names = Object.keys(VIEWS), active = names[0];
  function render() {
    tabsEl.innerHTML = names.map(function (n) {
      return "<button type=\"button\" role=\"tab\" class=\"tab-btn" + (n === active ? " active" : "") + "\" aria-selected=\"" + (n === active) + "\" data-aops=\"" + esc(n) + "\">" + esc(n) + "</button>";
    }).join("");
    body.innerHTML = VIEWS[active]();
  }
  tabsEl.addEventListener("click", function (e) {
    var n = e.target && e.target.getAttribute && e.target.getAttribute("data-aops");
    if (n && VIEWS[n]) { active = n; render(); }
  });
  render();
})();
