"""FastAPI application for TrustIntern."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.analyze import Lookups, analyze_opportunity
from app.document import MAX_PDF_BYTES
from app.samples import get_samples
from app.storage import get_report, init_db, list_reports, save_report


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="TrustIntern API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173"],
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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
) -> Any:
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

    pdf_bytes: bytes | None = None
    if pdf is not None and (pdf.filename or "").strip():
        raw = await pdf.read()
        filename = (pdf.filename or "").lower()
        content_type = (pdf.content_type or "").lower()
        is_pdf = filename.endswith(".pdf") or "pdf" in content_type
        if len(raw) > MAX_PDF_BYTES:
            fields["pdf"] = "PDF must be at most 5 MB"
        elif not is_pdf:
            fields["pdf"] = "PDF only"
        else:
            pdf_bytes = raw

    if fields:
        return _validation_error("Request validation failed", fields)

    data = {
        "company_name": company_name,
        "recruiter_name": (recruiter_name or None) or None,
        "recruiter_email": (recruiter_email or None) or None,
        "website_url": (website_url or None) or None,
        "message": message,
        "live_lookups": _parse_live_lookups(live_lookups),
        "pdf": pdf_bytes,
    }
    report = analyze_opportunity(data, Lookups())
    return save_report(report)


@app.get("/api/investigations")
def list_investigations() -> list[dict[str, Any]]:
    return list_reports()


@app.get("/api/investigations/{investigation_id}")
def get_investigation(investigation_id: int) -> dict[str, Any]:
    report = get_report(investigation_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return report
