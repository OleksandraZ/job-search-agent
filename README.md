# job-search-agent

[![Tests](https://github.com/OleksandraZ/job-search-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/OleksandraZ/job-search-agent/actions/workflows/tests.yml)
[![Daily job search](https://github.com/OleksandraZ/job-search-agent/actions/workflows/daily-job-search.yml/badge.svg)](https://github.com/OleksandraZ/job-search-agent/actions/workflows/daily-job-search.yml)

A pipeline that runs every morning on **GitHub Actions**. It collects new job
postings in Munich and remote roles across Germany from job boards and hundreds of
company career pages, keeps the ones matching your keywords, drops ones it has already
sent, sorts the rest by whether the role **requires German**, and posts the result to
Telegram. The role is just a YAML file: QA, Python, Cloud/DevOps and Data Engineering
sets are included, and [adding your own](#use-it-for-your-own-search) needs no code changes.

<img src="docs/img/telegram-sample.png" alt="A daily Telegram report: three English-speaking QA jobs and one German-speaking job, the last also found on arbeitsagentur.de" width="520">

## Highlights

- **Sorting by required language, not the language of the ad.** A German ad that
  says "Deutschkenntnisse von Vorteil" is still fine for English speakers, and an
  English ad can still require C1 German. See [The language classifier](#the-language-classifier).
- **Many sources, one contract.** Every job board and ATS vendor (Greenhouse, Lever,
  Personio, Workday...) has its own adapter, and each converts its data into the
  same `NormalizedJob` shape, so the rest of the pipeline doesn't know where a job came from.
- **Each job is sent once.** The same posting on three boards, under a new tracking
  URL, or listed for another city is recognized and merged into one entry
  (`also on: …`), and isn't sent again for 90 days.
- **The company list maintains itself.** A weekly workflow re-checks every company's
  careers page and moves companies in or out of the fetch list when their ATS changes
  or their endpoint dies.
- **Every lesson is written down.** Real bugs and the reasoning behind each fix are in
  [`docs/lessons/`](#lessons-learned).

## How it's tested

260+ pytest tests run on every push ([`tests.yml`](.github/workflows/tests.yml)),
together with `ruff` and `mypy`. They're **fully offline**: HTTP calls are replaced
with stubbed responses shaped like the real payloads, so the suite runs in about a
second and never fails because a job board is down.

| Area | What the tests protect |
|---|---|
| Adapters (boards + ATS) | Each source's payload is mapped correctly into `NormalizedJob`; non-German locations are dropped; one failed request doesn't throw away the rest |
| Location + language classification | Munich/remote detection, German-requirement phrases, optional-language wording, negation |
| Filters | Whole-word title matching, excluded terms, required skills, maximum years of experience |
| Dedupe | Already-sent jobs stay out; reposts across boards/URLs are merged into one entry |
| Company resolution | ATS vendor detection and identifier extraction from careers pages; moves between the two company files |
| Infrastructure | Retry on 429/5xx, Telegram message splitting, config file validation |

Most classification and filter tests are **regression tests for bugs that reached a
real Telegram message**. For example, the title keyword `SDET` matched inside
"Emsdetten" (a German town) and sent a tax-clerk job as a QA role. Title matching
has used whole words since then, and a test pins that down
([`tests/test_filters.py`](tests/test_filters.py)).

## The language classifier

[`pipeline/classify_language.py`](pipeline/classify_language.py) uses rules, not an
LLM. The output feeds a daily decision about which jobs to apply for, so it needs to
be predictable, free to run and testable. Every rule in
[`config/language_rules.yaml`](config/language_rules.yaml) traces back to a real
posting it got wrong. It runs two checks:

1. **Explicit requirement.** Regexes for German-requirement phrases in both languages
   ("Deutsch C1", "verhandlungssichere Deutschkenntnisse", "fluent German"). A
   match doesn't count if optional wording ("von Vorteil", "nice to have", "a plus")
   follows **in the same clause**. Word gaps stop at `.`, `;` and HTML tags, so an
   optional phrase in one bullet point can't cancel a requirement in the next.
2. **Whole-description fallback.** If no phrase matches, it counts common German and
   English words. An ad written mostly in German (≥15 German words, ≥60% ratio)
   counts as German-required even if it never says so.

| Description | Result | Why |
|---|---|---|
| `Deutschkenntnisse B2 von Vorteil, aber nicht zwingend.` | English | German mentioned, but marked optional in the same clause |
| `Gute Deutschkenntnisse, Englisch von Vorteil.` | German | The optional wording applies to English, not German |
| `Deutschkenntnisse (B2). Andere Skills sind von Vorteil…` | German | "von Vorteil" is in the next sentence, so it doesn't apply |
| An ad written entirely in German with no language requirement stated | German | Fallback: 0.91–0.94 German word ratio on real samples vs 0.00 for an English ad |

## Lessons learned

[`docs/lessons/`](docs/lessons/) records about 40 real bugs and surprises found while
building this: what happened, how it was found and the rule that came out of it.

- [`classification.md`](docs/lessons/classification.md): the regex false positives
  behind the classifier, e.g. an optional phrase in one bullet point cancelling a
  real German requirement in the bullet next to it.
- [`adapters.md`](docs/lessons/adapters.md): building board adapters, e.g. a site
  whose `robots.txt` explicitly allows AI crawlers while its firewall blocks them
  anyway (treated as "don't scrape", not "work around it"), and search boxes that
  ignore the query.
- [`ats_adapters.md`](docs/lessons/ats_adapters.md): company career pages, e.g.
  Workday's search endpoint returning 400 above an undocumented page size of 20, and
  Greenhouse descriptions that are HTML-escaped twice.

## Use it for your own search

**What you can change without touching code:** the roles you search for, set in one
YAML file of keywords. **What's fixed:** the location (Munich, plus remote jobs anywhere
in Germany) and the list of job boards and companies, which are Germany-focused. Searching
another city or country would need code changes.

You need Python 3.13+, a Telegram account and about 15 minutes. Expect the first run to
take a while (see step 6).

### 1. Get the code

Fork the repo on GitHub if you want it to run daily (see
[Run it every day](#run-it-every-day-on-github-actions)), or just clone it to run it on
your machine:

```bash
git clone https://github.com/<your-username>/job-search-agent.git   # or OleksandraZ/... if you didn't fork
cd job-search-agent
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Start with an empty history

`storage/jobs.db` remembers every job already sent, so nothing is sent twice. The copy
in the repo holds the original author's history: keep it and you'll never see jobs
they already got. Delete it, and a fresh one is created on your first real run:

```bash
rm storage/jobs.db
```

### 3. Create your Telegram bot

1. In Telegram, open [@BotFather](https://t.me/BotFather), send `/newbot` and follow
   the prompts. It replies with a **bot token** like `123456789:AAE...`.
2. Open a chat with your new bot and press **Start** (a bot can't message you until
   you've written to it first). Send it any message, e.g. `hi`.
3. Open `https://api.telegram.org/bot<your token>/getUpdates` in a browser and find
   `"chat":{"id":123456789,...}`. That number is your **chat ID**. If the page shows
   `"result":[]`, send the bot another message and reload.
4. Create a file named `.env` in the project folder (it's git-ignored, so your token
   never gets committed):

   ```
   TELEGRAM_BOT_TOKEN=123456789:AAE...
   TELEGRAM_CHAT_ID=123456789
   ```

### 4. Describe your search

Create a file in `config/`, e.g. `config/keywords_frontend.yaml`. Only
`title_match_terms` is required:

```yaml
report_label: Frontend        # shown in the message: "New Frontend jobs"
title_match_terms:            # a job is kept if its title contains one of these words
  - Frontend
  - Front-End
  - React Developer
  - Frontend-Entwickler       # add the German titles too
```

Run it once (step 5), look at what comes back, then tighten it with the optional
filters in the [keywords file reference](#keywords-file-reference), e.g. drop `Senior`
roles or require a specific skill. The four shipped `config/keywords_*.yaml` files are
worked examples of every option.

### 5. Try it without sending anything

```bash
python main.py --keywords keywords_frontend.yaml --dry-run
```

This prints the message instead of sending it, and doesn't record anything as seen,
so you can repeat it as often as you like while tuning your keywords.

### 6. Send it for real

```bash
python main.py --keywords keywords_frontend.yaml
```

**How long it takes:** anywhere from 20 minutes to 2–3 hours. It queries every
job board and several hundred company career pages, and reads the full description of
every job whose title matches. Broad terms like `Software Engineer` match many titles
and make the run much longer. It logs its progress the whole time, so a long quiet
stretch isn't a hang.

The jobs you're sent are recorded in `storage/jobs.db` and won't be sent again for 90
days, so the next run only shows new ones.

### Run it every day on GitHub Actions

Your fork already contains the daily workflow. To switch it on:

1. **Commit your changes** (your keywords file and the deleted `storage/jobs.db`) and
   push them to your fork.
2. **Add your Telegram credentials as secrets.** In your fork go to Settings → Secrets
   and variables → Actions → *Secrets* → New repository secret, and add
   `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. **Choose your search.** On the same page open the *Variables* tab and add
   `KEYWORDS_FILE` = `keywords_frontend.yaml`. Without it, the QA search runs.
4. **Enable workflows.** GitHub turns off scheduled workflows in new forks. Open the
   Actions tab and click the button to enable them.
5. **Test it.** Actions → Daily job search → Run workflow. You should get a Telegram
   message when it finishes.

What to expect afterwards:

- It runs once a day, scheduled for about 06:13 Berlin time, but GitHub often starts
  scheduled runs a few hours late.
- **After every run, the workflow pushes a commit to your `main`** with the updated
  `storage/jobs.db`. Run `git pull --rebase` before you push your own changes, and
  never force-push: that would roll back the history and resend old jobs.
- If the messages stop, check the Actions tab: a failed run shows there with its log,
  and GitHub switches off scheduled workflows in repositories with no activity for 60
  days (one click to switch back on).
- The weekly company re-check (2–3 hours) only runs on a schedule in the original
  repo, so your fork doesn't spend time on it. You get its results when you sync.

### Getting updates from the original repo

New adapters, fixes and the weekly company-list updates land in the original repo.
GitHub's **Sync fork** button will usually report a conflict on `storage/jobs.db`,
because both repos change it every day. Always keep **your** copy, since it's your
own history. From the command line:

```bash
git remote add upstream https://github.com/OleksandraZ/job-search-agent.git   # once
git pull --rebase                       # get your bot's latest commit first
git fetch upstream
git merge upstream/main                 # if it stops on storage/jobs.db:
git checkout --ours storage/jobs.db && git add storage/jobs.db && git commit --no-edit
git push
```

## Keywords file reference

A keywords file is a YAML file in `config/` passed with `--keywords <file name>`.
`title_match_terms` is the only required key. Filters run in this order, and each one
is optional:

1. `title_match_terms`: job-title words/phrases to match. Matching ignores case and
   uses whole words, so `Java` doesn't match "JavaScript". The list is also sent as
   the search query to every board that supports free-text search, so keep entries to
   plain role/skill terms, not sentences. Include German titles too: German postings
   often keep the English title, but not always. Short, simple terms work best: a list
   of long multi-word phrases matched zero real postings when we tried it.
2. `title_exclude_terms`: drop a job whose title also contains one of these words
   (e.g. `Senior`, `Werkstudent`). Useful when a broad term pulls in the wrong
   seniority or employment type.
3. `require_term_groups`: a list of groups; the title or description must mention at
   least one term from **every** group (e.g. `[[Python, SQL], [Airflow, dbt, Spark]]`
   = Python or SQL, and a pipeline tool). Jobs with an empty description are kept,
   since "unknown" isn't "doesn't mention it".
4. `software_signal` (`{titles: [...], terms: [...]}`): a lighter alternative. Only
   jobs whose title matches one of `titles` (ambiguous ones like `Quality Engineer`)
   must mention one of `terms`. `keywords_qa.yaml` uses it to keep out
   manufacturing QA.
5. `description_exclude_terms`: drop a job whose title or description mentions any of
   these (domains like `Embedded`, `ISO 26262`). An entry can also be a rule like
   `{terms: [Selenium, Cypress], unless: [Playwright, Python]}`, which only drops the
   job if none of the `unless` terms appear. Prefer `title_exclude_terms` for words
   that often appear in descriptions by accident (benefits lists, "Vollzeit oder
   Teilzeit").
6. `max_required_years`: drop a job whose description asks for more years of
   experience than this. Jobs that state no number are kept.
7. `report_label`: names the search in the Telegram message ("New Frontend jobs").
   Without it the message just says "New jobs".

## Other commands

```bash
# Excel report of ALL currently fitting jobs, seen or not (never sends anything).
# Writes reports/market_report_<date>.xlsx plus reports/raw_jobs_<date>.json.
# Defaults to the four shipped searches; pass your own with --keywords.
python -m tools.market_report --keywords keywords_frontend.yaml

# Rebuild that report in seconds from saved jobs after changing filters
# (new title_match_terms need a fresh fetch: they were never searched)
python -m tools.market_report --from-raw reports/raw_jobs_<date>.json

# Run the tests, linter and type checker
pip install -r requirements-dev.txt
pytest && ruff check . && mypy .
```

See [`CLAUDE.md`](CLAUDE.md) for the adapter contract and contribution rules used
when extending this project with an AI coding agent.

## How it works

```
fetch (boards + companies) → scope filter (Munich / Germany-remote) → title match
  → optional filters (title excludes, required skills, description excludes,
    max years of experience) → dedupe (seen before?)
  → language classify (DE required / EN okay) → Telegram
```

- **Sources** — `config/sources.yaml` lists job boards; `config/companies.yaml` lists
  companies sourced directly from their ATS (Greenhouse, Lever, Personio, etc) —
  only ones that can actually be fetched; the rest wait in
  `config/unresolved_companies.yaml` with a `reason` and are re-checked weekly. Each
  source/company resolves to an adapter under `adapters/boards/` or `adapters/ats/`
  that fetches and normalizes postings into a common `NormalizedJob` shape.
- **Agents** — `agents/munich_local.py` and `agents/germany_remote.py` each filter the
  same raw job list down to their scope (`pipeline/location.py`).
- **Pipeline** — `pipeline/filters.py` matches titles against
  the keywords file passed with `--keywords` (default `config/keywords_qa.yaml`) and applies
  that file's optional filters (`pipeline/experience.py` reads the required years of
  experience from the description), `storage/dedupe.py` drops jobs already sent
  (SQLite, `storage/jobs.db`) — recognized by normalized title + company
  (`pipeline/duplicates.py`) or by the same source + URL, so a repost on another
  board, under a new tracking URL or for another city, or a listing retitled under
  its old URL, isn't sent again within 90 days — and
  `pipeline/classify_language.py` splits the rest into German-required vs
  English-okay. Copies of one job found in the same run become a single Telegram
  entry with an `also on: …` line.
- **Notifier** — `notifier/telegram.py` formats and sends the report.

## How the scheduled runs work

Three workflows live in `.github/workflows/`:

| Workflow | When | What it does |
|---|---|---|
| `tests.yml` | Every push and PR | `ruff`, `mypy`, `pytest` (offline, about a second) |
| `daily-job-search.yml` | Daily, ~06:13 Berlin, or manually | Runs the search named by the `KEYWORDS_FILE` repo variable (default `keywords_qa.yaml`) and sends it to Telegram |
| `weekly-company-recheck.yml` | Sundays (original repo only), or manually | `python -m tools.resolve_ats`, 2–3 hours: re-detects every company in `config/unresolved_companies.yaml`, checks that every `config/companies.yaml` endpoint still answers, moves companies between the two files and writes `tools/resolve_ats_report.md` |

**Why the bot commits to `main`:** a GitHub runner starts empty every time, so state
that has to survive until the next run is kept in git: `storage/jobs.db` (what was
already sent) and the two company files. Each run commits whatever changed. The two
scheduled workflows share a concurrency group so they never push at the same time.

That's why you should always `git pull --rebase` before pushing and **never
force-push**: a force push replaces the bot's commits, `jobs.db` falls back to an old
state, and the next run resends every job seen since then. A local run without
`--dry-run` updates `storage/jobs.db` too, so pull first and commit the database
afterwards.

## Project layout

```
adapters/boards/   job-board adapters (fetch_jobs(source_config) -> list[NormalizedJob])
adapters/ats/      company-direct ATS adapters (fetch_jobs(company_config) -> list[NormalizedJob])
adapters/registry.py  adapter lookup + fetch_from_sources()/fetch_from_companies()
agents/            scope filters (Munich-local, Germany-remote)
pipeline/          title/skill/description/experience/location/language filtering
storage/           SQLite dedupe of already-sent jobs
notifier/          Telegram formatting + sending
config/            sources.yaml, companies.yaml, keywords_*.yaml, language_rules.yaml
tools/             resolve_ats.py — resolves companies to an ATS vendor (weekly re-check);
                   company_lists.py — keeps companies.yaml to fetchable companies;
                   market_report.py — Excel report of all fitting jobs
reports/           market reports + saved raw jobs (git-ignored)
docs/lessons/      the "why" behind adapter/classification gotchas
tests/             pytest suite (offline; run in CI by .github/workflows/tests.yml)
```
