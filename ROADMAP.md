# Roadmap

Job-Batch grows from a single-user job-ranking CLI into a multi-student platform with resume upload, AI-tailored cover letters, and browser-driven application form-filling.

The roadmap is split into 6 phases. Each phase has a GitHub milestone and a set of issues. Pick an issue, comment to claim it, open a PR back to `main`.

All issues live at https://github.com/NavyaTejaBoddu/Job-Batch/issues.

---

## Phase 1 — Multi-tenant foundation

Goal: stop pretending there's one user. Make the existing engine score every job against every registered student's profile.

Milestone: https://github.com/NavyaTejaBoddu/Job-Batch/milestone/1

- [#1 Introduce User and StudentProfile schemas](https://github.com/NavyaTejaBoddu/Job-Batch/issues/1)
- [#2 Extend SQLite schema for users, profiles, per-user matches](https://github.com/NavyaTejaBoddu/Job-Batch/issues/2)
- [#3 Make run.py iterate over users](https://github.com/NavyaTejaBoddu/Job-Batch/issues/3)

## Phase 2 — Resume upload & parsing

Goal: students can hand the system a resume and have it become their profile.

Milestone: https://github.com/NavyaTejaBoddu/Job-Batch/milestone/2

- [#4 Resume storage table + ingestion CLI](https://github.com/NavyaTejaBoddu/Job-Batch/issues/4)
- [#5 LLM-based resume to structured profile extraction](https://github.com/NavyaTejaBoddu/Job-Batch/issues/5)

## Phase 3 — Student-facing surface (bot)

Goal: a chat surface (Telegram/Discord) so students can register, upload a resume, and see their digest without touching the repo.

Milestone: https://github.com/NavyaTejaBoddu/Job-Batch/milestone/3

- [#6 Choose and scaffold the bot platform (decision issue)](https://github.com/NavyaTejaBoddu/Job-Batch/issues/6)
- [#7 Bot commands: /register, /upload_resume, /digest, /status](https://github.com/NavyaTejaBoddu/Job-Batch/issues/7)
- [#8 Daily push of digests to registered users via bot](https://github.com/NavyaTejaBoddu/Job-Batch/issues/8)

## Phase 4 — Cover letters & tailoring

Goal: turn ranked jobs into ready-to-send application material.

Milestone: https://github.com/NavyaTejaBoddu/Job-Batch/milestone/4

- [#9 tailor.py: per-job cover letter and resume-bullet suggestions](https://github.com/NavyaTejaBoddu/Job-Batch/issues/9)
- [#10 Store tailored outputs and surface in bot](https://github.com/NavyaTejaBoddu/Job-Batch/issues/10)

## Phase 5 — Application automation

Goal: actually fill the forms. Always prepare, never submit without the student confirming the specific application.

Milestone: https://github.com/NavyaTejaBoddu/Job-Batch/milestone/5

- [#11 Playwright form-filler for Greenhouse-hosted applications](https://github.com/NavyaTejaBoddu/Job-Batch/issues/11)
- [#12 Playwright form-filler for Lever-hosted applications](https://github.com/NavyaTejaBoddu/Job-Batch/issues/12)
- [#13 Application tracker table and bot status surface](https://github.com/NavyaTejaBoddu/Job-Batch/issues/13)
- [#14 Safety rails: never auto-submit without per-application confirmation](https://github.com/NavyaTejaBoddu/Job-Batch/issues/14)

## Phase 6 — Sources & tuning for students

Goal: the engine surfaces roles students actually want.

Milestone: https://github.com/NavyaTejaBoddu/Job-Batch/milestone/6

- [#15 Tune keyword filters and ranker for early-career roles](https://github.com/NavyaTejaBoddu/Job-Batch/issues/15)
- [#16 Add Simplify.jobs as a job source](https://github.com/NavyaTejaBoddu/Job-Batch/issues/16)
- [#17 (Stretch) Handshake source investigation](https://github.com/NavyaTejaBoddu/Job-Batch/issues/17)

---

## Out of scope (for now)

- Native mobile apps. Bot first.
- Auto-submitting applications without student confirmation. **Not a feature**; it's a safety boundary, see #14.
- Resume rewriting. We surface suggested bullets — the student edits their own resume.

## How to suggest a new phase

Open an issue with the `enhancement` label and a short pitch. Don't make a PR until a maintainer agrees the work belongs on the roadmap.
