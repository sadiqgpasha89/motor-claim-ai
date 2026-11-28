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
    if (window.MCPager && window.MCPager.reveal("workflow", true)) {
      if (location.hash !== "#workflow") history.pushState(null, "", "#workflow");
    } else if (section) {
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

  window.renderDamageAiLab = function (scenarioId) {
    var lab = DATA.damageAiLab;
    var tabsEl = el("damage-scenario-tabs");
    var stepperEl = el("damage-workflow-stepper");
    var bodyEl = el("damage-lab-body");
    if (!lab || !tabsEl || !stepperEl || !bodyEl) return;

    var activeId = scenarioId && lab.scenarios[scenarioId] ? scenarioId : lab.activeId;
    var sc = lab.scenarios[activeId];
    if (!sc) return;

    tabsEl.innerHTML = Object.keys(lab.scenarios)
      .map(function (k) {
        var item = lab.scenarios[k];
        var activeCls = k === activeId ? "btn-primary" : "btn-outline";
        return (
          '<button type="button" class="btn ' +
          activeCls +
          ' btn-sm" onclick="renderDamageAiLab(\'' +
          escapeHtml(k) +
          "')\">" +
          escapeHtml(item.label) +
          "</button>"
        );
      })
      .join("");

    stepperEl.innerHTML = sc.workflowSteps
      .map(function (st) {
        return (
          '<div class="dmg-step-card ' +
          escapeHtml(st.status) +
          '">' +
          '<div style="display:flex; justify-content:space-between; font-weight:700;"><span>Step ' +
          st.num +
          '</span><span style="text-transform:uppercase; font-size:10px;">' +
          escapeHtml(st.status) +
          "</span></div>" +
          '<div style="font-weight:700; margin-top:2px;">' +
          escapeHtml(st.title) +
          "</div>" +
          '<div style="color:#475569; margin-top:3px; font-size:11.5px;">' +
          escapeHtml(st.summary) +
          "</div>" +
          "</div>"
        );
      })
      .join("");

    var svgBoxes = sc.components
      .map(function (c) {
        var color = c.repairability === "uncertain" ? "#f59e0b" : c.repairability === "replace" ? "#f43f5e" : "#10b981";
        var dash = c.repairability === "uncertain" ? ' stroke-dasharray="2 1"' : "";
        return (
          '<rect x="' +
          c.bbox.x +
          '" y="' +
          c.bbox.y +
          '" width="' +
          c.bbox.w +
          '" height="' +
          c.bbox.h +
          '" fill="' +
          color +
          '" fill-opacity="0.2" stroke="' +
          color +
          '" stroke-width="1.2"' +
          dash +
          ' rx="1.5"/>' +
          '<text x="' +
          (c.bbox.x + 1.2) +
          '" y="' +
          Math.max(6, c.bbox.y - 1.5) +
          '" fill="' +
          color +
          '" font-size="3.4" font-weight="bold">' +
          escapeHtml(c.component) +
          " · " +
          Math.round(c.confidence * 100) +
          "% (" +
          escapeHtml(c.repairability) +
          ")</text>"
        );
      })
      .join("");

    var compCards = sc.components
      .map(function (c) {
        var pct = Math.round(c.confidence * 100);
        var repBadge =
          c.repairability === "uncertain" ? "badge-amber" : c.repairability === "replace" ? "badge-rose" : "badge-green";
        var barCls = pct >= 80 ? "" : pct >= 65 ? " medium" : " low";
        return (
          '<div class="dmg-comp-card">' +
          '<div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">' +
          "<div><strong>" +
          escapeHtml(c.fullName) +
          '</strong><div style="font-size:11.5px; color:#475569;">Location: <code>' +
          escapeHtml(c.location) +
          "</code> · Severity: <strong>" +
          escapeHtml(c.severity) +
          "</strong> · Quality: <strong>" +
          escapeHtml(c.imageQuality) +
          "</strong></div></div>" +
          '<span class="badge ' +
          repBadge +
          '">' +
          escapeHtml(c.repairability.toUpperCase()) +
          "</span></div>" +
          '<div><div style="display:flex; justify-content:space-between; font-weight:700;"><span>Component Confidence</span><span>' +
          pct +
          "% (" +
          c.confidence.toFixed(2) +
          ')</span></div><div class="conf-meter-wrap"><div class="conf-bar"><div class="conf-fill' +
          barCls +
          '" style="width:' +
          pct +
          '%;"></div></div></div><div style="font-size:11.5px; color:#475569; margin-top:4px;">' +
          escapeHtml(c.rationale) +
          "</div></div>" +
          '<div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:8px;"><strong>Visible damage:</strong> ' +
          escapeHtml(c.visibleDamage) +
          "</div>" +
          '<div style="background:#fffbeb; border:1px solid #fde68a; border-radius:8px; padding:8px;"><strong>Possible hidden damage:</strong> ' +
          escapeHtml(c.hiddenDamage) +
          "</div>" +
          '<div style="font-size:11.5px; color:#334155;"><strong>Est:</strong> ' +
          escapeHtml(c.cost) +
          "<br/><strong>Evidence:</strong> <code>" +
          escapeHtml(c.evidence) +
          "</code></div>" +
          "</div>"
        );
      })
      .join("");

    var tableRows = [
      ["Vehicle", sc.vehicle],
      ["Damage location", sc.components.map(function (c) { return c.location; }).join(", ")],
      ["Damaged component", sc.components.map(function (c) { return c.component; }).join(", ")],
      ["Damage severity", sc.components.map(function (c) { return c.severity; }).join(", ")],
      ["Repairability", sc.components.map(function (c) { return c.component + ": " + c.repairability; }).join(" | ")],
      ["Visible damage", sc.components.map(function (c) { return c.visibleDamage; }).join(" | ")],
      ["Possible hidden damage", sc.components.map(function (c) { return c.hiddenDamage; }).join(" | ")],
      ["Image quality", sc.overallImageQuality + " (overall score " + Math.round(sc.overallImageScore * 100) + "%)"],
      ["Confidence", sc.components.map(function (c) { return c.component + ": " + c.confidence.toFixed(2); }).join(" | ")],
      ["Evidence", sc.components.map(function (c) { return c.evidence; }).join(" ; ")]
    ]
      .map(function (r) {
        return "<tr><th style='width:170px;'>" + escapeHtml(r[0]) + "</th><td>" + escapeHtml(r[1]) + "</td></tr>";
      })
      .join("");

    var incHtml = sc.inconsistencies.length
      ? sc.inconsistencies.map(function (i) { return "<div class='badge badge-rose' style='display:block; margin-bottom:6px;'>" + escapeHtml(i) + "</div>"; }).join("")
      : "<span class='badge badge-green'>Zero cross-photo or FNOL inconsistencies</span>";

    bodyEl.innerHTML =
      '<div class="risk-guardrail-banner" style="margin-top:0;">' +
      "<span><strong>Component Confidence Guardrail:</strong> " +
      escapeHtml(sc.guardrailNote) +
      "</span>" +
      '<span class="badge ' +
      (sc.routeToHumanAssessor ? "badge-amber" : "badge-green") +
      '">' +
      (sc.routeToHumanAssessor ? "Routed to Human Assessor (" + escapeHtml(sc.recommendedRole) + ")" : "Autonomous Ready") +
      "</span></div>" +
      '<div class="grid-2">' +
      '<div class="dmg-canvas-box">' +
      '<div style="display:flex; justify-content:space-between; font-size:12px;"><span><strong>Detected Vehicle:</strong> ' +
      escapeHtml(sc.vehicle) +
      '</span><span class="badge badge-blue">Img Quality: ' +
      escapeHtml(sc.overallImageQuality) +
      " (" +
      Math.round(sc.overallImageScore * 100) +
      "%)</span></div>" +
      '<svg viewBox="0 0 100 100" style="width:100%; height:230px; background:#020617; border:1px solid #334155; border-radius:8px;">' +
      '<rect x="14" y="16" width="72" height="68" rx="14" fill="#1e293b" stroke="#475569" stroke-width="1.2"/>' +
      '<rect x="24" y="24" width="52" height="18" rx="5" fill="#0f172a" stroke="#64748b" stroke-width="0.8"/>' +
      '<rect x="24" y="58" width="52" height="14" rx="4" fill="#0f172a" stroke="#64748b" stroke-width="0.8"/>' +
      '<text x="50" y="51" text-anchor="middle" fill="#94a3b8" font-size="3.4" font-family="monospace">BOUNDING-BOX REGION MAP</text>' +
      svgBoxes +
      "</svg>" +
      '<div style="font-size:12px;"><strong>Inconsistencies:</strong> ' +
      incHtml +
      "<br/><strong>Additional Photo Requests:</strong> " +
      escapeHtml(sc.photoRequests.join(" · ")) +
      "</div>" +
      "</div>" +
      '<div class="table-wrap"><table><tbody>' +
      tableRows +
      "</tbody></table></div>" +
      "</div>" +
      '<div class="dmg-comp-grid">' +
      compCards +
      "</div>";
  };

  window.renderEcosystemDashboard = function (filterType) {
    var tbody = el("eco-dashboard-body");
    if (!tbody || !DATA.ecosystemProviders) return;
    var f = filterType || "all";
    var rows = DATA.ecosystemProviders.filter(function (p) {
      return f === "all" || p.type === f;
    });
    tbody.innerHTML = rows
      .map(function (p) {
        var availCls = p.availability === "Available" ? "badge-green" : p.availability === "Busy" ? "badge-amber" : "badge-rose";
        var slaCls = p.sla === "Within SLA" ? "badge-green" : p.sla === "At Risk" ? "badge-amber" : "badge-rose";
        var loadCls = p.currentLoad === "Low" ? "badge-green" : p.currentLoad === "Medium" ? "badge-amber" : "badge-rose";
        var licCls = p.licence.indexOf("EXPIRED") >= 0 ? "badge-rose" : "badge-slate";
        return (
          "<tr>" +
          "<td><strong>" + escapeHtml(p.name) + '</strong><br/><span style="font-size:11px; color:#64748b; text-transform:uppercase;">' + escapeHtml(p.type) + "</span></td>" +
          '<td><span class="badge ' + availCls + '">' + escapeHtml(p.availability) + "</span></td>" +
          '<td><span class="badge ' + slaCls + '">' + escapeHtml(p.sla) + "</span></td>" +
          "<td><strong>" + p.rating.toFixed(1) + "</strong></td>" +
          '<td><span class="badge ' + loadCls + '">' + escapeHtml(p.currentLoad) + "</span> <span style=\"font-size:11px; color:#64748b;\">(" + escapeHtml(p.loadRatio) + ")</span></td>" +
          "<td><strong>" + escapeHtml(p.city) + "</strong><br/><span style=\"font-size:11px; color:#475569;\">" + escapeHtml(p.skills.join(", ")) + "</span></td>" +
          '<td><span class="badge ' + licCls + '">' + escapeHtml(p.licence) + '</span><br/><span style="font-size:11px; color:#475569;">Parts: ' + escapeHtml(p.parts) + "</span></td>" +
          "</tr>"
        );
      })
      .join("");
  };

  window.runEcoSim = function (mode) {
    var out = el("eco-sim-output");
    if (!out) return;
    var logs = {
      preferred_honoured:
        "[ProviderCoordination] Customer requested: Garage A — Apex Motors (Mumbai Andheri) | Claim: Maruti Baleno OD (₹64,200)\n" +
        "  • Surveyor Licence Check: R. K. Sharma (IRDAI-SLA-DEMO-4421) -> VERIFIED (expires in 365d)\n" +
        "  • Surveyor Score (93.6/100): Geo=30 (Andheri zone match) + Skill=25 (OEM Maruti) + Capacity=15 (Low 3/12) + SLA=15 (Within SLA) + Rating=9.6 (4.8★)\n" +
        "  • Garage Check: Garage A is network-verified, Within SLA, Low load (5/20), Rating 4.7★ -> CUSTOMER PREFERENCE HONOURED\n" +
        "  • Parts & Logistics: Front Bumper & Headlamp IN STOCK (1d); Pickup scheduled + WhatsApp notification sent.",
      unauthorized_override:
        "[Guardrail Triggered] Actor 'claims_handler' attempted override_customer_preference=true (Garage A -> Garage B) without Manager authorization.\n" +
        "  • Result: 403 NOT_AUTHORISED | Agent status: NEEDS_HUMAN | Action: override_guardrail [blocked_policy]\n" +
        "  • Policy Rule: CUSTOMER-PREFERENCE-AUTH-GUARD-V1 — Customer choice & contractual rules cannot be overridden without Claims Manager/Admin + documented override_reason.\n" +
        "  • Retained: Garage A — Apex Motors Cashless Hub.",
      ev_safety_contract:
        "[Contractual EV Safety Rule] Customer preferred non-EV Garage A on Tata Nexon EV claim (ev_battery_impacted=true).\n" +
        "  • Contractual Mandate: POL-WORDING-EV-2025:EV-SAFE-01 prohibits servicing HV traction battery at non-EV workshops.\n" +
        "  • Redirected to: VoltCare OEM EV Specialist Centre (score 94.8/100, EV HV Certified, Within SLA, Low load 2/10, Rating 4.9★)\n" +
        "  • Logistics: SafeTow EV Flatbed Recovery dispatched + HV OEM Battery Tray ordered (ETA 3d) + Customer notified.",
      expired_licence:
        "[IIISLA Licence Verification Gate] Attempted assignment of Legacy Unverified Assessor (IRDAI-SLA-EXP-0009).\n" +
        "  • Registry Response: verified=false (licence_status='expired', expired 30 days ago) -> 400 VALIDATION_ERROR / blocked_policy\n" +
        "  • Auto-Fallback: Selected Surveyor C / R. K. Sharma (verified IIISLA, Within SLA, Available).",
      resched_followup_repair:
        "[Full Ecosystem Lifecycle] Claim CLM-ECO-2026\n" +
        "  • Inspection Rescheduled: Customer requested afternoon slot -> reschedule_count=1, WhatsApp notice sent.\n" +
        "  • Surveyor Report Follow-up: Follow-up #1 triggered + SLA task assigned to surveyor.\n" +
        "  • Repair Milestones: intake_confirmed -> teardown -> body_paint -> qc_pending -> repair_completed\n" +
        "  • Repair Completion Confirmed: Garage QC signed off, delivery scheduled, customer handover WhatsApp notification sent!"
    };
    out.textContent = logs[mode] || logs.preferred_honoured;
  };

  var cxState = {
    presetKey: "registered_survey_pending",
    triggerKey: "survey_scheduled",
    escalatedRef: null
  };

  window.setCxDemoStage = function (presetKey) {
    if (!DATA.customerExperienceLab || !DATA.customerExperienceLab.presets[presetKey]) return;
    cxState.presetKey = presetKey;
    cxState.triggerKey = DATA.customerExperienceLab.presets[presetKey].defaultTrigger;
    cxState.escalatedRef = null;
    window.renderCustomerExperienceLab();
  };

  window.selectCxTrigger = function (triggerKey) {
    cxState.triggerKey = triggerKey;
    cxState.escalatedRef = null;
    window.renderCustomerExperienceLab();
  };

  window.triggerCxHumanEscalation = function () {
    var lab = DATA.customerExperienceLab;
    var preset = lab.presets[cxState.presetKey];
    var lang = el("cx-lang-select") ? el("cx-lang-select").value : "en-IN";
    var reqCh = el("cx-channel-select") ? el("cx-channel-select").value : "whatsapp";
    var waConsent = el("cx-wa-consent") ? el("cx-wa-consent").checked : true;
    var effCh = reqCh === "whatsapp" && !waConsent ? "email" : reqCh;
    cxState.escalatedRef = {
      ref: "ESC-DEMO-4812",
      channel: effCh,
      blockedWa: reqCh === "whatsapp" && !waConsent,
      lang: lang,
      claimNumber: preset.claimNumber
    };
    window.renderCustomerExperienceLab();
  };

  window.renderCustomerExperienceLab = function () {
    var lab = DATA.customerExperienceLab;
    var trackerEl = el("cx-tracker-box");
    var gridEl = el("cx-triggers-grid");
    var previewEl = el("cx-message-preview");
    if (!lab || !trackerEl || !gridEl || !previewEl) return;

    var preset = lab.presets[cxState.presetKey];
    var lang = el("cx-lang-select") ? el("cx-lang-select").value : "en-IN";
    var reqCh = el("cx-channel-select") ? el("cx-channel-select").value : "whatsapp";
    var waConsent = el("cx-wa-consent") ? el("cx-wa-consent").checked : true;
    var waBlocked = reqCh === "whatsapp" && !waConsent;
    var effCh = waBlocked ? "email" : reqCh;
    var titles = lab.stageTitles[lang] || lab.stageTitles["en-IN"];

    var stagesHtml = preset.stages
      .map(function (st, idx) {
        var statusTag =
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
          '<div class="cx-stage-card ' +
          escapeHtml(st.status) +
          '">' +
          '<div style="display:flex; justify-content:space-between; font-size:10.5px; font-weight:700; text-transform:uppercase;">' +
          "<span>Step " +
          (idx + 1) +
          "</span><span>" +
          escapeHtml(statusTag) +
          "</span></div>" +
          '<div style="font-weight:800; font-size:13px;">' +
          escapeHtml(titles[idx]) +
          "</div>" +
          '<div style="line-height:1.4;">' +
          escapeHtml(st.detail) +
          "</div>" +
          (st.date ? '<div style="font-family:monospace; font-size:10.5px; opacity:0.8;">' + escapeHtml(st.date) + "</div>" : "") +
          "</div>"
        );
      })
      .join("");

    trackerEl.innerHTML =
      '<div class="cx-tracker-header">' +
      '<div><div style="font-size:11px; text-transform:uppercase; letter-spacing:0.06em; opacity:0.8;">Motor claim tracker</div>' +
      '<div style="font-size:16px; font-weight:800;">' +
      escapeHtml(preset.claimNumber) +
      " · " +
      escapeHtml(preset.vehicle) +
      "</div></div>" +
      '<span class="badge badge-green">' +
      preset.progressPct +
      "% Complete</span></div>" +
      '<div class="cx-tracker-grid">' +
      stagesHtml +
      "</div>";

    gridEl.innerHTML = lab.triggers
      .map(function (tr) {
        var isFlagged = preset.activeTriggers.indexOf(tr.key) >= 0;
        var isSel = cxState.triggerKey === tr.key;
        return (
          '<button type="button" class="cx-trigger-btn' +
          (isSel ? " active" : "") +
          (isFlagged ? " flagged" : "") +
          '" onclick="selectCxTrigger(\'' +
          escapeHtml(tr.key) +
          "')\">" +
          '<div style="display:flex; justify-content:space-between; align-items:center; gap:6px;">' +
          "<strong>" +
          escapeHtml(tr.label) +
          "</strong>" +
          (isFlagged ? '<span class="badge badge-amber" style="font-size:9.5px; padding:1px 6px;">ACTIVE</span>' : "") +
          "</div>" +
          '<div style="font-size:10.5px; opacity:0.75; margin-top:2px; font-family:monospace;">' +
          escapeHtml(tr.key) +
          "</div></button>"
        );
      })
      .join("");

    if (cxState.escalatedRef) {
      previewEl.innerHTML =
        '<div style="display:flex; flex-wrap:wrap; justify-content:space-between; gap:8px; margin-bottom:8px;">' +
        "<strong>Human Specialist Escalation Created: " +
        escapeHtml(cxState.escalatedRef.ref) +
        " (4-hour Callback SLA)</strong>" +
        '<span class="badge badge-rose">ClaimTask Assigned: claims_handler</span></div>' +
        '<div style="background:#fff; border:1px solid #fecdd3; border-radius:8px; padding:10px;">' +
        "Immediate acknowledgement dispatched on <strong>" +
        escapeHtml(cxState.escalatedRef.channel.toUpperCase()) +
        "</strong> in <code>" +
        escapeHtml(cxState.escalatedRef.lang) +
        "</code>" +
        (cxState.escalatedRef.blockedWa
          ? " (WhatsApp opt-in consent unchecked &rarr; routed via consented Email fallback)."
          : " (WhatsApp opt-in consent verified).") +
        "</div>";
      return;
    }

    var msgMap = lab.messages[cxState.triggerKey] || lab.messages.documents_missing;
    var msg = msgMap[lang] || msgMap["en-IN"];
    var subj = msg.subject.replace("{cn}", preset.claimNumber);
    var body = msg.body.replace(/\{cn\}/g, preset.claimNumber);

    previewEl.innerHTML =
      '<div style="display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:8px; margin-bottom:8px;">' +
      "<strong>State-Aware AI Update Preview · <code>" +
      escapeHtml(cxState.triggerKey) +
      "</code> (" +
      escapeHtml(lang) +
      ")</strong>" +
      '<div style="display:flex; gap:6px;">' +
      '<span class="badge ' +
      (waBlocked ? "badge-amber" : "badge-green") +
      '">Effective Channel: ' +
      escapeHtml(effCh.toUpperCase()) +
      "</span>" +
      (effCh === "whatsapp" ? '<span class="badge badge-blue">wamid.DEMO Verified</span>' : "") +
      "</div></div>" +
      (waBlocked
        ? '<div class="badge badge-amber" style="display:block; margin-bottom:8px;">WhatsApp Consent Guardrail: WhatsApp opt-in is unchecked (RC_WHATSAPP_CONSENT_REQUIRED) — routed to ' +
          escapeHtml(effCh.toUpperCase()) +
          ".</div>"
        : "") +
      '<div style="background:#ffffff; border:1px solid #c7d2fe; border-radius:8px; padding:10px;">' +
      '<div style="font-weight:700; margin-bottom:4px;">' +
      escapeHtml(subj) +
      "</div>" +
      "<div>" +
      escapeHtml(body) +
      "</div></div>";
  };

  document.addEventListener("DOMContentLoaded", function () {
    renderOrchestratorEngine();
    if (window.runOrchLab) window.runOrchLab("parallel_wave");
    if (window.applyRiskPreset) window.applyRiskPreset("low_fast_track");
    if (window.renderDamageAiLab) window.renderDamageAiLab("guardrail_uncertain");
    if (window.renderEcosystemDashboard) window.renderEcosystemDashboard("all");
    if (window.runEcoSim) window.runEcoSim("preferred_honoured");
    if (window.renderCustomerExperienceLab) window.renderCustomerExperienceLab();
    renderActiveWorkflow();
    renderQuestions();
    renderCapabilityMatrix();
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
