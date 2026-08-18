import logging

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


def fetch_from_sources(
    sources_config: dict, keywords_config: dict, source_ids: list[str]
) -> list[NormalizedJob]:
    sources_by_id = {source["id"]: source for source in sources_config["sources"]}
    search_terms = keywords_config["title_match_terms"]

    jobs: list[NormalizedJob] = []
    for source_id in source_ids:
        source = sources_by_id.get(source_id)
        if source is None:
            logger.warning("source %s not found in sources.yaml", source_id)
            continue

        fetch_jobs = ADAPTERS.get(source["adapter"])
        if fetch_jobs is None:
            logger.warning("no adapter registered for %s", source["adapter"])
            continue

        try:
            source_jobs = fetch_jobs({**source, "search_terms": search_terms})
        except Exception:
            logger.exception("failed to fetch jobs from %s", source_id)
            continue

        logger.info("fetched %d jobs from %s", len(source_jobs), source_id)
        jobs.extend(source_jobs)

    return jobs
