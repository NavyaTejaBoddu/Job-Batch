"""Local (no-API) generation for a job card's "kit".

Currently produces a recruiter/hiring-manager outreach message, tailored from
the candidate profile + the specific job. Pure templating — no network, no LLM.
"""

from __future__ import annotations

import config

# Skills to look for in the job text so the message can name relevant overlaps.
_PROFILE_SKILLS = [
    "AWS", "Azure", "Terraform", "Ansible", "CloudFormation",
    "Kubernetes", "Helm", "EKS", "AKS", "Docker",
    "Jenkins", "GitHub Actions", "Azure DevOps", "ArgoCD", "CI/CD",
    "Prometheus", "Grafana", "ELK", "CloudWatch",
    "Python", "Bash", "Linux", "SRE", "observability",
]

_HIGHLIGHTS = [
    "cut deployment time 45% through a CI/CD pipeline redesign",
    "ran multi-zone EKS/AKS clusters at 99.95% uptime",
    "authored reusable Terraform modules to standardize infra across environments",
]


def _matched_skills(text: str, limit: int = 4) -> list[str]:
    low = (text or "").lower()
    out: list[str] = []
    for s in _PROFILE_SKILLS:
        if s.lower() in low and s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def recruiter_message(title: str, company: str, description: str = "") -> str:
    """A concise, ready-to-send outreach message for this role."""
    name = config.CANDIDATE_NAME
    email = config.CANDIDATE_EMAIL
    headline = config.CANDIDATE_HEADLINE
    role = (title or "the open DevOps role").strip()
    org = (company or "your team").strip()

    matched = _matched_skills(f"{title} {description}")
    if matched:
        overlap = (
            f"My day-to-day maps closely to what you're hiring for — "
            f"especially {', '.join(matched[:-1])}"
            + (f", and {matched[-1]}" if len(matched) > 1 else matched[0])
            + "."
        )
    else:
        overlap = (
            "My background in cloud infrastructure, containers, and CI/CD "
            "lines up well with this role."
        )

    highlights = "; ".join(_HIGHLIGHTS)

    return (
        f"Hi,\n\n"
        f"I came across the {role} position at {org} and wanted to reach out — "
        f"it's a strong match for my background. I'm {name}, a {headline}.\n\n"
        f"{overlap} A few things I've recently delivered: {highlights}.\n\n"
        f"I'd love to learn more about the team and how I could contribute. "
        f"Would you be open to a quick conversation? I'm happy to share more "
        f"detail or my resume.\n\n"
        f"Best regards,\n"
        f"{name}\n"
        f"{email}"
    )


def generate(card: dict) -> str:
    """Dispatch for a card dict. (Only recruiter outreach for now.)"""
    return recruiter_message(
        card.get("title", ""), card.get("company", ""),
        card.get("description", ""))
