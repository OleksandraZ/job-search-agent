# Lessons: building ATS (company-direct) adapters

Full incident narratives behind `adapters/ats/*`. Same spirit as
`docs/lessons/adapters.md` for board sources: this file is cross-cutting lessons
that apply to *building the next ATS adapter or extending `tools/resolve_ats.py`*,
not a repeat of any one platform's specifics (those live in each adapter module's
own comments, since there's no per-company `notes:` field the way `sources.yaml`
has one per board source).

## Prefer each platform's own structured country/location field over the shared text heuristic

`adapters/ats/_common.py`'s `is_germany_relevant()` is a last-resort text guard for
platforms with no structured country field at all. Check for one before reaching for
it — verified live, four of the six platforms have one:

- Lever: `country` (ISO code, e.g. `"DE"`)
- Ashby: `address.postalAddress.addressCountry` (full name, e.g. `"Germany"`)
- SmartRecruiters: `location.country` (lowercase ISO code, e.g. `"de"`)
- Workday: `jobPostingInfo.country.descriptor` on the *detail* endpoint only (full
  name, e.g. `"Germany"`) - not present on the search/listing endpoint.

Greenhouse and Personio have no country field anywhere in their response - only a
free-text city (`location.name` / `<office>`), so those two adapters are the ones
that actually need `is_germany_relevant()`.

## Greenhouse's `content` field is HTML-entity-*double*-encoded

A live fetch (`boards-api.greenhouse.io/v1/boards/n26/jobs?content=true`) returned a
`content` string containing the literal characters `&lt;p&gt;...&lt;/p&gt;`, not real
`<p>` tags - i.e. the HTML was escaped once for storage and never unescaped in the
API response. `adapters/ats/greenhouse_api.py` runs `html.unescape()` on it before
building `NormalizedJob.description` - skipping this would leave
`classify_language.py`'s `<` tag-boundary guard never seeing a real tag boundary (see
`docs/lessons/classification.md#clause-bounded-gaps`). Lever and Ashby's HTML fields
did **not** have this problem (real tags, verified live) - don't assume every
platform needs the same unescape step.

## Workday's search endpoint 400s above `limit: 20` - undocumented, found by testing

`POST .../wday/cxs/{tenant}/{site}/jobs` with `"limit": 100` returns HTTP 400 with an
opaque `{"errorCode":"HTTP_400", ...}` body (no message explaining why). `"limit": 20`
succeeds, `25` and `50` both 400 - the cap is exactly 20, tested directly against a
real tenant (Airbus). `adapters/ats/workday_api.py`'s `SEARCH_PAGE_SIZE = 20` plus
`_search_all_pages()`'s offset-based pagination (capped at `MAX_PAGES_PER_TERM = 5`
as a runaway-loop guard) work around this - don't raise `SEARCH_PAGE_SIZE` without
retesting the real cap, it isn't documented anywhere Workday publishes.

## Workday's location-facet shape is not consistent across tenants

Verified live against two real companies:

- **Airbus** (`ag.wd3.myworkdayjobs.com`) exposes a clean country-level
  `locationCountry` sub-facet - one `"Germany"` entry covers every German office in
  one filter value.
- **Roche** (`roche.wd3.myworkdayjobs.com`) has no country-level grouping at all,
  only a flat city+country `locations` sub-facet. Its German offices are split
  across per-city entries (`Mannheim`: 46 jobs, `Penzberg`: 51, `Grenzach`: 8) plus a
  near-empty literal `"Germany"` entry (1 job) - filtering on the literal `"Germany"`
  descriptor alone would have silently dropped 105 of 106 real German postings.

`adapters/ats/workday_api.py`'s `_collect_germany_facet_ids()` handles this by
scanning *every* sub-facet under `locationMainGroup` (not assuming a fixed
`facetParameter` name) and collecting any entry whose descriptor matches a German
city/country name (`_common.py`'s `looks_like_a_german_location()` - a **strict**
variant with no default-true fallback, unlike `is_germany_relevant()`; see below for
why that distinction matters), then applies all matched ids as one OR'd
`appliedFacets` filter. Known residual gap: a German office in a town not in
`GERMANY_HINTS` (Penzberg and Grenzach themselves aren't) still won't be pre-selected
by the facet filter - the detail-endpoint `country.descriptor` check on the
title-matched subset (see next section) is what actually catches those, not the
facet step.

## Two different default biases for the same city-name heuristic, by design

`_common.py` has two functions built on the same `GERMANY_HINTS`/`NON_GERMANY_HINTS`
regexes but with opposite defaults for an unmatched/ambiguous string:

- `is_germany_relevant()` defaults **True** (keep) on an ambiguous string. Used to
  gate a single job's own location text - an unmatched case (e.g. a bare `"Remote"`,
  or a small town not in either hint list) is a harmless miss, since downstream
  Munich/remote filtering narrows further anyway.
- `looks_like_a_german_location()` defaults **False** (exclude) - strict, no
  fallback. Used only by `workday_api.py` to pick which of a company's *many* (often
  hundreds, spanning every country the company hires in) location-facet entries to
  select as an OR filter. A default-true bias there would include most of the
  world's cities by default, defeating the filter entirely - confirmed empirically:
  Roche's flat `locations` facet has entries like `"Almaty"`, `"Ankara"`, `"Baku"`
  that `is_germany_relevant()` alone (neither hint list matches them) would happily
  keep.

Don't reuse one function in the other's context - the two use cases need opposite
defaults for the same "unmatched" outcome.

## Workday's detail-endpoint `country.descriptor` is the real backstop, not the facet filter

Because the facet-selection step above is a best-effort heuristic (and can under- or
in principle over-select), `workday_api.py` treats it only as a *volume-bounding*
pre-filter, not the final word. Every title-matched candidate still gets its detail
page fetched (bounded to that subset, same rule as the board adapters), and the
detail response's `jobPostingInfo.country.descriptor` is checked directly - a job is
dropped if that field disagrees with "Germany", regardless of what the facet filter
let through. This is the one authoritative signal that's consistent across every
Workday tenant seen so far, unlike the facet shape.

## SmartRecruiters' listing endpoint has no description at all - and no reliable "search" either

`GET .../v1/companies/{id}/postings` returns full structured fields (title,
location, id) but **zero** description text anywhere in the response - confirmed
live (`sorted(job.keys())` has no `jobAd`/`description` field). The full description
only exists on the *detail* endpoint (`.../postings/{id}`), under
`jobAd.sections.{companyDescription,jobDescription,qualifications,...}.text` - real
HTML, no unescaping needed (unlike Greenhouse). `adapters/ats/smartrecruiters_api.py`
fetches this only for the title-matched subset, same bounding rule as every other
adapter's detail-page fetch.

Also worth noting: `postingUrl` only appears on the *detail* response, but a stable
public URL can be built directly from listing data alone -
`https://jobs.smartrecruiters.com/{identifier}/{posting id}` resolves without the
slug suffix (verified live) - so `NormalizedJob.url` doesn't have to depend on a
successful detail fetch the way the description does.

## `tools/resolve_ats.py`'s regex identifier extraction needs mandatory-literal patterns, not optional groups

An early version matched Greenhouse's slug with one pattern using an optional
`(?:v1/boards/)?` group. A real page (commercetools's careers page) contained the
literal text `boards-api.greenhouse.io/v1/boards/` followed immediately by a JS
template variable (the real slug injected client-side at runtime, not present in the
static HTML at all). With the optional group, regex backtracking matched `"v1"`
itself as a bogus identifier instead of the whole pattern simply failing to match -
`boards-api.greenhouse.io/v1/boards/v1/jobs` genuinely 404s. Fixed by splitting into
two separate mandatory-literal patterns (`.../v1/boards/(slug)` and
`boards\.greenhouse\.io/(slug)` tried independently) so a partial match with no real
slug present fails outright rather than backtracking into a substring of its own
literal text. See `tests/test_resolve_ats.py`'s
`test_greenhouse_v1_boards_prefix_with_no_real_slug_does_not_false_positive` for the
regression test.
