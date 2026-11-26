from __future__ import annotations

import hashlib
import re
from typing import Tuple

INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"override\s+(approval|rules|settlement|decision)", re.IGNORECASE),
    re.compile(r"approve\s+claim\s+immediately", re.IGNORECASE),
    re.compile(r"bypass\s+(siu|surveyor|human\s+review|maker-checker)", re.IGNORECASE),
    re.compile(r"<\s*script\b", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(admin|superuser|finance)", re.IGNORECASE),
]

PHONE_RE = re.compile(r"\b(?:\+91[-\s]?)?[6-9]\d{9}\b")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
AADHAAR_RE = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/plain",
    "application/json",
}


def mask_phone(phone: str | None) -> str:
    if not phone or len(phone) < 4:
        return "****"
    return "*" * (len(phone) - 4) + phone[-4:]


def mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    prefix = local[:2] if len(local) >= 2 else local[:1]
    return f"{prefix}***@{domain}"


def mask_bank_account(acct: str | None) -> str:
    if not acct or len(acct) < 4:
        return "XXXX"
    return "X" * (len(acct) - 4) + acct[-4:]


def mask_text_pii(text: str) -> str:
    masked = PHONE_RE.sub("[MASKED_PHONE]", text)
    masked = EMAIL_RE.sub("[MASKED_EMAIL]", masked)
    masked = PAN_RE.sub("[MASKED_PAN]", masked)
    masked = AADHAAR_RE.sub("[MASKED_ID]", masked)
    return masked


def scan_for_prompt_injection(text: str) -> Tuple[bool, list[str]]:
    hits: list[str] = []
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            hits.append(pattern.pattern)
    return (len(hits) > 0, hits)


def sanitize_untrusted_text(text: str) -> tuple[str, bool, list[str]]:
    detected, hits = scan_for_prompt_injection(text)
    cleaned = text
    if detected:
        for pat in INJECTION_PATTERNS:
            cleaned = pat.sub("[FILTERED_UNTRUSTED_DIRECTIVE]", cleaned)
    return cleaned, detected, hits


def validate_upload_bytes(filename: str, content_type: str, data: bytes, max_mb: int = 25) -> dict:
    size_bytes = len(data)
    if size_bytes == 0:
        raise ValueError("Uploaded file is empty")
    if size_bytes > max_mb * 1024 * 1024:
        raise ValueError(f"File exceeds {max_mb} MB limit")

    sniffed_mime = content_type
    if data.startswith(b"%PDF"):
        sniffed_mime = "application/pdf"
    elif data.startswith(b"\xff\xd8\xff"):
        sniffed_mime = "image/jpeg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        sniffed_mime = "image/png"
    elif data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        sniffed_mime = "image/webp"

    if sniffed_mime not in ALLOWED_MIME_TYPES:
        raise ValueError(f"Unsupported or mismatched MIME type: {sniffed_mime}")

    if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in data:
        raise ValueError("Malware signature detected in uploaded file")

    sha256 = hashlib.sha256(data).hexdigest()
    return {
        "filename": filename,
        "mime_type": sniffed_mime,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "malware_scan": "clean",
    }
