from adapters.boards import NormalizedJob
from agents._common import SOURCE_IDS, fetch_from_sources
from pipeline.location import filter_munich


def filter_jobs(jobs: list[NormalizedJob]) -> list[NormalizedJob]:
    return filter_munich(jobs)


def run(sources_config: dict, keywords_config: dict) -> list[NormalizedJob]:
    jobs = fetch_from_sources(sources_config, keywords_config, SOURCE_IDS)
    return filter_jobs(jobs)
