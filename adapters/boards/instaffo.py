from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ElementTree

import httpx
from bs4 import BeautifulSoup

from adapters.boards import NormalizedJob
from http_client import fetch_each, get_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://jobs.instaffo.com"
SITEMAP_URL = BASE_URL + "/sitemap-jobs.xml"
REQUEST_DELAY_SECONDS = 1.0

# Instaffo's own job listing/search page (/en/browsejobs/qa-engineer) is a pure
# client-rendered SPA - the raw HTML has no __NEXT_DATA__/RSC-embedded job data at
# all, just page chrome; jobs load via a JS fetch after hydration. Its robots.txt
# disallows /api/ and /*?q= for every crawler with no named-bot exception (unlike
# XING's explicit ClaudeBot/Claude-User carve-out - see adapters/boards/xing_jobs.py),
# so hitting that internal API directly isn't an option here even setting aside
# JS-rendering.
#
# Individual job detail pages (/en/job/<slug>-<hex-id>) ARE server-rendered, with a
# real schema.org JobPosting JSON-LD block - and the sitewide job sitemap (not
# disallowed by robots.txt) lists every one of them (~1958 unique jobs, all
# categories, not just QA - there's no per-category sitemap). Crawl that sitemap
# instead of the listing page: derive a rough title from each URL's slug (strip the
# trailing 12-hex-char id, hyphens -> spaces), pre-filter with the exact same
# substring check pipeline/filters.py:filter_by_title applies downstream, and only
# fetch the handful of detail pages that survive (~5-20 in practice) - the same
# title-matched-subset narrowing every other adapter uses, just applied one step
# earlier (on the slug) since there's no cheap listing endpoint to narrow from here.
# A job whose real title wouldn't have survived filter_by_title anyway (e.g. "Quality
# Assurance Engineer" doesn't literally contain any single title_match_terms entry)
# is correctly skipped at this stage too - no coverage lost versus fetching every job.
JOB_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
TRAILING_HEX_ID_PATTERN = re.compile(r"-[0-9a-f]{12}$")
# Slugs transliterate umlauts away (e.g. "Qualitätssicherung" -> "qualitatssicherung"),
# but title_match_terms keeps them (e.g. "Qualitätsingenieur") - normalize both sides
# the same way for this slug-only prefilter so a German term with an umlaut doesn't
# silently fail to match here. This normalization is local to the prefilter; the real
# fetched title (with proper umlauts) is what filter_by_title checks downstream.
UMLAUT_MAP = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss"})


def fetch_jobs(source_config: dict) -> list[NormalizedJob]:
    search_terms = source_config.get("search_terms", [])

    try:
        response = get_with_retry(SITEMAP_URL, timeout=60)
    except httpx.HTTPError as exc:
        logger.warning("instaffo sitemap fetch failed: %s", exc)
        return []

    all_urls = _parse_job_urls(response.text)
    candidates = [url for url in all_urls if _slug_matches(url, search_terms)]
    logger.info(
        "fetching %d/%d slug-title-matched instaffo job pages",
        len(candidates),
        len(all_urls),
    )

    jobs = []
    for _url, job in fetch_each(
        candidates,
        lambda u: _fetch_job(u, source_config["id"]),
        delay_seconds=REQUEST_DELAY_SECONDS,
        logger=logger,
        log_context="instaffo job fetch",
    ):
        if job is not None:
            jobs.append(job)

    return [job for job in jobs if job.url]


def _parse_job_urls(sitemap_xml: str) -> list[str]:
    root = ElementTree.fromstring(sitemap_xml)
    urls = [loc.text for loc in root.findall(".//sm:url/sm:loc", JOB_SITEMAP_NS) if loc.text]
    # Sitemap lists both /de/job/ and /en/job/ variants per posting - keep only the
    # English URL as the canonical NormalizedJob.url (same job either way).
    return [url for url in urls if url.startswith(BASE_URL + "/en/job/")]


def _slug_to_title_text(url: str) -> str:
    slug = url.rsplit("/", 1)[-1]
    slug = TRAILING_HEX_ID_PATTERN.sub("", slug)
    return slug.replace("-", " ").translate(UMLAUT_MAP)


def _slug_matches(url: str, terms: list[str]) -> bool:
    text = _slug_to_title_text(url).lower()
    return any(term.lower().translate(UMLAUT_MAP) in text for term in terms)


def _fetch_job(url: str, source_id: str) -> NormalizedJob | None:
    response = get_with_retry(url)
    soup = BeautifulSoup(response.text, "html.parser")

    posting = None
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(str(tag.string))
        except (json.JSONDecodeError, TypeError):
            continue
        if data.get("@type") == "JobPosting":
            posting = data
            break

    if posting is None:
        return None

    locations = posting.get("jobLocation") or []
    location = ", ".join(
        loc["address"]["addressLocality"]
        for loc in locations
        if isinstance(loc, dict) and (loc.get("address") or {}).get("addressLocality")
    )

    return NormalizedJob(
        source_id=source_id,
        title=posting.get("title", ""),
        company=(posting.get("hiringOrganization") or {}).get("name", ""),
        url=url,
        location=location,
        # Raw HTML, not get_text() - keeps structure intact for
        # pipeline/classify_language.py's HTML-tag clause boundary.
        description=posting.get("description", "") or "",
    )
