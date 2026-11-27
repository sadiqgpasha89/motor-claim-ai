(function () {
  "use strict";

  var DATA = window.MOTORCLAIM_WORKFLOW_DATA;
  var state = {
    scenarioId: "orch-engine",
    stepIdx: 0,
    playTimer: null,
    selectedOrchState: "VALIDATION"
  };

  function el(id) {
    return document.getElementById(id);
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function statusBadgeClass(kind) {
    if (kind === "green") return "badge-green";
    if (kind === "amber") return "badge-amber";
    if (kind === "rose") return "badge-rose";
    if (kind === "purple") return "badge-purple";
    if (kind === "slate") return "badge-slate";
    return "badge-blue";
  }

  function renderScenarioBar() {
    var container = el("scenario-bar");
    if (!container) return;
    var html = Object.keys(DATA.scenarios)
      .map(function (key) {
        var sc = DATA.scenarios[key];
        var active = key === state.scenarioId ? " active" : "";
        return (
          '<button type="button" class="scenario-btn' +
          active +
          '" data-scenario="' +
          escapeHtml(sc.id) +
          '">' +
          '<div class="sc-id">' +
          escapeHtml(sc.claimNumber) +
          "</div>" +
          '<div class="sc-title">' +
          escapeHtml(sc.title) +
          "</div>" +
          '<span class="sc-tag">' +
          escapeHtml(sc.tag) +
          "</span>" +
          "</button>"
        );
      })
      .join("");
    container.innerHTML = html;

    container.querySelectorAll(".scenario-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        selectScenario(btn.getAttribute("data-scenario"));
      });
    });
  }

  function renderScenarioSummary(sc) {
    var box = el("scenario-summary");
    if (!box) return;
    box.innerHTML =
      '<div class="scenario-meta">' +
      "<strong>" +
      escapeHtml(sc.claimNumber) +
      "</strong> · " +
      escapeHtml(sc.vehicle) +
      " · <span>" +
      escapeHtml(sc.policy) +
      "</span>" +
      '<div style="margin-top:4px; color:#475569; font-size:12.5px;">' +
      escapeHtml(sc.summary) +
      "</div>" +
      '<div style="margin-top:6px; display:flex; flex-wrap:wrap; gap:8px;">' +
      '<span class="badge badge-blue">Claimed: ' +
      escapeHtml(sc.claimedAmount) +
      "</span>" +
      '<span class="badge badge-green">Outcome: ' +
      escapeHtml(sc.outcomeAmount) +
      "</span>" +
      '<span class="badge badge-slate">' +
      escapeHtml(sc.automationSplit) +
      "</span>" +
      "</div>" +
      "</div>";
  }

  function renderOperationsRibbon(sc, activeStep) {
    var container = el("ops-ribbon");
    if (!container) return;

    var html = DATA.operations
      .map(function (op) {
        var matchingSteps = sc.steps.filter(function (s) {
          return s.opKey === op.key;
        });
        var isActive = activeStep && activeStep.opKey === op.key;

        var statusLabel = "Not reached";
        var statusColor = "#64748b";
        if (matchingSteps.length > 0) {
          var hasRose = matchingSteps.some(function (s) {
            return s.statusKind === "rose";
          });
          var hasAmber = matchingSteps.some(function (s) {
            return s.statusKind === "amber";
          });
          var hasSlate = matchingSteps.every(function (s) {
            return s.statusKind === "slate";
          });
          if (hasRose) {
            statusLabel = "Exception / Guard";
            statusColor = "#be123c";
          } else if (hasAmber) {
            statusLabel = "Human Gate";
            statusColor = "#b45309";
          } else if (hasSlate) {
            statusLabel = "Queued / Gated";
            statusColor = "#64748b";
          } else {
            statusLabel = "Autonomous OK";
            statusColor = "#047857";
          }
        }

        return (
          '<button type="button" class="op-card' +
          (isActive ? " active" : "") +
          '" data-op="' +
          escapeHtml(op.key) +
          '">' +
          '<div class="op-num">0' +
          op.index +
          " · " +
          escapeHtml(op.agentLabel) +
          "</div>" +
          '<div class="op-name">' +
          escapeHtml(op.title) +
          "</div>" +
          '<div class="op-status-line" style="color:' +
          statusColor +
          ';">' +
          escapeHtml(statusLabel) +
          "</div>" +
          "</button>"
        );
      })
      .join("");
    container.innerHTML = html;

    container.querySelectorAll(".op-card").forEach(function (card) {
      card.addEventListener("click", function () {
        var opKey = card.getAttribute("data-op");
        var idx = sc.steps.findIndex(function (s) {
          return s.opKey === opKey;
        });
        if (idx >= 0) {
          stopPlayback();
          state.stepIdx = idx;
          renderActiveWorkflow();
        }
      });
    });
  }

  function renderChainNodes(sc) {
    var container = el("chain-nodes");
    if (!container) return;

    var html = sc.steps
      .map(function (step, idx) {
        var classes = ["chain-node"];
        if (step.actorType === "human") classes.push("human-gate");
        if (step.actorType === "fallback") classes.push("fallback-gate");
        if (step.statusKind === "slate") classes.push("blocked-step");
        if (idx === state.stepIdx) classes.push("selected");

        var actorChip =
          step.actorType === "human"
            ? "HUMAN GATE"
            : step.actorType === "fallback"
            ? "FALLBACK / GUARD"
            : step.actorType === "deterministic_service"
            ? "DETERMINISTIC"
            : "AI AGENT";

        return (
          '<button type="button" class="' +
          classes.join(" ") +
          '" data-step-idx="' +
          idx +
          '">' +
          '<div class="cn-top"><span>' +
          escapeHtml(step.stepCode) +
          " · " +
          escapeHtml(step.opKey) +
          "</span><span>" +
          actorChip +
          "</span></div>" +
          '<div class="cn-title">' +
          escapeHtml(step.nodeTitle) +
          "</div>" +
          '<div class="cn-sub">' +
          escapeHtml(step.executionStatus) +
          "</div>" +
          "</button>"
        );
      })
      .join("");

    container.innerHTML = html;
    container.querySelectorAll(".chain-node").forEach(function (btn) {
      btn.addEventListener("click", function () {
        stopPlayback();
        state.stepIdx = parseInt(btn.getAttribute("data-step-idx"), 10);
        renderActiveWorkflow();
      });
    });
  }

  function renderInspector(sc, step) {
    var container = el("stage-inspector");
    if (!container || !step) return;

    var confPct = Math.round((step.confidence || 0) * 100);
    var fillClass = step.confidence >= 0.85 ? "" : step.confidence >= 0.65 ? " medium" : " low";

    var evidenceHtml = step.evidence
      .map(function (e) {
        return "<li>" + escapeHtml(e) + "</li>";
      })
      .join("");

    var dataHtml = step.dataRetrieved
      .map(function (d) {
        return "<li>" + escapeHtml(d) + "</li>";
      })
      .join("");

    var toolsHtml = step.toolsInvoked
      .map(function (t) {
        return '<span class="chip chip-tool">' + escapeHtml(t) + "</span>";
      })
      .join("");

    var rulesHtml = step.businessRules
      .map(function (r) {
        return '<span class="chip chip-rule">' + escapeHtml(r) + "</span>";
      })
      .join("");

    var humanBadge = step.humanReviewRequired
      ? '<span class="badge badge-amber">Human Review Required</span>'
      : '<span class="badge badge-green">No Human Touch Needed</span>';

    var actionsList = step.actionsExecuted || [
      {
        actionType: step.toolsInvoked && step.toolsInvoked[0] ? step.toolsInvoked[0] : "publish_result",
        status: step.humanReviewRequired ? "gated_human_review" : "executed",
        summary: step.agentOutput
      }
    ];
    var actionsHtml = actionsList
      .map(function (a) {
        return (
          '<div class="action-exec-item">' +
          '<span class="chip chip-tool">' +
          escapeHtml(a.actionType) +
          "</span>" +
          '<span class="badge ' +
          (a.status === "executed" ? "badge-green" : a.status === "blocked_policy" ? "badge-rose" : "badge-amber") +
          '">' +
          escapeHtml(a.status) +
          "</span>" +
          "<span>" +
          escapeHtml(a.summary) +
          "</span>" +
          "</div>"
        );
      })
      .join("");

    var dec = step.decision || {
      decisionId: "dec-" + sc.id + "-" + step.stepCode,
      routingOutcome: step.nextAction ? step.nextAction.split("->")[0].trim() : step.executionStatus,
      reasonCodes: ["RC_" + step.opKey.toUpperCase() + "_EVALUATED"],
      policyRuleRefs: step.businessRules || [],
      explanation: step.agentOutput
    };
    var decReasonHtml = (dec.reasonCodes || [])
      .map(function (rc) {
        return '<span class="chip chip-rule">' + escapeHtml(rc) + "</span>";
      })
      .join("");
    var depsText =
      step.dependsOn && step.dependsOn.length > 0
        ? "Upstream deps satisfied: " + step.dependsOn.join(", ")
        : "Entry stage or workflow trigger";

    container.innerHTML =
      '<div class="inspector-grid">' +
      '<div class="inspector-panel">' +
      '<div class="inspector-header">' +
      "<div>" +
      '<div class="inspector-kicker">Operation ' +
      escapeHtml(step.opKey) +
      " · Step " +
      escapeHtml(step.stepCode) +
      " of " +
      sc.steps.length +
      "</div>" +
      '<h3 class="inspector-title">' +
      escapeHtml(step.nodeTitle) +
      "</h3>" +
      '<div style="font-size:12.5px; color:#475569;"><code>' +
      escapeHtml(step.codeRef) +
      "</code></div>" +
      "</div>" +
      '<div style="display:flex; flex-direction:column; align-items:flex-end; gap:6px;">' +
      '<span class="badge ' +
      statusBadgeClass(step.statusKind) +
      '">' +
      escapeHtml(step.executionStatus) +
      "</span>" +
      humanBadge +
      "</div>" +
      "</div>" +
      '<div class="kv-list">' +
      '<div class="kv-block">' +
      '<div class="kv-label">Why This Wakes Up (Dependency &amp; Trigger)</div>' +
      '<div class="kv-value">' +
      escapeHtml(step.wakeTrigger) +
      '<div style="font-size:11.5px; color:#475569; margin-top:4px;">' +
      escapeHtml(depsText) +
      "</div>" +
      "</div>" +
      "</div>" +
      '<div class="kv-block">' +
      '<div class="kv-label">Agent / Service Output</div>' +
      '<div class="kv-value"><strong>' +
      escapeHtml(step.agentOutput) +
      "</strong></div>" +
      "</div>" +
      '<div class="kv-block">' +
      '<div class="kv-label">Controlled Actions Executed</div>' +
      '<div class="action-exec-list">' +
      actionsHtml +
      "</div>" +
      "</div>" +
      '<div class="kv-block">' +
      '<div class="kv-label">Evidence Captured &amp; Cited</div>' +
      '<ul style="margin:4px 0 0; padding-left:18px; font-size:12.5px;">' +
      evidenceHtml +
      "</ul>" +
      "</div>" +
      '<div class="kv-block">' +
      '<div class="kv-label">Allowed Decisions &amp; Hard Safety Boundary</div>' +
      '<div class="kv-value">' +
      escapeHtml(step.allowedDecisions) +
      "</div>" +
      "</div>" +
      "</div>" +
      "</div>" +
      '<div class="inspector-panel">' +
      '<div class="kv-list">' +
      '<div class="decision-box">' +
      '<div class="kv-label">Decision Intelligence Trace (' +
      escapeHtml(dec.decisionId) +
      ")</div>" +
      '<div class="kv-value"><strong>Routing Outcome:</strong> <code>' +
      escapeHtml(dec.routingOutcome) +
      "</code></div>" +
      '<div class="kv-value" style="margin-top:4px;">' +
      escapeHtml(dec.explanation) +
      "</div>" +
      '<div class="chip-row" style="margin-top:6px;">' +
      decReasonHtml +
      "</div>" +
      "</div>" +
      '<div class="kv-block">' +
      '<div class="kv-label">Confidence Level</div>' +
      '<div class="kv-value" style="display:flex; justify-content:space-between; font-weight:700;">' +
      "<span>" +
      confPct +
      "% (" +
      escapeHtml(step.confidence.toFixed(2)) +
      ")</span>" +
      "<span>" +
      escapeHtml(step.confidenceBand) +
      "</span>" +
      "</div>" +
      '<div class="conf-meter-wrap"><div class="conf-bar"><div class="conf-fill' +
      fillClass +
      '" style="width:' +
      confPct +
      '%;"></div></div></div>' +
      "</div>" +
      '<div class="kv-block">' +
      '<div class="kv-label">Tools Invoked (Allowlisted)</div>' +
      '<div class="chip-row">' +
      toolsHtml +
      "</div>" +
      "</div>" +
      '<div class="kv-block">' +
      '<div class="kv-label">Data Retrieved</div>' +
      '<ul style="margin:4px 0 0; padding-left:18px; font-size:12.5px;">' +
      dataHtml +
      "</ul>" +
      "</div>" +
      '<div class="kv-block">' +
      '<div class="kv-label">Business Rules Applied</div>' +
      '<div class="chip-row">' +
      rulesHtml +
      "</div>" +
      "</div>" +
      '<div class="kv-block">' +
      '<div class="kv-label">What Happens If This Step Fails / Flags Anomaly</div>' +
      '<div class="kv-value">' +
      escapeHtml(step.failureBehavior) +
      "</div>" +
      "</div>" +
      '<div class="next-action-box">' +
      '<div class="kv-label">Next Action &amp; Downstream Handoff</div>' +
      "<div><code>" +
      escapeHtml(step.nextAction) +
      "</code></div>" +
      "</div>" +
      "</div>" +
      "</div>" +
      "</div>";

    var counter = el("step-counter");
    if (counter) {
      counter.textContent = "Step " + (state.stepIdx + 1) + " / " + sc.steps.length;
    }

    var prevBtn = el("btn-prev-step");
    var nextBtn = el("btn-next-step");
    if (prevBtn) prevBtn.disabled = state.stepIdx <= 0;
    if (nextBtn) nextBtn.disabled = state.stepIdx >= sc.steps.length - 1;
  }

  function renderActiveWorkflow() {
    var sc = DATA.scenarios[state.scenarioId];
    if (!sc) return;
    if (state.stepIdx >= sc.steps.length) state.stepIdx = 0;
    var activeStep = sc.steps[state.stepIdx];

    renderScenarioBar();
    renderScenarioSummary(sc);
    renderOperationsRibbon(sc, activeStep);
    renderChainNodes(sc);
    renderInspector(sc, activeStep);
  }

  function selectScenario(id) {
    if (!DATA.scenarios[id]) return;
    stopPlayback();
    state.scenarioId = id;
    state.stepIdx = 0;
    renderActiveWorkflow();
  }

  function stopPlayback() {
    if (state.playTimer) {
      clearInterval(state.playTimer);
      state.playTimer = null;
    }
    var playBtn = el("btn-play-walkthrough");
    if (playBtn) {
      playBtn.textContent = "Play Walkthrough";
    }
  }

  function togglePlayback() {
    var sc = DATA.scenarios[state.scenarioId];
    if (!sc) return;
    if (state.playTimer) {
      stopPlayback();
      return;
    }
    var playBtn = el("btn-play-walkthrough");
    if (playBtn) {
      playBtn.textContent = "Pause Walkthrough";
    }
    if (state.stepIdx >= sc.steps.length - 1) {
      state.stepIdx = 0;
      renderActiveWorkflow();
    }
    state.playTimer = setInterval(function () {
      var current = DATA.scenarios[state.scenarioId];
      if (state.stepIdx < current.steps.length - 1) {
        state.stepIdx += 1;
        renderActiveWorkflow();
      } else {
        stopPlayback();
      }
    }, 2200);
  }

  function renderQuestions() {
    var grid = el("questions-grid");
    if (!grid) return;
    grid.innerHTML = DATA.questions
      .map(function (item) {
        return (
          '<article class="qa-card">' +
          '<div class="qa-q">' +
          escapeHtml(item.q) +
          "</div>" +
          '<p class="qa-a">' +
          escapeHtml(item.a) +
          "</p>" +
          "</article>"
        );
      })
      .join("");
  }

  function fmtInr(n) {
    return (
      "₹" +
      n.toLocaleString("en-IN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      })
    );
  }

  var selectedAgentName = "fnol_concierge";

  function renderCapabilityMatrix() {
    var body = el("capabilities-matrix-body");
    var inspector = el("agent-contract-inspector");
    if (!body || !DATA.capabilitiesMatrix) return;

    body.innerHTML = DATA.capabilitiesMatrix
      .map(function (ag) {
        var active = ag.agentName === selectedAgentName ? " active" : "";
        var actionsHtml = (ag.authorisedActions || [])
          .map(function (a) {
            return '<span class="chip chip-tool">' + escapeHtml(a) + "</span>";
          })
          .join(" ");
        return (
          '<tr class="cap-row-btn' +
          active +
          '" data-agent="' +
          escapeHtml(ag.agentName) +
          '">' +
          "<td><strong>" +
          escapeHtml(ag.displayName) +
          "</strong><br/><code>" +
          escapeHtml(ag.agentName) +
          '</code><br/><small style="color:#475569;">' +
          escapeHtml(ag.stage) +
          "</small></td>" +
          "<td>" +
          escapeHtml(ag.enhancement) +
          "</td>" +
          "<td>" +
          escapeHtml(ag.responsibility) +
          "</td>" +
          '<td><div class="chip-row">' +
          actionsHtml +
          "</div></td>" +
          "<td><small><strong>Deps:</strong> " +
          escapeHtml((ag.dependsOn || []).join(", ") || "Entry") +
          "<br/><strong>Rework:</strong> " +
          escapeHtml((ag.reworkTargets || []).join(", ") || "None") +
          "</small></td>" +
          "</tr>"
        );
      })
      .join("");

    body.querySelectorAll(".cap-row-btn").forEach(function (row) {
      row.addEventListener("click", function () {
        selectedAgentName = row.getAttribute("data-agent");
        renderCapabilityMatrix();
      });
    });

    if (inspector) {
      var cur =
        DATA.capabilitiesMatrix.find(function (a) {
          return a.agentName === selectedAgentName;
        }) || DATA.capabilitiesMatrix[0];
      if (cur) {
        inspector.innerHTML =
          '<div style="display:flex; flex-wrap:wrap; justify-content:space-between; gap:8px; margin-bottom:10px;">' +
          "<div><span class=\"badge badge-blue\">" +
          escapeHtml(cur.stage) +
          "</span> <strong style=\"font-size:16px;\">" +
          escapeHtml(cur.displayName) +
          "</strong> (<code>" +
          escapeHtml(cur.agentName) +
          "</code>)</div>" +
          '<span class="badge badge-amber">' +
          escapeHtml(cur.humanGate) +
          "</span>" +
          "</div>" +
          '<div class="grid-2">' +
          '<div class="kv-block"><div class="kv-label">Input Contract</div><div class="kv-value"><code>' +
          escapeHtml(cur.inputContract) +
          "</code></div></div>" +
          '<div class="kv-block"><div class="kv-label">Published Output Contract</div><div class="kv-value"><code>' +
          escapeHtml(cur.outputContract) +
          "</code></div></div>" +
          "</div>";
      }
    }
  }

  window.recalcDemo = function () {
    var zd = el("sim-zd").checked;
    var cons = el("sim-cons").checked;
    var metalRate = parseFloat(el("sim-age").value);
    var excess = Math.max(0, parseFloat(el("sim-excess").value || "0"));
    var salvage = Math.max(0, parseFloat((el("sim-salvage") && el("sim-salvage").value) || "85000"));
    var idv = 780000;

    var lines = [
      {
        code: "PRT-FRT-BMP-01",
        desc: "Front Bumper Assembly (Plastic 50%)",
        type: "part",
        amt: 12500,
        rate: 0.5,
        waivable: true,
        note: "Rubber/Nylon/Plastic 50% IMT depreciation"
      },
      {
        code: "PRT-HL-LED-RH",
        desc: "Headlamp Assembly LED RH (Glass 0%)",
        type: "part",
        amt: 18400,
        rate: 0,
        waivable: true,
        note: "Glass parts carry 0% depreciation"
      },
      {
        code: "PRT-FND-RH-01",
        desc: "Front Fender Panel RH (Metal age-graded)",
        type: "part",
        amt: 7800,
        rate: metalRate,
        waivable: true,
        note: "Metal schedule (" + Math.round(metalRate * 100) + "% rate)"
      },
      {
        code: "LABOUR-RNR-01",
        desc: "Bumper + Fender R&R Labour & Painting",
        type: "labour",
        amt: 7600,
        rate: 0,
        waivable: false,
        note: "Labour carries 0% depreciation"
      },
      {
        code: "PRT-CONS-KIT-01",
        desc: "AC Gas, Coolant & Fasteners Kit",
        type: "consumable",
        amt: 2400,
        rate: cons ? 0 : 1,
        waivable: false,
        note: cons
          ? "Covered under Consumables Add-on (ADDON-CONS-01)"
          : "Consumables excluded without Add-on (100% deducted)"
      }
    ];

    var gross = 0;
    var appliedDepTotal = 0;
    var waiverTotal = 0;
    var noAddonDepTotal = 0;
    var traceRows = [];

    lines.forEach(function (ln) {
      gross += ln.amt;
      var rawDep = ln.amt * ln.rate;
      var appliedDep = rawDep;
      var noAddonRate = ln.type === "consumable" ? 1 : ln.rate;
      noAddonDepTotal += ln.amt * noAddonRate;

      var note = ln.note;
      if (zd && ln.waivable && rawDep > 0) {
        waiverTotal += rawDep;
        appliedDep = 0;
        note += " → Waived by ADDON-ZD-01";
      }
      appliedDepTotal += appliedDep;
      var netLine = ln.amt - appliedDep;
      traceRows.push(
        "<tr>" +
          "<td><code>" +
          ln.code +
          "</code><br/><small style='color:#475569;'>" +
          escapeHtml(ln.desc) +
          "</small></td>" +
          "<td>" +
          fmtInr(ln.amt) +
          "</td>" +
          "<td>" +
          fmtInr(rawDep) +
          "</td>" +
          "<td>" +
          fmtInr(appliedDep) +
          "</td>" +
          "<td><strong>" +
          fmtInr(netLine) +
          "</strong></td>" +
          "<td style='font-size:12px; color:#475569;'>" +
          escapeHtml(note) +
          "</td>" +
          "</tr>"
      );
    });

    var net = Math.min(idv, Math.max(0, gross - appliedDepTotal - excess));
    var noAddonNet = Math.min(idv, Math.max(0, gross - noAddonDepTotal - excess));
    var ctlNet = Math.max(0, idv - excess - salvage);

    el("out-gross").textContent = fmtInr(gross);
    el("out-dep").textContent = fmtInr(appliedDepTotal);
    el("out-waiver").textContent = fmtInr(waiverTotal);
    el("out-net").textContent = fmtInr(net);

    var traceBody = el("sim-trace-body");
    if (traceBody) {
      traceBody.innerHTML = traceRows.join("");
    }

    var scenBody = el("sim-scenarios-body");
    if (scenBody) {
      var scenarios = [
        {
          label: "1. Cashless Network Repair (Recommended)",
          pathway: "cashless",
          dep: appliedDepTotal,
          waiver: waiverTotal,
          salvage: 0,
          netPay: net,
          note: "Active add-ons applied; net capped at IDV ₹7,80,000"
        },
        {
          label: "2. Customer Reimbursement Alternative",
          pathway: "reimbursement",
          dep: appliedDepTotal,
          waiver: waiverTotal,
          salvage: 0,
          netPay: net,
          note: "Direct insured payout on GST invoice at non-network workshop"
        },
        {
          label: "3. Standard Tariff Baseline (No Add-ons)",
          pathway: "cashless_no_addons",
          dep: noAddonDepTotal,
          waiver: 0,
          salvage: 0,
          netPay: noAddonNet,
          note: "Shows add-on benefit: +" + fmtInr(Math.max(0, net - noAddonNet)) + " saved"
        },
        {
          label: "4. Constructive Total Loss (IDV - Salvage)",
          pathway: "total_loss",
          dep: 0,
          waiver: 0,
          salvage: salvage,
          netPay: ctlNet,
          note: "CTL applies if net repair >= 75% IDV (₹5,85,000)"
        }
      ];
      scenBody.innerHTML = scenarios
        .map(function (s, idx) {
          return (
            '<tr style="' +
            (idx === 0 ? "background:#f0fdf4; font-weight:600;" : "") +
            '">' +
            "<td>" +
            escapeHtml(s.label) +
            "<br/><small style='color:#475569; font-weight:400;'>" +
            escapeHtml(s.note) +
            "</small></td>" +
            "<td><code>" +
            escapeHtml(s.pathway) +
            "</code></td>" +
            "<td>" +
            fmtInr(gross) +
            "</td>" +
            "<td>" +
            fmtInr(s.dep) +
            "</td>" +
            "<td>" +
            fmtInr(s.waiver) +
            "</td>" +
            "<td>" +
            fmtInr(excess) +
            "</td>" +
            "<td>" +
            fmtInr(s.salvage) +
            "</td>" +
            "<td><strong>" +
            fmtInr(s.netPay) +
            "</strong></td>" +
            "</tr>"
          );
        })
        .join("");
    }
  };

  window.showPipeline = function (key, btn) {
    ["e2e", "doc", "pay"].forEach(function (k) {
      var panel = el("pipe-" + k);
      if (!panel) return;
      panel.classList.toggle("hidden", k !== key);
      if (k === key && window.mermaid) {
        var nodes = panel.querySelectorAll(".mermaid:not([data-processed='true'])");
        if (nodes.length > 0) {
          window.mermaid.run({ nodes: Array.from(nodes) });
        }
      }
    });
    document.querySelectorAll(".tab-btn").forEach(function (b) {
      b.classList.remove("active");
    });
    if (btn) btn.classList.add("active");
  };

  window.loadScenarioIntoWorkflow = function (scenarioId) {
    selectScenario(scenarioId);
    var section = el("workflow");
    if (section) {
      section.scrollIntoView({ behavior: "smooth" });
    }
  };

  function initMermaid() {
    if (!window.mermaid) return;
    window.mermaid.initialize({
      startOnLoad: false,
      theme: "base",
      securityLevel: "loose",
      flowchart: {
        useMaxWidth: true,
        htmlLabels: true,
        curve: "basis"
      },
      themeVariables: {
        fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        fontSize: "14px",
        primaryColor: "#e5f3ff",
        primaryBorderColor: "#93c5fd",
        primaryTextColor: "#004f99",
        lineColor: "#64748b",
        secondaryColor: "#f5faff",
        tertiaryColor: "#f8fafc"
      }
    });

    var visibleDiagrams = Array.from(document.querySelectorAll(".mermaid")).filter(function (node) {
      return !node.closest(".hidden");
    });
    if (visibleDiagrams.length > 0) {
      window.mermaid.run({ nodes: visibleDiagrams });
    }
  }

  function renderOrchestratorEngine() {
    var respGrid = el("orch-responsibilities-grid");
    if (respGrid && DATA.orchestratorResponsibilities) {
      respGrid.innerHTML = DATA.orchestratorResponsibilities
        .map(function (item, idx) {
          return (
            '<div class="orch-resp-card">' +
            '<span class="badge badge-blue">#' +
            (idx + 1) +
            " · <code>" +
            escapeHtml(item.code) +
            "</code></span>" +
            '<div class="orch-resp-title">' +
            escapeHtml(item.title) +
            "</div>" +
            '<p class="orch-resp-desc">' +
            escapeHtml(item.desc) +
            "</p>" +
            "</div>"
          );
        })
        .join("");
    }

    var dagBody = el("orch-task-schedule-body");
    if (dagBody && DATA.taskScheduleTable) {
      dagBody.innerHTML = DATA.taskScheduleTable
        .map(function (row) {
          var badgeCls =
            row.execution.indexOf("Parallel") >= 0
              ? "badge-blue"
              : row.execution === "Conditional"
              ? "badge-purple"
              : row.execution === "Approval gated"
              ? "badge-amber"
              : "badge-slate";
          return (
            "<tr>" +
            "<td><strong>" +
            escapeHtml(row.task) +
            "</strong></td>" +
            "<td>" +
            escapeHtml(row.dependency) +
            "</td>" +
            '<td><span class="badge ' +
            badgeCls +
            '">' +
            escapeHtml(row.execution) +
            "</span></td>" +
            "<td><code>" +
            escapeHtml(row.group) +
            "</code></td>" +
            "<td><code>" +
            escapeHtml(row.owner) +
            "</code></td>" +
            "</tr>"
          );
        })
        .join("");
    }

    renderStateContractInspector();
  }

  function renderStateContractInspector() {
    var strip = el("orch-state-strip");
    var inspector = el("orch-state-inspector");
    if (!strip || !inspector || !DATA.stateContracts) return;

    strip.innerHTML = DATA.stateContracts
      .map(function (sc) {
        var classes = ["state-pill-btn"];
        if (sc.isBranch) classes.push("branch-track");
        if (sc.state === state.selectedOrchState) classes.push("active");
        return (
          '<button type="button" class="' +
          classes.join(" ") +
          '" data-orch-state="' +
          escapeHtml(sc.state) +
          '">' +
          escapeHtml(sc.state) +
          "</button>"
        );
      })
      .join("");

    strip.querySelectorAll(".state-pill-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.selectedOrchState = btn.getAttribute("data-orch-state");
        renderStateContractInspector();
      });
    });

    var cur =
      DATA.stateContracts.find(function (s) {
        return s.state === state.selectedOrchState;
      }) || DATA.stateContracts[0];

    function listItems(arr) {
      return (arr || [])
        .map(function (x) {
          return "<li>" + escapeHtml(x) + "</li>";
        })
        .join("");
    }

    inspector.innerHTML =
      '<div style="display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:8px; margin-bottom:12px;">' +
      '<div><span class="badge badge-blue">' +
      escapeHtml(cur.phase) +
      '</span> <strong style="font-size:17px; margin-left:6px;"><code>' +
      escapeHtml(cur.state) +
      "</code></strong></div>" +
      '<span class="badge badge-amber">Owner: ' +
      escapeHtml(cur.responsible) +
      "</span>" +
      "</div>" +
      '<div class="contract-grid-4">' +
      '<div class="kv-block"><div class="kv-label">1. Entry Conditions</div><ul style="margin:4px 0 0; padding-left:16px; font-size:12.5px;">' +
      listItems(cur.entryConditions) +
      "</ul></div>" +
      '<div class="kv-block"><div class="kv-label">2. Required Data</div><ul style="margin:4px 0 0; padding-left:16px; font-size:12.5px;">' +
      listItems(cur.requiredData) +
      "</ul></div>" +
      '<div class="kv-block"><div class="kv-label">3. Allowed Actions</div><ul style="margin:4px 0 0; padding-left:16px; font-size:12.5px;">' +
      listItems(cur.allowedActions) +
      "</ul></div>" +
      '<div class="kv-block"><div class="kv-label">4. Exit Conditions</div><ul style="margin:4px 0 0; padding-left:16px; font-size:12.5px;">' +
      listItems(cur.exitConditions) +
      "</ul></div>" +
      '<div class="kv-block"><div class="kv-label">5. Responsible Agent / Service</div><div class="kv-value"><strong>' +
      escapeHtml(cur.responsible) +
      "</strong></div></div>" +
      '<div class="kv-block"><div class="kv-label">6. SLA</div><div class="kv-value">' +
      escapeHtml(cur.sla) +
      "</div></div>" +
      '<div class="kv-block"><div class="kv-label">7. Retry Strategy (Exponential Backoff)</div><div class="kv-value">' +
      escapeHtml(cur.retryStrategy) +
      "</div></div>" +
      '<div class="kv-block"><div class="kv-label">8. Human Escalation Criteria</div><ul style="margin:4px 0 0; padding-left:16px; font-size:12.5px;">' +
      listItems(cur.humanEscalation) +
      "</ul></div>" +
      "</div>";
  }

  window.runOrchLab = function (mode) {
    var box = el("orch-lab-output");
    if (!box) return;
    var logs = {
      parallel_wave:
        "[ClaimOrchestrator] State: REGISTERED -> VALIDATION\n" +
        "[Scheduler] Dependency 'fnol_intake' satisfied -> Launching ThreadPoolExecutor wave 'post_fnol_parallel' (4 concurrent workers):\n" +
        "  • Worker-1 (policy_validation): Hybrid RAG matched POL-IN-DEMO-2026-1001 (Zero Dep + Consumables active) [9ms]\n" +
        "  • Worker-2 (document_extraction): RC + Policy + DL reconciled (0 conflicts, SHA-256 indexed) [11ms]\n" +
        "  • Worker-3 (duplicate_check): Active claim check on MH02DEMO1042 completed [4ms]\n" +
        "  • Worker-4 (customer_communication): Localized registration update dispatched in preferred language [6ms]\n" +
        "[Wave Commit] Wall duration: 12ms (sequential sum: 30ms) -> Transitioning VALIDATION -> TRIAGE",
      duplicate_event:
        "[Inbound Event] POST /api/v1/claims/{id}/orchestration/events { event_id: 'evt-fnol-0042', event_type: 'EvidenceUploaded' }\n" +
        "  • 1st delivery: OrchestrationEventLog inserted (tenant_id, claim_id, event_id) -> status='processed', wave triggered.\n" +
        "[Duplicate Replay] POST /api/v1/claims/{id}/orchestration/events { event_id: 'evt-fnol-0042', event_type: 'EvidenceUploaded' }\n" +
        "  • 2nd delivery: UniqueConstraint hit -> duplicate_ignored=true, duplicate_hits=1.\n" +
        "  • Audit: DUPLICATE_EVENT_IGNORED recorded · Zero duplicate tasks, state jumps, or payouts executed.",
      backoff_dlq:
        "[Task: damage_assessment] Timeout budget (20s) exceeded on Attempt #1 -> AGENT_TIMEOUT_RETRY\n" +
        "  • Exponential Backoff Attempt 1: delay = 300 * 2.0^0 = 300ms -> retrying...\n" +
        "  • Exponential Backoff Attempt 2: delay = 300 * 2.0^1 = 600ms -> retrying...\n" +
        "  • Attempt 3 exhausted (max_retries=2) -> TASK_MOVED_TO_DLQ\n" +
        "[Dead-Letter Queue] Persisted DeadLetterRecord { task_key: 'damage_assessment', error_code: 'ORCH_RETRY_EXHAUSTED', status: 'open' }\n" +
        "[Recovery] Operator triggers POST /api/v1/orchestration/dlq/{dlq_id}/replay -> Task restored to 'pending' -> Completed cleanly!",
      pause_resume:
        "[Operator] POST /api/v1/claims/{id}/orchestration/pause { reason: 'Awaiting customer daylight photos' }\n" +
        "  • workflow_state.paused = true · 2 pending OrchestrationTasks marked 'paused' · Active SLATimer frozen (status='paused').\n" +
        "  • Premature /orchestrate call returns paused_reason without altering state.\n" +
        "[Operator] POST /api/v1/claims/{id}/orchestration/resume { run_ready_stages: true }\n" +
        "  • SLATimer unpaused · Paused tasks restored -> Resumed from exact checkpoint (skipping already-completed steps).",
      compensation_saga:
        "[Saga Trigger] POST /api/v1/claims/{id}/orchestration/compensate { trigger_reason: 'Policyholder withdrew claim before inspection' }\n" +
        "  • Step 1: release_surveyor_assignment_and_load -> Cancelled open SurveyAssignment & decremented Surveyor active_load\n" +
        "  • Step 2: release_garage_intake_allocation -> Cleared assigned_garage_id reservation\n" +
        "  • Step 3: void_pending_doa_approval & supersede_pending_settlement -> Voided pending Approvals & superseded Settlement\n" +
        "  • Step 4: freeze_pending_payment_prevent_double_debit -> Locked any timeout_reconcile_pending instruction\n" +
        "  • Audit & Outbox: CompensationExecuted emitted · Claim transitioned safely to HUMAN_REVIEW."
    };
    box.textContent = logs[mode] || logs.parallel_wave;
  };

  window.applyRiskPreset = function (preset) {
    var lossEl = el("risk-loss-inr");
    if (!lossEl) return;
    var sets = {
      low_fast_track: { loss: 18500, fraud: 0.05, missing: false, est: false, invPol: false, inj: false, multi: false, ev: false, conflict: false, dispute: false, label: "LOW RISK Straight-Through Intake" },
      medium_standard: { loss: 64200, fraud: 0.25, missing: true, est: true, invPol: false, inj: false, multi: false, ev: false, conflict: false, dispute: false, label: "MEDIUM RISK Standard Assisted" },
      high_multi_ev: { loss: 310000, fraud: 0.45, missing: false, est: false, invPol: false, inj: true, multi: true, ev: true, conflict: false, dispute: false, label: "HIGH RISK Multi-Vehicle & EV Complex" },
      escalate_late_evidence: { loss: 18500, fraud: 0.86, missing: false, est: false, invPol: false, inj: false, multi: true, ev: true, conflict: true, dispute: false, label: "DYNAMIC ESCALATION: Started LOW (₹18.5k), Late Evidence Pushed to HIGH" }
    };
    var cfg = sets[preset] || sets.low_fast_track;
    el("risk-loss-inr").value = cfg.loss;
    el("risk-fraud-score").value = cfg.fraud;
    el("risk-missing-docs").checked = cfg.missing;
    el("risk-est-discrepancy").checked = cfg.est;
    el("risk-policy-invalid").checked = cfg.invPol;
    el("risk-injury").checked = cfg.inj;
    el("risk-multi-veh").checked = cfg.multi;
    el("risk-ev-battery").checked = cfg.ev;
    el("risk-conflict").checked = cfg.conflict;
    el("risk-dispute").checked = cfg.dispute;
    window.updateRiskSimulation(cfg.label);
  };

  window.updateRiskSimulation = function (presetNote) {
    var outEl = el("risk-sim-output");
    if (!outEl) return;
    var loss = parseFloat((el("risk-loss-inr") || {}).value) || 0;
    var fraud = parseFloat((el("risk-fraud-score") || {}).value) || 0;
    var missingDocs = !!(el("risk-missing-docs") || {}).checked;
    var estDisc = !!(el("risk-est-discrepancy") || {}).checked;
    var polInvalid = !!(el("risk-policy-invalid") || {}).checked;
    var injury = !!(el("risk-injury") || {}).checked;
    var multiVeh = !!(el("risk-multi-veh") || {}).checked;
    var evBattery = !!(el("risk-ev-battery") || {}).checked;
    var conflict = !!(el("risk-conflict") || {}).checked;
    var dispute = !!(el("risk-dispute") || {}).checked;

    var highDrivers = [];
    if (injury || multiVeh) highDrivers.push("Injury or third-party liability / Multiple vehicles (+45)");
    if (fraud >= 0.65) highDrivers.push("Suspected fraud signal score=" + fraud.toFixed(3) + " -> SIU escalation, NEVER auto-rejects (+40)");
    if (loss >= 250000) highDrivers.push("Significant loss >= ₹2,50,000 (+35)");
    if (conflict) highDrivers.push("Conflicting evidence / document mismatch (+35)");
    if (evBattery) highDrivers.push("EV traction battery / HV damage (+35)");
    if (polInvalid || dispute) highDrivers.push("Legal or coverage dispute / invalid policy (+35)");

    var medDrivers = [];
    if (loss >= 50000 && loss < 250000) medDrivers.push("Damage requires IRDAI physical inspection (>= ₹50,000) (+22)");
    if (estDisc) medDrivers.push("Estimate discrepancies / variance (+20)");
    if (missingDocs) medDrivers.push("Missing documents follow-up (+18)");

    var tier = "LOW";
    var path = "fast_track";
    var handling = "Straight-through assisted processing";
    var goal = "Minimize human touchpoints";
    var score = 12;
    if (highDrivers.length > 0) {
      tier = "HIGH";
      path = "complex_investigation";
      handling = "Specialist and human-led handling";
      goal = "Improve investigative quality, preserve evidence (legal_hold=true) and ensure controlled decisions";
      score = Math.min(100, 65 + highDrivers.length * 15);
    } else if (medDrivers.length > 0) {
      tier = "MEDIUM";
      path = "standard";
      handling = "AI-assisted claims handling";
      goal = "Reduce handler effort and waiting time";
      score = Math.min(64, 25 + medDrivers.length * 14);
    }

    ["LOW", "MEDIUM", "HIGH"].forEach(function (t) {
      var card = el("risk-card-" + t);
      if (card) {
        if (t === tier) card.classList.add("active-tier");
        else card.classList.remove("active-tier");
      }
    });

    var autoEligible = tier === "LOW" && loss <= 25000;
    var header = presetNote ? "[Scenario] " + presetNote + "\n" : "";
    var driverLines = highDrivers.length
      ? highDrivers.concat(medDrivers)
      : medDrivers.length
      ? medDrivers
      : ["All 5 Low-Risk Criteria Met: Minor damage, Complete docs, Valid policy, Low estimate (₹" + loss.toLocaleString("en-IN") + "), Zero material anomalies"];

    outEl.textContent =
      header +
      "[RiskEngine IN-RISK-PROCESSING-2026] Tier: " + tier + " RISK | Path: " + path + " | Score: " + score + "/100\n" +
      "  • Handling Mode: " + handling + " | Goal: " + goal + "\n" +
      "  • Active Drivers (" + driverLines.length + "): " + driverLines.join(" ; ") + "\n" +
      "  • Automation & Limits: " + (tier === "LOW"
        ? (autoEligible
            ? "ELIGIBLE FOR STRAIGHT-THROUGH AUTO-APPROVAL (<= ₹25,000 limit; physical survey BYPASSED)"
            : "L1 Fast-Track Assisted (₹25,000–₹49,999.99; physical survey BYPASSED)")
        : (tier === "MEDIUM"
            ? "AI-Assisted Surveyor/Repair Coordination + Maker-Checker DoA Required"
            : "SPECIALIST HUMAN-LED ONLY · Evidence Legal Hold ACTIVE (legal_hold=true) · L1 Handler Blocked")) + "\n" +
      "  • Fraud Score Guardrail: fraud_signal_score=" + fraud.toFixed(3) + " | fraud_score_can_reject=false (NEVER auto-rejects claim!)";
  };

  document.addEventListener("DOMContentLoaded", function () {
    renderOrchestratorEngine();
    if (window.runOrchLab) window.runOrchLab("parallel_wave");
    if (window.applyRiskPreset) window.applyRiskPreset("low_fast_track");
    renderActiveWorkflow();
    renderQuestions();
    renderCapabilityMatrix();
    window.recalcDemo();
    initMermaid();

    var prevBtn = el("btn-prev-step");
    var nextBtn = el("btn-next-step");
    var playBtn = el("btn-play-walkthrough");
    var resetBtn = el("btn-reset-step");

    if (prevBtn) {
      prevBtn.addEventListener("click", function () {
        stopPlayback();
        if (state.stepIdx > 0) {
          state.stepIdx -= 1;
          renderActiveWorkflow();
        }
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener("click", function () {
        var sc = DATA.scenarios[state.scenarioId];
        stopPlayback();
        if (sc && state.stepIdx < sc.steps.length - 1) {
          state.stepIdx += 1;
          renderActiveWorkflow();
        }
      });
    }
    if (playBtn) {
      playBtn.addEventListener("click", togglePlayback);
    }
    if (resetBtn) {
      resetBtn.addEventListener("click", function () {
        stopPlayback();
        state.stepIdx = 0;
        renderActiveWorkflow();
      });
    }
  });
})();
