# Contributing to Job-Batch

Thanks for working on this. The goal of the project is to help students search for jobs and reduce the busywork of applying. Keep that in mind when you make tradeoffs.

## Workflow

1. **Pick an issue.** Browse [open issues](https://github.com/NavyaTejaBoddu/Job-Batch/issues) or the [roadmap](./ROADMAP.md). Comment to claim it so others know it's taken.
2. **Branch from `main`.** Naming: `<your-handle>/<short-slug>` (e.g. `hemanjan/multi-tenant-schema`).
3. **Make focused commits.** One logical change per commit. Write the *why* in the commit body if it isn't obvious.
4. **Open a PR back to `main`.** Reference the issue number in the description (`Closes #3`). Include a short test plan.
5. **Wait for review.** Address comments by pushing follow-up commits to the same branch.

## Code

The active codebase is in [`job-fetcher/`](./job-fetcher/). It is Python 3.11+. See [`job-fetcher/README.md`](./job-fetcher/README.md) for setup and [`job-fetcher/CLAUDE.md`](./job-fetcher/CLAUDE.md) for the architecture map.

- Run the offline tests before pushing: `python job-fetcher/test_offline.py && python job-fetcher/test_deliver.py`.
- Don't introduce new top-level dependencies without a reason in the PR description.
- Keep changes scoped to the issue being closed. Refactors that aren't required to ship the feature belong in a separate PR.

## Safety rule: prepare, don't submit

For any code in `job-fetcher/automation/` (the form-fillers), **never click Submit on behalf of the student without an explicit, per-application confirmation step**. This is not a preference; it is the hard rule the system is built around. See [#14](https://github.com/NavyaTejaBoddu/Job-Batch/issues/14) for the regression test that enforces it.

If you find yourself writing code that submits an application automatically, stop. Surface the prepared application to the student, wait for them to confirm, then submit.

## AI / LLM use

We use Claude (Haiku for cheap classification, Sonnet for ranking and tailoring). When adding LLM calls:

- Route through the existing Anthropic client; don't instantiate a new one.
- Truncate large inputs (job descriptions are already capped at 4000 chars).
- Use the Batches API when you have 20+ requests of the same shape.
- Cache by content hash where possible. Re-running the daily job should not re-bill.

## Issue and PR templates

Templates live in [`.github/`](./.github/). Use them — they prompt for the things reviewers will ask for anyway (reproduction steps, acceptance criteria, etc.).

## Questions

Open a discussion or comment on the most relevant existing issue.
