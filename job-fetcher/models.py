"""Job schema + helpers shared across the whole pipeline.

Every fetcher normalizes its source's payload into a `Job`, so the rest of
the app (filters, store, classify, rank, deliver) is source-agnostic.
"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# HTML stripping
# --------------------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_BREAK_RE = re.compile(r"(?i)</(p|div|li|h[1-6]|tr)>|<br\s*/?>")
_WS_RE = re.compile(r"[ \t\f\v]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def strip_html(raw: str | None) -> str:
    """Convert an HTML fragment to readable plain text.

    Some sources (e.g. Greenhouse) HTML-*encode* their markup, so the payload
    arrives as ``&lt;p&gt;`` rather than ``<p>``. We unescape first to turn
    that back into real tags, strip tags (block closings become newlines so
    paragraph structure survives), then unescape once more for any residual
    entities like ``&amp;`` or ``&#39;``.
    """
    if not raw:
        return ""
    text = html.unescape(raw)
    text = _BLOCK_BREAK_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = _MULTI_NL_RE.sub("\n\n", text)
    # Trim trailing spaces on each line and surrounding whitespace.
    text = "\n".join(line.strip() for line in text.splitlines())
    return text.strip()


# --------------------------------------------------------------------------
# Stable id helper
# --------------------------------------------------------------------------
def make_id(*parts: str | None) -> str:
    """Deterministic short id from arbitrary parts.

    Used when a source gives no stable id of its own (e.g. RSS items) — we
    hash the URL or another stable string so reruns dedupe consistently.
    """
    joined = "|".join(p for p in parts if p)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------
# Date parsing — sources use ISO 8601, unix seconds, unix millis, RFC-822.
# --------------------------------------------------------------------------
def parse_date(value: object) -> datetime | None:
    """Best-effort parse of the many date formats sources emit.

    Always returns a timezone-aware UTC datetime, or None if unparseable.
    """
    if value is None or value == "":
        return None

    # Numeric epoch — could be seconds or milliseconds.
    if isinstance(value, (int, float)):
        return _from_epoch(float(value))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # Pure number as a string (Lever uses unix millis).
        if re.fullmatch(r"-?\d+(\.\d+)?", s):
            return _from_epoch(float(s))
        # ISO 8601, tolerating a trailing "Z".
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return _ensure_utc(dt)
        except ValueError:
            pass
        # RFC-822 (RSS pubDate).
        try:
            dt = parsedate_to_datetime(s)
            if dt is not None:
                return _ensure_utc(dt)
        except (TypeError, ValueError):
            pass
    return None


def _from_epoch(num: float) -> datetime | None:
    # Heuristic: values past ~year 2286 in seconds are really milliseconds.
    if num > 1e12:
        num /= 1000.0
    try:
        return datetime.fromtimestamp(num, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# The one schema everything normalizes to.
# --------------------------------------------------------------------------
class Job(BaseModel):
    source: str
    external_id: str
    company: str
    title: str
    url: str
    location: str | None = None
    description: str = ""
    posted_at: datetime | None = None
    remote: bool | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    tags: list[str] = Field(default_factory=list)

    @property
    def key(self) -> str:
        """Dedupe key: stable across reruns and unique within a source."""
        return dedupe_key(self.source, self.external_id)


def dedupe_key(source: str, external_id: str) -> str:
    return f"{source}:{external_id}"
