from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup

from adapters.boards import NormalizedJob, title_matches
from http_client import fetch_each, get_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://www.xing.com"
SEARCH_URL = BASE_URL + "/jobs/search"
REQUEST_DELAY_SECONDS = 1.5

# XING's robots.txt disallows /jobs/search(?*) for generic crawlers ("User-agent: *")
# but has a separate block explicitly allowing it for named AI-agent bots, including
# "ClaudeBot" and "Claude-User" - a deliberate carve-out for exactly this use case.
# User confirmed (2026-08-18): identify honestly as Claude-User so requests fall under
# that explicit allow rule, rather than spoofing a generic browser UA against a path
# XING disallows for anonymous scrapers. Job detail pages (/jobs/<slug>-<id>) aren't
# restricted for anyone, but the same header is used there too for consistency.
HEADERS = {"User-Agent": "Claude-User/1.0 (+https://www.anthropic.com/claude-user)"}

LOCATION_OVERFLOW_PATTERN = re.compile(r"\s*\+\s*\d+\s*weitere\s*$")


def fetch_jobs(source_config: dict) -> list[NormalizedJob]:
    search_terms = source_config.get("search_terms", [])
    jobs_by_url: dict[str, NormalizedJob] = {}

    for _term, html in fetch_each(
        search_terms,
        _search,
        delay_seconds=REQUEST_DELAY_SECONDS,
        logger=logger,
        log_context="xing search",
    ):
        for job in _parse_search_page(html, source_config["id"]):
            jobs_by_url[job.url] = job

    _fill_descriptions(jobs_by_url, search_terms)

    return list(jobs_by_url.values())


def _search(term: str) -> str:
    response = get_with_retry(SEARCH_URL, params={"keywords": term}, headers=HEADERS)
    return response.text


def _parse_search_page(html: str, source_id: str) -> list[NormalizedJob]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.find_all("article", attrs={"data-testid": "job-search-result"}):
        title_el = card.select_one('[data-testid="job-teaser-list-title"]')
        company_el = card.select_one('p[class*="Company"]')
        location_el = card.select_one('div[class*="multi-location-display-styles__Container"]')
        link_el = card.find("a", href=True)
        href = str(link_el["href"]) if link_el else ""
        # Most cards link to XING's own /jobs/<slug>-<id> detail page. A minority
        # ("Externes Job-Angebot") link straight out to a partner site (e.g.
        # jobware.de) with an already-absolute URL - kept as-is since those carry
        # static UTM/campaign params, not per-request signed tokens (unlike
        # englishjobsde's talent.com clickouts), so they stay stable across runs.
        url = href if href.startswith("http") else (BASE_URL + href if href else "")

        location = ""
        if location_el:
            # "Bautzen , Görlitz , Chemnitz + 0 weitere" - strip the "+ N weitere"
            # (additional locations not listed) suffix; not needed for
            # is_munich()'s substring search over the visible city names.
            location = LOCATION_OVERFLOW_PATTERN.sub("", location_el.get_text(" ", strip=True)).strip()

        jobs.append(
            NormalizedJob(
                source_id=source_id,
                title=title_el.get_text(strip=True) if title_el else "",
                company=company_el.get_text(strip=True) if company_el else "",
                url=url,
                location=location,
                description="",
            )
        )
    return [job for job in jobs if job.url]


def _fill_descriptions(jobs_by_url: dict[str, NormalizedJob], search_terms: list[str]) -> None:
    # Same narrowing as the other adapters: only pay for a detail-page request for
    # jobs whose title already matches search_terms. Restricted to XING's own detail
    # pages - the "Externes Job-Angebot" cards link to a different site per employer,
    # with no shared markup to parse a description from.
    candidates = [
        job
        for job in jobs_by_url.values()
        if title_matches(job.title, search_terms) and job.url.startswith(BASE_URL + "/jobs/")
    ]
    logger.info(
        "fetching full descriptions for %d/%d title-matched xing jobs (internal detail pages only)",
        len(candidates),
        len(jobs_by_url),
    )

    # XING is a DACH-wide board (Germany/Austria/Switzerland), not Germany-only - a
    # real Wien posting ("Arbeiten Sie zu 100% remote von überall in Österreich aus")
    # matched pipeline/location.py's unambiguous full-remote phrase and would have
    # been sent as a Germany-remote match despite being explicitly Austria-only.
    # location.py has no country concept, so it's filtered here instead: every
    # detail page carries a schema.org JobPosting JSON-LD block with a real
    # jobLocation[].address.addressCountry - drop the job outright when that's a
    # confirmed non-DE country (only covers title-matched jobs, i.e. the same set
    # whose description could otherwise trigger a remote-phrase false positive;
    # non-title-matched jobs never get a populated description and pipeline/
    # location.py's is_munich()/is_remote() already only trust structured location
    # text for those, which is real city/region data with no country ambiguity risk).
    for job, (description, country) in fetch_each(
        candidates,
        lambda j: _fetch_description_and_country(j.url),
        delay_seconds=REQUEST_DELAY_SECONDS,
        logger=logger,
        log_context="xing description fetch",
    ):
        if country and country != "DE":
            logger.info("dropping non-Germany xing job (%s): %s", country, job.url)
            del jobs_by_url[job.url]
            continue
        if description:
            job.description = description


def _fetch_description_and_country(url: str) -> tuple[str, str]:
    response = get_with_retry(url, headers=HEADERS)
    soup = BeautifulSoup(response.text, "html.parser")
    desc_el = soup.find(attrs={"data-testid": "expandable-content"})  # type: ignore[call-overload]
    # Raw inner HTML, not get_text() - keeps <li>/<ul> bullet-point structure intact
    # for pipeline/classify_language.py's HTML-tag clause boundary.
    description = desc_el.decode_contents() if desc_el else ""

    country = ""
    ld_json_el = soup.find("script", type="application/ld+json")
    if ld_json_el and ld_json_el.string:
        try:
            data = json.loads(ld_json_el.string)
            country = data["jobLocation"][0]["address"]["addressCountry"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            pass

    return description, country
