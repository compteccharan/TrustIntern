"""Run a live multi-agent investigation and print OSINT evidence.

Usage (from backend/):
  python scripts/live_osint_case.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:8000"

# Real-ish suspicious internship: real company site + scam language + LinkedIn URL
CASE = {
    "company_name": "Google",
    "recruiter_name": "Riya Shah",
    "recruiter_email": "hr.google.careers@gmail.com",
    "website_url": "https://www.google.com",
    "message": (
        "Congratulations. You are selected for a Google remote internship. "
        "Pay a registration fee of Rs 2000 to confirm your seat. "
        "Only 1 internship slot remains. Share your bank account number and OTP. "
        "Verify my profile https://www.linkedin.com/in/sundar-pichai "
        "and message me on WhatsApp +91 98765 43210."
    ),
    "live_lookups": "true",
    "force_heuristic": "true",
}


def main() -> int:
    with httpx.Client(timeout=120.0) as client:
        health = client.get(f"{BASE}/api/health")
        health.raise_for_status()
        print("health:", health.json())

        print("\n=== Starting live run (heuristic planner, live_lookups=true) ===")
        started = client.post(f"{BASE}/api/investigations/runs", data=CASE)
        print("start status:", started.status_code)
        print(started.text[:500])
        started.raise_for_status()
        run_id = started.json()["run_id"]
        print("run_id:", run_id)

        events = []
        with client.stream(
            "GET", f"{BASE}/api/investigations/runs/{run_id}/events", timeout=120.0
        ) as stream:
            buf = ""
            for chunk in stream.iter_text():
                buf += chunk
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    data_line = next(
                        (
                            ln[5:].strip()
                            for ln in block.splitlines()
                            if ln.startswith("data:")
                        ),
                        None,
                    )
                    if not data_line:
                        continue
                    ev = json.loads(data_line)
                    events.append(ev)
                    et = ev.get("type")
                    payload = ev.get("payload") or {}
                    if et == "planner_mode":
                        print(f"\nplanner_mode: {payload.get('mode')}")
                    elif et == "agent_started":
                        print(f"  agent_started: {payload.get('agent_type')}")
                    elif et == "agent_spawn":
                        print(
                            f"  spawn: {payload.get('agent_type')} — {payload.get('reason', '')[:80]}"
                        )
                    elif et == "agent_finding":
                        e = payload.get("evidence") or payload
                        print(
                            f"    finding [{e.get('status')}] {e.get('indicator_id')}: "
                            f"{(e.get('title') or '')[:70]}"
                        )
                        if e.get("source_url"):
                            print(f"      url: {e.get('source_url')}")
                        if e.get("excerpt"):
                            print(f"      excerpt: {str(e.get('excerpt'))[:120]}")
                    elif et == "score_ready":
                        print(
                            f"\nscore_ready: {payload.get('score')} / "
                            f"{payload.get('risk_level')}"
                        )
                        eq = payload.get("equation") or []
                        print("equation:", [f"{x.get('label')}+{x.get('points')}" for x in eq])
                    elif et == "run_done":
                        print("\nrun_done")
                    elif et == "error":
                        print("ERROR:", payload)

        # Final persisted report
        time.sleep(0.3)
        report = client.get(f"{BASE}/api/investigations/runs/{run_id}")
        if report.status_code == 200:
            body = report.json()
            print("\n=== Final report summary ===")
            print("score:", body.get("score"), body.get("risk_level"))
            print("planner/agent_trace:", body.get("agent_trace"))
            interesting = [
                e
                for e in (body.get("evidence") or [])
                if any(
                    k in (e.get("indicator_id") or "")
                    for k in ("reddit", "linkedin", "wikipedia", "company", "web_")
                )
                or "Reddit" in (e.get("source") or "")
                or "LinkedIn" in (e.get("title") or "")
            ]
            print(f"\nOSINT-related evidence rows: {len(interesting)}")
            for e in interesting:
                print(
                    f"- [{e.get('status')}] {e.get('indicator_id')}: {e.get('title')}"
                )
                print(f"  source={e.get('source')} url={e.get('source_url')}")
                if e.get("excerpt"):
                    print(f"  excerpt={str(e.get('excerpt'))[:140]}")

            # Heuristic integrity: score points only from scoring indicators
            scored = [
                e
                for e in (body.get("evidence") or [])
                if e.get("status") == "indicator" and int(e.get("points") or 0) > 0
            ]
            print("\nScored indicators (should be fixed-checker rules only):")
            for e in scored:
                print(f"  +{e.get('points')} {e.get('indicator_id')} — {e.get('title')}")

        print(f"\nTotal SSE events: {len(events)}")
        types = {}
        for ev in events:
            types[ev.get("type")] = types.get(ev.get("type"), 0) + 1
        print("event counts:", types)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
