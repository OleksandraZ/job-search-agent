from __future__ import annotations

import logging
import re
import time

import httpx

from adapters.boards import NormalizedJob
from http_client import get_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://www.wearedevelopers.com"
JOBS_MD_URL = BASE_URL + "/jobs.md"
REQUEST_DELAY_SECONDS = 0.5

# WeAreDevelopers Labs publishes every page as clean Markdown (append ".md" to any
# URL - see https://www.wearedevelopers.com/agents.md) specifically for machine
# consumption: no HTML parsing needed. /jobs.md?country=DE&q=<term> is a real,
# working keyword search (confirmed: "QA Engineer" narrows ~54k unfiltered DE jobs
# down to 222 matching), queried once per title_match_terms entry like
# arbeitnow_api.py. Only page 1 (~25 results) is fetched per term - some terms alone
# return 200+ results across ~9 pages, and relying on filter_by_title downstream
# (same as every other adapter) plus the breadth of 23 different search terms
# already gives good coverage without deep-paginating each one.
JOB_HEADING = re.compile(r"^## (.+)$", re.MULTILINE)
FIELD = re.compile(r"^- \*\*(\w+):\*\* (.+)$", re.MULTILINE)
VIEW_JOB_LINK = re.compile(r"^- \[View job\]\((\S+)\)$", re.MULTILINE)


def fetch_jobs(source_config: dict) -> list[NormalizedJob]:
    search_terms = source_config.get("search_terms", [])
    jobs_by_url: dict[str, NormalizedJob] = {}

    for i, term in enumerate(search_terms):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        try:
            text = _search(term)
        except httpx.HTTPError as exc:
            logger.warning("wearedevelopers search for %r failed: %s", term, exc)
            continue

        for job in _parse_jobs_md(text, source_config["id"]):
            jobs_by_url[job.url] = job

    _fill_descriptions(jobs_by_url, search_terms)

    return list(jobs_by_url.values())


def _search(term: str) -> str:
    response = get_with_retry(JOBS_MD_URL, params={"country": "DE", "q": term})
    return response.text


def _parse_jobs_md(text: str, source_id: str) -> list[NormalizedJob]:
    headings = list(JOB_HEADING.finditer(text))
    jobs = []
    for i, heading in enumerate(headings):
        block_end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        block = text[heading.end() : block_end]

        fields = dict(FIELD.findall(block))
        link_match = VIEW_JOB_LINK.search(block)

        jobs.append(
            NormalizedJob(
                source_id=source_id,
                title=heading.group(1).strip(),
                company=fields.get("Company", ""),
                url=link_match.group(1) if link_match else "",
                location=fields.get("Location", ""),
                description="",
            )
        )
    return [job for job in jobs if job.url]


def _fill_descriptions(jobs_by_url: dict[str, NormalizedJob], search_terms: list[str]) -> None:
    # Same narrowing as the other adapters: only pay for a detail-page request for
    # jobs whose title already matches search_terms (the check
    # pipeline/filters.py:filter_by_title applies downstream anyway).
    candidates = [job for job in jobs_by_url.values() if _title_matches(job.title, search_terms)]
    logger.info(
        "fetching full descriptions for %d/%d title-matched wearedevelopers jobs",
        len(candidates),
        len(jobs_by_url),
    )

    for i, job in enumerate(candidates):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)
        try:
            description = _fetch_description(job.url)
        except httpx.HTTPError as exc:
            logger.warning("failed to fetch description for %s: %s", job.url, exc)
            continue
        if description:
            job.description = description


def _title_matches(title: str, terms: list[str]) -> bool:
    lowered = title.lower()
    return any(term.lower() in lowered for term in terms)


def _fetch_description(url: str) -> str:
    response = get_with_retry(url + ".md")
    text = response.text
    # Everything after the "## <title>" heading is the job body (About the Role,
    # requirements, skills, etc.) - the same clean markdown as the listing, just the
    # detail page's version. No HTML tags here (it's plain markdown, not markdown
    # rendered to HTML), so pipeline/classify_language.py's HTML-tag clause boundary
    # never triggers on this source - "." and ";" alone still bound each clause.
    heading = JOB_HEADING.search(text)
    return text[heading.end() :].strip() if heading else ""
