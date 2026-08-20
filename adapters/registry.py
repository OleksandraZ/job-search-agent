import logging
from concurrent.futures import ThreadPoolExecutor

from adapters.ats import ashby_api, greenhouse_api, lever_api, personio_feed, smartrecruiters_api, workday_api
from adapters.boards import (
    NormalizedJob,
    arbeitnow_api,
    builtin,
    bundesagentur,
    devjobs,
    englishjobsde,
    get_in_it,
    html_scrape,
    instaffo,
    stepstone,
    testdevjobs,
    wearedevelopers,
    xing_jobs,
)

logger = logging.getLogger(__name__)

ADAPTERS = {
    "arbeitnow_api": arbeitnow_api.fetch_jobs,
    "html_scrape": html_scrape.fetch_jobs,
    "stepstone": stepstone.fetch_jobs,
    "devjobs": devjobs.fetch_jobs,
    "testdevjobs": testdevjobs.fetch_jobs,
    "wearedevelopers": wearedevelopers.fetch_jobs,
    "englishjobsde": englishjobsde.fetch_jobs,
    "builtin": builtin.fetch_jobs,
    "xing_jobs": xing_jobs.fetch_jobs,
    "get_in_it": get_in_it.fetch_jobs,
    "instaffo": instaffo.fetch_jobs,
    "bundesagentur": bundesagentur.fetch_jobs,
}

# Keyed by config/companies.yaml's `ats:` value (set by tools/resolve_ats.py),
# not by an `adapter:` field the way ADAPTERS is - companies have no per-source
# id list to opt into, so every resolved company is in scope.
ATS_ADAPTERS = {
    "greenhouse": greenhouse_api.fetch_jobs,
    "lever": lever_api.fetch_jobs,
    "ashby": ashby_api.fetch_jobs,
    "smartrecruiters": smartrecruiters_api.fetch_jobs,
    "personio": personio_feed.fetch_jobs,
    "workday": workday_api.fetch_jobs,
}


# Each source/company's own rate-limit spacing (e.g. http_client.fetch_each's
# delay_seconds between an adapter's own requests) happens inside that one adapter
# call, in its own thread, so it's untouched by this - only the wait *between*
# unrelated sources/companies is removed. Capped rather than unbounded both because
# several ATS platforms concentrate many companies on one shared host (e.g. 24+
# companies all hitting boards-api.greenhouse.io - too much concurrency there risks
# tripping that host's own rate limiting for the whole batch) and because a first
# attempt at 10 workers reliably tripped macOS's DNS resolver under the burst of
# simultaneous lookups (verified live: every one of 98 companies failed with
# "nodename nor servname provided" on that run) even with http_client.py's
# connection-error retry in place.
MAX_WORKERS = 4


def fetch_from_sources(
    sources_config: dict, keywords_config: dict, source_ids: list[str]
) -> list[NormalizedJob]:
    sources_by_id = {source["id"]: source for source in sources_config["sources"]}
    search_terms = keywords_config["title_match_terms"]

    def _fetch_one(source_id: str) -> list[NormalizedJob]:
        source = sources_by_id.get(source_id)
        if source is None:
            logger.warning("source %s not found in sources.yaml", source_id)
            return []

        fetch_jobs = ADAPTERS.get(source["adapter"])
        if fetch_jobs is None:
            logger.warning("no adapter registered for %s", source["adapter"])
            return []

        try:
            source_jobs = fetch_jobs({**source, "search_terms": search_terms})
        except Exception:
            logger.exception("failed to fetch jobs from %s", source_id)
            return []

        logger.info("fetched %d jobs from %s", len(source_jobs), source_id)
        return source_jobs

    jobs: list[NormalizedJob] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for source_jobs in executor.map(_fetch_one, source_ids):
            jobs.extend(source_jobs)

    return jobs


def fetch_from_companies(companies_config: dict, keywords_config: dict) -> list[NormalizedJob]:
    search_terms = keywords_config["title_match_terms"]

    def _fetch_one(company) -> list[NormalizedJob]:
        fetch_jobs = ATS_ADAPTERS.get(company.get("ats"))
        if fetch_jobs is None:
            return []  # unresolved or not-yet-built ATS - inert, same as a board _todo

        try:
            company_jobs = fetch_jobs({**company, "search_terms": search_terms})
        except Exception:
            logger.exception("failed to fetch jobs from company %s", company["name"])
            return []

        logger.info("fetched %d jobs from %s (%s)", len(company_jobs), company["name"], company["ats"])
        return company_jobs

    jobs: list[NormalizedJob] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for company_jobs in executor.map(_fetch_one, companies_config["companies"]):
            jobs.extend(company_jobs)

    return jobs
