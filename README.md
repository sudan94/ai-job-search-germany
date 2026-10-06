# AI Job Search Germany

A self-hosted job search assistant for Germany. Every day it collects jobs from Indeed,
StepStone, LinkedIn, the Arbeitsagentur and company career pages. It drops the roles that need
German, scores the rest against your CV with AI, and gives you one dashboard to track your
applications.

**Stack:** Python · FastAPI · React · OpenAI · SQLite · Docker

## Features

- **Many sources in one place:** Indeed, StepStone, LinkedIn and XING (via JSearch), Bundesagentur
  für Arbeit, Arbeitnow, Adzuna, and company boards on Greenhouse, Lever and Ashby.
- **CV matching:** upload your CV once; every job gets a 0–100 score with matched and missing
  skills.
- **English-only filter:** jobs that require German are detected and set aside, with the reason.
- **Smart filters:** Germany-only, job-title filters (seniority, stack) and a minimum score you set.
- **Application tracking:** statuses, applied date, follow-up reminders, contact, notes and a
  timeline for every job.
- **Tracker board:** drag jobs between Interested, Applied and Rejected.
- **Runs daily on its own:** a built-in scheduler scans every morning.

## How it works

```
job sources → remove duplicates → Germany filter → title filter → German-language check
            → rank against your CV → AI score → dashboard
```

The free filters run first, so the AI only scores jobs that are worth it. Each run stops once it
has enough good matches, which keeps the OpenAI cost to a few cents a day.

Every job gets one of six statuses:

| Status | Meaning |
| --- | --- |
| New | Found and not reviewed yet |
| Rejected by system | Needs German, or scored below your minimum |
| Interested | Worth applying to |
| Applied | Application sent |
| Rejected | The company said no |
| Ignored | Not for you |

## Installation

You need [Docker](https://www.docker.com/products/docker-desktop/) installed.

**1. Clone the repo**

```bash
git clone https://github.com/sudan94/ai-job-search-germany.git
cd ai-job-search-germany
```

**2. Add your API keys**

```bash
cp .env.example .env
```

Open `.env` and fill in:

| Key | Required | Where to get it |
| --- | --- | --- |
| `OPENAI_API_KEY` | Yes, for scoring | [platform.openai.com](https://platform.openai.com/api-keys) |
| `JSEARCH_API_KEY` | For Indeed, StepStone, LinkedIn | [openwebninja.com](https://www.openwebninja.com/api/jsearch) (free: 200 requests/month) |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | Optional | [developer.adzuna.com](https://developer.adzuna.com) (free) |

The other sources need no key.

**3. Start it**

```bash
docker compose up -d --build
```

Open the dashboard at **http://localhost:8080**.

Useful commands:

```bash
docker compose logs -f backend    # watch what it's doing
docker compose up -d --build      # restart after changing .env
docker compose down               # stop (your data is kept)
```

## Getting started

1. **CV tab:** upload your CV (PDF, TXT or Markdown). The page shows what was read from it.
2. **Settings tab:** set your keywords, locations and minimum score, and switch on the sources
   you want.
3. **Run now:** press the button at the top. The first run takes a minute or two.
4. **Jobs tab:** click a job to see its score and details, and mark it Interested or Applied.
5. **Tracker tab:** follow your applications and set follow-up dates.

After that, it runs by itself every day at 09:00 (Berlin time). You can change the time in
Settings.
