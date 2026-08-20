---
name: process-new-companies
description: Resolve and verify newly added config/companies.yaml entries (name+url only) — dedupe check, run tools/resolve_ats.py, spot-check the resolved ats/identifier live, flag custom/unresolved/no-adapter-yet companies. Use whenever new companies have been added to companies.yaml, e.g. extending the Phase 6 company-direct sourcing list.
---

# Process new companies in config/companies.yaml

New entries land in `config/companies.yaml` as just `name` + `url` — no `ats`,
`identifier`, `careers_url`, `match_method`, or `resolved_at`. Those five fields are
filled in by `tools/resolve_ats.py`; see its module docstring and
`docs/lessons/ats_adapters.md` for how/why it works the way it does.

## 1. Identify which entries are new

```bash
git diff config/companies.yaml
```

Any entry with no `ats` key at all (not even `ats: null`) is unprocessed.

## 2. Check for duplicates before resolving

Compare each new `name`/`url` against the existing ~200 entries — case-insensitive
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

Default behavior only targets entries currently `ats: null`/`custom`/missing, so
already-resolved companies are untouched — safe to run after any batch of additions.
Rewrites `config/companies.yaml` in place and writes `tools/resolve_ats_report.md`.

## 4. Bucket the newly resolved entries by what needs attention

- **Resolved to one of the 6 built adapters** (`greenhouse`, `lever`, `ashby`,
  `smartrecruiters`, `personio`, `workday`) — ready to fetch immediately via
  `adapters/registry.py`'s `ATS_ADAPTERS`. No further action.
- **Resolved to a vendor with no adapter built** (`softgarden`, `recruitee`,
  `teamtailor`, `join`, `rexx`, `onlyfy`, `dvinci`, `bamboohr`, `jazzhr`) — inert,
  same as a board `_todo` entry. Worth noting if several new companies cluster on one
  vendor — may justify building that adapter next.
  - `rexx`, `dvinci`, and `jazzhr` match presence-only (no capture group), so
    `identifier` stays `null` even though `ats` is set — fill in manually from the
    live careers page if you're about to build against one of these.
- **`ats: custom`** — a real careers page was found, no recognized vendor
  fingerprint. Candidate for a future generic scraper; leave as-is otherwise.
- **`ats: null`** — no careers page found at all. Worth one manual look (wrong
  homepage URL? a Cloudflare challenge, like GetYourGuide/AnyDesk — see the module
  docstring) before accepting it as genuinely unresolved.

## 5. Spot-check the resolved matches against a live fetch

`resolve_ats.py`'s own docstring warns this is "a single automated,
unauthenticated-GET heuristic pass... re-verify a company's resolved ats/identifier
against a live fetch before trusting it." For each newly resolved company, confirm by
hand:

```bash
# greenhouse
curl -s "https://boards-api.greenhouse.io/v1/boards/<identifier>/jobs?content=true" | python3 -m json.tool | head -20
# lever
curl -s "https://api.lever.co/v0/postings/<identifier>?mode=json" | python3 -m json.tool | head -20
# ashby
curl -s "https://api.ashbyhq.com/posting-api/job-board/<identifier>" | python3 -m json.tool | head -20
# personio
curl -s "https://<identifier>.jobs.personio.de/xml" | head -20
```

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
spot-check that looked wrong). Don't commit without asking — resolution is a live
network call against real company sites, and a bad match would silently point a
future run at the wrong company's job board.
