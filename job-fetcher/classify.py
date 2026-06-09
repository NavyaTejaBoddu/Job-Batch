"""Haiku classifier — the cheap first pass.

For each new prefiltered job, Claude returns strict JSON:
  {relevant, category, seniority, us_based}

We use the SDK's structured-outputs support (`messages.parse` with a Pydantic
model) so the JSON is schema-validated for us. When the new-job count is large,
we switch to the Message Batches API (~50% cheaper, async).

Only NEW jobs reach this module — the store has already gated out anything we
classified on a previous run, so we never re-bill Claude for the same job.
"""

from __future__ import annotations

import logging
import time
from typing import Literal

import anthropic
from pydantic import BaseModel

import config
from models import Job
from store import Store

log = logging.getLogger(__name__)

# Above this many new jobs, use the async Batches API instead of N sync calls.
BATCH_THRESHOLD = 40
_BATCH_POLL_SECONDS = 15
_BATCH_MAX_WAIT_SECONDS = 24 * 3600


class Classification(BaseModel):
    relevant: bool
    category: Literal["devops", "mlops", "platform", "sre", "other"]
    seniority: Literal["junior", "mid", "senior", "staff"]
    us_based: bool


# Hand-written JSON schema for the Batches path (the sync path derives this
# from the Pydantic model automatically via messages.parse).
_CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "category": {"type": "string",
                     "enum": ["devops", "mlops", "platform", "sre", "other"]},
        "seniority": {"type": "string",
                      "enum": ["junior", "mid", "senior", "staff"]},
        "us_based": {"type": "boolean"},
    },
    "required": ["relevant", "category", "seniority", "us_based"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a job-posting classifier for a DevOps engineer's job search. "
    "Decide whether a posting is relevant to DevOps/MLOps/Platform/SRE work, "
    "its primary category, its seniority level, and whether it is US-based "
    "(including remote-US). Be strict: sales, support, marketing, and "
    "non-engineering roles are not relevant."
)


def _user_prompt(job: Job) -> str:
    desc = job.description[:config.DESCRIPTION_TRUNCATE]
    return (
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location: {job.location or 'unknown'}\n"
        f"Tags: {', '.join(job.tags) if job.tags else 'none'}\n\n"
        f"Description:\n{desc}"
    )


def _parse(text: str) -> Classification:
    """Validate a raw JSON string into a Classification (shared by both paths)."""
    return Classification.model_validate_json(text)


# --------------------------------------------------------------------------
# Sync path (one call per job)
# --------------------------------------------------------------------------
def classify_job(client: anthropic.Anthropic, job: Job) -> Classification:
    resp = client.messages.parse(
        model=config.CLASSIFY_MODEL,
        max_tokens=256,
        system=_SYSTEM,
        messages=[{"role": "user", "content": _user_prompt(job)}],
        output_format=Classification,
    )
    if resp.parsed_output is None:
        raise ValueError(f"classifier returned no parsed output for {job.key}")
    return resp.parsed_output


# --------------------------------------------------------------------------
# Batch path (one async batch for many jobs, ~50% cheaper)
# --------------------------------------------------------------------------
def _classify_via_batch(client: anthropic.Anthropic,
                        jobs: list[Job]) -> dict[str, Classification]:
    from anthropic.types.message_create_params import (
        MessageCreateParamsNonStreaming,
    )
    from anthropic.types.messages.batch_create_params import Request

    # custom_id must be [A-Za-z0-9_-], so map index -> job key.
    index_to_key = {f"job-{i}": j.key for i, j in enumerate(jobs)}
    requests = [
        Request(
            custom_id=f"job-{i}",
            params=MessageCreateParamsNonStreaming(
                model=config.CLASSIFY_MODEL,
                max_tokens=256,
                system=_SYSTEM,
                messages=[{"role": "user", "content": _user_prompt(j)}],
                output_config={"format": {"type": "json_schema",
                                          "schema": _CLASSIFY_SCHEMA}},
            ),
        )
        for i, j in enumerate(jobs)
    ]

    batch = client.messages.batches.create(requests=requests)
    log.info("classify batch %s submitted (%d jobs)", batch.id, len(jobs))

    waited = 0
    while True:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        if waited >= _BATCH_MAX_WAIT_SECONDS:
            raise TimeoutError(f"classify batch {batch.id} did not finish")
        time.sleep(_BATCH_POLL_SECONDS)
        waited += _BATCH_POLL_SECONDS

    out: dict[str, Classification] = {}
    for result in client.messages.batches.results(batch.id):
        key = index_to_key.get(result.custom_id)
        if key is None or result.result.type != "succeeded":
            log.warning("classify batch item %s: %s",
                        result.custom_id, result.result.type)
            continue
        msg = result.result.message
        text = next((b.text for b in msg.content if b.type == "text"), "")
        try:
            out[key] = _parse(text)
        except Exception as e:  # noqa: BLE001
            log.warning("classify parse failed for %s: %s", key, e)
    return out


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def classify_new(store: Store, jobs: list[Job]) -> dict[str, Classification]:
    """Classify the given (new) jobs, persist results, and return them.

    Skips any job already classified in the DB (idempotent / no re-billing).
    """
    keys = [j.key for j in jobs]
    todo_keys = set(store.unclassified(keys))
    todo = [j for j in jobs if j.key in todo_keys]
    if not todo:
        log.info("classify: nothing to do (all %d already classified)",
                 len(jobs))
        return {}

    client = anthropic.Anthropic()
    log.info("classify: %d jobs via %s", len(todo),
             "batch" if len(todo) >= BATCH_THRESHOLD else "sync")

    results: dict[str, Classification] = {}
    if len(todo) >= BATCH_THRESHOLD:
        results = _classify_via_batch(client, todo)
    else:
        by_key = {j.key: j for j in todo}
        for j in todo:
            try:
                results[j.key] = classify_job(client, j)
            except Exception as e:  # noqa: BLE001 — one bad job mustn't stop the run
                log.warning("classify failed for %s: %s", j.key, e)
        _ = by_key

    for key, c in results.items():
        store.record_classification(
            key, relevant=c.relevant, category=c.category,
            seniority=c.seniority, us_based=c.us_based)
    log.info("classify: recorded %d classifications", len(results))
    return results
