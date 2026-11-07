"""Dedicated tests for scoring modules."""

from src.models import Repository
from src.scoring import ScoringEngine
from src.scoring.activity import ActivityTracker
from src.scoring.quality import (
    calculate_activity_score,
    calculate_community_score,
    calculate_maintenance_score,
    calculate_popularity_score,
)
from src.scoring.security import (
    calculate_license_score,
    calculate_security_score,
    check_copilot,
    check_dependabot,
    check_security_policy,
    check_vulnerability_tool,
    get_refresh_interval,
    health_status,
)


def _repo(**kw):
    base = {"id": "github:o/r", "owner": "o", "name": "r",
            "url": "https://github.com/o/r"}
    base.update(kw)
    return Repository(**base)


class TestPopularityScore:
    def test_scales_with_stars(self):
        low = calculate_popularity_score(_repo(stars=100, forks=10))
        high = calculate_popularity_score(_repo(stars=100000, forks=10000))
        assert high > low
        assert 0 <= low <= 100

    def test_zero_stars_is_zero(self):
        assert calculate_popularity_score(_repo(stars=0, forks=0)) == 0.0


class TestActivityScore:
    def test_recent_push_scores_high(self):
        assert calculate_activity_score(2, 15, 3) > 70

    def test_stale_activity_scores_low(self):
        assert calculate_activity_score(300, 0, 0) < 40

    def test_no_activity_is_zero(self):
        assert calculate_activity_score(0, 0, 0) == 0.0


class TestMaintenanceScore:
    def test_all_signals_present(self):
        assert calculate_maintenance_score(True, True, 2, 3) == 100.0

    def test_missing_signals_and_slow_commits(self):
        score = calculate_maintenance_score(False, False, 90, 200)
        assert score < 40


class TestCommunityScore:
    def test_bounds(self):
        assert 0 <= calculate_community_score(0, 0, 0) <= 100
        assert calculate_community_score(50, 5000, 5) > \
            calculate_community_score(0, 0, 500)


class TestSecurityChecks:
    def test_security_policy_via_topic(self):
        assert check_security_policy(_repo(topics=["security"]))
        assert not check_security_policy(_repo(topics=["web"]))

    def test_vulnerability_tool_by_name(self):
        assert check_vulnerability_tool(_repo(name="trivy"))
        assert check_vulnerability_tool(_repo(name="x", description="a semgrep wrapper"))
        assert not check_vulnerability_tool(_repo(name="x", description="nothing"))

    def test_copilot_and_dependabot_topics(self):
        repo = _repo(topics=["copilot", "dependabot"])
        assert check_copilot(repo)
        assert check_dependabot(repo)

    def test_security_score_bounds(self):
        assert calculate_security_score() == 0.0
        assert calculate_security_score(True, True, True, True) == 100.0

    def test_license_scores(self):
        assert calculate_license_score("MIT") == 100
        assert calculate_license_score("GPL-3.0") == 50
        assert calculate_license_score(None) == 0
        assert calculate_license_score("Custom") == 25


class TestHealthStatus:
    def test_all_statuses(self):
        assert health_status(archived=True) == "ARCHIVED"
        assert health_status(last_commit_days=None) == "UNKNOWN"
        assert health_status(last_commit_days=3) == "MAINTAINED"
        assert health_status(last_commit_days=60) == "SLOW"
        assert health_status(last_commit_days=120) == "STALE"

    def test_active_requires_release_and_contributors(self):
        assert health_status(last_commit_days=3, release_days=10,
                             contributors_90d=5) == "ACTIVE"
        assert health_status(last_commit_days=3, release_days=None,
                             contributors_90d=None) == "MAINTAINED"

    def test_refresh_intervals(self):
        assert get_refresh_interval("ACTIVE") == 1
        assert get_refresh_interval("ARCHIVED") == 90
        assert get_refresh_interval("UNKNOWN") == 14
        assert get_refresh_interval("bogus") == 14


class FakeClient:
    def get_commits(self, owner, name, since=None, per_page=100):
        return [{"commit": {"committer": {"date": "2026-10-30T00:00:00Z"}}}] * 5

    def get_releases(self, owner, name, per_page=100):
        return [{"published_at": "2026-10-20T00:00:00Z"}]

    def get_contributors(self, owner, name, per_page=100):
        return [{}] * 4

    def close(self):
        pass


class TestActivityTracker:
    def test_estimates_without_client(self):
        tracker = ActivityTracker(client=None)
        activity = tracker.get_activity(_repo(pushed_at="2026-10-30T00:00:00Z"))
        assert activity["last_push_days"] is not None
        assert activity["commits_30d"] is None

    def test_fetches_with_client(self):
        tracker = ActivityTracker(client=FakeClient())
        activity = tracker.get_activity(_repo())
        assert activity["commits_30d"] == 5
        assert activity["contributors_90d"] == 4

    def test_client_failure_falls_back(self):
        class BadClient(FakeClient):
            def get_commits(self, *a, **k):
                raise RuntimeError("api down")
        tracker = ActivityTracker(client=BadClient())
        activity = tracker.get_activity(_repo(pushed_at="2026-10-30T00:00:00Z"))
        assert activity["commits_30d"] is None

    def test_push_health_buckets(self):
        tracker = ActivityTracker(client=None)
        stale = tracker.get_push_health(
            _repo(pushed_at="2020-01-01T00:00:00Z"))
        assert stale["status"] == "STALE"
        assert tracker.get_push_health(_repo(pushed_at=None))["status"] == "UNKNOWN"


class TestScoringEngine:
    def test_score_repository_returns_all_components(self):
        engine = ScoringEngine(client=FakeClient())
        repo = _repo(stars=10000, forks=500, license="MIT",
                     topics=["llm"], description="A sufficiently long description",
                     pushed_at="2026-10-30T00:00:00Z")
        score = engine.score_repository(repo)
        for key in ("overall", "popularity", "activity", "maintenance",
                    "community", "documentation", "license", "security",
                    "awesome_quality"):
            assert key in score
        assert 0 <= score["overall"] <= 100

    def test_classify_health_archived(self):
        engine = ScoringEngine(client=None)
        health = engine.classify_health(_repo(archived=True))
        assert health["status"] == "ARCHIVED"

    def test_awesome_quality_bonus(self):
        engine = ScoringEngine(client=None)
        plain = engine.score_repository(_repo())
        curated = engine.score_repository(_repo(
            awesome={"is_awesome_list": True, "categories": ["a", "b", "c"]}))
        assert curated["awesome_quality"] > plain["awesome_quality"]
