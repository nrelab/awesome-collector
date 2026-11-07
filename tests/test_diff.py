"""Tests for snapshot diff change detection (issue: diff reported every
shared repo as 'updated' and never populated stale/archived)."""


from src.main import CLICommands


def _repo(repo_id, **overrides):
    base = {
        "id": repo_id,
        "owner": repo_id.split(":", 1)[1].split("/")[0],
        "name": repo_id.split("/")[-1],
        "url": f"https://github.com/{repo_id.split(':', 1)[1]}",
        "stars": 100,
        "forks": 10,
        "language": "Python",
        "archived": False,
        "pushed_at": "2026-10-01T00:00:00Z",
        "health_status": "ACTIVE",
        "score_overall": 50.0,
    }
    base.update(overrides)
    return base


class TestDiff:
    def setup_method(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.commands = CLICommands(config_dir="config", data_dir=self.tmp)
        self.store = self.commands.json_store

    def _snapshot(self, date, repos):
        self.store.save_daily_snapshot(date, {
            "date": date,
            "repositories": repos,
        })

    def test_unchanged_repo_not_in_updated(self):
        repo = _repo("github:a/b")
        self._snapshot("2026-01-01", [repo])
        self._snapshot("2026-01-02", [dict(repo)])
        result = self.commands.diff("2026-01-01", "2026-01-02")
        assert result["updated"] == []
        assert result["updated_count"] == 0

    def test_changed_repo_reports_changed_fields(self):
        old = _repo("github:a/b", stars=100)
        new = _repo("github:a/b", stars=150, language="Go")
        self._snapshot("2026-01-01", [old])
        self._snapshot("2026-01-02", [new])
        result = self.commands.diff("2026-01-01", "2026-01-02")
        assert result["updated_count"] == 1
        changes = result["updated"][0]["changes"]
        assert changes["stars"] == {"from": 100, "to": 150}
        assert changes["language"] == {"from": "Python", "to": "Go"}
        assert "forks" not in changes
        assert result["compared_fields"]

    def test_new_and_removed_repos(self):
        self._snapshot("2026-01-01", [_repo("github:a/old")])
        self._snapshot("2026-01-02", [_repo("github:a/new")])
        result = self.commands.diff("2026-01-01", "2026-01-02")
        assert [r["id"] for r in result["new"]] == ["github:a/new"]
        assert [r["id"] for r in result["removed"]] == ["github:a/old"]

    def test_stale_populated_from_health_status(self):
        self._snapshot("2026-01-01", [])
        self._snapshot("2026-01-02", [
            _repo("github:a/stale", health_status="STALE"),
            _repo("github:a/active", health_status="ACTIVE"),
        ])
        result = self.commands.diff("2026-01-01", "2026-01-02")
        assert [r["id"] for r in result["stale"]] == ["github:a/stale"]

    def test_stale_populated_from_old_pushed_at(self):
        self._snapshot("2026-01-01", [])
        self._snapshot("2026-01-02", [
            _repo("github:a/stale", health_status="UNKNOWN",
                  pushed_at="2020-01-01T00:00:00Z"),
        ])
        result = self.commands.diff("2026-01-01", "2026-01-02")
        assert [r["id"] for r in result["stale"]] == ["github:a/stale"]

    def test_archived_populated(self):
        self._snapshot("2026-01-01", [])
        self._snapshot("2026-01-02", [
            _repo("github:a/archived", archived=True),
            _repo("github:a/archived2", health_status="ARCHIVED"),
            _repo("github:a/live", archived=False),
        ])
        result = self.commands.diff("2026-01-01", "2026-01-02")
        ids = {r["id"] for r in result["archived"]}
        assert ids == {"github:a/archived", "github:a/archived2"}

    def test_nested_health_and_score_shapes(self):
        old = _repo("github:a/b", health={"status": "ACTIVE"},
                    score={"overall": 40.0})
        old.pop("health_status"); old.pop("score_overall")
        new = dict(old, health={"status": "MAINTAINED"},
                   score={"overall": 55.0})
        self._snapshot("2026-01-01", [old])
        self._snapshot("2026-01-02", [new])
        result = self.commands.diff("2026-01-01", "2026-01-02")
        changes = result["updated"][0]["changes"]
        assert changes["health_status"] == {"from": "ACTIVE", "to": "MAINTAINED"}
        assert changes["score_overall"] == {"from": 40.0, "to": 55.0}

    def test_missing_snapshot(self):
        result = self.commands.diff("2026-01-01", "2026-01-02")
        assert "error" in result

    def test_trending_still_works(self):
        self._snapshot("2026-01-01", [_repo("github:a/b", stars=100)])
        self._snapshot("2026-01-02", [_repo("github:a/b", stars=700)])
        result = self.commands.diff("2026-01-01", "2026-01-02")
        assert result["trending_count"] == 1
        assert result["trending"][0]["star_gain"] == 600
