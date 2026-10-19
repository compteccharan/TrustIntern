# TrustIntern 🕵️

**An investigation desk that tells students whether an internship offer is a scam, and shows its working.**

TrustIntern looks at the company name, recruiter email, website, message text, and an offer-letter PDF or screenshot. It runs a small team of research agents and returns an **explainable risk score**: every point is tied to a specific piece of evidence. Reports download as a PDF.

> Heuristic indicator score, not a probability of fraud.

**Live demo:** https://trustintern.charancodes.com

## How it works
1. **Fixed checkers** look at the email domain, domain age (RDAP), website and message text.
2. **Gemma 4 plans** which research agents to launch: company, recruiter, complaints, domain, document, follow-up. Only allowlisted agent types run; at most 8 agents and depth 2.
3. **Gemma 4 vision** reads the offer letter (PDF or screenshot) and flags inconsistencies.
4. **Deterministic scoring** (`backend/app/scoring.py`) adds up fixed indicator points: upfront fee 25, domain mismatch 20, sensitive data 20, young domain 15, offer conflict 15, unrelated domain 10, urgency 10, personal email 5. The total is capped at 100 and never reduced. **Gemma never assigns points.**
5. Progress streams to the React desk over SSE; Gemma then writes a plain-language summary of the evidence.

## Where Gemma 4 runs
- **Locally:** `gemma4:e2b` through [Ollama](https://ollama.com) on your own machine (`OLLAMA_HOST`, default `http://127.0.0.1:11434`). Offer letters and screenshots never leave the laptop.
- **Hosted demo:** the live site falls back to the same open-weight Gemma 4 family served by Google's Gemini API (`gemma-4-26b-a4b-it`, set with `GEMINI_API_KEY` and `GEMMA_MODEL`).
- **No model at all:** a heuristic planner takes over so the investigation still finishes. The score never depends on the model.

## Stack
FastAPI · Python agents (requests, BeautifulSoup, pypdf, pypdfium2) · Gemma 4 via Ollama · React 18 + Vite · jsPDF · Vercel · GitHub Actions CI

## Run locally
```bash
ollama pull gemma4:e2b
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```
Environment variables: `OLLAMA_HOST` (default `http://127.0.0.1:11434`), `GEMMA_MODEL` (default `gemma4:e2b` locally), and `GEMINI_API_KEY` for the hosted Gemma 4 fallback. Never commit `backend/.env`. The full API is documented in `backend/CONTRACT.md`.

## Built with agents, recorded with Entire
- Cursor, Codex and Antigravity hooks record sessions as **Entire checkpoints** (`refs/entire/checkpoints/*`), and `commit_linking: always` links them to commits through `Entire-Checkpoint:` lines.
- Six **trail runners** (`.entire/runners/`) score every branch for risk, security, drift and confidence, and add a review and a summary.
- The **DevRelay** gateway and skills (`.cursor/skills/`) saved the build sessions to DEV as public Agent Sessions:
  - [Build plan (the 5.5-hour hackathon plan)](https://dev.to/agent_sessions/-trustintern-solid-project-build-plan-hackathon-mvp-55-hour-deadline--ndy4ni)
  - [Implement the backend per the locked plan](https://dev.to/agent_sessions/implement-the-full-trustintern-backend-per-the-locked-plan-do-not-edit-the-t6f644)
  - [Gemma multimodal multi-agent OSINT + SSE](https://dev.to/agent_sessions/implement-the-full-gemma-multimodal-multi-agent-osint-sse-plan-do-not-edit-fcapuh)
  - [Set up Ollama for local Gemma 4](https://dev.to/agent_sessions/set-up-ollama-so-i-can-build-with-open-models-ollama-runs-open-models-in-two-pafagl)
  - [Redesign the investigation desk](https://dev.to/agent_sessions/redesign-the-trustintern-investigation-desk-ui-workspace-sadidt)
  - [Deploy to Vercel](https://dev.to/agent_sessions/finish-deploying-trustintern-to-vercel-do-not-print-secrets-do-not-commit-tke35w)
  - All sessions: https://dev.to/noahosmont

## Hacktoberfest 2026
Built for the DEV Hacktoberfest Open-Source AI Challenge, Week 2: Side Hustle. The core app was built on 16 Oct 2026. Before the deadline (18 Oct, 11:59 PM PDT) I added the README, LICENSE and the had_image fix (PR #6) on 17 Oct, then crawlable SEO pages, a Search Console tag and Vercel Web Analytics (PRs #7 to #9) on 18 Oct. Any commits after the deadline will be listed here. 19 Oct 2026: copy-only change to the gemma-status line so hosted visitors (`gemma_configured: false`) see that the demo uses deterministic checks and the heuristic planner, with Gemma 4 planning and vision available when self-hosting with Ollama. The local Ollama status copy is unchanged.

## License
MIT. See [LICENSE](LICENSE).
