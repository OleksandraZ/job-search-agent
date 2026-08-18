from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from adapters.boards import NormalizedJob
from http_client import fetch_each, get_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://englishjobs.de"
REQUEST_DELAY_SECONDS = 0.5


def fetch_jobs(source_config: dict) -> list[NormalizedJob]:
    search_terms = source_config.get("search_terms", [])
    jobs_by_url: dict[str, NormalizedJob] = {}

    for _term, html in fetch_each(
        search_terms,
        _search,
        delay_seconds=REQUEST_DELAY_SECONDS,
        logger=logger,
        log_context="englishjobs.de search",
    ):
        for job in _parse_search_page(html, source_config["id"]):
            jobs_by_url[job.url] = job

    return list(jobs_by_url.values())


def _search(term: str) -> str:
    slug = term.replace(" ", "_")
    response = get_with_retry(f"{BASE_URL}/jobs/{slug}")
    return response.text


def _parse_search_page(html: str, source_id: str) -> list[NormalizedJob]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("div.job.js-job"):
        title_el = card.select_one('[itemprop="title"]')
        # Company, location, posted-date, always in that order - confirmed by
        # sampling every card on a results page.
        fields = [li.get_text(strip=True) for li in card.select("ul.space-y-1 li")]
        company = fields[0] if len(fields) > 0 else ""
        location = fields[1] if len(fields) > 1 else ""
        # This is a clickout-tracked aggregator (talent.com-powered) - the listing
        # page is englishjobs.de's own, but "View job" redirects out to whatever
        # arbitrary external site/employer actually posted it, with no consistent
        # structure to fetch a fuller description from (unlike stepstone.py/
        # devjobs.py/testdevjobs.py, which each have one single, consistent,
        # same-site detail page). So the search-result snippet - real excerpted
        # text from the actual posting, not a placeholder - is used as-is, same
        # approach as html_scrape.py's GermanTechJobs RSS.
        snippet_el = card.select_one("div.mr-4")
        # NOT the <a>'s full href: the same real posting gets a different, freshly
        # re-signed clickout URL every time it's returned (confirmed: querying
        # "Test Engineer" and "Senior Test Engineer" both surface the identical
        # Amazon Robotics job, same /clickout/<id> path, but a different trailing
        # tracking payload each time). Using the full href as job.url would defeat
        # both this function's own dedup-by-url AND pipeline/dedupe.py's persistent
        # SQLite dedup (job_id is derived from source_id+url), so the same job would
        # look "new" on every single run forever. The card's own id attribute is
        # the stable per-job identifier - confirmed the bare "/clickout/<id>" (no
        # query string at all) still 302-redirects correctly to the real posting.
        job_id = card.get("id", "")

        jobs.append(
            NormalizedJob(
                source_id=source_id,
                # Not get_text(strip=True) or get_text(" ", strip=True): the
                # matched search term(s) in the title are wrapped in separate <em>
                # tags (e.g. "Senior <em>QA</em>/QC <em>Engineer</em>"), so
                # strip=True's per-node stripping eats the real space before
                # "<em>QA</em>" while a " " separator invents one that was never
                # there between "QA" and "/QC" - either way corrupts titles like
                # "QA/QC" into something filter_by_title's substring check won't
                # match. get_text() with no args preserves the original spacing
                # exactly; only the final whitespace-collapse is safe to do.
                title=re.sub(r"\s+", " ", title_el.get_text()).strip() if title_el else "",
                company=company,
                url=f"{BASE_URL}/clickout/{job_id}" if job_id else "",
                location=location,
                description=snippet_el.decode_contents() if snippet_el else "",
            )
        )
    return [job for job in jobs if job.url]
