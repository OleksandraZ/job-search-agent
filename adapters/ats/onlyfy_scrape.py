from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from adapters.ats._common import looks_like_a_german_location
from adapters.boards import NormalizedJob
from http_client import get_with_retry

logger = logging.getLogger(__name__)

LISTING_URL_TEMPLATE = "https://{identifier}.onlyfy.jobs/en"


def fetch_jobs(company_config: dict) -> list[NormalizedJob]:
    identifier = company_config["identifier"]
    response = get_with_retry(LISTING_URL_TEMPLATE.format(identifier=identifier))
    soup = BeautifulSoup(response.text, "html.parser")

    source_id_prefix = f"onlyfy:{identifier}"
    jobs = []
    for card in soup.find_all("a", attrs={"data-testid": "job-card"}, href=True):
        title_el = card.find(None, attrs={"data-testid": "job-title"})
        info_el = card.find(None, attrs={"data-testid": "job-more-info"})
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            continue

        # "job-more-info" is "<city> | <employment type>" (verified live against
        # ARRK Engineering, whose board also lists non-Germany offices - e.g.
        # Hefei, China - alongside Munich). This is a bare city name with no
        # country field at all, so the *strict* variant is required here, not
        # is_germany_relevant()'s default-true-on-ambiguous bias - that bias would
        # (and did, before this was caught live) mislabel "Hefei" as Germany.
        info_text = info_el.get_text(strip=True) if info_el else ""
        city = info_text.split("|")[0].strip()
        if not looks_like_a_german_location(city):
            continue

        job_url = str(card["href"])
        if job_url.startswith("/"):
            job_url = f"https://{identifier}.onlyfy.jobs{job_url}"

        jobs.append(
            NormalizedJob(
                source_id=f"{source_id_prefix}:{job_url}",
                title=title,
                company=company_config["name"],
                url=job_url,
                location=f"{city}, Germany",
                # onlyfy's job detail page renders entirely client-side (React
                # Server Components streaming, no description anywhere in the
                # static HTML or any discoverable API - verified live against
                # ARRK Engineering) - same accepted limitation as Arbeitnow
                # (empty description, see docs/lessons/classification.md). Not
                # worth a Playwright dependency for two companies.
                description="",
            )
        )
    return jobs
