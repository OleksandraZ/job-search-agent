from __future__ import annotations

import logging
import time

import httpx
from bs4 import BeautifulSoup

from adapters.boards import NormalizedJob, title_matches
from http_client import fetch_each_concurrent, get_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://en.devjobs.de"
SEARCH_URL = BASE_URL + "/jobs/search"
# DEVjobs.de's default httpx UA gets a 403 - a browser UA is required. Confirmed by
# testing with and without it.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}
REQUEST_DELAY_SECONDS = 0.5
MAX_PAGES_PER_PROFESSION = 30
# See http_client.fetch_each_concurrent's docstring - kept modest since every
# description request here hits the same host (en.devjobs.de).
DESCRIPTION_FETCH_WORKERS = 4

# DEVjobs.de has no free-text search - /jobs/search only accepts jobProfessions from a
# fixed, small taxonomy (confirmed by testing every title_match_terms entry as a
# slug: only these two returned real results, everything else returned 0). So,
# unlike arbeitnow_api.py/stepstone.py, this adapter doesn't read source_config's
# search_terms to build queries - it crawls these two known-good categories in full
# and lets pipeline/filters.py:filter_by_title narrow the result downstream, same
# approach as GermanTechJobs' unfiltered RSS feed.
JOB_PROFESSIONS = ["qa-engineer", "test-automation-engineer"]


def fetch_jobs(source_config: dict) -> list[NormalizedJob]:
    search_terms = source_config.get("search_terms", [])
    jobs_by_url: dict[str, NormalizedJob] = {}

    for profession in JOB_PROFESSIONS:
        for page in range(1, MAX_PAGES_PER_PROFESSION + 1):
            if jobs_by_url or page > 1:
                time.sleep(REQUEST_DELAY_SECONDS)
            try:
                response = get_with_retry(
                    SEARCH_URL,
                    params={"jobProfessions": profession, "page": page},
                    headers=HEADERS,
                )
            except httpx.HTTPError as exc:
                logger.warning("devjobs %s page %d failed: %s", profession, page, exc)
                break

            page_jobs = _parse_search_page(response.text, source_config["id"])
            if not page_jobs:
                break
            for job in page_jobs:
                jobs_by_url[job.url] = job

    _fill_descriptions(jobs_by_url, search_terms)

    return list(jobs_by_url.values())


def _parse_search_page(html: str, source_id: str) -> list[NormalizedJob]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select('a[href^="/job/"]'):
        title_el = card.select_one("h2")
        company_el = card.select_one("div.ml-2 p")
        location_el = card.select_one("div.ml-2 span")
        # Listing cards carry a short (~200 char) role summary, real text but not
        # the full description - for title-matched jobs the adapter fetches the
        # detail page (below) for the full description instead.
        snippet_el = card.select_one("p.line-clamp-2")
        href = str(card.get("href", ""))

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
    # Same narrowing as arbeitnow_api.py/stepstone.py: only pay for a detail-page
    # request for jobs whose title already matches search_terms (the check
    # pipeline/filters.py:filter_by_title applies downstream anyway).
    candidates = [job for job in jobs_by_url.values() if title_matches(job.title, search_terms)]
    logger.info(
        "fetching full descriptions for %d/%d title-matched devjobs jobs",
        len(candidates),
        len(jobs_by_url),
    )

    for job, description in fetch_each_concurrent(
        candidates,
        lambda j: _fetch_description(j.url),
        max_workers=DESCRIPTION_FETCH_WORKERS,
        logger=logger,
        log_context="devjobs description fetch",
    ):
        if description:
            job.description = description


def _fetch_description(url: str) -> str:
    response = get_with_retry(url, headers=HEADERS)
    soup = BeautifulSoup(response.text, "html.parser")
    # The single div wrapping the real job body ("Your role in the team" /
    # "Our expectations of you" / "What we offer" / benefits) - confirmed unique on
    # the page (unlike the "these jobs might also interest you" recommendations
    # widget, which sits in a different parent).
    desc_el = soup.find("div", class_="md:-mt-2")
    # Raw inner HTML, not get_text() - keeps <li>/<ul> bullet-point structure intact
    # for pipeline/classify_language.py's HTML-tag clause boundary.
    return desc_el.decode_contents() if desc_el else ""
