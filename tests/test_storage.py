import json
import os
import tempfile

from src.main import CLICommands
from src.models import Repository
from src.storage.json_store import JsonStore
from src.storage.markdown import MarkdownRenderer
from src.storage.sqlite import SqliteStore


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
        self.store.save_repository(
            Repository(id="github:test/repo", owner="test", name="repo",
                       url="https://github.com/test/repo")
        )
        self.store.save_categories("github:test/repo", ["AI", "Security"])
        result = self.store.get_by_category("AI")
        assert len(result) == 1
        assert result[0]["id"] == "github:test/repo"

    def test_save_categories_idempotent(self):
        self.store.save_repository(
            Repository(id="github:test/repo", owner="test", name="repo",
                       url="https://github.com/test/repo")
        )
        self.store.save_categories("github:test/repo", ["AI"])
        self.store.save_categories("github:test/repo", ["AI"])
        assert len(self.store.get_by_category("AI")) == 1

    def test_save_sources(self):
        self.store.save_repository(
            Repository(id="github:test/repo", owner="test", name="repo",
                       url="https://github.com/test/repo")
        )
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
            "category": "Security",
            "repositories": {
                "AppSec": [
                    {"name": "test/repo", "stars": 100, "category": "AppSec",
                     "parent": "Security", "score": 90},
                ],
            },
        }]
        report = renderer.render_report("2026-09-15", {"total": 10}, sections)
        assert "Security" in report
        assert "test/repo" in report

    def test_render_report_skips_legacy_flat_sections(self):
        renderer = MarkdownRenderer()
        sections = [{
            "title": "Security",
            "repositories": [{"name": "test/repo", "stars": 100, "score": 90}],
        }]
        report = renderer.render_report("2026-09-15", {"total": 10}, sections)
        assert "Security" not in report

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


class TestSqliteStoreLookups:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.store = SqliteStore(f"{self.tmp}/test.sqlite")
        self.store.save_repository(
            Repository(id="github:cat/repo", owner="cat", name="repo",
                       url="https://github.com/cat/repo", stars=10)
        )
        self.store.save_repository(
            Repository(id="github:nocat/repo", owner="nocat", name="repo",
                       url="https://github.com/nocat/repo", stars=5)
        )

    def test_get_all_categories(self):
        self.store.save_categories("github:cat/repo", ["AI", "Security"])
        result = self.store.get_all_categories()
        assert result == {"github:cat/repo": ["AI", "Security"]}
        assert self.store.get_all_categories().get("github:nocat/repo") is None

    def test_get_all_sources(self):
        self.store.save_sources("github:cat/repo", [
            {"repository": "github:other/list", "section": "Tools"}
        ])
        result = self.store.get_all_sources()
        assert result["github:cat/repo"] == [
            {"repository": "github:other/list", "section": "Tools"}
        ]

    def test_save_categories_does_not_leak_between_repos(self):
        self.store.save_categories("github:cat/repo", ["AI"])
        self.store.save_categories("github:nocat/repo", ["Security"])
        assert [r["id"] for r in self.store.get_by_category("AI")] == ["github:cat/repo"]
        assert [r["id"] for r in self.store.get_by_category("Security")] == ["github:nocat/repo"]


class TestCategoryHierarchy:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.store = SqliteStore(f"{self.tmp}/db/awesome.sqlite")
        self.store.save_repository(
            Repository(id="github:a/b", owner="a", name="b",
                       url="https://github.com/a/b")
        )

    def test_saves_leaf_with_parent(self):
        self.store.save_categories("github:a/b", ["LLM"], {"LLM": "AI"})
        parents = self.store.get_category_parents()
        assert parents["LLM"] == "AI"
        assert parents["AI"] is None

    def test_get_category_tree(self):
        self.store.save_categories(
            "github:a/b", ["LLM", "Agents", "Rust"], {"LLM": "AI", "Agents": "AI", "Rust": "Programming Languages"}
        )
        tree = self.store.get_category_tree()
        assert tree["AI"] == ["Agents", "LLM"]
        assert tree["Programming Languages"] == ["Rust"]

    def test_categories_without_parent_still_save(self):
        self.store.save_categories("github:a/b", ["AI"])
        assert self.store.get_category_parents()["AI"] is None
        assert len(self.store.get_by_category("AI")) == 1

    def test_parent_is_shared_across_repositories(self):
        self.store.save_repository(
            Repository(id="github:a/c", owner="a", name="c", url="https://github.com/a/c")
        )
        self.store.save_categories("github:a/b", ["LLM"], {"LLM": "AI"})
        self.store.save_categories("github:a/c", ["Agents"], {"Agents": "AI"})
        assert self.store.get_by_category("LLM")[0]["id"] == "github:a/b"
        assert self.store.get_by_category("Agents")[0]["id"] == "github:a/c"
        assert self.store.get_category_parents()["AI"] is None

    def test_upsert_does_not_orphan_an_existing_leaf(self):
        self.store.save_categories("github:a/b", ["LLM"], {"LLM": "AI"})
        self.store.save_categories("github:a/b", ["LLM"])
        assert self.store.get_category_parents()["LLM"] == "AI"

    def test_migration_adds_parent_id_to_legacy_database(self):
        legacy = os.path.join(self.tmp, "legacy.sqlite")
        import sqlite3

        conn = sqlite3.connect(legacy)
        conn.execute("CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)")
        conn.execute("INSERT INTO categories (name) VALUES ('LLM')")
        conn.commit()
        conn.close()

        migrated = SqliteStore(legacy)
        columns = {
            row[1]
            for row in migrated._get_connection().execute("PRAGMA table_info(categories)")
        }
        assert "parent_id" in columns
        assert migrated.get_category_parents() == {"LLM": None}


class TestDocRenderers:
    def setup_method(self):
        self.renderer = MarkdownRenderer()
        self.categories = {
            "AI": {
                "LLM": [
                    {"id": "github:a/b", "name": "a/b", "url": "https://github.com/a/b",
                     "description": "Thing", "score": 90.0, "stars": 100,
                     "category": "LLM", "parent": "AI"},
                    {"id": "github:a/c", "name": "a/c", "url": "https://github.com/a/c",
                     "description": "Other", "score": 50.0, "stars": 10,
                     "category": "LLM", "parent": "AI"},
                ],
            },
            "Security": {
                "AppSec": [
                    {"id": "github:a/b", "name": "a/b", "url": "https://github.com/a/b",
                     "description": "Thing", "score": 90.0, "stars": 100,
                     "category": "AppSec", "parent": "Security"},
                ],
            },
        }

    def test_render_sitemap(self):
        out = self.renderer.render_sitemap(self.categories, 2, "2026-09-15T00:00:00Z")
        assert "# Awesome Repository Sitemap" in out
        assert "Total repositories: 2" in out
        assert "## AI" in out and "## Security" in out
        assert "### LLM" in out and "### AppSec" in out

    def test_render_sitemap_orders_leaves(self):
        out = self.renderer.render_sitemap(self.categories, 2)
        assert out.index("### LLM") < out.index("### AppSec")

    def test_render_llms_txt(self):
        out = self.renderer.render_llms_txt(self.categories, 2, "2026-09-15T00:00:00Z")
        assert "# Awesome Collector" in out
        assert "- [a/b](https://github.com/a/b): Thing" in out

    def test_render_agents_md_dedupes_repos(self):
        out = self.renderer.render_agents_md(
            self.categories, {"total_stars": 110, "by_health": {"ACTIVE": 2}}, 2
        )
        assert "- Total repositories: 2" in out
        assert "- `AI` (2 repositories)" in out
        assert "  - `LLM` (2 repositories)" in out
        assert "- `Security` (1 repository)" in out
        assert out.count("| [a/b](https://github.com/a/b) |") == 1

    def test_render_agents_md_counts_unique_when_total_missing(self):
        out = self.renderer.render_agents_md(self.categories)
        assert "- Total repositories: 2" in out

    def test_render_category_index(self):
        out = self.renderer.render_category_index(
            {"AI": {"LLM": ["github:a/b"]}}
        )
        assert "## AI" in out
        assert "- github:a/b" in out


class TestGenerate:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.commands = CLICommands(data_dir=f"{self.tmp}/data")
        self.docs_dir = f"{self.tmp}/docs"
        store = self.commands.sqlite_store
        for repo_id, score, stars in [
            ("github:high/repo", 90.0, 500),
            ("github:low/repo", 10.0, 1),
        ]:
            owner, name = repo_id[len("github:"):].split("/")
            store.save_repository(
                Repository(id=repo_id, owner=owner, name=name,
                           url=f"https://github.com/{owner}/{name}",
                           stars=stars, language="Python",
                           description="desc", score={"overall": score},
                           health={"status": "ACTIVE"})
            )
        store.save_categories("github:high/repo", ["LLM"], {"LLM": "AI"})

    def test_generate_writes_artifacts(self):
        result = self.commands.generate(docs_dir=self.docs_dir)
        assert result["repositories"] == 2
        for name in ["sitemap.md", "llms.txt", "agents.md"]:
            assert os.path.exists(f"{self.docs_dir}/{name}")
        assert os.path.exists(f"{self.tmp}/data/index.json")

    def test_generate_writes_index(self):
        self.commands.generate(docs_dir=self.docs_dir)
        with open(f"{self.tmp}/data/index.json") as f:
            index = json.load(f)
        assert index["total"] == 2
        assert "AI" in index["categories"]
        assert "Uncategorized" in index["categories"]
        assert index["category_tree"]["AI"]["LLM"] == ["github:high/repo"]

    def test_generate_nests_leaves_under_parent(self):
        self.commands.generate(docs_dir=self.docs_dir)
        with open(f"{self.docs_dir}/sitemap.md") as f:
            content = f.read()
        assert "## AI" in content
        assert "### LLM" in content
        assert content.index("## AI") < content.index("### LLM")

    def test_generate_writes_daily_snapshot(self):
        result = self.commands.generate(docs_dir=self.docs_dir)
        date_str = os.path.basename(result["files"][-1]).replace(".json", "")
        snapshot = self.commands.json_store.load_daily_snapshot(date_str)
        assert snapshot["summary"]["total"] == 2
        assert len(snapshot["sections"]) == 2
        assert snapshot["summary"]["categories"] == 2

    def test_generate_sorts_by_score_descending(self):
        self.commands.generate(docs_dir=self.docs_dir)
        with open(f"{self.docs_dir}/sitemap.md") as f:
            content = f.read()
        assert content.index("high/repo") < content.index("low/repo")


class TestGenerateEmptyDataset:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.commands = CLICommands(data_dir=f"{self.tmp}/data")
        self.docs_dir = f"{self.tmp}/docs"

    def test_generate_on_empty_dataset_writes_docs(self):
        result = self.commands.generate(docs_dir=self.docs_dir)
        assert result["repositories"] == 0
        assert result["files"]

    def test_generate_does_not_clobber_existing_docs_when_empty(self):
        self.commands.generate(docs_dir=self.docs_dir)
        with open(f"{self.docs_dir}/sitemap.md") as f:
            before = f.read()

        empty = CLICommands(data_dir=f"{self.tmp}/empty-data")
        result = empty.generate(docs_dir=self.docs_dir)

        assert result["skipped"] is True
        assert result["files"] == []
        with open(f"{self.docs_dir}/sitemap.md") as f:
            assert f.read() == before


class TestValidateAndTrending:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.commands = CLICommands(data_dir=f"{self.tmp}/data")
        store = self.commands.sqlite_store
        for repo_id, score, health, stars in [
            ("github:a/high", 90.0, "ACTIVE", 500),
            ("github:a/low", 10.0, "STALE", 5),
        ]:
            owner, name = repo_id[len("github:"):].split("/")
            store.save_repository(
                Repository(id=repo_id, owner=owner, name=name,
                           url=f"https://github.com/{owner}/{name}",
                           stars=stars, language="Python",
                           description="desc", collected_at="2026-10-09T00:00:00Z",
                           score={"overall": score}, health={"status": health})
            )

    def test_validate_falls_back_to_sqlite(self):
        result = self.commands.validate()
        assert result["total"] == 2
        assert result["errors"] == 0

    def test_validate_reports_missing_fields(self):
        self.commands.sqlite_store.save_repository(
            Repository(id="github:a/bad", owner="a", name="bad",
                       url="https://github.com/a/bad")
        )
        result = self.commands.validate()
        assert result["errors"] == 1
        assert "collected_at" in result["error_details"][0]

    def test_trending_filters_and_sorts_by_score(self):
        result = self.commands.trending()
        assert result["total"] == 1
        assert result["trending"][0]["id"] == "github:a/high"
        assert result["trending"][0]["score"] == {"overall": 90.0}
        assert result["trending"][0]["health"] == {"status": "ACTIVE"}

    def test_score_persists_to_json_store(self):
        self.commands.score()
        stored = self.commands.json_store.load_repository("github:a/high")
        assert stored is not None
        assert stored["score"]["overall"] is not None
        assert stored["health"]["status"] is not None
