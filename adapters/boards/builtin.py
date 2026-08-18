from __future__ import annotations

import logging
import time

import httpx
from bs4 import BeautifulSoup

from adapters.boards import NormalizedJob, title_matches
from http_client import get_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://builtin.com"
LISTING_URL = BASE_URL + "/jobs/eu/germany/dev-engineering/search/qa"
REQUEST_DELAY_SECONDS = 0.5
MAX_PAGES = 10


def fetch_jobs(source_config: dict) -> list[NormalizedJob]:
    search_terms = source_config.get("search_terms", [])
    # No free-text search here - every title_match_terms entry was tested as both a
    # "/search/<slug>" path and a "?q=" query param: "/search/qa" is the only real,
    # populated category (matches sources.yaml's configured URL); other slugs return
    # 0-2 results falling back to an unrelated generic "Top Software Engineer Jobs"
    # listing, and "?q=" is silently ignored (identical results with or without it,
    # same kind of dead param as Arbeitnow's documented API). So this adapter crawls
    # the one working "/search/qa" category in full (paginated) and relies on
    # filter_by_title downstream, same approach as GermanTechJobs' RSS.
    jobs_by_url: dict[str, NormalizedJob] = {}

    for page in range(1, MAX_PAGES + 1):
        if page > 1:
            time.sleep(REQUEST_DELAY_SECONDS)
        try:
            response = get_with_retry(LISTING_URL, params={"page": page})
        except httpx.HTTPError as exc:
            logger.warning("builtin.com page %d failed: %s", page, exc)
            break

        page_jobs = _parse_listing_page(response.text, source_config["id"])
        if not page_jobs:
            break
        for job in page_jobs:
            jobs_by_url[job.url] = job

    _fill_descriptions(jobs_by_url, search_terms)

    return list(jobs_by_url.values())


def _parse_listing_page(html: str, source_id: str) -> list[NormalizedJob]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("div.job-bounded-responsive"):
        title_el = card.select_one('[data-id="job-card-title"]')
        company_el = card.select_one('[data-id="company-title"] span')
        location_el = card.select_one("i.fa-location-dot")
        location = ""
        if location_el:
            location_container = location_el.find_parent("div", class_=lambda c: c and "d-flex" in c)
            location_span = location_container.find_next("span") if location_container else None
            location = location_span.get_text(strip=True) if location_span else ""
        # Work mode ("Hybrid" / "In-Office" / "In-Office or Remote" / "Remote or
        # Hybrid" / "Remote") is a real, employer-declared structured signal, same
        # trust level as Arbeitnow's "Fully Remote" location values - folded into
        # location (not description) so pipeline/location.py:is_remote()'s bare
        # "remote" match picks it up.
        work_mode_el = card.select_one("i.fa-house-building")
        work_mode = ""
        if work_mode_el:
            work_mode_div = work_mode_el.find_parent("div")
            work_mode_span = work_mode_div.find_next_sibling("span") if work_mode_div else None
            work_mode = work_mode_span.get_text(strip=True) if work_mode_span else ""
        href = str(title_el.get("href", "")) if title_el else ""

        jobs.append(
            NormalizedJob(
                source_id=source_id,
                title=title_el.get_text(strip=True) if title_el else "",
                company=company_el.get_text(strip=True) if company_el else "",
                url=BASE_URL + href if href else "",
                location=f"{location} {work_mode}".strip(),
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
        "fetching full descriptions for %d/%d title-matched builtin.com jobs",
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
    response = get_with_retry(url)
    soup = BeautifulSoup(response.text, "html.parser")
    # The single element wrapping the whole job posting body (role, responsibilities,
    # requirements, benefits, company info) - identified by an id matching the job's
    # own numeric id, confirmed unique on the page. It also trails into a "Similar
    # Companies Hiring" widget at the end (company names/industries only, not
    # requirement-shaped text - accepted as harmless noise rather than chasing an
    # exact-boundary selector).
    desc_el = soup.select_one("div.job-post-item")
    # Raw inner HTML, not get_text() - keeps <li>/<ul> bullet-point structure intact
    # for pipeline/classify_language.py's HTML-tag clause boundary.
    return desc_el.decode_contents() if desc_el else ""
