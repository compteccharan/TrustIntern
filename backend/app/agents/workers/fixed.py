"""Fixed checkers agent — wraps analyze_opportunity (score engine path)."""

from __future__ import annotations

import asyncio
from typing import Any

from app.analyze import Lookups, analyze_opportunity
from app.agents.schema import AgentSpec


async def run(ctx: dict[str, Any], spec: AgentSpec) -> list[dict[str, Any]]:
    """Run deterministic checkers. Returns evidence; full report stored on ctx."""
    data = ctx.get("data") or {}
    lookups: Lookups = ctx.get("lookups") or Lookups()

    def _sync() -> dict[str, Any]:
        return analyze_opportunity(data, lookups)

    report = await asyncio.to_thread(_sync)
    ctx["fixed_report"] = report
    evidence = list(report.get("evidence") or [])
    # Tag source for agent_trace readability without changing scoring fields
    for item in evidence:
        item.setdefault("_agent_type", "fixed_checkers")
        item.setdefault("_agent_id", spec.agent_id)
    return evidence
