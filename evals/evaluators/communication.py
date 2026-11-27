"""Customer Communication: factual accuracy, approved-template compliance, consent and adverse gating."""

from __future__ import annotations

from contextlib import nullcontext

from evals.core import AgentEval, CaseResult, Checks, load_dataset
from evals.harness import dump, model_outage, run_agent, split_request
from evals.metrics import r4, rate
from services.workflow.customer_experience import compose_state_aware_message

AGENT = "customer_communication"


def evaluate() -> AgentEval:
    ds = load_dataset("communication")
    results: list[CaseResult] = []
    factual: list[bool] = []
    template: list[bool] = []
    consent: list[bool] = []
    adverse: list[bool] = []
    locale: list[bool] = []

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
        if exp.get("no_actions"):
            ck.eq("no_actions", len(resp.actions_executed), 0)
            ck.eq("next_action", resp.suggested_next_action, exp["next"])
            ck.eq("fallback_mode", res.get("fallback_mode"), exp["fallback"])
            results.append(ck.result(case, AGENT))
            continue

        text = f"{res.get('subject', '')} {res.get('draft_message', '')}"
        if "contains" in exp or "not_contains" in exp:
            hits = [ck.expect(f"contains[{t}]", t in text, observed=text[:120]) for t in exp.get("contains", [])]
            hits += [
                ck.expect(f"not_contains[{t}]", t not in dump(resp), observed="present in response")
                for t in exp.get("not_contains", [])
            ]
            if scored:
                factual.append(all(hits))
        if exp.get("approved_template"):
            trigger = res["trigger_event"]
            ctx = {
                **facts,
                "claim_number": facts.get("claim_number", resp.claim_id if hasattr(resp, "claim_id") else ""),
            }
            approved = compose_state_aware_message(trigger, res["language"], ctx)
            ok = ck.eq("body_is_approved_template", res["draft_message"], approved["body"])
            if scored:
                template.append(ok)
        if "routing" in exp:
            ck.eq("routing", resp.decision.routing_outcome if resp.decision else None, exp["routing"])
        if "next" in exp:
            ck.eq("next_action", resp.suggested_next_action, exp["next"])
        if "trigger" in exp:
            ck.eq("trigger", res["trigger_event"], exp["trigger"])
        if "language" in exp:
            ok = ck.eq("language", res["language"], exp["language"])
            if exp.get("non_ascii"):
                ok = ck.expect("localised_script", any(ord(ch) > 127 for ch in res["draft_message"])) and ok
            if scored:
                locale.append(ok)
        action = resp.actions_executed[0] if resp.actions_executed else None
        if "action_status" in exp:
            ok = ck.eq("action_status", action.status if action else None, exp["action_status"])
            if scored:
                adverse.append(
                    ok and ck.items["status"] and ck.eq("requires_human_review", res["requires_human_review"], True)
                )
        if "effective_channel" in exp:
            ok = ck.eq("effective_channel", res["effective_channel"], exp["effective_channel"])
            if "wa_blocked" in exp:
                ok = ck.eq("wa_blocked", res["whatsapp_blocked_no_consent"], exp["wa_blocked"]) and ok
            if "sent_channel_not" in exp:
                ok = (
                    ck.expect(
                        "not_sent_on_blocked_channel",
                        action is not None and action.payload.get("channel") != exp["sent_channel_not"],
                        observed=action.payload.get("channel") if action else None,
                    )
                    and ok
                )
            for code in exp.get("reason_codes_include", []):
                ok = (
                    ck.expect(f"reason_code[{code}]", code in (resp.decision.reason_codes if resp.decision else []))
                    and ok
                )
            if scored:
                consent.append(ok)
        results.append(ck.result(case, AGENT))

    metrics = {
        "factual_accuracy": r4(rate(factual)),
        "approved_template_compliance": r4(rate(template)),
        "consent_compliance": r4(rate(consent)),
        "adverse_notice_gating": r4(rate(adverse)),
        "localisation_accuracy": r4(rate(locale)),
    }
    return AgentEval(agent=AGENT, metrics=metrics, cases=results)
