---
name: add-board-source
description: Add a real fetch_jobs adapter for a job board source in config/sources.yaml, replacing its _todo classification placeholder. Use when wiring up one of the board sources (e.g. building out Phase 5 of job_search_agent_plan.md), or fixing an adapter that broke.
---

# Add a board source adapter

Every not-yet-built source in `config/sources.yaml` carries an `adapter:` value ending
in `_todo` (`json_api_todo`, `html_scrape_todo`, `js_rendered_todo`, `broken_todo`,
`ambiguous_todo`) or `anti_bot_avoid` — see `meta.adapter_legend` in that file for what
each means. Treat it as a hint, not a guarantee: it's a single automated,
unauthenticated GET with no pagination/search-flow/login-wall check — see
`docs/lessons/adapters.md` (the `_todo`/LinkedIn section) for why that already
produced one real miscall, and don't skip step 1 below just because a classification
already exists.

Current adapter-build status (count, phase, which sources are done) is tracked in
`CLAUDE.md`'s Status section, not here. Next candidates: sources still carrying a
`_todo`/`anti_bot_avoid` classification in `config/sources.yaml` (see
`job_search_agent_source_classification` memory for the full pass).

## 1. Find out what the source's URL actually serves

Fetch it yourself with a real browser user-agent and read the raw HTML:

```bash
curl -sL -A "Mozilla/5.0" "<source url>" -o /tmp/page.html
```

- **Server-rendered HTML** — job data is actually in the response; a normal
  `requests`/`BeautifulSoup` scrape works.
- **Client-rendered SPA** — a near-empty shell (`<div id="root">`, a `main.*.js`
  bundle, a placeholder like `window.__detailedJob="JOB_PLACEHOLDER"`). Don't write a
  selector parser against this and assume it'll work later — see step 5.

Also check for a clean Markdown version built for machine consumption before writing
any HTML selectors — look for `<link rel="alternate" type="text/markdown">` in the
page head, or try appending `.md` to the URL (`wearedevelopers_jobs` has this at
`/jobs.md?country=DE&q=<term>`, documented at `/agents.md`). Cheaper to build and
maintain than a scraper when it exists.

**Check `robots.txt` before deciding what User-Agent to send** — some sites carve out
an explicit exception for named AI-agent bots. See `docs/lessons/adapters.md#robots-txt-ai-bots`
for why, and `adapters/boards/xing_jobs.py`'s `HEADERS` for the working example.
Surface the choice to the user (AskUserQuestion) rather than picking silently — it's a
real policy decision, not just an implementation detail.

## 2. If it's server-rendered: verify field-by-field against a live fetch

Pull a real page/response and inspect the *actual* markup or JSON before writing
selectors — don't guess class or field names:

```bash
curl -s "<api or page url>" | python3 -m json.tool | head -80   # JSON API
# or, for HTML:
python3 -c "
from bs4 import BeautifulSoup
soup = BeautifulSoup(open('/tmp/page.html'), 'html.parser')
print(soup.select_one('<candidate selector>').prettify())
"
```

This is how the Arbeitnow card selectors were found — by dumping one real job card's
full markup and reading it, not by inspecting minified source blindly.

**Check for a `<script type="application/ld+json">` `schema.org JobPosting` block, or
(on a Next.js site) a `__NEXT_DATA__`/RSC-streamed JSON blob, before writing CSS
selectors.** See `docs/lessons/adapters.md#json-ld` for why; reference
implementations: `xing_jobs.py`, `get_in_it.py`, `instaffo.py`, `bundesagentur.py`.

## 3. If a documented "API" exists, verify it actually supports what you need — don't trust the docs

**Confirm a search/query param actually changes the result set before trusting it** —
the same applies to a site's own visible search box, not just a documented external
API. See `docs/lessons/adapters.md#fake-search` for why (Arbeitnow, `devjobs`,
`testdevjobs`, and `builtin` each had this in a different shape).

Test a handful of `title_match_terms` entries as both a query param and a URL-path
slug, with and without the param, and diff the responses. If it turns out to be a
fixed taxonomy/listing rather than real search, don't read `search_terms` in the
adapter at all — crawl the one/few working listing(s) in full (paginated) and lean on
`filter_by_title` downstream, same approach as GermanTechJobs' RSS.

## 4. If the "real" API doesn't support search, look for the one the site's own UI uses

Fetch the site's search page and grep the HTML for `/api/` references — the
frontend's own fetch calls are often visible in an inline `<script>` block, even
before minification strips names, or in the bundled JS:

```bash
curl -sL -A "Mozilla/5.0" "<site>/?search=<term>" -o /tmp/search.html
grep -o '/api/[a-zA-Z_-]*' /tmp/search.html | sort -u
python3 -c "
content = open('/tmp/search.html').read()
i = content.find('/api/jobs')  # or whatever turned up above
print(content[i-150:i+300])
"
```

This is how Arbeitnow's real search endpoint (`/api/jobs`, undocumented,
HTML-fragment response) was found. It's a real tradeoff: more fragile than a
documented API, may break without notice, and may return HTML fragments requiring a
parser instead of clean JSON. **Surface this tradeoff to the user explicitly
(AskUserQuestion or equivalent) before committing to it** — it affects
`requirements.txt` and how much you trust the source going forward.

## 5. If it's a JS-rendered SPA with no usable API: check for an RSS/feed alternative before reaching for a browser

Look for `<link rel="alternate" type="application/rss+xml">` in the page head, or try
`/rss`, `/feed` on the root domain. An RSS feed avoids a Playwright dependency
(heavier install + CI cost — the plan explicitly gates Playwright on "only if a
source requires JS rendering").

Tradeoff to flag to the user: RSS feeds are often *global*, unfiltered by the
category/location the configured URL was scoped to (GermanTechJobs' RSS is all 1183
jobs sitewide, not just the Tester/Munich subset the URL implied) — the downstream
`title_match_terms` filter has to do more work, and structured fields like location
may simply not exist in the feed (see the `CLAUDE.md` caveat on
`NormalizedJob.location`). Ask the user rather than deciding solo — it changes what
data is actually available for later location/language filtering.

## 6. Write the adapter

Create `adapters/boards/<adapter_name>.py` implementing the contract documented in
`CLAUDE.md` under "Adapter contract" — `fetch_jobs(source_config: dict) -> list[NormalizedJob]`.
Points that matter in practice:

- If the source needs search queries (like Arbeitnow), read
  `source_config["search_terms"]` — don't hardcode terms. It's injected by
  `agents/_common.py` from `keywords.yaml`'s `title_match_terms`.
- Use `http_client.py`'s `get_with_retry()`/`post_with_retry()` for every HTTP call,
  don't hand-roll a new retry loop — see `CLAUDE.md`'s adapter-contract section for
  why there are two layers (per-request retry vs. per-source isolation). You still
  need to catch `httpx.HTTPError` per-request yourself and decide whether to skip
  that one request/term and continue (most adapters should) or let it propagate.
- If the source's own rate limits are tighter than the single retry can smooth over,
  space out requests yourself on top of it (`arbeitnow_api.py`'s
  `REQUEST_DELAY_SECONDS`). Test empirically: `arbeitnow_api.py` originally fired all
  23 search-term requests back to back and got rate-limited after ~11;
  `sleep(1.5)` between requests was verified sufficient by testing directly with
  `curl`.
- Every `NormalizedJob` field must be set even if the source has no real value for
  it — use an honest placeholder (e.g. `location="Germany"`) rather than guessing.
  Note in a code comment *why* the field is a placeholder, since it directly limits
  what `pipeline/location.py` and `pipeline/filters.py` can do with jobs from this
  source downstream.
- **Clickout/aggregator sources: don't use the raw `href` as `NormalizedJob.url`.**
  See `docs/lessons/adapters.md#stable-ids` for why (a freshly-signed clickout link
  broke both in-adapter and persistent SQLite dedup for `englishjobsde`). Use a
  stable per-card identifier instead, and test that the canonical URL built from it
  still redirects correctly.
- **`get_text()` spacing gotcha when a field has inline tags around individual
  words** (e.g. search-term highlighting). See
  `docs/lessons/adapters.md#get-text-spacing` for why — use `get_text()` with no
  arguments, then a single `re.sub(r"\s+", " ", text).strip()` pass.

## 7. Make sure `description` actually gets populated — not just `location`

An empty `description` silently defaults to English in `classify_language.py` — see
`CLAUDE.md`'s description-required note for why this matters and how to bound the
extra request volume (title-matched subset only, not every raw result).

If the listing/search response has no real description, check whether the
individual job's **detail/permalink page** does (same method as step 1 — it can
render differently from the listing page). If it does:

- **Don't fetch every job's detail page unconditionally.** Narrow first to jobs
  whose title already matches `source_config["search_terms"]` (the same substring
  check `filter_by_title` applies downstream anyway) — `arbeitnow_api.py` does this,
  cutting ~150 candidates down to ~50 real requests. Jobs that don't survive this
  narrowing keep `description=""`, which is harmless — they get filtered out before
  ever reaching the language classifier.
- **Apply the same rate-limit spacing/backoff as the listing fetch** to the
  detail-page requests too — don't assume a different endpoint on the same site has
  different or no limits.
- **Store raw inner HTML, not `.get_text()`-flattened plain text**, if that's the
  convention other sources use (check `adapters/boards/html_scrape.py` /
  `config/language_rules.yaml`). See `docs/lessons/classification.md#clause-bounded-gaps`
  for why — flattening silently removes the `<` tag-boundary guard
  `classify_language.py` relies on to stop a match from bleeding into the next
  bullet point.

Test this in two separate steps — a working fetch and a working classification can
fail independently:

```python
# 1. Did the fetch actually get descriptions?
with_desc = [j for j in jobs if j.description]
print(f"{len(with_desc)}/{len(jobs)} have a non-empty description")

# 2. Does the classifier actually produce non-English results from this source?
german, english = classify_language.split_by_language(jobs)
print(f"german={len(german)} english={len(english)}")
```

If (2) stays at 0 German even once (1) confirms descriptions are populated, the
classifier's patterns themselves may not generalize to this source's phrasing —
happened once already: Arbeitnow's real descriptions surfaced "Deutschkenntnisse
mindestens auf B2-Niveau," missed because `config/language_rules.yaml`'s CEFR
pattern only listed C1/C2. Check `pipeline/*` findings against the *other* sources
too before assuming a gap is source-specific.

## 8. Register the adapter

Add it to the `ADAPTERS` dict in `agents/_common.py`, keyed by the adapter name
string that will go in `sources.yaml`:

```python
ADAPTERS = {
    "arbeitnow_api": arbeitnow_api.fetch_jobs,
    "html_scrape": html_scrape.fetch_jobs,
    "<new_adapter_name>": <new_module>.fetch_jobs,
}
```

## 9. Update `config/sources.yaml`

- Change the source's `adapter:` field from its `_todo`/`anti_bot_avoid`
  classification to the real adapter name (the one now registered in
  `agents/_common.py`'s `ADAPTERS`).
- Add any adapter-specific fields it needs (e.g. `rss_url:`, `api_url:`).
- Update `notes:` to explain what fetch mechanism is actually used and why, in
  enough detail that the next person doesn't have to re-derive it (see the
  `germantechjobs_testing_germany` and `arbeitnow_qa_jobs` entries for the pattern).

## 10. Wire it into the agent(s) that should use it

Add the source's `id` to `SOURCE_IDS` in `agents/munich_local.py` and/or
`agents/germany_remote.py` (or a new agent module, same shape). If a new dependency
was needed (e.g. `beautifulsoup4`), add it to `requirements.txt` and
`.venv/bin/pip install` it locally before testing.

## 11. Test before sending anything real

```bash
.venv/bin/python main.py --dry-run
```

Check: the fetched-count log line looks sane (not 0, not obviously wrong), the
printed titles actually look like real candidate jobs, and — if this source produces
`location` or `description` text that `pipeline/location.py` will classify —
spot-check a few matched jobs against the source's real page/feed content directly.
A bare substring/regex match against free-text prose is a known false-positive trap
(see `docs/lessons/classification.md#unambiguous-phrases`) — verify a new source's
text doesn't trip the same kind of false positive before trusting it.

If the new source is *richer* than the ones already built (a real structured
`location` field, substantial free-text company boilerplate, or English-first
phrasing), specifically re-check these against its real fetched text. Each is
already a `CLAUDE.md` checklist item with the full story linked — don't assume the
existing patterns/thresholds generalize without checking:

- `docs/lessons/classification.md#is-munich-fallback` — trust a real structured
  `location` exclusively once one exists.
- `docs/lessons/classification.md#english-german-signals` — German-requirement
  signals can be phrased entirely in English.
- `docs/lessons/classification.md#whole-description-german` — a posting can require
  German with no explicit statement at all.
- `docs/lessons/adapters.md#country-check` — verify the country field if the source
  isn't Germany-only by construction.

Never run without `--dry-run` (i.e. actually send to Telegram) without the user's
explicit go-ahead first.
