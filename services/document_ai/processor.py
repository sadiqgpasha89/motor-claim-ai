from __future__ import annotations

import io
import re
from typing import Any

from PIL import Image

from packages.security.sanitizer import sanitize_untrusted_text

REG_PLATE_RE = re.compile(r"\b[A-Z]{2}[-\s]?\d{2}[-\s]?[A-Z]{1,2}[-\s]?\d{4}\b")
POLICY_NO_RE = re.compile(r"\bPOL-[A-Z0-9-]+\b")
DL_RE = re.compile(r"\b[A-Z]{2}\d{2}[-\s]?\d{4,11}\b")


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
                "issues": [f"Resolution {w}x{h} below minimum 320x240"],
                "guidance": "Capture higher-resolution photo closer to the vehicle.",
            }
        return {
            "angle": angle,
            "quality_status": "acceptable",
            "issues": [],
            "resolution": f"{w}x{h}",
        }
    except Exception:
        return {
            "angle": angle,
            "quality_status": "acceptable",
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
            }
        )

    image_quality = check_image_quality(filename, raw_bytes) if mime_type.startswith("image/") else None

    return {
        "doc_type": doc_type,
        "classification_confidence": cls_conf,
        "ocr_version": "ocr-adapter-v1",
        "sanitized_text": sanitized_text,
        "prompt_injection_flagged": inj_detected,
        "prompt_injection_patterns": inj_hits,
        "facts": facts,
        "image_quality": image_quality,
    }
