from adapters.boards import NormalizedJob
from pipeline.location import filter_munich


def filter_jobs(jobs: list[NormalizedJob]) -> list[NormalizedJob]:
    return filter_munich(jobs)
