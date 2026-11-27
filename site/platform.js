/* Phase 3 platform and security showcase. Reads window.PLATFORM_DEMO (generated, see platform-data.js).
 * DEMO / SYNTHETIC data. Every row is a real response from the API.
 */
(function () {
  "use strict";
  var D = window.PLATFORM_DEMO;
  var tabsEl = document.getElementById("plat-tabs");
  var body = document.getElementById("plat-body");
  if (!D || !tabsEl || !body) return;

  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function table(head, rows) {
    return "<div class=\"table-wrap\"><table><thead><tr>" + head.map(function (h) { return "<th>" + esc(h) + "</th>"; }).join("") +
      "</tr></thead><tbody>" + rows.map(function (r) { return "<tr>" + r.map(function (c) { return "<td>" + esc(c) + "</td>"; }).join("") + "</tr>"; }).join("") + "</tbody></table></div>";
  }
  function msg(call) { var b = call.body || {}; return b.message || (b.status ? b.status : ""); }

  var VIEWS = {
    "Tool gateway": function () {
      var t = D.tool_calls;
      var rows = [
        ["Transient outage, then success", t.retry_then_success.http_status, "attempts " + t.retry_then_success.body.attempts],
        ["Same idempotency key again", t.idempotent_replay.http_status, "replayed " + t.idempotent_replay.body.replayed + ", no second booking"],
        ["Agent not allowed the tool", t.denied_agent.http_status, msg(t.denied_agent)],
        ["Payment as a gateway tool", t.denied_payment_tool.http_status, msg(t.denied_payment_tool)],
        ["Surveyor system down, call 1", t.outage_then_fast_fail[0].http_status, msg(t.outage_then_fast_fail[0])],
        ["Surveyor system down, call 2", t.outage_then_fast_fail[1].http_status, msg(t.outage_then_fast_fail[1])]
      ];
      var p = D.tool_policy.tool_policy;
      return "<p class=\"section-sub\">Checks on every call: " + esc(D.tool_policy.checks.join(", ")) + ".</p>" +
        table(["Scenario", "HTTP", "Result"], rows) +
        "<h4>Tool policy</h4>" + table(["Tool", "System", "Agents", "Roles", "Approval"], Object.keys(p).map(function (k) {
          return [k, p[k].port, p[k].allowed_agents.join(", ") || "none", p[k].allowed_roles.join(", "), p[k].route_only ? "API route only" : (p[k].approval_required ? "required" : "no")];
        }));
    },
    "Circuits": function () {
      var c = D.circuit_breakers;
      return "<p class=\"section-sub\">A dependency that keeps failing opens its circuit. Calls then fail fast instead of piling up.</p>" +
        table(["Dependency", "State", "Consecutive failures"], c.circuit_breakers.map(function (b) { return [b.name, b.state, b.consecutive_failures]; })) +
        "<p class=\"section-sub\">Tool calls by status: " + esc(JSON.stringify(c.tool_invocations)) + ".</p>";
    },
    "Event bus": function () {
      var e = D.event_bus;
      return "<p class=\"section-sub\">The claims ledger consumer failed on purpose. Each pass retries with backoff. After the last attempt the delivery is dead, an operator replays it, and the next dispatch delivers it.</p>" +
        table(["Pass", "Delivered", "Failed", "Dead", "Skipped"], e.failing_consumer_passes.map(function (p, i) { return [i + 1, p.delivered, p.failed, p.dead, p.skipped]; })) +
        "<p>Dead deliveries: " + esc(JSON.stringify(e.dead_deliveries)) + ". Replay status: <strong>" + esc(e.replayed.status) + "</strong>. After recovery, delivered: " + esc(e.after_recovery.delivered) + ".</p>";
    },
    "Audit & PII": function () {
      var a = D.audit_integrity, l = D.llm_gateway;
      return "<p>Audit hash chain: <strong>" + (a.ok ? "verified" : "BROKEN") + "</strong>. " + esc(a.checked) + " events checked. Head " + esc(String(a.head_hash).slice(0, 16)) + "&hellip;</p>" +
        "<p class=\"section-sub\">Any change to an event, or to an earlier one, breaks the chain from that point.</p>" +
        "<p>LLM gateway: " + esc(l.pii_tokens_redacted) + " personal data values were replaced by tokens before the model call. Model: " + esc(l.model) +
        ". Tokens are estimates: " + esc(l.usage.tokens_input) + " in, " + esc(l.usage.tokens_output) + " out.</p><p class=\"section-sub\">Output sent back: " + esc(l.text) + "</p>";
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
