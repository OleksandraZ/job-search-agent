from __future__ import annotations

import logging

from adapters.ats._common import is_germany_relevant, looks_like_a_german_location
from adapters.boards import NormalizedJob, title_matches
from http_client import fetch_each, get_with_retry, post_with_retry

logger = logging.getLogger(__name__)

# Undocumented CxS API - verified live against Airbus (ag.wd3.myworkdayjobs.com)
# and Roche (roche.wd3.myworkdayjobs.com).
SEARCH_URL_TEMPLATE = "https://{tenant}.{wd_host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
DETAIL_URL_TEMPLATE = "https://{tenant}.{wd_host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{path}"
PUBLIC_URL_TEMPLATE = "https://{tenant}.{wd_host}.myworkdayjobs.com/{site}{path}"
REQUEST_DELAY_SECONDS = 1.0
# The endpoint 400s above 20 (verified live: 20 succeeds, 25 and 100 both 400) -
# not documented anywhere, found by testing directly.
SEARCH_PAGE_SIZE = 20
MAX_PAGES_PER_TERM = 5


def _collect_germany_facet_ids(facets: list[dict]) -> dict[str, list[str]]:
    # The location facet's shape isn't consistent across Workday tenants - verified
    # live: Airbus exposes a clean country-level "locationCountry" sub-facet
    # ("Germany" -> one id covering every German office), but Roche only has a flat
    # city+country "locations" sub-facet with no separate country grouping, where
    # German offices are split across per-city entries (Mannheim, Penzberg,
    # Grenzach...) plus a near-empty literal "Germany" entry (1 job). This collects
    # matches from whichever sub-facet(s) actually contain them, keyed by that
    # sub-facet's own facetParameter name, rather than assuming one fixed shape.
    ids_by_param: dict[str, list[str]] = {}
    for group in facets:
        for sub in group.get("values", []):
            param = sub.get("facetParameter")
            if not param:
                continue
            for value in sub.get("values", []):
                if looks_like_a_german_location(value.get("descriptor") or ""):
                    ids_by_param.setdefault(param, []).append(value["id"])
    return ids_by_param


def _search_page(base_url: str, applied_facets: dict, term: str, offset: int) -> dict:
    body = {
        "appliedFacets": applied_facets,
        "limit": SEARCH_PAGE_SIZE,
        "offset": offset,
        "searchText": term,
    }
    response = post_with_retry(base_url, json=body)
    return response.json()


def _search_all_pages(base_url: str, applied_facets: dict, term: str) -> list[dict]:
    postings: list[dict] = []
    offset = 0
    for _ in range(MAX_PAGES_PER_TERM):
        data = _search_page(base_url, applied_facets, term, offset)
        page = data.get("jobPostings", [])
        postings.extend(page)
        offset += SEARCH_PAGE_SIZE
        if offset >= data.get("total", 0) or not page:
            break
    return postings


def _fetch_detail(detail_url: str) -> dict:
    response = get_with_retry(detail_url)
    return response.json().get("jobPostingInfo") or {}


def fetch_jobs(company_config: dict) -> list[NormalizedJob]:
    identifier = company_config["identifier"]
    tenant, wd_host, site = identifier["tenant"], identifier["wd_host"], identifier["site"]
    search_terms = company_config.get("search_terms", [])
    base_url = SEARCH_URL_TEMPLATE.format(tenant=tenant, wd_host=wd_host, site=site)

    facets_response = post_with_retry(
        base_url, json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
    ).json()
    applied_facets = _collect_germany_facet_ids(facets_response.get("facets", []))
    if not applied_facets:
        logger.warning("no Germany-relevant location facet found for %s, skipping", company_config["name"])
        return []

    source_id = f"workday:{tenant}/{site}"
    jobs_by_url: dict[str, NormalizedJob] = {}
    detail_urls_by_job_url: dict[str, str] = {}
    for _term, postings in fetch_each(
        search_terms,
        lambda term: _search_all_pages(base_url, applied_facets, term),
        delay_seconds=REQUEST_DELAY_SECONDS,
        logger=logger,
        log_context="workday search",
    ):
        for raw in postings:
            path = raw.get("externalPath")
            title = (raw.get("title") or "").strip()
            if not path or not title:
                continue
            url = PUBLIC_URL_TEMPLATE.format(tenant=tenant, wd_host=wd_host, site=site, path=path)
            jobs_by_url[url] = NormalizedJob(
                source_id=source_id,
                title=title,
                company=company_config["name"],
                url=url,
                location=raw.get("locationsText") or "",
                description="",
            )
            detail_urls_by_job_url[url] = DETAIL_URL_TEMPLATE.format(
                tenant=tenant, wd_host=wd_host, site=site, path=path
            )

    candidates = [job for job in jobs_by_url.values() if title_matches(job.title, search_terms)]
    logger.info(
        "fetching full descriptions for %d/%d title-matched workday jobs at %s",
        len(candidates),
        len(jobs_by_url),
        company_config["name"],
    )

    confirmed_non_germany: set[str] = set()
    for job, posting in fetch_each(
        candidates,
        lambda job: _fetch_detail(detail_urls_by_job_url[job.url]),
        delay_seconds=REQUEST_DELAY_SECONDS,
        logger=logger,
        log_context="workday description fetch",
    ):
        # Belt-and-suspenders final check: the facet selection above is a
        # best-effort city-name heuristic (see _collect_germany_facet_ids), so a
        # non-Germany job could in principle slip through it. The detail endpoint's
        # own country.descriptor (verified live on both Airbus and Roche postings)
        # is authoritative - drop the job if it disagrees.
        country = (posting.get("country") or {}).get("descriptor")
        if country and country != "Germany":
            confirmed_non_germany.add(job.url)
            continue
        description = posting.get("jobDescription") or ""
        if description:
            job.description = description

    return [
        job
        for job in jobs_by_url.values()
        if job.url not in confirmed_non_germany and is_germany_relevant(job.location)
    ]
