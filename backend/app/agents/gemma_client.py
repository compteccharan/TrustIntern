"""google-genai wrapper for Gemma 4 (planner + multimodal claims). Never scores."""

from __future__ import annotations

import json
import os
import re
from typing import Any


DEFAULT_MODEL = "gemma-4-26b-a4b-it"


class GemmaClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")
        self.model = model or os.environ.get("GEMMA_MODEL", DEFAULT_MODEL)
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def _ensure_client(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _generate(self, contents: Any, *, timeout_s: float = 20.0) -> str:
        client = self._ensure_client()
        # google-genai generate_content is sync; callers wrap with asyncio.to_thread
        response = client.models.generate_content(
            model=self.model,
            contents=contents,
        )
        text = getattr(response, "text", None) or ""
        if not text and getattr(response, "candidates", None):
            try:
                parts = response.candidates[0].content.parts
                text = "".join(getattr(p, "text", "") or "" for p in parts)
            except Exception:  # noqa: BLE001
                text = ""
        return text.strip()

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
    ) -> list[dict[str, str]]:
        """Multimodal: list scam-relevant claims with exact quotes; do not score."""
        import asyncio
        from google.genai import types

        prompt = (
            "List scam-relevant claims from this offer letter page with exact quotes. "
            "Do not score or rate risk. Return ONLY a JSON array of objects with keys: "
            "claim_type, quote. Focus on fees, urgency, sensitive data requests, company names."
        )
        if text_hint:
            prompt += f"\nExtracted text hint:\n{text_hint[:1200]}"

        def _call() -> str:
            image_bytes = __import__("base64").b64decode(image_b64)
            contents = [
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                        types.Part.from_text(text=prompt),
                    ],
                )
            ]
            return self._generate(contents)

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
    # Strip markdown fences
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    # Find first array
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < 0 or end <= start:
        raise ValueError("no_json_array")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("not_a_list")
    return [x for x in data if isinstance(x, dict)]
