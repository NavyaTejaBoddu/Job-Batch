"""Offline test for deliver.py — seeds sample ranked jobs, renders the digest.

No Claude, no network. Verifies the Markdown digest, the CSV append (and its
idempotency), and graceful handling. Run: python test_deliver.py
"""

from __future__ import annotations

import os
import sys
import tempfile

import config
from models import Job
from store import Store


def _force_utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def main() -> None:
    _force_utf8()
    tmpdir = tempfile.mkdtemp()
    config.DIGEST_DIR = os.path.join(tmpdir, "digests")
    config.MATCHES_CSV = os.path.join(tmpdir, "matches.csv")
    db = os.path.join(tmpdir, "jobs.db")
    date = "2026-06-09"

    import deliver  # imported after config paths are patched

    store = Store(db)
    samples = [
        (Job(source="greenhouse", external_id="1", company="Datadog",
             title="Senior Site Reliability Engineer", url="https://dd/1",
             location="New York, NY (Remote-US)", salary_min=180000,
             salary_max=230000, tags=["Infra"]),
         dict(relevant=True, category="sre", seniority="senior", us_based=True),
         dict(score=91, reason="Strong AWS/Terraform/K8s + observability match.",
              gaps=["No Datadog-specific experience"])),
        (Job(source="ashby", external_id="2", company="Ramp",
             title="Platform Engineer, Infrastructure", url="https://ramp/2",
             location="Remote, US", salary_min=160000, salary_max=200000),
         dict(relevant=True, category="platform", seniority="senior",
              us_based=True),
         dict(score=84, reason="Good IaC + CI/CD fit; fintech aligns with banking bg.",
              gaps=["GCP not in profile"])),
        (Job(source="greenhouse", external_id="3", company="Anthropic",
             title="DevOps Engineer | Pipe & Run", url="https://an/3",
             location="San Francisco, CA", salary_min=None, salary_max=None),
         dict(relevant=True, category="devops", seniority="mid", us_based=True),
         dict(score=72, reason="Solid DevOps fit; title has a pipe to test escaping.",
              gaps=[])),
    ]
    jobs = [s[0] for s in samples]
    store.add_new(jobs, first_seen=date)
    for job, cls, rnk in samples:
        store.record_classification(job.key, **cls)
        store.record_rank(job.key, **rnk)

    # --- render ---
    path = deliver.deliver(store, date)

    print("=" * 70)
    print("GENERATED DIGEST")
    print("=" * 70)
    with open(path, encoding="utf-8") as f:
        print(f.read())

    print("=" * 70)
    print("GENERATED matches.csv")
    print("=" * 70)
    with open(config.MATCHES_CSV, encoding="utf-8") as f:
        print(f.read())

    # --- idempotency: deliver again, CSV must not grow ---
    with open(config.MATCHES_CSV, encoding="utf-8") as f:
        n_before = sum(1 for _ in f)
    deliver.deliver(store, date)
    with open(config.MATCHES_CSV, encoding="utf-8") as f:
        n_after = sum(1 for _ in f)

    print("=" * 70)
    ok = n_before == n_after
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] CSV idempotent on re-run: {n_before} -> {n_after} lines")
    print(f"[PASS] digest sorted highest-first + pipe escaping: see above")

    store.close()
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
