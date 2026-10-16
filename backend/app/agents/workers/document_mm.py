"""Document multimodal agent — rasterize first PDF page; quote claims via Gemma or heuristics."""

from __future__ import annotations

import asyncio
import base64
import io
import re
from typing import Any

from app.agents.schema import AgentSpec
from app.agents.workers._fetch import clear_or_unknown
from app.checks import (
    FEE_PHRASES,
    SENSITIVE_PHRASES,
    URGENCY_PHRASES,
    find_fee_evidence,
    find_sensitive_evidence,
    find_urgency_evidence,
)


def rasterize_first_page(pdf_bytes: bytes) -> dict[str, Any]:
    """Return {ok, png_bytes, error}. Uses pypdfium2 when available."""
    if not pdf_bytes:
        return {"ok": False, "png_bytes": None, "error": "empty"}
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return {"ok": False, "png_bytes": None, "error": "pypdfium2_missing"}
    try:
        doc = pdfium.PdfDocument(pdf_bytes)
        if len(doc) < 1:
            return {"ok": False, "png_bytes": None, "error": "no_pages"}
        page = doc[0]
        bitmap = page.render(scale=1.5)
        pil = bitmap.to_pil()
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        return {"ok": True, "png_bytes": buf.getvalue(), "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "png_bytes": None, "error": str(exc)}


def _heuristic_quotes(text: str) -> list[dict[str, str]]:
    quotes: list[dict[str, str]] = []
    lower = text.lower()
    for phrase in FEE_PHRASES + URGENCY_PHRASES + SENSITIVE_PHRASES:
        idx = lower.find(phrase)
        if idx < 0:
            continue
        start = max(0, idx - 20)
        end = min(len(text), idx + len(phrase) + 40)
        quotes.append(
            {
                "claim_type": "scam_relevant",
                "quote": text[start:end].strip(),
                "phrase": phrase,
            }
        )
        if len(quotes) >= 5:
            break
    return quotes


def _map_quotes_to_evidence(quotes: list[dict[str, str]], source: str) -> list[dict[str, Any]]:
    """Map quoted claims into existing indicator rules only — never invent points."""
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()
    for q in quotes:
        quote = (q.get("quote") or "").strip()
        if not quote:
            continue
        for finder in (find_fee_evidence, find_urgency_evidence, find_sensitive_evidence):
            item = finder(quote, source)
            if item and item["indicator_id"] not in seen:
                seen.add(item["indicator_id"])
                evidence.append(item)
    return evidence


async def run(ctx: dict[str, Any], spec: AgentSpec) -> list[dict[str, Any]]:
    data = ctx.get("data") or {}
    pdf_bytes: bytes | None = data.get("pdf") or spec.inputs.get("pdf_bytes")
    image = data.get("image") or {}
    image_bytes: bytes | None = image.get("bytes") if isinstance(image, dict) else None
    image_mime = (image.get("mime") if isinstance(image, dict) else None) or "image/png"
    evidence: list[dict[str, Any]] = []

    if not pdf_bytes and not image_bytes:
        return [
            clear_or_unknown(
                indicator_id="document_multimodal",
                title="No document or image for multimodal review",
                reason="Upload an offer-letter PDF or an image (PNG, JPEG, or WebP).",
                status="unknown",
                source="Document multimodal",
            )
        ]

    vision_bytes: bytes | None = None
    vision_mime = "image/png"
    text = ""
    raster_error = None

    if image_bytes:
        vision_bytes = image_bytes
        vision_mime = image_mime
    if pdf_bytes:
        from app.document import extract_pdf_text

        extracted = await asyncio.to_thread(extract_pdf_text, pdf_bytes)
        text = extracted.get("text") or ""
        if vision_bytes is None:
            raster = await asyncio.to_thread(rasterize_first_page, pdf_bytes)
            ctx["pdf_page_png"] = raster.get("png_bytes") if raster.get("ok") else None
            if raster.get("ok"):
                vision_bytes = raster["png_bytes"]
                vision_mime = "image/png"
            else:
                raster_error = raster.get("error")

    quotes: list[dict[str, str]] = []
    gemma = ctx.get("gemma")
    force_heuristic = bool(ctx.get("force_heuristic"))
    used_gemma = False

    if (
        gemma
        and getattr(gemma, "available", False)
        and vision_bytes
        and not force_heuristic
    ):
        try:
            b64 = base64.b64encode(vision_bytes).decode("ascii")
            quotes = await gemma.extract_document_claims(
                image_b64=b64,
                text_hint=text[:1500],
                mime_type=vision_mime,
            )
            used_gemma = bool(quotes)
        except Exception:  # noqa: BLE001
            quotes = []

    if not quotes and text:
        quotes = _heuristic_quotes(text)

    if quotes:
        evidence.append(
            clear_or_unknown(
                indicator_id="document_multimodal",
                title=(
                    "Gemma 4 vision claims extracted"
                    if used_gemma
                    else "Document claims extracted without vision model"
                ),
                reason=(
                    "Open-weight Gemma 4 read the image and returned quoted claims. "
                    "Points still come only from scoring.py."
                    if used_gemma
                    else "No Gemma vision result; phrase rules were applied to extracted text."
                ),
                status="clear",
                source="Document multimodal",
                excerpt="; ".join(q.get("quote", "")[:80] for q in quotes[:3]),
            )
        )
        # Only rule-matched indicators get points via scoring.py
        evidence.extend(_map_quotes_to_evidence(quotes, "Offer letter (multimodal)"))
    else:
        reason = "No claims extracted."
        if image_bytes and (
            force_heuristic or not gemma or not getattr(gemma, "available", False)
        ):
            reason = (
                "Image received, but Gemma vision did not run. "
                "Set GEMINI_API_KEY so open-weight Gemma 4 can read it."
            )
        elif raster_error:
            reason = f"Page raster failed ({raster_error}); no quotes available."
        evidence.append(
            clear_or_unknown(
                indicator_id="document_multimodal",
                title="Multimodal document review incomplete",
                reason=reason,
                status="unknown",
                source="Document multimodal",
            )
        )

    return evidence
