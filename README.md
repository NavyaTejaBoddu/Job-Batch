# Job-Batch

**Help students search for jobs and automate the application process.**

Job-Batch is a Python pipeline that fetches roles from many job boards every day, dedupes them, and uses Claude to filter and rank them for each student. The roadmap extends this engine into a multi-student product with resume upload, AI-tailored cover letters, and browser-driven form-filling.

## Repository layout

```
Job-Batch/
├── job-fetcher/          # The pipeline (Python). See job-fetcher/README.md.
├── scripts/              # Operational scripts (issue creation, setup, etc.)
├── .github/              # Issue/PR templates and workflows
├── ROADMAP.md            # 6-phase plan with links to milestones and issues
├── CONTRIBUTING.md       # How to work on this project
└── LICENSE               # MIT
```

## Where the code lives

The matching engine is in [`job-fetcher/`](./job-fetcher/). It runs daily on GitHub Actions, dedupes against SQLite, two-stage filters with Claude Haiku + Sonnet, and writes a Markdown digest plus an optional email.

See [`job-fetcher/README.md`](./job-fetcher/README.md) for setup, environment variables, and how to add company sources.

## Where we are going

This repo is being grown from a single-user CLI into a multi-student platform. The plan is split into 6 phases:

1. **Multi-tenant foundation** — user/profile schemas, per-user ranking.
2. **Resume upload & parsing** — store resumes, extract structured fields with Claude.
3. **Student-facing surface** — Telegram/Discord bot for register, upload, digest, status.
4. **Cover letters & tailoring** — per-job cover letters and resume-bullet suggestions, grounded in the student's actual resume.
5. **Application automation** — Playwright form-fillers for Greenhouse and Lever. Prepare, don't submit.
6. **Sources & tuning for students** — Simplify.jobs, early-career keyword tuning, Handshake investigation.

See [ROADMAP.md](./ROADMAP.md) for milestone and issue links.

## Status

Single-user prototype is working today. Multi-tenant work tracked in [open issues](https://github.com/NavyaTejaBoddu/Job-Batch/issues).

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md). The short version:
- Pick an open issue, comment to claim it.
- Branch from `main`. Open a PR back to `main`.
- For application-automation code, never auto-submit without explicit per-application student confirmation.

## License

MIT. See [LICENSE](./LICENSE).
