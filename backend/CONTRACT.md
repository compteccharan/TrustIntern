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
| POST | `/api/investigations` | Multipart analyze + save + return full report |
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

Validation errors return HTTP 422:

```json
{"error":"validation_error","message":"...","fields":{...}}
```

Lookup failures (fetch, PDF parse, RDAP) never fail the HTTP request; they become evidence with `status: "unknown"` and `points: 0`.

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

## Run

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
