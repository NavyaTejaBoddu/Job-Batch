"""SQLite persistence: dedupe + classification/ranking results.

The DB is the source of truth for novelty. A job is "new" iff its dedupe key
is not already a row. Only new jobs are sent to Claude, which is the main cost
gate — and it makes the whole run idempotent: a second run the same day finds
nothing new, sends nothing to Claude, and reproduces the same digest.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from models import Job

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key          TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    external_id  TEXT NOT NULL,
    company      TEXT,
    title        TEXT,
    url          TEXT,
    location     TEXT,
    description  TEXT,
    posted_at    TEXT,
    remote       INTEGER,
    salary_min   REAL,
    salary_max   REAL,
    tags         TEXT,          -- JSON array
    first_seen   TEXT NOT NULL, -- YYYY-MM-DD, set on first insert
    created_at   TEXT NOT NULL, -- ISO timestamp of insert

    -- Haiku classification (filled later)
    classified   INTEGER NOT NULL DEFAULT 0,
    relevant     INTEGER,
    category     TEXT,
    seniority    TEXT,
    us_based     INTEGER,

    -- Sonnet ranking (filled later)
    ranked       INTEGER NOT NULL DEFAULT 0,
    score        INTEGER,
    reason       TEXT,
    gaps         TEXT            -- JSON array
);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen);
"""


class Store:
    """Thin wrapper over a SQLite connection holding the jobs table."""

    def __init__(self, path: str) -> None:
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # -- novelty ---------------------------------------------------------
    def is_new(self, key: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM jobs WHERE key = ?", (key,))
        return cur.fetchone() is None

    def add_new(self, jobs: list[Job], first_seen: str) -> list[Job]:
        """Insert jobs not already stored; return only the newly inserted ones.

        Idempotent: keys already present are skipped (INSERT OR IGNORE), so a
        re-run inserts nothing and returns an empty list.
        """
        new: list[Job] = []
        now = datetime.now(timezone.utc).isoformat()
        for job in jobs:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO jobs
                   (key, source, external_id, company, title, url, location,
                    description, posted_at, remote, salary_min, salary_max,
                    tags, first_seen, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job.key, job.source, job.external_id, job.company,
                    job.title, job.url, job.location, job.description,
                    job.posted_at.isoformat() if job.posted_at else None,
                    _bool_to_int(job.remote), job.salary_min, job.salary_max,
                    json.dumps(job.tags), first_seen, now,
                ),
            )
            if cur.rowcount:  # 1 if inserted, 0 if it already existed
                new.append(job)
        self.conn.commit()
        return new

    def save(self, job: Job, first_seen: str) -> bool:
        """Insert a single job. Returns True if it was new."""
        return bool(self.add_new([job], first_seen))

    # -- Claude results --------------------------------------------------
    def record_classification(self, key: str, *, relevant: bool, category: str,
                              seniority: str, us_based: bool) -> None:
        self.conn.execute(
            """UPDATE jobs
               SET classified = 1, relevant = ?, category = ?,
                   seniority = ?, us_based = ?
               WHERE key = ?""",
            (_bool_to_int(relevant), category, seniority,
             _bool_to_int(us_based), key),
        )
        self.conn.commit()

    def record_rank(self, key: str, *, score: int, reason: str,
                    gaps: list[str]) -> None:
        self.conn.execute(
            """UPDATE jobs
               SET ranked = 1, score = ?, reason = ?, gaps = ?
               WHERE key = ?""",
            (score, reason, json.dumps(gaps), key),
        )
        self.conn.commit()

    # -- reads for downstream stages ------------------------------------
    def unclassified(self, keys: list[str]) -> list[str]:
        """Of the given keys, which have not been classified yet."""
        if not keys:
            return []
        placeholders = ",".join("?" * len(keys))
        cur = self.conn.execute(
            f"SELECT key FROM jobs WHERE classified = 0 AND key IN ({placeholders})",
            keys,
        )
        return [r["key"] for r in cur.fetchall()]

    def matches_for_date(self, date: str) -> list[sqlite3.Row]:
        """Ranked rows first seen on `date` — what the day's digest shows."""
        cur = self.conn.execute(
            """SELECT * FROM jobs
               WHERE first_seen = ? AND ranked = 1
               ORDER BY score DESC, company ASC""",
            (date,),
        )
        return cur.fetchall()

    def get(self, key: str) -> sqlite3.Row | None:
        cur = self.conn.execute("SELECT * FROM jobs WHERE key = ?", (key,))
        return cur.fetchone()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    def close(self) -> None:
        self.conn.close()


def _bool_to_int(b: bool | None) -> int | None:
    return None if b is None else int(b)


def row_to_job(row: sqlite3.Row) -> Job:
    """Reconstruct a Job from a stored row (for digest rendering)."""
    return Job(
        source=row["source"],
        external_id=row["external_id"],
        company=row["company"] or "",
        title=row["title"] or "",
        url=row["url"] or "",
        location=row["location"],
        description=row["description"] or "",
        posted_at=datetime.fromisoformat(row["posted_at"])
        if row["posted_at"] else None,
        remote=None if row["remote"] is None else bool(row["remote"]),
        salary_min=row["salary_min"],
        salary_max=row["salary_max"],
        tags=json.loads(row["tags"]) if row["tags"] else [],
    )
