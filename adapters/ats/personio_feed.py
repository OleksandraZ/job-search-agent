from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import httpx

from adapters.ats._common import is_germany_relevant
from adapters.boards import NormalizedJob
from http_client import get_with_retry

logger = logging.getLogger(__name__)

FEED_URL_TEMPLATE = "https://{identifier}.jobs.personio.de/xml"
# Verified live against Clark: https://{identifier}.jobs.personio.de/job/{id}
# resolves directly - a stable public URL, the feed itself has no url field.
JOB_URL_TEMPLATE = "https://{identifier}.jobs.personio.de/job/{position_id}"


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


def fetch_jobs(company_config: dict) -> list[NormalizedJob]:
    identifier = company_config["identifier"]

    try:
        response = get_with_retry(FEED_URL_TEMPLATE.format(identifier=identifier))
        root = ET.fromstring(response.text)
    except (httpx.HTTPError, ET.ParseError) as exc:
        logger.warning("personio feed fetch/parse failed for %s: %s", identifier, exc)
        return []

    source_id = f"personio:{identifier}"
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
                source_id=source_id,
                title=title,
                company=company_config["name"],
                url=JOB_URL_TEMPLATE.format(identifier=identifier, position_id=position_id),
                location=location,
                description=_description(position),
            )
        )
    return jobs
