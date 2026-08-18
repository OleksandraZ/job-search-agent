from adapters.boards import NormalizedJob, title_matches


def filter_by_title(jobs: list[NormalizedJob], title_match_terms: list[str]) -> list[NormalizedJob]:
    return [job for job in jobs if title_matches(job.title, title_match_terms)]
