"""Company OSINT — website fetch, Wikipedia, Reddit, LinkedIn URL notes."""

from __future__ import annotations

import asyncio
from typing import Any

from app.agents.schema import AgentSpec
from app.agents.workers._fetch import (
    clear_or_unknown,
    duckduckgo_search,
    reddit_search,
    safe_get_text,
    wikipedia_summary,
)


async def run(ctx: dict[str, Any], spec: AgentSpec) -> list[dict[str, Any]]:
    data = ctx.get("data") or {}
    live = bool(data.get("live_lookups", True))
    company = (spec.inputs.get("company_name") or data.get("company_name") or "").strip()
    website = (spec.inputs.get("website_url") or data.get("website_url") or "").strip()
    timeout = float(spec.budget.timeout_s)
    evidence: list[dict[str, Any]] = []

    if not live:
        evidence.append(
            clear_or_unknown(
                indicator_id="company_osint",
                title="Company OSINT skipped",
                reason="Live lookup was not requested for this run.",
                status="unknown",
                source="Company OSINT",
                source_url=website or None,
            )
        )
        return evidence

    if website:
        result = await asyncio.to_thread(safe_get_text, website, timeout_s=timeout)
        if result.get("ok"):
            title = result.get("title") or ""
            company_l = company.lower()
            title_l = title.lower()
            consistent = bool(company_l) and any(
                tok in title_l for tok in company_l.split() if len(tok) >= 4
            )
            evidence.append(
                clear_or_unknown(
                    indicator_id="company_osint",
                    title="Company website fetched",
                    reason=(
                        "Website title appears consistent with company name."
                        if consistent
                        else "Website fetched; title does not clearly match company name."
                    ),
                    status="clear" if consistent else "unknown",
                    source="Company OSINT",
                    source_url=result.get("url") or website,
                    excerpt=(title or result.get("text") or "")[:180] or None,
                )
            )
        else:
            evidence.append(
                clear_or_unknown(
                    indicator_id="company_osint",
                    title="Company website not fetched",
                    reason=result.get("error") or "Fetch failed.",
                    status="unknown",
                    source="Company OSINT",
                    source_url=website,
                )
            )
    else:
        evidence.append(
            clear_or_unknown(
                indicator_id="company_osint",
                title="No company website provided",
                reason="No website URL was supplied for company OSINT.",
                status="unknown",
                source="Company OSINT",
            )
        )

    if not company:
        return evidence

    wiki = await asyncio.to_thread(wikipedia_summary, company, timeout_s=timeout)
    if wiki and wiki.get("extract"):
        evidence.append(
            clear_or_unknown(
                indicator_id="company_wikipedia",
                title="Wikipedia summary found"
                if not wiki.get("disambiguation")
                else "Wikipedia disambiguation (ambiguous company)",
                reason="Public encyclopedia entry used as company identity context.",
                status="clear" if not wiki.get("disambiguation") else "unknown",
                source="Company OSINT",
                source_url=wiki.get("url"),
                excerpt=(wiki.get("extract") or "")[:180] or None,
            )
        )
    else:
        evidence.append(
            clear_or_unknown(
                indicator_id="company_wikipedia",
                title="No Wikipedia summary",
                reason="No Wikipedia REST summary matched the company name.",
                status="unknown",
                source="Company OSINT",
            )
        )

    reddit_hits = await asyncio.to_thread(
        reddit_search,
        f"{company} internship OR hiring OR job",
        timeout_s=timeout,
        max_results=2,
    )
    if reddit_hits:
        top = reddit_hits[0]
        evidence.append(
            clear_or_unknown(
                indicator_id="company_reddit",
                title=f"Reddit company discussion (r/{top.get('subreddit') or 'reddit'})",
                reason="Reddit archive mention of the company; not a legitimacy proof.",
                status="clear",
                source="Company OSINT",
                source_url=top.get("url"),
                excerpt=(top.get("title") or "")[:180] or None,
            )
        )
    else:
        evidence.append(
            clear_or_unknown(
                indicator_id="company_reddit",
                title="No Reddit company results",
                reason="PullPush returned no posts for the company query.",
                status="unknown",
                source="Company OSINT",
            )
        )

    # LinkedIn company pages are usually login-walled; try DDG then mark honestly.
    li_hits = await asyncio.to_thread(
        duckduckgo_search,
        f'site:linkedin.com/company "{company}"',
        timeout_s=timeout,
        max_results=2,
    )
    if li_hits:
        top = next(
            (h for h in li_hits if "linkedin.com" in (h.get("url") or "").lower()),
            li_hits[0],
        )
        evidence.append(
            clear_or_unknown(
                indicator_id="company_linkedin",
                title="LinkedIn company search hit",
                reason="Search engine returned a LinkedIn-related URL; page may require login.",
                status="clear",
                source="Company OSINT",
                source_url=top.get("url"),
                excerpt=(top.get("snippet") or top.get("title") or "")[:180] or None,
            )
        )
    else:
        evidence.append(
            clear_or_unknown(
                indicator_id="company_linkedin",
                title="LinkedIn company search unavailable",
                reason=(
                    "No LinkedIn company URL found via public search "
                    "(search engines often block bots; LinkedIn pages require login)."
                ),
                status="unknown",
                source="Company OSINT",
            )
        )

    return evidence
