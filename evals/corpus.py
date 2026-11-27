"""Ground truth for citation checks: the approved policy-wording corpus."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

POLICIES_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "synthetic_policy_samples" / "policies.json"

_DOC_RE = re.compile(r"POL-WORDING-[A-Z]+-\d{4}")
_CLAUSE_RE = re.compile(r"\b(?:SEC|ADDON|COND|EV)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")
_PAGE_RE = re.compile(r"\bp\.(\d+)(?:-(\d+))?")


@dataclass(frozen=True)
class Clause:
    document_id: str
    clause_id: str
    page: int
    text: str


@lru_cache(maxsize=1)
def corpus() -> dict[tuple[str, str], Clause]:
    docs: list[dict[str, Any]] = json.loads(POLICIES_PATH.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], Clause] = {}
    for doc in docs:
        for c in doc["clauses"]:
            out[(doc["document_id"], c["clause_id"])] = Clause(
                doc["document_id"], c["clause_id"], int(c["page"]), c["text"]
            )
    return out


@dataclass(frozen=True)
class ParsedRef:
    document_id: str | None
    clause_ids: tuple[str, ...]
    page_lo: int | None
    page_hi: int | None


def parse_clause_ref(ref: str) -> ParsedRef:
    """Parse e.g. ``POL-WORDING-PC-2024 SEC-1-1 p.3`` or ``POL-WORDING-EV-2025 EV-BAT-01 / EV-SAFE-01 p.2-3``."""
    doc = _DOC_RE.search(ref)
    pages = _PAGE_RE.search(ref)
    lo = int(pages.group(1)) if pages else None
    hi = int(pages.group(2)) if pages and pages.group(2) else lo
    remainder = _DOC_RE.sub(" ", ref)  # the document id itself contains "EV-2025" and must not read as a clause
    return ParsedRef(doc.group(0) if doc else None, tuple(_CLAUSE_RE.findall(remainder)), lo, hi)


def resolve_reference(ref: str) -> tuple[bool, str]:
    """True when every clause named in ``ref`` exists in the named document and the page is consistent."""
    parsed = parse_clause_ref(ref)
    if not parsed.document_id or not parsed.clause_ids:
        return False, f"unparseable reference '{ref}'"
    table = corpus()
    for cid in parsed.clause_ids:
        clause = table.get((parsed.document_id, cid))
        if clause is None:
            return False, f"clause {parsed.document_id}/{cid} does not exist in the approved corpus"
        if (
            parsed.page_lo is not None
            and parsed.page_hi is not None
            and not (parsed.page_lo <= clause.page <= parsed.page_hi)
        ):
            return False, f"{cid} is on p.{clause.page}, reference says p.{parsed.page_lo}-{parsed.page_hi}"
    return True, ""


def citation_is_grounded(source_id: str, reference: str, excerpt: str) -> tuple[bool, str]:
    """A citation is grounded when its reference resolves AND its excerpt is quoted from that clause."""
    ok, why = resolve_reference(reference)
    if not ok:
        return False, why
    parsed = parse_clause_ref(reference)
    if parsed.document_id != source_id:
        return False, f"source_id {source_id} does not match reference document {parsed.document_id}"
    if excerpt:
        clause = corpus()[(parsed.document_id, parsed.clause_ids[0])]
        if excerpt.strip() not in clause.text:
            return False, f"excerpt is not a quotation from {parsed.clause_ids[0]}"
    return True, ""
