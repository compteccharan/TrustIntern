"""Integration tests locking demo scores and safe fetch behavior."""

from __future__ import annotations

import io
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.analyze import Lookups, analyze_opportunity
from app.checks import check_website, default_fetch_url, is_safe_url
from app.main import app
from app.samples import get_sample, get_samples
from app.scoring import DISCLAIMER


def _stub_lookups() -> Lookups:
    def fetch_url(url: str) -> dict[str, Any]:
        raise AssertionError(f"fetch_url should not be called, got {url}")

    def rdap(host: str) -> dict[str, Any]:
        raise AssertionError(f"rdap should not be called, got {host}")

    return Lookups(fetch_url=fetch_url, rdap=rdap)


def _sample_as_data(sample_id: str) -> dict[str, Any]:
    s = get_sample(sample_id)
    assert s is not None
    return {
        "company_name": s["company_name"],
        "recruiter_name": s.get("recruiter_name"),
        "recruiter_email": s.get("recruiter_email") or None,
        "website_url": s.get("website_url"),
        "message": s["message"],
        "live_lookups": False,
        "pdf": None,
    }


def test_samples_endpoint_three_fictional():
    client = TestClient(app)
    resp = client.get("/api/samples")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    assert all(s.get("fictional") is True for s in data)
    assert {s["id"] for s in data} == {"suspicious", "consistent", "limited"}
    for s in data:
        assert "score" not in s


def test_health():
    client = TestClient(app)
    assert client.get("/api/health").json() == {"status": "ok"}


def test_suspicious_score_90():
    report = analyze_opportunity(_sample_as_data("suspicious"), _stub_lookups())
    assert report["disclaimer"] == DISCLAIMER
    assert report["score"] == 90
    assert report["risk_level"] == "High observed risk indicators"
    ids = [e["indicator_id"] for e in report["equation"]]
    assert ids == [
        "upfront_fee",
        "domain_mismatch",
        "sensitive_data",
        "unrelated_domain",
        "urgency",
        "personal_email",
    ]
    assert sum(e["points"] for e in report["equation"]) == 90


def test_consistent_score_0():
    report = analyze_opportunity(_sample_as_data("consistent"), _stub_lookups())
    assert report["score"] == 0
    assert report["risk_level"] == "Lower observed risk indicators"
    assert report["equation"] == []
    fee_indicators = [
        e
        for e in report["evidence"]
        if e["indicator_id"] == "upfront_fee" and e["status"] == "indicator"
    ]
    assert fee_indicators == []


def test_limited_score_0_private_url_not_fetched():
    fetched: list[str] = []

    def fetch_url(url: str) -> dict[str, Any]:
        fetched.append(url)
        return {"ok": True, "blocked": False, "status_code": 200, "final_url": url}

    def rdap(host: str) -> dict[str, Any]:
        fetched.append(f"rdap:{host}")
        return {"ok": True, "age_days": 400, "error": None}

    # Even with live_lookups true, private IP must not be fetched
    data = _sample_as_data("limited")
    data["live_lookups"] = True
    report = analyze_opportunity(data, Lookups(fetch_url=fetch_url, rdap=rdap))
    assert report["score"] == 0
    assert fetched == []  # blocked before request; RDAP also skipped for blocked host

    website = next(
        e for e in report["evidence"] if e["indicator_id"] == "website_reachability"
    )
    assert website["status"] == "unknown"

    # Default sample path with lookups off
    report_off = analyze_opportunity(_sample_as_data("limited"), _stub_lookups())
    assert report_off["score"] == 0
    website_off = next(
        e
        for e in report_off["evidence"]
        if e["indicator_id"] == "website_reachability"
    )
    assert website_off["status"] == "unknown"
    assert "Live lookup was not requested" in website_off["reason"]


def test_localhost_not_fetched():
    called = []

    def fetch_url(url: str) -> dict[str, Any]:
        called.append(url)
        return {"ok": True, "blocked": False, "status_code": 200, "final_url": url}

    result = check_website(
        "https://127.0.0.1/",
        live_lookups=True,
        fetch_url=fetch_url,
    )
    assert result["status"] == "unknown"
    assert called == []
    assert is_safe_url("https://127.0.0.1/") is False


def test_fee_message_and_pdf_deduped():
    # Build a tiny PDF containing registration fee
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    # pypdf blank page has no text — inject via page content is hard.
    # Use analyze path with mocked pdf bytes that extract_pdf_text can read.
    # Instead, call merge path via analyze with custom: use document.extract after
    # creating PDF with reportlab-like minimal content isn't available.
    # Fallback: unit-level already covers merge; here simulate by passing
    # message fee + manually verifying analyze_pdf + merge via monkeypatch.

    from app import document as document_mod

    original = document_mod.extract_pdf_text

    def fake_extract(pdf_bytes: bytes):
        return {
            "ok": True,
            "text": "Please pay the registration fee before onboarding.",
            "error": None,
        }

    document_mod.extract_pdf_text = fake_extract  # type: ignore[assignment]
    try:
        data = {
            "company_name": "Aurora Tech Pvt Ltd",
            "recruiter_name": "Riya Shah",
            "recruiter_email": "hr@aurora-tech.example",
            "website_url": "https://aurora-tech.example",
            "message": "Pay a registration fee of Rs 2000 to confirm your seat.",
            "live_lookups": False,
            "pdf": b"%PDF-fake",
        }
        report = analyze_opportunity(data, _stub_lookups())
        fee = [
            e
            for e in report["evidence"]
            if e["indicator_id"] == "upfront_fee" and e["status"] == "indicator"
        ]
        assert len(fee) == 1
        assert fee[0]["points"] == 25
        assert "Offer letter" in fee[0]["also_found_in"]
        # Score includes only one fee (plus possibly others from this crafted input)
        fee_points = sum(
            e["points"] for e in report["equation"] if e["indicator_id"] == "upfront_fee"
        )
        assert fee_points == 25
    finally:
        document_mod.extract_pdf_text = original  # type: ignore[assignment]


def test_missing_message_422():
    client = TestClient(app)
    resp = client.post(
        "/api/investigations",
        data={
            "company_name": "Acme",
            "message": "",
            "live_lookups": "false",
        },
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "validation_error"
    assert "message" in body["fields"]


def test_history_persists():
    client = TestClient(app)
    sample = get_sample("consistent")
    assert sample is not None
    resp = client.post(
        "/api/investigations",
        data={
            "company_name": sample["company_name"],
            "recruiter_name": sample["recruiter_name"],
            "recruiter_email": sample["recruiter_email"],
            "website_url": sample["website_url"],
            "message": sample["message"],
            "live_lookups": "false",
        },
    )
    assert resp.status_code == 200
    created = resp.json()
    assert created["id"] >= 1
    assert created["score"] == 0

    listed = client.get("/api/investigations").json()
    assert any(r["id"] == created["id"] for r in listed)

    one = client.get(f"/api/investigations/{created['id']}").json()
    assert one["id"] == created["id"]
    assert one["disclaimer"] == DISCLAIMER


def test_get_samples_helper():
    samples = get_samples()
    assert len(samples) == 3
