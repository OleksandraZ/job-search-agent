# Lessons: building board adapters

Full incident narratives behind the tight gotcha list in `CLAUDE.md`. Each section
leads with the rule and why it exists — keep reading past that only if you want the
real source and root cause behind it. Each source's own quirks live in its
`sources.yaml` `notes:` field — this file is cross-cutting lessons that apply to
*building the next adapter*, not a repeat of any one source's specifics.

## <a name="json-ld"></a>Prefer a page's own JSON-LD/embedded-JSON over CSS-selector scraping

**Check for a `JobPosting` JSON-LD block (or a framework's embedded JSON) before
writing CSS selectors.** It gives clean, structured fields in one `json.loads()` and
survives a CSS/class-name refactor that would break selector-based scraping.

`xing_jobs`, `get_in_it`, `instaffo`, and `bundesagentur` all turned out to have a
real `schema.org JobPosting` `<script type="application/ld+json">` block (or, for
`get_in_it`, a `__NEXT_DATA__` JSON blob) on their detail pages — parsing that
directly gives clean, structured title/company/location/description fields, far more
robust than selector-based scraping. Check for this before writing BeautifulSoup
selectors against a new source's detail page.

## <a name="robots-txt-ai-bots"></a>A site's own `robots.txt` can carve out an explicit exception for AI-agent crawlers

**Check `robots.txt` for a named AI-agent-bot allowlist before defaulting to a
generic browser User-Agent.** Some sites explicitly permit AI-agent crawlers on
paths they disallow generally — identifying honestly as the matching bot is both
more compliant and more honest than spoofing a browser.

XING's `robots.txt` disallows `/jobs/search` for `User-agent: *` but has a separate,
named block explicitly *allowing* it for `ClaudeBot`/`Claude-User`/`GPTBot`/etc. — a
deliberate site-level policy for exactly this use case (see
`adapters/boards/xing_jobs.py`'s `HEADERS`). Surface the choice to the user
(AskUserQuestion) rather than picking silently — it's a real policy decision, not
just an implementation detail.

## <a name="country-check"></a>A source covering "Germany" isn't always Germany-only

**Verify the country field if a source isn't Germany-only by construction.**
`pipeline/location.py` has no country concept, so a foreign posting that happens to
match a remote-phrase or city-name pattern can slip through as a false
Munich/remote match.

Two sources turned out to include non-German postings despite being framed as German
job boards: XING is DACH-wide (Germany/Austria/Switzerland) and Bundesagentur für
Arbeit's official database includes some Luxembourg/Romania-based listings. Fix at
the adapter level, not the shared pipeline: check each job's real `addressCountry`
(from JSON-LD, or — cheaper, if the source's own search API already returns it, as
Bundesagentur's does — straight from the listing response) and drop or trim
non-Germany locations before the job ever reaches `pipeline/location.py`.
`xing_jobs.py` and `bundesagentur.py` show two different implementations of the same
fix.

## <a name="fake-search"></a>A recurring trap: a site's own search box often doesn't do what it looks like it does

**Confirm a search/query param actually changes the result set before trusting it.**
A site's own search box is often silently ignored, or backed by only a handful of
real category slugs rather than genuine free-text search.

Three separate sources (`devjobs`, `testdevjobs`, `builtin`) turned out to have a
`?q=`/`?search=` query param that's silently ignored (identical results with or
without it) and/or a small *fixed taxonomy* of working category slugs (e.g. Built
In's `/search/qa` is the only populated category out of 18 tested
`title_match_terms` slugs; everything else 404s into an unrelated generic listing).
`get_in_it` had the same shape one level deeper: its SSR filter schema has no
keyword field *at all*, only a fixed `thematicPriority` facet id. Diff the response
with/without the param before building `search_terms`-driven queries against it; if
it doesn't change, crawl the one/few working fixed listing(s) instead and lean on
`filter_by_title` downstream, same as GermanTechJobs' RSS.

## <a name="stable-ids"></a>Aggregator/clickout sources need a stable per-job identifier, not the listing link's raw `href`

**Use a stable per-job identifier, not the listing link's raw `href`, for
aggregator/clickout sources.** A freshly-signed clickout URL that changes per search
term breaks both in-adapter and persistent SQLite dedup.

`englishjobsde` (talent.com-powered) returns a *different*, freshly-signed
`/clickout/<id>?sig=...` URL for the same real job depending on which search term
surfaced it — using that raw href as `NormalizedJob.url` broke both the adapter's own
in-run dedup-by-url and `pipeline/dedupe.py`'s persistent SQLite dedup (job_id is
`hash(source_id + url)`), so the same job would look "new" forever. Fixed by using
the job card's own stable DOM id to build a canonical URL (`/clickout/<id>`, no query
string — confirmed the bare path still redirects correctly).

## <a name="get-text-spacing"></a>BeautifulSoup `get_text()` spacing gotcha

**Use `get_text()` with no arguments plus a whitespace-collapse regex when a field
has inline tags around individual words.** `strip=True` eats real spaces between text
nodes; `get_text(" ", strip=True)` invents fake ones at every tag boundary — either
corrupts the substring `filter_by_title` relies on.

`englishjobsde` wraps matched search terms in `<em>`: `"Senior <em>QA</em>/QC
<em>Engineer</em>"`. `get_text(strip=True)` produced `"SeniorQA/QCEngineer"`;
`get_text(" ", strip=True)` produced `"QA /QC"` instead of `"QA/QC"`. Correct
approach: `get_text()` with no arguments (preserves the original spacing exactly),
then a single `re.sub(r"\s+", " ", ...).strip()` pass on the whole string.

## `adapter:` `_todo` classification and the LinkedIn catch

**A `_todo` classification is a single automated pass, not a guarantee — re-verify
per-source before building against it.** It already produced one real miscall.

Originally every source in `sources.yaml` started as `adapter: html_scrape` (a single
generic placeholder). A 2026-08-17 automated pass reclassified all not-yet-built
sources into `json_api_todo`/`html_scrape_todo`/`js_rendered_todo`/`anti_bot_avoid`/
`broken_todo`/`ambiguous_todo` (see `sources.yaml`'s `meta.adapter_legend`) — a
single-page-fetch heuristic (text length, SPA-shell detection, status code), verified
against a priority-1 sample by hand. The one real catch: LinkedIn's plain GET returns
only cookie-consent boilerplate, not real listings, despite "looking" scrapeable by
text volume — overridden to `anti_bot_avoid` per `job_search_agent_plan.md` §4's own
Tier-3 guidance (see `sources.yaml`'s `linkedin_jobs` entry).

## Failure handling and retries: why two layers, not one

**Use `http_client.py`'s `get_with_retry()` for every HTTP call; let
`fetch_from_sources()` isolate source-level failures.** Don't hand-roll a new retry
loop, and don't retry a whole source fetch again after it fails — that's already the
per-request retry's job, done cheaper.

- **Per-request retry** (`get_with_retry()`/`post_with_retry()`) handles transient
  failures (429/5xx, one retry after backoff). Every adapter and the Telegram
  notifier share it.
- **Per-source isolation, no source-level retry** — `fetch_from_sources()` wraps each
  `fetch_jobs()` call in `try/except Exception`: an unhandled exception loses that
  source's jobs for the run but doesn't take down the others, and isn't itself
  retried. Retrying an entire multi-request source fetch again would be expensive and
  mostly redundant with the per-request retry already inside the adapter — a source
  that still fails after that has a real, not transient, problem; the next scheduled
  run picks it back up.
- Adapters making many requests per call (one per search term, one per job detail
  page) should still catch *per-request* `httpx.HTTPError` and keep going after
  `get_with_retry()`'s retries are exhausted, so one bad request doesn't discard
  everything else already fetched in that call — see `arbeitnow_api.py`'s per-term
  `try/except` around `_search()` and per-job `try/except` around
  `_fetch_description()`.

## Per-run wall time keeps growing as sources are added

**Per-run wall time grows with every source added — a long-running `main.py` isn't
necessarily stuck.** Each adapter's own rate-limit spacing between detail-page
fetches is additive across the *whole* run, not just within one source.

This is easy to underestimate: when Phase 5 finished (all 11 priority-1 sources
built, 12 adapters total), a full run had grown to ~25-30 minutes end to end.
`bundesagentur` alone accounted for ~9 of those minutes by itself (~500+
detail-page requests at 1s spacing on a title-match-heavy run), on top of XING's
~80-90 requests and every other source's. Re-measure rather than trusting that
figure once more sources are added — check the *current* per-run time against any
timeout budget (e.g. GitHub Actions scheduling in Phase 7), not this historical one.

## <a name="run-once"></a>Why `main.py` doesn't call each agent's `run()`

**Fetch once via the shared union of both agents' source ids, not once per agent.**
Both agents currently draw from the same source list, so calling `run()` on each
would double the request volume against every rate-limited board.

`main.py` fetches once via `agents._common.fetch_from_sources()` with the union of
both agents' `SOURCE_IDS`, then calls each agent's `filter_jobs()` on the shared raw
list. If a future agent gets a distinct source list, this can revert to independent
`run()` calls for that agent without changing the others.

## <a name="dedupe-merge"></a>`munich_jobs + remote_jobs` needs deduping before use

**Dedupe `munich_jobs + remote_jobs` by `url` before anything downstream runs.** A
job can legitimately be both Munich-based *and* remote-eligible, so it shows up in
both `filter_jobs()` results and would otherwise be sent twice.

Found via a real WeAreDevelopers posting (location "München, Germany (Remote
available)") once a source finally produced a dual-classifiable job. `main.py`
dedupes by `url` (`{job.url: job for job in munich_jobs + remote_jobs}`) before
`filter_by_title`/`dedupe.filter_unseen` run. Keep this in mind if another merge
point is ever added upstream of the language classifier or the Telegram send.
