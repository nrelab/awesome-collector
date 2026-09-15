from typing import Optional

from src.models import Repository


def calculate_security_score(
    has_security_policy: bool = False,
    has_vulnerability_tool: bool = False,
    has_copilot: bool = False,
    has_dependabot: bool = False,
) -> float:
    score = 0.0
    if has_security_policy:
        score += 30
    if has_vulnerability_tool:
        score += 30
    if has_copilot:
        score += 20
    if has_dependabot:
        score += 20
    return score


def check_security_policy(repo: Repository) -> bool:
    return bool(repo.topics and "security" in [t.lower() for t in repo.topics])


def check_vulnerability_tool(repo: Repository) -> bool:
    name_lower = repo.name.lower()
    desc_lower = (repo.description or "").lower()
    security_tools = [
        "dependabot", "snyk", "snyk-lab", "trivy", "grype", "safety",
        "bandit", "semgrep", "sonar", "codeql", "oss-index", "npm audit",
        "auditjs", "retire", "license-checker", "safety", "pip-audit",
    ]
    return any(tool in name_lower or tool in desc_lower for tool in security_tools)


def check_copilot(repo: Repository) -> bool:
    return bool(repo.topics and "copilot" in [t.lower() for t in repo.topics])


def check_dependabot(repo: Repository) -> bool:
    return bool(repo.topics and "dependabot" in [t.lower() for t in repo.topics])


def calculate_license_score(license_key: Optional[str]) -> int:
    if not license_key:
        return 0
    license_lower = license_key.lower()
    permissive = [
        "mit", "apache-2.0", "bsd", "bsd-2-clause", "bsd-3-clause",
        "isc", "unlicense", "0bsd", "psf-2.0", "wtfpl", "zlib",
    ]
    copyleft = [
        "gpl-2.0", "gpl-3.0", "agpl-3.0", "lgpl-2.1", "lgpl-3.0",
        "mpl-2.0", "epl-1.0", "cddl-1.0", "spl-1.0",
    ]
    if any(l in license_lower for l in permissive):
        return 100
    if any(l in license_lower for l in copyleft):
        return 50
    return 25


def health_status(
    last_commit_days: Optional[int] = None,
    release_days: Optional[int] = None,
    contributors_90d: Optional[int] = None,
    archived: bool = False,
) -> str:
    if archived:
        return "ARCHIVED"
    if last_commit_days is None:
        return "UNKNOWN"
    if last_commit_days <= 7:
        if release_days is not None and release_days <= 14 and (contributors_90d is not None and contributors_90d >= 3):
            return "ACTIVE"
        return "MAINTAINED"
    if last_commit_days <= 30:
        return "MAINTAINED"
    if last_commit_days <= 90:
        return "SLOW"
    if last_commit_days <= 180:
        return "STALE"
    return "STALE"


def get_refresh_interval(health_status: str) -> int:
    return {
        "ACTIVE": 1,
        "MAINTAINED": 3,
        "SLOW": 7,
        "STALE": 30,
        "ARCHIVED": 90,
        "UNKNOWN": 14,
    }.get(health_status, 14)