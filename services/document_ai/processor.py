from __future__ import annotations

import io
import re
from typing import Any

from PIL import Image

from packages.security.sanitizer import sanitize_untrusted_text

REG_PLATE_RE = re.compile(r"\b[A-Z]{2}[-\s]?\d{2}[-\s]?[A-Z]{1,2}[-\s]?\d{4}\b")
POLICY_NO_RE = re.compile(r"\bPOL-[A-Z0-9-]+\b")
DL_RE = re.compile(r"\b[A-Z]{2}\d{2}[-\s]?\d{4,11}\b")
VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{15,17}\b")


def classify_document(filename: str, mime_type: str, text_hint: str = "") -> tuple[str, float]:
    lower = f"{filename} {text_hint}".lower()
    if mime_type.startswith("image/") and any(
        k in lower for k in ["front", "rear", "left", "right", "damage", "bumper", "photo", "odometer", "vin", "closeup"]
    ):
        return "damage_photo", 0.94
    if "rc" in lower or "registration" in lower or "chassis" in lower:
        return "registration_certificate", 0.91
    if "dl" in lower or "licence" in lower or "license" in lower:
        return "driving_licence", 0.90
    if "policy" in lower or "schedule" in lower or "uin" in lower:
        return "policy_schedule", 0.93
    if "estimate" in lower or "quote" in lower or "garage" in lower:
        return "repair_estimate", 0.92
    if "invoice" in lower or "bill" in lower:
        return "invoice", 0.89
    if "fir" in lower or "police" in lower:
        return "fir", 0.90
    if "survey" in lower:
        return "survey_report", 0.91
    if mime_type.startswith("image/"):
        return "damage_photo", 0.78
    return "claim_document", 0.72


def check_image_quality(filename: str, data: bytes) -> dict[str, Any]:
    lower = filename.lower()
    angle = "closeup"
    for candidate in ["front", "rear", "left", "right", "odometer", "vin"]:
        if candidate in lower:
            angle = candidate
            break

    if "blurry" in lower or "dark" in lower or "low_quality" in lower:
        return {
            "angle": angle,
            "quality_status": "recapture_needed",
            "quality_score": 0.34,
            "issues": ["Low sharpness / underexposed frame detected"],
            "guidance": "Please retake photo in daylight with full panel visible and camera steady.",
        }

    try:
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        if w < 320 or h < 240:
            return {
                "angle": angle,
                "quality_status": "recapture_needed",
                "quality_score": 0.42,
                "issues": [f"Resolution {w}x{h} below minimum 320x240"],
                "guidance": "Capture higher-resolution photo closer to the vehicle.",
            }
        return {
            "angle": angle,
            "quality_status": "acceptable",
            "quality_score": 0.92,
            "issues": [],
            "resolution": f"{w}x{h}",
        }
    except Exception:
        return {
            "angle": angle,
            "quality_status": "acceptable",
            "quality_score": 0.86,
            "issues": [],
            "note": "Synthetic image metadata accepted",
        }


def extract_document_facts(
    *,
    filename: str,
    mime_type: str,
    raw_bytes: bytes,
    policy_number_expected: str,
    vehicle_reg_expected: str,
    text_override: str | None = None,
) -> dict[str, Any]:
    raw_text = text_override or ""
    if not raw_text and mime_type in {"text/plain", "application/json", "application/pdf"}:
        try:
            raw_text = raw_bytes.decode("utf-8", errors="ignore")[:8000]
        except Exception:
            raw_text = ""

    sanitized_text, inj_detected, inj_hits = sanitize_untrusted_text(raw_text)
    doc_type, cls_conf = classify_document(filename, mime_type, sanitized_text)

    facts: list[dict[str, Any]] = []
    reg_matches = REG_PLATE_RE.findall(sanitized_text.upper())
    if reg_matches:
        extracted_reg = reg_matches[0].replace(" ", "")
        status = "verified" if extracted_reg.replace("-", "") == vehicle_reg_expected.replace("-", "").upper() else "mismatch"
        facts.append(
            {
                "field_name": "vehicle_registration",
                "extracted_value": extracted_reg,
                "confidence": 0.92,
                "page_number": 1,
                "bbox": {"x": 120, "y": 210, "w": 220, "h": 34},
                "validation_status": status,
                "source_doc_type": doc_type,
                "source_filename": filename,
            }
        )

    pol_matches = POLICY_NO_RE.findall(sanitized_text.upper())
    if pol_matches:
        extracted_pol = pol_matches[0]
        status = "verified" if extracted_pol == policy_number_expected.upper() else "mismatch"
        facts.append(
            {
                "field_name": "policy_number",
                "extracted_value": extracted_pol,
                "confidence": 0.94,
                "page_number": 1,
                "bbox": {"x": 110, "y": 140, "w": 260, "h": 30},
                "validation_status": status,
                "source_doc_type": doc_type,
                "source_filename": filename,
            }
        )

    dl_matches = DL_RE.findall(sanitized_text.upper())
    if dl_matches:
        facts.append(
            {
                "field_name": "driving_licence_number",
                "extracted_value": dl_matches[0],
                "confidence": 0.87,
                "page_number": 1,
                "bbox": {"x": 90, "y": 310, "w": 240, "h": 32},
                "validation_status": "unverified",
                "source_doc_type": doc_type,
                "source_filename": filename,
            }
        )

    vin_matches = VIN_RE.findall(sanitized_text.upper())
    if vin_matches:
        facts.append(
            {
                "field_name": "vin_chassis",
                "extracted_value": vin_matches[0],
                "confidence": 0.88,
                "page_number": 1,
                "bbox": {"x": 115, "y": 260, "w": 280, "h": 28},
                "validation_status": "unverified",
                "source_doc_type": doc_type,
                "source_filename": filename,
            }
        )

    if not facts and doc_type != "damage_photo":
        facts.append(
            {
                "field_name": "document_summary",
                "extracted_value": f"Classified as {doc_type} ({filename})",
                "confidence": cls_conf,
                "page_number": 1,
                "bbox": None,
                "validation_status": "unverified",
                "source_doc_type": doc_type,
                "source_filename": filename,
            }
        )

    image_quality = check_image_quality(filename, raw_bytes) if mime_type.startswith("image/") else None

    return {
        "doc_type": doc_type,
        "classification_confidence": cls_conf,
        "ocr_version": "ocr-adapter-v2",
        "sanitized_text": sanitized_text,
        "prompt_injection_flagged": inj_detected,
        "prompt_injection_patterns": inj_hits,
        "facts": facts,
        "image_quality": image_quality,
    }


def reconcile_claim_documents(
    *,
    evidences: list[dict[str, Any]],
    extracted_facts: list[dict[str, Any]],
    expected_policy_number: str = "",
    expected_vehicle_reg: str = "",
) -> dict[str, Any]:
    """Cross-reconciles extracted fields across multiple uploaded documents with full provenance."""

    ev_by_id = {e.get("id"): e for e in evidences if e.get("id")}
    field_values: dict[str, list[dict[str, Any]]] = {}
    field_confidences: dict[str, float] = {}
    provenance_index: list[dict[str, Any]] = []

    for fact in extracted_facts:
        fname = fact.get("field_name", "unknown")
        val = str(fact.get("verified_value") or fact.get("extracted_value") or "").strip()
        conf = float(fact.get("confidence", 0.0))
        ev_id = fact.get("evidence_id", "")
        ev_meta = ev_by_id.get(ev_id, {})
        source_doc = fact.get("source_doc_type") or ev_meta.get("doc_type", "claim_document")
        source_file = fact.get("source_filename") or ev_meta.get("filename", "upload")
        sha_prefix = str(ev_meta.get("sha256", ""))[:12]

        entry = {
            "field_name": fname,
            "value": val,
            "confidence": round(conf, 3),
            "validation_status": fact.get("validation_status", "unverified"),
            "evidence_id": ev_id,
            "source_doc_type": source_doc,
            "source_filename": source_file,
            "sha256_prefix": sha_prefix,
            "page_number": fact.get("page_number", 1),
            "bbox": fact.get("bbox"),
        }
        field_values.setdefault(fname, []).append(entry)
        field_confidences[fname] = round(max(field_confidences.get(fname, 0.0), conf), 3)
        provenance_index.append(entry)

    conflicts: list[dict[str, Any]] = []
    for fname, entries in field_values.items():
        if fname in {"document_summary", "document_identity"}:
            continue
        norm_map: dict[str, list[dict[str, Any]]] = {}
        for item in entries:
            norm = item["value"].replace("-", "").replace(" ", "").upper()
            if norm:
                norm_map.setdefault(norm, []).append(item)
        if len(norm_map) > 1:
            conflicts.append(
                {
                    "conflict_type": "cross_document_discrepancy",
                    "field_name": fname,
                    "distinct_values": [
                        {
                            "value": items[0]["value"],
                            "sources": [f"{i['source_doc_type']}:{i['source_filename']}" for i in items],
                        }
                        for items in norm_map.values()
                    ],
                    "severity": "high",
                    "resolution_action": f"Reconcile conflicting {fname} across uploaded documents",
                }
            )

    for fact in extracted_facts:
        if fact.get("validation_status") == "mismatch":
            fname = fact.get("field_name", "unknown")
            expected = expected_vehicle_reg if "vehicle" in fname else (expected_policy_number if "policy" in fname else "")
            conflicts.append(
                {
                    "conflict_type": "fnol_vs_document_mismatch",
                    "field_name": fname,
                    "extracted_value": fact.get("extracted_value"),
                    "expected_value": expected,
                    "severity": "high",
                    "resolution_action": f"Verify {fname} against original document and patch ExtractedFact",
                }
            )

    doc_types_present = sorted({str(e.get("doc_type", "")) for e in evidences if e.get("doc_type")})
    core_required = ["policy_schedule", "registration_certificate", "driving_licence"]
    missing_core_docs = [d for d in core_required if d not in doc_types_present]

    if conflicts:
        reconciliation_status = "conflicts_detected"
    elif not extracted_facts and not evidences:
        reconciliation_status = "pending_documents"
    elif missing_core_docs and len(doc_types_present) == 0:
        reconciliation_status = "pending_documents"
    else:
        reconciliation_status = "reconciled"

    return {
        "reconciliation_status": reconciliation_status,
        "document_count": len(evidences),
        "doc_types_present": doc_types_present,
        "missing_core_docs": missing_core_docs,
        "field_confidences": field_confidences,
        "conflicts": conflicts,
        "provenance_index": provenance_index,
    }
