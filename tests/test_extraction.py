"""Tests for repository content extraction (README/docs/API references)."""

import base64
import tempfile

from src.extraction.content import ContentExtractor, ExtractionConfig
from src.main import CLICommands
from src.models import Repository


def _b64(text):
    return base64.b64encode(text.encode()).decode()


class FakeGitHubClient:
    """Minimal fake implementing get(), get_readme(), close()."""

    def __init__(self, readme=None, listings=None, files=None):
        self._readme = readme
        self._listings = listings or {}
        self._files = files or {}
        self.calls = []

    def get_readme(self, owner, name):
        return self._readme

    def get(self, path, **kwargs):
        self.calls.append(path)
        # file contents first, then directory listings
        for prefix, payload in self._files.items():
            if path.endswith(prefix):
                return payload
        for prefix, listing in self._listings.items():
            if path.endswith(prefix):
                return listing
        return []

    def close(self):
        pass


class TestExtractionConfig:
    def test_select_respects_min_score_and_cap(self):
        rows = [
            {"id": "github:o/a", "score_overall": 90},
            {"id": "github:o/b", "score_overall": 50},
            {"id": "github:o/c", "score_overall": 10},
        ]
        cfg = ExtractionConfig(min_score=40, max_repositories=1)
        extractor = ContentExtractor(client=None, config=cfg)
        selected = extractor.select_repositories(rows)
        assert [r["id"] for r in selected] == ["github:o/a"]

    def test_select_sorted_by_score_desc(self):
        rows = [
            {"id": "github:o/a", "score_overall": 10},
            {"id": "github:o/b", "score_overall": 90},
        ]
        extractor = ContentExtractor(client=None)
        selected = extractor.select_repositories(rows)
        assert selected[0]["id"] == "github:o/b"


class TestContentExtractor:
    def _row(self, repo_id="github:o/tool", score=80):
        return {"id": repo_id, "score_overall": score}

    def test_extracts_readme(self):
        client = FakeGitHubClient(readme={
            "name": "README.md",
            "content": _b64("# Tool\n\nDoes things."),
            "html_url": "https://github.com/o/tool#readme",
        })
        extractor = ContentExtractor(client, ExtractionConfig(include_docs=False, include_api_specs=False))
        payload = extractor.extract(self._row())
        assert payload["document_count"] == 1
        doc = payload["documents"][0]
        assert doc["kind"] == "readme"
        assert doc["content"].startswith("# Tool")
        assert doc["url"]
        assert payload["repository_id"] == "github:o/tool"

    def test_extracts_docs_and_api_specs(self):
        listing = [
            {"type": "file", "name": "guide.md", "path": "docs/guide.md",
             "html_url": "https://github.com/o/tool/blob/main/docs/guide.md"},
            {"type": "file", "name": "openapi.json", "path": "docs/openapi.json",
             "html_url": "https://github.com/o/tool/blob/main/docs/openapi.json"},
            {"type": "dir", "name": "subdir", "path": "docs/subdir"},
        ]
        files = {
            "docs/guide.md": {"content": _b64("# Guide")},
            "docs/openapi.json": {"content": _b64('{"openapi":"3.0.0"}')},
        }
        client = FakeGitHubClient(
            readme=None,
            listings={"/contents/docs": listing},
            files=files,
        )
        extractor = ContentExtractor(client)
        payload = extractor.extract(self._row())
        kinds = {d["kind"] for d in payload["documents"]}
        assert "docs" in kinds and "api" in kinds
        paths = {d["path"] for d in payload["documents"]}
        assert "docs/guide.md" in paths
        assert "docs/openapi.json" in paths

    def test_respects_max_files_per_repo(self):
        listing = [
            {"type": "file", "name": f"doc{i}.md", "path": f"docs/doc{i}.md"}
            for i in range(20)
        ]
        files = {f"docs/doc{i}.md": {"content": _b64(f"doc {i}")}
                 for i in range(20)}
        client = FakeGitHubClient(listings={"/contents/docs": listing}, files=files)
        cfg = ExtractionConfig(max_files_per_repo=3, include_readme=False)
        extractor = ContentExtractor(client, cfg)
        payload = extractor.extract(self._row())
        assert payload["document_count"] <= 3

    def test_truncates_oversized_files(self):
        big = "x" * 300_000
        client = FakeGitHubClient(readme={
            "name": "README.md", "content": _b64(big),
        })
        cfg = ExtractionConfig(max_bytes_per_file=1000,
                               include_docs=False, include_api_specs=False)
        extractor = ContentExtractor(client, cfg)
        payload = extractor.extract(self._row())
        doc = payload["documents"][0]
        assert doc["truncated"] is True
        assert doc["bytes"] <= 1000

    def test_run_reports_failures_without_aborting(self):
        client = FakeGitHubClient(readme={
            "name": "README.md", "content": _b64("hi"),
        })
        rows = [
            self._row("github:o/good"),
            self._row("github:o/bad"),
            {"id": "not-a-github-id", "score_overall": 90},
        ]
        extractor = ContentExtractor(client, ExtractionConfig(
            include_docs=False, include_api_specs=False))
        report, payloads = extractor.run(rows)
        assert report.failed == 1
        assert report.succeeded == 2
        assert report.failures[0]["id"] == "not-a-github-id"
        assert len(payloads) == 2

    def test_empty_extraction_counts_as_skipped(self):
        client = FakeGitHubClient(readme=None, listings={}, files={})
        extractor = ContentExtractor(client)
        report, payloads = extractor.run([self._row()])
        assert report.skipped == 1
        assert report.succeeded == 0


class TestExtractCommand:
    def test_extract_content_persists_payloads(self, monkeypatch):
        tmp = tempfile.mkdtemp()
        commands = CLICommands(config_dir="config", data_dir=tmp)
        commands.sqlite_store.save_repository(Repository(
            id="github:o/tool", owner="o", name="tool",
            url="https://github.com/o/tool", score={"overall": 90.0},
        ))
        fake_client = FakeGitHubClient(readme={
            "name": "README.md", "content": _b64("# Tool"),
        })
        monkeypatch.setattr("src.main._get_github_client", lambda token: fake_client)
        result = commands.extract_content(github_token="x", min_score=50)
        assert result["succeeded"] == 1
        stored = commands.json_store.load_content("github:o/tool")
        assert stored is not None
        assert stored["documents"][0]["kind"] == "readme"

    def test_extract_dry_run_does_not_persist(self, monkeypatch):
        tmp = tempfile.mkdtemp()
        commands = CLICommands(config_dir="config", data_dir=tmp)
        commands.sqlite_store.save_repository(Repository(
            id="github:o/tool", owner="o", name="tool",
            url="https://github.com/o/tool", score={"overall": 90.0},
        ))
        fake_client = FakeGitHubClient(readme={
            "name": "README.md", "content": _b64("# Tool"),
        })
        monkeypatch.setattr("src.main._get_github_client", lambda token: fake_client)
        result = commands.extract_content(github_token="x", dry_run=True)
        assert result["succeeded"] == 1
        assert commands.json_store.load_content("github:o/tool") is None
