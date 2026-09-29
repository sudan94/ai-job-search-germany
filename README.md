# Job Portal

A self-hosted job search assistant for the German market. Once a day it collects postings from
job boards and company career pages, filters out the ones that don't fit, scores the rest
against your CV with an LLM, and gives you a dashboard to track every application from first
look to the company's answer.

It is built for one person: you run it on your own machine or server, with your own API keys.

```
sources → normalize → dedup → Germany filter → title filter → language filter
        → embed + rank → LLM score (until N matches) → store → you track
```

**Stack:** Python · FastAPI · SQLAlchemy · SQLite · OpenAI · React · MUI · Vite · Docker

---

## Contents

- [Features](#features)
- [Quick start](#quick-start)
- [Getting API keys](#getting-api-keys)
- [Your first run](#your-first-run)
- [Using the dashboard](#using-the-dashboard)
- [Configuration](#configuration)
- [Job sources](#job-sources)
- [How filtering and scoring work](#how-filtering-and-scoring-work)
- [Scheduling the daily run](#scheduling-the-daily-run)
- [Project structure](#project-structure)
- [API](#api)
- [Data model and upgrades](#data-model-and-upgrades)
- [Tests](#tests)
- [Changelog](#changelog)
- [Limitations](#limitations)

---

## Features

- **Seven sources**: Arbeitnow, Bundesagentur für Arbeit, Adzuna, Greenhouse, Lever, Ashby, and
  JSearch, which brings in **Indeed, StepStone, LinkedIn and XING** postings through Google for
  Jobs.
- **CV-based scoring**: your CV is parsed once into a structured profile (experience, education,
  projects, skills, languages), and every job is scored 0–100 against it with the matched and
  missing skills listed.
- **Cheap filters first**: deduplication, a Germany-only filter, a job-title filter and a
  German-language check all run before any LLM call is billed.
- **English-only mode**: jobs that require German are detected and set aside, with the phrase
  that gave them away.
- **Configurable pass mark**: set the minimum score in Settings, and choose whether jobs below it
  are rejected automatically.
- **Application tracking**: six statuses, applied and follow-up dates, a contact, notes, and a
  timeline of every change for each job.
- **Tracker board**: drag jobs between Interested, Applied and Rejected.
- **Follow-up reminders**: jobs past their follow-up date are flagged on the dashboard.
- **Daily schedule**: an in-process timer, or cron / Windows Task Scheduler on a laptop.
- **Runs without an OpenAI key**: jobs are still collected, deduplicated and ranked; only
  scoring is skipped, and the dashboard says so.

---

## Quick start

### With Docker (recommended)

```bash
git clone https://github.com/<your-username>/job-portal.git
cd job-portal
cp .env.example .env          # then add your OPENAI_API_KEY (see "Getting API keys")
docker compose up -d --build
```

| What | Where |
| --- | --- |
| Dashboard | http://localhost:8080 |
| API docs (Swagger) | http://localhost:8000/docs |

The database lives on the `job-data` Docker volume, so rebuilding never loses your jobs. The
backend container stays on, so the daily 09:00 (Europe/Berlin) run fires on time, and if the
container starts after a missed run it catches up straight away.

```bash
docker compose logs -f backend                        # watch a run
docker compose exec backend python -m app.run_daily   # run a scan by hand
docker compose up -d --build                          # apply code or .env changes
docker compose down                                   # stop (the data volume survives)
```

### Without Docker

Requires Python 3.12+ and Node 20+.

```bash
python -m venv .venv
.venv\Scripts\activate                 # Linux/macOS: source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env                   # add your keys

cd backend
uvicorn app.main:app --reload          # API on http://localhost:8000
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev                            # dashboard on http://localhost:5173 (proxies /api to :8000)
```

---

## Getting API keys

Put every key in `.env`. It is listed in `.gitignore`, so it is never committed.

| Key | Needed for | How to get it | Cost |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | CV parsing, scoring, language checks | platform.openai.com → API keys | Pay per use; a daily run with `gpt-4o-mini` costs cents |
| `JSEARCH_API_KEY` | Indeed, StepStone, LinkedIn, XING postings | Sign up at [openwebninja.com](https://www.openwebninja.com/api/jsearch) and subscribe to the free JSearch plan | Free tier: 200 requests/month |
| `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | Adzuna aggregator | Sign up at developer.adzuna.com | Free |

Everything else (Arbeitnow, Bundesagentur, Greenhouse, Lever, Ashby) needs no key.

**JSearch through RapidAPI instead?** A RapidAPI key works as well. Set
`JSEARCH_API_HOST=jsearch.p.rapidapi.com` next to the key; the app switches the URL and auth
header to match.

After changing `.env`, restart the backend (`docker compose up -d --build`), then switch the
source on in **Settings → Sources**.

---

## Your first run

1. **Upload your CV** on the **CV** tab (PDF, TXT or Markdown). It is parsed once into a
   structured profile. The page then shows every section it found, how many pages and characters
   it read, and the raw extracted text, so you can check nothing was missed. If the model or the
   embedding step fails, the CV is still saved, and the page says which step did not run.
2. **Open Settings.** Check the search keywords and locations, choose your sources, and set the
   minimum score. The defaults target junior Python, AI and junior-to-mid PHP roles, in English
   and German.
3. **Press Run now.** The first run collects a few hundred postings and takes a minute or two.
4. **Work through the Jobs table.** Click a row to see the score breakdown, the language verdict
   and the tracking panel. Mark promising jobs **Interested** and they appear on the **Tracker**
   board.

---

## Using the dashboard

The dashboard has five tabs: **Jobs**, **Tracker**, **Runs**, **CV** and **Settings**.

### Statuses

| Status | Set by | Meaning |
| --- | --- | --- |
| **New** | pipeline | Collected, not decided on yet. |
| **Rejected by system** | pipeline | Requires German, below the similarity floor, or scored under the minimum. Kept with its reason, so the filters can be checked. |
| **Interested** | you | Worth applying to. Shows on the Tracker board. |
| **Applied** | you | Application sent. The date is recorded. Shows on the Tracker board. |
| **Rejected** | you | The company said no. Keeps the applied date. |
| **Ignored** | you | Not for you. |

The pipeline only ever moves a job between **New** and **Rejected by system**. Once you set any
other status yourself, no run and no threshold change will touch it. Jobs marked Applied,
Rejected or Ignored are never re-scored.

### Jobs tab

- Count tiles for every status; click one to show only that status.
- Filters: status, minimum score, text search, matches only, follow-ups due, remote only.
- Score colours follow your pass mark: red below it, amber up to 15 points above, green beyond.
- Jobs from JSearch show the job site they came from (StepStone, Indeed, …) as their source.
- A banner appears when follow-ups are due.

### The job drawer

Clicking a job opens a panel with:

- **Status buttons** for all six statuses.
- **Applied on**: filled in when you mark a job Applied; editable if you applied earlier.
- **Follow up on**: a date, with +3d / +7d / +14d shortcuts.
- **Contact**: recruiter or hiring manager.
- **Notes**.
- **Timeline**: every status change, from you or the pipeline, with its reason (for example
  *"Score 52 is below the minimum of 65"*), plus entries you add yourself, such as *"Phone screen
  with Anna on Tuesday"*.
- The score verdict, matched and missing skills, the language verdict, the full description, and
  a **Rescore** button.

### Tracker tab

A board with three columns: **Interested**, **Applied** and **Rejected**. Drag a card to change
its status, or click it to open the drawer. Cards show the score, days since applying, the
follow-up date and the contact. Overdue follow-ups are highlighted and float to the top of their
column.

### Minimum score

Set in **Settings → Filtering** with a slider or a number (default 65). Two switches sit next to
it:

- **Mark jobs scored below the minimum as "Rejected by system".** If off, low scorers stay
  **New** and are only hidden by the Jobs page filter.
- **Open the Jobs page on matches only.**

Saving a new minimum re-sorts every job already scored. Lower it from 65 to 55 and the 55–64 jobs
come back as New immediately, without waiting for the next run.

### Runs tab

One row per run: what each source returned, how many jobs each filter dropped, how many were
scored and passed, and any errors. The title-filter terms that did the most work are listed, so
you can tune the lists from real numbers.

---

## Configuration

Secrets and process settings live in `.env`. Everything you tune day to day lives in the
database and is edited on the Settings page.

### `.env`

| Variable | Default | What it does |
| --- | --- | --- |
| `OPENAI_API_KEY` | – | Scoring, CV parsing and language checks. Also used for embeddings. |
| `OPENAI_BASE_URL` | – | Optional OpenAI-compatible gateway. Leave blank for the real API. |
| `CHAT_MODEL` | `gpt-4o-mini` | Model for parsing and scoring. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Model for ranking jobs against the CV. |
| `JSEARCH_API_KEY` | – | Enables the JSearch source (Indeed, StepStone, …). |
| `JSEARCH_API_HOST` | `api.openwebninja.com` | Set to `jsearch.p.rapidapi.com` for a RapidAPI key. |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | – | Enables the Adzuna source. |
| `DATABASE_URL` | `sqlite:///./data/job_portal.db` | SQLite by default; a Postgres URL also works. |
| `TIMEZONE` | `Europe/Berlin` | Timezone for the daily run. |
| `ENABLE_SCHEDULER` | `true` | Turn off when cron or Task Scheduler runs the scan instead. |
| `CATCH_UP_ON_STARTUP` | `true` | On startup, run today's scan if it was missed. |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:8080` | Allowed dashboard origins. |
| `LOG_LEVEL` | `INFO` | Backend log level. |

A blank `OPENAI_BASE_URL` is treated as unset. This matters because the OpenAI SDK reads that
variable itself, and an empty value would make every request fail with a vague "Connection error".

### Settings page

| Section | Settings |
| --- | --- |
| Filtering | English only, Germany only, minimum score, auto-reject below minimum, open Jobs on matches only, matches wanted per run, max scored jobs per run, similarity floor |
| Title filter | On/off, terms to drop, terms required |
| Search | Keywords, locations, radius, max posting age, results per source, remote only |
| Sources | Turn each source on or off |
| JSearch | Which job sites to keep, max requests per run |
| ATS companies | Greenhouse / Lever / Ashby boards to follow; add any company by its board slug |
| Daily run | Run time, scheduler on/off |

---

## Job sources

| Source | Key | Notes |
| --- | --- | --- |
| Arbeitnow | none | English-friendly tech jobs in Germany and remote-EU. |
| Bundesagentur für Arbeit | none | Germany's largest job database (public app key `jobboerse-jobsuche`). |
| Adzuna | free | Aggregator; descriptions are snippets rather than full text. |
| Greenhouse | none | One public call per company board you follow. |
| Lever | none | Same, for companies on Lever. |
| Ashby | none | Same; ships with six verified German companies (DeepL, Enpal, Tacto, Langfuse, Flip, cargo.one). |
| JSearch | free tier | Google for Jobs results: Indeed, StepStone, LinkedIn, XING, Glassdoor and more. |

### Indeed and StepStone

Neither can be queried directly. Indeed retired its Publisher API in 2023, StepStone never had a
public API, and both block scrapers. LinkedIn's job API is partner-only.

Google for Jobs indexes their postings, and **JSearch** exposes that index through a regular API.
Each result names the site it came from, so:

- the **publisher list** in Settings keeps only the sites you want (default: Indeed, StepStone,
  LinkedIn, XING, Glassdoor; leave it empty to keep everything),
- the Jobs table shows `StepStone` or `Indeed` as the source, and
- the link opens the posting on that site when JSearch provides one.

The free tier allows **200 requests a month**. One request covers one keyword and returns up to
10 jobs. A run uses at most `Max requests per run` (default 5), which keeps a daily run inside the
free tier. Keywords are paired with your locations in turn, so five requests cover several cities.

### Adding more

- **More companies:** any company on Greenhouse, Lever or Ashby is one board slug away in
  Settings. These are often the jobs you would apply to directly anyway.
- **A new source:** add one file in `backend/app/sources/` that implements `JobSource.fetch`,
  plus one line in the registry in `backend/app/sources/__init__.py`.

`max_age_days` does not apply to company boards (Greenhouse, Lever, Ashby): they only list jobs
that are still open, so an old publish date does not mean a stale posting.

---

## How filtering and scoring work

Everything free happens before anything is billed, and the paid steps stop as soon as the run
has what it needs.

### 1. Germany filter

With **Germany only** on, a job is kept when its location names a German place and dropped when
it names anywhere else, so "Remote, Brasil" and "Remote – EMEA" are dropped even though they are
remote. When the location is empty, just "Remote", or a small town, the employer decides: a
`GmbH`, a description that mentions Germany, or a Bundesagentur posting is kept.

Place names match as whole words, so "chal**len**ges" is not read as the city Halle. Austrian and
Swiss cities are excluded explicitly, since their companies are also GmbHs.

### 2. Title filter

Runs on the **title only**. Descriptions mention everything, while the title says what the job
actually is.

1. **Drop** terms win first: seniority (`senior`, `staff`, `head`, `manager`), other disciplines
   (`hardware`, `sales`, `elektro`), other stacks (`java`, `salesforce`, `.net`).
2. **Keep** terms must then appear: `python`, `php`, `ai`, `backend`, `entwickl`, …

Terms of five or more characters match inside words, so `software` catches
"Softwareentwicklung". Shorter terms must be whole words, so `java` doesn't match "JavaScript".
Both lists are editable in Settings.

### 3. Language filter

A job description in English doesn't mean the job works in English, so:

1. A free regex pass catches clear cases both ways (`verhandlungssicheres Deutsch`,
   `fluent German`, `Unternehmenssprache ist Englisch`).
2. Unclear cases go to the model, which returns the working language, whether German is required,
   a confidence and the phrase it relied on.
3. With **English only** on, German-required jobs become **Rejected by system**, with the
   evidence kept so you can check the filter isn't too strict.

### 4. Ranking and scoring

Every remaining job is embedded and ranked by similarity to your CV, then scored best match
first. The run **stops once it has enough matches** (`Matches wanted per run`, default 20) or
hits the ceiling (`Max scored jobs per run`, default 60). Skipped jobs stay pending for the next
run. Embeddings are cached, so a job already seen costs nothing again.

| Step | Model setting | Why |
| --- | --- | --- |
| CV parsing | temperature 0 | Runs once per upload; everything depends on it. |
| Language check | temperature 0 | Only for jobs the regex couldn't settle. |
| Scoring | temperature 0 | The same job should get the same score every run. |

All three use **structured outputs**, so results come back as valid JSON matching a schema. If
the model declines one job, that job is marked and the run continues.

Without an OpenAI key, ranking falls back to a built-in word-overlap method. That is enough to
push unrelated jobs down, but it is not semantic. The CV records which method embedded it, and a
run never compares vectors from two different methods.

### CV parsing

PDFs are read with both **PyMuPDF** and **pypdf**, and whichever extracts more text is used.
pypdf alone often reads only one column of a two-column CV, or skips text boxes in designed
templates. The parser reads up to 40,000 characters. If a section is missing from the extracted
text on the CV page, that part of the PDF is an image: export the CV with selectable text, or
paste it into the text box instead.

---

## Scheduling the daily run

In Docker, or on any always-on server, the built-in timer is enough. On a laptop that sleeps,
set `ENABLE_SCHEDULER=false` and let the operating system run the scan:

```bash
cd backend
python -m app.run_daily              # run now
python -m app.run_daily --if-due     # run only if today's run was missed
python -m app.run_daily --json       # machine-readable summary
```

The command exits non-zero when a run fails, so a scheduler can alert on it.

**Windows Task Scheduler**, daily at 09:00:

```powershell
schtasks /create /tn "Job Portal daily scan" /sc daily /st 09:00 ^
  /tr "C:\path\to\job-portal\.venv\Scripts\python.exe -m app.run_daily --if-due"
```

Set **Start in** to `C:\path\to\job-portal\backend`, and tick **Run task as soon as possible
after a scheduled start is missed** so a sleeping laptop still catches up.

**cron**, daily at 09:00:

```cron
0 9 * * * cd /srv/job-portal/backend && /srv/job-portal/.venv/bin/python -m app.run_daily --if-due >> /var/log/job-portal.log 2>&1
```

---

## Project structure

```
backend/
  app/
    main.py             FastAPI app, routes, serves the built frontend
    config.py           .env settings
    db.py               database setup, startup upgrades
    models.py           SQLAlchemy models and statuses
    settings_store.py   dashboard settings, validated with Pydantic
    llm.py              OpenAI client and embedding backends
    scheduler.py        daily timer and missed-run catch-up
    run_daily.py        command-line entry point for cron / Task Scheduler
    sources/            one adapter per job source
    pipeline/           normalize, dedup, geo, relevance, language, scoring, run
    cv/profile.py       CV text extraction and parsing
    routers/            API endpoints: jobs, runs, settings, cv
  tests/                offline tests: no network, no model calls
frontend/
  src/
    pages/              Jobs, Tracker, Runs, CV, Settings
    components/         job drawer, confirm dialog
docker-compose.yml      backend + nginx-served frontend, SQLite on a volume
```

---

## API

Interactive docs are at http://localhost:8000/docs. The main endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/jobs` | List jobs. Filters: `status`, `source`, `min_score`, `search`, `remote_only`, `english_only`, `follow_up_due`; sort by `score`, `similarity`, `first_seen`, `posted_date`, `company`, `applied_date`, `follow_up_date`, `status_changed_at` |
| `GET` | `/api/jobs/{id}` | One job with description, analysis and timeline |
| `PATCH` | `/api/jobs/{id}/status` | Update tracking: `status`, `notes`, `contact`, `applied_date`, `follow_up_date`, or add a timeline entry with `log`. Only fields you send change; `null` clears a date |
| `GET` | `/api/jobs/{id}/events` | The job's timeline |
| `DELETE` | `/api/jobs/{id}/events/{event_id}` | Remove a timeline entry |
| `POST` | `/api/jobs/{id}/rescore` | Re-run the language check and scoring for one job |
| `DELETE` | `/api/jobs/{id}` | Delete one job |
| `DELETE` | `/api/jobs?confirm=true` | Delete every job |
| `GET` / `POST` | `/api/runs` | Run history / start a run |
| `GET` | `/api/runs/active` | Whether a run is in progress |
| `DELETE` | `/api/runs/{id}` | Delete a run and the jobs it first found |
| `DELETE` | `/api/runs?confirm=true` | Clear the run history |
| `GET` | `/api/stats` | Counts per status, matches, follow-ups due, last run |
| `GET` / `PUT` | `/api/settings` | Read / save dashboard settings |
| `GET` | `/api/settings/sources` | Sources, and whether each is on and configured |
| `GET` | `/api/cv` | The active CV profile |
| `POST` | `/api/cv/upload` | Upload a CV file |
| `POST` | `/api/cv/text` | Save a pasted CV |
| `GET` | `/api/cv/raw` | The extracted CV text |
| `GET` | `/api/health` | Health, whether the LLM is enabled, next scheduled run |

---

## Data model and upgrades

| Table | Holds |
| --- | --- |
| `job` | One row per unique posting |
| `job_analysis` | What the pipeline found: similarity, score, matched/missing skills, language verdict, cached embedding |
| `application` | What you did: status, applied date, follow-up date, contact, notes |
| `application_event` | The timeline of status changes and your entries |
| `cv_profile` | The parsed CV and its embedding |
| `run_log` | One row per run, with counts, errors and per-source details |
| `app_setting` | The dashboard settings |
| `schema_migration` | Which one-off data upgrades have run |

The tables are separate so a failure in one pipeline stage never destroys an earlier stage's
work.

**Deduplication** uses a stable ID: the source's own ID where it has one, otherwise a hash of the
normalized title, company and location, with gender markers like `(m/w/d)` removed. The same job
seen on a later day collapses into one row.

**Upgrading an existing install** needs no manual steps. On startup the app adds any new columns
(`_ADDED_COLUMNS` in `db.py`) and runs any pending data upgrades once each (`_DATA_MIGRATIONS`).
For example, the status update moved every old `rejected` row, which used to mean "filtered out",
to `system_rejected`. There is deliberately no Alembic: one personal SQLite file doesn't need it.

**Deleting.** Every delete is permanent and behind a confirm dialog. Deleting a run removes only
the jobs that run found first. The two "delete everything" endpoints require `?confirm=true`.

---

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

136 tests, all offline: a fake source and a fake model cover the full run. They include
thresholds and auto-reject, the English-only filter, dedup across runs, tracking and follow-ups,
the timeline, the JSearch adapter against recorded responses, multi-page PDF extraction, and the
database upgrade path. The tests blank all API keys, so they never call a real service.

---

## Changelog

### Tracking and sources update

- **New statuses:** New, Applied, Rejected by system, Rejected, Interested, Ignored. "Rejected"
  now means the company said no; filter rejections have their own status. Existing data is
  migrated automatically on startup.
- **Application tracking:** applied date, follow-up date with reminders, contact, notes, and a
  per-job timeline of every status change.
- **Tracker board** with drag-and-drop between Interested, Applied and Rejected.
- **Configurable minimum score:** a number field next to the slider, an auto-reject switch, a
  default-view switch, and re-sorting of already-scored jobs when the minimum changes. Score
  colours follow the minimum.
- **Indeed, StepStone, LinkedIn and XING** postings through the new JSearch source, with a
  publisher filter and a per-run request budget. Works with OpenWeb Ninja and RapidAPI keys.
- **Better CV reading:** PDFs are read with PyMuPDF and pypdf, keeping whichever reads more. The
  parser now captures education, projects and certifications, and the CV page shows every
  section plus the raw extracted text.
- **Removed cover letters.** The dashboard focuses on finding and tracking jobs.

---

## Limitations

- **Single user**: no accounts or login. Run it locally or behind your own authentication.
- **No auto-applying**: it finds and ranks jobs; you apply.
- **No scraping**: sources are public APIs only. Indeed and StepStone arrive through JSearch,
  which depends on what Google for Jobs has indexed.
- **No salary data**: salaries are not parsed or shown, even where a source returns them.
