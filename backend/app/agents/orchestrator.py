"""Async multi-agent orchestrator: fixed checkers first, then planner spawn loop."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.agents.bus import EventBus, bus as default_bus
from app.agents.gemma_client import GemmaClient, _fallback_narrative
from app.agents.planner import plan_next_agents
from app.agents.registry import get_runner, is_allowed
from app.agents.schema import AgentEvent, AgentSpec, Budget
from app.analyze import Lookups
from app.scoring import (
    DISCLAIMER,
    build_equation,
    build_recommendations,
    compute_score,
    merge_evidence,
    risk_level_for_score,
)
from app.storage import save_report

MAX_AGENTS = 8
MAX_DEPTH = 2
WALL_CLOCK_S = 45.0


def _now_iso() -> str:
    try:
        return datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc).isoformat()


def _event(run_id: str, etype: str, payload: dict[str, Any]) -> AgentEvent:
    return AgentEvent(type=etype, run_id=run_id, ts=_now_iso(), payload=payload)  # type: ignore[arg-type]


class Orchestrator:
    def __init__(
        self,
        event_bus: EventBus | None = None,
        gemma: GemmaClient | None = None,
        lookups: Lookups | None = None,
        *,
        force_heuristic: bool = False,
        max_agents: int = MAX_AGENTS,
        max_depth: int = MAX_DEPTH,
        wall_clock_s: float = WALL_CLOCK_S,
        persist: bool = True,
    ) -> None:
        self.bus = event_bus or default_bus
        self.gemma = gemma if gemma is not None else GemmaClient()
        self.lookups = lookups or Lookups()
        self.force_heuristic = force_heuristic
        self.max_agents = max_agents
        self.max_depth = max_depth
        self.wall_clock_s = wall_clock_s
        self.persist = persist

    async def run(self, run_id: str, data: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        # Idempotent if start_run already created the queue
        if await self.bus.subscribe(run_id) is None:
            await self.bus.create_run(run_id)
        await self.bus.publish(
            _event(
                run_id,
                "run_started",
                {
                    "company_name": data.get("company_name"),
                    "live_lookups": bool(data.get("live_lookups", True)),
                },
            )
        )

        ctx: dict[str, Any] = {
            "data": data,
            "lookups": self.lookups,
            "gemma": self.gemma,
            "force_heuristic": self.force_heuristic,
            "run_id": run_id,
        }
        all_evidence: list[dict[str, Any]] = []
        agent_trace: list[dict[str, Any]] = []
        agents_run = 0
        already_spawned: set[str] = set()
        planner_mode_emitted = False
        planner_mode = "heuristic"

        # 1) Always run fixed_checkers first
        fixed_spec = AgentSpec(
            agent_type="fixed_checkers",
            agent_id=str(uuid.uuid4()),
            parent_id=None,
            reason="Deterministic score engine — always first",
            inputs={},
            priority=0,
            budget=Budget(),
            depth=0,
        )
        fixed_evidence = await self._execute_agent(
            run_id, ctx, fixed_spec, all_evidence, agent_trace
        )
        agents_run += 1
        already_spawned.add("fixed_checkers")
        all_evidence.extend(fixed_evidence)

        # 2) Initial planner spawn
        mode, specs, rejected = await plan_next_agents(
            data=data,
            findings=all_evidence,
            already_spawned=already_spawned,
            parent_id=fixed_spec.agent_id,
            depth=1,
            gemma=self.gemma,
            force_heuristic=self.force_heuristic,
        )
        planner_mode = mode
        if not planner_mode_emitted:
            await self.bus.publish(
                _event(run_id, "planner_mode", {"mode": planner_mode})
            )
            planner_mode_emitted = True

        for rej in rejected:
            await self.bus.publish(
                _event(
                    run_id,
                    "error",
                    {
                        "reason": "unknown_agent_type",
                        "agent_type": rej.get("agent_type"),
                        "detail": rej.get("detail"),
                    },
                )
            )

        queue: asyncio.Queue[AgentSpec] = asyncio.Queue()
        for spec in specs:
            await queue.put(spec)
            await self.bus.publish(
                _event(
                    run_id,
                    "agent_spawn",
                    {
                        "agent_type": spec.agent_type,
                        "agent_id": spec.agent_id,
                        "parent_id": spec.parent_id,
                        "reason": spec.reason,
                        "depth": spec.depth,
                    },
                )
            )
            already_spawned.add(spec.agent_type)

        # 3) Spawn / execute loop with caps
        while not queue.empty() and agents_run < self.max_agents:
            if time.monotonic() - started > self.wall_clock_s:
                await self.bus.publish(
                    _event(
                        run_id,
                        "error",
                        {"reason": "wall_clock_exceeded", "limit_s": self.wall_clock_s},
                    )
                )
                break

            spec = await queue.get()
            if not is_allowed(spec.agent_type):
                await self.bus.publish(
                    _event(
                        run_id,
                        "error",
                        {
                            "reason": "unknown_agent_type",
                            "agent_type": spec.agent_type,
                            "agent_id": spec.agent_id,
                        },
                    )
                )
                continue

            if spec.depth > self.max_depth:
                continue

            findings = await self._execute_agent(
                run_id, ctx, spec, all_evidence, agent_trace
            )
            agents_run += 1
            all_evidence.extend(findings)

            # Dynamic follow-up spawn if depth allows
            if (
                agents_run < self.max_agents
                and spec.depth < self.max_depth
                and time.monotonic() - started <= self.wall_clock_s
            ):
                mode2, more, rej2 = await plan_next_agents(
                    data=data,
                    findings=findings,
                    already_spawned=already_spawned,
                    parent_id=spec.agent_id,
                    depth=spec.depth + 1,
                    gemma=self.gemma,
                    force_heuristic=self.force_heuristic,
                )
                for rej in rej2:
                    await self.bus.publish(
                        _event(
                            run_id,
                            "error",
                            {
                                "reason": "unknown_agent_type",
                                "agent_type": rej.get("agent_type"),
                                "detail": rej.get("detail"),
                            },
                        )
                    )
                for child in more:
                    if agents_run + queue.qsize() >= self.max_agents:
                        break
                    if child.agent_type in already_spawned:
                        continue
                    await queue.put(child)
                    already_spawned.add(child.agent_type)
                    await self.bus.publish(
                        _event(
                            run_id,
                            "agent_spawn",
                            {
                                "agent_type": child.agent_type,
                                "agent_id": child.agent_id,
                                "parent_id": child.parent_id,
                                "reason": child.reason,
                                "depth": child.depth,
                                "planner_mode": mode2,
                            },
                        )
                    )

        # 4) Score from scoring.py only (strip internal agent tags)
        clean_evidence = []
        for item in all_evidence:
            row = {k: v for k, v in item.items() if not str(k).startswith("_")}
            clean_evidence.append(row)
        merged = merge_evidence(clean_evidence)
        score = compute_score(merged)
        equation = build_equation(merged)
        recommendations = build_recommendations(merged)

        await self.bus.publish(
            _event(
                run_id,
                "score_ready",
                {
                    "score": score,
                    "risk_level": risk_level_for_score(score),
                    "equation": equation,
                    "disclaimer": DISCLAIMER,
                },
            )
        )

        # 5) Narrative (Gemma restates ledger; fallback if unavailable)
        narrative_text = _fallback_narrative(
            score, [e for e in merged if e.get("status") == "indicator"]
        )
        if self.gemma and self.gemma.available and not self.force_heuristic:
            try:
                narrative_text = await self.gemma.narrative(
                    score=score, evidence=merged
                )
            except Exception:  # noqa: BLE001
                pass
        await self.bus.publish(
            _event(run_id, "narrative", {"text": narrative_text})
        )

        # Prefer fixed report input_summary / created_at when available
        fixed_report = ctx.get("fixed_report") or {}
        report: dict[str, Any] = {
            "id": 0,
            "created_at": fixed_report.get("created_at") or _now_iso(),
            "score": score,
            "risk_level": risk_level_for_score(score),
            "disclaimer": DISCLAIMER,
            "equation": equation,
            "evidence": merged,
            "recommendations": recommendations,
            "input_summary": fixed_report.get("input_summary")
            or {
                "company_name": (data.get("company_name") or "").strip(),
                "recruiter_name": data.get("recruiter_name"),
                "recruiter_email": data.get("recruiter_email"),
                "website_url": data.get("website_url"),
                "message_preview": (data.get("message") or "")[:180],
                "had_pdf": bool(data.get("pdf")),
                "live_lookups": bool(data.get("live_lookups", True)),
            },
            "agent_trace": agent_trace,
            "narrative": narrative_text,
            "run_id": run_id,
            "planner_mode": planner_mode,
        }

        if self.persist:
            report = await asyncio.to_thread(save_report, report)

        await self.bus.publish(
            _event(
                run_id,
                "run_done",
                {
                    "report_id": report.get("id"),
                    "score": score,
                    "agents_run": agents_run,
                    "planner_mode": planner_mode,
                },
            )
        )
        await self.bus.complete(run_id)
        return report

    async def _execute_agent(
        self,
        run_id: str,
        ctx: dict[str, Any],
        spec: AgentSpec,
        _all_evidence: list[dict[str, Any]],
        agent_trace: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        runner = get_runner(spec.agent_type)
        await self.bus.publish(
            _event(
                run_id,
                "agent_started",
                {
                    "agent_type": spec.agent_type,
                    "agent_id": spec.agent_id,
                    "reason": spec.reason,
                    "depth": spec.depth,
                },
            )
        )
        findings: list[dict[str, Any]] = []
        error: str | None = None
        if runner is None:
            error = "unknown_agent_type"
            await self.bus.publish(
                _event(
                    run_id,
                    "error",
                    {
                        "reason": "unknown_agent_type",
                        "agent_type": spec.agent_type,
                        "agent_id": spec.agent_id,
                    },
                )
            )
        else:
            try:
                findings = await runner(ctx, spec)
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                await self.bus.publish(
                    _event(
                        run_id,
                        "error",
                        {
                            "reason": "agent_failed",
                            "agent_type": spec.agent_type,
                            "agent_id": spec.agent_id,
                            "detail": error,
                        },
                    )
                )
                findings = []

        for item in findings:
            item.setdefault("_agent_type", spec.agent_type)
            item.setdefault("_agent_id", spec.agent_id)
            await self.bus.publish(
                _event(
                    run_id,
                    "agent_finding",
                    {
                        "agent_type": spec.agent_type,
                        "agent_id": spec.agent_id,
                        "indicator_id": item.get("indicator_id"),
                        "title": item.get("title"),
                        "status": item.get("status"),
                        "points": item.get("points"),
                        "source": item.get("source"),
                        "source_url": item.get("source_url"),
                    },
                )
            )

        await self.bus.publish(
            _event(
                run_id,
                "agent_done",
                {
                    "agent_type": spec.agent_type,
                    "agent_id": spec.agent_id,
                    "finding_count": len(findings),
                    "error": error,
                },
            )
        )
        agent_trace.append(
            {
                "agent_type": spec.agent_type,
                "agent_id": spec.agent_id,
                "parent_id": spec.parent_id,
                "reason": spec.reason,
                "depth": spec.depth,
                "finding_count": len(findings),
                "error": error,
            }
        )
        return findings


# In-memory run registry for API status
_runs: dict[str, dict[str, Any]] = {}


def get_run(run_id: str) -> dict[str, Any] | None:
    return _runs.get(run_id)


def register_run(run_id: str, meta: dict[str, Any]) -> None:
    _runs[run_id] = meta


async def start_run(
    data: dict[str, Any],
    *,
    force_heuristic: bool | None = None,
    lookups: Lookups | None = None,
    persist: bool = True,
) -> str:
    """Create run_id, schedule orchestrator background task, return run_id."""
    import os

    run_id = str(uuid.uuid4())
    if force_heuristic is None:
        force = os.environ.get("FORCE_HEURISTIC_PLANNER", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
    else:
        force = force_heuristic

    orch = Orchestrator(
        lookups=lookups,
        force_heuristic=force,
        persist=persist,
    )
    # Create the SSE queue before the background task so subscribers never race.
    await default_bus.create_run(run_id)
    register_run(run_id, {"status": "running", "report": None})

    async def _task() -> None:
        try:
            report = await orch.run(run_id, data)
            _runs[run_id] = {"status": "done", "report": report}
        except Exception as exc:  # noqa: BLE001
            _runs[run_id] = {"status": "error", "error": str(exc), "report": None}
            try:
                await default_bus.publish(
                    _event(run_id, "error", {"reason": "orchestrator_failed", "detail": str(exc)})
                )
                await default_bus.publish(
                    _event(run_id, "run_done", {"error": str(exc)})
                )
                await default_bus.complete(run_id)
            except Exception:  # noqa: BLE001
                pass

    asyncio.create_task(_task())
    return run_id
