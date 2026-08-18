from __future__ import annotations

import json
import logging

import httpx
from bs4 import BeautifulSoup

from adapters.boards import NormalizedJob, title_matches
from http_client import fetch_each, get_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://www.get-in-it.de"
SEARCH_URL = BASE_URL + "/jobsuche"
REQUEST_DELAY_SECONDS = 1.0

# get in IT has no free-text search - its jobsuche page's server-rendered filter
# schema (company/degree/studySubject/thematicPriority/city/state/radius/homeOffice,
# read from the page's own __NEXT_DATA__ state) has no keyword field at all; a
# `?keywords=`/`?q=` query param gets parsed into the Next.js route (visible in
# __NEXT_DATA__["query"]) but never reaches the job list - confirmed by diffing
# responses with and without it (identical unfiltered 3610-job set both times). Real
# filtering instead uses `thematicPriority`, a fixed facet list; id 24 is "Quality
# Assurance" (name/slug confirmed via the page's own `thematicPriorities` state),
# narrowing to ~100 real QA-tagged jobs. Same "fixed taxonomy, not real search" shape
# as devjobs/builtin, just via a numeric facet id instead of a URL slug.
THEMATIC_PRIORITY_QUALITY_ASSURANCE = 24


def fetch_jobs(source_config: dict) -> list[NormalizedJob]:
    search_terms = source_config.get("search_terms", [])

    try:
        response = get_with_retry(
            SEARCH_URL, params={"thematicPriority": THEMATIC_PRIORITY_QUALITY_ASSURANCE}
        )
    except httpx.HTTPError as exc:
        logger.warning("get-in-it search failed: %s", exc)
        return []

    jobs_by_url = {job.url: job for job in _parse_search_page(response.text, source_config["id"])}

    _fill_descriptions(jobs_by_url, search_terms)

    return list(jobs_by_url.values())


def _parse_search_page(html: str, source_id: str) -> list[NormalizedJob]:
    data = _next_data(html)
    if data is None:
        return []

    # Pagination beyond this first batch is client-side only (a "load more" button
    # that fetches via JS after hydration) - no URL param (start/page/offset) changed
    # the server-rendered result, tested directly against all of them. Accepted
    # limitation: this covers the first ~39 of ~100 real QA-tagged jobs, the same
    # kind of partial-coverage tradeoff as other sources' single-listing-page crawls
    # (e.g. stepstone's one page per search term).
    raw_jobs = data["props"]["initialState"]["jobSearchJobs"]["jobs"]

    jobs = []
    for raw in raw_jobs:
        location = ", ".join(loc["name"] for loc in raw.get("locations", []))
        href = raw.get("url", "")
        jobs.append(
            NormalizedJob(
                source_id=source_id,
                title=raw.get("title", ""),
                company=(raw.get("company") or {}).get("title", ""),
                url=BASE_URL + href if href else "",
                location=location,
                description="",
            )
        )
    return [job for job in jobs if job.url]


def _fill_descriptions(jobs_by_url: dict[str, NormalizedJob], search_terms: list[str]) -> None:
    # Same narrowing as the other adapters: only pay for a detail-page request for
    # jobs whose title already matches search_terms (the check
    # pipeline/filters.py:filter_by_title applies downstream anyway).
    candidates = [job for job in jobs_by_url.values() if title_matches(job.title, search_terms)]
    logger.info(
        "fetching full descriptions for %d/%d title-matched get-in-it jobs",
        len(candidates),
        len(jobs_by_url),
    )

    for job, description in fetch_each(
        candidates,
        lambda j: _fetch_description(j.url),
        delay_seconds=REQUEST_DELAY_SECONDS,
        logger=logger,
        log_context="get-in-it description fetch",
    ):
        if description:
            job.description = description


def _fetch_description(url: str) -> str:
    response = get_with_retry(url)
    data = _next_data(response.text)
    if data is None:
        return ""
    job = data["props"]["initialState"]["jobJob"]["job"]
    # "content" is already a raw HTML string (real <section>/<p> markup) - keeps
    # structure intact for pipeline/classify_language.py's HTML-tag clause boundary.
    # Deliberately not folding the listing's `homeOffice` boolean into location as a
    # "remote" signal - a real posting with homeOffice=true read "können wir nach
    # individueller Abstimmung auch mobiles Arbeiten anbieten" (occasional/negotiable
    # home office, not a full-remote commitment), the same "sounds remote but isn't"
    # trap as TestDevJobs' "remote-first" case. Leaving it out of location means
    # pipeline/location.py:is_remote() falls back to its conservative description-text
    # check (100% remote / vollständig remote / etc.) instead of over-trusting the
    # ambiguous boolean.
    return job.get("content") or ""


def _next_data(html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag is None or not tag.string:
        return None
    try:
        return json.loads(tag.string)
    except json.JSONDecodeError:
        return None
