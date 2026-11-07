"""Dedicated tests for normalization and deduplication modules."""

import pytest

from src.models import Repository
from src.normalize.dedupe import DuplicateMatch, dedupe_repositories
from src.normalize.repository import (
    create_repository_from_api,
    create_repository_from_url,
    merge_sources,
    normalize_repository,
)
from src.normalize.urls import (
    extract_owner_name_from_id,
    is_github_url,
    normalize_github_url,
    normalize_repository_url,
    normalize_url,
    repository_from_row,
    repository_id,
    repository_id_from_url,
    to_canonical_url,
)


def _repo(repo_id="github:o/r", **kw):
    owner, name = repo_id[len("github:"):].split("/")
    base = {"id": repo_id, "owner": owner, "name": name,
            "url": f"https://github.com/{owner}/{name}"}
    base.update(kw)
    return Repository(**base)


class TestURLNormalization:
    @pytest.mark.parametrize("url,expected", [
        ("https://github.com/Foo/Bar", "github:foo/bar"),
        ("https://github.com/foo/bar/", "github:foo/bar"),
        ("https://github.com/foo/bar.git", "github:foo/bar"),
        ("git@github.com:foo/bar.git", "github:foo/bar"),
        ("git://github.com/foo/bar.git", "github:foo/bar"),
        ("git@ssh.github.com:/foo/bar", "github:foo/bar"),
    ])
    def test_normalize_url(self, url, expected):
        assert normalize_url(url) == expected

    def test_non_github_url_passthrough(self):
        assert normalize_url("https://gitlab.com/a/b") == "https://gitlab.com/a/b"

    def test_repository_id_from_url_variants(self):
        assert repository_id_from_url("https://github.com/a/b") == "github:a/b"
        assert repository_id_from_url("git@github.com:a/b.git") == "github:a/b"
        assert repository_id_from_url("https://github.com/a/b.git") == "github:a/b"
        assert repository_id_from_url("https://gitlab.com/a/b") is None
        assert repository_id_from_url("") is None

    def test_repository_id_lowercases(self):
        assert repository_id("Owner", "Repo") == "github:owner/repo"

    def test_is_github_url(self):
        assert is_github_url("https://github.com/a/b")
        assert is_github_url("https://www.github.com/a/b")
        assert not is_github_url("https://gitlab.com/a/b")

    def test_normalize_github_url(self):
        assert normalize_github_url("https://github.com/a/b.git") == \
            "https://github.com/a/b"

    def test_extract_owner_name(self):
        assert extract_owner_name_from_id("github:a/b") == ("a", "b")
        with pytest.raises(ValueError):
            extract_owner_name_from_id("github:a/b/c")
        with pytest.raises(ValueError):
            extract_owner_name_from_id("gitlab:a/b")

    def test_to_canonical_url(self):
        assert to_canonical_url("github:a/b") == "https://github.com/a/b"


class TestNormalizeRepository:
    def test_normalize_sets_canonical_fields(self):
        repo = Repository(id="placeholder", owner="Foo", name="Bar",
                          url="https://github.com/Foo/Bar")
        result = normalize_repository(repo)
        assert result.id == "github:foo/bar"
        assert result.url == "https://github.com/foo/bar"
        assert result.owner == "foo"
        assert result.name == "bar"

    def test_normalize_repository_url(self):
        repo = _repo(url="git@github.com:o/r.git")
        assert normalize_repository_url(repo) == "github:o/r"


class TestCreateRepository:
    def test_from_api_maps_fields(self):
        data = {
            "name": "Repo", "owner": {"login": "Owner"},
            "html_url": "https://github.com/Owner/Repo",
            "description": "d", "stargazers_count": 10, "forks_count": 2,
            "open_issues_count": 3, "language": "Python",
            "topics": ["a"], "license": {"key": "mit"},
            "archived": True, "created_at": "c", "updated_at": "u",
            "pushed_at": "p",
        }
        repo = create_repository_from_api(data, "2026-01-01T00:00:00Z")
        assert repo.id == "github:owner/repo"
        assert repo.stars == 10
        assert repo.forks == 2
        assert repo.issues == 3
        assert repo.license == "mit"
        assert repo.archived is True
        assert repo.collected_at == "2026-01-01T00:00:00Z"

    def test_from_url(self):
        repo = create_repository_from_url("https://github.com/a/b", "t")
        assert repo is not None
        assert repo.id == "github:a/b"
        assert create_repository_from_url("https://gitlab.com/a/b", "t") is None

    def test_from_row_maps_score_health(self):
        repo = repository_from_row({
            "id": "github:a/b", "owner": "a", "name": "b",
            "url": "https://github.com/a/b",
            "score_overall": 77.0, "health_status": "SLOW",
        })
        assert repo.score == {"overall": 77.0}
        assert repo.health == {"status": "SLOW"}


class TestMergeSources:
    def test_adds_new_sources_only(self):
        repo = _repo(sources=[{"repository": "github:x/y", "section": "A"}])
        merge_sources(repo, [
            {"repository": "github:x/y", "section": "A"},   # dup
            {"repository": "github:x/z", "section": "B"},   # new
        ])
        assert len(repo.sources) == 2


class TestDedupe:
    def test_dedupes_by_id(self):
        repos = [_repo("github:a/b"), _repo("github:a/b"), _repo("github:a/c")]
        unique, dups = dedupe_repositories(repos)
        assert len(unique) == 2
        assert len(dups) == 1
        assert isinstance(dups[0], DuplicateMatch)

    def test_dedupe_by_url_field(self):
        repos = [
            _repo("github:a/b", url="https://github.com/a/b"),
            _repo("github:a/b2", url="git@github.com:a/b.git"),
        ]
        unique, dups = dedupe_repositories(repos, match_fields=["url"])
        # both normalize to github:a/b → merged
        assert len(unique) == 1
        assert len(dups) == 1

    def test_dedupe_preserves_first_seen(self):
        first = _repo("github:a/b", description="first")
        second = _repo("github:a/b", description="second")
        unique, _ = dedupe_repositories([first, second])
        assert unique[0].description == "first"
