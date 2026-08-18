from adapters.boards import NormalizedJob
from agents._common import fetch_from_sources
from pipeline.location import filter_munich

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


def filter_jobs(jobs: list[NormalizedJob]) -> list[NormalizedJob]:
    return filter_munich(jobs)


def run(sources_config: dict, keywords_config: dict) -> list[NormalizedJob]:
    jobs = fetch_from_sources(sources_config, keywords_config, SOURCE_IDS)
    return filter_jobs(jobs)
