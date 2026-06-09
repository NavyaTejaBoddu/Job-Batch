"""Deliver the day's matches: Markdown digest + running CSV + optional email.

Reads ranked rows for a given date straight from the store (so a same-day
re-run regenerates the identical digest without re-billing Claude). The CSV
append is idempotent — rows already recorded for a job key are skipped.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import smtplib
import sqlite3
from email.mime.text import MIMEText

import config
from store import Store

log = logging.getLogger(__name__)

_CSV_FIELDS = [
    "date", "key", "score", "title", "company", "location",
    "salary_min", "salary_max", "source", "category", "seniority",
    "url", "reason",
]


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------
def _fmt_salary(lo: float | None, hi: float | None) -> str:
    def k(v: float) -> str:
        return f"${v/1000:.0f}k" if v >= 1000 else f"${v:.0f}"
    if lo and hi:
        return f"{k(lo)}–{k(hi)}"
    if lo:
        return f"{k(lo)}+"
    if hi:
        return f"up to {k(hi)}"
    return "—"


def _md_cell(text: str | None) -> str:
    """Escape pipes/newlines so a value can't break the Markdown table."""
    if not text:
        return "—"
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


# --------------------------------------------------------------------------
# Markdown digest
# --------------------------------------------------------------------------
def build_markdown(rows: list[sqlite3.Row], date: str) -> str:
    lines: list[str] = [f"# DevOps/MLOps Job Digest — {date}", ""]

    if not rows:
        lines.append("_No new US-based DevOps/MLOps matches today._")
        return "\n".join(lines) + "\n"

    # Summary line: counts by category.
    by_cat: dict[str, int] = {}
    for r in rows:
        by_cat[r["category"] or "other"] = by_cat.get(r["category"] or "other", 0) + 1
    cat_summary = ", ".join(f"{n} {c}" for c, n in sorted(by_cat.items()))
    lines.append(f"**{len(rows)} new matches** — {cat_summary}")
    lines.append("")

    lines.append("| Score | Title | Company | Location | Salary | Source | "
                 "Why it fits | Apply |")
    lines.append("|------:|-------|---------|----------|--------|--------|"
                 "-------------|-------|")
    for r in rows:
        salary = _fmt_salary(r["salary_min"], r["salary_max"])
        apply = f"[Apply]({r['url']})" if r["url"] else "—"
        lines.append(
            f"| {r['score']} "
            f"| {_md_cell(r['title'])} "
            f"| {_md_cell(r['company'])} "
            f"| {_md_cell(r['location'])} "
            f"| {salary} "
            f"| {_md_cell(r['source'])} "
            f"| {_md_cell(r['reason'])} "
            f"| {apply} |"
        )

    # Optional detail: gaps per role.
    lines.append("")
    lines.append("## Notes")
    for r in rows:
        gaps = json.loads(r["gaps"]) if r["gaps"] else []
        gap_str = f" — gaps: {', '.join(gaps)}" if gaps else ""
        lines.append(f"- **{_md_cell(r['title'])}** @ {_md_cell(r['company'])} "
                     f"({r['score']}/100, {r['seniority'] or '?'}){gap_str}")
    return "\n".join(lines) + "\n"


def write_digest(rows: list[sqlite3.Row], date: str) -> str:
    os.makedirs(config.DIGEST_DIR, exist_ok=True)
    path = os.path.join(config.DIGEST_DIR, f"{date}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_markdown(rows, date))
    log.info("digest written: %s (%d matches)", path, len(rows))
    return path


# --------------------------------------------------------------------------
# Running CSV (idempotent append)
# --------------------------------------------------------------------------
def append_csv(rows: list[sqlite3.Row], date: str) -> None:
    if not rows:
        return
    path = config.MATCHES_CSV
    existing_keys: set[str] = set()
    file_exists = os.path.exists(path)
    if file_exists:
        with open(path, newline="", encoding="utf-8") as f:
            for rec in csv.DictReader(f):
                existing_keys.add(rec.get("key", ""))

    new_rows = [r for r in rows if r["key"] not in existing_keys]
    if not new_rows:
        log.info("matches.csv: no new rows to append")
        return

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        for r in new_rows:
            writer.writerow({
                "date": date, "key": r["key"], "score": r["score"],
                "title": r["title"], "company": r["company"],
                "location": r["location"], "salary_min": r["salary_min"],
                "salary_max": r["salary_max"], "source": r["source"],
                "category": r["category"], "seniority": r["seniority"],
                "url": r["url"], "reason": r["reason"],
            })
    log.info("matches.csv: appended %d rows", len(new_rows))


# --------------------------------------------------------------------------
# Optional email
# --------------------------------------------------------------------------
def send_email(markdown: str, date: str) -> bool:
    cfg = config.smtp_config()
    if not (cfg["host"] and cfg["user"] and cfg["password"] and cfg["to"]):
        log.info("SMTP env vars unset — not emailing (digest still written)")
        return False
    msg = MIMEText(markdown, "plain", "utf-8")
    msg["Subject"] = f"DevOps/MLOps Job Digest — {date}"
    msg["From"] = cfg["user"]
    msg["To"] = cfg["to"]
    try:
        port = int(cfg["port"] or 587)
        with smtplib.SMTP(cfg["host"], port, timeout=30) as server:
            server.starttls()
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["user"], [cfg["to"]], msg.as_string())
        log.info("digest emailed to %s", cfg["to"])
        return True
    except Exception as e:  # noqa: BLE001 — email failure must not crash the run
        log.warning("email failed: %s", e)
        return False


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def deliver(store: Store, date: str) -> str:
    """Build + write the digest, append CSV, and email if configured."""
    rows = store.matches_for_date(date)
    path = write_digest(rows, date)
    append_csv(rows, date)
    send_email(build_markdown(rows, date), date)
    return path
