"""Orchestrator SSE sequence and locked suspicious score under heuristic multi-agent."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi.testclient import TestClient

from app.agents.bus import EventBus
from app.agents.orchestrator import Orchestrator
from app.agents.registry import get_runner, is_allowed
from app.agents.schema import AgentSpec, Budget
from app.analyze import Lookups
from app.main import app
from app.samples import get_sample
from app.scoring import DISCLAIMER


def _stub_lookups() -> Lookups:
    def fetch_url(url: str) -> dict[str, Any]:
        raise AssertionError(f"fetch_url should not be called, got {url}")

    def rdap(host: str) -> dict[str, Any]:
        raise AssertionError(f"rdap should not be called, got {host}")

    return Lookups(fetch_url=fetch_url, rdap=rdap)


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


def test_suspicious_multiagent_heuristic_score_still_90():
    bus = EventBus()

    async def _run() -> dict[str, Any]:
        orch = Orchestrator(
            event_bus=bus,
            lookups=_stub_lookups(),
            force_heuristic=True,
            persist=False,
            max_agents=8,
            wall_clock_s=45.0,
        )
        return await orch.run("test-run-suspicious", _suspicious_data())

    report = asyncio.run(_run())
    assert report["disclaimer"] == DISCLAIMER
    assert report["score"] == 90
    assert report["risk_level"] == "High observed risk indicators"
    assert report["planner_mode"] == "heuristic"
    assert isinstance(report.get("agent_trace"), list)
    assert any(a["agent_type"] == "fixed_checkers" for a in report["agent_trace"])
    # OSINT must not invent weighted points beyond fixed checkers
    indicator_points = sum(
        int(e["points"])
        for e in report["evidence"]
        if e.get("status") == "indicator"
    )
    assert indicator_points == 90


def test_sse_event_sequence_heuristic():
    bus = EventBus()

    async def _run() -> list[str]:
        orch = Orchestrator(
            event_bus=bus,
            lookups=_stub_lookups(),
            force_heuristic=True,
            persist=False,
        )
        await orch.run("test-run-sse", _suspicious_data())
        return [e.type for e in bus.history("test-run-sse")]

    types = asyncio.run(_run())
    assert types[0] == "run_started"
    assert "planner_mode" in types
    assert types.index("planner_mode") < types.index("score_ready")
    # fixed checkers start before score
    started = [
        e
        for e in bus.history("test-run-sse")
        if e.type == "agent_started"
    ]
    assert started[0].payload.get("agent_type") == "fixed_checkers"
    assert "score_ready" in types
    assert "narrative" in types
    assert types[-1] == "run_done"
    # spawn events present for OSINT agents
    assert "agent_spawn" in types
    mode_events = [
        e for e in bus.history("test-run-sse") if e.type == "planner_mode"
    ]
    assert mode_events[0].payload.get("mode") == "heuristic"


def test_unknown_agent_type_never_executed():
    assert get_runner("not_a_real_agent") is None
    assert is_allowed("not_a_real_agent") is False

    bus = EventBus()

    async def _run() -> None:
        orch = Orchestrator(
            event_bus=bus,
            lookups=_stub_lookups(),
            force_heuristic=True,
            persist=False,
            max_agents=2,
        )
        # Monkey-patch: after fixed, inject unknown into queue by calling _execute
        # directly with unknown type
        await orch.bus.create_run("rej")
        await orch._execute_agent(
            "rej",
            {"data": _suspicious_data(), "lookups": _stub_lookups()},
            AgentSpec(
                agent_type="not_a_real_agent",
                agent_id="x",
                reason="test",
                inputs={},
                budget=Budget(),
                depth=1,
            ),
            [],
            [],
        )

    asyncio.run(_run())
    errors = [e for e in bus.history("rej") if e.type == "error"]
    assert any(e.payload.get("reason") == "unknown_agent_type" for e in errors)


def test_api_runs_and_sse_stream():
    with TestClient(app) as client:
        sample = get_sample("suspicious")
        assert sample is not None
        resp = client.post(
            "/api/investigations/runs",
            data={
                "company_name": sample["company_name"],
                "recruiter_name": sample["recruiter_name"],
                "recruiter_email": sample["recruiter_email"],
                "website_url": sample["website_url"],
                "message": sample["message"],
                "live_lookups": "false",
                "force_heuristic": "true",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        run_id = body["run_id"]
        assert body["status"] == "running"

        # Collect SSE until run_done (TestClient streams)
        with client.stream("GET", f"/api/investigations/runs/{run_id}/events") as stream:
            assert stream.status_code == 200
            assert "text/event-stream" in stream.headers.get("content-type", "")
            events: list[dict[str, Any]] = []
            for line in stream.iter_lines():
                if not line:
                    continue
                if isinstance(line, bytes):
                    line = line.decode("utf-8")
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line[6:])
                events.append(payload)
                if payload.get("type") == "run_done":
                    break

        types = [e["type"] for e in events]
        assert "run_started" in types
        assert "planner_mode" in types
        assert "score_ready" in types
        assert "run_done" in types
        score_evt = next(e for e in events if e["type"] == "score_ready")
        assert score_evt["payload"]["score"] == 90


def test_sync_investigations_still_works():
    with TestClient(app) as client:
        sample = get_sample("suspicious")
        assert sample is not None
        resp = client.post(
            "/api/investigations",
            data={
                "company_name": sample["company_name"],
                "recruiter_name": sample["recruiter_name"],
                "recruiter_email": sample["recruiter_email"],
                "website_url": sample["website_url"],
                "message": sample["message"],
                "live_lookups": "false",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["score"] == 90
