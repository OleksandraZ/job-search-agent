from __future__ import annotations

import logging

from adapters.ats._common import is_germany_relevant
from adapters.boards import NormalizedJob
from http_client import get_with_retry

logger = logging.getLogger(__name__)

API_URL_TEMPLATE = "https://api.ashbyhq.com/posting-api/job-board/{identifier}"


def _is_germany(raw: dict, location: str) -> bool:
    # Ashby postings carry a real structured address.postalAddress.addressCountry
    # field (verified live against DeepL: "Germany"/"United States"/"Switzerland"/
    # "United Kingdom"/"Japan" across real postings) - trust it directly, same as
    # Lever's `country` field, falling back to the location-string guard only when
    # a posting has no address at all.
    country = ((raw.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
    if country:
        return country.strip().lower() == "germany"
    return is_germany_relevant(location)


def fetch_jobs(company_config: dict) -> list[NormalizedJob]:
    identifier = company_config["identifier"]
    response = get_with_retry(API_URL_TEMPLATE.format(identifier=identifier))
    data = response.json()

    source_id = f"ashby:{identifier}"
    jobs = []
    for raw in data.get("jobs", []):
        location = raw.get("location") or ""
        if not _is_germany(raw, location):
            continue

        jobs.append(
            NormalizedJob(
                source_id=source_id,
                title=(raw.get("title") or "").strip(),
                company=company_config["name"],
                url=raw.get("jobUrl") or "",
                location=location,
                description=raw.get("descriptionHtml") or "",
            )
        )
    return [job for job in jobs if job.url]
