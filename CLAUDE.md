# job-search-agent

See `job_search_agent_plan.md` for the full build spec and phase plan.

For the *why* behind any gotcha below, see:
- `docs/lessons/adapters.md` — building/fixing a board adapter
- `docs/lessons/ats_adapters.md` — building/fixing an ATS (company-direct) adapter
- `docs/lessons/classification.md` — `pipeline/location.py` and `pipeline/classify_language.py`

Each source's own quirks (fetch mechanism, selectors, search-param behavior) live in
its `sources.yaml` `notes:` field, not here.

## Code quality

After every task, `ruff check .` and `mypy .` must both show no errors before the
task is considered done. Fix any findings — don't suppress them with inline
ignores unless the ignore itself is the correct fix.

## Before adding a source

- [ ] [Check for JSON-LD/`__NEXT_DATA__`](docs/lessons/adapters.md#json-ld) before writing CSS selectors
- [ ] [Confirm `?q=`/`?search=` actually changes results](docs/lessons/adapters.md#fake-search) (diff with/without)
- [ ] [Check `robots.txt` for a named-bot allowlist](docs/lessons/adapters.md#robots-txt-ai-bots) before spoofing a UA
- [ ] [Verify the country field](docs/lessons/adapters.md#country-check) if the source isn't Germany-only by construction
- [ ] [Use a stable per-job id](docs/lessons/adapters.md#stable-ids), not a signed/session-tagged clickout URL
- [ ] [Fetch full descriptions for the title-matched subset](#description-required) — an empty one silently defaults to English
- [ ] [Use `get_text()` + a whitespace-collapse regex](docs/lessons/adapters.md#get-text-spacing) if a field has inline tags around words

## Before touching location/language classification

- [ ] [Require an unambiguous phrase](docs/lessons/classification.md#unambiguous-phrases), not a bare word, for anything free-text
- [ ] [Bound word-gaps to one clause](docs/lessons/classification.md#clause-bounded-gaps) — stop at `.`/`;`/`<`, don't bleed across bullet points
- [ ] [Check for negation](docs/lessons/classification.md#negation-check) immediately before a phrase match, not just the match itself
- [ ] [Trust a real structured `location` exclusively](docs/lessons/classification.md#is-munich-fallback) once one exists — don't also scan free text
- [ ] [Re-validate every pattern against the new source's real fetched text](docs/lessons/classification.md#phrase-generalization) — a phrase "unambiguous" on one source isn't guaranteed to stay that way
- [ ] [Check for the requirement phrased in English too](docs/lessons/classification.md#english-german-signals), not just German prose
- [ ] [Check whether the posting is predominantly German with no explicit statement](docs/lessons/classification.md#whole-description-german) at all

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
something; there's no way to signal "unknown" downstream.

**<a name="description-required"></a>`description` is not optional in practice, even though the type allows `""`.**
`pipeline/classify_language.py` only has `description` to work with — an empty
string always classifies as English by default, *silently*. A listing/search-result
endpoint frequently only has summary fields (title/company/location); if that's all
an adapter uses, every job from that source quietly gets the wrong language bucket.
Check the source's individual job/detail page for a fuller description before
accepting `description=""` as final, narrowed to the title-matched subset (not every
raw result) to bound the extra request volume — see the `add-board-source` skill and
`docs/lessons/adapters.md`.

**Adapter interface:** `adapters/boards/<name>.py` exposes

```python
def fetch_jobs(source_config: dict) -> list[NormalizedJob]:
```

`source_config` is the source's entry from `config/sources.yaml` (a plain dict — `id`,
`adapter`, `url`, plus whatever adapter-specific fields it needs), with one key always
injected on top: `search_terms` — `keywords.yaml`'s `title_match_terms`, added by
`agents/_common.py:fetch_from_sources()` before calling the adapter. An adapter only
needs to read `search_terms` if it actually sends queries to the source.

Every HTTP call goes through `http_client.py`'s `get_with_retry()`/`post_with_retry()`
(shared retry-after-backoff on 429/5xx, one retry) — don't hand-roll a new retry loop.
`fetch_from_sources()` wraps each source's whole `fetch_jobs()` call in a
`try/except`, so one source's unhandled failure doesn't take down the others and isn't
itself retried; an adapter making many requests per call should still catch
per-request `httpx.HTTPError` internally so one bad request doesn't discard everything
else already fetched. See `docs/lessons/adapters.md` for the full reasoning.

**Registration:** adapters are looked up by name in `agents/_common.py`'s `ADAPTERS`
dict, keyed by the string used in `sources.yaml`'s `adapter:` field. An unregistered
`adapter:` value isn't an error — `fetch_from_sources()` logs a warning and skips it,
so it's safe for `sources.yaml` to carry `adapter:` values with no corresponding
module yet.

**`adapter:` `_todo` values** (`json_api_todo`/`html_scrape_todo`/`js_rendered_todo`/
`anti_bot_avoid`/`broken_todo`/`ambiguous_todo`, see `sources.yaml`'s
`meta.adapter_legend`) mark sources not yet built — informational, inert until
someone builds against them, and only as reliable as a single automated
single-page-fetch heuristic pass — see `docs/lessons/adapters.md` for when/how it was
run and the one real misclassification it produced. Re-verify per-source before
building against a `_todo` classification — see the `add-board-source` skill.

## Company-direct sourcing (ATS adapters)

`config/companies.yaml` entries need to resolve to a real ATS vendor, via
`tools/resolve_ats.py`, before `adapters/registry.py`'s `fetch_from_companies()` can
fetch anything from them. Each entry's `ats` field has four possible states:

- `null` — never been through resolution at all (a bare `name`+`url` entry).
- `"unresolved"` — resolution ran and found no careers page/vendor anywhere.
- `"custom"` — resolution found a real careers page, but no recognized vendor.
- `<vendor>` (e.g. `"greenhouse"`) — resolved to a known ATS platform.

`null` is reserved **exclusively** for "never attempted" — a real attempt always
leaves `ats` set to a vendor, `"custom"`, or the literal string `"unresolved"`, never
back to `null`. This distinction is why `tools/resolve_ats.py`'s `is_new_entry()` can
be a plain `ats is None` check, and it's what `main.py` relies on: it calls
`resolve_pending()` before every run, which resolves only genuinely new (`ats: null`)
companies automatically — so a freshly-added `companies.yaml` entry doesn't need a
manual `resolve_ats.py` run first. It does **not** retry `"unresolved"`/`"custom"`
entries on every run — re-fetching an already-attempted dead/vendor-less careers page
on every single run would add real latency for an outcome that essentially never
changes. Run `python -m tools.resolve_ats` (optionally `--force`) by hand to retry
those deliberately — see `tools/resolve_ats.py`'s `needs_resolution()` for exactly
what that targets, and the `process-new-companies` skill for the full workflow.

**Adapter interface:** `adapters/ats/<name>.py` exposes

```python
def fetch_jobs(company_config: dict) -> list[NormalizedJob]:
```

`company_config` is the company's entry from `config/companies.yaml` (`name`, `url`,
`ats`, `identifier`, plus whatever `resolve_ats.py` filled in), with `search_terms`
injected the same way board adapters get it (see above). Same `NormalizedJob`
contract, same `http_client.py` retry rule, same per-request `httpx.HTTPError`
isolation, same title-matched-subset bound on detail-page fetches for description —
everything in the board-adapter contract section above applies here too except where
noted below.

**Registration:** ATS adapters are looked up by the company's `ats:` value in
`adapters/registry.py`'s `ATS_ADAPTERS` dict — unlike board `ADAPTERS`, there's no
per-company opt-in list; every resolved company is automatically in scope. A vendor
with no adapter built (e.g. `rexx`, `teamtailor`, `dvinci`, `jazzhr`) is inert, same
as a board `_todo` entry, and not an error — `fetch_from_companies()` just returns `[]`
for it.

See `docs/lessons/ats_adapters.md` for the fetch-mechanism specifics of each built
vendor (which have a structured country field vs. which need `is_germany_relevant`/
`looks_like_a_german_location`, which need a second detail-page fetch, etc.) and the
recurring gotchas in `resolve_ats.py`'s own discovery/identifier-extraction logic.

## Agent shape

`agents/munich_local.py` and `agents/germany_remote.py` both follow the same shape:

```python
SOURCE_IDS = [...]                                   # sources.yaml ids this agent draws from
def filter_jobs(jobs: list[NormalizedJob]) -> list[NormalizedJob]: ...   # pure scope filter
def run(sources_config, keywords_config) -> list[NormalizedJob]: ...     # fetch + filter_jobs, standalone use
```

`filter_jobs()` narrows a raw job list to the agent's scope, using
`pipeline/location.py` (`filter_munich`/`filter_remote`) — pure, no I/O, reusable
without re-fetching. `main.py` fetches once via `fetch_from_sources()` with the union
of both agents' `SOURCE_IDS` rather than calling each agent's `run()` (which would
double the request volume, since both agents currently share one source list), then
calls each agent's `filter_jobs()` on the shared raw list, then dedupes the two
results by `url` before anything downstream runs. See `docs/lessons/adapters.md` for
why both of those choices matter in practice.

## Gotchas not covered by a checklist above

Every item in the two pre-task checklists already links its own "why" — restating
them here would just be the same fact twice. This section is only for gotchas that
*aren't* a checklist item anywhere in this file:

- Per-run wall time grows with every source added (each adapter's rate-limit spacing is additive across the whole run) — a long-running `main.py` isn't necessarily stuck. Full story: `docs/lessons/adapters.md`.
