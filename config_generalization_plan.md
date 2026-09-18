# Config generalization: swappable keywords + configurable target city

## Context

This project started as a personal QA-job search agent hardcoded to Munich + QA
roles. The user wants to publish it as a GitHub repo other people can fork and run
for their own search — without hosting, auth, or multi-tenancy (that idea was
explicitly scoped down last round). The two hardcoded assumptions standing in the
way are: (1) `config/keywords.yaml`'s `title_match_terms` only covers QA-style
roles, and (2) `pipeline/location.py`'s Munich-matching regex is a literal
`münchen|munich|muenchen` pattern with no way to point it at another city.

This round's scope, per the user's answers: make both configurable via one
swappable YAML file passed with a CLI flag; keep `sources.yaml`/`companies.yaml`
(the board/company lists) fixed and shared; rename the Munich-specific symbols to
generic "target city" names since the underlying logic is no longer Munich-only.
GitHub Actions cron is an explicitly separate follow-up — not touched here, beyond
being the reason a CLI-flag (not just an env var) override is worth having.

## Design

**Config swap mechanism** — `main.py` gets a `--keywords PATH` CLI flag. When
omitted, behavior is unchanged (`config/keywords.yaml`). When given, that file is
read directly instead. A new tiny `load_yaml_path(path: Path) -> dict` helper in
`main.py` handles the arbitrary-path case; the existing `load_yaml(name)`
(CONFIG_DIR-relative) keeps its current contract and default-path test coverage
untouched.

**City config lives in the same file as keywords** — a new `city_match_terms: list[str]`
key alongside the existing `title_match_terms` in `config/keywords.yaml`. Shipped
default: `[München, Munich, Muenchen]` (today's literal values, just moved from
Python into config). A fork wanting Hamburg swaps in their own file with their own
`title_match_terms` + `city_match_terms` and passes `--keywords their-file.yaml`.

**Threading the city terms through** — rather than introducing module-level mutable
state in `pipeline/location.py` (which would need test teardown/reset to avoid
cross-test pollution), `is_target_city()` / `filter_target_city()` take an optional
`city_match_terms: list[str] | None = None` parameter, defaulting to the module's
own `DEFAULT_CITY_MATCH_TERMS` when omitted. `agents/city_local.py`'s `filter_jobs()`
gains the same optional parameter and passes it straight through — this is a
backward-compatible, additive change to the documented "Agent shape" contract
(`filter_jobs(jobs)` still works exactly as before for any caller that doesn't pass
it), not a departure from "pure, no I/O". `main.py`'s `build_report()` is the only
caller that supplies it, from `keywords_config.get("city_match_terms")`.

User-supplied city terms get `re.escape()`'d before being joined into the regex
alternation — the hardcoded terms today don't contain regex metacharacters, but an
arbitrary user-typed city name might (e.g. a name with parentheses or a period).

**Renaming** (per the user's explicit choice — generic names over smallest-diff):
- `pipeline/location.py`: `MUNICH_PATTERN` → `DEFAULT_CITY_MATCH_TERMS` (a list, now
  compiled via a new `_compile_city_pattern()` helper); `is_munich()` → `is_target_city()`;
  `filter_munich()` → `filter_target_city()`.
- `agents/munich_local.py` → renamed to `agents/city_local.py` (same shape, calls
  `filter_target_city`).
- `main.py`: import (`from agents import city_local, germany_remote`), the
  `munich_jobs` local var → `city_jobs`, and the log line / comment wording that
  says "Munich" → generic "city-local".

**Not renamed**: `adapters/boards/munich_startup_jobs.py` stays as-is — it's a real
external board (Munich Startup Jobs) scoped to that city regardless of what a fork
configures as their target city, unrelated to the internal matching logic being
generalized. Only its comments that reference `is_munich()` by name get updated to
the new symbol name.

## Files to change

**Core logic**
- `pipeline/location.py` — rename + parameterize as above; keep the existing
  doc-comments' concrete Munich/Kirchdorf-Taufkirchen reasoning (still accurate as
  the calibration story for the *default* terms), just adjust wording from "the
  hardcoded assumption" to "the configured/default city".
- `agents/munich_local.py` → `agents/city_local.py`
- `agents/_common.py` — update the file-name reference in its module comment.
- `main.py` — `--keywords` CLI flag, `load_yaml_path()`, `build_report()`'s call
  into `city_local.filter_jobs(raw_jobs, keywords_config.get("city_match_terms"))`,
  variable/log-message renames.
- `config/keywords.yaml` — add `city_match_terms` (+ update `meta.usage`/`meta.counts`
  to document it).

**Tests** (rename to match, plus new coverage for the actual new behavior)
- `tests/test_location.py` — rename imports/tests (`is_munich` → `is_target_city`
  throughout); add a test that a custom `city_match_terms` list overrides the
  default (matches the new city, no longer matches München) and one confirming
  omitting it preserves today's default behavior.
- `tests/test_agents_shape.py` — rename `munich_local` import/test to `city_local`;
  add a test that `city_local.filter_jobs()` forwards a custom `city_match_terms`
  through to the underlying filter.
- `tests/test_main.py` — add a test that `build_report()` actually uses
  `keywords_config["city_match_terms"]` when present (e.g. a München-located job
  drops out of the report once `city_match_terms` is set to `["Hamburg"]`), and a
  test that `main()` reads from `keywords_path` via `load_yaml_path()` when given,
  instead of the default `config/keywords.yaml`.

**Docs** (same rename, referenced only in prose/comments, not exhaustively listed —
representative set below; sweep is mechanical, same find-and-rename each place)
- `README.md` — update the `agents/munich_local.py` reference; add a short
  "Customizing your search" section documenting `--keywords`, the
  `title_match_terms`/`city_match_terms` fields, and an honest caveat that spelling
  variants for a city other than the shipped Munich example may be incomplete until
  tested against real postings (same spirit as the existing
  `docs/lessons/classification.md` notes).
- `CLAUDE.md` — update the "Agent shape" section's code fence and prose to the
  renamed file/functions and the new optional `city_match_terms` parameter.
- `docs/lessons/classification.md` — rename the `is-munich-fallback` heading/anchor
  and its `is_munich()` references to `is_target_city()`.
- `.claude/skills/edit-classification/SKILL.md` — update its `is_munich`/`is_remote`
  references (frontmatter description, section 5's link + prose, section 9's code
  sample) to match.
- `docs/lessons/adapters.md` — rename the `dedupe-merge` section's
  `munich_jobs + remote_jobs` heading/anchor/prose to `city_jobs + remote_jobs`.
- `.claude/skills/add-board-source/SKILL.md`, `adapters/boards/xing_jobs.py`,
  `adapters/boards/munich_startup_jobs.py` (comment only, not the file/source
  itself), `adapters/ats/_common.py`, `job_search_agent_plan.md` — each has one or
  two comment/prose references to the old symbol or file names; update in place.

## Explicitly out of scope this round
- GitHub Actions workflow / cron — separate follow-up plan once this lands.
- `sources.yaml` / `companies.yaml` — stay fixed and shared, per earlier agreement.
- Renaming `adapters/boards/munich_startup_jobs.py` or its `sources.yaml` entry.

## Verification
1. `ruff check .` and `mypy .` — must show no errors (project's standing bar).
2. `pytest` — full suite green, including the new/renamed tests above.
3. Manual dry-run of the default path: `.venv/bin/python main.py --dry-run` —
   confirm output is unchanged from today (still Munich-scoped).
4. Manual dry-run with an override file: write a small temp YAML with
   `title_match_terms` + `city_match_terms: ["Hamburg"]`, run
   `.venv/bin/python main.py --dry-run --keywords <temp file>`, and confirm the
   printed report reflects the swapped-in city/keyword scope instead of the default.
