"""Cheap US + relevance prefilter, run before spending any Claude calls.

Both gates are deliberately coarse — Claude makes the final call on
us_based/relevant downstream. The goal here is only to cut obvious noise
(non-US locations, unrelated roles) so we don't pay to classify them.
"""

from __future__ import annotations

import re

import config
from models import Job

# --------------------------------------------------------------------------
# US location signals
# --------------------------------------------------------------------------
# Full state/territory names (matched case-insensitively, word-bounded).
_US_STATE_NAMES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
    "district of columbia", "puerto rico",
]

# Two-letter codes — matched CASE-SENSITIVELY (uppercase only) so we don't
# trip on lowercase English words ("Dublin or Munich" -> OR, "India" -> IN).
_US_STATE_ABBR = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC", "PR",
]

# Phrases that clearly indicate the US.
_US_PHRASES = [
    "united states", "u.s.a", "u.s.", "usa", "remote us", "remote - us",
    "us only", "us-only", "us based", "us-based", "americas", "north america",
]

# "Keep me anyway" remote signals (lenient) — unless a non-US region appears.
_ANYWHERE = [
    "worldwide", "anywhere", "global", "fully remote", "remote anywhere",
]

# Explicit non-US countries/regions/cities. If one of these appears and there
# is no US signal, drop the job.
_NON_US = [
    # regions
    "europe", "emea", "apac", "latam", "latin america", "middle east",
    "asia", "africa", "oceania",
    # countries
    "canada", "mexico", "united kingdom", "uk", "england", "scotland",
    "wales", "ireland", "france", "germany", "spain", "italy", "portugal",
    "netherlands", "belgium", "switzerland", "austria", "poland", "sweden",
    "norway", "denmark", "finland", "greece", "czech", "hungary", "romania",
    "ukraine", "russia", "turkey", "israel", "uae", "saudi", "qatar",
    "egypt", "nigeria", "kenya", "south africa", "india", "pakistan",
    "bangladesh", "china", "japan", "singapore", "malaysia", "indonesia",
    "thailand", "vietnam", "philippines", "australia", "new zealand",
    "brazil", "argentina", "chile", "colombia", "peru", "korea", "taiwan",
    "hong kong", "luxembourg", "estonia", "lithuania", "latvia", "croatia",
    "serbia", "bulgaria", "slovakia", "slovenia", "iceland",
    # common non-US cities (no state qualifier to rescue them)
    "london", "paris", "berlin", "munich", "frankfurt", "hamburg", "dublin",
    "amsterdam", "barcelona", "madrid", "lisbon", "rome", "milan", "zurich",
    "geneva", "vienna", "warsaw", "prague", "stockholm", "oslo", "copenhagen",
    "helsinki", "athens", "istanbul", "tel aviv", "dubai", "bangalore",
    "bengaluru", "hyderabad", "mumbai", "delhi", "chennai", "pune", "gurgaon",
    "noida", "tokyo", "osaka", "seoul", "beijing", "shanghai", "shenzhen",
    "sydney", "melbourne", "brisbane", "auckland", "toronto", "vancouver",
    "montreal", "ottawa", "sao paulo", "mexico city", "bogota", "manila",
    "jakarta", "bangkok",
]

_ABBR_RE = re.compile(r"\b(" + "|".join(_US_STATE_ABBR) + r")\b")  # case-sensitive
_STATE_NAME_RE = re.compile(
    r"\b(" + "|".join(_US_STATE_NAMES) + r")\b", re.IGNORECASE)
_US_TOKEN_RE = re.compile(r"\bUS\b")  # bare uppercase "US"


def _has_us_signal(loc: str) -> bool:
    low = loc.lower()
    if any(p in low for p in _US_PHRASES):
        return True
    if _US_TOKEN_RE.search(loc) or _ABBR_RE.search(loc):
        return True
    if _STATE_NAME_RE.search(loc):
        return True
    return False


def _has_non_us(loc_low: str) -> bool:
    return any(re.search(r"\b" + re.escape(n) + r"\b", loc_low)
               for n in _NON_US)


def passes_us(job: Job) -> bool:
    """True if the job's location looks US-based or US-inclusive remote.

    With config.US_STRICT (default), only an explicit US signal passes —
    worldwide/anywhere/global and bare "Remote" are dropped. Otherwise the
    lenient rules keep remote/worldwide roles.
    """
    strict = getattr(config, "US_STRICT", False)
    loc = (job.location or "").strip()
    if not loc:
        # No location at all: keep only if explicitly remote (and not strict).
        return (job.remote is True) and not strict

    if _has_us_signal(loc):
        return True
    if strict:
        return False                # US-only: require an explicit US signal

    low = loc.lower()
    non_us = _has_non_us(low)
    if any(a in low for a in _ANYWHERE):
        return not non_us           # worldwide/anywhere, unless EU/APAC-only
    if non_us:
        return False                # clearly non-US, no US signal
    # Ambiguous (some place text, no recognized signal): keep only if remote.
    return "remote" in low or job.remote is True


# --------------------------------------------------------------------------
# Relevance keyword prefilter (title + tags)
# --------------------------------------------------------------------------
_KEYWORD_RES = [
    re.compile(r"\b" + re.escape(k) + r"\b", re.IGNORECASE)
    for k in config.RELEVANCE_KEYWORDS
]


def is_relevant(job: Job) -> bool:
    """True if title or tags contain a DevOps/MLOps-ish keyword."""
    haystack = job.title + " " + " ".join(job.tags)
    return any(rx.search(haystack) for rx in _KEYWORD_RES)


# --------------------------------------------------------------------------
# Combined prefilter
# --------------------------------------------------------------------------
def prefilter(jobs: list[Job]) -> tuple[list[Job], dict[str, int]]:
    """Keep jobs that are both US-based and relevant.

    Returns (survivors, stats) where stats explains the funnel.
    """
    us = [j for j in jobs if passes_us(j)]
    relevant = [j for j in jobs if is_relevant(j)]
    kept = [j for j in jobs if passes_us(j) and is_relevant(j)]
    stats = {
        "total": len(jobs),
        "us_pass": len(us),
        "relevant_pass": len(relevant),
        "kept": len(kept),
    }
    return kept, stats
