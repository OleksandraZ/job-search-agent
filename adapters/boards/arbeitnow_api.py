from __future__ import annotations

import logging
import time

import httpx
from bs4 import BeautifulSoup

from adapters.boards import NormalizedJob, title_matches
from http_client import get_with_retry

logger = logging.getLogger(__name__)

# The documented job-board-api has no search/tags filtering (confirmed by testing —
# ?search= and ?tags= are silently ignored) and only returns the newest ~175 postings,
# so relevant older jobs never surface. /api/jobs is the internal endpoint behind the
# site's own search box: undocumented, returns an HTML fragment (parsed below), but
# does real full-text search across the whole catalog. It rate-limits (429) after a
# burst of requests but recovers within a few seconds, so each request is spaced out
# in addition to _http.get_with_retry()'s single retry-after-backoff on a 429.
SEARCH_API_URL = "https://www.arbeitnow.com/api/jobs"
REQUEST_DELAY_SECONDS = 1.5


def fetch_jobs(source_config: dict) -> list[NormalizedJob]:
    search_terms = source_config.get("search_terms", [])
    jobs_by_url: dict[str, NormalizedJob] = {}

    for i, term in enumerate(search_terms):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        try:
            data = _search(term)
        except httpx.HTTPError as exc:
            logger.warning("arbeitnow search for %r failed: %s", term, exc)
            continue

        for job in _parse_search_fragment(data, source_config["id"]):
            jobs_by_url[job.url] = job

    _fill_descriptions(jobs_by_url, search_terms)

    return list(jobs_by_url.values())


def _search(term: str) -> str:
    response = get_with_retry(SEARCH_API_URL, params={"page": 1, "search": term, "sort_by": "relevance"})
    return response.json()["data"]


def _parse_search_fragment(html: str, source_id: str) -> list[NormalizedJob]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("div[data-link]"):
        title_el = card.select_one('h3[itemprop="title"] a')
        company_el = card.select_one('a[itemprop="hiringOrganization"]')
        location_el = card.select_one("span.text-gray-600")

        jobs.append(
            NormalizedJob(
                source_id=source_id,
                title=title_el.get_text(strip=True) if title_el else "",
                company=company_el.get_text(strip=True) if company_el else "",
                url=str(card.get("data-link", "")),
                location=location_el.get_text(strip=True) if location_el else "",
                description="",
            )
        )
    return [job for job in jobs if job.url]


def _fill_descriptions(jobs_by_url: dict[str, NormalizedJob], search_terms: list[str]) -> None:
    # The search-fragment cards above never carry a description (needed by
    # pipeline/classify_language.py), and individual detail pages ARE real
    # server-rendered HTML with a full description at [itemprop="description"] - but
    # fetching every job's detail page is too expensive to do unconditionally
    # (searching ~20 terms already returns ~150 unique jobs). Narrow to jobs whose
    # title actually matches search_terms - the same check pipeline/filters.py
    # applies downstream anyway - before paying for the extra request per job.
    candidates = [job for job in jobs_by_url.values() if title_matches(job.title, search_terms)]
    logger.info(
        "fetching full descriptions for %d/%d title-matched arbeitnow jobs",
        len(candidates),
        len(jobs_by_url),
    )

    for i, job in enumerate(candidates):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)
        try:
            job.description = _fetch_description(job.url)
        except httpx.HTTPError as exc:
            logger.warning("failed to fetch description for %s: %s", job.url, exc)


def _fetch_description(url: str) -> str:
    response = get_with_retry(url)
    soup = BeautifulSoup(response.text, "html.parser")
    desc_el = soup.select_one('[itemprop="description"]')
    # Raw inner HTML, not get_text() - keeps <li>/<ul> bullet-point structure intact
    # so pipeline/classify_language.py's HTML-tag clause boundary still applies here,
    # same as it does for GermanTechJobs' RSS description text.
    return desc_el.decode_contents() if desc_el else ""
