from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from adapters.boards import NormalizedJob, title_matches
from http_client import fetch_each, get_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://www.munich-startup.de"
REQUEST_DELAY_SECONDS = 1.0


def fetch_jobs(source_config: dict) -> list[NormalizedJob]:
    # The listing page's own ?q= search param is silently ignored (verified live:
    # identical 15 results with and without it) - it's a client-side-only React
    # filter that never reaches the server-rendered response. No pagination control
    # exists either; the single listing page is the whole "Stellenangebote" catalog
    # (verified live: same job count with/without a query param). Crawl it in full
    # and lean on title_matches downstream, same approach as GermanTechJobs' RSS.
    search_terms = source_config.get("search_terms", [])
    source_id = source_config["id"]

    response = get_with_retry(source_config["url"])
    soup = BeautifulSoup(response.text, "html.parser")

    jobs_by_url: dict[str, NormalizedJob] = {}
    for card in soup.select('a[href^="/jobs/anzeige/"]'):
        href = card.get("href")
        title_el = card.select_one(".text-card-title")
        if not href or not title_el:
            continue
        company_el = card.select_one(".text-card-meta")
        url = BASE_URL + str(href)
        jobs_by_url[url] = NormalizedJob(
            source_id=source_id,
            title=title_el.get_text(strip=True),
            company=company_el.get_text(strip=True) if company_el else "",
            url=url,
            # No structured location field exists anywhere on this platform - verified
            # live against multiple job detail pages, including one whose title itself
            # names a city ("... B2B Sales Job München Startup"). A generic
            # placeholder ("germany", in pipeline/location.py's
            # GENERIC_LOCATION_PLACEHOLDERS) lets is_munich()/is_remote() fall back to
            # scanning the description text instead of silently defaulting to "no".
            location="Germany",
            description="",
        )

    _fill_descriptions(jobs_by_url, search_terms)
    return list(jobs_by_url.values())


def _fill_descriptions(jobs_by_url: dict[str, NormalizedJob], search_terms: list[str]) -> None:
    candidates = [job for job in jobs_by_url.values() if title_matches(job.title, search_terms)]
    logger.info(
        "fetching full descriptions for %d/%d title-matched munich-startup jobs",
        len(candidates),
        len(jobs_by_url),
    )

    for job, description in fetch_each(
        candidates,
        lambda j: _fetch_description(j.url),
        delay_seconds=REQUEST_DELAY_SECONDS,
        logger=logger,
        log_context="munich-startup description fetch",
    ):
        job.description = description


def _fetch_description(url: str) -> str:
    response = get_with_retry(url)
    soup = BeautifulSoup(response.text, "html.parser")
    desc_el = soup.select_one(".pinboard-prose")
    # Raw inner HTML, not get_text() - keeps <h2>/<p>/<li> tag boundaries intact for
    # pipeline/classify_language.py's clause-bounded phrase matching.
    return desc_el.decode_contents() if desc_el else ""
