# job-search-agent

A scheduled pipeline that finds new QA Engineer job postings in Germany (remote) and
Munich (onsite/hybrid/remote), splits them by the language *required* for the role
(German vs English), and sends a formatted summary to Telegram once a day.

See [`job_search_agent_plan.md`](job_search_agent_plan.md) for the full build spec and
phase plan, and [`CLAUDE.md`](CLAUDE.md) for the adapter contract and contribution
rules used when extending this project with an AI coding agent.

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
  `config/keywords.yaml`, `storage/dedupe.py` drops jobs already sent (SQLite,
  `storage/jobs.db`), and `pipeline/classify_language.py` splits the rest into
  German-required vs English-okay.
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

# fetch, filter, and send today's report to Telegram
python main.py
```

## Project layout

```
adapters/boards/   job-board adapters (fetch_jobs(source_config) -> list[NormalizedJob])
adapters/ats/      company-direct ATS adapters (fetch_jobs(company_config) -> list[NormalizedJob])
adapters/registry.py  adapter lookup + fetch_from_sources()/fetch_from_companies()
agents/            scope filters (Munich-local, Germany-remote)
pipeline/          title/location/language filtering
storage/           SQLite dedupe of already-sent jobs
notifier/          Telegram formatting + sending
config/            sources.yaml, companies.yaml, keywords.yaml, language_rules.yaml
tools/             resolve_ats.py — resolves companies.yaml entries to an ATS vendor
docs/lessons/      the "why" behind adapter/classification gotchas
tests/             pytest suite
```
