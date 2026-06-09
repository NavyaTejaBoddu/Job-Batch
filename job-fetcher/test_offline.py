"""Offline tests for classify.py / rank.py — no network, no billing.

We mock the Anthropic client so we can verify:
  - the structured-output parsing/validation logic,
  - that results are persisted to the store,
  - that the rank stage only sees relevant + us_based jobs.

Run: python test_offline.py
"""

from __future__ import annotations

import os
import sys
import tempfile

import classify
import rank
from classify import Classification
from models import Job
from rank import Ranking
from store import Store


def _force_utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


# --------------------------------------------------------------------------
# Fake Anthropic client: returns whatever the mapped output_format expects.
# --------------------------------------------------------------------------
class _Resp:
    def __init__(self, parsed):
        self.parsed_output = parsed


class FakeClient:
    """Stands in for anthropic.Anthropic(). Records calls; returns canned objs."""

    def __init__(self, classification=None, ranking=None):
        self._classification = classification
        self._ranking = ranking
        self.calls = 0
        self.messages = self  # so client.messages.parse(...) works

    def parse(self, **kwargs):
        self.calls += 1
        fmt = kwargs.get("output_format")
        if fmt is Classification:
            return _Resp(self._classification)
        if fmt is Ranking:
            return _Resp(self._ranking)
        raise AssertionError(f"unexpected output_format {fmt}")


def _job(key_id: str, title: str, loc: str | None = "Remote, US") -> Job:
    return Job(source="greenhouse", external_id=key_id, company="Acme",
               title=title, url="https://x/1", location=loc,
               description="We use Terraform, Kubernetes, AWS, CI/CD. " * 150)


PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
_failures = 0


def check(name: str, cond: bool) -> None:
    global _failures
    print(f"  [{PASS if cond else FAIL}] {name}")
    if not cond:
        _failures += 1


def main() -> None:
    _force_utf8()
    print("=" * 70)
    print("OFFLINE CLAUDE-STAGE TESTS (mocked client, no API calls)")
    print("=" * 70)

    # 1. Strict JSON parsing / validation
    print("\n1. structured-output parsing")
    c = classify._parse(
        '{"relevant": true, "category": "devops", '
        '"seniority": "senior", "us_based": true}')
    check("classify parses valid JSON", isinstance(c, Classification)
          and c.relevant and c.category == "devops")
    r = rank._parse('{"score": 87, "reason": "Strong AWS/Terraform fit.", '
                    '"gaps": ["No GCP experience"]}')
    check("rank parses valid JSON", isinstance(r, Ranking) and r.score == 87
          and r.gaps == ["No GCP experience"])

    bad = False
    try:
        classify._parse('{"category": "devops"}')  # missing required fields
    except Exception:
        bad = True
    check("classify rejects incomplete JSON", bad)

    bad2 = False
    try:
        rank._parse('{"score": 250, "reason": "x", "gaps": []}')  # out of range
    except Exception:
        bad2 = True
    check("rank rejects score > 100", bad2)

    # 2. Prompt building + truncation
    print("\n2. prompt building")
    import config as cfg
    j = _job("1", "Senior DevOps Engineer")
    prompt = classify._user_prompt(j)
    check("description is long enough to test truncation",
          len(j.description) > cfg.DESCRIPTION_TRUNCATE)
    check("classify prompt truncates description to limit",
          len(prompt) < len(j.description) + 500)
    check("rank prompt includes title", "Senior DevOps Engineer"
          in rank._user_prompt(j))

    # 3. classify_job / rank_job with mocked client
    print("\n3. single-job calls (mocked)")
    fake_c = FakeClient(classification=Classification(
        relevant=True, category="devops", seniority="senior", us_based=True))
    out = classify.classify_job(fake_c, j)
    check("classify_job returns Classification", out.category == "devops"
          and fake_c.calls == 1)
    fake_r = FakeClient(ranking=Ranking(
        score=82, reason="Great fit.", gaps=["No GCP"]))
    out_r = rank.rank_job(fake_r, j)
    check("rank_job returns Ranking", out_r.score == 82 and fake_r.calls == 1)

    # 4. End-to-end stage wiring against a temp DB
    print("\n4. classify_new + rank_relevant persist to store")
    tmp = tempfile.mktemp(suffix=".db")
    store = Store(tmp)
    jobs = [_job("100", "Senior SRE"), _job("101", "Sales Executive",
                                            loc="Remote, US")]
    store.add_new(jobs, first_seen="2026-06-09")

    # Monkeypatch anthropic.Anthropic so the stages use our fake client.
    import anthropic
    real = anthropic.Anthropic
    # job 100 -> relevant devops/US; job 101 -> classify the same here, but
    # we'll flip relevance per-key below via a smarter fake.

    class RoutingFake(FakeClient):
        def parse(self, **kwargs):
            self.calls += 1
            content = kwargs["messages"][0]["content"]
            fmt = kwargs.get("output_format")
            if fmt is Classification:
                relevant = "Sales" not in content
                return _Resp(Classification(
                    relevant=relevant,
                    category="devops" if relevant else "other",
                    seniority="senior",
                    us_based=True))
            return _Resp(Ranking(score=90, reason="Strong match.",
                                 gaps=[]))

    anthropic.Anthropic = lambda *a, **k: RoutingFake()  # type: ignore
    try:
        classifications = classify.classify_new(store, jobs)
        check("classify_new classified both jobs", len(classifications) == 2)
        check("classifier marked SRE relevant",
              classifications["greenhouse:100"].relevant is True)
        check("classifier marked Sales NOT relevant",
              classifications["greenhouse:101"].relevant is False)

        rankings = rank.rank_relevant(store, jobs, classifications)
        check("rank only ran on the relevant job", len(rankings) == 1
              and "greenhouse:100" in rankings)

        # Persistence: re-read from DB
        row = store.get("greenhouse:100")
        check("classification persisted", row["classified"] == 1
              and row["relevant"] == 1)
        check("ranking persisted", row["ranked"] == 1 and row["score"] == 90)

        # Idempotency: nothing left to classify on a second pass
        again = classify.classify_new(store, jobs)
        check("second classify pass is a no-op (no re-billing)",
              len(again) == 0)
    finally:
        anthropic.Anthropic = real
        store.close()
        try:
            os.remove(tmp)
        except OSError:
            pass

    print("\n" + "=" * 70)
    if _failures:
        print(f"{_failures} FAILURE(S)")
        sys.exit(1)
    print("ALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
