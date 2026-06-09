"""Local, no-API scoring — a drop-in alternative to Claude classify/rank.

When no ANTHROPIC_API_KEY is set, the pipeline uses this instead of Claude. It
classifies and scores each job purely from keyword overlap with the profile, so
you still get a ranked digest with reasons — for free, with no network calls.

It returns the same `Classification` / `Ranking` objects the Claude path does,
so the store, run.py, and deliver.py all work unchanged.
"""

from __future__ import annotations

import logging

from classify import Classification
from models import Job
from rank import Ranking
from store import Store

log = logging.getLogger(__name__)

# Skills from the profile (lowercase), grouped so the reason text reads well.
_PROFILE_SKILLS = [
    "aws", "azure", "terraform", "ansible", "cloudformation",
    "kubernetes", "helm", "eks", "aks", "docker", "containers",
    "jenkins", "github actions", "azure devops", "argocd", "ci/cd",
    "prometheus", "grafana", "elk", "cloudwatch", "observability",
    "python", "bash", "linux", "sql",
    "devops", "sre", "site reliability", "platform", "infrastructure",
    "mlops", "iam", "vpc", "helm", "blue-green", "canary",
]

# Core role signals that make a posting clearly relevant.
_CORE_ROLE = [
    "devops", "sre", "site reliability", "platform engineer", "platform",
    "infrastructure", "mlops", "cloud engineer", "reliability",
    "kubernetes", "ci/cd", "terraform",
]

# Titles that are clearly NOT engineering, even if they tripped the prefilter.
_NEGATIVE_TITLE = [
    "sales", "account executive", "recruiter", "marketing", "designer",
    "attorney", "counsel", "accountant", "customer success", "support",
    "manager, people", "people partner", "executive assistant",
]

# Skills/stacks the profile does NOT emphasize — surfaced as gaps if required.
_OUT_OF_PROFILE = [
    "gcp", "google cloud", "scala", "ruby", "php", ".net", "golang",
    "openstack", "openshift", "rust", "c++",
]


def _haystack(job: Job) -> str:
    return (job.title + " " + " ".join(job.tags) + " " + job.description).lower()


def classify(job: Job) -> Classification:
    title_l = job.title.lower()
    text = _haystack(job)

    matched = [s for s in _PROFILE_SKILLS if s in text]
    has_core = any(c in title_l for c in _CORE_ROLE)
    is_negative = any(n in title_l for n in _NEGATIVE_TITLE)
    relevant = (has_core or len(matched) >= 4) and not is_negative

    if "mlops" in text or ("machine learning" in text and "ops" in text):
        category = "mlops"
    elif "sre" in title_l or "site reliability" in text or "reliability" in title_l:
        category = "sre"
    elif "platform" in title_l:
        category = "platform"
    elif "devops" in text or "terraform" in text or "kubernetes" in text \
            or "ci/cd" in text:
        category = "devops"
    else:
        category = "other"

    if any(w in title_l for w in ("staff", "principal", "distinguished")):
        seniority = "staff"
    elif any(w in title_l for w in ("senior", "sr.", "sr ", "lead", "iii")):
        seniority = "senior"
    elif any(w in title_l for w in ("junior", "jr.", "jr ", "associate",
                                    "intern", "entry", " i ", " ii ")):
        seniority = "junior"
    else:
        seniority = "mid"

    # Passed the US prefilter already, so treat as US-based.
    return Classification(relevant=relevant, category=category,
                          seniority=seniority, us_based=True)


def rank(job: Job, cls: Classification) -> Ranking:
    text = _haystack(job)
    title_l = job.title.lower()
    matched = [s for s in _PROFILE_SKILLS if s in text]

    score = 40
    score += min(len(set(matched)), 12) * 4          # up to +48
    if any(c in title_l for c in _CORE_ROLE):
        score += 6
    if cls.seniority in ("senior", "staff"):
        score += 6                                    # profile is senior-level
    elif cls.seniority == "junior":
        score -= 12
    if job.remote:
        score += 4
    score = max(0, min(100, score))

    top = list(dict.fromkeys(matched))[:6]
    reason = ("Matches your skills: " + ", ".join(top) + "."
              if top else "Relevant DevOps/MLOps role; limited skill overlap.")

    gaps = [g for g in _OUT_OF_PROFILE if g in text]
    return Ranking(score=score, reason=reason, gaps=gaps)


def score_new(store: Store, jobs: list[Job]) -> tuple[dict, dict]:
    """Classify + rank new jobs locally; persist results.

    Returns (classifications, rankings) keyed by job.key — same shape the
    Claude path produces, so run.py can report identically.
    """
    keys = [j.key for j in jobs]
    todo_keys = set(store.unclassified(keys))
    todo = [j for j in jobs if j.key in todo_keys]
    if not todo:
        log.info("heuristic: nothing to do (all already scored)")
        return {}, {}

    log.info("heuristic: scoring %d jobs locally (no API)", len(todo))
    classifications: dict[str, Classification] = {}
    rankings: dict[str, Ranking] = {}
    for j in todo:
        c = classify(j)
        store.record_classification(
            j.key, relevant=c.relevant, category=c.category,
            seniority=c.seniority, us_based=c.us_based)
        classifications[j.key] = c
        if c.relevant and c.us_based:
            r = rank(j, c)
            store.record_rank(j.key, score=r.score, reason=r.reason,
                              gaps=r.gaps)
            rankings[j.key] = r
    log.info("heuristic: %d relevant, %d ranked",
             sum(1 for c in classifications.values() if c.relevant),
             len(rankings))
    return classifications, rankings
