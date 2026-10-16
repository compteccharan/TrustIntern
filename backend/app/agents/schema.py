"""AgentSpec / AgentEvent contracts for the multi-agent OSINT runtime."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


EventType = Literal[
    "run_started",
    "planner_mode",
    "agent_started",
    "agent_finding",
    "agent_spawn",
    "agent_done",
    "score_ready",
    "narrative",
    "run_done",
    "error",
]


class Budget(BaseModel):
    max_http: int = 3
    timeout_s: float = 12.0


class AgentSpec(BaseModel):
    agent_type: str
    agent_id: str
    parent_id: str | None = None
    reason: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    priority: int = 50
    budget: Budget = Field(default_factory=Budget)
    depth: int = 0


class AgentEvent(BaseModel):
    type: EventType
    run_id: str
    ts: str
    payload: dict[str, Any] = Field(default_factory=dict)


ALLOWED_AGENT_TYPES: frozenset[str] = frozenset(
    {
        "fixed_checkers",
        "company_osint",
        "recruiter_osint",
        "domain_osint",
        "document_multimodal",
        "web_complaint_search",
        "entity_followup",
    }
)
