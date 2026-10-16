"""Scoring weights, risk levels, equation building, and recommendations."""

from __future__ import annotations

from typing import Any

DISCLAIMER = "Heuristic indicator score, not a probability of fraud."

INDICATORS: dict[str, dict[str, Any]] = {
    "upfront_fee": {"points": 25, "label": "Upfront fee"},
    "domain_mismatch": {"points": 20, "label": "Email domain mismatch"},
    "sensitive_data": {"points": 20, "label": "Sensitive data request"},
    "young_domain": {"points": 15, "label": "Newly registered domain"},
    "offer_inconsistency": {"points": 15, "label": "Offer letter conflict"},
    "unrelated_domain": {"points": 10, "label": "Company not in domain"},
    "urgency": {"points": 10, "label": "Urgency or guarantee"},
    "personal_email": {"points": 5, "label": "Personal email provider"},
}

# Display order for equation when multiple indicators fire
EQUATION_ORDER = [
    "upfront_fee",
    "domain_mismatch",
    "sensitive_data",
    "young_domain",
    "offer_inconsistency",
    "unrelated_domain",
    "urgency",
    "personal_email",
]


def risk_level_for_score(score: int) -> str:
    if score <= 30:
        return "Lower observed risk indicators"
    if score <= 60:
        return "Needs verification"
    return "High observed risk indicators"


def compute_score(evidence: list[dict[str, Any]]) -> int:
    total = 0
    for item in evidence:
        if item.get("status") == "indicator":
            total += int(item.get("points") or 0)
    return min(total, 100)


def build_equation(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in evidence:
        if item.get("status") != "indicator":
            continue
        iid = item["indicator_id"]
        if iid in by_id:
            continue
        meta = INDICATORS.get(iid, {})
        by_id[iid] = {
            "indicator_id": iid,
            "label": meta.get("label", iid),
            "points": int(item.get("points") or meta.get("points") or 0),
        }
    ordered: list[dict[str, Any]] = []
    for iid in EQUATION_ORDER:
        if iid in by_id:
            ordered.append(by_id.pop(iid))
    ordered.extend(by_id.values())
    return ordered


def build_recommendations(evidence: list[dict[str, Any]]) -> list[str]:
    ids = {
        item["indicator_id"]
        for item in evidence
        if item.get("status") == "indicator"
    }
    recs: list[str] = []
    if "upfront_fee" in ids:
        recs.append("Do not pay a fee to receive an internship.")
    if "sensitive_data" in ids:
        recs.append(
            "Do not share bank details, OTPs, or identity numbers with a recruiter."
        )
    if ids & {"domain_mismatch", "unrelated_domain", "personal_email"}:
        recs.append(
            "Contact the company through an address you find yourself, not the one in the message."
        )
    recs.append(
        "A low score is not proof the offer is real. Verify the role with the company independently."
    )
    return recs


def merge_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by indicator_id; second sources go into also_found_in."""
    merged: dict[str, dict[str, Any]] = {}
    passthrough: list[dict[str, Any]] = []

    for raw in items:
        item = dict(raw)
        item.setdefault("also_found_in", [])
        iid = item.get("indicator_id")
        status = item.get("status")

        # clear/unknown website/domain-age rows use distinct ids and always pass through
        if status != "indicator" or not iid:
            passthrough.append(item)
            continue

        if iid not in merged:
            merged[iid] = item
            continue

        existing = merged[iid]
        source = item.get("source")
        if source and source not in existing.get("also_found_in", []):
            if source != existing.get("source"):
                existing.setdefault("also_found_in", []).append(source)

    # Preserve roughly arrival order: indicators first in EQUATION_ORDER, then others
    result: list[dict[str, Any]] = []
    for iid in EQUATION_ORDER:
        if iid in merged:
            result.append(merged.pop(iid))
    result.extend(merged.values())
    result.extend(passthrough)
    return result
