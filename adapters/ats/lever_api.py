from __future__ import annotations

import logging

from adapters.ats._common import is_germany_relevant
from adapters.boards import NormalizedJob
from http_client import get_with_retry

logger = logging.getLogger(__name__)

API_URL_TEMPLATE = "https://api.lever.co/v0/postings/{identifier}"


def _is_germany(raw: dict, location: str) -> bool:
    # Lever postings carry a real structured `country` field (verified live against
    # FINN: "DE" on every posting) - trust it directly per CLAUDE.md's "trust a real
    # structured location exclusively" rule, rather than the location-string guard
    # other ATS adapters need. Falls back to that guard only if a company's postings
    # don't set `country` at all.
    country = (raw.get("country") or "").strip().upper()
    if country:
        return country == "DE"
    return is_germany_relevant(location)


def fetch_jobs(company_config: dict) -> list[NormalizedJob]:
    identifier = company_config["identifier"]
    response = get_with_retry(API_URL_TEMPLATE.format(identifier=identifier), params={"mode": "json"})
    data = response.json()

    source_id = f"lever:{identifier}"
    jobs = []
    for raw in data:
        location = (raw.get("categories") or {}).get("location") or ""
        if not _is_germany(raw, location):
            continue

        jobs.append(
            NormalizedJob(
                source_id=source_id,
                title=(raw.get("text") or "").strip(),
                company=company_config["name"],
                url=raw.get("hostedUrl") or "",
                location=location,
                description=raw.get("description") or "",
            )
        )
    return [job for job in jobs if job.url]
