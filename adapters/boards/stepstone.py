from __future__ import annotations

import logging
import time
import urllib.parse

import httpx
from bs4 import BeautifulSoup

from adapters.boards import NormalizedJob, title_matches
from http_client import get_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://www.stepstone.de"
SEARCH_URL_TEMPLATE = BASE_URL + "/jobs/{slug}"
REQUEST_DELAY_SECONDS = 1.0


def fetch_jobs(source_config: dict) -> list[NormalizedJob]:
    search_terms = source_config.get("search_terms", [])
    jobs_by_url: dict[str, NormalizedJob] = {}

    for i, term in enumerate(search_terms):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        search_url = _search_url(term)
        try:
            response = get_with_retry(search_url, params={"radius": 30})
        except httpx.HTTPError as exc:
            logger.warning("stepstone search for %r failed: %s", term, exc)
            continue

        for job in _parse_search_page(response.text, source_config["id"]):
            jobs_by_url[job.url] = job

    _fill_descriptions(jobs_by_url, search_terms)

    return list(jobs_by_url.values())


def _search_url(term: str) -> str:
    slug = urllib.parse.quote(term.replace(" ", "-"))
    return SEARCH_URL_TEMPLATE.format(slug=slug)


def _parse_search_page(html: str, source_id: str) -> list[NormalizedJob]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select('[data-testid="job-item"]'):
        title_el = card.select_one('[data-testid="job-item-title"]')
        company_el = card.select_one('[data-at="job-item-company-name"]')
        location_el = card.select_one('[data-at="job-item-location"]')
        # Listing cards carry a short (~300 char) snippet, often truncated
        # mid-sentence - real text, usable as a fallback, but detail pages
        # (fetched below for title-matched jobs) give the full description.
        snippet_el = card.select_one('[data-at="jobcard-content"]')
        href = str(title_el.get("href", "")) if title_el else ""

        jobs.append(
            NormalizedJob(
                source_id=source_id,
                title=title_el.get_text(strip=True) if title_el else "",
                company=company_el.get_text(strip=True) if company_el else "",
                url=BASE_URL + href if href else "",
                location=location_el.get_text(strip=True) if location_el else "",
                description=snippet_el.decode_contents() if snippet_el else "",
            )
        )
    return [job for job in jobs if job.url]


def _fill_descriptions(jobs_by_url: dict[str, NormalizedJob], search_terms: list[str]) -> None:
    # Same narrowing as arbeitnow_api.py: only pay for a detail-page request
    # for jobs whose title already matches search_terms (the check
    # pipeline/filters.py:filter_by_title applies downstream anyway).
    candidates = [job for job in jobs_by_url.values() if title_matches(job.title, search_terms)]
    logger.info(
        "fetching full descriptions for %d/%d title-matched stepstone jobs",
        len(candidates),
        len(jobs_by_url),
    )

    for i, job in enumerate(candidates):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)
        try:
            description = _fetch_description(job.url)
        except httpx.HTTPError as exc:
            logger.warning("failed to fetch description for %s: %s", job.url, exc)
            continue
        if description:
            job.description = description


def _fetch_description(url: str) -> str:
    # StepStone's "-inline.html" detail pages reset the connection (HTTP/2
    # INTERNAL_ERROR) without a Referer header - confirmed by testing with and
    # without it. A search-results-page Referer is enough; the exact term
    # doesn't matter, it just has to look like real site navigation.
    response = get_with_retry(url, headers={"Referer": BASE_URL + "/jobs/qa-engineer"})
    soup = BeautifulSoup(response.text, "html.parser")
    desc_el = soup.select_one('[data-at="job-ad-content"]')
    # Raw inner HTML, not get_text() - keeps <li>/<ul> bullet-point structure
    # intact for pipeline/classify_language.py's HTML-tag clause boundary.
    return desc_el.decode_contents() if desc_el else ""
