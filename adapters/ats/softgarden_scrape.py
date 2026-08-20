from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from adapters.boards import NormalizedJob, title_matches
from http_client import get_with_retry

logger = logging.getLogger(__name__)

# Softgarden has at least two distinct hosting conventions confirmed live
# (<slug>.softgarden.io and <slug>.career.softgarden.de - see
# tools/resolve_ats.py's ATS_PATTERNS comment), but only the .io one has a known
# page structure (Apache Wicket-rendered, /vacancies listing, stable
# /job/<id>/<slug> detail links - verified live against CQSE and PASSAUER WOLF).
# The .career.softgarden.de convention (Sunfire) 404s on the same paths, so this
# adapter only targets .io; a company resolved on the other domain shape
# currently yields zero jobs rather than guessing at an unverified structure.
#
# Deliberately the bare root, not a hardcoded /en/vacancies - a company with no
# English locale configured 404s on that path (verified live: Donner & Reuschel
# and RTLZWEI both only have a German locale, redirecting the root to
# /de/vacancies instead). The root always redirects to whichever locale the
# company actually has, English or German - the /job/<id>/<slug> link structure
# is identical either way, only the visible job titles' language differs.
LISTING_URL_TEMPLATE = "https://{identifier}.softgarden.io/"


def _whitespace_collapse(text: str) -> str:
    # get_text() concatenates inline-tag-separated words with no whitespace
    # between them - collapse per CLAUDE.md's "get_text + whitespace-collapse
    # regex" rule.
    return re.sub(r"\s+", " ", text).strip()


def _listing_jobs(response: httpx.Response) -> list[tuple[str, str]]:
    soup = BeautifulSoup(response.text, "html.parser")
    seen: set[str] = set()
    jobs: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        if "/job/" not in href:
            continue
        title = _whitespace_collapse(a.get_text())
        if not title:
            continue
        url = urljoin(str(response.url), href)
        if url in seen:
            continue
        seen.add(url)
        jobs.append((title, url))
    return jobs


def _fetch_description(url: str) -> str:
    try:
        detail = get_with_retry(url)
    except httpx.HTTPError:
        logger.warning("softgarden detail fetch failed for %s", url)
        return ""
    soup = BeautifulSoup(detail.text, "html.parser")
    body = soup.find("body")
    return _whitespace_collapse(body.get_text(" ")) if body else ""


def fetch_jobs(company_config: dict) -> list[NormalizedJob]:
    identifier = company_config["identifier"]
    search_terms = company_config.get("search_terms", [])

    try:
        response = get_with_retry(LISTING_URL_TEMPLATE.format(identifier=identifier))
    except httpx.HTTPError:
        logger.warning("softgarden listing fetch failed for %s", identifier)
        return []

    source_id_prefix = f"softgarden:{identifier}"
    jobs = []
    for title, url in _listing_jobs(response):
        if search_terms and not title_matches(title, search_terms):
            continue

        # Full description fetched only for the title-matched subset, bounding
        # request volume per CLAUDE.md's adapter contract - the listing page
        # itself has no description text at all.
        jobs.append(
            NormalizedJob(
                source_id=f"{source_id_prefix}:{url}",
                title=title,
                company=company_config["name"],
                url=url,
                # No structured location field anywhere on softgarden's listing or
                # detail page (verified live) - every company in this bucket is a
                # domestic German SME/hospital/chain with no visible international
                # postings, so "Germany" is an honest placeholder rather than a
                # guess. See CLAUDE.md's NormalizedJob.location contract.
                location="Germany",
                description=_fetch_description(url),
            )
        )
    return jobs
