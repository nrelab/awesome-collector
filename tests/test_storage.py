import json
import os
import sqlite3
import tempfile
import pytest
from pathlib import Path

from src.models import Repository
from src.storage.json_store import JsonStore
from src.storage.sqlite import SqliteStore
from src.storage.markdown import MarkdownRenderer


class TestJsonStore:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.store = JsonStore(self.tmp)

    def test_save_and_load_repository(self):
        repo = Repository(
            id="github:test/repo", owner="test", name="repo",
            url="https://github.com/test/repo", stars=100,
        )
        self.store.save_repository(repo)
        loaded = self.store.load_repository("github:test/repo")
        assert loaded is not None
        assert loaded["id"] == "github:test/repo"
        assert loaded["stars"] == 100

    def test_load_missing(self):
        assert self.store.load_repository("github:nope/repo") is None

    def test_save_daily_snapshot(self):
        self.store.save_daily_snapshot("2026-09-15", {"total": 100})
        loaded = self.store.load_daily_snapshot("2026-09-15")
        assert loaded["total"] == 100

    def test_list_daily_snapshots(self):
        self.store.save_daily_snapshot("2026-09-14", {})
        self.store.save_daily_snapshot("2026-09-15", {})
        snaps = self.store.list_daily_snapshots()
        assert "2026-09-14" in snaps
        assert "2026-09-15" in snaps

    def test_save_load_awesome_list(self):
        self.store.save_awesome_list("test/repo", {"is_awesome_list": True})
        data = self.store.load_awesome_list("test/repo")
        assert data is not None
        assert data["is_awesome_list"] is True

    def test_get_all_repositories(self):
        for i in range(3):
            repo = Repository(
                id=f"github:test/repo{i}", owner="test", name=f"repo{i}",
                url=f"https://github.com/test/repo{i}",
            )
            self.store.save_repository(repo)
        all_repos = self.store.get_all_repositories()
        assert len(all_repos) == 3


class TestSqliteStore:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.store = SqliteStore(f"{self.tmp}/test.sqlite")

    def test_save_and_get_repository(self):
        repo = Repository(
            id="github:test/repo", owner="test", name="repo",
            url="https://github.com/test/repo", stars=100, language="Python",
        )
        self.store.save_repository(repo)
        result = self.store.get_repository("github:test/repo")
        assert result is not None
        assert result["owner"] == "test"

    def test_get_total_count(self):
        for i in range(5):
            repo = Repository(
                id=f"github:test/repo{i}", owner="test", name=f"repo{i}",
                url=f"https://github.com/test/repo{i}",
            )
            self.store.save_repository(repo)
        assert self.store.get_total_count() == 5

    def test_save_categories(self):
        self.store.save_categories("github:test/repo", ["AI", "Security"])
        result = self.store.get_by_category("AI")
        assert len(result) == 1
        assert result[0]["id"] == "github:test/repo"

    def test_save_sources(self):
        sources = [{"repository": "github:other/list", "section": "Tools"}]
        self.store.save_sources("github:test/repo", sources)
        repo = self.store.get_repository("github:test/repo")
        assert repo is not None

    def test_save_daily_metric(self):
        self.store.save_daily_metric("github:test/repo", "2026-09-15", 100, 10, 5)

    def test_get_by_health(self):
        repo = Repository(
            id="github:active/repo", owner="active", name="repo",
            url="https://github.com/active/repo", health={"status": "ACTIVE"},
        )
        self.store.save_repository(repo)
        results = self.store.get_by_health("ACTIVE")
        assert len(results) == 1

    def test_get_stale_repos(self):
        repo = Repository(
            id="github:stale/repo", owner="stale", name="repo",
            url="https://github.com/stale/repo", pushed_at="2025-01-01",
        )
        self.store.save_repository(repo)
        stale = self.store.get_stale_repos(max_days=60)
        assert any(r["id"] == "github:stale/repo" for r in stale)

    def test_vacuum(self):
        self.store.vacuum()

    def test_get_stats(self):
        self.store.save_repository(
            Repository(id="github:t/repo1", owner="t", name="repo1",
                       url="https://github.com/t/repo1", language="Python", stars=100)
        )
        self.store.save_repository(
            Repository(id="github:t/repo2", owner="t", name="repo2",
                       url="https://github.com/t/repo2", language="Rust", stars=200)
        )
        stats = self.store.get_stats()
        assert stats["total"] == 2
        assert "by_language" in stats


class TestMarkdownRenderer:
    def test_render_report(self):
        renderer = MarkdownRenderer()
        report = renderer.render_report("2026-09-15", {
            "total": 100, "new": 5
        }, [])
        assert "# Awesome Repository Report" in report
        assert "2026-09-15" in report

    def test_render_report_with_sections(self):
        renderer = MarkdownRenderer()
        sections = [{
            "title": "Security",
            "repositories": [{"name": "test/repo", "stars": 100, "category": "Security", "score": 90}],
        }]
        report = renderer.render_report("2026-09-15", {"total": 10}, sections)
        assert "Security" in report
        assert "test/repo" in report

    def test_render_daily_diff(self):
        renderer = MarkdownRenderer()
        changes = {"new": [], "trending": [], "updated": [], "stale": [], "archived": [], "removed": []}
        report = renderer.render_daily_diff(changes)
        assert "# Daily Change Report" in report

    def test_render_markdown_table(self):
        table = MarkdownRenderer.render_markdown_table(
            ["Name", "Stars"], [["repo1", "100"], ["repo2", "200"]]
        )
        assert "| Name | Stars |" in table
        assert "| repo1 | 100 |" in table


class TestStorageIntegration:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.store = SqliteStore(f"{self.tmp}/test.sqlite")

    def test_json_to_sqlite_roundtrip(self):
        repo = Repository(
            id="github:roundtrip/repo", owner="rt", name="repo",
            url="https://github.com/rt/repo", stars=42, language="Python",
            topics=["awesome-list"], description="Test repo",
        )
        self.store.save_repository(repo)
        result = self.store.get_repository("github:roundtrip/repo")
        assert result["stars"] == 42
        assert result["language"] == "Python"
        assert result["owner"] == "rt"