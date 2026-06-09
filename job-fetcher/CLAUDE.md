# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A daily DevOps/MLOps job-digest pipeline. Once a day it fetches postings from free
job APIs, keeps only new US-based DevOps/MLOps-relevant roles, uses Claude to
classify (Haiku) then rank (Sonnet) them against a profile, and writes a
date-stamped Markdown digest. See `README.md` for the user-facing setup/scheduling.

## Commands

The interpreter lives in a local venv. On Windows, always set `PYTHONUTF8=1` —
job text contains em-dashes/curly quotes and the console defaults to cp1252.

```powershell
# Run the full pipeline
$env:PYTHONUTF8="1"; .\.venv\Scripts\python.exe run.py

# Offline tests — no network, no Claude billing (mocked client / seeded DB)
.\.venv\Scripts\python.exe test_offline.py    # classify/rank parsing, persistence, idempotency
.\.venv\Scripts\python.exe test_deliver.py    # digest + CSV rendering

# Install deps
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

There is no build step, linter, or pytest harness — the two `test_*.py` files are
standalone scripts with their own pass/fail assertions (run them directly).

## Architecture

Pipeline (in `run.py`):
`fetch_all → normalize → store/dedupe → US+relevance prefilter → score new jobs → deliver`

Every source normalizes to one `Job` pydantic model (`models.py`), so everything
downstream is source-agnostic. The whole design hinges on a few non-obvious rules:

- **Novelty comes from the DB, not source timestamps.** A job is "new" iff its
  dedupe key `f"{source}:{external_id}"` is absent from `jobs.db`. Source
  `posted_at` values are unreliable and are only a secondary signal. This is the
  main cost gate — only new jobs reach Claude, and a second same-day run inserts
  nothing and bills nothing. `store.add_new()` returns only the rows it actually
  inserted (`INSERT OR IGNORE` + `rowcount`).

- **Scoring has two backends, auto-selected by `ANTHROPIC_API_KEY` in `run.py`.**
  Both produce `Classification` + `Ranking` objects and persist via the same
  `store.record_classification` / `record_rank`, so everything downstream is
  identical regardless of which ran.
  - **Key set → Claude.** Haiku (`classify.py`, `CLASSIFY_MODEL`) runs on all new
    prefiltered jobs; only those it marks `relevant AND us_based` go to Sonnet
    (`rank.py`, `RANK_MODEL`). Both use structured outputs
    (`client.messages.parse` with a pydantic model) so JSON is schema-validated.
    `classify.py` auto-switches to the Message Batches API when new-job count ≥
    `BATCH_THRESHOLD` (40).
  - **No key → `heuristic.py`.** Free, offline keyword-overlap scorer against the
    profile skills. `heuristic.score_new()` does both classify + rank in one pass.
    This is the default — the app is fully usable with no API key or cost.

### Per-area gotchas

- **`fetchers.py`** — two source groups wired into module-level tables `_GROUP_A`
  (slug-driven ATS feeds; slugs come from `config.py`) and `_GROUP_B` (slugless
  aggregators). **To add a source, write `fetch_x()` returning `list[Job]` and add
  one row to the right table** — `_safe()` wraps every fetcher in try/except so one
  failing source never crashes the run. A shared throttled `httpx` client enforces
  a per-host delay. Adzuna/USAJobs self-skip when their key env vars are unset.

- **`models.py` `strip_html`** — unescapes entities *before* stripping tags, then
  again after. This order matters: Greenhouse HTML-*encodes* its content
  (`&lt;p&gt;`), so stripping first would leave visible tags.

- **`filters.py` US filter** — state **abbreviations** are matched
  **case-sensitively** (uppercase only) so lowercase English words don't false-match
  (`"Dublin or Munich"` must not hit `OR`; `"India"` must not hit `IN`). Full state
  names and non-US country/city lists are case-insensitive. Remote/worldwide is kept
  leniently unless a non-US region also appears. Both filters are deliberately coarse
  — Claude is the real gate, so over-including is fine.

- **`deliver.py`** — reads ranked rows straight from the store (so reruns reproduce
  the digest without re-billing). Markdown cells escape `|`; CSV append is idempotent
  (deduped by job key). Email only fires when all `SMTP_*` + `DIGEST_TO` are set.

### Config

`config.py` holds the company slug lists, `RELEVANCE_KEYWORDS`, the `PROFILE` text the
ranker scores against, model IDs, paths (`DB_PATH`, `DIGEST_DIR`, `MATCHES_CSV`), and
env-based credential helpers. No secrets are hardcoded — all keys read from env.

## Deployment note

For GitHub Actions, `job-fetcher/` must be the **repository root** (Actions only reads
`.github/workflows/` from the root). The workflow commits `jobs.db` back so dedupe
state survives across daily runs.
