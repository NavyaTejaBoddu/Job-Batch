"""All job-source fetchers + fetch_all().

Each fetcher returns list[Job] in the common schema. Network/parse errors
inside a single source are caught by fetch_all() so one bad source never
crashes the run. HTTP is polite: descriptive User-Agent, 30s timeout, and a
small per-host delay.

Milestone 1 implements Group A direct ATS feeds: Greenhouse, Lever, Ashby.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

import config
from models import Job, make_id, parse_date, strip_html

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Shared polite HTTP client with per-host throttling.
# --------------------------------------------------------------------------
_client: httpx.Client | None = None
_last_hit: dict[str, float] = {}


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=config.HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": config.USER_AGENT},
        )
    return _client


def _throttle(url: str) -> None:
    """Sleep so we don't hit the same host faster than PER_HOST_DELAY."""
    host = urlparse(url).netloc
    now = time.monotonic()
    last = _last_hit.get(host)
    if last is not None:
        wait = config.PER_HOST_DELAY - (now - last)
        if wait > 0:
            time.sleep(wait)
    _last_hit[host] = time.monotonic()


def http_get(url: str, *, headers: dict[str, str] | None = None,
             params: dict[str, Any] | None = None) -> httpx.Response:
    """Throttled GET that raises on HTTP error status."""
    _throttle(url)
    resp = _get_client().get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp


# ==========================================================================
# Group A — direct ATS feeds
# ==========================================================================
def fetch_greenhouse(slug: str) -> list[Job]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    data = http_get(url, params={"content": "true"}).json()
    company = _board_company(data) or slug.replace("-", " ").title()
    jobs: list[Job] = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name")
        tags = [d.get("name", "") for d in (j.get("departments") or [])]
        jobs.append(Job(
            source="greenhouse",
            external_id=str(j["id"]),
            company=company,
            title=j.get("title", "").strip(),
            url=j.get("absolute_url", ""),
            location=loc,
            description=strip_html(j.get("content")),
            posted_at=parse_date(j.get("updated_at") or j.get("first_published")),
            remote=_looks_remote(loc),
            tags=[t for t in tags if t],
        ))
    return jobs


def _board_company(data: dict[str, Any]) -> str | None:
    # Greenhouse jobs payload doesn't always carry the org name; some boards
    # nest it. Fall back to None and let the caller use the slug.
    meta = data.get("meta") or {}
    return meta.get("company") or data.get("name")


def fetch_lever(slug: str) -> list[Job]:
    url = f"https://api.lever.co/v0/postings/{slug}"
    data = http_get(url, params={"mode": "json"}).json()
    company = slug.replace("-", " ").title()
    jobs: list[Job] = []
    for j in data:
        cats = j.get("categories") or {}
        loc = cats.get("location")
        # createdAt is unix milliseconds.
        salary_min, salary_max = _lever_salary(j)
        tags = [v for v in (cats.get("team"), cats.get("commitment"),
                            cats.get("department")) if v]
        jobs.append(Job(
            source="lever",
            external_id=str(j.get("id") or make_id(j.get("hostedUrl"))),
            company=company,
            title=(j.get("text") or "").strip(),
            url=j.get("hostedUrl") or j.get("applyUrl", ""),
            location=loc,
            description=j.get("descriptionPlain") or strip_html(j.get("description")),
            posted_at=parse_date(j.get("createdAt")),
            remote=_looks_remote(" ".join(filter(None, [loc, cats.get("commitment")]))),
            salary_min=salary_min,
            salary_max=salary_max,
            tags=tags,
        ))
    return jobs


def _lever_salary(j: dict[str, Any]) -> tuple[float | None, float | None]:
    sal = j.get("salaryRange") or {}
    return _as_float(sal.get("min")), _as_float(sal.get("max"))


def fetch_ashby(slug: str) -> list[Job]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    data = http_get(url, params={"includeCompensation": "true"}).json()
    company = data.get("organizationName") or slug.replace("-", " ").title()
    jobs: list[Job] = []
    for j in data.get("jobs", []):
        loc = j.get("location")
        salary_min, salary_max = _ashby_salary(j)
        tags = [v for v in (j.get("department"), j.get("team"),
                            j.get("employmentType")) if v]
        jobs.append(Job(
            source="ashby",
            external_id=str(j.get("id") or make_id(j.get("jobUrl"))),
            company=company,
            title=(j.get("title") or "").strip(),
            url=j.get("jobUrl") or j.get("applyUrl", ""),
            location=loc,
            description=j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")),
            posted_at=parse_date(j.get("publishedAt")),
            remote=j.get("isRemote") if j.get("isRemote") is not None
            else _looks_remote(loc),
            salary_min=salary_min,
            salary_max=salary_max,
            tags=tags,
        ))
    return jobs


def _ashby_salary(j: dict[str, Any]) -> tuple[float | None, float | None]:
    comp = j.get("compensation") or {}
    tiers = comp.get("compensationTiers") or []
    lows: list[float] = []
    highs: list[float] = []
    for t in tiers:
        for comp_part in t.get("components", []):
            lo = _as_float(comp_part.get("minValue"))
            hi = _as_float(comp_part.get("maxValue"))
            if lo is not None:
                lows.append(lo)
            if hi is not None:
                highs.append(hi)
    return (min(lows) if lows else None, max(highs) if highs else None)


def fetch_workable(slug: str) -> list[Job]:
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
    data = http_get(url, params={"details": "true"}).json()
    company = data.get("name") or slug.replace("-", " ").title()
    jobs: list[Job] = []
    for j in data.get("jobs", []):
        loc = _loc_str(j.get("city"), j.get("state"), j.get("country")) \
            or j.get("location")
        remote = j.get("telecommuting")
        if remote is None:
            remote = _looks_remote(loc)
        jobs.append(Job(
            source="workable",
            external_id=str(j.get("shortcode") or j.get("code")
                            or make_id(j.get("url"))),
            company=company,
            title=(j.get("title") or "").strip(),
            url=j.get("url") or j.get("application_url", ""),
            location=loc,
            description=strip_html(j.get("description")),
            posted_at=parse_date(j.get("published_on") or j.get("created_at")),
            remote=remote,
            tags=[v for v in (j.get("department"), j.get("function"),
                              j.get("employment_type")) if v],
        ))
    return jobs


def fetch_recruitee(slug: str) -> list[Job]:
    url = f"https://{slug}.recruitee.com/api/offers/"
    data = http_get(url).json()
    jobs: list[Job] = []
    for j in data.get("offers", []):
        loc = j.get("location") or _loc_str(
            j.get("city"), j.get("state_name"), j.get("country"))
        desc = "\n\n".join(filter(None, [
            strip_html(j.get("description")),
            strip_html(j.get("requirements")),
        ]))
        jobs.append(Job(
            source="recruitee",
            external_id=str(j.get("id") or make_id(j.get("careers_url"))),
            company=j.get("company_name") or slug.replace("-", " ").title(),
            title=(j.get("title") or j.get("position") or "").strip(),
            url=j.get("careers_url") or j.get("careers_apply_url", ""),
            location=loc,
            description=desc,
            posted_at=parse_date(j.get("published_at") or j.get("created_at")),
            remote=bool(j.get("remote")) if j.get("remote") is not None
            else _looks_remote(loc),
            tags=list(j.get("tags") or []) + (
                [j["department"]] if j.get("department") else []),
        ))
    return jobs


def fetch_personio(slug: str) -> list[Job]:
    # Some accounts live on .de, others on .com — try both.
    last_err: Exception | None = None
    for tld in ("de", "com"):
        url = f"https://{slug}.jobs.personio.{tld}/xml"
        try:
            resp = http_get(url, params={"language": "en"})
            return _parse_personio_xml(resp.text, slug, tld)
        except httpx.HTTPError as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    return []


def _parse_personio_xml(xml_text: str, slug: str, tld: str) -> list[Job]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_text)
    jobs: list[Job] = []
    for pos in root.iter("position"):
        pid = _xml_text(pos, "id")
        if not pid:
            continue
        title = _xml_text(pos, "name") or ""
        office = _xml_text(pos, "office")
        # jobDescriptions -> jobDescription -> name/value (HTML).
        parts: list[str] = []
        jd = pos.find("jobDescriptions")
        if jd is not None:
            for d in jd.findall("jobDescription"):
                name = _xml_text(d, "name")
                value = strip_html(_xml_text(d, "value"))
                parts.append(f"{name}\n{value}" if name else value)
        tags = [v for v in (_xml_text(pos, "department"),
                            _xml_text(pos, "employmentType"),
                            _xml_text(pos, "seniority")) if v]
        jobs.append(Job(
            source="personio",
            external_id=str(pid),
            company=slug.replace("-", " ").title(),
            title=title.strip(),
            url=f"https://{slug}.jobs.personio.{tld}/job/{pid}",
            location=office,
            description="\n\n".join(p for p in parts if p).strip(),
            posted_at=parse_date(_xml_text(pos, "createdAt")),
            remote=_looks_remote(office),
            tags=tags,
        ))
    return jobs


def _xml_text(parent, tag: str) -> str | None:
    if parent is None:
        return None
    el = parent.find(tag)
    if el is None or el.text is None:
        return None
    return el.text.strip()


def fetch_smartrecruiters(slug: str) -> list[Job]:
    # List endpoint has no description; fetch each posting's full ad (capped).
    list_url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    data = http_get(list_url, params={"limit": 100}).json()
    content = data.get("content", [])
    jobs: list[Job] = []
    for i, item in enumerate(content):
        pid = item.get("id")
        if not pid:
            continue
        loc = (item.get("location") or {})
        loc_str = loc.get("fullLocation") or _loc_str(
            loc.get("city"), loc.get("region"), loc.get("country"))
        description = ""
        apply_url = item.get("ref", "")
        if i < config.SMARTRECRUITERS_DETAIL_CAP:
            try:
                detail = http_get(f"{list_url}/{pid}").json()
                description = _smartrecruiters_desc(detail)
                apply_url = detail.get("applyUrl") or detail.get(
                    "postingUrl") or apply_url
            except httpx.HTTPError as e:
                log.debug("smartrecruiters/%s detail %s failed: %s",
                          slug, pid, e)
        remote = bool(loc.get("remote")) if loc.get("remote") is not None \
            else _looks_remote(loc_str)
        jobs.append(Job(
            source="smartrecruiters",
            external_id=str(pid),
            company=(item.get("company") or {}).get("name") or slug,
            title=(item.get("name") or "").strip(),
            url=apply_url,
            location=loc_str,
            description=description,
            posted_at=parse_date(item.get("releasedDate")),
            remote=remote,
            tags=[v.get("label", "") for v in
                  ((item.get("department"), item.get("function"))) if v
                  and isinstance(v, dict)],
        ))
    return jobs


def _smartrecruiters_desc(detail: dict[str, Any]) -> str:
    sections = ((detail.get("jobAd") or {}).get("sections") or {})
    order = ("companyDescription", "jobDescription",
             "qualifications", "additionalInformation")
    parts: list[str] = []
    for key in order:
        sec = sections.get(key) or {}
        text = strip_html(sec.get("text"))
        if text:
            parts.append(text)
    return "\n\n".join(parts).strip()


# ==========================================================================
# Group B — aggregators
# ==========================================================================
def fetch_remotive() -> list[Job]:
    jobs: dict[str, Job] = {}
    for query in config.AGGREGATOR_QUERIES:
        url = "https://remotive.com/api/remote-jobs"
        data = http_get(url, params={"search": query}).json()
        for j in data.get("jobs", []):
            loc = j.get("candidate_required_location")
            job = Job(
                source="remotive",
                external_id=str(j.get("id") or make_id(j.get("url"))),
                company=j.get("company_name") or "",
                title=(j.get("title") or "").strip(),
                url=j.get("url", ""),
                location=loc,
                description=strip_html(j.get("description")),
                posted_at=parse_date(j.get("publication_date")),
                remote=True,
                tags=list(j.get("tags") or []) + (
                    [j["category"]] if j.get("category") else []),
            )
            jobs[job.key] = job
    return list(jobs.values())


def fetch_remoteok() -> list[Job]:
    data = http_get("https://remoteok.com/api").json()
    jobs: list[Job] = []
    # First element is a legal/metadata notice — skip anything without an id.
    for j in data:
        if not isinstance(j, dict) or "id" not in j:
            continue
        title = (j.get("position") or j.get("title") or "").strip()
        tags = list(j.get("tags") or [])
        if not _keyword_match(title, tags):
            continue
        loc = j.get("location") or "Remote"
        jobs.append(Job(
            source="remoteok",
            external_id=str(j["id"]),
            company=j.get("company") or "",
            title=title,
            url=j.get("url", ""),
            location=loc,
            description=strip_html(j.get("description")),
            posted_at=parse_date(j.get("date") or j.get("epoch")),
            remote=True,
            salary_min=_as_float(j.get("salary_min")),
            salary_max=_as_float(j.get("salary_max")),
            tags=tags,
        ))
    return jobs


def fetch_arbeitnow() -> list[Job]:
    jobs: dict[str, Job] = {}
    for page in range(1, config.MAX_PAGES + 1):
        url = "https://www.arbeitnow.com/api/job-board-api"
        data = http_get(url, params={"page": page}).json()
        rows = data.get("data", [])
        if not rows:
            break
        for j in rows:
            job = Job(
                source="arbeitnow",
                external_id=str(j.get("slug") or make_id(j.get("url"))),
                company=j.get("company_name") or "",
                title=(j.get("title") or "").strip(),
                url=j.get("url", ""),
                location=j.get("location"),
                description=strip_html(j.get("description")),
                posted_at=parse_date(j.get("created_at")),
                remote=bool(j.get("remote")),
                tags=list(j.get("tags") or []) + list(j.get("job_types") or []),
            )
            jobs[job.key] = job
    return list(jobs.values())


_WWR_FEEDS = [
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
]


def fetch_weworkremotely() -> list[Job]:
    import xml.etree.ElementTree as ET

    jobs: dict[str, Job] = {}
    for feed in _WWR_FEEDS:
        resp = http_get(feed)
        root = ET.fromstring(resp.content)
        for item in root.iter("item"):
            link = _xml_text(item, "link") or ""
            raw_title = _xml_text(item, "title") or ""
            # Title format is "Company: Role".
            if ": " in raw_title:
                company, _, title = raw_title.partition(": ")
            else:
                company, title = "", raw_title
            region = _xml_text(item, "region")
            job = Job(
                source="weworkremotely",
                external_id=_xml_text(item, "guid") or make_id(link),
                company=company.strip(),
                title=title.strip(),
                url=link,
                location=region or "Remote",
                description=strip_html(_xml_text(item, "description")),
                posted_at=parse_date(_xml_text(item, "pubDate")),
                remote=True,
                tags=[t for t in [_xml_text(item, "category")] if t],
            )
            jobs[job.key] = job
    return list(jobs.values())


def fetch_adzuna() -> list[Job]:
    app_id, app_key = config.adzuna_keys()
    if not app_id or not app_key:
        log.info("adzuna: ADZUNA_APP_ID/ADZUNA_APP_KEY unset — skipping")
        return []
    jobs: dict[str, Job] = {}
    for page in range(1, config.MAX_PAGES + 1):
        url = f"https://api.adzuna.com/v1/api/jobs/us/search/{page}"
        params = {
            "app_id": app_id, "app_key": app_key, "what": "devops",
            "results_per_page": 50, "content-type": "application/json",
        }
        data = http_get(url, params=params).json()
        rows = data.get("results", [])
        if not rows:
            break
        for j in rows:
            loc = (j.get("location") or {}).get("display_name")
            job = Job(
                source="adzuna",
                external_id=str(j.get("id") or make_id(j.get("redirect_url"))),
                company=(j.get("company") or {}).get("display_name") or "",
                title=(j.get("title") or "").strip(),
                url=j.get("redirect_url", ""),
                location=loc,
                description=strip_html(j.get("description")),
                posted_at=parse_date(j.get("created")),
                remote=_looks_remote(loc),
                salary_min=_as_float(j.get("salary_min")),
                salary_max=_as_float(j.get("salary_max")),
                tags=[c for c in [(j.get("category") or {}).get("label")] if c],
            )
            jobs[job.key] = job
    return list(jobs.values())


def fetch_usajobs() -> list[Job]:
    email, key = config.usajobs_keys()
    if not email or not key:
        log.info("usajobs: USAJOBS_EMAIL/USAJOBS_API_KEY unset — skipping")
        return []
    url = "https://data.usajobs.gov/api/search"
    headers = {
        "Host": "data.usajobs.gov",
        "User-Agent": email,
        "Authorization-Key": key,
    }
    data = http_get(url, headers=headers,
                    params={"Keyword": "devops", "ResultsPerPage": 50}).json()
    items = (data.get("SearchResult") or {}).get("SearchResultItems", [])
    jobs: list[Job] = []
    for it in items:
        d = it.get("MatchedObjectDescriptor") or {}
        remun = d.get("PositionRemuneration") or [{}]
        salary_min = _as_float(remun[0].get("MinimumRange"))
        salary_max = _as_float(remun[0].get("MaximumRange"))
        summary = ((d.get("UserArea") or {}).get("Details") or {}).get(
            "JobSummary") or d.get("QualificationSummary") or ""
        jobs.append(Job(
            source="usajobs",
            external_id=str(it.get("MatchedObjectId")
                            or make_id(d.get("PositionURI"))),
            company=d.get("OrganizationName") or "",
            title=(d.get("PositionTitle") or "").strip(),
            url=d.get("PositionURI", ""),
            location=d.get("PositionLocationDisplay"),
            description=strip_html(summary),
            posted_at=parse_date(d.get("PublicationStartDate")
                                 or d.get("PositionStartDate")),
            remote=_looks_remote(d.get("PositionLocationDisplay")),
            salary_min=salary_min,
            salary_max=salary_max,
            tags=[jc.get("Name", "") for jc in (d.get("JobCategory") or [])],
        ))
    return jobs


# --------------------------------------------------------------------------
# Small shared helpers
# --------------------------------------------------------------------------
def _loc_str(*parts: str | None) -> str | None:
    vals = [p.strip() for p in parts if p and p.strip()]
    return ", ".join(vals) if vals else None


def _keyword_match(title: str, tags: list[str]) -> bool:
    haystack = (title + " " + " ".join(tags)).lower()
    return any(k in haystack for k in config.RELEVANCE_KEYWORDS)
def _as_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _looks_remote(text: str | None) -> bool | None:
    if not text:
        return None
    return "remote" in text.lower()


# ==========================================================================
# Orchestration
# ==========================================================================
def _safe(label: str, thunk: Callable[[], list[Job]]) -> list[Job]:
    """Run a fetcher, logging and swallowing any failure so the run survives."""
    try:
        jobs = thunk()
        log.info("%s: %d jobs", label, len(jobs))
        return jobs
    except httpx.HTTPStatusError as e:
        log.warning("%s: HTTP %s", label, e.response.status_code)
    except httpx.HTTPError as e:
        log.warning("%s: request failed: %s", label, e)
    except Exception as e:  # noqa: BLE001 — never let one source kill the run
        log.warning("%s: parse error: %s", label, e)
    return []


# Per-source-type (slug, fetcher) wiring for Group A.
_GROUP_A: list[tuple[str, list[str], Callable[[str], list[Job]]]] = [
    ("greenhouse", config.GREENHOUSE, fetch_greenhouse),
    ("lever", config.LEVER, fetch_lever),
    ("ashby", config.ASHBY, fetch_ashby),
    ("workable", config.WORKABLE, fetch_workable),
    ("recruitee", config.RECRUITEE, fetch_recruitee),
    ("personio", config.PERSONIO, fetch_personio),
    ("smartrecruiters", config.SMARTRECRUITERS, fetch_smartrecruiters),
]

# Slugless Group B aggregators.
_GROUP_B: list[tuple[str, Callable[[], list[Job]]]] = [
    ("remotive", fetch_remotive),
    ("remoteok", fetch_remoteok),
    ("arbeitnow", fetch_arbeitnow),
    ("weworkremotely", fetch_weworkremotely),
    ("adzuna", fetch_adzuna),
    ("usajobs", fetch_usajobs),
]


def fetch_group_a() -> list[Job]:
    """Every configured Group A company across all ATS feeds."""
    jobs: list[Job] = []
    for source, slugs, fn in _GROUP_A:
        for slug in slugs:
            jobs += _safe(f"{source}/{slug}", lambda fn=fn, slug=slug: fn(slug))
    return jobs


def fetch_group_b() -> list[Job]:
    """Every aggregator source (Adzuna/USAJobs self-skip without keys)."""
    jobs: list[Job] = []
    for source, fn in _GROUP_B:
        jobs += _safe(source, fn)
    return jobs


def fetch_all() -> list[Job]:
    """All sources, Group A + Group B."""
    return fetch_group_a() + fetch_group_b()
