from adapters.boards import NormalizedJob


def filter_by_title(jobs: list[NormalizedJob], title_match_terms: list[str]) -> list[NormalizedJob]:
    terms = [term.lower() for term in title_match_terms]
    return [job for job in jobs if any(term in job.title.lower() for term in terms)]
