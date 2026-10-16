"""Phrase rules, domain comparison, website fetch, and RDAP checks."""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from app.scoring import INDICATORS

FEE_PHRASES = [
    "registration fee",
    "training fee",
    "processing fee",
    "security deposit",
    "refundable deposit",
    "internship fee",
    "enrollment fee",
    "pay to confirm",
    "payment required",
]

FEE_NEGATIONS = [
    "no fee",
    "no payment",
    "without payment",
    "free of charge",
]

URGENCY_PHRASES = [
    "only one slot",
    "only 1 slot",
    "only 1 internship slot",
    "limited seats",
    "act now",
    "last chance",
    "within 24 hours",
    "guaranteed selection",
    "offer expires",
]

SENSITIVE_PHRASES = [
    "bank account",
    "otp",
    "upi pin",
    "cvv",
    "aadhaar",
    "aadhar",
    "ssn",
    "password",
    "routing number",
    "ifsc",
]

PERSONAL_EMAIL_HOSTS = {
    "gmail.com",
    "yahoo.com",
    "yahoo.co.in",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "proton.me",
    "protonmail.com",
    "icloud.com",
}

COMPANY_SUFFIXES = {"pvt", "ltd", "llc", "inc", "private", "limited"}

FetchUrlFn = Callable[[str], dict[str, Any]]
RdapFn = Callable[[str], dict[str, Any]]


def _excerpt_around(text: str, phrase: str, radius: int = 40) -> str:
    lower = text.lower()
    idx = lower.find(phrase.lower())
    if idx < 0:
        return phrase
    start = max(0, idx - radius)
    end = min(len(text), idx + len(phrase) + radius)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


def _sentence_has_negation(sentence: str) -> bool:
    lower = sentence.lower()
    return any(neg in lower for neg in FEE_NEGATIONS)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p for p in parts if p.strip()]


def find_fee_evidence(text: str, source: str) -> dict[str, Any] | None:
    sentences = _sentences(text) or [text]
    for sentence in sentences:
        if _sentence_has_negation(sentence):
            continue
        lower = sentence.lower()
        for phrase in FEE_PHRASES:
            if phrase in lower:
                reason = (
                    "The recruitment message asks for a registration fee."
                    if source == "Recruitment message"
                    else "The offer document asks for an upfront fee."
                )
                return {
                    "indicator_id": "upfront_fee",
                    "title": "Upfront payment requested",
                    "reason": reason,
                    "excerpt": _excerpt_around(text, phrase),
                    "points": INDICATORS["upfront_fee"]["points"],
                    "status": "indicator",
                    "source": source,
                    "source_url": None,
                    "also_found_in": [],
                }
    return None


def find_urgency_evidence(text: str, source: str) -> dict[str, Any] | None:
    lower = text.lower()
    for phrase in URGENCY_PHRASES:
        if phrase in lower:
            return {
                "indicator_id": "urgency",
                "title": "Urgency or guaranteed selection",
                "reason": "The message uses urgency or guarantee language.",
                "excerpt": _excerpt_around(text, phrase),
                "points": INDICATORS["urgency"]["points"],
                "status": "indicator",
                "source": source,
                "source_url": None,
                "also_found_in": [],
            }
    return None


def find_sensitive_evidence(text: str, source: str) -> dict[str, Any] | None:
    lower = text.lower()
    for phrase in SENSITIVE_PHRASES:
        # Word-boundary-ish for short tokens like otp/ssn/cvv
        if len(phrase) <= 4:
            if not re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", lower):
                continue
        elif phrase not in lower:
            continue
        return {
            "indicator_id": "sensitive_data",
            "title": "Sensitive data requested",
            "reason": "The message asks for bank details, OTP, or identity information.",
            "excerpt": _excerpt_around(text, phrase),
            "points": INDICATORS["sensitive_data"]["points"],
            "status": "indicator",
            "source": source,
            "source_url": None,
            "also_found_in": [],
        }
    return None


def _host_from_url(url: str | None) -> str | None:
    if not url or not url.strip():
        return None
    raw = url.strip()
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    host = (parsed.hostname or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _email_host(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    host = email.rsplit("@", 1)[-1].lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def check_personal_email(
    email: str | None, company_name: str
) -> dict[str, Any] | None:
    if not company_name or not company_name.strip():
        return None
    host = _email_host(email)
    if not host:
        return None
    if host in PERSONAL_EMAIL_HOSTS:
        return {
            "indicator_id": "personal_email",
            "title": "Personal email provider",
            "reason": "The recruiter email uses a consumer email provider.",
            "excerpt": email,
            "points": INDICATORS["personal_email"]["points"],
            "status": "indicator",
            "source": "Recruiter email",
            "source_url": None,
            "also_found_in": [],
        }
    return None


def check_domain_mismatch(
    email: str | None, website_url: str | None
) -> dict[str, Any]:
    email_host = _email_host(email)
    web_host = _host_from_url(website_url)
    if not email_host or not web_host:
        return {
            "indicator_id": "domain_mismatch",
            "title": "Email domain not compared",
            "reason": "Email or website was missing, so domains could not be compared.",
            "excerpt": None,
            "points": 0,
            "status": "unknown",
            "source": "Domain comparison",
            "source_url": None,
            "also_found_in": [],
        }
    if email_host == web_host:
        return {
            "indicator_id": "domain_mismatch",
            "title": "Email domain matches website",
            "reason": "Recruiter email host matches the website host.",
            "excerpt": f"{email_host} vs {web_host}",
            "points": 0,
            "status": "clear",
            "source": "Domain comparison",
            "source_url": None,
            "also_found_in": [],
        }
    # Personal email vs company site still counts as mismatch when both present
    return {
        "indicator_id": "domain_mismatch",
        "title": "Email domain does not match website",
        "reason": "The recruiter email host differs from the company website host.",
        "excerpt": f"{email_host} vs {web_host}",
        "points": INDICATORS["domain_mismatch"]["points"],
        "status": "indicator",
        "source": "Domain comparison",
        "source_url": None,
        "also_found_in": [],
    }


def _company_tokens(company_name: str) -> list[str]:
    raw = re.findall(r"[a-zA-Z]+", company_name.lower())
    return [t for t in raw if t not in COMPANY_SUFFIXES and len(t) >= 4]


def check_unrelated_domain(
    company_name: str, website_url: str | None
) -> dict[str, Any] | None:
    host = _host_from_url(website_url)
    if not host or not company_name.strip():
        return None
    # IP literals are not meaningful company domains — do not score unrelated_domain
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    host_flat = host.replace(".", "")
    tokens = _company_tokens(company_name)
    if not tokens:
        return None
    for token in tokens:
        if token in host_flat:
            return {
                "indicator_id": "unrelated_domain",
                "title": "Company name appears in domain",
                "reason": "A company name token appears in the website host.",
                "excerpt": f"{token} in {host}",
                "points": 0,
                "status": "clear",
                "source": "Domain comparison",
                "source_url": None,
                "also_found_in": [],
            }
    return {
        "indicator_id": "unrelated_domain",
        "title": "Company name not in domain",
        "reason": "No significant company name token appears in the website host.",
        "excerpt": f"{company_name} vs {host}",
        "points": INDICATORS["unrelated_domain"]["points"],
        "status": "indicator",
        "source": "Domain comparison",
        "source_url": None,
        "also_found_in": [],
    }


def is_blocked_host(host: str | None) -> bool:
    if not host:
        return True
    h = host.lower().strip(".")
    if h == "localhost" or h.endswith(".localhost"):
        return True
    if h == "metadata.google.internal":
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        # Resolve not done here — block obvious private name patterns only via IP literals
        return False
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return True
    # Explicit metadata IP
    if str(ip) == "169.254.169.254":
        return True
    return False


def is_safe_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if is_blocked_host(host):
        return False
    return True


def default_fetch_url(url: str) -> dict[str, Any]:
    """Fetch URL safely. Returns status clear/unknown dict-like result."""
    if not is_safe_url(url):
        return {
            "ok": False,
            "blocked": True,
            "status_code": None,
            "final_url": url,
            "error": "blocked",
        }
    try:
        resp = requests.get(
            url,
            timeout=8,
            allow_redirects=False,
            stream=True,
            headers={"User-Agent": "TrustIntern/1.0"},
        )
        # One redirect hop if Location present
        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            if not location:
                return {
                    "ok": False,
                    "blocked": False,
                    "status_code": resp.status_code,
                    "final_url": url,
                    "error": "redirect_missing_location",
                }
            next_url = requests.compat.urljoin(url, location)
            if not is_safe_url(next_url):
                return {
                    "ok": False,
                    "blocked": True,
                    "status_code": None,
                    "final_url": next_url,
                    "error": "blocked_redirect",
                }
            resp = requests.get(
                next_url,
                timeout=8,
                allow_redirects=False,
                stream=True,
                headers={"User-Agent": "TrustIntern/1.0"},
            )
            url = next_url

        # Cap body read ~1 MB
        max_bytes = 1_000_000
        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_content(chunk_size=8192):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                break
            chunks.append(chunk)
        ok = 200 <= resp.status_code < 400
        return {
            "ok": ok,
            "blocked": False,
            "status_code": resp.status_code,
            "final_url": url,
            "error": None if ok else f"http_{resp.status_code}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "blocked": False,
            "status_code": None,
            "final_url": url,
            "error": str(exc),
        }


def check_website(
    website_url: str | None,
    live_lookups: bool,
    fetch_url: FetchUrlFn | None = None,
) -> dict[str, Any]:
    if not live_lookups:
        return {
            "indicator_id": "website_reachability",
            "title": "Website not checked",
            "reason": "Live lookup was not requested for this run.",
            "excerpt": None,
            "points": 0,
            "status": "unknown",
            "source": "Website lookup",
            "source_url": website_url,
            "also_found_in": [],
        }
    if not website_url or not website_url.strip():
        return {
            "indicator_id": "website_reachability",
            "title": "Website not provided",
            "reason": "No website URL was supplied.",
            "excerpt": None,
            "points": 0,
            "status": "unknown",
            "source": "Website lookup",
            "source_url": None,
            "also_found_in": [],
        }
    url = website_url.strip()
    if "://" not in url:
        url = "https://" + url

    if not is_safe_url(url):
        return {
            "indicator_id": "website_reachability",
            "title": "Website not fetched",
            "reason": "The URL targets a private, local, or blocked address and was not fetched.",
            "excerpt": website_url,
            "points": 0,
            "status": "unknown",
            "source": "Website lookup",
            "source_url": website_url,
            "also_found_in": [],
        }

    fetcher = fetch_url or default_fetch_url
    result = fetcher(url)
    if result.get("blocked"):
        return {
            "indicator_id": "website_reachability",
            "title": "Website not fetched",
            "reason": "The URL targets a private, local, or blocked address and was not fetched.",
            "excerpt": website_url,
            "points": 0,
            "status": "unknown",
            "source": "Website lookup",
            "source_url": website_url,
            "also_found_in": [],
        }
    if result.get("ok"):
        return {
            "indicator_id": "website_reachability",
            "title": "Website reachable",
            "reason": f"HTTP {result.get('status_code')} response received.",
            "excerpt": None,
            "points": 0,
            "status": "clear",
            "source": "Website lookup",
            "source_url": result.get("final_url") or website_url,
            "also_found_in": [],
        }
    return {
        "indicator_id": "website_reachability",
        "title": "Website unreachable",
        "reason": "The website could not be reached or returned an error.",
        "excerpt": result.get("error"),
        "points": 0,
        "status": "unknown",
        "source": "Website lookup",
        "source_url": website_url,
        "also_found_in": [],
    }


def default_rdap(host: str) -> dict[str, Any]:
    try:
        resp = requests.get(
            f"https://rdap.org/domain/{host}",
            timeout=8,
            headers={"User-Agent": "TrustIntern/1.0"},
        )
        if resp.status_code != 200:
            return {"ok": False, "age_days": None, "error": f"http_{resp.status_code}"}
        data = resp.json()
        events = data.get("events") or []
        created = None
        for ev in events:
            if ev.get("eventAction") in ("registration", "registered"):
                created = ev.get("eventDate")
                break
        if not created:
            return {"ok": False, "age_days": None, "error": "no_registration_date"}
        # Parse ISO date
        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - created_dt).days
        return {"ok": True, "age_days": age, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "age_days": None, "error": str(exc)}


def check_domain_age(
    website_url: str | None,
    live_lookups: bool,
    rdap: RdapFn | None = None,
) -> dict[str, Any]:
    if not live_lookups:
        return {
            "indicator_id": "young_domain",
            "title": "Domain age not checked",
            "reason": "Live lookup was not requested for this run.",
            "excerpt": None,
            "points": 0,
            "status": "unknown",
            "source": "RDAP lookup",
            "source_url": website_url,
            "also_found_in": [],
        }
    host = _host_from_url(website_url)
    if not host or is_blocked_host(host):
        return {
            "indicator_id": "young_domain",
            "title": "Domain age unknown",
            "reason": "No usable public domain was available for RDAP lookup.",
            "excerpt": None,
            "points": 0,
            "status": "unknown",
            "source": "RDAP lookup",
            "source_url": website_url,
            "also_found_in": [],
        }
    lookup = rdap or default_rdap
    result = lookup(host)
    if not result.get("ok") or result.get("age_days") is None:
        return {
            "indicator_id": "young_domain",
            "title": "Domain age unknown",
            "reason": "RDAP lookup failed or returned no registration date.",
            "excerpt": result.get("error"),
            "points": 0,
            "status": "unknown",
            "source": "RDAP lookup",
            "source_url": website_url,
            "also_found_in": [],
        }
    age_days = int(result["age_days"])
    if age_days < 180:
        return {
            "indicator_id": "young_domain",
            "title": "Newly registered domain",
            "reason": f"Domain registered approximately {age_days} days ago.",
            "excerpt": f"{host}: {age_days} days",
            "points": INDICATORS["young_domain"]["points"],
            "status": "indicator",
            "source": "RDAP lookup",
            "source_url": website_url,
            "also_found_in": [],
        }
    return {
        "indicator_id": "young_domain",
        "title": "Domain age looks established",
        "reason": f"Domain registered approximately {age_days} days ago.",
        "excerpt": f"{host}: {age_days} days",
        "points": 0,
        "status": "clear",
        "source": "RDAP lookup",
        "source_url": website_url,
        "also_found_in": [],
    }


def scan_text_phrases(text: str, source: str) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for finder in (find_fee_evidence, find_urgency_evidence, find_sensitive_evidence):
        item = finder(text, source)
        if item:
            evidence.append(item)
    return evidence
