# Job search portal — project brief

A personal tool that pulls jobs from German job sources every day, scores each one against my CV, filters out the ones that don't fit or that require German, drafts a cover letter for the good ones, and tracks what I've applied to. Single user, runs for me only.

## Who it's for and what it needs to do

I'm a backend engineer in Germany (PHP background, moving toward Python/AI roles) looking for backend, full-stack, and junior AI/Python jobs in Germany and remote-EU, at workplaces that operate in English. The tool should:

- Collect job postings from several German job sources once a day.
- Score each posting 0–100 against my CV and reject anything below a threshold I set.
- Read each job description, work out whether the job runs in English or needs German, and (when the English-only setting is on) drop the German-required ones.
- Draft a cover letter for each job that passes.
- Skip any job it has already seen on a previous run.
- Let me mark jobs as applied, ignored, or interested, and never re-surface those.
- Show everything in a simple dashboard and let me change settings there.

## Decisions to make up front (read this before building)

A few things in the original idea don't survive contact with reality, so here's how to handle them.

**"Scrape every portal" is the wrong approach.** StepStone, LinkedIn, XING, and Indeed all sit behind Cloudflare and aggressive anti-bot systems, and their terms forbid scraping. Building and maintaining scrapers for them is a losing battle and legally grey. Go API-first instead. Three free sources cover most of what I want:

- **Bundesagentur für Arbeit Jobsuche API** — the largest job database in Germany, free, no signup. Authenticate by sending the header `X-API-Key: jobboerse-jobsuche`. Search via `GET https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/app/jobs` with params like `was` (keyword), `wo` (location), `umkreis` (radius km), `veroeffentlichtseit` (days since posted), `arbeitszeit` (vz/tz/ho for full-time/part-time/home-office). Take the `refnr` from each result, base64-encode it, and fetch full details via `GET .../pc/v4/jobdetails/{base64(refnr)}`.
- **Arbeitnow API** — free, no key, English-friendly tech jobs in Germany plus remote-EU, with a `remote` flag and visa-sponsorship tags. This is almost exactly my target segment. Endpoint: `GET https://www.arbeitnow.com/api/job-board-api`, paginated. It aggregates from ATS systems, so the data is clean.
- **Adzuna API** — free tier, needs a free `app_id` and `app_key`, has a Germany endpoint and aggregates many boards. Good as a third source. Respect its rate limits.

**Hit specific companies through their ATS, not their careers page.** Most companies I care about run Greenhouse, Lever, Personio, SmartRecruiters, Recruitee, or Teamtailor, and those have predictable public JSON endpoints that are fine to use. Examples: Greenhouse `https://boards-api.greenhouse.io/v1/boards/{company}/jobs`, Lever `https://api.lever.co/v0/postings/{company}?mode=json`. This is the same ATS-endpoint approach from my earlier YAML scanner, so reuse that list of tracked companies. Build the source layer so a new ATS is a small adapter, not a rewrite.

**The daily 9 AM run needs an always-on process.** An in-process scheduler on a laptop won't fire when the laptop is asleep. Either deploy the backend to a small always-on host (Railway, Fly.io, or a cheap VPS) and use APScheduler, or run it locally and trigger the daily job from system cron / Windows Task Scheduler calling a CLI command. Build a `python -m app.run_daily` entry point either way, so the scan works whether a scheduler calls it or I run it by hand. On startup, check whether today's run already happened and catch up if it didn't.

**Keep LLM cost down with a two-stage score.** Don't send every job to a chat model. Embed my CV once and embed each new job description, rank by cosine similarity (that's nearly free with `text-embedding-3-small`), then send only the top candidates to a cheap chat model (`gpt-4o-mini` or similar) for a real rubric score and the cover letter. A daily run should cost cents, not euros.

**"English-speaking job" is not the same as "English job description."** A German-language posting can be an English-speaking workplace, and an English posting can still demand fluent German. Don't rely on language detection of the JD alone. Detect the JD language as a signal, then have the model read the description and return a structured judgment: working language, whether German is required, and its confidence. Treat phrases like "verhandlungssicheres Deutsch", "Deutschkenntnisse erforderlich", or "sehr gute Deutschkenntnisse" as strong German-required signals.

## Architecture

A FastAPI backend, a React + MUI frontend (Vite), and SQLite to start (a single file, easy to back up; swap for Postgres later if needed). The daily pipeline is a sequence of stages, each reading and writing the database, so a failure in one stage doesn't lose the work of earlier ones.

```
sources → normalize → dedup → language filter → embed + prefilter → LLM score → cover letter → store
```

Structure the source layer as one adapter per source behind a shared interface, so each returns a list of normalized jobs and the pipeline doesn't care where they came from.

```
app/
  main.py                # FastAPI app + routes
  config.py              # settings, thresholds, keys from env
  db.py                  # SQLAlchemy setup
  models.py              # ORM models
  sources/
    base.py              # JobSource interface -> list[RawJob]
    arbeitsagentur.py
    arbeitnow.py
    adzuna.py
    ats_greenhouse.py
    ats_lever.py
  pipeline/
    normalize.py         # RawJob -> Job, stable external id
    dedup.py             # skip already-seen jobs
    language.py          # JD language + German-required judgment
    scoring.py           # embeddings prefilter + LLM rubric score
    cover_letter.py      # draft in my voice
    run.py               # orchestrates the daily run
  cv/
    profile.py           # parse CV once, store structured profile + embedding
  run_daily.py           # CLI entry point for cron / scheduler
frontend/                # React + MUI + Vite
```

## Data model

- **cv_profile** — parsed once from my CV: extracted skills, years of experience, role targets, raw text, and its embedding. Re-parse only when I upload a new CV.
- **job** — one row per unique posting: `external_id` (stable, see dedup), `source`, `title`, `company`, `location`, `remote` (bool), `url`, `description` (full text), `posted_date`, `first_seen`, `raw_json`.
- **job_analysis** — `job_id`, `similarity` (embedding cosine), `score` (0–100 from the model), `score_reasons` (short JSON: what matched, what's missing), `working_language`, `german_required` (bool), `language_confidence`.
- **application** — `job_id`, `status` (`new`, `interested`, `applied`, `ignored`, `rejected`), `cover_letter`, `applied_date`, `notes`. Status drives what shows in the dashboard and what gets skipped on future runs.
- **run_log** — one row per daily run: timestamp, counts (fetched, new, scored, passed, letters written), errors. Lets me see at a glance what happened at 9 AM.

## Dedup and "already seen"

Give every job a stable `external_id` so re-runs recognise it:

- Use the source's own id where there is one (Bundesagentur `refnr`, Arbeitnow slug, ATS posting id).
- Otherwise hash a normalized `title + company + location`, lowercased and whitespace-collapsed, so the same job from two sources or two days collapses to one row.

On each run, look up `external_id` before doing any expensive work. If it exists, skip it entirely (no re-embedding, no re-scoring, no LLM call). Jobs I've marked `applied` or `ignored` stay in the database and never re-surface, but the tool shouldn't waste a scoring call on them either.

## Scoring

Compare against the structured CV profile, not just raw text.

1. Cosine-similarity every new job's description embedding against the CV embedding. Drop the bottom of the list below a similarity floor.
2. For the survivors, send CV summary + JD to the chat model and ask for a strict JSON object: `score` (0–100), `matched` (skills/requirements I meet), `missing` (hard requirements I don't), and a one-line `verdict`. Give it a rubric in the system prompt: weight must-have technical requirements heavily, penalise missing hard requirements (years of experience I don't have, a required certification, mandatory German), reward overlap with my actual stack. Ask it to be honest rather than generous, since a score that flatters me wastes my time.
3. Reject anything under the threshold from settings (default 65). Keep rejected jobs in the database with their reasons so I can audit whether the filter is too harsh.

## Cover letters — write them in my voice, not generic AI prose

This is the part most tools get wrong. The letters must not read as machine-generated. Put these rules in the generation system prompt:

- No AI tells: no em-dash overuse, no "I am excited to apply", no hollow superlatives, no rule-of-three lists, no trailing "-ing" analysis clauses. Plain, direct sentences.
- Frame my Python/AI experience honestly as academic and personal-project work, never as production experience I don't have. Overclaiming gets me caught in interviews.
- Match the register of the posting: formal if the posting is formal, informal if it's relaxed.
- Ground every claim in a concrete project or result from my CV, not adjectives about myself.
- Keep it short and functional. One page, three or four short paragraphs.
- Output the letter only, no preamble, no `[Company Name]` placeholders — fill real values from the job.

Generate the letter lazily: only for jobs that pass scoring, and cache it so it isn't regenerated on every dashboard load. Let me edit and regenerate from the UI.

## Settings (all editable in the dashboard, stored in the DB)

- English-only toggle (drops German-required jobs).
- Minimum score threshold.
- Search keywords and locations per source, plus a remote-only toggle.
- Radius in km and max age of postings in days.
- Which sources and which tracked ATS companies are active.
- Daily run time (default 09:00 Europe/Berlin).

## Frontend

A small MUI dashboard, nothing fancy:

- **Job list** — table sorted by score, with source, title, company, location, remote flag, score, and status. Filter by status and score. A row opens a detail drawer.
- **Detail drawer** — full JD, the score breakdown (matched / missing), the language verdict, the drafted cover letter (editable, copy button, regenerate button), and status buttons.
- **Settings page** — everything above.
- **Runs page** — the `run_log` history so I can see what each 9 AM scan did and whether anything failed.

## Build in vertical slices, one working thing at a time

Don't build all sources, then all scoring, then the UI. Build one thin slice end to end, get it working, then widen. Suggested milestones:

1. FastAPI skeleton, SQLite, models, one source (Arbeitnow — no key, cleanest data). Fetch, normalize, store, dedup. A `/jobs` endpoint returns them. Prove the loop works.
2. CV upload and parsing into a structured profile plus embedding.
3. Embedding prefilter and the LLM rubric score. A threshold rejects low scores.
4. Language detection and the English-only filter.
5. Cover letter generation in my voice, cached, editable.
6. The React/MUI dashboard against the endpoints that already exist.
7. Add the Bundesagentur and Adzuna sources and the ATS adapters behind the same interface.
8. The daily scheduler plus the `run_daily` CLI entry point, with run logging and catch-up.
9. Application tracking: statuses, and skipping applied/ignored jobs on future runs.

Each milestone should end with something that runs and that I can look at.

## Tech stack

FastAPI, SQLAlchemy, SQLite (Postgres-ready), `httpx` for source calls, APScheduler for the timer, `openai` for embeddings and chat, `lingua` or `langdetect` for the language signal, Pydantic for the settings and the structured LLM outputs. React + MUI + Vite on the front. Keep all keys and thresholds in a `.env` read by `config.py`; never hard-code the OpenAI key.

## Out of scope for v1

Auto-applying to jobs (keep me in the loop — draft, I send). Multi-user accounts. Scraping the anti-bot portals. Salary parsing beyond what the APIs already give. Add these later if the core earns its keep.
