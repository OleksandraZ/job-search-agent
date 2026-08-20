from __future__ import annotations

import html
import logging

from adapters.ats._common import is_germany_relevant
from adapters.boards import NormalizedJob
from http_client import get_with_retry

logger = logging.getLogger(__name__)

API_URL_TEMPLATE = "https://boards-api.greenhouse.io/v1/boards/{identifier}/jobs"


def fetch_jobs(company_config: dict) -> list[NormalizedJob]:
    identifier = company_config["identifier"]
    # content=true returns the full job description inline - no per-job detail
    # fetch needed, unlike several board adapters. This is also an unpaginated
    # listing endpoint (verified live against a 71-job company): every job comes
    # back in one response.
    response = get_with_retry(API_URL_TEMPLATE.format(identifier=identifier), params={"content": "true"})
    data = response.json()

    source_id = f"greenhouse:{identifier}"
    jobs = []
    for raw in data.get("jobs", []):
        location = ((raw.get("location") or {}).get("name") or "").strip()
        if not is_germany_relevant(location):
            continue

        jobs.append(
            NormalizedJob(
                source_id=source_id,
                title=(raw.get("title") or "").strip(),
                company=raw.get("company_name") or company_config["name"],
                url=raw.get("absolute_url") or "",
                location=location,
                # Greenhouse's `content` field is HTML-entity-encoded HTML (a
                # literal "&lt;p&gt;..." string, not real "<p>..." tags) - verified
                # against a live fetch. Unescape once so classify_language.py's `<`
                # tag-boundary guard sees real tag boundaries, per the get-text/
                # clause-boundary convention other adapters follow.
                description=html.unescape(raw.get("content") or ""),
            )
        )
    return [job for job in jobs if job.url]
