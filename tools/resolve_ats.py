"""Phase 6 prep: classify each config/companies.yaml entry by ATS platform.

Two-step resolution: (1) find the company's real careers page (a discovered
in-page link, or a fallback list of common paths), (2) scan its content for one of
several ATS fingerprints - in the final resolved URL, the page's raw content, or a
data-* attribute - since most companies white-label/embed the ATS rather than
redirecting to it (e.g. FINN's own /careers page never leaves finn.com, but embeds a
lever.co link). If neither step finds a recognized vendor, an active fallback probes
each of the six adapter-backed platforms' own APIs directly with a slug guessed from
the company's name/domain - catches companies whose apply flow is built entirely
client-side, with zero fingerprint anywhere in their own site's content (verified
live: Celonis, GetYourGuide, Contentful, Staffbase, Parloa, Omio, AnyDesk).

Every company lands in one of three buckets:
- `ats: <vendor>` - a fingerprint or active probe found a recognized platform.
- `ats: "custom"` - a real careers page was found but no recognized vendor - a
  candidate for a future generic scraper, not yet built.
- `ats: null` - no careers page could be found at all.

This is a single automated, unauthenticated-GET heuristic pass, same caveat as the
board-source `_todo` classification in sources.yaml: informational, not a guarantee.
Re-verify a company's resolved `ats`/`identifier` against a live fetch before trusting
it in an adapter (same "verify field-by-field" step the add-board-source skill
already requires for board sources).

Usage: .venv/bin/python -m tools.resolve_ats [--force]
Rewrites config/companies.yaml in place, adding `ats`, `identifier`, `careers_url`,
`match_method`, and `resolved_at` to every company entry, prints a per-ATS count
summary, and writes tools/resolve_ats_report.md. By default only re-checks companies
currently `ats: null` or `ats: "custom"`; `--force` re-checks every company.
"""

from __future__ import annotations

import argparse
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import yaml
from bs4 import BeautifulSoup

from http_client import get_with_retry

logger = logging.getLogger(__name__)

COMPANIES_PATH = Path(__file__).parent.parent / "config" / "companies.yaml"
REPORT_PATH = Path(__file__).parent / "resolve_ats_report.md"

# Every company hits a different host, so - unlike adapters/registry.py's concern
# about several ATS platforms sharing one host - the only real constraint here is not
# hammering the local DNS resolver (see http_client.py's TransportError retry, added
# after 10 concurrent workers there reliably tripped it). Kept at the same modest cap.
MAX_WORKERS = 4

# An identifying UA rather than a browser-spoof - matches this repo's convention
# elsewhere (xing_jobs.py identifies honestly as "Claude-User/1.0") and the plan this
# was built against explicitly asked for "something identifying, not a browser-spoof".
# A prior browser-spoofed UA didn't actually help against the one real case that
# mattered anyway (GetYourGuide/AnyDesk's Cloudflare challenge ignores UA entirely -
# that's TLS/JA3 fingerprinting, not fixable by any UA string).
HEADERS = {"User-Agent": "job-search-agent/1.0 (+personal project; resolving company career pages)"}

CAREER_PATH_GUESSES = [
    "/careers",
    "/career",
    "/jobs",
    "/en/careers",
    "/en/jobs",
    "/karriere",
    "/de/karriere",
    "/join-us",
]
CAREER_LINK_PATTERN = re.compile(
    r"career|karriere|jobs?\b|stellenangebote|stellenanzeigen|wir suchen|join us", re.IGNORECASE
)

# A second, distinct pattern for the second hop only (see `_detect_ats`'s "second
# hop" comment) - a career-hub page (already matched CAREER_LINK_PATTERN to get
# here) commonly links to its actual job listing via phrasing that doesn't itself
# contain "career"/"job"/"karriere" at all, e.g. "See our open roles". Verified live
# against Taxfix: its /en/careers/ hub page's only link to the real (Ashby-embedded)
# listing page is anchor text "See our open roles" / "Open roles" - neither matches
# CAREER_LINK_PATTERN. Kept separate from CAREER_LINK_PATTERN rather than merged
# into it, since these terms (bare "role", "opening") are too generic to risk
# matching unrelated homepage links.
JOB_LISTING_LINK_PATTERN = re.compile(
    r"open\s*(?:role|position|vacanc\w*)s?|current\s*openings?|job\s*openings?|"
    r"view\s*(?:all\s*)?jobs|see\s*(?:all\s*)?(?:our\s*)?(?:jobs|roles)|"
    r"offene\s*stellen|alle\s*stellen",
    re.IGNORECASE,
)

# Each entry: (ats name, list of regexes tried in order - first capture group(s) give
# the identifier). Most platforms link directly (`jobs.lever.co/<slug>`); Greenhouse's
# standard embed snippet instead carries the slug as a `for=` query param
# (`boards.greenhouse.io/embed/job_board/js?for=<slug>`), so both forms are checked.
ATS_PATTERNS: list[tuple[str, list[re.Pattern[str]]]] = [
    (
        "greenhouse",
        [
            re.compile(
                r"boards\.greenhouse\.io/embed/job_board[^\"'\s]*[?&]for=([a-z0-9_-]+)", re.IGNORECASE
            ),
            # Deliberately two separate mandatory-literal patterns rather than one
            # with an optional `(?:v1/boards/)?` group: a real page was seen with the
            # literal text "boards-api.greenhouse.io/v1/boards/" followed by a JS
            # template variable (the slug injected at runtime, not present in the
            # static HTML) - with an optional group, regex backtracking matched "v1"
            # itself as a bogus identifier instead of failing outright. Verified live
            # against commercetools's careers page.
            re.compile(r"boards-api\.greenhouse\.io/v1/boards/([a-z0-9_-]+)", re.IGNORECASE),
            re.compile(r"boards\.greenhouse\.io/([a-z0-9_-]+)", re.IGNORECASE),
            # Newer regional job-board domain, e.g. job-boards.eu.greenhouse.io -
            # verified live against Raisin. The slug still works against the
            # standard boards-api.greenhouse.io endpoint regardless of which
            # regional domain the company's own career page displays.
            re.compile(r"job-boards(?:\.\w+)?\.greenhouse\.io/([a-z0-9_-]+)", re.IGNORECASE),
        ],
    ),
    ("lever", [re.compile(r"jobs\.lever\.co/([a-z0-9_-]+)", re.IGNORECASE)]),
    ("ashby", [re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_-]+)", re.IGNORECASE)]),
    (
        "smartrecruiters",
        [
            re.compile(r"jobs\.smartrecruiters\.com/([a-z0-9_-]+)", re.IGNORECASE),
            re.compile(r"api\.smartrecruiters\.com/v1/companies/([a-z0-9_-]+)", re.IGNORECASE),
        ],
    ),
    ("personio", [re.compile(r"([a-z0-9-]+)\.jobs\.personio\.(?:de|com)", re.IGNORECASE)]),
    (
        "workday",
        [re.compile(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/([a-z0-9_-]+)", re.IGNORECASE)],
    ),
    # softgarden: no fetch_jobs adapter exists yet (not one of the 6 in
    # adapters/registry.py's ATS_ADAPTERS), so this is inert like a board `_todo`
    # entry - resolve_ats.py tags it for a future adapter build rather than leaving
    # it as an unexplained null. Identifier is the company's subdomain slug, e.g.
    # "passauerwolf1" from https://passauerwolf1.softgarden.io - verified live
    # against PASSAUER WOLF Medizin fürs Leben's careers page.
    (
        "softgarden",
        [
            # Two distinct domain conventions confirmed live on different
            # companies: <slug>.softgarden.io (PASSAUER WOLF) and
            # <slug>.career.softgarden.de (Sunfire) - the original pattern only
            # covered the first, silently missing every company on the second.
            re.compile(r"([a-z0-9-]+)\.(?:career\.)?softgarden\.(?:io|de)", re.IGNORECASE),
        ],
    ),
    # Workable: no fetch_jobs adapter exists yet either, same inert-until-built
    # status as softgarden. Verified live against Plan A's careers page
    # (apply.workable.com/plana) - the public apply subdomain is the stable
    # per-company slug, confirmed live to be Workable's own documented URL
    # convention (not guessed).
    ("workable", [re.compile(r"apply\.workable\.com/([a-z0-9_-]+)", re.IGNORECASE)]),
    # The eight vendors below have no adapter built (or planned yet) - unlike every
    # pattern above, none of these were checked against a real live page, so they're
    # kept as simple domain/path matches on purpose: they only feed bucketing/
    # reporting, not a job-fetching adapter. Capture a slug where the platform's
    # public URL convention is well-known (subdomain-per-company, or join.com's
    # documented /companies/<slug> path); left as a presence-only check (no capture
    # group) where it isn't, per this file's own "flag identifier: null for manual
    # fill-in rather than discarding the match" rule below.
    ("recruitee", [re.compile(r"([a-z0-9-]+)\.recruitee\.com", re.IGNORECASE)]),
    ("teamtailor", [re.compile(r"([a-z0-9-]+)\.teamtailor\.com", re.IGNORECASE)]),
    ("join", [re.compile(r"join\.com/companies/([a-z0-9-]+)", re.IGNORECASE)]),
    ("rexx", [re.compile(r"rexx-systems\.com", re.IGNORECASE)]),
    ("onlyfy", [re.compile(r"([a-z0-9-]+)\.onlyfy\.jobs", re.IGNORECASE)]),
    ("dvinci", [re.compile(r"d-vinci\.de", re.IGNORECASE)]),
    ("bamboohr", [re.compile(r"([a-z0-9-]+)\.bamboohr\.com", re.IGNORECASE)]),
    ("jazzhr", [re.compile(r"jazzhr\.com", re.IGNORECASE)]),
]


def _match_signature(url: str, text: str, expected_name: str) -> dict | None:
    # Next.js's embedded page-data JSON (and similar React/JS payloads) escapes
    # forward slashes inside string literals - verified live on n8n's careers
    # page, whose raw HTML has the real ashbyhq URL as a JSON string with every
    # slash written out as the 6-character sequence u002F, not a literal slash.
    # Every pattern below expects a literal slash, so without normalizing first,
    # a real ATS reference embedded this way is silently invisible to every
    # signature check.
    haystack = f"{url}\n{text}".replace("\\u002F", "/").replace("\\/", "/")
    for ats, patterns in ATS_PATTERNS:
        for pattern in patterns:
            matches = list(pattern.finditer(haystack))
            if not matches:
                continue
            identifier: str | dict[str, str] | None
            if ats == "workday":
                match = matches[0]
                identifier = {"tenant": match.group(1), "wd_host": match.group(2), "site": match.group(3)}
            elif matches[0].groups():
                # A page can carry more than one reference matching the same
                # pattern - most often the vendor's own tracking/analytics
                # subdomain embedded on every page it hosts, which happens to
                # share the same "<slug>.<vendor>.<tld>" shape as the real
                # per-company board. Verified live: Softgarden injects
                # "matomo.softgarden.io" (its own analytics) before the real
                # "cqse.softgarden.io" reference on CQSE's careers page;
                # Recruitee injects "careers-analytics.recruitee.com" before the
                # real company slug on every Recruitee-hosted page seen so far.
                # Taking the first match blindly picked the tracker's subdomain
                # instead of the company's own. Prefer whichever candidate's
                # slug actually fuzzy-matches the company name; fall back to the
                # first match only when none do (matches this file's existing
                # default-permissive bias - see _names_match's other callers).
                candidates = list(dict.fromkeys(m.group(1) for m in matches))
                identifier = next(
                    (c for c in candidates if _names_match(c, expected_name)), candidates[0]
                )
            else:
                # A presence-only pattern (no capture group) - vendor confirmed, but
                # no slug to extract. Recorded rather than discarded (see the
                # ATS_PATTERNS comment above).
                identifier = None
            return {"ats": ats, "identifier": identifier}
    return None


# Widget embeds that carry the identifier in a data-* attribute rather than a URL a
# domain-shaped regex above would catch - e.g. Greenhouse's `data-board-token="acme"`
# snippet embed, which never puts "greenhouse.io" or the slug in a URL at all.
DATA_ATTR_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("greenhouse", re.compile(r'data-board-token=["\']([a-z0-9_-]+)["\']', re.IGNORECASE)),
    ("personio", re.compile(r'data-personio-(?:id|client)=["\']([a-z0-9_-]+)["\']', re.IGNORECASE)),
    ("softgarden", re.compile(r'data-softgarden-id=["\']([a-z0-9_-]+)["\']', re.IGNORECASE)),
]


def _match_data_attributes(text: str) -> dict | None:
    for ats, pattern in DATA_ATTR_PATTERNS:
        match = pattern.search(text)
        if match:
            return {"ats": ats, "identifier": match.group(1)}
    return None


def _find_matching_links(pattern: re.Pattern[str], base_url: str, html: str) -> list[str]:
    """Every (deduped, order-preserved) link on the page whose href or text matches
    `pattern`. Deliberately returns *all* matches, not just the first - a homepage
    can have an earlier, unrelated match (verified live: Taxfix's homepage links to
    a blog post titled "Personen mit Zweitjob" - a German compound word for "second
    job" - before its real "Karriere" link; taking only the first match picked the
    blog post and the real careers page was never even tried).
    """
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        text = a.get_text()
        if pattern.search(href) or pattern.search(text):
            url = urljoin(base_url, href)
            if url not in links:
                links.append(url)
    return links


def _candidate_career_urls(company_url: str, homepage_url: str, homepage_html: str) -> list[str]:
    candidates = _find_matching_links(CAREER_LINK_PATTERN, homepage_url, homepage_html)

    parsed = urlparse(company_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    candidates.extend(base + path for path in CAREER_PATH_GUESSES)
    # dedupe, keep order - a discovered link can coincide with a path guess
    return list(dict.fromkeys(candidates))


def _normalize_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _names_match(candidate: str, expected: str) -> bool:
    a, b = _normalize_name(candidate), _normalize_name(expected)
    return bool(a) and bool(b) and (a in b or b in a)


# Subdomain-like labels that aren't the brand itself - stripped repeatedly from the
# front of the domain before taking the first remaining label as a slug guess (e.g.
# "de.scalable.capital" -> strip "de" -> "scalable").
DOMAIN_NOISE_LABELS = {"www", "de", "en", "eu", "careers", "jobs", "m"}


def _slug_candidates(company: dict) -> list[str]:
    labels = urlparse(company["url"]).netloc.split(".")
    while labels and labels[0] in DOMAIN_NOISE_LABELS:
        labels.pop(0)
    domain_slug = re.sub(r"[^a-z0-9-]", "", labels[0].lower()) if labels else ""

    name_slug = re.sub(r"[^a-z0-9]+", "-", company["name"].lower()).strip("-")

    candidates = [s for s in (domain_slug, name_slug) if s]
    # dedupe, keep order
    return list(dict.fromkeys(candidates))


def _probe_greenhouse(slug: str, expected_name: str) -> str | None:
    try:
        response = get_with_retry(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if data.get("error"):
        return None
    jobs = data.get("jobs", [])
    if jobs and not _names_match(jobs[0].get("company_name", ""), expected_name):
        return None
    return slug


def _probe_lever(slug: str, _expected_name: str) -> str | None:
    # Lever postings carry no per-job company-name field to cross-check (verified
    # live) - a successful list response (even an empty one) is the only signal
    # available; a non-existent slug returns {"ok": false, ...} instead of a list.
    try:
        response = get_with_retry(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return slug if isinstance(data, list) else None


def _probe_ashby(slug: str, _expected_name: str) -> str | None:
    # Same no-company-name-field situation as Lever - trust the response shape.
    try:
        response = get_with_retry(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return slug if isinstance(data.get("jobs"), list) else None


def _probe_smartrecruiters(slug: str, expected_name: str) -> str | None:
    # Unlike Greenhouse (which flags an invalid board with an explicit "error" field)
    # or Lever/Ashby (whose response *shape* itself differs for an invalid slug),
    # SmartRecruiters returns a 200 with the same {"content": [], "totalFound": 0}
    # shape for a bogus slug as for a real company with zero open postings - verified
    # live, /v1/companies/<anything>/postings never errors. "content" key presence is
    # therefore not a valid signal at all; at least one real posting (with a matching
    # company name) is the only thing this endpoint can actually confirm.
    try:
        response = get_with_retry(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings")
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    postings = data.get("content", [])
    if not postings:
        return None
    if not _names_match((postings[0].get("company") or {}).get("name", ""), expected_name):
        return None
    return slug


def _probe_personio(slug: str, _expected_name: str) -> str | None:
    # No usable per-job company-name field in the feed either - a 200 with a
    # parseable <workzag-jobs> root is the signal; a non-existent identifier 404s
    # (verified live).
    try:
        response = get_with_retry(f"https://{slug}.jobs.personio.de/xml")
    except httpx.HTTPError:
        return None
    return slug if response.text.strip().startswith("<?xml") else None


# Tried in this order (most-to-least common in a live spot check) so a company on
# a common platform resolves after fewer requests. Workday is deliberately excluded
# - its identifier needs a tenant/wd-host/site combination that can't be guessed
# from a company name the way a single slug can for the other five.
PROBE_FUNCTIONS = [
    ("greenhouse", _probe_greenhouse),
    ("ashby", _probe_ashby),
    ("lever", _probe_lever),
    ("personio", _probe_personio),
    ("smartrecruiters", _probe_smartrecruiters),
]


def _probe_all_platforms(company: dict) -> dict | None:
    for slug in _slug_candidates(company):
        for ats, probe in PROBE_FUNCTIONS:
            confirmed_slug = probe(slug, company["name"])
            if confirmed_slug:
                return {"ats": ats, "identifier": confirmed_slug}
    return None


# Vendors resolve_ats can only presence-detect (no capture group anywhere in
# ATS_PATTERNS - see the comment above that list) - identifier stays null forever
# once one of these matches, so treating a null identifier there as "still needs
# resolving" would re-issue the same live requests every single call to
# resolve_pending() for no possible change in outcome.
PRESENCE_ONLY_ATS = {"rexx", "dvinci", "jazzhr"}


# `ats` has three "not a real vendor" states, kept deliberately distinct so `null`
# means exactly one thing (never attempted) instead of doing double duty for both
# "never tried" and "tried, found nothing":
#   - None        - never been through resolution at all (a bare name+url entry).
#   - "unresolved" - resolution ran and found no careers page/vendor anywhere.
#   - "custom"     - resolution found a real careers page, but no recognized vendor.
# _detect_ats/_unresolved() below only ever produce the latter two for an entry
# that's actually been attempted - `ats: null` in companies.yaml after this file has
# touched an entry would be a bug, not an outcome.
UNRESOLVED = "unresolved"


def needs_resolution(company: dict) -> bool:
    """True for a company worth *retrying* by hand: never attempted (`ats: null`),
    `ats: "unresolved"`/`"custom"` (resolve_ats didn't find a vendor last time -
    worth another shot since the company's own site can change), or a null
    `identifier` on a vendor that should have one - the last case guards against a
    hand-edited or partially-written companies.yaml entry, not just resolve_ats.py's
    own output.

    This is the CLI's own default filter (`python -m tools.resolve_ats`, no
    `--force`) - a deliberate, on-demand retry a person chooses to run. It is NOT
    what `resolve_pending()` uses for the automatic pre-`main.py` check below: an
    `"unresolved"`/`"custom"` result already reflects a real attempt, and
    re-fetching the same dead/vendor-less careers page on every single `main.py` run
    would add real latency for an outcome that essentially never changes between
    runs. See `is_new_entry()`.
    """
    ats = company.get("ats")
    if ats in (None, UNRESOLVED, "custom"):
        return True
    return company.get("identifier") is None and ats not in PRESENCE_ONLY_ATS


def is_new_entry(company: dict) -> bool:
    """True only for a company that has never been through resolution at all.
    `ats: null` is reserved exclusively for this case (see the `UNRESOLVED` comment
    above) - a company that was already tried and found nothing gets `ats:
    "unresolved"`, not null, specifically so this check can be a plain `is None`
    rather than needing to also inspect `resolved_at`. Unlike `needs_resolution()`,
    an already-attempted `"unresolved"`/`"custom"` company does NOT count here -
    that's a real, already-paid-for attempt, not something worth re-fetching on
    every `main.py` run. Use `python -m tools.resolve_ats` by hand to retry those.
    """
    return company.get("ats") is None


def _unresolved() -> dict:
    return {"ats": UNRESOLVED, "identifier": None, "careers_url": None, "match_method": None}


def _scan_page(url: str, text: str, expected_name: str) -> dict | None:
    match = _match_signature(url, text, expected_name)
    if match:
        return {**match, "careers_url": url, "match_method": "page_scan"}
    data_match = _match_data_attributes(text)
    if data_match:
        return {**data_match, "careers_url": url, "match_method": "data_attr"}
    return None


def _detect_ats(company: dict) -> dict:
    company_url = company["url"]

    try:
        homepage = get_with_retry(company_url, headers=HEADERS)
    except httpx.HTTPError as exc:
        logger.warning("could not fetch homepage for %s: %s", company["name"], exc)
        probed = _probe_all_platforms(company)
        if probed:
            return {**probed, "careers_url": None, "match_method": "api_probe"}
        return _unresolved()

    found = _scan_page(str(homepage.url), homepage.text, company["name"])
    if found:
        return found

    # First real careers page found (200, regardless of fingerprint match) - kept so
    # the custom-vs-unresolved decision below can tell "found a page, no known
    # vendor" apart from "couldn't find a careers page at all".
    first_found_career_url: str | None = None
    visited = {str(homepage.url)}
    for url in _candidate_career_urls(company_url, str(homepage.url), homepage.text):
        if url in visited:
            continue
        visited.add(url)
        try:
            response = get_with_retry(url, headers=HEADERS)
        except httpx.HTTPError:
            continue

        if first_found_career_url is None:
            first_found_career_url = str(response.url)

        found = _scan_page(str(response.url), response.text, company["name"])
        if found:
            return found

        # Second hop: this candidate 200'd (a real page exists) but carries no ATS
        # signature itself - many companies put a marketing/culture hub at their
        # "Karriere"/"Careers" link and only embed the ATS one click deeper, on an
        # "open roles"/"job openings" sub-page. Verified live: Taxfix's own
        # /en/careers/ hub page has zero Ashby references anywhere in its ~370KB of
        # HTML; the real embed only appears on /en/job-openings/, reached via a
        # "See our open roles" link on the hub page itself - a link that
        # CAREER_LINK_PATTERN wouldn't have matched even if this loop had started
        # from the hub page directly.
        for deeper_url in _find_matching_links(JOB_LISTING_LINK_PATTERN, str(response.url), response.text):
            if deeper_url in visited:
                continue
            visited.add(deeper_url)
            try:
                deeper_response = get_with_retry(deeper_url, headers=HEADERS)
            except httpx.HTTPError:
                continue
            found = _scan_page(str(deeper_response.url), deeper_response.text, company["name"])
            if found:
                return found

    # Passive scanning only sees ATS references present in static HTML/embedded
    # JSON - a company whose apply flow constructs the ATS URL entirely client-side
    # (verified live: Celonis's career page never mentions "greenhouse" anywhere,
    # in any fetched page, yet boards-api.greenhouse.io/v1/boards/celonis/jobs is a
    # real 265-job board) is invisible to it. Actively probing each platform's own
    # API with a slug guessed from the company's name/domain catches these -
    # verified live to find real, correctly-matched boards for GetYourGuide,
    # Contentful, Staffbase, and Parloa, none of which reference their ATS
    # anywhere in their own site's content.
    probed = _probe_all_platforms(company)
    if probed:
        return {**probed, "careers_url": None, "match_method": "api_probe"}

    if first_found_career_url:
        return {
            "ats": "custom",
            "identifier": None,
            "careers_url": first_found_career_url,
            "match_method": None,
        }
    return _unresolved()


def _detect_ats_safe(company: dict) -> dict:
    try:
        return _detect_ats(company)
    except Exception:
        logger.exception("ATS detection failed for %s", company["name"])
        return _unresolved()


def resolve_all(companies: list[dict]) -> None:
    def _resolve_one(company: dict) -> None:
        result = _detect_ats_safe(company)
        company["ats"] = result["ats"]
        company["identifier"] = result["identifier"]
        company["careers_url"] = result["careers_url"]
        company["match_method"] = result["match_method"]
        company["resolved_at"] = datetime.now(timezone.utc).isoformat()
        logger.info("%s -> %s", company["name"], result["ats"])

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # list() to force every future to complete (and any exception to surface)
        # before returning - _resolve_one mutates company dicts in place, so its
        # return value itself is unused.
        list(executor.map(_resolve_one, companies))


def _summarize(companies: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for company in companies:
        # "new" (never attempted, ats: null) is kept distinct from the real
        # "unresolved" outcome string - see the UNRESOLVED comment above.
        key = company.get("ats") or "new"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _write_report(companies: list[dict]) -> None:
    total = len(companies)
    counts = _summarize(companies)
    vendor_counts = {k: v for k, v in counts.items() if k not in (UNRESOLVED, "custom", "new")}
    resolved_count = sum(vendor_counts.values())
    custom = [c for c in companies if c.get("ats") == "custom"]
    unresolved = [c for c in companies if c.get("ats") == UNRESOLVED]
    new = [c for c in companies if c.get("ats") is None]

    def _pct(count: int) -> float:
        return (count / total * 100) if total else 0.0

    lines = [
        "# ATS resolution report",
        "",
        f"Total companies: {total}",
        "",
        "## Bucket summary",
        "",
        f"- Resolved (real vendor): {resolved_count} ({_pct(resolved_count):.1f}%)",
        f"- Custom (careers page found, no recognized vendor): {len(custom)} ({_pct(len(custom)):.1f}%)",
        f"- Unresolved (attempted, no careers page found): {len(unresolved)} ({_pct(len(unresolved)):.1f}%)",
        f"- New (never attempted): {len(new)} ({_pct(len(new)):.1f}%)",
        "",
        "## Resolved by vendor",
        "",
    ]
    for vendor, count in sorted(vendor_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {vendor}: {count}")

    lines += ["", "## Unresolved companies (attempted, found nothing)", ""]
    lines += [f"- {c['name']} — {c['url']}" for c in unresolved] or ["(none)"]

    lines += ["", "## Custom (candidate for a future generic scraper)", ""]
    lines += [f"- {c['name']} — {c.get('careers_url') or c['url']}" for c in custom] or ["(none)"]

    lines += ["", "## New (never attempted)", ""]
    lines += [f"- {c['name']} — {c['url']}" for c in new] or ["(none)"]

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("wrote report to %s", REPORT_PATH)


def resolve_pending() -> list[dict]:
    """Resolve every company entry that `is_new_entry()` - never been through
    resolution at all - in place on disk, and return just that subset. Called by
    main.py before each run - a freshly-added companies.yaml entry (name+url only)
    has no `ats`, so `adapters/registry.py`'s
    `ATS_ADAPTERS.get(company.get("ats"))` would silently return None and skip it
    forever without this.

    Deliberately narrower than `needs_resolution()` - an already-attempted
    `null`/`custom` result is not re-fetched here (see `is_new_entry()`'s
    docstring for why); run `python -m tools.resolve_ats` by hand to retry those.
    No-op (returns `[]`, doesn't touch the file) once every company has been
    through resolution at least once, which is the common case on every run after
    a company's first.
    """
    with open(COMPANIES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    companies = data["companies"]
    to_resolve = [c for c in companies if is_new_entry(c)]
    if not to_resolve:
        return []

    logger.info("resolving %d pending company ATS entries", len(to_resolve))
    resolve_all(to_resolve)

    with open(COMPANIES_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True, default_flow_style=False)

    logger.info("pending resolution summary: %s", _summarize(to_resolve))
    _write_report(companies)
    return to_resolve


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-check every company, not just those currently unresolved/custom",
    )
    args = parser.parse_args(argv)

    with open(COMPANIES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    companies = data["companies"]
    to_resolve = companies if args.force else [c for c in companies if needs_resolution(c)]
    logger.info("resolving %d of %d companies (force=%s)", len(to_resolve), len(companies), args.force)

    resolve_all(to_resolve)

    with open(COMPANIES_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True, default_flow_style=False)

    logger.info("ATS resolution summary: %s", _summarize(companies))
    _write_report(companies)


if __name__ == "__main__":
    main()
