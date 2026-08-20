from __future__ import annotations

import logging

from adapters.ats._common import is_germany_relevant
from adapters.boards import NormalizedJob
from http_client import get_with_retry

logger = logging.getLogger(__name__)

API_URL_TEMPLATE = "https://apply.workable.com/api/v1/widget/accounts/{identifier}"


def _is_germany(raw: dict, city: str) -> bool:
    # Workable's own structured `country` field (full name, e.g. "Germany" - verified
    # live against Mondu/WorkMotion/Usercentrics) - trust it directly per CLAUDE.md's
    # "trust a real structured location exclusively" rule, same as lever_api.py's
    # `country`. Falls back to the text guard only if a job's `country` is empty -
    # checked against the *raw* city, before any "Germany" suffix is appended for
    # display (an earlier version checked the already-suffixed display string and
    # so always matched, regardless of the real city - caught by
    # test_falls_back_to_location_guard_when_country_missing).
    country = (raw.get("country") or "").strip()
    if country:
        return country == "Germany"
    return is_germany_relevant(city)


def fetch_jobs(company_config: dict) -> list[NormalizedJob]:
    identifier = company_config["identifier"]
    response = get_with_retry(API_URL_TEMPLATE.format(identifier=identifier), params={"details": "true"})
    data = response.json()

    source_id = f"workable:{identifier}"
    jobs = []
    for raw in data.get("jobs", []):
        city = (raw.get("city") or "").strip()
        if not _is_germany(raw, city):
            continue
        location = f"{city}, Germany" if city else "Germany"

        jobs.append(
            NormalizedJob(
                source_id=source_id,
                title=(raw.get("title") or "").strip(),
                company=company_config["name"],
                url=raw.get("url") or raw.get("shortlink") or "",
                location=location,
                description=raw.get("description") or "",
            )
        )
    return [job for job in jobs if job.url]
