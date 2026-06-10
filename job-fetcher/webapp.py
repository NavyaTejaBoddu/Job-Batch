"""Pipeline-board web app — a Kanban for tracking job applications.

Columns: wishlist -> applied -> interviewing -> offer -> rejected.
Add a card by pasting a URL (auto-fetched for title/company) or free text.
Drag cards between columns. Click a card to generate a recruiter outreach
message (local, no API).

Run:  python webapp.py   then open http://127.0.0.1:5000
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone

import httpx
from flask import Flask, g, jsonify, render_template, request

import config
import kit
from models import strip_html

STATUSES = ["wishlist", "applied", "interviewing", "offer", "rejected"]

app = Flask(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    company     TEXT,
    location    TEXT,
    url         TEXT,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'wishlist',
    kit         TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


# --------------------------------------------------------------------------
# DB helpers
# --------------------------------------------------------------------------
def _db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(config.BOARD_DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute(_SCHEMA)
        g.db.commit()
    return g.db


@app.teardown_appcontext
def _close_db(exc: object) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(r: sqlite3.Row) -> dict:
    return {k: r[k] for k in r.keys()}


# --------------------------------------------------------------------------
# URL / text parsing for new cards
# --------------------------------------------------------------------------
_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _meta(html: str, prop: str) -> str | None:
    # Matches <meta property="og:title" content="..."> in either attr order.
    for pat in (
        rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\'](.*?)["\']',
        rf'<meta[^>]+content=["\'](.*?)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']',
    ):
        m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
        if m:
            return strip_html(m.group(1)).strip()
    return None


def _company_from_url(url: str) -> str:
    """Guess the company from common ATS URL shapes, e.g.
    boards.greenhouse.io/<slug>/..., jobs.lever.co/<slug>/...,
    jobs.ashbyhq.com/<slug>/..., <slug>.recruitee.com."""
    try:
        u = httpx.URL(url)
        host, parts = u.host, [p for p in u.path.split("/") if p]
        ats = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
               "smartrecruiters.com")
        if any(a in host for a in ats) and parts:
            slug = parts[1] if parts[0] in ("v1", "companies") and len(parts) > 1 \
                else parts[0]
            return slug.replace("-", " ").title()
        if host.endswith(".recruitee.com"):
            return host.split(".")[0].replace("-", " ").title()
    except Exception:  # noqa: BLE001
        pass
    return ""


def _get(url: str) -> httpx.Response:
    r = httpx.get(url, timeout=config.HTTP_TIMEOUT, follow_redirects=True,
                  headers={"User-Agent": config.USER_AGENT})
    r.raise_for_status()
    return r


def _parse_ats(url: str) -> dict | None:
    """Use a known ATS's JSON API for clean title/company/location."""
    try:
        u = httpx.URL(url)
        host = u.host
        parts = [p for p in u.path.split("/") if p]

        # Greenhouse: .../<slug>/jobs/<id>
        if "greenhouse.io" in host and "jobs" in parts:
            i = parts.index("jobs")
            slug, jid = parts[i - 1], parts[i + 1]
            j = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}"
                     f"/jobs/{jid}?content=true").json()
            return {"title": j.get("title", ""),
                    "company": slug.replace("-", " ").title(),
                    "location": (j.get("location") or {}).get("name", ""),
                    "description": strip_html(j.get("content"))[:1000]}

        # Lever: jobs.lever.co/<slug>/<id>
        if "lever.co" in host and len(parts) >= 2:
            slug, jid = parts[0], parts[1]
            j = _get(f"https://api.lever.co/v0/postings/{slug}/{jid}"
                     "?mode=json").json()
            cats = j.get("categories") or {}
            return {"title": j.get("text", ""),
                    "company": slug.replace("-", " ").title(),
                    "location": cats.get("location", ""),
                    "description": (j.get("descriptionPlain")
                                    or strip_html(j.get("description")))[:1000]}

        # Ashby: jobs.ashbyhq.com/<slug>/<job-uuid>
        if "ashbyhq.com" in host and len(parts) >= 2:
            slug, jid = parts[0], parts[1]
            data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
                        "?includeCompensation=true").json()
            for j in data.get("jobs", []):
                if str(j.get("id")) == jid:
                    return {"title": j.get("title", ""),
                            "company": data.get("organizationName")
                            or slug.replace("-", " ").title(),
                            "location": j.get("location", ""),
                            "description": (j.get("descriptionPlain")
                                            or strip_html(
                                                j.get("descriptionHtml")))[:1000]}
    except Exception:  # noqa: BLE001
        return None
    return None


_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL)


def _iter_jobpostings(data: object):
    """Yield JobPosting objects from arbitrary JSON-LD (dict/list/@graph)."""
    if isinstance(data, list):
        for item in data:
            yield from _iter_jobpostings(item)
    elif isinstance(data, dict):
        if "@graph" in data:
            yield from _iter_jobpostings(data["@graph"])
        t = data.get("@type")
        if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
            yield data


def _ld_location(job_location: object) -> str:
    """Build 'City, Region, Country' from a JSON-LD jobLocation (or list)."""
    if isinstance(job_location, list):
        return next((s for s in (_ld_location(j) for j in job_location) if s), "")
    if isinstance(job_location, dict):
        addr = job_location.get("address") or job_location
        if isinstance(addr, dict):
            parts = [addr.get("addressLocality"), addr.get("addressRegion"),
                     addr.get("addressCountry")]
            parts = [p["name"] if isinstance(p, dict) else p for p in parts]
            return ", ".join(p for p in parts if p)
    return ""


def _parse_jsonld(html: str) -> dict | None:
    for m in _LD_RE.finditer(html):
        try:
            data = json.loads(m.group(1).strip())
        except (ValueError, TypeError):
            continue
        for job in _iter_jobpostings(data):
            org = job.get("hiringOrganization")
            company = org.get("name") if isinstance(org, dict) else (org or "")
            return {
                "title": (job.get("title") or "").strip(),
                "company": (company or "").strip(),
                "location": _ld_location(job.get("jobLocation")),
                "description": strip_html(job.get("description"))[:1000],
            }
    return None


_ID_SEG_RE = re.compile(r"^[0-9]+$|^[0-9a-f]{8,}$", re.IGNORECASE)
_SKIP_SEG = {"jobs", "job", "positions", "position", "careers", "career",
             "posting", "postings", "apply", "p", "o", "en", "us"}


def _title_from_url(url: str) -> str:
    """Readable title guessed from the URL path, e.g.
    '.../senior-devops-engineer-12345' -> 'Senior Devops Engineer'."""
    try:
        u = httpx.URL(url)
        segs = [s for s in u.path.split("/") if s]
        for s in reversed(segs):
            if _ID_SEG_RE.match(s) or s.lower() in _SKIP_SEG:
                continue
            txt = re.sub(r"[-_]+", " ", s)
            txt = re.sub(r"\b\d{4,}\b", "", txt).strip()  # drop embedded ids
            if len(txt) >= 3:
                return txt.title()[:120]
        return u.host or "Untitled job"
    except Exception:  # noqa: BLE001
        return "Untitled job"


def _host(url: str) -> str:
    try:
        return httpx.URL(url).host or ""
    except Exception:  # noqa: BLE001
        return ""


def _parse_url(url: str) -> dict:
    """Fetch a job URL → {title, company, location, description}.

    Order of preference: known-ATS JSON API → page JSON-LD JobPosting →
    OpenGraph/<title> meta → readable title derived from the URL path.
    The raw URL is never used as the title.
    """
    out = {"title": "", "company": "", "location": "", "description": "",
           "url": url}

    ats = _parse_ats(url)
    if ats and ats.get("title"):
        out.update({k: v for k, v in ats.items() if v})

    if not out["title"]:
        try:
            html = _get(url).text
            ld = _parse_jsonld(html)
            if ld:
                out.update({k: v for k, v in ld.items() if v})
            if not out["title"]:
                title = _meta(html, "og:title")
                if not title:
                    m = _TITLE_RE.search(html)
                    title = strip_html(m.group(1)).strip() if m else ""
                out["title"] = title
            if not out["company"]:
                out["company"] = _meta(html, "og:site_name") or ""
            if not out["description"]:
                out["description"] = (_meta(html, "og:description")
                                      or _meta(html, "description") or "")[:1000]
        except Exception:  # noqa: BLE001 — bad/blocked URL still creates a card
            pass

    # Guaranteed fallbacks — never leave the raw URL as the title.
    if not out["title"]:
        out["title"] = _title_from_url(url)
    if not out["company"]:
        out["company"] = _company_from_url(url) or _host(url)
    return out


def _parse_text(text: str) -> dict:
    """Turn pasted free text into a card. First line = title; rest = description."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    title = lines[0][:140] if lines else "Untitled job"
    return {"title": title, "company": "", "location": "",
            "description": text.strip()[:2000], "url": ""}


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@app.get("/")
def index():
    return render_template("index.html", statuses=STATUSES)


@app.get("/api/cards")
def list_cards():
    rows = _db().execute(
        "SELECT * FROM cards ORDER BY updated_at DESC").fetchall()
    return jsonify([_row_to_dict(r) for r in rows])


@app.post("/api/cards")
def add_card():
    data = request.get_json(force=True) or {}
    raw = (data.get("input") or "").strip()
    if not raw:
        return jsonify({"error": "empty input"}), 400
    parsed = _parse_url(raw) if _URL_RE.match(raw) else _parse_text(raw)
    now = _now()
    db = _db()
    cur = db.execute(
        """INSERT INTO cards
           (title, company, location, url, description, status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (parsed["title"], parsed["company"], parsed["location"],
         parsed["url"], parsed["description"], "wishlist", now, now),
    )
    db.commit()
    row = db.execute("SELECT * FROM cards WHERE id=?",
                     (cur.lastrowid,)).fetchone()
    return jsonify(_row_to_dict(row)), 201


@app.patch("/api/cards/<int:card_id>")
def update_card(card_id: int):
    data = request.get_json(force=True) or {}
    fields, vals = [], []
    for col in ("title", "company", "location", "status", "description"):
        if col in data:
            if col == "status" and data[col] not in STATUSES:
                return jsonify({"error": "bad status"}), 400
            fields.append(f"{col}=?")
            vals.append(data[col])
    if not fields:
        return jsonify({"error": "no fields"}), 400
    fields.append("updated_at=?")
    vals.append(_now())
    vals.append(card_id)
    db = _db()
    db.execute(f"UPDATE cards SET {', '.join(fields)} WHERE id=?", vals)
    db.commit()
    row = db.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
    if row is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_row_to_dict(row))


@app.delete("/api/cards/<int:card_id>")
def delete_card(card_id: int):
    db = _db()
    db.execute("DELETE FROM cards WHERE id=?", (card_id,))
    db.commit()
    return "", 204


@app.post("/api/cards/<int:card_id>/kit")
def make_kit(card_id: int):
    db = _db()
    row = db.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
    if row is None:
        return jsonify({"error": "not found"}), 404
    text = kit.generate(_row_to_dict(row))
    db.execute("UPDATE cards SET kit=?, updated_at=? WHERE id=?",
               (text, _now(), card_id))
    db.commit()
    return jsonify({"kit": text})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
