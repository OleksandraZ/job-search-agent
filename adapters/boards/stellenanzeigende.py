from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup

from adapters.boards import NormalizedJob, title_matches
from http_client import fetch_each, get_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://www.stellenanzeigen.de"
SEARCH_URL = f"{BASE_URL}/suche/"
REQUEST_DELAY_SECONDS = 1.0
# The site's own search box submits this field name (verified live against the
# homepage's <input name="fulltext">), and ?fulltext=<term> genuinely filters
# results (verified live: "Tester" -> 13 real, on-topic jobs). No pagination
# affordance was found (no "load more" UI text, no working page/offset param) - a
# search term whose true match count exceeds one page's worth would be under-
# counted, same accepted tradeoff as other single-page-crawl adapters here.
JOB_HREF_PATTERN = re.compile(r"^/job/")


def fetch_jobs(source_config: dict) -> list[NormalizedJob]:
    search_terms = source_config.get("search_terms", [])
    source_id = source_config["id"]

    jobs_by_url: dict[str, NormalizedJob] = {}
    for _term, jobs in fetch_each(
        search_terms,
        lambda term: _search(term, source_id),
        delay_seconds=REQUEST_DELAY_SECONDS,
        logger=logger,
        log_context="stellenanzeigen.de search",
    ):
        for job in jobs:
            jobs_by_url[job.url] = job

    _fill_descriptions(jobs_by_url, search_terms)
    return list(jobs_by_url.values())


def _search(term: str, source_id: str) -> list[NormalizedJob]:
    response = get_with_retry(SEARCH_URL, params={"fulltext": term})
    soup = BeautifulSoup(response.text, "html.parser")

    jobs: dict[str, NormalizedJob] = {}
    for card in soup.select("div[data-jobid]"):
        # Each card embeds the same /job/ href on two anchors - an invisible
        # "hitzone" overlay (no text) that comes first in the DOM, and the real
        # title link inside <h3> - h3 specifically, not just "first match", to
        # avoid silently grabbing the empty overlay's text.
        link = card.select_one("h3 a[href]")
        if not link or not JOB_HREF_PATTERN.match(str(link.get("href", ""))):
            continue
        url = BASE_URL + str(link["href"])

        company_el = card.select_one('[data-testid="company-name"]')
        location_icon = card.select_one("i.fa-map-marker-alt")
        location_el = location_icon.find_next("span") if location_icon else None

        jobs[url] = NormalizedJob(
            source_id=source_id,
            title=link.get_text(strip=True),
            company=company_el.get_text(strip=True) if company_el else "",
            url=url,
            location=location_el.get_text(strip=True) if location_el else "Germany",
            description="",
        )
    return list(jobs.values())


def _fill_descriptions(jobs_by_url: dict[str, NormalizedJob], search_terms: list[str]) -> None:
    candidates = [job for job in jobs_by_url.values() if title_matches(job.title, search_terms)]
    logger.info(
        "fetching full descriptions for %d/%d title-matched stellenanzeigen.de jobs",
        len(candidates),
        len(jobs_by_url),
    )

    for job, result in fetch_each(
        candidates,
        lambda j: _fetch_description_and_country(j.url),
        delay_seconds=REQUEST_DELAY_SECONDS,
        logger=logger,
        log_context="stellenanzeigen.de description fetch",
    ):
        description, country = result
        # Trust the detail page's real structured jobLocation.address.addressCountry
        # over the listing card's bare city text once it's available, per CLAUDE.md's
        # "trust a real structured location once one exists" rule - drop a job that
        # turns out not to be Germany-based rather than silently keeping it.
        if country and country != "DE":
            del jobs_by_url[job.url]
            continue
        job.description = description


def _fetch_description_and_country(url: str) -> tuple[str, str]:
    response = get_with_retry(url)
    match = re.search(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
        response.text,
        re.DOTALL,
    )
    if not match:
        return "", ""
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return "", ""

    description = data.get("description") or ""
    # The CMS prefixes every description with a literal "html\n<title>...</title>"
    # block duplicating the job title (verified live) - not real content, strip it.
    description = re.sub(r"^html\s*<title>.*?</title>\s*", "", description, flags=re.DOTALL)

    locations = data.get("jobLocation") or []
    country = ""
    if locations and isinstance(locations, list):
        country = ((locations[0].get("address") or {}).get("addressCountry") or "").strip().upper()

    return description, country
