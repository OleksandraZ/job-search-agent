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

# Shared by munich_local.py and germany_remote.py: main.py fetches once via the union
# of both agents' SOURCE_IDS rather than calling each agent's run() separately (which
# would double the request volume) - that only avoids doubling request volume if both
# agents actually draw from the same source list.
SOURCE_IDS = [
    "arbeitnow_qa_jobs",
    "germantechjobs_testing_germany",
    "stepstone_germany",
    "devjobs_germany_qa_engineer",
    "testdevjobs_remote_germany",
    "wearedevelopers_jobs",
    "englishjobsde",
    "built_in_qa_germany",
    "xing_jobs",
    "get_in_it",
    "instaffo_qa_engineer",
    "bundesagentur_für_arbeit_jobsuche",
]

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
