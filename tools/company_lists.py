"""Keep config/companies.yaml to companies whose jobs can actually be fetched, and
everything else in config/unresolved_companies.yaml - with a `reason` saying why.

A company belongs in companies.yaml when both hold:
- its `ats` has an adapter in adapters/registry.py's ATS_ADAPTERS, and
- that ATS still answers for its identifier (`endpoint_alive()` - a board with zero
  open jobs is alive; a 404 for the identifier itself is not).

Everything else - `custom`, `unresolved`, a vendor with no adapter (rexx,
teamtailor...), or a dead endpoint (e.g. a Personio careers page the company switched
off - 59 of them on 2026-10-23) - lives in unresolved_companies.yaml, so
fetch_from_companies() never spends a request on it. `rebalance()` moves entries
between the two files in both directions; tools/resolve_ats.py calls it after every
resolution, and the weekly workflow re-runs the unresolved file so a company that
moves to a supported ATS (or switches its page back on) comes back by itself.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

from adapters.ats.personio_feed import FEED_URL_TEMPLATE as PERSONIO_FEED
from adapters.ats.personio_feed import SEARCH_URL_TEMPLATE as PERSONIO_SEARCH
from adapters.ats.recruitee_api import _api_url as recruitee_api_url
from adapters.registry import ATS_ADAPTERS
from http_client import get_with_retry, post_with_retry

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "config"
COMPANIES_PATH = CONFIG_DIR / "companies.yaml"
UNRESOLVED_PATH = CONFIG_DIR / "unresolved_companies.yaml"

UNRESOLVED_HEADER = """\
# Companies whose jobs can't be fetched right now - each with a `reason`. Kept out of
# companies.yaml so fetch_from_companies() never spends a request on them, and so a
# new company batch can be deduped against known dead ends. Moved here and back
# automatically by tools/company_lists.py:rebalance() (called from
# tools/resolve_ats.py); the weekly workflow re-runs this whole file, so a company
# that moves to a supported ATS comes back to companies.yaml by itself.
"""

# What the ATS answers for an identifier that doesn't exist (verified live
# 2026-10-23 with a made-up slug): 404 everywhere, except Workday (422 for an unknown
# tenant/site) and BambooHR (302 away from the <slug>.bamboohr.com host).
# SmartRecruiters answers 200 + an empty list for *any* slug, so a dead one can't be
# told apart from a live one with no openings - treated as alive.
DEAD_STATUS = {404, 410, 422}


def _status(method: str, url: str, **kwargs) -> int | None:
    """HTTP status for url, or None when the request itself failed (timeout, DNS,
    5xx after the retry) - "couldn't tell", never "dead"."""
    try:
        request = post_with_retry if method == "POST" else get_with_retry
        return request(url, **kwargs).status_code
    except httpx.HTTPStatusError as exc:
        return exc.response.status_code
    except httpx.HTTPError:
        return None


def _alive_from(status: int | None) -> bool | None:
    if status is None or status >= 500 or status == 429:
        return None
    return status not in DEAD_STATUS and status < 400


def endpoint_alive(company: dict) -> bool | None:
    """True/False when the ATS clearly answered for this identifier, None when it
    couldn't be told (network error, 5xx, rate limit, or a vendor with no reliable
    signal) - callers must leave a None entry where it is."""
    ats = company.get("ats")
    ident = company.get("identifier")
    if not ident:
        return None
    if ats == "greenhouse":
        return _alive_from(_status("GET", f"https://boards-api.greenhouse.io/v1/boards/{ident}/jobs"))
    if ats == "lever":
        url = f"https://api.lever.co/v0/postings/{ident}"
        return _alive_from(_status("GET", url, params={"mode": "json"}))
    if ats == "ashby":
        return _alive_from(_status("GET", f"https://api.ashbyhq.com/posting-api/job-board/{ident}"))
    if ats == "workable":
        return _alive_from(_status("GET", f"https://apply.workable.com/api/v1/widget/accounts/{ident}"))
    if ats == "recruitee":
        return _alive_from(_status("GET", recruitee_api_url(ident)))
    if ats == "softgarden":
        return _alive_from(_status("GET", f"https://{ident}.softgarden.io/"))
    if ats == "onlyfy":
        return _alive_from(_status("GET", f"https://{ident}.onlyfy.jobs/en"))
    if ats == "join":
        return _alive_from(_status("GET", f"https://join.com/companies/{ident}"))
    if ats == "personio":
        # Either the XML feed or search.json is enough - personio_feed.py falls back.
        feed = _alive_from(_status("GET", PERSONIO_FEED.format(identifier=ident)))
        if feed:
            return True
        search = _alive_from(_status("GET", PERSONIO_SEARCH.format(identifier=ident)))
        return True if search else (None if None in (feed, search) else False)
    if ats == "bamboohr":
        try:
            response = get_with_retry(f"https://{ident}.bamboohr.com/careers/list")
        except httpx.HTTPStatusError as exc:
            return _alive_from(exc.response.status_code)
        except httpx.HTTPError:
            return None
        return urlparse(str(response.url)).netloc.lower() == f"{ident}.bamboohr.com".lower()
    if ats == "workday" and isinstance(ident, dict):
        host = f"https://{ident['tenant']}.{ident['wd_host']}.myworkdayjobs.com"
        url = f"{host}/wday/cxs/{ident['tenant']}/{ident['site']}/jobs"
        body = {"limit": 1, "offset": 0, "searchText": "", "appliedFacets": {}}
        return _alive_from(_status("POST", url, json=body))
    return None  # smartrecruiters (see DEAD_STATUS comment) or anything new


def reason_for(company: dict, alive: bool | None = None) -> str:
    """Why a company can't be fetched - stored as `reason` in the unresolved file."""
    ats = company.get("ats")
    if company.get("excluded"):
        return company.get("reason") or "excluded by hand"
    if ats == "unresolved":
        return company.get("reason") or "no careers page found"
    if ats == "custom":
        return company.get("reason") or "careers page has no supported ATS"
    if ats not in ATS_ADAPTERS:
        return f"{ats}: no adapter yet"
    if alive is False:
        return f"{ats} endpoint for '{company.get('identifier')}' is gone (404)"
    return company.get("reason") or "unknown"


def is_fetchable(company: dict) -> bool:
    # `excluded: true` = removed by hand (e.g. not a fit) - kept in the unresolved
    # file so a future batch still dedupes against it, but never fetched again even
    # though its ATS may be perfectly alive.
    if company.get("excluded"):
        return False
    return company.get("ats") in ATS_ADAPTERS and bool(company.get("identifier"))


def rebalance(
    companies: list[dict], unresolved: list[dict], *, check_live: list[dict] | None = None
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Split both lists by is_fetchable() + endpoint_alive(). Returns
    (companies, unresolved, moved_in, moved_out).

    Liveness is probed for every unresolved entry with a supported ATS (it may have
    come back) and for the companies.yaml entries in `check_live` (pass all of them
    for the weekly check, only freshly resolved ones otherwise). A None liveness
    answer never moves anything.
    """
    check_ids = {id(c) for c in check_live or []}
    keep, moved_out = [], []
    for c in companies:
        if not is_fetchable(c):
            moved_out.append({**c, "reason": reason_for(c)})
            continue
        if id(c) in check_ids and endpoint_alive(c) is False:
            moved_out.append({**c, "reason": reason_for(c, alive=False)})
            continue
        keep.append(c)

    stay, moved_in = [], []
    for c in unresolved:
        if is_fetchable(c) and endpoint_alive(c) is True:
            moved_in.append({k: v for k, v in c.items() if k != "reason"})
        else:
            # A supported-ATS entry that's still here is one whose endpoint is gone.
            alive = False if is_fetchable(c) else None
            stay.append({**c, "reason": c.get("reason") or reason_for(c, alive=alive)})

    for c in moved_out:
        logger.info("-> unresolved_companies.yaml: %s (%s)", c["name"], c["reason"])
    for c in moved_in:
        logger.info("-> companies.yaml: %s (%s:%s)", c["name"], c["ats"], c.get("identifier"))
    return keep + moved_in, stay + moved_out, moved_in, moved_out


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("companies") or []


def save(path: Path, companies: list[dict], header: str = "") -> None:
    body = yaml.safe_dump(
        {"companies": companies}, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    path.write_text(header + body, encoding="utf-8")
