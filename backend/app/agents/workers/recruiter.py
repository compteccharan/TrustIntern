"""Recruiter OSINT — email notes, Reddit mentions, LinkedIn URL checks."""

from __future__ import annotations

import asyncio
from typing import Any

from app.agents.schema import AgentSpec
from app.agents.workers._fetch import (
    clear_or_unknown,
    duckduckgo_search,
    reddit_search,
    safe_get_text,
)
from app.checks import PERSONAL_EMAIL_HOSTS, is_safe_url


def _email_host(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[-1].lower().strip() or None


async def run(ctx: dict[str, Any], spec: AgentSpec) -> list[dict[str, Any]]:
    data = ctx.get("data") or {}
    live = bool(data.get("live_lookups", True))
    name = (spec.inputs.get("recruiter_name") or data.get("recruiter_name") or "").strip()
    email = (spec.inputs.get("recruiter_email") or data.get("recruiter_email") or "").strip()
    company = (spec.inputs.get("company_name") or data.get("company_name") or "").strip()
    timeout = float(spec.budget.timeout_s)
    evidence: list[dict[str, Any]] = []

    host = _email_host(email)
    if host:
        if host in PERSONAL_EMAIL_HOSTS:
            evidence.append(
                clear_or_unknown(
                    indicator_id="recruiter_email_note",
                    title="Recruiter uses consumer email host",
                    reason="Noted for OSINT context; scoring still comes from fixed checkers.",
                    status="clear",
                    source="Recruiter OSINT",
                    excerpt=email,
                )
            )
        else:
            evidence.append(
                clear_or_unknown(
                    indicator_id="recruiter_email_note",
                    title="Recruiter email host recorded",
                    reason=f"Recruiter email host is {host}.",
                    status="clear",
                    source="Recruiter OSINT",
                    excerpt=email,
                )
            )
    else:
        evidence.append(
            clear_or_unknown(
                indicator_id="recruiter_email_note",
                title="Recruiter email missing",
                reason="No recruiter email was supplied for OSINT.",
                status="unknown",
                source="Recruiter OSINT",
            )
        )

    if not live:
        evidence.append(
            clear_or_unknown(
                indicator_id="recruiter_presence",
                title="Recruiter search skipped",
                reason="Live lookup was not requested for this run.",
                status="unknown",
                source="Recruiter OSINT",
            )
        )
        return evidence

    query_parts = [p for p in (name, company) if p]
    if not query_parts:
        evidence.append(
            clear_or_unknown(
                indicator_id="recruiter_presence",
                title="Insufficient recruiter identity",
                reason="No recruiter name or company to search.",
                status="unknown",
                source="Recruiter OSINT",
            )
        )
        return evidence

    base = " ".join(query_parts)
    reddit_hits = await asyncio.to_thread(
        reddit_search, base, timeout_s=timeout, max_results=2
    )
    if reddit_hits:
        top = reddit_hits[0]
        evidence.append(
            clear_or_unknown(
                indicator_id="recruiter_presence",
                title="Reddit mention of recruiter/company",
                reason="A Reddit archive result may relate to the recruiter or company.",
                status="clear",
                source="Recruiter OSINT",
                source_url=top.get("url"),
                excerpt=(top.get("title") or "")[:180] or None,
            )
        )
    else:
        evidence.append(
            clear_or_unknown(
                indicator_id="recruiter_presence",
                title="No Reddit recruiter results",
                reason=f"PullPush returned no posts for {base!r}.",
                status="unknown",
                source="Recruiter OSINT",
            )
        )

    # LinkedIn: prefer an explicit URL from the message; else search (often blocked)
    message = data.get("message") or ""
    from app.agents.workers.followup import LINKEDIN_RE

    linkedin_urls = LINKEDIN_RE.findall(message)
    if linkedin_urls:
        url = linkedin_urls[0]
        if is_safe_url(url):
            fetched = await asyncio.to_thread(safe_get_text, url, timeout_s=timeout)
            if fetched.get("ok") and (fetched.get("title") or fetched.get("text")):
                evidence.append(
                    clear_or_unknown(
                        indicator_id="recruiter_linkedin",
                        title="LinkedIn profile URL fetched",
                        reason="Fetched public HTML from a LinkedIn URL found in the message.",
                        status="clear",
                        source="Recruiter OSINT",
                        source_url=fetched.get("url") or url,
                        excerpt=(fetched.get("title") or fetched.get("text") or "")[:180]
                        or None,
                    )
                )
            else:
                evidence.append(
                    clear_or_unknown(
                        indicator_id="recruiter_linkedin",
                        title="LinkedIn URL noted but not readable",
                        reason=(
                            fetched.get("error")
                            or "LinkedIn typically requires login; treated as unverified."
                        ),
                        status="unknown",
                        source="Recruiter OSINT",
                        source_url=url,
                        excerpt=url,
                    )
                )
        else:
            evidence.append(
                clear_or_unknown(
                    indicator_id="recruiter_linkedin",
                    title="LinkedIn URL blocked by SSRF guard",
                    reason="URL failed the safe-URL check.",
                    status="unknown",
                    source="Recruiter OSINT",
                    excerpt=url,
                )
            )
    elif name:
        li_hits = await asyncio.to_thread(
            duckduckgo_search,
            f'site:linkedin.com/in "{name}" {company}'.strip(),
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
                    indicator_id="recruiter_linkedin",
                    title="LinkedIn-related search hit",
                    reason="Search engine returned a LinkedIn-related URL for the recruiter name.",
                    status="clear",
                    source="Recruiter OSINT",
                    source_url=top.get("url"),
                    excerpt=(top.get("snippet") or top.get("title") or "")[:180] or None,
                )
            )
        else:
            evidence.append(
                clear_or_unknown(
                    indicator_id="recruiter_linkedin",
                    title="LinkedIn profile not found publicly",
                    reason=(
                        "No public LinkedIn hit (search often blocked; "
                        "profiles usually require login)."
                    ),
                    status="unknown",
                    source="Recruiter OSINT",
                )
            )

    return evidence
