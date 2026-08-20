from __future__ import annotations

import logging

from adapters.boards import NormalizedJob
from http_client import get_with_retry

logger = logging.getLogger(__name__)

API_URL_TEMPLATE = "https://{identifier}.recruitee.com/api/offers/"


def fetch_jobs(company_config: dict) -> list[NormalizedJob]:
    identifier = company_config["identifier"]
    response = get_with_retry(API_URL_TEMPLATE.format(identifier=identifier))
    data = response.json()

    source_id = f"recruitee:{identifier}"
    jobs = []
    for raw in data.get("offers", []):
        # Recruitee's own structured `country_code` field (ISO, e.g. "DE" -
        # verified live against AVEDO's 187 real postings, present on every one) -
        # trust it directly per CLAUDE.md's "trust a real structured location
        # exclusively" rule.
        if (raw.get("country_code") or "").strip().upper() != "DE":
            continue

        jobs.append(
            NormalizedJob(
                source_id=source_id,
                title=(raw.get("title") or "").strip(),
                company=company_config["name"],
                url=raw.get("careers_url") or "",
                location=raw.get("location") or "Germany",
                description=raw.get("description") or "",
            )
        )
    return [job for job in jobs if job.url]
