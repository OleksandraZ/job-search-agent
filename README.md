# job-search-agent

A scheduled pipeline that finds new job postings in Germany (remote) and Munich
(onsite/hybrid/remote) matching a keyword set of your choosing, splits them by the
language *required* for the role (German vs English), and sends a formatted
summary to Telegram twice a day. Fork it, point it at your own role, done — no code
changes needed to search for something other than what it ships with. Ships with
two keyword sets as working examples: QA Engineer roles (`config/keywords_qa.yaml`,
the default) and junior/associate Python roles
(`config/keywords_junior_python.yaml`) — see [Add your own search](#add-your-own-search).

**Scope that's *not* yet configurable:** the location filter is fixed to Munich +
Germany-wide-remote (`pipeline/location.py`), and the board/company source lists
(`config/sources.yaml`, `config/companies.yaml`) are fixed and Germany-focused.
Only the keyword set (what roles you're matching) is swappable today — a fork
targeting a different city or country would need code changes, not just a new
config file.

See [`CLAUDE.md`](CLAUDE.md) for the adapter contract and contribution rules used
when extending this project with an AI coding agent.

## How it works

```
fetch (boards + companies) → scope filter (Munich / Germany-remote) → title match
  → dedupe (seen before?) → language classify (DE required / EN okay) → Telegram
```

- **Sources** — `config/sources.yaml` lists job boards; `config/companies.yaml` lists
  companies sourced directly from their ATS (Greenhouse, Lever, Personio, etc). Each
  source/company resolves to an adapter under `adapters/boards/` or `adapters/ats/`
  that fetches and normalizes postings into a common `NormalizedJob` shape.
- **Agents** — `agents/munich_local.py` and `agents/germany_remote.py` each filter the
  same raw job list down to their scope (`pipeline/location.py`).
- **Pipeline** — `pipeline/filters.py` matches titles against
  `config/keywords_qa.yaml` (or whatever file `--keywords` points at),
  `storage/dedupe.py` drops jobs already sent (SQLite, `storage/jobs.db`), and
  `pipeline/classify_language.py` splits the rest into German-required vs
  English-okay.
- **Notifier** — `notifier/telegram.py` formats and sends the report.

## Setup

Requires Python 3.9+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

Create a `.env` file (git-ignored) with your Telegram bot credentials:

```
TELEGRAM_BOT_TOKEN=<your bot token>
TELEGRAM_CHAT_ID=<your chat id>
```

## Usage

```bash
# print the report instead of sending it to Telegram
python main.py --dry-run

# fetch, filter, and send today's report to Telegram (default: config/keywords_qa.yaml)
python main.py

# run against a different keyword set (e.g. the junior/associate Python search)
python main.py --keywords keywords_junior_python.yaml
```

## Add your own search

Searching for a different role doesn't need any code changes — add a new YAML file
under `config/` and point `--keywords` at it:

1. Copy an existing file as a starting template, e.g.
   `cp config/keywords_qa.yaml config/keywords_frontend.yaml`.
2. Edit `title_match_terms`: the list of job-title words/phrases to match (case-
   insensitive, whole-word — a bare `Frontend` won't match inside an unrelated
   word). This list is also sent as the search query to every board that supports
   free-text search, so keep entries to plain role/skill terms, not full sentences.
   Include both English and German titles — German postings often keep the English
   title as a loanword, but not always.
3. Optionally add `title_exclude_terms`: drop any title match that also contains
   one of these words (e.g. `Senior`, `Werkstudent`) — useful when a broad term
   like a bare skill name would otherwise pull in postings outside your target
   seniority/employment type.
4. Optionally add `report_label`: names this search in the Telegram heading
   (`New {label} jobs`) and the no-jobs message, so different searches are
   distinguishable in chat history. Defaults to `"QA"` if omitted.
5. Run it: `python main.py --dry-run --keywords keywords_frontend.yaml` to check
   the output, then drop `--dry-run` once it looks right.

Both shipped `config/keywords_*.yaml` files document this contract in their own
`meta.usage` field with real worked examples (including one real trap: a
combinatorial multi-word phrase list matched zero real postings — short, bare
terms combined with `title_exclude_terms` worked far better in practice).

To run your new search on a schedule too, add a step to
`.github/workflows/daily-job-search.yml` alongside the existing ones (see
[Scheduled runs](#scheduled-runs-github-actions) below).

## Scheduled runs (GitHub Actions)

`.github/workflows/daily-job-search.yml` runs both keyword searches twice a day
(13:00 and 19:00 Europe/Berlin) and on manual dispatch. It needs two repo secrets
(Settings → Secrets and variables → Actions):

```
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

`storage/jobs.db` (dedupe state) and `config/companies.yaml` (ATS resolution
results) are tracked in git rather than ignored, because the runner's filesystem
doesn't survive between runs — the workflow commits whatever changed back to the
repo at the end of each run so the next scheduled run sees it.

## Project layout

```
adapters/boards/   job-board adapters (fetch_jobs(source_config) -> list[NormalizedJob])
adapters/ats/      company-direct ATS adapters (fetch_jobs(company_config) -> list[NormalizedJob])
adapters/registry.py  adapter lookup + fetch_from_sources()/fetch_from_companies()
agents/            scope filters (Munich-local, Germany-remote)
pipeline/          title/location/language filtering
storage/           SQLite dedupe of already-sent jobs
notifier/          Telegram formatting + sending
config/            sources.yaml, companies.yaml, keywords_*.yaml, language_rules.yaml
tools/             resolve_ats.py — resolves companies.yaml entries to an ATS vendor
docs/lessons/      the "why" behind adapter/classification gotchas
tests/             pytest suite
```
