"""Entity follow-up — phone / LinkedIn / payment handle notes (no invented scores)."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from app.agents.schema import AgentSpec
from app.agents.workers._fetch import clear_or_unknown, duckduckgo_search, reddit_search
from app.checks import is_safe_url


PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s\-]?)?(?:\(?\d{2,4}\)?[\s\-]?)?\d{3,4}[\s\-]?\d{3,4}"
)
LINKEDIN_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/[^\s]+", re.IGNORECASE
)
PAYMENT_RE = re.compile(
    r"\b(?:upi|paytm|gpay|phonepe|venmo|paypal|cashapp)\b[:\s]*([^\s,]{3,40})",
    re.IGNORECASE,
)


def extract_entities(text: str) -> dict[str, list[str]]:
    phones = []
    for m in PHONE_RE.finditer(text or ""):
        raw = re.sub(r"\D", "", m.group(0))
        if 10 <= len(raw) <= 15:
            phones.append(m.group(0).strip())
    linkedin = LINKEDIN_RE.findall(text or "")
    payments = [m.group(0).strip() for m in PAYMENT_RE.finditer(text or "")]
    return {
        "phones": list(dict.fromkeys(phones))[:3],
        "linkedin": list(dict.fromkeys(linkedin))[:3],
        "payments": list(dict.fromkeys(payments))[:3],
    }


async def run(ctx: dict[str, Any], spec: AgentSpec) -> list[dict[str, Any]]:
    data = ctx.get("data") or {}
    live = bool(data.get("live_lookups", True))
    entity_type = (spec.inputs.get("entity_type") or "").strip().lower()
    value = (spec.inputs.get("value") or "").strip()
    timeout = float(spec.budget.timeout_s)
    evidence: list[dict[str, Any]] = []

    if not value:
        # Auto-scan message if no explicit entity
        entities = extract_entities(data.get("message") or "")
        for phone in entities["phones"][:1]:
            evidence.append(
                clear_or_unknown(
                    indicator_id="entity_followup",
                    title="Phone number noted",
                    reason="A phone-like number was found in the recruitment message.",
                    status="clear",
                    source="Entity follow-up",
                    excerpt=phone,
                )
            )
        for url in entities["linkedin"][:1]:
            evidence.append(
                clear_or_unknown(
                    indicator_id="entity_followup",
                    title="LinkedIn URL noted",
                    reason="A LinkedIn URL was found in the recruitment message.",
                    status="clear",
                    source="Entity follow-up",
                    source_url=url if is_safe_url(url) else None,
                    excerpt=url,
                )
            )
        for pay in entities["payments"][:1]:
            evidence.append(
                clear_or_unknown(
                    indicator_id="entity_followup",
                    title="Payment handle noted",
                    reason="A payment-app style handle was found in the recruitment message.",
                    status="clear",
                    source="Entity follow-up",
                    excerpt=pay,
                )
            )
        if not evidence:
            evidence.append(
                clear_or_unknown(
                    indicator_id="entity_followup",
                    title="No follow-up entities",
                    reason="No phone, LinkedIn URL, or payment handle found.",
                    status="unknown",
                    source="Entity follow-up",
                )
            )
        return evidence

    evidence.append(
        clear_or_unknown(
            indicator_id="entity_followup",
            title=f"Follow-up entity: {entity_type or 'unknown'}",
            reason="Entity recorded for OSINT context; does not assign score points.",
            status="clear",
            source="Entity follow-up",
            source_url=value if value.startswith("http") and is_safe_url(value) else None,
            excerpt=value[:180],
        )
    )

    if live and entity_type in {"linkedin", "payment", "name"}:
        # Prefer Reddit archives; skip bare phone searches (too many false hits).
        reddit_hits = await asyncio.to_thread(
            reddit_search, value, timeout_s=timeout, max_results=2
        )
        if reddit_hits:
            top = reddit_hits[0]
            evidence.append(
                clear_or_unknown(
                    indicator_id="entity_followup_search",
                    title="Reddit mention of entity",
                    reason="A Reddit archive result may relate to the follow-up entity.",
                    status="clear",
                    source="Entity follow-up",
                    source_url=top.get("url"),
                    excerpt=(top.get("title") or top.get("snippet") or "")[:180] or None,
                )
            )
        elif entity_type == "linkedin" or "linkedin.com" in value.lower():
            hits = await asyncio.to_thread(
                duckduckgo_search,
                f"site:linkedin.com {value}",
                timeout_s=timeout,
                max_results=2,
            )
            if hits:
                top = next(
                    (h for h in hits if "linkedin.com" in (h.get("url") or "").lower()),
                    hits[0],
                )
                evidence.append(
                    clear_or_unknown(
                        indicator_id="entity_followup_search",
                        title="Public mention of LinkedIn entity",
                        reason="A public search result may relate to the LinkedIn URL.",
                        status="clear",
                        source="Entity follow-up",
                        source_url=top.get("url"),
                        excerpt=(top.get("snippet") or top.get("title") or "")[:180]
                        or None,
                    )
                )
    elif live and entity_type == "phone":
        evidence.append(
            clear_or_unknown(
                indicator_id="entity_followup_search",
                title="Phone noted without public search",
                reason=(
                    "Phone numbers are recorded from the message but not searched "
                    "publicly (high false-positive rate)."
                ),
                status="unknown",
                source="Entity follow-up",
                excerpt=value[:40],
            )
        )

    return evidence
