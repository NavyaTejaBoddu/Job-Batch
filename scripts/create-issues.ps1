# create-issues.ps1
# One-shot: creates labels, milestones, and 14 roadmap issues
# on NavyaTejaBoddu/Job-Batch. Idempotent. ASCII-only.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\create-issues.ps1
#
# Prereqs: gh installed and authenticated with WRITE access.

$ErrorActionPreference = "Continue"
$repo = "NavyaTejaBoddu/Job-Batch"

# ---------- Labels ----------
Write-Host ""
Write-Host "=== Labels ===" -ForegroundColor Cyan
$labels = @(
  @{ name = "phase-1";    color = "0E8A16"; desc = "Phase 1: Multi-tenant foundation" },
  @{ name = "phase-2";    color = "1D76DB"; desc = "Phase 2: Resume upload and parsing" },
  @{ name = "phase-3";    color = "5319E7"; desc = "Phase 3: Student-facing surface" },
  @{ name = "phase-4";    color = "B60205"; desc = "Phase 4: Cover letters and tailoring" },
  @{ name = "phase-5";    color = "D93F0B"; desc = "Phase 5: Application automation" },
  @{ name = "phase-6";    color = "FBCA04"; desc = "Phase 6: Student sources and tuning" },
  @{ name = "backend";    color = "C5DEF5"; desc = "Backend / data layer work" },
  @{ name = "ai";         color = "BFD4F2"; desc = "Claude / LLM-related work" },
  @{ name = "automation"; color = "F9D0C4"; desc = "Browser / form automation" },
  @{ name = "ui";         color = "FEF2C0"; desc = "User-facing surface (bot / web)" },
  @{ name = "infra";      color = "E99695"; desc = "CI, deployment, safety rails" },
  @{ name = "research";   color = "D4C5F9"; desc = "Investigation / spike work" }
)
foreach ($l in $labels) {
  $out = gh label create $l.name --repo $repo --color $l.color --description $l.desc 2>&1
  if ($LASTEXITCODE -eq 0) { Write-Host "  + $($l.name)" -ForegroundColor Green }
  else { Write-Host "  . $($l.name) (exists or skipped)" -ForegroundColor DarkGray }
}

# ---------- Milestones ----------
Write-Host ""
Write-Host "=== Milestones ===" -ForegroundColor Cyan
$milestones = @(
  "Phase 1 - Multi-tenant foundation",
  "Phase 2 - Resume upload and parsing",
  "Phase 3 - Student-facing surface (bot)",
  "Phase 4 - Cover letters and tailoring",
  "Phase 5 - Application automation",
  "Phase 6 - Student sources and tuning"
)
foreach ($m in $milestones) {
  $out = gh api "repos/$repo/milestones" -f title="$m" 2>&1
  if ($LASTEXITCODE -eq 0) { Write-Host "  + $m" -ForegroundColor Green }
  else { Write-Host "  . $m (exists or skipped)" -ForegroundColor DarkGray }
}

# ---------- Issues ----------
Write-Host ""
Write-Host "=== Issues ===" -ForegroundColor Cyan

$ms1 = "Phase 1 - Multi-tenant foundation"
$ms2 = "Phase 2 - Resume upload and parsing"
$ms3 = "Phase 3 - Student-facing surface (bot)"
$ms4 = "Phase 4 - Cover letters and tailoring"
$ms5 = "Phase 5 - Application automation"
$ms6 = "Phase 6 - Student sources and tuning"

$issues = @(
  @{
    title = "Introduce User and StudentProfile schemas"
    labels = "enhancement,phase-1,backend"
    milestone = $ms1
    body = @'
Today config.py defines one hardcoded PROFILE (senior DevOps). To serve many students, we need typed records for users and per-user profiles.

## Tasks
- In job-fetcher/models.py, add User (id, email, created_at) and StudentProfile (user_id, name, degree, grad_year, target_roles, locations, work_auth, skills, summary).
- Keep the existing Job model untouched.
- Add a ProfileLoader that returns the active profile by user_id; keep current hardcoded profile as a seed for backwards compatibility.

## Acceptance
- New Pydantic models with field validation.
- Unit test in test_offline.py style that instantiates a profile and round-trips it through JSON.
'@
  },
  @{
    title = "Extend SQLite schema for users, profiles, per-user matches"
    labels = "enhancement,phase-1,backend"
    milestone = $ms1
    body = @'
store.py currently stores jobs only. Add user/profile tables and a user_id column on the matches table so two students can be ranked against the same job pool independently.

## Tasks
- Add users, profiles, and user_matches(user_id, job_id, score, reasoning, gaps, created_at) tables.
- Write a small migration helper that creates the tables if absent (idempotent, runs on startup).
- Update matches.csv writer to include user_id column.

## Acceptance
- Existing tests still pass.
- New test seeds two users and confirms each gets independent rows in user_matches.
'@
  },
  @{
    title = "Make run.py iterate over users"
    labels = "enhancement,phase-1,backend"
    milestone = $ms1
    body = @'
The pipeline currently scores against the single PROFILE. Loop the rank stage over all active users.

## Tasks
- After dedupe, fetch all User rows.
- For each user, call classify and rank with their profile. Keep the Batches-API path active (batch size accumulates across users).
- Write one digest per user to digests/<user_id>/YYYY-MM-DD.md.

## Acceptance
- Two seeded users produce two distinct digests with different rankings.
- Same-day rerun does not re-bill (idempotency preserved per user).
'@
  },
  @{
    title = "Resume storage table + ingestion CLI"
    labels = "enhancement,phase-2,backend"
    milestone = $ms2
    body = @'
Add a resumes(user_id, raw_text, uploaded_at, source) table. Provide a CLI command "python -m job_fetcher.add_resume <user_id> <path>" that accepts .txt, .md, or .pdf and stores extracted raw text.

## Tasks
- Use pypdf for PDF extraction (add to requirements.txt).
- Store text only, not the binary blob, to keep jobs.db small.

## Acceptance
- Sample resume PDF parses and is retrievable from the DB.
- Test in test_offline.py style with a fixture text resume.
'@
  },
  @{
    title = "LLM-based resume to structured profile extraction"
    labels = "enhancement,phase-2,ai"
    milestone = $ms2
    body = @'
Use Claude Haiku to extract structured fields (degree, grad year, skills, projects, experience) from raw resume text and populate the student's StudentProfile.

## Tasks
- New module job-fetcher/resume_parser.py with an extract_profile(resume_text) -> StudentProfile function.
- Reuse the existing Anthropic client setup; do not re-instantiate.
- Cache the extraction per resume hash to avoid re-billing on re-runs.

## Acceptance
- Given a sample resume fixture, extracted fields match expected values within a tolerance test.
- Cost is bounded to one Haiku call per new resume.
'@
  },
  @{
    title = "Choose and scaffold the bot platform (decision issue)"
    labels = "enhancement,phase-3,ui"
    milestone = $ms3
    body = @'
Decision: ship a chat-bot surface before a web app. Pick Telegram or Discord (recommend Telegram, simpler bot API, no server hosting needed beyond a long-poll worker).

## Tasks
- Document choice in job-fetcher/CLAUDE.md.
- Add python-telegram-bot (or discord.py) to requirements.txt.
- Add a BOT_TOKEN env var and document in README.

## Acceptance
- Decision recorded.
- A "hello" command works against a test bot.
'@
  },
  @{
    title = "Bot commands: /register, /upload_resume, /digest, /status"
    labels = "enhancement,phase-3,ui"
    milestone = $ms3
    body = @'
Minimum viable student surface.

- /register <email> -> creates a User row.
- /upload_resume -> accepts a file attachment, runs the extractor from the resume-parser issue.
- /digest -> returns today's top 10 ranked jobs for this user.
- /status -> shows resume on file, profile summary, last digest date.

## Acceptance
- End-to-end manual test: a fresh chat user can register, upload a resume, and receive a ranked digest.
'@
  },
  @{
    title = "Daily push of digests to registered users via bot"
    labels = "enhancement,phase-3,ui"
    milestone = $ms3
    body = @'
Extend deliver.py so that after digests are written, the bot pushes each user's digest as a chat message.

## Tasks
- New sink in deliver.py alongside the email sink.
- Throttle to respect Telegram/Discord rate limits.

## Acceptance
- Two registered users receive their respective digests via chat after a scheduled run.
'@
  },
  @{
    title = "tailor.py: per-job cover letter and resume-bullet suggestions"
    labels = "enhancement,phase-4,ai"
    milestone = $ms4
    body = @'
For each job with rank score >= 70, generate a one-page cover letter and a list of resume bullets to emphasize, grounded in the student's actual resume.

## Tasks
- New module job-fetcher/tailor.py.
- Sonnet call with: job description + student resume text + profile.
- Strict prompt: do not invent experience the resume does not contain.
- Route through Batches API when >= 20 candidates exist.

## Acceptance
- For 5 sample jobs, generated letters contain no fabricated experience (manual eyeball).
- Cost stays bounded by a configurable MAX_TAILORED_PER_USER_PER_DAY (default 5).
'@
  },
  @{
    title = "Store tailored outputs and surface in bot"
    labels = "enhancement,phase-4,backend"
    milestone = $ms4
    body = @'
Add a tailored_outputs(user_id, job_id, cover_letter, resume_bullets, created_at) table. Add a bot command "/letter <job_id>" that returns the cover letter.

## Acceptance
- Student can request and receive a per-job cover letter via chat.
- Re-requesting the same job returns the cached version.
'@
  },
  @{
    title = "Playwright form-filler for Greenhouse-hosted applications"
    labels = "enhancement,phase-5,automation"
    milestone = $ms5
    body = @'
Build a Playwright script that, given a Greenhouse job URL + student profile + resume PDF path, opens the application in a visible browser, fills standard fields, attaches the resume, and STOPS AT THE SUBMIT BUTTON for human confirmation.

## Tasks
- New module job-fetcher/automation/greenhouse.py.
- Add playwright to a separate requirements-automation.txt (keep core slim).
- Generate a GIF of one end-to-end run.

## Acceptance
- For 3 real Greenhouse postings, all standard fields populate correctly and the script halts before submit.
- Failure modes (missing fields, captcha, login wall) surface clear errors, not silent skips.
'@
  },
  @{
    title = "Playwright form-filler for Lever-hosted applications"
    labels = "enhancement,phase-5,automation"
    milestone = $ms5
    body = @'
Mirror of the Greenhouse form-filler for Lever-hosted applications. Should share helper utilities with the Greenhouse filler.

## Acceptance
- For 3 real Lever postings, all standard fields populate correctly and the script halts before submit.
- Failure modes (missing fields, captcha, login wall) surface clear errors, not silent skips.
'@
  },
  @{
    title = "Application tracker table and bot status surface"
    labels = "enhancement,phase-5,backend"
    milestone = $ms5
    body = @'
Add applications(user_id, job_id, status, applied_at, notes) where status is one of: prepared, submitted, interview, offer, rejected.

Bot commands:
- /applied <job_id> -> marks submitted
- /applications -> lists recent

## Acceptance
- After the form-filler runs, a "prepared" row is created.
- Student can mark "submitted" from chat.
'@
  },
  @{
    title = "Safety rails: never auto-submit without per-application confirmation"
    labels = "enhancement,phase-5,infra"
    milestone = $ms5
    body = @'
Document and enforce the rule that no submission happens without an explicit student confirmation step for that specific job.

## Tasks
- Add a CONTRIBUTING.md note.
- In each automation module, raise on any code path that would click Submit without a confirmed_at timestamp on the application row.

## Acceptance
- A regression test attempts to auto-submit without confirmation and is rejected.
'@
  },
  @{
    title = "Tune keyword filters and ranker for early-career roles"
    labels = "enhancement,phase-6,ai"
    milestone = $ms6
    body = @'
The current keyword set in filters.py and the implicit ranker bias favor senior DevOps. Tune for student/early-career signals: intern, new grad, entry-level, 0-2 years, university hire, etc.

## Tasks
- New keyword constants in filters.py.
- Update the Sonnet ranker prompt in rank.py to weight early-career fit.

## Acceptance
- Running against the seeded job pool, the top 20 ranked roles for a student profile contain >= 10 explicitly early-career roles.
'@
  },
  @{
    title = "Add Simplify.jobs as a job source"
    labels = "enhancement,phase-6,backend,good first issue"
    milestone = $ms6
    body = @'
Add a fetcher for Simplify.jobs (or their published GitHub job repos like SimplifyJobs/Summer202X-Internships and New-Grad-Positions). These are high-signal student boards.

## Acceptance
- New fetcher returns >= 50 jobs in a test run.
- Dedupe with existing sources behaves correctly.
'@
  },
  @{
    title = "(Stretch) Handshake source investigation"
    labels = "research,phase-6"
    milestone = $ms6
    body = @'
Research whether Handshake exposes any programmatic access. Likely requires institutional login. Outcome may be "not feasible without partnership"; document the finding.

## Acceptance
- A short write-up in job-fetcher/docs/sources.md with the conclusion.
'@
  }
)

foreach ($i in $issues) {
  $tmp = New-TemporaryFile
  Set-Content -Path $tmp -Value $i.body -Encoding utf8
  $url = gh issue create --repo $repo --title $i.title --body-file $tmp --label $i.labels --milestone $i.milestone 2>&1
  Remove-Item $tmp -Force
  if ($LASTEXITCODE -eq 0) {
    Write-Host ("  + " + $i.title) -ForegroundColor Green
    Write-Host ("    " + $url) -ForegroundColor DarkGray
  } else {
    Write-Host ("  ! " + $i.title) -ForegroundColor Red
    Write-Host ("    " + $url) -ForegroundColor DarkGray
  }
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Cyan
Write-Host ("Verify: gh issue list --repo " + $repo + " --state open") -ForegroundColor Yellow
