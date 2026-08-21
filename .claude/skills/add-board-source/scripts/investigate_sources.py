"""First-pass investigation battery for the remaining priority-2 board sources.

Read-only: fetches each URL once with a real browser User-Agent, plus its
robots.txt, and reports the standard add-board-source-skill step-1 signals so we
don't have to re-derive them by hand per source:

- HTTP status
- JSON-LD presence, and whether any block is schema.org JobPosting specifically
  (parsed properly - handles array-form "@type" and postings nested under @graph,
  not just a flat string match)
- __NEXT_DATA__ / other embedded-JSON-state presence (Next.js or similar SSR
  frameworks that hydrate from a JSON blob in the page)
- RSS/Atom <link rel="alternate"> discovery
- visible body text length (crude SPA-shell heuristic - a near-empty count means
  content is very likely JS-rendered client-side, not in the raw fetch)
- robots.txt: whether "User-agent: *" is disallowed for this URL, and - per
  Claude/Anthropic identity named in its own group - whether that identity is
  allowed (as opposed to only ever falling under the generic "*" rule)

Uses urllib.robotparser.RobotFileParser instead of hand-rolled group-splitting -
that parser folds in group semantics, Allow: overrides, and wildcard fallback
correctly. Two real caveats it does NOT resolve:

1. When a site declares two SEPARATE groups for the exact same agent name
   (verified live on remote_ok.com - an earlier blanket "ClaudeBot: Disallow: /"
   block under a Cloudflare-managed section, and a later, more specific
   "ClaudeBot: Allow: /" block the site's own comment says is meant to override
   it), Python's parser matches whichever group appears FIRST in the file, not
   the more specific/later one a site may clearly intend to be authoritative.
2. CPython's _add_entry() routes a group to default_entry (not rp.entries) if
   "*" appears ANYWHERE in that group's User-agent lines - so a MIXED group like
   "User-agent: *\nUser-agent: ClaudeBot\nDisallow: /paywall" is swallowed whole
   into the wildcard entry. ClaudeBot was named explicitly right there, but
   rp.entries never sees it, so robots_claude_mentioned comes back False for it.

Treat every robots_claude_* field as a first-pass signal, not a final verdict -
read the raw robots.txt by hand before committing to a UA choice on anything
this flags as ambiguous or ambiguous-looking.

Does not test search params, pagination, or find description selectors - those
still need a per-source follow-up once a source clears this first pass.

Fetches with a spoofed Chrome UA, not a real Claude bot identity - the robots.txt
check here is informational (deciding whether it's OK to proceed with building an
adapter at all), not something the fetch request itself is honoring. Deliberate,
not an oversight: an adapter actually built against a source with an explicit
Claude allowance (like remote_ok) should identify honestly with that UA instead.
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
import yaml

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
TIMEOUT = 15.0
MAX_WORKERS = 5
# Current per Anthropic's docs (ClaudeBot, Claude-User, Claude-SearchBot) plus the
# older, now-deprecated identities still worth checking in case a site's robots.txt
# has a stale rule referencing them.
CLAUDE_UA_NAMES = {"claudebot", "claude-user", "claude-searchbot", "anthropic-ai", "claude-web"}


@dataclass
class SourceReport:
    id: str
    url: str
    http_status: int | str
    visible_text_len: int = 0
    has_ldjson: bool = False
    has_jobposting_ldjson: bool = False
    has_next_data: bool = False
    rss_links: list[str] = field(default_factory=list)
    robots_status: int | str = ""
    robots_wildcard_disallowed: bool = False
    robots_claude_mentioned: bool = False
    # Per-identity, not one collapsed bool - ClaudeBot (training) and Claude-User
    # (on-demand fetch) commonly get different rules on the same site, and an
    # adapter needs to know which specific identity is allowed to identify
    # honestly with it - see the module docstring's closing paragraph.
    robots_claude_status: dict[str, bool] = field(default_factory=dict)
    error: str = ""


def _visible_text_len(html: str) -> int:
    body_match = re.search(r"<body[^>]*>(.*)</body>", html, re.DOTALL | re.IGNORECASE)
    body = body_match.group(1) if body_match else html
    text = re.sub(r"<[^>]+>", " ", body)
    return len(re.sub(r"\s+", " ", text).strip())


def _ldjson_blocks(html: str) -> list[str]:
    return re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )


def _has_jobposting(blocks: list[str]) -> bool:
    for b in blocks:
        try:
            data = json.loads(b)
        except json.JSONDecodeError:
            continue

        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            graph = data.get("@graph")
            # @graph is usually a list, but treat a lone dict the same way rather
            # than let `for item in items` silently iterate its string keys instead
            # of the object itself.
            items = graph if isinstance(graph, list) else ([graph] if isinstance(graph, dict) else [data])
        else:
            # Valid JSON that isn't an object/array (a bare string/number) - not
            # something schema.org JobPosting could ever be.
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            t = item.get("@type", "")
            types = t if isinstance(t, list) else [t]
            if "JobPosting" in types:
                return True
    return False


def _rss_links(html: str) -> list[str]:
    return re.findall(
        r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )


def _check_robots(client: httpx.Client, base_url: str, report: SourceReport) -> None:
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        resp = client.get(robots_url, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        report.robots_status = f"ERR:{exc.__class__.__name__}"
        return
    report.robots_status = resp.status_code
    if resp.status_code != 200:
        return

    rp = RobotFileParser()
    rp.parse(resp.text.splitlines())
    report.robots_wildcard_disallowed = not rp.can_fetch("*", base_url)

    # rp.entries holds only groups whose User-agent lines are ALL non-"*" -
    # CPython's _add_entry() routes a group to default_entry instead the moment
    # "*" appears anywhere in it, even alongside an explicit ClaudeBot mention
    # (see the module docstring's caveat #2) - so this misses that mixed-group
    # case, but does correctly catch a group named for Claude specifically.
    mentioned_names = [
        name for entry in rp.entries for name in CLAUDE_UA_NAMES if entry.applies_to(name)
    ]
    report.robots_claude_mentioned = bool(mentioned_names)
    report.robots_claude_status = {name: rp.can_fetch(name, base_url) for name in mentioned_names}


def investigate(client: httpx.Client, source_id: str, url: str) -> SourceReport:
    report = SourceReport(id=source_id, url=url, http_status="")
    try:
        resp = client.get(url, timeout=TIMEOUT, follow_redirects=True)
    except httpx.HTTPError as exc:
        report.http_status = f"ERR:{exc.__class__.__name__}"
        report.error = str(exc)
        _check_robots(client, url, report)
        return report

    report.http_status = resp.status_code
    html = resp.text
    report.visible_text_len = _visible_text_len(html)
    blocks = _ldjson_blocks(html)
    report.has_ldjson = bool(blocks)
    report.has_jobposting_ldjson = _has_jobposting(blocks)
    report.has_next_data = "__NEXT_DATA__" in html
    report.rss_links = _rss_links(html)

    _check_robots(client, url, report)
    return report


def _print_report(r: SourceReport) -> None:
    print(f"=== {r.id} ===")
    print(f"  url: {r.url}")
    print(f"  http_status: {r.http_status}")
    if r.error:
        print(f"  error: {r.error}")
    print(f"  visible_text_len: {r.visible_text_len}")
    print(f"  has_ldjson: {r.has_ldjson}  has_jobposting_ldjson: {r.has_jobposting_ldjson}")
    print(f"  has_next_data: {r.has_next_data}")
    print(f"  rss_links: {r.rss_links}")
    print(
        f"  robots: status={r.robots_status} "
        f"wildcard_disallowed_for_this_url={r.robots_wildcard_disallowed} "
        f"claude_mentioned={r.robots_claude_mentioned} "
        f"claude_status={r.robots_claude_status}"
    )
    print()


# adapter: values meaning "not yet resolved" - see sources.yaml's own
# meta.adapter_legend for what each means. Kept here only as the no-args default
# selector below; sources.yaml's legend is still the source of truth for the set.
UNRESOLVED_ADAPTER_VALUES = {
    "json_api_todo",
    "html_scrape_todo",
    "js_rendered_todo",
    "anti_bot_avoid",
    "broken_todo",
    "ambiguous_todo",
}


def main(source_ids: list[str] | None) -> None:
    with open("config/sources.yaml") as f:
        sources = yaml.safe_load(f)["sources"]
    by_id = {s["id"]: s for s in sources}

    if source_ids is None:
        # No args - re-derive "what's left to investigate" from sources.yaml itself
        # every time, rather than a hardcoded list that's accurate only the moment
        # it's written and silently stale the moment any of those sources gets
        # resolved (built or explicitly skipped).
        source_ids = sorted(s["id"] for s in sources if s.get("adapter") in UNRESOLVED_ADAPTER_VALUES)
        print(f"(no ids given - defaulting to all {len(source_ids)} still-unresolved sources)\n")

    known_ids = [sid for sid in source_ids if sid in by_id]
    for sid in source_ids:
        if sid not in by_id:
            print(f"{sid}: NOT FOUND in sources.yaml")

    with httpx.Client(headers={"User-Agent": UA}) as client, ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as pool:
        futures = [pool.submit(investigate, client, sid, by_id[sid]["url"]) for sid in known_ids]
        for future in futures:
            _print_report(future.result())


if __name__ == "__main__":
    main(sys.argv[1:] or None)
