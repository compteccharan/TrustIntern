"""PDF text extraction and offer-letter checks."""

from __future__ import annotations

import io
import re
from typing import Any

from pypdf import PdfReader

from app.checks import scan_text_phrases
from app.scoring import INDICATORS


MAX_PDF_BYTES = 5 * 1024 * 1024


def extract_pdf_text(pdf_bytes: bytes) -> dict[str, Any]:
    """Return {ok, text, error}. Failures never raise to the caller."""
    if not pdf_bytes:
        return {"ok": False, "text": "", "error": "empty"}
    if len(pdf_bytes) > MAX_PDF_BYTES:
        return {"ok": False, "text": "", "error": "too_large"}
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if getattr(reader, "is_encrypted", False):
            # Try empty password; if still encrypted, unknown
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001
                return {"ok": False, "text": "", "error": "encrypted"}
            if reader.is_encrypted:
                return {"ok": False, "text": "", "error": "encrypted"}
        parts: list[str] = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001
                continue
        text = "\n".join(parts).strip()
        if not text:
            return {"ok": False, "text": "", "error": "empty_text"}
        return {"ok": True, "text": text, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "text": "", "error": str(exc)}


def check_offer_company_mismatch(
    pdf_text: str, company_name: str
) -> dict[str, Any] | None:
    """Flag if PDF mentions a different company-like name conflicting with input."""
    if not pdf_text or not company_name.strip():
        return None
    # Look for "Company:" or "Employer:" style lines with a different name
    patterns = [
        r"(?:company|employer|organization)\s*[:\-]\s*([A-Za-z0-9 &.,'\-]{2,80})",
        r"(?:offer\s+from|joining)\s+([A-Za-z0-9 &.,'\-]{2,80})",
    ]
    company_norm = re.sub(r"\s+", " ", company_name.strip().lower())
    for pat in patterns:
        for match in re.finditer(pat, pdf_text, flags=re.IGNORECASE):
            found = re.sub(r"\s+", " ", match.group(1).strip().lower())
            found = found.rstrip(".,")
            if not found:
                continue
            # Conflict if neither contains the other as substring of significant tokens
            if found != company_norm and company_norm not in found and found not in company_norm:
                return {
                    "indicator_id": "offer_inconsistency",
                    "title": "Offer letter company conflict",
                    "reason": "The offer document names a company that differs from the submitted company.",
                    "excerpt": match.group(0).strip()[:120],
                    "points": INDICATORS["offer_inconsistency"]["points"],
                    "status": "indicator",
                    "source": "Offer letter",
                    "source_url": None,
                    "also_found_in": [],
                }
    return None


def analyze_pdf(
    pdf_bytes: bytes | None, company_name: str
) -> tuple[list[dict[str, Any]], bool]:
    """Return (evidence_items, had_pdf)."""
    if pdf_bytes is None:
        return [], False
    if len(pdf_bytes) == 0:
        return [
            {
                "indicator_id": "pdf_parse",
                "title": "Offer letter unreadable",
                "reason": "The uploaded PDF was empty or could not be read.",
                "excerpt": None,
                "points": 0,
                "status": "unknown",
                "source": "Offer letter",
                "source_url": None,
                "also_found_in": [],
            }
        ], True

    extracted = extract_pdf_text(pdf_bytes)
    if not extracted["ok"]:
        return [
            {
                "indicator_id": "pdf_parse",
                "title": "Offer letter unreadable",
                "reason": "The uploaded PDF was empty, encrypted, or could not be read.",
                "excerpt": extracted.get("error"),
                "points": 0,
                "status": "unknown",
                "source": "Offer letter",
                "source_url": None,
                "also_found_in": [],
            }
        ], True

    text = extracted["text"]
    evidence = scan_text_phrases(text, "Offer letter")
    conflict = check_offer_company_mismatch(text, company_name)
    if conflict:
        evidence.append(conflict)
    return evidence, True
