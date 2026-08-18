---
name: add-board-source
description: Add a real fetch_jobs adapter for a job board source in config/sources.yaml, replacing its _todo classification placeholder. Use when wiring up one of the board sources (e.g. building out Phase 5 of job_search_agent_plan.md), or fixing an adapter that broke.
---

# Add a board source adapter

Every not-yet-built source in `config/sources.yaml` carries an `adapter:` value ending
in `_todo` (`json_api_todo`, `html_scrape_todo`, `js_rendered_todo`, `broken_todo`,
`ambiguous_todo`) or `anti_bot_avoid` — see `meta.adapter_legend` in that file for what
each means. These come from a 2026-08-17 automated single-page-fetch classification
pass across all sources, not hand verification — a useful hint for what kind of
investigation to expect, but not a substitute for step 1 below. This skill is the
process actually used to turn `arbeitnow_qa_jobs`, `germantechjobs_testing_germany`,
`stepstone_germany`, `devjobs_germany_qa_engineer`, `testdevjobs_remote_germany`,
`wearedevelopers_jobs`, `englishjobsde`, `built_in_qa_germany`, `xing_jobs`,
`get_in_it`, `instaffo_qa_engineer`, and `bundesagentur_für_arbeit_jobsuche` into
working adapters (in that order — see `job_search_agent_phase5` memory for what each
one turned up) — follow the same steps for the next one. **All 11 priority-1 sources
are done as of 2026-08-18** (Phase 5 complete); the next candidates are the
lower-priority sources still carrying a `_todo`/`anti_bot_avoid` classification in
`config/sources.yaml` (see `job_search_agent_source_classification` memory).

## 1. Find out what the source's URL actually serves

Check the source's current `adapter:` classification first — `html_scrape_todo` means
the automated pass found real visible text and job-related keywords on a plain fetch
(a good sign, not a guarantee); `js_rendered_todo` means it found an SPA shell;
`anti_bot_avoid` means it was blocked (or, like LinkedIn, returns something that looks
like content but is actually just cookie-consent boilerplate — the automated pass can
be fooled by this, which is exactly why LinkedIn needed a manual override). Don't skip
the manual check just because a classification already exists — it was a single
unauthenticated GET with no pagination/search-flow/login-wall verification.

Fetch it yourself with a real browser user-agent and read the raw HTML:

```bash
curl -sL -A "Mozilla/5.0" "<source url>" -o /tmp/page.html
```

Two outcomes seen so far, both real:

- **Server-rendered HTML** — the job data is actually in the response. A normal
  `requests`/`BeautifulSoup` scrape works. This is the "true" `html_scrape` case.
- **Client-rendered SPA** — the response is a near-empty shell (`<div id="root">`,
  a `main.*.js` bundle, `window.__detailedJob="JOB_PLACEHOLDER"` and similar). This
  happened with GermanTechJobs. A plain scrape returns nothing; don't write a
  BeautifulSoup parser against this and assume it'll work later.

Also worth a quick check before writing any HTML selectors: some sites publish a
clean Markdown version of every page specifically for machine/agent consumption
(look for `<link rel="alternate" type="text/markdown">` in the page head, or try
appending `.md` to the URL). `wearedevelopers_jobs` has exactly this
(`/jobs.md?country=DE&q=<term>`, documented at `/agents.md`) — real working
keyword search, clean structured fields, no HTML parsing needed at all. Much cheaper
to build and maintain than a BeautifulSoup scraper when it exists.

**Check the source's `robots.txt` too, before deciding what User-Agent to send.** Most
sites just have one blanket `User-agent: *` block, but some carve out an explicit
exception for named AI-agent bots: XING's disallows `/jobs/search` generally but has a
separate block explicitly *allowing* it for `ClaudeBot`/`Claude-User`/`GPTBot`/
`PerplexityBot`/etc. — a deliberate site-level policy for exactly this kind of use
case. If a source has this, identifying honestly with the matching bot User-Agent (see
`adapters/boards/xing_jobs.py`'s `HEADERS`) is both more compliant and more honest than
defaulting to a generic browser UA against a path the site disallows for anonymous
scrapers. Surface this choice to the user (AskUserQuestion) rather than picking
silently — it changes what the adapter honestly claims to be.

## 2. If it's server-rendered: verify field-by-field against a live fetch

Pull a real page/response and inspect the *actual* markup or JSON before writing
selectors — don't guess class names or field names.

```bash
curl -s "<api or page url>" | python3 -m json.tool | head -80   # JSON API
# or, for HTML:
python3 -c "
from bs4 import BeautifulSoup
soup = BeautifulSoup(open('/tmp/page.html'), 'html.parser')
print(soup.select_one('<candidate selector>').prettify())
"
```

This is how the Arbeitnow card selectors (`h3[itemprop="title"] a`,
`a[itemprop="hiringOrganization"]`, `span.text-gray-600` for location) were found —
by dumping one real job card's full markup and reading it, not by inspecting
minified source blindly.

**Before writing CSS selectors, check for a `<script type="application/ld+json">`
`schema.org JobPosting` block, or (on a Next.js site) a `__NEXT_DATA__`/RSC-streamed
JSON blob.** `xing_jobs`, `get_in_it`, `instaffo`, and `bundesagentur` all turned out
to have one of these on their detail pages — a single `json.loads()` gives clean,
structured `title`/`hiringOrganization`/`jobLocation`/`description` fields (often
including a real `address.addressCountry`, useful for the country check in step 11)
directly, no selector-guessing and far more robust to the site's next CSS refactor.
Check for this before falling back to BeautifulSoup selectors.

## 3. If a documented "API" exists, verify it actually supports what you need — don't trust the docs

Arbeitnow's public `job-board-api` looked right (JSON, no auth) but testing showed
`?search=` and `?tags=` were silently ignored — it only returns the newest ~175 jobs,
recency-sorted, no filtering. Confirmed by requesting with and without the params and
diffing the response. Don't assume a documented endpoint does what its name implies;
hit it with the filter you need and check the response actually changed.

**This applies just as much to a site's own visible search box, not just a documented
external API** — it happened three separate times (`devjobs`, `testdevjobs`,
`builtin`): a `?q=`/`?search=` param that's silently ignored (identical result set
with or without it — same test as above, diff the response), and/or the site only has
a small *fixed taxonomy* of working category slugs behind a search-looking URL, not
real free-text search (Built In's `/search/qa` was the only populated category out of
18 tested `title_match_terms` slugs — everything else either 404'd into an unrelated
generic "Top Software Engineer Jobs" fallback or returned zero results). Test a
handful of `title_match_terms` entries as both a query param and a URL-path slug
before assuming either works generally. If it turns out to be a fixed
taxonomy/listing rather than real search, don't read `search_terms` at all in the
adapter — crawl the one/few working listing(s) in full instead (paginated) and lean
on `filter_by_title` downstream, same approach as GermanTechJobs' RSS.

## 4. If the "real" API doesn't support search, look for the one the site's own UI uses

Fetch the site's search page and grep the HTML for `/api/` references — the frontend's
own fetch calls are often visible in an inline `<script>` block even before minification
strips names, or in the bundled JS:

```bash
curl -sL -A "Mozilla/5.0" "<site>/?search=<term>" -o /tmp/search.html
grep -o '/api/[a-zA-Z_-]*' /tmp/search.html | sort -u
python3 -c "
content = open('/tmp/search.html').read()
i = content.find('/api/jobs')  # or whatever turned up above
print(content[i-150:i+300])
"
```

This is how Arbeitnow's real search endpoint (`/api/jobs`, undocumented, HTML-fragment
response, used by the site's own search box) was found. It's a real tradeoff: more
fragile than a documented API, may break without notice, and here also returns HTML
fragments requiring a parser instead of clean JSON. **Surface this tradeoff to the user
explicitly (AskUserQuestion or equivalent) before committing to it** — it affects
`requirements.txt` and how much you trust the source going forward. Don't silently
adopt an undocumented endpoint.

## 5. If it's a JS-rendered SPA with no usable API: check for an RSS/feed alternative before reaching for a browser

Look for `<link rel="alternate" type="application/rss+xml">` in the page head, or try
`/rss`, `/feed` on the root domain. An RSS feed avoids a Playwright dependency (heavier
install + CI cost — the plan explicitly gates Playwright on "only if a source requires
JS rendering"). Tradeoff to flag to the user: RSS feeds are often *global*, unfiltered
by the category/location the configured URL was scoped to (GermanTechJobs' RSS is all
1183 jobs sitewide, not just the Tester/Munich subset the URL implied) — the downstream
`title_match_terms` filter has to do more work, and structured fields like location may
simply not exist in the feed (see the CLAUDE.md caveat on `NormalizedJob.location`).
This is also a call worth asking the user about rather than deciding solo, since it
changes what data is actually available for later location/language filtering.

## 6. Write the adapter

Create `adapters/boards/<adapter_name>.py` implementing the contract documented in
`CLAUDE.md` under "Adapter contract" — `fetch_jobs(source_config: dict) -> list[NormalizedJob]`.
Points that matter in practice:

- If the source needs search queries (like Arbeitnow), read `source_config["search_terms"]`
  — don't hardcode terms. It's injected by `agents/_common.py` from
  `keywords.yaml`'s `title_match_terms`.
- **Use `http_client.py`'s `get_with_retry()` for every HTTP call, don't hand-roll a
  new retry loop.** It's the shared retry-after-backoff helper (one retry on 429/5xx)
  used by every adapter and the Telegram notifier — see `CLAUDE.md`'s "Failure handling
  and retries" section. It handles the *retry*; you still need to catch
  `httpx.HTTPError` around each call yourself and decide whether to skip that one
  request/term and continue (most adapters should) or let the exception propagate and
  fail the whole `fetch_jobs()` call (only if partial results genuinely aren't useful).
- If the source's own rate limits are tighter than `get_with_retry()`'s single retry
  can smooth over, space out requests yourself on top of it (`arbeitnow_api.py`'s
  `REQUEST_DELAY_SECONDS`). Test empirically how aggressive you can be —
  `arbeitnow_api.py` originally fired all 23 search-term requests back to back and got
  rate-limited after ~11; `sleep(1.5)` between requests was verified sufficient by
  testing directly with `curl` (see job_search_agent_phase2 memory).
- Every `NormalizedJob` field must be set even if the source has no real value for it —
  use an honest placeholder (e.g. `location="Germany"`) rather than guessing. Note in a
  code comment *why* the field is a placeholder, since it directly limits what
  `pipeline/location.py` and `pipeline/filters.py` can do with jobs from this source
  downstream.
- **If the source is a clickout-tracked aggregator (talent.com-style, or anything
  where "view job" redirects out through a tracking link), don't use the raw `href`
  as `NormalizedJob.url`.** `englishjobsde` returns a *different*, freshly-signed
  `/clickout/<id>?sig=...` link for the exact same job depending on which search term
  surfaced it — using that as `url` broke both this adapter's own in-run
  dedup-by-url dict *and* `pipeline/dedupe.py`'s persistent SQLite dedup (job_id is
  `hash(source_id + url)`), so the same job looked "new" on every run forever. Look
  for a stable per-card identifier instead (a DOM `id` attribute, a numeric job ID
  embedded in the card) and build the canonical URL from that — test that the
  bare/minimal form (no query string) still redirects correctly before relying on it.
- **BeautifulSoup spacing gotcha when a title/field has inline tags around individual
  words** (e.g. search-term highlighting: `"Senior <em>QA</em>/QC <em>Engineer</em>"`).
  `get_text(strip=True)` strips whitespace *per text node*, which can eat a real space
  between nodes (`"SeniorQA/QCEngineer"`); `get_text(" ", strip=True)` inserts a space
  at *every* tag boundary, which can invent one that was never there
  (`"QA /QC"` instead of `"QA/QC"`) — either corrupts a substring
  `pipeline/filters.py:filter_by_title` needs intact downstream. Use `get_text()` with
  no arguments (preserves the original spacing exactly), then a single
  `re.sub(r"\s+", " ", text).strip()` pass on the whole string.

## 7. Make sure `description` actually gets populated — not just `location`

`pipeline/classify_language.py` (German vs English) needs real `description` text to
work at all; an empty string always classifies as English by default, silently. This
is easy to miss because the adapter will otherwise work fine — titles, companies,
locations all look correct — while every job from that source quietly gets the wrong
language bucket.

**This already happened once**: `arbeitnow_api.py`'s search-fragment cards only ever
carried title/company/location, never a description, so every Arbeitnow job defaulted
to English regardless of its real requirement — undetected until a later dry-run
showed 0 German matches from a source that should have had some. Check whether the
source's *listing/search* response includes a real description at all before assuming
it does; a compact search-result card is a common case where it doesn't.

If it doesn't, check whether the individual job's **detail/permalink page** does (same
method as step 1 — fetch it and check for real content vs. another SPA shell; it can
differ from the listing page's rendering). If it does:

- **Don't fetch every job's detail page unconditionally** — a search across ~20 terms
  can return 150+ unique jobs, and one more HTTP request per job is expensive and
  rate-limit-risky. Narrow first: only fetch descriptions for jobs whose title already
  matches `source_config["search_terms"]` (the same substring check
  `pipeline/filters.py:filter_by_title` applies downstream anyway) — `arbeitnow_api.py`
  does this and cuts ~150 candidates down to ~50 real requests. Jobs that don't survive
  this narrowing keep `description=""`, which is harmless — they get filtered out by
  the title-match step before ever reaching the language classifier.
- **Apply the same rate-limit spacing/backoff as the listing fetch** (see step 6) to
  the detail-page requests too — don't assume a different endpoint on the same site has
  different or no limits.
- **Store raw inner HTML, not `.get_text()`-flattened plain text**, if other sources'
  descriptions are also raw HTML (check `adapters/boards/html_scrape.py` /
  `config/language_rules.yaml` for the convention in use). `classify_language.py`'s
  clause-boundary logic uses `<` (an HTML tag start) to stop a match from bleeding into
  an unrelated `<li>` bullet point — flattening to plain text silently removes that
  guard.

Testing this is two separate checks, not one — a working fetch and a working
classification can fail independently:

```python
# 1. Did the fetch actually get descriptions?
with_desc = [j for j in jobs if j.description]
print(f"{len(with_desc)}/{len(jobs)} have a non-empty description")

# 2. Does the classifier actually produce non-English results from this source?
german, english = classify_language.split_by_language(jobs)
print(f"german={len(german)} english={len(english)}")
```

If (2) stays at 0 German even once (1) confirms descriptions are populated, the
classifier's patterns themselves may not generalize to this source's phrasing — that
happened too: Arbeitnow's real descriptions surfaced "Deutschkenntnisse mindestens auf
B2-Niveau", a real requirement `config/language_rules.yaml`'s CEFR pattern didn't catch
because it only listed C1/C2. Testing a new source's real content can surface gaps in
shared pipeline logic, not just bugs in the new adapter — check `pipeline/*` findings
against the *other* sources too before assuming they're source-specific.

## 8. Register the adapter

Add it to the `ADAPTERS` dict in `agents/_common.py`, keyed by the adapter name string
that will go in `sources.yaml`:

```python
ADAPTERS = {
    "arbeitnow_api": arbeitnow_api.fetch_jobs,
    "html_scrape": html_scrape.fetch_jobs,
    "<new_adapter_name>": <new_module>.fetch_jobs,
}
```

## 9. Update `config/sources.yaml`

- Change the source's `adapter:` field from its `_todo`/`anti_bot_avoid` classification
  to the real adapter name (the one now registered in `agents/_common.py`'s `ADAPTERS`).
- Add any adapter-specific fields it needs (e.g. `rss_url:`, `api_url:`).
- Update `notes:` to explain what fetch mechanism is actually used and why, in enough
  detail that the next person doesn't have to re-derive it (see the
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

Check: the fetched-count log line looks sane (not 0, not obviously wrong), the printed
titles actually look like real candidate jobs, and — if this source produces `location`
or `description` text that `pipeline/location.py` will classify — spot-check a few
matched jobs against the source's real page/feed content directly. A bare
substring/regex match against free-text prose is a known false-positive trap (a past
bug matched "remote" inside "Remote-Erstgespräch", an unrelated remote *interview*
mention, misclassifying a hybrid Nürnberg job as remote) — verify a new source's
description text doesn't trip the same kind of false positive before trusting it.

Two more classification checks worth doing specifically when the new source is
*richer* than the ones already built (a real structured `location` field, or
substantial free-text company-boilerplate, or English-first phrasing):

- **`is_munich()`'s free-text-description fallback only fires when `location` is
  empty or a known no-data placeholder** (`GENERIC_LOCATION_PLACEHOLDERS` in
  `pipeline/location.py`) — once a source has a real structured `location`, that
  field is trusted exclusively. This was added after a StepStone posting's
  boilerplate company description ("mit Sitz in ... München") got misread as the
  job's location instead of the company's HQ. If the new source has rich free-text
  `description` (company bios, benefits prose), check a few matches against the real
  page the same way you'd check a remote-phrase match.
- **German-requirement signals can be phrased entirely in English** (a source that
  auto-translates, or is English-first but still lists some German-requiring roles).
  Grep a batch of real fetched descriptions for `german`/`deutsch`/`fluen`/CEFR levels
  near disclaimer-ish words ("plus", "desirable", "nice to have") and check
  `config/language_rules.yaml`'s patterns actually catch what you find — don't assume
  the existing German-phrase patterns generalize. See `job_search_agent_phase5`
  memory for the specific real phrasings ("Good knowledge of German and English.",
  "fluency in German", "German as a plus") that were missed before being added.
- **A posting can require German without any explicit phrase at all** — a real
  Instaffo/XING posting was 100% German prose with no self-referential "German
  required" statement anywhere, and defaulted to the English bucket despite requiring
  German just to read it. `is_german_required()`'s whole-description stopword-ratio
  fallback (`config/language_rules.yaml`'s `whole_description_language_signal`) covers
  this now, but re-check it against the new source's real German-only postings if it
  has any - don't assume the calibrated thresholds generalize without checking.
- **A source that reads as "German" or "Germany" in its name isn't necessarily
  Germany-only.** `pipeline/location.py` has no country concept - it trusts a
  structured `location` field once one exists. XING (DACH-wide) and Bundesagentur für
  Arbeit (includes some Luxembourg/Romania postings) both leaked non-Germany jobs that
  a remote-phrase or city-name match could otherwise wrongly pull into a Munich/remote
  digest. Check a batch of real fetched jobs' country field (JSON-LD's
  `address.addressCountry`, or the source's own search API if it already includes a
  country, cheaper - see `bundesagentur.py`) before assuming a source is Germany-only;
  if it isn't, filter/drop non-Germany jobs at the adapter level (see `xing_jobs.py`
  and `bundesagentur.py` for two different implementations of the same fix).

Never run without `--dry-run` (i.e. actually send to Telegram) without the user's
explicit go-ahead first.
