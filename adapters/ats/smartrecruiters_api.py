from __future__ import annotations

import logging

from adapters.ats._common import is_germany_relevant
from adapters.boards import NormalizedJob, title_matches
from http_client import fetch_each, get_with_retry

logger = logging.getLogger(__name__)

LIST_URL_TEMPLATE = "https://api.smartrecruiters.com/v1/companies/{identifier}/postings"
DETAIL_URL_TEMPLATE = "https://api.smartrecruiters.com/v1/companies/{identifier}/postings/{posting_id}"
# https://jobs.smartrecruiters.com/{identifier}/{posting id} resolves directly
# (verified live) - a stable public URL derivable from the listing response alone,
# no need to depend on a successful detail fetch for it.
PUBLIC_URL_TEMPLATE = "https://jobs.smartrecruiters.com/{identifier}/{posting_id}"
REQUEST_DELAY_SECONDS = 0.5
# The listing endpoint has no description at all (verified live) - only the detail
# endpoint's jobAd.sections does, so descriptions are fetched per-job, bounded to the
# title-matched subset, same rule as the board adapters' detail-page fetches.
DESCRIPTION_SECTIONS = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")


def _is_germany(location: dict) -> bool:
    # SmartRecruiters postings carry a real structured location.country field
    # (verified live: "de" on every Seven Senders posting) - trust it directly, same
    # as Lever's `country` and Ashby's `addressCountry`.
    country = (location.get("country") or "").strip().lower()
    if country:
        return country == "de"
    return is_germany_relevant(location.get("fullLocation") or "")


def _location_text(location: dict) -> str:
    return location.get("fullLocation") or location.get("city") or ""


def _fetch_description(identifier: str, posting_id: str) -> str:
    response = get_with_retry(DETAIL_URL_TEMPLATE.format(identifier=identifier, posting_id=posting_id))
    sections = (response.json().get("jobAd") or {}).get("sections") or {}
    parts = [sections[key]["text"] for key in DESCRIPTION_SECTIONS if sections.get(key, {}).get("text")]
    return "\n".join(parts)


def fetch_jobs(company_config: dict) -> list[NormalizedJob]:
    identifier = company_config["identifier"]
    search_terms = company_config.get("search_terms", [])

    response = get_with_retry(LIST_URL_TEMPLATE.format(identifier=identifier), params={"limit": 100})
    postings = response.json().get("content", [])

    source_id = f"smartrecruiters:{identifier}"
    jobs = []
    for raw in postings:
        location = raw.get("location") or {}
        if not _is_germany(location):
            continue
        title = (raw.get("name") or "").strip()
        jobs.append(
            NormalizedJob(
                source_id=source_id,
                title=title,
                company=company_config["name"],
                url=PUBLIC_URL_TEMPLATE.format(identifier=identifier, posting_id=raw["id"]),
                location=_location_text(location),
                description="",
            )
        )

    matched = [job for job in jobs if title_matches(job.title, search_terms)]
    for job, description in fetch_each(
        matched,
        lambda job: _fetch_description(identifier, job.url.rsplit("/", 1)[-1]),
        delay_seconds=REQUEST_DELAY_SECONDS,
        logger=logger,
        log_context="smartrecruiters detail fetch",
    ):
        job.description = description

    return jobs
