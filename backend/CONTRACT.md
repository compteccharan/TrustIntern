# TrustIntern API Contract

Base URL: `http://127.0.0.1:8000`

CORS origin: `http://127.0.0.1:5173`

No authentication.

Disclaimer (exact): `Heuristic indicator score, not a probability of fraud.`

## Endpoints

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/api/health` | `{"status":"ok"}` |
| GET | `/api/samples` | Three fictional sample inputs (no scores) |
| POST | `/api/investigations` | Multipart analyze + save + return full report (sync, samples / offline lock) |
| POST | `/api/investigations/runs` | Start async multi-agent OSINT run; returns `{run_id, status:"running"}` |
| GET | `/api/investigations/runs/{run_id}/events` | SSE `text/event-stream` of `AgentEvent` JSON until `run_done` |
| GET | `/api/investigations/runs/{run_id}` | Run status + final report when done |
| GET | `/api/investigations` | Newest first, full reports |
| GET | `/api/investigations/{id}` | One report or 404 |

Interactive docs: `/docs`

## POST `/api/investigations` fields

| Field | Required | Rules |
| --- | --- | --- |
| `company_name` | yes | 1–200 characters |
| `recruiter_name` | no | max 200 |
| `recruiter_email` | no | if present must contain `@` |
| `website_url` | no | string |
| `message` | yes | 1–20000 characters |
| `live_lookups` | no | bool, default `true` (samples send `false`) |
| `pdf` | no | PDF only, max 5 MB |
| `image` | no | PNG, JPEG, WebP, or GIF, max 5 MB. Sent to Gemma vision on `POST /runs` |

Validation errors return HTTP 422:

```json
{"error":"validation_error","message":"...","fields":{...}}
```

Lookup failures (fetch, PDF parse, RDAP) never fail the HTTP request; they become evidence with `status: "unknown"` and `points: 0`.

## POST `/api/investigations/runs`

Same multipart fields as sync `POST /api/investigations`, plus:

| Field | Required | Rules |
| --- | --- | --- |
| `force_heuristic` | no | bool, default `false`. When `true`, skip Gemma and use heuristic spawn rules |

Response:

```json
{"run_id":"<uuid>","status":"running"}
```

Then subscribe:

```http
GET /api/investigations/runs/{run_id}/events
Accept: text/event-stream
```

Each SSE message is `data: {AgentEvent JSON}\n\n`. Stream ends after `run_done`.

### AgentEvent shape

```json
{
  "type": "run_started",
  "run_id": "...",
  "ts": "2026-10-16T12:00:00+05:30",
  "payload": {}
}
```

| `type` | Meaning |
| --- | --- |
| `run_started` | Orchestrator began |
| `planner_mode` | `payload.mode` is `gemma` or `heuristic`. When `gemma`, `payload.model` is the open-weight id (default `gemma-4-26b-a4b-it`) and `payload.provider` is `gemini-api` |
| `agent_started` | Allowlisted agent began |
| `agent_finding` | One evidence row from an agent |
| `agent_spawn` | Planner/heuristic enqueued a child agent |
| `agent_done` | Agent finished |
| `score_ready` | Deterministic score from `scoring.py` only |
| `narrative` | Plain-language restatement of the ledger (not a score) |
| `run_done` | Final; stream closes |
| `error` | Includes `unknown_agent_type` for planner proposals outside the registry |

Typical order: `run_started` → `planner_mode` → `agent_started(fixed_checkers)` → findings → `agent_spawn(...)` → more agents → `score_ready` → `narrative` → `run_done`.

### Scoring boundary (non-negotiable)

- Only `scoring.py` weights create points
- Gemma / OSINT never invent indicator points
- Unknown `agent_type` from the planner → `error` with `reason: "unknown_agent_type"`; never executed
- Registry allowlist only: `fixed_checkers`, `company_osint`, `recruiter_osint`, `domain_osint`, `document_multimodal`, `web_complaint_search`, `entity_followup`
- Caps: max 8 agents, max depth 2, ~45s wall clock

Persisted reports from runs may include `agent_trace`, `narrative`, `run_id`, and `planner_mode` without changing score semantics.

## Report shape

```json
{
  "id": 1,
  "created_at": "2026-10-16T12:00:00+05:30",
  "score": 90,
  "risk_level": "High observed risk indicators",
  "disclaimer": "Heuristic indicator score, not a probability of fraud.",
  "equation": [
    {"indicator_id": "upfront_fee", "label": "Upfront fee", "points": 25}
  ],
  "evidence": [
    {
      "indicator_id": "upfront_fee",
      "title": "Upfront payment requested",
      "reason": "The recruitment message asks for a registration fee.",
      "excerpt": "Pay a registration fee of Rs 2000",
      "points": 25,
      "status": "indicator",
      "source": "Recruitment message",
      "source_url": null,
      "also_found_in": []
    }
  ],
  "recommendations": ["Do not pay a fee to receive an internship."],
  "input_summary": {
    "company_name": "Aurora Tech Pvt Ltd",
    "recruiter_name": "Riya Shah",
    "recruiter_email": "hr.aurora@gmail.com",
    "website_url": "https://quickplacement-jobs.example",
    "message_preview": "Congratulations. Pay a registration fee",
    "had_pdf": false,
    "live_lookups": false
  }
}
```

### Report rules

- `risk_level`: exactly `Lower observed risk indicators` (0–30), `Needs verification` (31–60), `High observed risk indicators` (61–100)
- `status`: exactly `indicator` | `clear` | `unknown`
- Only `indicator` rows enter `equation`
- Same `indicator_id` once; second source goes in `also_found_in`
- `message_preview`: first 180 characters of message

## Scoring indicators

| id | points | label |
| --- | --- | --- |
| `upfront_fee` | 25 | Upfront fee |
| `domain_mismatch` | 20 | Email domain mismatch |
| `sensitive_data` | 20 | Sensitive data request |
| `young_domain` | 15 | Newly registered domain |
| `offer_inconsistency` | 15 | Offer letter conflict |
| `unrelated_domain` | 10 | Company not in domain |
| `urgency` | 10 | Urgency or guarantee |
| `personal_email` | 5 | Personal email provider |

Sum distinct indicators, cap at 100. Never subtract.

## Locked demo samples (`GET /api/samples`)

All have `"fictional": true`. Demo uses `live_lookups=false`.

| Sample | Expected score (lookups off) |
| --- | --- |
| suspicious | 90 |
| consistent | 0 |
| limited | 0 |

## Env vars (multi-agent / Gemma)

| Variable | Required | Meaning |
| --- | --- | --- |
| `GEMINI_API_KEY` | for Gemma path | Google AI Studio / Gemini API key |
| `GEMMA_MODEL` | no | Default `gemma-4-26b-a4b-it` |
| `FORCE_HEURISTIC_PLANNER` | no | `1`/`true` forces heuristic spawn (demo without key) |

Without a key, the planner emits `planner_mode: heuristic` and still runs fixed checkers + OSINT workers.

## Run

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Start a live multi-agent run + SSE

```bash
# Start run (force heuristic for offline demo)
curl -s -X POST http://127.0.0.1:8000/api/investigations/runs \
  -F company_name="Aurora Tech Pvt Ltd" \
  -F recruiter_name="Riya Shah" \
  -F recruiter_email="hr.aurora@gmail.com" \
  -F website_url="https://quickplacement-jobs.example" \
  -F message="Congratulations. Pay a registration fee of Rs 2000..." \
  -F live_lookups=false \
  -F force_heuristic=true

# Subscribe (replace RUN_ID)
curl -N http://127.0.0.1:8000/api/investigations/runs/RUN_ID/events
```
