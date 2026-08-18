import re
import xml.etree.ElementTree as ET

from adapters.boards import NormalizedJob
from http_client import get_with_retry

# GermanTechJobs' filtered job-list pages are a client-rendered React app with no
# job data in the raw HTML, so this adapter reads the site's RSS feed instead
# (unfiltered by category/location — narrowed downstream by title_match_terms).
TITLE_PATTERN = re.compile(r"^(?P<title>.+?)\s*@\s*(?P<company>.+?)(?:\s*\[.*\])?$")


def fetch_jobs(source_config: dict) -> list[NormalizedJob]:
    rss_url = source_config["rss_url"]
    response = get_with_retry(rss_url)
    root = ET.fromstring(response.text)

    jobs = []
    for item in root.findall("./channel/item"):
        raw_title = (item.findtext("title") or "").strip()
        match = TITLE_PATTERN.match(raw_title)
        title = match.group("title").strip() if match else raw_title
        company = match.group("company").strip() if match else "Unknown"

        jobs.append(
            NormalizedJob(
                source_id=source_config["id"],
                title=title,
                company=company,
                url=(item.findtext("link") or "").strip(),
                location="Germany",
                description=item.findtext("description") or "",
            )
        )
    return jobs
