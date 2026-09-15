import time
from typing import Optional

from src.models import Repository
from src.github.client import GitHubClient


class ActivityTracker:
    def __init__(self, client: Optional[GitHubClient] = None):
        self.client = client

    def get_activity(self, repo: Repository) -> dict:
        if self.client is None:
            return self._estimate_activity(repo)

        try:
            owner, name = repo.id[len("github:"):].split("/", 1)
            commits = self.client.get_commits(owner, name, since=self._thirty_days_ago())
            releases = self.client.get_releases(owner, name, per_page=10)
            contributors = self.client.get_contributors(owner, name, per_page=1)

            last_push = None
            if commits:
                last_push = commits[0].get("commit", {}).get("committer", {}).get("date")

            return {
                "last_commit": last_push,
                "commits_30d": len(commits),
                "releases_90d": len(releases),
                "contributors_90d": len(contributors),
                "last_push_days": self._days_since(last_push) if last_push else None,
                "release_days": self._days_since(releases[0].get("published_at")) if releases else None,
            }
        except Exception:
            return self._estimate_activity(repo)

    def get_push_health(self, repo: Repository) -> dict:
        pushed_at = repo.pushed_at
        if pushed_at:
            days = self._days_since(pushed_at)
            if days <= 7:
                status = "ACTIVE"
            elif days <= 30:
                status = "MAINTAINED"
            elif days <= 90:
                status = "SLOW"
            else:
                status = "STALE"
            return {"status": status, "last_push_days": days, "last_push": pushed_at}
        return {"status": "UNKNOWN", "last_push_days": None, "last_push": None}

    def _estimate_activity(self, repo: Repository) -> dict:
        last_push = repo.pushed_at
        return {
            "last_commit": last_push,
            "commits_30d": None,
            "releases_90d": None,
            "contributors_90d": None,
            "last_push_days": self._days_since(last_push) if last_push else None,
            "release_days": None,
        }

    @staticmethod
    def _days_since(date_str: Optional[str]) -> Optional[int]:
        if not date_str:
            return None
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - dt).days
        except Exception:
            return None

    @staticmethod
    def _thirty_days_ago() -> str:
        from datetime import datetime, timezone, timedelta
        return (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()