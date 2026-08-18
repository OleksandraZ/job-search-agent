# job-search-agent

See `job_search_agent_plan.md` for the full build spec and phase plan.

## NormalizedJob and the adapter contract

Every board adapter converts its source's data into `NormalizedJob`
(`adapters/boards/__init__.py`):

```python
@dataclass
class NormalizedJob:
    source_id: str    # the sources.yaml `id` this job came from
    title: str
    company: str
    url: str
    location: str      # free text; may be a placeholder if the source has no real location field
    description: str   # free text; may be "" if the source's response has no description
```

All six fields are required strings — there's no `Optional`. When a source genuinely
doesn't have a value for `location` or `description`, the adapter still has to set
something (see caveats below); there's no way to signal "unknown" downstream.

**`description` is not optional in practice, even though the type allows `""`.**
`pipeline/classify_language.py` (German vs English) only has `description` to work
with — an empty string always classifies as English by default, *silently*. A listing
or search-result endpoint frequently only has summary fields (title/company/location),
not the full description; if that's all an adapter uses, every job from that source
will quietly get the wrong language bucket. Check the source's individual job/detail
page for a fuller description before accepting `description=""` as final — see the
`add-board-source` skill's step on this (written after `arbeitnow_api.py` had exactly
this bug) for the fetch-cost tradeoffs (don't fetch every job's detail page
unconditionally) and how to verify it's actually working (checking "did the fetch get
descriptions" and "does the classifier produce non-English results" are two separate
checks, not one).

**Adapter interface:** `adapters/boards/<name>.py` exposes

```python
def fetch_jobs(source_config: dict) -> list[NormalizedJob]:
```

`source_config` is the source's entry from `config/sources.yaml` (a plain dict — `id`,
`adapter`, `url`, plus whatever adapter-specific fields it needs, e.g. `rss_url`), with
one key always injected on top: `search_terms` — the list from
`keywords.yaml`'s `title_match_terms`, added by `agents/_common.py:fetch_from_sources()`
before calling the adapter. An adapter only needs to read `search_terms` if it actually
sends queries to the source (e.g. `arbeitnow_api.py` does; `html_scrape.py` doesn't,
since GermanTechJobs' RSS feed can't be queried).

**Registration:** adapters are looked up by name in `agents/_common.py`'s `ADAPTERS`
dict, keyed by the string used in `sources.yaml`'s `adapter:` field. When a source gets
a real adapter, its `adapter:` field is updated to that adapter's registry key (see
`arbeitnow_qa_jobs` → `arbeitnow_api`). An unregistered `adapter:` value (any source
without real code yet) isn't an error — `fetch_from_sources()` logs a warning and skips
it, so it's safe for `sources.yaml` to carry `adapter:` values with no corresponding
module.

**`adapter:` values not yet built:** originally every source in `sources.yaml` started
as `adapter: html_scrape` (a single generic placeholder). A 2026-08-17 automated pass
fetched all 114 not-yet-built sources and reclassified each into `json_api_todo` /
`html_scrape_todo` / `js_rendered_todo` / `anti_bot_avoid` / `broken_todo` /
`ambiguous_todo` (see `sources.yaml`'s `meta.adapter_legend` for exact definitions) —
informational, not registered adapters, so they're inert until someone builds against
them. This replaced the blanket placeholder specifically because it was misleading:
`html_scrape` is also the registry key for one *real* adapter (GermanTechJobs'
RSS-based one), so a source still carrying that value looked like it had working code
when it didn't. The classification is a single-page-fetch heuristic (text length,
SPA-shell detection, status code) — verified against a priority-1 sample by hand,
including one real catch (LinkedIn's plain GET returns only cookie-consent
boilerplate, not listings, despite "looking" scrapeable by text volume; overridden to
`anti_bot_avoid` per `job_search_agent_plan.md` §4's own Tier-3 guidance). Re-verify
per-source before actually building against a `_todo` classification — see the
`add-board-source` skill.

**Real adapters built so far** (Phase 5, in build order): `arbeitnow_api`,
`html_scrape` (GermanTechJobs), `stepstone`, `devjobs`, `testdevjobs`,
`wearedevelopers`, `englishjobsde`, `builtin`, `xing_jobs`, `get_in_it`, `instaffo`,
`bundesagentur` — **all 11 priority-1 sources now have a real, working adapter**;
Phase 5's board-source build-out is complete (see `job_search_agent_phase5` memory
for per-source investigation notes). The remaining ~75 `html_scrape_todo`/11
`js_rendered_todo` sources in `sources.yaml` are lower-priority and untouched. Each
source's `sources.yaml` `notes:` field is the authoritative per-source reference
(fetch mechanism, selectors, quirks) — this file covers cross-cutting lessons that
apply to *building the next one*, not a repeat of every source's specifics.

**Prefer a page's own JSON-LD/embedded-JSON over CSS-selector scraping when both are
available.** `xing_jobs`, `get_in_it`, `instaffo`, and `bundesagentur` all turned out
to have a real `schema.org JobPosting` `<script type="application/ld+json">` block (or,
for `get_in_it`, a `__NEXT_DATA__` JSON blob) on their detail pages — parsing that
directly gives clean, structured title/company/location/description fields in one
`json.loads()`, and is far more robust to a site's next CSS/class-name refactor than
selector-based scraping. Check for this before writing BeautifulSoup selectors against
a new source's detail page.

**A site's own `robots.txt` can carve out an explicit exception for AI-agent
crawlers.** XING's disallows `/jobs/search` for `User-agent: *` but has a separate,
named block explicitly *allowing* it for `ClaudeBot`/`Claude-User`/`GPTBot`/etc. — a
deliberate site-level policy for exactly this use case. Check a new source's
`robots.txt` for a similar named-bot block before defaulting to a generic browser
User-Agent; if one exists, identifying honestly as the matching bot (see
`adapters/boards/xing_jobs.py`'s `HEADERS`) is both more compliant and more honest
than spoofing a browser. Surface the choice to the user (AskUserQuestion) rather than
picking silently — it's a real policy decision, not just an implementation detail.

**A source covering "Germany" isn't always Germany-only — check for cross-border
leakage.** Two sources this session turned out to include non-German postings despite
being framed as German job boards: XING is DACH-wide (Germany/Austria/Switzerland) and
Bundesagentur für Arbeit's official database includes some Luxembourg/Romania-based
listings. `pipeline/location.py` has no country concept, so a foreign posting that
happens to match a remote-phrase or city-name pattern can slip through as a false
Munich/remote match. Fix at the adapter level, not the shared pipeline: check each
job's real `addressCountry` (from JSON-LD, or — cheaper, if the source's own search API
already returns it, as Bundesagentur's does — straight from the listing response) and
drop or trim non-Germany locations before the job ever reaches `pipeline/location.py`.
Check for this on any new source that isn't a Germany-only platform by construction.

**A recurring trap: a site's own search box often doesn't do what it looks like it
does.** Not just documented external APIs (step 3 of the skill) — three separate
sources (`devjobs`, `testdevjobs`, `builtin`) turned out to have a `?q=`/`?search=`
query param that's silently ignored (identical results with or without it) and/or a
small *fixed taxonomy* of working category slugs instead of real free-text search
(e.g. Built In's `/search/qa` is the only populated category out of 18 tested
`title_match_terms` slugs; everything else 404s into an unrelated generic listing).
Confirm a query param actually changes the result set (diff with/without it) before
building `search_terms`-driven queries against it; if it doesn't, crawl the one/few
working fixed listing(s) instead and lean on `filter_by_title` downstream, same as
GermanTechJobs' RSS.

**Aggregator/clickout sources need a stable per-job identifier, not the listing
link's raw `href`.** `englishjobsde` (talent.com-powered) returns a *different*,
freshly-signed `/clickout/<id>?sig=...` URL for the same real job depending on which
search term surfaced it — using that raw href as `NormalizedJob.url` broke both the
adapter's own in-run dedup-by-url and `pipeline/dedupe.py`'s persistent SQLite dedup
(job_id is `hash(source_id + url)`), so the same job would look "new" forever. Fixed
by using the job card's own stable DOM id to build a canonical URL
(`/clickout/<id>`, no query string — confirmed the bare path still redirects
correctly). Check for this whenever a source's "view job" link carries a tracking
signature/session param.

**BeautifulSoup `get_text()` spacing gotcha:** when a title/field has inline tags
around individual words (e.g. `englishjobsde` wraps matched search terms in
`<em>`: `"Senior <em>QA</em>/QC <em>Engineer</em>"`), `get_text(strip=True)` strips
whitespace *per text node* and can eat a real space (`"SeniorQA/QCEngineer"`), while
`get_text(" ", strip=True)` inserts a space at *every* tag boundary and can invent one
that was never there (`"QA /QC"` instead of `"QA/QC"`) — corrupting the substring
`filter_by_title` downstream relies on either way. Correct approach: `get_text()` with
no arguments (preserves the original spacing exactly), then a single
`re.sub(r"\s+", " ", ...).strip()` pass on the whole string.

**Failure handling and retries:** two layers, deliberately different granularity.

- **Per-request retry** — `http_client.py`'s `get_with_retry()` / `post_with_retry()`
  is the shared retry-after-backoff helper: one retry on 429/5xx after a fixed backoff,
  raises via `response.raise_for_status()` otherwise. Every adapter's HTTP calls go
  through this (`arbeitnow_api.py`, `html_scrape.py`), as does the Telegram notifier
  (`notifier/telegram.py:send_message()`). Don't hand-roll a new retry loop in a new
  adapter — import `get_with_retry` from `http_client.py`. It lives at the project
  root (not under `adapters/`) specifically so both fetch-side (adapters) and
  send-side (notifier) code can share it.
- **Per-source isolation, no source-level retry** — `fetch_from_sources()` wraps the
  whole `fetch_jobs()` call in a `try/except Exception` per source: an unhandled
  exception (e.g. all retries exhausted) loses that source's jobs for the run but
  doesn't take down the others, and isn't itself retried. Retrying an entire
  multi-request source fetch again (vs. the single failed request within it) would be
  expensive and mostly redundant with the per-request retry already inside the
  adapter — a source that still fails after that has a real, not transient, problem;
  the next scheduled run picks it back up.
- Adapters that make many requests per call (e.g. one per search term, one per job
  detail page) should still catch *per-request* `httpx.HTTPError` and keep going
  after `get_with_retry()`'s retries are exhausted, so one bad request doesn't
  discard everything else already fetched in that call — see `arbeitnow_api.py`'s
  per-term `try/except` around `_search()` and per-job `try/except` around
  `_fetch_description()`.

**Per-run wall time now runs ~25-30 minutes end to end across all 12 sources** (as of
Phase 5's completion) — each adapter's own rate-limit spacing between detail-page
fetches is additive across the whole run, not just within one source, and it adds up:
`bundesagentur` alone makes ~500+ detail-page requests at 1s spacing on a
title-match-heavy run (~9+ minutes by itself), on top of XING's ~80-90 requests and
every other source's. This is expected, not a hang — worth knowing before assuming a
long-running `main.py` is stuck. Keep this in mind if per-run cost ever needs actively
managing (e.g. before adding GitHub Actions scheduling in Phase 7 — check the
workflow's timeout budget against this).

## Agent shape

`agents/munich_local.py` and `agents/germany_remote.py` both follow the same shape:

```python
SOURCE_IDS = [...]                                   # sources.yaml ids this agent draws from
def filter_jobs(jobs: list[NormalizedJob]) -> list[NormalizedJob]: ...   # pure scope filter
def run(sources_config, keywords_config) -> list[NormalizedJob]: ...     # fetch + filter_jobs, standalone use
```

`filter_jobs()` narrows a raw job list to the agent's scope, using `pipeline/location.py`
(`filter_munich` / `filter_remote`). It's a pure function over an already-fetched job
list — no I/O — so it can be reused without re-fetching.

**Why `main.py` doesn't call each agent's `run()`:** both agents currently draw from the
*same source list* (there's no Munich-specific or remote-specific board query yet), so
calling `run()` on each would fetch everything twice — doubling the request volume
against every rate-limited board. Instead `main.py` fetches once via
`agents._common.fetch_from_sources()` with the union of both agents' `SOURCE_IDS`, then
calls each agent's `filter_jobs()` on the shared raw list. If a future agent gets a
distinct source list, this can revert to independent `run()` calls for that agent
without changing the others.

**`munich_jobs + remote_jobs` needs deduping before use.** A job can legitimately be
both Munich-based *and* remote-eligible (e.g. location "München, Germany (Remote
available)"), so it shows up in both `filter_jobs()` results — concatenating them
without deduping sent the same job twice in one digest (found via a real
WeAreDevelopers posting once a source finally produced a dual-classifiable job).
`main.py` dedupes by `url` (`{job.url: job for job in munich_jobs + remote_jobs}`)
before `filter_by_title`/`dedupe.filter_unseen` run. Keep this in mind if another
merge point is ever added upstream of the language classifier or the Telegram send.

## Known caveats (read before touching a specific source)

- **GermanTechJobs (`adapters/boards/html_scrape.py`):** the configured
  `germantechjobs.de/en/jobs/Tester/all` URL is a client-rendered SPA with no job data
  in the raw HTML. The adapter reads the site's RSS feed instead
  (`rss_url` in `sources.yaml`), which is global/unfiltered (~1183 items, all
  categories) and has **no structured location field** — `location` is set to the
  literal placeholder `"Germany"`. This means Munich/remote classification for
  GermanTechJobs jobs depends entirely on what the free-text `description` happens to
  mention, and most postings mention neither — expect most GermanTechJobs matches to
  fall out of both `agents/munich_local.py` and `agents/germany_remote.py`.
- **Arbeitnow (`adapters/boards/arbeitnow_api.py`):** uses the site's internal,
  undocumented `/api/jobs` search endpoint (HTML-fragment response, parsed with
  BeautifulSoup) rather than the documented `job-board-api`, because the documented one
  silently ignores `?search=`/`?tags=` and only returns the newest ~175 jobs. This is a
  more fragile dependency (internal endpoint, could change without notice) — a
  deliberate, user-approved tradeoff. It rate-limits after a burst of requests; the
  adapter spaces out requests (`REQUEST_DELAY_SECONDS`) on top of `http_client.py`'s
  retry-once-on-429. The search-fragment cards only
  carry title/company/location, never a description, so the adapter separately fetches
  each *title-matched* job's detail page (`[itemprop="description"]`, real
  server-rendered HTML unlike the SPA listing page) to fill in `description` — narrowed
  to the title-matched subset (not all ~150 raw results) to bound the extra request
  volume, using the same rate-limit spacing as the search calls.
- **`pipeline/location.py` and `pipeline/classify_language.py` classification:**
  free-text `description`/`location` matching requires strong, unambiguous phrases
  rather than bare words, and needs to stay within one clause — two real bugs already
  came from getting this wrong:
  - A bare `remote`/`homeoffice` substring match misclassified a hybrid Nürnberg job as
    remote (it matched "Remote-Erstgespräch", a remote *interview* mention, and
    "2 Tage Homeoffice", which is hybrid not full-remote). Fixed by requiring
    unambiguous phrases (`100% remote`, `fully remote`) in free text, while still
    trusting a source's short, structured `location` field more loosely.
  - `config/language_rules.yaml`'s patterns bound word-gaps at `[^.;<]` — stopping at
    sentence punctuation *and* HTML tag boundaries (descriptions are HTML with `<li>`
    bullet points) — specifically because an unbounded gap let a disclaimer phrase
    ("von Vorteil") in one bullet point falsely negate a real requirement match in an
    unrelated adjacent one. Before adding or loosening a pattern here, validate it
    against real fetched description text first (not written from assumption) — see
    `job_search_agent_phase4` memory for the specific false-positive cases this ruled
    out, including one where the exact same surface phrase ("gute Deutschkenntnisse")
    means opposite things depending on what immediately follows it.
  - Even an "unambiguous phrase" match isn't safe from **negation**: a real Arbeitnow
    posting read "hybrid, not full remote" — "full remote" matched
    `DESCRIPTION_REMOTE_PATTERN` as a phrase, but "not" right before it flips the
    meaning entirely, and nothing checked for that. `pipeline/location.py:is_remote()`
    now checks the clause immediately *before* a match for negation words (`not`,
    `nicht`, `kein(e)`, `no longer`) using the same clause-bounded-window technique as
    the disclaimer check above, just looking backward. Check both directions — what
    precedes and what follows — before trusting any new regex classifier here.
  - **`is_munich()`'s free-text fallback is now gated on the source having no real
    location field**, not applied unconditionally alongside the structured field. A
    real StepStone posting for a Kirchdorf an der Iller (near Ulm) role was
    misclassified as Munich because its description's standard company-boilerplate
    opener ("Das Unternehmen mit Sitz in Taufkirchen bei München...") mentions the
    company's *HQ city*, not the job's actual location — and that same "mit Sitz in
    &lt;city&gt;" opener recurs across unrelated StepStone postings regardless of
    where the role itself is, so it wasn't a one-off. Once a source has a real,
    structured `location` (StepStone, DEVjobs, TestDevJobs, Built In all do),
    `is_munich()` trusts it exclusively; the description-scanning fallback only
    fires for `location` values that are empty or a known no-data placeholder
    (`GENERIC_LOCATION_PLACEHOLDERS = {"germany", "deutschland"}`, i.e. GermanTechJobs).
    Adding a source with substantial free-text company-boilerplate in `description` is
    exactly when this class of bug resurfaces — re-check it.
  - **Not every "unambiguous" phrase stays unambiguous as more sources arrive:**
    `remote[\s-]?first` was removed from `DESCRIPTION_REMOTE_PATTERN` after a real
    TestDevJobs posting read "Remote-first – work where you work best, whether from
    home or in a hybrid mode from our office ... in Berlin" — the company's own
    definition of "remote-first" there explicitly included hybrid office work, so it
    isn't the same kind of hard commitment as "100% remote"/"fully remote". A phrase
    added against one source's real data isn't guaranteed to generalize to the next
    source's usage of it — re-validate against the new source's real text, not just
    trust the existing list.
  - **German-requirement signals also show up phrased in English** — not just direct
    German prose. `config/language_rules.yaml`'s `german_required_patterns` originally
    only matched German words (`Deutschkenntnisse`, CEFR-level-near-`deutsch`, etc.);
    real DEVjobs.de text (which auto-translates German-origin postings to English) and
    EnglishJobs.de text (an English-first board that still lists some
    German-requiring roles) surfaced real, stated requirements phrased entirely in
    English that nothing caught: "Good knowledge of German and English.", "Very good
    written and spoken German and English skills.", "fluency in German and English"
    (a different word stem than "fluent" — `\bfluen\w*`, not `fluent\w*`, is needed to
    catch both). Symmetrically, `optional_disclaimer_patterns` was German-phrase-only
    (`von Vorteil`, `wünschenswert`, ...) — a real "Fluent English skills and German
    as a plus." posting was wrongly counted as German-required because there was no
    English disclaimer to cancel it (`a plus`, `desirable`, `nice to have`,
    `not required`/`not mandatory` were added). Both directions need validating
    against each new source's actual English-phrased text, not just its German-phrased
    text — see `job_search_agent_phase5` memory for the exact false-positive/negative
    cases this ruled out.
  - **A posting can require German without ever *stating* it does.** Every pattern
    above looks for an explicit requirement phrase — but a real Instaffo posting (and,
    checking after the fact, an already-sent XING one) was 100% German prose front to
    back with no self-referential "Deutschkenntnisse required" statement anywhere,
    since the platform's own market is German and stating the obvious would be
    redundant. Both defaulted to the English bucket. `is_german_required()` now has a
    second, independent check (`_is_predominantly_german()`) — a stopword-frequency
    ratio over the whole description (`config/language_rules.yaml`'s
    `whole_description_language_signal`), triggered only when explicit-phrase matching
    finds nothing. Calibrated against real fetched samples before wiring in (3 pure-
    German postings scored 0.91-0.94 German-word ratio; a genuinely English Built In
    posting scored 0.00) — thresholds have wide margin on both sides. This is a
    deliberate, narrow exception to "requires, not written in" (see
    `job_search_agent_plan.md` §8): a fully German-language ad is treated as itself
    evidence of the requirement. **When building a true-negative test sample here,
    verify it's actually negative** — an initial "clean English" sample turned out to
    genuinely require German stated in English prose ("Very good English and German
    language skills are a prerequisite"), a true positive via the *existing*
    explicit-phrase path, not a bug in the new code.
