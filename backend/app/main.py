"""FastAPI application for TrustIntern."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app.agents.bus import RUN_COMPLETE, bus
from app.agents.orchestrator import get_run, start_run
from app.analyze import Lookups, analyze_opportunity
from app.agents.gemma_client import DEFAULT_MODEL, gemma_configured
from app.document import MAX_PDF_BYTES

# Vercel rejects the whole request at the edge once the body exceeds 4.5 MB.
_VERCEL_UPLOAD_BYTES = 4 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_MIMES = {
    "image/png": "image/png",
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/webp": "image/webp",
    "image/gif": "image/gif",
}
from app.samples import get_samples
from app.storage import get_report, init_db, list_reports, save_report


def _load_local_env() -> None:
    """Read backend/.env without overriding variables already set in the process."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_local_env()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="TrustIntern API", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "https://trustintern.charancodes.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _validation_error(message: str, fields: dict[str, Any]) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": message,
            "fields": fields,
        },
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    fields: dict[str, Any] = {}
    for err in exc.errors():
        loc = err.get("loc") or ()
        # Skip "body" / "query" prefix — use last path segment as field name
        key_parts = [str(p) for p in loc if p not in ("body", "query", "path")]
        key = key_parts[-1] if key_parts else "request"
        fields[key] = err.get("msg") or "Invalid value"
    return _validation_error("Request validation failed", fields)


def _parse_live_lookups(value: str | bool | None) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _upload_limit(local_limit: int) -> int:
    if os.environ.get("VERCEL"):
        return min(local_limit, _VERCEL_UPLOAD_BYTES)
    return local_limit


def _image_mime(upload: UploadFile) -> str | None:
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    if content_type in IMAGE_MIMES:
        return IMAGE_MIMES[content_type]
    name = (upload.filename or "").lower()
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".jpg") or name.endswith(".jpeg"):
        return "image/jpeg"
    if name.endswith(".webp"):
        return "image/webp"
    if name.endswith(".gif"):
        return "image/gif"
    return None


async def _parse_investigation_form(
    company_name: str,
    message: str,
    recruiter_name: str | None,
    recruiter_email: str | None,
    website_url: str | None,
    live_lookups: str,
    pdf: UploadFile | None,
    image: UploadFile | None = None,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    fields: dict[str, Any] = {}

    company_name = (company_name or "").strip()
    if not company_name or len(company_name) > 200:
        fields["company_name"] = "Required, 1–200 characters"

    if message is None or not str(message).strip() or len(message) > 20000:
        fields["message"] = "Required, 1–20000 characters"

    if recruiter_name is not None and len(recruiter_name) > 200:
        fields["recruiter_name"] = "Max 200 characters"

    if recruiter_email is not None and recruiter_email != "" and "@" not in recruiter_email:
        fields["recruiter_email"] = "Must contain @"

    pdf_limit = _upload_limit(MAX_PDF_BYTES)
    pdf_bytes: bytes | None = None
    if pdf is not None and (pdf.filename or "").strip():
        raw = await pdf.read()
        filename = (pdf.filename or "").lower()
        content_type = (pdf.content_type or "").lower()
        is_pdf = filename.endswith(".pdf") or "pdf" in content_type
        if len(raw) > pdf_limit:
            fields["pdf"] = f"PDF must be at most {pdf_limit // (1024 * 1024)} MB"
        elif not is_pdf:
            fields["pdf"] = "PDF only"
        else:
            pdf_bytes = raw

    image_limit = _upload_limit(MAX_IMAGE_BYTES)
    image_payload: dict[str, Any] | None = None
    if image is not None and (image.filename or "").strip():
        raw_img = await image.read()
        mime = _image_mime(image)
        if len(raw_img) > image_limit:
            fields["image"] = f"Image must be at most {image_limit // (1024 * 1024)} MB"
        elif not mime:
            fields["image"] = "PNG, JPEG, WebP, or GIF only"
        else:
            image_payload = {"bytes": raw_img, "mime": mime}

    if fields:
        return None, _validation_error("Request validation failed", fields)

    data = {
        "company_name": company_name,
        "recruiter_name": (recruiter_name or None) or None,
        "recruiter_email": (recruiter_email or None) or None,
        "website_url": (website_url or None) or None,
        "message": message,
        "live_lookups": _parse_live_lookups(live_lookups),
        "pdf": pdf_bytes,
        "image": image_payload,
    }
    return data, None


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": os.environ.get("GEMMA_MODEL", DEFAULT_MODEL),
        "weights": "open-weight",
        "provider": "ollama",
        "gemma_configured": gemma_configured(),
    }


@app.get("/api/samples")
def samples() -> list[dict[str, Any]]:
    return get_samples()


@app.post("/api/investigations")
async def create_investigation(
    company_name: str = Form(...),
    message: str = Form(...),
    recruiter_name: str | None = Form(None),
    recruiter_email: str | None = Form(None),
    website_url: str | None = Form(None),
    live_lookups: str = Form("true"),
    pdf: UploadFile | None = File(None),
    image: UploadFile | None = File(None),
) -> Any:
    data, err = await _parse_investigation_form(
        company_name,
        message,
        recruiter_name,
        recruiter_email,
        website_url,
        live_lookups,
        pdf,
        image,
    )
    if err is not None:
        return err
    assert data is not None
    report = analyze_opportunity(data, Lookups())
    return save_report(report)


@app.post("/api/investigations/runs")
async def create_investigation_run(
    company_name: str = Form(...),
    message: str = Form(...),
    recruiter_name: str | None = Form(None),
    recruiter_email: str | None = Form(None),
    website_url: str | None = Form(None),
    live_lookups: str = Form("true"),
    force_heuristic: str = Form("false"),
    pdf: UploadFile | None = File(None),
    image: UploadFile | None = File(None),
) -> Any:
    """Start async multi-agent OSINT run; subscribe via GET .../events."""
    data, err = await _parse_investigation_form(
        company_name,
        message,
        recruiter_name,
        recruiter_email,
        website_url,
        live_lookups,
        pdf,
        image,
    )
    if err is not None:
        return err
    assert data is not None
    run_id = await start_run(
        data,
        force_heuristic=_parse_bool(force_heuristic, default=False),
    )
    return {"run_id": run_id, "status": "running"}


def _sse_response(run_id: str) -> StreamingResponse:
    return StreamingResponse(
        _iter_run_events(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _iter_run_events(run_id: str):
    """Yield SSE frames for a run that is executing in this same process."""
    queue = await bus.subscribe(run_id)
    for _ in range(50):
        if queue is not None:
            break
        await asyncio.sleep(0.02)
        queue = await bus.subscribe(run_id)

    for past in bus.history(run_id):
        yield f"data: {past.model_dump_json()}\n\n"
        if past.type == "run_done":
            return

    if queue is None:
        yield (
            "data: "
            + json.dumps(
                {
                    "type": "error",
                    "run_id": run_id,
                    "ts": "",
                    "payload": {"reason": "run_not_found"},
                }
            )
            + "\n\n"
        )
        return

    while True:
        item = await queue.get()
        if item is RUN_COMPLETE:
            break
        yield f"data: {item.model_dump_json()}\n\n"
        if getattr(item, "type", None) == "run_done":
            break


@app.post("/api/investigations/runs/stream")
async def stream_investigation_run(
    company_name: str = Form(...),
    message: str = Form(...),
    recruiter_name: str | None = Form(None),
    recruiter_email: str | None = Form(None),
    website_url: str | None = Form(None),
    live_lookups: str = Form("true"),
    force_heuristic: str = Form("false"),
    pdf: UploadFile | None = File(None),
    image: UploadFile | None = File(None),
) -> Any:
    """Run the investigation inside this response.

    Serverless instances do not keep a background task alive after the POST
    returns, and the next request may land on a different instance. Streaming
    the run from the same invocation is what works on Vercel.
    """
    data, err = await _parse_investigation_form(
        company_name,
        message,
        recruiter_name,
        recruiter_email,
        website_url,
        live_lookups,
        pdf,
        image,
    )
    if err is not None:
        return err
    assert data is not None
    run_id = await start_run(
        data,
        force_heuristic=_parse_bool(force_heuristic, default=False),
    )
    return _sse_response(run_id)


@app.get("/api/investigations/runs/{run_id}/events")
async def investigation_run_events(run_id: str) -> StreamingResponse:
    """SSE stream of AgentEvent JSON objects; ends after run_done."""
    meta = get_run(run_id)
    queue = await bus.subscribe(run_id)
    if queue is None and meta is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _sse_response(run_id)


@app.get("/api/investigations/runs/{run_id}")
def get_investigation_run(run_id: str) -> dict[str, Any]:
    meta = get_run(run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run_id": run_id, **meta}


@app.get("/api/investigations")
def list_investigations() -> list[dict[str, Any]]:
    return list_reports()


@app.get("/api/investigations/{investigation_id}")
def get_investigation(investigation_id: int) -> dict[str, Any]:
    report = get_report(investigation_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return report
