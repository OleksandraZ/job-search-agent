"""Recognize the same job posted on several boards, several times, or per city.

A job's URL is not a stable identity: in storage/jobs.db (2026-10-06) 266 of 712 sent
entries were repeats of an already-sent job - e.g. one Blackwave posting sent 21
times in four weeks, because Xing's links carry changing tracking parameters
(location_hash/utm_*) and the same job is also listed on Bundesagentur and
stellenanzeigen.de. So jobs are compared by normalized title + company instead -
used by the daily Telegram run (storage/dedupe.py, notifier/telegram.py) and the
Excel report (tools/market_report.py) alike.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from adapters.boards import NormalizedJob

# Legal-form tokens ignored when comparing company names ("imbus AG" == "imbus").
_LEGAL_FORMS = {
    "gmbh", "mbh", "ag", "se", "kg", "kgaa", "co", "ug", "ohg", "gbr", "ev", "inc",
    "ltd", "llc", "plc", "bv", "nv", "sa", "sas", "srl", "oy", "ab", "as",
}
_GENDER_MARKER = re.compile(
    r"\(.*?\)|\[.*?\]|\b[mwfdx]\s*[/|]\s*[mwfdx]\s*(?:[/|]\s*[mwfdx])?\b|\ball[\s-]*genders?\b",
    re.IGNORECASE,
)
MAX_LOCATION_CHARS = 60


def duplicate_key(job: NormalizedJob) -> str:
    """'<normalized title>|<first meaningful company word>'. Real duplicates differ
    only in gender markers ("(m/w/d)" vs "- m/f/d"), legal forms and branch suffixes
    ("FERCHAU GmbH Niederlassung ..." vs "FERCHAU - Connecting People") or casing
    ("imbus AG" vs "Imbus Ag"). The city is deliberately not part of the key: the
    same opening is routinely listed once per city (user decision 2026-10-06)."""
    title = " ".join(re.findall(r"[a-z0-9äöüß+#]+", _GENDER_MARKER.sub(" ", job.title.lower())))
    company_words = [w for w in re.findall(r"[a-z0-9äöüß]+", job.company.lower()) if w not in _LEGAL_FORMS]
    return f"{title}|{company_words[0] if company_words else ''}"


def _host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return re.sub(r"^(?:www\d?|en|de|m)\.", "", host)


def _is_company_site(job: NormalizedJob) -> bool:
    # Company (ATS) jobs carry "<vendor>:<company>" source ids (adapters/registry.py),
    # board jobs a plain sources.yaml id.
    return ":" in job.source_id


@dataclass
class JobGroup:
    """All copies of one job found in a run, in first-seen order."""

    copies: list[NormalizedJob]

    @property
    def best_described(self) -> NormalizedJob:
        """The copy with the most complete description - the most reliable basis
        for the language label."""
        return max(self.copies, key=lambda job: len(job.description))

    @property
    def main(self) -> NormalizedJob:
        """The copy whose link is shown: the company's own career page if any copy
        comes from one (direct application, no board tracking), otherwise the most
        completely described board copy (user decision 2026-10-06)."""
        company_copies = [job for job in self.copies if _is_company_site(job)]
        pool = company_copies or self.copies
        return max(pool, key=lambda job: len(job.description))

    @property
    def locations(self) -> str:
        """All copies' locations, de-duplicated and cut to MAX_LOCATION_CHARS at a
        comma - some boards put a dozen cities into a single listing's location
        field (seen on StepStone/Bundesagentur, 2026-10-06), which would otherwise
        blow up a one-line Telegram entry."""
        joined = ", ".join(dict.fromkeys(job.location for job in self.copies if job.location))
        if len(joined) <= MAX_LOCATION_CHARS:
            return joined
        cut = joined.rfind(", ", 0, MAX_LOCATION_CHARS)
        return (joined[:cut] if cut > 0 else joined[:MAX_LOCATION_CHARS]) + ", …"

    @property
    def other_hosts(self) -> list[str]:
        """Websites of the other copies (e.g. 'xing.com'), excluding the main link's
        own site - a second copy on the same board adds nothing worth showing."""
        main_host = _host(self.main.url)
        return list(dict.fromkeys(h for job in self.copies if (h := _host(job.url)) and h != main_host))


def group_duplicates(jobs: list[NormalizedJob]) -> list[JobGroup]:
    """Jobs grouped by duplicate_key(), in first-seen order."""
    groups: dict[str, list[NormalizedJob]] = {}
    for job in jobs:
        groups.setdefault(duplicate_key(job), []).append(job)
    return [JobGroup(copies) for copies in groups.values()]
