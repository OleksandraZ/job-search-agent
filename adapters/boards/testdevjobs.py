from __future__ import annotations

import logging
import time

import httpx
from bs4 import BeautifulSoup

from adapters.boards import NormalizedJob, title_matches
from http_client import fetch_each, get_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://testdevjobs.com"
REQUEST_DELAY_SECONDS = 0.5
MAX_PAGES = 10


def fetch_jobs(source_config: dict) -> list[NormalizedJob]:
    search_terms = source_config.get("search_terms", [])
    # No free-text search here - this source is a fixed, pre-filtered listing page
    # (config's `path`, e.g. "/location/remote-germany/") rather than a query
    # endpoint, same as GermanTechJobs' RSS. Paginated (page 2 is
    # "<path>2/") until an empty page is returned.
    path = source_config["path"]
    jobs_by_url: dict[str, NormalizedJob] = {}

    for page in range(1, MAX_PAGES + 1):
        if page > 1:
            time.sleep(REQUEST_DELAY_SECONDS)
        url = BASE_URL + path if page == 1 else BASE_URL + path + f"{page}/"
        try:
            response = get_with_retry(url)
        except httpx.HTTPError as exc:
            logger.warning("testdevjobs page %d failed: %s", page, exc)
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
    for card in soup.select("div.job-tile-wrapper"):
        title_el = card.select_one("p.jobtitle")
        company_el = card.select_one("p.comptitle")
        link_el = card.select_one('a[href^="/job/"]')
        # Each card has one or more country badges followed by a work-mode badge
        # ("🌐 Fully Remote" / "🌐 On-Site") - all share the same
        # itemprop="addressCountry" markup, so the last one is the work-mode value
        # and everything before it is the location.
        badges = [
            el.get_text(strip=True)
            for el in card.select('span[itemprop="address"] span[itemprop="addressCountry"]')
        ]
        # Multi-country badges already carry a trailing comma in their own text
        # (e.g. "Germany,"), so strip it before rejoining or a multi-country job
        # ends up with doubled commas ("London,, United Kingdom,,").
        location = ", ".join(b.rstrip(",").strip() for b in badges[:-1]) if len(badges) > 1 else ""
        work_mode = badges[-1] if badges else ""
        href = str(link_el.get("href", "")) if link_el else ""

        jobs.append(
            NormalizedJob(
                source_id=source_id,
                title=title_el.get_text(strip=True) if title_el else "",
                company=company_el.get_text(strip=True) if company_el else "",
                url=BASE_URL + href if href else "",
                # work_mode folded into location (not description) since it's a
                # real, source-provided structured signal ("🌐 Fully Remote" /
                # "🌐 On-Site") - pipeline/location.py:is_remote() bare-matches
                # "remote" against job.location and trusts structured fields, same
                # as Arbeitnow's "Fully Remote" location values.
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
        "fetching full descriptions for %d/%d title-matched testdevjobs jobs",
        len(candidates),
        len(jobs_by_url),
    )

    for job, description in fetch_each(
        candidates,
        lambda j: _fetch_description(j.url),
        delay_seconds=REQUEST_DELAY_SECONDS,
        logger=logger,
        log_context="testdevjobs description fetch",
    ):
        if description:
            job.description = description


def _fetch_description(url: str) -> str:
    response = get_with_retry(url)
    soup = BeautifulSoup(response.text, "html.parser")
    desc_el = soup.select_one('[itemprop="description"]')
    # Raw inner HTML, not get_text() - keeps <li>/<ul> bullet-point structure intact
    # for pipeline/classify_language.py's HTML-tag clause boundary.
    return desc_el.decode_contents() if desc_el else ""
