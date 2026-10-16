"""Orchestrate checks into a TrustIntern report dict (without persisted id)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.checks import (
    check_domain_age,
    check_domain_mismatch,
    check_personal_email,
    check_unrelated_domain,
    check_website,
    scan_text_phrases,
)
from app.document import analyze_pdf
from app.scoring import (
    DISCLAIMER,
    build_equation,
    build_recommendations,
    compute_score,
    merge_evidence,
    risk_level_for_score,
)

FetchUrlFn = Callable[[str], dict[str, Any]]
RdapFn = Callable[[str], dict[str, Any]]


class Lookups:
    def __init__(
        self,
        fetch_url: FetchUrlFn | None = None,
        rdap: RdapFn | None = None,
    ) -> None:
        self.fetch_url = fetch_url
        self.rdap = rdap


def _message_preview(message: str) -> str:
    return message[:180]


def analyze_opportunity(
    data: dict[str, Any],
    lookups: Lookups | None = None,
) -> dict[str, Any]:
    """Analyze an opportunity and return a report dict (id filled by storage)."""
    lookups = lookups or Lookups()

    company_name = (data.get("company_name") or "").strip()
    recruiter_name = data.get("recruiter_name")
    recruiter_email = data.get("recruiter_email")
    website_url = data.get("website_url")
    message = data.get("message") or ""
    live_lookups = bool(data.get("live_lookups", True))
    pdf_bytes = data.get("pdf")

    evidence: list[dict[str, Any]] = []

    # Message phrase checks
    evidence.extend(scan_text_phrases(message, "Recruitment message"))

    # Domain / email rules (no network)
    evidence.append(check_domain_mismatch(recruiter_email, website_url))
    unrelated = check_unrelated_domain(company_name, website_url)
    if unrelated:
        evidence.append(unrelated)
    personal = check_personal_email(recruiter_email, company_name)
    if personal:
        evidence.append(personal)

    # PDF
    pdf_evidence, had_pdf = analyze_pdf(pdf_bytes, company_name)
    evidence.extend(pdf_evidence)

    # Live lookups
    evidence.append(
        check_website(website_url, live_lookups, fetch_url=lookups.fetch_url)
    )
    evidence.append(
        check_domain_age(website_url, live_lookups, rdap=lookups.rdap)
    )

    evidence = merge_evidence(evidence)
    score = compute_score(evidence)
    equation = build_equation(evidence)
    recommendations = build_recommendations(evidence)

    try:
        tz = ZoneInfo("Asia/Kolkata")
        created_at = datetime.now(tz).isoformat()
    except Exception:  # noqa: BLE001
        created_at = datetime.now(timezone.utc).isoformat()

    return {
        "id": 0,
        "created_at": created_at,
        "score": score,
        "risk_level": risk_level_for_score(score),
        "disclaimer": DISCLAIMER,
        "equation": equation,
        "evidence": evidence,
        "recommendations": recommendations,
        "input_summary": {
            "company_name": company_name,
            "recruiter_name": recruiter_name,
            "recruiter_email": recruiter_email,
            "website_url": website_url,
            "message_preview": _message_preview(message),
            "had_pdf": had_pdf,
            "live_lookups": live_lookups,
        },
    }
