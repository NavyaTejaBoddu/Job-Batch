"""Sonnet ranker — the smarter second pass.

Only jobs the classifier marked relevant AND us_based reach this stage. For
each, Claude scores fit against my profile and returns strict JSON:
  {score: 0-100, reason: "one sentence", gaps: ["..."]}

Like the classifier, this uses structured outputs for guaranteed-valid JSON
and only ever sees jobs not previously ranked, so reruns don't re-bill.
"""

from __future__ import annotations

import logging

import anthropic
from pydantic import BaseModel, Field

import config
from models import Job
from store import Store

log = logging.getLogger(__name__)


class Ranking(BaseModel):
    score: int = Field(ge=0, le=100)
    reason: str
    gaps: list[str] = Field(default_factory=list)


_SYSTEM = (
    "You are a technical recruiter scoring how well a job posting fits a "
    "specific candidate. Score 0-100 (100 = perfect fit). Weigh required "
    "skills, seniority, domain, and location against the candidate profile. "
    "Give one concise sentence of reasoning and list concrete gaps (skills or "
    "requirements the candidate may not meet). Be calibrated: reserve 85+ for "
    "strong matches.\n\nCANDIDATE PROFILE:\n" + config.PROFILE
)


def _user_prompt(job: Job) -> str:
    desc = job.description[:config.DESCRIPTION_TRUNCATE]
    salary = ""
    if job.salary_min or job.salary_max:
        salary = f"Salary: {job.salary_min} - {job.salary_max}\n"
    return (
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location: {job.location or 'unknown'}\n"
        f"{salary}"
        f"Tags: {', '.join(job.tags) if job.tags else 'none'}\n\n"
        f"Description:\n{desc}"
    )


def _parse(text: str) -> Ranking:
    """Validate a raw JSON string into a Ranking (shared / testable)."""
    return Ranking.model_validate_json(text)


def rank_job(client: anthropic.Anthropic, job: Job) -> Ranking:
    resp = client.messages.parse(
        model=config.RANK_MODEL,
        max_tokens=512,
        system=_SYSTEM,
        messages=[{"role": "user", "content": _user_prompt(job)}],
        output_format=Ranking,
    )
    if resp.parsed_output is None:
        raise ValueError(f"ranker returned no parsed output for {job.key}")
    return resp.parsed_output


def rank_relevant(store: Store, jobs: list[Job],
                  classifications: dict[str, object]) -> dict[str, Ranking]:
    """Rank only jobs the classifier marked relevant AND us_based.

    `classifications` maps job.key -> Classification. Persists scores and
    returns them.
    """
    targets = [
        j for j in jobs
        if (c := classifications.get(j.key)) is not None
        and getattr(c, "relevant", False) and getattr(c, "us_based", False)
    ]
    if not targets:
        log.info("rank: no relevant+us_based jobs to rank")
        return {}

    client = anthropic.Anthropic()
    log.info("rank: scoring %d relevant jobs", len(targets))

    results: dict[str, Ranking] = {}
    for j in targets:
        try:
            r = rank_job(client, j)
            store.record_rank(j.key, score=r.score, reason=r.reason,
                              gaps=r.gaps)
            results[j.key] = r
        except Exception as e:  # noqa: BLE001 — one bad job mustn't stop the run
            log.warning("rank failed for %s: %s", j.key, e)
    log.info("rank: recorded %d rankings", len(results))
    return results
