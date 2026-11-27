/*
 * Settlement decision workbench - browser/Node mirror of services/settlement/workbench.py.
 *
 * All money is held as integer paise in BigInt so results match the Python Decimal calculation exactly
 * (ROUND_HALF_UP on non-negative values). Rules, labels, clauses and the demo claim are read from
 * settlement-workbench-data.js, which is generated from the same JSON files the backend uses.
 * tests/unit/test_settlement_workbench.py runs both engines and asserts identical output.
 */
(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.SettlementEngine = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var ZERO = 0n;

  // ---------------------------------------------------------------- money helpers

  function parseMoney(v) {
    var s = String(v).trim();
    if (/e/i.test(s)) s = Number(s).toFixed(4);
    var neg = s.charAt(0) === "-";
    if (neg) s = s.slice(1);
    var parts = s.split(".");
    var whole = parts[0] === "" ? "0" : parts[0];
    var frac = ((parts[1] || "") + "000").slice(0, 3);
    var paise = BigInt(whole) * 100n + BigInt(frac.slice(0, 2));
    if (frac.charAt(2) >= "5") paise += 1n;
    return neg ? -paise : paise;
  }

  function fmt(p) {
    var neg = p < 0n;
    var a = neg ? -p : p;
    var c = a % 100n;
    var s = (a / 100n).toString() + "." + (c < 10n ? "0" : "") + c.toString();
    return neg && a !== 0n ? "-" + s : s;
  }

  function bp(rate) {
    return BigInt(Math.round(parseFloat(rate) * 10000));
  }

  function fmtBp4(basis) {
    var f = (basis % 10000n).toString();
    while (f.length < 4) f = "0" + f;
    return (basis / 10000n).toString() + "." + f;
  }

  // a * b / c, half-up, for non-negative operands
  function mulDiv(a, b, c) {
    return (a * b * 2n + c) / (2n * c);
  }

  function ratio4(n, d) {
    if (d === 0n) return "0.0000";
    return fmtBp4((n * 20000n + d) / (2n * d));
  }

  function maxB(a, b) {
    return a > b ? a : b;
  }

  function minB(a, b) {
    return a < b ? a : b;
  }

  function sum(list, pick) {
    var t = ZERO;
    for (var i = 0; i < list.length; i++) t += pick(list[i]);
    return t;
  }

  // ---------------------------------------------------------------- inputs

  function defaultInputs(data) {
    var d = data.demo.defaults;
    return {
      vehicle_age_months: parseInt(d.vehicle_age_months, 10),
      idv_inr: parseMoney(d.idv_inr),
      market_value_inr: parseMoney(d.market_value_inr),
      compulsory_deductible_inr: parseMoney(d.compulsory_deductible_inr),
      voluntary_deductible_inr: parseMoney(d.voluntary_deductible_inr),
      salvage_value_inr: parseMoney(d.salvage_value_inr),
      zero_depreciation: !!d.zero_depreciation,
      consumables: !!d.consumables
    };
  }

  function inputsFromMapping(data, o) {
    var base = defaultInputs(data);
    o = o || {};
    function money(key) {
      return o[key] === undefined || o[key] === null || o[key] === "" ? base[key] : parseMoney(o[key]);
    }
    return {
      vehicle_age_months: o.vehicle_age_months === undefined ? base.vehicle_age_months : parseInt(o.vehicle_age_months, 10),
      idv_inr: money("idv_inr"),
      market_value_inr: money("market_value_inr"),
      compulsory_deductible_inr: money("compulsory_deductible_inr"),
      voluntary_deductible_inr: money("voluntary_deductible_inr"),
      salvage_value_inr: money("salvage_value_inr"),
      zero_depreciation: o.zero_depreciation === undefined ? base.zero_depreciation : !!o.zero_depreciation,
      consumables: o.consumables === undefined ? base.consumables : !!o.consumables
    };
  }

  function echoInputs(inp) {
    return {
      vehicle_age_months: inp.vehicle_age_months,
      idv_inr: fmt(inp.idv_inr),
      market_value_inr: fmt(inp.market_value_inr),
      compulsory_deductible_inr: fmt(inp.compulsory_deductible_inr),
      voluntary_deductible_inr: fmt(inp.voluntary_deductible_inr),
      salvage_value_inr: fmt(inp.salvage_value_inr),
      zero_depreciation: inp.zero_depreciation,
      consumables: inp.consumables
    };
  }

  // ---------------------------------------------------------------- calculator (mirrors SettlementCalculator.calculate)

  function metalBp(age, schedule) {
    for (var i = 0; i < schedule.length; i++) {
      if (age <= parseInt(schedule[i].max_months, 10)) return bp(schedule[i].rate);
    }
    return 5000n;
  }

  function calculate(ctx, lines, opts) {
    opts = opts || {};
    var dep = ctx.data.depreciation;
    var addons = opts.addons || ctx.addons;
    var pathway = opts.pathway || "cashless";
    var salvage = opts.salvage === undefined ? ZERO : opts.salvage;
    var comp = opts.compulsory === undefined ? ctx.inp.compulsory_deductible_inr : opts.compulsory;
    var vol = opts.voluntary === undefined ? ctx.inp.voluntary_deductible_inr : opts.voluntary;
    var idv = ctx.inp.idv_inr;
    var age = ctx.inp.vehicle_age_months;

    var zdActive = !!addons.zero_depreciation && !!dep.zero_depreciation_addon_waives_part_depreciation;
    var consActive = !!addons.consumables && !!dep.consumables_addon_covers_consumables;
    var matRatioBp = bp(dep.part_category_rates.painting_material_component_ratio);

    var gross = ZERO;
    var depTotal = ZERO;
    var waiver = ZERO;
    var trace = [];

    lines.forEach(function (ln) {
      if (ln.amount <= ZERO) return;
      var amt = ln.amount;
      gross += amt;
      var rateBp;
      var note;
      if (ln.line_type === "labour") {
        rateBp = 0n;
        note = "Labour carries 0% depreciation";
      } else if (ln.line_type === "paint") {
        rateBp = (5000n * matRatioBp) / 10000n;
        note = "Painting material component (50% of paint cost @ 50% dep = 25%)";
      } else if (ln.line_type === "consumable" || ln.part_category === "consumables_default") {
        if (consActive) {
          rateBp = 0n;
          note = "Covered under Consumables Add-on (ADDON-CONS-01)";
        } else {
          rateBp = 10000n;
          note = "Consumables excluded without Consumables Add-on (100% deducted)";
        }
      } else if (ln.part_category === "metal") {
        rateBp = metalBp(age, dep.metal_wood_age_schedule);
        note = "Metal age-graded depreciation (" + age + " months age)";
      } else {
        var r = dep.part_category_rates[ln.part_category];
        rateBp = bp(r === undefined ? "0.00" : r);
        note = "Category '" + ln.part_category + "' standard rate";
      }
      var rawDep = mulDiv(amt, rateBp, 10000n);
      var applied;
      if (zdActive && (ln.line_type === "part" || ln.line_type === "paint") && rawDep > ZERO) {
        waiver += rawDep;
        applied = ZERO;
        note += " -> Waived by Zero Depreciation Add-on (ADDON-ZD-01)";
      } else {
        applied = rawDep;
      }
      depTotal += applied;
      trace.push({ raw: rawDep, applied: applied, net: amt - applied, note: note });
    });

    var ctlThreshold = mulDiv(idv, bp(dep.constructive_total_loss_idv_ratio_threshold), 10000n);
    var isTotalLoss = gross - depTotal >= ctlThreshold || pathway === "total_loss";
    var netBefore = isTotalLoss
      ? idv - comp - vol - salvage
      : gross - depTotal - comp - vol - salvage;
    var net = maxB(netBefore, ZERO);
    if (!isTotalLoss) net = minB(net, idv);

    return {
      gross: gross,
      dep: depTotal,
      waiver: waiver,
      comp: comp,
      vol: vol,
      salvage: salvage,
      net: net,
      isTotalLoss: isTotalLoss,
      ctlThreshold: ctlThreshold,
      trace: trace
    };
  }

  // ---------------------------------------------------------------- authority (mirrors resolve_required_authority)

  function resolveAuthority(doa, amount, claimType, conditions) {
    var tiers = doa.authority_tiers.slice().sort(function (a, b) {
      var x = parseMoney(a.max_settlement_inr);
      var y = parseMoney(b.max_settlement_inr);
      return x < y ? -1 : x > y ? 1 : 0;
    });
    var skipped = [];
    var resolved = null;
    for (var i = 0; i < tiers.length; i++) {
      var tier = tiers[i];
      var blocked = (tier.disallowed_conditions || []).filter(function (c) {
        return conditions.indexOf(c) !== -1;
      });
      if (amount > parseMoney(tier.max_settlement_inr)) {
        skipped.push({ role: tier.role, reason_code: "amount_exceeds_limit" });
      } else if (tier.allowed_claim_types.indexOf(claimType) === -1) {
        skipped.push({ role: tier.role, reason_code: "claim_type_not_allowed" });
      } else if (blocked.length > 0) {
        skipped.push({ role: tier.role, reason_code: "condition_blocked" });
      } else {
        resolved = tier;
        break;
      }
    }
    if (resolved === null) resolved = tiers[tiers.length - 1];
    var release = resolved.role;
    for (var j = 0; j < doa.authority_tiers.length; j++) {
      if (doa.authority_tiers[j].required_for_payment_release) {
        release = doa.authority_tiers[j].role;
        break;
      }
    }
    return {
      checker_role: resolved.role,
      max_settlement_inr: fmt(parseMoney(resolved.max_settlement_inr)),
      payment_release_role: release,
      skipped_tiers: skipped,
      rule_version: doa.rule_id + ":" + doa.version
    };
  }

  // ---------------------------------------------------------------- context

  function makeContext(data, inp) {
    var demo = data.demo;
    var ctx = {
      data: data,
      inp: inp,
      demo: demo,
      rule: data.scenario_rule,
      params: data.scenario_rule.parameters,
      labels: data.scenario_rule.labels,
      addons: { zero_depreciation: inp.zero_depreciation, consumables: inp.consumables }
    };
    ctx.quote = demo.quote_lines.map(function (q) {
      return {
        line: {
          id: q.id,
          part_code: q.part_code,
          description: q.description,
          part_category: q.part_category,
          line_type: q.line_type,
          amount: parseMoney(q.assessed_inr)
        },
        claimed: parseMoney(q.claimed_inr),
        assessed: parseMoney(q.assessed_inr),
        assessment_code: q.assessment_code === undefined ? null : q.assessment_code
      };
    });
    return ctx;
  }

  function label(ctx, key) {
    return ctx.labels[key];
  }

  function linesFrom(raw) {
    return raw.map(function (x) {
      return {
        id: x.id,
        part_code: x.part_code,
        description: x.description,
        part_category: x.part_category,
        line_type: x.line_type,
        amount: parseMoney(x.amount_inr)
      };
    });
  }

  function assessedLines(ctx) {
    return ctx.quote
      .filter(function (q) {
        return q.assessed > ZERO;
      })
      .map(function (q) {
        return q.line;
      });
  }

  function claimedTotal(ctx) {
    return sum(ctx.quote, function (q) {
      return q.claimed;
    });
  }

  function assessmentAdjustments(ctx) {
    return ctx.quote
      .filter(function (q) {
        return q.assessment_code && q.assessed !== q.claimed;
      })
      .map(function (q) {
        return [q.assessment_code, q.assessed - q.claimed];
      });
  }

  function view(ctx, lines, addons) {
    var res = calculate(ctx, lines, { addons: addons });
    var tariff = calculate(ctx, lines, { addons: { zero_depreciation: false, consumables: false } });
    var benefit = tariff.dep - res.dep;
    var running = res.gross - res.dep - res.comp - res.vol;
    return {
      gross: res.gross,
      tariffDep: tariff.dep,
      appliedDep: res.dep,
      zdBenefit: res.waiver,
      consBenefit: benefit - res.waiver,
      comp: res.comp,
      vol: res.vol,
      net: res.net,
      floorCap: res.net - running,
      result: res
    };
  }

  function clauseRecords(ctx, meta) {
    var out = [];
    meta.clauses.forEach(function (ref) {
      if (ref.when === "zd_active" && !ctx.inp.zero_depreciation) return;
      if (ref.when === "cons_active" && !ctx.inp.consumables) return;
      var c = ctx.data.clauses[ref.id];
      out.push({
        clause_id: c.clause_id,
        document_id: ctx.rule.policy_document_id,
        page: c.page,
        title: c.title,
        applied_for: ref.applied_for
      });
    });
    return out;
  }

  function approval(ctx, amount, claimType, conditions, assessorNote) {
    var auth = resolveAuthority(ctx.data.doa, amount, claimType, conditions);
    return {
      recommended_by: label(ctx, "role_settlement_agent"),
      maker: label(ctx, "role_maker"),
      checker_role: auth.checker_role,
      checker_label: label(ctx, "role_" + auth.checker_role),
      authority_limit_inr: auth.max_settlement_inr,
      authority_amount_inr: fmt(amount),
      payment_release_role: auth.payment_release_role,
      payment_release_label: label(ctx, "role_" + auth.payment_release_role),
      skipped_tiers: auth.skipped_tiers.map(function (t) {
        return {
          role: t.role,
          label: label(ctx, "role_" + t.role),
          reason_code: t.reason_code,
          reason: label(ctx, "skip_" + t.reason_code)
        };
      }),
      assessor_note: assessorNote ? label(ctx, assessorNote) : null,
      maker_checker_note: label(ctx, "maker_checker_note"),
      demo_note: label(ctx, "approval_demo_note"),
      rule_version: auth.rule_version
    };
  }

  function item(ctx, code, amount, clauseId) {
    var out = { code: code, label: label(ctx, code), amount: fmt(amount) };
    if (clauseId !== undefined && clauseId !== null) out.clause_id = clauseId;
    return out;
  }

  // ---------------------------------------------------------------- scenario assembly (mirrors _assemble)

  function assemble(ctx, meta, a) {
    var adjustments = a.adjustments;
    var withheld = a.withheld;
    var assessed = a.claimed + sum(adjustments, function (x) { return x[1]; });
    var approved = assessed + sum(withheld, function (x) { return x[1]; });
    var deductions = a.deductions.filter(function (d) { return d[1] !== ZERO; });
    var benefits = a.benefits.filter(function (b) { return b[1] !== ZERO; });

    var recon = [];
    adjustments.concat(withheld).forEach(function (x) {
      recon.push(item(ctx, x[0], x[1]));
    });
    deductions.forEach(function (d) {
      recon.push(item(ctx, d[0], -d[1], d[2]));
    });
    benefits.forEach(function (b) {
      recon.push(item(ctx, b[0], b[1], b[2]));
    });
    if (a.floorCap !== ZERO) recon.push(item(ctx, "floor_cap", a.floorCap, "SEC-1-6"));
    var effect = sum(recon, function (r) { return parseMoney(r.amount); });

    return {
      scenario_code: meta.code,
      number: meta.number,
      label: meta.label,
      group: meta.group,
      pathway: meta.pathway,
      status: meta.status,
      summary: meta.summary,
      assumptions: meta.assumptions.slice(),
      claimed: { amount: fmt(a.claimed), basis: label(ctx, a.claimedBasis) },
      assessed: {
        amount: fmt(assessed),
        adjustments: adjustments.map(function (x) { return item(ctx, x[0], x[1]); })
      },
      approved: {
        amount: fmt(approved),
        withheld: withheld.map(function (x) { return item(ctx, x[0], x[1]); })
      },
      deducted: {
        total: fmt(sum(deductions, function (d) { return d[1]; })),
        items: deductions.map(function (d) { return item(ctx, d[0], d[1], d[2]); })
      },
      addon_benefits: {
        total: fmt(sum(benefits, function (b) { return b[1]; })),
        items: benefits.map(function (b) { return item(ctx, b[0], b[1], b[2]); })
      },
      net_payable: fmt(a.net),
      policy_clauses: clauseRecords(ctx, meta),
      approval: approval(ctx, a.authAmount, a.authClaimType, a.authConditions, a.assessorNote),
      customer_receives: {
        amount: fmt(a.net),
        payee: label(ctx, a.payee),
        outcome: label(ctx, a.outcome),
        customer_pays: fmt(a.customerPays)
      },
      why_different: {
        requested: fmt(a.claimed),
        receives: fmt(a.net),
        gap: fmt(a.claimed - a.net),
        items: recon,
        balanced: a.claimed + effect === a.net
      },
      insurer_net_cost: fmt(a.insurerNetCost === undefined ? a.net : a.insurerNetCost),
      comparison: a.comparison
    };
  }

  function repairDeductions(v) {
    return {
      deductions: [
        ["tariff_depreciation", v.tariffDep, "SEC-1-2"],
        ["compulsory_excess", v.comp, "SEC-1-5"],
        ["voluntary_excess", v.vol, "SEC-1-5"]
      ],
      benefits: [
        ["addon_zero_dep", v.zdBenefit, "ADDON-ZD-01"],
        ["addon_consumables", v.consBenefit, "ADDON-CONS-01"]
      ]
    };
  }

  function option(ctx, code, v) {
    return {
      code: code,
      label: label(ctx, "option_" + code),
      gross_inr: fmt(v.gross),
      applied_depreciation_inr: fmt(v.appliedDep),
      net_payable_inr: fmt(v.net)
    };
  }

  // ---------------------------------------------------------------- scenarios

  function cashless(ctx, meta, base) {
    var rd = repairDeductions(base);
    return assemble(ctx, meta, {
      claimed: claimedTotal(ctx), claimedBasis: "basis_garage_quote",
      adjustments: assessmentAdjustments(ctx), withheld: [],
      deductions: rd.deductions, benefits: rd.benefits, floorCap: base.floorCap, net: base.net,
      customerPays: base.gross - base.net,
      payee: "payee_network_garage", outcome: "outcome_cashless",
      authAmount: base.net, authClaimType: meta.claim_type, authConditions: [],
      assessorNote: "assessor_decision_none", comparison: {}
    });
  }

  function reimbursement(ctx, meta, base) {
    var rd = repairDeductions(base);
    var claimed = claimedTotal(ctx);
    return assemble(ctx, meta, {
      claimed: claimed, claimedBasis: "basis_garage_quote",
      adjustments: assessmentAdjustments(ctx), withheld: [],
      deductions: rd.deductions, benefits: rd.benefits, floorCap: base.floorCap, net: base.net,
      customerPays: claimed - base.net,
      payee: "payee_customer", outcome: "outcome_reimbursement",
      authAmount: base.net, authClaimType: meta.claim_type, authConditions: [],
      assessorNote: "assessor_decision_none",
      comparison: {
        customer_funds_upfront_inr: fmt(claimed),
        reimbursed_inr: fmt(base.net),
        customer_pays_if_cashless_inr: fmt(base.gross - base.net),
        customer_pays_if_reimbursed_inr: fmt(claimed - base.net),
        documents_required: ctx.params.reimbursement_documents.slice()
      }
    });
  }

  function repairVsReplacement(ctx, meta, base) {
    var alt = ctx.demo.repair_alternative;
    var replaced = alt.replaces_line_ids;
    var repairLines = ctx.quote
      .filter(function (q) { return q.assessed > ZERO && replaced.indexOf(q.line.id) === -1; })
      .map(function (q) { return q.line; })
      .concat(linesFrom(alt.lines));
    var repair = view(ctx, repairLines);
    var substitution = repair.gross - base.gross;
    var rd = repairDeductions(repair);
    return assemble(ctx, meta, {
      claimed: claimedTotal(ctx), claimedBasis: "basis_garage_quote",
      adjustments: assessmentAdjustments(ctx).concat([["repair_substitution", substitution]]), withheld: [],
      deductions: rd.deductions, benefits: rd.benefits, floorCap: repair.floorCap, net: repair.net,
      customerPays: repair.gross - repair.net,
      payee: "payee_network_garage", outcome: "outcome_repair",
      authAmount: repair.net, authClaimType: meta.claim_type, authConditions: [],
      assessorNote: "assessor_decision_none",
      comparison: {
        options: [option(ctx, "replace", base), option(ctx, "repair", repair)],
        recommended_option: repair.net < base.net ? "repair" : "replace",
        insurer_saving_inr: fmt(base.net - repair.net)
      }
    });
  }

  function partialApproval(ctx, meta, base) {
    var cfg = ctx.demo.partial_approval;
    var heldIds = cfg.withheld_line_ids;
    var held = ctx.quote.filter(function (q) { return heldIds.indexOf(q.line.id) !== -1 && q.assessed > ZERO; });
    var kept = ctx.quote
      .filter(function (q) { return q.assessed > ZERO && heldIds.indexOf(q.line.id) === -1; })
      .map(function (q) { return q.line; });
    var partial = view(ctx, kept);
    var rd = repairDeductions(partial);
    var heldTotal = sum(held, function (q) { return q.assessed; });
    return assemble(ctx, meta, {
      claimed: claimedTotal(ctx), claimedBasis: "basis_garage_quote",
      adjustments: assessmentAdjustments(ctx),
      withheld: heldTotal !== ZERO ? [[cfg.reason_code, -heldTotal]] : [],
      deductions: rd.deductions, benefits: rd.benefits, floorCap: partial.floorCap, net: partial.net,
      customerPays: base.gross - partial.net,
      payee: "payee_network_garage", outcome: "outcome_partial",
      authAmount: partial.net, authClaimType: meta.claim_type, authConditions: [],
      assessorNote: "assessor_decision_holdback",
      comparison: {
        withheld_lines: held.map(function (q) {
          return {
            line_id: q.line.id,
            part_code: q.line.part_code,
            description: q.line.description,
            amount_inr: fmt(q.assessed)
          };
        }),
        net_if_released_inr: fmt(base.net),
        additional_payable_on_release_inr: fmt(base.net - partial.net)
      }
    });
  }

  function supplementary(ctx, meta, base) {
    var supp = linesFrom(ctx.demo.supplementary_lines);
    var suppTotal = sum(supp, function (l) { return l.amount; });
    var revised = view(ctx, assessedLines(ctx).concat(supp));
    var thrBp = bp(ctx.params.supplementary_reinspection_variance_threshold);
    var reinspect = base.gross !== ZERO ? suppTotal * 10000n >= thrBp * base.gross : false;
    var rd = repairDeductions(revised);
    return assemble(ctx, meta, {
      claimed: claimedTotal(ctx) + suppTotal, claimedBasis: "basis_garage_quote_plus_supplementary",
      adjustments: assessmentAdjustments(ctx), withheld: [],
      deductions: rd.deductions, benefits: rd.benefits, floorCap: revised.floorCap, net: revised.net,
      customerPays: revised.gross - revised.net,
      payee: "payee_network_garage", outcome: "outcome_supplementary",
      authAmount: revised.net, authClaimType: meta.claim_type, authConditions: [],
      assessorNote: reinspect ? "assessor_decision_reinspection" : "assessor_decision_no_reinspection",
      comparison: {
        initial_net_inr: fmt(base.net),
        revised_net_inr: fmt(revised.net),
        incremental_payable_inr: fmt(revised.net - base.net),
        supplementary_assessed_inr: fmt(suppTotal),
        cumulative_gross_inr: fmt(revised.gross),
        variance_ratio: ratio4(suppTotal, base.gross),
        variance_threshold: fmtBp4(thrBp),
        reinspection_required: reinspect,
        lines: supp.map(function (l) {
          return { part_code: l.part_code, description: l.description, amount_inr: fmt(l.amount) };
        })
      }
    });
  }

  function totalLoss(ctx, meta) {
    var inp = ctx.inp;
    var res = calculate(ctx, [], { pathway: "total_loss" });
    var claimed = inp.market_value_inr;
    var running = inp.idv_inr - res.comp - res.vol;
    return assemble(ctx, meta, {
      claimed: claimed, claimedBasis: "basis_market_value",
      adjustments: [["idv_basis", inp.idv_inr - claimed]], withheld: [],
      deductions: [
        ["compulsory_excess", res.comp, "SEC-1-5"],
        ["voluntary_excess", res.vol, "SEC-1-5"]
      ],
      benefits: [], floorCap: res.net - running, net: res.net,
      customerPays: res.comp + res.vol,
      payee: "payee_customer", outcome: "outcome_total_loss",
      authAmount: res.net, authClaimType: meta.claim_type, authConditions: ["total_loss"],
      assessorNote: null,
      comparison: {
        idv_inr: fmt(inp.idv_inr),
        market_value_inr: fmt(claimed),
        shortfall_vs_market_inr: fmt(maxB(claimed - inp.idv_inr, ZERO)),
        surrender_net_inr: fmt(res.net)
      }
    });
  }

  function constructiveTotalLoss(ctx, meta) {
    var inp = ctx.inp;
    var spec = ctx.demo.stress_ctl_line;
    var stressAmount = mulDiv(inp.idv_inr, bp(ctx.params.ctl_stress_repair_ratio_of_idv), 10000n);
    var stress = {
      id: "CTL1",
      part_code: spec.part_code,
      description: spec.description,
      part_category: spec.part_category,
      line_type: spec.line_type,
      amount: stressAmount
    };
    var test = calculate(ctx, [stress]);
    var triggered = test.isTotalLoss;
    var surrenderNet = maxB(inp.idv_inr - test.comp - test.vol, ZERO);
    var comparison = {
      stress_estimate_inr: fmt(stressAmount),
      net_repair_inr: fmt(test.gross - test.dep),
      ctl_threshold_inr: fmt(test.ctlThreshold),
      ctl_triggered: triggered,
      surrender_net_inr: fmt(surrenderNet)
    };
    if (!triggered) {
      var v = view(ctx, [stress]);
      var rd = repairDeductions(v);
      return assemble(ctx, meta, {
        claimed: stressAmount, claimedBasis: "basis_repair_estimate",
        adjustments: [], withheld: [], deductions: rd.deductions, benefits: rd.benefits,
        floorCap: v.floorCap, net: v.net, customerPays: v.gross - v.net,
        payee: "payee_network_garage", outcome: "outcome_ctl_not_triggered",
        authAmount: v.net, authClaimType: "cashless", authConditions: [],
        assessorNote: null, comparison: comparison
      });
    }
    var res = calculate(ctx, [stress], { pathway: "total_loss", salvage: inp.salvage_value_inr });
    var running = inp.idv_inr - res.comp - res.vol - res.salvage;
    comparison.retention_net_inr = fmt(res.net);
    return assemble(ctx, meta, {
      claimed: stressAmount, claimedBasis: "basis_repair_estimate",
      adjustments: [["idv_basis", inp.idv_inr - stressAmount]], withheld: [],
      deductions: [
        ["compulsory_excess", res.comp, "SEC-1-5"],
        ["voluntary_excess", res.vol, "SEC-1-5"],
        ["salvage_retained", res.salvage, "SEC-1-7"]
      ],
      benefits: [], floorCap: res.net - running, net: res.net,
      customerPays: res.comp + res.vol,
      payee: "payee_customer", outcome: "outcome_ctl_retention",
      authAmount: res.net, authClaimType: meta.claim_type, authConditions: ["total_loss"],
      assessorNote: null, comparison: comparison
    });
  }

  function salvageRecovery(ctx, meta) {
    var inp = ctx.inp;
    var surrender = calculate(ctx, [], { pathway: "total_loss" });
    var retention = calculate(ctx, [], { pathway: "total_loss", salvage: inp.salvage_value_inr });
    var proceeds = inp.salvage_value_inr;
    var disposal = mulDiv(proceeds, bp(ctx.params.salvage_disposal_cost_ratio), 10000n);
    var netRecovery = proceeds - disposal;
    var surrenderCost = surrender.net - netRecovery;
    var claimed = inp.market_value_inr;
    var running = inp.idv_inr - surrender.comp - surrender.vol;
    var saleAuth = approval(ctx, netRecovery, "total_loss", [], null);
    return assemble(ctx, meta, {
      claimed: claimed, claimedBasis: "basis_market_value",
      adjustments: [["idv_basis", inp.idv_inr - claimed]], withheld: [],
      deductions: [
        ["compulsory_excess", surrender.comp, "SEC-1-5"],
        ["voluntary_excess", surrender.vol, "SEC-1-5"]
      ],
      benefits: [], floorCap: surrender.net - running, net: surrender.net,
      customerPays: surrender.comp + surrender.vol,
      payee: "payee_customer", outcome: "outcome_total_loss",
      authAmount: surrender.net, authClaimType: meta.claim_type, authConditions: ["total_loss"],
      assessorNote: null,
      insurerNetCost: surrenderCost,
      comparison: {
        surrender: {
          customer_payout_inr: fmt(surrender.net),
          salvage_proceeds_inr: fmt(proceeds),
          disposal_cost_inr: fmt(disposal),
          net_recovery_inr: fmt(netRecovery),
          insurer_net_cost_inr: fmt(surrenderCost)
        },
        retention: {
          customer_payout_inr: fmt(retention.net),
          insurer_net_cost_inr: fmt(retention.net)
        },
        retention_saving_for_insurer_inr: fmt(surrenderCost - retention.net),
        salvage_sale_checker_role: saleAuth.checker_role,
        salvage_sale_checker_label: saleAuth.checker_label
      }
    });
  }

  function addonScenario(ctx, meta, key) {
    var lines = assessedLines(ctx);
    var other = key === "zero_depreciation" ? "consumables" : "zero_depreciation";
    var heldAddons = {};
    heldAddons[other] = !!ctx.addons[other];
    function withKey(on) {
      var a = {};
      a[other] = heldAddons[other];
      a[key] = on;
      return a;
    }
    var withAddon = view(ctx, lines, withKey(true));
    var without = view(ctx, lines, withKey(false));
    var rd = repairDeductions(withAddon);
    return assemble(ctx, meta, {
      claimed: claimedTotal(ctx), claimedBasis: "basis_garage_quote",
      adjustments: assessmentAdjustments(ctx), withheld: [],
      deductions: rd.deductions, benefits: rd.benefits, floorCap: withAddon.floorCap, net: withAddon.net,
      customerPays: withAddon.gross - withAddon.net,
      payee: "payee_network_garage", outcome: "outcome_addon",
      authAmount: withAddon.net, authClaimType: meta.claim_type, authConditions: [],
      assessorNote: "assessor_decision_none",
      comparison: {
        active_on_policy: !!ctx.addons[key],
        with_addon: {
          applied_depreciation_inr: fmt(withAddon.appliedDep),
          net_payable_inr: fmt(withAddon.net)
        },
        without_addon: {
          applied_depreciation_inr: fmt(without.appliedDep),
          net_payable_inr: fmt(without.net)
        },
        benefit_inr: fmt(withAddon.net - without.net)
      }
    });
  }

  function differentDeductibles(ctx, meta, base) {
    var lines = assessedLines(ctx);
    var classes = ctx.params.deductible_matrix_vehicle_classes;
    var voluntary = ctx.params.voluntary_deductible_options_inr.map(parseMoney);
    var compMap = ctx.data.depreciation.compulsory_deductible_by_vehicle_class_inr;
    var matrix = classes.map(function (vehicleClass) {
      var comp = parseMoney(compMap[vehicleClass]);
      return {
        vehicle_class: vehicleClass,
        compulsory_inr: fmt(comp),
        cells: voluntary.map(function (vol) {
          return {
            voluntary_inr: fmt(vol),
            net_payable_inr: fmt(calculate(ctx, lines, { compulsory: comp, voluntary: vol }).net)
          };
        })
      };
    });
    var rd = repairDeductions(base);
    return assemble(ctx, meta, {
      claimed: claimedTotal(ctx), claimedBasis: "basis_garage_quote",
      adjustments: assessmentAdjustments(ctx), withheld: [],
      deductions: rd.deductions, benefits: rd.benefits, floorCap: base.floorCap, net: base.net,
      customerPays: base.gross - base.net,
      payee: "payee_network_garage", outcome: "outcome_deductible",
      authAmount: base.net, authClaimType: meta.claim_type, authConditions: [],
      assessorNote: "assessor_decision_none",
      comparison: {
        current_compulsory_inr: fmt(base.comp),
        current_voluntary_inr: fmt(base.vol),
        voluntary_options_inr: voluntary.map(fmt),
        matrix: matrix
      }
    });
  }

  function underinsurance(ctx, meta, base) {
    var inp = ctx.inp;
    var lossAfterDep = base.gross - base.appliedDep;
    var under = inp.market_value_inr > ZERO && inp.idv_inr < inp.market_value_inr;
    var proRated = under ? mulDiv(lossAfterDep, inp.idv_inr, inp.market_value_inr) : lossAfterDep;
    var reduction = lossAfterDep - proRated;
    var running = proRated - base.comp - base.vol;
    var net = minB(maxB(running, ZERO), inp.idv_inr);
    var rd = repairDeductions(base);
    rd.deductions.splice(1, 0, ["pro_rata", reduction, "SEC-1-6"]);
    return assemble(ctx, meta, {
      claimed: claimedTotal(ctx), claimedBasis: "basis_garage_quote",
      adjustments: assessmentAdjustments(ctx), withheld: [],
      deductions: rd.deductions, benefits: rd.benefits, floorCap: net - running, net: net,
      customerPays: base.gross - net,
      payee: "payee_network_garage", outcome: "outcome_pro_rata",
      authAmount: net, authClaimType: meta.claim_type, authConditions: [],
      assessorNote: "assessor_decision_none",
      comparison: {
        idv_inr: fmt(inp.idv_inr),
        market_value_inr: fmt(inp.market_value_inr),
        idv_ratio: ratio4(inp.idv_inr, inp.market_value_inr),
        underinsured: under,
        shortfall_on_total_loss_inr: fmt(maxB(inp.market_value_inr - inp.idv_inr, ZERO)),
        idv_cap_inr: fmt(inp.idv_inr),
        net_without_pro_rata_inr: fmt(base.net),
        net_with_pro_rata_inr: fmt(net),
        pro_rata_reduction_inr: fmt(reduction)
      }
    });
  }

  // ---------------------------------------------------------------- ledger and trace

  function ledger(ctx, base) {
    var steps = [];
    var running = ZERO;
    function add(key, sign, amount, clauseId) {
      running = sign === "+" ? running + amount : running - amount;
      var step = { key: key, label: label(ctx, key), sign: sign, amount: fmt(amount), running_total: fmt(running) };
      if (clauseId) step.clause_id = clauseId;
      steps.push(step);
    }
    add("approved_amount", "+", base.gross, "SEC-1-1");
    add("tariff_depreciation", "-", base.tariffDep, "SEC-1-2");
    add("addon_zero_dep", "+", base.zdBenefit, "ADDON-ZD-01");
    add("addon_consumables", "+", base.consBenefit, "ADDON-CONS-01");
    add("compulsory_excess", "-", base.comp, "SEC-1-5");
    add("voluntary_excess", "-", base.vol, "SEC-1-5");
    add("other_deductions", "-", ZERO);
    if (base.floorCap !== ZERO) {
      add("floor_cap", base.floorCap > ZERO ? "+" : "-", base.floorCap < ZERO ? -base.floorCap : base.floorCap, "SEC-1-6");
    }
    return { steps: steps, net_payable: fmt(base.net) };
  }

  function lineTrace(ctx, base) {
    var idx = 0;
    return ctx.quote.map(function (q) {
      var common = {
        line_id: q.line.id,
        part_code: q.line.part_code,
        description: q.line.description,
        line_type: q.line.line_type,
        claimed_inr: fmt(q.claimed),
        assessed_inr: fmt(q.assessed)
      };
      if (q.assessed > ZERO) {
        var t = base.result.trace[idx++];
        common.approved_inr = fmt(q.assessed);
        common.raw_depreciation_inr = fmt(t.raw);
        common.applied_depreciation_inr = fmt(t.applied);
        common.net_line_inr = fmt(t.net);
        common.note = t.note;
      } else {
        common.approved_inr = fmt(ZERO);
        common.raw_depreciation_inr = fmt(ZERO);
        common.applied_depreciation_inr = fmt(ZERO);
        common.net_line_inr = fmt(ZERO);
        common.note = label(ctx, q.assessment_code || "duplicate_line");
      }
      common.assessment_code = q.assessment_code;
      return common;
    });
  }

  // ---------------------------------------------------------------- public API

  function build(data, inputs) {
    var inp = inputs || defaultInputs(data);
    var ctx = makeContext(data, inp);
    var base = view(ctx, assessedLines(ctx));
    var builders = {
      cashless_repair: function (m) { return cashless(ctx, m, base); },
      reimbursement: function (m) { return reimbursement(ctx, m, base); },
      repair_vs_replacement: function (m) { return repairVsReplacement(ctx, m, base); },
      partial_approval: function (m) { return partialApproval(ctx, m, base); },
      supplementary_estimate: function (m) { return supplementary(ctx, m, base); },
      total_loss: function (m) { return totalLoss(ctx, m); },
      constructive_total_loss: function (m) { return constructiveTotalLoss(ctx, m); },
      salvage_recovery: function (m) { return salvageRecovery(ctx, m); },
      zero_dep_addon: function (m) { return addonScenario(ctx, m, "zero_depreciation"); },
      consumables_addon: function (m) { return addonScenario(ctx, m, "consumables"); },
      different_deductibles: function (m) { return differentDeductibles(ctx, m, base); },
      underinsurance_idv: function (m) { return underinsurance(ctx, m, base); }
    };
    var scenarios = ctx.rule.scenarios.map(function (meta) {
      return builders[meta.code](meta);
    });
    var dep = data.depreciation;
    return {
      claim_ref: ctx.demo.claim_ref,
      title: ctx.demo.title,
      disclaimer: ctx.demo.disclaimer,
      inputs: echoInputs(inp),
      parameters: ctx.params,
      rule_versions: {
        depreciation: dep.rule_id + ":" + dep.version,
        authority: data.doa.rule_id + ":" + data.doa.version,
        scenarios: ctx.rule.rule_id + ":" + ctx.rule.version
      },
      summary: {
        claimed_inr: fmt(claimedTotal(ctx)),
        assessed_inr: fmt(base.gross),
        net_payable_inr: fmt(base.net),
        scenario_count: scenarios.length
      },
      ledger: ledger(ctx, base),
      line_trace: lineTrace(ctx, base),
      scenarios: scenarios
    };
  }

  return {
    build: build,
    defaultInputs: defaultInputs,
    inputsFromMapping: inputsFromMapping,
    parseMoney: parseMoney,
    formatMoney: fmt
  };
});
