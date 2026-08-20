from __future__ import annotations

import logging

import httpx

from adapters.ats._common import is_germany_relevant
from adapters.boards import NormalizedJob
from http_client import get_with_retry

logger = logging.getLogger(__name__)

LISTING_URL_TEMPLATE = "https://{identifier}.bamboohr.com/careers/list"
DETAIL_URL_TEMPLATE = "https://{identifier}.bamboohr.com/careers/{job_id}/detail"


def _location_and_is_germany(raw: dict) -> tuple[str, bool]:
    # Two separate location sub-objects, neither populated on every posting
    # (verified live against Bragi: one posting had `location.city` set with
    # `atsLocation` entirely null, another had the reverse) - atsLocation.country
    # is the more reliable structured signal when present; a bare city name falls
    # back to the text heuristic, same as CLAUDE.md's "trust a real structured
    # location, else fall back" rule elsewhere in this codebase.
    ats_location = raw.get("atsLocation") or {}
    location_field = raw.get("location") or {}
    country = (ats_location.get("country") or location_field.get("addressCountry") or "").strip()
    city = (location_field.get("city") or ats_location.get("city") or "").strip()

    is_germany = country.lower() == "germany" if country else is_germany_relevant(city)

    if city:
        location = f"{city}, Germany" if is_germany else f"{city}, {country}".strip(", ")
    else:
        location = "Germany" if is_germany else (country or "")
    return location, is_germany


def fetch_jobs(company_config: dict) -> list[NormalizedJob]:
    identifier = company_config["identifier"]
    response = get_with_retry(LISTING_URL_TEMPLATE.format(identifier=identifier))
    data = response.json()

    source_id_prefix = f"bamboohr:{identifier}"
    jobs = []
    for raw in data.get("result", []):
        location, is_germany = _location_and_is_germany(raw)
        if not is_germany:
            continue

        job_id = raw.get("id")
        url = f"https://{identifier}.bamboohr.com/careers/{job_id}" if job_id else ""

        description = ""
        if job_id:
            try:
                detail = get_with_retry(
                    DETAIL_URL_TEMPLATE.format(identifier=identifier, job_id=job_id)
                )
                description = (detail.json().get("result", {}).get("jobOpening", {}).get("description")) or ""
            except httpx.HTTPError:
                logger.warning("bamboohr detail fetch failed for %s job %s", identifier, job_id)

        jobs.append(
            NormalizedJob(
                source_id=f"{source_id_prefix}:{job_id}",
                title=(raw.get("jobOpeningName") or "").strip(),
                company=company_config["name"],
                url=url,
                location=location,
                description=description,
            )
        )
    return [job for job in jobs if job.url]
