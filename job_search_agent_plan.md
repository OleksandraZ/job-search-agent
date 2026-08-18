# QA Job Search Agent — Build Spec

## 1. Goal
A scheduled pipeline that finds new QA Engineer job postings in Germany (remote) and Munich
(onsite/hybrid/remote) posted in the last 24h, splits them by the language *required* for the
role (German vs English), and sends a formatted summary to Telegram once daily.

---

## 2. Architecture

```
                ┌───────────────────────┐
                │   Orchestrator (cron)  │
                └──────────┬─────────────┘
                           │
        ┌──────────────────┴───────────────────┐
        │                                       │
┌───────▼────────┐                    ┌─────────▼─────────┐
│ Germany-Remote   │                    │  Munich-Local      │
│ Search Agent     │                    │  Search Agent      │
└───────┬────────┘                    └─────────┬─────────┘
        │  raw job listings                     │  raw job listings
        └──────────────────┬───────────────────┘
                           │
                ┌──────────▼─────────────┐
                │  Filter & Dedupe        │
                │  (keywords, date, seen) │
                └──────────┬─────────────┘
                           │
                ┌──────────▼─────────────┐
                │  Language Classifier    │
                │  (required: EN vs DE)   │
                └──────────┬─────────────┘
                           │
                ┌──────────▼─────────────┐
                │  Telegram Notifier      │
                └─────────────────────────┘
```

- **Agent A — Germany / Remote:** searches nationwide, keeps only remote-eligible roles.
- **Agent B — Munich / Local:** searches Munich specifically, keeps onsite + hybrid + remote.
- Both feed into the same filter → classify → notify pipeline.

---

## 3. Config Files

Three config files drive the pipeline (all shared alongside this plan):

| File | Contents |
|---|---|
| `config/sources.yaml` | 109 board sources (all enabled), each with `id`, `adapter`, `url`, `priority`, `category` |
| `config/keywords.yaml` | Title-match terms + search-query term buckets (EN/DE) |
| `config/companies.yaml` | 200 companies (100 Series B startups + 100 kununu top employers) for direct ATS sourcing |

Sources plug into the pipeline via a common adapter interface:
`fetch_jobs(config) -> list[NormalizedJob]`. Adding a new board or company batch means adding a
config entry (and, for a genuinely new adapter type, a small adapter function) — no pipeline
redesign needed.

```yaml
sources:
  - id: arbeitnow
    type: board
    adapter: arbeitnow_api
    scope: germany_remote_and_local
  - id: germantechjobs_munich
    type: board
    adapter: html_scrape
    url_template: "https://germantechjobs.de/en/jobs/Tester/Munich"
  - id: greenhouse_companies
    type: company
    adapter: greenhouse_api
    company_list: config/companies.yaml
```

---

## 4. Board Sources — Build Order

`config/sources.yaml` has all 109 platforms enabled, with `adapter: html_scrape` as a default
placeholder to be overridden per-source as real adapters are built. Build in this tier order:

| Tier | What it means | Examples |
|---|---|---|
| **1 — Real JSON API, no key** | Stable, structured, cheap to filter | Arbeitnow — `GET https://www.arbeitnow.com/api/job-board-api`, no auth |
| **2 — HTML scrape, no anti-bot** | Needs a health check for silent breakage | StepStone, Indeed, DEVjobs, GermanTechJobs, get in IT, Instaffo, XING, etc. |
| **3 — Actively anti-scraping / ToS risk** | Avoid direct scraping | LinkedIn — use a native LinkedIn job alert emailed to you and parse that, not the site |

---

## 5. Keyword Matching

`config/keywords.yaml` has one bucket, `title_match_terms` (20 entries, EN + DE role
titles): it's both the search query sent to every board that supports free-text
search, and the post-fetch title filter (`pipeline/filters.py:filter_by_title`) run
on every job regardless of source. Combining the two roles keeps per-run request
volume down — see the wall-time gotcha in `CLAUDE.md` — since a skill-qualified query
(e.g. "QA Engineer Playwright") wouldn't change what survives the filter afterward
anyway, which only ever matches on bare role titles. An earlier, unbuilt design had
separate `priority_search_terms`/`search_terms_en`/`search_terms_de` buckets for a
role×skill matrix sent as board queries; dropped since no adapter ever read them.

- `title_match_terms` includes both English and German role titles, since German QA
  postings often keep the English title as a loanword rather than translating it.

---

## 6. Date Filtering (last 24h)

- Where a platform supports it natively (Indeed `fromage=1`, LinkedIn `f_TPR=r86400`, StepStone
  `age=1`), use the native filter.
- Where not supported, filter client-side using the `updated_at`/`created_at` field from the API.
- Store `last_run_timestamp` so each run only looks at postings newer than the previous run.

---

## 7. Deduplication

- SQLite database (`jobs.db`), table `seen_jobs`: `job_id` (hash of source+url), `title`,
  `company`, `first_seen_at`.
- Filter out any job whose hash already exists before sending.

---

## 8. Language Classification — Required Language of the Role

Classify by the language the role **requires**. Two buckets only, German takes priority
whenever it's required — via either of two independent signals:

- **German bucket** — either:
  - German is explicitly required (regardless of whether English is also required). Detect
    via phrases like `Deutsch (C1|C2|fließend|verhandlungssicher|Muttersprache)`,
    "gute Deutschkenntnisse", "sehr gute Deutschkenntnisse"; **or**
  - the posting itself is predominantly written in German with no explicit requirement
    statement at all. Real postings from German-market platforms (Instaffo, XING) turned
    out to skip stating the requirement outright, since it's implicit to their own market —
    a stopword-frequency check over the description (`config/language_rules.yaml`'s
    `whole_description_language_signal`) catches this: understanding the ad, and therefore
    the role, already requires German. This is the one place the original "requires, not
    written in" framing is deliberately relaxed — a fully German-language ad is treated as
    itself evidence of the requirement, not just a proxy for it.
- **English bucket** — everything else: no explicit language requirement stated, the posting
  isn't predominantly German, and English is required with no German requirement mentioned.

This is mostly a requirement-extraction problem, handled with regex over the description
(no language-ID library needed), plus the stopword-ratio fallback above for the
no-explicit-statement case. Logic (see `pipeline/classify_language.py`):

```
if german_requirement_regex.search(description):
    bucket = "german"
elif predominantly_german(description):  # stopword-frequency fallback
    bucket = "german"
else:
    bucket = "english"
```

Keep the phrase list and the stopword lists/thresholds in `config/language_rules.yaml` (not
hardcoded) so they can be tuned as false positives/negatives show up in real output.

---

## 9. Telegram Notification

Bot already created; `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are stored as GitHub Actions
repo secrets on `OleksandraZ/job-search-agent`.

- Send via HTTPS POST to `https://api.telegram.org/bot<token>/sendMessage` — no SDK needed.
- Message format:

```
📅 18.08.2026 — New QA jobs

🇬🇧 English-speaking (3)
1. QA Automation Engineer — Acme GmbH (Munich, Hybrid)
   https://...
2. SDET — TechCo (Remote, Germany)
   https://...
3. QA Engineer — StartupX (Munich, Onsite)
   https://...

🇩🇪 German-speaking (2)
1. Qualitätssicherung Ingenieur — BigCorp (München, Vor Ort)
   https://...
2. Testautomatisierung Engineer — Firma GmbH (Remote)
   https://...
```

- If zero new jobs, send a short "no new postings today" message so you know the pipeline ran.

---

## 10. Scheduling

GitHub Actions, once daily at 9:00 AM Munich time, repo: `git@github.com:OleksandraZ/job-search-agent.git`.

- GitHub Actions cron runs in UTC; Munich shifts UTC+1 (CET) / UTC+2 (CEST). Schedule at
  `0 7 * * *` (07:00 UTC) — lands at 9:00 AM CEST / 8:00 AM CET, ~1hr drift twice a year. For
  exact 9:00 AM year-round, define two cron triggers guarded by a date-range check in `main.py`.
- Secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) live in repo Settings → Secrets and
  variables → Actions.
- Workflow file: `.github/workflows/daily_run.yml` — checkout, setup Python, install
  `requirements.txt`, run `python main.py`.

---

## 11. Company-Based Sourcing (ATS Adapters)

Direct sourcing from company career pages, via each company's ATS (applicant tracking system)
public API — one adapter per ATS covers many companies via a shared registry.

### 11.1 ATS platforms and endpoints

| ATS | URL pattern | Public API |
|---|---|---|
| Greenhouse | `boards.greenhouse.io/{company}` | `GET https://boards-api.greenhouse.io/v1/boards/{company}/jobs` |
| Lever | `jobs.lever.co/{company}` | `GET https://api.lever.co/v0/postings/{company}?mode=json` |
| Ashby | `jobs.ashbyhq.com/{company}` | `GET https://api.ashbyhq.com/posting-api/job-board/{company}` |
| SmartRecruiters | `jobs.smartrecruiters.com/{company}` | `GET https://api.smartrecruiters.com/v1/companies/{company}/postings` |
| Personio | `{company}.jobs.personio.de` | XML feed at `{company}.jobs.personio.de/xml` |
| Workday | `{company}.wd*.myworkdayjobs.com` | JSON via `/wday/cxs/{tenant}/{site}/jobs` (undocumented, stable) |

### 11.2 Company Registry

`config/companies.yaml` — 200 entries, each just `name` + `url`:

```yaml
companies:
  - name: "FINN"
    url: "https://www.finn.com"
  - name: "Atruvia AG"
    url: "https://www.atruvia.de"
  ...
```

### 11.3 Remaining Work

1. Run `tools/resolve_ats.py` across all 200 to fill in `ats` + `identifier` (fetches each
   company's careers page and pattern-matches against the URL/HTML signatures in §11.1).
2. Build ATS adapters (Greenhouse/Lever first — most common among these companies).

---

## 12. Project Structure

```
qa-job-agent/
├── config/
│   ├── sources.yaml
│   ├── companies.yaml
│   └── keywords.yaml
├── main.py
├── agents/
│   ├── germany_remote.py
│   └── munich_local.py
├── adapters/
│   ├── boards/
│   │   ├── arbeitnow_api.py
│   │   ├── html_scrape.py     # generic, config-driven scraper for tier-2 boards
│   │   └── ...
│   └── ats/
│       ├── greenhouse_api.py
│       ├── lever_api.py
│       ├── ashby_api.py
│       ├── smartrecruiters_api.py
│       ├── personio_feed.py
│       └── workday_api.py
├── tools/
│   └── resolve_ats.py
├── pipeline/
│   ├── filters.py
│   ├── dedupe.py
│   └── classify_language.py
├── notifier/
│   └── telegram.py
├── storage/
│   └── jobs.db
├── .github/workflows/
│   └── daily_run.yml
├── requirements.txt
└── README.md
```

---

## 13. Build Phases

1. **Phase 1 — MVP:** Arbeitnow (API) + GermanTechJobs (HTML scrape), Munich agent only, keyword
   filter, no language split, plain Telegram message.
2. **Phase 2 — Add Germany-remote agent** and merge outputs.
3. **Phase 3 — Add dedupe (SQLite).**
4. **Phase 4 — Add language classification** and the split message format.
5. **Phase 5 — Add remaining board sources**, error handling/retries.
6. **Phase 6 — Company-direct sourcing:** ATS adapters, run `resolve_ats.py` across all 200
   companies.
7. **Phase 7 — Add GitHub Actions scheduling.**
8. **Phase 8 — Polish:** logging, "no jobs today" message, per-source health checks,
   config-driven tuning (no code changes needed to adjust keywords/sources).

---

## 14. Tech Stack

- Python 3.11+
- `httpx` or `requests` for HTTP
- `beautifulsoup4` (+ `playwright` only if a source requires JS rendering)
- `re` (stdlib) for German/English requirement extraction
- `sqlite3` (stdlib) for dedupe storage
- `PyYAML` for config
- GitHub Actions for scheduling
- Telegram Bot API via plain HTTPS
