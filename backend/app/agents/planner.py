"""Gemma spawn planner with heuristic fallback. Never assigns score points."""

from __future__ import annotations

import uuid
from typing import Any

from app.agents.gemma_client import GemmaClient
from app.agents.registry import catalog, is_allowed
from app.agents.schema import ALLOWED_AGENT_TYPES, AgentSpec, Budget
from app.agents.workers.followup import extract_entities


def heuristic_spawns(
    data: dict[str, Any],
    *,
    already: set[str] | None = None,
    parent_id: str | None = None,
    depth: int = 1,
) -> list[AgentSpec]:
    """Always-available demo planner when Gemma is down or forced off."""
    already = already or set()
    specs: list[AgentSpec] = []
    company = (data.get("company_name") or "").strip()
    email = (data.get("recruiter_email") or "").strip()
    website = (data.get("website_url") or "").strip()
    message = data.get("message") or ""
    pdf = data.get("pdf")
    image = data.get("image")

    def _add(agent_type: str, reason: str, inputs: dict[str, Any], priority: int = 50) -> None:
        if agent_type in already or agent_type == "fixed_checkers":
            return
        if not is_allowed(agent_type):
            return
        specs.append(
            AgentSpec(
                agent_type=agent_type,
                agent_id=str(uuid.uuid4()),
                parent_id=parent_id,
                reason=reason,
                inputs=inputs,
                priority=priority,
                budget=Budget(),
                depth=depth,
            )
        )
        already.add(agent_type)

    if company:
        _add(
            "company_osint",
            "Company name present — fetch public company presence",
            {"company_name": company, "website_url": website},
            priority=40,
        )
    if email or (data.get("recruiter_name") or "").strip():
        _add(
            "recruiter_osint",
            "Recruiter identity present — check email domain and public mentions",
            {
                "recruiter_name": data.get("recruiter_name"),
                "recruiter_email": email,
                "company_name": company,
            },
            priority=45,
        )
    if website:
        _add(
            "domain_osint",
            "Website URL present — check title/snippet consistency",
            {"website_url": website, "company_name": company},
            priority=50,
        )
    if pdf or image:
        reason = "Offer image uploaded — Gemma vision extracts quoted claims"
        if pdf and image:
            reason = "PDF and offer image uploaded — Gemma vision extracts quoted claims"
        elif pdf:
            reason = "PDF uploaded — rasterize first page for Gemma vision"
        _add(
            "document_multimodal",
            reason,
            {},
            priority=35,
        )
    if company:
        _add(
            "web_complaint_search",
            "Search public web for internship complaint mentions",
            {"company_name": company},
            priority=60,
        )

    entities = extract_entities(message)
    if entities["phones"] or entities["linkedin"] or entities["payments"]:
        value = (
            (entities["phones"] or entities["linkedin"] or entities["payments"])[0]
        )
        etype = (
            "phone"
            if entities["phones"]
            else "linkedin"
            if entities["linkedin"]
            else "payment"
        )
        _add(
            "entity_followup",
            f"Detected {etype} entity in message — follow up",
            {"entity_type": etype, "value": value},
            priority=55,
        )

    specs.sort(key=lambda s: s.priority)
    return specs


async def plan_next_agents(
    *,
    data: dict[str, Any],
    findings: list[dict[str, Any]],
    already_spawned: set[str],
    parent_id: str | None,
    depth: int,
    gemma: GemmaClient | None,
    force_heuristic: bool = False,
) -> tuple[str, list[AgentSpec], list[dict[str, Any]]]:
    """Return (mode, specs, rejected_unknowns).

    mode is 'gemma' or 'heuristic'.
    Rejected unknowns are agent_type dicts that must become error events.
    """
    rejected: list[dict[str, Any]] = []
    cat = catalog()
    summary = {
        "company_name": data.get("company_name"),
        "recruiter_name": data.get("recruiter_name"),
        "recruiter_email": data.get("recruiter_email"),
        "website_url": data.get("website_url"),
        "message_preview": (data.get("message") or "")[:180],
        "had_pdf": bool(data.get("pdf")),
        "had_image": bool(data.get("image")),
        "live_lookups": bool(data.get("live_lookups", True)),
    }

    use_gemma = (
        not force_heuristic
        and gemma is not None
        and gemma.available
    )

    if use_gemma:
        try:
            raw = await gemma.plan_spawns(
                summary=summary,
                findings=[
                    {
                        "indicator_id": f.get("indicator_id"),
                        "title": f.get("title"),
                        "status": f.get("status"),
                        "source": f.get("source"),
                    }
                    for f in findings
                ],
                catalog=cat,
                already_spawned=sorted(already_spawned),
            )
            specs: list[AgentSpec] = []
            seen = set(already_spawned)
            for item in raw:
                agent_type = str(item.get("agent_type") or "").strip()
                if not agent_type:
                    continue
                if agent_type == "fixed_checkers":
                    continue
                if agent_type not in ALLOWED_AGENT_TYPES or not is_allowed(agent_type):
                    rejected.append(
                        {
                            "agent_type": agent_type,
                            "reason": "unknown_agent_type",
                            "detail": item.get("reason"),
                        }
                    )
                    continue
                if agent_type in seen:
                    continue
                specs.append(
                    AgentSpec(
                        agent_type=agent_type,
                        agent_id=str(uuid.uuid4()),
                        parent_id=parent_id,
                        reason=str(item.get("reason") or "Planner spawn"),
                        inputs=dict(item.get("inputs") or {}),
                        priority=int(item.get("priority") or 50),
                        budget=Budget(),
                        depth=depth,
                    )
                )
                seen.add(agent_type)
            return "gemma", specs, rejected
        except Exception:  # noqa: BLE001
            pass

    specs = heuristic_spawns(
        data,
        already=set(already_spawned),
        parent_id=parent_id,
        depth=depth,
    )
    return "heuristic", specs, rejected


def reject_unknown_type(agent_type: str) -> dict[str, Any]:
    return {
        "agent_type": agent_type,
        "reason": "unknown_agent_type",
    }
