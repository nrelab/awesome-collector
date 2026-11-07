"""Health-based incremental refresh scheduling.

Repositories are only re-fetched from the GitHub API when the time elapsed
since their last check exceeds the interval configured for their current
health status (see ``config/sources.yml`` → ``incremental.refresh_policy``
and ``docs/schema.md`` → "Refresh Policy").

Fallback rules (documented in docs/pipeline.md):

- Repositories with no recorded health status are treated as ``UNKNOWN``
  and use the ``UNKNOWN`` interval (14 days by default).
- Repositories with no ``collected_at`` timestamp have never been checked
  and are always due for refresh.
- ``collected_at`` is used as the last-checked timestamp: it is refreshed
  to the current time whenever a repository's metadata is successfully
  updated.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from src.models import Repository

DEFAULT_REFRESH_POLICY: dict[str, int] = {
    "ACTIVE": 1,
    "MAINTAINED": 3,
    "SLOW": 7,
    "STALE": 30,
    "ARCHIVED": 90,
    "UNKNOWN": 14,
}


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def health_status_of(repo: Repository) -> str:
    if repo.health and repo.health.get("status"):
        return repo.health["status"]
    return "UNKNOWN"


def refresh_interval_days(status: str, policy: dict[str, int] | None = None) -> int:
    intervals = policy or DEFAULT_REFRESH_POLICY
    return intervals.get(status) or intervals.get("UNKNOWN", 14)


def is_due(repo: Repository, now: datetime, policy: dict[str, int] | None = None) -> bool:
    """Return True when ``repo`` is due for a metadata refresh at ``now``."""
    last_checked = parse_timestamp(repo.collected_at)
    if last_checked is None:
        return True
    interval = refresh_interval_days(health_status_of(repo), policy)
    return (now - last_checked).days >= interval


@dataclass
class RefreshSelection:
    due: list[Repository]
    skipped: list[Repository]


def select_due_repositories(
    repos: list[Repository],
    now: datetime | None = None,
    policy: dict[str, int] | None = None,
) -> RefreshSelection:
    now = now or datetime.now(UTC)
    due: list[Repository] = []
    skipped: list[Repository] = []
    for repo in repos:
        (due if is_due(repo, now, policy) else skipped).append(repo)
    return RefreshSelection(due=due, skipped=skipped)
