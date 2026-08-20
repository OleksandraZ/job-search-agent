from __future__ import annotations

import json
import logging
import re

import httpx

from adapters.boards import NormalizedJob
from http_client import get_with_retry

logger = logging.getLogger(__name__)

COMPANY_URL_TEMPLATE = "https://join.com/companies/{identifier}"
NEXT_DATA_PATTERN = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


def _next_data(html: str) -> dict | None:
    # join.com is a classic Next.js pages-router SSR site - the entire Redux-style
    # initial state (including job listings/details) is embedded as a single JSON
    # blob in a `__NEXT_DATA__` script tag, verified live against Tangany. No
    # separate API call needed for either the listing or job detail page.
    match = NEXT_DATA_PATTERN.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def fetch_jobs(company_config: dict) -> list[NormalizedJob]:
    identifier = company_config["identifier"]
    response = get_with_retry(COMPANY_URL_TEMPLATE.format(identifier=identifier))
    data = _next_data(response.text)
    if not data:
        logger.warning("join.com __NEXT_DATA__ not found for %s", identifier)
        return []

    items = data.get("props", {}).get("pageProps", {}).get("initialState", {}).get("jobs", {}).get(
        "items", []
    )

    source_id_prefix = f"join:{identifier}"
    jobs = []
    for raw in items:
        # A real structured `country.iso3166` field (ISO code, e.g. "DE" - verified
        # live against Tangany) - trust it directly per CLAUDE.md's "trust a real
        # structured location exclusively" rule.
        country_code = (raw.get("country") or {}).get("iso3166") or ""
        if country_code.strip().upper() != "DE":
            continue

        id_param = raw.get("idParam")
        if not id_param:
            continue
        url = f"{COMPANY_URL_TEMPLATE.format(identifier=identifier)}/{id_param}"

        city = (raw.get("city") or {}).get("cityName") or ""
        location = f"{city}, Germany" if city else "Germany"

        description = ""
        try:
            detail_response = get_with_retry(url)
            detail_data = _next_data(detail_response.text)
            if detail_data:
                job = detail_data.get("props", {}).get("pageProps", {}).get("initialState", {}).get(
                    "job", {}
                )
                description = job.get("description") or ""
        except httpx.HTTPError:
            logger.warning("join.com detail fetch failed for %s", url)

        jobs.append(
            NormalizedJob(
                source_id=f"{source_id_prefix}:{raw.get('id')}",
                title=(raw.get("title") or "").strip(),
                company=company_config["name"],
                url=url,
                location=location,
                description=description,
            )
        )
    return jobs
