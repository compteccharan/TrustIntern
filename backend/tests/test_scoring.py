"""Unit tests for scoring, phrase rules, dedupe, and cap."""

from __future__ import annotations

from app.checks import find_fee_evidence, is_safe_url
from app.scoring import (
    DISCLAIMER,
    build_equation,
    compute_score,
    merge_evidence,
    risk_level_for_score,
)


def test_disclaimer_exact():
    assert DISCLAIMER == "Heuristic indicator score, not a probability of fraud."


def test_free_of_charge_does_not_raise_fee():
    text = (
        "The internship is free of charge at every stage. "
        "No registration fee is mentioned elsewhere either — wait, free of charge."
    )
    # Sentence with free of charge and no fee phrase
    assert find_fee_evidence(
        "The internship is free of charge at every stage.",
        "Recruitment message",
    ) is None
    # Same sentence with fee phrase + negation
    assert (
        find_fee_evidence(
            "There is no fee and no registration fee required.",
            "Recruitment message",
        )
        is None
    )


def test_fee_phrase_raises():
    item = find_fee_evidence(
        "Pay a registration fee of Rs 2000 to confirm.",
        "Recruitment message",
    )
    assert item is not None
    assert item["indicator_id"] == "upfront_fee"
    assert item["points"] == 25
    assert "registration fee" in (item["excerpt"] or "").lower()


def test_merge_dedupes_fee_across_sources():
    items = [
        {
            "indicator_id": "upfront_fee",
            "title": "Upfront payment requested",
            "reason": "msg",
            "excerpt": "registration fee",
            "points": 25,
            "status": "indicator",
            "source": "Recruitment message",
            "source_url": None,
            "also_found_in": [],
        },
        {
            "indicator_id": "upfront_fee",
            "title": "Upfront payment requested",
            "reason": "pdf",
            "excerpt": "registration fee",
            "points": 25,
            "status": "indicator",
            "source": "Offer letter",
            "source_url": None,
            "also_found_in": [],
        },
    ]
    merged = merge_evidence(items)
    fee = [m for m in merged if m["indicator_id"] == "upfront_fee"]
    assert len(fee) == 1
    assert fee[0]["points"] == 25
    assert "Offer letter" in fee[0]["also_found_in"]
    assert compute_score(merged) == 25


def test_score_cap_100():
    items = [
        {
            "indicator_id": "upfront_fee",
            "points": 25,
            "status": "indicator",
            "source": "a",
            "also_found_in": [],
        },
        {
            "indicator_id": "domain_mismatch",
            "points": 20,
            "status": "indicator",
            "source": "a",
            "also_found_in": [],
        },
        {
            "indicator_id": "sensitive_data",
            "points": 20,
            "status": "indicator",
            "source": "a",
            "also_found_in": [],
        },
        {
            "indicator_id": "young_domain",
            "points": 15,
            "status": "indicator",
            "source": "a",
            "also_found_in": [],
        },
        {
            "indicator_id": "offer_inconsistency",
            "points": 15,
            "status": "indicator",
            "source": "a",
            "also_found_in": [],
        },
        {
            "indicator_id": "unrelated_domain",
            "points": 10,
            "status": "indicator",
            "source": "a",
            "also_found_in": [],
        },
        {
            "indicator_id": "urgency",
            "points": 10,
            "status": "indicator",
            "source": "a",
            "also_found_in": [],
        },
        {
            "indicator_id": "personal_email",
            "points": 5,
            "status": "indicator",
            "source": "a",
            "also_found_in": [],
        },
    ]
    # 25+20+20+15+15+10+10+5 = 120 → 100
    assert compute_score(items) == 100
    assert risk_level_for_score(100) == "High observed risk indicators"


def test_equation_only_indicators():
    evidence = [
        {
            "indicator_id": "upfront_fee",
            "points": 25,
            "status": "indicator",
            "source": "Recruitment message",
            "also_found_in": [],
        },
        {
            "indicator_id": "website_reachability",
            "points": 0,
            "status": "unknown",
            "source": "Website lookup",
            "also_found_in": [],
        },
    ]
    eq = build_equation(evidence)
    assert len(eq) == 1
    assert eq[0]["indicator_id"] == "upfront_fee"


def test_blocked_localhost_url():
    assert is_safe_url("https://127.0.0.1/") is False
    assert is_safe_url("http://localhost/foo") is False
    assert is_safe_url("https://192.168.0.10/intern") is False
    assert is_safe_url("http://169.254.169.254/latest") is False
    assert is_safe_url("https://northwindlabs.com") is True
