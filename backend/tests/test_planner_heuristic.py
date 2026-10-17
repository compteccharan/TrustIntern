"""Heuristic planner and unknown agent_type rejection."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.agents.gemma_client import GemmaClient
from app.agents.planner import heuristic_spawns, plan_next_agents
from app.agents.registry import is_allowed
from app.agents.schema import ALLOWED_AGENT_TYPES
from app.samples import get_sample


def _suspicious_data() -> dict[str, Any]:
    s = get_sample("suspicious")
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


def test_heuristic_spawns_company_and_recruiter():
    specs = heuristic_spawns(_suspicious_data(), already=set(), depth=1)
    types = [s.agent_type for s in specs]
    assert "company_osint" in types
    assert "recruiter_osint" in types
    assert "domain_osint" in types
    assert "web_complaint_search" in types
    assert "fixed_checkers" not in types
    for s in specs:
        assert is_allowed(s.agent_type)
        assert s.agent_type in ALLOWED_AGENT_TYPES


def test_heuristic_spawns_pdf_document_mm():
    data = _suspicious_data()
    data["pdf"] = b"%PDF-1.4 fake"
    specs = heuristic_spawns(data, already=set(), depth=1)
    assert any(s.agent_type == "document_multimodal" for s in specs)


def test_heuristic_spawns_image_document_mm():
    data = _suspicious_data()
    data["image"] = {"bytes": b"png", "mime": "image/png"}
    specs = heuristic_spawns(data, already=set(), depth=1)
    assert any(s.agent_type == "document_multimodal" for s in specs)


class _ImageOnlyPlanner(GemmaClient):
    """Captures the planner prompt without calling Ollama."""

    def __init__(self) -> None:
        super().__init__()
        self.prompt = ""

    @property
    def available(self) -> bool:  # type: ignore[override]
        return True

    def _generate(
        self,
        prompt: str,
        *,
        images: list[str] | None = None,
        timeout_s: float = 180.0,
    ) -> str:
        del images, timeout_s
        self.prompt = prompt
        return json.dumps(
            [
                {
                    "agent_type": "document_multimodal",
                    "reason": "Offer image uploaded",
                    "inputs": {},
                }
            ]
        )


def test_image_only_upload_reaches_gemma_planner():
    data = _suspicious_data()
    data["pdf"] = None
    data["image"] = {"bytes": b"\x89PNG\r\n", "mime": "image/png"}
    gemma = _ImageOnlyPlanner()
    mode, specs, rejected = asyncio.run(
        plan_next_agents(
            data=data,
            findings=[],
            already_spawned=set(),
            parent_id=None,
            depth=1,
            gemma=gemma,
            force_heuristic=False,
        )
    )
    assert mode == "gemma"
    assert rejected == []
    assert '"had_image": true' in gemma.prompt
    assert '"had_pdf": false' in gemma.prompt
    assert "If had_pdf or had_image is true, include document_multimodal" in gemma.prompt
    assert any(s.agent_type == "document_multimodal" for s in specs)


def test_heuristic_skips_already_spawned():
    data = _suspicious_data()
    specs = heuristic_spawns(
        data, already={"company_osint", "recruiter_osint"}, depth=1
    )
    types = {s.agent_type for s in specs}
    assert "company_osint" not in types
    assert "recruiter_osint" not in types


def test_unknown_agent_type_rejected_never_allowed():
    assert is_allowed("evil_shell") is False
    assert is_allowed("fixed_checkers") is True


class _FakeGemmaUnknown:
    available = True

    async def plan_spawns(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "agent_type": "rm_rf_root",
                "reason": "should never run",
                "inputs": {},
            },
            {
                "agent_type": "company_osint",
                "reason": "ok",
                "inputs": {"company_name": "Aurora Tech Pvt Ltd"},
            },
        ]


def test_planner_rejects_unknown_agent_type():
    mode, specs, rejected = asyncio.run(
        plan_next_agents(
            data=_suspicious_data(),
            findings=[],
            already_spawned=set(),
            parent_id="parent",
            depth=1,
            gemma=_FakeGemmaUnknown(),  # type: ignore[arg-type]
            force_heuristic=False,
        )
    )
    assert mode == "gemma"
    assert any(r["agent_type"] == "rm_rf_root" for r in rejected)
    assert all(r.get("reason") == "unknown_agent_type" for r in rejected)
    assert all(s.agent_type != "rm_rf_root" for s in specs)
    assert any(s.agent_type == "company_osint" for s in specs)


def test_force_heuristic_ignores_gemma():
    mode, specs, rejected = asyncio.run(
        plan_next_agents(
            data=_suspicious_data(),
            findings=[],
            already_spawned=set(),
            parent_id=None,
            depth=1,
            gemma=_FakeGemmaUnknown(),  # type: ignore[arg-type]
            force_heuristic=True,
        )
    )
    assert mode == "heuristic"
    assert rejected == []
    assert any(s.agent_type == "company_osint" for s in specs)
