from typing import Optional

from src.github.client import GitHubClient
from src.models import Repository
from src.scoring.quality import (
    calculate_popularity_score, calculate_activity_score,
    calculate_maintenance_score, calculate_community_score,
)
from src.scoring.security import (
    calculate_security_score, calculate_license_score,
    check_security_policy, check_vulnerability_tool,
    check_copilot, check_dependabot, health_status,
)
from src.scoring.activity import ActivityTracker


class ScoringEngine:
    def __init__(self, client: Optional[GitHubClient] = None):
        self.activity_tracker = ActivityTracker(client)

    def score_repository(
        self,
        repo: Repository,
        weights: Optional[dict[str, float]] = None,
    ) -> dict[str, float]:
        weights = weights or {
            "popularity": 0.20, "activity": 0.20, "maintenance": 0.20,
            "community": 0.15, "documentation": 0.10,
            "license": 0.05, "security": 0.05, "awesome_quality": 0.05,
        }

        activity = self.activity_tracker.get_activity(repo)
        last_push_days = activity.get("last_push_days")
        commits_30d = activity.get("commits_30d", 0) or 0
        releases_90d = activity.get("releases_90d", 0) or 0

        popularity = calculate_popularity_score(repo)
        activity_score = calculate_activity_score(
            last_push_days or 999, commits_30d, releases_90d
        )
        maintenance = calculate_maintenance_score(
            has_readme=bool(repo.description),
            has_license=bool(repo.license),
            issue_response_days=None,
            last_commit_days=last_push_days or 999,
        )
        community = calculate_community_score(
            activity.get("contributors_90d", 0) or 0,
            repo.forks or 0,
            repo.issues or 0,
        )
        documentation = self._score_documentation(repo)
        license_score = calculate_license_score(repo.license)
        security = self._score_security(repo)
        awesome_quality = self._score_awesome_quality(repo)

        overall = (
            popularity * weights["popularity"]
            + activity_score * weights["activity"]
            + maintenance * weights["maintenance"]
            + community * weights["community"]
            + documentation * weights["documentation"]
            + license_score * weights["license"]
            + security * weights["security"]
            + awesome_quality * weights["awesome_quality"]
        )

        return {
            "overall": round(overall, 1),
            "popularity": round(popularity, 1),
            "activity": round(activity_score, 1),
            "maintenance": round(maintenance, 1),
            "community": round(community, 1),
            "documentation": round(documentation, 1),
            "license": round(license_score, 1),
            "security": round(security, 1),
            "awesome_quality": round(awesome_quality, 1),
        }

    def _score_documentation(self, repo: Repository) -> float:
        readme_quality = 50
        if repo.description and len(repo.description) > 20:
            readme_quality = 75
        return readme_quality

    def _score_security(self, repo: Repository) -> float:
        return calculate_security_score(
            has_security_policy=check_security_policy(repo),
            has_vulnerability_tool=check_vulnerability_tool(repo),
            has_copilot=check_copilot(repo),
            has_dependabot=check_dependabot(repo),
        )

    def _score_awesome_quality(self, repo: Repository) -> float:
        if not repo.awesome:
            return 50.0
        awesome = repo.awesome
        categories = awesome.get("categories", [])
        is_curated = awesome.get("is_awesome_list", False)
        score = 50.0
        if is_curated:
            score += 25
        if len(categories) >= 3:
            score += 25
        return min(score, 100)

    def classify_health(self, repo: Repository) -> dict:
        activity = self.activity_tracker.get_activity(repo)
        status = health_status(
            last_commit_days=activity.get("last_push_days"),
            release_days=activity.get("release_days"),
            contributors_90d=activity.get("contributors_90d"),
            archived=repo.archived,
        )
        return {
            "status": status,
            "last_commit_days": activity.get("last_push_days"),
            "release_days": activity.get("release_days"),
            "contributors_90d": activity.get("contributors_90d"),
        }