"""Domain OSINT — title/snippet consistency vs company (beyond fixed RDAP)."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from app.agents.schema import AgentSpec
from app.agents.workers._fetch import clear_or_unknown, safe_get_text
from app.checks import _company_tokens, _host_from_url


async def run(ctx: dict[str, Any], spec: AgentSpec) -> list[dict[str, Any]]:
    data = ctx.get("data") or {}
    live = bool(data.get("live_lookups", True))
    company = (spec.inputs.get("company_name") or data.get("company_name") or "").strip()
    website = (spec.inputs.get("website_url") or data.get("website_url") or "").strip()
    timeout = float(spec.budget.timeout_s)
    host = _host_from_url(website)

    if not live:
        return [
            clear_or_unknown(
                indicator_id="domain_osint",
                title="Domain OSINT skipped",
                reason="Live lookup was not requested for this run.",
                status="unknown",
                source="Domain OSINT",
                source_url=website or None,
            )
        ]

    if not host:
        return [
            clear_or_unknown(
                indicator_id="domain_osint",
                title="No domain to inspect",
                reason="No usable website host was available.",
                status="unknown",
                source="Domain OSINT",
            )
        ]

    result = await asyncio.to_thread(safe_get_text, website, timeout_s=timeout)
    if not result.get("ok"):
        return [
            clear_or_unknown(
                indicator_id="domain_osint",
                title="Domain page not fetched",
                reason=result.get("error") or "Fetch failed.",
                status="unknown",
                source="Domain OSINT",
                source_url=website,
            )
        ]

    blob = f"{result.get('title') or ''} {result.get('text') or ''}".lower()
    tokens = _company_tokens(company)
    matched = [t for t in tokens if t in re.sub(r"[^a-z0-9]", "", blob) or t in blob]
    if matched:
        return [
            clear_or_unknown(
                indicator_id="domain_osint",
                title="Domain content mentions company",
                reason="Page title or body includes a company name token.",
                status="clear",
                source="Domain OSINT",
                source_url=result.get("url") or website,
                excerpt=(result.get("title") or matched[0])[:180],
            )
        ]
    return [
        clear_or_unknown(
            indicator_id="domain_osint",
            title="Domain content lacks company tokens",
            reason="Fetched page does not clearly mention the company name.",
            status="unknown",
            source="Domain OSINT",
            source_url=result.get("url") or website,
            excerpt=(result.get("title") or "")[:180] or None,
        )
    ]
