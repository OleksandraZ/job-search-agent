from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET

import httpx

from adapters.ats._common import is_germany_relevant
from adapters.boards import NormalizedJob, title_matches
from http_client import fetch_each, get_with_retry

logger = logging.getLogger(__name__)

FEED_URL_TEMPLATE = "https://{identifier}.jobs.personio.de/xml"
# Verified live against Clark: https://{identifier}.jobs.personio.de/job/{id}
# resolves directly - a stable public URL, the feed itself has no url field.
JOB_URL_TEMPLATE = "https://{identifier}.jobs.personio.de/job/{position_id}"
# Some companies switch the XML feed off while their careers page stays live: /xml
# 404s, but /search.json still lists every open position (verified live 2026-10-23:
# 27 of ~380 resolved companies, 127 jobs, e.g. finapi-gmbh, carly). search.json has
# an empty "description" field, so - same rule as every other listing-only source -
# descriptions come from each title-matched job's detail page, whose JSON-LD
# JobPosting carries the full HTML description (verified live against carly).
SEARCH_URL_TEMPLATE = "https://{identifier}.jobs.personio.de/search.json"
REQUEST_DELAY_SECONDS = 0.5
_JSON_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)


def _location_text(position: ET.Element) -> str:
    offices = []
    office = position.findtext("office")
    if office and office.strip():
        offices.append(office.strip())
    for extra in position.findall("./additionalOffices/office"):
        if extra.text and extra.text.strip():
            offices.append(extra.text.strip())
    return ", ".join(offices)


def _description(position: ET.Element) -> str:
    # Verified live against Clark: <jobDescriptions>/<jobDescription>/<value> holds
    # real HTML inside a CDATA section - ElementTree exposes CDATA content as plain
    # .text with no extra unescaping needed, unlike Greenhouse's entity-encoded
    # content. The feed already carries the full description, no detail-page fetch
    # needed the way SmartRecruiters' listing does.
    parts = []
    for desc in position.findall("./jobDescriptions/jobDescription"):
        value = desc.findtext("value") or ""
        if value.strip():
            parts.append(value)
    return "\n".join(parts)


def _jobs_from_feed(xml_text: str, identifier: str, company: str) -> list[NormalizedJob]:
    root = ET.fromstring(xml_text)
    jobs = []
    for position in root.findall("./position"):
        position_id = position.findtext("id")
        title = (position.findtext("name") or "").strip()
        if not position_id or not title:
            continue

        location = _location_text(position)
        if not is_germany_relevant(location):
            continue

        jobs.append(
            NormalizedJob(
                source_id=f"personio:{identifier}",
                title=title,
                company=company,
                url=JOB_URL_TEMPLATE.format(identifier=identifier, position_id=position_id),
                location=location,
                description=_description(position),
            )
        )
    return jobs


def _fetch_detail_description(url: str) -> str:
    html = get_with_retry(url).text
    for block in _JSON_LD.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return str(data.get("description") or "")
    return ""


def _jobs_from_search_json(identifier: str, company: str, search_terms: list[str]) -> list[NormalizedJob]:
    positions = get_with_retry(SEARCH_URL_TEMPLATE.format(identifier=identifier)).json()
    jobs = []
    for position in positions:
        title = (position.get("name") or "").strip()
        if not position.get("id") or not title:
            continue

        location = ", ".join(office for office in position.get("offices") or [] if office) or (
            position.get("office") or ""
        )
        if not is_germany_relevant(location):
            continue

        jobs.append(
            NormalizedJob(
                source_id=f"personio:{identifier}",
                title=title,
                company=company,
                url=JOB_URL_TEMPLATE.format(identifier=identifier, position_id=position["id"]),
                location=location,
                description="",
            )
        )

    matched = [job for job in jobs if title_matches(job.title, search_terms)]
    for job, description in fetch_each(
        matched,
        lambda job: _fetch_detail_description(job.url),
        delay_seconds=REQUEST_DELAY_SECONDS,
        logger=logger,
        log_context="personio detail fetch",
    ):
        job.description = description
    return jobs


def fetch_jobs(company_config: dict) -> list[NormalizedJob]:
    identifier = company_config["identifier"]
    company = company_config["name"]

    try:
        response = get_with_retry(FEED_URL_TEMPLATE.format(identifier=identifier))
        return _jobs_from_feed(response.text, identifier, company)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            logger.warning("personio feed fetch failed for %s: %s", identifier, exc)
            return []
    except (httpx.HTTPError, ET.ParseError) as exc:
        logger.warning("personio feed fetch/parse failed for %s: %s", identifier, exc)
        return []

    try:
        return _jobs_from_search_json(identifier, company, company_config.get("search_terms", []))
    except (httpx.HTTPError, ValueError) as exc:
        # A 404 here too means the whole careers page is switched off (not hiring /
        # left Personio) - not an error worth more than a log line.
        logger.info("personio XML feed and search.json both unavailable for %s: %s", identifier, exc)
        return []
