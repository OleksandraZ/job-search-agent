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
it — verified live, most platforms have one:

- Lever: `country` (ISO code, e.g. `"DE"`)
- Ashby: `address.postalAddress.addressCountry` (full name, e.g. `"Germany"`)
- SmartRecruiters: `location.country` (lowercase ISO code, e.g. `"de"`)
- Workday: `jobPostingInfo.country.descriptor` on the *detail* endpoint only (full
  name, e.g. `"Germany"`) - not present on the search/listing endpoint.
- Workable: `country` (full name, e.g. `"Germany"`) on the widget listing endpoint
  directly, no separate detail fetch needed for this field.
- Recruitee: `country_code` (ISO, e.g. `"DE"`) on every one of 187 real postings
  checked live against AVEDO - no fallback needed in practice.
- join.com: `country.iso3166` (ISO, e.g. `"DE"`) in the `__NEXT_DATA__` initial
  state, both listing and detail.
- BambooHR: two separate sub-objects, neither populated on every posting
  (`atsLocation.country` and `location.addressCountry`) - check both, prefer
  `atsLocation` when both are present (verified live against Bragi).

Greenhouse, Personio, softgarden, onlyfy, and rexx have no country field anywhere -
those need `is_germany_relevant()` or (see below) the stricter
`looks_like_a_german_location()`.

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

## `ats: null` means exactly one thing: never attempted - not "attempted, found nothing" too

Early on, a failed resolution attempt and a never-attempted entry were both stored as
`ats: null` - indistinguishable from each other without also checking `resolved_at`.
That ambiguity broke `main.py`'s pre-run auto-resolve: it should only ever resolve
*new* companies automatically (cheap, always safe), never retry a company that was
already tried and genuinely has no discoverable vendor (expensive - a full
homepage+career-page+probe crawl - and re-fetching the same dead page on every single
run adds real, avoidable latency for an outcome that essentially never changes).

Fixed by giving "attempted, found nothing" its own real value, `ats: "unresolved"`
(see the `UNRESOLVED` constant), so `is_new_entry()` can be a plain `ats is None`
check instead of also inspecting `resolved_at`. `needs_resolution()` (the CLI's own
manual-retry filter) still treats `null`/`"unresolved"`/`"custom"` the same way -
worth another shot by hand, since a company's own site can change - but
`resolve_pending()` (what `main.py` calls automatically) only ever touches `null`.
Migrating existing data required a one-off pass converting every already-attempted
`ats: null` (i.e. one with a `resolved_at` stamp) to `ats: "unresolved"` - a fresh
`companies.yaml` won't need this, but a hand-edited one that sets `ats: null`
explicitly on an already-tried company would reintroduce the ambiguity.

## A page can carry more than one match for the same ATS pattern - the vendor's own tracking subdomain, not just the company's

Several platforms inject their own analytics/widget subdomain on every page they
host, and it happens to share the exact same `<slug>.<vendor>.<tld>` shape as the
real per-company board - `_match_signature()`'s first-match-wins regex search picked
the tracker instead of the real company, silently, for a meaningful chunk of
companies:

- Softgarden injects `matomo.softgarden.io` (its own analytics) *before* the real
  `cqse.softgarden.io` reference on CQSE's careers page (and `certificate.softgarden.io`
  on FitX's - the exact shared subdomain isn't consistent across companies, only the
  pattern of "some noise subdomain shows up first" is).
- Recruitee injects `careers-analytics.recruitee.com` before the real company slug on
  every Recruitee-hosted page seen so far (AVEDO, koenig.solutions, Dorow Clinic,
  Leonardo Hotels all showed this).
- SmartRecruiters injects `oneclick-ui.smartrecruiters.com` the same way (R+V
  Versicherung, Assystem Germany, HE Space Operations).

Fixed by collecting *every* regex match on the page (`pattern.finditer`, not
`.search()`) and preferring whichever candidate's slug fuzzy-matches the company name
via `_names_match()` (already used elsewhere for active-probe verification), falling
back to the first match only when none do - same default-permissive bias as the rest
of this file (a real signal is never discarded outright). The fallback case is a real
residual gap: for koenig.solutions/Dorow Clinic/Leonardo Hotels/FitX, the tracker
subdomain is the *only* match anywhere in static HTML, so the wrong identifier still
gets stored. Verified this fails safe rather than silently wrong, though: fetching
`careers-analytics.recruitee.com/api/offers/` 403s, and
`oneclick-ui.smartrecruiters.com`'s postings endpoint 200s with `totalFound: 0` -
either way the adapter just returns zero jobs for that company, never another
company's data. See `tests/test_resolve_ats.py`'s
`test_prefers_name_matching_identifier_over_a_shared_tracking_subdomain` and
`test_falls_back_to_first_match_when_no_candidate_matches_the_company_name`.

**Practical implication:** re-checking `needs_resolution()`/`resolve_pending()`
against companies that *already* have a non-null `ats` and non-null `identifier`
won't happen automatically even after a bug like this is fixed - both functions treat
"has an identifier" as "fully resolved," with no way to tell a real slug from a wrong
one. Force-resolving specific companies by name (`resolve_all([...])` on a filtered
list) is the way to retroactively fix already-"resolved" bad data; a full
`--force` re-run works too but re-fetches everything, including the companies that
were already correct.

## A discovered career link is often just a marketing hub, not where the ATS embed lives

`resolve_ats.py` used to try each discovered/guessed career-page candidate exactly
once and move on if it had no signature. That's not deep enough for a real, common
pattern: a company's own "Karriere"/"Careers" nav link often leads to a marketing/
culture hub page (team photos, benefits copy) with **zero** ATS references anywhere,
and the actual job-listing page - where the ATS is really embedded - is one click
further, reached via a link like "See our open roles" that doesn't contain the words
"career"/"job"/"karriere" at all. Verified live against Taxfix: its `/en/careers/`
hub page (370KB of HTML) has no Ashby reference anywhere; the real embed is on
`/en/job-openings/`, reached via that hub page's "See our open roles" link.

Fixed with a second, distinct link pattern (`JOB_LISTING_LINK_PATTERN`, deliberately
*not* merged into `CAREER_LINK_PATTERN` - terms like bare "role"/"opening" are too
generic to risk matching an unrelated homepage link) used only as a second hop: if a
top-level candidate 200s but has no signature, scan *it* for a job-listing-style link
and try that too. See `tests/test_resolve_ats.py`'s
`test_second_hop_finds_ats_signature_on_a_job_listing_page_linked_from_a_bare_career_hub`.

This also motivated `_find_matching_links()` returning *every* match on a page
instead of just the first (`_find_career_link()`'s old behavior) - Taxfix's own
homepage has an earlier, unrelated link ("Personen mit Zweitjob", a blog post about
second-job tax brackets) that matched `CAREER_LINK_PATTERN` before the real
"Karriere" link, so the real link was never even tried under the old first-match-wins
version.

## Softgarden has (at least) two distinct domain conventions, and a hardcoded locale path silently drops companies with no English site

Two confirmed-live URL shapes for the same platform: `<slug>.softgarden.io`
(PASSAUER WOLF) and `<slug>.career.softgarden.de` (Sunfire) - the original
fingerprint regex only covered the first, so every company on the second shape
resolved to `custom` regardless of anything else being right. `resolve_ats.py`'s
pattern now covers both (`([a-z0-9-]+)\.(?:career\.)?softgarden\.(?:io|de)`).

Separately, `adapters/ats/softgarden_scrape.py` first hardcoded `/en/vacancies` as
the listing path - works for CQSE/PASSAUER WOLF, but 404s for a company with no
English locale configured at all (verified live: Donner & Reuschel and RTLZWEI, both
German-only, 404 on `/en/vacancies` but redirect their bare root to `/de/vacancies`
successfully). Fixed by requesting the bare root and following the redirect
(`get_with_retry`'s `follow_redirects=True`) to whichever locale the company actually
has - the `/job/<id>/<slug>` link structure is identical either way, only the visible
title language differs. See
`tests/test_ats_softgarden.py::test_requests_the_bare_root_not_a_hardcoded_english_locale`.

The `.career.softgarden.de` shape (Sunfire) still isn't handled by the adapter at
all - its connection to softgarden is entirely client-side JS with zero trace in any
statically-fetched page (including the discovered career-hub link, which is
self-referential - it points back to the same page rather than to a real listing
page), so there was nothing to build against. `softgarden_scrape.py`'s
`LISTING_URL_TEMPLATE` only targets `.io`; a company resolved on the `.de` domain
shape currently yields zero jobs from the adapter rather than guessing at an
unverified structure.

## Build the location display string only *after* confirming the country, not before

Two adapters (`workable_api.py`, `onlyfy_scrape.py`) initially built the
user-facing `location` string (`f"{city}, Germany"`) *before* checking whether the
job was actually Germany-based, then fed that already-"Germany"-suffixed string into
the fallback text-heuristic check. `is_germany_relevant()`/`looks_like_a_german_location()`
both do a substring search for "germany" - so a string that already contains the
literal word "Germany" (because the code just appended it, unconditionally) always
passes the check, regardless of the real city. Caught two different ways: a unit test
(`test_falls_back_to_location_guard_when_country_missing` in
`tests/test_ats_workable.py`) for Workable, and a live-data mismatch for Onlyfy - a
real ARRK Engineering posting in Hefei, China got labeled `"Hefei, Germany"`. Fix in
both cases: check the raw city (or whatever raw field) for germany-relevance first,
and only build the display string with the "Germany" suffix after that check passes.

## A bare city-name list with no country field at all needs the *strict* location guard, not the default-permissive one

Extends the "two different default biases" section above: `is_germany_relevant()`'s
default-true-on-ambiguous bias is fine when there's *some* other structured signal
narrowing things (a real `country` field that's just occasionally empty, e.g.
Workable/BambooHR) - an unmatched city is a rare, harmless edge case. It's the wrong
tool when a bare city name is the *only* signal for every single posting, with no
narrowing elsewhere - onlyfy's listing page has no country field whatsoever, and a
real live board (ARRK Engineering) mixes German and non-German cities (Munich next to
Hefei, China) with nothing else to tell them apart. `onlyfy_scrape.py` uses
`looks_like_a_german_location()` (strict, no default-true fallback) for exactly this
reason - same underlying justification `workday_api.py`'s facet-selection already
established. Known tradeoff, same as documented above for Workday: a real German
office in a small town not in `GERMANY_HINTS` (e.g. Garching, Neufahrn bei
Freising - both real ITM Isotope Technologies Munich locations) won't be picked up.
Worth revisiting `GERMANY_HINTS`'s city list if this bites again.

## rexx isn't a centralized per-slug service - some ATS platforms can't get one shared adapter at all

Every company resolved to `rexx` has `identifier: null` because `resolve_ats.py`'s
rexx pattern is presence-only (no capture group) - and that's not a gap in the regex,
it's because there's genuinely no per-company slug to capture. Verified live against
three real rexx-hosted career sites (Dataport, CANCOM, iteratec): rexx is fully
white-labeled onto each company's *own* domain, using a generic branded CSS/JS
framework ("rexx-kit") with no `<company>.rexx-systems.com`-style subdomain, no
centralized API, and no discoverable per-company identifier anywhere in the page.
Each company's own site has its own jQuery-autocomplete search endpoints (e.g.
`karriere.dataport.de/jobsearch-jajax0.php`), which might be scrapeable per company
but aren't a shared pattern one adapter could cover the way `<slug>.lever.co` does
for every Lever customer. Left unregistered in `ATS_ADAPTERS` rather than guessed at
- would need per-company reverse-engineering, not a generic slug-based adapter.

## Some job-detail pages are entirely client-rendered with no fallback API - description stays empty, same as Arbeitnow

`onlyfy_scrape.py`'s listing page is server-rendered (title/location visible in
static HTML via `data-testid` attributes), but its job *detail* page renders via
Next.js App Router RSC streaming (`self.__next_f.push(...)`) with the actual
description text nowhere in the initial HTML and no discoverable fallback API
(checked for `__NEXT_DATA__`, `/api/`, and `/_next/data/` references - none found).
join.com looked the same at first (also Next.js) but turned out fine - it uses the
older pages-router `__NEXT_DATA__` script tag instead, which embeds the *entire*
Redux-style initial state (including the full job description) as parseable JSON, no
extra request needed. Don't assume "Next.js" implies either shape; check the actual
page for `__NEXT_DATA__` vs. `self.__next_f` before deciding a description is
unreachable. Where it genuinely is (onlyfy), `description=""` is accepted as a known,
documented limitation - same precedent as Arbeitnow (see
`docs/lessons/classification.md`) - not worth a Playwright dependency for two
companies.
