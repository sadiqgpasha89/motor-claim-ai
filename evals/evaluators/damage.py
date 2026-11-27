"""Damage AI: classification precision/recall, image-quality gating and confidence calibration."""

from __future__ import annotations

from contextlib import nullcontext

from evals.core import AgentEval, CaseResult, Checks, load_dataset
from evals.harness import model_outage, run_agent, split_request
from evals.metrics import brier_score, expected_calibration_error, precision_recall_f1, r4, rate, safe_div

AGENT = "damage_assessment"


def evaluate() -> AgentEval:
    ds = load_dataset("damage")
    results: list[CaseResult] = []
    tp = fp = fn = 0
    calib: list[tuple[float, bool]] = []
    recapture_hits: list[bool] = []
    quality_ok = quality_total = 0
    uncertain_escalated: list[bool] = []
    over_cap = 0
    obs_total = 0

    for case in ds.cases:
        raw = dict(case.input)
        outage = bool(raw.pop("_outage", False))
        facts, req = split_request(raw)
        with model_outage() if outage else nullcontext():
            resp = run_agent(AGENT, facts, **req)
        exp = case.expected
        res = resp.result
        ck = Checks()
        scored = not case.known_gap

        ck.eq("status", resp.status.value, exp["status"])
        if "routing" in exp:
            ck.eq("routing", resp.decision.routing_outcome if resp.decision else None, exp["routing"])
        if "next" in exp:
            ck.eq("next_action", resp.suggested_next_action, exp["next"])
        if outage:
            ck.eq("fallback_mode", res.get("fallback_mode"), exp.get("fallback"))
            results.append(ck.result(case, AGENT))
            continue

        observations = res.get("observations", [])
        got = {(o["damaged_component"], o["repairability"]) for o in observations}
        want = {(c["component"], c["repairability"]) for c in exp.get("components", [])}
        if "components" in exp:
            ck.expect("components_present", want <= got, observed=sorted(got), expected=sorted(want))
            if scored:
                got_names = {g[0] for g in got}
                want_names = {w[0] for w in want}
                # Component *detection* is scored on names; repairability correctness feeds calibration below.
                tp += len(got_names & want_names)
                fp += len(got_names - want_names)
                fn += len(want_names - got_names)
        for o in observations:
            conf = float(o.get("component_confidence", o.get("confidence", 0.0)))
            if "components" in exp and scored:
                correct = (o["damaged_component"], o["repairability"]) in want
                calib.append((conf, correct))
            obs_total += 1
        for part in exp.get("part_codes_include", []):
            ck.expect(f"part[{part}]", part in {o.get("part_code") for o in observations})
        if "recapture" in exp:
            ck.eq("recapture_files", sorted(res["recapture_required_files"]), sorted(exp["recapture"]))
            if scored:
                recapture_hits.append(sorted(res["recapture_required_files"]) == sorted(exp["recapture"]))
        if "image_quality" in exp:
            ok = ck.eq("image_quality", res["overall_image_quality"], exp["image_quality"])
            if scored:
                quality_total += 1
                quality_ok += int(ok)
        for angle in exp.get("missing_angles_include", []):
            ck.expect(f"missing_angle[{angle}]", angle in res["missing_angles"], observed=res["missing_angles"])
        if "inconsistency" in exp:
            ck.expect(
                "inconsistency",
                exp["inconsistency"] in {i.get("type") for i in res["inconsistencies"]},
                observed=[i.get("type") for i in res["inconsistencies"]],
            )
        for task in exp.get("tasks", []):
            made = [a for a in resp.actions_executed if a.action_type == "create_claim_task"]
            ck.expect(
                f"task[{task}]",
                any(task in str(a.payload) + a.summary for a in made),
                observed=[a.summary for a in made],
            )
        for tool in exp.get("tools", []):
            ck.expect(f"tool[{tool}]", tool in {a.action_type for a in resp.actions_executed})
        for code in exp.get("reason_codes_include", []):
            ck.expect(f"reason_code[{code}]", code in (resp.decision.reason_codes if resp.decision else []))
        if exp.get("ev_alert"):
            ck.expect("ev_safety_alerts", bool(res.get("ev_safety_alerts")))
        if "confidence_max" in exp:
            ok = resp.confidence <= exp["confidence_max"]
            ck.expect("confidence_max", ok, observed=resp.confidence, expected=f"<={exp['confidence_max']}")
            over_cap += int(not ok)
        if exp.get("uncertain_requires_human") and scored:
            uncertain_escalated.append(resp.status.value == "needs_human")
        if "no_text_echo" in exp:
            ck.expect(
                "injection_not_echoed_in_conf",
                all(float(o.get("component_confidence", 0)) < 0.99 for o in observations),
            )
        results.append(ck.result(case, AGENT))

    prf = precision_recall_f1(tp, fp, fn)
    confs = [c for c, _ in calib]
    outcomes = [ok for _, ok in calib]
    metrics = {
        "classification_precision": r4(prf["precision"]),
        "classification_recall": r4(prf["recall"]),
        "classification_f1": r4(prf["f1"]),
        "image_quality_accuracy": r4(safe_div(quality_ok, quality_total)),
        "recapture_recall": r4(rate(recapture_hits)),
        "uncertain_escalation_recall": r4(rate(uncertain_escalated)),
        "confidence_ece": r4(expected_calibration_error(confs, outcomes)),
        "confidence_brier": r4(brier_score(confs, outcomes)),
        "confidence_over_cap_count": float(over_cap),
    }
    return AgentEval(agent=AGENT, metrics=metrics, cases=results)
