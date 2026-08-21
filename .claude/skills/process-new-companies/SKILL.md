---
name: process-new-companies
description: Resolve and verify newly added config/companies.yaml entries (name+url only) — dedupe check, run tools/resolve_ats.py, spot-check the resolved ats/identifier live, flag custom/unresolved/no-adapter-yet companies. Use whenever new companies have been added to companies.yaml, e.g. extending the company-direct sourcing list.
---

# Process new companies in config/companies.yaml

New entries land in `config/companies.yaml` as just `name` + `url` — no `ats`,
`identifier`, `careers_url`, `match_method`, or `resolved_at`. Those five fields are
filled in by `tools/resolve_ats.py`; see its module docstring, `CLAUDE.md`'s
"Company-direct sourcing" section, and `docs/lessons/ats_adapters.md` for how/why it
works the way it does.

**`main.py` already auto-resolves brand-new entries before every run** (via
`resolve_pending()`), so this skill isn't strictly required before the next scheduled
run picks a new company up. It's for doing that resolution *now* — to verify it
worked, spot-check the result, and catch a bad match before it silently sits in
`companies.yaml` — rather than waiting and hoping.

## 1. Identify which entries are new

```bash
git diff config/companies.yaml
```

`ats: null` means exactly "never attempted" (nothing else is stored as `null` -
see `CLAUDE.md`) - any entry with `ats: null` or no `ats` key at all is unprocessed.

## 2. Check for duplicates before resolving

Compare each new `name`/`url` against the existing ~600 entries — case-insensitive
name match, and the same domain-label-stripping `resolve_ats.py`'s
`_slug_candidates`/`_normalize_name` use (drop `www`/`de`/`en`/etc., compare the
remaining label). A duplicate wastes a resolution request, and if it resolves to a
different `identifier` than an existing entry for the same real company, double-fetches
the same jobs. Not a correctness bug downstream — `storage/jobs.db` dedupes by job
`url`, not by company — but still worth flagging rather than silently absorbing.

## 3. Run resolve_ats.py — no `--force`

```bash
.venv/bin/python -m tools.resolve_ats
```

Default behavior (`needs_resolution()`) targets `ats: null`/`"unresolved"`/`"custom"`,
so already-resolved companies are untouched — safe to run after any batch of
additions. Rewrites `config/companies.yaml` in place and writes
`tools/resolve_ats_report.md`.

## 4. Bucket the newly resolved entries by what needs attention

Built adapters (ready to fetch immediately via `adapters/registry.py`'s
`ATS_ADAPTERS` — check that dict directly for the current list, don't trust a
hand-maintained count here): `greenhouse`, `lever`, `ashby`, `smartrecruiters`,
`personio`, `workday`, `workable`, `recruitee`, `softgarden`, `bamboohr`, `join`,
`onlyfy`.

- **Resolved to a built vendor above** — no further action, will fetch on the next
  run.
- **Resolved to a vendor with no adapter** (`rexx`, `teamtailor`, `dvinci`,
  `jazzhr`) — inert, same as a board `_todo` entry. `rexx` in particular isn't
  buildable as one shared adapter at all - see the "rexx isn't a centralized
  per-slug service" lesson in `docs/lessons/ats_adapters.md` before spending time on
  it. Worth noting if several new companies cluster on `teamtailor`/`dvinci`/`jazzhr`
  — may justify building that adapter next.
- **`ats: "custom"`** — a real careers page was found, no recognized vendor
  fingerprint. Leave as-is unless you're deliberately building a generic scraper.
- **`ats: "unresolved"`** — no careers page found at all. Worth one manual look
  (wrong homepage URL? a Cloudflare challenge, like GetYourGuide/AnyDesk — see the
  module docstring) before accepting it as genuinely unresolvable.

## 5. Spot-check the resolved matches against a live fetch

`resolve_ats.py`'s own docstring warns this is "a single automated,
unauthenticated-GET heuristic pass... re-verify a company's resolved ats/identifier
against a live fetch before trusting it." **This matters even when `identifier` is
non-null** — several vendors (softgarden, recruitee, smartrecruiters) have been
caught extracting the platform's own shared analytics/widget subdomain instead of the
real company slug (e.g. `matomo.softgarden.io`, `careers-analytics.recruitee.com`) -
see the "shared tracking subdomain" lesson in `docs/lessons/ats_adapters.md`. A
non-null identifier is not the same as a *correct* one; `needs_resolution()` has no
way to detect this automatically, so it won't get retried on its own.

For each newly resolved company, confirm by hand:

```bash
# greenhouse
curl -s "https://boards-api.greenhouse.io/v1/boards/<identifier>/jobs?content=true" | python3 -m json.tool | head -20
# lever
curl -s "https://api.lever.co/v0/postings/<identifier>?mode=json" | python3 -m json.tool | head -20
# ashby
curl -s "https://api.ashbyhq.com/posting-api/job-board/<identifier>" | python3 -m json.tool | head -20
# personio
curl -s "https://<identifier>.jobs.personio.de/xml" | head -20
# workable
curl -s "https://apply.workable.com/api/v1/widget/accounts/<identifier>?details=true" | python3 -m json.tool | head -20
# recruitee
curl -s "https://<identifier>.recruitee.com/api/offers/" | python3 -m json.tool | head -20
# smartrecruiters
curl -s "https://api.smartrecruiters.com/v1/companies/<identifier>/postings" | python3 -m json.tool | head -20
# bamboohr
curl -s "https://<identifier>.bamboohr.com/careers/list" | python3 -m json.tool | head -20
# softgarden — no plain-JSON endpoint, check the listing HTML has real /job/ links
curl -sL "https://<identifier>.softgarden.io/" | grep -o '/job/[0-9]*' | head -5
```

`join` and `onlyfy` don't have a curl-friendly check — `join`'s data is embedded JSON
in a `__NEXT_DATA__` script tag, `onlyfy`'s in `data-testid` HTML attributes; use
step 6's real-fetch check instead for those two.

Check that the returned company name actually matches. Treat `match_method:
api_probe` results as the least trustworthy — for lever/ashby/personio there's no
company-name field to cross-check even during resolution itself (see
`resolve_ats.py`'s `_probe_lever`/`_probe_ashby`/`_probe_personio` comments), so a
probe match is trusting response *shape* alone.

## 6. Do one real fetch for the newly resolved companies

```bash
.venv/bin/python -c "
from adapters.registry import ATS_ADAPTERS
import yaml
companies = yaml.safe_load(open('config/companies.yaml'))['companies']
keywords = yaml.safe_load(open('config/keywords.yaml'))
new = [c for c in companies if c['name'] in {'<new company names>'}]
for c in new:
    fetch = ATS_ADAPTERS.get(c['ats'])
    jobs = fetch({**c, 'search_terms': keywords['title_match_terms']}) if fetch else []
    print(c['name'], c['ats'], len(jobs))
"
```

Confirms the identifier is real and the adapter actually returns jobs for this
company, not just that resolution "succeeded" — the same bias toward a real run over
a dry-run trust exercise as adding a board adapter (see the
`feedback_realsend_perboard` memory).

## 7. Lint, then report

`ruff check .` and `mypy .` must show no errors (per `CLAUDE.md`). Report to the user:
how many new companies, the count in each bucket from step 4, and anything that needs
manual follow-up (duplicate, no-adapter-yet vendor, `custom`, unresolved, or a
spot-check that looked wrong — including a *non-null* identifier that turned out
wrong). Don't commit without asking — resolution is a live network call against real
company sites, and a bad match would silently point a future run at the wrong
company's job board.
