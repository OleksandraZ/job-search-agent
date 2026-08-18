from __future__ import annotations

import json
import logging

from bs4 import BeautifulSoup

from adapters.boards import NormalizedJob, title_matches
from http_client import fetch_each, get_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://www.arbeitsagentur.de"
DETAIL_URL_TEMPLATE = BASE_URL + "/jobsuche/jobdetail/{ref}"
# Official, documented public API (https://jobsuche.api.bund.dev/) - the
# arbeitsagentur.de frontend's own bundled config.js confirms the real search
# endpoint moved from v4 to v6 (a JS-app config value, not something to guess at).
# "jobboerse-jobsuche" is the well-known public API key/OIDC client id embedded in
# that same config.js - not a secret, the same value every third-party integration
# against this API uses.
SEARCH_API_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
API_HEADERS = {"X-API-Key": "jobboerse-jobsuche"}
REQUEST_DELAY_SECONDS = 1.0
GERMANY = "DEUTSCHLAND"


def fetch_jobs(source_config: dict) -> list[NormalizedJob]:
    search_terms = source_config.get("search_terms", [])
    jobs_by_url: dict[str, NormalizedJob] = {}

    for _term, data in fetch_each(
        search_terms,
        _search,
        delay_seconds=REQUEST_DELAY_SECONDS,
        logger=logger,
        log_context="bundesagentur search",
    ):
        for job in _parse_search_response(data, source_config["id"]):
            jobs_by_url[job.url] = job

    _fill_descriptions(jobs_by_url, search_terms)

    return list(jobs_by_url.values())


def _search(term: str) -> dict:
    # size=100 comfortably covers every real term's result count seen so far (max
    # ~100) in one request - no pagination needed.
    response = get_with_retry(SEARCH_API_URL, params={"was": term, "size": 100}, headers=API_HEADERS)
    return response.json()


def _parse_search_response(data: dict, source_id: str) -> list[NormalizedJob]:
    jobs = []
    for raw in data.get("ergebnisliste", []):
        ref = raw.get("referenznummer")
        if not ref:
            continue

        # Bundesagentur is Germany's federal employment agency but its listings
        # aren't exclusively German - a real sample turned up Luxembourg- and
        # Romania-based postings alongside the German ones (same kind of
        # cross-border leak as XING's DACH scope, smaller in proportion here).
        # Keep only the German location(s) of a multi-site posting, and drop the
        # job entirely if none of its locations are in Germany.
        de_locations = [
            loc
            for loc in raw.get("stellenlokationen", [])
            if (loc.get("adresse") or {}).get("land") == GERMANY
        ]
        if not de_locations:
            continue
        location = ", ".join(
            loc["adresse"]["ort"] for loc in de_locations if (loc.get("adresse") or {}).get("ort")
        )

        jobs.append(
            NormalizedJob(
                source_id=source_id,
                title=raw.get("stellenangebotsTitel", ""),
                company=raw.get("firma", ""),
                url=DETAIL_URL_TEMPLATE.format(ref=ref),
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
        "fetching full descriptions for %d/%d title-matched bundesagentur jobs",
        len(candidates),
        len(jobs_by_url),
    )

    for job, description in fetch_each(
        candidates,
        lambda j: _fetch_description(j.url),
        delay_seconds=REQUEST_DELAY_SECONDS,
        logger=logger,
        log_context="bundesagentur description fetch",
    ):
        if description:
            job.description = description


def _fetch_description(url: str) -> str:
    # The /jobsuche/jobdetail/<ref> human-facing page is server-rendered with a real
    # schema.org JobPosting JSON-LD block, including the full description - unlike
    # the search API's dedicated /pc/v4/jobdetails endpoint, which 404s on every
    # real referenznummer tried (tested directly; the JS-app config.js's documented
    # resource path doesn't actually resolve). This works uniformly whether the
    # listing has a normal BA-hosted application flow or an external clickout
    # ("Chiffre" postings) - confirmed against both kinds directly.
    response = get_with_retry(url)
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(str(tag.string))
        except (json.JSONDecodeError, TypeError):
            continue
        if data.get("@type") == "JobPosting":
            # Plain text, not HTML (no tags at all) - pipeline/classify_language.py's
            # '.'/';' clause boundaries still work fine without the HTML-tag one.
            return data.get("description", "") or ""
    return ""
