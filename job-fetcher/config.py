"""Static configuration: company lists, keywords, profile, env-based keys.

Nothing secret lives here. All credentials are read from environment
variables at the point of use (see the helpers at the bottom).
"""

from __future__ import annotations

import os

# --------------------------------------------------------------------------
# Group A — direct ATS feeds. I supply company slugs; the pipeline fetches
# every open role and filters for US/relevance later.
# --------------------------------------------------------------------------
GREENHOUSE = [
    "stripe", "databricks", "anthropic", "datadog", "cloudflare",
    "robinhood", "instacart", "coinbase", "dropbox", "figma", "gitlab",
]
LEVER = ["netflix", "plaid"]
ASHBY = [
    "snowflake", "ramp", "notion", "linear", "vanta", "retool",
    "mercury", "zapier", "replit", "cursor",
]
# The slugs below are verified-working examples so each fetcher can be tested.
# Many are EU-based and get trimmed by the later US filter — swap in your own.
WORKABLE = ["huggingface"]
RECRUITEE = ["gorgias"]
PERSONIO = ["personio"]              # tries .jobs.personio.de then .com
SMARTRECRUITERS = ["Visa"]           # company identifier, case-sensitive

# --------------------------------------------------------------------------
# Group B aggregator search terms (Remotive/RemoteOK keyword queries)
# --------------------------------------------------------------------------
AGGREGATOR_QUERIES = ["devops", "sre", "platform engineer", "mlops"]
SMARTRECRUITERS_DETAIL_CAP = 60      # cap per-posting detail fetches

# --------------------------------------------------------------------------
# Relevance keyword prefilter (matched against title + tags, case-insensitive)
# --------------------------------------------------------------------------
RELEVANCE_KEYWORDS = [
    "devops", "mlops", "sre", "site reliability", "platform engineer",
    "infrastructure", "cloud engineer", "kubernetes", "ci/cd", "terraform",
]

# --------------------------------------------------------------------------
# HTTP politeness
# --------------------------------------------------------------------------
USER_AGENT = (
    "job-search-copilot/1.0 (DevOps job digest; "
    "contact: boddunavyateja@gmail.com)"
)
HTTP_TIMEOUT = 30.0          # seconds
PER_HOST_DELAY = 1.0         # seconds between requests to the same host
MAX_PAGES = 5                # pagination cap for aggregators

# --------------------------------------------------------------------------
# Claude models
# --------------------------------------------------------------------------
CLASSIFY_MODEL = "claude-haiku-4-5-20251001"
RANK_MODEL = "claude-sonnet-4-6"
DESCRIPTION_TRUNCATE = 4000  # chars sent to Claude

# --------------------------------------------------------------------------
# Local storage / output paths (relative to this package directory)
# --------------------------------------------------------------------------
import os.path as _osp

_HERE = _osp.dirname(_osp.abspath(__file__))
DB_PATH = _osp.join(_HERE, "jobs.db")
DIGEST_DIR = _osp.join(_HERE, "digests")
MATCHES_CSV = _osp.join(_HERE, "matches.csv")

# Secondary recency window: optionally ignore postings older than this many
# days by their source timestamp (the DB is still the source of truth for
# novelty). Set to None to disable.
RECENCY_DAYS: int | None = None

# --------------------------------------------------------------------------
# My profile — passed to the Sonnet ranker.
# --------------------------------------------------------------------------
PROFILE = """Navya Teja Boddu
USA | DevOps Engineer | AWS & Azure | Kubernetes, Terraform, CI/CD, Docker

DevOps Engineer with 6 years of hands-on experience building and operating
CI/CD pipelines, Kubernetes clusters, and cloud infrastructure on AWS and Azure
for healthcare (HIPAA) and banking (PCI-DSS) enterprises. Reduced deployment
time by 45% through pipeline redesign. Strong in Terraform IaC, container
orchestration (EKS/AKS), and observability (Prometheus/Grafana).

Strong: AWS, Azure, Terraform, Ansible, Kubernetes/Helm, EKS/AKS,
CI/CD (Jenkins, GitHub Actions, Azure DevOps, ArgoCD), Docker, Linux,
observability (Prometheus, Grafana, ELK, CloudWatch), scripting (Python, Bash).

Certifications: AWS DevOps Engineer Professional, Azure DevOps Engineer Expert,
AWS Solutions Architect Associate, CKA, HashiCorp Terraform Associate.

Interested in: DevOps, Platform, SRE, and MLOps roles, senior level.
Based in the USA. Open to remote-US or hybrid.
"""


# --------------------------------------------------------------------------
# Environment-based credentials (read lazily; never hardcoded)
# --------------------------------------------------------------------------
def adzuna_keys() -> tuple[str | None, str | None]:
    return os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")


def usajobs_keys() -> tuple[str | None, str | None]:
    return os.getenv("USAJOBS_EMAIL"), os.getenv("USAJOBS_API_KEY")


def smtp_config() -> dict[str, str | None]:
    return {
        "host": os.getenv("SMTP_HOST"),
        "port": os.getenv("SMTP_PORT", "587"),
        "user": os.getenv("SMTP_USER"),
        "password": os.getenv("SMTP_PASS"),
        "to": os.getenv("DIGEST_TO"),
    }
