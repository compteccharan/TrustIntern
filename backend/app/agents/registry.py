"""Allowlisted agent_type → async worker mapping.

Unknown types from the planner are never executed.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.agents.schema import ALLOWED_AGENT_TYPES, AgentSpec
from app.agents.workers import (
    company,
    document_mm,
    domain,
    fixed,
    followup,
    recruiter,
    search,
)

AgentRunner = Callable[[dict[str, Any], AgentSpec], Awaitable[list[dict[str, Any]]]]

REGISTRY: dict[str, AgentRunner] = {
    "fixed_checkers": fixed.run,
    "company_osint": company.run,
    "recruiter_osint": recruiter.run,
    "domain_osint": domain.run,
    "document_multimodal": document_mm.run,
    "web_complaint_search": search.run,
    "entity_followup": followup.run,
}


def is_allowed(agent_type: str) -> bool:
    return agent_type in ALLOWED_AGENT_TYPES and agent_type in REGISTRY


def get_runner(agent_type: str) -> AgentRunner | None:
    if not is_allowed(agent_type):
        return None
    return REGISTRY[agent_type]


def catalog() -> list[dict[str, str]]:
    """Human-readable allowlist for the planner prompt."""
    descriptions = {
        "fixed_checkers": "Deterministic phrase/domain/PDF/RDAP checkers (always first)",
        "company_osint": "Safe fetch of company website + public presence snippets",
        "recruiter_osint": "Email domain + public search for recruiter + company",
        "domain_osint": "Domain title/snippet consistency vs company name",
        "document_multimodal": "Rasterize PDF page; extract quoted scam-relevant claims",
        "web_complaint_search": "Public web search for company + internship scam complaints",
        "entity_followup": "Follow up on phone, LinkedIn URL, or payment handle",
    }
    return [
        {"agent_type": t, "description": descriptions.get(t, t)}
        for t in sorted(ALLOWED_AGENT_TYPES)
        if t != "fixed_checkers"  # planner never re-spawns fixed; orchestrator owns it
    ]
