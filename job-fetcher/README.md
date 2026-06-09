# Job Search Copilot

A daily DevOps/MLOps job digest for US-based roles. Once a day it fetches
postings from free job sources, keeps only new US-based DevOps/MLOps-relevant
roles, uses Claude to classify (cheap pass) then rank (smarter pass) them
against a profile, and writes a date-stamped Markdown digest of the best
matches — optionally emailing it.

No paid services, no scraping. Only public/free APIs.

## How it works

```
fetch_all → normalize → store/dedupe (SQLite) → US + relevance prefilter →
score new jobs → deliver digest
```

**Scoring has two interchangeable backends, auto-selected at runtime:**

- **Claude** (when `ANTHROPIC_API_KEY` is set) — Haiku classifies, Sonnet ranks
  0–100 against your profile with reasons + gaps. Smartest results; costs cents.
- **Local heuristic** (when no key is set, the default) — scores each job by
  keyword overlap with your profile skills, with bonuses for senior/staff titles
  and core DevOps/SRE roles. **No API, no network, no cost.** Produces the same
  ranked digest shape, just with rule-based scores instead of LLM judgment.

Both write identical data to the store, so the digest/CSV/email work the same
either way. Set the key to switch to Claude; unset it to use the heuristic — no
code changes.

- **Idempotent.** A job is "new" only if its dedupe key (`source:external_id`)
  isn't already in `jobs.db`. Running twice the same day adds no duplicates and
  re-bills Claude for nothing.
- **Resilient.** Every external call is wrapped — one failing source is logged
  and skipped; the run never crashes.
- **Cost-gated.** Only new jobs reach Claude; Haiku classifies before Sonnet
  ranks; large batches use the Message Batches API (~50% cheaper).

## Job sources

**Group A — direct ATS feeds** (you supply company slugs in `config.py`):
Greenhouse, Lever, Ashby, Workable, Recruitee, Personio (XML), SmartRecruiters.

**Group B — aggregators** (no key): Remotive, RemoteOK, Arbeitnow,
WeWorkRemotely (RSS). **Free with a key (self-skip if unset):** Adzuna, USAJobs.

## Project structure

```
job-fetcher/
  models.py        Job schema + dedupe key + helpers (HTML strip, date parse)
  fetchers.py      all source fetchers + fetch_all()
  filters.py       US filter + relevance keyword prefilter
  store.py         SQLite: is_new(), add_new(), record classification/rank
  classify.py      Haiku classifier (structured outputs; Batches API for large sets)
  rank.py          Sonnet ranker (scores against PROFILE)
  heuristic.py     free local scorer used when no ANTHROPIC_API_KEY is set
  deliver.py       Markdown digest + matches.csv + optional SMTP email
  config.py        company lists, keywords, profile, env-based keys
  run.py           orchestrates the full daily pipeline
  test_offline.py  offline tests for classify/rank (mocked client)
  test_deliver.py  offline test for the digest/CSV
  .github/workflows/daily.yml
  requirements.txt
  README.md
```

## Setup

Requires **Python 3.11+**.

```bash
cd job-fetcher
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
```

Dependencies: `httpx`, `pydantic`, `anthropic`. Everything else is standard
library (`sqlite3`, `xml.etree`, `smtplib`, `logging`, …).

## Environment variables

All secrets come from the environment — nothing is hardcoded.

| Variable | Required? | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Optional | Switches scoring to Claude (Haiku classify + Sonnet rank). **Without it, the free local heuristic scores the jobs instead** — you still get a ranked digest, just rule-based. The SDK reads this automatically. |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | Optional | Enables the Adzuna source. |
| `USAJOBS_EMAIL`, `USAJOBS_API_KEY` | Optional | Enables the USAJobs source (US federal roles). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `DIGEST_TO` | Optional | Email the digest. If any is missing, the digest is just written to disk. `SMTP_PORT` defaults to 587. |

> **`ANTHROPIC_API_KEY` is a pay-as-you-go API key from**
> [console.anthropic.com](https://console.anthropic.com) → Billing → API keys.
> A Claude Pro/Max subscription is **not** the same thing — that covers
> Claude.ai and Claude Code, not standalone API scripts like this one.

### Getting the free keys

**Adzuna** (free developer tier):
1. Register at <https://developer.adzuna.com/>.
2. Create an app to get an **App ID** and **App Key**.
3. Set `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`.

**USAJobs** (free):
1. Request an API key at <https://developer.usajobs.gov/>.
2. You'll receive an **Authorization-Key** tied to your email.
3. Set `USAJOBS_EMAIL` (the email you registered) and `USAJOBS_API_KEY`.

Setting env vars locally:

```bash
# macOS/Linux
export ANTHROPIC_API_KEY="sk-ant-..."
# Windows PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

## Configure which companies to track

Edit the slug lists in `config.py` (`GREENHOUSE`, `LEVER`, `ASHBY`,
`WORKABLE`, `RECRUITEE`, `PERSONIO`, `SMARTRECRUITERS`). The shipped lists
include verified-working examples; swap in the companies you care about. The
US + relevance filter and Claude trim everything else, so over-including is
cheap.

You can also tune `RELEVANCE_KEYWORDS`, the `PROFILE` text the ranker scores
against, and `AGGREGATOR_QUERIES`.

## Run it

```bash
python run.py
```

Each run prints the fetch/filter/store funnel and (if a key is set) the Claude
results, then writes `digests/YYYY-MM-DD.md` and appends `matches.csv`.

Run the offline tests (no API calls, no billing):

```bash
python test_offline.py     # classify/rank parsing, persistence, idempotency
python test_deliver.py     # digest + CSV rendering
```

## Output

- `digests/YYYY-MM-DD.md` — the day's ranked matches (score, title, company,
  location, salary, source, apply link, one-line reason) plus a summary line.
- `matches.csv` — a running, deduped log of every match.
- `jobs.db` — SQLite store; the source of truth for novelty and the Claude
  results cache.

## Scheduling (daily)

### Option 1 — cron (local machine / server)

Add a crontab entry to run at 8am local time. Use absolute paths and export
the env vars in the command (or source a file that does):

```cron
0 8 * * * cd /path/to/job-fetcher && \
  ANTHROPIC_API_KEY=sk-ant-... \
  /path/to/job-fetcher/.venv/bin/python run.py >> /path/to/job-fetcher/run.log 2>&1
```

On **Windows**, use Task Scheduler: create a Basic Task → Daily → 8:00am →
Action "Start a program":
- Program: `C:\path\to\job-fetcher\.venv\Scripts\python.exe`
- Arguments: `run.py`
- Start in: `C:\path\to\job-fetcher`

Set the env vars as **user environment variables** (System Properties →
Environment Variables) so the scheduled task inherits them.

### Option 2 — GitHub Actions

`.github/workflows/daily.yml` runs the pipeline on a daily `schedule:` cron,
installs deps, runs `run.py`, and commits the new digest / CSV / `jobs.db`
back to the repo (so dedupe state persists across runs).

Setup:
1. Make the **`job-fetcher/` directory the repository root** (GitHub Actions
   only reads workflows from `.github/workflows/` at the repo root).
2. Push to GitHub.
3. Add your keys under **Settings → Secrets and variables → Actions**:
   `ANTHROPIC_API_KEY` (and optionally `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`,
   `USAJOBS_EMAIL`, `USAJOBS_API_KEY`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
   `SMTP_PASS`, `DIGEST_TO`).
4. The workflow has `permissions: contents: write` so it can commit results.

> GitHub cron is **UTC**. The shipped `0 13 * * *` is ~8am US Central / 9am US
> Eastern — adjust for your timezone. You can also trigger it manually from the
> Actions tab (`workflow_dispatch`).

## Cost control

- Only jobs not already in `jobs.db` are sent to Claude — the main cost gate.
- Haiku (cheap) classifies; only `relevant` + `us_based` jobs go to Sonnet.
- Descriptions are truncated to ~4,000 chars before sending.
- ≥ 40 new jobs in a run → the classifier uses the Message Batches API (~50%
  cheaper).
- A second run the same day sends nothing to Claude.
