"""Pydantic schemas for TrustIntern reports and API payloads."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RiskLevel = Literal[
    "Lower observed risk indicators",
    "Needs verification",
    "High observed risk indicators",
]

EvidenceStatus = Literal["indicator", "clear", "unknown"]


class EquationItem(BaseModel):
    indicator_id: str
    label: str
    points: int


class EvidenceItem(BaseModel):
    indicator_id: str
    title: str
    reason: str
    excerpt: str | None = None
    points: int
    status: EvidenceStatus
    source: str
    source_url: str | None = None
    also_found_in: list[str] = Field(default_factory=list)


class InputSummary(BaseModel):
    company_name: str
    recruiter_name: str | None = None
    recruiter_email: str | None = None
    website_url: str | None = None
    message_preview: str
    had_pdf: bool
    live_lookups: bool


class Report(BaseModel):
    id: int
    created_at: str
    score: int
    risk_level: RiskLevel
    disclaimer: str
    equation: list[EquationItem]
    evidence: list[EvidenceItem]
    recommendations: list[str]
    input_summary: InputSummary


class HealthResponse(BaseModel):
    status: str


class ValidationErrorBody(BaseModel):
    error: str = "validation_error"
    message: str
    fields: dict[str, Any] = Field(default_factory=dict)


class SampleInput(BaseModel):
    id: str
    label: str
    fictional: bool = True
    company_name: str
    recruiter_name: str | None = None
    recruiter_email: str | None = None
    website_url: str | None = None
    message: str
    live_lookups: bool = False
