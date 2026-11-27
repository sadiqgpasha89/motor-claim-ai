"""Document Intelligence: OCR / field accuracy, validation precision, reconciliation and quarantine."""

from __future__ import annotations

from typing import Any

from evals.core import AgentEval, Case, CaseResult, Checks, load_dataset
from evals.harness import run_agent
from evals.metrics import char_accuracy, precision_recall_f1, r4, rate, safe_div, set_confusion
from evals.synthetic import ocr_noise_cases
from services.document_ai.processor import extract_document_facts

AGENT = "document_intelligence"


def _run_ocr(case: Case) -> dict[str, Any]:
    inp = case.input
    text = inp.get("text", "")
    return extract_document_facts(
        filename=inp["filename"],
        mime_type=inp["mime_type"],
        raw_bytes=text.encode("utf-8"),
        policy_number_expected=inp.get("policy_number", ""),
        vehicle_reg_expected=inp.get("vehicle_reg", ""),
        text_override=text or None,
    )


def evaluate() -> AgentEval:
    ds = load_dataset("document")
    results: list[CaseResult] = []

    field_hits = field_total = 0
    char_scores: list[float] = []
    val_tp = val_fp = val_fn = 0
    inj_pos: list[bool] = []
    inj_neg_flagged: list[bool] = []
    conflict_tp = conflict_fp = conflict_fn = 0
    routing_ok: list[bool] = []

    for case in ds.cases:
        ck = Checks()
        exp = case.expected
        if case.input["mode"] == "ocr":
            out = _run_ocr(case)
            by_name = {f["field_name"]: f for f in out["facts"]}
            for name, want in exp.get("fields", {}).items():
                got = by_name.get(name, {})
                value_ok = got.get("extracted_value") == want["value"]
                ck.expect(f"{name}.value", value_ok, observed=got.get("extracted_value"), expected=want["value"])
                ck.expect(
                    f"{name}.status",
                    got.get("validation_status") == want["status"],
                    observed=got.get("validation_status"),
                    expected=want["status"],
                )
                if not case.known_gap:
                    field_total += 1
                    field_hits += int(value_ok)
                    char_scores.append(char_accuracy(str(got.get("extracted_value", "")), want["value"]))
                    predicted_mismatch = got.get("validation_status") == "mismatch"
                    true_mismatch = want["status"] == "mismatch"
                    val_tp += int(predicted_mismatch and true_mismatch)
                    val_fp += int(predicted_mismatch and not true_mismatch)
                    val_fn += int((not predicted_mismatch) and true_mismatch)
            for name in exp.get("absent", []):
                ck.expect(f"{name}.absent", name not in by_name, observed=sorted(by_name))
            ck.eq("injection_flagged", out["prompt_injection_flagged"], exp["injection"])
            for banned in exp.get("sanitized_excludes", []):
                ck.expect(f"sanitized_excludes[{banned[:18]}]", banned.lower() not in out["sanitized_text"].lower())
            if not case.known_gap:
                flagged = bool(out["prompt_injection_flagged"])
                if exp["injection"]:
                    inj_pos.append(flagged)
                else:
                    inj_neg_flagged.append(flagged)
        else:
            facts = {k: v for k, v in case.input.items() if k != "mode"}
            resp = run_agent(AGENT, facts)
            res = resp.result
            if "reconciliation_status" in exp:
                ck.eq("reconciliation_status", res["reconciliation_status"], exp["reconciliation_status"])
            ck.eq("agent_status", resp.status.value, exp["agent_status"])
            got_fields = {c["field_name"] for c in res["conflicts"]}
            ck.eq("conflict_fields", sorted(got_fields), sorted(exp["conflict_fields"]))
            ck.eq("routing", resp.decision.routing_outcome if resp.decision else None, exp["routing"])
            if "missing_core_docs" in exp:
                ck.eq("missing_core_docs", sorted(res["missing_core_docs"]), sorted(exp["missing_core_docs"]))
            if not case.known_gap:
                tp, fp, fn = set_confusion(got_fields, exp["conflict_fields"])
                conflict_tp, conflict_fp, conflict_fn = conflict_tp + tp, conflict_fp + fp, conflict_fn + fn
                routing_ok.append(resp.decision is not None and resp.decision.routing_outcome == exp["routing"])
        results.append(ck.result(case, AGENT))

    # Seeded OCR-noise robustness (statistical, regression-guarded against baseline)
    noisy_hits: list[bool] = []
    for case in ocr_noise_cases():
        out = _run_ocr(case)
        got = next((f["extracted_value"] for f in out["facts"] if f["field_name"] == "vehicle_registration"), "")
        noisy_hits.append(got == case.expected["fields"]["vehicle_registration"]["value"])

    val = precision_recall_f1(val_tp, val_fp, val_fn)
    conflicts = precision_recall_f1(conflict_tp, conflict_fp, conflict_fn)
    metrics = {
        "field_accuracy": r4(safe_div(field_hits, field_total)),
        "ocr_char_accuracy": r4(safe_div(sum(char_scores), len(char_scores))),
        "ocr_robustness_accuracy": r4(rate(noisy_hits)),
        "validation_precision": r4(val["precision"]),
        "validation_recall": r4(val["recall"]),
        "conflict_detection_f1": r4(conflicts["f1"]),
        "injection_detection_recall": r4(rate(inj_pos)),
        "injection_false_positive_rate": r4(safe_div(sum(inj_neg_flagged), len(inj_neg_flagged), default=0.0)),
        "routing_accuracy": r4(rate(routing_ok)),
    }
    return AgentEval(agent=AGENT, metrics=metrics, cases=results, extra={"ocr_noise_cases": len(noisy_hits)})
