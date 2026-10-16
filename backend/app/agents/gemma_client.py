"""Local Ollama client for Gemma 4 (planner + multimodal claims). Never scores."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


DEFAULT_MODEL = "gemma4:e2b"
DEFAULT_HOST = "http://127.0.0.1:11434"


def ollama_base_url(host: str | None = None) -> str:
    raw = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).strip().rstrip("/")
    if not raw.startswith("http://") and not raw.startswith("https://"):
        raw = "http://" + raw
    return raw


def ollama_reachable(host: str | None = None, timeout: float = 1.5) -> bool:
    url = ollama_base_url(host) + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except Exception:  # noqa: BLE001
        return False


class GemmaClient:
    def __init__(
        self,
        host: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        # api_key is unused. Local Ollama does not need one.
        del api_key
        self.host = ollama_base_url(host)
        self.model = model or os.environ.get("GEMMA_MODEL", DEFAULT_MODEL)

    @property
    def available(self) -> bool:
        return ollama_reachable(self.host)

    def _generate(
        self,
        prompt: str,
        *,
        images: list[str] | None = None,
        timeout_s: float = 180.0,
    ) -> str:
        message: dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            message["images"] = images
        payload = {
            "model": self.model,
            "messages": [message],
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.2,
                "top_p": 0.95,
                "top_k": 64,
                "num_ctx": 4096,
                "num_predict": 700,
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.host + "/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"ollama_http_{exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"ollama_unreachable: {exc.reason}") from exc
        message_out = body.get("message") or {}
        return str(message_out.get("content") or "").strip()

    async def plan_spawns(
        self,
        *,
        summary: dict[str, Any],
        findings: list[dict[str, Any]],
        catalog: list[dict[str, str]],
        already_spawned: list[str],
    ) -> list[dict[str, Any]]:
        """Ask Gemma for JSON spawn specs. Raises on failure so planner can fall back."""
        import asyncio

        prompt = (
            "You are an OSINT planner for internship scam investigations.\n"
            "You NEVER assign risk scores or points. You only propose agents to run.\n"
            "Return ONLY a JSON array of objects with keys: agent_type, reason, inputs.\n"
            f"Allowlisted agent_type values: {[c['agent_type'] for c in catalog]}\n"
            f"Catalog: {json.dumps(catalog)}\n"
            f"Input summary: {json.dumps(summary)}\n"
            f"Recent findings (truncated): {json.dumps(findings[:12], default=str)}\n"
            f"Already spawned types: {already_spawned}\n"
            "Propose 0-3 useful next agents. Prefer company_osint, recruiter_osint, "
            "document_multimodal, web_complaint_search, entity_followup, domain_osint.\n"
            "Do not invent agent_type values outside the allowlist."
        )

        def _call() -> str:
            return self._generate(prompt)

        text = await asyncio.to_thread(_call)
        return _parse_json_array(text)

    async def extract_document_claims(
        self,
        *,
        image_b64: str,
        text_hint: str = "",
        mime_type: str = "image/png",
    ) -> list[dict[str, str]]:
        """Multimodal: list scam-relevant claims with exact quotes; do not score."""
        import asyncio

        del mime_type  # Ollama takes raw base64; the local model infers the image type.
        prompt = (
            "List scam-relevant claims from this offer letter page with exact quotes. "
            "Do not score or rate risk. Return ONLY a JSON array of objects with keys: "
            "claim_type, quote. Focus on fees, urgency, sensitive data requests, company names."
        )
        if text_hint:
            prompt += f"\nExtracted text hint:\n{text_hint[:1200]}"
        image = (image_b64 or "").strip()
        if image.startswith("data:") and "," in image:
            image = image.split(",", 1)[1]

        def _call() -> str:
            return self._generate(prompt, images=[image] if image else None)

        text = await asyncio.to_thread(_call)
        raw = _parse_json_array(text)
        out: list[dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            quote = str(item.get("quote") or "").strip()
            if not quote:
                continue
            out.append(
                {
                    "claim_type": str(item.get("claim_type") or "scam_relevant"),
                    "quote": quote[:400],
                }
            )
        return out

    async def narrative(self, *, score: int, evidence: list[dict[str, Any]]) -> str:
        """Plain-language restatement of the scored ledger. Does not invent points."""
        import asyncio

        indicators = [
            e
            for e in evidence
            if e.get("status") == "indicator"
        ]
        prompt = (
            "Restate this internship investigation ledger in 2-4 plain sentences for a student. "
            "Do not invent new risk scores or change the numbers. "
            f"Score from deterministic rules: {score}. "
            f"Indicators: {json.dumps(indicators[:10], default=str)}"
        )

        def _call() -> str:
            return self._generate(prompt)

        try:
            text = await asyncio.to_thread(_call)
            return text[:1200] if text else _fallback_narrative(score, indicators)
        except Exception:  # noqa: BLE001
            return _fallback_narrative(score, indicators)


def _fallback_narrative(score: int, indicators: list[dict[str, Any]]) -> str:
    if not indicators:
        return (
            f"Deterministic checkers scored this opportunity at {score}. "
            "No weighted risk indicators fired; verify the role independently."
        )
    labels = [e.get("title") or e.get("indicator_id") for e in indicators[:5]]
    return (
        f"Deterministic checkers scored this opportunity at {score}. "
        f"Observed indicators include: {', '.join(str(x) for x in labels)}. "
        "This is a heuristic indicator score, not a probability of fraud."
    )


def _parse_json_array(text: str) -> list[dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty_model_response")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < 0 or end <= start:
        raise ValueError("no_json_array")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("not_a_list")
    return [x for x in data if isinstance(x, dict)]
