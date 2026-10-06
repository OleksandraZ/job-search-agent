from typing import Union

from adapters.boards import NormalizedJob, title_matches
from pipeline.experience import required_years


def filter_by_title(jobs: list[NormalizedJob], title_match_terms: list[str]) -> list[NormalizedJob]:
    return [job for job in jobs if title_matches(job.title, title_match_terms)]


def exclude_by_title(jobs: list[NormalizedJob], title_exclude_terms: list[str]) -> list[NormalizedJob]:
    return [job for job in jobs if not title_matches(job.title, title_exclude_terms)]



def require_term_groups(jobs: list[NormalizedJob], groups: list[list[str]]) -> list[NormalizedJob]:
    # Keeps a job only if, for EVERY group, its title or description mentions at
    # least one of that group's terms - the "(role) AND (skill A OR skill B) AND
    # (tool X OR tool Y)" part of a search that title_match_terms' OR-only matching
    # can't express. A job with an empty description is kept, not dropped: some
    # sources never provide one (e.g. Arbeitnow, see CLAUDE.md's
    # description-required note), so an empty string means "unknown", not
    # "doesn't mention the skill".
    return [
        job
        for job in jobs
        if not job.description.strip()
        or all(
            title_matches(job.title, group) or title_matches(job.description, group)
            for group in groups
        )
    ]


def exclude_by_description(
    jobs: list[NormalizedJob], description_exclude_terms: list[Union[str, dict[str, list[str]]]]
) -> list[NormalizedJob]:
    # Drops a job whose description (or title) mentions an out-of-scope domain/tool,
    # even when its title is otherwise a perfect match - a term that rules a job out
    # in its description rules it out in its title too, and checking the title also
    # covers jobs whose description is empty. Each entry is either a plain term ("SAP" - any
    # mention drops the job) or a conditional rule {terms: [...], unless: [...]}:
    # dropped only if the description mentions one of `terms` AND neither title nor
    # description mentions any `unless` term - e.g. Selenium is only a reason to
    # drop a job that doesn't also use Playwright/Python. Same word-boundary
    # matching as titles.
    def excluded(job: NormalizedJob) -> bool:
        for entry in description_exclude_terms:
            if isinstance(entry, str):
                if title_matches(job.title, [entry]) or title_matches(job.description, [entry]):
                    return True
            elif title_matches(job.description, entry["terms"]) and not (
                title_matches(job.title, entry["unless"])
                or title_matches(job.description, entry["unless"])
            ):
                return True
        return False

    return [job for job in jobs if not excluded(job)]


def exclude_by_required_years(jobs: list[NormalizedJob], max_required_years: int) -> list[NormalizedJob]:
    # Drops a job whose description asks for more than max_required_years of
    # experience (pipeline/experience.py:required_years()). A job that states no
    # number - including an empty description - is kept: "not stated" isn't "too many".
    return [
        job for job in jobs
        if (years := required_years(job.description)) is None or years <= max_required_years
    ]
