"""Tests for health-based incremental refresh scheduling and execution."""

import tempfile
from datetime import UTC, datetime, timedelta

from src.main import CLICommands
from src.models import Repository
from src.refresh import (
    is_due,
    refresh_interval_days,
    select_due_repositories,
)

NOW = datetime(2026, 11, 1, tzinfo=UTC)


def _repo(repo_id, health="ACTIVE", collected_at=None, pushed_at=None):
    return Repository(
        id=repo_id, owner="o", name=repo_id.split("/")[-1],
        url=f"https://github.com/{repo_id}",
        collected_at=collected_at or (NOW - timedelta(days=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        pushed_at=pushed_at,
        health={"status": health} if health else None,
    )


def _days_ago(n):
    return (NOW - timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


class TestRefreshPolicy:
    def test_interval_boundaries(self):
        # ACTIVE interval = 1 day
        assert refresh_interval_days("ACTIVE") == 1
        assert is_due(_repo("github:o/r", "ACTIVE", _days_ago(1)), NOW)
        assert not is_due(_repo("github:o/r", "ACTIVE", _days_ago(0)), NOW)

        # STALE interval = 30 days
        assert refresh_interval_days("STALE") == 30
        assert is_due(_repo("github:o/r", "STALE", _days_ago(30)), NOW)
        assert not is_due(_repo("github:o/r", "STALE", _days_ago(29)), NOW)

        # ARCHIVED interval = 90 days
        assert is_due(_repo("github:o/r", "ARCHIVED", _days_ago(90)), NOW)
        assert not is_due(_repo("github:o/r", "ARCHIVED", _days_ago(89)), NOW)

    def test_unknown_health_uses_default_interval(self):
        assert refresh_interval_days("UNKNOWN") == 14
        assert refresh_interval_days("NONSENSE") == 14
        assert is_due(_repo("github:o/r", "UNKNOWN", _days_ago(14)), NOW)
        assert not is_due(_repo("github:o/r", "UNKNOWN", _days_ago(13)), NOW)

    def test_missing_collected_at_always_due(self):
        repo = Repository(id="github:o/r", owner="o", name="r",
                          url="https://github.com/o/r", collected_at=None,
                          health={"status": "ACTIVE"})
        assert is_due(repo, NOW)

    def test_custom_policy(self):
        policy = {"ACTIVE": 5, "UNKNOWN": 2}
        assert refresh_interval_days("ACTIVE", policy) == 5
        assert refresh_interval_days("STALE", policy) == 2  # falls back to UNKNOWN

    def test_select_partitions_due_and_skipped(self):
        repos = [
            _repo("github:o/due", "ACTIVE", _days_ago(5)),
            _repo("github:o/fresh", "ACTIVE", _days_ago(0)),
            _repo("github:o/never", "MAINTAINED", None),
        ]
        selection = select_due_repositories(repos, now=NOW)
        assert {r.id for r in selection.due} == {"github:o/due", "github:o/never"}
        assert [r.id for r in selection.skipped] == ["github:o/fresh"]


class FakeGitHubClient:
    def __init__(self, fail_for=()):
        self.fail_for = set(fail_for)
        self.calls = []

    def get_repository(self, owner, name):
        self.calls.append(f"{owner}/{name}")
        if f"{owner}/{name}" in self.fail_for:
            raise RuntimeError("api error")
        return {
            "name": name,
            "owner": {"login": owner},
            "html_url": f"https://github.com/{owner}/{name}",
            "description": "desc",
            "stargazers_count": 42,
            "forks_count": 3,
            "language": "Python",
            "topics": [],
            "archived": False,
            "pushed_at": "2026-10-30T00:00:00Z",
            "created_at": "2020-01-01T00:00:00Z",
            "updated_at": "2026-10-30T00:00:00Z",
        }

    def close(self):
        pass


class TestRefreshCommand:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.commands = CLICommands(config_dir="config", data_dir=self.tmp)
        old = (datetime.now(UTC) - timedelta(days=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        for repo_id, health in [
            ("github:o/due", "ACTIVE"),
            ("github:o/fail", "ACTIVE"),
            ("github:o/fresh", "ACTIVE"),
        ]:
            owner, name = repo_id[len("github:"):].split("/")
            collected = old if name != "fresh" else datetime.now(
                UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.commands.sqlite_store.save_repository(Repository(
                id=repo_id, owner=owner, name=name,
                url=f"https://github.com/{owner}/{name}",
                collected_at=collected,
                health={"status": health},
            ))

    def test_refresh_counts_and_updates(self, monkeypatch):
        fake = FakeGitHubClient(fail_for={"o/fail"})
        monkeypatch.setattr("src.main._get_github_client", lambda token: fake)
        result = self.commands.refresh(github_token="x")
        assert result["checked"] == 2      # due + fail; fresh is skipped
        assert result["updated"] == 1
        assert result["failed"] == 1
        assert result["skipped"] == 1
        # metadata actually updated
        row = self.commands.sqlite_store.get_repository("github:o/due")
        assert row["stars"] == 42
        assert row["health_status"] in ("ACTIVE", "MAINTAINED", "SLOW")

    def test_refresh_dry_run_does_not_save(self, monkeypatch):
        fake = FakeGitHubClient()
        monkeypatch.setattr("src.main._get_github_client", lambda token: fake)
        before = self.commands.sqlite_store.get_repository("github:o/due")
        result = self.commands.refresh(github_token="x", dry_run=True)
        assert result["updated"] == 2
        after = self.commands.sqlite_store.get_repository("github:o/due")
        assert after["stars"] == before["stars"]

    def test_refresh_without_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        result = self.commands.refresh(github_token=None)
        assert result["checked"] == 0
        assert "error" in result
