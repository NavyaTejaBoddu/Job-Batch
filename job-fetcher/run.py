"""Daily pipeline orchestrator.

Milestone 1: fetch Group A (Greenhouse/Lever/Ashby), normalize, and print a
sample of jobs so we can eyeball the schema and HTML stripping.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date

import config
import fetchers
import filters
from store import Store


def _force_utf8_stdout() -> None:
    """Windows consoles default to cp1252; job text is UTF-8. Avoid mojibake."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    _force_utf8_stdout()
    _setup_logging()
    log = logging.getLogger("run")

    log.info("Fetching all sources (Group A + Group B)...")
    jobs = fetchers.fetch_all()
    log.info("Total normalized jobs: %d", len(jobs))

    # Per-source counts.
    by_source: dict[str, int] = {}
    for j in jobs:
        by_source[j.source] = by_source.get(j.source, 0) + 1
    print("\n" + "=" * 78)
    print("JOBS BY SOURCE")
    print("=" * 78)
    for src in sorted(by_source):
        print(f"  {src:18s}: {by_source[src]}")

    # ----------------------------------------------------------------
    # US + relevance prefilter
    # ----------------------------------------------------------------
    kept, stats = filters.prefilter(jobs)
    print("\n" + "=" * 78)
    print("PREFILTER FUNNEL")
    print("=" * 78)
    print(f"  total fetched          : {stats['total']}")
    print(f"  pass US filter         : {stats['us_pass']}")
    print(f"  pass relevance filter  : {stats['relevant_pass']}")
    print(f"  pass BOTH (kept)       : {stats['kept']}")

    kept_by_source: dict[str, int] = {}
    for j in kept:
        kept_by_source[j.source] = kept_by_source.get(j.source, 0) + 1
    print("\n  survivors by source:")
    for src in sorted(kept_by_source):
        print(f"    {src:18s}: {kept_by_source[src]}")

    # ----------------------------------------------------------------
    # Store / dedupe — only jobs not already in the DB are "new" and will
    # be the ones sent to Claude in later milestones.
    # ----------------------------------------------------------------
    today = date.today().isoformat()
    store = Store(config.DB_PATH)
    before = store.count()
    new_jobs = store.add_new(kept, first_seen=today)
    after = store.count()

    print("\n" + "=" * 78)
    print("STORE / DEDUPE")
    print("=" * 78)
    print(f"  DB rows before run : {before}")
    print(f"  kept (US+relevant) : {len(kept)}")
    print(f"  NEW this run       : {len(new_jobs)}  <- only these go to Claude")
    print(f"  already seen       : {len(kept) - len(new_jobs)}")
    print(f"  DB rows after run  : {after}")

    print("\n  sample NEW jobs this run:")
    for j in new_jobs[:12]:
        print(f"    • {j.title}  @ {j.company}  [{j.source}]")
    if not new_jobs:
        print("    (none — every kept job was already in the DB)")

    # ----------------------------------------------------------------
    # Claude classify (Haiku) -> rank (Sonnet). Only NEW jobs, and only
    # if a key is configured (otherwise skip cleanly, like Adzuna/USAJobs).
    # ----------------------------------------------------------------
    if not os.getenv("ANTHROPIC_API_KEY"):
        log.info("ANTHROPIC_API_KEY unset — skipping Claude classify/rank")
    elif not new_jobs:
        log.info("No new jobs — skipping Claude (no re-billing)")
    else:
        import classify
        import rank

        classifications = classify.classify_new(store, new_jobs)
        rankings = rank.rank_relevant(store, new_jobs, classifications)

        print("\n" + "=" * 78)
        print("CLAUDE RESULTS")
        print("=" * 78)
        n_relevant = sum(1 for c in classifications.values()
                         if c.relevant and c.us_based)
        print(f"  classified : {len(classifications)}")
        print(f"  relevant+US: {n_relevant}")
        print(f"  ranked     : {len(rankings)}")

    # ----------------------------------------------------------------
    # Deliver: digest + CSV + optional email. Reads ranked rows from the
    # DB, so it regenerates today's digest even on a Claude-less rerun.
    # ----------------------------------------------------------------
    import deliver

    path = deliver.deliver(store, today)
    matches = store.matches_for_date(today)
    print("\n" + "=" * 78)
    print("DELIVER")
    print("=" * 78)
    print(f"  digest: {path}")
    print(f"  today's ranked matches: {len(matches)}")
    for r in matches[:10]:
        print(f"    [{r['score']:3d}] {r['title']} @ {r['company']}")
    store.close()


if __name__ == "__main__":
    main()
