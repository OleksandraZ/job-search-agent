from __future__ import annotations

import json
import logging

from adapters.boards import NormalizedJob
from http_client import fetch_each, get_with_retry

logger = logging.getLogger(__name__)

# The listing page (source_config["url"]) is server-rendered and embeds the full
# search-result state as a plain (non-JSON-LD) JS object literal - `App.Data = {...}`
# in an inline <script> tag, not fetched separately. `searchTerm` (verified live:
# 7397 -> 149 results for "Tester") and `offset` (25 results/page) both work as plain
# GET query params even though the HTML form posts - no JS rendering needed.
PAGE_SIZE = 25
# The search treats a multi-word term as an OR-of-words match, not an exact phrase
# (verified live: "Software Test Engineer" returned 295 results) - deliberately
# over-broad; pipeline/filters.py's title_matches narrows the real candidates
# downstream, same as arbeitnow_api.py's full-text search. Capped per term to bound
# request volume against that breadth.
MAX_PAGES_PER_TERM = 4
REQUEST_DELAY_SECONDS = 1.0
# U+00AD SOFT HYPHEN - FERCHAU's own text embeds these at hyphenation points inside
# German compound words (e.g. "Soft\xadwa\xadre\xadtester"). Invisible when rendered,
# but left in raw would sit inside NormalizedJob.title/description text.
SOFT_HYPHEN = "\xad"


def fetch_jobs(source_config: dict) -> list[NormalizedJob]:
    search_terms = source_config.get("search_terms", [])
    source_id = source_config["id"]
    search_url = source_config["url"]
    jobs_by_url: dict[str, NormalizedJob] = {}

    for _term, offers in fetch_each(
        search_terms,
        lambda term: _search_all_pages(search_url, term),
        delay_seconds=REQUEST_DELAY_SECONDS,
        logger=logger,
        log_context="ferchau search",
    ):
        for offer in offers:
            job = _to_job(offer, source_id)
            if job is not None:
                jobs_by_url[job.url] = job

    return list(jobs_by_url.values())


def _search_all_pages(search_url: str, term: str) -> list[dict]:
    offers: list[dict] = []
    offset = 0
    for _ in range(MAX_PAGES_PER_TERM):
        response = get_with_retry(search_url, params={"searchTerm": term, "offset": offset})
        data = _parse_app_data(response.text)
        if data is None:
            break
        offers.extend(data.get("Offers") or [])
        total = (data.get("OffersCount") or {}).get("total", 0)
        offset += PAGE_SIZE
        if offset >= total:
            break
    return offers


def _parse_app_data(html: str) -> dict | None:
    marker = "App.Data = {"
    i = html.find(marker)
    if i == -1:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(html, i + len(marker) - 1)
    except ValueError:
        return None
    return data.get("ControllerResponse", {}).get("Data")


def _clean(text: str) -> str:
    return text.replace(SOFT_HYPHEN, "")


def _to_job(offer: dict, source_id: str) -> NormalizedJob | None:
    # FERCHAU's own site mixes other-country listings (verified live: AT postings
    # appear on the de/de "Tester" search) into the same feed despite the German-
    # language URL - trust the real structured locationCountryCode field, not the URL.
    if (offer.get("locationCountryCode") or "").strip().upper() != "DE":
        return None
    slug = offer.get("slug")
    if not slug:
        return None

    sections = [offer.get("intro") or ""]
    for headline_key, body_key in (
        ("tasksHeadline", "tasks"),
        ("requirementsHeadline", "requirements"),
        ("benefitsHeadline", "benefits"),
    ):
        body = offer.get(body_key)
        if body:
            sections.append(f"<p>{offer.get(headline_key) or ''}</p>{body}")
    # Raw inner HTML, not flattened - keeps <li>/<ul> tag boundaries intact for
    # pipeline/classify_language.py's clause-bounded phrase matching.
    description = _clean("".join(sections))

    location = ", ".join(
        p
        for p in (offer.get("locationCity"), offer.get("locationRegion"), offer.get("locationCountry"))
        if p
    )

    return NormalizedJob(
        source_id=source_id,
        title=_clean(offer.get("title") or ""),
        company=_clean(offer.get("contactPersonOrganizationName") or "FERCHAU"),
        # touch.ferchau.com is the real rendering host behind www.ferchau.com (seen
        # throughout the embedded state); slug already carries a stable numeric job id.
        url=f"https://touch.ferchau.com{slug}",
        location=_clean(location) or "Germany",
        description=description,
    )
