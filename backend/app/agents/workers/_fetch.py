"""Safe HTTP helpers shared by OSINT workers."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from app.checks import is_safe_url


def unwrap_result_url(href: str) -> str:
    """Unwrap DuckDuckGo redirect links to the underlying http(s) target."""
    raw = (href or "").strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    parsed = urlparse(raw)
    qs = parse_qs(parsed.query)
    if "uddg" in qs and qs["uddg"]:
        return unquote(qs["uddg"][0])
    return raw


def normalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    return raw


def safe_get_text(
    url: str,
    *,
    timeout_s: float = 8.0,
    max_bytes: int = 200_000,
) -> dict[str, Any]:
    """Fetch a public URL and return title + text snippet. Never raises."""
    url = normalize_url(url)
    if not url or not is_safe_url(url):
        return {
            "ok": False,
            "blocked": True,
            "url": url,
            "title": None,
            "text": "",
            "error": "blocked",
        }
    try:
        resp = requests.get(
            url,
            timeout=timeout_s,
            allow_redirects=False,
            stream=True,
            headers={"User-Agent": "TrustIntern/1.0 (+osint)"},
        )
        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            if not location:
                return {
                    "ok": False,
                    "blocked": False,
                    "url": url,
                    "title": None,
                    "text": "",
                    "error": "redirect_missing_location",
                }
            next_url = requests.compat.urljoin(url, location)
            if not is_safe_url(next_url):
                return {
                    "ok": False,
                    "blocked": True,
                    "url": next_url,
                    "title": None,
                    "text": "",
                    "error": "blocked_redirect",
                }
            resp = requests.get(
                next_url,
                timeout=timeout_s,
                allow_redirects=False,
                stream=True,
                headers={"User-Agent": "TrustIntern/1.0 (+osint)"},
            )
            url = next_url

        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_content(chunk_size=8192):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                break
            chunks.append(chunk)
        body = b"".join(chunks)
        content_type = (resp.headers.get("Content-Type") or "").lower()
        title = None
        text = ""
        if "html" in content_type or body[:50].lstrip().lower().startswith(b"<!doctype") or b"<html" in body[:200].lower():
            soup = BeautifulSoup(body, "html.parser")
            if soup.title and soup.title.string:
                title = soup.title.string.strip()[:200]
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:2000]
        else:
            try:
                text = body.decode("utf-8", errors="replace")[:2000]
            except Exception:  # noqa: BLE001
                text = ""
        ok = 200 <= resp.status_code < 400
        return {
            "ok": ok,
            "blocked": False,
            "url": url,
            "status_code": resp.status_code,
            "title": title,
            "text": text,
            "error": None if ok else f"http_{resp.status_code}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "blocked": False,
            "url": url,
            "title": None,
            "text": "",
            "error": str(exc),
        }


_UA = {"User-Agent": "TrustIntern/1.0 (+osint; hackathon research)"}


def duckduckgo_search(query: str, *, timeout_s: float = 8.0, max_results: int = 3) -> list[dict[str, str]]:
    """Best-effort public HTML search. Often bot-blocked; prefer reddit_search / wikipedia."""
    q = (query or "").strip()
    if not q:
        return []
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": q},
            timeout=timeout_s,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        results: list[dict[str, str]] = []
        for result in soup.select(".result"):
            a = result.select_one("a.result__a")
            snippet_el = result.select_one(".result__snippet")
            if not a or not a.get("href"):
                continue
            href = unwrap_result_url(a["href"])
            parsed = urlparse(href if "://" in href else f"https://{href}")
            if parsed.scheme and parsed.scheme not in ("http", "https"):
                continue
            results.append(
                {
                    "title": (a.get_text() or "").strip()[:200],
                    "url": href,
                    "snippet": (snippet_el.get_text(" ", strip=True) if snippet_el else "")[:400],
                }
            )
            if len(results) >= max_results:
                break
        return results
    except Exception:  # noqa: BLE001
        return []


def reddit_search(
    query: str,
    *,
    timeout_s: float = 12.0,
    max_results: int = 3,
) -> list[dict[str, str]]:
    """Search Reddit archives via PullPush public JSON API."""
    q = (query or "").strip()
    if not q:
        return []
    endpoint = "https://api.pullpush.io/reddit/search/submission/"
    if not is_safe_url(endpoint):
        return []
    try:
        resp = requests.get(
            endpoint,
            params={"q": q, "size": max_results},
            timeout=timeout_s,
            headers=_UA,
        )
        if resp.status_code != 200:
            return []
        rows = (resp.json() or {}).get("data") or []
        out: list[dict[str, str]] = []
        for row in rows[:max_results]:
            permalink = row.get("permalink") or ""
            url = (
                f"https://www.reddit.com{permalink}"
                if str(permalink).startswith("/")
                else (row.get("url") or "")
            )
            title = (row.get("title") or "").strip()
            body = (row.get("selftext") or "").strip().replace("\n", " ")
            out.append(
                {
                    "title": title[:200],
                    "url": url,
                    "snippet": (body[:400] if body else title)[:400],
                    "subreddit": (row.get("subreddit") or "").strip(),
                }
            )
        return out
    except Exception:  # noqa: BLE001
        return []


def wikipedia_summary(title: str, *, timeout_s: float = 10.0) -> dict[str, Any] | None:
    """Fetch a Wikipedia REST summary for a company/topic name."""
    name = (title or "").strip()
    if not name:
        return None
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote_plus(name)}"
    try:
        resp = requests.get(url, timeout=timeout_s, headers=_UA)
        if resp.status_code != 200:
            return None
        data = resp.json()
        page_url = (
            (data.get("content_urls") or {}).get("desktop") or {}
        ).get("page")
        return {
            "ok": True,
            "title": data.get("title"),
            "extract": (data.get("extract") or "")[:500],
            "url": page_url,
            "disambiguation": data.get("type") == "disambiguation",
        }
    except Exception:  # noqa: BLE001
        return None


def clear_or_unknown(
    *,
    indicator_id: str,
    title: str,
    reason: str,
    status: str,
    source: str,
    source_url: str | None = None,
    excerpt: str | None = None,
) -> dict[str, Any]:
    """OSINT rows that must not invent score points."""
    return {
        "indicator_id": indicator_id,
        "title": title,
        "reason": reason,
        "excerpt": excerpt,
        "points": 0,
        "status": status,
        "source": source,
        "source_url": source_url,
        "also_found_in": [],
    }
