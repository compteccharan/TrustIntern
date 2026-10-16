"""Web complaint search — Reddit archives + general queries; clear/unknown only."""

from __future__ import annotations

import asyncio
from typing import Any

from app.agents.schema import AgentSpec
from app.agents.workers._fetch import clear_or_unknown, duckduckgo_search, reddit_search


async def run(ctx: dict[str, Any], spec: AgentSpec) -> list[dict[str, Any]]:
    data = ctx.get("data") or {}
    live = bool(data.get("live_lookups", True))
    company = (spec.inputs.get("company_name") or data.get("company_name") or "").strip()
    timeout = float(spec.budget.timeout_s)
    evidence: list[dict[str, Any]] = []

    if not live:
        return [
            clear_or_unknown(
                indicator_id="web_complaint_search",
                title="Complaint search skipped",
                reason="Live lookup was not requested for this run.",
                status="unknown",
                source="Web complaint search",
            )
        ]

    if not company:
        return [
            clear_or_unknown(
                indicator_id="web_complaint_search",
                title="No company for complaint search",
                reason="Company name missing.",
                status="unknown",
                source="Web complaint search",
            )
        ]

    # Reddit via PullPush (works when DDG/reddit.com JSON are blocked)
    reddit_q = f"{company} internship scam OR fraud OR fee OR registration"
    reddit_hits = await asyncio.to_thread(
        reddit_search, reddit_q, timeout_s=timeout, max_results=3
    )
    if reddit_hits:
        top = reddit_hits[0]
        sub = top.get("subreddit") or "reddit"
        evidence.append(
            clear_or_unknown(
                indicator_id="reddit_complaints",
                title=f"Reddit discussion found (r/{sub})",
                reason=(
                    "A Reddit archive hit matched a complaint-style query; "
                    "not scored as an indicator — review the source."
                ),
                status="clear",
                source="Reddit OSINT",
                source_url=top.get("url"),
                excerpt=(top.get("title") or top.get("snippet") or "")[:180] or None,
            )
        )
        # Extra hits as supporting context (still unscored)
        for extra in reddit_hits[1:2]:
            evidence.append(
                clear_or_unknown(
                    indicator_id="reddit_complaints_extra",
                    title=f"Additional Reddit hit (r/{extra.get('subreddit') or 'reddit'})",
                    reason="Supporting Reddit archive result; not scored.",
                    status="clear",
                    source="Reddit OSINT",
                    source_url=extra.get("url"),
                    excerpt=(extra.get("title") or "")[:180] or None,
                )
            )
    else:
        evidence.append(
            clear_or_unknown(
                indicator_id="reddit_complaints",
                title="No Reddit archive results",
                reason=f"PullPush search for {reddit_q!r} returned no posts.",
                status="unknown",
                source="Reddit OSINT",
            )
        )

    # General web (DDG) — may be empty when bot-challenged
    web_q = spec.inputs.get("query") or f'"{company}" internship scam'
    web_hits = await asyncio.to_thread(
        duckduckgo_search, web_q, timeout_s=timeout, max_results=3
    )
    if web_hits:
        top = web_hits[0]
        evidence.append(
            clear_or_unknown(
                indicator_id="web_complaint_search",
                title="Public web complaint result recorded",
                reason="A public web result was found; not scored as an indicator.",
                status="clear",
                source="Web complaint search",
                source_url=top.get("url"),
                excerpt=(top.get("snippet") or top.get("title") or "")[:180] or None,
            )
        )
    else:
        evidence.append(
            clear_or_unknown(
                indicator_id="web_complaint_search",
                title="General web search unavailable or empty",
                reason=(
                    "DuckDuckGo HTML search returned no results "
                    "(often bot-blocked). Reddit archive path is primary."
                ),
                status="unknown",
                source="Web complaint search",
            )
        )

    return evidence
