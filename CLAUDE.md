# job-search-agent

See `job_search_agent_plan.md` for the full build spec and phase plan.

For the *why* behind any gotcha below, see:
- `docs/lessons/adapters.md` — building/fixing a board adapter
- `docs/lessons/classification.md` — `pipeline/location.py` and `pipeline/classify_language.py`

Each source's own quirks (fetch mechanism, selectors, search-param behavior) live in
its `sources.yaml` `notes:` field, not here.

## Status

**Priority-1 board adapters: 12/12 built · Phases complete: 1-5 of 8.** This line is
the one place to update when either number changes — don't restate progress as dated
prose elsewhere in this file. Full adapter list: `sources.yaml`'s
`meta.adapter_legend`. Phase definitions: `job_search_agent_plan.md` §13.
Per-source build notes: `job_search_agent_phase5` memory (historical, not kept current).

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
