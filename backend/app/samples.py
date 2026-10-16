"""Locked fictional sample inputs for demo and tests."""

from __future__ import annotations

from typing import Any

SAMPLES: list[dict[str, Any]] = [
    {
        "id": "suspicious",
        "label": "Suspicious",
        "fictional": True,
        "company_name": "Aurora Tech Pvt Ltd",
        "recruiter_name": "Riya Shah",
        "recruiter_email": "hr.aurora@gmail.com",
        "website_url": "https://quickplacement-jobs.example",
        "message": (
            "Congratulations. Pay a registration fee of Rs 2000 to confirm your seat. "
            "Only 1 internship slot remains. Share your bank account number and OTP "
            "so we can process the stipend."
        ),
        "live_lookups": False,
    },
    {
        "id": "consistent",
        "label": "Consistent",
        "fictional": True,
        "company_name": "Northwind Labs",
        "recruiter_name": "Aditi Menon",
        "recruiter_email": "careers@northwindlabs.com",
        "website_url": "https://northwindlabs.com",
        "message": (
            "Northwind Labs is hiring a software engineering intern for a 12-week "
            "summer term on the platform team. Send a resume to the careers address. "
            "The internship is free of charge at every stage."
        ),
        "live_lookups": False,
    },
    {
        "id": "limited",
        "label": "Limited Evidence",
        "fictional": True,
        "company_name": "Brightpath",
        "recruiter_name": "Unknown",
        "recruiter_email": "",
        "website_url": "https://192.168.0.10/intern",
        "message": "Congratulations, you have been selected. We will share more details soon.",
        "live_lookups": False,
    },
]


def get_samples() -> list[dict[str, Any]]:
    return [dict(s) for s in SAMPLES]


def get_sample(sample_id: str) -> dict[str, Any] | None:
    for s in SAMPLES:
        if s["id"] == sample_id:
            return dict(s)
    return None
